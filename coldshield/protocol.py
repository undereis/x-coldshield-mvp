"""Bounded Modbus TCP framing; simulator-specific signed register semantics."""
from dataclasses import dataclass
import socket
import struct
import time

THERMAL_REGISTERS = frozenset((0, 1, 2))
DEFROST_REGISTERS = frozenset((10, 11, 12))
REGISTERS = THERMAL_REGISTERS | DEFROST_REGISTERS


class ProtocolError(ValueError):
    pass


@dataclass(frozen=True)
class Frame:
    transaction_id: int
    unit_id: int
    pdu: bytes

    @property
    def function(self):
        if not self.pdu:
            raise ProtocolError("Empty PDU")
        return self.pdu[0]

    def encode(self):
        if not 1 <= len(self.pdu) <= 253:
            raise ProtocolError("PDU must contain 1..253 bytes")
        return struct.pack(">HHHB", self.transaction_id, 0, len(self.pdu) + 1, self.unit_id) + self.pdu


def read_frame(sock, timeout=3.0):
    """Read exactly one ADU without consuming the next; one deadline per ADU."""
    deadline = time.monotonic() + timeout

    def exact(size, clean_eof=False):
        buf = bytearray()
        while len(buf) < size:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ProtocolError("Frame deadline exceeded")
            sock.settimeout(remaining)
            try:
                part = sock.recv(size - len(buf))
            except socket.timeout as exc:
                raise ProtocolError("Frame deadline exceeded") from exc
            if not part:
                if clean_eof and not buf:
                    return None
                raise ProtocolError("Incomplete frame at EOF")
            buf.extend(part)
        return bytes(buf)

    header = exact(7, clean_eof=True)
    if header is None:
        return None
    transaction, protocol, length, unit = struct.unpack(">HHHB", header)
    if protocol != 0 or not 2 <= length <= 254:
        raise ProtocolError("Invalid MBAP protocol or length")
    return Frame(transaction, unit, exact(length - 1))


def decode_write(frame):
    if frame.function != 6 or len(frame.pdu) != 5:
        raise ProtocolError("FC06 requires exactly 5 PDU bytes")
    return struct.unpack(">Hh", frame.pdu[1:])


def decode_read(frame):
    if frame.function != 3 or len(frame.pdu) != 5:
        raise ProtocolError("FC03 requires exactly 5 PDU bytes")
    address, quantity = struct.unpack(">HH", frame.pdu[1:])
    if not 1 <= quantity <= 125 or address + quantity > 65536:
        raise ProtocolError("Invalid read range")
    return address, quantity


def write_frame(register, value, transaction_id=1):
    return Frame(transaction_id, 1, struct.pack(">BHh", 6, register, value))


def read_request(register, quantity, transaction_id=1):
    return Frame(transaction_id, 1, struct.pack(">BHH", 3, register, quantity))


def exception_response(frame, code):
    return Frame(frame.transaction_id, frame.unit_id, bytes((frame.function | 0x80, code)))


def validate_response(request, response):
    if response is None:
        raise ProtocolError("Upstream closed without response")
    if (response.transaction_id, response.unit_id) != (request.transaction_id, request.unit_id):
        raise ProtocolError("Response identity mismatch")
    if response.function == request.function | 0x80:
        if len(response.pdu) != 2 or response.pdu[1] not in (1, 2, 3, 4, 5, 6, 8, 10, 11):
            raise ProtocolError("Malformed exception response")
        return response
    if response.function != request.function:
        raise ProtocolError("Response function mismatch")
    if request.function == 6 and response.pdu != request.pdu:
        raise ProtocolError("Write echo mismatch")
    if request.function == 3:
        _, quantity = decode_read(request)
        if len(response.pdu) != 2 + quantity * 2 or response.pdu[1] != quantity * 2:
            raise ProtocolError("Read response length mismatch")
    return response


def exchange(port, request, timeout=3.0, before_send=None):
    """Always loopback. No retries: a failed reply may hide a completed write."""
    with socket.create_connection(("127.0.0.1", port), timeout=timeout) as sock:
        sock.settimeout(timeout)
        if before_send is not None:
            before_send()
        sock.sendall(request.encode())
        return validate_response(request, read_frame(sock, timeout))
