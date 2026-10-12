#!/usr/bin/env python3
"""P125 active-media ring opaque probe transform tests."""

from __future__ import annotations

import hashlib
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
MEDIA = ROOT / "research" / "media" / "v1"
SOURCE = ROOT / "research" / "door" / "v1_5_7" / "comelit-v4-persistent-ctpp-door.c"

sys.path.insert(0, str(MEDIA))

import entrance_p116_r68_ringid_probe_core as core  # noqa: E402
import entrance_p122_on_demand_media_door_transform as p122  # noqa: E402
import entrance_p125_ringid_probe_media_transform as p125  # noqa: E402


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _forbidden_name() -> str:
    return "V4_RING_" + "LOGICAL" + "_CALL_ID"


class P125RingProbeMediaTransformTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = SOURCE.read_text(encoding="utf-8")
        cls.p122_generated = p122.transform(cls.source, include_p116=True)
        cls.generated_a = p125.transform(cls.source)
        cls.generated_b = p125.transform(cls.source)

    def test_n2_media_transform_once_and_deterministic(self) -> None:
        self.assertEqual(_sha256_text(self.p122_generated), p125.INPUT_SOURCE_SHA256)
        self.assertEqual(self.generated_a, self.generated_b)
        self.assertEqual(_sha256_text(self.generated_a), "a66bded0e618f3308204acb8514f33054036c9eac585daa5cc1e28316572b6ef")
        self.assertEqual(self.generated_a.count(core.BEGIN), 1)
        self.assertEqual(self.generated_a.count("static void\nv4_ring_probe_emit"), 1)
        self.assertEqual(self.generated_a.count('v4_ring_probe_emit(body, body_len, "INITIAL");'), 1)
        self.assertEqual(self.generated_a.count('v4_ring_probe_emit(body, body_len, "RETRANSMIT");'), 1)

    def test_n5_media_anchor_exists_once_after_p122_chain(self) -> None:
        self.assertEqual(self.p122_generated.count(core._HELPER_ANCHOR), 1)

    def test_n6_media_markers_and_no_forbidden_name(self) -> None:
        for marker in (
            "V4_RING_BODY_32_35",
            "V4_RING_PEER_CONNECTION",
            "V4_RING_PHASE",
            "V4_RING_PARSE_STATUS=OK",
            "V4_RING_PARSE_STATUS=INSUFFICIENT_LENGTH",
        ):
            self.assertIn(marker, self.generated_a)
        self.assertNotIn(_forbidden_name(), self.generated_a)

    def test_media_input_source_sha_and_transform_name_are_pinned(self) -> None:
        self.assertEqual(p125.P122_TRANSFORM, "entrance_p122_on_demand_media_door_transform.py")
        self.assertEqual(
            p125.INPUT_SOURCE_SHA256,
            "92e12f5a27dd728231e073076429863cdc059825819f4f600d5d3dd50138ca26",
        )


if __name__ == "__main__":
    unittest.main()
