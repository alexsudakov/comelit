#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
MEDIA = ROOT / "research" / "media" / "v1"
sys.path.insert(0, str(MEDIA))

from entrance_offset8_rtp_stream_inventory_pcap_forensic import analyze, report
from entrance_post_218_non_pseudotcp_udp_pcap_forensic import SelectedDatagram
from pseudotcp_pcap_handshake_forensic import Endpoint


def rtp(seq: int, timestamp: int, ssrc: int, pt: int, media_len: int, marker: bool = False) -> bytes:
    second = pt | (0x80 if marker else 0)
    return (
        bytes([0x80, second])
        + seq.to_bytes(2, "big")
        + timestamp.to_bytes(4, "big")
        + ssrc.to_bytes(4, "big")
        + bytes([0x55]) * media_len
    )


def wrapped(prefix: bytes, *args, **kwargs) -> bytes:
    if len(prefix) != 8:
        raise ValueError("test prefix must be exactly eight bytes")
    return prefix + rtp(*args, **kwargs)


class P58ContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = Endpoint(b"\x01\x01\x01\x01", 1000)
        self.device = Endpoint(b"\x02\x02\x02\x02", 2000)

    def dgram(self, packet: int, ts: float, source: Endpoint, target: Endpoint, payload: bytes) -> SelectedDatagram:
        return SelectedDatagram(packet, ts, source, target, payload)

    def test_stream_inventory_wrapper_cardinality_and_residual(self) -> None:
        base = 1000.0
        p0 = b"CM01ABCD"
        p1 = b"CM01ABCE"
        datagrams = (
            self.dgram(218, base, self.device, self.client, b"boundary"),
            self.dgram(219, base + 0.020, self.device, self.client, wrapped(p0, 10, 1000, 7, 8, 160)),
            self.dgram(220, base + 0.040, self.device, self.client, wrapped(p0, 11, 1160, 7, 8, 160)),
            self.dgram(221, base + 0.060, self.device, self.client, wrapped(p1, 12, 1320, 7, 8, 160)),
            self.dgram(222, base + 0.061, self.device, self.client, wrapped(p0, 40, 90000, 9, 99, 1200, True)),
            self.dgram(223, base + 0.062, self.device, self.client, wrapped(p0, 41, 93000, 9, 99, 600, True)),
            self.dgram(224, base + 0.063, self.client, self.device, wrapped(p0, 90, 2000, 11, 8, 160)),
            self.dgram(225, base + 0.083, self.client, self.device, wrapped(p0, 91, 2160, 11, 8, 160)),
            self.dgram(226, base + 0.084, self.client, self.device, b"opaque-residual"),
        )
        result = analyze(datagrams, client=self.client, device=self.device)

        self.assertEqual(result.opaque_count, 8)
        self.assertEqual(result.shaped_count, 7)
        self.assertEqual(result.residual_count, 1)
        self.assertEqual(len(result.streams), 3)
        self.assertEqual(result.wrapper_distinct_prefixes, 2)
        self.assertTrue(all(stat.unique_values == 1 for stat in result.wrapper_stats[:7]))
        self.assertEqual(result.wrapper_stats[7].unique_values, 2)

        audio_down = result.streams[0]
        self.assertEqual(audio_down.direction, "DEVICE_TO_CLIENT")
        self.assertEqual(audio_down.payload_type, 8)
        self.assertEqual(audio_down.packet_count, 3)
        self.assertEqual(audio_down.seq_plus1, 2)
        self.assertEqual(audio_down.seq_gap, 0)
        self.assertEqual(audio_down.ts_delta_mode, 160)
        self.assertEqual(audio_down.ts_delta_mode_count, 2)
        self.assertEqual(audio_down.media_len_min, 160)
        self.assertEqual(audio_down.media_len_max, 160)

        video_down = result.streams[1]
        self.assertEqual(video_down.payload_type, 99)
        self.assertEqual(video_down.packet_count, 2)
        self.assertEqual(video_down.marker_count, 2)
        self.assertEqual(video_down.ts_delta_mode, 3000)

        audio_up = result.streams[2]
        self.assertEqual(audio_up.direction, "CLIENT_TO_DEVICE")
        self.assertEqual(audio_up.payload_type, 8)
        self.assertEqual(audio_up.seq_plus1, 1)
        self.assertEqual(result.residual_client_count, 1)
        self.assertEqual(result.residual_device_count, 0)

    def test_report_is_metadata_only(self) -> None:
        base = 1000.0
        prefix = b"CM01ABCD"
        datagrams = (
            self.dgram(218, base, self.device, self.client, b"boundary"),
            self.dgram(219, base + 0.020, self.device, self.client, wrapped(prefix, 1, 100, 5, 8, 160)),
            self.dgram(220, base + 0.040, self.device, self.client, wrapped(prefix, 2, 260, 5, 8, 160)),
        )
        text = report(analyze(datagrams, client=self.client, device=self.device))
        self.assertIn("RTP_OFFSET=8", text)
        self.assertIn("RTP_ANON_STREAM_COUNT=1", text)
        self.assertIn("WRAPPER_BYTE_VALUES_EMITTED=false", text)
        self.assertIn("RAW_PAYLOAD_EMITTED=false", text)
        self.assertIn("H264_INSPECTION_PERFORMED=false", text)
        self.assertIn("NETWORK_IO_PERFORMED=false", text)
        self.assertNotIn("CM01ABCD", text)

    def test_boundary_is_fail_closed(self) -> None:
        with self.assertRaises(ValueError):
            analyze((), client=self.client, device=self.device)


if __name__ == "__main__":
    unittest.main()
