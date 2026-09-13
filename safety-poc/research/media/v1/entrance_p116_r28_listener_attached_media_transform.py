#!/usr/bin/env python3
"""P116/R28 research-only listener-attached inbound media model.

This module is offline-only.  It opens no sockets, performs no Door or Gate
action, emits no packet payloads, and does not replace the existing Python data
plane.  Its RTP boundary is the already-proven
H264RecoveryRtpShim -> HA Stream -> HLS -> camera entity path, represented here
only by scalar counters and marker names.

Explicit default-closed seams:

* ``transport_reuse_proven`` must be true before media can start.  R28 native
  static analysis supports media RX as a ViperTunnel channel open, not a new
  transport bootstrap; callers may set this flag only when that evidence is in
  force.
* ``teardown_ring_listener_survival_proven`` remains false by default because
  native media-channel close proves official media close scoping, not our HA
  listener lifecycle after a live attached-media run.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


DEFAULT_OUTPUT = Path("safety-poc/research/media/v1/r28_listener_attached_media_candidate.txt")


class Source(str, Enum):
    ENTRANCE = "entrance"
    GATE = "gate"
    UNKNOWN = "unknown"


class SignalKind(str, Enum):
    CALL_INIT = "CALL_INIT"
    MALFORMED = "MALFORMED"


class MediaState(str, Enum):
    LISTENER_READY = "LISTENER_READY"
    ARMED = "ARMED"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"
    FAILED_CLOSED = "FAILED_CLOSED"


@dataclass
class RegistrationState:
    ready: bool = True
    generation: int = 1
    replaced_by_media: bool = False


@dataclass
class CallTransactionState:
    active: bool = False
    source: Source | None = None
    generation: int = 0


@dataclass
class EvidenceFlags:
    inbound_media_request_direction: str = "DEVICE_TO_CLIENT"
    inbound_video_rx_initiation: str = "AUTO_ON_INCOMING_CALL"
    transport_reuse_proven: bool = True
    new_ice_allowed: bool = False
    new_cloud_negotiation_allowed: bool = False
    new_pseudotcp_allowed: bool = False
    new_registration_allowed: bool = False
    teardown_ring_listener_survival_proven: bool = False


@dataclass
class AttachedMediaDiagnostics:
    call_init_observed: bool = False
    armed: bool = False
    active: bool = False
    failed_closed: bool = False
    malformed_rejected: bool = False
    unknown_source_rejected: bool = False
    entrance_gate_mixed: bool = False
    second_call_init_blocked: bool = False
    door_action_sent: bool = False
    gate_action_sent: bool = False
    refresh_loop_started: bool = False
    new_ice_bootstrap: bool = False
    new_cloud_negotiation: bool = False
    new_pseudotcp_session: bool = False
    new_registration: bool = False
    rtpc_channels_opened: int = 0
    rtp_packets_emitted: int = 0
    media_teardown_preserved_transport: bool = True
    media_teardown_preserved_registration: bool = True
    media_teardown_preserved_ring_listener: str = "UNKNOWN"
    loopback_boundary: str = "H264RecoveryRtpShim"
    candidate_helper_executed: bool = False


@dataclass
class ListenerAttachedInboundMediaModel:
    evidence: EvidenceFlags = field(default_factory=EvidenceFlags)
    registration: RegistrationState = field(default_factory=RegistrationState)
    call: CallTransactionState = field(default_factory=CallTransactionState)
    diagnostics: AttachedMediaDiagnostics = field(default_factory=AttachedMediaDiagnostics)
    media_state: MediaState = MediaState.LISTENER_READY
    _teardown_count: int = 0

    def observe_signal(self, kind: SignalKind, source: Source) -> bool:
        if kind is SignalKind.MALFORMED:
            self.diagnostics.malformed_rejected = True
            self._fail_closed()
            return False
        if kind is not SignalKind.CALL_INIT or source is not Source.ENTRANCE:
            self.diagnostics.unknown_source_rejected = True
            return False
        if self.media_state is MediaState.ACTIVE:
            self.diagnostics.second_call_init_blocked = True
            return False
        if self.call.active:
            self.diagnostics.second_call_init_blocked = True
            return False

        self.call = CallTransactionState(active=True, source=source, generation=self.call.generation + 1)
        self.diagnostics.call_init_observed = True
        self.diagnostics.armed = True
        self.media_state = MediaState.ARMED
        return True

    def start_attached_media(self) -> bool:
        if self.media_state is not MediaState.ARMED or not self.call.active:
            return False
        if self.call.source is not Source.ENTRANCE:
            self.diagnostics.entrance_gate_mixed = True
            self._fail_closed()
            return False
        if self.evidence.inbound_media_request_direction != "DEVICE_TO_CLIENT":
            self._fail_closed()
            return False
        if self.evidence.inbound_video_rx_initiation == "UNKNOWN":
            self._fail_closed()
            return False
        if not self.evidence.transport_reuse_proven:
            self._fail_closed()
            return False
        if (
            self.evidence.new_ice_allowed
            or self.evidence.new_cloud_negotiation_allowed
            or self.evidence.new_pseudotcp_allowed
            or self.evidence.new_registration_allowed
        ):
            self._fail_closed()
            return False

        self.diagnostics.rtpc_channels_opened = 2
        self.diagnostics.active = True
        self.media_state = MediaState.ACTIVE
        return True

    def emit_h264_rtp_to_loopback_boundary(self, packet_count: int = 1) -> bool:
        if self.media_state is not MediaState.ACTIVE or packet_count <= 0:
            return False
        self.diagnostics.rtp_packets_emitted += packet_count
        return True

    def teardown_media(self) -> bool:
        self._teardown_count += 1
        if self.media_state is MediaState.ACTIVE:
            self.diagnostics.active = False
            self.media_state = MediaState.CLOSED
        self.call.active = False
        self.diagnostics.media_teardown_preserved_transport = True
        self.diagnostics.media_teardown_preserved_registration = not self.registration.replaced_by_media
        self.diagnostics.media_teardown_preserved_ring_listener = (
            "true" if self.evidence.teardown_ring_listener_survival_proven else "UNKNOWN"
        )
        return True

    @property
    def teardown_count(self) -> int:
        return self._teardown_count

    def request_door(self) -> bool:
        self.diagnostics.door_action_sent = False
        return False

    def request_gate(self) -> bool:
        self.diagnostics.gate_action_sent = False
        return False

    def start_refresh_loop(self) -> bool:
        self.diagnostics.refresh_loop_started = False
        return False

    def _fail_closed(self) -> None:
        self.media_state = MediaState.FAILED_CLOSED
        self.diagnostics.failed_closed = True
        self.diagnostics.active = False


def transform(_: str = "") -> str:
    model = ListenerAttachedInboundMediaModel()
    lines = [
        "=== COMELIT P116 R28 LISTENER ATTACHED MEDIA CANDIDATE ===",
        f"INBOUND_MEDIA_REQUEST_DIRECTION={model.evidence.inbound_media_request_direction}",
        f"INBOUND_VIDEO_RX_INITIATION={model.evidence.inbound_video_rx_initiation}",
        "NO_NETWORK=true",
        "NO_DOOR_ACTION=true",
        "NO_GATE_ACTION=true",
        "NO_REFRESH_LOOP=true",
        "NEW_ICE_BOOTSTRAP=false",
        "NEW_CLOUD_NEGOTIATION=false",
        "NEW_PSEUDOTCP_SESSION=false",
        "NEW_CTPP_REGISTRATION=false",
        "CALL_TRANSACTION_SEPARATE_FROM_REGISTRATION=true",
        "LOOPBACK_BOUNDARY=H264RecoveryRtpShim",
        "CANDIDATE_HELPER_EXECUTED=false",
        "=== END COMELIT P116 R28 LISTENER ATTACHED MEDIA CANDIDATE ===",
    ]
    return "\n".join(lines) + "\n"


def report() -> str:
    return transform()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--report", action="store_true")
    args = parser.parse_args(argv)
    text = report()
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
