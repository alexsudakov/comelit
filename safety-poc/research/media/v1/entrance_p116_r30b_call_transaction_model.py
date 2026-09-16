"""P116/R30B offline call-transaction model.

This module is an intercepted, offline-only model. It never opens transports,
never shells out, and never calls Home Assistant or Comelit live surfaces.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import struct
from typing import Callable

from entrance_p116_r30_call_ctp_envelope_model import (
    FLAG_ACK,
    FLAG_DATA,
    FLAG_SYN,
    LOGADDR_LEN,
    OP_INVITE,
    OP_MEDIA_REQUEST,
    build_call_bound_media_packet,
    build_ctp_envelope,
    is_inbound_invite,
    parse_ctp_envelope,
)

LOCAL_CONNECTION_DIRECTION_RULE = "NATIVE_PROVEN"
OFFICIAL_NATIVE_LOCAL_ID_EQUIVALENCE = "PROVEN"
MEDIA_CHANNEL_ALLOCATOR_STATUS = "OFFLINE_COMPONENT_ONLY"
MEDIA_OPEN_BEFORE_CALL_SIGNALING_BARRIER = "REJECTED"

PROFILE_PROVENANCE = (
    "EXTERNAL_TESTED_CLIENT_PROFILE:public-jfmlima:"
    "e3714dcccadb5bf934c32ce1400d891c3cfc61bb:call.py:_video_settings"
)


class TransactionRejected(ValueError):
    """Raised when a candidate transition must fail closed."""


@dataclass(frozen=True, slots=True)
class OuterCtppHandle:
    value: int

    def __post_init__(self) -> None:
        if not isinstance(self.value, int) or self.value <= 0:
            raise ValueError("outer CTPP handle must be a positive integer")


@dataclass(frozen=True, slots=True)
class InboundPeerFacts:
    outer_ctpp_handle: OuterCtppHandle
    peer_connection_id: bytes
    peer_sequence: int
    peer_acknowledgement: int
    source_logical_address: bytes
    destination_logical_address: bytes
    logical_call_id: bytes


@dataclass(frozen=True, slots=True)
class InterceptedWrite:
    semantic_kind: str
    outer_ctpp_handle: OuterCtppHandle
    serialized_ctp_packet: bytes
    call_connection_id: bytes
    sequence: int
    acknowledgement: int
    inner_opcode: int | None
    inner_length: int


@dataclass(slots=True)
class InterceptedWriter:
    writes: list[InterceptedWrite] = field(default_factory=list)

    def intercept(
        self,
        *,
        semantic_kind: str,
        outer_ctpp_handle: OuterCtppHandle,
        serialized_ctp_packet: bytes,
        call_connection_id: bytes,
        sequence: int,
        acknowledgement: int,
        inner_opcode: int | None,
        inner_length: int,
    ) -> InterceptedWrite:
        record = InterceptedWrite(
            semantic_kind=semantic_kind,
            outer_ctpp_handle=outer_ctpp_handle,
            serialized_ctp_packet=serialized_ctp_packet,
            call_connection_id=_require_connection_id(call_connection_id),
            sequence=sequence,
            acknowledgement=acknowledgement,
            inner_opcode=inner_opcode,
            inner_length=inner_length,
        )
        self.writes.append(record)
        return record

    @property
    def intercepted_ack_writes(self) -> int:
        return sum(1 for write in self.writes if write.semantic_kind == "TRANSPORT_ACK")

    @property
    def intercepted_media_open_writes(self) -> int:
        return sum(1 for write in self.writes if write.semantic_kind == "MEDIA_OPEN")

    @property
    def intercepted_media_stop_writes(self) -> int:
        return sum(1 for write in self.writes if write.semantic_kind == "MEDIA_STOP")

    @property
    def network_writes(self) -> int:
        return 0

    @property
    def door_actions(self) -> int:
        return 0

    @property
    def gate_actions(self) -> int:
        return 0

    @property
    def self_activation_actions(self) -> int:
        return 0

    @property
    def refresh_or_repeat_actions(self) -> int:
        return 0


@dataclass(slots=True)
class CallTransaction:
    inbound_serialized_ctp_packet: bytes
    outer_ctpp_handle: OuterCtppHandle
    peer_connection_id: bytes
    candidate_local_connection_id: bytes
    peer_sequence: int
    peer_acknowledgement: int
    next_tx_sequence: int
    next_tx_acknowledgement: int
    source_logical_address: bytes
    destination_logical_address: bytes
    logical_call_id: bytes
    call_phase: str
    media_channel_id: int | None = None
    media_phase: str = "NONE"
    write_count: int = 0
    events: list[str] = field(default_factory=list)

    @classmethod
    def from_peer_facts(
        cls,
        facts: InboundPeerFacts,
        *,
        inbound_serialized_ctp_packet: bytes,
        next_tx_sequence_seed: int | None = None,
    ) -> CallTransaction:
        del next_tx_sequence_seed
        return cls(
            inbound_serialized_ctp_packet=inbound_serialized_ctp_packet,
            outer_ctpp_handle=facts.outer_ctpp_handle,
            peer_connection_id=_require_connection_id(facts.peer_connection_id),
            candidate_local_connection_id=derive_native_local_connection_id(facts.peer_connection_id),
            peer_sequence=facts.peer_sequence,
            peer_acknowledgement=facts.peer_acknowledgement,
            next_tx_sequence=facts.peer_acknowledgement,
            next_tx_acknowledgement=facts.peer_sequence,
            source_logical_address=_require_logical_address(facts.destination_logical_address),
            destination_logical_address=_require_logical_address(facts.source_logical_address),
            logical_call_id=facts.logical_call_id,
            call_phase="CREATED",
            events=["CALL_TRANSACTION_CREATED"],
        )

    def connection_for_serialization(self) -> bytes:
        return _require_connection_id(self.candidate_local_connection_id)

    @property
    def local_tx_sequence(self) -> int:
        return self.next_tx_sequence

    @property
    def local_acknowledgement(self) -> int:
        return self.next_tx_acknowledgement

    def intercept_transport_ack(self, writer: InterceptedWriter) -> InterceptedWrite:
        packet = build_ctp_envelope(
            flags=FLAG_ACK,
            connection=self.connection_for_serialization(),
            sequence=self.next_tx_sequence,
            acknowledgement=self.next_tx_acknowledgement,
            inner_body=b"",
            source_raw=self.source_logical_address,
            destination_raw=self.destination_logical_address,
        )
        record = writer.intercept(
            semantic_kind="TRANSPORT_ACK",
            outer_ctpp_handle=self.outer_ctpp_handle,
            serialized_ctp_packet=packet,
            call_connection_id=self.connection_for_serialization(),
            sequence=self.next_tx_sequence,
            acknowledgement=self.next_tx_acknowledgement,
            inner_opcode=None,
            inner_length=0,
        )
        self.write_count += 1
        self.events.append("TRANSPORT_ACK_INTERCEPTED")
        return record

    def accept_inbound_body_packet(self, serialized_ctp_packet: bytes) -> None:
        envelope = parse_ctp_envelope(serialized_ctp_packet)
        if envelope.version != 0x18:
            raise TransactionRejected("unsupported CTP version")
        if envelope.is_syn or envelope.flags != FLAG_DATA:
            raise TransactionRejected("accepted inbound body must be CTP DATA")
        if envelope.connection != self.peer_connection_id:
            raise TransactionRejected("inbound body connection mismatch")
        if not envelope.inner_body:
            raise TransactionRejected("accepted inbound body must carry a body")
        if envelope.sequence != self.next_tx_acknowledgement:
            raise TransactionRejected("inbound body sequence is not the next expected peer sequence")
        self.next_tx_acknowledgement = (envelope.sequence + 1) % 256

    def intercept_capability_stage(self) -> None:
        if "TRANSPORT_ACK_INTERCEPTED" not in self.events:
            raise TransactionRejected("capability stage requires intercepted ACK")
        self.events.append("CAPABILITY_STAGE_INTERCEPTED")

    def intercept_alerting_stage(self) -> None:
        if "CAPABILITY_STAGE_INTERCEPTED" not in self.events:
            raise TransactionRejected("alerting stage requires capability stage")
        self.events.append("ALERTING_STAGE_INTERCEPTED")

    def reach_call_signaling_order_barrier(self) -> None:
        if "ALERTING_STAGE_INTERCEPTED" not in self.events:
            raise TransactionRejected("barrier requires alerting stage")
        self.call_phase = "SIGNALING_BARRIER_REACHED"
        self.events.append("CALL_SIGNALING_ORDER_BARRIER_REACHED")

    def allocate_media_channel(self, allocator: Callable[[], int]) -> int:
        if "CALL_SIGNALING_ORDER_BARRIER_REACHED" not in self.events:
            raise TransactionRejected("media channel allocation requires call signaling barrier")
        if self.media_channel_id is not None:
            raise TransactionRejected("media channel already allocated")
        candidate = allocator()
        if not isinstance(candidate, int) or not 1 <= candidate <= 0xFFFF:
            raise TransactionRejected("media channel id must be non-zero LE16")
        self.media_channel_id = candidate
        self.media_phase = "ALLOCATED"
        self.events.append("MEDIA_CHANNEL_ALLOCATED")
        return candidate

    def intercept_media_open(self, writer: InterceptedWriter) -> InterceptedWrite:
        if "CALL_SIGNALING_ORDER_BARRIER_REACHED" not in self.events:
            raise TransactionRejected("media OPEN before call signaling barrier rejected")
        if self.media_channel_id is None:
            raise TransactionRejected("media OPEN before media-channel allocation rejected")
        if self.media_phase == "ACTIVE":
            raise TransactionRejected("second media OPEN rejected")
        if self.media_phase == "STOPPED":
            raise TransactionRejected("media OPEN after STOP rejected")
        mediareq26 = build_mediareq26_open(self.media_channel_id)
        record = self._intercept_media_packet(writer, "MEDIA_OPEN", mediareq26)
        self.media_phase = "ACTIVE"
        self.events.append("MEDIA_OPEN_INTERCEPTED")
        return record

    def intercept_media_stop(
        self,
        writer: InterceptedWriter,
        *,
        media_channel_id: int | None = None,
    ) -> InterceptedWrite:
        if self.media_phase == "STOPPED":
            raise TransactionRejected("second media STOP already stopped")
        if self.media_phase != "ACTIVE" or self.media_channel_id is None:
            raise TransactionRejected("media STOP before OPEN rejected")
        if media_channel_id is not None and media_channel_id != self.media_channel_id:
            raise TransactionRejected("media STOP channel mismatch rejected")
        mediareq26 = build_mediareq26_stop(self.media_channel_id)
        record = self._intercept_media_packet(writer, "MEDIA_STOP", mediareq26)
        self.media_phase = "STOPPED"
        self.events.append("MEDIA_STOP_INTERCEPTED")
        return record

    def _intercept_media_packet(
        self,
        writer: InterceptedWriter,
        semantic_kind: str,
        mediareq26: bytes,
    ) -> InterceptedWrite:
        sequence = self.next_tx_sequence
        packet = build_call_bound_media_packet(
            local_connection=self.connection_for_serialization(),
            sequence=sequence,
            acknowledgement=self.next_tx_acknowledgement,
            mediareq26=mediareq26,
            source_raw=self.source_logical_address,
            destination_raw=self.destination_logical_address,
        )
        record = writer.intercept(
            semantic_kind=semantic_kind,
            outer_ctpp_handle=self.outer_ctpp_handle,
            serialized_ctp_packet=packet,
            call_connection_id=self.connection_for_serialization(),
            sequence=sequence,
            acknowledgement=self.next_tx_acknowledgement,
            inner_opcode=OP_MEDIA_REQUEST,
            inner_length=len(mediareq26),
        )
        self.next_tx_sequence = (self.next_tx_sequence + 1) % 256
        self.write_count += 1
        return record


def _require_connection_id(value: bytes) -> bytes:
    if not isinstance(value, bytes) or len(value) != 2:
        raise TypeError("CTP connection id must be exactly two bytes")
    return value


def _require_logical_address(value: bytes) -> bytes:
    if not isinstance(value, bytes) or len(value) != LOGADDR_LEN:
        raise ValueError("logical address must be exactly ten bytes")
    return value


def toggle_direction_bit(peer_connection_id: bytes) -> bytes:
    word = struct.unpack(">H", _require_connection_id(peer_connection_id))[0]
    return struct.pack(">H", word ^ 0x8000)


def derive_native_local_connection_id(peer_connection_id: bytes) -> bytes:
    local = toggle_direction_bit(peer_connection_id)
    word = struct.unpack(">H", local)[0]
    if word == 0 or (word & 0x7FFF) == 0x7FFF:
        raise TransactionRejected("derived native local CTP connection id is invalid/reserved")
    return local


def capture_inbound_invite(
    *,
    outer_ctpp_handle: OuterCtppHandle,
    serialized_ctp_packet: bytes,
) -> InboundPeerFacts:
    envelope = parse_ctp_envelope(serialized_ctp_packet)
    if envelope.version != 0x18:
        raise TransactionRejected("unsupported CTP version")
    if not envelope.is_syn or envelope.flags != FLAG_SYN:
        raise TransactionRejected("initial inbound call must be CTP SYN")
    if not is_inbound_invite(envelope):
        raise TransactionRejected("initial inbound call must be INVITE")
    if len(envelope.inner_body) != 40:
        raise TransactionRejected("INVITE body must be exactly 40 bytes")
    if envelope.opcode != OP_INVITE:
        raise TransactionRejected("INVITE opcode required")
    return InboundPeerFacts(
        outer_ctpp_handle=outer_ctpp_handle,
        peer_connection_id=envelope.connection,
        peer_sequence=envelope.sequence,
        peer_acknowledgement=envelope.acknowledgement,
        source_logical_address=envelope.source_raw,
        destination_logical_address=envelope.destination_raw,
        logical_call_id=envelope.inner_body[24:28],
    )


def create_call_transaction(
    *,
    outer_ctpp_handle: OuterCtppHandle,
    serialized_ctp_packet: bytes,
    next_tx_sequence_seed: int | None = None,
) -> CallTransaction:
    facts = capture_inbound_invite(
        outer_ctpp_handle=outer_ctpp_handle,
        serialized_ctp_packet=serialized_ctp_packet,
    )
    transaction = CallTransaction.from_peer_facts(
        facts,
        inbound_serialized_ctp_packet=serialized_ctp_packet,
        next_tx_sequence_seed=next_tx_sequence_seed,
    )
    transaction.events.insert(0, "INVITE_CAPTURED")
    return transaction


def build_mediareq26_open(media_channel_id: int) -> bytes:
    _require_media_channel_id(media_channel_id)
    out = bytearray(26)
    struct.pack_into(">H", out, 0, OP_MEDIA_REQUEST)
    out[2] = 0x14
    out[3] = 0x32
    struct.pack_into("<I", out, 4, 0)
    struct.pack_into("<H", out, 8, media_channel_id)
    struct.pack_into("<H", out, 10, 0xFFFF)
    struct.pack_into("<I", out, 12, 0)
    struct.pack_into("<H", out, 16, 800)
    struct.pack_into("<H", out, 18, 480)
    struct.pack_into("<H", out, 20, 320)
    struct.pack_into("<H", out, 22, 240)
    out[24] = 16
    out[25] = 0
    return bytes(out)


def build_mediareq26_stop(media_channel_id: int) -> bytes:
    _require_media_channel_id(media_channel_id)
    out = bytearray(26)
    struct.pack_into(">H", out, 0, OP_MEDIA_REQUEST)
    out[2] = 0x94
    out[3] = 0x00
    struct.pack_into("<I", out, 4, 0)
    struct.pack_into("<H", out, 8, media_channel_id)
    return bytes(out)


def _require_media_channel_id(media_channel_id: int) -> None:
    if not isinstance(media_channel_id, int) or not 1 <= media_channel_id <= 0xFFFF:
        raise TransactionRejected("media channel id must be non-zero LE16")


def run_offline_happy_path() -> tuple[CallTransaction, InterceptedWriter]:
    invite = bytearray(40)
    struct.pack_into(">H", invite, 0, OP_INVITE)
    invite[2:12] = b"00000643\x00\x00"
    invite[12:22] = b"000401177\x00"
    invite[24:28] = b"CALL"
    packet = build_ctp_envelope(
        flags=FLAG_SYN,
        connection=b"\x12\x34",
        sequence=0x56,
        acknowledgement=0x78,
        inner_body=bytes(invite),
        source_raw=b"00000643\x00\x00",
        destination_raw=b"000401177\x00",
    )
    writer = InterceptedWriter()
    transaction = create_call_transaction(
        outer_ctpp_handle=OuterCtppHandle(7),
        serialized_ctp_packet=packet,
        next_tx_sequence_seed=0x21,
    )
    transaction.intercept_transport_ack(writer)
    transaction.intercept_capability_stage()
    transaction.intercept_alerting_stage()
    transaction.reach_call_signaling_order_barrier()
    transaction.allocate_media_channel(lambda: 0x3456)
    transaction.intercept_media_open(writer)
    transaction.intercept_media_stop(writer)
    return transaction, writer


def verify_happy_path(transaction: CallTransaction, writer: InterceptedWriter) -> dict[str, bool | int]:
    inbound_packet = parse_ctp_envelope(transaction.inbound_serialized_ctp_packet)
    ack_write = _single_write(writer, "TRANSPORT_ACK")
    open_write = _single_write(writer, "MEDIA_OPEN")
    stop_write = _single_write(writer, "MEDIA_STOP")
    ack_packet = parse_ctp_envelope(ack_write.serialized_ctp_packet)
    open_packet = parse_ctp_envelope(open_write.serialized_ctp_packet)
    stop_packet = parse_ctp_envelope(stop_write.serialized_ctp_packet)
    open_channel_id = _inner_media_channel_id(open_packet.inner_body)
    stop_channel_id = _inner_media_channel_id(stop_packet.inner_body)
    outer_connection = _outer_handle_as_connection(transaction.outer_ctpp_handle)
    source_destination_reversed = (
        open_packet.source_raw == transaction.source_logical_address
        and open_packet.destination_raw == transaction.destination_logical_address
        and stop_packet.source_raw == transaction.source_logical_address
        and stop_packet.destination_raw == transaction.destination_logical_address
    )
    stop_sequence_follows_open = stop_packet.sequence == ((open_packet.sequence + 1) % 256)
    all_connection_fields = [
        parse_ctp_envelope(write.serialized_ctp_packet).connection for write in writer.writes
    ]
    event_positions = _event_positions(transaction.events)
    call_transaction_capture = (
        inbound_packet.flags == FLAG_SYN
        and inbound_packet.opcode == OP_INVITE
        and len(inbound_packet.inner_body) == 40
        and inbound_packet.connection == transaction.peer_connection_id
        and inbound_packet.sequence == transaction.peer_sequence
        and inbound_packet.acknowledgement == transaction.peer_acknowledgement
        and inbound_packet.destination_raw == transaction.source_logical_address
        and inbound_packet.source_raw == transaction.destination_logical_address
        and inbound_packet.inner_body[24:28] == transaction.logical_call_id
    )
    outer_ctpp_handle_separation = (
        outer_connection is None
        or (
            transaction.peer_connection_id != outer_connection
            and transaction.candidate_local_connection_id != outer_connection
            and all(connection != outer_connection for connection in all_connection_fields)
        )
    )
    ack_model_intercepted = (
        writer.intercepted_ack_writes == 1
        and len(ack_packet.inner_body) == 0
        and ack_write.inner_length == 0
        and ack_packet.sequence == open_packet.sequence
        and ack_packet.acknowledgement == transaction.next_tx_acknowledgement
    )
    call_signaling_order_barrier = (
        event_positions.get("CAPABILITY_STAGE_INTERCEPTED", 999) <
        event_positions.get("ALERTING_STAGE_INTERCEPTED", -1) <
        event_positions.get("CALL_SIGNALING_ORDER_BARRIER_REACHED", -1) <
        event_positions.get("MEDIA_CHANNEL_ALLOCATED", -1) <
        event_positions.get("MEDIA_OPEN_INTERCEPTED", -1)
        and all(
            write.semantic_kind not in {"CAPABILITY_STAGE", "ALERTING_STAGE"}
            for write in writer.writes
        )
    )
    media_channel_single_allocation = (
        isinstance(transaction.media_channel_id, int)
        and 1 <= transaction.media_channel_id <= 0xFFFF
        and transaction.events.count("MEDIA_CHANNEL_ALLOCATED") == 1
        and {open_channel_id, stop_channel_id} == {transaction.media_channel_id}
    )
    return {
        "CALL_TRANSACTION_CAPTURE": call_transaction_capture,
        "OUTER_CTPP_HANDLE_SEPARATION": outer_ctpp_handle_separation,
        "ACK_MODEL_INTERCEPTED": ack_model_intercepted,
        "CALL_SIGNALING_ORDER_BARRIER": call_signaling_order_barrier,
        "MEDIA_CHANNEL_SINGLE_ALLOCATION": media_channel_single_allocation,
        "OPEN_INNER_MEDIAREQ26_LENGTH": len(open_packet.inner_body),
        "OPEN_FULL_CTP_PACKET_LENGTH": len(open_write.serialized_ctp_packet),
        "OPEN_USES_CALL_TRANSACTION_CONNECTION": (
            open_packet.connection == transaction.candidate_local_connection_id
        ),
        "OPEN_USES_OUTER_CTPP_HANDLE_AS_CONNECTION": (
            outer_connection is not None and open_packet.connection == outer_connection
        ),
        "OPEN_MEDIA_CHANNEL_MATCH": open_channel_id == transaction.media_channel_id,
        "STOP_INNER_MEDIAREQ26_LENGTH": len(stop_packet.inner_body),
        "STOP_FULL_CTP_PACKET_LENGTH": len(stop_write.serialized_ctp_packet),
        "STOP_REUSES_OPEN_MEDIA_CHANNEL": (
            open_channel_id == stop_channel_id == transaction.media_channel_id
        ),
        "STOP_USES_CALL_TRANSACTION_CONNECTION": (
            stop_packet.connection == transaction.candidate_local_connection_id
        ),
        "STOP_AFTER_OPEN_ONLY": (
            _write_index(writer, "MEDIA_OPEN") < _write_index(writer, "MEDIA_STOP")
            and "MEDIA_OPEN_INTERCEPTED" in transaction.events
            and "MEDIA_STOP_INTERCEPTED" in transaction.events
        ),
        "OUTBOUND_LOGICAL_ADDRESSES_REVERSED": source_destination_reversed,
        "STOP_SEQUENCE_FOLLOWS_OPEN": stop_sequence_follows_open,
    }


def _single_write(writer: InterceptedWriter, semantic_kind: str) -> InterceptedWrite:
    matches = [write for write in writer.writes if write.semantic_kind == semantic_kind]
    if len(matches) != 1:
        raise TransactionRejected(f"expected exactly one {semantic_kind} write")
    return matches[0]


def _write_index(writer: InterceptedWriter, semantic_kind: str) -> int:
    for index, write in enumerate(writer.writes):
        if write.semantic_kind == semantic_kind:
            return index
    raise TransactionRejected(f"missing {semantic_kind} write")


def _event_positions(events: list[str]) -> dict[str, int]:
    return {event: index for index, event in enumerate(events)}


def _inner_media_channel_id(inner_body: bytes) -> int | None:
    if len(inner_body) < 10:
        return None
    return struct.unpack_from("<H", inner_body, 8)[0]


def _outer_handle_as_connection(outer_ctpp_handle: OuterCtppHandle) -> bytes | None:
    if not 0 <= outer_ctpp_handle.value <= 0xFFFF:
        return None
    return struct.pack(">H", outer_ctpp_handle.value)


def _bool_marker(value: bool | int) -> str:
    if not isinstance(value, bool):
        raise TypeError("boolean marker requires a bool")
    return "true" if value else "false"


def _pass_marker(value: bool | int) -> str:
    if not isinstance(value, bool):
        raise TypeError("PASS marker requires a bool")
    return "PASS" if value else "FAIL"


def report() -> str:
    transaction, writer = run_offline_happy_path()
    evidence = verify_happy_path(transaction, writer)
    markers = (
        "=== COMELIT P116 R30B OFFLINE CALL TRANSACTION ===",
        f"CALL_TRANSACTION_CAPTURE={_pass_marker(evidence['CALL_TRANSACTION_CAPTURE'])}",
        f"OUTER_CTPP_HANDLE_SEPARATION={_pass_marker(evidence['OUTER_CTPP_HANDLE_SEPARATION'])}",
        f"ACK_MODEL_INTERCEPTED={_pass_marker(evidence['ACK_MODEL_INTERCEPTED'])}",
        f"CALL_SIGNALING_ORDER_BARRIER={_pass_marker(evidence['CALL_SIGNALING_ORDER_BARRIER'])}",
        f"MEDIA_CHANNEL_SINGLE_ALLOCATION={_pass_marker(evidence['MEDIA_CHANNEL_SINGLE_ALLOCATION'])}",
        f"FULL_CTP_MEDIA_OPEN_SERIALIZATION={_pass_marker(evidence['OPEN_USES_CALL_TRANSACTION_CONNECTION'] and evidence['OPEN_MEDIA_CHANNEL_MATCH'] and evidence['OPEN_FULL_CTP_PACKET_LENGTH'] == 60)}",
        f"FULL_CTP_MEDIA_STOP_SERIALIZATION={_pass_marker(evidence['STOP_USES_CALL_TRANSACTION_CONNECTION'] and evidence['STOP_REUSES_OPEN_MEDIA_CHANNEL'] and evidence['STOP_FULL_CTP_PACKET_LENGTH'] == 60)}",
        f"OPEN_STOP_MEDIA_CHANNEL_IDENTITY={_pass_marker(evidence['STOP_REUSES_OPEN_MEDIA_CHANNEL'])}",
        f"PER_CALL_SEQUENCE_STATE={_pass_marker(evidence['STOP_SEQUENCE_FOLLOWS_OPEN'])}",
        f"INTERCEPTED_ACK_WRITES={writer.intercepted_ack_writes}",
        f"INTERCEPTED_MEDIA_OPEN_WRITES={writer.intercepted_media_open_writes}",
        f"INTERCEPTED_MEDIA_STOP_WRITES={writer.intercepted_media_stop_writes}",
        f"NETWORK_WRITES={writer.network_writes}",
        f"DOOR_ACTIONS={writer.door_actions}",
        f"GATE_ACTIONS={writer.gate_actions}",
        f"SELF_ACTIVATION_ACTIONS={writer.self_activation_actions}",
        f"REFRESH_OR_REPEAT_ACTIONS={writer.refresh_or_repeat_actions}",
        "PRODUCTION_FILES_CHANGED=0",
        f"LOCAL_CONNECTION_DIRECTION_RULE={LOCAL_CONNECTION_DIRECTION_RULE}",
        f"OFFICIAL_NATIVE_LOCAL_ID_EQUIVALENCE={OFFICIAL_NATIVE_LOCAL_ID_EQUIVALENCE}",
        "LIVE_CALL_BOUND_MEDIA=NOT_PROVEN",
        "LIVE_AUTHORIZED=false",
        f"MEDIA_CHANNEL_ALLOCATOR_STATUS={MEDIA_CHANNEL_ALLOCATOR_STATUS}",
        f"OPEN_INNER_MEDIAREQ26_LENGTH={evidence['OPEN_INNER_MEDIAREQ26_LENGTH']}",
        f"OPEN_FULL_CTP_PACKET_LENGTH={evidence['OPEN_FULL_CTP_PACKET_LENGTH']}",
        f"OPEN_USES_CALL_TRANSACTION_CONNECTION={_bool_marker(evidence['OPEN_USES_CALL_TRANSACTION_CONNECTION'])}",
        f"OPEN_USES_OUTER_CTPP_HANDLE_AS_CONNECTION={_bool_marker(evidence['OPEN_USES_OUTER_CTPP_HANDLE_AS_CONNECTION'])}",
        f"OPEN_MEDIA_CHANNEL_MATCH={_bool_marker(evidence['OPEN_MEDIA_CHANNEL_MATCH'])}",
        f"STOP_INNER_MEDIAREQ26_LENGTH={evidence['STOP_INNER_MEDIAREQ26_LENGTH']}",
        f"STOP_FULL_CTP_PACKET_LENGTH={evidence['STOP_FULL_CTP_PACKET_LENGTH']}",
        f"STOP_REUSES_OPEN_MEDIA_CHANNEL={_bool_marker(evidence['STOP_REUSES_OPEN_MEDIA_CHANNEL'])}",
        f"STOP_USES_CALL_TRANSACTION_CONNECTION={_bool_marker(evidence['STOP_USES_CALL_TRANSACTION_CONNECTION'])}",
        f"STOP_AFTER_OPEN_ONLY={_bool_marker(evidence['STOP_AFTER_OPEN_ONLY'])}",
        f"OUTBOUND_LOGICAL_ADDRESSES_REVERSED={_bool_marker(evidence['OUTBOUND_LOGICAL_ADDRESSES_REVERSED'])}",
        f"STOP_SEQUENCE_FOLLOWS_OPEN={_bool_marker(evidence['STOP_SEQUENCE_FOLLOWS_OPEN'])}",
        f"EVENT_ORDER={'->'.join(transaction.events)}",
        "=== END COMELIT P116 R30B OFFLINE CALL TRANSACTION ===",
    )
    return "\n".join(markers)


if __name__ == "__main__":
    print(report())
