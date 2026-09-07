#!/usr/bin/env python3
"""P72: compose proven RTPC OPEN and client media-signaling generation rules.

This module is OFFLINE ONLY.  It combines already-promoted contracts without
performing network I/O or allocating live RTPC target/channel ids:

* P70: RTPC ABCD OPEN is 15 bytes and OPEN[14] is channel transport = 1;
* P63/P65: client 0x000A/0x001A body structure, RTPC-id bindings, address-role
  placement, video geometry, and sequence deltas are capture-cross-validated.

The two RTPC target/channel ids remain caller supplied.  P66 proved they behave
as runtime-generated, distinct, non-zero correlation ids and observed a
sequential relation, but this module deliberately does not invent an allocator
or a starting value.  Therefore it is a deterministic body builder, not a live
launcher and not authorization to transmit anything.
"""
from __future__ import annotations

from dataclasses import dataclass
import struct
from typing import Sequence

from entrance_rtpc_open_trailer_static_contract import generation_contract, serialize_open

REFERENCE_GEOMETRY = (800, 480, 320, 240, 16)


@dataclass(frozen=True)
class ClientMediaBodies:
    rtpc_open_1: bytes
    rtpc_open_2: bytes
    client_000a: bytes
    client_001a: bytes


def _validate_u16(value: int, label: str, *, nonzero: bool = False) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{label} must be an integer")
    if not 0 <= value <= 0xFFFF:
        raise ValueError(f"{label} out of 16-bit range")
    if nonzero and value == 0:
        raise ValueError(f"{label} must be non-zero")
    return value


