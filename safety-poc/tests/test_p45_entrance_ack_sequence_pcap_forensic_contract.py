import hashlib
import importlib.util
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
MEDIA_DIR = ROOT / "safety-poc/research/media/v1"
FORENSIC = MEDIA_DIR / "entrance_ack_sequence_pcap_forensic.py"

sys.path.insert(0, str(MEDIA_DIR))
spec = importlib.util.spec_from_file_location(
    "entrance_ack_sequence_pcap_forensic",
    FORENSIC,
)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)

from entrance_device_video_ack_pcap_forensic import VipFrame  # noqa: E402


class P45EntranceAckSequencePcapForensicContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = FORENSIC.read_text(encoding="utf-8")

    @staticmethod
    def _body(length, prefix, sequence, action, first_addr, second_addr, flags=0x0000):
        body = bytearray(length)
        body[0:2] = prefix.to_bytes(2, "little")
        body[2:6] = sequence.to_bytes(4, "little")
        body[6:8] = action.to_bytes(2, "big")
        if length >= 10:
            body[8:10] = flags.to_bytes(2, "big")
        first = length - 20
        second = length - 10
        body[first:first + 9] = first_addr
        body[first + 9] = 0
        body[second:second + 9] = second_addr
        body[second + 9] = 0
        return bytes(body)

    @classmethod
    def _ack_body(cls, sequence, first_addr, second_addr):
        body = bytearray(32)
        body[0:2] = (0x1800).to_bytes(2, "little")
        body[2:6] = sequence.to_bytes(4, "little")
        body[6:8] = b"\x00\x00"
        body[8:12] = b"\xff\xff\xff\xff"
        # Reversed role relative to the device frame.
        body[12:21] = second_addr
        body[21] = 0
        body[22:31] = first_addr
        body[31] = 0
        return bytes(body)

    @staticmethod
    def _frame(direction, packet, timestamp, request_id, body):
        return VipFrame(
            direction=direction,
            first_packet=packet,
            last_packet=packet,
            timestamp=timestamp,
            request_id=request_id,
            body=body,
        )

    def _synthetic_frames(self):
        request_id = 0x12345678
        first_addr = b"ADDRONE01"
        second_addr = b"ADDRTWO02"

        pre_client = self._frame(
            "CLIENT_TO_DEVICE",
            198,
            1.000,
            request_id,
            self._body(40, 0x1840, 0x10000000, 0x0008, second_addr, first_addr, 0x0003),
        )
        anchor_body = self._body(
            40, 0x1840, 0x20000000, 0x0008, first_addr, second_addr, 0x0003
        )
        anchor = self._frame("DEVICE_TO_CLIENT", 200, 1.100, request_id, anchor_body)
        ack1 = self._frame(
            "CLIENT_TO_DEVICE", 201, 1.120, request_id,
            self._ack_body(0x11000000, first_addr, second_addr),
        )
        dev2 = self._frame(
            "DEVICE_TO_CLIENT", 203, 1.300, request_id,
            self._body(36, 0x1840, 0x30000000, 0x0002, first_addr, second_addr, 0x0011),
        )
        ack2 = self._frame(
            "CLIENT_TO_DEVICE", 204, 1.320, request_id,
            self._ack_body(0x12000000, first_addr, second_addr),
        )
        client_event = self._frame(
            "CLIENT_TO_DEVICE", 206, 1.400, request_id,
            self._body(44, 0x1840, 0x13000000, 0x000A, second_addr, first_addr, 0x0011),
        )
        dev3 = self._frame(
            "DEVICE_TO_CLIENT", 209, 1.600, request_id,
            self._body(44, 0x1840, 0x40000000, 0x000A, first_addr, second_addr, 0x0011),
        )
        ack3 = self._frame(
            "CLIENT_TO_DEVICE", 210, 1.620, request_id,
            self._ack_body(0x14000000, first_addr, second_addr),
        )
        return (
            pre_client,
            anchor,
            ack1,
            dev2,
            ack2,
            client_event,
            dev3,
            ack3,
        ), anchor_body

    def test_generic_tail_relation_supports_variable_device_body_lengths(self):
        frames, anchor_body = self._synthetic_frames()
        anchor, _client, bindings = module.analyze(
            frames,
            anchor_body_sha256=hashlib.sha256(anchor_body).hexdigest(),
            anchor_packet=200,
        )
        self.assertEqual(anchor.first_packet, 200)
        self.assertEqual([item.nearest_device.body_length for item in bindings], [40, 36, 44])
        self.assertTrue(all(item.reversed_tail_relation for item in bindings))

    def test_each_ack_binds_to_immediately_preceding_device_frame(self):
        frames, anchor_body = self._synthetic_frames()
        _anchor, _client, bindings = module.analyze(
            frames,
            anchor_body_sha256=hashlib.sha256(anchor_body).hexdigest(),
            anchor_packet=200,
        )
        self.assertEqual(
            [(item.ack.first_packet, item.nearest_device.first_packet) for item in bindings],
            [(201, 200), (204, 203), (210, 209)],
        )
        self.assertTrue(bindings[0].nearest_device_is_anchor)
        self.assertFalse(bindings[1].nearest_device_is_anchor)
        self.assertFalse(bindings[2].nearest_device_is_anchor)
        self.assertTrue(all(item.intervening_same_ctpp_frames == 0 for item in bindings))

    def test_client_sequence_deltas_are_reported_without_sequence_values(self):
        frames, anchor_body = self._synthetic_frames()
        anchor, client, bindings = module.analyze(
            frames,
            anchor_body_sha256=hashlib.sha256(anchor_body).hexdigest(),
            anchor_packet=200,
        )
        output = module.report(anchor, client, bindings)
        self.assertIn("ANCHOR_IMMEDIATE_ACK_CANDIDATE_COUNT=1", output)
        self.assertIn("sequence_delta_prev_client=0x01000000", output)
        self.assertIn("sequence_delta_prev_ack=0x01000000", output)
        self.assertIn("ACK_SEQUENCE_VALUES_EMITTED=false", output)
        self.assertIn("ACK_SEQUENCE_DELTAS_EMITTED=true", output)
        for literal in ("0x10000000", "0x11000000", "0x12000000", "0x13000000", "0x14000000"):
            self.assertNotIn(literal, output)

    def test_frozen_capture_and_anchor_identity_remain_pinned(self):
        self.assertEqual(
            module.EXPECTED_PCAP_SHA256,
            "f15bb1922f55237bfaeb570bd288f7023e0196c05e878dfdaa76ad165bbc044a",
        )
        self.assertEqual(module.DEVICE_VIDEO_PCAP_PACKET, 200)
        self.assertEqual(
            module.DEVICE_VIDEO_BODY_SHA256,
            "fbb8884012c7b6f0202a2a1418ffaf0ac06b5cbfe66a823b4d7780e559c4b02b",
        )

    def test_output_contract_is_private_and_offline_only(self):
        for marker in (
            "ACK_SEQUENCE_VALUES_EMITTED=false",
            "ACK_BYTES_EMITTED=false",
            "REQUEST_ID_EMITTED=false",
            "ENDPOINTS_EMITTED=false",
            "PROTOCOL_ADDRESSES_EMITTED=false",
            "RAW_PAYLOAD_EMITTED=false",
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
            "subprocess",
            "urllib.request",
            "os.system",
            "os.kill",
            "print(frame.body",
            "payload.hex()",
            "base64",
        ):
            self.assertNotIn(forbidden, self.text)


if __name__ == "__main__":
    unittest.main()
