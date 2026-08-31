from pathlib import Path
import unittest


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "deploy"
    / "install_p13_production_release.sh"
)


class P13ProductionReleaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = SCRIPT.read_text(encoding="utf-8")

    def test_release_is_git_and_runtime_identity_bound(self):
        self.assertIn("git -C \"$REPO_ROOT\" archive HEAD:safety-poc", self.text)
        self.assertIn(
            "EXPECTED_HOLDER_SHA="
            "50c0a916f73ec810f131be1f48f47761"
            "a2cc69b9d06107d121519f97c538b450",
            self.text,
        )
        self.assertIn(
            "EXPECTED_WRAPPER_SHA="
            "bf36b381f4921871f0b4df0820548b8"
            "943b935f1dfcd1521ceb79001dab71aa9",
            self.text,
        )
        self.assertIn(
            "EXPECTED_PAYLOAD_SHA="
            "0d0159f9cc562c1c67bc362b192a30d3"
            "fabd634b2b92c3a96d8f318ecd842832",
            self.text,
        )

    def test_release_content_is_hashed_before_and_after_promotion(self):
        self.assertGreaterEqual(
            self.text.count("sha256sum -c RELEASE_CONTENT.sha256"),
            2,
        )
        self.assertIn('ln -sfn "$RELEASE" "$CURRENT"', self.text)
        self.assertIn('ln -sfn "$OLD_CURRENT" "$PREVIOUS"', self.text)

    def test_first_install_handles_absent_current_selector(self):
        self.assertIn(
            'if [[ -L "$CURRENT" ]]; then',
            self.text,
        )
        self.assertIn(
            "P13_PRODUCTION_FIRST_INSTALL=true",
            self.text,
        )
        self.assertIn(
            "P13_PRODUCTION_CURRENT_NOT_SYMLINK=true",
            self.text,
        )
        self.assertIn(
            "P13_PRODUCTION_OLD_CURRENT_TARGET=FAIL",
            self.text,
        )

    def test_poc_dispatch_is_archived_and_replaced_by_deny_only_dispatch(self):
        self.assertIn(
            "RETIRED=\"$PROD_ROOT/retired\"",
            self.text,
        )
        self.assertIn(
            "p13_production_runtime_dispatch.sh",
            self.text,
        )
        self.assertIn(
            "P13_PRODUCTION_OBSERVED_OPEN_RETIRED=true",
            self.text,
        )

    def test_install_is_non_actuating(self):
        self.assertIn(
            "P13_PRODUCTION_INSTALL_NON_ACTUATING=true",
            self.text,
        )
        self.assertIn(
            "P13_COMELIT_NETWORK_ACTION_PERFORMED=false",
            self.text,
        )
        self.assertIn(
            "PHYSICAL_DOOR_ACTION=false",
            self.text,
        )
        self.assertIn(
            "SEND_ARMED_REACHED=false",
            self.text,
        )

        for forbidden in (
            "systemctl start",
            "open_door",
            "p13_one_shot_physical_runner.sh",
            "comelit-p13-observed-open",
        ):
            self.assertNotIn(forbidden, self.text)

    def test_failed_promotion_restores_dispatch_and_current(self):
        self.assertIn("install -m 755", self.text)
        self.assertIn('"$OLD_DISPATCH_BACKUP" "$DISPATCH_DEST"', self.text)
        self.assertIn('ln -sfn "$OLD_CURRENT" "$CURRENT"', self.text)
        self.assertIn("P13_PRODUCTION_INSTALL=FAIL", self.text)


if __name__ == "__main__":
    unittest.main()
