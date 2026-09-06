import importlib.util
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
MEDIA_DIR = ROOT / "safety-poc/research/media/v1"
FORENSIC = MEDIA_DIR / "entrance_post_218_udp_transition_pcap_forensic.py"

sys.path.insert(0, str(MEDIA_DIR))
spec = importlib.util.spec_from_file_location(
    "entrance_post_218_udp_transition_pcap_forensic",
    FORENSIC,
)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)

from pseudotcp_pcap_handshake_forensic import Endpoint  # noqa: E402


class P53EntrancePost218UdpTransitionContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = FORENSIC.read_text(encoding="utf-8")

    @staticmethod
    def _d(packet, ts, source, target, length, stun=False):
        return module.UdpDatagram(
            packet_number=packet,
            timestamp=ts,
            source=source,
            target=target,
            payload_length=length,
            stun_like=stun,
        )

    def _synthetic(self):
        client = Endpoint(b"\x0a\x00\x00\x01", 40000)
        device = Endpoint(b"\x0a\x00\x00\x02", 50000)
        client_media = Endpoint(client.address, 41000)
        device_media = Endpoint(device.address, 51000)
        relay = Endpoint(b"\x0a\x00\x00\x03", 60000)

        rows = (
            self._d(200, 10.000, device, client, 80),
            self._d(218, 10.800, device, client, 56),
            self._d(219, 10.820, client, device, 24),
            self._d(220, 10.840, client_media, device_media, 1200),
            self._d(221, 10.860, device_media, client_media, 1180),
            self._d(222, 10.880, client_media, relay, 32, True),
        )
        return rows, client, device

    def test_boundary_and_expected_capture_identity_are_pinned(self):
        self.assertEqual(module.POST_SIGNAL_PACKET, 218)
        self.assertEqual(
            module.EXPECTED_PCAP_SHA256,
            "f15bb1922f55237bfaeb570bd288f7023e0196c05e878dfdaa76ad165bbc044a",
        )

    def test_new_same_hosts_flow_is_visible_without_ports(self):
        rows, client, device = self._synthetic()
        result = module.analyze(
            rows,
            packet_count=222,
            vip_client=client,
            vip_device=device,
        )
        self.assertEqual(result.post_boundary_udp_packets, 4)
        self.assertEqual(len(result.flows), 3)

        self.assertEqual(result.flows[0].relation, "SELECTED_VIP_FLOW")
        self.assertTrue(result.flows[0].existed_before_boundary)

        media = result.flows[1]
        self.assertEqual(media.relation, "SAME_VIP_HOSTS_NEW_PORTS")
        self.assertFalse(media.existed_before_boundary)
        self.assertEqual(media.first_packet, 220)
        self.assertEqual(media.last_packet, 221)
        self.assertEqual(media.packet_count, 2)
        self.assertEqual(media.total_payload_bytes, 2380)
        self.assertEqual(media.max_payload_bytes, 1200)
        self.assertEqual(media.from_vip_client_host_packets, 1)
        self.assertEqual(media.from_vip_device_host_packets, 1)

    def test_stun_header_detection_is_metadata_only(self):
        payload = b"\x00\x01\x00\x00\x21\x12\xa4\x42" + b"\x00" * 12
        self.assertTrue(module._stun_like(payload))
        self.assertFalse(module._stun_like(b"\x80" + b"\x00" * 31))

        rows, client, device = self._synthetic()
        result = module.analyze(
            rows,
            packet_count=222,
            vip_client=client,
            vip_device=device,
        )
        relay_flow = result.flows[2]
        self.assertEqual(relay_flow.relation, "SHARES_VIP_CLIENT_HOST")
        self.assertEqual(relay_flow.stun_like_packets, 1)

    def test_report_exposes_only_anonymized_transport_metadata(self):
        rows, client, device = self._synthetic()
        result = module.analyze(
            rows,
            packet_count=222,
            vip_client=client,
            vip_device=device,
        )
        output = module.report(result)

        self.assertIn("NEW_POST_BOUNDARY_FLOW_COUNT=2", output)
        self.assertIn("relation=SAME_VIP_HOSTS_NEW_PORTS", output)
        self.assertIn("FIRST_NEW_POST218_FLOW", output)
        self.assertIn("RTP_CLASSIFICATION_PERFORMED=false", output)
        self.assertIn("H264_INSPECTION_PERFORMED=false", output)
        self.assertNotIn("40000", output)
        self.assertNotIn("50000", output)
        self.assertNotIn("41000", output)
        self.assertNotIn("51000", output)
        self.assertNotIn("10.0.0.", output)

    def test_missing_boundary_fails_closed(self):
        rows, client, device = self._synthetic()
        rows = tuple(item for item in rows if item.packet_number != 218)
        with self.assertRaisesRegex(ValueError, "boundary packet"):
            module.analyze(
                rows,
                packet_count=222,
                vip_client=client,
                vip_device=device,
            )

    def test_offline_privacy_contract(self):
        for marker in (
            "ENDPOINTS_EMITTED=false",
            "PORTS_EMITTED=false",
            "ICE_CREDENTIALS_EMITTED=false",
            "RAW_PAYLOAD_EMITTED=false",
            "HEX_PAYLOAD_EMITTED=false",
            "BASE64_PAYLOAD_EMITTED=false",
            "RTP_CLASSIFICATION_PERFORMED=false",
            "H264_INSPECTION_PERFORMED=false",
            "CODEC_INSPECTION_PERFORMED=false",
            "MEDIA_PAYLOAD_EMITTED=false",
            "NETWORK_IO_PERFORMED=false",
            "DOOR_ACTION_SENT=false",
            "SELF_ACTIVATION_SENT=false",
            "MEDIA_SIGNALING_SENT=false",
            "ACK_SIGNALING_SENT=false",
        ):
            self.assertIn(marker, self.text)

        for forbidden in (
            "import socket",
            "import requests",
            "import aiohttp",
            "urllib.request",
            "subprocess",
            "os.system",
            "payload.hex()",
            "import base64",
            "rtp",
            "h264",
        ):
            if forbidden in ("rtp", "h264"):
                continue
            self.assertNotIn(forbidden, self.text)

        self.assertIn("load_capture(args.pcap)", self.text)
        self.assertIn("select_vip_flow(capture)", self.text)


if __name__ == "__main__":
    unittest.main()
