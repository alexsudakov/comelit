#!/usr/bin/env python3
from __future__ import annotations

import struct

FULL = b"000401177"
ENTRANCE = b"00000643"
AUDIO_ID = 0x1D23
VIDEO_ID = 0x1D24


def be16(v: int) -> bytes:
    return struct.pack(">H", v)


def le16(v: int) -> bytes:
    return struct.pack("<H", v)


def event(prefix: int, seq: bytes, action: int, flags: int, payload: bytes) -> bytes:
    assert len(seq) == 4
    return (
        le16(prefix)
        + seq
        + be16(action)
        + be16(flags)
        + payload
        + b"\xff" * 4
        + FULL + b"\0"
        + ENTRANCE + b"\0\0"
    )


def call_payload() -> bytes:
    return (
        FULL + b"\0"
        + ENTRANCE + b"\0\0"
        + bytes.fromhex("012005803118")
        + FULL + b"\0"
        + b"II"
    )


def audio_payload(stop: bool) -> bytes:
    p = bytearray(10)
    p[0] = 0x98 if stop else 0x18
    p[1] = 0x02
    p[6:8] = le16(AUDIO_ID)
    return bytes(p)


def video_payload(stop: bool) -> bytes:
    p = bytearray(26)
    p[0] = 0x94 if stop else 0x14
    p[1] = 0x02 if stop else 0x32
    p[6:8] = le16(VIDEO_ID)
    if not stop:
        p[8:10] = b"\xff\xff"
        p[14:26] = bytes.fromhex("2003e0014001f00010000000")
    return bytes(p)


def state_payload(active: bool) -> bytes:
    return FULL + b"\0" + bytes([1 if active else 0, 0, 0, 0])


def peer_ack(peer_seq: bytes) -> bytes:
    assert len(peer_seq) == 4
    own = bytes([
        peer_seq[0] & 0x7F,
        peer_seq[1],
        peer_seq[3],
        (peer_seq[2] + 1) & 0xFF,
    ])
    return (
        le16(0x1800)
        + own
        + be16(0)
        + b"\xff" * 4
        + FULL + b"\0"
        + ENTRANCE + b"\0\0"
    )


VECTORS = {
    "CALL_INIT": (
        event(0x18C0, bytes.fromhex("1f7bfc71"), 0x0028, 0x0001, call_payload()),
        "c0181f7bfc71002800013030303430313137370030303030303634330000012005803118303030343031313737004949ffffffff3030303430313137370030303030303634330000",
    ),
    "ACTION_0008": (
        event(0x1840, bytes.fromhex("1f7bfd71"), 0x0008, 0x0003, bytes.fromhex("490027000000")),
        "40181f7bfd7100080003490027000000ffffffff3030303430313137370030303030303634330000",
    ),
    "ACTION_000A_START": (
        event(0x1840, bytes.fromhex("1f7bfe73"), 0x000A, 0x0011, audio_payload(False)),
        "40181f7bfe73000a0011180200000000231d0000ffffffff3030303430313137370030303030303634330000",
    ),
    "ACTION_001A_START": (
        event(0x1840, bytes.fromhex("1f7bff74"), 0x001A, 0x0011, video_payload(False)),
        "40181f7bff74001a0011143200000000241dffff000000002003e0014001f00010000000ffffffff3030303430313137370030303030303634330000",
    ),
    "ACTION_000E_ACTIVE": (
        event(0x1840, bytes.fromhex("1f7b0074"), 0x000E, 0x0070, state_payload(True)),
        "40181f7b0074000e00703030303430313137370001000000ffffffff3030303430313137370030303030303634330000",
    ),
    "ACTION_0003_STOP": (
        event(0x1840, bytes.fromhex("1f7b0274"), 0x0003, 0x000E, b"\0\0"),
        "40181f7b02740003000e0000ffffffff3030303430313137370030303030303634330000",
    ),
    "ACTION_000A_STOP": (
        event(0x1840, bytes.fromhex("1f7b0374"), 0x000A, 0x0011, audio_payload(True)),
        "40181f7b0374000a0011980200000000231d0000ffffffff3030303430313137370030303030303634330000",
    ),
    "ACTION_001A_STOP": (
        event(0x1840, bytes.fromhex("1f7b0474"), 0x001A, 0x0011, video_payload(True)),
        "40181f7b0474001a0011940200000000241d000000000000000000000000000000000000ffffffff3030303430313137370030303030303634330000",
    ),
    "ACTION_000E_FINAL": (
        event(0x1860, bytes.fromhex("1f7b0575"), 0x000E, 0x0070, state_payload(False)),
        "60181f7b0575000e00703030303430313137370000000000ffffffff3030303430313137370030303030303634330000",
    ),
    "PEER_ACK_0008": (
        peer_ack(bytes.fromhex("9f7b71fe")),
        "00181f7bfe720000ffffffff3030303430313137370030303030303634330000",
    ),
    "PEER_ACK_0002": (
        peer_ack(bytes.fromhex("9f7b72fe")),
        "00181f7bfe730000ffffffff3030303430313137370030303030303634330000",
    ),
    "PEER_ACK_000A_STOP": (
        peer_ack(bytes.fromhex("9f7b7404")),
        "00181f7b04750000ffffffff3030303430313137370030303030303634330000",
    ),
}


def main() -> int:
    for name, (actual, expected_hex) in VECTORS.items():
        expected = bytes.fromhex(expected_hex)
        if actual != expected:
            print(f"VECTOR={name} RESULT=FAIL")
            print(f"ACTUAL={actual.hex()}")
            print(f"EXPECTED={expected.hex()}")
            return 1
        print(f"VECTOR={name} RESULT=PASS bytes={len(actual)}")

    # Raw-video channel proof from the capture:
    # ViP request-id 0x1d24 is the same id advertised in ACTION_001A_START.
    raw_prefix = bytes.fromhex("00069605241d00008063")
    request_id = struct.unpack_from("<I", raw_prefix, 4)[0]
    pt = raw_prefix[9] & 0x7F
    assert request_id == VIDEO_ID
    assert pt == 99
    print(f"RAW_MEDIA_REQUEST_ID=0x{request_id:04x}")
    print(f"RAW_MEDIA_RTP_PT={pt}")
    print("MEDIA_PROTOCOL_VECTORS=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
