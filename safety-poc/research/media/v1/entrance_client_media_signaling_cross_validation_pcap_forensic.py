#!/usr/bin/env python3
"""Offline cross-validation for client 0x000a/0x001a media signaling.

P61/P62 reduced the unresolved contract to small action-specific fields.  This
analyzer validates a second, independently observed protocol model against the
frozen primary capture without emitting body bytes or channel/request-id
values.  It checks:

* two client RTPC channel-open requests in the packet-206 CONTROL exchange;
* runtime binding of those request-id bytes to client 0x000a and 0x001a;
* action-specific RTPC-link / video-config tag layouts;
* video-config geometry as LE16 semantic values;
* previously established client sequence and address-role relations.

No network I/O, media decoding, payload extraction, or signaling is performed.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Iterable

from entrance_device_video_ack_pcap_forensic import (
    EXPECTED_PCAP_SHA256,
    VipFrame,
    load_capture,
    select_vip_flow,
)
from entrance_post_ack_0002_pcap_forensic import collect_extended_vip_frames
from entrance_client_media_signaling_body_contract_pcap_forensic import (
    _find_anchor,
    _find_exact,
    CLIENT_000A_PACKET,
    CLIENT_001A_PACKET,
)

CONTROL_OPEN_PACKET = 206
REFERENCE_GEOMETRY = (800, 480, 320, 240, 16)


@dataclass(frozen=True)
class Result:
    rtpc_open_count: int
    c000a_rtpc_open_ordinal: int | None
    c001a_rtpc_open_ordinal: int | None
    distinct_rtpc_bindings: bool
    c000a_tag_ok: bool
    c001a_tag_ok: bool
    c000a_reserved_ok: bool
    c001a_reserved_ok: bool
    sequence_contract_ok: bool
    address_contract_ok: bool
    width: int
    height: int
    secondary_width: int
    secondary_height: int
    fps: int
    geometry_reference_match: bool

    @property
    def generation_contract_ok(self) -> bool:
        return all(
            (
                self.rtpc_open_count == 2,
                self.c000a_rtpc_open_ordinal is not None,
                self.c001a_rtpc_open_ordinal is not None,
                self.distinct_rtpc_bindings,
                self.c000a_tag_ok,
                self.c001a_tag_ok,
                self.c000a_reserved_ok,
                self.c001a_reserved_ok,
                self.sequence_contract_ok,
                self.address_contract_ok,
                self.geometry_reference_match,
            )
        )


def _rtpc_client_opens(frames: Iterable[VipFrame]) -> tuple[VipFrame, ...]:
    result = []
    for frame in frames:
        body = frame.body
        if (
            frame.direction == "CLIENT_TO_DEVICE"
            and frame.first_packet == CONTROL_OPEN_PACKET
            and frame.request_id == 0
            and frame.body_length == 15
            and len(body) == 15
            and int.from_bytes(body[0:2], "little") == 0xABCD
            and body[8:12] == b"RTPC"
        ):
            result.append(frame)
    return tuple(result)


def _binding_ordinal(value: bytes, opens: tuple[VipFrame, ...]) -> int | None:
    matches = [index for index, frame in enumerate(opens, start=1) if frame.body[12:14] == value]
    return matches[0] if len(matches) == 1 else None


def _previous_client_ctpp(frames: tuple[VipFrame, ...], target: VipFrame) -> VipFrame | None:
    candidates = [
        frame
        for frame in frames
        if frame.direction == "CLIENT_TO_DEVICE"
        and frame.request_id == target.request_id
        and frame.timestamp < target.timestamp
        and frame.body_length >= 6
    ]
    return max(candidates, key=lambda frame: (frame.timestamp, frame.first_packet)) if candidates else None


def analyze(frames: Iterable[VipFrame]) -> Result:
    ordered = tuple(sorted(frames, key=lambda frame: (frame.timestamp, frame.first_packet)))
    anchor = _find_anchor(ordered)
    c000a = _find_exact(
        ordered,
        direction="CLIENT_TO_DEVICE",
        packet=CLIENT_000A_PACKET,
        action=0x000A,
        body_len=44,
    )
    c001a = _find_exact(
        ordered,
        direction="CLIENT_TO_DEVICE",
        packet=CLIENT_001A_PACKET,
        action=0x001A,
        body_len=60,
    )
    if not (anchor.request_id == c000a.request_id == c001a.request_id):
        raise ValueError("target signaling frames do not share CTPP request id")

    opens = _rtpc_client_opens(ordered)
    c000a_open = _binding_ordinal(c000a.body[16:18], opens)
    c001a_open = _binding_ordinal(c001a.body[16:18], opens)
    distinct = (
        c000a_open is not None
        and c001a_open is not None
        and c000a_open != c001a_open
    )

    c000a_tag_ok = c000a.body[10:16] == bytes((0x18, 0x02, 0, 0, 0, 0))
    c001a_tag_ok = c001a.body[10:16] == bytes((0x14, 0x32, 0, 0, 0, 0))
    c000a_reserved_ok = c000a.body[18:20] == b"\x00\x00"
    # Frozen primary capture variant: FF FF followed by four zero bytes.
    c001a_reserved_ok = c001a.body[18:24] == b"\xff\xff\x00\x00\x00\x00"

    width = int.from_bytes(c001a.body[24:26], "little")
    height = int.from_bytes(c001a.body[26:28], "little")
    secondary_width = int.from_bytes(c001a.body[28:30], "little")
    secondary_height = int.from_bytes(c001a.body[30:32], "little")
    fps = int.from_bytes(c001a.body[32:34], "little")
    geometry = (width, height, secondary_width, secondary_height, fps)

    previous = _previous_client_ctpp(ordered, c000a)
    if previous is None:
        sequence_ok = False
    else:
        prev_seq = int.from_bytes(previous.body[2:6], "little")
        seq_000a = int.from_bytes(c000a.body[2:6], "little")
        seq_001a = int.from_bytes(c001a.body[2:6], "little")
        sequence_ok = (
            seq_000a == prev_seq
            and ((seq_001a - seq_000a) & 0xFFFFFFFF) == 0x00010000
        )

    role_a = anchor.body[20:29]
    role_b = anchor.body[30:39]
    address_ok = (
        len(role_a) == 9
        and len(role_b) == 9
        and c000a.body[24:33] == role_b
        and c000a.body[34:43] == role_a
        and c001a.body[40:49] == role_b
        and c001a.body[50:59] == role_a
    )

    return Result(
        rtpc_open_count=len(opens),
        c000a_rtpc_open_ordinal=c000a_open,
        c001a_rtpc_open_ordinal=c001a_open,
        distinct_rtpc_bindings=distinct,
        c000a_tag_ok=c000a_tag_ok,
        c001a_tag_ok=c001a_tag_ok,
        c000a_reserved_ok=c000a_reserved_ok,
        c001a_reserved_ok=c001a_reserved_ok,
        sequence_contract_ok=sequence_ok,
        address_contract_ok=address_ok,
        width=width,
        height=height,
        secondary_width=secondary_width,
        secondary_height=secondary_height,
        fps=fps,
        geometry_reference_match=geometry == REFERENCE_GEOMETRY,
    )


def _ordinal(value: int | None) -> str:
    return "NONE" if value is None else str(value)


def report(result: Result) -> str:
    lines = [
        "=== COMELIT ENTRANCE CLIENT MEDIA SIGNALING CROSS-VALIDATION PCAP FORENSIC ===",
        "PCAP_SHA256_GATE=PASS",
        f"CLIENT_RTPC_OPEN_COUNT={result.rtpc_open_count}",
        f"CLIENT_000A_RTPC_OPEN_ORDINAL={_ordinal(result.c000a_rtpc_open_ordinal)}",
        f"CLIENT_001A_RTPC_OPEN_ORDINAL={_ordinal(result.c001a_rtpc_open_ordinal)}",
        f"RTPC_BINDINGS_DISTINCT={'true' if result.distinct_rtpc_bindings else 'false'}",
        f"CLIENT_000A_RTPC_LINK_TAG_CONTRACT={'PASS' if result.c000a_tag_ok else 'FAIL'}",
        f"CLIENT_001A_VIDEO_CONFIG_TAG_CONTRACT={'PASS' if result.c001a_tag_ok else 'FAIL'}",
        f"CLIENT_000A_RESERVED_CONTRACT={'PASS' if result.c000a_reserved_ok else 'FAIL'}",
        f"CLIENT_001A_RESERVED_VARIANT_CONTRACT={'PASS' if result.c001a_reserved_ok else 'FAIL'}",
        f"CLIENT_SEQUENCE_CONTRACT={'PASS' if result.sequence_contract_ok else 'FAIL'}",
        f"CLIENT_ADDRESS_ROLE_CONTRACT={'PASS' if result.address_contract_ok else 'FAIL'}",
        (
            "VIDEO_CONFIG_GEOMETRY "
            f"width={result.width} height={result.height} "
            f"secondary_width={result.secondary_width} secondary_height={result.secondary_height} "
            f"fps={result.fps}"
        ),
        f"VIDEO_CONFIG_REFERENCE_GEOMETRY_MATCH={'true' if result.geometry_reference_match else 'false'}",
        f"LIVE_BODY_GENERATION_CONTRACT={'PASS' if result.generation_contract_ok else 'NOT_PROVEN'}",
        "REQUEST_ID_VALUES_EMITTED=false",
        "PROTOCOL_ADDRESS_VALUES_EMITTED=false",
        "SEQUENCE_VALUES_EMITTED=false",
        "RAW_PAYLOAD_EMITTED=false",
        "HEX_PAYLOAD_EMITTED=false",
        "BASE64_PAYLOAD_EMITTED=false",
        "MEDIA_PAYLOAD_EMITTED=false",
        "NETWORK_IO_PERFORMED=false",
        "DOOR_ACTION_SENT=false",
        "MEDIA_SIGNALING_SENT=false",
        "ACK_SIGNALING_SENT=false",
        "=== END COMELIT ENTRANCE CLIENT MEDIA SIGNALING CROSS-VALIDATION PCAP FORENSIC ===",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pcap", type=Path, required=True)
    parser.add_argument("--expected-sha256", default=EXPECTED_PCAP_SHA256)
    args = parser.parse_args()

    if hashlib.sha256(args.pcap.read_bytes()).hexdigest() != args.expected_sha256.lower():
        print("PCAP_SHA256_GATE=FAIL")
        print("NETWORK_IO_PERFORMED=false")
        return 2

    capture = load_capture(args.pcap)
    analysis = select_vip_flow(capture)
    try:
        result = analyze(collect_extended_vip_frames(analysis))
    except ValueError as exc:
        print(f"FORENSIC_GATE=FAIL reason={type(exc).__name__}")
        print("RAW_PAYLOAD_EMITTED=false")
        print("NETWORK_IO_PERFORMED=false")
        return 3

    print(report(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
