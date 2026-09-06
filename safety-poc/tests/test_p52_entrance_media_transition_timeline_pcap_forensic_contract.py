import hashlib
import importlib.util
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
MEDIA_DIR = ROOT / "safety-poc/research/media/v1"
FORENSIC = MEDIA_DIR / "entrance_media_transition_timeline_pcap_forensic.py"

sys.path.insert(0, str(MEDIA_DIR))
spec = importlib.util.spec_from_file_location(
    "entrance_media_transition_timeline_pcap_forensic",
    FORENSIC,
)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)

from entrance_device_video_ack_pcap_forensic import VipFrame  # noqa: E402


ADDR_A = b"ADDR00001"
ADDR_B = b"ADDR00002"


class P52EntranceMediaTransitionTimelineContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = FORENSIC.read_text(encoding="utf-8")

    @staticmethod
    def _event_body(length, prefix, sequence, action, flags, first=ADDR_A, second=ADDR_B):
        body = bytearray(length)
        body[0:2] = prefix.to_bytes(2, "little")
        body[2:6] = sequence.to_bytes(4, "little")
        body[6:8] = action.to_bytes(2, "big")
        body[8:10] = flags.to_bytes(2, "big")
        if length >= 30:
            body[length - 20 : length - 11] = first
            body[length - 11] = 0
            body[length - 10 : length - 1] = second
            body[length - 1] = 0
        return bytes(body)

    @classmethod
    def _frame(
        cls,
        direction,
        packet,
        timestamp,
        request_id,
        *,
        length,
        prefix,
        sequence,
        action,
        flags,
        first=ADDR_A,
        second=ADDR_B,
    ):
        return VipFrame(
            direction=direction,
            first_packet=packet,
            last_packet=packet,
            timestamp=timestamp,
            request_id=request_id,
            body=cls._event_body(
                length, prefix, sequence, action, flags, first=first, second=second
            ),
        )

    @classmethod
    def _ack(cls, direction, packet, timestamp, request_id, sequence, source):
        source_body = source.body
        first = source_body[len(source_body) - 20 : len(source_body) - 11]
        second = source_body[len(source_body) - 10 : len(source_body) - 1]
        body = bytearray(32)
        body[0:2] = (0x1800).to_bytes(2, "little")
        body[2:6] = sequence.to_bytes(4, "little")
        body[6:8] = (0x0000).to_bytes(2, "big")
        body[8:12] = b"\xff\xff\xff\xff"
        body[12:21] = second
        body[21] = 0
        body[22:31] = first
        body[31] = 0
        return VipFrame(
            direction=direction,
            first_packet=packet,
            last_packet=packet,
            timestamp=timestamp,
            request_id=request_id,
            body=bytes(body),
        )

    def _synthetic(self):
        ctpp = 77
        anchor = self._frame(
            "DEVICE_TO_CLIENT",
            200,
            10.000,
            ctpp,
            length=40,
            prefix=0x1840,
            sequence=0x10000000,
            action=0x0008,
            flags=0x0003,
        )
        ack_200 = self._ack(
            "CLIENT_TO_DEVICE", 201, 10.020, ctpp, 0x11000000, anchor
        )
        event_0002 = self._frame(
            "DEVICE_TO_CLIENT",
            203,
            10.208,
            ctpp,
            length=36,
            prefix=0x1840,
            sequence=0x10010000,
            action=0x0002,
            flags=0x000C,
        )
        ack_0002 = self._ack(
            "CLIENT_TO_DEVICE", 204, 10.228, ctpp, 0x12000000, event_0002
        )
        client_000a = self._frame(
            "CLIENT_TO_DEVICE",
            206,
            10.332,
            ctpp,
            length=44,
            prefix=0x1840,
            sequence=0x12000000,
            action=0x000A,
            flags=0x0011,
        )
        device_000a = self._frame(
            "DEVICE_TO_CLIENT",
            209,
            10.532,
            ctpp,
            length=44,
            prefix=0x1840,
            sequence=0x10020000,
            action=0x000A,
            flags=0x0011,
        )
        client_ack_000a = self._ack(
            "CLIENT_TO_DEVICE", 210, 10.553, ctpp, 0x13000000, device_000a
        )
        device_ack_000a = self._ack(
            "DEVICE_TO_CLIENT", 211, 10.624, ctpp, 0x11020000, client_000a
        )
        client_001a = self._frame(
            "CLIENT_TO_DEVICE",
            212,
            10.645,
            ctpp,
            length=60,
            prefix=0x1840,
            sequence=0x13010000,
            action=0x001A,
            flags=0x0011,
        )
        device_ack_001a = self._ack(
            "DEVICE_TO_CLIENT", 218, 10.808, ctpp, 0x14030000, client_001a
        )
        new_channel = self._frame(
            "DEVICE_TO_CLIENT",
            230,
            11.000,
            88,
            length=12,
            prefix=0x2200,
            sequence=0x01020304,
            action=0x0005,
            flags=0x0001,
        )
        return (
            anchor,
            ack_200,
            event_0002,
            ack_0002,
            client_000a,
            device_000a,
            client_ack_000a,
            device_ack_000a,
            client_001a,
            device_ack_001a,
            new_channel,
        ), hashlib.sha256(anchor.body).hexdigest()

    def test_frozen_capture_and_extended_window_are_pinned(self):
        self.assertEqual(
            module.EXPECTED_PCAP_SHA256,
            "f15bb1922f55237bfaeb570bd288f7023e0196c05e878dfdaa76ad165bbc044a",
        )
        self.assertEqual(module.TIMELINE_START_PACKET, 200)
        self.assertEqual(module.TIMELINE_END_PACKET, 360)

    def test_bidirectional_ack_bindings_skip_intervening_ack_shapes(self):
        frames, anchor_hash = self._synthetic()
        result = module.analyze(
            frames,
            anchor_body_sha256=anchor_hash,
            anchor_packet=200,
        )
        pairs = [
            (
                binding.ack.first_packet,
                binding.source_frame.first_packet,
                binding.source_frame.direction,
                binding.source_frame.action,
            )
            for binding in result.ack_bindings
        ]
        self.assertEqual(
            pairs,
            [
                (201, 200, "DEVICE_TO_CLIENT", 0x0008),
                (204, 203, "DEVICE_TO_CLIENT", 0x0002),
                (210, 209, "DEVICE_TO_CLIENT", 0x000A),
                (211, 206, "CLIENT_TO_DEVICE", 0x000A),
                (218, 212, "CLIENT_TO_DEVICE", 0x001A),
            ],
        )
        self.assertTrue(all(binding.reversed_tail_relation for binding in result.ack_bindings))

    def test_extended_timeline_exposes_client_actions_and_new_channel(self):
        frames, anchor_hash = self._synthetic()
        result = module.analyze(
            frames,
            anchor_body_sha256=anchor_hash,
            anchor_packet=200,
        )
        output = module.report(result)
        self.assertIn("source_action=0x000a", output)
        self.assertIn("source_action=0x001a", output)
        self.assertIn("ack_direction=DEVICE_TO_CLIENT", output)
        self.assertIn("ack_direction=CLIENT_TO_DEVICE", output)
        self.assertIn("FIRST_NEW_CHANNEL_FRAME direction=DEVICE_TO_CLIENT packet_first=230", output)
        self.assertIn("FIRST_FRAME_AFTER_PACKET_218 direction=DEVICE_TO_CLIENT packet_first=230", output)
        self.assertIn("channel=OTHER_NEW", output)

    def test_sequence_values_are_not_emitted(self):
        frames, anchor_hash = self._synthetic()
        result = module.analyze(
            frames,
            anchor_body_sha256=anchor_hash,
            anchor_packet=200,
        )
        output = module.report(result)
        self.assertIn("SEQUENCE_VALUES_EMITTED=false", output)
        self.assertIn("SEQUENCE_DELTAS_EMITTED=true", output)
        for literal in (
            "0x10000000",
            "0x12000000",
            "0x13010000",
            "request_id=77",
            "request_id=88",
        ):
            self.assertNotIn(literal, output)

    def test_missing_anchor_fails_closed(self):
        frames, anchor_hash = self._synthetic()
        with self.assertRaisesRegex(ValueError, "device-video anchor"):
            module.analyze(
                frames[1:],
                anchor_body_sha256=anchor_hash,
                anchor_packet=200,
            )

    def test_output_privacy_and_offline_contract(self):
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
            "os.kill",
            "import base64",
            "payload.hex()",
            "print(frame.body",
        ):
            self.assertNotIn(forbidden, self.text)

        self.assertIn("load_capture(args.pcap)", self.text)
        self.assertIn("collect_extended_vip_frames(analysis)", self.text)


if __name__ == "__main__":
    unittest.main()
