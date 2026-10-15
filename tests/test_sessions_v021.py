"""Loopback admission, persistent-session quotas and interruptible shutdown."""
from contextlib import contextmanager
from pathlib import Path
import socket
import socketserver
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from coldshield.config import default_policy
from coldshield.gateway import make_gateway
from coldshield.protocol import ProtocolError, read_frame, read_request, write_frame
from coldshield.server import LabServer
from coldshield.simulator import make_simulator
from coldshield.storage import atomic_json


class EchoHandler(socketserver.BaseRequestHandler):
    def handle(self):
        while True:
            deadline = self.server.next_request_deadline(self.request)
            if deadline is None:
                return
            try:
                frame = read_frame(self.request, deadline=deadline)
                if frame is None:
                    return
                self.request.settimeout(max(0.001, deadline - time.monotonic()))
                self.request.sendall(frame.encode())
            except (OSError, ProtocolError):
                return


@contextmanager
def serving(server):
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.005})
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)


class SessionTests(unittest.TestCase):
    @contextmanager
    def service(self, kind, **limits):
        if kind == "echo":
            with serving(LabServer(0, EchoHandler, **limits)) as server:
                yield server
            return
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            if kind == "simulator":
                with patch("coldshield.simulator.LabServer", side_effect=lambda p, h: LabServer(p, h, **limits)):
                    server = make_simulator(0, root / "sim")
                with serving(server):
                    yield server
            else:
                policy = root / "policy.json"
                atomic_json(policy, default_policy())
                with serving(make_simulator(0, root / "sim")) as upstream:
                    with patch("coldshield.gateway.LabServer", side_effect=lambda p, h: LabServer(p, h, **limits)):
                        server = make_gateway(0, upstream.server_address[1], policy, root / "gateway")
                    with serving(server):
                        yield server

    def connected(self, server):
        sock = socket.create_connection(server.server_address, timeout=0.5)
        sock.settimeout(0.5)
        self.addCleanup(sock.close)
        return sock

    def wait_sessions(self, server, count):
        deadline = time.monotonic() + 0.5
        while time.monotonic() < deadline:
            with server.session_lock:
                if len(server.active_sessions) == count:
                    return
            time.sleep(0.002)
        self.fail(f"Expected {count} active sessions")

    def assert_closed(self, sock):
        try:
            self.assertEqual(sock.recv(1), b"")
        except ConnectionResetError:
            pass  # Explicit admission overflow may reset rather than return EOF.

    def test_every_service_caps_workers_before_spawning_and_recovers_slot(self):
        for kind in ("echo", "simulator", "gateway"):
            with self.subTest(kind=kind), self.service(kind, max_clients=1) as server:
                first = self.connected(server)
                self.wait_sessions(server, 1)
                overflow = self.connected(server)
                self.assert_closed(overflow)
                self.wait_sessions(server, 1)
                first.close()
                self.wait_sessions(server, 0)
                replacement = self.connected(server)
                replacement.sendall(read_request(0, 1).encode())
                self.assertIsNotNone(read_frame(replacement, timeout=0.5))

    def test_grouped_complete_frames_are_limited_by_request_quota(self):
        for kind in ("echo", "simulator", "gateway"):
            with self.subTest(kind=kind), self.service(kind, max_requests=2) as server:
                sock = self.connected(server)
                sock.sendall(b"".join(read_request(0, 1, tid).encode() for tid in (1, 2, 3)))
                for tid in (1, 2):
                    self.assertEqual(read_frame(sock, timeout=0.5).transaction_id, tid)
                self.assert_closed(sock)
                self.wait_sessions(server, 0)

    def test_idle_session_is_closed_at_absolute_session_deadline(self):
        for kind in ("echo", "simulator", "gateway"):
            with self.subTest(kind=kind), self.service(kind, session_seconds=0.12) as server:
                start = time.monotonic()
                sock = self.connected(server)
                self.assert_closed(sock)
                self.assertLess(time.monotonic() - start, 0.3)

    def test_repeated_complete_frames_do_not_extend_session(self):
        with self.service("echo", session_seconds=0.12) as server:
            sock = self.connected(server)
            self.wait_sessions(server, 1)
            with server.session_lock:
                session = next(iter(server.active_sessions.values()))
                original_end = session.ends_at
            for tid in (1, 2):
                sock.sendall(write_frame(0, -22, tid).encode())
                self.assertEqual(read_frame(sock, timeout=0.5).transaction_id, tid)
                time.sleep(0.02)
            self.assertEqual(session.ends_at, original_end)
            self.assert_closed(sock)
            self.assertEqual(session.requests, 3)  # The final idle frame attempt counts.

    def test_shutdown_interrupts_idle_workers_within_point_three_seconds(self):
        for kind in ("echo", "simulator", "gateway"):
            with self.subTest(kind=kind), self.service(kind) as server:
                sock = self.connected(server)
                self.wait_sessions(server, 1)
                started = time.monotonic()
                server.shutdown()
                server.server_close()
                self.assertLess(time.monotonic() - started, 0.3)
                self.assertTrue(server.stopping.is_set())
                self.assert_closed(sock)
                self.wait_sessions(server, 0)
                server.request_stop()
                server.server_close()

    def test_stop_retains_active_worker_until_handler_returns(self):
        entered = threading.Event()
        release = threading.Event()

        class HeldHandler(socketserver.BaseRequestHandler):
            def handle(self):
                entered.set()
                release.wait(timeout=1)

        server = LabServer(0, HeldHandler, max_clients=1)
        with serving(server):
            self.connected(server)
            self.assertTrue(entered.wait(timeout=0.5))
            server.request_stop()
            self.wait_sessions(server, 1)
            self.assertFalse(server.slots.acquire(blocking=False))
            closing = threading.Thread(target=server.server_close)
            closing.start()
            try:
                time.sleep(0.02)
                self.assertTrue(closing.is_alive())
            finally:
                release.set()
                closing.join(timeout=0.5)
            self.assertFalse(closing.is_alive())
            self.wait_sessions(server, 0)

    def test_close_cannot_overtake_an_admitted_worker_registration(self):
        admitted = threading.Event()
        register = threading.Event()
        closing_started = threading.Event()
        closed = threading.Event()
        original = socketserver.ThreadingTCPServer.process_request

        def delayed_registration(server, request, peer):
            admitted.set()
            register.wait(timeout=1)
            original(server, request, peer)

        server = LabServer(0, EchoHandler)

        def close():
            closing_started.set()
            server.server_close()
            closed.set()

        with patch.object(socketserver.ThreadingTCPServer, "process_request", delayed_registration), serving(server):
            self.connected(server)
            self.assertTrue(admitted.wait(timeout=0.5))
            closer = threading.Thread(target=close)
            closer.start()
            try:
                self.assertTrue(closing_started.wait(timeout=0.5))
                self.assertFalse(closed.wait(timeout=0.02))
            finally:
                register.set()
                closer.join(timeout=0.5)
            self.assertFalse(closer.is_alive())
            self.assertTrue(closed.is_set())
            self.wait_sessions(server, 0)

    def test_constructor_rejects_nonpositive_or_wrong_type_limits(self):
        for name, values in (("max_clients", (0, -1, True, 1.5, "8")),
                             ("max_requests", (0, -1, False, 2.5, "64")),
                             ("session_seconds", (0, -1, True, "30", float("inf"), float("nan")))):
            for value in values:
                with self.subTest(name=name, value=value), self.assertRaises(ValueError):
                    LabServer(0, EchoHandler, **{name: value})
        for port in (True, -1, 65536, "5020"):
            with self.subTest(port=port), self.assertRaises(ValueError):
                LabServer(port, EchoHandler)
