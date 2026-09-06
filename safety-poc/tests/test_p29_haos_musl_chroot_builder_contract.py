from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = (
    ROOT
    / "safety-poc/research/media/v1/ct120_prepare_haos_graceful_stop_v1_5_7_v3.sh"
)


class P29HaosMuslChrootBuilderContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = SCRIPT.read_text(encoding="utf-8")

    def test_exact_recovered_base_and_release_branch_are_pinned(self):
        self.assertIn(
            "BASE_MAIN=c9dc9ad0b1fb2ae4701340437edc9d2ff93b81ea",
            self.text,
        )
        self.assertIn(
            "BRANCH=fix/graceful-pseudotcp-stop-haos-v1-5-7",
            self.text,
        )
        self.assertIn(
            "CURRENT_V156_BINARY_SHA="
            "c171e7d1d342d059858f0cfca4f81dc8a07679f1d18992718bec2d6ead84db86",
            self.text,
        )

    def test_official_alpine_minirootfs_is_exact_and_checksum_verified(self):
        for required in (
            "ALPINE_VERSION_EXPECTED=3.24.1",
            "ALPINE_ROOTFS_NAME=alpine-minirootfs-3.24.1-x86_64.tar.gz",
            "ALPINE_ROOTFS_URL=https://dl-cdn.alpinelinux.org/alpine/v3.24/releases/x86_64/alpine-minirootfs-3.24.1-x86_64.tar.gz",
            "ALPINE_ROOTFS_SHA256_URL=https://dl-cdn.alpinelinux.org/alpine/v3.24/releases/x86_64/alpine-minirootfs-3.24.1-x86_64.tar.gz.sha256",
            'parsed.scheme != "https"',
            'parsed.hostname != "dl-cdn.alpinelinux.org"',
            "V157_CHROOT_ALPINE_CHECKSUM_NAME_GATE=PASS",
            "V157_CHROOT_ALPINE_CHECKSUM_GATE=PASS",
            "V157_CHROOT_ALPINE_VERSION_GATE=PASS",
        ):
            self.assertIn(required, self.text)

    def test_builder_requires_chroot_not_docker_or_podman(self):
        self.assertIn('for command in git python3 sha256sum strings file awk grep sed uname chroot tar sort paste stat', self.text)
        self.assertIn('chroot "$ROOTFS" /bin/sh -eu -c', self.text)
        self.assertNotIn('docker info', self.text)
        self.assertNotIn('podman info', self.text)
        self.assertNotIn('"$CONTAINER_RUNTIME" run', self.text)

    def test_exact_graceful_source_and_environment_are_verified(self):
        for required in (
            "GRACEFUL_SOURCE_SHA=5827d9fd043b85fc0c59a31661a1a125c6b239771e2a70c3e5afdd95f1a03c73",
            "FROZEN_V153_SOURCE_SHA=088e0e23c07404792254f5c18e3f12dbbd499a676bda2d3883988d1d9bb3be6f",
            "TRANSFORM_SHA=b98e3f774054934421d7fda71e8c28aa89e9383adefe170221b00aa6184cbb6f",
            "EXPECTED_LIBNICE=0.1.22",
            "EXPECTED_GLIB=2.88.1",
            "EXPECTED_INTERPRETER=/lib/ld-musl-x86_64.so.1",
            "V157_CHROOT_VENDORED_LIBNICE_CLOSE_SYMBOL=PASS",
            "V157_CHROOT_INTERPRETER_GATE=PASS",
            "V157_CHROOT_NEEDED_GATE=PASS",
        ):
            self.assertIn(required, self.text)

    def test_candidate_is_never_executed(self):
        self.assertIn('echo "candidate_executed=false"', self.text)
        self.assertIn('echo "CANDIDATE_EXECUTED=false"', self.text)
        self.assertNotIn('"$CANDIDATE" --', self.text)
        self.assertNotIn('"$CANDIDATE" 2>', self.text)
        self.assertNotIn('"$BINARY" --', self.text)

    def test_door_media_and_force_close_remain_forbidden(self):
        for required in (
            'echo "DOOR_ACTION_SENT=false"',
            'echo "SELF_ACTIVATION_SENT=false"',
            'echo "MEDIA_SIGNALING_SENT=false"',
            'V4_DOOR_AUTOMATIC_RETRY_ALLOWED=false',
            'V4_DOOR_PHYSICAL_EFFECT_ASSERTED=false',
            'PSEUDOTCP_GRACEFUL_CLOSE_FORCE_RST_SENT=false',
            "V157_CHROOT_FORCE_CLOSE_GATE=PASS",
        ):
            self.assertIn(required, self.text)
        for forbidden in ("button.press", "SIGUSR1", "open_door("):
            self.assertNotIn(forbidden, self.text)

    def test_github_fetch_and_push_are_token_only(self):
        self.assertGreaterEqual(self.text.count("GIT_TERMINAL_PROMPT=0"), 2)
        self.assertGreaterEqual(self.text.count("-c credential.helper="), 2)
        self.assertGreaterEqual(
            self.text.count('-c "credential.helper=store --file=$CREDS"'), 2
        )
        self.assertGreaterEqual(self.text.count("-c credential.useHttpPath=true"), 2)
        self.assertIn("V157_CHROOT_TOKEN_ONLY_FETCH_RC", self.text)
        self.assertIn("V157_CHROOT_TOKEN_ONLY_PUSH_RC", self.text)

    def test_release_is_tested_before_token_push(self):
        self.assertIn("V157_CHROOT_REPOSITORY_TEST_RC", self.text)
        self.assertIn("V157_CHROOT_STAGED_PATH_GATE=PASS", self.text)
        self.assertLess(
            self.text.index("V157_CHROOT_REPOSITORY_TEST_RC"),
            self.text.index('push origin "HEAD:refs/heads/$BRANCH"'),
        )


if __name__ == "__main__":
    unittest.main()
