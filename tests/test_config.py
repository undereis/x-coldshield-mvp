"""Strict policy validation and explicit, bounded maintenance windows."""

import copy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest

from coldshield.config import ConfigError, default_policy, load_policy, validate_policy


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)

    def enabled_policy(self, duration=600):
        policy = default_policy()
        policy["maintenance"] = {
            "enabled": True,
            "starts_at": self.now.isoformat(),
            "expires_at": (self.now + timedelta(seconds=duration)).isoformat(),
        }
        return policy

    def test_default_schema_is_closed_and_conservative(self):
        data = default_policy()
        self.assertEqual(set(data), {"version", "min_temp", "max_temp", "maintenance"})
        self.assertEqual(data["version"], 2)
        self.assertEqual(data["min_temp"], -40)
        self.assertEqual(data["max_temp"], -15)
        self.assertEqual(data["maintenance"], {"enabled": False, "starts_at": None, "expires_at": None})
        policy = validate_policy(data)
        self.assertFalse(policy.maintenance_open(self.now))

    def test_default_policy_returns_independent_nested_dicts(self):
        data = default_policy()
        data["maintenance"]["enabled"] = True
        self.assertFalse(default_policy()["maintenance"]["enabled"])

    def test_active_window_has_start_inclusive_end_exclusive_bounds(self):
        policy = validate_policy(self.enabled_policy())
        self.assertFalse(policy.maintenance_open(self.now - timedelta(microseconds=1)))
        self.assertTrue(policy.maintenance_open(self.now))
        self.assertTrue(policy.maintenance_open(self.now + timedelta(seconds=599)))
        self.assertFalse(policy.maintenance_open(self.now + timedelta(seconds=600)))

    def test_offset_timestamps_are_compared_as_instants(self):
        data = self.enabled_policy()
        data["maintenance"]["starts_at"] = "2026-10-14T14:00:00+02:00"
        data["maintenance"]["expires_at"] = "2026-10-14T14:10:00+02:00"
        self.assertTrue(validate_policy(data).maintenance_open(self.now))

    def test_window_duration_is_positive_and_at_most_fifteen_minutes(self):
        for duration in (0, -1, 901):
            with self.subTest(duration=duration), self.assertRaises(ConfigError):
                validate_policy(self.enabled_policy(duration))
        self.assertTrue(validate_policy(self.enabled_policy(900)).maintenance_open(self.now))

    def test_enabled_window_requires_valid_aware_timestamps(self):
        for value in (None, "", "not-a-date", "2026-10-14T12:00:00", 123, True):
            for field in ("starts_at", "expires_at"):
                with self.subTest(field=field, value=value):
                    data = self.enabled_policy()
                    data["maintenance"][field] = value
                    with self.assertRaises(ConfigError):
                        validate_policy(data)

    def test_temperatures_are_ints_and_constrained_by_hard_envelope(self):
        for field, value in (("min_temp", True), ("max_temp", False), ("max_temp", -15.0), ("min_temp", "-40"), ("min_temp", -41), ("max_temp", -14), ("min_temp", -14), ("max_temp", -41)):
            with self.subTest(field=field, value=value):
                data = default_policy()
                data[field] = value
                with self.assertRaises(ConfigError):
                    validate_policy(data)
        data = default_policy()
        data.update(min_temp=-25, max_temp=-20)
        validated = validate_policy(data)
        self.assertEqual((validated.min_temp, validated.max_temp), (-25, -20))

    def test_version_and_enabled_have_strict_types(self):
        for value in (1, 3, True, "2", 2.0, None):
            with self.subTest(version=value):
                data = default_policy()
                data["version"] = value
                with self.assertRaises(ConfigError):
                    validate_policy(data)
        for value in (1, 0, "false", None):
            with self.subTest(enabled=value):
                data = default_policy()
                data["maintenance"]["enabled"] = value
                with self.assertRaises(ConfigError):
                    validate_policy(data)

    def test_missing_and_unknown_fields_are_rejected(self):
        for field in default_policy():
            with self.subTest(missing=field):
                data = default_policy()
                del data[field]
                with self.assertRaises(ConfigError):
                    validate_policy(data)
        for field in ("enabled", "starts_at", "expires_at"):
            with self.subTest(missing_maintenance=field):
                data = default_policy()
                del data["maintenance"][field]
                with self.assertRaises(ConfigError):
                    validate_policy(data)
        for nested in (False, True):
            with self.subTest(nested=nested):
                data = default_policy()
                target = data["maintenance"] if nested else data
                target["allowed_registers"] = [999]
                with self.assertRaises(ConfigError):
                    validate_policy(data)

    def test_non_object_inputs_and_maintenance_are_rejected(self):
        for value in (None, [], "policy", 5):
            with self.subTest(value=value), self.assertRaises(ConfigError):
                validate_policy(value)
            data = default_policy()
            data["maintenance"] = value
            with self.subTest(maintenance=value), self.assertRaises(ConfigError):
                validate_policy(data)

    def test_validation_does_not_mutate_input(self):
        data = self.enabled_policy()
        original = copy.deepcopy(data)
        validate_policy(data)
        self.assertEqual(data, original)

    def test_load_policy_reads_valid_policy(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "policy.json"
            path.write_text(json.dumps(self.enabled_policy()), encoding="utf-8")
            policy = load_policy(path)
            self.assertTrue(policy.maintenance_open(self.now))

    def test_missing_policy_is_fail_closed_without_creating_a_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "missing.json"
            with self.assertRaises(ConfigError):
                load_policy(path)
            self.assertFalse(path.exists())

    def test_corrupt_or_invalid_policy_never_falls_back_to_open(self):
        for content in ("{", "null", "[]", '{"maintenance_window_open":true,"max_temp":-15}'):
            with self.subTest(content=content), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "policy.json"
                path.write_text(content, encoding="utf-8")
                with self.assertRaises(ConfigError):
                    load_policy(path)
                self.assertEqual(path.read_text(encoding="utf-8"), content)

    def test_duplicate_policy_keys_are_rejected(self):
        content = json.dumps(default_policy()).replace('"version": 2', '"version": 2, "version": 2')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "policy.json"
            path.write_text(content, encoding="utf-8")
            with self.assertRaises(ConfigError):
                load_policy(path)

    def test_oversized_policy_is_rejected(self):
        content = json.dumps(default_policy()) + " " * 16384
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "policy.json"
            path.write_text(content, encoding="utf-8")
            with self.assertRaises(ConfigError):
                load_policy(path)


if __name__ == "__main__":
    unittest.main()
