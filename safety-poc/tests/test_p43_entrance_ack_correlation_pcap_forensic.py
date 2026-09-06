import hashlib
import importlib.util
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
MEDIA_DIR = ROOT / "safety-poc/research/media/v1"
FORENSIC = MEDIA_DIR / "entrance_ack_correlation_pcap_forensic.py"

sys.path.insert(0, str(MEDIA_DIR))
spec = importlib.util.spec_from_file_location(
    "entrance_ack_correlation_pcap_forensic",
    FORENSIC,
)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


class P43EntranceAckCorrelationPcapForensic(unittest.TestCase):
    def _frame(
        self,
        *,
        direction,
        packet,
        timestamp,
        request_id,
        body,
    ):
        return module.VipFrame(
            direction=direction,
            first_packet=packet,
            last_packet=packet,
            timestamp=timestamp,
            request_id=request_id,
            body=bytes(body),
        )

    def _synthetic_pair(self):
        device = bytearray(40)
        device[0:2] = (0x1840).to_bytes(2, "little")
        device[2:6] = (0x10203040).to_bytes(4, "little")
        device[6:8] = (0x0008).to_bytes(2, "big")
        device[8:10] = (0x0003).to_bytes(2, "big")
        device[10:12] = b"XY"
        device[12:20] = b"ABCDEFGH"
        device[20:28] = b"ijklmnop"
        device[28:37] = b"123456789"
        device[37:40] = b"QRS"

        ack = bytearray(32)
        ack[0:2] = (0x1800).to_bytes(2, "little")
        ack[2:6] = (0x10203040).to_bytes(4, "little")
        ack[6:8] = (0x0000).to_bytes(2, "big")
        ack[8:12] = b"\xff\xff\xff\xff"
        # Deliberately match different source offsets than the relation assumed
        # by P42: this exercises offset discovery without revealing values.
        ack[12:20] = device[12:20]
        ack[20:22] = b"\x00\x00"
        ack[22:31] = device[28:37]
        ack[31] = 0

        anchor = self._frame(
            direction="DEVICE_TO_CLIENT",
            packet=200,
            timestamp=1.0,
            request_id=77,
            body=device,
        )
        client_ack = self._frame(
            direction="CLIENT_TO_DEVICE",
            packet=201,
            timestamp=1.02,
            request_id=77,
            body=ack,
        )
        return anchor, client_ack

    def test_discovers_offset_relations_and_sequence_equality(self):
        anchor, ack = self._synthetic_pair()
        relation = module.relation(anchor, ack)

        self.assertTrue(relation.sequence_equal)
        self.assertEqual(relation.sequence_delta, 0)
        self.assertIn((12, 12), relation.matches8)
        self.assertIn((28, 22), relation.matches9)

    def test_correlates_structural_ack_with_frozen_anchor_contract(self):
        anchor, ack = self._synthetic_pair()
        old_hash = module.DEVICE_VIDEO_BODY_SHA256
        old_packet = module.DEVICE_VIDEO_PCAP_PACKET
        try:
            module.DEVICE_VIDEO_BODY_SHA256 = hashlib.sha256(anchor.body).hexdigest()
            module.DEVICE_VIDEO_PCAP_PACKET = 200
            found_anchor, correlations = module.correlate((anchor, ack))
        finally:
            module.DEVICE_VIDEO_BODY_SHA256 = old_hash
            module.DEVICE_VIDEO_PCAP_PACKET = old_packet

        self.assertEqual(found_anchor, anchor)
        self.assertEqual(len(correlations), 1)
        self.assertEqual(correlations[0].ack, ack)
        self.assertTrue(correlations[0].anchor_relation.sequence_equal)

    def test_report_emits_metadata_not_addresses_or_payload(self):
        anchor, ack = self._synthetic_pair()
        item = module.AckCorrelation(
            ack=ack,
            anchor_relation=module.relation(anchor, ack),
            preceding_relations=(module.relation(anchor, ack),),
        )
        output = module.report(anchor, (item,))

        self.assertIn("STRUCTURAL_ACK_COUNT=1", output)
        self.assertIn("sequence_equal=true", output)
        self.assertIn("match8_offsets=", output)
        self.assertIn("match9_offsets=", output)
        self.assertIn("ACK_BYTES_EMITTED=false", output)
        self.assertIn("PROTOCOL_ADDRESSES_EMITTED=false", output)
        self.assertIn("RAW_PAYLOAD_EMITTED=false", output)
        self.assertIn("NETWORK_IO_PERFORMED=false", output)
        self.assertIn("ACK_SIGNALING_SENT=false", output)

        for secret in (
            "ABCDEFGH",
            "ijklmnop",
            "123456789",
            "request_id=77",
        ):
            self.assertNotIn(secret, output)

    def test_constant_padding_does_not_create_slice_matches(self):
        source = b"\x00" * 40
        ack = b"\x00" * 32
        self.assertEqual(module.equal_slice_offsets(source, ack, 8), ())
        self.assertEqual(module.equal_slice_offsets(source, ack, 9), ())

    def test_is_offline_only_and_does_not_authorize_ack(self):
        text = FORENSIC.read_text(encoding="utf-8")
        for forbidden in (
            "import socket",
            "import requests",
            "import aiohttp",
            "subprocess",
            "os.kill",
            "api.comelitgroup.com",
        ):
            self.assertNotIn(forbidden, text)

        for required in (
            '"NETWORK_IO_PERFORMED=false"',
            '"DOOR_ACTION_SENT=false"',
            '"MEDIA_SIGNALING_SENT=false"',
            '"ACK_SIGNALING_SENT=false"',
            "EXPECTED_PCAP_SHA256",
            "DEVICE_VIDEO_BODY_SHA256",
        ):
            self.assertIn(required, text)


if __name__ == "__main__":
    unittest.main()
