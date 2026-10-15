"""Independent regressions for lease revocation and durable interlock failures."""

from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from coldshield.config import default_policy
from coldshield.gateway import Gateway, make_gateway
from coldshield.protocol import Frame, write_frame
from coldshield.storage import AuditError, AuditStore, atomic_json, read_events


class GatewayReviewTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.policy_path = self.root / "policy.json"
        self.now = datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)
        policy = default_policy()
        policy["maintenance"] = {
            "enabled": True,
            "starts_at": (self.now - timedelta(seconds=60)).isoformat(),
            "expires_at": (self.now + timedelta(seconds=540)).isoformat(),
        }
        atomic_json(self.policy_path, policy)
        self.audit = AuditStore(self.root / "audit.sqlite3")
        self.gateway = Gateway(self.policy_path, self.audit)
        clock = patch("coldshield.config.utcnow", return_value=self.now)
        clock.start()
        self.addCleanup(clock.stop)

    def state_response(self, request, active=(0, 0, 0)):
        return Frame(request.transaction_id, 1, b"\x03\x06" + struct.pack(">3H", *active))

    def test_revoked_policy_during_audit_prevents_all_writes(self):
        for register, value in ((0, -22), (10, 0)):
            with self.subTest(register=register):
                policy = default_policy()
                policy["maintenance"] = {
                    "enabled": True,
                    "starts_at": self.now.isoformat(),
                    "expires_at": (self.now + timedelta(seconds=600)).isoformat(),
                }
                atomic_json(self.policy_path, policy)
                original_record = self.audit.record

                def revoke_after_intent(request_id, phase, decision, reason, **fields):
                    original_record(request_id, phase, decision, reason, **fields)
                    if phase == "decision" and decision == "AUTHORIZED":
                        atomic_json(self.policy_path, default_policy())

                request = write_frame(register, value)
                with patch.object(self.audit, "record", side_effect=revoke_after_intent), patch("coldshield.gateway.exchange", return_value=request) as upstream:
                    response = self.gateway.process(request)
                self.assertEqual(response.pdu, b"\x86\x03")
                upstream.assert_not_called()
                self.assertEqual(read_events(self.audit.path)[0]["reason"], "POLICY_CHANGED_OR_EXPIRED")

    def test_intent_audit_failure_prevents_upstream_delivery(self):
        with self.assertLogs("coldshield.gateway", level="ERROR"), patch.object(self.audit, "record", side_effect=AuditError("disk unavailable")), patch("coldshield.gateway.exchange") as upstream:
            response = self.gateway.process(write_frame(0, -22))
        self.assertEqual(response.pdu, b"\x86\x04")
        upstream.assert_not_called()

    def test_lease_expiry_during_audit_prevents_thermal_delivery(self):
        current_time = [self.now]
        original_record = self.audit.record

        def expire_after_intent(request_id, phase, decision, reason, **fields):
            original_record(request_id, phase, decision, reason, **fields)
            if phase == "decision" and decision == "AUTHORIZED":
                current_time[0] = self.now + timedelta(seconds=541)

        request = write_frame(0, -22)
        with patch("coldshield.config.utcnow", side_effect=lambda: current_time[0]), patch.object(self.audit, "record", side_effect=expire_after_intent), patch("coldshield.gateway.exchange", return_value=request) as upstream:
            response = self.gateway.process(request)
        self.assertEqual(response.pdu, b"\x86\x03")
        upstream.assert_not_called()

    def test_reservation_failure_prevents_defrost_write(self):
        request = write_frame(10, 1)
        state = self.state_response(request)
        with self.assertLogs("coldshield.gateway", level="ERROR"), patch.object(self.audit, "reserve_start", side_effect=AuditError("disk unavailable")), patch("coldshield.gateway.exchange", return_value=state) as upstream:
            response = self.gateway.process(request)
        self.assertEqual(response.pdu, b"\x86\x04")
        self.assertEqual(upstream.call_count, 1)
        self.assertEqual(upstream.call_args.args[1].function, 3)

    def test_ambiguous_delivery_reservation_survives_gateway_restart(self):
        request = write_frame(10, 1)
        with patch("coldshield.gateway.exchange", side_effect=[self.state_response(request), TimeoutError("reply lost")]):
            response = self.gateway.process(request)
        self.assertEqual(response.pdu, b"\x86\x0b")
        replacement = Gateway(self.policy_path, AuditStore(self.audit.path))
        second = write_frame(11, 1)
        with patch("coldshield.gateway.exchange", return_value=self.state_response(second)) as upstream:
            denied = replacement.process(second)
        self.assertEqual(denied.pdu, b"\x86\x03")
        self.assertEqual(upstream.call_count, 1)
        self.assertEqual(read_events(self.audit.path)[0]["reason"], "DEFROST_INTERLOCK")

    def test_active_defrost_blocks_other_aisle_after_cooldown_expires(self):
        self.audit.reserve_start(10, 1)
        request = write_frame(11, 1)
        with patch("coldshield.gateway.exchange", return_value=self.state_response(request, (1, 0, 0))) as upstream:
            response = self.gateway.process(request)
        self.assertEqual(response.pdu, b"\x86\x03")
        self.assertEqual(upstream.call_count, 1)

    def test_unknown_defrost_state_prevents_start(self):
        request = write_frame(10, 1)
        with patch("coldshield.gateway.exchange", return_value=self.state_response(request, (2, 0, 0))) as upstream:
            response = self.gateway.process(request)
        self.assertEqual(response.pdu, b"\x86\x0b")
        self.assertEqual(upstream.call_count, 1)
        self.assertEqual(read_events(self.audit.path)[0]["reason"], "DEFROST_STATE_UNAVAILABLE")

    def test_backward_wall_clock_does_not_clear_cooldown(self):
        self.audit.reserve_start(10, 1000)
        self.assertTrue(self.audit.recent_start(1001))
        self.assertTrue(self.audit.recent_start(500))
        self.assertFalse(self.audit.recent_start(1120))

    def test_second_gateway_cannot_share_runtime_lease(self):
        class NoNetworkServer:
            server_address = ("127.0.0.1", 12345)
            def server_close(self):
                pass

        runtime = self.root / "runtime"
        with patch("coldshield.gateway.LabServer", side_effect=lambda *args: NoNetworkServer()):
            first = make_gateway(port=0, runtime_dir=runtime, policy_path=self.policy_path)
            self.addCleanup(first.server_close)
            with self.assertRaises(OSError):
                make_gateway(port=0, runtime_dir=runtime, policy_path=self.policy_path)

    def test_decision_and_ambiguous_outcome_remain_correlated(self):
        with patch("coldshield.gateway.exchange", side_effect=TimeoutError("reply lost")):
            self.gateway.process(write_frame(0, -22, transaction_id=45))
        events = list(reversed(read_events(self.audit.path)))
        self.assertEqual([event["phase"] for event in events], ["decision", "outcome"])
        self.assertEqual([event["decision"] for event in events], ["AUTHORIZED", "FAILED"])
        self.assertEqual(len({event["request_id"] for event in events}), 1)
        self.assertTrue(all(event["transaction_id"] == 45 for event in events))
        self.assertEqual(json.loads(events[1]["details"])["delivery"], "unknown")

    def test_concurrent_audit_writes_preserve_every_event(self):
        def record(index):
            self.audit.record(str(index), "decision", "BLOCKED", "CONCURRENT_REVIEW")

        with ThreadPoolExecutor(max_workers=4) as executor:
            list(executor.map(record, range(40)))
        events = read_events(self.audit.path)
        self.assertEqual(len(events), 40)
        self.assertEqual({event["request_id"] for event in events}, {str(index) for index in range(40)})
        self.assertEqual(len({event["id"] for event in events}), 40)


if __name__ == "__main__":
    unittest.main()
