#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
MEDIA = ROOT / "research" / "media" / "v1"
sys.path.insert(0, str(MEDIA))

import entrance_p105_len24_fallback_forensic as p105


class P105Len24FallbackForensicTests(unittest.TestCase):
    def test_wrapper_length_consistency_pass_and_fail(self) -> None:
        packet = bytearray(24)
        packet[2] = 16
        self.assertTrue(p105.classify_datagram(bytes(packet)).wrapper_len_consistent)
        packet[2] = 15
        self.assertFalse(p105.classify_datagram(bytes(packet)).wrapper_len_consistent)

    def test_rtp_version_and_payload_type_gates(self) -> None:
        packet = bytearray(24)
        packet[2] = 16
        packet[8] = 0x80
        packet[9] = 99
        shape = p105.classify_datagram(bytes(packet))
        self.assertEqual(shape.byte0_version_bits_at_8, 2)
        self.assertTrue(shape.rtp_pt_99_or_8)
        self.assertTrue(p105.offset8_wrapped_rtp(shape))

        packet[9] = 8
        self.assertTrue(p105.offset8_wrapped_rtp(p105.classify_datagram(bytes(packet))))

        packet[9] = 97
        shape = p105.classify_datagram(bytes(packet))
        self.assertFalse(shape.rtp_pt_99_or_8)
        self.assertFalse(p105.offset8_wrapped_rtp(shape))

        packet[8] = 0x40
        packet[9] = 99
        shape = p105.classify_datagram(bytes(packet))
        self.assertEqual(shape.byte0_version_bits_at_8, 1)
        self.assertFalse(p105.offset8_wrapped_rtp(shape))

    def test_rtcp_range_and_stun_magic(self) -> None:
        packet = bytearray(24)
        packet[8] = 0x80
        packet[9] = 200
        shape = p105.classify_datagram(bytes(packet))
        self.assertTrue(shape.rtcp_pt_range)
        packet[9] = 199
        self.assertFalse(p105.classify_datagram(bytes(packet)).rtcp_pt_range)

        packet = bytearray(24)
        packet[4:8] = b"\x21\x12\xa4\x42"
        self.assertTrue(p105.classify_datagram(bytes(packet)).stun_magic_present)
        packet[7] = 0
        self.assertFalse(p105.classify_datagram(bytes(packet)).stun_magic_present)

    def test_pseudotcp_header_shape_true_and_false(self) -> None:
        packet = bytearray(24)
        packet[13] = 0x02
        self.assertTrue(p105.classify_datagram(bytes(packet)).pseudotcp_header_shape)

        packet[13] = 0x80
        self.assertFalse(p105.classify_datagram(bytes(packet)).pseudotcp_header_shape)

        packet = bytearray(24)
        packet[0] = 1
        self.assertFalse(p105.classify_datagram(bytes(packet)).pseudotcp_header_shape)

        packet = bytearray(24)
        packet[20] = 1
        self.assertFalse(p105.classify_datagram(bytes(packet)).pseudotcp_header_shape)

    def test_short_datagram_is_guarded(self) -> None:
        shape = p105.classify_datagram(b"\x80")
        self.assertEqual(shape.wrapper_inner_len_le16, 0)
        self.assertEqual(shape.byte0_version_bits_at_0, 2)
        self.assertEqual(shape.byte0_version_bits_at_8, 0)
        self.assertEqual(shape.rtp_pt_at_8, 0)
        self.assertEqual(shape.rtcp_pt_at_8, 0)
        self.assertFalse(shape.wrapper_len_consistent)
        self.assertFalse(shape.stun_magic_present)
        self.assertFalse(shape.pseudotcp_header_shape)

    def test_hypothesis_table_does_not_support_without_predicate_evidence(self) -> None:
        packet = bytes([0x01] * 24)
        shape = p105.classify_datagram(packet)
        table = dict((role, status) for role, status, _ in p105.hypothesis_table((shape,)))
        self.assertEqual(table["offset-8 wrapped RTP"], "REFUTED")
        self.assertEqual(table["RTCP"], "REFUTED")
        self.assertEqual(table["other already-known protocol frame"], "REFUTED")
        self.assertEqual(table["PseudoTCP/control frame"], "REFUTED")
        verdict, classification, _evidence = p105.verdict_for((shape,))
        self.assertEqual(verdict, "OBSERVED_UNRESOLVED")
        self.assertEqual(classification, "UNKNOWN")

    def test_optional_pcap_not_provided(self) -> None:
        result = p105.analyze_capture(None)
        self.assertEqual(result.sha256_status, "NOT_PROVIDED")
        self.assertIsNone(result.len24_count)
        self.assertEqual(result.verdict, "NOT_OBSERVED")

    def test_wrong_digest_exit_code_2(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pcap = Path(tmp) / "self_activation.pcap"
            pcap.write_bytes(b"not a capture")
            self.assertEqual(p105.main(["--pcap", str(pcap)]), 2)


if __name__ == "__main__":
    unittest.main()
