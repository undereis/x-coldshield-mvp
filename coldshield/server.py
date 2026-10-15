"""Bounded TCP workers for the loopback-only laboratory."""
from dataclasses import dataclass
import socket
import socketserver
import threading
import time

from .limits import (MAX_CLIENTS, MAX_SESSION_REQUESTS, REQUEST_BUDGET,
                     SESSION_MAX_SECONDS, validate_port, validate_positive_int,
                     validate_positive_number)


@dataclass
class Session:
    started_at: float
    ends_at: float
    requests: int = 0


class LabServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    # Retain the runtime lease until all bounded handlers finish on shutdown.
    daemon_threads = False
    block_on_close = True

    def __init__(self, port, handler, *, max_clients=MAX_CLIENTS,
                 session_seconds=SESSION_MAX_SECONDS,
                 max_requests=MAX_SESSION_REQUESTS):
        validate_port(port, allow_ephemeral=True)
        self.max_clients = validate_positive_int(max_clients, "max_clients")
        self.session_seconds = validate_positive_number(session_seconds, "session_seconds")
        self.max_requests = validate_positive_int(max_requests, "max_requests")
        self.slots = threading.BoundedSemaphore(max_clients)
        self.stopping = threading.Event()
        self.session_lock = threading.Lock()
        self.active_sessions = {}
        self._close_lock = threading.Lock()
        self._closed = False
        super().__init__(("127.0.0.1", port), handler)

    def process_request(self, request, client_address):
        # Admission happens before a worker exists. Overflow receives EOF/reset.
        with self.session_lock:
            admitted = not self.stopping.is_set() and self.slots.acquire(blocking=False)
            if admitted:
                now = time.monotonic()
                self.active_sessions[request] = Session(now, now + self.session_seconds)
                # Stop/close cannot race between admission and worker registration.
                try:
                    super().process_request(request, client_address)
                except BaseException:
                    self.active_sessions.pop(request, None)
                    self.slots.release()
                    raise
        if not admitted:
            self.shutdown_request(request)

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            with self.session_lock:
                self.active_sessions.pop(request, None)
            self.slots.release()

    def next_request_deadline(self, sock):
        """Reserve one frame attempt, including an idle or malformed attempt."""
        with self.session_lock:
            session = self.active_sessions.get(sock)
            now = time.monotonic()
            if (self.stopping.is_set() or session is None or now >= session.ends_at
                    or session.requests >= self.max_requests):
                return None
            session.requests += 1
            return min(session.ends_at, now + REQUEST_BUDGET)

    def request_stop(self):
        """Interrupt client I/O; workers retain their slots until they finish."""
        with self.session_lock:
            self.stopping.set()
            clients = tuple(self.active_sessions)
        for client in clients:
            try:
                client.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    def shutdown(self):
        self.request_stop()
        super().shutdown()

    def server_close(self):
        self.request_stop()
        with self._close_lock:
            if self._closed:
                return
            super().server_close()  # ThreadingMixIn joins the non-daemon workers.
            self._closed = True
