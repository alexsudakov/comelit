#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import re
import subprocess
import sys
import unittest

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


def function_body(text: str, name: str) -> str:
    marker = f"def {name}("
    tail = text.split(marker, 1)[1]
    match = re.search(r"\n(?:def|class) [A-Za-z_]", tail)
    return tail if match is None else tail[: match.start()]


class SafeCursorTests(unittest.TestCase):
    def test_brief_parser_accepts_only_load_bearing_tags(self) -> None:
        self.assertEqual(
            CURSOR.parse_brief_logcat_line(
                "I/ComelitStatus( 123): VIP REGISTER CHANGED REGISTERING -> REGISTERED\n"
            ),
            ("ComelitStatus", "VIP REGISTER CHANGED REGISTERING -> REGISTERED"),
        )
        self.assertEqual(
            CURSOR.parse_brief_logcat_line(
                "E/ViperSocketReaderRun: VIPER SOCKET CONNECTION LOST\n"
            ),
            ("ViperSocketReaderRun", "VIPER SOCKET CONNECTION LOST"),
        )
        self.assertIsNone(CURSOR.parse_brief_logcat_line("I/OtherTag: hello\n"))

    def test_stale_event_before_cursor_does_not_pass(self) -> None:
        buf = CURSOR.SafeLogEventBuffer()
        self.assertTrue(
            buf.ingest_brief_line(
                "I/ComelitStatus: VIP REGISTER CHANGED REGISTERING -> REGISTERED"
            )
        )
        cursor = buf.capture_cursor()
        verdict = buf.evaluate_after(cursor)
        self.assertFalse(verdict.registration_ready_fresh_scalar)

    def test_fresh_event_after_cursor_passes(self) -> None:
        buf = CURSOR.SafeLogEventBuffer()
        cursor = buf.capture_cursor()
        buf.ingest_brief_line(
            "I/ComelitStatus: VIP REGISTER CHANGED REGISTERING -> REGISTERED"
        )
        verdict = buf.evaluate_after(cursor)
        self.assertTrue(verdict.registration_ready_fresh_scalar)

    def test_later_transport_failure_invalidates(self) -> None:
        buf = CURSOR.SafeLogEventBuffer()
        cursor = buf.capture_cursor()
        buf.ingest_brief_line(
            "I/ComelitStatus: VIP REGISTER CHANGED NOT_REGISTERED -> REGISTERED"
        )
        buf.ingest_brief_line(
            "E/ViperSocketReaderRun: VIPER SOCKET CONNECTION LOST"
        )
        verdict = buf.evaluate_after(cursor)
        self.assertFalse(verdict.registration_ready_fresh_scalar)
        self.assertTrue(verdict.transport_failure_after_transition)

    def test_safe_snapshot_has_no_raw_log_line_field(self) -> None:
        buf = CURSOR.SafeLogEventBuffer()
        raw = "I/ComelitStatus: VIP REGISTER CHANGED REGISTERING -> REGISTERED"
        buf.ingest_brief_line(raw)
        snapshot = buf.safe_snapshot()
        self.assertEqual(len(snapshot), 1)
        self.assertFalse(hasattr(snapshot[0], "raw_line"))
        self.assertNotIn(raw, repr(snapshot[0]))


class RunnerStaticContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = RUNNER_PATH.read_text(encoding="utf-8")

    def test_identity_and_exact_approval_gate(self) -> None:
        self.assertIn(
            'BASE_R40H_SHA = "f317bc1145b4165db0ef3677ebba777edd6780d1"',
            self.text,
        )
        self.assertIn(
            'APPROVAL_TOKEN = "I_APPROVE_R41_V4_NO_RING_PREFLIGHT_ONCE"',
            self.text,
        )
        approval = self.text.index('os.environ.get("R41_APPROVAL", "")')
        private_input = self.text.index("read_control_url(Path(args.control_url_file))")
        adb_start = self.text.index("logcat.start()")
        self.assertLess(approval, private_input)
        self.assertLess(approval, adb_start)

    def test_timeout_has_safety_margin_below_failsafe(self) -> None:
        self.assertIn("FAILSAFE_CONTINUOUS_DOWN_SECONDS = 300", self.text)
        self.assertIn("MAX_OPERATIONAL_TIMEOUT_SECONDS = 240", self.text)
        self.assertIn("value > MAX_OPERATIONAL_TIMEOUT_SECONDS", self.text)

    def test_one_persistent_logcat_and_t_is_startup_only(self) -> None:
        body = function_body(self.text, "build_adb_logcat_command")
        for token in ('"logcat"', '"-T", "1"', '"ComelitStatus:I"', '"ViperSocketReaderRun:E"'):
            self.assertIn(token, body)
        self.assertNotIn('"clear"', body)
        self.assertNotIn("/proc/uptime", self.text)
        logcat_class = self.text.split("class PersistentSafeLogcat:", 1)[1].split(
            "@dataclasses.dataclass", 1
        )[0]
        self.assertEqual(logcat_class.count("subprocess.Popen("), 1)

    def test_control_action_surface_is_closed(self) -> None:
        self.assertIn(
            '_ALLOWED_CONTROL_ACTIONS = frozenset({"status", "stop", "start"})',
            self.text,
        )
        self.assertIn("if action not in _ALLOWED_CONTROL_ACTIONS", self.text)

    def test_control_url_is_runtime_only(self) -> None:
        self.assertIn("--control-url-file", self.text)
        self.assertIn("private_file_metadata_invalid", self.text)
        self.assertNotRegex(self.text, r"192\.168\.\d+\.\d+")
        self.assertNotIn("/api/webhook/", self.text)

    def test_ring_budget_is_hardcoded_false(self) -> None:
        gate = function_body(self.text, "evaluate_gate")
        self.assertIn("ring_budget_available=False", gate)
        self.assertIn("if verdict.physical_ring_allowed", gate)
        self.assertNotIn("ring_budget_available=True", self.text)

    def test_no_actuation_media_or_ring_invocation_surface(self) -> None:
        # Result/accounting markers such as SYNTHETIC_RING_COUNT=0 are allowed.
        # Reject actual invocation/API surfaces instead of matching marker prose.
        lowered = self.text.lower()
        for forbidden in (
            "comelit.open_door",
            "open_gate(",
            "async_simulate_entrance_ring(",
            "simulate-entrance-ring",
            "camera.turn_on",
            "media_session.async_acquire",
            "homeassistant.restart",
            '"action":"ring"',
            '"action": "ring"',
        ):
            self.assertNotIn(forbidden, lowered)

    def test_single_experimental_stop_site(self) -> None:
        self.assertEqual(function_body(self.text, "run_attempt").count('control.post("stop"'), 1)

    def test_one_normal_restore_start_and_one_failsafe_recovery_start(self) -> None:
        restore = function_body(self.text, "restore_listener_once")
        failsafe = function_body(self.text, "_failsafe_child")
        self.assertEqual(restore.count('control.post("start"'), 1)
        self.assertEqual(failsafe.count('control.post("start"'), 1)
        self.assertIn("at most one recovery", failsafe.lower())

    def test_ui_sample_is_forced_post_pause(self) -> None:
        run = function_body(self.text, "run_attempt")
        pause_confirm = run.index("sample_twice(control, status_paused)")
        unlink = run.index("ui_file.unlink()")
        prompt = run.index("R41_OPERATOR_UI_STATE_SAMPLE_NOW=true")
        wait = run.index('state.last_step = "WAIT_APP_READY"')
        self.assertLess(pause_confirm, unlink)
        self.assertLess(unlink, prompt)
        self.assertLess(prompt, wait)

    def test_raw_logcat_not_persisted_or_printed(self) -> None:
        self.assertNotIn("stdout=open(", self.text)
        self.assertNotIn("logcat.txt", self.text)
        self.assertIn("stderr=subprocess.DEVNULL", self.text)

    def test_missing_approval_performs_zero_live_work(self) -> None:
        env = os.environ.copy()
        env.pop("R41_APPROVAL", None)
        result = subprocess.run(
            [
                sys.executable, str(RUNNER_PATH),
                "--control-url-file", "/does/not/exist",
                "--adb-serial", "not-used",
                "--attempt-id", "offline-negative-test",
            ],
            cwd=ROOT, env=env, text=True, capture_output=True, check=False,
        )
        self.assertEqual(result.returncode, 64, result.stderr)
        for token in (
            "APPROVAL_GRANTED=false",
            "ADB_LIVE_INVOCATIONS=0",
            "LISTENER_PAUSE_COUNT=0",
            "PHYSICAL_RING_COUNT=0",
            "RESULT=BLOCKED_APPROVAL_REQUIRED",
        ):
            self.assertIn(token, result.stdout)


class PlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = PLAN_PATH.read_text(encoding="utf-8")

    def test_plan_records_cursor_correction(self) -> None:
        for token in (
            "PERSISTENT_LOGCAT_STREAM=true",
            "ADB_T_USED_AS_ATTEMPT_CURSOR=false",
            "ADB_T_INITIAL_BACKLOG_ONLY=true",
            "HOST_SAFE_EVENT_CURSOR=true",
            "LOGCAT_BUFFER_CLEAR=false",
            "RAW_LOGCAT_PERSISTED=false",
        ):
            self.assertIn(token, self.text)

    def test_plan_keeps_live_unexecuted(self) -> None:
        self.assertIn("LIVE_EXECUTED=false", self.text)
        self.assertIn("NEXT_LIVE_AUTHORIZED=false", self.text)
        self.assertIn("RING_BUDGET_AVAILABLE_HARDCODED_FALSE=true", self.text)


if __name__ == "__main__":
    unittest.main()
