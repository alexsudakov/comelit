import io
import re
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MEDIA = ROOT / "research" / "media" / "v1"
sys.path.insert(0, str(MEDIA))

from entrance_p116_r30_call_ctp_envelope_model import FLAG_DATA, build_ctp_envelope
import entrance_p116_r52_capability_word_forensic as r52


SRC = b"SRCADDR001"
DST = b"DSTADDR002"


def vip_frame(direction, packet, body, request_id=7):
    return r52.VipFrame(direction, packet, packet, float(packet), request_id, body)


def envelope(connection, inner_body, *, seq=1, ack=2, flags=FLAG_DATA):
    return build_ctp_envelope(
        flags=flags,
        connection=connection.to_bytes(2, "big"),
        sequence=seq,
        acknowledgement=ack,
        inner_body=inner_body,
        source_raw=SRC,
        destination_raw=DST,
    )


class P116R52CapabilityWordForensicTests(unittest.TestCase):
    def test_capabilities_body_contract_and_le32_decode(self):
        body = r52.build_capabilities_body(call_type=0x49, capability_word=0x00000027)
        self.assertEqual(body, b"\x00\x03\x49\x00\x27\x00\x00\x00")
        self.assertEqual(r52.parse_capabilities_body(body), (0x49, 0x00, 0x00000027))

    def test_direction_separation_by_client_and_peer_relation(self):
        frames = [
            vip_frame(
                "CLIENT_TO_DEVICE",
                10,
                envelope(0x1234, r52.build_capabilities_body(call_type=0x49, capability_word=0x27), seq=3),
            ),
            vip_frame(
                "DEVICE_TO_CLIENT",
                11,
                envelope(0x9234, r52.build_capabilities_body(call_type=0x50, capability_word=0x1B), seq=4),
            ),
        ]
        rows = r52.extract_capabilities_from_vip_frames(frames, capture_label="UNIT")
        self.assertEqual([row.direction for row in rows], ["CLIENT_TO_DEVICE", "DEVICE_TO_CLIENT"])
        self.assertEqual([row.capability_word for row in rows], [0x27, 0x1B])
        self.assertEqual(rows[0].peer_connection_match, "CLIENT_LOCAL")
        self.assertEqual(rows[1].peer_connection_match, "DEVICE_PEER_XOR_CLIENT_LOCAL")

    def test_fail_closed_on_truncated_capabilities_body(self):
        bad = vip_frame("CLIENT_TO_DEVICE", 10, envelope(0x1234, b"\x00\x03\x49"))
        with self.assertRaises(ValueError):
            r52.extract_capabilities_from_vip_frames([bad], capture_label="UNIT")

    def test_fail_closed_on_non_data_capabilities(self):
        bad = vip_frame(
            "CLIENT_TO_DEVICE",
            10,
            envelope(0x1234, r52.build_capabilities_body(call_type=0x49, capability_word=0x27), flags=0x00),
        )
        with self.assertRaises(ValueError):
            r52.extract_capabilities_from_vip_frames([bad], capture_label="UNIT")

    def test_no_raw_output_invariant(self):
        frame = vip_frame(
            "CLIENT_TO_DEVICE",
            10,
            envelope(0x1234, r52.build_capabilities_body(call_type=0x49, capability_word=0x27)),
        )
        rows = r52.extract_capabilities_from_vip_frames([frame], capture_label="UNIT")
        text = "\n".join(r52.tsv_lines(rows))
        self.assertIn("SANITIZED", text)
        self.assertNotRegex(text, re.compile(r"(?:[0-9a-fA-F]{2}[ :]){3,}[0-9a-fA-F]{2}"))
        self.assertNotRegex(text, re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"))

    def test_main_reports_sanitized_scalars_for_missing_flow(self):
        with redirect_stdout(io.StringIO()) as output:
            rc = r52.main(["/dev/null", "--label", "EMPTY"])
        self.assertEqual(rc, 2)
        text = output.getvalue()
        self.assertIn("FORENSIC_GATE=FAIL", text)
        self.assertIn("NETWORK_IO_PERFORMED=false", text)


if __name__ == "__main__":
    unittest.main()
