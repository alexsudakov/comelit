"""P116/R44 offline inbound-call peer simulator.

This module is a TEST/RESEARCH oracle only.  It performs no network I/O and
contains no Home Assistant or Comelit runtime action.

Two deliberately separate evidence modes exist:

* STRICT_NATIVE: uses only contracts recovered from primary staged native
  evidence (P116/R43B extraction).  Byte values that are runtime-derived are
  expressed as documented builders (offsets/width/endianness/source formula),
  never as copied capture literals.
* LAB_CORROBORATION: uses the pinned independent public implementation only to
  exercise parser/order/state-machine behaviour offline.  Its bytes MUST NOT be
  promoted into production constants.  The native extraction explicitly refutes
  the public alerting shape (opcode 0x000C / 8 bytes); the lab fixtures are kept
  unchanged on purpose so the two profiles cannot be confused.

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

# --- primary-native call-adoption contracts (P116/R43B) -----------------------
#
# CTP_TX_SERIALIZE(conn, body, len, flags):
#   wire byte 0  = flags_arg | (0x80 if queued body length == 0)
# The inbound RX path acknowledges a peer frame whose header flags byte has bit
# 6 (0x40) set by calling the serializer with flags argument 0 and an empty
# body, therefore the first adopted-call transport ACK carries wire flags 0x80.
NATIVE_FIRST_ACK_FLAGS = 0x80
NATIVE_FIRST_ACK_BODY_LENGTH = 0
NATIVE_FIRST_ACK_ACKNOWLEDGEMENT_FOLLOWS_SEQUENCE_PLUS_ONE = True
# The hash-pinned R30A/R30B offline model emits flags 0x00 and
# acknowledgement == peer_sequence.  Primary native evidence refutes both, so
# the frozen model is not a byte-exact source for the wire ACK.
R30B_ACK_BYTE_MODEL_MATCHES_NATIVE = False

# csp_send_capab_report: malloc(0x8), ctp_write(conn, body, 8)
#   body[0:2] = 00 03                    (wire inner opcode 0x0003)
#   body[2]   = call-type byte           (runtime: byte at [CallFsm+824]+18)
#   body[3]   = reserved byte            (native call site passes 0)
#   body[4:8] = 32-bit capability word   (runtime: CallFsm+840, little-endian)
NATIVE_CAPABILITIES_OPCODE = 0x0003
NATIVE_CAPABILITIES_BODY_LENGTH = 8
NATIVE_CAPABILITIES_FIXED_BYTES = bytes((0x00, 0x03))
NATIVE_CAPABILITIES_CALL_TYPE_OFFSET = 2
NATIVE_CAPABILITIES_RESERVED_OFFSET = 3
NATIVE_CAPABILITIES_RESERVED_BYTE = 0x00
NATIVE_CAPABILITIES_WORD_OFFSET = 4
NATIVE_CAPABILITIES_WORD_WIDTH = 4
NATIVE_CAPABILITIES_WORD_ENDIANNESS = "little"

# csp_send_alerting: malloc(0x3), ctp_write(conn, body, 3)
#   body[0:2] = 00 0a   (wire inner opcode 0x000A, native; NOT 0x000C)
#   body[2]   = one runtime byte; the adopted-call call site passes 0
NATIVE_ALERTING_OPCODE = 0x000A
NATIVE_ALERTING_BODY_LENGTH = 3
NATIVE_ALERTING_FIXED_BYTES = bytes((0x00, 0x0A))
NATIVE_ALERTING_FIELD_OFFSET = 2
NATIVE_ALERTING_ADOPTION_ARGUMENT = 0x00


def build_native_capabilities_body(*, call_type: int, capability_word: int) -> bytes:
    """Build the native CAPABILITIES body from the runtime field sources.

    Runtime-derived fields are expressed as a formula (offset/width/endianness),
    not as a copied capture literal.
    """
    if not 0 <= call_type <= 0xFF:
        raise ValueError("call_type must be one byte")
    if not 0 <= capability_word <= 0xFFFFFFFF:
        raise ValueError("capability_word must be 32-bit")
    return (
        NATIVE_CAPABILITIES_FIXED_BYTES
        + bytes((call_type, NATIVE_CAPABILITIES_RESERVED_BYTE))
        + struct.pack("<I", capability_word)
    )


def build_native_alerting_body(*, alerting_argument: int = NATIVE_ALERTING_ADOPTION_ARGUMENT) -> bytes:
    """Build the native ALERTING body: fixed opcode prefix plus one runtime byte."""
    if not 0 <= alerting_argument <= 0xFF:
        raise ValueError("alerting_argument must be one byte")
    return NATIVE_ALERTING_FIXED_BYTES + bytes((alerting_argument,))


def parse_native_capabilities_body(body: bytes) -> tuple[int, int, int]:
    """Return (call_type, reserved, capability_word) for a native CAPABILITIES body."""
    if len(body) != NATIVE_CAPABILITIES_BODY_LENGTH:
        raise ValueError("native CAPABILITIES body must be 8 bytes")
    if body[0:2] != NATIVE_CAPABILITIES_FIXED_BYTES:
        raise ValueError("native CAPABILITIES opcode prefix mismatch")
    word = struct.unpack_from("<I", body, NATIVE_CAPABILITIES_WORD_OFFSET)[0]
    return body[NATIVE_CAPABILITIES_CALL_TYPE_OFFSET], body[NATIVE_CAPABILITIES_RESERVED_OFFSET], word


def parse_native_alerting_body(body: bytes) -> int:
    """Return the single runtime byte of a native ALERTING body."""
    if len(body) != NATIVE_ALERTING_BODY_LENGTH:
        raise ValueError("native ALERTING body must be 3 bytes")
    if body[0:2] != NATIVE_ALERTING_FIXED_BYTES:
        raise ValueError("native ALERTING opcode prefix mismatch")
    return body[NATIVE_ALERTING_FIELD_OFFSET]


OP_CAPABILITIES = NATIVE_CAPABILITIES_OPCODE
# Kept for LAB fixtures; native evidence refutes 0x000C for csp_send_alerting.
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
    capabilities_opcode: int | None = None
    capabilities_body_length: int | None = None
    alerting_opcode: int | None = None
    alerting_body_length: int | None = None
    ack_acknowledgement_follows_sequence_plus_one: bool = False

    def require_strict_ready(self) -> None:
        missing: list[str] = []
        if self.ack_flags is None:
            missing.append("FIRST_ACK_FLAGS")
        # A contract counts as proven when either an exact literal body is
        # available or the native serializer layout (opcode + length + field
        # offsets) is pinned and the profile carries primary-native provenance.
        if self.capabilities_body is None and (
            self.capabilities_opcode is None or self.capabilities_body_length is None
        ):
            missing.append("CSP_SEND_CAPAB_REPORT_EXACT_BODY")
        if self.alerting_body is None and (
            self.alerting_opcode is None or self.alerting_body_length is None
        ):
            missing.append("CSP_SEND_ALERTING_EXACT_BODY")
        if self.capabilities_opcode is None or self.capabilities_body_length is None:
            missing.append("CAPABILITIES_OPCODE_LENGTH")
        if self.alerting_opcode is None or self.alerting_body_length is None:
            missing.append("ALERTING_OPCODE_LENGTH")
        if missing or not self.primary_native:
            raise EvidenceGap(
                "STRICT_NATIVE profile incomplete: " + ",".join(missing or ["PRIMARY_NATIVE_PROVENANCE"])
            )


# Primary-native profile: every byte contract below is recovered from the staged
# native evidence; runtime-derived fields stay symbolic through the builders.
STRICT_NATIVE_PROFILE = CallAdoptionWireProfile(
    name="STRICT_NATIVE",
    primary_native=True,
    ack_flags=NATIVE_FIRST_ACK_FLAGS,
    capabilities_body=None,
    alerting_body=build_native_alerting_body(),
    capabilities_opcode=NATIVE_CAPABILITIES_OPCODE,
    capabilities_body_length=NATIVE_CAPABILITIES_BODY_LENGTH,
    alerting_opcode=NATIVE_ALERTING_OPCODE,
    alerting_body_length=NATIVE_ALERTING_BODY_LENGTH,
    ack_acknowledgement_follows_sequence_plus_one=True,
)

LAB_CORROBORATION_PROFILE = CallAdoptionWireProfile(
    name="LAB_CORROBORATION",
    primary_native=False,
    ack_flags=FLAG_ACK,
    capabilities_body=LAB_LOCAL_CAPABILITIES_BODY,
    alerting_body=LAB_LOCAL_ALERTING_BODY,
    capabilities_opcode=NATIVE_CAPABILITIES_OPCODE,
    capabilities_body_length=len(LAB_LOCAL_CAPABILITIES_BODY),
    alerting_opcode=OP_SETUP_ACK,
    alerting_body_length=len(LAB_LOCAL_ALERTING_BODY),
)

STRICT_NATIVE_PROFILE_READY = True
LAB_CORROBORATION_STILL_ISOLATED = True


def profile_ready(profile: CallAdoptionWireProfile) -> bool:
    try:
        profile.require_strict_ready()
    except EvidenceGap:
        return False
    return True


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
    generation: int = 1
    call_type_byte: int = 0x49
    capability_word: int = 0x00000027

    @property
    def local_connection(self) -> bytes:
        return _direction_flip(self.peer_connection)

    @property
    def expected_first_ack_acknowledgement(self) -> int:
        return (self.peer_sequence + 1) & 0xFF

    def begin_generation(self, generation: int) -> None:
        """Reset transaction state so a new call generation cannot reuse it."""
        self.generation = generation
        self.events.clear()
        self.local_body_sequence = None
        self.local_capabilities_seen = False
        self.local_alerting_seen = False

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

    def build_native_local_ack(self, *, sequence: int | None = None) -> bytes:
        """Build the native-equivalent empty transport ACK for strict tests."""
        seq = self.peer_acknowledgement if sequence is None else sequence
        return build_ctp_envelope(
            flags=NATIVE_FIRST_ACK_FLAGS,
            connection=self.local_connection,
            sequence=seq,
            acknowledgement=self.expected_first_ack_acknowledgement,
            inner_body=b"",
            source_raw=self.destination_raw,
            destination_raw=self.source_raw,
        )

    def build_native_local_capabilities(self, *, sequence: int) -> bytes:
        return build_ctp_envelope(
            flags=FLAG_DATA,
            connection=self.local_connection,
            sequence=sequence,
            acknowledgement=self.expected_first_ack_acknowledgement,
            inner_body=build_native_capabilities_body(
                call_type=self.call_type_byte, capability_word=self.capability_word
            ),
            source_raw=self.destination_raw,
            destination_raw=self.source_raw,
        )

    def build_native_local_alerting(self, *, sequence: int) -> bytes:
        return build_ctp_envelope(
            flags=FLAG_DATA,
            connection=self.local_connection,
            sequence=sequence,
            acknowledgement=self.expected_first_ack_acknowledgement,
            inner_body=build_native_alerting_body(),
            source_raw=self.destination_raw,
            destination_raw=self.source_raw,
        )

    def observe_local_transport_ack(
        self,
        serialized_ctp_packet: bytes,
        *,
        profile: CallAdoptionWireProfile,
        strict_native: bool,
    ) -> None:
        if strict_native:
            profile.require_strict_ready()
        if self.local_capabilities_seen or self.local_alerting_seen:
            raise SimulationRejected("transport ACK after local signaling started")
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
        if profile.ack_acknowledgement_follows_sequence_plus_one:
            if envelope.acknowledgement != self.expected_first_ack_acknowledgement:
                raise SimulationRejected(
                    "native ACK acknowledgement must equal accepted peer sequence + 1"
                )
        elif envelope.acknowledgement != self.peer_sequence:
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
        if self.local_capabilities_seen:
            raise SimulationRejected("duplicate local CAPABILITIES")
        envelope = parse_ctp_envelope(serialized_ctp_packet)
        self._check_common_local(envelope)
        if envelope.flags != FLAG_DATA:
            raise SimulationRejected("CAPABILITIES must be DATA")
        if (
            profile.capabilities_opcode is not None
            and envelope.opcode != profile.capabilities_opcode
        ):
            raise SimulationRejected("CAPABILITIES opcode mismatch")
        if (
            profile.capabilities_body_length is not None
            and len(envelope.inner_body) != profile.capabilities_body_length
        ):
            raise SimulationRejected("CAPABILITIES length mismatch")
        if profile.capabilities_body is not None:
            if envelope.inner_body != profile.capabilities_body:
                raise SimulationRejected("CAPABILITIES body mismatch")
        else:
            try:
                call_type, reserved, word = parse_native_capabilities_body(envelope.inner_body)
            except ValueError as exc:
                raise SimulationRejected(f"native CAPABILITIES body invalid: {exc}") from exc
            if reserved != NATIVE_CAPABILITIES_RESERVED_BYTE:
                raise SimulationRejected("native CAPABILITIES reserved byte must be zero")
            if (call_type, word) != (self.call_type_byte, self.capability_word):
                raise SimulationRejected("CAPABILITIES runtime fields do not match sources")
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
        if self.local_alerting_seen:
            raise SimulationRejected("duplicate local ALERTING")
        envelope = parse_ctp_envelope(serialized_ctp_packet)
        self._check_common_local(envelope)
        if envelope.flags != FLAG_DATA:
            raise SimulationRejected("ALERTING must be DATA")
        if profile.alerting_opcode is not None and envelope.opcode != profile.alerting_opcode:
            raise SimulationRejected("ALERTING/setup opcode mismatch")
        if (
            profile.alerting_body_length is not None
            and len(envelope.inner_body) != profile.alerting_body_length
        ):
            raise SimulationRejected("ALERTING/setup length mismatch")
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


def run_strict_native_call(
    *, panel: FakeInboundPanel | None = None
) -> tuple[FakeInboundPanel, dict[str, bytes]]:
    """Drive one complete strict-native local signaling sequence offline.

    Returns the panel and the built local frames.  No network I/O happens here;
    the caller decides whether to parse/verify the frames.
    """
    panel = panel or FakeInboundPanel()
    panel.build_invite()
    ack = panel.build_native_local_ack()
    panel.observe_local_transport_ack(
        ack, profile=STRICT_NATIVE_PROFILE, strict_native=True
    )
    seq_after_ack = panel.local_body_sequence
    if seq_after_ack is None:
        raise EvidenceGap("transport ACK did not seed local body sequence")
    capabilities = panel.build_native_local_capabilities(sequence=seq_after_ack)
    panel.observe_local_capabilities(
        capabilities, profile=STRICT_NATIVE_PROFILE, strict_native=True
    )
    seq_after_capabilities = panel.local_body_sequence
    if seq_after_capabilities is None:
        raise EvidenceGap("CAPABILITIES did not advance local body sequence")
    alerting = panel.build_native_local_alerting(sequence=seq_after_capabilities)
    panel.observe_local_alerting(alerting, profile=STRICT_NATIVE_PROFILE, strict_native=True)
    return panel, {"ack": ack, "capabilities": capabilities, "alerting": alerting}


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
            "STRICT_NATIVE_FAILS_CLOSED=%s" % ("false" if STRICT_NATIVE_PROFILE_READY else "true"),
            "STRICT_NATIVE_PROFILE_READY=%s" % ("true" if STRICT_NATIVE_PROFILE_READY else "false"),
            "STRICT_NATIVE_PRIMARY_NATIVE_PROVENANCE=true",
            "FIRST_ACK_FLAGS=%#04x" % NATIVE_FIRST_ACK_FLAGS,
            "CAPABILITIES_OPCODE=%#06x" % NATIVE_CAPABILITIES_OPCODE,
            "CAPABILITIES_BODY_LENGTH=%d" % NATIVE_CAPABILITIES_BODY_LENGTH,
            "ALERTING_OPCODE=%#06x" % NATIVE_ALERTING_OPCODE,
            "ALERTING_BODY_LENGTH=%d" % NATIVE_ALERTING_BODY_LENGTH,
            "LAB_CORROBORATION_AVAILABLE=true",
            "LAB_CORROBORATION_STILL_ISOLATED=%s" % LAB_CORROBORATION_STILL_ISOLATED,
            "LAB_CONSTANTS_PROMOTABLE_TO_PRODUCTION=false",
            "=== END P116 R44 OFFLINE INBOUND CALL SIMULATOR ===",
        )
    )
