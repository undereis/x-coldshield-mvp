"""Headless dashboard behavior and command outcome regression tests."""
from datetime import timedelta
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import call, patch

from streamlit.testing.v1 import AppTest

from coldshield.client import CommandResult, send_write
from coldshield.config import default_policy, utcnow
from coldshield.protocol import Frame, ProtocolError, exception_response, write_frame
from coldshield.storage import AuditStore

ROOT = Path(__file__).resolve().parents[1]


class CommandClientTests(unittest.TestCase):
    def test_only_matching_echo_acknowledged(self):
        request = write_frame(0, -22)
        with patch("coldshield.client.exchange", return_value=request) as exchange:
            self.assertEqual(send_write(5021, 0, -22).status, "ACKNOWLEDGED")
            self.assertEqual(exchange.call_args.args[0], 5021)
        for response in (None, Frame(2, 1, request.pdu), Frame(1, 2, request.pdu), write_frame(0, 50)):
            with self.subTest(response=response), patch("coldshield.client.exchange", return_value=response):
                self.assertEqual(send_write(5021, 0, -22).status, "UNAVAILABLE")

    def test_correlated_exceptions_and_failures(self):
        request = write_frame(0, 50)
        for code in (1, 2, 3, 4, 5, 6, 8, 10, 11):
            with self.subTest(code=code), patch("coldshield.client.exchange", return_value=exception_response(request, code)):
                result = send_write(5021, 0, 50)
                self.assertEqual(result.status, "DENIED" if code in (1, 2, 3) else "UNAVAILABLE")
                self.assertEqual(result.exception_code, code)
        for error in (ConnectionRefusedError("offline"), TimeoutError("deadline"), ProtocolError("malformed")):
            with self.subTest(error=error), patch("coldshield.client.exchange", side_effect=error):
                self.assertEqual(send_write(5021, 0, 50).status, "UNAVAILABLE")
        with patch("coldshield.client.exchange", return_value=Frame(7, 1, b"\x86\x03")):
            self.assertEqual(send_write(5021, 0, 50).status, "UNAVAILABLE")
        with patch("coldshield.client.exchange", return_value=Frame(1, 1, b"\x86\x03\x00")):
            self.assertEqual(send_write(5021, 0, 50).status, "UNAVAILABLE")

    def test_invalid_arguments_never_connect(self):
        with patch("coldshield.client.exchange") as exchange:
            for args in ((0, 0, -22), (5021, -1, -22), (5021, 0, 32768), (True, 0, -22)):
                self.assertEqual(send_write(*args).status, "UNAVAILABLE")
            exchange.assert_not_called()


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.policy = self.directory / "policy.json"
        self.runtime = self.directory / "runtime"
        self.env = patch.dict(os.environ, {"COLDSHIELD_POLICY_PATH": str(self.policy),
                                          "COLDSHIELD_RUNTIME_DIR": str(self.runtime),
                                          "COLDSHIELD_GATEWAY_PORT": "5021", "COLDSHIELD_SIMULATOR_PORT": "5020"})
        self.env.start()
        self.addCleanup(self.env.stop)

    def app(self):
        # A clean environment may spend >10s importing Arrow/pandas on first render.
        app = AppTest.from_file(str(ROOT / "dashboard.py"), default_timeout=30).run()
        self.assertFalse(app.exception, [item.value for item in app.exception])
        return app

    def assert_no_crash(self, app):
        self.assertFalse(app.exception, [item.value for item in app.exception])

    def snapshot(self, age=0):
        self.runtime.mkdir(exist_ok=True)
        state = {"schema_version": 2, "last_update": (utcnow() - timedelta(seconds=age)).isoformat(),
                 "freezers": {f"Aisle {i + 1}": {"setpoint_c": -20, "defrost": False} for i in range(3)}}
        (self.runtime / "simulator_state.json").write_text(json.dumps(state))

    def test_missing_files_are_not_created(self):
        app = self.app()
        app.run()
        self.assert_no_crash(app)
        self.assertFalse(self.policy.exists())
        self.assertFalse(self.runtime.exists())
        self.assertTrue(any("Policy unavailable" in item.value for item in app.error))
        self.assertTrue(any("telemetry unavailable" in item.value for item in app.warning))

    def test_invalid_or_colliding_ports_stop_commands(self):
        for port in ("not a port", "0", "5020"):
            with self.subTest(port=port), patch.dict(os.environ, {"COLDSHIELD_GATEWAY_PORT": port}), patch("coldshield.client.send_write") as send:
                app = self.app()
                self.assertTrue(app.error)
                self.assertFalse(app.button)
                send.assert_not_called()

    def test_valid_and_corrupt_policy_remain_unchanged_on_reruns(self):
        for content in (json.dumps(default_policy()), "broken policy"):
            with self.subTest(content=content):
                self.policy.write_text(content)
                before = self.policy.stat().st_mtime_ns
                app = self.app()
                app.checkbox(key="enable_direct").check().run()
                app.run()
                self.assert_no_crash(app)
                self.assertEqual(self.policy.read_text(), content)
                self.assertEqual(self.policy.stat().st_mtime_ns, before)
                self.assertFalse(self.runtime.exists())

    def test_failures_do_not_appear_as_success_or_blocks(self):
        self.policy.write_text(json.dumps(default_policy()))
        with patch("coldshield.client.exchange", side_effect=ConnectionRefusedError("offline")):
            app = self.app()
            for key in ("legitimate", "thermal_attack", "cascade_attack"):
                app.button(key=key).click().run()
                self.assert_no_crash(app)
                self.assertFalse(app.success)
                self.assertTrue(any("No verified acknowledgement" in item.value for item in app.error))

    def test_direct_and_reset_commands_require_explicit_gate(self):
        with patch("coldshield.client.send_write", return_value=CommandResult("ACKNOWLEDGED", "Verified echo")) as send:
            app = self.app()
            self.assertTrue(app.button(key="direct_attack").disabled)
            self.assertTrue(app.button(key="reset_lab").disabled)
            send.assert_not_called()
            app.checkbox(key="enable_direct").check().run()
            app.button(key="direct_attack").click().run()
            send.assert_called_once_with(5020, 0, 50)
            send.reset_mock()
            app.button(key="reset_lab").click().run()
            self.assertEqual(send.call_args_list, [call(5020, reg, val) for reg, val in
                             ((0, -20), (1, -20), (2, -18), (10, 0), (11, 0), (12, 0))])
            send.reset_mock()
            app.checkbox(key="enable_direct").uncheck().run()
            self.assertTrue(app.button(key="direct_attack").disabled)
            send.assert_not_called()
            self.assert_no_crash(app)

    def test_cascade_stops_after_unacknowledged_first_write(self):
        with patch("coldshield.client.send_write", return_value=CommandResult("DENIED", "Denied", 3)) as send:
            app = self.app()
            app.button(key="cascade_attack").click().run()
            self.assert_no_crash(app)
            send.assert_called_once_with(5021, 10, 1)
            self.assertFalse(app.success)
            self.assertTrue(any("has not been demonstrated" in item.value for item in app.warning))

    def test_stale_and_corrupt_telemetry_are_explicit(self):
        self.policy.write_text(json.dumps(default_policy()))
        self.snapshot(age=30)
        app = self.app()
        self.assertTrue(any("Telemetry is stale" in item.value for item in app.warning))
        self.assertEqual(len([item for item in app.metric if "setpoint" in item.label]), 4)
        (self.runtime / "simulator_state.json").write_text("corrupt")
        app.run()
        self.assert_no_crash(app)
        self.assertTrue(any("telemetry unavailable" in item.value for item in app.warning))
        self.assertEqual(len([item for item in app.metric if "Aisle" in item.label]), 0)

    def test_audit_is_bounded_and_corruption_is_visible(self):
        store = AuditStore(self.runtime / "audit.sqlite3")
        for index in range(205):
            store.record(str(index), "decision", "DENY", "test event")
        app = self.app()
        self.assertEqual(len(app.dataframe[0].value), 200)
        self.assertEqual(app.dataframe[0].value.iloc[0]["id"], 205)
        (self.runtime / "audit.sqlite3").write_bytes(b"damaged")
        app.run()
        self.assert_no_crash(app)
        self.assertTrue(any("Audit database unavailable or corrupt" in item.value for item in app.error))


if __name__ == "__main__":
    unittest.main()
