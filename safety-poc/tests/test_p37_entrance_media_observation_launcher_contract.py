from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[2]
MEDIA_DIR = ROOT / "safety-poc/research/media/v1"
RUNNER = MEDIA_DIR / "ct120_run_entrance_self_activation_signaling_probe.sh"
LAUNCHER = MEDIA_DIR / "ct120_launch_entrance_media_observation_probe_v1.sh"


class P37EntranceMediaObservationLauncherContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runner = RUNNER.read_text(encoding="utf-8")
        cls.launcher = LAUNCHER.read_text(encoding="utf-8")

    def test_launcher_parses_as_bash_without_execution(self):
        result = subprocess.run(
            ["bash", "-n", str(LAUNCHER)],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_provenance_pins_full_transform_chain_and_frozen_source(self):
        required = (
            "BASE_RUNNER_BLOB=399db88970197d63f424262cfbde38d9253d816a",
            "SOURCE_EXPECTED_BLOB=c6bdfc17edbfb58d6d87c0c6e9dd58082752734b",
            "OBS_TRANSFORM_EXPECTED_BLOB=85a66b95d4f2ed633f978901fc9041d4a5999531",
            "SIGNAL_TRANSFORM_EXPECTED_BLOB=b8cdb7fc70b3475ad5b6a0cb0077ef0430f95f30",
            "PRESTART_TRANSFORM_EXPECTED_BLOB=7b1b79706abb9c2273bfa42c83760fade7b823c8",
            "PROVENANCE_GATE=PASS",
        )
        for marker in required:
            self.assertIn(marker, self.launcher)

        for gate in (
            "LAUNCHER_BASE_RUNNER_BLOB_GATE=FAIL",
            "LAUNCHER_SOURCE_BLOB_GATE=FAIL",
            "LAUNCHER_OBS_TRANSFORM_BLOB_GATE=FAIL",
            "LAUNCHER_SIGNAL_TRANSFORM_BLOB_GATE=FAIL",
            "LAUNCHER_PRESTART_TRANSFORM_BLOB_GATE=FAIL",
        ):
            self.assertIn(gate, self.launcher)

    def test_launcher_patch_matches_exact_reviewed_p30_runner(self):
        old_transform = (
            "TRANSFORM_REL=safety-poc/research/media/v1/"
            "entrance_self_activation_signaling_transform.py"
        )
        new_transform = (
            "TRANSFORM_REL=safety-poc/research/media/v1/"
            "entrance_media_observation_transform.py"
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

    def test_underlying_runner_remains_exactly_once_and_restores_listener(self):
        for marker in (
            "LIVE_INVOCATIONS=1",
            "ENTRANCE_SIGNALING_LIVE_INVOCATION_LIMIT=1",
            "ENTRANCE_SIGNALING_AUTO_RETRY=false",
            "AUTOMATIC_RETRY=false",
            "restore_listener()",
            "trap on_exit EXIT",
            "LISTENER_RESTORE_READY=PASS",
            "HOME_ASSISTANT_CORE_STOPPED=false",
            "HOME_ASSISTANT_CORE_RESTARTED=false",
            "DOOR_ACTION_SENT=false",
        ):
            self.assertIn(marker, self.runner)

        self.assertEqual(
            self.runner.count(
                'timeout --signal=TERM --kill-after=5s 75s "$CANDIDATE_WRAPPER"'
            ),
            1,
        )

    def test_launcher_itself_invokes_only_the_patched_runner_once(self):
        self.assertEqual(
            self.launcher.count('"$PATCHED_RUNNER" > "$DETAIL_LOG" 2>&1'),
            1,
        )
        self.assertNotIn('"$CANDIDATE_WRAPPER"', self.launcher)
        self.assertNotIn("curl \\", self.launcher)
        self.assertIn("AUTOMATIC_RETRY=false", self.launcher)

    def test_summary_requires_observation_and_negative_safety_invariants(self):
        required = (
            "MEDIA_OBSERVATION_STARTED_COUNT=$obs_started",
            "MEDIA_OBSERVATION_RESULT_COUNT=$obs_result",
            "MEDIA_OBSERVATION_EVENTS=$obs_events",
            "MEDIA_OBSERVATION_BYTES=$obs_bytes",
            "MEDIA_OBSERVATION_MAX_CHUNK=$obs_max",
            "MEDIA_OBSERVATION_WINDOW_MS=$obs_window",
            "MEDIA_OBSERVATION_PAYLOAD_STORED=$payload_stored",
            "MEDIA_OBSERVATION_PAYLOAD_EMITTED=$payload_emitted",
            "RTP_H264_INSPECTION_PERFORMED=$rtp_inspection",
            "FINAL_DEVICE_VIDEO_ACK_SENT=$final_ack",
            "MEDIA_PAYLOAD_CAPTURED=$media_capture",
            '"$obs_window" = 3000',
            '"$payload_stored" = false',
            '"$payload_emitted" = false',
            '"$rtp_inspection" = false',
            '"$final_ack" = false',
            '"$media_capture" = false',
            '"$listener_after" = PASS',
        )
        for marker in required:
            self.assertIn(marker, self.launcher)

        # Observation completion is required, but non-zero media bytes are not:
        # zero bytes is a valid diagnostic result at this stage.
        self.assertIn('"$obs_started" -eq 1', self.launcher)
        self.assertIn('"$obs_result" -eq 1', self.launcher)
        self.assertNotIn('"$obs_bytes" -gt 0', self.launcher)
        self.assertNotIn('"$obs_events" -gt 0', self.launcher)

    def test_compact_summary_is_a_real_exit_gate(self):
        self.assertIn(
            "grep -Fxq 'CT120_ENTRANCE_MEDIA_OBSERVATION_LAUNCH=PASS' \"$SUMMARY_FILE\"",
            self.launcher,
        )
        self.assertIn('if [ "$final_rc" -eq 0 ]; then', self.launcher)
        self.assertIn("final_rc=1", self.launcher)
        self.assertIn("trap - EXIT", self.launcher)
        self.assertIn('exit "$final_rc"', self.launcher)


if __name__ == "__main__":
    unittest.main()
