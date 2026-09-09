#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
MEDIA = ROOT / "research" / "media" / "v1"
if str(MEDIA) not in sys.path:
    sys.path.insert(0, str(MEDIA))

from entrance_p94_device_000a_frame_metadata_transform import (  # noqa: E402
    report,
    transform,
)

SOURCE = ROOT / "research" / "door" / "v1_5_7" / "comelit-v4-persistent-ctpp-door.c"


class P94Device000AFrameMetadataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.generated = transform(SOURCE.read_text(encoding="utf-8"))

    def test_composes_p93_without_changing_existing_gate_predicate(self) -> None:
        generated = self.generated
        self.assertIn("p93_device_000a_ctpp_frames++;", generated)
        self.assertIn("p93_device_000a_len44++;", generated)
        self.assertIn("p93_device_000a_prefix_1840++;", generated)
        self.assertIn("p93_device_000a_action_000a++;", generated)
        self.assertIn("p93_device_000a_tag_match++;", generated)
        self.assertIn("p93_device_000a_target_match++;", generated)
        self.assertIn(
            "memcmp(body + 10u, p78_rtpc_client_000a + 10u, 6u)",
            generated,
        )
        self.assertIn(
            "memcmp(body + 16u, p78_rtpc_client_000a + 16u, 2u)",
            generated,
        )

    def test_metadata_observation_occurs_before_len44_gate(self) -> None:
        generated = self.generated
        start = generated.index(
            "static gboolean\np92_device_000a_is_valid(guint16 request_id"
        )
        end = generated.index("return TRUE;", start)
        block = generated[start:end]
        count = block.index("p93_device_000a_ctpp_frames++;")
        observe = block.index("p94_observe_device_000a_frame_metadata(body, body_len);")
        len_gate = block.index("body_len != 44u")
        self.assertLess(count, observe)
        self.assertLess(observe, len_gate)

    def test_only_first_three_same_ctpp_frames_are_retained(self) -> None:
        generated = self.generated
        self.assertIn("#define P94_DEVICE_000A_FRAME_META_MAX 3u", generated)
        self.assertIn(
            "p94_device_000a_frame_meta_count >= P94_DEVICE_000A_FRAME_META_MAX",
            generated,
        )
        self.assertIn("p94_device_000a_frame_meta_count++", generated)

    def test_metadata_fields_are_structural_scalars_only(self) -> None:
        generated = self.generated
        self.assertIn("p94_device_000a_frame_body_len[index] = body_len;", generated)
        self.assertIn("p94_device_000a_frame_prefix[index]", generated)
        self.assertIn("p94_device_000a_frame_action[index]", generated)
        self.assertIn("p94_device_000a_frame_flags[index]", generated)
        for forbidden in (
            'printf("%02x',
            'fprintf(stderr, "%02x',
            "P80_DEVICE_000A_FRAME_PAYLOAD",
            "P80_DEVICE_000A_FRAME_SEQUENCE",
            "P80_DEVICE_000A_FRAME_TARGET",
            "P80_DEVICE_000A_FRAME_CHANNEL",
        ):
            self.assertNotIn(forbidden, generated)

    def test_timeout_emits_metadata_before_unchanged_p92_failure(self) -> None:
        generated = self.generated
        start = generated.index("p92_device_000a_timeout_cb(gpointer data)")
        end = generated.index("static gboolean\np92_device_000a_is_valid", start)
        block = generated[start:end]
        meta = block.index("P80_DEVICE_000A_FRAME_META_COUNT=%u")
        frame = block.index("P80_DEVICE_000A_FRAME_%u_BODY_LEN=%u")
        gate_timeout = block.index("P80_DEVICE_000A_GATE_TIMEOUT=true")
        p92_fail = block.index('p78_fail_rtpc("P92_DEVICE_000A_TIMEOUT=true")')
        self.assertLess(meta, frame)
        self.assertLess(frame, gate_timeout)
        self.assertLess(gate_timeout, p92_fail)

    def test_report_preserves_safety_and_lifetime_contract(self) -> None:
        text = report()
        self.assertIn("P94_PROTOCOL_BEHAVIOR_CHANGED=false", text)
        self.assertIn("P94_FRAME_METADATA_LIMIT=3", text)
        self.assertIn("P94_RAW_PAYLOAD_EMITTED=false", text)
        self.assertIn("P94_SEQUENCE_VALUE_EMITTED=false", text)
        self.assertIn("P94_TARGET_ID_VALUE_EMITTED=false", text)
        self.assertIn("P94_CHANNEL_ID_VALUE_EMITTED=false", text)
        self.assertIn("P94_AUTOMATIC_RETRY=false", text)
        self.assertIn("P94_SECOND_CTPP_OPEN=false", text)
        self.assertIn("P94_DOOR_ACTION_SENT=false", text)
        self.assertIn("P94_MEDIA_HARD_LIMIT_SECONDS=180", text)
        self.assertIn("NETWORK_IO_PERFORMED=false", text)
        self.assertIn("CANDIDATE_EXECUTED=false", text)


if __name__ == "__main__":
    unittest.main()
