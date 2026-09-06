from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
MEDIA = ROOT / "safety-poc" / "research" / "media" / "v1"
if str(MEDIA) not in sys.path:
    sys.path.insert(0, str(MEDIA))

import entrance_post_218_non_pseudotcp_udp_pcap_forensic as p55
from pseudotcp_pcap_handshake_forensic import Endpoint


class P55Post218NonPseudoTcpUdpContract(unittest.TestCase):
    def setUp(self):
        self.client = Endpoint(b"\x0a\x00\x00\x01", 10000)
        self.device = Endpoint(b"\x0a\x00\x00\x02", 20000)

    def datagram(self, packet, ts, source, target, payload):
        return p55.SelectedDatagram(
            packet_number=packet,
            timestamp=ts,
            source=source,
            target=target,
            payload=payload,
        )

    def fixture(self):
        boundary = b"\x00" * 24 + b"boundary"
        pseudotcp = b"\x00" * 24 + b"abcdefgh"
        stun = b"\x00\x01\x00\x00\x21\x12\xa4\x42" + b"s" * 12
        return (
            self.datagram(218, 10.000, self.device, self.client, boundary),
            self.datagram(219, 10.020, self.device, self.client, pseudotcp),
            self.datagram(220, 10.030, self.client, self.device, stun),
            self.datagram(221, 10.040, self.device, self.client, b"d" * 1400),
            self.datagram(222, 10.050, self.client, self.device, b"c" * 60),
        )

    def test_three_way_classification_reconciles_counts_and_bytes(self):
        result = p55.analyze(
            self.fixture(),
            client=self.client,
            device=self.device,
        )
        self.assertEqual(result.selected_udp_count, 4)
        self.assertEqual(result.selected_udp_bytes, 1512)
        self.assertEqual(result.pseudotcp_count, 1)
        self.assertEqual(result.pseudotcp_bytes, 32)
        self.assertEqual(result.stun_count, 1)
        self.assertEqual(result.stun_bytes, 20)
        self.assertEqual(result.opaque_count, 2)
        self.assertEqual(result.opaque_bytes, 1460)
        self.assertEqual(result.opaque_device_count, 1)
        self.assertEqual(result.opaque_device_bytes, 1400)
        self.assertEqual(result.opaque_client_count, 1)
        self.assertEqual(result.opaque_client_bytes, 60)
        self.assertEqual(result.opaque_min_len, 60)
        self.assertEqual(result.opaque_max_len, 1400)
        self.assertEqual(result.first_opaque_packet, 221)
        self.assertEqual(result.last_opaque_packet, 222)

    def test_report_is_metadata_only_and_directional(self):
        result = p55.analyze(
            self.fixture(),
            client=self.client,
            device=self.device,
        )
        text = p55.report(result)
        self.assertIn("POST218_CLASS_COUNT_RECONCILED=true", text)
        self.assertIn("POST218_CLASS_BYTES_RECONCILED=true", text)
        self.assertIn("POST218_OPAQUE_NON_PSEUDOTCP_BYTES=1460", text)
        self.assertIn("direction=DEVICE_TO_CLIENT payload_len=1400", text)
        self.assertIn("direction=CLIENT_TO_DEVICE payload_len=60", text)
        self.assertIn("RTP_CLASSIFICATION_PERFORMED=false", text)
        self.assertIn("H264_INSPECTION_PERFORMED=false", text)
        self.assertIn("NETWORK_IO_PERFORMED=false", text)
        self.assertNotIn("10.0.0.1", text)
        self.assertNotIn("10000", text)
        self.assertNotIn("20000", text)

    def test_missing_boundary_fails_closed(self):
        with self.assertRaises(ValueError):
            p55.analyze(
                tuple(item for item in self.fixture() if item.packet_number != 218),
                client=self.client,
                device=self.device,
            )

    def test_boundary_and_privacy_contract_are_fixed(self):
        source = (MEDIA / "entrance_post_218_non_pseudotcp_udp_pcap_forensic.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("BOUNDARY_PACKET = 218", source)
        self.assertIn("TIMELINE_LIMIT = 20", source)
        self.assertIn("_pseudotcp_segment", source)
        self.assertIn("STUN_MAGIC_COOKIE", source)
        self.assertNotIn("import av", source)
        self.assertNotIn("ffmpeg", source.lower())
        self.assertNotIn("nal_unit", source.lower())
        self.assertNotIn("rtp_payload", source.lower())


if __name__ == "__main__":
    unittest.main()
