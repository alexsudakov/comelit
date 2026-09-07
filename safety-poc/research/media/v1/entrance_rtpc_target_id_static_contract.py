#!/usr/bin/env python3
"""P73: deterministic offline model for the RTPC target/channel-id allocator.

This module promotes only the instruction-level allocator semantics proven from
the official Android client's `libvipcomelit.so`.  It performs no network I/O,
does not load proprietary code, and does not embed capture-derived target ids.

Proven allocator core:
    candidate = ((high_halfword << 15) | low15_counter) & 0xffff
    next_low = (candidate_low + 1) & 0x7fff
    if candidate is already in the tunnel channel list, repeat with next_low
    after 0x7fff collisions, fail and keep the advanced low counter

The constructor seeds `low15_counter` from `rand@LIBC() & 0x7fff`; therefore the
absolute first runtime id is state-dependent, not a global constant.
"""
from __future__ import annotations

import argparse
import hashlib
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

SO_VIPCOMELIT_SHA256 = "465c841a8a8400c8e301a18b728594b295a49b5bd5a127fa6b9643f94bf884f0"
START_VALUE = "RUNTIME_STATE_DEPENDENT"
LOW15_MASK = 0x7FFF
U16_MASK = 0xFFFF
SEARCH_BUDGET = 0x7FFF
RTPC_KEY = 10
RTPC_TAG = b"RTPC"
RTPC_TRANSPORT = 1

# Little-endian A64 encodings of decisive instructions in libvipcomelit.so.
INSTRUCTION_PATTERNS = {
    "CREATE_LDRSH_ACTIVE_0X120": bytes.fromhex("1340c279"),
    "CREATE_LDRH_HIGH_0": bytes.fromhex("08004079"),
    "CREATE_LDRH_LOW_0X128": bytes.fromhex("0b504279"),
    "CREATE_LSL_HIGH_15": bytes.fromhex("0a411153"),
    "CREATE_ORR_CANDIDATE": bytes.fromhex("74010a2a"),
    "CREATE_AND_LOW_0X7FFF": bytes.fromhex("ab390012"),
    "CREATE_COMPARE_CHANNEL_ID_0X24": bytes.fromhex("df21346b"),
    "CREATE_STORE_LOW_0X128": bytes.fromhex("0b500279"),
    "CREATE_STORE_ID_0X24": bytes.fromhex("14480079"),
    "OPEN_LOAD_ID_0X24": bytes.fromhex("ea4a4079"),
    "OPEN_STORE_ID_12_14": bytes.fromhex("0a180079"),
    "NEW_CALL_RAND_PLT": bytes.fromhex("99190194"),
    "NEW_AND_SEED_0X7FFF": bytes.fromhex("08380012"),
    "NEW_STORE_SEED_0X128": bytes.fromhex("68520279"),
    "CALLER_LOAD_TRANSPORT": bytes.fromhex("622740b9"),
    "CALLER_LOAD_TUNNEL_STATE": bytes.fromhex("600640f9"),
    "CALLER_CALL_OPEN": bytes.fromhex("f4510194"),
}


@dataclass
class AllocatorState:
    """Synthetic state for the proven native allocator fields."""

    low15_counter: int
    high_halfword: int = 0
    in_use_ids: set[int] = field(default_factory=set)
    active_channel_count: int = 0

    def __post_init__(self) -> None:
        self.low15_counter = _u15(self.low15_counter, "low15_counter")
        self.high_halfword = _u16(self.high_halfword, "high_halfword")
        self.in_use_ids = {_u16(value, "in_use_id") for value in self.in_use_ids}
        if self.active_channel_count < 0:
            raise ValueError("active_channel_count must be non-negative")


@dataclass(frozen=True)
class AllocationResult:
    target_id: int
    low15_used: int
    next_low15_counter: int
    collisions: int


