from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
MEDIA = ROOT / "safety-poc" / "research" / "media" / "v1"
DOC = ROOT / "safety-poc" / "docs" / "P116_HA_STREAM_RTP_BRIDGE.md"
ARTIFACT = ROOT / ".p116-evidence" / "private" / "p115-run5" / "video.rtpdatagrams"
if str(MEDIA) not in sys.path:
    sys.path.insert(0, str(MEDIA))

import entrance_p116_r13c_single_idr_probe as r13c


class P116R13CSingleIdrAndTracePlanTests(unittest.TestCase):
    def test_single_idr_probe_is_socket_free_and_private_variant_only(self) -> None:
        source = (MEDIA / "entrance_p116_r13c_single_idr_probe.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("uint16 big-endian length-prefixed RTP datagram file", source)
        self.assertIn("omits exactly the second IDR access unit", source)
        self.assertIn("path.chmod(0o600)", source)
        self.assertNotIn("socket.", source)
        self.assertNotIn("bind(", source)
        self.assertNotIn("sendto(", source)
        self.assertNotIn("base64", source)

    @unittest.skipUnless(ARTIFACT.is_file(), "private P116 RTP artifact unavailable")
    def test_variant_removes_exactly_second_idr_au_at_packet_boundaries(self) -> None:
        raw_packets = r13c._read_length_prefixed_rtp(ARTIFACT)
        rtp = [
            pkt
            for raw_index, raw in enumerate(raw_packets)
            if (pkt := r13c._rtp_payload(raw, raw_index)) is not None
        ]
        units = r13c._depacketize_h264(rtp)
        idr_units = [unit for unit in units if unit.has_idr]
        self.assertEqual(len(idr_units), 2)
        second = idr_units[1]
        self.assertEqual(second.index, 8)
        self.assertEqual((second.packets[0].seq, second.packets[-1].seq), (4916, 4921))
        self.assertEqual(second.nal_type_csv(), "5")

        with tempfile.TemporaryDirectory(prefix="p116-r13c-test-", dir="/tmp") as tmp:
            variant = Path(tmp) / "video.single-idr.rtpdatagrams"
            remove_indexes = {pkt.raw_index for pkt in second.packets}
            r13c._write_length_prefixed(
                variant,
                [
                    packet
                    for index, packet in enumerate(raw_packets)
                    if index not in remove_indexes
                ],
            )
            self.assertEqual(variant.stat().st_mode & 0o777, 0o600)
            variant_packets = r13c._read_length_prefixed_rtp(variant)
            variant_rtp = [
                pkt
                for raw_index, raw in enumerate(variant_packets)
                if (pkt := r13c._rtp_payload(raw, raw_index)) is not None
            ]
            variant_units = r13c._depacketize_h264(variant_rtp)
            self.assertEqual(len(variant_packets), len(raw_packets) - len(second.packets))
            self.assertEqual(len(variant_units), len(units) - 1)
            self.assertEqual(sum(unit.has_idr for unit in variant_units), 1)
            self.assertEqual(sum(unit.has_sps for unit in variant_units), 9)
            self.assertEqual(sum(unit.has_pps for unit in variant_units), 9)

    def test_document_records_capture_plan_privacy_gate_and_numeric_policy(self) -> None:
        doc = DOC.read_text(encoding="utf-8")
        for required in (
            "P116 R13C single-IDR closure",
            "| `SECOND_IDR_REQUIRED_FOR_FIRST_PART` | `false` |",
            "OFFICIAL_APP_POST_ACTIVE_EVENTS",
            "OUR_HELPER_POST_ACTIVE_EVENTS",
            ">=5 s before media-active and >=60 s after",
            "raw PCAP",
            "outside Git",
            "mode `600`",
            "unknown numerics resolve to `<redacted>`",
            "MARKER_SPECIFIC_ALLOWLIST_PROPOSAL=true",
        ):
            self.assertIn(required, doc)
        self.assertNotIn("catch-all numeric allowlist", doc.lower().split("forbidden", 1)[-1])


if __name__ == "__main__":
    unittest.main()
