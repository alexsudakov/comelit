import importlib.util
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
MEDIA = ROOT / "safety-poc" / "research" / "media" / "v1"
MODULE_PATH = MEDIA / "entrance_post_218_rtp_v2_shape_pcap_forensic.py"
BASE_PATH = MEDIA / "pseudotcp_pcap_handshake_forensic.py"
P55_PATH = MEDIA / "entrance_post_218_non_pseudotcp_udp_pcap_forensic.py"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


base = _load("p56_base", BASE_PATH)
p55 = _load("p56_p55", P55_PATH)
p56 = _load("p56_module", MODULE_PATH)


def rtp(seq: int, ssrc: int = 0x11223344, pt: int = 96, marker: bool = False, data_len: int = 20):
    b0 = 0x80
    b1 = pt | (0x80 if marker else 0)
    return bytes([b0, b1]) + seq.to_bytes(2, "big") + (1234).to_bytes(4, "big") + ssrc.to_bytes(4, "big") + (b"x" * data_len)


class P56ContractTest(unittest.TestCase):
    def setUp(self):
        self.client = base.Endpoint(b"\x0a\x00\x00\x01", 10000)
        self.device = base.Endpoint(b"\x0a\x00\x00\x02", 20000)

    def dg(self, packet, ts, source, target, payload):
        return p55.SelectedDatagram(packet, ts, source, target, payload)

    def datagrams(self):
        # packet 218 only needs to be the unique selected-flow boundary datagram.
        return (
            self.dg(218, 10.000, self.device, self.client, b"boundary"),
            self.dg(219, 10.020, self.device, self.client, rtp(10, pt=96, marker=True, data_len=100)),
            self.dg(220, 10.040, self.device, self.client, rtp(11, pt=96, data_len=80)),
            self.dg(221, 10.060, self.device, self.client, rtp(13, pt=96, data_len=60)),
            self.dg(222, 10.080, self.client, self.device, rtp(20, ssrc=0x55667788, pt=8, data_len=20)),
            self.dg(223, 10.100, self.client, self.device, rtp(20, ssrc=0x55667788, pt=8, data_len=20)),
            self.dg(224, 10.120, self.device, self.client, b"not-rtp"),
        )

    def test_rtp_header_shape_plain_extension_and_padding(self):
        plain = p56._parse_rtp_v2_shape(rtp(1, data_len=10))
        self.assertIsNotNone(plain)
        self.assertEqual(plain.header_length, 12)
        self.assertEqual(plain.media_data_length, 10)

        ext = bytearray(rtp(2, data_len=8))
        ext[0] |= 0x10
        ext = ext[:12] + b"\x10\x00\x00\x01" + b"ABCD" + ext[12:]
        parsed_ext = p56._parse_rtp_v2_shape(bytes(ext))
        self.assertIsNotNone(parsed_ext)
        self.assertEqual(parsed_ext.header_length, 20)

        padded = bytearray(rtp(3, data_len=8))
        padded[0] |= 0x20
        padded.extend(b"\x00\x00\x00\x04")
        parsed_padding = p56._parse_rtp_v2_shape(bytes(padded))
        self.assertIsNotNone(parsed_padding)
        self.assertEqual(parsed_padding.media_data_length, 8)

    def test_rejects_invalid_shapes(self):
        self.assertIsNone(p56._parse_rtp_v2_shape(b"short"))
        bad_version = bytearray(rtp(1))
        bad_version[0] = 0x40
        self.assertIsNone(p56._parse_rtp_v2_shape(bytes(bad_version)))
        bad_padding = bytearray(rtp(1, data_len=1))
        bad_padding[0] |= 0x20
        bad_padding[-1] = 99
        self.assertIsNone(p56._parse_rtp_v2_shape(bytes(bad_padding)))

    def test_analysis_and_sequence_progression(self):
        result = p56.analyze(self.datagrams(), client=self.client, device=self.device)
        self.assertEqual(result.opaque_count, 6)
        self.assertEqual(result.rtp_count, 5)
        self.assertEqual(result.non_rtp_count, 1)
        self.assertEqual(result.device_rtp_count, 3)
        self.assertEqual(result.client_rtp_count, 2)
        self.assertEqual(len(result.streams), 2)

        device_stream = result.streams[0]
        self.assertEqual(device_stream.payload_type, 96)
        self.assertEqual(device_stream.sequence_plus1_count, 1)
        self.assertEqual(device_stream.sequence_gap_count, 1)
        self.assertEqual(device_stream.sequence_duplicate_count, 0)

        client_stream = result.streams[1]
        self.assertEqual(client_stream.payload_type, 8)
        self.assertEqual(client_stream.sequence_duplicate_count, 1)

    def test_report_is_metadata_only(self):
        result = p56.analyze(self.datagrams(), client=self.client, device=self.device)
        text = p56.report(result)
        self.assertIn("RTP_V2_SHAPED_COUNT=5", text)
        self.assertIn("payload_type=96", text)
        self.assertIn("seq_plus1=1 seq_gap=1 seq_duplicate=0", text)
        self.assertIn("SEQUENCE_VALUES_EMITTED=false", text)
        self.assertIn("SSRC_VALUES_EMITTED=false", text)
        self.assertIn("H264_INSPECTION_PERFORMED=false", text)
        self.assertIn("CODEC_IDENTIFICATION_PERFORMED=false", text)
        self.assertIn("NETWORK_IO_PERFORMED=false", text)
        self.assertNotIn("11223344", text.lower())
        self.assertNotIn("55667788", text.lower())
        self.assertNotIn("sequence=", text.lower())

    def test_boundary_fail_closed(self):
        missing = tuple(x for x in self.datagrams() if x.packet_number != 218)
        with self.assertRaises(ValueError):
            p56.analyze(missing, client=self.client, device=self.device)

    def test_no_codec_or_payload_parser_surface(self):
        source = MODULE_PATH.read_text(encoding="utf-8").lower()
        self.assertIn("boundary_packet", source)
        self.assertNotIn("import av", source)
        self.assertNotIn("ffmpeg", source)
        self.assertNotIn("nal_unit", source)
        self.assertNotIn("h264_payload", source)


if __name__ == "__main__":
    unittest.main()
