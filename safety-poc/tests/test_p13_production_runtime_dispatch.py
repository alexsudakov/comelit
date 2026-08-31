from pathlib import Path
import unittest


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "deploy"
    / "p13_production_runtime_dispatch.sh"
)


class P13ProductionRuntimeDispatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = SCRIPT.read_text(encoding="utf-8")

    def test_readiness_uses_immutable_release_not_git_worktree(self):
        self.assertIn(
            "PROD_ROOT=/opt/comelit-door-safety-poc/p13",
            self.text,
        )
        self.assertIn(
            "sha256sum -c RELEASE_CONTENT.sha256",
            self.text,
        )
        self.assertNotIn("/root/comelit-git", self.text)
        self.assertNotIn("git -C", self.text)

    def test_proven_runtime_artifacts_are_hash_verified(self):
        self.assertIn(
            "P13_PRODUCTION_RUNTIME_ARTIFACT_IDENTITIES=PASS",
            self.text,
        )
        self.assertIn('sha256sum "$HOLDER"', self.text)
        self.assertIn('sha256sum "$WRAPPER"', self.text)
        self.assertIn('sha256sum "$PAYLOAD"', self.text)

    def test_observed_open_is_terminally_retired(self):
        self.assertIn("observed-open)", self.text)
        self.assertIn(
            "P13_PRODUCTION_OBSERVED_OPEN_RETIRED=true",
            self.text,
        )
        self.assertIn("P13_RESEND_ALLOWED=false", self.text)
        self.assertIn("exit 126", self.text)

        for forbidden in (
            "p13_hermes_observed_acceptance",
            "p13_one_shot_physical_runner",
            "p13_hermes_one_shot",
            'bash "$GATE"',
        ):
            self.assertNotIn(forbidden, self.text)

    def test_dispatch_has_no_physical_effect_claim(self):
        self.assertIn(
            "P13_PHYSICAL_EFFECT_ASSERTED=false",
            self.text,
        )
        self.assertIn(
            "P13_PRODUCTION_LIVE_COMMAND_EXPOSED=false",
            self.text,
        )
        self.assertIn(
            "PHYSICAL_DOOR_ACTION=false",
            self.text,
        )


if __name__ == "__main__":
    unittest.main()
