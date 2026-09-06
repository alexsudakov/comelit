import hashlib
import importlib.util
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
MEDIA_DIR = ROOT / "safety-poc/research/media/v1"
FORENSIC = MEDIA_DIR / "entrance_device_video_ack_pcap_forensic.py"

sys.path.insert(0, str(MEDIA_DIR))
spec = importlib.util.spec_from_file_location(
    "entrance_device_video_ack_pcap_forensic",
    FORENSIC,
)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)

from pseudotcp_pcap_handshake_forensic import (  # noqa: E402
    Endpoint,
    FlowAnalysis,
    PseudoTcpSegment,
)


class P42EntranceDeviceVideoAckPcapForensicContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = FORENSIC.read_text(encoding="utf-8")

    @staticmethod
    def _segment(packet, timestamp, source, target, sequence, data):
        return PseudoTcpSegment(
            packet_number=packet,
            timestamp=timestamp,
            source=source,
            target=target,
            wire_length=24 + len(data),
            sequence=sequence,
            acknowledgment=0,
            control=0,
            flags=0,
            window=65535,
            data=data,
        )

    @staticmethod
    def _vip_frame(request_id, body):
        return (
            b"\x00\x06"
            + len(body).to_bytes(2, "little")
            + request_id.to_bytes(4, "little")
            + body
        )

    def _synthetic_analysis(self):
        client = Endpoint(b"\x01\x01\x01\x01", 1111)
        device = Endpoint(b"\x02\x02\x02\x02", 2222)
        request_id = 0x12345678

        device_body = bytearray(40)
        device_body[0:2] = (0x1840).to_bytes(2, "little")
        device_body[2:6] = (0x11223344).to_bytes(4, "little")
        device_body[6:8] = b"\x00\x08"
        device_body[8:10] = b"\x00\x03"
        device_body[16:20] = b"\xff\xff\xff\xff"
        device_body[20:28] = b"ENTRANCE"
        device_body[28:30] = b"\x00\x00"
        device_body[30:39] = b"FULLADDR9"
        device_body[39] = 0

        ack_body = bytearray(32)
        ack_body[0:2] = (0x1800).to_bytes(2, "little")
        ack_body[2:6] = (0x11233344).to_bytes(4, "little")
        ack_body[6:8] = b"\x00\x00"
        ack_body[8:12] = b"\xff\xff\xff\xff"
        ack_body[12:20] = device_body[20:28]
        ack_body[20:22] = b"\x00\x00"
        ack_body[22:31] = device_body[30:39]
        ack_body[31] = 0

        device_frame = self._vip_frame(request_id, bytes(device_body))
        ack_frame = self._vip_frame(request_id, bytes(ack_body))

        segments = (
            self._segment(199, 6.250, device, client, 5000, device_frame[:19]),
            self._segment(200, 6.260, device, client, 5019, device_frame[19:]),
            self._segment(201, 6.300, client, device, 9000, ack_frame[:17]),
            self._segment(202, 6.310, client, device, 9017, ack_frame[17:]),
            # Exact transport retransmission: must be deduplicated, not counted
            # as a second application ACK.
            self._segment(203, 6.320, client, device, 9000, ack_frame[:17]),
        )
        analysis = FlowAnalysis(
            segments=segments,
            client=client,
            device=device,
            anchor_hits_client=1,
            anchor_hits_device=0,
        )
        return analysis, bytes(device_body), bytes(ack_body), request_id

    def test_frozen_capture_identity_and_anchor_are_pinned(self):
        self.assertEqual(
            module.EXPECTED_PCAP_SHA256,
            "f15bb1922f55237bfaeb570bd288f7023e0196c05e878dfdaa76ad165bbc044a",
        )
        self.assertEqual(
            module.DEVICE_VIDEO_BODY_SHA256,
            "fbb8884012c7b6f0202a2a1418ffaf0ac06b5cbfe66a823b4d7780e559c4b02b",
        )
        self.assertEqual(module.DEVICE_VIDEO_PCAP_PACKET, 200)
        self.assertLess(module.WINDOW_START_PACKET, 200)
        self.assertGreater(module.WINDOW_END_PACKET, 200)

    def test_fragmented_frame_is_reassembled_and_transport_retransmit_deduped(self):
        analysis, device_body, _ack_body, _request_id = self._synthetic_analysis()
        frames = module.collect_vip_frames(analysis)
        evidence = module.derive_ack_evidence(
            frames,
            anchor_body_sha256=hashlib.sha256(device_body).hexdigest(),
        )

        self.assertEqual(evidence.anchor.first_packet, 199)
        self.assertEqual(evidence.anchor.last_packet, 200)
        self.assertEqual(len(evidence.candidates), 1)
        self.assertEqual(len(evidence.matching_acks), 1)
        self.assertEqual(evidence.matching_acks[0].first_packet, 201)
        self.assertEqual(evidence.matching_acks[0].last_packet, 202)

    def test_ack_shape_address_relation_and_sequence_delta_are_structural_only(self):
        analysis, device_body, ack_body, request_id = self._synthetic_analysis()
        evidence = module.derive_ack_evidence(
            module.collect_vip_frames(analysis),
            anchor_body_sha256=hashlib.sha256(device_body).hexdigest(),
        )
        ack = evidence.matching_acks[0]

        self.assertTrue(module._is_structural_ack(ack))
        self.assertTrue(module._address_relation_matches(evidence.anchor, ack))
        self.assertEqual(module._sequence_delta(evidence.anchor, ack), 0x00010000)
        self.assertEqual(ack.body_sha256, hashlib.sha256(ack_body).hexdigest())

        output = module.report(evidence)
        self.assertIn("OFFICIAL_CLIENT_DEVICE_VIDEO_ACK=PROVEN", output)
        self.assertIn("ACK_SEQUENCE_DELTA=0x00010000", output)
        self.assertIn("ACK_ADDRESS_RELATION_MATCH=true", output)
        self.assertIn("CAPTURE_DERIVED_ACK_CONTRACT=PASS", output)
        self.assertNotIn(str(request_id), output)
        self.assertNotIn("ENTRANCE", output)
        self.assertNotIn("FULLADDR9", output)

    def test_conflicting_retransmission_fails_closed(self):
        analysis, _device_body, _ack_body, _request_id = self._synthetic_analysis()
        client = analysis.client
        device = analysis.device
        bad = self._segment(204, 6.330, client, device, 9000, b"X")
        corrupted = FlowAnalysis(
            segments=analysis.segments + (bad,),
            client=client,
            device=device,
            anchor_hits_client=1,
            anchor_hits_device=0,
        )
        with self.assertRaisesRegex(ValueError, "conflicting retransmission"):
            module.collect_vip_frames(corrupted)

    def test_output_contract_never_emits_payload_or_endpoints(self):
        for marker in (
            "REQUEST_ID_EMITTED=false",
            "ENDPOINTS_EMITTED=false",
            "PROTOCOL_ADDRESSES_EMITTED=false",
            "RAW_PAYLOAD_EMITTED=false",
            "MEDIA_PAYLOAD_EMITTED=false",
            "NETWORK_IO_PERFORMED=false",
            "DOOR_ACTION_SENT=false",
            "MEDIA_SIGNALING_SENT=false",
        ):
            self.assertIn(marker, self.text)

        for forbidden in (
            "print(frame.body",
            "print(ack.body",
            "payload.hex()",
            "base64",
            "source.address",
            "target.address",
        ):
            self.assertNotIn(forbidden, self.text)

    def test_forensic_is_offline_only(self):
        for forbidden in (
            "import socket",
            "import requests",
            "import aiohttp",
            "subprocess",
            "urllib.request",
            "os.system",
            "os.kill",
        ):
            self.assertNotIn(forbidden, self.text)

        self.assertIn("load_capture(args.pcap)", self.text)
        self.assertIn("capture.sha256 != args.expected_sha256.lower()", self.text)
        self.assertIn("select_vip_flow(capture)", self.text)


if __name__ == "__main__":
    unittest.main()
