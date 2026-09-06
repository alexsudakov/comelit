#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
MEDIA = ROOT / "research" / "media" / "v1"
sys.path.insert(0, str(MEDIA))

from entrance_client_media_signaling_body_contract_pcap_forensic import (
    _best_copy_spans,
    _find_all,
    analyze,
    report,
)
from entrance_device_video_ack_pcap_forensic import VipFrame
from pseudotcp_pcap_handshake_forensic import Endpoint


def body(length: int, *, sequence: int, action: int, flags: int) -> bytearray:
    data = bytearray(length)
    data[0:2] = (0x1840).to_bytes(2, "little")
    data[2:6] = sequence.to_bytes(4, "little")
    data[6:8] = action.to_bytes(2, "big")
    data[8:10] = flags.to_bytes(2, "big")
    return data


class P60ContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = Endpoint(b"\x0a\x00\x00\x01", 40000)
        self.device = Endpoint(b"\x0a\x00\x00\x02", 50000)
        self.request_id = 77
        self.address_a = b"ADDRROLEA"
        self.address_b = b"ADDRROLEB"

    def frame(self, direction: str, packet: int, ts: float, payload: bytes) -> VipFrame:
        return VipFrame(direction, packet, packet, ts, self.request_id, payload)

    def anchor(self) -> VipFrame:
        data = body(40, sequence=0x10000000, action=0x0008, flags=0x0003)
        data[20:29] = self.address_a
        data[30:39] = self.address_b
        return self.frame("DEVICE_TO_CLIENT", 200, 1.000, bytes(data))

    def test_find_all_and_copy_spans(self) -> None:
        self.assertEqual(_find_all(b"abcabc", b"abc"), (0, 3))
        spans = _best_copy_spans(b"xxxxABCDEFGHyyyy", (("SRC", b"00ABCDEFGH11"),))
        self.assertTrue(any(span.length >= 8 for span in spans))

    def test_analyze_derives_sequence_and_address_relations_without_values(self) -> None:
        anchor = self.anchor()

        prev_client = body(32, sequence=0x22000000, action=0x0000, flags=0xFFFF)
        prev_device = body(36, sequence=0x11010000, action=0x0002, flags=0x000C)

        c000a = body(44, sequence=0x22000000, action=0x000A, flags=0x0011)
        c000a[12:21] = self.address_b
        c000a[22:31] = self.address_a
        c000a[32:44] = b"COMMONBLOCK1"

        d000a = body(44, sequence=0x11020000, action=0x000A, flags=0x0011)
        d000a[12:21] = self.address_a
        d000a[22:31] = self.address_b
        d000a[32:44] = b"COMMONBLOCK1"

        c001a = body(60, sequence=0x22010000, action=0x001A, flags=0x0011)
        c001a[12:21] = self.address_b
        c001a[22:31] = self.address_a
        c001a[32:44] = b"COMMONBLOCK1"
        c001a[44:60] = b"EXTENSION-000001"

        frames = (
            anchor,
            self.frame("DEVICE_TO_CLIENT", 203, 1.200, bytes(prev_device)),
            self.frame("CLIENT_TO_DEVICE", 204, 1.220, bytes(prev_client)),
            self.frame("CLIENT_TO_DEVICE", 206, 1.330, bytes(c000a)),
            self.frame("DEVICE_TO_CLIENT", 209, 1.530, bytes(d000a)),
            self.frame("CLIENT_TO_DEVICE", 212, 1.640, bytes(c001a)),
        )

        with patch(
            "entrance_client_media_signaling_body_contract_pcap_forensic._find_anchor",
            return_value=anchor,
        ):
            result = analyze(frames, client=self.client, device=self.device)

        self.assertEqual(result.client_000a.sequence_delta_previous_same_direction, 0)
        self.assertEqual(result.device_000a.sequence_delta_previous_same_direction, 0x00010000)
        self.assertEqual(result.client_001a.sequence_delta_previous_same_direction, 0x00010000)
        self.assertEqual(len(result.client_000a.address_matches), 2)
        self.assertEqual(len(result.device_000a.address_matches), 2)
        self.assertGreaterEqual(result.client_001a_copy_coverage_bytes, 12)

        text = report(result)
        self.assertIn("MIRROR_000A_DIFF_POSITION_COUNT=", text)
        self.assertIn("CLIENT_001A_COPY_COVERAGE_BYTES=", text)
        self.assertIn("PROTOCOL_ADDRESS_VALUES_EMITTED=false", text)
        self.assertIn("RAW_PAYLOAD_EMITTED=false", text)
        self.assertIn("NETWORK_IO_PERFORMED=false", text)
        self.assertNotIn("ADDRROLEA", text)
        self.assertNotIn("ADDRROLEB", text)

    def test_fail_closed_when_target_frame_missing(self) -> None:
        anchor = self.anchor()
        with patch(
            "entrance_client_media_signaling_body_contract_pcap_forensic._find_anchor",
            return_value=anchor,
        ):
            with self.assertRaises(ValueError):
                analyze((anchor,), client=self.client, device=self.device)


if __name__ == "__main__":
    unittest.main()
