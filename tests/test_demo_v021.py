"""Measure the real CLI demo's decisions, isolated artifacts and child shutdown."""
import hashlib
import json
from pathlib import Path
import socket
import tempfile
import unittest

from scripts.demo import claim_output, run_demo


class AutomatedLocalDemoTests(unittest.TestCase):
    def test_actual_demo_proves_decisions_state_and_clean_child_shutdown(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'demo'
            report = run_demo(output)
            self.assertTrue(report['successful'], report['errors'])
            expected = {
                'CLOSED: legitimate setpoint -22': ('DENIED', 'MAINTENANCE_CLOSED'),
                'OPEN: legitimate setpoint -22': ('ACKNOWLEDGED', 'VALIDATED_RESPONSE'),
                'OPEN: unsafe setpoint +50': ('DENIED', 'THERMAL_LIMIT'),
                'OPEN: defrost register 10 ON': ('ACKNOWLEDGED', 'VALIDATED_RESPONSE'),
                'OPEN: defrost register 11 ON': ('DENIED', 'DEFROST_INTERLOCK'),
                'OPEN: unsupported FC16': ('DENIED', 'FUNCTION_NOT_ALLOWED'),
                'OPEN: unsupported register 999': ('DENIED', 'REGISTER_NOT_ALLOWED'),
            }
            commands = {entry['command']: entry for entry in report['commands']}
            for name, (status, reason) in expected.items():
                entry = commands[name]
                self.assertEqual((entry['status'], entry['reason']), (status, reason))
                self.assertTrue(entry['request_id'])
                self.assertTrue(entry['audit_event_ids'])
            self.assertEqual(commands['OPEN: verify blocked temperature']['register_values'], [-22])
            self.assertEqual(commands['OPEN: verify defrost state']['register_values'], [1, 0, 0])
            self.assertFalse(json.loads((output / 'policy.json').read_text())['maintenance']['enabled'])
            self.assertEqual(len(report['processes']), 2)
            for child in report['processes']:
                self.assertEqual(child['host'], '127.0.0.1')
                self.assertTrue(child['stopped'])
                self.assertEqual(child['exit_code'], 0)
                self.assertFalse(child.get('forced_termination', False))
                with socket.socket() as probe:
                    self.assertNotEqual(probe.connect_ex(('127.0.0.1', child['port'])), 0)
            manifest = json.loads((output / 'manifest.json').read_text())
            for name, checksum in manifest['files'].items():
                self.assertEqual(checksum, hashlib.sha256((output / name).read_bytes()).hexdigest())
            self.assertIn('report.json', manifest['files'])
            self.assertIn('report.md', manifest['files'])
            self.assertIn('audit-export.json', manifest['files'])

    def test_existing_output_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)
            marker = path / 'marker'
            marker.write_text('keep')
            with self.assertRaises(ValueError):
                claim_output(path)
            self.assertEqual(marker.read_text(), 'keep')
