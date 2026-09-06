from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / (
    "safety-poc/research/media/v1/ct120_run_entrance_self_activation_signaling_probe.sh"
)
LAUNCHER = ROOT / (
    "safety-poc/research/media/v1/ct120_launch_entrance_media_structural_classifier_probe_v1.sh"
)
CLASSIFIER = ROOT / (
    "safety-poc/research/media/v1/entrance_media_structural_classifier_transform.py"
)


class P41EntranceMediaStructuralClassifierLauncherContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runner = RUNNER.read_text(encoding="utf-8")
        cls.launcher = LAUNCHER.read_text(encoding="utf-8")
        cls.classifier = CLASSIFIER.read_text(encoding="utf-8")

    def test_provenance_pins_runner_source_and_full_transform_chain(self):
        for marker in (
            "BASE_RUNNER_BLOB=399db88970197d63f424262cfbde38d9253d816a",
            "SOURCE_EXPECTED_BLOB=c6bdfc17edbfb58d6d87c0c6e9dd58082752734b",
            "CLASSIFIER_TRANSFORM_EXPECTED_BLOB=0aed2ca1152a0a0403b023e5efa6d5021a9bfff6",
            "OBS_TRANSFORM_EXPECTED_BLOB=85a66b95d4f2ed633f978901fc9041d4a5999531",
            "SIGNAL_TRANSFORM_EXPECTED_BLOB=b8cdb7fc70b3475ad5b6a0cb0077ef0430f95f30",
            "PRESTART_TRANSFORM_EXPECTED_BLOB=7b1b79706abb9c2273bfa42c83760fade7b823c8",
            "LAUNCHER_BASE_RUNNER_BLOB_GATE=FAIL",
            "LAUNCHER_SOURCE_BLOB_GATE=FAIL",
            "LAUNCHER_CLASSIFIER_TRANSFORM_BLOB_GATE=FAIL",
            "LAUNCHER_OBS_TRANSFORM_BLOB_GATE=FAIL",
            "LAUNCHER_SIGNAL_TRANSFORM_BLOB_GATE=FAIL",
            "LAUNCHER_PRESTART_TRANSFORM_BLOB_GATE=FAIL",
        ):
            self.assertIn(marker, self.launcher)

    def test_patch_anchors_match_exact_reviewed_p30_runner(self):
        old_transform = (
            "TRANSFORM_REL=safety-poc/research/media/v1/"
            "entrance_self_activation_signaling_transform.py"
        )
        new_transform = (
            "TRANSFORM_REL=safety-poc/research/media/v1/"
            "entrance_media_structural_classifier_transform.py"
        )
        old_timer = (
            "if grep -Fq $'        100,\\n        v4_door_tick_cb,' "
            '"$CANDIDATE_SOURCE"; then'
        )
        new_timer = (
            "if grep -Fq '        v4_door_tick_cb,' "
            '"$CANDIDATE_SOURCE"; then'
        )
        old_live_gate = '''    if [ "$COUNT" -ne 1 ]; then
        LIVE_GATE=FAIL
    fi
done
'''
        new_live_gate = '''    if [ "$marker" = 'ENTRANCE_SIGNALING_DOOR_ACTION_SENT=false' ]; then
        if [ "$COUNT" -lt 1 ]; then
            LIVE_GATE=FAIL
        fi
    elif [ "$COUNT" -ne 1 ]; then
        LIVE_GATE=FAIL
    fi
done
'''

        self.assertEqual(self.runner.count(old_transform), 1)
        self.assertEqual(self.runner.count(old_timer), 1)
        self.assertEqual(self.runner.count(old_live_gate), 1)

        patched = self.runner.replace(old_transform, new_transform, 1)
        patched = patched.replace(old_timer, new_timer, 1)
        patched = patched.replace(old_live_gate, new_live_gate, 1)

        self.assertNotIn(old_transform, patched)
        self.assertEqual(patched.count(new_transform), 1)
        self.assertNotIn(old_timer, patched)
        self.assertEqual(patched.count(new_timer), 1)
        self.assertNotIn(old_live_gate, patched)
        self.assertEqual(patched.count(new_live_gate), 1)

    def test_launcher_invokes_reviewed_runner_exactly_once_without_retry(self):
        invocation = '"$PATCHED_RUNNER" > "$DETAIL_LOG" 2>&1'
        self.assertEqual(self.launcher.count(invocation), 1)
        self.assertIn("AUTOMATIC_RETRY=false", self.launcher)
        self.assertIn("Exactly one runner invocation", self.launcher)
        self.assertNotIn("for attempt in", self.launcher)
        self.assertNotIn("while true", self.launcher)

    def test_summary_requires_complete_signaling_observation_and_listener_restore(self):
        for marker in (
            'preflight="$(last_value \'ENTRANCE_SIGNALING_PREFLIGHT=\' \'NOT_REACHED\')"',
            'live_invocations="$(last_value \'LIVE_INVOCATIONS=\' \'0\')"',
            'open_count="$(count_exact \'PSEUDOTCP_OPEN=PASS\')"',
            'reg_count="$(count_exact \'V4_CTPP_REGISTRATION=PASS\')"',
            'self_sent="$(count_exact \'ENTRANCE_SELF_ACTIVATION_SENT=PASS\')"',
            'self_ack="$(count_exact \'ENTRANCE_SELF_ACTIVATION_ACK=PASS\')"',
            'video_sent="$(count_exact \'ENTRANCE_VIDEO_EVENT_SENT=PASS\')"',
            'video_ack="$(count_exact \'ENTRANCE_VIDEO_EVENT_ACK=PASS\')"',
            'device_video="$(count_exact \'ENTRANCE_DEVICE_VIDEO_EVENT=PASS\')"',
            'obs_result="$(count_exact \'ENTRANCE_MEDIA_OBSERVATION_RESULT=PASS\')"',
            '[ "$listener_after" = PASS ]',
            "CT120_ENTRANCE_MEDIA_STRUCTURAL_LAUNCH=PASS",
        ):
            self.assertIn(marker, self.launcher)

    def test_structural_result_gate_is_bounded_and_fail_closed(self):
        for marker in (
            "ENTRANCE_MEDIA_STRUCT_FRAMES=",
            "ENTRANCE_MEDIA_STRUCT_CTPP_FRAMES=",
            "ENTRANCE_MEDIA_STRUCT_OTHER_FRAMES=",
            "ENTRANCE_MEDIA_STRUCT_MALFORMED=",
            "ENTRANCE_MEDIA_STRUCT_TAIL_BYTES=",
            "ENTRANCE_MEDIA_STRUCT_RAW_PAYLOAD_EMITTED=",
            "ENTRANCE_MEDIA_STRUCT_HEX_EMITTED=",
            "ENTRANCE_MEDIA_STRUCT_BASE64_EMITTED=",
            '[ "$struct_malformed" -eq 0 ]',
            '[ "$struct_frame_lines" -eq "$struct_frames" ]',
            '[ "$struct_raw" = false ]',
            '[ "$struct_hex" = false ]',
            '[ "$struct_base64" = false ]',
        ):
            self.assertIn(marker, self.launcher)

        self.assertIn("is_uint()", self.launcher)
        self.assertIn("is_uint \"$struct_frames\"", self.launcher)
        self.assertIn("is_uint \"$struct_tail\"", self.launcher)

    def test_compact_terminal_output_contains_only_structural_frame_metadata(self):
        self.assertIn(
            "grep -F 'ENTRANCE_MEDIA_STRUCT_FRAME=' \"$DETAIL_LOG\"",
            self.launcher,
        )
        self.assertNotIn('cat "$DETAIL_LOG"', self.launcher)
        self.assertIn("STRUCTURAL FRAME METADATA", self.launcher)

    def test_no_ack_payload_or_door_boundary_is_relaxed(self):
        for marker in (
            '[ "$door_result_count" -eq 0 ]',
            '[ "$door_action" = false ]',
            '[ "$final_ack" = false ]',
            '[ "$media_capture" = false ]',
            '[ "$rtp_inspection" = false ]',
            'PSEUDOTCP_GRACEFUL_CLOSE_FORCE=false',
        ):
            self.assertIn(marker, self.launcher)

        for forbidden in (
            "FINAL_DEVICE_VIDEO_ACK_SENT=true",
            "MEDIA_PAYLOAD_CAPTURED=true",
            "RTP_H264_INSPECTION_PERFORMED=true",
            "STRUCT_RAW_PAYLOAD_EMITTED=true",
            "STRUCT_HEX_EMITTED=true",
            "STRUCT_BASE64_EMITTED=true",
        ):
            self.assertNotIn(forbidden, self.launcher)

    def test_classifier_dependency_remains_structural_only(self):
        for marker in (
            "#define ENTRANCE_MEDIA_CLASSIFIER_MAX 512",
            "ENTRANCE_MEDIA_STRUCT_RAW_PAYLOAD_EMITTED=false",
            "ENTRANCE_MEDIA_STRUCT_HEX_EMITTED=false",
            "ENTRANCE_MEDIA_STRUCT_BASE64_EMITTED=false",
            "ENTRANCE_FINAL_DEVICE_VIDEO_ACK_SENT=false",
            "ENTRANCE_RTP_H264_INSPECTION_PERFORMED=false",
        ):
            self.assertIn(marker, self.classifier)


if __name__ == "__main__":
    unittest.main()
