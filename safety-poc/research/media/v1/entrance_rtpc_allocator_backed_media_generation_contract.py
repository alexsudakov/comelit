#!/usr/bin/env python3
"""P74: allocator-backed offline RTPC media body generation contract.

This module composes the P73 native target-id allocator model with the P72
RTPC OPEN and client media-signaling builders.  It performs no network I/O and
does not accept caller-supplied RTPC target ids on its public composition API.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import entrance_rtpc_client_media_generation_contract as p72
import entrance_rtpc_target_id_static_contract as p73

REFERENCE_GEOMETRY = p72.REFERENCE_GEOMETRY


@dataclass(frozen=True)
class AllocatorBackedClientMediaBodies:
    allocation_1: p73.AllocationResult
    allocation_2: p73.AllocationResult
    rtpc_open_1: bytes
    rtpc_open_2: bytes
    client_000a: bytes
    client_001a: bytes


def _allocate_two_or_raise(state: p73.AllocatorState) -> tuple[p73.AllocationResult, p73.AllocationResult]:
    allocation_1 = p73.allocate_target_id(state)
    if allocation_1 is None:
        raise RuntimeError("allocator exhausted before first RTPC allocation")

    allocation_2 = p73.allocate_target_id(state)
    if allocation_2 is None:
        raise RuntimeError("allocator exhausted before second RTPC allocation")

    if allocation_1.target_id == allocation_2.target_id:
        raise RuntimeError("allocator returned duplicate RTPC target ids")
    return allocation_1, allocation_2


def build_from_allocator_state(
    state: p73.AllocatorState,
    *,
    ctpp_seq_000a: int,
    ctpp_seq_001a: int,
    address_role_a: bytes,
    address_role_b: bytes,
    geometry: Sequence[int] = REFERENCE_GEOMETRY,
) -> AllocatorBackedClientMediaBodies:
    """Compose OPEN/0x000A/0x001A bodies from authoritative allocator results.

    The caller supplies allocator state and media context, but never the two
    RTPC target ids.  Collision skips, wrap, and exhaustion are delegated to P73.
    """
    allocation_1, allocation_2 = _allocate_two_or_raise(state)
    first = allocation_1.target_id
    second = allocation_2.target_id

    return AllocatorBackedClientMediaBodies(
        allocation_1=allocation_1,
        allocation_2=allocation_2,
        rtpc_open_1=p72.build_rtpc_open(first),
        rtpc_open_2=p72.build_rtpc_open(second),
        client_000a=p72.build_client_000a(
            previous_client_ctpp_sequence=ctpp_seq_000a,
            rtpc_target_id=first,
            address_role_a=address_role_a,
            address_role_b=address_role_b,
        ),
        client_001a=p72.build_client_001a(
            previous_client_ctpp_sequence=ctpp_seq_001a,
            rtpc_target_id=second,
            address_role_a=address_role_a,
            address_role_b=address_role_b,
            geometry=geometry,
        ),
    )


def build_from_runtime_rand_value(
    rand_value: int,
    *,
    ctpp_seq_000a: int,
    ctpp_seq_001a: int,
    address_role_a: bytes,
    address_role_b: bytes,
    geometry: Sequence[int] = REFERENCE_GEOMETRY,
) -> AllocatorBackedClientMediaBodies:
    """Build from the constructor seed rule `rand@LIBC() & 0x7fff`.

    The synthetic tunnel state includes the constructor-created MGMT channel id
    0, matching the official path proven in P73.
    """
    seed_low15 = p73.seed_from_runtime_prng(rand_value)
    state = p73.new_tunnel_state(seed_low15, include_mgmt_channel=True)
    return build_from_allocator_state(
        state,
        ctpp_seq_000a=ctpp_seq_000a,
        ctpp_seq_001a=ctpp_seq_001a,
        address_role_a=address_role_a,
        address_role_b=address_role_b,
        geometry=geometry,
    )


def report() -> str:
    return "\n".join(
        (
            "=== COMELIT P74 ALLOCATOR-BACKED RTPC MEDIA GENERATION CONTRACT ===",
            "RTPC_TARGET_ID_ALLOCATION_CONTRACT=PROVEN_STATIC",
            "RTPC_TARGET_ID_SOURCE=P73_NATIVE_ALLOCATOR",
            "RTPC_TARGET_IDS_CALLER_SUPPLIED=false",
            "RTPC_OPEN_GENERATION_CONTRACT=PROVEN_COMPOSED",
            "CLIENT_000A_GENERATION_CONTRACT=PROVEN_COMPOSED",
            "CLIENT_001A_GENERATION_CONTRACT=PROVEN_COMPOSED",
            "RTPC_ALLOCATOR_REQUIRES_STRICT_SEQUENTIAL_IDS=false",
            "CAPTURE_SEQUENTIAL_RELATION=OBSERVED_AND_EXPLAINED",
            "CAPTURE_SEQUENTIAL_IDS_EXPLAINED=true",
            f"RTPC_TARGET_ID_START_VALUE={p73.START_VALUE}",
            "CAPTURE_NUMERIC_TARGET_IDS_USED_AS_CONSTANTS=false",
            "OUTBOUND_RTPC_MEDIA_BODY_GENERATION_CONTRACT=PROVEN_OFFLINE_COMPOSED",
            "P72_HISTORY_MARKER=RTPC_TARGET_ID_ALLOCATION_CONTRACT_CALLER_SUPPLIED_NOT_PROVEN_PRESERVED_IN_P72",
            "P73_HISTORY_MARKER=GENERIC_NATIVE_ALLOCATOR_PROVEN_STATIC_PRESERVED_IN_P73",
            "LIVE_TRANSMISSION_AUTHORIZED=false",
            "NETWORK_IO_PERFORMED=false",
            "DNS_LOOKUP_PERFORMED=false",
            "P2P_ICE_STUN_TURN_PERFORMED=false",
            "PSEUDOTCP_PERFORMED=false",
            "CTPP_SIGNALING_SENT=false",
            "RTPC_SIGNALING_SENT=false",
            "DOOR_ACTION_SENT=false",
            "MEDIA_SIGNALING_SENT=false",
            "CAMERA_MEDIA_SESSION_STARTED=false",
            "RAW_PAYLOAD_EMITTED=false",
            "MEDIA_PAYLOAD_EMITTED=false",
            "PROPRIETARY_ARTIFACTS_COMMITTED=false",
            "=== END COMELIT P74 ALLOCATOR-BACKED RTPC MEDIA GENERATION CONTRACT ===",
        )
    )


def main() -> int:
    print(report())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