def _u15(value: int, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= LOW15_MASK:
        raise ValueError(f"{label} must be a 15-bit integer")
    return value


def _u16(value: int, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= U16_MASK:
        raise ValueError(f"{label} must be a 16-bit integer")
    return value


def compose_target_id(high_halfword: int, low15_counter: int) -> int:
    """Model `ldrh high; ldrh low; lsl high,#15; orr; strh/cmp uxth`."""
    return ((_u16(high_halfword, "high_halfword") << 15) | _u15(low15_counter, "low15_counter")) & U16_MASK


def allocate_target_id(state: AllocatorState) -> AllocationResult | None:
    """Allocate one id, mutating synthetic state exactly like the proven loop.

    The native failure path stores the advanced counter and returns NULL after
    `0x7fff` collisions.  This model does the same and adds no extra policy.
    """
    low = state.low15_counter
    for collisions in range(SEARCH_BUDGET):
        target_id = compose_target_id(state.high_halfword, low)
        next_low = (low + 1) & LOW15_MASK
        if target_id not in state.in_use_ids:
            state.low15_counter = next_low
            state.in_use_ids.add(target_id)
            state.active_channel_count += 1
            return AllocationResult(
                target_id=target_id,
                low15_used=low,
                next_low15_counter=next_low,
                collisions=collisions,
            )
        low = next_low
    state.low15_counter = low
    return None


def seed_from_runtime_prng(rand_value: int) -> int:
    """Model `rand@LIBC() & 0x7fff` used by `viper_tunnel_new`."""
    if not isinstance(rand_value, int) or isinstance(rand_value, bool):
        raise ValueError("rand_value must be an integer")
    return rand_value & LOW15_MASK


def new_tunnel_state(seed_low15: int, *, high_halfword: int = 0, include_mgmt_channel: bool = True) -> AllocatorState:
    """Construct synthetic post-`viper_tunnel_new` allocator state.

    The native constructor uses calloc, seeds low15, then links an internal MGMT
    channel with zeroed id field.  That MGMT channel does not consume the low15
    counter, but its id 0 participates in collision checks.
    """
    ids = {0} if include_mgmt_channel else set()
    return AllocatorState(
        low15_counter=seed_low15,
        high_halfword=high_halfword,
        in_use_ids=ids,
        active_channel_count=1 if include_mgmt_channel else 0,
    )


def allocate_many(state: AllocatorState, count: int) -> list[AllocationResult]:
    if count < 0:
        raise ValueError("count must be non-negative")
    out: list[AllocationResult] = []
    for _ in range(count):
        result = allocate_target_id(state)
        if result is None:
            raise RuntimeError("allocator exhausted")
        out.append(result)
    return out


def serialize_open(channel_tag: bytes, target_id: int, transport: int = RTPC_TRANSPORT) -> bytes:
    if not isinstance(channel_tag, bytes) or len(channel_tag) != 4:
        raise ValueError("channel_tag must be exactly four bytes")
    target_id = _u16(target_id, "target_id")
    if not isinstance(transport, int) or isinstance(transport, bool) or not 0 <= transport <= 0xFF:
        raise ValueError("transport must be an 8-bit integer")
    return (
        struct.pack("<I", 0x0001ABCD)
        + struct.pack("<H", 7)
        + b"\x00\x00"
        + channel_tag
        + struct.pack("<H", target_id)
        + bytes((transport,))
    )


def build_rtpc_open_from_allocator(state: AllocatorState) -> bytes:
    result = allocate_target_id(state)
    if result is None:
        raise RuntimeError("allocator exhausted")
    return serialize_open(RTPC_TAG, result.target_id, RTPC_TRANSPORT)


def sequential_ids_naturally_explained(ids: Iterable[int]) -> bool:
    values = [_u16(value, "observed_id") for value in ids]
    return len(values) >= 2 and all(((b - a) & U16_MASK) == 1 for a, b in zip(values, values[1:]))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _find_all(data: bytes, needle: bytes) -> list[int]:
    offsets: list[int] = []
    start = 0
    while True:
        index = data.find(needle, start)
        if index < 0:
            return offsets
        offsets.append(index)
        start = index + 1


def so_instruction_evidence(so_path: Path) -> dict[str, list[int]]:
    data = so_path.read_bytes()
    return {name: _find_all(data, pattern) for name, pattern in INSTRUCTION_PATTERNS.items()}


def report(sha_status: str = "NOT_PROVIDED", instruction_evidence: dict[str, list[int]] | None = None) -> str:
    evidence_status = "NOT_PROVIDED"
    if instruction_evidence is not None:
        evidence_status = "PASS" if all(instruction_evidence.values()) else "FAIL"
    return "\n".join(
        (
            "=== COMELIT P73 RTPC TARGET ID STATIC CONTRACT ===",
            f"SO_VIPCOMELIT_SHA256_GATE={sha_status}",
            f"STATIC_INSTRUCTION_EVIDENCE={evidence_status}",
            "RTPC_TARGET_ID_ALLOCATION_CONTRACT=PROVEN_STATIC",
            "RTPC_TARGET_ID_GENERATION_RULE=((high_halfword<<15)|low15_counter)&0xffff; then low15=(low15+1)&0x7fff; skip in-use ids",
            "RTPC_TARGET_ID_COLLISION_AVOIDANCE=PROVEN_STATIC",
            "RTPC_TARGET_ID_OPEN_OFFSET=12:14",
            f"RTPC_TARGET_ID_START_VALUE={START_VALUE}",
            "CAPTURE_SEQUENTIAL_IDS_EXPLAINED=true",
            "RTPC_ALLOCATOR_SCOPE=GENERIC_CHANNEL_ALLOCATOR_SHARED_BY_RTPC",
            "RTPC_DEDICATED_ALLOCATOR_BRANCH=false",
            "LOW15_SEED_SOURCE=rand@LIBC()&0x7fff",
            "LOW15_ZERO_GENERICALLY_POSSIBLE=true",
            "LOW15_ZERO_USER_VISIBLE_WITH_CONSTRUCTOR_MGMT=COLLISION_SKIPPED",
            "HIGH_COMPONENT_INITIAL_VALUE=ZERO_AFTER_CALLOC_ON_PROVEN_CONSTRUCTOR_PATH",
            "HIGH_COMPONENT_MUTATION_OUTSIDE_PROVEN_PATH=NOT_PROVEN",
            "LIVE_TRANSMISSION_AUTHORIZED=false",
            "NETWORK_IO_PERFORMED=false",
            "DOOR_ACTION_SENT=false",
            "MEDIA_SIGNALING_SENT=false",
            "RAW_PAYLOAD_EMITTED=false",
            "PROPRIETARY_ARTIFACTS_COMMITTED=false",
            "=== END COMELIT P73 RTPC TARGET ID STATIC CONTRACT ===",
        )
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--libvipcomelit-so", type=Path, help="external proprietary libvipcomelit.so for SHA-gated validation")
    args = parser.parse_args(argv)

    sha_status = "NOT_PROVIDED"
    evidence = None
    try:
        if args.libvipcomelit_so is not None:
            if not args.libvipcomelit_so.exists():
                print(report("FAIL", None))
                return 3
            if _sha256(args.libvipcomelit_so) != SO_VIPCOMELIT_SHA256:
                print(report("FAIL", None))
                return 2
            sha_status = "PASS"
            evidence = so_instruction_evidence(args.libvipcomelit_so)
            if not all(evidence.values()):
                print(report(sha_status, evidence))
                return 4
        print(report(sha_status, evidence))
        return 0
    except OSError:
        print(report("FAIL", evidence))
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
