#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
MEDIA = ROOT / "safety-poc" / "research" / "media" / "v1"
sys.path.insert(0, str(MEDIA))

from entrance_p93_device_000a_gate_diagnostics_transform import (  # noqa: E402
    DEFAULT_SOURCE,
    report,
    transform,
)


class P93Device000AGateDiagnosticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        source_path = DEFAULT_SOURCE
        if not source_path.exists():
            source_path = ROOT / source_path
        cls.candidate = transform(source_path.read_text(encoding="utf-8"))

    def test_composes_p92_without_changing_order_gate(self) -> None:
        candidate = self.candidate
        self.assertIn("P92_DEVICE_000A_GATE_ARMED=true", candidate)
        self.assertIn("P92_DEVICE_000A_TIMEOUT_SECONDS=3", candidate)
        self.assertIn("P92_DEVICE_000A_OBSERVED=PASS", candidate)
        self.assertIn("P92_DEVICE_000A_GATE=PASS", candidate)
        self.assertIn("P92_WAIT_DEVICE_000A=true", candidate)
        self.assertIn("p78_queue_rtpc_client_001a", candidate)

    def test_validator_counts_progress_stages_only(self) -> None:
        candidate = self.candidate
        start = candidate.index("p92_device_000a_is_valid")
        block = candidate[start : start + 2400]
        stages = (
            "p93_device_000a_ctpp_frames++;",
            "p93_device_000a_len44++;",
            "p93_device_000a_prefix_1840++;",
            "p93_device_000a_action_000a++;",
            "p93_device_000a_tag_match++;",
            "p93_device_000a_target_match++;",
        )
        positions = [block.index(stage) for stage in stages]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("request_id != v4_ctpp_channel_id", block)
        self.assertIn("body_len != 44u", block)
        self.assertIn("body[0] != 0x40u", block)
        self.assertIn("body[6] != 0x00u || body[7] != 0x0au", block)
        self.assertIn("memcmp(body + 10u, p78_rtpc_client_000a + 10u, 6u)", block)
        self.assertIn("memcmp(body + 16u, p78_rtpc_client_000a + 16u, 2u)", block)

    def test_timeout_emits_safe_numeric_counters_before_existing_fail(self) -> None:
        candidate = self.candidate
        start = candidate.index("p92_device_000a_timeout_cb")
        block = candidate[start : start + 2600]
        for marker in (
            "P80_DEVICE_000A_CTPP_FRAME_COUNT=%",
            "P80_DEVICE_000A_LEN44_COUNT=%",
            "P80_DEVICE_000A_PREFIX_1840_COUNT=%",
            "P80_DEVICE_000A_ACTION_000A_COUNT=%",
            "P80_DEVICE_000A_TAG_MATCH_COUNT=%",
            "P80_DEVICE_000A_TARGET_MATCH_COUNT=%",
            "P80_DEVICE_000A_GATE_TIMEOUT=true",
        ):
            self.assertIn(marker, block)
        self.assertLess(
            block.index("P80_DEVICE_000A_GATE_TIMEOUT=true"),
            block.index('p78_fail_rtpc("P92_DEVICE_000A_TIMEOUT=true")'),
        )

    def test_success_adds_only_allowlisted_validation_marker(self) -> None:
        self.assertIn("P80_DEVICE_000A_VALIDATION=PASS", self.candidate)
        self.assertIn("P92_DEVICE_000A_OBSERVED=PASS", self.candidate)

    def test_no_payload_or_identity_values_are_emitted(self) -> None:
        candidate = self.candidate
        for forbidden in (
            'printf("%02x',
            'fprintf(stderr, "%02x',
            "RAW_PAYLOAD=",
            "TARGET_ID_VALUE=",
            "PROTOCOL_ADDRESS_VALUE=",
        ):
            self.assertNotIn(forbidden, candidate)

    def test_safety_and_lifetime_invariants_are_preserved(self) -> None:
        candidate = self.candidate
        self.assertIn("P80_MEDIA_LIFETIME_OWNER=HOME_ASSISTANT", candidate)
        self.assertIn("P80_SIGNALING_WATCHDOG_DISARMED=true", candidate)
        self.assertIn("P80_V4_LISTENER_TIMEOUT_DISARMED=true", candidate)
        self.assertIn("P78_SECOND_CTPP_OPEN=false", candidate)
        self.assertIn("P80_DOOR_SIGNAL_ENTRYPOINT=false", candidate)
        self.assertNotIn("signal(SIGUSR1, v4_door_signal_handler);", candidate)

        text = report()
        self.assertIn("P93_PROTOCOL_BEHAVIOR_CHANGED=false", text)
        self.assertIn("P93_RAW_PAYLOAD_EMITTED=false", text)
        self.assertIn("P93_TARGET_ID_VALUE_EMITTED=false", text)
        self.assertIn("P93_AUTOMATIC_RETRY=false", text)
        self.assertIn("P93_SECOND_CTPP_OPEN=false", text)
        self.assertIn("P93_DOOR_ACTION_SENT=false", text)
        self.assertIn("P93_MEDIA_HARD_LIMIT_SECONDS=180", text)
        self.assertIn("NETWORK_IO_PERFORMED=false", text)
        self.assertIn("CANDIDATE_EXECUTED=false", text)


if __name__ == "__main__":
    unittest.main()
