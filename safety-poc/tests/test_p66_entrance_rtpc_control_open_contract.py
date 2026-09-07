#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
MEDIA = ROOT / "research" / "media" / "v1"
sys.path.insert(0, str(MEDIA))

from entrance_device_video_ack_pcap_forensic import VipFrame
from entrance_rtpc_control_open_contract_pcap_forensic import analyze, report


class P66RtpcControlOpenContractTests(unittest.TestCase):
    @staticmethod
    def frame(direction: str, packet: int, ts: float, body: bytes, request_id: int = 0) -> VipFrame:
        return VipFrame(direction, packet, packet, ts, request_id, body)

    @staticmethod
    def open_body(request_id: bytes, *, trailer: int = 0) -> bytes:
        body = bytearray(15)
        body[0:2] = (0xABCD).to_bytes(2, "little")
        body[2:8] = b"\x00" * 6
        body[8:12] = b"RTPC"
        body[12:14] = request_id
        body[14] = trailer
        return bytes(body)

    @staticmethod
    def reply_body(request_id: bytes) -> bytes:
        body = bytearray(12)
        body[0:2] = b"\x00\x01"
        body[4:6] = request_id
        return bytes(body)

    def fixture(self, *, prior=False, extra_diff=False, missing_second_echo=False):
        rid1 = b"\x34\x12"
        rid2 = b"\x35\x12"
        prior_body = bytearray(15)
        prior_body[0:2] = b"\x01\x02"
        if prior:
            prior_body[6:8] = rid1

        frames = [
            self.frame("DEVICE_TO_CLIENT", 205, 1.000, bytes(prior_body)),
            self.frame("CLIENT_TO_DEVICE", 206, 1.100, self.open_body(rid1)),
            self.frame(
                "CLIENT_TO_DEVICE",
                206,
                1.110,
                self.open_body(rid2, trailer=1 if extra_diff else 0),
            ),
            self.frame("DEVICE_TO_CLIENT", 207, 1.200, self.reply_body(rid1)),
        ]
        if not missing_second_echo:
            frames.append(self.frame("DEVICE_TO_CLIENT", 209, 1.300, self.reply_body(rid2)))

        wrappers = (
            b"AA" + rid1 + b"BBBB",
            b"CC" + rid2 + b"DDDD",
        )
        return tuple(frames), wrappers

    def test_runtime_generation_contract_passes(self) -> None:
        frames, wrappers = self.fixture()
        result = analyze(frames, wrappers)
        self.assertTrue(result.runtime_generation_contract_ok)
        self.assertEqual(result.open_count, 2)
        self.assertTrue(result.fixed_field_contract)
        self.assertTrue(result.template_static_except_request_id)
        self.assertTrue(result.request_ids_distinct)
        self.assertTrue(result.request_ids_nonzero)
        self.assertTrue(result.request_ids_sequential)
        self.assertTrue(all(item.device_echo_supported for item in result.relations))
        text = report(result)
        self.assertIn("RTPC_RUNTIME_ID_GENERATION_CONTRACT=PASS", text)
        self.assertIn("REQUEST_ID_VALUES_EMITTED=false", text)
        self.assertIn("CONTROL_BODY_VALUES_EMITTED=false", text)
        self.assertIn("NETWORK_IO_PERFORMED=false", text)
        self.assertNotIn("3412", text)
        self.assertNotIn("3512", text)

    def test_prior_occurrence_fails_closed(self) -> None:
        frames, wrappers = self.fixture(prior=True)
        result = analyze(frames, wrappers)
        self.assertFalse(result.runtime_generation_contract_ok)
        self.assertGreater(result.relations[0].prior_control_match_count, 0)

    def test_extra_open_body_difference_fails_closed(self) -> None:
        frames, wrappers = self.fixture(extra_diff=True)
        result = analyze(frames, wrappers)
        self.assertFalse(result.runtime_generation_contract_ok)
        self.assertFalse(result.template_static_except_request_id)
        self.assertIn(14, result.open_body_diff_positions)

    def test_missing_device_echo_fails_closed(self) -> None:
        frames, wrappers = self.fixture(missing_second_echo=True)
        result = analyze(frames, wrappers)
        self.assertFalse(result.runtime_generation_contract_ok)
        self.assertFalse(result.relations[1].device_echo_supported)


if __name__ == "__main__":
    unittest.main()
