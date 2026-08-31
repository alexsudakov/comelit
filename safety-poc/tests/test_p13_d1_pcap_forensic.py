from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "p13_d1_pcap_forensic.py"
spec = importlib.util.spec_from_file_location("p13_d1_pcap_forensic", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def fixture_pin(address: bytes = b"12345678", output: int = 1) -> str:
    return hashlib.sha256(address + b"|" + str(output).encode("ascii")).hexdigest()


def tap_body(opcode: int, *, address: bytes | None = None, output: int = 1) -> bytes:
    prefix = opcode.to_bytes(2, "little") + b"ABCD"
    if address is None:
        return prefix + b"generic"
    inner = b"\x00\x2d" + address + b"\x00\x00" + bytes([output])
    return prefix + len(inner).to_bytes(2, "big") + inner + b"\x00\x00\x00\xff\xff\xff\xff"


def vip_frame(request_id: int, body: bytes) -> bytes:
    return b"\x00\x06" + len(body).to_bytes(2, "little") + request_id.to_bytes(4, "little") + body


class P13D1PcapForensicTests(unittest.TestCase):
    def test_pair_pin_recognizes_addr10_without_exposing_plaintext_contract(self):
        body = tap_body(0x1840, address=b"12345678", output=1)
        with mock.patch.object(module, "EXPECTED_PEER_TARGET_SHA256", fixture_pin()):
            self.assertTrue(module.body_has_expected_target(body))

    def test_reassembly_deduplicates_overlap_and_reports_no_gap(self):
        segments = [
            module.Segment(100, 1.0, b"abcdef"),
            module.Segment(103, 1.1, b"defghi"),
        ]
        result = module.reassemble_segments(segments)
        self.assertEqual(result.data, b"abcdefghi")
        self.assertEqual(result.gaps, 0)
        self.assertEqual(result.conflicts, 0)

    def test_vip_parser_preserves_timestamp_request_and_body(self):
        first = vip_frame(7, b"abc")
        second = vip_frame(9, b"defg")
        raw = first + second
        stream = module.Reassembled(raw, tuple([10.0] * len(first) + [11.0] * len(second)), 0, 0)
        frames, skipped = module.parse_vip_stream(stream, "fixture")
        self.assertEqual(skipped, 0)
        self.assertEqual(len(frames), 2)
        self.assertEqual(frames[0].request_id, 7)
        self.assertEqual(frames[0].timestamp, 10.0)
        self.assertEqual(frames[1].body, b"defg")

    def test_capture_prefix_gate_accepts_exact_primary_capture_shape(self):
        first = vip_frame(7, b"abc")
        second = vip_frame(9, b"defg")
        raw = module.EXPECTED_CAPTURE_PREFIX + first + second
        stream = module.Reassembled(
            raw,
            tuple([10.0] * len(raw)),
            0,
            0,
        )

        frames, skipped = module.parse_vip_stream(stream, "fixture")

        self.assertEqual(skipped, len(module.EXPECTED_CAPTURE_PREFIX))
        self.assertEqual(frames[0].stream_offset, len(module.EXPECTED_CAPTURE_PREFIX))
        self.assertTrue(
            module.capture_prefix_matches(
                stream,
                frames,
                skipped,
            )
        )

    def test_capture_prefix_gate_rejects_wrong_prefix_and_trailing_bytes(self):
        frame = vip_frame(7, b"abc")

        wrong_raw = b"\\x01" * len(module.EXPECTED_CAPTURE_PREFIX) + frame
        wrong_stream = module.Reassembled(
            wrong_raw,
            tuple([10.0] * len(wrong_raw)),
            0,
            0,
        )
        wrong_frames, wrong_skipped = module.parse_vip_stream(
            wrong_stream,
            "fixture",
        )
        self.assertFalse(
            module.capture_prefix_matches(
                wrong_stream,
                wrong_frames,
                wrong_skipped,
            )
        )

        trailing_raw = module.EXPECTED_CAPTURE_PREFIX + frame + b"\\x99"
        trailing_stream = module.Reassembled(
            trailing_raw,
            tuple([10.0] * len(trailing_raw)),
            0,
            0,
        )
        trailing_frames, trailing_skipped = module.parse_vip_stream(
            trailing_stream,
            "fixture",
        )
        self.assertFalse(
            module.capture_prefix_matches(
                trailing_stream,
                trailing_frames,
                trailing_skipped,
            )
        )

    def test_semantic_target_match_keeps_standalone_candidate_without_claiming_exact_body(self):
        pin = fixture_pin()
        door = module.VipFrame(10.0, 77, tap_body(0x1840, address=b"12345678"), 0, "out")
        prepared_bodies = [
            tap_body(0x18C0),
            tap_body(0x1800),
            tap_body(0x1820),
            tap_body(0x18C0, address=b"12345678"),
            tap_body(0x1800),
            tap_body(0x1820),
        ]
        with mock.patch.object(module, "EXPECTED_PEER_TARGET_SHA256", pin):
            prepared = [
                module.PreparedWrite(
                    index + 1,
                    body,
                    hashlib.sha256(body).hexdigest(),
                    int.from_bytes(body[:2], "little"),
                    module.body_has_expected_target(body),
                )
                for index, body in enumerate(prepared_bodies)
            ]
            result = module.analyze([door], [], door, prepared)
        self.assertEqual(result["P13_D1_STANDALONE_RELATION"], "SEMANTIC_TARGET_MATCH_DIFFERENT_CONTEXT")
        self.assertEqual(result["P13_D1_STANDALONE_ACCEPTABLE"], "true")
        self.assertEqual(result["P13_D1_PREPARED_OPERATION_SUFFIX_MATCH"], "true")

    def test_missing_target_semantic_is_contradiction(self):
        door = module.VipFrame(10.0, 77, tap_body(0x1840, address=b"12345678"), 0, "out")
        prepared_bodies = [tap_body(value) for value in (0x18C0, 0x1800, 0x1820, 0x18C0, 0x1800, 0x1820)]
        prepared = [
            module.PreparedWrite(
                index + 1,
                body,
                hashlib.sha256(body).hexdigest(),
                int.from_bytes(body[:2], "little"),
                False,
            )
            for index, body in enumerate(prepared_bodies)
        ]
        result = module.analyze([door], [], door, prepared)
        self.assertEqual(result["P13_D1_STANDALONE_RELATION"], "CONTRADICTION")
        self.assertEqual(result["P13_D1_STANDALONE_ACCEPTABLE"], "false")

    def test_ack_is_proven_only_by_inbound_target_semantic(self):
        pin = fixture_pin()
        door = module.VipFrame(10.0, 77, tap_body(0x1840, address=b"12345678"), 0, "out")
        response = module.VipFrame(10.1, 77, tap_body(0x1840, address=b"12345678"), 0, "in")
        with mock.patch.object(module, "EXPECTED_PEER_TARGET_SHA256", pin):
            result, count, _ = module.classify_ack(door, [door], [response])
        self.assertEqual(result, "PROVEN")
        self.assertEqual(count, 1)

    def test_generic_response_is_not_promoted_to_door_ack(self):
        door = module.VipFrame(10.0, 77, tap_body(0x1840, address=b"12345678"), 0, "out")
        neighbor = module.VipFrame(9.0, 77, tap_body(0x1800), 0, "out")
        generic = module.VipFrame(9.1, 77, b"same-response", 0, "in")
        door_generic = module.VipFrame(10.1, 77, b"same-response", 0, "in")
        result, count, overlap = module.classify_ack(
            door,
            [neighbor, door],
            [generic, door_generic],
        )
        self.assertEqual(result, "NOT_DISTINGUISHABLE")
        self.assertEqual(count, 1)
        self.assertTrue(overlap)

    def test_source_declares_offline_boundary(self):
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("NETWORK_ACTION_PERFORMED=false", text)
        self.assertIn("PHYSICAL_DOOR_ACTION=false", text)
        self.assertIn("SEND_ARMED_REACHED=false", text)
        self.assertNotIn("socket.socket", text)
        self.assertNotIn("asyncio.open_connection", text)


if __name__ == "__main__":
    unittest.main()
