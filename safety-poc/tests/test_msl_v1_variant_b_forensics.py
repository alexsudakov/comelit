#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SAFETY = ROOT / "safety-poc"
MEDIA = SAFETY / "research" / "media" / "v1"
SOURCE = SAFETY / "research" / "door" / "v1_5_7" / "comelit-v4-persistent-ctpp-door.c"
RUNNER = MEDIA / "ct120_run_msl_v1_variant_b_live.sh"

sys.path.insert(0, str(MEDIA))

import entrance_msl_v1_idle_listener_media_transform as variant_b  # noqa: E402


def sha_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class MslV1VariantBForensicsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.base = SOURCE.read_text(encoding="utf-8")
        cls.generated_a = variant_b.transform(cls.base)
        cls.generated_b = variant_b.transform(cls.base)
        cls.runner = RUNNER.read_text(encoding="utf-8")

    def test_generated_source_is_deterministic(self) -> None:
        real = sha_text(self.generated_a)
        mutated = sha_text(variant_b.transform(self.base + "\n/* variant-b-mutation */\n"))
        self.assertEqual(self.generated_a, self.generated_b)
        self.assertNotEqual(real, mutated)
        print(f"MSL_B_GENERATED_SOURCE_REPRODUCIBLE=true REAL={real} MUTATED={mutated}")

    def test_001a_markers_are_split_and_not_local_media_active(self) -> None:
        tx_case = self.generated_a.split("case P12_TX_MSL_B_IDLE_SELF_ACTIVATION:", 1)[1].split("break;", 1)[0]
        self.assertIn('msl_b_print_clock_marker("B03B_001A_TX_COMPLETED")', tx_case)
        self.assertIn("msl_b_arm_device_ack_wait()", tx_case)
        self.assertNotIn("msl_b_activate_idle_media_after_ack", tx_case)
        self.assertIn('msl_b_print_clock_marker("B03A_001A_QUEUED")', self.generated_a)
        self.assertIn('msl_b_print_clock_marker("B04_DEVICE_ACK_OBSERVED")', self.generated_a)
        self.assertNotIn("B03_INITIAL_001A_SENT", self.generated_a)
        print("MSL_B_B03_SPLIT_AND_LOCAL_ACTIVE_GATE=PASS")

    def test_post_001a_diagnostic_counters_are_emitted(self) -> None:
        for marker in (
            "MSL_B_POST_001A_FRAME_COUNT",
            "MSL_B_POST_001A_SAME_REQUEST_ID_COUNT",
            "MSL_B_POST_001A_BODY32_COUNT",
            "MSL_B_POST_001A_1800_COUNT",
            "MSL_B_ACK_REQUEST_ID_MATCH_COUNT",
            "MSL_B_ACK_HEADER_MATCH_COUNT",
            "MSL_B_ACK_ADDRESS_ROLE_MATCH_COUNT",
            "MSL_B_ACK_EXACT_MATCH_COUNT",
            "MSL_B_DEVICE_0008_COUNT",
            "MSL_B_DEVICE_000A_COUNT",
            "MSL_B_DEVICE_RESPONSE_COUNT",
            "MSL_B_RTPC_OPEN_RESPONSE_COUNT",
            "ACK_REJECT_WRONG_REQUEST_ID",
            "ACK_REJECT_WRONG_LENGTH",
            "ACK_REJECT_WRONG_PREFIX",
            "ACK_REJECT_WRONG_FLAGS",
            "ACK_REJECT_ADDRESS_ROLE",
            "ACK_REJECT_OTHER",
        ):
            self.assertIn(marker, self.generated_a)
            self.assertIn(marker, self.runner)
        print("MSL_B_POST_001A_DIAGNOSTIC_COUNTERS_PRESENT=true")

    def test_runner_uses_split_markers_for_phase_deltas(self) -> None:
        self.assertIn("MSL_B_PHASE_B02_TO_B03A_MS", self.runner)
        self.assertIn("MSL_B_PHASE_B03A_TO_B03B_MS", self.runner)
        self.assertIn("MSL_B_PHASE_B03B_TO_B04_MS", self.runner)
        self.assertIn("MSL_B_B03A_001A_QUEUED_MONO_MS", self.runner)
        self.assertIn("MSL_B_B03B_001A_TX_COMPLETED_MONO_MS", self.runner)
        self.assertIn("MSL_B_B04_DEVICE_ACK_OBSERVED_MONO_MS", self.runner)
        self.assertNotIn("MSL_B_B03_INITIAL_001A_SENT_MONO_MS", self.runner)
        self.assertNotIn("MSL_B_B04_STRUCTURAL_ACK_MEDIA_ACCEPTED_MONO_MS", self.runner)
        print("MSL_B_RUNNER_SPLIT_MARKER_DELTAS=true")


if __name__ == "__main__":
    unittest.main()
