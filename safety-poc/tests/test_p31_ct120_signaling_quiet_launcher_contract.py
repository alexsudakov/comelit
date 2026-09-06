from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
LAUNCHER = ROOT / "safety-poc/research/media/v1/ct120_launch_entrance_self_activation_signaling_probe_v2.sh"
BASE_RUNNER = ROOT / "safety-poc/research/media/v1/ct120_run_entrance_self_activation_signaling_probe.sh"


class P31Ct120SignalingQuietLauncherContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = LAUNCHER.read_text(encoding="utf-8")
        cls.base = BASE_RUNNER.read_text(encoding="utf-8")

    def test_base_runner_contains_known_multiline_grep_false_positive(self):
        bad = "if grep -Fq $'        100,\\n        v4_door_tick_cb,' \"$CANDIDATE_SOURCE\"; then"
        self.assertEqual(self.base.count(bad), 1)
        self.assertIn("v4_door_tick_cb,", self.base)

    def test_launcher_patches_only_door_timer_gate_pattern(self):
        old = "old = \"if grep -Fq $'        100,\\\\n        v4_door_tick_cb,' \\\"$CANDIDATE_SOURCE\\\"; then\""
        new = "new = \"if grep -Fq '        v4_door_tick_cb,' \\\"$CANDIDATE_SOURCE\\\"; then\""
        self.assertIn(old, self.text)
        self.assertIn(new, self.text)
        self.assertIn("RUNNER_PATCH_ANCHOR_COUNT", self.text)
        self.assertIn("RUNNER_PATCH_GATE=PASS", self.text)

    def test_exact_reviewed_base_runner_blob_is_pinned(self):
        self.assertIn(
            "BASE_RUNNER_BLOB=399db88970197d63f424262cfbde38d9253d816a",
            self.text,
        )
        self.assertIn("LAUNCHER_BASE_RUNNER_BLOB_GATE=FAIL", self.text)

    def test_exactly_one_runner_invocation_and_no_retry(self):
        invocation = '"$PATCHED_RUNNER" > "$DETAIL_LOG" 2>&1'
        self.assertEqual(self.text.count(invocation), 1)
        self.assertIn("AUTOMATIC_RETRY=false", self.text)
        self.assertNotIn("while true", self.text.lower())

    def test_verbose_output_is_kept_out_of_terminal(self):
        self.assertIn("DETAIL_LOG=", self.text)
        self.assertIn("SUMMARY_FILE=", self.text)
        self.assertIn('cat "$SUMMARY_FILE"', self.text)
        self.assertNotIn('tee "$DETAIL_LOG"', self.text)
        self.assertNotIn('tee "$LOG"', self.text)

    def test_summary_contains_required_live_and_safety_markers(self):
        for marker in (
            "PSEUDOTCP_OPEN_COUNT=",
            "CTPP_REGISTRATION_COUNT=",
            "SELF_ACTIVATION_SENT_COUNT=",
            "SELF_ACTIVATION_ACK_COUNT=",
            "CLIENT_VIDEO_EVENT_SENT_COUNT=",
            "CLIENT_VIDEO_EVENT_ACK_COUNT=",
            "DEVICE_VIDEO_EVENT_COUNT=",
            "SIGNALING_PROBE_PASS_COUNT=",
            "DOOR_RESULT_MARKER_COUNT=",
            "DOOR_ACTION_SENT=",
            "FINAL_DEVICE_VIDEO_ACK_SENT=",
            "MEDIA_PAYLOAD_CAPTURED=",
            "LISTENER_READY_AFTER=",
            "CT120_ENTRANCE_SIGNALING_LAUNCH=PASS",
            "CT120_ENTRANCE_SIGNALING_LAUNCH=FAIL",
        ):
            self.assertIn(marker, self.text)

    def test_launcher_has_no_direct_door_or_media_actuation(self):
        for forbidden in (
            "kill -USR1",
            "button.press",
            "pseudo_tcp_socket_send(",
            "nice_agent_send(",
            "0x0028",
            "0x0008",
        ):
            self.assertNotIn(forbidden, self.text)


if __name__ == "__main__":
    unittest.main()
