from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "safety-poc/research/media/v1/ct120_run_entrance_self_activation_signaling_probe.sh"


class P30Ct120EntranceSignalingRunnerContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = SCRIPT.read_text(encoding="utf-8")

    def test_exactly_one_network_wrapper_invocation(self):
        invocation = 'timeout --signal=TERM --kill-after=5s 75s "$CANDIDATE_WRAPPER" 2>&1 | tee "$LOG"'
        self.assertEqual(self.text.count(invocation), 1)
        self.assertIn('echo "ENTRANCE_SIGNALING_LIVE_INVOCATION_LIMIT=1"', self.text)
        self.assertIn('echo "ENTRANCE_SIGNALING_AUTO_RETRY=false"', self.text)
        self.assertIn("LIVE_INVOCATIONS=1", self.text)

    def test_listener_is_stopped_and_restored_without_ha_core_restart(self):
        self.assertIn('post_control status "$STATUS_BEFORE" 10', self.text)
        self.assertIn('post_control stop "$STOP_RESPONSE" 20', self.text)
        self.assertIn("restore_listener", self.text)
        self.assertIn("trap on_exit EXIT", self.text)
        self.assertIn('echo "LISTENER_STOP_GATE=PASS"', self.text)
        self.assertIn('echo "LISTENER_RESTORE_READY=PASS"', self.text)
        self.assertIn('echo "HOME_ASSISTANT_CORE_STOPPED=false"', self.text)
        self.assertIn('echo "HOME_ASSISTANT_CORE_RESTARTED=false"', self.text)
        for forbidden in (
            "ha core stop",
            "ha core restart",
            "docker restart",
            "systemctl restart home-assistant",
        ):
            self.assertNotIn(forbidden, self.text.lower())

    def test_door_is_forbidden(self):
        self.assertIn('echo "ENTRANCE_SIGNALING_DOOR_ACTION_ALLOWED=false"', self.text)
        self.assertIn('echo "DOOR_ACTION_SENT=false"', self.text)
        self.assertIn("DOOR_RESULT_COUNT=", self.text)
        for forbidden in (
            "button.press",
            "os.kill",
            "kill -USR1",
            "SIGUSR1",
        ):
            self.assertNotIn(forbidden, self.text)

    def test_live_success_requires_full_signaling_sequence(self):
        for marker in (
            "PSEUDOTCP_OPEN=PASS",
            "V4_CTPP_REGISTRATION=PASS",
            "ENTRANCE_SELF_ACTIVATION_SENT=PASS",
            "ENTRANCE_SELF_ACTIVATION_ACK=PASS",
            "ENTRANCE_VIDEO_EVENT_SENT=PASS",
            "ENTRANCE_VIDEO_EVENT_ACK=PASS",
            "ENTRANCE_DEVICE_VIDEO_EVENT=PASS",
            "ENTRANCE_SIGNALING_PROBE_RESULT=PASS",
        ):
            self.assertIn(marker, self.text)

    def test_stage_deliberately_stops_before_media_capture(self):
        self.assertIn('echo "ENTRANCE_SIGNALING_FINAL_DEVICE_VIDEO_ACK_ALLOWED=false"', self.text)
        self.assertIn('echo "ENTRANCE_SIGNALING_MEDIA_PAYLOAD_CAPTURE_ALLOWED=false"', self.text)
        self.assertIn("ENTRANCE_FINAL_DEVICE_VIDEO_ACK_SENT=false", self.text)
        self.assertIn("ENTRANCE_MEDIA_PAYLOAD_CAPTURED=false", self.text)
        self.assertIn('echo "FINAL_DEVICE_VIDEO_ACK_SENT=false"', self.text)
        self.assertIn('echo "MEDIA_PAYLOAD_CAPTURED=false"', self.text)

    def test_wrapper_and_secret_identity_are_pinned(self):
        self.assertIn("BASE_WRAPPER_SHA256=a564535dff0cf10b1fe4766171f2960c52fb581f1c816cf81d2992c5c84e79c9", self.text)
        self.assertIn("SECRETS_FILE=/root/.config/comelit/secrets.env", self.text)
        self.assertIn("ENTRANCE_SIGNALING_SECRETS_CONTENT_EMITTED=false", self.text)

    def test_candidate_is_built_from_v157_research_source(self):
        self.assertIn("SOURCE_REL=safety-poc/research/door/v1_5_7/comelit-v4-persistent-ctpp-door.c", self.text)
        self.assertIn("entrance_self_activation_signaling_transform.py", self.text)
        self.assertIn("ENTRANCE_SIGNALING_BUILD_RC=", self.text)
        self.assertIn("ENTRANCE_SIGNALING_LONG_TIMEOUT_GATE=PASS", self.text)


if __name__ == "__main__":
    unittest.main()
