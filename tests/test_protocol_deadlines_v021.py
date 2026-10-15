"""A single monotonic budget covers connection, authorization and framing."""
import unittest
from unittest.mock import patch

from coldshield.client import send_write
from coldshield.config import ConfigError
from coldshield.limits import CLIENT_TIMEOUT
from coldshield.protocol import ProtocolError, exchange, read_frame, write_frame


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


class TimedSocket:
    def __init__(self, clock, packet, *, read_seconds=0.0, send_seconds=0.0, fragment=100):
        self.clock = clock
        self.packet = packet
        self.read_seconds = read_seconds
        self.send_seconds = send_seconds
        self.fragment = fragment
        self.timeouts = []
        self.sent = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def settimeout(self, value):
        self.timeouts.append(value)

    def sendall(self, packet):
        self.sent.append(packet)
        self.clock.now += self.send_seconds

    def recv(self, size):
        self.clock.now += self.read_seconds
        size = min(size, self.fragment)
        part, self.packet = self.packet[:size], self.packet[size:]
        return part


class ProtocolDeadlineTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.request = write_frame(0, -22)
        self.enterContext(patch("coldshield.protocol.time.monotonic", self.clock))

    def test_expired_deadline_never_connects(self):
        with patch("coldshield.protocol.socket.create_connection") as connect:
            with self.assertRaises(ProtocolError):
                exchange(5020, self.request, deadline=99.0)
            connect.assert_not_called()

    def test_connect_consumes_budget_and_does_not_reset_read_timeout(self):
        sock = TimedSocket(self.clock, self.request.encode(), read_seconds=0.2, send_seconds=0.1)

        def connect(address, timeout):
            self.assertEqual(address, ("127.0.0.1", 5020))
            self.assertAlmostEqual(timeout, 1.0)
            self.clock.now += 0.6
            return sock

        with patch("coldshield.protocol.socket.create_connection", side_effect=connect):
            with self.assertRaises(ProtocolError):
                exchange(5020, self.request, timeout=1.0)
        self.assertEqual(sock.sent, [self.request.encode()])
        self.assertLessEqual(max(sock.timeouts), 0.400001)

    def test_expired_connection_cannot_authorize_or_send(self):
        sock = TimedSocket(self.clock, self.request.encode())

        def connect(*args, **kwargs):
            self.clock.now += 1.1
            return sock

        with patch("coldshield.protocol.socket.create_connection", side_effect=connect), patch("builtins.print") as callback:
            with self.assertRaises(ProtocolError):
                exchange(5020, self.request, before_send=callback)
            callback.assert_not_called()
        self.assertEqual(sock.sent, [])

    def test_authorization_expiration_prevents_send(self):
        sock = TimedSocket(self.clock, self.request.encode())

        def authorize():
            self.clock.now += 0.3

        with patch("coldshield.protocol.socket.create_connection", return_value=sock):
            with self.assertRaises(ProtocolError):
                exchange(5020, self.request, timeout=1, before_send=authorize, deadline=100.2)
        self.assertEqual(sock.sent, [])

    def test_authorization_error_propagates_without_sending(self):
        sock = TimedSocket(self.clock, b"")

        def revoked():
            raise ConfigError("revoked")

        with patch("coldshield.protocol.socket.create_connection", return_value=sock):
            with self.assertRaises(ConfigError):
                exchange(5020, self.request, before_send=revoked)
        self.assertEqual(sock.sent, [])

    def test_fragmented_frame_uses_one_budget_for_header_and_pdu(self):
        sock = TimedSocket(self.clock, self.request.encode(), read_seconds=0.11, fragment=1)
        with self.assertRaises(ProtocolError):
            read_frame(sock, timeout=1.0)
        self.assertLessEqual(self.clock.now, 101.11)
        self.assertTrue(all(a > b for a, b in zip(sock.timeouts, sock.timeouts[1:])))

    def test_absolute_deadline_caps_frame_even_with_longer_timeout(self):
        sock = TimedSocket(self.clock, self.request.encode(), read_seconds=0.15)
        with self.assertRaises(ProtocolError):
            read_frame(sock, timeout=5.0, deadline=100.2)
        self.assertAlmostEqual(sock.timeouts[0], 0.2)

    def test_invalid_limits_and_port_never_connect(self):
        with patch("coldshield.protocol.socket.create_connection") as connect:
            for value in (0, -1, True, "1", float("nan"), float("inf")):
                with self.subTest(timeout=value), self.assertRaises(ValueError):
                    exchange(5020, self.request, timeout=value)
            for port in (0, -1, True, "5020", 65536):
                with self.subTest(port=port), self.assertRaises(ValueError):
                    exchange(port, self.request)
            connect.assert_not_called()

    def test_client_has_full_request_budget_and_no_retry(self):
        with patch("coldshield.client.exchange", side_effect=TimeoutError("uncertain")) as call:
            self.assertEqual(send_write(5021, 0, -22).status, "UNAVAILABLE")
            call.assert_called_once()
            self.assertEqual(call.call_args.kwargs["timeout"], CLIENT_TIMEOUT)
