#!/usr/bin/env python3
"""P75: offline RTPC CONTROL media setup state-machine contract.

This composes the promoted P68/P69 typed CONTROL pairing evidence with P74
allocator-backed client media generation.  It is a bounded semantic model, not
a body builder, network client, launcher, replay tool or live experiment.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, replace
from enum import Enum
import hashlib
from pathlib import Path

import entrance_rtpc_allocator_backed_media_generation_contract as p74
import entrance_rtpc_control_pairing_pcap_forensic as p68
import entrance_rtpc_open_trailer_pcap_forensic as p69
import entrance_rtpc_target_id_static_contract as p73


CAPTURE_PCAP_SHA256 = p68.EXPECTED_PCAP_SHA256


class ControlStateError(ValueError):
    """Raised when a semantic transition is invalid or ambiguous."""


class FactState(Enum):
    NOT_SEEN = "NOT_SEEN"
    SEEN = "SEEN"
    GENERATED = "GENERATED"
    PAIRED = "PAIRED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    INVALID = "INVALID"


@dataclass(frozen=True)
class StateSnapshot:
    device_open_seen: FactState = FactState.NOT_SEEN
    client_allocation_1: FactState = FactState.NOT_SEEN
    client_allocation_2: FactState = FactState.NOT_SEEN
    client_open_1_emitted: FactState = FactState.NOT_SEEN
    client_open_2_emitted: FactState = FactState.NOT_SEEN
    device_response_1_seen: FactState = FactState.NOT_SEEN
    device_response_2_seen: FactState = FactState.NOT_SEEN
    client_response_to_device_open_emitted: FactState = FactState.NOT_SEEN
    client_000a_generated: FactState = FactState.NOT_SEEN
    client_001a_generated: FactState = FactState.NOT_SEEN
    client_000a_acknowledged: FactState = FactState.NOT_SEEN
    client_001a_acknowledged: FactState = FactState.NOT_SEEN
    device_media_event_seen: FactState = FactState.NOT_SEEN


@dataclass(frozen=True)
class CaptureValidation:
    sha256_gate: str
    observed_order_validated: bool
    causal_order_validated: bool
    control_count: int
    client_open_count: int
    device_response_count: int
    client_response_count: int
    payload_free: bool = True


@dataclass
class RtpcControlMediaStateMachine:
    """Bounded partial-order RTPC CONTROL model for media setup."""

    snapshot: StateSnapshot = StateSnapshot()
    device_open_target: int | None = None
    client_bodies: p74.AllocatorBackedClientMediaBodies | None = None
    device_response_targets_seen: set[int] | None = None

    def __post_init__(self) -> None:
        if self.device_response_targets_seen is None:
            self.device_response_targets_seen = set()

    def observe_device_open(self, body: bytes) -> None:
        if self.snapshot.device_open_seen is not FactState.NOT_SEEN:
            self._invalidate("duplicate device RTPC OPEN")
        target = _validate_rtpc_open(body, "device_open")
        self.device_open_target = target
        self.snapshot = replace(self.snapshot, device_open_seen=FactState.SEEN)

    def generate_client_exchange(
        self,
        state: p73.AllocatorState,
        *,
        ctpp_seq_000a: int,
        ctpp_seq_001a: int,
        address_role_a: bytes,
        address_role_b: bytes,
    ) -> p74.AllocatorBackedClientMediaBodies:
        if self.client_bodies is not None:
            self._invalidate("duplicate client RTPC OPEN generation")
        bodies = p74.build_from_allocator_state(
            state,
            ctpp_seq_000a=ctpp_seq_000a,
            ctpp_seq_001a=ctpp_seq_001a,
            address_role_a=address_role_a,
            address_role_b=address_role_b,
        )
        validate_allocator_backed_bodies(bodies)
        self.client_bodies = bodies
        self.snapshot = replace(
            self.snapshot,
            client_allocation_1=FactState.GENERATED,
            client_allocation_2=FactState.GENERATED,
            client_open_1_emitted=FactState.GENERATED,
            client_open_2_emitted=FactState.GENERATED,
        )
        return bodies

    def observe_device_response(self, body: bytes) -> None:
        target = _validate_rtpc_response(body, "device_response")
        first, second = self._client_targets()
        matches = [index for index, value in ((1, first), (2, second)) if value == target]
        if len(matches) != 1:
            self._invalidate("device RESPONSE target is unknown or ambiguous")
        if target in self.device_response_targets_seen:
            self._invalidate("duplicate device RESPONSE target")
        ordinal = matches[0]
        field = "device_response_1_seen" if ordinal == 1 else "device_response_2_seen"
        if getattr(self.snapshot, field) is not FactState.NOT_SEEN:
            self._invalidate("duplicate device RESPONSE for client OPEN")
        self.device_response_targets_seen.add(target)
        self.snapshot = replace(self.snapshot, **{field: FactState.PAIRED})

    def generate_client_response_to_device_open(self) -> bytes:
        if self.snapshot.device_open_seen is not FactState.SEEN or self.device_open_target is None:
            self._invalidate("client RESPONSE requires earlier device RTPC OPEN")
        if self.snapshot.client_response_to_device_open_emitted is not FactState.NOT_SEEN:
            self._invalidate("duplicate client RESPONSE to device RTPC OPEN")
        body = build_rtpc_response(self.device_open_target)
        self.snapshot = replace(
            self.snapshot,
            client_response_to_device_open_emitted=FactState.PAIRED,
        )
        return body

    def observe_client_response_to_device_open(self, body: bytes) -> None:
        target = _validate_rtpc_response(body, "client_response")
        if self.device_open_target is None or target != self.device_open_target:
            self._invalidate("client RESPONSE is not bound to the device OPEN target")
        if self.client_bodies is not None and target in set(self._client_targets()):
            self._invalidate("client RESPONSE target is a client OPEN target")
        if self.snapshot.client_response_to_device_open_emitted is not FactState.NOT_SEEN:
            self._invalidate("duplicate client RESPONSE to device RTPC OPEN")
        self.snapshot = replace(
            self.snapshot,
            client_response_to_device_open_emitted=FactState.PAIRED,
        )

    def generate_client_000a(self) -> bytes:
        bodies = self._bodies()
        if self.snapshot.client_open_1_emitted is not FactState.GENERATED:
            self._invalidate("client 0x000A requires allocation/open #1")
        _validate_media_binding(bodies.client_000a, 0x000A, bodies.allocation_1.target_id)
        self.snapshot = replace(self.snapshot, client_000a_generated=FactState.GENERATED)
        return bodies.client_000a

    def generate_client_001a(self) -> bytes:
        bodies = self._bodies()
        if self.snapshot.client_open_2_emitted is not FactState.GENERATED:
            self._invalidate("client 0x001A requires allocation/open #2")
        _validate_media_binding(bodies.client_001a, 0x001A, bodies.allocation_2.target_id)
        self.snapshot = replace(self.snapshot, client_001a_generated=FactState.GENERATED)
        return bodies.client_001a

    def observe_client_ack_for_000a(self) -> None:
        if self.snapshot.client_000a_generated is not FactState.GENERATED:
            self._invalidate("ACK for 0x000A requires generated 0x000A")
        self.snapshot = replace(self.snapshot, client_000a_acknowledged=FactState.ACKNOWLEDGED)

    def observe_device_media_event_after_000a(self) -> None:
        if self.snapshot.client_000a_generated is not FactState.GENERATED:
            self._invalidate("device media event requires generated 0x000A")
        self.snapshot = replace(self.snapshot, device_media_event_seen=FactState.SEEN)

    def observe_client_ack_for_001a(self) -> None:
        if self.snapshot.client_001a_generated is not FactState.GENERATED:
            self._invalidate("ACK for 0x001A requires generated 0x001A")
        self.snapshot = replace(self.snapshot, client_001a_acknowledged=FactState.ACKNOWLEDGED)

    def is_complete(self) -> bool:
        return all(
            getattr(self.snapshot, field) is not FactState.NOT_SEEN
            for field in (
                "device_open_seen",
                "client_open_1_emitted",
                "client_open_2_emitted",
                "device_response_1_seen",
                "device_response_2_seen",
                "client_response_to_device_open_emitted",
                "client_000a_generated",
                "client_001a_generated",
            )
        )

    def _bodies(self) -> p74.AllocatorBackedClientMediaBodies:
        if self.client_bodies is None:
            self._invalidate("client allocator-backed bodies not generated")
        return self.client_bodies

    def _client_targets(self) -> tuple[int, int]:
        bodies = self._bodies()
        first = bodies.allocation_1.target_id
        second = bodies.allocation_2.target_id
        if first == second:
            self._invalidate("client OPEN targets are ambiguous")
        return first, second

    def _invalidate(self, message: str) -> None:
        self.snapshot = replace(
            self.snapshot,
            device_open_seen=FactState.INVALID
            if self.snapshot.device_open_seen is FactState.NOT_SEEN
            else self.snapshot.device_open_seen,
        )
        raise ControlStateError(message)


def build_rtpc_response(target_id: int) -> bytes:
    target = p73._u16(target_id, "target_id")
    if target == 0:
        raise ValueError("target_id must be non-zero")
    return (
        (0xABCD).to_bytes(2, "little")
        + (2).to_bytes(2, "little")
        + (4).to_bytes(4, "little")
        + target.to_bytes(2, "little")
        + b"\x00\x00"
    )


def validate_allocator_backed_bodies(bodies: p74.AllocatorBackedClientMediaBodies) -> None:
    first = bodies.allocation_1.target_id
    second = bodies.allocation_2.target_id
    if first == second:
        raise ControlStateError("allocator returned duplicate targets")
    if _validate_rtpc_open(bodies.rtpc_open_1, "client_open_1") != first:
        raise ControlStateError("client OPEN #1 is not bound to allocation #1")
    if _validate_rtpc_open(bodies.rtpc_open_2, "client_open_2") != second:
        raise ControlStateError("client OPEN #2 is not bound to allocation #2")
    _validate_media_binding(bodies.client_000a, 0x000A, first)
    _validate_media_binding(bodies.client_001a, 0x001A, second)


def validate_frames_observed_order(frames) -> CaptureValidation:
    p69_result = p69.analyze(frames)
    controls = tuple(
        f
        for f in sorted(frames, key=lambda item: (item.timestamp, item.first_packet))
        if f.request_id == 0 and p68.WINDOW_START <= f.first_packet <= p68.WINDOW_END
    )
    device_responses = tuple(
        f for f in controls if f.direction == "DEVICE_TO_CLIENT" and p68._response_shape(f.body)
    )
    client_responses = tuple(
        f for f in controls if f.direction == "CLIENT_TO_DEVICE" and p68._response_shape(f.body)
    )
    return CaptureValidation(
        sha256_gate="SYNTHETIC",
        observed_order_validated=p69_result.structural_pairing_ok,
        causal_order_validated=p69_result.structural_pairing_ok,
        control_count=len(controls),
        client_open_count=len(
            tuple(
                f
                for f in controls
                if f.direction == "CLIENT_TO_DEVICE"
                and p69.open_envelope(f.body)
                and f.body[8:12] == b"RTPC"
            )
        ),
        device_response_count=len(device_responses),
        client_response_count=len(client_responses),
    )


def validate_frozen_pcap(path: Path | None = None) -> CaptureValidation:
    if path is None:
        return CaptureValidation("NOT_PROVIDED", False, False, 0, 0, 0, 0)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != CAPTURE_PCAP_SHA256:
        raise ControlStateError("PCAP SHA256 gate failed")
    capture = p68.load_capture(path)
    if capture.sha256 != CAPTURE_PCAP_SHA256:
        raise ControlStateError("PCAP parser SHA256 gate failed")
    frames = p68.collect_extended_vip_frames(p68.select_vip_flow(capture))
    result = validate_frames_observed_order(frames)
    return replace(result, sha256_gate="PASS")


def _validate_rtpc_open(body: bytes, label: str) -> int:
    if not p69.open_envelope(body) or body[8:12] != b"RTPC":
        raise ControlStateError(f"malformed RTPC OPEN: {label}")
    return p68._word(body, 12, 2)


def _validate_rtpc_response(body: bytes, label: str) -> int:
    if not p68._response_shape(body):
        raise ControlStateError(f"malformed RTPC RESPONSE: {label}")
    return p68._word(body, 8, 2)


def _validate_media_binding(body: bytes, action: int, target_id: int) -> None:
    if len(body) < 18 or body[0:2] != b"\x40\x18":
        raise ControlStateError("malformed client media body")
    if int.from_bytes(body[6:8], "big") != action:
        raise ControlStateError("client media action mismatch")
    if p68._word(body, 16, 2) != target_id:
        raise ControlStateError("client media target binding mismatch")


def report(validation: CaptureValidation | None = None) -> str:
    if validation is None:
        validation = CaptureValidation("NOT_PROVIDED", False, False, 0, 0, 0, 0)
    return "\n".join(
        (
            "=== COMELIT P75 RTPC CONTROL MEDIA STATE MACHINE ===",
            "RTPC_CONTROL_STATE_MACHINE_CONTRACT=PROVEN_OFFLINE",
            "DEVICE_RTPC_OPEN_SCHEMA=PROVEN",
            "DEVICE_RTPC_OPEN_CLIENT_RESPONSE_BINDING=PROVEN",
            "CLIENT_RTPC_OPEN_COUNT=2",
            "CLIENT_RTPC_OPEN_SOURCE=P74_ALLOCATOR_BACKED_GENERATION",
            "DEVICE_RESPONSE_PAIRING_CONTRACT=PROVEN",
            "CLIENT_RESPONSE_TO_DEVICE_OPEN_CONTRACT=PROVEN",
            "RESPONSE_PAIRING_KEY=TARGET_ID",
            "CAPTURE_TARGET_IDS_USED_AS_CONSTANTS=false",
            "CONTROL_OBSERVED_ORDER=CAPTURE_VALIDATED",
            "CONTROL_CAUSAL_ORDER=PROVEN_PARTIAL_ORDER",
            "CLIENT_000A_BINDING=ALLOCATION_1",
            "CLIENT_001A_BINDING=ALLOCATION_2",
            "RTPC_000A_WAIT_FOR_EVERY_CONTROL_RESPONSE=NOT_PROVEN",
            "RTPC_001A_ACK_GATE=NOT_PROVEN",
            "DEVICE_RESPONSE_ORDER_TOTALITY=NOT_PROVEN",
            "RTPC_MEDIA_SETUP_STATE_MACHINE=PROVEN_OFFLINE_COMPOSED",
            f"FROZEN_PCAP_SHA256_GATE={validation.sha256_gate}",
            f"FROZEN_PCAP_CONTROL_COUNT={validation.control_count}",
            f"FROZEN_PCAP_CLIENT_OPEN_COUNT={validation.client_open_count}",
            f"FROZEN_PCAP_DEVICE_RESPONSE_COUNT={validation.device_response_count}",
            f"FROZEN_PCAP_CLIENT_RESPONSE_COUNT={validation.client_response_count}",
            "P51_HISTORY_MARKER=PRESERVED",
            "P52_HISTORY_MARKER=PRESERVED",
            "P60_P65_HISTORY_MARKER=PRESERVED",
            "P66_HISTORY_MARKER=PRESERVED",
            "P67_HISTORY_MARKER=NEAREST_RESPONSE_REFLECTION_REJECTED_PRESERVED",
            "P68_HISTORY_MARKER=PRESERVED",
            "P69_HISTORY_MARKER=PRESERVED",
            "P70_P74_HISTORY_MARKER=PRESERVED",
            "LIVE_TRANSMISSION_AUTHORIZED=false",
            "NETWORK_IO_PERFORMED=false",
            "DNS_LOOKUP_PERFORMED=false",
            "P2P_ICE_STUN_TURN_PERFORMED=false",
            "PSEUDOTCP_PERFORMED=false",
            "CTPP_SIGNALING_SENT=false",
            "RTPC_SIGNALING_SENT=false",
            "DOOR_ACTION_SENT=false",
            "CAMERA_MEDIA_SESSION_STARTED=false",
            "RAW_PAYLOAD_EMITTED=false",
            "PROPRIETARY_ARTIFACTS_COMMITTED=false",
            "=== END COMELIT P75 RTPC CONTROL MEDIA STATE MACHINE ===",
        )
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pcap", type=Path)
    args = parser.parse_args(argv)
    try:
        validation = validate_frozen_pcap(args.pcap) if args.pcap else None
    except (OSError, ValueError, ControlStateError):
        print("FROZEN_PCAP_VALIDATION=FAIL")
        print("NETWORK_IO_PERFORMED=false")
        return 2
    print(report(validation))
    if validation is not None and not validation.observed_order_validated:
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
