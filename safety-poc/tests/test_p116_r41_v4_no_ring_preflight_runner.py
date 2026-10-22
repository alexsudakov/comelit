#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
RESEARCH = ROOT / "research" / "media" / "v1"
CURSOR_PATH = RESEARCH / "entrance_p116_r41_persistent_logcat_cursor.py"
RUNNER_PATH = RESEARCH / "ct120_run_p116_r41_v4_no_ring_preflight.py"
PLAN_PATH = RESEARCH / "P116_R41_OFFICIAL_APP_READINESS_LIVE_PREFLIGHT_PLAN_V4.md"


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


CURSOR = load(CURSOR_PATH, "p116_r41_v4_cursor_test")
RUNNER = load(RUNNER_PATH, "p116_r41_v4_runner_test")


def function_body(text: str, name: str) -> str:
    marker = f"def {name}("
    tail = text.split(marker, 1)[1]
    match = re.search(r"\n(?:def|class) [A-Za-z_]", tail)
    return tail if match is None else tail[: match.start()]


class SafeCursorTests(unittest.TestCase):
    def test_parser_accepts_only_load_bearing_tags(self) -> None:
        self.assertEqual(
            CURSOR.parse_brief_logcat_line(
                "I/ComelitStatus( 123): VIP REGISTER CHANGED REGISTERING -> REGISTERED\n"
            ),
            ("ComelitStatus", "VIP REGISTER CHANGED REGISTERING -> REGISTERED"),
        )
        self.assertIsNone(CURSOR.parse_brief_logcat_line("I/OtherTag: secret\n"))

    def test_cursor_rejects_stale_and_accepts_fresh(self) -> None:
        buf = CURSOR.SafeLogEventBuffer()
        buf.ingest_brief_line("I/ComelitStatus: VIP REGISTER CHANGED REGISTERING -> REGISTERED")
        cursor = buf.capture_cursor()
        self.assertFalse(buf.evaluate_after(cursor).registration_ready_fresh_scalar)
        buf.ingest_brief_line("I/ComelitStatus: VIP REGISTER CHANGED NOT_REGISTERED -> REGISTERED")
        self.assertTrue(buf.evaluate_after(cursor).registration_ready_fresh_scalar)

    def test_later_transport_failure_invalidates_without_raw_retention(self) -> None:
        buf = CURSOR.SafeLogEventBuffer()
        raw = "I/ComelitStatus: VIP REGISTER CHANGED NOT_REGISTERED -> REGISTERED"
        cursor = buf.capture_cursor()
        buf.ingest_brief_line(raw)
        buf.ingest_brief_line("E/ViperSocketReaderRun: VIPER SOCKET CONNECTION LOST")
        verdict = buf.evaluate_after(cursor)
        self.assertFalse(verdict.registration_ready_fresh_scalar)
        self.assertTrue(verdict.transport_failure_after_transition)
        self.assertNotIn(raw, repr(buf.safe_snapshot()))
        self.assertFalse(hasattr(buf.safe_snapshot()[0], "raw_line"))

    def test_reduced_event_buffer_fails_closed_at_fixed_bound(self) -> None:
        buf = CURSOR.SafeLogEventBuffer()
        with mock.patch.object(CURSOR, "MAX_REDUCED_EVENTS", 1):
            self.assertTrue(buf.ingest_brief_line(
                "I/ComelitStatus: VIP REGISTER CHANGED NONE -> REGISTERED"
            ))
            self.assertFalse(buf.ingest_brief_line(
                "I/ComelitStatus: VIP REGISTER CHANGED REGISTERED -> NOT_REGISTERED"
            ))
        self.assertFalse(buf.healthy)
        self.assertEqual(buf.event_count, 1)


class RunnerContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = RUNNER_PATH.read_text(encoding="utf-8")

    def test_exact_public_approval_precedes_runtime_inputs(self) -> None:
        approval = self.text.index('os.environ.get("R41_APPROVAL", "")')
        self.assertLess(approval, self.text.index("read_control_url(Path(args.control_url_file))"))
        self.assertLess(approval, self.text.index("logcat.start()"))

    def test_missing_approval_does_zero_live_work(self) -> None:
        env = os.environ.copy()
        env.pop("R41_APPROVAL", None)
        result = subprocess.run(
            [sys.executable, str(RUNNER_PATH), "--control-url-file", "/missing",
             "--adb-serial", "unused", "--attempt-id", "offline-negative"],
            cwd=ROOT, env=env, text=True, capture_output=True, check=False,
        )
        self.assertEqual(result.returncode, 64, result.stderr)
        for marker in (
            "APPROVAL_GRANTED=false", "ADB_LIVE_INVOCATIONS=0",
            "LISTENER_PAUSE_COUNT=0", "PHYSICAL_RING_COUNT=0",
            "RESULT=BLOCKED_APPROVAL_REQUIRED",
        ):
            self.assertIn(marker, result.stdout)

    def test_missing_approval_needs_no_runtime_arguments(self) -> None:
        env = os.environ.copy()
        env.pop("R41_APPROVAL", None)
        result = subprocess.run(
            [sys.executable, str(RUNNER_PATH)], cwd=ROOT, env=env,
            text=True, capture_output=True, check=False,
        )
        self.assertEqual(result.returncode, 64, result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertIn("RESULT=BLOCKED_APPROVAL_REQUIRED", result.stdout)
        self.assertIn("OPERATIONAL_TIMEOUT_SECONDS=0", result.stdout)

    def test_private_child_without_inherited_capability_is_denied(self) -> None:
        env = os.environ.copy()
        env.pop("R41_FAILSAFE_CONFIG_FD", None)
        result = subprocess.run(
            [sys.executable, str(RUNNER_PATH), "--_failsafe-child"],
            cwd=ROOT, env=env, text=True, capture_output=True, check=False,
        )
        self.assertEqual(result.returncode, 77)
        self.assertEqual(result.stdout, "")

    def test_private_child_rejects_regular_file_as_capability(self) -> None:
        with tempfile.TemporaryFile() as capability:
            env = os.environ.copy()
            env["R41_FAILSAFE_CONFIG_FD"] = str(capability.fileno())
            result = subprocess.run(
                [sys.executable, str(RUNNER_PATH), "--_failsafe-child"],
                cwd=ROOT, env=env, pass_fds=(capability.fileno(),),
                text=True, capture_output=True, check=False,
            )
        self.assertEqual(result.returncode, 77)
        self.assertEqual(result.stdout, "")

    def test_only_child_has_one_listener_start_call_site(self) -> None:
        self.assertEqual(self.text.count('control.post("start"'), 1)
        self.assertEqual(function_body(self.text, "_send_listener_start_once").count('control.post("start"'), 1)
        self.assertIn("_send_listener_start_once", function_body(self.text, "_failsafe_child"))
        self.assertNotIn('control.post("start"', function_body(self.text, "run_attempt"))
        self.assertEqual(function_body(self.text, "run_attempt").count('control.post("stop"'), 1)

    def test_timeout_and_bounded_orphan_lifetime(self) -> None:
        self.assertEqual(RUNNER.FAILSAFE_CONTINUOUS_DOWN_SECONDS, 300)
        self.assertEqual(RUNNER.FAILSAFE_MAX_LIFETIME_BEFORE_PAUSE_SECONDS, 30)
        self.assertEqual(RUNNER.MAX_OPERATIONAL_TIMEOUT_SECONDS, 240)
        self.assertGreater(RUNNER.FAILSAFE_MAX_LIFETIME_AFTER_PAUSE_SECONDS, 300)
        with self.assertRaises(ValueError):
            RUNNER.validate_timeout_seconds(241)

    def test_evidence_cursor_is_captured_only_after_confirmed_pause(self) -> None:
        body = function_body(self.text, "run_attempt")
        self.assertLess(
            body.index('raise AttemptEnd(23, "BLOCKED_LISTENER_PAUSE_NOT_CONFIRMED")'),
            body.index("state.pre_pause_log_cursor = logcat.capture_cursor()"),
        )

    def test_logcat_is_single_filtered_process_and_never_cleared(self) -> None:
        body = function_body(self.text, "build_adb_logcat_command")
        for token in ('"logcat"', '"-T", "1"', '"ComelitStatus:I"', '"ViperSocketReaderRun:E"'):
            self.assertIn(token, body)
        self.assertNotIn('"clear"', body)
        klass = self.text.split("class PersistentSafeLogcat:", 1)[1].split("@dataclasses.dataclass", 1)[0]
        self.assertEqual(klass.count("subprocess.Popen("), 1)
        self.assertNotIn("logcat.txt", self.text)
        self.assertEqual(RUNNER.MAX_LOGCAT_LINE_BYTES, 512)

    def test_closed_control_and_no_physical_action_surface(self) -> None:
        self.assertIn('_ALLOWED_CONTROL_ACTIONS = frozenset({"status", "stop", "start"})', self.text)
        self.assertIn("ring_budget_available=False", function_body(self.text, "evaluate_gate"))
        lowered = self.text.lower()
        for forbidden in (
            "comelit.open_door", "open_gate(", "simulate-entrance-ring",
            "camera.turn_on", "media_session.async_acquire", "homeassistant.restart",
            '"action":"ring"', '"action": "ring"',
        ):
            self.assertNotIn(forbidden, lowered)

    def test_control_url_is_not_exposed_in_curl_argv(self) -> None:
        captured = {}

        def fake_run(argv, **kwargs):
            captured["argv"] = argv
            captured["input"] = kwargs["input"]
            captured["env"] = kwargs["env"]
            return subprocess.CompletedProcess(argv, 0, '{"ok":true}', "")

        url = "https://control.invalid/private-token"
        self.assertTrue(RUNNER.ControlClient(url, run=fake_run).post("status")["ok"])
        self.assertNotIn(url, captured["argv"])
        self.assertIn(url, captured["input"])
        self.assertNotIn("R41_APPROVAL", captured["env"])
        self.assertNotIn("PYTHONPATH", captured["env"])

    def test_runtime_files_reject_symlinks_and_non_private_ui(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "target"
            target.write_text("CONNECTED", encoding="utf-8")
            target.chmod(0o600)
            link = root / "ui"
            link.symlink_to(target)
            self.assertEqual(RUNNER.read_ui_state(link), "UNKNOWN")
            link.unlink()
            link.write_text("CONNECTED", encoding="utf-8")
            link.chmod(0o644)
            self.assertEqual(RUNNER.read_ui_state(link), "UNKNOWN")


class FailsafeLifecycleTests(unittest.TestCase):
    def test_bounded_pre_pause_lifetime_exits_without_control_call(self) -> None:
        calls: list[str] = []

        class FakeControl:
            def __init__(self, *args, **kwargs):
                pass

            def post(self, action, timeout=10):
                calls.append(action)
                return {}

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            root.chmod(0o700)
            read_fd, write_fd = os.pipe()
            config = {"run_root": str(root), "control_url": "http://invalid",
                      "curl_path": "curl", "heartbeat_fd": read_fd}
            with mock.patch.object(RUNNER, "ControlClient", FakeControl), mock.patch.object(
                RUNNER, "FAILSAFE_MAX_LIFETIME_BEFORE_PAUSE_SECONDS", -1
            ):
                self.assertEqual(RUNNER._failsafe_child(config), 0)
            os.close(write_fd)
            self.assertEqual(calls, [])
            self.assertEqual(
                (root / "failsafe-outcome").read_text().strip(),
                "BOUNDED_PRE_PAUSE_LIFETIME_EXPIRED",
            )

    def test_parent_death_before_pause_exits_without_control_call(self) -> None:
        calls: list[str] = []

        class FakeControl:
            def __init__(self, *args, **kwargs):
                pass

            def post(self, action, timeout=10):
                calls.append(action)
                return {}

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            root.chmod(0o700)
            read_fd, write_fd = os.pipe()
            os.close(write_fd)
            config = {"run_root": str(root), "control_url": "http://invalid",
                      "curl_path": "curl", "heartbeat_fd": read_fd}
            with mock.patch.object(RUNNER, "ControlClient", FakeControl):
                self.assertEqual(RUNNER._failsafe_child(config), 0)
            self.assertEqual(calls, [])
            self.assertEqual((root / "failsafe-outcome").read_text().strip(), "DISARMED_BEFORE_PAUSE")

    def test_normal_restore_request_causes_exactly_one_start(self) -> None:
        calls: list[str] = []

        class FakeControl:
            def __init__(self, *args, **kwargs):
                pass

            def post(self, action, timeout=10):
                calls.append(action)
                if action == "status":
                    return {"ok": True, "supervisor_running": False, "running": False,
                            "listener_ready": False, "last_error": None}
                return {"ok": True}

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            root.chmod(0o700)
            RUNNER._write_private(root / "pause-started", "true\n")
            RUNNER._write_private(root / "restore-request", "true\n")
            read_fd, write_fd = os.pipe()
            config = {"run_root": str(root), "control_url": "http://invalid",
                      "curl_path": "curl", "heartbeat_fd": read_fd}
            with mock.patch.object(RUNNER, "ControlClient", FakeControl):
                self.assertEqual(RUNNER._failsafe_child(config), 0)
            os.close(write_fd)
            self.assertEqual(calls.count("start"), 1)
            self.assertEqual((root / "failsafe-outcome").read_text().strip(), "RESTORE_START_SENT_ONCE")

    def test_continuous_down_failsafe_causes_exactly_one_recovery_start(self) -> None:
        calls: list[str] = []

        class FakeControl:
            def __init__(self, *args, **kwargs):
                pass

            def post(self, action, timeout=10):
                calls.append(action)
                return {"ok": action == "start", "supervisor_running": False,
                        "running": False, "listener_ready": False}

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            root.chmod(0o700)
            RUNNER._write_private(root / "pause-started", "true\n")
            read_fd, write_fd = os.pipe()
            config = {"run_root": str(root), "control_url": "http://invalid",
                      "curl_path": "curl", "heartbeat_fd": read_fd}
            with mock.patch.object(RUNNER, "ControlClient", FakeControl), mock.patch.object(
                RUNNER, "FAILSAFE_CONTINUOUS_DOWN_SECONDS", -1
            ):
                self.assertEqual(RUNNER._failsafe_child(config), 0)
            os.close(write_fd)
            self.assertEqual(calls.count("start"), 1)
            self.assertEqual((root / "failsafe-outcome").read_text().strip(), "RECOVERY_START_SENT_ONCE")

    def test_post_pause_lifetime_ceiling_recovers_unknown_state_once(self) -> None:
        calls: list[str] = []

        class FakeControl:
            def __init__(self, *args, **kwargs):
                pass

            def post(self, action, timeout=10):
                calls.append(action)
                if action == "status":
                    raise RuntimeError("unknown")
                return {"ok": True}

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            root.chmod(0o700)
            RUNNER._write_private(root / "pause-started", "true\n")
            read_fd, write_fd = os.pipe()
            config = {"run_root": str(root), "control_url": "http://invalid",
                      "curl_path": "curl", "heartbeat_fd": read_fd}
            with mock.patch.object(RUNNER, "ControlClient", FakeControl), mock.patch.object(
                RUNNER, "FAILSAFE_MAX_LIFETIME_AFTER_PAUSE_SECONDS", -1
            ):
                self.assertEqual(RUNNER._failsafe_child(config), 0)
            os.close(write_fd)
            self.assertEqual(calls.count("start"), 1)
            self.assertEqual(
                (root / "failsafe-outcome").read_text().strip(),
                "BOUNDED_LIFETIME_RECOVERY_START_SENT_ONCE",
            )

    def test_orphan_after_pause_exits_when_listener_is_ready(self) -> None:
        calls: list[str] = []

        class FakeControl:
            def __init__(self, *args, **kwargs):
                pass

            def post(self, action, timeout=10):
                calls.append(action)
                return {"ok": True, "supervisor_running": True, "running": True,
                        "listener_ready": True, "last_error": None}

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            root.chmod(0o700)
            RUNNER._write_private(root / "pause-started", "true\n")
            read_fd, write_fd = os.pipe()
            os.close(write_fd)
            config = {"run_root": str(root), "control_url": "http://invalid",
                      "curl_path": "curl", "heartbeat_fd": read_fd}
            with mock.patch.object(RUNNER, "ControlClient", FakeControl):
                self.assertEqual(RUNNER._failsafe_child(config), 0)
            self.assertEqual(calls, ["status", "status"])
            self.assertEqual((root / "failsafe-outcome").read_text().strip(), "PARENT_GONE_LISTENER_READY")


class PlanTests(unittest.TestCase):
    def test_plan_records_hardening_and_no_live_execution(self) -> None:
        text = PLAN_PATH.read_text(encoding="utf-8")
        for marker in (
            "CHILD_CAPABILITY_GATE=true", "SINGLE_START_OWNER=true",
            "ORPHAN_LIFETIME_BOUNDED=true", "RAW_LOGCAT_PERSISTED=false",
            "LIVE_EXECUTED=false", "NEXT_LIVE_AUTHORIZED=false",
        ):
            self.assertIn(marker, text)


if __name__ == "__main__":
    unittest.main()
