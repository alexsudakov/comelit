import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RUNNER = (
    ROOT
    / "safety-poc/research/media/v1"
    / "ct120_run_pseudotcp_open_probe.sh"
)


class P20Ct120PseudoTcpOpenRunnerContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = RUNNER.read_text(encoding="utf-8")

    def test_shell_syntax(self):
        subprocess.run(["bash", "-n", str(RUNNER)], check=True)

    def test_runner_is_bound_to_merged_open_probe_research(self):
        self.assertIn(
            "REQUIRED_ANCESTOR=33649c16b6a6bf646d7735b4d3796f5fc1bd222d",
            self.text,
        )
        self.assertIn("git -C \"$REPO\" merge-base --is-ancestor", self.text)
        self.assertIn(
            "pseudotcp_open_probe_transform.py",
            self.text,
        )
        self.assertIn(
            "comelit-v4-persistent-ctpp-door.c",
            self.text,
        )

    def test_runner_never_embeds_or_fetches_github_credentials(self):
        self.assertNotIn("github.com", self.text)
        self.assertNotIn("api.github.com", self.text)
        self.assertNotIn("git fetch", self.text)
        self.assertNotIn("GITHUB_TOKEN", self.text)
        self.assertNotIn(".github-token", self.text)
        self.assertNotIn("credential.helper", self.text)

    def test_historical_wrapper_is_hash_pinned_and_never_modified(self):
        self.assertIn(
            "BASE_WRAPPER_SHA256=a564535dff0cf10b1fe4766171f2960c52fb581f1c816cf81d2992c5c84e79c9",
            self.text,
        )
        self.assertIn('source.read_text(encoding="utf-8")', self.text)
        self.assertIn("out.write_text", self.text)
        self.assertNotIn('> "$BASE_WRAPPER"', self.text)
        self.assertNotIn('chmod 700 "$BASE_WRAPPER"', self.text)

    def test_secret_material_is_not_printed_or_sourced_by_runner(self):
        self.assertIn("CT120_OPEN_PROBE_SECRETS_CONTENT_EMITTED=false", self.text)
        self.assertNotIn('cat "$SECRETS_FILE"', self.text)
        self.assertNotIn('source "$SECRETS_FILE"', self.text)
        self.assertNotIn('. "$SECRETS_FILE"', self.text)

    def test_exactly_one_network_capable_wrapper_invocation(self):
        invocation = (
            'timeout --signal=TERM --kill-after=5s 90s '
            '"$CANDIDATE_WRAPPER" 2>&1 | tee "$LOG"'
        )
        self.assertEqual(self.text.count(invocation), 1)
        self.assertIn("CT120_PSEUDOTCP_OPEN_LIVE_INVOCATION_LIMIT=1", self.text)
        self.assertIn("CT120_PSEUDOTCP_OPEN_LIVE_INVOCATIONS=1", self.text)
        self.assertIn("CT120_PSEUDOTCP_OPEN_AUTO_RETRY=false", self.text)
        self.assertNotIn("while true", self.text.lower())

    def test_preflight_occurs_before_live_invocation(self):
        preflight = self.text.index('echo "CT120_PSEUDOTCP_OPEN_PREFLIGHT=PASS"')
        live = self.text.index(
            'timeout --signal=TERM --kill-after=5s 90s "$CANDIDATE_WRAPPER"'
        )
        self.assertLess(preflight, live)
        self.assertIn("CT120_OPEN_PROBE_BUILD_RC=$BUILD_RC", self.text)
        self.assertIn("CT120_OPEN_PROBE_DOOR_SIGNAL_GATE=PASS", self.text)
        self.assertIn("CT120_OPEN_PROBE_LONG_TIMEOUT_GATE=PASS", self.text)
        self.assertIn(
            "grep -Fq 'signal(SIGUSR1, v4_door_signal_handler);'",
            self.text,
        )

    def test_live_gate_requires_transport_proof_and_safety_markers(self):
        for marker in (
            "PSEUDOTCP_OPEN=PASS",
            "PSEUDOTCP_OPEN_PROBE_RESULT=PASS",
            "PSEUDOTCP_OPEN_PROBE_APP_SIGNALING_SENT=false",
            "PSEUDOTCP_OPEN_PROBE_SELF_ACTIVATION_SENT=false",
            "PSEUDOTCP_OPEN_PROBE_MEDIA_SIGNALING_SENT=false",
            "PSEUDOTCP_OPEN_PROBE_DOOR_ACTION_SENT=false",
        ):
            self.assertIn(marker, self.text)
        self.assertIn("CT120_PSEUDOTCP_OPEN_GATE=$GATE", self.text)

    def test_runner_does_not_manage_home_assistant_or_actuate_door(self):
        for forbidden in (
            "ha core",
            "hassio",
            "/config/custom_components",
            "button.press",
            "kill -USR1",
            "rsync",
            "scp ",
            "ssh ",
        ):
            self.assertNotIn(forbidden, self.text)

        self.assertIn("DOOR_ACTION_SENT=false", self.text)
        self.assertIn("SELF_ACTIVATION_SENT=false", self.text)
        self.assertIn("MEDIA_SIGNALING_SENT=false", self.text)

    def test_runner_keeps_evidence_and_cleans_only_detached_worktree(self):
        self.assertIn('RUN_ROOT="/root/comelit-media-open-probe-$STAMP"', self.text)
        self.assertIn('MANIFEST="$RUN_ROOT/MANIFEST.txt"', self.text)
        self.assertIn('LOG="$RUN_ROOT/live.log"', self.text)
        self.assertIn('worktree remove --force "$WT"', self.text)
        self.assertNotIn('rm -rf "$RUN_ROOT"', self.text)


if __name__ == "__main__":
    unittest.main()
