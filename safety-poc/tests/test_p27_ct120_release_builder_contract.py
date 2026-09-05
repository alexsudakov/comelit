from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = (
    ROOT
    / "safety-poc/research/media/v1"
    / "ct120_prepare_hacs_graceful_stop_v1_5_5.sh"
)


class P27Ct120ReleaseBuilderContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = SCRIPT.read_text(encoding="utf-8")

    def test_release_is_pinned_to_reviewed_base_and_branch(self):
        self.assertIn(
            "BASE_MAIN=7c3ce946aca267bdc2a41423a6a4130cf09c1754",
            self.text,
        )
        self.assertIn(
            "BRANCH=fix/graceful-pseudotcp-stop-v1-5-5",
            self.text,
        )
        self.assertIn('REMOTE_BRANCH != "$RELEASE_SEED_SHA"', self.text)
        self.assertIn("V155_RELEASE_BRANCH_SEED_IDENTITY=PASS", self.text)

    def test_github_fetch_push_boundary_is_token_only(self):
        self.assertIn("GIT_TERMINAL_PROMPT=0", self.text)
        self.assertIn("-c credential.helper=", self.text)
        self.assertIn(
            '-c "credential.helper=store --file=$CREDS"',
            self.text,
        )
        self.assertIn("-c credential.useHttpPath=true", self.text)
        self.assertIn('push origin "HEAD:refs/heads/$BRANCH"', self.text)
        self.assertNotIn("https://$", self.text)
        self.assertNotIn("Authorization:", self.text)

    def test_builder_only_transforms_frozen_native_source(self):
        self.assertIn(
            "SOURCE_REL=safety-poc/research/door/v1_5_3/"
            "comelit-v4-persistent-ctpp-door.c",
            self.text,
        )
        self.assertIn(
            "TRANSFORM_REL=safety-poc/research/media/v1/"
            "pseudotcp_graceful_stop_transform.py",
            self.text,
        )
        self.assertIn(
            "RELEASE_SOURCE_REL=$RELEASE_DIR_REL/"
            "comelit-v4-persistent-ctpp-door.c",
            self.text,
        )
        self.assertIn("V155_RELEASE_FROZEN_SOURCE_GATE=PASS", self.text)
        self.assertIn("V155_RELEASE_FROZEN_BINARY_GATE=PASS", self.text)

    def test_candidate_is_compiled_but_never_executed(self):
        self.assertIn('cc \\\n      -O2', self.text)
        self.assertIn('cp "$CANDIDATE_BINARY" "$BINARY"', self.text)
        self.assertNotIn('"$CANDIDATE_BINARY" 2>&1', self.text)
        self.assertNotIn("timeout --signal", self.text)
        self.assertIn('echo "CANDIDATE_EXECUTED=false"', self.text)

    def test_no_live_comelit_or_home_assistant_action(self):
        for forbidden in (
            "curl ",
            "/api/webhook/",
            "ha core",
            "button.press",
            "SIGUSR1",
            "comelit-p2p-cloud-probe",
        ):
            self.assertNotIn(forbidden, self.text)

        for required in (
            'echo "COMELIT_NETWORK_SESSION_STARTED=false"',
            'echo "HOME_ASSISTANT_TOUCHED=false"',
            'echo "DOOR_ACTION_SENT=false"',
            'echo "SELF_ACTIVATION_SENT=false"',
            'echo "MEDIA_SIGNALING_SENT=false"',
        ):
            self.assertIn(required, self.text)

    def test_release_bumps_manifest_and_freezes_artifact_hashes(self):
        self.assertIn('data["version"] = "1.5.5"', self.text)
        self.assertIn("EXPECTED_SOURCE_SHA = \"$SOURCE_SHA\"", self.text)
        self.assertIn("EXPECTED_BINARY_SHA = \"$BINARY_SHA\"", self.text)
        self.assertIn("release=1.5.5", self.text)
        self.assertIn("binary_sha256=$BINARY_SHA", self.text)
        self.assertIn("source_sha256=$SOURCE_SHA", self.text)

    def test_release_test_proves_exact_transform_and_door_contract(self):
        self.assertIn(
            "test_release_source_is_exact_reviewed_transform_of_frozen_v153",
            self.text,
        )
        self.assertIn(
            'source.count("pseudo_tcp_socket_close(pseudo_tcp, FALSE);")',
            self.text,
        )
        self.assertIn(
            'b"V4_DOOR_OPERATION_WRITES_SENT=5"',
            self.text,
        )
        self.assertIn(
            'b"V4_DOOR_AUTOMATIC_RETRY_ALLOWED=false"',
            self.text,
        )

    def test_only_expected_release_paths_are_staged(self):
        for path_var in (
            "$BINARY_REL",
            "$MANIFEST_REL",
            "$BUILD_INFO_REL",
            "$RELEASE_SOURCE_REL",
            "$RELEASE_TEST_REL",
        ):
            self.assertIn(path_var, self.text)
        self.assertIn("V155_RELEASE_STAGED_PATH_GATE=PASS", self.text)
        self.assertIn("V155_RELEASE_UNTRACKED_PATH_GATE=PASS", self.text)


if __name__ == "__main__":
    unittest.main()
