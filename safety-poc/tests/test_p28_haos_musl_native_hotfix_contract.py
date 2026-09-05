import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CURRENT_BINARY = ROOT / "custom_components/comelit/native/comelit-v4"
ARCHIVED_V155_BINARY = (
    ROOT
    / "safety-poc/research/door/v1_5_5"
    / "comelit-v4-glibc-incompatible"
)
CURRENT_SHA = "c171e7d1d342d059858f0cfca4f81dc8a07679f1d18992718bec2d6ead84db86"
V155_BAD_SHA = "597ddc5c341f173880505e9937e45f53bc21ecb810447992c3844bb116521458"
MUSL_INTERPRETER = b"/lib/ld-musl-x86_64.so.1"
GLIBC_INTERPRETER = b"/lib64/ld-linux-x86-64.so.2"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class P28HaosMuslNativeHotfixContract(unittest.TestCase):
    def test_manifest_is_1_5_6(self):
        manifest = json.loads(
            (ROOT / "custom_components/comelit/manifest.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(manifest["version"], "1.5.6")

    def test_current_native_is_restored_haos_compatible_musl_binary(self):
        binary = CURRENT_BINARY.read_bytes()
        self.assertEqual(sha256(CURRENT_BINARY), CURRENT_SHA)
        self.assertTrue(binary.startswith(b"\x7fELF"))
        self.assertIn(MUSL_INTERPRETER, binary)
        self.assertNotIn(GLIBC_INTERPRETER, binary)

    def test_incompatible_v155_binary_is_archived_not_production(self):
        binary = ARCHIVED_V155_BINARY.read_bytes()
        self.assertEqual(sha256(ARCHIVED_V155_BINARY), V155_BAD_SHA)
        self.assertTrue(binary.startswith(b"\x7fELF"))
        self.assertIn(GLIBC_INTERPRETER, binary)
        self.assertNotIn(MUSL_INTERPRETER, binary)
        self.assertNotEqual(binary, CURRENT_BINARY.read_bytes())

    def test_restored_binary_preserves_frozen_v153_door_safety_contract(self):
        binary = CURRENT_BINARY.read_bytes()
        for marker in (
            b"V4_DOOR_EXISTING_CTPP_REUSED=true",
            b"V4_DOOR_OPERATION_WRITES_SENT=5",
            b"V4_DOOR_AUTOMATIC_RETRY_ALLOWED=false",
            b"V4_DOOR_PHYSICAL_EFFECT_ASSERTED=false",
        ):
            self.assertIn(marker, binary)

    def test_graceful_close_is_preserved_as_research_but_not_shipped_in_hotfix(self):
        current = CURRENT_BINARY.read_bytes()
        archived = ARCHIVED_V155_BINARY.read_bytes()
        marker = b"PSEUDOTCP_GRACEFUL_CLOSE_REQUESTED=true"
        self.assertNotIn(marker, current)
        self.assertIn(marker, archived)

    def test_hotfix_build_info_records_root_cause_and_no_actuation_change(self):
        text = (
            ROOT / "safety-poc/research/door/v1_5_6/BUILD_INFO.txt"
        ).read_text(encoding="utf-8")
        for marker in (
            "release=1.5.6",
            "current_binary_sha256=" + CURRENT_SHA,
            "current_binary_interpreter=/lib/ld-musl-x86_64.so.1",
            "incompatible_v155_binary_sha256=" + V155_BAD_SHA,
            "incompatible_v155_interpreter=/lib64/ld-linux-x86-64.so.2",
            "failure_class=haos_dynamic_loader_incompatible",
            "observed_python_exception=FileNotFoundError",
            "pseudotcp_graceful_close_in_production=false",
            "pseudotcp_graceful_close_research_preserved=true",
            "automatic_retry_allowed=false",
            "physical_effect_asserted=false",
        ):
            self.assertIn(marker, text)


if __name__ == "__main__":
    unittest.main()
