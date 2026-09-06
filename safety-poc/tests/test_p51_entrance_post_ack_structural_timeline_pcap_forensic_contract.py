import hashlib
import importlib.util
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
MEDIA_DIR = ROOT / "safety-poc/research/media/v1"
FORENSIC = MEDIA_DIR / "entrance_post_ack_structural_timeline_pcap_forensic.py"

sys.path.insert(0, str(MEDIA_DIR))
spec = importlib.util.spec_from_file_location(
    "entrance_post_ack_structural_timeline_pcap_forensic",
    FORENSIC,
)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)

from entrance_device_video_ack_pcap_forensic import VipFrame  # noqa: E402


class P51EntrancePostAckStructuralTimelinePcapForensicContract(unittest.TestCase):
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
        return body

    @classmethod
    def _device_frame(
        cls,
        packet,
        timestamp,
        request_id,
        *,
        length,
        sequence,
        action,
        flags,
        first_addr=b"DEVADDR01",
        second_addr=b"CLIENT001",
    ):
        body = cls._body(length, 0x1840, sequence, action, flags)
        if length >= 20:
            first = length - 20
            second = length - 10
            body[first:first + 9] = first_addr
            body[first + 9] = 0
            body[second:second + 9] = second_addr
            body[second + 9] = 0
        return VipFrame(
            direction="DEVICE_TO_CLIENT",
            first_packet=packet,
            last_packet=packet,
            timestamp=timestamp,
            request_id=request_id,
            body=bytes(body),
        )

    @classmethod
    def _client_frame(
        cls,
        packet,
        timestamp,
        request_id,
        *,
        length,
        prefix,
        sequence,
        action,
        flags,
    ):
        return VipFrame(
            direction="CLIENT_TO_DEVICE",
            first_packet=packet,
            last_packet=packet,
            timestamp=timestamp,
            request_id=request_id,
            body=bytes(cls._body(length, prefix, sequence, action, flags)),
        )

    @classmethod
    def _ack_for(cls, device, packet, timestamp, sequence):
        body = cls._body(32, 0x1800, sequence, 0x0000, 0xFFFF)
        body[8:12] = b"\xff\xff\xff\xff"
        source = device.body
        first = len(source) - 20
        second = len(source) - 10
        body[12:21] = source[second:second + 9]
        body[21] = 0
        body[22:31] = source[first:first + 9]
        body[31] = 0
        return VipFrame(
            direction="CLIENT_TO_DEVICE",
            first_packet=packet,
            last_packet=packet,
            timestamp=timestamp,
            request_id=device.request_id,
            body=bytes(body),
        )

    def _synthetic(self):
        ctpp = 77
        anchor = self._device_frame(
            200, 10.000, ctpp,
            length=40,
            sequence=0x10000000,
            action=0x0008,
            flags=0x0003,
        )
        anchor_hash = hashlib.sha256(anchor.body).hexdigest()
        ack0 = self._ack_for(anchor, 201, 10.020, 0x11000000)

        event2 = self._device_frame(
            203, 10.208, ctpp,
            length=36,
            sequence=0x12000000,
            action=0x0002,
            flags=0x000C,
        )
        ack2 = self._ack_for(event2, 204, 10.228, 0x12000000)

        control = self._client_frame(
            206, 10.332, 0,
            length=15,
            prefix=0xABCD,
            sequence=0,
            action=0x0000,
            flags=0x5254,
        )
        command_a = self._client_frame(
            206, 10.332, ctpp,
            length=44,
            prefix=0x1840,
            sequence=0x12000000,
            action=0x000A,
            flags=0x0011,
        )
        response_a = self._device_frame(
            209, 10.500, ctpp,
            length=36,
            sequence=0x13000000,
            action=0x0003,
            flags=0x000C,
        )
        ack_a = self._ack_for(response_a, 210, 10.520, 0x13000000)
        command_b = self._client_frame(
            212, 10.645, ctpp,
            length=60,
            prefix=0x1840,
            sequence=0x13010000,
            action=0x001A,
            flags=0x0011,
        )
        new_channel = self._client_frame(
            220, 10.900, 88,
            length=12,
            prefix=0x2200,
            sequence=0x01020304,
            action=0x0005,
            flags=0x0001,
        )

        return (
            anchor,
            ack0,
            event2,
            ack2,
            control,
            command_a,
            response_a,
            ack_a,
            command_b,
            new_channel,
        ), anchor_hash

    def test_frozen_identity_and_timeline_window_are_pinned(self):
        self.assertEqual(
            module.EXPECTED_PCAP_SHA256,
            "f15bb1922f55237bfaeb570bd288f7023e0196c05e878dfdaa76ad165bbc044a",
        )
        self.assertEqual(module.TIMELINE_START_PACKET, 200)
        self.assertEqual(module.TIMELINE_END_PACKET, 240)
        self.assertEqual(module.DEVICE_VIDEO_PCAP_PACKET, 200)

    def test_timeline_contains_both_directions_in_capture_order(self):
        frames, anchor_hash = self._synthetic()
        result = module.analyze(
            frames,
            anchor_body_sha256=anchor_hash,
            anchor_packet=200,
        )
        packets = [item.frame.first_packet for item in result.frames]
        self.assertEqual(packets, [200, 201, 203, 204, 206, 206, 209, 210, 212, 220])
        directions = {item.frame.direction for item in result.frames}
        self.assertEqual(directions, {"CLIENT_TO_DEVICE", "DEVICE_TO_CLIENT"})

    def test_ack_bindings_use_nearest_device_and_reversed_address_relation(self):
        frames, anchor_hash = self._synthetic()
        result = module.analyze(
            frames,
            anchor_body_sha256=anchor_hash,
            anchor_packet=200,
        )
        self.assertEqual(len(result.ack_bindings), 3)
        self.assertEqual(
            [(b.ack.first_packet, b.nearest_device.first_packet) for b in result.ack_bindings],
            [(201, 200), (204, 203), (210, 209)],
        )
        self.assertTrue(all(b.reversed_tail_relation for b in result.ack_bindings))
        self.assertTrue(all(b.intervening_same_ctpp_frames == 0 for b in result.ack_bindings))

    def test_client_commands_and_new_channel_are_structurally_visible(self):
        frames, anchor_hash = self._synthetic()
        result = module.analyze(
            frames,
            anchor_body_sha256=anchor_hash,
            anchor_packet=200,
        )
        output = module.report(result)
        self.assertIn("packet_first=206", output)
        self.assertIn("action=0x000a", output)
        self.assertIn("packet_first=209", output)
        self.assertIn("action=0x0003", output)
        self.assertIn("ack_packet_first=210", output)
        self.assertIn("nearest_device_packet_first=209", output)
        self.assertIn("packet_first=212", output)
        self.assertIn("action=0x001a", output)
        self.assertIn("channel=OTHER_NEW", output)
        self.assertIn("FIRST_NEW_CHANNEL_FRAME", output)

    def test_sequence_values_are_not_reported(self):
        frames, anchor_hash = self._synthetic()
        result = module.analyze(
            frames,
            anchor_body_sha256=anchor_hash,
            anchor_packet=200,
        )
        output = module.report(result)
        self.assertIn("SEQUENCE_VALUES_EMITTED=false", output)
        self.assertIn("SEQUENCE_DELTAS_EMITTED=true", output)
        self.assertIn("sequence_delta_prev_same_ctpp_direction=", output)
        for literal in (
            "0x10000000",
            "0x11000000",
            "0x12000000",
            "0x13000000",
            "0x13010000",
            "request_id=77",
            "request_id=88",
        ):
            self.assertNotIn(literal, output)

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
            "b64encode",
            "b64decode",
            "payload.hex(",
            "frame.body.hex(",
            "print(frame.body",
        ):
            self.assertNotIn(forbidden, self.text)

        self.assertIn("load_capture(args.pcap)", self.text)
        self.assertIn("collect_extended_vip_frames(analysis)", self.text)
        self.assertIn("_reversed_tail_address_relation(nearest, frame)", self.text)


if __name__ == "__main__":
    unittest.main()
