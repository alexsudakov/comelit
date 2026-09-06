from contextlib import redirect_stdout
import io
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
MEDIA_DIR = ROOT / "safety-poc/research/media/v1"
LAUNCHER = MEDIA_DIR / "ct120_launch_entrance_device_video_ack_observation_probe_v1.sh"
BASE_RUNNER = MEDIA_DIR / "ct120_run_entrance_self_activation_signaling_probe.sh"


class P47EntranceDeviceVideoAckLauncherContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.launcher = LAUNCHER.read_text(encoding="utf-8")
        cls.base_runner = BASE_RUNNER.read_text(encoding="utf-8")

        prefix = 'python3 - "$BASE_RUNNER" "$PATCHED_RUNNER" > "$PATCH_LOG" 2>&1 <<\'PY\'\n'
        suffix = "\nPY\nPATCH_RC=$?"
        start = cls.launcher.index(prefix) + len(prefix)
        end = cls.launcher.index(suffix, start)
        cls.patch_python = cls.launcher[start:end]

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "base.sh"
            output = Path(tmp) / "patched.sh"
            source.write_text(cls.base_runner, encoding="utf-8")

            old_argv = sys.argv
            capture = io.StringIO()
            try:
                sys.argv = ["launcher-patch", str(source), str(output)]
                with redirect_stdout(capture):
                    exec(
                        compile(cls.patch_python, "<p47-launcher-patch>", "exec"),
                        {"__name__": "__main__"},
                    )
            finally:
                sys.argv = old_argv

            cls.patch_output = capture.getvalue()
            cls.patched_runner = output.read_text(encoding="utf-8")

    def test_exact_provenance_pins_are_present(self):
        pins = (
            "BASE_RUNNER_BLOB=399db88970197d63f424262cfbde38d9253d816a",
            "SOURCE_EXPECTED_BLOB=c6bdfc17edbfb58d6d87c0c6e9dd58082752734b",
            "ACK_OBS_TRANSFORM_EXPECTED_BLOB=5a87e2531c2cef0297d8a7e84d75f9d4f2182311",
            "OBS_TRANSFORM_EXPECTED_BLOB=85a66b95d4f2ed633f978901fc9041d4a5999531",
            "SIGNAL_TRANSFORM_EXPECTED_BLOB=b8cdb7fc70b3475ad5b6a0cb0077ef0430f95f30",
            "PRESTART_TRANSFORM_EXPECTED_BLOB=7b1b79706abb9c2273bfa42c83760fade7b823c8",
        )
        for pin in pins:
            self.assertIn(pin, self.launcher)

        for variable in (
            "RUNNER_BLOB",
            "SOURCE_BLOB",
            "ACK_OBS_TRANSFORM_BLOB",
            "OBS_TRANSFORM_BLOB",
            "SIGNAL_TRANSFORM_BLOB",
            "PRESTART_TRANSFORM_BLOB",
        ):
            self.assertIn(variable, self.launcher)

        self.assertIn("PROVENANCE_GATE=PASS", self.launcher)

    def test_real_patch_applies_to_pinned_runner(self):
        self.assertIn("RUNNER_PATCH_GATE=PASS", self.patch_output)
        self.assertIn(
            "RUNNER_TRANSFORM=entrance_device_video_ack_observation_transform.py",
            self.patch_output,
        )
        self.assertIn("RUNNER_FINAL_DEVICE_VIDEO_ACK_ALLOWED=true", self.patch_output)
        self.assertIn("RUNNER_DOOR_INVARIANT_COUNT_POLICY=AT_LEAST_ONE", self.patch_output)
        self.assertIn("RUNNER_AUTOMATIC_RETRY=false", self.patch_output)

        self.assertIn(
            "TRANSFORM_REL=safety-poc/research/media/v1/entrance_device_video_ack_observation_transform.py",
            self.patched_runner,
        )
        self.assertNotIn(
            "TRANSFORM_REL=safety-poc/research/media/v1/entrance_self_activation_signaling_transform.py",
            self.patched_runner,
        )

    def test_preflight_source_and_binary_gates_require_ack_observation_contract(self):
        for marker in (
            "ENTRANCE_DEVICE_VIDEO_ACK_SENT=PASS",
            "ENTRANCE_DEVICE_VIDEO_ACK_SEQUENCE_DELTA_FROM_CLIENT_VIDEO=0x01010000",
            "ENTRANCE_DEVICE_VIDEO_ACK_ADDRESS_ROLE_REVERSAL=true",
            "ENTRANCE_DEVICE_VIDEO_ACK_CTPP_REUSED=true",
            "ENTRANCE_MEDIA_OBSERVATION_STARTED=true",
            "ENTRANCE_MEDIA_OBSERVATION_RESULT=PASS",
            "ENTRANCE_MEDIA_OBSERVATION_PAYLOAD_STORED=false",
            "ENTRANCE_MEDIA_OBSERVATION_PAYLOAD_EMITTED=false",
            "ENTRANCE_RTP_H264_INSPECTION_PERFORMED=false",
            "ENTRANCE_FINAL_DEVICE_VIDEO_ACK_SENT=true",
            "ENTRANCE_MEDIA_PAYLOAD_CAPTURED=false",
            "PSEUDOTCP_GRACEFUL_CLOSE_FORCE=false",
        ):
            self.assertIn(marker, self.patched_runner)

        self.assertNotIn(
            "'ENTRANCE_FINAL_DEVICE_VIDEO_ACK_SENT=false'",
            self.patched_runner,
        )
        self.assertIn(
            'echo "ENTRANCE_SIGNALING_FINAL_DEVICE_VIDEO_ACK_ALLOWED=true"',
            self.patched_runner,
        )
        self.assertIn('echo "FINAL_DEVICE_VIDEO_ACK_SENT=true"', self.patched_runner)

    def test_live_gate_keeps_event_markers_exactly_once_and_door_false_at_least_once(self):
        expected_policy = '''    if [ "$marker" = 'ENTRANCE_SIGNALING_DOOR_ACTION_SENT=false' ]; then
        if [ "$COUNT" -lt 1 ]; then
            LIVE_GATE=FAIL
        fi
    elif [ "$COUNT" -ne 1 ]; then
        LIVE_GATE=FAIL
    fi
'''
        self.assertIn(expected_policy, self.patched_runner)

        for marker in (
            "'ENTRANCE_DEVICE_VIDEO_ACK_SENT=PASS'",
            "'ENTRANCE_MEDIA_OBSERVATION_STARTED=true'",
            "'ENTRANCE_MEDIA_OBSERVATION_RESULT=PASS'",
            "'ENTRANCE_FINAL_DEVICE_VIDEO_ACK_SENT=true'",
        ):
            self.assertIn(marker, self.patched_runner)

    def test_exactly_one_live_wrapper_invocation_and_no_retry(self):
        invocation = 'timeout --signal=TERM --kill-after=5s 75s "$CANDIDATE_WRAPPER"'
        self.assertEqual(self.patched_runner.count(invocation), 1)
        self.assertIn('echo "ENTRANCE_SIGNALING_LIVE_INVOCATION_LIMIT=1"', self.patched_runner)
        self.assertIn('echo "ENTRANCE_SIGNALING_AUTO_RETRY=false"', self.patched_runner)
        self.assertNotIn("for attempt in", self.patched_runner)
        self.assertNotIn("while true", self.patched_runner)

    def test_listener_restore_and_home_assistant_boundaries_are_preserved(self):
        for marker in (
            "trap on_exit EXIT",
            "restore_listener()",
            "LISTENER_RESTORE_READY=PASS",
            "HOME_ASSISTANT_CORE_STOPPED=false",
            "HOME_ASSISTANT_CORE_RESTARTED=false",
        ):
            self.assertIn(marker, self.patched_runner)

        self.assertNotIn("ha core stop", self.patched_runner.lower())
        self.assertNotIn("ha core restart", self.patched_runner.lower())

    def test_outer_summary_is_fail_closed_on_ack_and_metadata_only_observation(self):
        for marker in (
            '[ "$ack_sent" -eq 1 ]',
            '[ "$ack_delta" = 0x01010000 ]',
            '[ "$ack_reversal" = true ]',
            '[ "$ack_ctpp" = true ]',
            '[ "$obs_started" -eq 1 ]',
            '[ "$obs_result" -eq 1 ]',
            '[ "$obs_window" = 3000 ]',
            '[ "$payload_stored" = false ]',
            '[ "$payload_emitted" = false ]',
            '[ "$rtp_inspection" = false ]',
            '[ "$door_result_count" -eq 0 ]',
            '[ "$door_action" = false ]',
            '[ "$final_ack" = true ]',
            '[ "$media_capture" = false ]',
            '[ "$listener_restore" = PASS ]',
            '[ "$listener_after" = PASS ]',
            "CT120_ENTRANCE_DEVICE_VIDEO_ACK_OBSERVATION_LAUNCH=PASS",
        ):
            self.assertIn(marker, self.launcher)

        self.assertIn("AUTOMATIC_RETRY=false", self.launcher)

    def test_launcher_emits_no_payload_content(self):
        for forbidden in (
            "PAYLOAD_HEX",
            "PAYLOAD_BASE64",
            "base64.b64encode",
            "tcpdump",
            "tshark",
        ):
            self.assertNotIn(forbidden, self.launcher)

        for marker in (
            "MEDIA_OBSERVATION_PAYLOAD_STORED=$payload_stored",
            "MEDIA_OBSERVATION_PAYLOAD_EMITTED=$payload_emitted",
            "RTP_H264_INSPECTION_PERFORMED=$rtp_inspection",
        ):
            self.assertIn(marker, self.launcher)


if __name__ == "__main__":
    unittest.main()
