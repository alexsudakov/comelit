#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
MEDIA = ROOT / "research" / "media" / "v1"
sys.path.insert(0, str(MEDIA))

from entrance_client_media_signaling_field_sources_pcap_forensic import analyze, report
from entrance_device_video_ack_pcap_forensic import VipFrame
from entrance_post_218_non_pseudotcp_udp_pcap_forensic import SelectedDatagram
from pseudotcp_pcap_handshake_forensic import Endpoint


def vip_body(length: int, seq: int, action: int, flags: int) -> bytearray:
    b = bytearray(length)
    b[0:2] = (0x1840).to_bytes(2, "little")
    b[2:6] = seq.to_bytes(4, "little")
    b[6:8] = action.to_bytes(2, "big")
    b[8:10] = flags.to_bytes(2, "big")
    return b


def rtp(seq: int, ts: int, ssrc: int, pt: int, media_len: int) -> bytes:
    return (
        bytes([0x80, pt & 0x7F])
        + seq.to_bytes(2, "big")
        + ts.to_bytes(4, "big")
        + ssrc.to_bytes(4, "big")
        + b"X" * media_len
    )


class P61ContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = Endpoint(b"\x0a\x00\x00\x01", 40000)
        self.device = Endpoint(b"\x0a\x00\x00\x02", 50000)
        self.request_id = 77
        self.addr_a = b"ADDRROLEA"
        self.addr_b = b"ADDRROLEB"

    def frame(self, direction: str, packet: int, ts: float, body: bytes, request_id: int | None = None) -> VipFrame:
        return VipFrame(direction, packet, packet, ts, self.request_id if request_id is None else request_id, body)

    def dgram(self, packet: int, ts: float, source: Endpoint, target: Endpoint, payload: bytes) -> SelectedDatagram:
        return SelectedDatagram(packet, ts, source, target, payload)

    def test_relations_are_metadata_only_and_find_rtp_timestamp(self) -> None:
        anchor_body = vip_body(40, 0x10000000, 0x0008, 0x0003)
        anchor_body[20:29] = self.addr_a
        anchor_body[30:39] = self.addr_b
        anchor = self.frame("DEVICE_TO_CLIENT", 200, 1.0, bytes(anchor_body))

        earlier = vip_body(36, 0x10010000, 0x0002, 0x000C)
        earlier[10:14] = b"ABCD"
        control = bytearray(15)
        control[4:8] = b"WXYZ"

        ts = 0x11223344
        c000a = vip_body(44, 0x22000000, 0x000A, 0x0011)
        c000a[10:14] = b"ABCD"
        c000a[12:16] = ts.to_bytes(4, "big")
        c000a[16:20] = b"WXYZ"
        c000a[20:24] = b"\x00\x00\xff\xff"
        c000a[24:33] = self.addr_b
        c000a[33] = 0
        c000a[34:43] = self.addr_a
        c000a[43] = 0

        d000a = bytearray(c000a)
        d000a[2:6] = (0x11020000).to_bytes(4, "little")
        d000a[24:33] = self.addr_a
        d000a[34:43] = self.addr_b

        c001a = vip_body(60, 0x22010000, 0x001A, 0x0011)
        c001a[12:16] = ts.to_bytes(4, "big")
        c001a[20:24] = ts.to_bytes(4, "big")
        c001a[34:60] = c000a[18:44]

        frames = (
            anchor,
            self.frame("DEVICE_TO_CLIENT", 203, 1.2, bytes(earlier)),
            self.frame("DEVICE_TO_CLIENT", 205, 1.3, bytes(control), request_id=0),
            self.frame("CLIENT_TO_DEVICE", 206, 1.33, bytes(c000a)),
            self.frame("DEVICE_TO_CLIENT", 209, 1.53, bytes(d000a)),
            self.frame("CLIENT_TO_DEVICE", 212, 1.64, bytes(c001a)),
        )
        wrapper = b"WRAPTEST"
        datagrams = (
            self.dgram(218, 2.0, self.device, self.client, b"boundary"),
            self.dgram(219, 2.02, self.device, self.client, wrapper + rtp(1, 100, 7, 99, 20)),
            self.dgram(300, 2.50, self.client, self.device, wrapper + rtp(5, ts, 9, 8, 160)),
        )

        with patch(
            "entrance_client_media_signaling_field_sources_pcap_forensic._find_anchor",
            return_value=anchor,
        ):
            result = analyze(frames, client=self.client, device=self.device, datagrams=datagrams)

        text = report(result)
        self.assertIn("kind=TS_BE", text)
        self.assertIn("source=CONTROL_PACKET_205", text)
        self.assertIn("BODY_VALUES_EMITTED=false", text)
        self.assertIn("NETWORK_IO_PERFORMED=false", text)
        self.assertNotIn("ADDRROLEA", text)
        self.assertNotIn("11223344", text)

    def test_missing_target_fails_closed(self) -> None:
        anchor_body = vip_body(40, 1, 0x0008, 0x0003)
        anchor_body[20:29] = self.addr_a
        anchor_body[30:39] = self.addr_b
        anchor = self.frame("DEVICE_TO_CLIENT", 200, 1.0, bytes(anchor_body))
        with patch(
            "entrance_client_media_signaling_field_sources_pcap_forensic._find_anchor",
            return_value=anchor,
        ):
            with self.assertRaises(ValueError):
                analyze((anchor,), client=self.client, device=self.device, datagrams=())


if __name__ == "__main__":
    unittest.main()
