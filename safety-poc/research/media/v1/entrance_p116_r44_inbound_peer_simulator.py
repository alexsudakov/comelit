"""P116/R44 offline inbound-call peer simulator.

This module is a TEST/RESEARCH oracle only.  It performs no network I/O and
contains no Home Assistant or Comelit runtime action.

Two deliberately separate evidence modes exist:

* STRICT_NATIVE: requires byte-exact primary-native contracts.  At the time
  this file was introduced those contracts are intentionally incomplete, so
  the strict profile fails closed instead of inventing bytes.
* LAB_CORROBORATION: uses the pinned independent public implementation only
  to exercise parser/order/state-machine behaviour offline.  Its bytes MUST
  NOT be promoted into production constants.

The point of the simulator is to make physical calls a final hardware
validation step rather than the normal development/debug loop.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import struct

from entrance_p116_r30_call_ctp_envelope_model import (
    FLAG_ACK,
    FLAG_DATA,
    FLAG_SYN,
    OP_INVITE,
    build_ctp_envelope,
    parse_ctp_envelope,
)

OP_CAPABILITIES = 0x0003
OP_SETUP_ACK = 0x000C
CAP_VIDEO_REQUEST_BIT = 0x08

# Independent public implementation, pinned elsewhere in the research docs.
# These are LAB-ONLY fixtures and are never classified as primary-native.
LAB_LOCAL_CAPABILITIES_BODY = bytes.fromhex("00 03 49 00 27 00 00 00")
LAB_LOCAL_ALERTING_BODY = bytes.fromhex("00 0c 00 00 00 00 00 00")
LAB_PEER_CAPABILITIES_BODY = bytes.fromhex("00 03 50 03 3b 00 00 00")


class EvidenceGap(RuntimeError):
    """Raised when STRICT_NATIVE would otherwise require guessed bytes."""


class SimulationRejected(ValueError):
    """Raised when the synthetic peer sees an invalid/order-breaking frame."""


@dataclass(frozen=True, slots=True)
class CallAdoptionWireProfile:
    name: str
    primary_native: bool
    ack_flags: int | None
    capabilities_body: bytes | None
    alerting_body: bytes | None

    def require_strict_ready(self) -> None:
        missing: list[str] = []
        if self.ack_flags is None:
            missing.append("FIRST_ACK_FLAGS")
        if self.capabilities_body is None:
            missing.append("CSP_SEND_CAPAB_REPORT_EXACT_BODY")
        if self.alerting_body is None:
            missing.append("CSP_SEND_ALERTING_EXACT_BODY")
        if missing or not self.primary_native:
            raise EvidenceGap(
                "STRICT_NATIVE profile incomplete: " + ",".join(missing or ["PRIMARY_NATIVE_PROVENANCE"])
            )


STRICT_NATIVE_PROFILE = CallAdoptionWireProfile(
    name="STRICT_NATIVE",
    primary_native=True,
    ack_flags=None,
    capabilities_body=None,
    alerting_body=None,
)

LAB_CORROBORATION_PROFILE = CallAdoptionWireProfile(
    name="LAB_CORROBORATION",
    primary_native=False,
    ack_flags=FLAG_ACK,
    capabilities_body=LAB_LOCAL_CAPABILITIES_BODY,
    alerting_body=LAB_LOCAL_ALERTING_BODY,
)


def _direction_flip(connection: bytes) -> bytes:
    if len(connection) != 2:
        raise ValueError("connection must be exactly two bytes")
    word = struct.unpack(">H", connection)[0]
    return struct.pack(">H", word ^ 0x8000)


@dataclass(slots=True)
class FakeInboundPanel:
    """Deterministic, side-effect-free peer for one inbound call."""

    peer_connection: bytes = b"\x12\x34"
    peer_sequence: int = 0x56
    peer_acknowledgement: int = 0x78
    source_raw: bytes = b"00000643\x00\x00"
    destination_raw: bytes = b"000401177\x00"
    call_id: bytes = b"LAB1"
    events: list[str] = field(default_factory=list)
    local_body_sequence: int | None = None
    local_capabilities_seen: bool = False
    local_alerting_seen: bool = False

    @property
    def local_connection(self) -> bytes:
        return _direction_flip(self.peer_connection)

    def build_invite(self) -> bytes:
        body = bytearray(40)
        struct.pack_into(">H", body, 0, OP_INVITE)
        body[2:12] = self.source_raw
        body[12:22] = self.destination_raw
        body[24:28] = self.call_id
        packet = build_ctp_envelope(
            flags=FLAG_SYN,
            connection=self.peer_connection,
            sequence=self.peer_sequence,
            acknowledgement=self.peer_acknowledgement,
            inner_body=bytes(body),
            source_raw=self.source_raw,
            destination_raw=self.destination_raw,
        )
        self.events.append("PEER_INVITE_EMITTED")
        return packet

    def observe_local_transport_ack(
        self,
        serialized_ctp_packet: bytes,
        *,
        profile: CallAdoptionWireProfile,
        strict_native: bool,
    ) -> None:
        if strict_native:
            profile.require_strict_ready()
        envelope = parse_ctp_envelope(serialized_ctp_packet)
        self._check_common_local(envelope)
        if envelope.inner_body:
            raise SimulationRejected("transport ACK must have an empty body")
        if profile.ack_flags is None:
            raise EvidenceGap("ACK flags are not pinned")
        if envelope.flags != profile.ack_flags:
            raise SimulationRejected("transport ACK flags mismatch")
        if envelope.sequence != self.peer_acknowledgement:
            raise SimulationRejected("first local sequence must equal INVITE acknowledgement")
        if envelope.acknowledgement != self.peer_sequence:
            raise SimulationRejected("first local acknowledgement must equal INVITE sequence")
        self.local_body_sequence = envelope.sequence
        self.events.append("LOCAL_TRANSPORT_ACK_ACCEPTED")

    def observe_local_capabilities(
        self,
        serialized_ctp_packet: bytes,
        *,
        profile: CallAdoptionWireProfile,
        strict_native: bool,
    ) -> None:
        if strict_native:
            profile.require_strict_ready()
        if "LOCAL_TRANSPORT_ACK_ACCEPTED" not in self.events:
            raise SimulationRejected("CAPABILITIES before transport ACK")
        envelope = parse_ctp_envelope(serialized_ctp_packet)
        self._check_common_local(envelope)
        if envelope.flags != FLAG_DATA:
            raise SimulationRejected("CAPABILITIES must be DATA")
        if envelope.opcode != OP_CAPABILITIES or len(envelope.inner_body) != 8:
            raise SimulationRejected("CAPABILITIES opcode/length mismatch")
        if profile.capabilities_body is None:
            raise EvidenceGap("native CAPABILITIES body is not pinned")
        if envelope.inner_body != profile.capabilities_body:
            raise SimulationRejected("CAPABILITIES body mismatch")
        self._accept_local_body_sequence(envelope.sequence)
        self.local_capabilities_seen = True
        self.events.append("LOCAL_CAPABILITIES_ACCEPTED")

    def observe_local_alerting(
        self,
        serialized_ctp_packet: bytes,
        *,
        profile: CallAdoptionWireProfile,
        strict_native: bool,
    ) -> None:
        if strict_native:
            profile.require_strict_ready()
        if not self.local_capabilities_seen:
            raise SimulationRejected("ALERTING before CAPABILITIES")
        envelope = parse_ctp_envelope(serialized_ctp_packet)
        self._check_common_local(envelope)
        if envelope.flags != FLAG_DATA:
            raise SimulationRejected("ALERTING must be DATA")
        if envelope.opcode != OP_SETUP_ACK or len(envelope.inner_body) != 8:
            raise SimulationRejected("ALERTING/setup opcode/length mismatch")
        if profile.alerting_body is None:
            raise EvidenceGap("native ALERTING body is not pinned")
        if envelope.inner_body != profile.alerting_body:
            raise SimulationRejected("ALERTING body mismatch")
        self._accept_local_body_sequence(envelope.sequence)
        self.local_alerting_seen = True
        self.events.append("LOCAL_ALERTING_ACCEPTED")

    def build_peer_capabilities(self) -> bytes:
        if not (self.local_capabilities_seen and self.local_alerting_seen):
            raise SimulationRejected("peer CAPABILITIES withheld until call-adoption signaling completes")
        packet = build_ctp_envelope(
            flags=FLAG_DATA,
            connection=self.peer_connection,
            # R30C proves transport ownership/rules.  For this LAB fixture we
            # keep the first body-bearing peer sequence equal to the INVITE
            # sequence so R30B's strict accepted-body state can consume it.
            sequence=self.peer_sequence,
            acknowledgement=self.peer_acknowledgement,
            inner_body=LAB_PEER_CAPABILITIES_BODY,
            source_raw=self.source_raw,
            destination_raw=self.destination_raw,
        )
        self.events.append("PEER_CAPABILITIES_EMITTED")
        return packet

    def safe_transcript(self) -> tuple[str, ...]:
        """Return semantic events only; never raw payload/session bytes."""
        return tuple(self.events)

    def _check_common_local(self, envelope) -> None:
        if envelope.connection != self.local_connection:
            raise SimulationRejected("local call connection direction mismatch")
        if envelope.source_raw != self.destination_raw:
            raise SimulationRejected("local source logical address mismatch")
        if envelope.destination_raw != self.source_raw:
            raise SimulationRejected("local destination logical address mismatch")

    def _accept_local_body_sequence(self, sequence: int) -> None:
        if self.local_body_sequence is None:
            raise SimulationRejected("body sequence used before ACK state")
        if sequence != self.local_body_sequence:
            raise SimulationRejected("unexpected local body sequence")
        self.local_body_sequence = (self.local_body_sequence + 1) & 0xFF


def build_lab_local_packet(
    *,
    panel: FakeInboundPanel,
    sequence: int,
    acknowledgement: int,
    body: bytes,
    flags: int = FLAG_DATA,
) -> bytes:
    """Build one LAB-only local CTP packet for simulator regression tests."""
    return build_ctp_envelope(
        flags=flags,
        connection=panel.local_connection,
        sequence=sequence,
        acknowledgement=acknowledgement,
        inner_body=body,
        source_raw=panel.destination_raw,
        destination_raw=panel.source_raw,
    )


def report() -> str:
    return "\n".join(
        (
            "=== P116 R44 OFFLINE INBOUND CALL SIMULATOR ===",
            "NETWORK_IO=false",
            "PHYSICAL_CALLS=0",
            "STRICT_NATIVE_FAILS_CLOSED=true",
            "LAB_CORROBORATION_AVAILABLE=true",
            "LAB_CONSTANTS_PROMOTABLE_TO_PRODUCTION=false",
            "=== END P116 R44 OFFLINE INBOUND CALL SIMULATOR ===",
        )
    )
