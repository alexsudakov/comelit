from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = (
    ROOT
    / "safety-poc/research/media/v1/ct120_run_listener_isolated_pseudotcp_open_probe.sh"
)


class P23ListenerIsolatedPseudoTcpProbeContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = SCRIPT.read_text(encoding="utf-8")

    def test_exact_ct120_and_ha_test_control_boundary(self):
        self.assertIn("CT120_IP=192.168.1.85", self.text)
        self.assertIn(
            "HA_WEBHOOK_URL=http://192.168.1.108:8123/api/webhook/"
            "comelit-ha-ring-test-control-v1",
            self.text,
        )
        self.assertIn('post_control status "$STATUS_BEFORE" 10', self.text)
        self.assertIn('post_control stop "$STOP_RESPONSE" 20', self.text)
        self.assertIn("restore_listener", self.text)

    def test_listener_must_be_ready_before_stop(self):
        for required in (
            'json_scalar "$file" supervisor_running',
            'json_scalar "$file" running',
            'json_scalar "$file" listener_ready',
            'json_scalar "$file" last_error',
            'LISTENER_READY_BEFORE=PASS',
            'LISTENER_STOP_GATE=PASS',
        ):
            self.assertIn(required, self.text)

    def test_only_listener_is_stopped_not_home_assistant_core(self):
        for forbidden in (
            "ha core stop",
            "ha core restart",
            "systemctl restart home-assistant",
            "docker restart",
            "supervisor restart",
        ):
            self.assertNotIn(forbidden, self.text.lower())
        self.assertIn('echo "HOME_ASSISTANT_CORE_STOPPED=false"', self.text)
        self.assertIn('echo "HOME_ASSISTANT_CORE_RESTARTED=false"', self.text)

    def test_transport_probe_is_invoked_exactly_once_in_script(self):
        self.assertEqual(self.text.count('bash "$PROBE_RUNNER" 2>&1 | tee "$PROBE_LOG"'), 1)
        self.assertIn('echo "PROBE_LIVE_INVOCATION_LIMIT=1"', self.text)
        self.assertIn('echo "PROBE_AUTO_RETRY=false"', self.text)
        self.assertIn('PROBE_LIVE_INVOCATIONS=1', self.text)

    def test_application_actions_remain_forbidden(self):
        for required in (
            'echo "PROBE_DOOR_ACTION_ALLOWED=false"',
            'echo "PROBE_SELF_ACTIVATION_ALLOWED=false"',
            'echo "PROBE_MEDIA_SIGNALING_ALLOWED=false"',
            'echo "DOOR_ACTION_SENT=false"',
            'echo "SELF_ACTIVATION_SENT=false"',
            'echo "MEDIA_SIGNALING_SENT=false"',
        ):
            self.assertIn(required, self.text)

        for forbidden in (
            "button.press",
            "SIGUSR1",
            "open_door",
            "V4_DOOR_RESULT=ACKED",
        ):
            self.assertNotIn(forbidden, self.text)

    def test_exit_guard_restores_listener(self):
        self.assertIn("trap on_exit EXIT", self.text)
        self.assertIn("if [ \"$LISTENER_STOPPED\" -eq 1 ]; then", self.text)
        self.assertIn("LISTENER_RESTORE_FINAL_GATE=FAIL", self.text)
        self.assertIn("exit 90", self.text)

    def test_comparison_has_three_explicit_outcomes(self):
        self.assertIn("CONCURRENT_LISTENER_HYPOTHESIS=SUPPORTED", self.text)
        self.assertIn(
            "CONCURRENT_LISTENER_HYPOTHESIS=NOT_SUPPORTED_BY_THIS_RUN",
            self.text,
        )
        self.assertIn("CONCURRENT_LISTENER_HYPOTHESIS=INCONCLUSIVE", self.text)


if __name__ == "__main__":
    unittest.main()
