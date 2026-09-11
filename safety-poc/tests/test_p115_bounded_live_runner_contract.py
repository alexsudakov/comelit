#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import re
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parent
RUNNER = ROOT / "research" / "media" / "v1" / "p115_bounded_live_runner.sh"

BASE_SHA = "5b134f19c29bd7b739b0ec3358b58480cf16f174"
PACKAGED_SHA = "91335b4490bc58910c78cb58b9c2d3eccc13f40dcfff7651995ad428cd71ddc7"
BASE_WRAPPER_SHA = "a564535dff0cf10b1fe4766171f2960c52fb581f1c816cf81d2992c5c84e79c9"


class P115BoundedLiveRunnerContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.runner = RUNNER.read_text(encoding="utf-8")

    def test_pause_mode_declared_and_default(self) -> None:
        self.assertIn("DEFAULT MODE: PAUSE_FOR_MEDIA_VIA_TEST_HARNESS", self.runner)
        self.assertIn('P115_LISTENER_MODE="${P115_LISTENER_MODE:-PAUSE_FOR_MEDIA_VIA_TEST_HARNESS}"', self.runner)
        self.assertIn("PAUSE_FOR_MEDIA_VIA_TEST_HARNESS|NO_LISTENER_ACTION", self.runner)
        self.assertIn("NO_LISTENER_ACTION", self.runner)

    def test_at_most_one_stop_and_one_start_post(self) -> None:
        actions = re.findall(r'\{"action":"([a-z]+)"\}', self.runner)
        self.assertEqual(actions.count("status"), 1)
        self.assertLessEqual(actions.count("stop"), 1)
        self.assertLessEqual(actions.count("start"), 1)
        self.assertEqual(sorted(set(actions)), ["start", "status", "stop"])
        self.assertIn("post_status()", self.runner)
        self.assertIn("post_control()", self.runner)

    def test_start_is_gated_by_confirmed_teardown(self) -> None:
        teardown_classification = self.runner.index("derive_teardown_confidence()")
        start_body = self.runner.index('{"action":"start"}')
        self.assertLess(teardown_classification, start_body)
        restore_function = self.runner[
            self.runner.index("restore_listener_if_allowed() {"):
            self.runner.index("derive_result()", self.runner.index("restore_listener_if_allowed() {"))
        ]
        self.assertIn('[ "$TEARDOWN_CONFIDENCE" != CONFIRMED ]', restore_function)
        self.assertIn("LISTENER_RESTART_SUPPRESSED=true", restore_function)
        self.assertIn("post_control start", restore_function)

    def test_ambiguous_teardown_blocks_further_attempts(self) -> None:
        self.assertIn("LIVE_BLOCKED_AMBIGUOUS_TEARDOWN=true", self.runner)
        self.assertIn("P115_STOP_ALL_LIVE_ATTEMPTS=true", self.runner)
        self.assertIn("exit 90", self.runner)

    def test_runner_pins_base_sha_and_packaged_binary_identity(self) -> None:
        self.assertIn(f"BASE_SHA={BASE_SHA}", self.runner)
        self.assertIn(f"P115_PACKAGED_BINARY_SHA256={PACKAGED_SHA}", self.runner)
        self.assertIn("P115_PACKAGED_BINARY_BYTES=257152", self.runner)
        self.assertIn(f"P115_BASE_WRAPPER_SHA256={BASE_WRAPPER_SHA}", self.runner)
        self.assertIn("EXPECTED_INTERPRETER=/lib/ld-musl-x86_64.so.1", self.runner)
        self.assertIn("/etc/alpine-release", self.runner)
        self.assertIn("ld-musl-x86_64.so.1", self.runner)
        for lib in ("libnice.so.10", "libglib-2.0.so.0", "libgobject-2.0.so.0"):
            self.assertIn(lib, self.runner)
        self.assertIn("P80_VIDEO_RTP_PACKETS=%llu", self.runner)
        self.assertIn("P80_AUDIO_RTP_PACKETS=%llu", self.runner)

    def test_runner_has_bounded_single_invocation_contract(self) -> None:
        self.assertIn("P115_LIVE_INVOCATION_LIMIT=1", self.runner)
        self.assertIn("MEDIA_SESSION_TIMEOUT_SECONDS=45", self.runner)
        self.assertIn("OUTER_TIMEOUT_SECONDS=75", self.runner)
        self.assertIn("LIVE_WINDOW_SECONDS=40", self.runner)
        self.assertIn("P115_AUTOMATIC_RETRY=false", self.runner)
        self.assertIn("P115_BLIND_RETRY=false", self.runner)
        self.assertEqual(re.findall(r"^LIVE_INVOCATIONS=1$", self.runner, re.MULTILINE), ["LIVE_INVOCATIONS=1"])
        self.assertIn('while [ "$OBSERVATION_SECONDS" -lt "$LIVE_WINDOW_SECONDS" ]', self.runner)
        self.assertIn("for i in 1 2 3 4 5; do", self.runner)

    def test_runner_contains_no_door_or_gate_action(self) -> None:
        for forbidden in ("--door", "--gate", "open_door", "DOOR_GATE"):
            self.assertNotIn(forbidden, self.runner)
        self.assertIn("DOOR_ACTIONS_SENT=0", self.runner)
        self.assertIn("GATE_ACTIONS_SENT=0", self.runner)

    def test_runner_emits_required_summary_markers(self) -> None:
        for marker in (
            "=== P115 LIVE RUN SUMMARY ===",
            "P115_LIVE_RUN_ID=",
            "P115_BASE_SHA=",
            "P115_LISTENER_MODE=",
            "P115_PACKAGED_BINARY_SHA_BEFORE_RUN=",
            "P115_PACKAGED_BINARY_SHA_GATE=",
            "P115_RUNTIME_ABI_GATE=",
            "P115_BASE_WRAPPER_SHA_GATE=",
            "LISTENER_READY_BEFORE=",
            "LISTENER_PAUSE_FOR_MEDIA_ALLOWED=",
            "LISTENER_PAUSED_ONLY_DURING_MEDIA=",
            "LISTENER_PAUSE_COUNT=",
            "LISTENER_START_COUNT=",
            "LISTENER_RESTORE_READY=",
            "LISTENER_RESTART_SUPPRESSED=",
            "LIVE_BLOCKED_AMBIGUOUS_TEARDOWN=",
            "P115_PRE_MEDIA_AMBIGUOUS=",
            "TEMPORARY_TEST_HARNESS=",
            "HARNESS_EQUIVALENCE=",
            "HARNESS_NOT_IDENTICAL_TO_PRODUCTION=",
            "PRODUCTION_LIFECYCLE_VALIDATED=",
            "LISTENER_READY_AFTER=",
            "LISTENER_RECONNECT_COUNT_BEFORE=",
            "LISTENER_RECONNECT_COUNT_AFTER=",
            "LIVE_CAMERA_ATTEMPT=",
            "LIVE_INVOCATIONS=",
            "MEDIA_PHASE_ACTIVE=",
            "P80_MEDIA_ACTIVE_OBSERVED=",
            "VIDEO_P114_MARKER_MAX=",
            "AUDIO_P114_MARKER_MAX=",
            "VIDEO_PACKET_PROGRESS=",
            "AUDIO_PACKET_PROGRESS=",
            "VIDEO_RTP_DATAGRAMS=",
            "AUDIO_RTP_DATAGRAMS=",
            "P115_H264_SPS_COUNT=",
            "P115_H264_PPS_COUNT=",
            "P115_H264_IDR_COUNT=",
            "P115_JPEG_RESULT=",
            "P115_SHORT_VIDEO_RESULT=",
            "TEARDOWN_CONFIDENCE=",
            "UPSTREAM_MEDIA_ACTIVE_AT_EXIT=",
            "DOOR_ACTIONS_SENT=0",
            "GATE_ACTIONS_SENT=0",
            "P115_RESULT=",
            "=== END P115 LIVE RUN SUMMARY ===",
        ):
            self.assertIn(marker, self.runner)

    def test_runner_uses_git_archive_not_checkout(self) -> None:
        self.assertIn('git -C "$REPO" archive "$BASE_SHA" custom_components/comelit/native', self.runner)
        for forbidden in ("git checkout", "git worktree", "git reset", "make ", "cmake", "gcc ", "clang "):
            self.assertNotIn(forbidden, self.runner)
        self.assertIn("BINARY_REBUILT=false", self.runner)
        self.assertIn("BINARY_SUBSTITUTED=false", self.runner)

    def test_runner_rejects_missing_musl_boundary_before_any_action(self) -> None:
        abi_fail = self.runner.index('[ "$P115_RUNTIME_ABI_GATE" = PASS ] || fail "P115_RUNTIME_ABI_GATE=FAIL"')
        preflight_fail = self.runner.index('if [ "$FAIL" -ne 0 ]; then', abi_fail)
        first_status = self.runner.index('post_status "$RUN_ROOT/listener-status-before.json" 10')
        live_anchor = self.runner.index("=== EXACTLY ONE P115 BASE WRAPPER LIVE INVOCATION ===")
        self.assertLess(abi_fail, preflight_fail)
        self.assertLess(preflight_fail, first_status)
        self.assertLess(preflight_fail, live_anchor)
        self.assertLess(self.runner.index("detect_runtime_boundary"), first_status)

    def test_shell_syntax_is_valid(self) -> None:
        result = subprocess.run(
            ["bash", "-n", str(RUNNER)],
            cwd=REPO_ROOT,
            check=False,
            text=True,
            capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_preflight_only_mode_performs_no_live_action(self) -> None:
        preflight_exit = self.runner.index('if [ "$P115_PREFLIGHT_ONLY" = true ]; then')
        first_status = self.runner.index('post_status "$RUN_ROOT/listener-status-before.json" 10')
        live_anchor = self.runner.index("=== EXACTLY ONE P115 BASE WRAPPER LIVE INVOCATION ===")
        sink_anchor = self.runner.index("start_udp_sink video", preflight_exit)
        self.assertLess(preflight_exit, first_status)
        self.assertLess(preflight_exit, sink_anchor)
        self.assertLess(preflight_exit, live_anchor)
        self.assertIn("P115_PREFLIGHT_ONLY=true", self.runner)
        self.assertIn("LIVE_INVOCATIONS_THIS_TASK=0", self.runner)

    def test_pre_live_requires_listener_ready_and_media_quiescent(self) -> None:
        listener_ready = self.runner.index('status_ready "$RUN_ROOT/listener-status-before.json"')
        media_quiescent = self.runner.index("if ! pre_media_quiescent; then")
        first_stop = self.runner.index('{"action":"stop"}')
        self.assertLess(listener_ready, first_stop)
        self.assertLess(media_quiescent, first_stop)

    def test_harness_equivalence_proof_documented(self) -> None:
        self.assertIn("TEMPORARY_TEST_HARNESS=true", self.runner)
        self.assertIn("HARNESS_EQUIVALENCE=", self.runner)
        self.assertIn("custom_components/comelit/supervisor.py:149", self.runner)
        self.assertIn("custom_components/comelit/supervisor.py:159", self.runner)
        self.assertIn("custom_components/comelit/supervisor.py:170", self.runner)
        self.assertIn("custom_components/comelit/supervisor.py:181", self.runner)
        self.assertIn("custom_components/comelit/supervisor.py:183", self.runner)
        self.assertIn("custom_components/comelit/test_control.py:57", self.runner)
        self.assertIn("custom_components/comelit/test_control.py:73", self.runner)
        self.assertIn("PRODUCTION_LIFECYCLE_VALIDATED=false", self.runner)

    def test_no_door_or_gate_action_in_pause_mode(self) -> None:
        pause_branch = self.runner[
            self.runner.index('if [ "$P115_LISTENER_MODE" = PAUSE_FOR_MEDIA_VIA_TEST_HARNESS ]; then'):
            self.runner.index('rm -rf "$RUN_DIR"')
        ]
        for forbidden in ("--door", "--gate", "open_door", "DOOR_GATE"):
            self.assertNotIn(forbidden, pause_branch)
        self.assertIn("DOOR_ACTIONS_SENT=0", self.runner)
        self.assertIn("GATE_ACTIONS_SENT=0", self.runner)


if __name__ == "__main__":
    unittest.main()