def _validate_u32(value: int, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 0xFFFFFFFF:
        raise ValueError(f"{label} out of 32-bit range")
    return value


def _validate_role(value: bytes, label: str) -> bytes:
    if not isinstance(value, bytes) or len(value) != 9:
        raise ValueError(f"{label} must be exactly 9 bytes")
    return value


def _validate_geometry(geometry: Sequence[int]) -> tuple[int, int, int, int, int]:
    values = tuple(geometry)
    if len(values) != 5:
        raise ValueError("geometry must contain exactly five fields")
    checked = tuple(_validate_u16(value, f"geometry[{index}]") for index, value in enumerate(values))
    if checked != REFERENCE_GEOMETRY:
        raise ValueError("only the cross-validated reference geometry is promoted")
    return checked  # type: ignore[return-value]


def rtpc_ids_sequential(first: int, second: int) -> bool:
    first = _validate_u16(first, "rtpc_target_1", nonzero=True)
    second = _validate_u16(second, "rtpc_target_2", nonzero=True)
    return ((second - first) & 0xFFFF) == 1


def build_rtpc_open(target_id: int) -> bytes:
    """Build one proven RTPC ABCD OPEN from a caller-supplied runtime target id."""
    target_id = _validate_u16(target_id, "rtpc_target_id", nonzero=True)
    entry = generation_contract(10)
    if entry.tag != b"RTPC" or entry.transport != 1:
        raise RuntimeError("promoted P70 RTPC contract changed")
    return serialize_open(entry.tag, target_id=target_id, transport=entry.transport)


def _base_body(length: int, *, sequence: int, action: int, flags: int) -> bytearray:
    sequence = _validate_u32(sequence, "sequence")
    action = _validate_u16(action, "action")
    flags = _validate_u16(flags, "flags")
    body = bytearray(length)
    body[0:2] = (0x1840).to_bytes(2, "little")
    body[2:6] = sequence.to_bytes(4, "little")
    body[6:8] = action.to_bytes(2, "big")
    body[8:10] = flags.to_bytes(2, "big")
    return body


def build_client_000a(
    *,
    previous_client_ctpp_sequence: int,
    rtpc_target_id: int,
    address_role_a: bytes,
    address_role_b: bytes,
) -> bytes:
    """Build client action 0x000A using the P63/P65 nearest-previous sequence rule."""
    sequence = _validate_u32(previous_client_ctpp_sequence, "previous_client_ctpp_sequence")
    target = _validate_u16(rtpc_target_id, "rtpc_target_id", nonzero=True)
    role_a = _validate_role(address_role_a, "address_role_a")
    role_b = _validate_role(address_role_b, "address_role_b")
    if role_a == role_b:
        raise ValueError("address roles must be distinct")

    body = _base_body(44, sequence=sequence, action=0x000A, flags=0x0011)
    body[10:16] = bytes((0x18, 0x02, 0x00, 0x00, 0x00, 0x00))
    body[16:18] = target.to_bytes(2, "little")
    body[18:20] = b"\x00\x00"
    body[20:24] = b"\xff" * 4
    body[24:33] = role_b
    body[33] = 0
    body[34:43] = role_a
    body[43] = 0
    return bytes(body)


def build_client_001a(
    *,
    previous_client_ctpp_sequence: int,
    rtpc_target_id: int,
    address_role_a: bytes,
    address_role_b: bytes,
    geometry: Sequence[int] = REFERENCE_GEOMETRY,
) -> bytes:
    """Build client action 0x001A using the P63/P65 nearest-previous +0x10000 rule."""
    previous = _validate_u32(previous_client_ctpp_sequence, "previous_client_ctpp_sequence")
    target = _validate_u16(rtpc_target_id, "rtpc_target_id", nonzero=True)
    role_a = _validate_role(address_role_a, "address_role_a")
    role_b = _validate_role(address_role_b, "address_role_b")
    if role_a == role_b:
        raise ValueError("address roles must be distinct")
    width, height, secondary_width, secondary_height, fps = _validate_geometry(geometry)
    sequence = (previous + 0x00010000) & 0xFFFFFFFF

    body = _base_body(60, sequence=sequence, action=0x001A, flags=0x0011)
    body[10:16] = bytes((0x14, 0x32, 0x00, 0x00, 0x00, 0x00))
    body[16:18] = target.to_bytes(2, "little")
    body[18:24] = b"\xff\xff\x00\x00\x00\x00"
    for offset, value in zip(
        (24, 26, 28, 30, 32),
        (width, height, secondary_width, secondary_height, fps),
    ):
        body[offset:offset + 2] = struct.pack("<H", value)
    body[34:36] = b"\x00\x00"
    body[36:40] = b"\xff" * 4
    body[40:49] = role_b
    body[49] = 0
    body[50:59] = role_a
    body[59] = 0
    return bytes(body)


def build_client_media_bodies(
    *,
    rtpc_target_1: int,
    rtpc_target_2: int,
    previous_sequence_for_000a: int,
    previous_sequence_for_001a: int,
    address_role_a: bytes,
    address_role_b: bytes,
    require_capture_sequential_ids: bool = True,
) -> ClientMediaBodies:
    """Compose two RTPC OPENs and the bound client 0x000A/0x001A bodies.

    The default sequential-id gate preserves the P66 observed relation while
    keeping allocation itself outside this module.  Callers may disable the gate
    for synthetic/unit analysis, but that does not promote a live allocator.
    """
    first = _validate_u16(rtpc_target_1, "rtpc_target_1", nonzero=True)
    second = _validate_u16(rtpc_target_2, "rtpc_target_2", nonzero=True)
    if first == second:
        raise ValueError("RTPC target ids must be distinct")
    if require_capture_sequential_ids and not rtpc_ids_sequential(first, second):
        raise ValueError("RTPC target ids do not satisfy the P66 sequential relation")

    return ClientMediaBodies(
        rtpc_open_1=build_rtpc_open(first),
        rtpc_open_2=build_rtpc_open(second),
        client_000a=build_client_000a(
            previous_client_ctpp_sequence=previous_sequence_for_000a,
            rtpc_target_id=first,
            address_role_a=address_role_a,
            address_role_b=address_role_b,
        ),
        client_001a=build_client_001a(
            previous_client_ctpp_sequence=previous_sequence_for_001a,
            rtpc_target_id=second,
            address_role_a=address_role_a,
            address_role_b=address_role_b,
        ),
    )


def report() -> str:
    return "\n".join(
        (
            "=== COMELIT P72 RTPC CLIENT MEDIA GENERATION CONTRACT ===",
            "RTPC_OPEN_BODY_CONTRACT=PROVEN",
            "RTPC_OPEN_TRAILER_CONTRACT=PROVEN_STATIC",
            "RTPC_OPEN_TRAILER_VALUE=1",
            "CLIENT_000A_BODY_CONTRACT=PROVEN_CAPTURE_CROSS_VALIDATED",
            "CLIENT_001A_BODY_CONTRACT=PROVEN_CAPTURE_CROSS_VALIDATED",
            "CLIENT_000A_SEQUENCE_RULE=NEAREST_PREVIOUS_CLIENT_CTPP_DELTA_0",
            "CLIENT_001A_SEQUENCE_RULE=NEAREST_PREVIOUS_CLIENT_CTPP_DELTA_0X00010000",
            "VIDEO_CONFIG_GEOMETRY=800x480 secondary=320x240 fps=16",
            "RTPC_TARGET_ID_RELATION=P66_DISTINCT_NONZERO_SEQUENTIAL_OBSERVED",
            "RTPC_TARGET_ID_ALLOCATION_CONTRACT=CALLER_SUPPLIED_NOT_PROVEN",
            "RTPC_TARGET_ID_START_VALUE=NOT_PROVEN",
            "LIVE_TRANSMISSION_AUTHORIZED=false",
            "NETWORK_IO_PERFORMED=false",
            "DOOR_ACTION_SENT=false",
            "MEDIA_SIGNALING_SENT=false",
            "ACK_SIGNALING_SENT=false",
            "RAW_PAYLOAD_EMITTED=false",
            "MEDIA_PAYLOAD_EMITTED=false",
            "=== END COMELIT P72 RTPC CLIENT MEDIA GENERATION CONTRACT ===",
        )
    )


def main() -> int:
    print(report())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
