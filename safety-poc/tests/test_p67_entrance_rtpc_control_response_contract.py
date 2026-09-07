#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
MEDIA = ROOT / "research" / "media" / "v1"
sys.path.insert(0, str(MEDIA))

from entrance_device_video_ack_pcap_forensic import VipFrame
from entrance_rtpc_control_response_contract_pcap_forensic import analyze, report


class P67RtpcControlResponseContractTests(unittest.TestCase):
    @staticmethod
    def frame(direction: str, packet: int, ts: float, body: bytes, request_id: int = 0) -> VipFrame:
        return VipFrame(direction, packet, packet, ts, request_id, body)

    @staticmethod
    def open_body(request_id: bytes, *, nonzero_reserved: bool = False) -> bytes:
        body = bytearray(15)
        body[0:2] = (0xABCD).to_bytes(2, "little")
        body[2:8] = b"\x00" * 6
        body[8:12] = b"RTPC"
        body[12:14] = request_id
        body[14] = 1 if nonzero_reserved else 0
        return bytes(body)

    @staticmethod
    def echo_body(request_id: bytes) -> bytes:
        body = bytearray(12)
        body[0:4] = b"ECHO"
        body[4:8] = b"RESP"
        body[8:10] = request_id
        body[10:12] = b"\x00\x00"
        return bytes(body)

    def fixture(self, *, mutate_response: bool = False, bad_open: bool = False):
        rid1 = b"\x34\x12"
        rid2 = b"\x35\x12"
        echo1 = self.echo_body(rid1)
        response = bytearray(echo1)
        if mutate_response:
            response[2] ^= 0x01
        return (
            self.frame("DEVICE_TO_CLIENT", 205, 1.000, b"\x00" * 15),
            self.frame("CLIENT_TO_DEVICE", 206, 1.100, self.open_body(rid1, nonzero_reserved=bad_open)),
            self.frame("CLIENT_TO_DEVICE", 206, 1.110, self.open_body(rid2)),
            self.frame("DEVICE_TO_CLIENT", 207, 1.200, echo1),
            self.frame("CLIENT_TO_DEVICE", 208, 1.250, bytes(response)),
            self.frame("DEVICE_TO_CLIENT", 209, 1.300, self.echo_body(rid2)),
        )

    def test_full_control_generation_contract_passes(self) -> None:
        result = analyze(self.fixture())
        self.assertTrue(result.live_control_generation_contract_ok)
        self.assertTrue(result.open_full_template_ok)
        self.assertEqual(result.device_echo_count, 2)
        self.assertEqual(result.device_echo_common_request_position, 8)
        self.assertTrue(result.client_response_exact_preceding_echo)
        self.assertEqual(result.client_response_request_id_ordinals, (1,))
        self.assertEqual(result.client_response_request_id_positions, (8,))
        text = report(result)
        self.assertIn("RTPC_LIVE_CONTROL_GENERATION_CONTRACT=PASS", text)
        self.assertIn("CONTROL_BODY_VALUES_EMITTED=false", text)
        self.assertIn("NETWORK_IO_PERFORMED=false", text)
        self.assertNotIn("3412", text)
        self.assertNotIn("3512", text)

    def test_non_exact_client_response_fails_closed(self) -> None:
        result = analyze(self.fixture(mutate_response=True))
        self.assertFalse(result.live_control_generation_contract_ok)
        self.assertFalse(result.client_response_exact_preceding_echo)
        self.assertEqual(result.client_response_diff_positions, (2,))

    def test_nonzero_open_reserved_byte_fails_closed(self) -> None:
        result = analyze(self.fixture(bad_open=True))
        self.assertFalse(result.live_control_generation_contract_ok)
        self.assertFalse(result.open_full_template_ok)


if __name__ == "__main__":
    unittest.main()
