from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "safety-poc/research/media/v1/ct120_prepare_haos_graceful_stop_v1_5_7_v4.sh"


class P29V4PipefailSymbolGateContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = SCRIPT.read_text(encoding="utf-8")

    def test_v3_blob_is_exactly_pinned(self):
        self.assertIn("V3_BLOB_SHA=e69315c00b41914295a28e635a6af97b6c764635", self.text)
        self.assertIn('git -C "$REPO" rev-parse "$RELEASE_SEED_SHA:$V3_REL"', self.text)
        self.assertIn("V157_V4_V3_BLOB_GATE=PASS", self.text)

    def test_only_known_pipefail_bug_is_patched(self):
        self.assertIn(
            'needle = """if strings -a \\\"$VENDORED_LIBNICE\\\" | grep -Fxq',
            self.text,
        )
        self.assertIn("if count != 1:", self.text)
        self.assertIn("unsafe symbol gate count=", self.text)
        self.assertIn("unsafe pipe remains", self.text)
        self.assertIn("V157_V4_PIPEFAIL_FALSE_NEGATIVE_FIX=PASS", self.text)

    def test_replacement_materializes_strings_before_grep(self):
        self.assertIn('VENDORED_LIBNICE_STRINGS=\\\"$BUILD/vendored-libnice.strings\\\"', self.text)
        self.assertIn('strings -a \\\"$VENDORED_LIBNICE\\\" > \\\"$VENDORED_LIBNICE_STRINGS\\\"', self.text)
        self.assertIn("V157_CHROOT_VENDORED_LIBNICE_STRINGS_RC", self.text)
        self.assertIn("grep -Fxq 'pseudo_tcp_socket_close'", self.text)

    def test_github_operations_remain_token_only(self):
        self.assertIn("GIT_TERMINAL_PROMPT=0", self.text)
        self.assertIn("-c credential.helper=", self.text)
        self.assertIn('-c "credential.helper=store --file=$CREDS"', self.text)
        self.assertIn("-c credential.useHttpPath=true", self.text)

    def test_candidate_and_actions_remain_forbidden(self):
        for marker in (
            'echo "V157_V4_CANDIDATE_EXECUTED=false"',
            'echo "V157_V4_COMELIT_NETWORK_SESSION_STARTED=false"',
            'echo "V157_V4_HOME_ASSISTANT_TOUCHED=false"',
            'echo "V157_V4_DOOR_ACTION_SENT=false"',
            'echo "V157_V4_SELF_ACTIVATION_SENT=false"',
            'echo "V157_V4_MEDIA_SIGNALING_SENT=false"',
        ):
            self.assertIn(marker, self.text)

        for forbidden in ("button.press", "SIGUSR1", "open_door("):
            self.assertNotIn(forbidden, self.text)

    def test_patched_v3_executes_once(self):
        self.assertEqual(
            self.text.count('RELEASE_SEED_SHA="$RELEASE_SEED_SHA" "$PATCHED"'),
            1,
        )
        self.assertIn("V157_V4_INNER_BUILDER_RC", self.text)


if __name__ == "__main__":
    unittest.main()
