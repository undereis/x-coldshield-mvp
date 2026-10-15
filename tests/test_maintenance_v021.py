"""Administrative locking, uncertainty interlocks and date range regression."""
from datetime import datetime, timezone
import fcntl
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from coldshield.config import ConfigError, default_policy, load_policy, parse_time, uncertainty_path
from coldshield.maintenance import set_window
from coldshield.storage import AtomicPublicationError, atomic_json


class MaintenancePublicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'policy.json'
        atomic_json(self.path, default_policy())

    def test_postpublication_failure_keeps_marker_and_requires_close(self):
        with patch('coldshield.storage.fsync_directory', side_effect=OSError('policy fsync')):
            with self.assertRaises(AtomicPublicationError):
                set_window(self.path, 60)
        self.assertTrue(json.loads(self.path.read_text())['maintenance']['enabled'])
        self.assertTrue(uncertainty_path(self.path).exists())
        with self.assertRaises(ConfigError):
            load_policy(self.path)
        with self.assertRaises(ConfigError):
            set_window(self.path, 60)
        set_window(self.path)
        self.assertFalse(uncertainty_path(self.path).exists())
        self.assertFalse(load_policy(self.path).enabled)

    def test_marker_creation_fsync_fault_prevents_open_policy_publication(self):
        with patch('coldshield.maintenance.os.fsync', side_effect=OSError('marker fsync')):
            with self.assertRaises(OSError):
                set_window(self.path, 60)
        self.assertFalse(json.loads(self.path.read_text())['maintenance']['enabled'])
        self.assertTrue(uncertainty_path(self.path).exists())
        with self.assertRaises(ConfigError):
            load_policy(self.path)
        set_window(self.path)

    def test_marker_removal_durability_failure_restores_interlock(self):
        real = __import__('coldshield.maintenance', fromlist=['fsync_directory']).fsync_directory
        calls = 0
        def fail_removal(path):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError('marker removal fsync')
            return real(path)
        with patch('coldshield.maintenance.fsync_directory', side_effect=fail_removal):
            with self.assertRaises(OSError):
                set_window(self.path, 60)
        self.assertTrue(uncertainty_path(self.path).exists())
        with self.assertRaises(ConfigError):
            load_policy(self.path)
        set_window(self.path)

    def test_marker_recreation_open_failure_quarantines_policy_closed(self):
        from coldshield import maintenance
        real_mark = maintenance._mark_uncertain
        real_sync = maintenance.fsync_directory
        marker_calls = 0
        sync_calls = 0
        def fail_marker_recreation(marker):
            nonlocal marker_calls
            marker_calls += 1
            if marker_calls == 2:
                raise PermissionError("marker recreation open refused")
            return real_mark(marker)
        def fail_removal_sync(directory):
            nonlocal sync_calls
            sync_calls += 1
            if sync_calls == 2:
                raise OSError("marker removal directory fsync")
            return real_sync(directory)
        with patch('coldshield.maintenance._mark_uncertain', side_effect=fail_marker_recreation), \
                patch('coldshield.maintenance.fsync_directory', side_effect=fail_removal_sync):
            with self.assertRaisesRegex(OSError, "quarantined closed"):
                set_window(self.path, 60)
        self.assertFalse(load_policy(self.path).enabled)
        self.assertFalse(load_policy(self.path).maintenance_open())

    def test_failed_closed_replacement_removes_open_policy_public_name(self):
        from coldshield import maintenance
        real_atomic = maintenance.atomic_json
        real_mark = maintenance._mark_uncertain
        real_sync = maintenance.fsync_directory
        marker_calls = 0
        sync_calls = 0
        publication_calls = 0
        def fail_marker_recreation(marker):
            nonlocal marker_calls
            marker_calls += 1
            if marker_calls == 2:
                raise PermissionError("marker recreation refused")
            return real_mark(marker)
        def fail_removal_sync(directory):
            nonlocal sync_calls
            sync_calls += 1
            if sync_calls == 2:
                raise OSError("marker removal fsync")
            return real_sync(directory)
        def fail_closed_replacement(path, data):
            nonlocal publication_calls
            publication_calls += 1
            if publication_calls == 2:
                raise AtomicPublicationError("closed replacement refused", published=False)
            return real_atomic(path, data)
        with patch('coldshield.maintenance._mark_uncertain', side_effect=fail_marker_recreation), \
                patch('coldshield.maintenance.fsync_directory', side_effect=fail_removal_sync), \
                patch('coldshield.maintenance.atomic_json', side_effect=fail_closed_replacement):
            with self.assertRaisesRegex(OSError, "quarantined closed"):
                set_window(self.path, 60)
        self.assertFalse(self.path.exists())
        with self.assertRaises(ConfigError):
            load_policy(self.path)

    def test_total_recovery_write_failure_reports_remaining_visibility(self):
        from coldshield.maintenance import _quarantine_policy
        with patch('coldshield.maintenance.atomic_json', side_effect=OSError('replace refused')), \
                patch.object(Path, 'unlink', side_effect=OSError('unlink refused')), \
                patch('coldshield.maintenance.os.replace', side_effect=OSError('rename refused')):
            with self.assertRaisesRegex(OSError, "policy may remain visible"):
                _quarantine_policy(self.path, default_policy())

    def test_later_close_waits_for_entire_older_open_transaction(self):
        entered = threading.Event()
        release = threading.Event()
        errors = []
        real = __import__('coldshield.maintenance', fromlist=['read_policy_data']).read_policy_data
        def slow_read(path):
            data = real(path)
            if threading.current_thread().name == 'older-open':
                entered.set()
                if not release.wait(1):
                    raise AssertionError('test release timeout')
            return data
        def update(seconds):
            try:
                set_window(self.path, seconds)
            except BaseException as exc:
                errors.append(exc)
        with patch('coldshield.maintenance.read_policy_data', side_effect=slow_read):
            opening = threading.Thread(target=update, args=(60,), name='older-open')
            closing = threading.Thread(target=update, args=(None,), name='later-close')
            opening.start()
            self.assertTrue(entered.wait(1))
            closing.start()
            # The open writer has parsed while holding the exclusive lock.
            with self.assertRaises(ConfigError):
                load_policy(self.path)
            release.set()
            opening.join(2)
            closing.join(2)
        self.assertFalse(opening.is_alive())
        self.assertFalse(closing.is_alive())
        self.assertEqual(errors, [])
        self.assertFalse(load_policy(self.path).enabled)

    def test_administrative_lock_has_finite_timeout(self):
        with Path(str(self.path) + '.lock').open('a') as lease:
            fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
            start = time.monotonic()
            with self.assertRaises(ConfigError):
                set_window(self.path, 60, lock_timeout=.03)
            self.assertLess(time.monotonic() - start, .2)
        self.assertFalse(load_policy(self.path).enabled)

    def test_duplicate_keys_and_date_overflow_are_config_errors(self):
        self.path.write_text(json.dumps(default_policy()).replace('"version": 2', '"version": 2, "version": 2'))
        with self.assertRaises(ConfigError):
            set_window(self.path, 60)
        for stamp in ('0001-01-01T00:00:00+01:00', '9999-12-31T23:59:59-01:00'):
            with self.subTest(stamp=stamp), self.assertRaises(ConfigError):
                parse_time(stamp)
        atomic_json(self.path, default_policy())
        with patch('coldshield.maintenance.utcnow', return_value=datetime.max.replace(tzinfo=timezone.utc)):
            with self.assertRaises(ConfigError):
                set_window(self.path, 1)


if __name__ == '__main__':
    unittest.main()
