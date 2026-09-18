"""P116/R34 offline helper-side model for attached inbound media.

This is a bounded research model. It never opens transports and only writes
serialized CTP packets into the R30B in-memory intercepted writer.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import struct
from typing import Any

from entrance_p116_r30_call_ctp_envelope_model import (
    OP_MEDIA_REQUEST,
    build_call_bound_media_packet,
    parse_ctp_envelope,
)
from entrance_p116_r30b_call_transaction_model import (
    CallTransaction,
    InterceptedWrite,
    InterceptedWriter,
    OuterCtppHandle,
    TransactionRejected,
    build_mediareq26_open as r30b_build_mediareq26_open,
    derive_native_local_connection_id,
)
from entrance_p116_r33_offline_scalar_trace_model import create_trace_at_call_barrier


MEDIAREQ26_BODY_LENGTH = 26
MEDIAREQ26_UNKNOWN_FIELDS = 0
MEDIAREQ26_INNER_OPCODE = OP_MEDIA_REQUEST
MEDIAREQ26_OPEN_ACTION = 0x14
MEDIAREQ26_STOP_ACTION = 0x94
MEDIAREQ26_FORM_TUNNEL = "TUNNEL"
MEDIAREQ26_FORM_ADDRESS = "ADDRESS"

STATE_CALL_TRANSACTION_CAPTURED = "CALL_TRANSACTION_CAPTURED"
STATE_MEDIA_CHANNEL_UNALLOCATED = "MEDIA_CHANNEL_UNALLOCATED"
STATE_CHANNEL_ALLOCATED_OPEN_REQUESTED = "CHANNEL_ALLOCATED_OPEN_REQUESTED"
STATE_MEDIA_OPEN_EMITTED = "MEDIA_OPEN_EMITTED"
STATE_MEDIA_ACTIVE_RTP_ELIGIBLE = "MEDIA_ACTIVE_RTP_ELIGIBLE"
STATE_MEDIA_STOP_EMITTED = "MEDIA_STOP_EMITTED"
STATE_MEDIA_CHANNEL_DISPOSED = "MEDIA_CHANNEL_DISPOSED"
STATE_TERMINAL = "TERMINAL"
STATE_ERROR = "ERROR"


class R34AttachedMediaRejected(ValueError):
    """Raised when the R34 offline model must fail closed."""


@dataclass(frozen=True, slots=True)
class SecondOpenForbiddenState:
    code: str
    description: str


SECOND_OPEN_FORBIDDEN_STATES: tuple[SecondOpenForbiddenState, ...] = (
    SecondOpenForbiddenState(
        "NO_CALL_TRANSACTION_CAPTURE_OR_SIGNALING_BARRIER",
        "no call-transaction capture / no call signaling barrier",
    ),
    SecondOpenForbiddenState(
        "NO_LOCAL_MEDIA_RX_CHANNEL_ALLOCATED",
        "no local media RX channel / id allocated",
    ),
    SecondOpenForbiddenState("OPEN_ALREADY_PENDING", "OPEN already pending"),
    SecondOpenForbiddenState(
        "OPEN_ALREADY_EMITTED_ACTIVE_OR_CONFIRMED",
        "OPEN already emitted/active or confirmed",
    ),
    SecondOpenForbiddenState("STOP_ALREADY_SENT", "STOP already sent"),
    SecondOpenForbiddenState("MEDIA_CHANNEL_ALREADY_DISPOSED", "media channel already disposed"),
    SecondOpenForbiddenState(
        "REGISTRATION_HANDLE_OR_FOREIGN_CALL_TRANSACTION",
        "OPEN aimed at the registration handle or a foreign call transaction",
    ),
)


@dataclass(frozen=True, slots=True)
class MediaRequest26Sources:
    form: str
    video_request: bool
    media_channel_id: int
    max_rtp_payload: int
    channel_profile_word: int
    profile_halfwords: tuple[int, int, int]
    profile_halfword_3: int
    profile_byte_4: int
    profile_selector: bool = False
    address_ipv4: bytes = b"\x00\x00\x00\x00"

    def __post_init__(self) -> None:
        _require_form(self.form)
        _require_u16(self.media_channel_id, "media_channel_id")
        _require_u16(self.max_rtp_payload, "max_rtp_payload")
        _require_u32(self.channel_profile_word, "channel_profile_word")
        if len(self.profile_halfwords) != 3:
            raise R34AttachedMediaRejected("profile_halfwords must carry exactly three values")
        for index, value in enumerate(self.profile_halfwords):
            _require_u16(value, f"profile_halfwords[{index}]")
        _require_u16(self.profile_halfword_3, "profile_halfword_3")
        _require_u8(self.profile_byte_4, "profile_byte_4")
        if not isinstance(self.address_ipv4, bytes) or len(self.address_ipv4) != 4:
            raise R34AttachedMediaRejected("address_ipv4 must be exactly four bytes")
        if self.form == MEDIAREQ26_FORM_TUNNEL and self.address_ipv4 != b"\x00\x00\x00\x00":
            raise R34AttachedMediaRejected("TUNNEL form requires a zero address field")


@dataclass(frozen=True, slots=True)
class MediaRxChannel:
    token: str
    channel_id: int


@dataclass(slots=True)
class R34AttachedMediaSession:
    writer: InterceptedWriter
    transaction: CallTransaction | None
    call_ctp_id: bytes | None
    outer_ctpp_handle: OuterCtppHandle
    call_ctp_valid: bool
    local_channel: MediaRxChannel | None = None
    open_pending: bool = False
    open_confirmed: bool = False
    video_rx_active: bool = False
    rtp_eligible: bool = False
    stop_sent: bool = False
    channel_disposed: bool = False
    disposed_channel_ids: list[int] = field(default_factory=list)
    disposed_channel_tokens: list[str] = field(default_factory=list)
    listener_alive: bool = True
    registration_alive: bool = True
    pseudotcp_alive: bool = True
    call_transaction_alive: bool = True
    current_state: str = STATE_CALL_TRANSACTION_CAPTURED
    events: list[str] = field(
        default_factory=lambda: [STATE_CALL_TRANSACTION_CAPTURED, STATE_MEDIA_CHANNEL_UNALLOCATED]
    )

    @property
    def network_tx(self) -> int:
        return 0

    @property
    def new_ice(self) -> int:
        return 0

    @property
    def new_cloud(self) -> int:
        return 0

    @property
    def new_pseudotcp(self) -> int:
        return 0

    @property
    def new_registration(self) -> int:
        return 0

    @property
    def door_actions(self) -> int:
        return 0

    @property
    def gate_actions(self) -> int:
        return 0

    @property
    def open_count(self) -> int:
        return self.writer.intercepted_media_open_writes

    @property
    def stop_count(self) -> int:
        return self.writer.intercepted_media_stop_writes

    def allocate_media_rx_channel(self, channel_id: int, *, token: str = "r34_media_rx_token") -> MediaRxChannel:
        self._require_call_ready()
        if self.local_channel is not None:
            raise R34AttachedMediaRejected("media RX channel already allocated")
        if self.channel_disposed:
            raise R34AttachedMediaRejected("media RX channel already disposed")
        _require_u16(channel_id, "channel_id")
        if not isinstance(token, str) or not token:
            raise R34AttachedMediaRejected("channel token must be a non-empty string")
        self._require_transaction().allocate_media_channel(lambda: channel_id)
        self.local_channel = MediaRxChannel(token=token, channel_id=channel_id)
        self.current_state = STATE_CHANNEL_ALLOCATED_OPEN_REQUESTED
        self.events.append("MEDIA_RX_CHANNEL_ALLOCATED")
        self.events.append(STATE_CHANNEL_ALLOCATED_OPEN_REQUESTED)
        return self.local_channel

    def send_open(
        self,
        sources: MediaRequest26Sources,
        *,
        transaction: CallTransaction | None = None,
        use_registration_handle: bool = False,
    ) -> InterceptedWrite:
        self._reject_open_if_forbidden(
            sources=sources,
            transaction=transaction,
            use_registration_handle=use_registration_handle,
        )
        body = serialize_mediareq26_open(sources)
        record = self._intercept_media_packet("MEDIA_OPEN", body)
        self.open_pending = True
        self.video_rx_active = True
        self.rtp_eligible = True
        self.current_state = STATE_MEDIA_OPEN_EMITTED
        self.events.append("CALL_BOUND_MEDIAREQ26_OPEN")
        self.events.append(STATE_MEDIA_OPEN_EMITTED)
        return record

    def observe_channel_open_response(
        self,
        *,
        channel_id: int,
        token: str | None = None,
        ok: bool = True,
    ) -> None:
        channel = self._require_live_channel(channel_id=channel_id, token=token)
        del channel
        if not self.open_pending and not self.video_rx_active:
            raise R34AttachedMediaRejected("channel open response without matching OPEN rejected")
        self.open_pending = False
        self.open_confirmed = bool(ok)
        self.events.append("CHANNEL_OPEN_RESPONSE_PASS" if ok else "CHANNEL_OPEN_RESPONSE_FAIL")

    def enable_rtp(self, *, channel_id: int, token: str | None = None) -> None:
        self._require_live_channel(channel_id=channel_id, token=token)
        if not self.video_rx_active or not self.rtp_eligible or self.open_count != 1:
            raise R34AttachedMediaRejected("RTP before one call-bound OPEN rejected")
        self.current_state = STATE_MEDIA_ACTIVE_RTP_ELIGIBLE
        self.events.append(STATE_MEDIA_ACTIVE_RTP_ELIGIBLE)

    def send_stop(self, *, form: str, channel_id: int, token: str | None = None) -> InterceptedWrite:
        _require_form(form)
        self._require_live_channel(channel_id=channel_id, token=token)
        if self.open_count != 1 or not self.video_rx_active:
            raise R34AttachedMediaRejected("STOP before OPEN rejected")
        if self.stop_count or self.stop_sent:
            raise R34AttachedMediaRejected("second STOP rejected")
        body = serialize_mediareq26_stop(form=form, media_channel_id=channel_id)
        record = self._intercept_media_packet("MEDIA_STOP", body)
        self.stop_sent = True
        self.current_state = STATE_MEDIA_STOP_EMITTED
        self.events.append("CALL_BOUND_MEDIAREQ26_STOP")
        self.events.append(STATE_MEDIA_STOP_EMITTED)
        return record

    def dispose_media_rx_channel(self, *, channel_id: int, token: str | None = None) -> None:
        channel = self._require_live_channel(channel_id=channel_id, token=token)
        if self.stop_count != 1 or not self.stop_sent:
            raise R34AttachedMediaRejected("dispose before STOP rejected")
        self.disposed_channel_ids.append(channel.channel_id)
        self.disposed_channel_tokens.append(channel.token)
        self.local_channel = None
        self.video_rx_active = False
        self.rtp_eligible = False
        self.open_pending = False
        self.channel_disposed = True
        self.current_state = STATE_MEDIA_CHANNEL_DISPOSED
        self.events.append("MEDIA_RX_CHANNEL_DISPOSED")
        self.events.append(STATE_MEDIA_CHANNEL_DISPOSED)

    def preserve_listener_registration_pseudotcp_call(self) -> None:
        if self.local_channel is not None or self.video_rx_active:
            raise R34AttachedMediaRejected("preservation is checked after media disposal")
        if not (
            self.listener_alive
            and self.registration_alive
            and self.pseudotcp_alive
            and self.call_transaction_alive
        ):
            raise R34AttachedMediaRejected("persistent listener/registration/PseudoTCP/call lost")
        self.events.append("LISTENER_REGISTRATION_PSEUDOTCP_CALL_TRANSACTION_PRESERVED")

    def end_call_transaction(self) -> None:
        self.call_ctp_valid = False
        self.call_transaction_alive = False
        self.current_state = STATE_TERMINAL
        self.events.append(STATE_TERMINAL)

    def _reject_open_if_forbidden(
        self,
        *,
        sources: MediaRequest26Sources,
        transaction: CallTransaction | None,
        use_registration_handle: bool,
    ) -> None:
        if use_registration_handle:
            raise R34AttachedMediaRejected("OPEN on registration handle rejected")
        if transaction is not None and transaction is not self.transaction:
            raise R34AttachedMediaRejected("OPEN bound to foreign call transaction rejected")
        self._require_call_ready()
        channel = self._require_live_channel(channel_id=sources.media_channel_id, token=None)
        if channel.channel_id != sources.media_channel_id:
            raise R34AttachedMediaRejected("OPEN channel mismatch rejected")
        if self.open_pending:
            raise R34AttachedMediaRejected("second OPEN rejected: OPEN already pending")
        if self.open_count or self.video_rx_active or self.open_confirmed:
            raise R34AttachedMediaRejected("second OPEN rejected: OPEN already emitted/active or confirmed")
        if self.stop_count or self.stop_sent:
            raise R34AttachedMediaRejected("second OPEN rejected: STOP already sent")
        if self.channel_disposed:
            raise R34AttachedMediaRejected("second OPEN rejected: media channel already disposed")

    def _require_call_ready(self) -> None:
        if self.transaction is None or self.call_ctp_id is None or not self.call_ctp_valid:
            raise R34AttachedMediaRejected("call transaction capture missing or invalid")
        if self.transaction.call_phase != "SIGNALING_BARRIER_REACHED":
            raise R34AttachedMediaRejected("call signaling barrier missing")
        if self.call_ctp_id != self.transaction.connection_for_serialization():
            raise R34AttachedMediaRejected("bounded call CTP id no longer matches transaction")
        outer_connection = _outer_handle_as_connection(self.outer_ctpp_handle)
        if outer_connection is not None and self.call_ctp_id == outer_connection:
            raise R34AttachedMediaRejected("call CTP id must not be the registration handle")

    def _require_live_channel(self, *, channel_id: int, token: str | None) -> MediaRxChannel:
        _require_u16(channel_id, "channel_id")
        if self.channel_disposed:
            raise R34AttachedMediaRejected("media channel token/id already disposed")
        if self.local_channel is None:
            raise R34AttachedMediaRejected("media RX channel not allocated")
        if self.local_channel.channel_id != channel_id:
            raise R34AttachedMediaRejected("wrong or stale media channel id rejected")
        if token is not None and self.local_channel.token != token:
            raise R34AttachedMediaRejected("wrong or stale media channel token rejected")
        return self.local_channel

    def _require_transaction(self) -> CallTransaction:
        if self.transaction is None:
            raise R34AttachedMediaRejected("call transaction is missing")
        return self.transaction

    def _intercept_media_packet(self, semantic_kind: str, mediareq26: bytes) -> InterceptedWrite:
        transaction = self._require_transaction()
        sequence = transaction.next_tx_sequence
        acknowledgement = transaction.next_tx_acknowledgement
        packet = build_call_bound_media_packet(
            local_connection=transaction.connection_for_serialization(),
            sequence=sequence,
            acknowledgement=acknowledgement,
            mediareq26=mediareq26,
            source_raw=transaction.source_logical_address,
            destination_raw=transaction.destination_logical_address,
        )
        record = self.writer.intercept(
            semantic_kind=semantic_kind,
            outer_ctpp_handle=transaction.outer_ctpp_handle,
            serialized_ctp_packet=packet,
            call_connection_id=transaction.connection_for_serialization(),
            sequence=sequence,
            acknowledgement=acknowledgement,
            inner_opcode=OP_MEDIA_REQUEST,
            inner_length=len(mediareq26),
        )
        transaction.next_tx_sequence = (transaction.next_tx_sequence + 1) % 256
        transaction.write_count += 1
        transaction.events.append(f"{semantic_kind}_INTERCEPTED")
        return record


def open_flags(*, form: str, video_request: bool, profile_selector: bool = False) -> int:
    _require_form(form)
    if form == MEDIAREQ26_FORM_TUNNEL:
        return (0x32 & ~0x08) | (0x08 if video_request else 0x00)
    return 0x30 | (0x04 if profile_selector else 0x00) | (0x08 if video_request else 0x00)


def stop_flags(*, form: str) -> int:
    _require_form(form)
    return 0x02 if form == MEDIAREQ26_FORM_TUNNEL else 0x00


def serialize_mediareq26_open(sources: MediaRequest26Sources) -> bytes:
    out = bytearray(MEDIAREQ26_BODY_LENGTH)
    struct.pack_into(">H", out, 0, MEDIAREQ26_INNER_OPCODE)
    out[2] = MEDIAREQ26_OPEN_ACTION
    out[3] = open_flags(
        form=sources.form,
        video_request=sources.video_request,
        profile_selector=sources.profile_selector,
    )
    out[4:8] = b"\x00\x00\x00\x00" if sources.form == MEDIAREQ26_FORM_TUNNEL else sources.address_ipv4
    struct.pack_into("<H", out, 8, sources.media_channel_id)
    struct.pack_into("<H", out, 10, sources.max_rtp_payload)
    struct.pack_into("<I", out, 12, sources.channel_profile_word)
    struct.pack_into("<H", out, 16, sources.profile_halfwords[0])
    struct.pack_into("<H", out, 18, sources.profile_halfwords[1])
    struct.pack_into("<H", out, 20, sources.profile_halfwords[2])
    struct.pack_into("<H", out, 22, sources.profile_halfword_3)
    out[24] = sources.profile_byte_4
    out[25] = 0
    result = bytes(out)
    if len(result) != MEDIAREQ26_BODY_LENGTH:
        raise AssertionError("mediareq26 OPEN serializer produced wrong length")
    return result


def serialize_mediareq26_stop(*, form: str, media_channel_id: int) -> bytes:
    _require_form(form)
    _require_u16(media_channel_id, "media_channel_id")
    out = bytearray(MEDIAREQ26_BODY_LENGTH)
    struct.pack_into(">H", out, 0, MEDIAREQ26_INNER_OPCODE)
    out[2] = MEDIAREQ26_STOP_ACTION
    out[3] = stop_flags(form=form)
    struct.pack_into("<H", out, 8, media_channel_id)
    result = bytes(out)
    if len(result) != MEDIAREQ26_BODY_LENGTH:
        raise AssertionError("mediareq26 STOP serializer produced wrong length")
    return result


def parse_mediareq26(body: bytes) -> dict[str, Any]:
    if not isinstance(body, bytes) or len(body) != MEDIAREQ26_BODY_LENGTH:
        raise R34AttachedMediaRejected("mediareq26 body must be exactly 26 bytes")
    return {
        "inner_opcode": struct.unpack_from(">H", body, 0)[0],
        "action": body[2],
        "flags": body[3],
        "address_ipv4": body[4:8],
        "media_channel_id": struct.unpack_from("<H", body, 8)[0],
        "max_rtp_payload": struct.unpack_from("<H", body, 10)[0],
        "channel_profile_word": struct.unpack_from("<I", body, 12)[0],
        "profile_halfword_0": struct.unpack_from("<H", body, 16)[0],
        "profile_halfword_1": struct.unpack_from("<H", body, 18)[0],
        "profile_halfword_2": struct.unpack_from("<H", body, 20)[0],
        "profile_halfword_3": struct.unpack_from("<H", body, 22)[0],
        "profile_byte_4": body[24],
        "trailing_reserved": body[25],
        "unknown_fields": MEDIAREQ26_UNKNOWN_FIELDS,
        "body_length": len(body),
    }


def serialize_call_bound_media_open(
    transaction: CallTransaction,
    sources: MediaRequest26Sources,
) -> bytes:
    return build_call_bound_media_packet(
        local_connection=transaction.connection_for_serialization(),
        sequence=transaction.local_tx_sequence,
        acknowledgement=transaction.local_acknowledgement,
        mediareq26=serialize_mediareq26_open(sources),
        source_raw=transaction.source_logical_address,
        destination_raw=transaction.destination_logical_address,
    )


def serialize_call_bound_media_stop(
    transaction: CallTransaction,
    *,
    form: str,
    media_channel_id: int,
) -> bytes:
    return build_call_bound_media_packet(
        local_connection=transaction.connection_for_serialization(),
        sequence=transaction.local_tx_sequence,
        acknowledgement=transaction.local_acknowledgement,
        mediareq26=serialize_mediareq26_stop(form=form, media_channel_id=media_channel_id),
        source_raw=transaction.source_logical_address,
        destination_raw=transaction.destination_logical_address,
    )


def capture_call_ctp_id_from_call_init(serialized_ctp_packet: bytes) -> bytes:
    if len(serialized_ctp_packet) < 4:
        raise R34AttachedMediaRejected("CALL_INIT packet too short for CTP connection capture")
    peer_connection = serialized_ctp_packet[2:4]
    return derive_native_local_connection_id(peer_connection)


def create_session_at_call_barrier() -> R34AttachedMediaSession:
    trace = create_trace_at_call_barrier()
    transaction = trace.transaction
    if not isinstance(transaction, CallTransaction):
        raise R34AttachedMediaRejected("R33 bootstrap did not return a CallTransaction")
    captured = capture_call_ctp_id_from_call_init(transaction.inbound_serialized_ctp_packet)
    if captured != transaction.connection_for_serialization():
        raise R34AttachedMediaRejected("captured call CTP id does not match transaction local id")
    return R34AttachedMediaSession(
        writer=trace.writer,
        transaction=transaction,
        call_ctp_id=captured,
        outer_ctpp_handle=transaction.outer_ctpp_handle,
        call_ctp_valid=True,
    )


def default_open_sources(
    *,
    form: str = MEDIAREQ26_FORM_TUNNEL,
    video_request: bool = False,
    profile_selector: bool = False,
    media_channel_id: int = 0x3456,
) -> MediaRequest26Sources:
    return MediaRequest26Sources(
        form=form,
        video_request=video_request,
        profile_selector=profile_selector,
        media_channel_id=media_channel_id,
        max_rtp_payload=0x04D2,
        channel_profile_word=0x00001234,
        profile_halfwords=(0x0320, 0x01E0, 0x0140),
        profile_halfword_3=0x00F0,
        profile_byte_4=0x10,
        address_ipv4=b"\x01\x02\x03\x04" if form == MEDIAREQ26_FORM_ADDRESS else b"\x00\x00\x00\x00",
    )


def run_offline_attached_media_trace() -> R34AttachedMediaSession:
    session = create_session_at_call_barrier()
    sources = default_open_sources()
    channel = session.allocate_media_rx_channel(sources.media_channel_id)
    session.send_open(sources)
    session.enable_rtp(channel_id=channel.channel_id, token=channel.token)
    session.observe_channel_open_response(channel_id=channel.channel_id, token=channel.token, ok=True)
    session.send_stop(form=sources.form, channel_id=channel.channel_id, token=channel.token)
    session.dispose_media_rx_channel(channel_id=channel.channel_id, token=channel.token)
    session.preserve_listener_registration_pseudotcp_call()
    return session


def second_open_forbidden_reasons() -> tuple[SecondOpenForbiddenState, ...]:
    return SECOND_OPEN_FORBIDDEN_STATES


def derive_gates(session: R34AttachedMediaSession) -> dict[str, bool | int | str]:
    open_writes = [write for write in session.writer.writes if write.semantic_kind == "MEDIA_OPEN"]
    stop_writes = [write for write in session.writer.writes if write.semantic_kind == "MEDIA_STOP"]
    open_body = parse_ctp_envelope(open_writes[0].serialized_ctp_packet).inner_body if open_writes else b""
    stop_body = parse_ctp_envelope(stop_writes[0].serialized_ctp_packet).inner_body if stop_writes else b""
    parsed_open = parse_mediareq26(open_body) if len(open_body) == MEDIAREQ26_BODY_LENGTH else {}
    parsed_stop = parse_mediareq26(stop_body) if len(stop_body) == MEDIAREQ26_BODY_LENGTH else {}
    positions = {event: index for index, event in enumerate(session.events)}
    stop_order = (
        positions.get("CALL_BOUND_MEDIAREQ26_STOP", 999)
        < positions.get("MEDIA_RX_CHANNEL_DISPOSED", -1)
        < positions.get("LISTENER_REGISTRATION_PSEUDOTCP_CALL_TRANSACTION_PRESERVED", 1000)
    )
    registered_misuse = False
    outer_connection = _outer_handle_as_connection(session.outer_ctpp_handle)
    if outer_connection is not None:
        registered_misuse = any(
            parse_ctp_envelope(write.serialized_ctp_packet).connection == outer_connection
            for write in open_writes + stop_writes
        )
    stale_channel_gate = (
        session.local_channel is None
        and len(session.disposed_channel_ids) == 1
        and parsed_open.get("media_channel_id") == session.disposed_channel_ids[0]
        and parsed_stop.get("media_channel_id") == session.disposed_channel_ids[0]
    )
    return {
        "CALL_CTP_CAPTURE_IMPLEMENTED": (
            session.call_ctp_id is not None
            and session.transaction is not None
            and session.call_ctp_id == session.transaction.connection_for_serialization()
        ),
        "MEDIAREQ26_SERIALIZER_IMPLEMENTED": (
            parsed_open.get("body_length") == MEDIAREQ26_BODY_LENGTH
            and parsed_stop.get("body_length") == MEDIAREQ26_BODY_LENGTH
            and parsed_open.get("unknown_fields") == MEDIAREQ26_UNKNOWN_FIELDS
            and parsed_stop.get("unknown_fields") == MEDIAREQ26_UNKNOWN_FIELDS
        ),
        "MEDIAREQ26_OPEN_IMPLEMENTED": (
            parsed_open.get("inner_opcode") == MEDIAREQ26_INNER_OPCODE
            and parsed_open.get("action") == MEDIAREQ26_OPEN_ACTION
        ),
        "MEDIAREQ26_STOP_IMPLEMENTED": (
            parsed_stop.get("inner_opcode") == MEDIAREQ26_INNER_OPCODE
            and parsed_stop.get("action") == MEDIAREQ26_STOP_ACTION
        ),
        "MEDIA_RX_STATE_IMPLEMENTED": STATE_MEDIA_CHANNEL_DISPOSED in session.events,
        "OPEN_COUNT_GATE": session.open_count <= 1,
        "STOP_COUNT_GATE": session.stop_count <= 1,
        "REGISTERED_CTPP_MISUSE_GATE": not registered_misuse,
        "STALE_CHANNEL_GATE": stale_channel_gate,
        "STOP_ORDER_GATE": stop_order,
        "LISTENER_PRESERVATION_MODEL": (
            session.listener_alive
            and session.registration_alive
            and session.pseudotcp_alive
            and session.call_transaction_alive
        ),
        "NEW_ICE": session.new_ice,
        "NEW_CLOUD": session.new_cloud,
        "NEW_PSEUDOTCP": session.new_pseudotcp,
        "NEW_REGISTRATION": session.new_registration,
        "NETWORK_TX": session.network_tx,
        "DOOR_ACTIONS": session.door_actions,
        "GATE_ACTIONS": session.gate_actions,
    }


def report(session: R34AttachedMediaSession | None = None) -> str:
    session = run_offline_attached_media_trace() if session is None else session
    gates = derive_gates(session)
    return "\n".join(
        (
            "=== COMELIT P116 R34 ATTACHED MEDIA OFFLINE IMPLEMENTATION ===",
            f"CALL_CTP_CAPTURE_IMPLEMENTED={_bool_marker(gates['CALL_CTP_CAPTURE_IMPLEMENTED'])}",
            f"MEDIAREQ26_SERIALIZER_IMPLEMENTED={_bool_marker(gates['MEDIAREQ26_SERIALIZER_IMPLEMENTED'])}",
            f"MEDIAREQ26_OPEN_IMPLEMENTED={_bool_marker(gates['MEDIAREQ26_OPEN_IMPLEMENTED'])}",
            f"MEDIAREQ26_STOP_IMPLEMENTED={_bool_marker(gates['MEDIAREQ26_STOP_IMPLEMENTED'])}",
            f"MEDIA_RX_STATE_IMPLEMENTED={_bool_marker(gates['MEDIA_RX_STATE_IMPLEMENTED'])}",
            f"OPEN_COUNT_GATE={_pass_marker(gates['OPEN_COUNT_GATE'])}",
            f"STOP_COUNT_GATE={_pass_marker(gates['STOP_COUNT_GATE'])}",
            f"REGISTERED_CTPP_MISUSE_GATE={_pass_marker(gates['REGISTERED_CTPP_MISUSE_GATE'])}",
            f"STALE_CHANNEL_GATE={_pass_marker(gates['STALE_CHANNEL_GATE'])}",
            f"STOP_ORDER_GATE={_pass_marker(gates['STOP_ORDER_GATE'])}",
            f"LISTENER_PRESERVATION_MODEL={_pass_marker(gates['LISTENER_PRESERVATION_MODEL'])}",
            f"NEW_ICE={_zero_marker(gates['NEW_ICE'])}",
            f"NEW_CLOUD={_zero_marker(gates['NEW_CLOUD'])}",
            f"NEW_PSEUDOTCP={_zero_marker(gates['NEW_PSEUDOTCP'])}",
            f"NEW_REGISTRATION={_zero_marker(gates['NEW_REGISTRATION'])}",
            f"NETWORK_TX={_zero_marker(gates['NETWORK_TX'])}",
            f"DOOR_ACTIONS={_zero_marker(gates['DOOR_ACTIONS'])}",
            f"GATE_ACTIONS={_zero_marker(gates['GATE_ACTIONS'])}",
            "=== END COMELIT P116 R34 ATTACHED MEDIA OFFLINE IMPLEMENTATION ===",
        )
    )


def _require_form(form: str) -> None:
    if form not in {MEDIAREQ26_FORM_TUNNEL, MEDIAREQ26_FORM_ADDRESS}:
        raise R34AttachedMediaRejected(f"unknown media request form: {form!r}")


def _require_u8(value: int, name: str) -> None:
    if not isinstance(value, int) or not 0 <= value <= 0xFF:
        raise R34AttachedMediaRejected(f"{name} must fit in one byte")


def _require_u16(value: int, name: str) -> None:
    if not isinstance(value, int) or not 1 <= value <= 0xFFFF:
        raise R34AttachedMediaRejected(f"{name} must be non-zero LE16")


def _require_u32(value: int, name: str) -> None:
    if not isinstance(value, int) or not 0 <= value <= 0xFFFFFFFF:
        raise R34AttachedMediaRejected(f"{name} must fit in LE32")


def _outer_handle_as_connection(outer_ctpp_handle: OuterCtppHandle) -> bytes | None:
    if not 0 <= outer_ctpp_handle.value <= 0xFFFF:
        return None
    return struct.pack(">H", outer_ctpp_handle.value)


def _bool_marker(value: bool | int | str) -> str:
    if not isinstance(value, bool):
        raise TypeError("boolean marker requires a bool")
    return "true" if value else "false"


def _pass_marker(value: bool | int | str) -> str:
    if not isinstance(value, bool):
        raise TypeError("PASS marker requires a bool")
    return "PASS" if value else "FAIL"


def _zero_marker(value: bool | int | str) -> str:
    return "0" if value == 0 else "OTHER"


__all__ = [
    "MEDIAREQ26_BODY_LENGTH",
    "MEDIAREQ26_UNKNOWN_FIELDS",
    "MEDIAREQ26_INNER_OPCODE",
    "MEDIAREQ26_OPEN_ACTION",
    "MEDIAREQ26_STOP_ACTION",
    "MEDIAREQ26_FORM_TUNNEL",
    "MEDIAREQ26_FORM_ADDRESS",
    "R34AttachedMediaRejected",
    "MediaRequest26Sources",
    "R34AttachedMediaSession",
    "open_flags",
    "stop_flags",
    "serialize_mediareq26_open",
    "serialize_mediareq26_stop",
    "parse_mediareq26",
    "serialize_call_bound_media_open",
    "serialize_call_bound_media_stop",
    "capture_call_ctp_id_from_call_init",
    "create_session_at_call_barrier",
    "default_open_sources",
    "run_offline_attached_media_trace",
    "second_open_forbidden_reasons",
    "derive_gates",
    "report",
    "r30b_build_mediareq26_open",
]


if __name__ == "__main__":
    print(report())
