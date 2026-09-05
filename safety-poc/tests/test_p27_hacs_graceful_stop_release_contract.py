import hashlib
import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
EXPECTED_SOURCE_SHA = "5827d9fd043b85fc0c59a31661a1a125c6b239771e2a70c3e5afdd95f1a03c73"
EXPECTED_BINARY_SHA = "597ddc5c341f173880505e9937e45f53bc21ecb810447992c3844bb116521458"
EXPECTED_BASE_SOURCE_SHA = "088e0e23c07404792254f5c18e3f12dbbd499a676bda2d3883988d1d9bb3be6f"
EXPECTED_TRANSFORM_SHA = "b98e3f774054934421d7fda71e8c28aa89e9383adefe170221b00aa6184cbb6f"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class P27HacsGracefulStopReleaseContract(unittest.TestCase):
    def test_manifest_is_1_5_5(self):
        manifest = json.loads(
            (ROOT / "custom_components/comelit/manifest.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(manifest["version"], "1.5.5")

    def test_release_source_and_binary_hashes_are_frozen(self):
        source = (
            ROOT / "safety-poc/research/door/v1_5_5"
            / "comelit-v4-persistent-ctpp-door.c"
        )
        binary = ROOT / "custom_components/comelit/native/comelit-v4"
        self.assertEqual(sha256(source), EXPECTED_SOURCE_SHA)
        self.assertEqual(sha256(binary), EXPECTED_BINARY_SHA)

    def test_release_source_is_exact_reviewed_transform_of_frozen_v153(self):
        base = (
            ROOT / "safety-poc/research/door/v1_5_3"
            / "comelit-v4-persistent-ctpp-door.c"
        )
        transform_path = (
            ROOT / "safety-poc/research/media/v1"
            / "pseudotcp_graceful_stop_transform.py"
        )
        release = (
            ROOT / "safety-poc/research/door/v1_5_5"
            / "comelit-v4-persistent-ctpp-door.c"
        )

        self.assertEqual(sha256(base), EXPECTED_BASE_SOURCE_SHA)
        self.assertEqual(sha256(transform_path), EXPECTED_TRANSFORM_SHA)

        spec = importlib.util.spec_from_file_location(
            "pseudotcp_graceful_stop_transform_release_test",
            transform_path,
        )
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)

        expected = module.transform(base.read_text(encoding="utf-8"))
        self.assertEqual(release.read_text(encoding="utf-8"), expected)

    def test_graceful_close_contract_is_present_and_never_force_closes(self):
        source = (
            ROOT / "safety-poc/research/door/v1_5_5"
            / "comelit-v4-persistent-ctpp-door.c"
        ).read_text(encoding="utf-8")

        self.assertEqual(
            source.count("pseudo_tcp_socket_close(pseudo_tcp, FALSE);"),
            1,
        )
        self.assertNotIn(
            "pseudo_tcp_socket_close(pseudo_tcp, TRUE);",
            source,
        )
        self.assertIn("PSEUDOTCP_GRACEFUL_STOP_TIMEOUT_MS 5000", source)
        self.assertIn("PSEUDOTCP_GRACEFUL_CLOSE_DRAINED_BYTES=%u", source)

    def test_current_binary_contains_graceful_and_door_safety_markers(self):
        binary = (
            ROOT / "custom_components/comelit/native/comelit-v4"
        ).read_bytes()

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

        self.assertNotIn(
            b"PSEUDOTCP_GRACEFUL_CLOSE_FORCE=true",
            binary,
        )

    def test_build_info_matches_release_artifacts(self):
        text = (
            ROOT / "safety-poc/research/door/v1_5_5/BUILD_INFO.txt"
        ).read_text(encoding="utf-8")

        for marker in (
            "release=1.5.5",
            "source_sha256=" + EXPECTED_SOURCE_SHA,
            "binary_sha256=" + EXPECTED_BINARY_SHA,
            "base_source_sha256=" + EXPECTED_BASE_SOURCE_SHA,
            "transform_sha256=" + EXPECTED_TRANSFORM_SHA,
            "pseudotcp_graceful_close=true",
            "pseudotcp_graceful_close_force=false",
            "pseudotcp_graceful_close_force_rst_sent=false",
            "door_contract_source=frozen_v1_5_3_transform_only",
            "automatic_retry_allowed=false",
            "physical_effect_asserted=false",
        ):
            self.assertIn(marker, text)


if __name__ == "__main__":
    unittest.main()
