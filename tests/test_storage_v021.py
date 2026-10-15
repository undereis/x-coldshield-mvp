"""Local fault injection for durable publication and shared audit budgets."""
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from coldshield.protocol import read_request, write_frame
from coldshield.simulator import Simulator
from coldshield.storage import (AtomicPublicationError, AuditError, AuditStore, atomic_json,
                                read_events)


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'state.json'
        atomic_json(self.path, {'old': 1})

    def test_prepublication_replace_failure_has_explicit_old_visibility(self):
        with patch('coldshield.storage.os.replace', side_effect=OSError('replace')):
            with self.assertRaises(AtomicPublicationError) as caught:
                atomic_json(self.path, {'new': 2})
        self.assertFalse(caught.exception.published)
        self.assertFalse(caught.exception.durability_uncertain)
        self.assertEqual(json.loads(self.path.read_text()), {'old': 1})
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    def test_postpublication_directory_fsync_failure_reports_visible_new_data(self):
        real_fsync = os.fsync
        calls = 0
        def fail_directory(fd):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError('directory fsync')
            return real_fsync(fd)
        with patch('coldshield.storage.os.fsync', side_effect=fail_directory):
            with self.assertRaises(AtomicPublicationError) as caught:
                atomic_json(self.path, {'new': 2})
        self.assertTrue(caught.exception.published)
        self.assertTrue(caught.exception.durability_uncertain)
        self.assertEqual(json.loads(self.path.read_text()), {'new': 2})

    def test_directory_open_and_close_failure_also_report_publication(self):
        real_open, real_close = os.open, os.close
        def fail_open(path, *args, **kwargs):
            if Path(path) == self.path.parent:
                raise OSError("directory open")
            return real_open(path, *args, **kwargs)
        def fail_close(fd):
            real_close(fd)
            raise OSError("directory close")
        for operation, fault in (("open", fail_open), ("close", fail_close)):
            with self.subTest(operation=operation), patch(f'coldshield.storage.os.{operation}', side_effect=fault):
                with self.assertRaises(AtomicPublicationError) as caught:
                    atomic_json(self.path, {'new': operation})
            self.assertTrue(caught.exception.published)

    def test_simulator_postpublication_retains_memory_and_reconciles(self):
        simulator = Simulator(self.path)
        simulator.snapshot()
        with patch('coldshield.storage.fsync_directory', side_effect=OSError('fsync')):
            reply = simulator.process(write_frame(0, -22))
        self.assertEqual(reply.pdu, b'\x86\x04')
        self.assertTrue(simulator.storage_degraded)
        self.assertEqual(simulator.registers[0], -22)
        self.assertEqual(json.loads(self.path.read_text())['freezers']['Aisle 1']['setpoint_c'], -22)
        self.assertEqual(simulator.process(write_frame(0, -24)).pdu, b'\x86\x04')
        self.assertEqual(simulator.process(read_request(0, 1)).function, 3)
        simulator.snapshot()
        self.assertFalse(simulator.storage_degraded)
        self.assertEqual(simulator.process(write_frame(0, -24)).function, 6)

    def test_simulator_prepublication_rolls_back_memory(self):
        simulator = Simulator(self.path)
        simulator.snapshot()
        with patch('coldshield.storage.os.replace', side_effect=OSError('replace')):
            self.assertEqual(simulator.process(write_frame(0, -22)).pdu, b'\x86\x04')
        self.assertEqual(simulator.registers[0], -20)
        self.assertTrue(simulator.storage_degraded)


class AuditBudgetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'audit.sqlite3'

    def record(self, audit, request='request', reason='THERMAL_LIMIT'):
        audit.record(request, 'decision', 'BLOCKED', reason, details={'value': -14})

    def test_hard_event_budget_preserves_original_records_on_reopen(self):
        audit = AuditStore(self.path, max_events=3)
        for index in range(3):
            self.record(audit, str(index))
        with self.assertRaises(AuditError):
            self.record(audit, 'four')
        reopened = AuditStore(self.path, max_events=3)
        with self.assertRaises(AuditError):
            self.record(reopened, 'five')
        self.assertEqual([row['request_id'] for row in read_events(self.path)], ['2', '1', '0'])

    def test_known_repeated_decision_denials_aggregate_at_shared_threshold(self):
        audit = AuditStore(self.path, max_events=2, denial_details_limit=2)
        self.record(audit, 'one', 'INVALID_FRAME')
        self.record(audit, 'two', 'FUNCTION_NOT_ALLOWED')
        for index in range(25):
            self.record(audit, str(index), 'INVALID_FRAME')
        data = audit.export(Path(self.temp.name) / 'export.json')
        self.assertEqual(len(data['events']), 2)
        summary = data['denial_summaries'][0]
        self.assertEqual(summary['reason'], 'INVALID_FRAME')
        self.assertEqual(summary['count'], 25)
        self.assertEqual(summary['first_request_id'], '0')
        self.assertEqual(summary['last_request_id'], '24')
        with self.assertRaises(AuditError):
            self.record(audit, 'thermal')
        with self.assertRaises(AuditError):
            audit.record('outcome', 'outcome', 'BLOCKED', 'INVALID_FRAME')

    def test_reserved_outcome_slots_cannot_be_consumed_by_other_requests(self):
        audit = AuditStore(self.path, max_events=3)
        audit.reserve_events('authorized')
        self.record(audit, 'other')
        with self.assertRaises(AuditError):
            self.record(audit, 'third')
        audit.record('authorized', 'decision', 'AUTHORIZED', 'POLICY_ACCEPTED')
        with self.assertRaises(AuditError):
            self.record(audit, 'fourth')
        audit.record('authorized', 'outcome', 'ACKNOWLEDGED', 'VALIDATED_RESPONSE')
        self.assertEqual(len(read_events(self.path)), 3)
        data = audit.export(Path(self.temp.name) / 'reserved.json')
        self.assertEqual(data['event_reservations'], [])

    def test_pending_reservations_survive_reopen_and_explicit_release(self):
        audit = AuditStore(self.path, max_events=2)
        audit.reserve_events('pending')
        reopened = AuditStore(self.path, max_events=2)
        with self.assertRaises(AuditError):
            self.record(reopened, 'unrelated')
        data = reopened.export(Path(self.temp.name) / 'pending.json')
        self.assertEqual(data['event_reservations'], [{'request_id': 'pending', 'remaining': 2}])
        reopened.release_events('pending')
        self.record(reopened, 'unrelated')

    def test_duplicate_reservation_and_oversized_samples_fail_explicitly(self):
        audit = AuditStore(self.path, max_record_bytes=1024, denial_details_limit=0)
        audit.reserve_events('pending')
        with self.assertRaises(AuditError):
            audit.reserve_events('pending')
        with self.assertRaises(AuditError):
            audit.record('big', 'decision', 'BLOCKED', 'INVALID_FRAME', details={'error': 'x' * 2000})
        self.assertEqual(audit.export(Path(self.temp.name) / 'empty.json')['denial_summaries'], [])

    def test_sqlite_byte_budget_and_lock_timeout_stop_writes(self):
        audit = AuditStore(self.path, max_bytes=65536, max_record_bytes=16000)
        index = 0
        with self.assertRaises(AuditError):
            while index < 100:
                audit.record(str(index), 'decision', 'BLOCKED', 'THERMAL_LIMIT', details={'error': 'x' * 12000})
                index += 1
        self.assertLessEqual(self.path.stat().st_size, 65536)
        db = sqlite3.connect(self.path)
        self.addCleanup(db.close)
        db.execute('BEGIN IMMEDIATE')
        start = time.monotonic()
        with self.assertRaises(AuditError):
            audit.reserve_events('busy')
        self.assertLess(time.monotonic() - start, .8)
        db.rollback()
        self.assertEqual(len(read_events(self.path)), index)

    def test_concurrent_store_reservations_share_the_same_budget(self):
        first = AuditStore(self.path, max_events=2)
        second = AuditStore(self.path, max_events=2)
        gate = threading.Barrier(3)
        results = []
        def reserve(store, request):
            gate.wait()
            try:
                store.reserve_events(request)
                results.append((request, "reserved"))
            except AuditError:
                results.append((request, "refused"))
        workers = [threading.Thread(target=reserve, args=(store, str(index)))
                   for index, store in enumerate((first, second))]
        for worker in workers:
            worker.start()
        gate.wait()
        for worker in workers:
            worker.join(1)
            self.assertFalse(worker.is_alive())
        self.assertEqual(sorted(result for _, result in results), ["refused", "reserved"])
        self.assertEqual(len(first.export(Path(self.temp.name) / 'concurrent.json')['event_reservations']), 1)

    def test_invalid_direct_field_values_raise_audit_error_before_sqlite(self):
        audit = AuditStore(self.path)
        with self.assertRaises(AuditError):
            audit.record('bad', 'decision', 'BLOCKED', 'TEST', register=2**64)
        with self.assertRaises(AuditError):
            audit.reserve_start(10, float('inf'))
        with self.assertRaises(AuditError):
            audit.reserve_start(999, 1)
        self.assertEqual(read_events(self.path), [])

    def mutate_db(self, statements):
        db = sqlite3.connect(self.path)
        try:
            for sql in statements:
                db.execute(sql)
            db.commit()
        finally:
            db.close()

    def test_missing_critical_table_is_not_silently_reconstructed(self):
        audit = AuditStore(self.path)
        audit.reserve_start(10, time.time())
        self.mutate_db(['DROP TABLE defrost_starts'])
        with self.assertRaisesRegex(AuditError, 'schema'):
            AuditStore(self.path)
        db = sqlite3.connect(self.path)
        try:
            self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name='defrost_starts'").fetchone())
        finally:
            db.close()

    def test_v02_migration_preserves_detailed_events_and_defrost_state(self):
        audit = AuditStore(self.path)
        audit.reserve_start(10, time.time())
        self.record(audit, 'baseline')
        self.mutate_db(['DROP TABLE event_reservations', 'DROP TABLE denial_summaries', 'PRAGMA user_version=0'])
        migrated = AuditStore(self.path)
        self.assertTrue(migrated.recent_start(time.time()))
        self.assertEqual(read_events(self.path)[0]['request_id'], 'baseline')
        migrated.reserve_events('new-request')
        self.assertEqual(migrated.export(Path(self.temp.name) / 'migration.json')['event_reservations'][0]['remaining'], 2)

    def test_partial_new_schema_and_empty_existing_database_fail_closed(self):
        AuditStore(self.path)
        self.mutate_db(['DROP TABLE denial_summaries'])
        with self.assertRaisesRegex(AuditError, 'schema'):
            AuditStore(self.path)
        self.path.unlink()
        self.path.touch()
        with self.assertRaisesRegex(AuditError, 'schema'):
            AuditStore(self.path)

    def test_invalid_persistent_defrost_value_is_refused_on_reopen(self):
        AuditStore(self.path)
        self.mutate_db(["INSERT INTO defrost_starts VALUES (999,1)"])
        with self.assertRaisesRegex(AuditError, 'defrost'):
            AuditStore(self.path)

    def test_exports_include_defrost_reservations_and_durable_json(self):
        audit = AuditStore(self.path)
        audit.reserve_start(10, 12345.0)
        self.record(audit)
        output = Path(self.temp.name) / 'export.json'
        data = audit.export(output)
        self.assertEqual(data, json.loads(output.read_text()))
        self.assertEqual(data['defrost_starts'], [{'register': 10, 'started': 12345.0}])
        with patch('coldshield.storage.fsync_directory', side_effect=OSError('directory')):
            with self.assertRaises(AtomicPublicationError):
                audit.export(output)


if __name__ == '__main__':
    unittest.main()
