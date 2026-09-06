import importlib.util
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
MEDIA = ROOT / "safety-poc" / "research" / "media" / "v1"
MODULE_PATH = MEDIA / "entrance_post_218_wrapped_rtp_shape_pcap_forensic.py"
BASE_PATH = MEDIA / "pseudotcp_pcap_handshake_forensic.py"
P55_PATH = MEDIA / "entrance_post_218_non_pseudotcp_udp_pcap_forensic.py"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


base = _load("p57_base", BASE_PATH)
p55 = _load("p57_p55", P55_PATH)
p57 = _load("p57_module", MODULE_PATH)


def rtp_packet(sequence: int, *, ssrc: int = 0x11223344, pt: int = 96, media_len: int = 20) -> bytes:
    return bytes([
        0x80,
        pt & 0x7F,
        (sequence >> 8) & 0xFF,
        sequence & 0xFF,
        0, 0, 0, 1,
        (ssrc >> 24) & 0xFF,
        (ssrc >> 16) & 0xFF,
        (ssrc >> 8) & 0xFF,
        ssrc & 0xFF,
    ]) + b"x" * media_len


def turn_wrap(inner: bytes, channel: int = 0x4001) -> bytes:
    return channel.to_bytes(2, "big") + len(inner).to_bytes(2, "big") + inner


class P57ContractTest(unittest.TestCase):
    def setUp(self):
        self.client = base.Endpoint(b"\x0a\x00\x00\x01", 10000)
        self.device = base.Endpoint(b"\x0a\x00\x00\x02", 20000)

    def d(self, packet, ts, source, target, payload):
        return p55.SelectedDatagram(packet, ts, source, target, payload)

    def capture(self):
        return (
            self.d(218, 10.000, self.device, self.client, b"boundary"),
            self.d(219, 10.020, self.device, self.client, turn_wrap(rtp_packet(10))),
            self.d(220, 10.040, self.device, self.client, turn_wrap(rtp_packet(11))),
            self.d(221, 10.060, self.device, self.client, b"ABCDEFGH" + rtp_packet(50, ssrc=0x55667788)),
            self.d(222, 10.080, self.device, self.client, b"ABCDEFGH" + rtp_packet(51, ssrc=0x55667788)),
            self.d(223, 10.100, self.client, self.device, b"not-rtp-at-any-small-offset"),
        )

    def test_turn_and_fixed_offset_detection(self):
        result = p57.analyze(self.capture(), client=self.client, device=self.device)
        self.assertEqual(result.opaque_count, 5)
        self.assertEqual(result.turn_shaped_count, 2)
        self.assertEqual(result.turn_inner_rtp_count, 2)
        self.assertEqual(result.turn_inner_rtp_seq_plus1, 1)
        by_offset = {item.offset: item for item in result.offsets}
        self.assertEqual(by_offset[4].shaped_count, 2)
        self.assertEqual(by_offset[4].seq_plus1, 1)
        self.assertEqual(by_offset[8].shaped_count, 2)
        self.assertEqual(by_offset[8].seq_plus1, 1)

    def test_metadata_only_report(self):
        text = p57.report(p57.analyze(self.capture(), client=self.client, device=self.device))
        self.assertIn("TURN_CHANNELDATA_INNER_RTP_COUNT=2", text)
        self.assertIn("TURN_CHANNEL_VALUES_EMITTED=false", text)
        self.assertIn("RAW_PAYLOAD_EMITTED=false", text)
        self.assertIn("H264_INSPECTION_PERFORMED=false", text)
        self.assertIn("NETWORK_IO_PERFORMED=false", text)
        self.assertNotIn("0x4001", text)
        self.assertNotIn("11223344", text)
        self.assertNotIn("55667788", text)
        self.assertNotIn("sequence=", text.lower())

    def test_turn_length_gate_rejects_invalid_wrapper(self):
        inner = rtp_packet(1)
        invalid = (0x4001).to_bytes(2, "big") + (len(inner) + 10).to_bytes(2, "big") + inner
        self.assertIsNone(p57._turn_channeldata(invalid))

    def test_boundary_is_fail_closed(self):
        missing = tuple(item for item in self.capture() if item.packet_number != 218)
        with self.assertRaises(ValueError):
            p57.analyze(missing, client=self.client, device=self.device)

    def test_contract_has_bounded_offsets_and_no_codec_parser(self):
        source = MODULE_PATH.read_text(encoding="utf-8")
        self.assertIn("MAX_RTP_OFFSET = 16", source)
        self.assertIn("TURN_CHANNEL_MIN = 0x4000", source)
        self.assertIn("TURN_CHANNEL_MAX = 0x7FFF", source)
        self.assertNotIn("import av", source)
        self.assertNotIn("ffmpeg", source.lower())
        self.assertNotIn("nal_unit", source.lower())


if __name__ == "__main__":
    unittest.main()
