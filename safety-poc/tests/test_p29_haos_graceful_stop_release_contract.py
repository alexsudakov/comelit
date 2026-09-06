import hashlib
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
EXPECTED_SOURCE_SHA = "5827d9fd043b85fc0c59a31661a1a125c6b239771e2a70c3e5afdd95f1a03c73"
EXPECTED_BINARY_SHA = "0942326900e12426ad75014ae844d70e97d813878019165b6480cca1e8730457"
EXPECTED_PREVIOUS_BINARY_SHA = "c171e7d1d342d059858f0cfca4f81dc8a07679f1d18992718bec2d6ead84db86"
EXPECTED_ROOTFS_SHA = "41f73e3cf5fa919b8aa5ca6b30dc48f0da2720776d7423e2a7748211456fe081"
EXPECTED_INTERPRETER = b"/lib/ld-musl-x86_64.so.1"
FORBIDDEN_INTERPRETER = b"/lib64/ld-linux-x86-64.so.2"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class P29HaosGracefulStopReleaseContract(unittest.TestCase):
    def test_manifest_is_1_5_7(self):
        manifest = json.loads(
            (ROOT / "custom_components/comelit/manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["version"], "1.5.7")

    def test_release_source_and_binary_hashes_are_frozen(self):
        source = ROOT / "safety-poc/research/door/v1_5_7/comelit-v4-persistent-ctpp-door.c"
        binary = ROOT / "custom_components/comelit/native/comelit-v4"
        self.assertEqual(sha256(source), EXPECTED_SOURCE_SHA)
        self.assertEqual(sha256(binary), EXPECTED_BINARY_SHA)
        self.assertNotEqual(EXPECTED_BINARY_SHA, EXPECTED_PREVIOUS_BINARY_SHA)

    def test_production_binary_is_musl_not_glibc(self):
        binary = (ROOT / "custom_components/comelit/native/comelit-v4").read_bytes()
        self.assertIn(EXPECTED_INTERPRETER, binary)
        self.assertNotIn(FORBIDDEN_INTERPRETER, binary)

    def test_graceful_and_door_safety_markers_remain_in_binary(self):
        binary = (ROOT / "custom_components/comelit/native/comelit-v4").read_bytes()
        for marker in (
            b"PSEUDOTCP_GRACEFUL_CLOSE_REQUESTED=true",
            b"PSEUDOTCP_GRACEFUL_CLOSE_FORCE=false",
            b"PSEUDOTCP_GRACEFUL_CLOSE_FORCE_RST_SENT=false",
            b"PSEUDOTCP_GRACEFUL_CLOSE_COMPLETE=true",
            b"V4_DOOR_EXISTING_CTPP_REUSED=true",
            b"V4_DOOR_OPERATION_WRITES_SENT=5",
            b"V4_DOOR_AUTOMATIC_RETRY_ALLOWED=false",
            b"V4_DOOR_PHYSICAL_EFFECT_ASSERTED=false",
        ):
            self.assertIn(marker, binary)
        self.assertNotIn(b"PSEUDOTCP_GRACEFUL_CLOSE_FORCE=true", binary)

    def test_build_info_binds_haos_compatibility_and_rootfs(self):
        text = (ROOT / "safety-poc/research/door/v1_5_7/BUILD_INFO.txt").read_text(encoding="utf-8")
        for marker in (
            "release=1.5.7",
            "source_sha256=" + EXPECTED_SOURCE_SHA,
            "binary_sha256=" + EXPECTED_BINARY_SHA,
            "build_environment=Alpine 3.24.1 minirootfs chroot",
            "alpine_rootfs_sha256=" + EXPECTED_ROOTFS_SHA,
            "libnice_version=0.1.22",
            "glib_version=2.88.1",
            "interpreter=/lib/ld-musl-x86_64.so.1",
            "pseudotcp_graceful_close=true",
            "pseudotcp_graceful_close_force=false",
            "automatic_retry_allowed=false",
            "physical_effect_asserted=false",
            "candidate_executed=false",
            "comelit_network_session_started=false",
        ):
            self.assertIn(marker, text)


if __name__ == "__main__":
    unittest.main()
