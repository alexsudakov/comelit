#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
MEDIA = ROOT / "research" / "media" / "v1"
sys.path.insert(0, str(MEDIA))

from entrance_device_video_ack_pcap_forensic import VipFrame
from entrance_p96_device_000a_peer_target_transform import transform
from entrance_p96_device_000a_target_binding_pcap_forensic import analyze, report


SOURCE = ROOT / "research" / "door" / "v1_5_7" / "comelit-v4-persistent-ctpp-door.c"


def rtpc_open(direction: str, packet: int, target: bytes) -> VipFrame:
    body = bytearray(15)
    body[0:2] = (0xABCD).to_bytes(2, "little")
    body[4:6] = (7).to_bytes(2, "little")
    body[8:12] = b"RTPC"
    body[12:14] = target
    body[14] = 1
    return VipFrame(direction, packet, packet, float(packet), 0, bytes(body))


def media_000a(
    direction: str,
    packet: int,
    request_id: int,
    tag: bytes,
    target: bytes,
) -> VipFrame:
    body = bytearray(44)
    body[0:2] = (0x1840).to_bytes(2, "little")
    body[6:8] = b"\x00\x0a"
    body[8:10] = b"\x00\x11"
    body[10:16] = tag
    body[16:18] = target
    return VipFrame(direction, packet, packet, float(packet), request_id, bytes(body))


class P96PeerTargetTests(unittest.TestCase):
    def test_frozen_relation_model_binds_device_000a_to_device_open(self) -> None:
        client_1 = b"\x31\x12"
        client_2 = b"\x32\x12"
        peer = b"\x77\x45"
        tag = b"TAG006"
        frames = (
            rtpc_open("DEVICE_TO_CLIENT", 205, peer),
            rtpc_open("CLIENT_TO_DEVICE", 206, client_1),
            rtpc_open("CLIENT_TO_DEVICE", 206, client_2),
            media_000a("CLIENT_TO_DEVICE", 206, 77, tag, client_1),
            media_000a("DEVICE_TO_CLIENT", 209, 77, tag, peer),
        )

        result = analyze(frames)
        self.assertTrue(result.peer_target_binding_proven)
        self.assertTrue(result.client_000a_target_equals_client_open_1)
        self.assertTrue(result.device_000a_target_equals_device_open_same_order)
        self.assertFalse(result.device_000a_target_equals_client_open_1)
        self.assertFalse(result.device_000a_target_equals_client_open_2)
        self.assertTrue(result.device_000a_tag_equals_client_000a_tag)

        text = report(result)
        self.assertIn("P96_DEVICE_000A_PEER_TARGET_BINDING=PASS", text)
        self.assertIn("TARGET_ID_VALUES_EMITTED=false", text)
        self.assertNotIn("7745", text.lower())

    def test_transform_changes_only_device_gate_target_source(self) -> None:
        candidate = transform(SOURCE.read_text(encoding="utf-8"))

        self.assertIn(
            "read_le16(body + 16u) != p78_rtpc_runtime.device_open_target",
            candidate,
        )
        self.assertNotIn(
            "memcmp(body + 16u, p78_rtpc_client_000a + 16u, 2u)",
            candidate,
        )
        self.assertIn("P80_DEVICE_000A_PEER_TARGET_MATCH=PASS", candidate)
        self.assertIn("P80_DEVICE_0002_GATE=PASS", candidate)
        self.assertIn("P78_RTPC_CLIENT_001A_SENT=PASS", candidate)
        self.assertIn("P80_MEDIA_ACTIVE=true", candidate)
        self.assertNotIn("signal(SIGUSR1, v4_door_signal_handler);", candidate)


if __name__ == "__main__":
    unittest.main()
