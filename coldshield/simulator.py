"""Synthetic register store. No vendor emulation or refrigeration process model."""
import logging
from pathlib import Path
import socketserver
import struct
import threading
import time
from .config import utcnow
from .limits import validate_positive_number
from .protocol import (REGISTERS, DEFROST_REGISTERS, Frame, ProtocolError, decode_read,
                       decode_write, exception_response, read_frame)
from .server import LabServer
from .storage import AtomicPublicationError, atomic_json


class Simulator:
    def __init__(self, state_path):
        self.registers = {0: -20, 1: -20, 2: -18, 10: 0, 11: 0, 12: 0}
        self.state_path = Path(state_path)
        self.lock = threading.Lock()
        self.storage_degraded = False

    def snapshot(self):
        try:
            atomic_json(self.state_path, {
                "schema_version": 2, "last_update": utcnow().isoformat(),
                "source": "synthetic_registers",
                "previous_snapshot_degraded": self.storage_degraded,
                "durability_state": "requires_fsync_confirmation",
                "freezers": {
                    f"Aisle {i + 1}": {"setpoint_c": self.registers[i],
                                        "defrost": bool(self.registers[i + 10])} for i in range(3)}})
        except OSError:
            self.storage_degraded = True
            raise
        self.storage_degraded = False

    def process(self, frame):
        if frame.unit_id != 1:
            return exception_response(frame, 2)
        with self.lock:
            try:
                if frame.function == 6:
                    address, value = decode_write(frame)
                    if address not in REGISTERS:
                        return exception_response(frame, 2)
                    if address in DEFROST_REGISTERS and value not in (0, 1):
                        return exception_response(frame, 3)
                    if self.storage_degraded:
                        return exception_response(frame, 4)
                    old = self.registers[address]
                    self.registers[address] = value
                    try:
                        self.snapshot()
                    except OSError as exc:
                        if not isinstance(exc, AtomicPublicationError) or not exc.published:
                            self.registers[address] = old
                        self.storage_degraded = True
                        return exception_response(frame, 4)
                    return frame  # Deliberately allows unsafe setpoints on direct lab port.
                if frame.function == 3:
                    address, quantity = decode_read(frame)
                    if not set(range(address, address + quantity)) <= REGISTERS:
                        return exception_response(frame, 2)
                    values = [self.registers[i] & 0xffff for i in range(address, address + quantity)]
                    return Frame(frame.transaction_id, 1, bytes((3, quantity * 2)) +
                                 struct.pack(f">{quantity}H", *values))
                return exception_response(frame, 1)
            except ProtocolError:
                return exception_response(frame, 3)


class SimulatorHandler(socketserver.BaseRequestHandler):
    def handle(self):
        stopping = getattr(self.server, "stopping", threading.Event())
        while not stopping.is_set():
            try:
                get_deadline = getattr(self.server, "next_request_deadline", None)
                deadline = get_deadline(self.request) if get_deadline else None
                if get_deadline and deadline is None:
                    return
                timeout = self.server.timeout_seconds
                if deadline is not None:
                    timeout = min(timeout, deadline - time.monotonic())
                    if timeout <= 0:
                        return
                frame = read_frame(self.request, timeout, deadline=deadline)
                if frame is None:
                    return
                response = self.server.simulator.process(frame)
                send_timeout = self.server.timeout_seconds
                if deadline is not None:
                    send_timeout = min(send_timeout, deadline - time.monotonic())
                    if send_timeout <= 0:
                        return
                self.request.settimeout(send_timeout)
                self.request.sendall(response.encode())
            except (OSError, ProtocolError):
                return


def make_simulator(port=5020, runtime_dir="runtime", timeout=3.0):
    timeout = validate_positive_number(timeout, "timeout")
    server = LabServer(port, SimulatorHandler)
    server.timeout_seconds = timeout
    server.simulator = Simulator(Path(runtime_dir) / "simulator_state.json")
    try:
        server.simulator.snapshot()
    except BaseException:
        server.server_close()
        raise
    stop = threading.Event()

    def heartbeat():
        while not stop.wait(2):
            with server.simulator.lock:
                try:
                    server.simulator.snapshot()
                except OSError:
                    logging.exception("Simulator snapshot unavailable")
    thread = threading.Thread(target=heartbeat, daemon=True)
    thread.start()
    original_close = server.server_close

    def close():
        stop.set()
        thread.join()
        original_close()
    server.server_close = close
    return server
