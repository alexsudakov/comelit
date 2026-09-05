import ast
import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

EXPECTED_SOURCE_SHA = "088e0e23c07404792254f5c18e3f12dbbd499a676bda2d3883988d1d9bb3be6f"
EXPECTED_BINARY_SHA = "c171e7d1d342d059858f0cfca4f81dc8a07679f1d18992718bec2d6ead84db86"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class P15HacsPersistentCtppReleaseContract(unittest.TestCase):
    def test_manifest_is_1_5_3(self):
        manifest = json.loads(
            (
                ROOT / "custom_components/comelit/manifest.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["version"], "1.5.3")

    def test_validated_native_artifact_is_installed(self):
        binary = (
            ROOT
            / "custom_components/comelit/native/comelit-v4"
        )
        self.assertEqual(sha256(binary), EXPECTED_BINARY_SHA)

    def test_research_source_identity_is_frozen(self):
        source = (
            ROOT
            / "safety-poc/research/door/v1_5_3"
            / "comelit-v4-persistent-ctpp-door.c"
        )
        self.assertEqual(sha256(source), EXPECTED_SOURCE_SHA)

    def test_runtime_consumes_native_write_count(self):
        source = (
            ROOT / "custom_components/comelit/runtime.py"
        ).read_text(encoding="utf-8")

        ast.parse(source)

        self.assertIn("V4_DOOR_WRITE_COUNT=", source)
        self.assertIn(
            '"V4_DOOR_CTPP_CHANNEL_ID=": "ctpp_channel_id"',
            source,
        )
        self.assertNotIn(
            '"write_count": 6 if state == "ACKED" else None',
            source,
        )

    def test_runtime_requires_door_specific_ack(self):
        source = (
            ROOT / "custom_components/comelit/runtime.py"
        ).read_text(encoding="utf-8")

        self.assertIn(
            "V4_DOOR_DOOR_SPECIFIC_ACK_PROVEN=",
            source,
        )
        self.assertIn(
            'diagnostic.get("door_specific_ack_proven") is True',
            source,
        )
        self.assertIn(
            'state == "ACKED"',
            source,
        )
        self.assertIn(
            '"automatic_retry_allowed": False',
            source,
        )
        self.assertIn(
            '"physical_effect_asserted": False',
            source,
        )

    def test_button_exposes_new_diagnostics(self):
        source = (
            ROOT / "custom_components/comelit/button.py"
        ).read_text(encoding="utf-8")

        ast.parse(source)

        for marker in (
            '"last_write_count"',
            '"last_door_specific_ack_proven"',
            '"last_existing_ctpp_reused"',
            '"last_ctpp_channel_id"',
        ):
            self.assertIn(marker, source)

    def test_binary_has_persistent_ctpp_contract(self):
        binary = (
            ROOT
            / "custom_components/comelit/native/comelit-v4"
        ).read_bytes()

        for marker in (
            b"V4_DOOR_EXISTING_CTPP_REUSED=true",
            b"V4_DOOR_OPERATION_WRITES_SENT=5",
            b"V4_DOOR_DOOR_SPECIFIC_ACK_PROVEN=false",
            b"V4_DOOR_WRITE_COUNT=%u",
            b"V4_DOOR_RESULT=%s",
            b"V4_DOOR_AUTOMATIC_RETRY_ALLOWED=false",
            b"V4_DOOR_PHYSICAL_EFFECT_ASSERTED=false",
        ):
            self.assertIn(marker, binary)

        for marker in (
            b"V4_DOOR_CTPP_OPEN_SENT=true",
            b"V4_DOOR_CTPP_CLOSE_SENT=true",
            b"V4_DOOR_WRITE_%u_ACKED=true",
        ):
            self.assertNotIn(marker, binary)

    def test_runtime_diagnostic_merge_cannot_override_validated_fields(self):
        source = (
            ROOT / "custom_components/comelit/runtime.py"
        ).read_text(encoding="utf-8")

        merge_pos = source.index("result.update(diagnostic)")
        write_pos = source.index(
            'result["write_count"] = write_count',
            merge_pos,
        )
        ack_flag_pos = source.index(
            'result["door_specific_ack_proven"] = (',
            merge_pos,
        )
        protocol_pos = source.index(
            'result["protocol_acked"] = (',
            merge_pos,
        )

        self.assertLess(merge_pos, write_pos)
        self.assertLess(write_pos, protocol_pos)
        self.assertLess(ack_flag_pos, protocol_pos)

    def test_button_requires_proven_protocol_ack(self):
        source = (
            ROOT / "custom_components/comelit/button.py"
        ).read_text(encoding="utf-8")

        self.assertIn(
            'if result.get("protocol_acked") is not True:',
            source,
        )
        self.assertNotIn(
            'if result.get("state") != "ACKED":',
            source,
        )

    def test_build_info_records_safety_contract(self):
        text = (
            ROOT
            / "safety-poc/research/door/v1_5_3"
            / "BUILD_INFO.txt"
        ).read_text(encoding="utf-8")

        self.assertIn(
            "binary_sha256=" + EXPECTED_BINARY_SHA,
            text,
        )
        self.assertIn(
            "source_sha256=" + EXPECTED_SOURCE_SHA,
            text,
        )
        self.assertIn(
            "automatic_retry_allowed=false",
            text,
        )
        self.assertIn(
            "physical_effect_asserted=false",
            text,
        )
        self.assertIn(
            "terminal_state_without_proven_ack=UNKNOWN_OUTCOME",
            text,
        )


if __name__ == "__main__":
    unittest.main()
