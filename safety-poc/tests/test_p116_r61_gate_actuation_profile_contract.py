from __future__ import annotations

import importlib.util
from dataclasses import replace
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
MEDIA = ROOT / "safety-poc/research/media/v1"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


contract = load_module(
    "r61_contract",
    MEDIA / "entrance_p116_r61_gate_actuation_profile_contract.py",
)
forensics = load_module(
    "r61_forensics",
    MEDIA / "entrance_p116_r61_gate_profile_forensics.py",
)
const = load_module("comelit_const_r61", ROOT / "custom_components/comelit/const.py")


def markers(lines: list[str]) -> dict[str, str]:
    return dict(line.split("=", 1) for line in lines if "=" in line)


class P116R61GateActuationProfileContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self._original_input = forensics.INPUT
        self._temp_input = tempfile.TemporaryDirectory()
        input_root = Path(self._temp_input.name)
        (input_root / "pcap").mkdir()
        (input_root / "dex-strings").mkdir()
        (input_root / "PROVENANCE.txt").write_text(
            "synthetic repository-only R61 test fixture\n",
            encoding="utf-8",
        )
        (input_root / "pcap" / "synthetic-evidence.pcap").write_bytes(
            b"R61-SYNTHETIC\x00" + b"00000643" + b"\x00" + b"00000610"
        )
        (input_root / "dex-strings" / "synthetic.txt").write_text(
            "opendoor-address-book\n"
            "opendoor-actions\n"
            "output-index\n"
            "actuator\n"
            "actuator-address-book\n"
            "door\n",
            encoding="utf-8",
        )
        forensics.INPUT = input_root

    def tearDown(self) -> None:
        forensics.INPUT = self._original_input
        self._temp_input.cleanup()

    def test_entrance_profile_validates_and_generates_symbolic_frames(self) -> None:
        profile = contract.entrance_proven_profile()
        verdict = contract.validate_profile(profile)

        self.assertTrue(verdict.valid, verdict.reasons)
        frames = contract.generate_symbolic_frames(profile)
        self.assertEqual(5, len(frames))
        self.assertTrue(all(frame["raw_payload_bytes_emitted"] is False for frame in frames))
        self.assertTrue(all(frame["automatic_retry_allowed"] is False for frame in frames))

    def test_rejects_entrance_to_gate_transfer(self) -> None:
        verdict = contract.validate_profile(contract.entrance_profile_transferred_to_gate())

        self.assertFalse(verdict.valid)
        self.assertTrue(
            any(reason.startswith("door_identity_provenance_mismatch") for reason in verdict.reasons)
        )

    def test_rejects_unattributed_field(self) -> None:
        profile = contract.entrance_proven_profile()
        profile = replace(
            profile,
            command_sequence=contract.ProfileField(
                "command_sequence",
                profile.command_sequence.value,
                None,
            ),
        )

        verdict = contract.validate_profile(profile)

        self.assertFalse(verdict.valid)
        self.assertIn("unattributed_field:command_sequence", verdict.reasons)

    def test_rejects_capture_derived_constant_promoted_to_protocol_constant(self) -> None:
        profile = contract.entrance_proven_profile()
        captured_promoted = contract.ProvenanceRef(
            artifact=".r61-input/pcap/self_activation.pcap",
            anchor="byte scan",
            door_identity="entrance",
            evidence_class=contract.EvidenceClass.OBSERVED,
            literal_class=contract.LiteralClass.PROTOCOL_CONSTANT,
        )
        profile = replace(
            profile,
            output_address_selector=contract.ProfileField(
                "output_address_selector",
                "capture-observed-selector",
                captured_promoted,
            ),
        )

        verdict = contract.validate_profile(profile)

        self.assertFalse(verdict.valid)
        self.assertIn("capture_literal_promoted:output_address_selector", verdict.reasons)

    def test_gate_unvalidated_profile_refuses_emission(self) -> None:
        profile = contract.gate_unvalidated_profile()
        verdict = contract.validate_profile(profile)

        self.assertFalse(verdict.valid)
        self.assertFalse(verdict.can_emit)
        with self.assertRaises(ValueError):
            contract.generate_symbolic_frames(profile)

    def test_derived_markers_flip_on_corrupted_input(self) -> None:
        result = markers(forensics.flip_markers())

        self.assertEqual("true", result["GATE_ACTUATION_PROFILE_VALIDATED_REAL"])
        self.assertEqual("false", result["GATE_ACTUATION_PROFILE_VALIDATED_MUTATED"])
        self.assertEqual("true", result["GATE_STANDARD_PRESS_ALLOWED_REAL"])
        self.assertEqual("false", result["GATE_STANDARD_PRESS_ALLOWED_MUTATED"])
        self.assertEqual("6", result["DOOR_PROFILE_WRITE_COUNT_LEGACY_ORACLE_REAL"])
        self.assertEqual("CONFLICT", result["DOOR_PROFILE_WRITE_COUNT_LEGACY_ORACLE_MUTATED"])
        self.assertEqual("PASS", result["NATIVE_SOURCE_SHA256_FLIPS"])
        self.assertEqual("PASS", result["DOOR_PROFILE_WRITE_COUNT_NATIVE_FLIPS"])
        self.assertEqual("PASS", result["DOOR_BODY_1_SHA256_FLIPS"])
        self.assertEqual("PASS", result["V4_DOOR_TARGET_MARKER_FLIPS"])
        self.assertEqual("PASS", result["PCAP_DOOR_ENTRANCE_ASCII_COUNT_FLIPS"])
        self.assertEqual("PASS", result["GATE_ACTUATION_PROFILE_VALIDATED_FLIPS"])
        self.assertEqual("PASS", result["GATE_STANDARD_PRESS_ALLOWED_FLIPS"])
        self.assertEqual("PASS", result["DOOR_PROFILE_WRITE_COUNT_LEGACY_ORACLE_FLIPS"])
        self.assertEqual("PASS", result["R61_SELF_CHECK"])

    def test_analyzer_reflects_r63_gate_promotion_while_r61_artifact_stays_historical(self) -> None:
        result = markers(forensics.derive_markers())

        self.assertEqual("5", result["DOOR_PROFILE_WRITE_COUNT_NATIVE"])
        self.assertEqual("6", result["DOOR_PROFILE_WRITE_COUNT_LEGACY_ORACLE_STEP_PLAN"])
        self.assertEqual("6", result["DOOR_PROFILE_WRITE_COUNT_LEGACY_ORACLE_ORACLE_PATH"])
        self.assertEqual("false", result["DOOR_PROFILE_WRITE_COUNT_LEGACY_ORACLE_CONFLICT"])
        self.assertEqual("6", result["DOOR_PROFILE_WRITE_COUNT_LEGACY_ORACLE"])
        self.assertEqual("NATIVE_5_VS_LEGACY_ORACLE_6", result["DOOR_PROFILE_WRITE_COUNT_DIVERGENCE"])
        self.assertEqual("entrance", result["V4_DOOR_TARGET_MARKER"])
        self.assertEqual("00000610", result["V4_GATE"])
        self.assertEqual("true", result["GATE_ACTUATION_PROFILE_VALIDATED"])
        self.assertEqual("true", result["GATE_STANDARD_PRESS_ALLOWED"])
        self.assertEqual("None", result["GATE_BLOCKED_REASON"])
        self.assertEqual("00000610", result["GATE_RING_SOURCE"])
        self.assertEqual("false", result["GATE_PROFILE_ARTIFACT_PRESENT"])

    def test_gate_marker_is_derivation_backed_by_shipped_const_text(self) -> None:
        const_text = (ROOT / "custom_components/comelit/const.py").read_text(encoding="utf-8")
        mutated = const_text.replace(
            '"actuation_profile_validated": True,',
            '"actuation_profile_validated": False,',
            1,
        )

        real = forensics.derive_gate_capability_from_const_text(const_text)
        changed = forensics.derive_gate_capability_from_const_text(mutated)

        self.assertTrue(real.actuation_profile_validated)
        self.assertTrue(real.press_allowed)
        self.assertFalse(changed.actuation_profile_validated)
        self.assertFalse(changed.press_allowed)

    def test_legacy_oracle_count_marker_is_derivation_backed(self) -> None:
        source = (ROOT / "safety-poc/src/comelit_safety_poc/door_semantics.py").read_text(
            encoding="utf-8"
        )
        mutated = source.replace(
            "SemanticStep.CONFIRM_FINAL: SemanticKind.WRITE,",
            "SemanticStep.CONFIRM_FINAL: SemanticKind.OPTIONAL_WAIT,",
            1,
        )

        real = forensics.derive_legacy_oracle_write_counts(door_semantics_text=source)
        changed = forensics.derive_legacy_oracle_write_counts(door_semantics_text=mutated)

        self.assertEqual((6, 6, False, "6"), real)
        self.assertEqual((5, 6, True, "CONFLICT"), changed)

    def test_forensics_report_tail_does_not_hardcode_gate_marker_values(self) -> None:
        source = (MEDIA / "entrance_p116_r61_gate_profile_forensics.py").read_text(
            encoding="utf-8"
        )

        self.assertNotIn('"GATE_ACTUATION_PROFILE_VALIDATED=false"', source)
        self.assertNotIn('"GATE_STANDARD_PRESS_ALLOWED=false"', source)
        self.assertNotIn("'GATE_ACTUATION_PROFILE_VALIDATED=false'", source)
        self.assertNotIn("'GATE_STANDARD_PRESS_ALLOWED=false'", source)

    def test_shipped_component_gate_is_promoted_by_r63(self) -> None:
        capability = const.resolve_door_capability(const.DOOR_GATE, media_paused=False)

        self.assertTrue(capability.configured)
        self.assertTrue(capability.ring_source_validated)
        self.assertEqual("00000610", capability.ring_source)
        self.assertTrue(capability.actuation_profile_validated)
        self.assertTrue(capability.press_allowed)


if __name__ == "__main__":
    unittest.main()
