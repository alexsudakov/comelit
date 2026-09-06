import hashlib
import importlib.util
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
MEDIA_DIR = ROOT / "safety-poc/research/media/v1"
FORENSIC = MEDIA_DIR / "entrance_post_ack_0002_pcap_forensic.py"
sys.path.insert(0, str(MEDIA_DIR))

spec = importlib.util.spec_from_file_location("p50_forensic", FORENSIC)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)

from entrance_device_video_ack_pcap_forensic import VipFrame  # noqa: E402


class P50EntrancePostAck0002PcapForensicContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = FORENSIC.read_text(encoding="utf-8")

    @staticmethod
    def _body(length, prefix, sequence, action, flags):
        body = bytearray(length)
        body[0:2] = prefix.to_bytes(2, "little")
        body[2:6] = sequence.to_bytes(4, "little")
        body[6:8] = action.to_bytes(2, "big")
        body[8:10] = flags.to_bytes(2, "big")
        return bytes(body)

    @classmethod
    def _frame(cls, direction, packet, timestamp, request_id, length, prefix, sequence, action, flags):
        return VipFrame(
            direction=direction,
            first_packet=packet,
            last_packet=packet,
            timestamp=timestamp,
            request_id=request_id,
            body=cls._body(length, prefix, sequence, action, flags),
        )

    @classmethod
    def _ack(cls, packet, timestamp, request_id, sequence):
        body = bytearray(cls._body(32, 0x1800, sequence, 0x0000, 0xFFFF))
        body[8:12] = b"\xff\xff\xff\xff"
        return VipFrame(
            direction="CLIENT_TO_DEVICE",
            first_packet=packet,
            last_packet=packet,
            timestamp=timestamp,
            request_id=request_id,
            body=bytes(body),
        )

    def _synthetic(self):
        ctpp = 77
        anchor = self._frame("DEVICE_TO_CLIENT", 200, 10.000, ctpp, 40, 0x1840, 0x10000000, 0x0008, 0x0003)
        frames = [anchor, self._ack(201, 10.020, ctpp, 0x11000000)]
        frames += [
            self._frame("DEVICE_TO_CLIENT", 203, 10.100, ctpp, 36, 0x1840, 0x12000000, 0x0002, 0x000C),
            self._ack(204, 10.120, ctpp, 0x12010000),
            self._frame("CLIENT_TO_DEVICE", 205, 10.140, 0, 15, 0x0600, 0, 0, 0),
            self._frame("DEVICE_TO_CLIENT", 209, 10.300, ctpp, 36, 0x1840, 0x13000000, 0x0002, 0x000C),
            self._ack(210, 10.320, ctpp, 0x13010000),
            self._frame("CLIENT_TO_DEVICE", 211, 10.340, 88, 12, 0x2200, 0x01020304, 0x0005, 0x0001),
            self._frame("DEVICE_TO_CLIENT", 215, 10.500, ctpp, 36, 0x1840, 0x14000000, 0x0002, 0x000C),
            self._ack(216, 10.520, ctpp, 0x14010000),
        ]
        return tuple(frames), hashlib.sha256(anchor.body).hexdigest()

    def test_frozen_identity_and_window_are_pinned(self):
        self.assertEqual(
            module.EXPECTED_PCAP_SHA256,
            "f15bb1922f55237bfaeb570bd288f7023e0196c05e878dfdaa76ad165bbc044a",
        )
        self.assertEqual((module.WINDOW_START_PACKET, module.WINDOW_END_PACKET), (160, 360))
        self.assertLess(module.WINDOW_START_PACKET, module.DEVICE_VIDEO_PCAP_PACKET)
        self.assertGreater(module.WINDOW_END_PACKET, module.DEVICE_VIDEO_PCAP_PACKET)

    def test_exact_p49_shape_and_response_partition(self):
        frames, anchor_hash = self._synthetic()
        result = module.analyze(frames, anchor_body_sha256=anchor_hash, anchor_packet=200)
        self.assertEqual(len(result.events), 3)
        for exchange in result.events:
            event = exchange.event
            self.assertEqual((event.body_length, event.prefix, event.action, event.flags), (36, 0x1840, 0x0002, 0x000C))
            self.assertEqual(event.direction, "DEVICE_TO_CLIENT")

        first, second, third = result.events
        self.assertEqual([r.frame.first_packet for r in first.responses], [204, 205])
        self.assertEqual([r.channel_class for r in first.responses], ["CTPP", "CONTROL"])
        self.assertTrue(first.responses[0].structural_ack)
        self.assertEqual([r.frame.first_packet for r in second.responses], [210, 211])
        self.assertEqual([r.channel_class for r in second.responses], ["CTPP", "OTHER"])
        self.assertTrue(second.responses[1].new_channel_after_anchor)
        self.assertEqual([r.frame.first_packet for r in third.responses], [216])
        self.assertTrue(third.responses[0].structural_ack)

    def test_report_exposes_only_structural_metadata_and_deltas(self):
        frames, anchor_hash = self._synthetic()
        output = module.report(module.analyze(frames, anchor_body_sha256=anchor_hash, anchor_packet=200))
        for marker in (
            "POST_ACK_0002_EVENT_COUNT=3",
            "channel=CTPP",
            "channel=CONTROL",
            "channel=OTHER",
            "new_channel_after_anchor=true",
            "SEQUENCE_VALUES_EMITTED=false",
            "SEQUENCE_DELTAS_EMITTED=true",
        ):
            self.assertIn(marker, output)
        for literal in ("0x11000000", "0x12010000", "0x13010000", "0x14010000", "request_id=77", "request_id=88"):
            self.assertNotIn(literal, output)

    def test_no_matching_event_fails_closed(self):
        frames, anchor_hash = self._synthetic()
        frames = tuple(f for f in frames if not (f.direction == "DEVICE_TO_CLIENT" and f.action == 0x0002))
        with self.assertRaisesRegex(ValueError, "no post-anchor"):
            module.analyze(frames, anchor_body_sha256=anchor_hash, anchor_packet=200)

    def test_privacy_and_offline_source_contract(self):
        for marker in (
            "REQUEST_ID_EMITTED=false",
            "ENDPOINTS_EMITTED=false",
            "PROTOCOL_ADDRESSES_EMITTED=false",
            "SEQUENCE_VALUES_EMITTED=false",
            "RAW_PAYLOAD_EMITTED=false",
            "HEX_PAYLOAD_EMITTED=false",
            "BASE64_PAYLOAD_EMITTED=false",
            "MEDIA_PAYLOAD_EMITTED=false",
            "NETWORK_IO_PERFORMED=false",
            "DOOR_ACTION_SENT=false",
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
            "os.kill",
            "payload.hex()",
            "import base64",
            ".b64encode(",
            ".b64decode(",
            "print(frame.body",
            "print(response.frame.body",
        ):
            self.assertNotIn(forbidden, self.text)

        self.assertIn("load_capture(args.pcap)", self.text)
        self.assertIn("p42.collect_vip_frames(analysis)", self.text)
        self.assertIn("p42.WINDOW_END_PACKET = WINDOW_END_PACKET", self.text)


if __name__ == "__main__":
    unittest.main()
