#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "research" / "media" / "v1" / "ct120_run_p105_entrance_media_live.sh"

SUMMARY_KEYS = [
    "P105_LIVE_RUN",
    "P105_HYPOTHESIS_ID",
    "P105_BRANCH_HEAD",
    "P105_LIVE_INVOCATIONS",
    "P105_WRAPPER_RC",
    "P105_OBSERVATION_SECONDS",
    "P105_REPO_HEAD",
    "LISTENER_READY_BEFORE",
    "LISTENER_STOP_GATE",
    "LISTENER_RESTORE_READY",
    "LISTENER_READY_AFTER",
    "LISTENER_RESTART_SUPPRESSED",
    "TEARDOWN_CONFIDENCE",
    "P105_CAMPAIGN_PROCESSES_REMAINING",
    "P105_CTPP_OPEN_COUNT",
    "P105_SECOND_CTPP_OPEN",
    "P105_DOOR_RESULT_COUNT",
    "P78_RTPC_SIGNALING_RESULT",
    "P80_DEVICE_ACK_000A_OBSERVED",
    "P80_DEVICE_ACK_001A_OBSERVED",
    "P80_POST_001A_ACK_GATE",
    "P80_PREACTIVE_MEDIA_DEMUX",
    "P80_PREACTIVE_MEDIA_PROFILE_ACCEPT",
    "P80_MEDIA_ACTIVE",
    "P80_VIDEO_RTP_FORWARDING",
    "P80_AUDIO_RTP_FORWARDING",
    "P80_WRAPPER_PROFILE_MISMATCH",
    "PSEUDOTCP_NOTIFY_PACKET_FAIL_LEN",
    "LEN24_FALLBACK_LINES_EMITTED",
    "P105_H264_SPS_COUNT",
    "P105_H264_PPS_COUNT",
    "P105_H264_IDR_COUNT",
    "P105_FFMPEG_PRESENT",
    "P105_JPEG_RESULT",
    "P105_JPEG_PATH",
    "P105_JPEG_SHA256",
    "P105_SHORT_VIDEO_RESULT",
    "P105_SHORT_VIDEO_PATH",
    "P105_SHORT_VIDEO_DURATION_SEC",
    "P105_SHORT_VIDEO_SHA256",
    "P105_RUN_ROOT",
    "DOOR_ACTION_SENT",
    "GATE_ACTION_SENT",
    "AUTOMATIC_RETRY",
    "HOME_ASSISTANT_CORE_STOPPED",
    "HOME_ASSISTANT_CORE_RESTARTED",
    "SECRETS_CONTENT_EMITTED",
]

POST_ENTRY_MARKERS = [
    "P78_RTPC_SIGNALING_RESULT",
    "P80_DEVICE_ACK_000A_OBSERVED",
    "P80_DEVICE_ACK_001A_OBSERVED",
    "P80_POST_001A_ACK_GATE",
    "P80_PREACTIVE_MEDIA_DEMUX",
    "P80_PREACTIVE_MEDIA_PROFILE_ACCEPT",
    "P80_PREACTIVE_MEDIA_PAYLOAD_TYPE",
    "P80_MEDIA_ACTIVE",
    "P80_VIDEO_RTP_FORWARDING",
    "P80_AUDIO_RTP_FORWARDING",
    "P80_DEVICE_ACK_000A_BINDING",
    "P80_DEVICE_ACK_001A_BINDING",
]


def function_body(text: str, name: str) -> str:
    return text.split(f"{name}() {{", 1)[1].split("\n}", 1)[0]


def without_shell_comments(text: str) -> str:
    return "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("#")
    )


