from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
INNER = ROOT / "safety-poc/research/media/v1/ct120_run_media_vip_bootstrap_probe.sh"
OUTER = ROOT / "safety-poc/research/media/v1/ct120_run_listener_isolated_media_vip_bootstrap.sh"


class P30MediaVipBootstrapRunnerContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inner = INNER.read_text(encoding="utf-8")
        cls.outer = OUTER.read_text(encoding="utf-8")

    def test_inner_is_one_shot_and_has_no_ha_control(self):
        self.assertEqual(
            self.inner.count('timeout --signal=TERM --kill-after=5s 120s "$CANDIDATE_WRAPPER"'),
            1,
        )
        self.assertIn('CT120_MEDIA_BOOTSTRAP_LIVE_INVOCATION_LIMIT=1', self.inner)
        self.assertIn('CT120_MEDIA_BOOTSTRAP_AUTO_RETRY=false', self.inner)
        self.assertNotIn('api/webhook', self.inner)
        self.assertNotIn('button.press', self.inner)

    def test_outer_stops_only_comelit_listener_and_restores(self):
        self.assertIn('comelit-ha-ring-test-control-v1', self.outer)
        self.assertIn('post_control stop "$STOP_RESPONSE" 20', self.outer)
        self.assertIn('restore_listener', self.outer)
        self.assertIn('trap on_exit EXIT', self.outer)
        for forbidden in (
            'ha core stop',
            'ha core restart',
            'docker restart',
            'systemctl restart home-assistant',
        ):
            self.assertNotIn(forbidden, self.outer.lower())

    def test_outer_invokes_inner_exactly_once(self):
        self.assertEqual(self.outer.count('bash "$PROBE_RUNNER" 2>&1 | tee "$PROBE_LOG"'), 1)
        self.assertIn('MEDIA_BOOTSTRAP_LIVE_INVOCATION_LIMIT=1', self.outer)
        self.assertIn('MEDIA_BOOTSTRAP_AUTO_RETRY=false', self.outer)

    def test_no_door_self_activation_or_video_actions(self):
        combined = self.inner + self.outer
        for required in (
            'DOOR_ACTION_SENT=false',
            'SELF_ACTIVATION_SENT=false',
            'MEDIA_SIGNALING_SENT=false',
        ):
            self.assertIn(required, combined)
        for forbidden in (
            'button.press',
            'open_door',
            'V4_DOOR_RESULT=ACKED',
            'SELF_ACTIVATION_SENT=true',
            'VIDEO_EVENT_SENT=true',
        ):
            self.assertNotIn(forbidden, combined)


if __name__ == "__main__":
    unittest.main()
