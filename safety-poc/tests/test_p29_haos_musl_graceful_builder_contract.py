from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = (
    ROOT
    / "safety-poc/research/media/v1/ct120_prepare_haos_graceful_stop_v1_5_7_v2.sh"
)


class P29HaosMuslGracefulBuilderContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = SCRIPT.read_text(encoding="utf-8")

    def test_release_is_based_on_recovered_v156_main(self):
        self.assertIn(
            "BASE_MAIN=c9dc9ad0b1fb2ae4701340437edc9d2ff93b81ea",
            self.text,
        )
        self.assertIn(
            "CURRENT_V156_BINARY_SHA="
            "c171e7d1d342d059858f0cfca4f81dc8a07679f1d18992718bec2d6ead84db86",
            self.text,
        )
        self.assertIn('data.get("version") != "1.5.6"', self.text)
        self.assertIn('data["version"] = "1.5.7"', self.text)

    def test_exact_graceful_source_is_rebuilt_not_regenerated(self):
        self.assertIn(
            "GRACEFUL_SOURCE_SHA="
            "5827d9fd043b85fc0c59a31661a1a125c6b239771e2a70c3e5afdd95f1a03c73",
            self.text,
        )
        self.assertIn(
            "GRACEFUL_SOURCE_REL=safety-poc/research/door/v1_5_5/"
            "comelit-v4-persistent-ctpp-door.c",
            self.text,
        )
        self.assertIn("V157_RELEASE_SOURCE_IDENTITY=PASS", self.text)

    def test_alpine_musl_environment_is_pinned_and_verified(self):
        for required in (
            "ALPINE_IMAGE=alpine:3.24.1",
            "EXPECTED_LIBNICE=0.1.22",
            "EXPECTED_GLIB=2.88.1",
            "EXPECTED_INTERPRETER=/lib/ld-musl-x86_64.so.1",
            "V157_RELEASE_ALPINE_VERSION_GATE=PASS",
            "V157_RELEASE_LIBNICE_GATE=PASS",
            "V157_RELEASE_GLIB_GATE=PASS",
            "V157_RELEASE_INTERPRETER_GATE=PASS",
            "V157_RELEASE_NEEDED_GATE=PASS",
        ):
            self.assertIn(required, self.text)

        self.assertIn(
            "EXPECTED_NEEDED_SORTED='libc.musl-x86_64.so.1,"
            "libglib-2.0.so.0,libgobject-2.0.so.0,libnice.so.10'",
            self.text,
        )
        self.assertIn("V157_RELEASE_GLIBC_INTERPRETER_GATE=PASS", self.text)

    def test_container_receives_no_comelit_secret_and_does_not_run_candidate(self):
        self.assertEqual(self.text.count('"$CONTAINER_RUNTIME" run --rm'), 1)
        self.assertIn("-v \"$WT:/src:ro\"", self.text)
        self.assertIn("-v \"$BUILD:/out\"", self.text)
        self.assertNotIn("/root/.config/comelit/secrets.env", self.text)
        self.assertNotIn("COMELIT_VIP_TOKEN", self.text)
        self.assertIn('echo "candidate_executed=false"', self.text)
        self.assertIn('echo "CANDIDATE_EXECUTED=false"', self.text)
        self.assertIn('echo "COMELIT_NETWORK_SESSION_STARTED=false"', self.text)

    def test_generated_release_test_is_cwd_safe(self):
        self.assertIn('cd "$WT" || exit 99', self.text)
        self.assertIn(
            "safety-poc.tests.test_p29_haos_graceful_stop_release_contract",
            self.text,
        )

    def test_door_and_media_actions_remain_forbidden(self):
        for required in (
            'echo "DOOR_ACTION_SENT=false"',
            'echo "SELF_ACTIVATION_SENT=false"',
            'echo "MEDIA_SIGNALING_SENT=false"',
            "V4_DOOR_AUTOMATIC_RETRY_ALLOWED=false",
            "V4_DOOR_PHYSICAL_EFFECT_ASSERTED=false",
            "PSEUDOTCP_GRACEFUL_CLOSE_FORCE_RST_SENT=false",
        ):
            self.assertIn(required, self.text)

        for forbidden in (
            "button.press",
            "SIGUSR1",
            "open_door(",
        ):
            self.assertNotIn(forbidden, self.text)

        self.assertIn(
            "grep -Fq 'PSEUDOTCP_GRACEFUL_CLOSE_FORCE=true'",
            self.text,
        )
        self.assertIn("V157_RELEASE_FORCE_CLOSE_GATE=FAIL", self.text)
        self.assertIn(
            'self.assertNotIn(b"PSEUDOTCP_GRACEFUL_CLOSE_FORCE=true", binary)',
            self.text,
        )

    def test_github_push_is_explicitly_token_authenticated(self):
        self.assertIn("GIT_TERMINAL_PROMPT=0", self.text)
        self.assertIn("-c credential.helper=", self.text)
        self.assertIn(
            '-c "credential.helper=store --file=$CREDS"',
            self.text,
        )
        self.assertIn("-c credential.useHttpPath=true", self.text)
        self.assertIn('push origin "HEAD:refs/heads/$BRANCH"', self.text)
        self.assertIn("V157_RELEASE_TOKEN_ONLY_PUSH_RC", self.text)

    def test_binary_safety_markers_are_required_before_commit(self):
        for marker in (
            "PSEUDOTCP_GRACEFUL_CLOSE_REQUESTED=true",
            "PSEUDOTCP_GRACEFUL_CLOSE_FORCE=false",
            "PSEUDOTCP_GRACEFUL_CLOSE_COMPLETE=true",
            "V4_DOOR_EXISTING_CTPP_REUSED=true",
            "V4_DOOR_OPERATION_WRITES_SENT=5",
            "V4_DOOR_AUTOMATIC_RETRY_ALLOWED=false",
            "V4_DOOR_PHYSICAL_EFFECT_ASSERTED=false",
        ):
            self.assertIn(marker, self.text)


if __name__ == "__main__":
    unittest.main()
