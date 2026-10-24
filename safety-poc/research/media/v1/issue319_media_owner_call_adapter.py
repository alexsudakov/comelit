#!/usr/bin/env python3
"""Issue #319 R10: deterministic, offline-only media-owner adoption model.

This is deliberately a research harness, not a production transform.  Frames
exist only as bytes in :class:`FakeWriter`; ``transmitted_frame_count`` is
therefore always zero.  R45 owns the wire bodies, R53 owns the profile and
timeout, and R56 owns the single-slot/full-flush progression semantics.  The
small adapters below name those dependencies and keep listener-specific R54
logic out of the P78/P80 model.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, IntEnum, auto
from typing import Callable, Iterable

import entrance_p116_r45_call_adoption_core as r45
import entrance_p116_r53_call_adoption_profile_core as r53


class State(Enum):
    ACTIVE_SELF_ACTIVATION = auto()
    CAPTURE_GUARD = auto()
    ADOPTION_PENDING = auto()
    ACK_FLUSH = auto()
    CAPABILITIES_FLUSH = auto()
    ALERTING_FLUSH = auto()
    WAIT_PEER_CAPABILITIES = auto()
    PEER_ACK_FLUSH = auto()
    MEDIA_BIND_DECISION = auto()
    OBSERVE_ONLY = auto()
    FAIL_CLOSED = auto()
    COMPLETE = auto()


class MediaBindDecision(Enum):
    EXISTING_CHANNEL_REBIND = auto()
    SINGLE_UPSTREAM_CHANNEL_SWITCH = auto()
    UNSUPPORTED_FAIL_CLOSED = auto()


class FlushResult(Enum):
    COMPLETE = auto()
    EWOULDBLOCK = auto()
    PARTIAL = auto()
    TIMEOUT = auto()
    ERROR = auto()


class Priority(IntEnum):
    SELF_ACTIVATION = 10
    R27_REFRESH = 20
    ADOPTION = 30


@dataclass(frozen=True)
class CallIdentity:
    """Protocol-owned identity.  No episode/hash/time surrogate is accepted."""

    call_id: str
    owner_generation: int
    connection: int


@dataclass(frozen=True)
class PeerFrame:
    kind: str
    identity: CallIdentity | None
    sequence: int = 0
    capability_word: int = 0x27
    video_requested: bool = True
    malformed: bool = False


@dataclass(frozen=True)
class WriteIntent:
    subject: str
    frame: bytes
    generation: int
    priority: Priority


@dataclass
class _Slot:
    intent: WriteIntent
    offset: int = 0
    completion: Callable[[WriteIntent], None] | None = None


class FakeWriter:
    """R56-shaped single P12 slot with no network or real writer primitive."""

    def __init__(self, outcomes: Iterable[FlushResult] = ()) -> None:
        self._outcomes = list(outcomes)
        self.slot: _Slot | None = None
        self.intents: list[WriteIntent] = []
        self.sent_frames: list[WriteIntent] = []  # completed in fake memory only
        self.rejected_busy: list[WriteIntent] = []

    @property
    def transmitted_frame_count(self) -> int:
        """Invariant: this fake owns no transport or production-writer handle."""
        return 0

    @property
    def real_producer_count(self) -> int:
        return 0

    @property
    def network_primitive_count(self) -> int:
        return 0

    @property
    def audio_tx_count(self) -> int:
        return 0

    @property
    def door_action_count(self) -> int:
        return 0

    @property
    def gate_action_count(self) -> int:
        return 0

    @property
    def event_ring_count(self) -> int:
        return 0

    def enqueue(
        self, intent: WriteIntent, completion: Callable[[WriteIntent], None]
    ) -> bool:
        self.intents.append(intent)
        if self.slot is not None:
            self.rejected_busy.append(intent)
            return False
        self.slot = _Slot(intent=intent, completion=completion)
        return True

    def flush(self) -> FlushResult:
        if self.slot is None:
            return FlushResult.COMPLETE
        result = self._outcomes.pop(0) if self._outcomes else FlushResult.COMPLETE
        if result in (FlushResult.EWOULDBLOCK, FlushResult.TIMEOUT, FlushResult.ERROR):
            return result
        if result is FlushResult.PARTIAL:
            remaining = len(self.slot.intent.frame) - self.slot.offset
            self.slot.offset += max(1, remaining // 2)
            return result
        completed = self.slot
        self.slot = None  # R56: release happens before completion callback.
        self.sent_frames.append(completed.intent)
        if completed.completion:
            completed.completion(completed.intent)
        return FlushResult.COMPLETE


class R45SerializerAdapter:
    """Stateful envelope adapter delegating all wire shapes to R45."""

    def __init__(self, connection: int, local_sequence: int = 0) -> None:
        self.connection = connection
        self.local_sequence = local_sequence & 0xFF
        self.acknowledgement = 0
        self.source_logical = b"OFFLINE319"
        self.dest_logical = b"FAKEPEER19"

    def _packet(self, body: bytes) -> bytes:
        packet = r45.build_packet(
            flags=r45.CTP_FLAG_DATA,
            connection=self.connection,
            sequence=self.local_sequence,
            acknowledgement=self.acknowledgement,
            body=body,
            source_logical=self.source_logical,
            dest_logical=self.dest_logical,
        )
        self.local_sequence = (self.local_sequence + 1) & 0xFF
        return packet

    def _empty_ack(self, peer_sequence: int) -> bytes:
        self.acknowledgement = (peer_sequence + 1) & 0xFF
        return r45.build_empty_ack(
            connection=self.connection,
            local_sequence=self.local_sequence,
            peer_sequence=peer_sequence,
            source_logical=self.source_logical,
            dest_logical=self.dest_logical,
        )

    def invite_ack(self, peer_sequence: int) -> bytes:
        return self._empty_ack(peer_sequence)

    def capabilities(self, call_type: int, capability_word: int) -> bytes:
        return self._packet(r45.serialize_capabilities(call_type, capability_word))

    def alerting(self, argument: int) -> bytes:
        return self._packet(r45.serialize_alerting(argument))

    def peer_ack(self, peer_sequence: int) -> bytes:
        return self._empty_ack(peer_sequence)


@dataclass(frozen=True)
class R53ProfileAdapter:
    call_type: int
    capability_word: int
    alerting_argument: int

    @classmethod
    def from_contract(cls) -> R53ProfileAdapter:
        return cls(*r53.helper_runtime_fields())


class P12ArbiterAdapter:
    """Deterministic priority arbitration over the R56 single-slot contract."""

    def __init__(self, writer: FakeWriter) -> None:
        self.writer = writer
        self.pending: list[tuple[WriteIntent, Callable[[WriteIntent], None]]] = []
        self.refresh_index = 0

    def submit(self, intent: WriteIntent, callback: Callable[[WriteIntent], None]) -> bool:
        self.pending.append((intent, callback))
        return self.dispatch()

    def dispatch(self) -> bool:
        if self.writer.slot is not None or not self.pending:
            return False
        best = max(range(len(self.pending)), key=lambda i: self.pending[i][0].priority)
        intent, callback = self.pending.pop(best)
        return self.writer.enqueue(intent, callback)

    def completed(self, intent: WriteIntent) -> None:
        if intent.subject == "R27_REFRESH":
            self.refresh_index += 1
        self.dispatch()


@dataclass(frozen=True)
class MediaOwnership:
    generation: int
    channel: str
    owner_proven: bool = True
    upstream_count: int = 1
    receiver_terminal: bool = False
    teardown_uncertain: bool = False


@dataclass
class AdoptionResult:
    state: State
    reason: str
    decision: MediaBindDecision | None = None


class MediaOwnerCallAdapter:
    """One-shot adoption state machine for an already-active media owner."""

    def __init__(self, writer: FakeWriter, ownership: MediaOwnership) -> None:
        self.writer = writer
        self.arbiter = P12ArbiterAdapter(writer)
        self.ownership = ownership
        self.profile = R53ProfileAdapter.from_contract()
        self.serializer: R45SerializerAdapter | None = None
        self.state = State.ACTIVE_SELF_ACTIVATION
        self.identity: CallIdentity | None = None
        self.initial_signature: tuple[str, int, int] | None = None
        self.pending_peer: PeerFrame | None = None
        self.logical_call_events = 0
        self.retry_count = 0
        self.decision: MediaBindDecision | None = None
        self.reason = "active_self_activation"
        self._current_subject: str | None = None

    def result(self) -> AdoptionResult:
        return AdoptionResult(self.state, self.reason, self.decision)

    def receive_call_init(self, frame: PeerFrame) -> AdoptionResult:
        if self.state in (State.FAIL_CLOSED, State.OBSERVE_ONLY, State.COMPLETE):
            return self.result()
        if frame.malformed or frame.kind != "CALL_INIT":
            return self._ignore("malformed_call_init")
        if frame.identity is None:
            return self._fail("absence_of_call_identity")
        identity = frame.identity
        if identity.owner_generation != self.ownership.generation:
            return self._fail("generation_mismatch")
        if self.identity is not None:
            if identity == self.identity:
                return self._ignore("retransmit_no_new_tx")
            if identity.owner_generation == self.identity.owner_generation:
                return self._observe_only("genuine_second_call_ambiguous_scope")
            return self._fail("generation_mismatch")
        if not identity.call_id:
            return self._fail("absence_of_call_identity")
        self.state = State.CAPTURE_GUARD
        if identity.connection <= 0:
            return self._observe_only("unknown_connection_scope")
        self.identity = identity
        self.serializer = R45SerializerAdapter(identity.connection)
        self.initial_signature = (identity.call_id, identity.connection, frame.sequence)
        self.logical_call_events += 1
        self.state = State.ADOPTION_PENDING
        self.reason = "adoption_pending"
        self._queue_adoption("INVITE_ACK", self.serializer.invite_ack(frame.sequence))
        return self.result()

    def receive_peer_capabilities(self, frame: PeerFrame) -> AdoptionResult:
        if self.state in (State.FAIL_CLOSED, State.OBSERVE_ONLY, State.COMPLETE):
            return self.result()
        if frame.malformed or frame.kind != "CAPABILITIES" or frame.identity is None:
            return self._ignore("malformed_peer_frame")
        if self.identity is None or frame.identity.connection != self.identity.connection:
            return self._ignore("foreign_connection")
        if frame.identity.owner_generation != self.ownership.generation:
            return self._fail("stale_peer_generation")
        if frame.identity != self.identity or not frame.video_requested:
            return self._fail("peer_response_unexpected")
        if self.pending_peer is not None:
            return self._ignore("duplicate_peer_capabilities")
        self.pending_peer = frame
        if self.state is State.WAIT_PEER_CAPABILITIES:
            assert self.serializer is not None
            self._queue_adoption("PEER_ACK", self.serializer.peer_ack(frame.sequence))
        return self.result()

    def writable(self) -> AdoptionResult:
        outcome = self.writer.flush()
        if self.state in (State.FAIL_CLOSED, State.OBSERVE_ONLY, State.COMPLETE):
            return self.result()
        if outcome is FlushResult.TIMEOUT:
            return self._fail("p12_step_timeout_no_retry")
        if outcome is FlushResult.ERROR:
            return self._fail("writer_error_no_retry")
        return self.result()

    def tick_timeout(self) -> AdoptionResult:
        if self.state in (State.FAIL_CLOSED, State.OBSERVE_ONLY, State.COMPLETE):
            return self.result()
        if self.writer.slot is not None or self.state is State.WAIT_PEER_CAPABILITIES:
            return self._fail("p12_step_timeout_no_retry")
        return self.result()

    def receiver_terminated(self) -> AdoptionResult:
        return self._fail("receiver_terminal")

    def teardown_became_uncertain(self) -> AdoptionResult:
        return self._fail("teardown_uncertain")

    def decide_media_bind(
        self,
        requested_channel: str,
        *,
        old_channel_closed_confirmed: bool = False,
    ) -> AdoptionResult:
        if self.state is not State.MEDIA_BIND_DECISION:
            return self._fail("media_bind_out_of_order")
        own = self.ownership
        if own.receiver_terminal:
            return self._fail("receiver_terminal")
        if own.teardown_uncertain:
            return self._fail("teardown_uncertain")
        if requested_channel == own.channel and own.owner_proven and self.identity is not None:
            self.decision = MediaBindDecision.EXISTING_CHANNEL_REBIND
        elif (
            requested_channel != own.channel
            and old_channel_closed_confirmed
            and own.upstream_count == 1
            and own.owner_proven
        ):
            self.decision = MediaBindDecision.SINGLE_UPSTREAM_CHANNEL_SWITCH
        else:
            self.decision = MediaBindDecision.UNSUPPORTED_FAIL_CLOSED
            return self._fail("unsupported_media_bind", keep_decision=True)
        self.state = State.COMPLETE
        self.reason = "offline_decision_only"
        return self.result()

    def _queue_adoption(self, subject: str, frame: bytes) -> None:
        if self.identity is None or self.state in (State.FAIL_CLOSED, State.OBSERVE_ONLY):
            return
        intent = WriteIntent(subject, frame, self.identity.owner_generation, Priority.ADOPTION)
        self._current_subject = subject
        self.state = {
            "INVITE_ACK": State.ACK_FLUSH,
            "CAPABILITIES": State.CAPABILITIES_FLUSH,
            "ALERTING": State.ALERTING_FLUSH,
            "PEER_ACK": State.PEER_ACK_FLUSH,
        }[subject]
        if not self.arbiter.submit(intent, self._on_flush):
            self.reason = "p12_busy_wait"
            return
        self.reason = f"{subject.lower()}_flush"

    def _on_flush(self, intent: WriteIntent) -> None:
        if self.state in (State.FAIL_CLOSED, State.OBSERVE_ONLY, State.COMPLETE):
            self.arbiter.dispatch()
            return
        if self.identity is None or intent.generation != self.identity.owner_generation:
            self._fail("late_completion_generation_mismatch")
            return
        if intent.subject == "INVITE_ACK":
            assert self.serializer is not None
            self._queue_adoption(
                "CAPABILITIES",
                self.serializer.capabilities(
                    self.profile.call_type, self.profile.capability_word
                ),
            )
        elif intent.subject == "CAPABILITIES":
            assert self.serializer is not None
            self._queue_adoption(
                "ALERTING", self.serializer.alerting(self.profile.alerting_argument)
            )
        elif intent.subject == "ALERTING":
            self.state = State.WAIT_PEER_CAPABILITIES
            self.reason = "waiting_peer_capabilities"
            if self.pending_peer is not None:
                assert self.serializer is not None
                self._queue_adoption(
                    "PEER_ACK",
                    self.serializer.peer_ack(self.pending_peer.sequence),
                )
            else:
                self.arbiter.dispatch()
        elif intent.subject == "PEER_ACK":
            self.state = State.MEDIA_BIND_DECISION
            self.reason = "peer_ack_fully_flushed"
            self.arbiter.dispatch()

    def _ignore(self, reason: str) -> AdoptionResult:
        self.reason = reason
        return self.result()

    def _observe_only(self, reason: str) -> AdoptionResult:
        self.state = State.OBSERVE_ONLY
        self.reason = reason
        self._cancel_queued_adoption()
        return self.result()

    def _cancel_queued_adoption(self) -> None:
        self.arbiter.pending = [
            item for item in self.arbiter.pending if item[0].priority is not Priority.ADOPTION
        ]

    def _fail(self, reason: str, *, keep_decision: bool = False) -> AdoptionResult:
        self.state = State.FAIL_CLOSED
        if not keep_decision:
            self.decision = MediaBindDecision.UNSUPPORTED_FAIL_CLOSED
        self.reason = reason
        self._cancel_queued_adoption()
        self.retry_count = 0
        return self.result()


class FakePeer:
    """Deterministic scenario factory; it performs no I/O."""

    def __init__(self, identity: CallIdentity) -> None:
        self.identity = identity

    def initial_and_retransmits(self, count: int = 4) -> list[PeerFrame]:
        initial = PeerFrame("CALL_INIT", self.identity, sequence=7)
        return [initial] + [PeerFrame("CALL_INIT", self.identity, sequence=7) for _ in range(count)]

    def capabilities(self, *, early: bool = False) -> PeerFrame:
        del early  # timing is expressed by when the harness delivers the frame.
        return PeerFrame("CAPABILITIES", self.identity, sequence=11)

    def foreign_capabilities(self) -> PeerFrame:
        foreign = CallIdentity(self.identity.call_id, self.identity.owner_generation, self.identity.connection + 1)
        return PeerFrame("CAPABILITIES", foreign, sequence=11)

    def stale_capabilities(self) -> PeerFrame:
        stale = CallIdentity(self.identity.call_id, self.identity.owner_generation - 1, self.identity.connection)
        return PeerFrame("CAPABILITIES", stale, sequence=11)

    def no_response(self) -> None:
        """Express the missing-response scenario without scheduling any event."""
        return None