class P105CT120LiveRunnerContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = RUNNER.read_text(encoding="utf-8")

    def test_launcher_is_executable_and_bash_syntax_clean(self) -> None:
        self.assertTrue(os.stat(RUNNER).st_mode & 0o111)
        result = subprocess.run(
            ["bash", "-n", str(RUNNER)],
            cwd=ROOT,
            check=False,
            text=True,
            capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_bounds_and_one_invocation_limit_are_declared_and_used(self) -> None:
        self.assertIn("LIVE_WINDOW_SECONDS=40", self.text)
        self.assertIn("OUTER_TIMEOUT_SECONDS=75", self.text)
        self.assertIn('"$OBSERVATION_SECONDS" -lt "$LIVE_WINDOW_SECONDS"', self.text)
        self.assertIn('"${OUTER_TIMEOUT_SECONDS}s" "$CANDIDATE_WRAPPER"', self.text)
        self.assertIn("P105_LIVE_INVOCATION_LIMIT=1", self.text)
        self.assertIn("LIVE_INVOCATIONS=1", self.text)
        self.assertEqual(re.findall(r"^LIVE_INVOCATIONS=1$", self.text, re.MULTILINE), ["LIVE_INVOCATIONS=1"])
        self.assertIn("P105_EXACTLY_ONCE_GATE=PASS", self.text)
        self.assertIn('[ "$LIVE_INVOCATIONS" -eq 1 ] || fail "P105_EXACTLY_ONCE_GATE=FAIL"', self.text)
        self.assertEqual(self.text.count('timeout --signal=TERM --kill-after=5s "${OUTER_TIMEOUT_SECONDS}s" "$CANDIDATE_WRAPPER"'), 1)

    def test_no_broad_process_kill_or_disallowed_action_surface(self) -> None:
        self.assertNotIn("killall", self.text)
        self.assertNotRegex(self.text, r"\bpkill\s+-f\b")
        self.assertIn('pgrep -af "$WRAPPER_NAME|$CANDIDATE_HOLDER_NAME"', self.text)
        for forbidden in ("OPEN_DOOR", "open_door", "create_door_message", "--door", " door "):
            self.assertNotIn(forbidden, self.text)

    def test_preflight_and_negative_gates_are_present(self) -> None:
        for marker in (
            "P105_LIVE_REQUIRES_ROOT=true",
            "P105_MISSING_COMMAND=$command",
            "P105_FFMPEG_PRESENT",
            "P105_FFPROBE_PRESENT",
            "P105_CT120_IDENTITY=FAIL",
            'git -C "$REPO" fetch origin "$BRANCH"',
            'git -C "$REPO" checkout -B "$BRANCH" "origin/$BRANCH"',
            "P105_REPO_HEAD=",
            'merge-base --is-ancestor "$EXPECTED_MIN_PARENT" HEAD',
            "P105_WORKTREE_CLEAN=FAIL",
            "P105_BASE_WRAPPER_PIN=FAIL",
            "P105_SECRETS_PRESENT=true",
            "P105_SECRETS_CONTENT_EMITTED=false",
            "pkg-config --exists nice glib-2.0 gio-2.0 gobject-2.0",
            "P105_EXISTING_CANDIDATE_PROCESS=FAIL",
            "P105_PREFLIGHT=FAIL",
            "P105_PREFLIGHT=PASS",
        ):
            self.assertIn(marker, self.text)
        for marker in (
            "P80_DEVICE_ACK_000A_OBSERVED=PASS",
            "P80_POST_001A_ACK_GATE=PASS",
            "P80_MEDIA_ACTIVE=true",
            "P80_PREACTIVE_MEDIA_PROFILE_ACCEPT=PASS",
            "P80_WRAPPER_PROFILE_MISMATCH_STATE=%s",
            "LEN24_FALLBACK_DIAGNOSTIC_ONLY=true",
            "P80_DOOR_SIGNAL_ENTRYPOINT=false",
        ):
            self.assertIn(marker, self.text)
        self.assertIn("signal(SIGUSR1, v4_door_signal_handler);", self.text)
        self.assertIn("grep -Fq 'signal(SIGUSR1, v4_door_signal_handler);'", self.text)

    def test_listener_order_and_uncertain_teardown_restore_suppression(self) -> None:
        ready = self.text.index('post_control status "$STATUS_BEFORE" 10')
        stop = self.text.index('post_control stop "$STOP_RESPONSE" 20')
        invoke = self.text.index('timeout --signal=TERM --kill-after=5s "${OUTER_TIMEOUT_SECONDS}s" "$CANDIDATE_WRAPPER"')
        self.assertLess(ready, stop)
        self.assertLess(stop, invoke)
        restore_body = function_body(self.text, "restore_listener")
        self.assertIn('[ "$TEARDOWN_CONFIDENCE" != CONFIRMED ]', restore_body)
        self.assertIn("LISTENER_RESTART_SUPPRESSED=true", restore_body)
        self.assertIn("LISTENER_RESTORE_FINAL_GATE=FAIL", restore_body)
        self.assertIn("return 90", restore_body)
        self.assertLess(
            restore_body.index('[ "$TEARDOWN_CONFIDENCE" != CONFIRMED ]'),
            restore_body.index("post_control start"),
        )
        confirmed_branch = self.text.split('if [ "$TEARDOWN_CONFIDENCE" = CONFIRMED ]; then', 1)[1]
        self.assertLess(confirmed_branch.index("restore_listener"), confirmed_branch.index("else"))
        uncertain_branch = confirmed_branch.split("else", 1)[1].split("fi", 1)[0]
        self.assertIn("LISTENER_RESTART_SUPPRESSED=true", uncertain_branch)
        self.assertIn("LISTENER_RESTORE_FINAL_GATE=FAIL", uncertain_branch)
        self.assertIn("exit 90", self.text)
        self.assertEqual(self.text.count("post_control start"), 1)

    def test_teardown_confidence_is_exit_state_not_historical_markers(self) -> None:
        collect_body = function_body(self.text, "collect_log_markers")
        derive_body = function_body(self.text, "derive_teardown_confidence")
        derive_logic = without_shell_comments(derive_body)

        self.assertIn('P80_MEDIA_ACTIVE="$(last_marker P80_MEDIA_ACTIVE NOT_REACHED)"', collect_body)
        self.assertIn('PSEUDOTCP_NOTIFY_PACKET="$(last_marker PSEUDOTCP_NOTIFY_PACKET NOT_OBSERVED)"', collect_body)
        self.assertNotRegex(collect_body, r"UPSTREAM_MEDIA_ACTIVE_AT_EXIT=.*")

        self.assertNotIn("P80_MEDIA_ACTIVE", derive_logic)
        self.assertNotIn("PSEUDOTCP_NOTIFY_PACKET", derive_logic)
        for token in (
            "UPSTREAM_MEDIA_ACTIVE_AT_EXIT",
            "CAMPAIGN_PROCESSES_REMAINING",
            "124",
            "137",
        ):
            self.assertIn(token, derive_body)
        self.assertIn('UPSTREAM_MEDIA_ACTIVE_AT_EXIT=false', derive_body)
        self.assertIn('UPSTREAM_MEDIA_ACTIVE_AT_EXIT=true', derive_body)
        self.assertIn('[ "$UPSTREAM_MEDIA_ACTIVE_AT_EXIT" = false ]', derive_body)
        self.assertIn('[ "$WRAPPER_RC" != 124 ]', derive_body)
        self.assertIn('[ "$WRAPPER_RC" != 137 ]', derive_body)

    def test_wrapper_derived_markers_have_fallbacks_and_no_unconditional_pass(self) -> None:
        self.assertIn("last_marker() {", self.text)
        for marker in POST_ENTRY_MARKERS:
            self.assertRegex(
                self.text,
                rf'{marker}="\$\(last_marker {marker} NOT_REACHED\)"',
            )
            self.assertNotIn(f'echo "{marker}=PASS"', self.text)
            self.assertNotIn(f"echo '{marker}=PASS'", self.text)
        for marker in (
            "P80_WRAPPER_PROFILE_MISMATCH",
            "P80_WRAPPER_PROFILE_MISMATCH_STATE",
            "PSEUDOTCP_NOTIFY_PACKET",
            "PSEUDOTCP_NOTIFY_PACKET_FAIL_LEN",
        ):
            self.assertIn(f"{marker}=NOT_OBSERVED", self.text)
        self.assertIn("LEN24_FALLBACK_SUMMARY_MAX=32", self.text)
        self.assertIn("/^LEN24_FALLBACK_/", self.text)

    def test_summary_block_contains_exact_required_keys(self) -> None:
        block = self.text.split('echo "=== COMELIT P105 CT120 LIVE RUN SUMMARY ==="', 1)[1]
        block = block.split('echo "=== END COMELIT P105 CT120 LIVE RUN SUMMARY ==="', 1)[0]
        keys = re.findall(r'echo "([A-Z0-9_]+)=', block)
        self.assertEqual(keys, SUMMARY_KEYS)

    def test_only_documented_url_literal_and_no_extra_network_capability(self) -> None:
        urls = re.findall(r"https?://[^\"'\s]+", self.text)
        self.assertEqual(
            urls,
            ["http://192.168.1.108:8123/api/webhook/comelit-ha-ring-test-control-v1}"],
        )
        self.assertIn('curl \\', self.text)
        self.assertIn('"$HA_WEBHOOK_URL"', self.text)
        for forbidden in ("nc ", "ncat", "socat", "wget ", "requests", "urllib", "/dev/tcp"):
            self.assertNotIn(forbidden, self.text)

    def test_capture_and_media_postprocessing_contract(self) -> None:
        for token in (
            "127.0.0.1",
            "VIDEO_RTP_PORT=17899",
            "AUDIO_RTP_PORT=17808",
            "P105_CAPTURE_VIDEO_PID_REDACTED=true",
            "P105_CAPTURE_AUDIO_PID_REDACTED=true",
            "P105_H264_SPS_COUNT",
            "P105_H264_PPS_COUNT",
            "P105_H264_IDR_COUNT",
            "P105_H264_FU_A_COUNT",
            "P105_H264_STAP_A_COUNT",
            "JPEG_RESULT=NOT_PROVABLE_FFMPEG_ABSENT",
            "SHORT_VIDEO_RESULT=NOT_PROVABLE_FFMPEG_ABSENT",
            "sha256sum",
            "chmod 600",
        ):
            self.assertIn(token, self.text)


if __name__ == "__main__":
    unittest.main()
