from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / (
    "safety-poc/research/media/v1/ct120_run_entrance_self_activation_signaling_probe.sh"
)
LAUNCHER_V3 = ROOT / (
    "safety-poc/research/media/v1/ct120_launch_entrance_self_activation_signaling_probe_v3.sh"
)


class P34EntranceSignalingLiveGateDuplicateInvariant(unittest.TestCase):
    def test_v3_patch_matches_pinned_p30_runner_and_relaxes_only_false_door_invariant(self):
        runner = RUNNER.read_text(encoding="utf-8")
        launcher = LAUNCHER_V3.read_text(encoding="utf-8")

        self.assertIn(
            "BASE_RUNNER_BLOB=399db88970197d63f424262cfbde38d9253d816a",
            launcher,
        )
        self.assertIn("AUTOMATIC_RETRY=false", launcher)

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

        self.assertEqual(runner.count(old_timer), 1)
        self.assertEqual(runner.count(old_live_gate), 1)

        patched = runner.replace(old_timer, new_timer, 1)
        patched = patched.replace(old_live_gate, new_live_gate, 1)

        self.assertNotIn(old_timer, patched)
        self.assertEqual(patched.count(new_timer), 1)
        self.assertNotIn(old_live_gate, patched)
        self.assertEqual(patched.count(new_live_gate), 1)

        # Event markers remain exactly-once. Only the immutable negative Door
        # safety assertion is permitted to repeat, because multiple identical
        # `false` observations do not represent multiple actions.
        self.assertIn(
            "if [ \"$marker\" = 'ENTRANCE_SIGNALING_DOOR_ACTION_SENT=false' ]; then",
            patched,
        )
        self.assertIn('if [ "$COUNT" -lt 1 ]; then', patched)
        self.assertIn('elif [ "$COUNT" -ne 1 ]; then', patched)

        required_event_markers = (
            "ENTRANCE_SELF_ACTIVATION_SENT=PASS",
            "ENTRANCE_SELF_ACTIVATION_ACK=PASS",
            "ENTRANCE_VIDEO_EVENT_SENT=PASS",
            "ENTRANCE_VIDEO_EVENT_ACK=PASS",
            "ENTRANCE_DEVICE_VIDEO_EVENT=PASS",
            "ENTRANCE_SIGNALING_PROBE_RESULT=PASS",
            "PSEUDOTCP_GRACEFUL_CLOSE_FORCE=false",
            "PSEUDOTCP_GRACEFUL_CLOSE_FORCE_RST_SENT=false",
        )
        for marker in required_event_markers:
            self.assertIn(marker, patched)


if __name__ == "__main__":
    unittest.main()
