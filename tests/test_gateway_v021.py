"""Regression evidence for startup, bounded queueing and audit-before-delivery."""
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from coldshield.config import ConfigError, default_policy
from coldshield.gateway import Gateway, make_gateway
from coldshield.limits import CLIENT_TIMEOUT, REQUEST_BUDGET, UPSTREAM_TIMEOUT
from coldshield.maintenance import set_window
from coldshield.protocol import write_frame
from coldshield.storage import AuditStore, atomic_json, read_events


class Gateway021Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.policy = self.root / 'policy.json'
        atomic_json(self.policy, default_policy())
        set_window(self.policy, 300)
        self.audit = AuditStore(self.root / 'audit.sqlite3')
        self.gateway = Gateway(self.policy, self.audit)

    def test_client_outlasts_complete_request_budget(self):
        self.assertGreater(CLIENT_TIMEOUT, REQUEST_BUDGET)
        self.assertLess(UPSTREAM_TIMEOUT * 2, REQUEST_BUDGET)

    def test_self_upstream_rejected_before_runtime_creation(self):
        runtime = self.root / 'never-created'
        with self.assertRaisesRegex(ValueError, 'own port'):
            make_gateway(5021, 5021, self.policy, runtime)
        self.assertFalse(runtime.exists())

    def test_bound_ephemeral_self_upstream_closes_server(self):
        class BoundServer:
            server_address = ('127.0.0.1', 5020)
            closed = False
            def server_close(self):
                self.closed = True
        server = BoundServer()
        with patch('coldshield.gateway.LabServer', return_value=server):
            with self.assertRaisesRegex(ValueError, 'own bound port'):
                make_gateway(0, 5020, self.policy, self.root / 'runtime')
        self.assertTrue(server.closed)

    def test_invalid_startup_policy_never_creates_listener(self):
        self.policy.write_text('{}')
        with patch('coldshield.gateway.LabServer') as listener:
            with self.assertRaises(ConfigError):
                make_gateway(0, 5020, self.policy, self.root / 'runtime')
        listener.assert_not_called()

    def test_invalid_topology_and_timeout_rejected_at_startup(self):
        for port, upstream, timeout in ((-1, 5020, 1), (65536, 5020, 1),
                                         (0, 0, 1), (0, 65536, 1), (0, 5020, 0)):
            with self.subTest(values=(port, upstream, timeout)), self.assertRaises(ValueError):
                make_gateway(port, upstream, self.policy, self.root / 'runtime', timeout)

    def test_contended_gateway_lock_has_finite_wait_and_never_forwards(self):
        self.gateway.lock.acquire()
        self.addCleanup(self.gateway.lock.release)
        started = time.monotonic()
        with patch('coldshield.gateway.exchange') as upstream:
            response = self.gateway.process(write_frame(0, -22), deadline=started + .35)
        self.assertEqual(response.pdu, b'\x86\x06')
        self.assertLess(time.monotonic() - started, .6)
        upstream.assert_not_called()
        self.assertEqual(read_events(self.audit.path)[0]['reason'], 'REQUEST_BUDGET_EXCEEDED')

    def test_shutdown_flag_refuses_before_authorization(self):
        with patch('coldshield.gateway.exchange') as upstream:
            response = self.gateway.process(write_frame(0, -22), cancelled=lambda: True)
        upstream.assert_not_called()
        self.assertEqual(response.pdu, b'\x86\x06')

    def test_storage_capacity_reserved_before_upstream_contact(self):
        audit = AuditStore(self.root / 'small.sqlite3', max_events=2)
        audit.record('old', 'outcome', 'ACKNOWLEDGED', 'VALIDATED_RESPONSE')
        gateway = Gateway(self.policy, audit)
        with self.assertLogs('coldshield.gateway', level='ERROR'), patch('coldshield.gateway.exchange') as upstream:
            response = gateway.process(write_frame(0, -22))
        upstream.assert_not_called()
        self.assertEqual(response.pdu, b'\x86\x04')
        self.assertEqual(len(read_events(audit.path)), 1)

    def test_reserved_outcome_survives_competing_critical_event(self):
        audit = AuditStore(self.root / 'reserved.sqlite3', max_events=2)
        gateway = Gateway(self.policy, audit)
        request = write_frame(0, -22)
        def upstream(*args, **kwargs):
            from coldshield.storage import AuditError
            with self.assertRaises(AuditError):
                audit.record('competitor', 'outcome', 'FAILED', 'UPSTREAM_FAILURE')
            return request
        with patch('coldshield.gateway.exchange', side_effect=upstream):
            self.assertEqual(gateway.process(request), request)
        events = read_events(audit.path)
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]['decision'], 'ACKNOWLEDGED')

    def test_post_publication_device_error_records_unknown_delivery(self):
        import json
        from coldshield.simulator import Simulator
        simulator = Simulator(self.root / 'state.json')
        simulator.snapshot()
        def local_exchange(port, frame, *args, **kwargs):
            return simulator.process(frame)
        with patch('coldshield.gateway.exchange', side_effect=local_exchange), patch(
                'coldshield.storage.fsync_directory', side_effect=OSError('directory fsync failed')):
            response = self.gateway.process(write_frame(0, -22))
        self.assertEqual(response.pdu, b'\x86\x04')
        self.assertEqual(simulator.registers[0], -22)
        self.assertEqual(json.loads(simulator.state_path.read_text())['freezers']['Aisle 1']['setpoint_c'], -22)
        outcome = read_events(self.audit.path)[0]
        self.assertEqual(outcome['decision'], 'UNKNOWN')
        self.assertEqual(json.loads(outcome['details'])['delivery'], 'unknown')

    def test_budget_consumed_by_intent_prevents_delivery(self):
        original = self.audit.record
        def slow_intent(*args, **kwargs):
            original(*args, **kwargs)
            if args[2] == 'AUTHORIZED':
                time.sleep(.12)
        with patch.object(self.audit, 'record', side_effect=slow_intent), patch('coldshield.gateway.exchange') as upstream:
            response = self.gateway.process(write_frame(0, -22), deadline=time.monotonic() + .35)
        upstream.assert_not_called()
        self.assertEqual(response.pdu, b'\x86\x06')
        self.assertEqual(read_events(self.audit.path)[0]['reason'], 'REQUEST_BUDGET_EXCEEDED')


if __name__ == '__main__':
    unittest.main()
