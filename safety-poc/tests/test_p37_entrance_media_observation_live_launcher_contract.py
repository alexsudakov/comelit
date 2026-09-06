from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / (
    "safety-poc/research/media/v1/ct120_run_entrance_self_activation_signaling_probe.sh"
)
LAUNCHER = ROOT / (
    "safety-poc/research/media/v1/ct120_launch_entrance_media_observation_probe_v1.sh"
)
OBS_TRANSFORM = ROOT / (
    "safety-poc/research/media/v1/entrance_media_observation_transform.py"
)


class P37EntranceMediaObservationLiveLauncherContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runner = RUNNER.read_text(encoding="utf-8")
        cls.launcher = LAUNCHER.read_text(encoding="utf-8")
        cls.transform = OBS_TRANSFORM.read_text(encoding="utf-8")

    def test_provenance_pins_reviewed_runner_and_observation_transform(self):
        self.assertIn(
            "BASE_RUNNER_BLOB=399db88970197d63f424262cfbde38d9253d816a",
            self.launcher,
        )
        self.assertIn(
            "OBS_TRANSFORM_BLOB=85a66b95d4f2ed633f978901fc9041d4a5999531",
            self.launcher,
        )
        self.assertIn("LAUNCHER_BASE_RUNNER_BLOB_GATE=FAIL", self.launcher)
        self.assertIn("LAUNCHER_OBS_TRANSFORM_BLOB_GATE=FAIL", self.launcher)

    def test_patch_anchors_match_exact_reviewed_p30_runner(self):
        old_transform = (
            "TRANSFORM_REL=safety-poc/research/media/v1/"
            "entrance_self_activation_signaling_transform.py"
        )
        old_timer = (
            "if grep -Fq $'        100,\\n        v4_door_tick_cb,' "
            '"$CANDIDATE_SOURCE"; then'
        )
        old_live_gate = '''    if [ "$COUNT" -ne 1 ]; then
        LIVE_GATE=FAIL
    fi
done
'''

        self.assertEqual(self.runner.count(old_transform), 1)
        self.assertEqual(self.runner.count(old_timer), 1)
        self.assertEqual(self.runner.count(old_live_gate), 1)

        self.assertIn("RUNNER_PATCH_ANCHOR_COUNT=", self.launcher)
        self.assertIn("RUNNER_OBSERVATION_TRANSFORM_SELECTION_INVALID=true", self.launcher)
        self.assertIn("RUNNER_DOOR_INVARIANT_POLICY_INVALID=true", self.launcher)

    def test_only_negative_door_invariant_is_relaxed_from_exactly_once(self):
        policy = (
            "if [ \"$marker\" = 'ENTRANCE_SIGNALING_DOOR_ACTION_SENT=false' ]; then"
        )
        self.assertIn(policy, self.launcher)
        self.assertIn('if [ "$COUNT" -lt 1 ]; then', self.launcher)
        self.assertIn('elif [ "$COUNT" -ne 1 ]; then', self.launcher)
        self.assertIn("RUNNER_DOOR_INVARIANT_COUNT_POLICY=AT_LEAST_ONE", self.launcher)

    def test_live_execution_is_exactly_one_runner_invocation_without_retry(self):
        invocation = '"$PATCHED_RUNNER" > "$DETAIL_LOG" 2>&1'
        self.assertEqual(self.launcher.count(invocation), 1)
        self.assertIn("AUTOMATIC_RETRY=false", self.launcher)
        self.assertNotIn("while true", self.launcher)
        self.assertNotIn("for attempt in", self.launcher)
        self.assertNotIn("until ", self.launcher)

    def test_observation_completion_and_safety_markers_are_fail_closed(self):
        required = (
            "ENTRANCE_MEDIA_OBSERVATION_STARTED=true",
            "ENTRANCE_MEDIA_OBSERVATION_RESULT=PASS",
            "ENTRANCE_MEDIA_OBSERVATION_WINDOW_MS=3000",
            "ENTRANCE_MEDIA_OBSERVATION_DEVICE_VIDEO_ACK_SENT=false",
            "ENTRANCE_MEDIA_OBSERVATION_PAYLOAD_STORED=false",
            "ENTRANCE_MEDIA_OBSERVATION_PAYLOAD_EMITTED=false",
            "ENTRANCE_RTP_H264_INSPECTION_PERFORMED=false",
            "FINAL_DEVICE_VIDEO_ACK_SENT=false",
            "MEDIA_PAYLOAD_CAPTURED=false",
            "DOOR_ACTION_SENT=false",
            "V4_DOOR_RESULT=",
        )
        for marker in required:
            self.assertIn(marker, self.launcher)

        forbidden_true = (
            "ENTRANCE_MEDIA_OBSERVATION_PAYLOAD_STORED=true",
            "ENTRANCE_MEDIA_OBSERVATION_PAYLOAD_EMITTED=true",
            "ENTRANCE_MEDIA_PAYLOAD_CAPTURED=true",
            "ENTRANCE_RTP_H264_INSPECTION_PERFORMED=true",
            "FINAL_DEVICE_VIDEO_ACK_SENT=true",
        )
        for marker in forbidden_true:
            self.assertIn(marker, self.launcher)

        self.assertIn('FORBIDDEN_TRUE_MARKER_COUNT=$forbidden_true', self.launcher)
        self.assertIn('CT120_ENTRANCE_MEDIA_OBSERVATION_LAUNCH=$final_gate', self.launcher)

    def test_metadata_values_accept_zero_but_must_be_numeric(self):
        self.assertIn("OBSERVATION_EVENTS=$events", self.launcher)
        self.assertIn("OBSERVATION_BYTES=$bytes", self.launcher)
        self.assertIn("OBSERVATION_MAX_CHUNK=$max_chunk", self.launcher)
        self.assertIn('[[ "$events" =~ ^[0-9]+$ ]]', self.launcher)
        self.assertIn('[[ "$bytes" =~ ^[0-9]+$ ]]', self.launcher)
        self.assertIn('[[ "$max_chunk" =~ ^[0-9]+$ ]]', self.launcher)
        self.assertNotIn('"$bytes" -gt 0', self.launcher)

    def test_pinned_transform_preserves_no_ack_no_payload_and_graceful_close(self):
        for marker in (
            "ENTRANCE_MEDIA_OBSERVATION_DEVICE_VIDEO_ACK_SENT=false",
            "ENTRANCE_MEDIA_OBSERVATION_PAYLOAD_STORED=false",
            "ENTRANCE_MEDIA_OBSERVATION_PAYLOAD_EMITTED=false",
            "ENTRANCE_MEDIA_PAYLOAD_CAPTURED=false",
            "ENTRANCE_RTP_H264_INSPECTION_PERFORMED=false",
            "pseudo_tcp_socket_close(pseudo_tcp, FALSE);",
            "PSEUDOTCP_GRACEFUL_CLOSE_FORCE=false",
            "PSEUDOTCP_GRACEFUL_CLOSE_FORCE_RST_SENT=false",
        ):
            self.assertIn(marker, self.transform)

        self.assertNotIn("pseudo_tcp_socket_close(pseudo_tcp, TRUE);", self.transform)


if __name__ == "__main__":
    unittest.main()
