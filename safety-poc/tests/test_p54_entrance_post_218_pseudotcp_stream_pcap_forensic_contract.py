import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[2]
MEDIA = ROOT / "safety-poc" / "research" / "media" / "v1"
MODULE_PATH = MEDIA / "entrance_post_218_pseudotcp_stream_pcap_forensic.py"
BASE_PATH = MEDIA / "pseudotcp_pcap_handshake_forensic.py"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


base = _load("p54_base", BASE_PATH)
p54 = _load("p54_module", MODULE_PATH)


class P54ContractTest(unittest.TestCase):
    def setUp(self):
        self.client = base.Endpoint(b"\x0a\x00\x00\x01", 10000)
        self.device = base.Endpoint(b"\x0a\x00\x00\x02", 20000)

    def seg(
        self,
        packet: int,
        ts: float,
        source,
        target,
        sequence: int,
        data: bytes = b"",
        flags: int = 0,
    ):
        return base.PseudoTcpSegment(
            packet_number=packet,
            timestamp=ts,
            source=source,
            target=target,
            wire_length=24 + len(data),
            sequence=sequence,
            acknowledgment=0,
            control=0,
            flags=flags,
            window=0,
            data=data,
        )

    def analysis(self):
        segments = (
            self.seg(218, 10.000, self.device, self.client, 100, b"boundary"),
            self.seg(219, 10.020, self.device, self.client, 200, b"a" * 1400),
            self.seg(220, 10.030, self.device, self.client, 1600, b"b" * 512),
            self.seg(221, 10.040, self.device, self.client, 1600, b"b" * 512),
            self.seg(222, 10.050, self.client, self.device, 300, b"c" * 40),
            self.seg(223, 10.060, self.client, self.device, 340, b""),
        )
        return base.FlowAnalysis(
            segments=segments,
            client=self.client,
            device=self.device,
            anchor_hits_client=1,
            anchor_hits_device=0,
        )

    def test_transport_summary_and_retransmit_dedup(self):
        result = p54.analyze(
            self.analysis(),
            vip_frames=(SimpleNamespace(first_packet=218),),
        )
        self.assertEqual(result.post_segment_count, 5)
        self.assertEqual(result.app_segment_count, 4)
        self.assertEqual(result.app_bytes_wire, 2464)
        self.assertEqual(result.unique_app_segment_count, 3)
        self.assertEqual(result.unique_app_bytes, 1952)
        self.assertEqual(result.retransmit_segment_count, 1)
        self.assertEqual(result.retransmit_bytes, 512)
        self.assertEqual(result.device_app_segments, 2)
        self.assertEqual(result.device_app_bytes, 1912)
        self.assertEqual(result.client_app_segments, 1)
        self.assertEqual(result.client_app_bytes, 40)
        self.assertEqual(result.zero_data_segments, 1)
        self.assertEqual(result.first_app_packet, 219)
        self.assertEqual(result.last_app_packet, 222)
        self.assertEqual(result.post_boundary_vip_frame_count, 0)
        self.assertEqual(result.min_app_len, 40)
        self.assertEqual(result.max_app_len, 1400)

    def test_report_is_metadata_only(self):
        result = p54.analyze(self.analysis(), vip_frames=())
        text = p54.report(result)
        self.assertIn("POST218_PSEUDOTCP_APP_DATA_PRESENT=true", text)
        self.assertIn("POST218_EXACT_RETRANSMIT_SEGMENT_COUNT=1", text)
        self.assertIn("direction=DEVICE_TO_CLIENT data_len=1400", text)
        self.assertIn("direction=CLIENT_TO_DEVICE data_len=40", text)
        self.assertIn("RAW_PAYLOAD_EMITTED=false", text)
        self.assertIn("MEDIA_SIGNATURE_INSPECTION_PERFORMED=false", text)
        self.assertIn("RTP_CLASSIFICATION_PERFORMED=false", text)
        self.assertIn("H264_INSPECTION_PERFORMED=false", text)
        self.assertIn("NETWORK_IO_PERFORMED=false", text)
        self.assertNotIn("10.0.0.1", text)
        self.assertNotIn("10000", text)
        self.assertNotIn("20000", text)
        self.assertNotIn("sequence=", text.lower())

    def test_boundary_is_fail_closed(self):
        analysis = self.analysis()
        missing = base.FlowAnalysis(
            segments=tuple(s for s in analysis.segments if s.packet_number != 218),
            client=analysis.client,
            device=analysis.device,
            anchor_hits_client=1,
            anchor_hits_device=0,
        )
        with self.assertRaises(ValueError):
            p54.analyze(missing)

    def test_contract_has_fixed_boundary_and_no_media_parser_surface(self):
        source = MODULE_PATH.read_text(encoding="utf-8")
        self.assertIn("BOUNDARY_PACKET = 218", source)
        self.assertIn("TIMELINE_LIMIT = 20", source)
        self.assertIn("collect_extended_vip_frames", source)
        self.assertNotIn("import av", source)
        self.assertNotIn("ffmpeg", source.lower())
        self.assertNotIn("rtp_payload", source.lower())
        self.assertNotIn("nal_unit", source.lower())


if __name__ == "__main__":
    unittest.main()
