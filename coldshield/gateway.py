"""Explicit command authorization and audited simulator forwarding."""
import fcntl
import logging
from pathlib import Path
import socketserver
import threading
import time
import uuid

from .config import ConfigError, load_policy
from .protocol import (DEFROST_REGISTERS, REGISTERS, THERMAL_REGISTERS, ProtocolError,
                       decode_read, decode_write, exchange, exception_response,
                       read_frame, read_request)
from .server import LabServer
from .storage import AuditError, AuditStore

LOG = logging.getLogger(__name__)


class Gateway:
    def __init__(self, policy_path, audit, upstream_port=5020, timeout=3.0):
        self.policy_path = Path(policy_path)
        self.audit = audit
        self.upstream_port = upstream_port
        self.timeout = timeout
        # Serialize authorization, state checks, reservations and delivery across clients.
        self.lock = threading.Lock()

    def process(self, frame, peer="local"):
        request_id = str(uuid.uuid4())
        fields = {"peer": peer, "transaction_id": frame.transaction_id,
                  "unit_id": frame.unit_id, "function": frame.function}
        with self.lock:
            try:
                return self._process(frame, request_id, fields)
            except AuditError:
                LOG.exception("Audit unavailable; request refused or delivery outcome uncertain: %s", request_id)
                return exception_response(frame, 4)

    def _process(self, frame, request_id, fields):
        def deny(reason, code=3):
            self.audit.record(request_id, "decision", "BLOCKED", reason, **fields)
            return exception_response(frame, code)

        if frame.unit_id != 1:
            return deny("UNIT_NOT_ALLOWED", 2)
        if frame.function not in (3, 6):
            return deny("FUNCTION_NOT_ALLOWED", 1)
        try:
            if frame.function == 6:
                address, value = decode_write(frame)
                fields.update(register=address, value=value)
                if address not in REGISTERS:
                    return deny("REGISTER_NOT_ALLOWED", 2)
            else:
                address, quantity = decode_read(frame)
                fields.update(register=address, details={"quantity": quantity})
                if not set(range(address, address + quantity)) <= REGISTERS:
                    return deny("REGISTER_NOT_ALLOWED", 2)
        except ProtocolError:
            return deny("INVALID_PDU")
        try:
            policy = load_policy(self.policy_path)
        except ConfigError as exc:
            fields["details"] = {"error": str(exc)}
            return deny("INVALID_POLICY", 4)
        fields["policy_hash"] = policy.digest
        if frame.function == 6:
            if not policy.maintenance_open():
                return deny("MAINTENANCE_CLOSED")
            if address in THERMAL_REGISTERS and not policy.min_temp <= value <= policy.max_temp:
                return deny("THERMAL_LIMIT")
            if address in DEFROST_REGISTERS and value not in (0, 1):
                return deny("INVALID_DEFROST_VALUE")
        # Persist authorization intent before contacting upstream, including state reads.
        self.audit.record(request_id, "decision", "AUTHORIZED", "POLICY_ACCEPTED", **fields)
        def current_write_policy():
            try:
                latest = load_policy(self.policy_path)
                return latest.digest == policy.digest and latest.maintenance_open()
            except ConfigError:
                return False

        def changed_policy():
            self.audit.record(request_id, "outcome", "BLOCKED", "POLICY_CHANGED_OR_EXPIRED", **fields)
            return exception_response(frame, 3)

        if frame.function == 6 and not current_write_policy():
            return changed_policy()
        if frame.function == 6 and address in DEFROST_REGISTERS and value == 1:
            try:
                state = exchange(self.upstream_port, read_request(10, 3, frame.transaction_id), self.timeout)
                if state.function != 3:
                    raise ProtocolError("Defrost state unavailable")
                import struct
                active = struct.unpack(">3H", state.pdu[2:])
                if any(item not in (0, 1) for item in active):
                    raise ProtocolError("Untrusted defrost state")
                other_active = any(item for index, item in enumerate(active) if index + 10 != address)
                if other_active or (not active[address - 10] and self.audit.recent_start(time.time())):
                    self.audit.record(request_id, "outcome", "BLOCKED", "DEFROST_INTERLOCK", **fields)
                    return exception_response(frame, 3)
                if not active[address - 10]:
                    # Reserve durably BEFORE sending. Keep on ambiguous failures and restarts.
                    self.audit.reserve_start(address, time.time())
            except (OSError, ProtocolError) as exc:
                self.audit.record(request_id, "outcome", "FAILED", "DEFROST_STATE_UNAVAILABLE",
                                  **{**fields, "details": {"error": str(exc)}})
                return exception_response(frame, 11)
        # Recheck all writes after potentially blocking audit/state operations.
        if frame.function == 6 and not current_write_policy():
            return changed_policy()
        def check_before_send():
            if frame.function == 6 and not current_write_policy():
                raise ConfigError("Policy changed or expired while connecting")
        try:
            response = exchange(self.upstream_port, frame, self.timeout, before_send=check_before_send)
        except ConfigError:
            return changed_policy()
        except (OSError, ProtocolError) as exc:
            # An absent/invalid echo cannot prove whether the write reached the controller.
            self.audit.record(request_id, "outcome", "FAILED", "UPSTREAM_FAILURE",
                              **{**fields, "details": {"error": str(exc), "delivery": "unknown"}})
            return exception_response(frame, 11)
        if response.function & 0x80:
            decision, reason = "REJECTED", "UPSTREAM_EXCEPTION"
        else:
            decision, reason = "ACKNOWLEDGED", "VALIDATED_RESPONSE"
        self.audit.record(request_id, "outcome", decision, reason, **fields)
        return response


class GatewayHandler(socketserver.BaseRequestHandler):
    def handle(self):
        gateway = self.server.gateway
        while True:
            try:
                frame = read_frame(self.request, gateway.timeout)
                if frame is None:
                    return
                response = gateway.process(frame, self.client_address[0])
                self.request.settimeout(gateway.timeout)
                self.request.sendall(response.encode())
            except ProtocolError as exc:
                try:
                    gateway.audit.record(str(uuid.uuid4()), "decision", "BLOCKED", "INVALID_FRAME",
                                         peer=self.client_address[0], details={"error": str(exc)})
                except AuditError:
                    LOG.exception("Unable to audit malformed frame")
                return  # Untrusted header: close rather than invent transaction identity.
            except OSError:
                return


def make_gateway(port=5021, upstream_port=5020, policy_path="policy_config.json",
                 runtime_dir="runtime", timeout=3.0):
    runtime = Path(runtime_dir)
    runtime.mkdir(parents=True, exist_ok=True)
    lease = (runtime / "gateway.lock").open("a")
    try:
        fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        audit = AuditStore(runtime / "audit.sqlite3")
        server = LabServer(port, GatewayHandler)
    except BaseException:
        lease.close()
        raise
    server.gateway = Gateway(policy_path, audit, upstream_port, timeout)
    original_close = server.server_close

    def close():
        original_close()
        lease.close()
    server.server_close = close
    return server
