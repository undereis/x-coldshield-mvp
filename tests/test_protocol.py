"""Local socket-pair checks for Modbus TCP framing and FC06 contracts."""

import socket
import struct
import threading
import unittest

from coldshield.protocol import (
    Frame,
    ProtocolError,
    decode_write,
    exception_response,
    read_frame,
    read_request,
    validate_response,
    write_frame,
)


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.reader, self.writer = socket.socketpair()
        self.addCleanup(self.reader.close)
        self.addCleanup(self.writer.close)

    def test_write_round_trip_preserves_transaction_and_signed_value(self):
        for register, value in ((0, -22), (1, -32768), (2, 32767), (10, 1)):
            with self.subTest(register=register, value=value):
                source = write_frame(register, value, transaction_id=1234)
                self.writer.sendall(source.encode())
                parsed = read_frame(self.reader, timeout=0.5)
                self.assertEqual(parsed.transaction_id, 1234)
                self.assertEqual(parsed.unit_id, 1)
                self.assertEqual(parsed.function, 6)
                self.assertEqual(decode_write(parsed), (register, value))

    def test_fragmented_header_and_pdu_are_reassembled(self):
        packet = write_frame(2, -18, transaction_id=7).encode()
        errors = []

        def send_fragments():
            try:
                # Socket reads are permitted to return fewer bytes than requested.
                for byte in packet:
                    self.writer.sendall(bytes([byte]))
                self.writer.shutdown(socket.SHUT_WR)
            except OSError as exc:
                errors.append(exc)

        sender = threading.Thread(target=send_fragments)
        sender.start()
        parsed = read_frame(self.reader, timeout=1)
        sender.join(timeout=1)
        self.assertFalse(sender.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(decode_write(parsed), (2, -18))
        self.assertIsNone(read_frame(self.reader, timeout=0.5))

    def test_grouped_frames_remain_independent(self):
        first = write_frame(0, -22, transaction_id=8)
        second = write_frame(0, 50, transaction_id=9)
        self.writer.sendall(first.encode() + second.encode())
        parsed_first = read_frame(self.reader, timeout=0.5)
        parsed_second = read_frame(self.reader, timeout=0.5)
        self.assertEqual(parsed_first.transaction_id, 8)
        self.assertEqual(decode_write(parsed_first), (0, -22))
        self.assertEqual(parsed_second.transaction_id, 9)
        self.assertEqual(decode_write(parsed_second), (0, 50))

    def test_short_reads_are_handled_deterministically(self):
        class ShortReadSocket:
            def __init__(self, sock):
                self.sock = sock
                self.reads = 0

            def settimeout(self, value):
                self.sock.settimeout(value)

            def recv(self, size):
                self.reads += 1
                return self.sock.recv(min(size, 1))

        self.writer.sendall(write_frame(0, -22).encode())
        fragmented = ShortReadSocket(self.reader)
        self.assertEqual(decode_write(read_frame(fragmented, timeout=0.5)), (0, -22))
        self.assertEqual(fragmented.reads, 12)

    def test_clean_eof_returns_none(self):
        self.writer.shutdown(socket.SHUT_WR)
        self.assertIsNone(read_frame(self.reader, timeout=0.5))

    def test_partial_header_eof_is_error(self):
        self.writer.sendall(b"\x00\x01\x00")
        self.writer.shutdown(socket.SHUT_WR)
        with self.assertRaises(ProtocolError):
            read_frame(self.reader, timeout=0.5)

    def test_partial_pdu_eof_is_error(self):
        self.writer.sendall(write_frame(0, -22).encode()[:-1])
        self.writer.shutdown(socket.SHUT_WR)
        with self.assertRaises(ProtocolError):
            read_frame(self.reader, timeout=0.5)

    def test_idle_connection_timeout_is_protocol_error(self):
        with self.assertRaises(ProtocolError):
            read_frame(self.reader, timeout=0.03)

    def test_partial_frame_timeout_is_protocol_error(self):
        self.writer.sendall(write_frame(0, -22).encode()[:8])
        with self.assertRaises(ProtocolError):
            read_frame(self.reader, timeout=0.03)

    def test_nonzero_protocol_identifier_is_rejected(self):
        packet = bytearray(write_frame(0, -22).encode())
        packet[2:4] = struct.pack(">H", 1)
        self.writer.sendall(packet)
        with self.assertRaises(ProtocolError):
            read_frame(self.reader, timeout=0.5)

    def test_invalid_mbap_lengths_are_rejected(self):
        for length in (0, 1, 255, 65535):
            with self.subTest(length=length):
                reader, writer = socket.socketpair()
                try:
                    writer.sendall(struct.pack(">HHHB", 1, 0, length, 1))
                    writer.shutdown(socket.SHUT_WR)
                    with self.assertRaises(ProtocolError):
                        read_frame(reader, timeout=0.5)
                finally:
                    reader.close()
                    writer.close()

    def test_decode_write_requires_fc06_and_exact_pdu(self):
        for pdu in (b"", b"\x03\x00\x00\x00\x01", b"\x06", b"\x06\x00\x00\x00", b"\x06\x00\x00\x00\x01\x00"):
            with self.subTest(pdu=pdu), self.assertRaises(ProtocolError):
                decode_write(Frame(1, 1, pdu))

    def test_read_request_has_fc03_wire_contract(self):
        frame = read_request(10, 3, transaction_id=19)
        self.assertEqual(frame.transaction_id, 19)
        self.assertEqual(frame.pdu, struct.pack(">BHH", 3, 10, 3))
        self.assertEqual(frame.encode()[:7], struct.pack(">HHHB", 19, 0, 6, 1))

    def test_exception_response_preserves_correlation(self):
        frame = write_frame(0, 50, transaction_id=21)
        response = exception_response(frame, 3)
        self.assertEqual(response.transaction_id, 21)
        self.assertEqual(response.unit_id, frame.unit_id)
        self.assertEqual(response.pdu, b"\x86\x03")

    def test_upstream_response_requires_matching_transaction_and_unit(self):
        request = write_frame(0, -22, transaction_id=100)
        for response in (Frame(101, 1, request.pdu), Frame(100, 2, request.pdu), None):
            with self.subTest(response=response), self.assertRaises(ProtocolError):
                validate_response(request, response)

    def test_upstream_response_requires_exact_write_echo(self):
        request = write_frame(0, -22)
        for response in (write_frame(0, -21), write_frame(1, -22), Frame(1, 1, b"\x03\x02\x00\x00")):
            with self.subTest(response=response), self.assertRaises(ProtocolError):
                validate_response(request, response)
        self.assertEqual(validate_response(request, request), request)

    def test_upstream_exception_is_preserved_and_validated(self):
        request = write_frame(0, -22)
        response = exception_response(request, 3)
        self.assertEqual(validate_response(request, response), response)
        for pdu in (b"\x86", b"\x86\x00", b"\x86\x03\x00"):
            with self.subTest(pdu=pdu), self.assertRaises(ProtocolError):
                validate_response(request, Frame(1, 1, pdu))

    def test_read_response_matches_requested_quantity(self):
        request = read_request(0, 2)
        valid = Frame(1, 1, b"\x03\x04\xff\xec\xff\xee")
        self.assertEqual(validate_response(request, valid), valid)
        for pdu in (b"\x03\x02\xff\xec", b"\x03\x02\xff\xec\xff\xee", b"\x03\x04\xff\xec"):
            with self.subTest(pdu=pdu), self.assertRaises(ProtocolError):
                validate_response(request, Frame(1, 1, pdu))


if __name__ == "__main__":
    unittest.main()
