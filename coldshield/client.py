"""Small loopback laboratory client with explicit, validated command outcomes."""
from dataclasses import dataclass
from typing import Literal

from .protocol import ProtocolError, exchange, validate_response, write_frame


@dataclass(frozen=True)
class CommandResult:
    status: Literal["ACKNOWLEDGED", "DENIED", "UNAVAILABLE"]
    message: str
    exception_code: int | None = None


def send_write(port, register, value):
    """No retries: losing a reply does not establish whether a write occurred."""
    try:
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError("Port must be an integer in 1..65535")
        if type(register) is not int or not 0 <= register <= 65535:
            raise ValueError("Register must be an unsigned 16-bit integer")
        if type(value) is not int or not -32768 <= value <= 32767:
            raise ValueError("Value must be a signed 16-bit integer")
        request = write_frame(register, value)
        response = validate_response(request, exchange(port, request, timeout=1.5))
    except (OSError, ProtocolError, ValueError, OverflowError) as exc:
        return CommandResult("UNAVAILABLE", f"No verified acknowledgement: {exc}. Outcome unknown; inspect telemetry and audit before retrying.")
    if response.function == 0x86:
        code = response.pdu[1]
        if code in (1, 2, 3):
            return CommandResult("DENIED", f"Request denied with Modbus exception {code}. Consult the audit for the decision reason.", code)
        return CommandResult("UNAVAILABLE", f"Device or gateway error (Modbus exception {code}); this is not evidence of a protective block.", code)
    return CommandResult("ACKNOWLEDGED", "Matching FC06 write acknowledgement received.")
