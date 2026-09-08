#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = (
    ROOT
    / "research"
    / "media"
    / "v1"
    / "ct120_run_entrance_p78_one_shot_live_closure.sh"
)


class P78LauncherStaticContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = LAUNCHER.read_text(encoding="utf-8")

    def test_review_pin_is_env_bound_and_fail_closed(self) -> None:
        self.assertIn(
            'P78_REVIEW_COMMIT_SHA="${P78_REVIEW_COMMIT_SHA:-}"',
            self.text,
        )
        for marker in (
            "P78_REVIEW_COMMIT_SHA_EMPTY",
            "ORIGIN_MAIN_NOT_REVIEW_COMMIT",
            "LOCAL_HEAD_NOT_REVIEW_COMMIT",
            "P78_LAUNCHER_WORKTREE_MISMATCH",
            "P78_TRANSFORM_WORKTREE_MISMATCH",
            "P78_VERIFIER_WORKTREE_MISMATCH",
            "P78_REVIEWED_LIVE_RUN",
        ):
            self.assertIn(marker, self.text)

    def test_sentinel_is_atomic_and_immediately_precedes_live_boundary(self) -> None:
        self.assertIn("SENTINEL=/root/.comelit-p78-live-consumed", self.text)
        self.assertIn("os.O_CREAT | os.O_EXCL", self.text)
        self.assertIn("CONSUMED_BEFORE_LIVE_ENTRYPOINT", self.text)
        self.assertIn("os.fsync(fd)", self.text)
        self.assertIn("os.fsync(parent)", self.text)
        self.assertIn("P78_SENTINEL_CONSUMED=true", self.text)

        self.assertLess(
            self.text.rindex("P78_MEDIA_CAPTURE_READY=true"),
            self.text.rindex("consume_sentinel"),
        )
        self.assertLess(
            self.text.rindex("consume_sentinel"),
            self.text.index(
                'timeout --signal=TERM --kill-after=5s 75s "$CANDIDATE_WRAPPER"'
            ),
        )
        self.assertNotRegex(self.text, r"rm\s+.*SENTINEL")

    def test_exactly_one_wrapper_no_retry_and_bounded_sll2_capture(self) -> None:
        self.assertEqual(
            self.text.count(
                'timeout --signal=TERM --kill-after=5s 75s "$CANDIDATE_WRAPPER"'
            ),
            1,
        )
        self.assertIn("P78_LIVE_INVOCATION_LIMIT=1", self.text)
        self.assertIn("P78_WRAPPER_INVOCATIONS=1", self.text)
        self.assertIn("P78_AUTO_RETRY=false", self.text)
        self.assertIn("AUTOMATIC_RETRY=false", self.text)
        self.assertNotIn("for attempt", self.text)
        self.assertNotIn("while true", self.text)

        match = re.search(r"CAPTURE_WINDOW_SECONDS=(\d+)", self.text)
        self.assertIsNotNone(match)
        assert match is not None
        self.assertLessEqual(int(match.group(1)), 12)
        self.assertIn("CAPTURE_DLT=LINUX_SLL2", self.text)
        self.assertIn('tcpdump -i any -y "$CAPTURE_DLT" -d udp', self.text)
        self.assertIn(
            'tcpdump -U -i any -y "$CAPTURE_DLT" -w "$PCAP_PATH" udp',
            self.text,
        )
        self.assertIn('"${CAPTURE_WINDOW_SECONDS}s"', self.text)
        self.assertNotIn('sleep "$CAPTURE_WINDOW_SECONDS"', self.text)

    def test_listener_is_status_only_and_never_controlled(self) -> None:
        self.assertIn("P78_LISTENER_CONTROL_MODE=STATUS_ONLY", self.text)
        self.assertIn("status_only() {", self.text)
        self.assertIn('-d \'{"action":"status"}\'', self.text)
        self.assertIn('status_only "$status_before"', self.text)
        self.assertIn('status_only "$status_after"', self.text)
        self.assertIn('require_status_running_ready "$status_before"', self.text)
        self.assertIn('require_status_running_ready "$status_after"', self.text)

        self.assertNotRegex(
            self.text,
            r'-d\s+[\'"]\{"action":"(?:start|stop|restart)"\}[\'"]',
        )
        for forbidden in (
            "post_control start",
            "post_control stop",
            "systemctl restart",
            "systemctl stop",
            "systemctl start",
            "async_start",
            "async_stop",
        ):
            self.assertNotIn(forbidden, self.text)

    def test_no_extra_ctpp_open_or_door_action_surface(self) -> None:
        self.assertNotIn("v4_queue_open_ctpp", self.text)
        self.assertNotIn("open_ctpp", self.text)
        self.assertNotIn("P12_TX_V4_DOOR_WRITE", self.text)
        self.assertNotIn("V4_DOOR_WRITE", self.text)
        self.assertIn("DOOR_ACTION_SENT_COUNT=0", self.text)
        self.assertIn("P78_DOOR_ACTION_SENT=false", self.text)
        self.assertIn("P78_SECOND_CTPP_OPEN=false", self.text)

    def test_holder_stage_results_are_evidence_derived(self) -> None:
        mappings = (
            ("P78_SELF_ACTIVATION_SENT", "ENTRANCE_SELF_ACTIVATION_SENT"),
            ("P78_CLIENT_VIDEO_EVENT_SENT", "ENTRANCE_VIDEO_EVENT_SENT"),
            ("P78_DEVICE_0008_EVENT", "ENTRANCE_DEVICE_VIDEO_EVENT"),
            ("P78_DEVICE_0008_ACK_SENT", "P78_DEVICE_0008_ACK_SENT"),
            ("P78_RTPC_OPEN_1_SENT", "P78_RTPC_OPEN_1_SENT"),
            ("P78_RTPC_OPEN_2_SENT", "P78_RTPC_OPEN_2_SENT"),
            ("P78_RTPC_DEVICE_OPEN_OBSERVED", "P78_RTPC_DEVICE_OPEN_OBSERVED"),
            ("P78_RTPC_CLIENT_RESPONSE_SENT", "P78_RTPC_CLIENT_RESPONSE_SENT"),
            ("P78_RTPC_DEVICE_RESPONSE_1", "P78_RTPC_DEVICE_RESPONSE_1"),
            ("P78_RTPC_DEVICE_RESPONSE_2", "P78_RTPC_DEVICE_RESPONSE_2"),
            ("P78_RTPC_CLIENT_000A_SENT", "P78_RTPC_CLIENT_000A_SENT"),
            ("P78_RTPC_CLIENT_001A_SENT", "P78_RTPC_CLIENT_001A_SENT"),
            ("P78_RTPC_SIGNALING_RESULT", "P78_RTPC_SIGNALING_RESULT"),
        )
        self.assertIn("emit_holder_results() {", self.text)
        self.assertIn("'NOT_REACHED'", self.text)
        for launcher_key, holder_key in mappings:
            self.assertIn(
                f"emit_detail_marker '{launcher_key}' '{holder_key}'",
                self.text,
            )
            self.assertNotIn(f"echo '{launcher_key}=PASS'", self.text)

    def test_live_verifier_decode_is_mandatory_and_final_pass_is_strict(self) -> None:
        verifier_call = self.text.split('python3 "$REPO/$P78_VERIFIER_REL"', 1)[1]
        self.assertIn("--decode", verifier_call)
        self.assertIn("P78_DECODE_REQUIRED=true", self.text)

        for marker in (
            "P78_H264_ORACLE",
            "P78_FFPROBE_STATUS",
            "P78_FFMPEG_DECODE_STATUS",
            "P78_SCRATCH_JPEG_COUNT",
            "P78_DECODE_STATUS",
        ):
            self.assertIn(marker, self.text)

        final_gate = self.text.split('if [[ "$wrapper_rc" -eq 0 &&', 1)[1]
        for required in (
            '"$terminal_result" == "PASS"',
            '"$capture_ok" == true',
            '"$verifier_rc" -eq 0',
            '"$h264_oracle" == "PASS"',
            '"$ffprobe_status" == "PASS"',
            '"$ffmpeg_status" == "PASS"',
            '"$decode_status" == "PASS"',
            '"$jpeg_count" == "1"',
            '"$listener_after_ok" == true',
        ):
            self.assertIn(required, final_gate)

    def test_required_safety_markers_exist(self) -> None:
        for marker in (
            "P78_PREFLIGHT=PASS",
            "P78_LISTENER_STATUS_BEFORE=RUNNING_READY",
            "P78_LISTENER_STATUS_AFTER=RUNNING_READY",
            "P78_MEDIA_CAPTURE_DLT_GATE=PASS",
            "P78_MEDIA_CAPTURE_BOUND=PASS",
            "P78_MEDIA_PAYLOAD_STDOUT=false",
            "P78_RAW_PAYLOAD_EMITTED=false",
            "P78_PSEUDOTCP_GRACEFUL_CLOSE_FORCE=false",
            "P78_PSEUDOTCP_GRACEFUL_CLOSE_FORCE_RST_SENT=false",
            "P78_HOME_ASSISTANT_CORE_STOPPED=false",
            "P78_HOME_ASSISTANT_CORE_RESTARTED=false",
            "LISTENER_CHANGED=NO",
            "P78_SENTINEL_CONSUMED=false",
            "LIVE_INVOCATIONS=0",
        ):
            self.assertIn(marker, self.text)


if __name__ == "__main__":
    unittest.main()
