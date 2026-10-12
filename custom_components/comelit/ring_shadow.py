from __future__ import annotations

from collections import deque
from dataclasses import dataclass, replace
from typing import Deque

SHADOW_OWNER_LISTENER = "listener"
SHADOW_OWNER_MEDIA = "on_demand_media"

SHADOW_DECISION_EMIT = "EMIT"
SHADOW_DECISION_SUPPRESS = "SUPPRESS"
SHADOW_DECISION_HANDOFF_REPLAY = "HANDOFF_REPLAY"
SHADOW_DECISION_OPEN_UNRESOLVED = "OPEN_UNRESOLVED"
SHADOW_DECISION_SHADOW = "SHADOW"

SHADOW_REASON_NO_LIVE_CALL = "no_live_call"
SHADOW_REASON_SAME_PROCESS_LISTENER = "same_process_listener_current_main"
SHADOW_REASON_SAME_PROCESS_MEDIA_RETRANSMIT = "same_process_media_retransmit"
# PR-1b may reintroduce media-route verdicts with an explicit media emit route.
SHADOW_REASON_LIVE_CALL_REPLAY = "live_call_replay"
SHADOW_REASON_HANDOFF_REPLAY = "handoff_replay"
SHADOW_REASON_LIVE_STATE_RESET = "live_state_reset"
SHADOW_REASON_HIGH_A2 = "HIGH_A2_terminal_handoff_duplicate_risk"
SHADOW_REASON_HIGH_3 = "HIGH_3_watchdog_expiry_unresolved"
SHADOW_REASON_MALFORMED = "malformed_shadow_batch"
SHADOW_REASON_INCOMPLETE = "incomplete_shadow_batch"

SHADOW_RING_SOURCE_TO_DOOR = {"00000643": "entrance", "00000610": "gate"}
SHADOW_RING_DEVICE_TO_CLIENT = "DEVICE_TO_CLIENT"
SHADOW_RING_CALL_INIT = "CALL_INIT"

SHADOW_RING_BATCH_KEYS = frozenset({
    "V4_RING_OBSERVED", "V4_RING_DIRECTION", "V4_RING_KIND",
    "V4_RING_DOOR", "V4_RING_SOURCE",
})
SHADOW_RING_SHA_KEYS = frozenset({"V4_RING_FRAME_SHA256", "V4_RING_RETRANSMIT_SHA256"})
SHADOW_RING_RETRANSMIT_KEYS = frozenset({"V4_RING_RETRANSMIT_SUPPRESSED"})
SHADOW_REMOTE_RELEASE_LINES = frozenset({
    "R37_REMOTE_RELEASE_OBSERVED=true",
    "R64_POST_CALL_REMOTE_RELEASE_OBSERVED=true",
    "R64_TERMINAL_REMOTE_RELEASE_OBSERVED=true",
})

SHADOW_MAX_LINES_PER_BATCH = 16
SHADOW_MAX_COMPLETED_BATCHES = 16
SHADOW_MAX_DECISIONS = 16
SHADOW_MAX_LIVE_KEYS = 4
SHADOW_MAX_GENERATIONS = 4
SHADOW_MAX_OWNER_GENERATIONS = 4
SHADOW_FAILURE_LATCH_LIMIT = 3
SHADOW_MAX_PROBE_RECORDS = 16
SHADOW_MAX_PROBE_SHA_SLOTS = 4

OWNER_GENERATION_IS_CALL_IDENTITY = False
HANDOFF_EPOCH_IS_CALL_IDENTITY = False
FULL_FRAME_SHA_USED_AS_CALL_IDENTITY = False
V4_RING_BODY_32_35_SEMANTICS = "UNKNOWN"
V4_RING_BODY_32_35_LIVE_VERIFIED = False

SHADOW_PROBE_KEYS = frozenset({
    "V4_RING_PHASE",
    "V4_RING_PEER_CONNECTION",
    "V4_RING_BODY_32_35",
    "V4_RING_PARSE_STATUS",
})
SHADOW_PROBE_PHASES = frozenset({"INITIAL", "RETRANSMIT"})
SHADOW_PROBE_PARSE_STATUSES = frozenset({"OK", "INSUFFICIENT_LENGTH"})
SHADOW_PROBE_SHA_CHANGED = "CHANGED"
SHADOW_PROBE_SHA_SAME = "SAME"
SHADOW_PROBE_SHA_FIRST_IN_GENERATION = "FIRST_IN_GENERATION"
SHADOW_PROBE_SHA_NOT_ADJACENT = "NOT_ADJACENT"

_MASK_OBSERVED = 1
_MASK_DIRECTION = 2
_MASK_KIND = 4
_MASK_DOOR = 8
_MASK_SOURCE = 16
_MASK_COMPLETE = 31


@dataclass(frozen=True)
class RingMarkerBatch:
    sequence: int
    complete: bool
    malformed: bool
    retransmit: bool
    door: str | None
    source: str | None
    identity_source: str
    frame_sha_present: bool
    retransmit_sha_present: bool
    # diagnostic batch sequence, NOT a process generation
    generation: int
    markers: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "sequence": self.sequence,
            "complete": self.complete,
            "malformed": self.malformed,
            "retransmit": self.retransmit,
            "door": self.door,
            "source": self.source,
            "identity_source": self.identity_source,
            "frame_sha_present": self.frame_sha_present,
            "retransmit_sha_present": self.retransmit_sha_present,
            "generation": self.generation,
            "markers": self.markers,
        }


@dataclass(frozen=True)
class ShadowDecision:
    decision: str
    reason: str
    production_effect: bool = False
    owner: str | None = None
    generation: int = 0
    owner_generation: tuple[str, int] | None = None
    handoff_epoch: int = 0
    handoff_token: int = 0
    retransmit: bool = False
    new_call_proven: bool = False
    reattach: bool = False
    rearm_watchdog: bool = False
    terminal_retry: bool = False
    missing_identity: bool = False

    def as_dict(self) -> dict[str, object]:
        return {
            "decision": self.decision,
            "reason": self.reason,
            "production_effect": self.production_effect,
            "owner": self.owner,
            "generation": self.generation,
            "owner_generation": self.owner_generation,
            "handoff_epoch": self.handoff_epoch,
            "handoff_token": self.handoff_token,
            "retransmit": self.retransmit,
            "new_call_proven": self.new_call_proven,
            "reattach": self.reattach,
            "rearm_watchdog": self.rearm_watchdog,
            "terminal_retry": self.terminal_retry,
            "missing_identity": self.missing_identity,
        }


@dataclass(frozen=True)
class RingProbeRecord:
    sequence: int
    owner_kind: str
    owner_generation: tuple[str, int]
    handoff_epoch: int
    phase: str
    parse_status: str
    peer_connection_present: bool
    body_32_35_present: bool
    body_32_35_unavailable: bool
    sha_changed_vs_prev_initial: str

    def as_dict(self) -> dict[str, object]:
        return {
            "sequence": self.sequence,
            "owner_kind": self.owner_kind,
            # Context only. OWNER_GENERATION_IS_CALL_IDENTITY=false.
            "owner_generation": self.owner_generation,
            # Context only. HANDOFF_EPOCH_IS_CALL_IDENTITY=false.
            "handoff_epoch": self.handoff_epoch,
            "phase": self.phase,
            "parse_status": self.parse_status,
            "peer_connection_present": self.peer_connection_present,
            "body_32_35_present": self.body_32_35_present,
            "body_32_35_unavailable": self.body_32_35_unavailable,
            "sha_changed_vs_prev_initial": self.sha_changed_vs_prev_initial,
        }


@dataclass
class _RingProbePending:
    phase: str | None = None
    peer_connection: str | None = None
    body_32_35: str | None = None


@dataclass
class _ShadowLive:
    door: str
    source: str
    generations: Deque[tuple[str, int]]
    origin_owner: str
    origin_generation: int
    origin_owner_generation: tuple[str, int]
    current_owner_kind: str
    current_owner_generation: tuple[str, int]
    previous_owner_kind: str | None
    previous_owner_generation: tuple[str, int] | None
    handoff_epoch: int
    handoff_token: int
    owner_lifecycle_epoch: int
    interaction_seen: bool
    watchdog_boundary_crossed: bool = False
    reset_reason: str | None = None
    reset_is_new_call_proof: bool = False
    reattached: bool = False


def _ring_key_mask(key: str) -> int:
    if key == "V4_RING_OBSERVED":
        return _MASK_OBSERVED
    if key == "V4_RING_DIRECTION":
        return _MASK_DIRECTION
    if key == "V4_RING_KIND":
        return _MASK_KIND
    if key == "V4_RING_DOOR":
        return _MASK_DOOR
    if key == "V4_RING_SOURCE":
        return _MASK_SOURCE
    return 0


class RingMarkerBatcher:
    def __init__(self) -> None:
        self._buffer: Deque[str] = deque(maxlen=16)
        self._completed: Deque[RingMarkerBatch] = deque(maxlen=16)
        assert self._buffer.maxlen == SHADOW_MAX_LINES_PER_BATCH
        assert self._completed.maxlen == SHADOW_MAX_COMPLETED_BATCHES
        self._present_mask = 0
        self._sequence = 0
        # diagnostic batch sequence, NOT a process generation
        self._generation = 0
        self._malformed = False
        self._retransmit = False
        self._frame_sha_present = False
        self._next_frame_sha_present = False
        self._retransmit_sha_present = False
        self._observed_value: str | None = None
        self._direction_value: str | None = None
        self._kind_value: str | None = None
        self._door_value: str | None = None
        self._source_value: str | None = None
        self._no_separator_count = 0
        self._observed_false_count = 0
        self._malformed_count = 0
        self._sha_marker_count = 0
        self._unknown_marker_count = 0
        self._eviction_count = 0

    def _reset_current(self, *, preserve_next_frame: bool = False) -> None:
        self._buffer.clear()
        self._present_mask = 0
        self._malformed = False
        self._retransmit = False
        self._frame_sha_present = False
        if not preserve_next_frame:
            self._next_frame_sha_present = False
        self._retransmit_sha_present = False
        self._observed_value = None
        self._direction_value = None
        self._kind_value = None
        self._door_value = None
        self._source_value = None

    def _append_marker(self, line: str) -> None:
        if len(self._buffer) == SHADOW_MAX_LINES_PER_BATCH:
            self._eviction_count += 1
            self._malformed = True
        self._buffer.append(line)

    def _remember_batch_value(self, key: str, value: str) -> None:
        if key == "V4_RING_OBSERVED":
            if self._observed_value is None:
                self._observed_value = value
            elif self._observed_value != value:
                if not self._malformed:
                    self._malformed_count += 1
                self._malformed = True
            return
        if key == "V4_RING_DIRECTION":
            if self._direction_value is None:
                self._direction_value = value
            elif self._direction_value != value:
                if not self._malformed:
                    self._malformed_count += 1
                self._malformed = True
            return
        if key == "V4_RING_KIND":
            if self._kind_value is None:
                self._kind_value = value
            elif self._kind_value != value:
                if not self._malformed:
                    self._malformed_count += 1
                self._malformed = True
            return
        if key == "V4_RING_DOOR":
            if self._door_value is None:
                self._door_value = value
            elif self._door_value != value:
                if not self._malformed:
                    self._malformed_count += 1
                self._malformed = True
            return
        if key == "V4_RING_SOURCE":
            if self._source_value is None:
                self._source_value = value
            elif self._source_value != value:
                if not self._malformed:
                    self._malformed_count += 1
                self._malformed = True

    def _validate_complete_batch(self) -> None:
        if self._direction_value != SHADOW_RING_DEVICE_TO_CLIENT:
            self._malformed = True
        if self._kind_value != SHADOW_RING_CALL_INIT:
            self._malformed = True
        expected_door = SHADOW_RING_SOURCE_TO_DOOR.get(self._source_value)
        if expected_door is None:
            self._malformed = True
        elif self._door_value != expected_door:
            self._malformed = True

    def _complete_batch(self) -> RingMarkerBatch:
        self._validate_complete_batch()
        if self._malformed:
            self._malformed_count += 1
        self._sequence += 1
        self._generation += 1
        markers = tuple(self._buffer)
        batch = RingMarkerBatch(
            sequence=self._sequence,
            complete=True,
            malformed=self._malformed,
            retransmit=self._retransmit,
            door=self._door_value,
            source=self._source_value,
            identity_source="observed",
            frame_sha_present=self._frame_sha_present,
            retransmit_sha_present=self._retransmit_sha_present,
            generation=self._generation,
            markers=markers,
        )
        self._completed.append(batch)
        self._reset_current()
        return batch

    def _complete_retransmit(self) -> RingMarkerBatch:
        previous = self._completed[-1] if self._completed else None
        self._sequence += 1
        self._generation += 1
        generation = self._generation
        if previous is None or previous.malformed:
            door = None
            source = None
            identity_source = "none"
        else:
            door = previous.door
            source = previous.source
            identity_source = "last_completed_batch"
        batch = RingMarkerBatch(
            sequence=self._sequence,
            complete=True,
            malformed=False,
            retransmit=True,
            door=door,
            source=source,
            identity_source=identity_source,
            frame_sha_present=False,
            retransmit_sha_present=self._retransmit_sha_present,
            generation=generation,
            markers=("V4_RING_RETRANSMIT_SUPPRESSED=true",),
        )
        self._completed.append(batch)
        self._reset_current()
        return batch

    def _mark_retransmit_sha_on_last_batch(self) -> None:
        if not self._completed:
            return
        previous = self._completed[-1]
        if not previous.retransmit or previous.retransmit_sha_present:
            return
        self._completed.pop()
        self._completed.append(replace(previous, retransmit_sha_present=True))

    def observe(self, line: str) -> tuple[RingMarkerBatch, ...]:
        if "=" not in line:
            self._no_separator_count += 1
            return ()
        key, value = line.split("=", 1)
        value = value.strip()

        if key == "V4_RING_OBSERVED":
            if value == "true":
                frame_sha_present = self._next_frame_sha_present
                self._reset_current(preserve_next_frame=True)
                self._frame_sha_present = frame_sha_present
                self._next_frame_sha_present = False
                self._append_marker(line)
                self._remember_batch_value(key, value)
                self._present_mask |= _MASK_OBSERVED
            elif value == "false":
                self._reset_current()
                self._observed_false_count += 1
                return ()
            else:
                if not self._malformed:
                    self._malformed_count += 1
                self._malformed = True
                self._append_marker(line)
                self._remember_batch_value(key, value)
                self._present_mask |= _MASK_OBSERVED
        elif key in SHADOW_RING_BATCH_KEYS:
            self._append_marker(line)
            self._remember_batch_value(key, value)
            self._present_mask |= _ring_key_mask(key)
        elif key in SHADOW_RING_SHA_KEYS:
            if key == "V4_RING_FRAME_SHA256":
                if self._present_mask == 0 and not self._buffer:
                    self._next_frame_sha_present = True
                else:
                    self._frame_sha_present = True
            else:
                self._retransmit_sha_present = True
                self._mark_retransmit_sha_on_last_batch()
            self._sha_marker_count += 1
        elif key in SHADOW_RING_RETRANSMIT_KEYS:
            if value == "true":
                return (self._complete_retransmit(),)
        elif key.startswith("V4_RING_"):
            self._unknown_marker_count += 1

        if self._present_mask == _MASK_COMPLETE:
            return (self._complete_batch(),)
        return ()

    def pending(self) -> RingMarkerBatch | None:
        if not self._buffer and self._present_mask == 0:
            return None
        markers = tuple(self._buffer)
        return RingMarkerBatch(
            sequence=self._sequence + 1,
            complete=False,
            malformed=self._malformed,
            retransmit=self._retransmit,
            door=self._door_value,
            source=self._source_value,
            identity_source=(
                "observed"
                if self._door_value is not None and self._source_value is not None
                else "none"
            ),
            frame_sha_present=self._frame_sha_present,
            retransmit_sha_present=self._retransmit_sha_present,
            generation=self._generation + 1,
            markers=markers,
        )

    def snapshot(self) -> dict[str, object]:
        pending = self.pending()
        return {
            "completed": tuple(batch.as_dict() for batch in self._completed),
            "pending": pending.as_dict() if pending is not None else None,
            "present_mask": self._present_mask,
            "no_separator_count": self._no_separator_count,
            "observed_false_count": self._observed_false_count,
            "malformed_count": self._malformed_count,
            "sha_marker_count": self._sha_marker_count,
            "unknown_marker_count": self._unknown_marker_count,
            "eviction_count": self._eviction_count,
        }


def _is_lower_hex(value: str, width: int) -> bool:
    if len(value) != width:
        return False
    return all(("0" <= char <= "9") or ("a" <= char <= "f") for char in value)


class RingProbeParser:
    """Key-specific shadow probe parser. It never owns call identity."""

    def __init__(self) -> None:
        self._pending: dict[str, _RingProbePending] = {
            SHADOW_OWNER_LISTENER: _RingProbePending(),
            SHADOW_OWNER_MEDIA: _RingProbePending(),
        }
        self._records: Deque[RingProbeRecord] = deque(maxlen=SHADOW_MAX_PROBE_RECORDS)
        assert self._records.maxlen == SHADOW_MAX_PROBE_RECORDS
        self._sequence = 0
        self._malformed_count = 0
        self._ignored_count = 0
        self._eviction_count = 0
        self._missing_status_count = 0
        self._pending_frame_sha: dict[str, str] = {}
        self._previous_initial_sha: Deque[tuple[tuple[str, int], str]] = deque(
            maxlen=SHADOW_MAX_PROBE_SHA_SLOTS
        )
        assert self._previous_initial_sha.maxlen == SHADOW_MAX_PROBE_SHA_SLOTS

    def _reset_pending(self, owner: str) -> None:
        self._pending[owner] = _RingProbePending()

    def _mark_malformed(self, owner: str) -> None:
        self._malformed_count += 1
        self._reset_pending(owner)
        self._pending_frame_sha.pop(owner, None)

    def _remember_previous_sha(self, owner_generation: tuple[str, int], digest: str) -> None:
        for index, (key, _previous) in enumerate(tuple(self._previous_initial_sha)):
            if key == owner_generation:
                del self._previous_initial_sha[index]
                break
        self._previous_initial_sha.append((owner_generation, digest))

    def _previous_sha(self, owner_generation: tuple[str, int]) -> str | None:
        for key, digest in self._previous_initial_sha:
            if key == owner_generation:
                return digest
        return None

    def _sha_changed_state(
        self,
        owner: str,
        owner_generation: tuple[str, int],
        phase: str,
    ) -> str:
        if phase != "INITIAL":
            self._pending_frame_sha.pop(owner, None)
            return SHADOW_PROBE_SHA_NOT_ADJACENT
        digest = self._pending_frame_sha.pop(owner, None)
        if digest is None:
            return SHADOW_PROBE_SHA_NOT_ADJACENT
        previous = self._previous_sha(owner_generation)
        self._remember_previous_sha(owner_generation, digest)
        if previous is None:
            return SHADOW_PROBE_SHA_FIRST_IN_GENERATION
        if previous == digest:
            return SHADOW_PROBE_SHA_SAME
        return SHADOW_PROBE_SHA_CHANGED

    def observe_sha(self, owner: str, line: str) -> None:
        if "=" not in line:
            return
        key, value = line.split("=", 1)
        value = value.strip()
        if key != "V4_RING_FRAME_SHA256":
            return
        if _is_lower_hex(value, 64):
            self._pending_frame_sha[owner] = value
        else:
            self._pending_frame_sha.pop(owner, None)

    def observe(
        self,
        owner: str,
        line: str,
        *,
        owner_generation: tuple[str, int],
        handoff_epoch: int,
    ) -> tuple[RingProbeRecord, ...]:
        if owner not in self._pending:
            self._ignored_count += 1
            return ()
        if "=" not in line:
            if line in SHADOW_PROBE_KEYS:
                self._mark_malformed(owner)
            return ()
        key, value = line.split("=", 1)
        value = value.strip()
        if key not in SHADOW_PROBE_KEYS:
            self._ignored_count += 1
            return ()

        pending = self._pending[owner]
        if key == "V4_RING_PHASE":
            if value not in SHADOW_PROBE_PHASES:
                self._mark_malformed(owner)
                return ()
            if pending.phase is not None:
                self._missing_status_count += 1
            self._pending[owner] = _RingProbePending(phase=value)
            return ()
        if key == "V4_RING_PEER_CONNECTION":
            if not _is_lower_hex(value, 4):
                self._mark_malformed(owner)
                return ()
            pending.peer_connection = value
            return ()
        if key == "V4_RING_BODY_32_35":
            if value != "----" and not _is_lower_hex(value, 8):
                self._mark_malformed(owner)
                return ()
            pending.body_32_35 = value
            return ()

        if value not in SHADOW_PROBE_PARSE_STATUSES:
            self._mark_malformed(owner)
            return ()
        if pending.phase is None:
            self._mark_malformed(owner)
            return ()
        if value == "OK" and (pending.peer_connection is None or pending.body_32_35 in (None, "----")):
            self._mark_malformed(owner)
            return ()

        self._sequence += 1
        if len(self._records) == SHADOW_MAX_PROBE_RECORDS:
            self._eviction_count += 1
        record = RingProbeRecord(
            sequence=self._sequence,
            owner_kind=owner,
            owner_generation=owner_generation,
            handoff_epoch=handoff_epoch,
            phase=pending.phase,
            parse_status=value,
            peer_connection_present=pending.peer_connection is not None,
            body_32_35_present=(
                pending.body_32_35 is not None and pending.body_32_35 != "----"
            ),
            body_32_35_unavailable=pending.body_32_35 == "----",
            sha_changed_vs_prev_initial=self._sha_changed_state(
                owner,
                owner_generation,
                pending.phase,
            ),
        )
        self._records.append(record)
        self._reset_pending(owner)
        return (record,)

    def snapshot(self) -> dict[str, object]:
        return {
            "records": tuple(record.as_dict() for record in self._records),
            "pending": {
                owner: {
                    "phase_present": pending.phase is not None,
                    "peer_connection_present": pending.peer_connection is not None,
                    "body_32_35_present": (
                        pending.body_32_35 is not None and pending.body_32_35 != "----"
                    ),
                    "body_32_35_unavailable": pending.body_32_35 == "----",
                    "frame_sha_pending": owner in self._pending_frame_sha,
                }
                for owner, pending in self._pending.items()
            },
            "malformed_count": self._malformed_count,
            "ignored_count": self._ignored_count,
            "eviction_count": self._eviction_count,
            "missing_status_count": self._missing_status_count,
            "record_count": len(self._records),
        }


class RingEmitGuard:
    def __init__(self) -> None:
        self._live: Deque[_ShadowLive] = deque(maxlen=4)
        self._decisions: Deque[ShadowDecision] = deque(maxlen=16)
        assert self._live.maxlen == SHADOW_MAX_LIVE_KEYS
        assert self._decisions.maxlen == SHADOW_MAX_DECISIONS
        self._last_decided: dict[str, str] = {
            SHADOW_OWNER_LISTENER: "",
            SHADOW_OWNER_MEDIA: "",
        }
        self._resets_total = 0

    @staticmethod
    def _entry_key(door: str, source: str) -> str:
        return door + "\n" + source

    def _find_live(self, door: str, source: str) -> _ShadowLive | None:
        for live in self._live:
            if live.door == door and live.source == source:
                return live
        return None

    def observe_interaction(self, owner: str) -> None:
        key = self._last_decided.get(owner, "")
        if not key:
            return
        for candidate in self._live:
            if (
                candidate.reset_reason is None
                and self._entry_key(candidate.door, candidate.source) == key
            ):
                candidate.interaction_seen = True
                return

    def note_watchdog_boundary_crossed(self, owner: str) -> None:
        for live in self._live:
            if live.current_owner_kind == owner:
                live.watchdog_boundary_crossed = True

    def reset_owner_lifecycle(self, owner: str, stale_owners: set[str]) -> None:
        for live in self._live:
            if live.current_owner_kind in stale_owners:
                if live.reset_reason is not None:
                    continue
                live.reset_reason = "owner_lifecycle_reset"
                live.reset_is_new_call_proof = False
                self._resets_total += 1
                self._remember_decision(ShadowDecision(
                    decision=SHADOW_DECISION_SHADOW,
                    reason=SHADOW_REASON_LIVE_STATE_RESET,
                    production_effect=False,
                    owner=live.current_owner_kind,
                    generation=live.current_owner_generation[1],
                    owner_generation=live.current_owner_generation,
                    handoff_epoch=live.handoff_epoch,
                    handoff_token=live.handoff_token,
                    new_call_proven=False,
                ))

    def note_owner_handoff(self, owner: str, owner_generation: tuple[str, int]) -> None:
        for live in self._live:
            if live.current_owner_kind == owner:
                continue
            live.previous_owner_kind = live.current_owner_kind
            live.previous_owner_generation = live.current_owner_generation
            live.handoff_epoch += 1
            live.handoff_token += 1

    def _remember_decision(self, decision: ShadowDecision) -> ShadowDecision:
        self._decisions.append(decision)
        return decision

    def _make_decision(
        self,
        decision: str,
        reason: str,
        owner: str,
        owner_generation: tuple[str, int],
        *,
        handoff_epoch: int = 0,
        handoff_token: int = 0,
        retransmit: bool = False,
        reattach: bool = False,
        rearm_watchdog: bool = False,
        missing_identity: bool = False,
    ) -> ShadowDecision:
        return self._remember_decision(ShadowDecision(
            decision=decision,
            reason=reason,
            production_effect=False,
            owner=owner,
            generation=owner_generation[1],
            owner_generation=owner_generation,
            handoff_epoch=handoff_epoch,
            handoff_token=handoff_token,
            retransmit=retransmit,
            new_call_proven=False,
            reattach=reattach,
            rearm_watchdog=rearm_watchdog,
            terminal_retry=False,
            missing_identity=missing_identity,
        ))

    def decide(
        self,
        *,
        door: str | None,
        source: str | None,
        owner: str,
        owner_generation: tuple[str, int],
        retransmit: bool = False,
        interaction_seen: bool = False,
        watchdog_boundary_crossed: bool = False,
        has_new_physical_call_discriminator: bool = False,
        production_emit_allowed: bool = False,
    ) -> ShadowDecision:
        if door is None or source is None:
            return self._make_decision(
                SHADOW_DECISION_SHADOW,
                SHADOW_REASON_INCOMPLETE,
                owner,
                owner_generation,
                retransmit=retransmit,
                missing_identity=True,
            )

        self._last_decided[owner] = self._entry_key(door, source)
        live = self._find_live(door, source)
        if live is None:
            generations: Deque[tuple[str, int]] = deque(maxlen=4)
            assert generations.maxlen == SHADOW_MAX_GENERATIONS
            generations.append(owner_generation)
            self._live.append(_ShadowLive(
                door=door,
                source=source,
                generations=generations,
                origin_owner=owner,
                origin_generation=owner_generation[1],
                origin_owner_generation=owner_generation,
                current_owner_kind=owner,
                current_owner_generation=owner_generation,
                previous_owner_kind=None,
                previous_owner_generation=None,
                handoff_epoch=0,
                handoff_token=0,
                owner_lifecycle_epoch=1,
                interaction_seen=interaction_seen,
            ))
            decision = (
                SHADOW_DECISION_EMIT
                if production_emit_allowed
                and has_new_physical_call_discriminator
                and not retransmit
                else SHADOW_DECISION_SHADOW
            )
            return self._make_decision(
                decision,
                SHADOW_REASON_NO_LIVE_CALL,
                owner,
                owner_generation,
                retransmit=retransmit,
            )

        if interaction_seen:
            live.interaction_seen = True
        if watchdog_boundary_crossed:
            live.watchdog_boundary_crossed = True

        if live.reset_reason is not None:
            live.generations.clear()
            live.generations.append(owner_generation)
            live.origin_owner = owner
            live.origin_generation = owner_generation[1]
            live.origin_owner_generation = owner_generation
            live.current_owner_kind = owner
            live.current_owner_generation = owner_generation
            live.previous_owner_kind = None
            live.previous_owner_generation = None
            live.handoff_epoch = 0
            live.handoff_token = 0
            live.owner_lifecycle_epoch += 1
            live.interaction_seen = interaction_seen
            live.watchdog_boundary_crossed = watchdog_boundary_crossed
            live.reset_reason = None
            live.reset_is_new_call_proof = False
            live.reattached = False
            return self._make_decision(
                SHADOW_DECISION_OPEN_UNRESOLVED,
                SHADOW_REASON_LIVE_STATE_RESET,
                owner,
                owner_generation,
                retransmit=retransmit,
            )

        if owner_generation == live.origin_owner_generation:
            if retransmit:
                return self._make_decision(
                    SHADOW_DECISION_SUPPRESS,
                    SHADOW_REASON_LIVE_CALL_REPLAY,
                    owner,
                    owner_generation,
                    handoff_epoch=live.handoff_epoch,
                    handoff_token=live.handoff_token,
                    retransmit=True,
                )
            if owner == SHADOW_OWNER_LISTENER:
                decision = SHADOW_DECISION_EMIT if production_emit_allowed else SHADOW_DECISION_SHADOW
                return self._make_decision(
                    decision,
                    SHADOW_REASON_SAME_PROCESS_LISTENER,
                    owner,
                    owner_generation,
                    handoff_epoch=live.handoff_epoch,
                    handoff_token=live.handoff_token,
                )
            if owner == SHADOW_OWNER_MEDIA:
                return self._make_decision(
                    SHADOW_DECISION_SUPPRESS,
                    SHADOW_REASON_SAME_PROCESS_MEDIA_RETRANSMIT,
                    owner,
                    owner_generation,
                    handoff_epoch=live.handoff_epoch,
                    handoff_token=live.handoff_token,
                )

        if owner_generation in live.generations:
            return self._make_decision(
                SHADOW_DECISION_SUPPRESS,
                SHADOW_REASON_LIVE_CALL_REPLAY,
                owner,
                owner_generation,
                handoff_epoch=live.handoff_epoch,
                handoff_token=live.handoff_token,
                retransmit=retransmit,
            )

        live.generations.append(owner_generation)
        previous_owner = live.current_owner_kind
        previous_generation = live.current_owner_generation
        owner_changed = previous_owner != owner
        if owner_changed:
            if (
                live.previous_owner_kind != previous_owner
                or live.previous_owner_generation != previous_generation
            ):
                live.previous_owner_kind = previous_owner
                live.previous_owner_generation = previous_generation
                live.handoff_epoch += 1
                live.handoff_token += 1
        live.current_owner_kind = owner
        live.current_owner_generation = owner_generation

        if retransmit:
            return self._make_decision(
                SHADOW_DECISION_SUPPRESS,
                SHADOW_REASON_LIVE_CALL_REPLAY,
                owner,
                owner_generation,
                handoff_epoch=live.handoff_epoch,
                handoff_token=live.handoff_token,
                retransmit=True,
            )
        if live.interaction_seen:
            return self._make_decision(
                SHADOW_DECISION_OPEN_UNRESOLVED,
                SHADOW_REASON_HIGH_A2,
                owner,
                owner_generation,
                handoff_epoch=live.handoff_epoch,
                handoff_token=live.handoff_token,
            )
        if live.watchdog_boundary_crossed:
            live.watchdog_boundary_crossed = False
            return self._make_decision(
                SHADOW_DECISION_OPEN_UNRESOLVED,
                SHADOW_REASON_HIGH_3,
                owner,
                owner_generation,
                handoff_epoch=live.handoff_epoch,
                handoff_token=live.handoff_token,
            )
        if owner_changed:
            return self._make_decision(
                SHADOW_DECISION_HANDOFF_REPLAY,
                SHADOW_REASON_HANDOFF_REPLAY,
                owner,
                owner_generation,
                handoff_epoch=live.handoff_epoch,
                handoff_token=live.handoff_token,
            )
        reattach = not live.reattached
        if reattach:
            live.reattached = True
        return self._make_decision(
            SHADOW_DECISION_SUPPRESS,
            SHADOW_REASON_LIVE_CALL_REPLAY,
            owner,
            owner_generation,
            handoff_epoch=live.handoff_epoch,
            handoff_token=live.handoff_token,
            reattach=reattach,
            rearm_watchdog=True,
        )

    def snapshot(self) -> dict[str, object]:
        return {
            "live": tuple(
                {
                    "door": live.door,
                    "source": live.source,
                    "generations": tuple(live.generations),
                    "origin_owner": live.origin_owner,
                    "origin_generation": live.origin_generation,
                    "origin_owner_generation": live.origin_owner_generation,
                    "current_owner_kind": live.current_owner_kind,
                    "current_owner_generation": live.current_owner_generation,
                    "previous_owner_kind": live.previous_owner_kind,
                    "previous_owner_generation": live.previous_owner_generation,
                    "handoff_epoch": live.handoff_epoch,
                    "handoff_token": live.handoff_token,
                    "owner_lifecycle_epoch": live.owner_lifecycle_epoch,
                    "interaction_seen": live.interaction_seen,
                    "watchdog_boundary_crossed": live.watchdog_boundary_crossed,
                    "reset_reason": live.reset_reason,
                    "reset_is_new_call_proof": live.reset_is_new_call_proof,
                    "reattached": live.reattached,
                }
                for live in self._live
            ),
            "decisions": tuple(decision.as_dict() for decision in self._decisions),
            "reset_count": self._resets_total,
            "resets_total": self._resets_total,
        }


class RingShadowController:
    """Config-entry-level shadow state. Pure sync. Never awaits, never does I/O."""

    def __init__(self) -> None:
        self._batchers = {
            SHADOW_OWNER_LISTENER: RingMarkerBatcher(),
            SHADOW_OWNER_MEDIA: RingMarkerBatcher(),
        }
        self._probe_parser = RingProbeParser()
        self._guard = RingEmitGuard()
        self._decisions: Deque[ShadowDecision] = deque(maxlen=16)
        self._states: Deque[tuple[str, str]] = deque(maxlen=16)
        assert self._decisions.maxlen == SHADOW_MAX_DECISIONS
        assert self._states.maxlen == SHADOW_MAX_OWNER_GENERATIONS * 4
        self._owner_generation = {
            SHADOW_OWNER_LISTENER: 0,
            SHADOW_OWNER_MEDIA: 0,
        }
        self._owner_running = {
            SHADOW_OWNER_LISTENER: False,
            SHADOW_OWNER_MEDIA: False,
        }
        self._last_started_owner: str | None = None
        # Context only. HANDOFF_EPOCH_IS_CALL_IDENTITY=false.
        self._handoff_context_epoch = 0
        self._malformed_batch_count = 0

    def observe_native_line(self, owner: str, line: str) -> None:
        batcher = self._batchers.get(owner)
        if batcher is None:
            return
        self._observe_probe_line_guarded(owner, line)
        batches = batcher.observe(line)
        if line in SHADOW_REMOTE_RELEASE_LINES:
            self._guard.observe_interaction(owner)
        for batch in batches:
            owner_generation = (owner, self._owner_generation.get(owner, 0))
            if batch.malformed:
                self._malformed_batch_count += 1
                self._decisions.append(ShadowDecision(
                    decision=SHADOW_DECISION_SHADOW,
                    reason=SHADOW_REASON_MALFORMED,
                    production_effect=False,
                    owner=owner,
                    generation=owner_generation[1],
                    owner_generation=owner_generation,
                    new_call_proven=False,
                    missing_identity=(batch.door is None or batch.source is None),
                ))
                continue
            if batch.retransmit and batch.identity_source == "none":
                self._decisions.append(ShadowDecision(
                    decision=SHADOW_DECISION_SHADOW,
                    reason=SHADOW_REASON_INCOMPLETE,
                    production_effect=False,
                    owner=owner,
                    generation=owner_generation[1],
                    owner_generation=owner_generation,
                    retransmit=True,
                    new_call_proven=False,
                    missing_identity=True,
                ))
                continue
            decision = self._guard.decide(
                door=batch.door,
                source=batch.source,
                owner=owner,
                owner_generation=owner_generation,
                retransmit=batch.retransmit,
                production_emit_allowed=False,
            )
            self._decisions.append(decision)

    def _observe_probe_line_guarded(self, owner: str, line: str) -> None:
        try:
            self._probe_parser.observe_sha(owner, line)
            self._probe_parser.observe(
                owner,
                line,
                owner_generation=(owner, self._owner_generation.get(owner, 0)),
                handoff_epoch=self._handoff_context_epoch,
            )
        except Exception:
            return

    def note_state(self, owner: str, state: str) -> None:
        self._states.append((owner, state))
        if (
            (owner == SHADOW_OWNER_LISTENER and state == "listener_start")
            or (owner == SHADOW_OWNER_MEDIA and state == "media_transport_start")
        ):
            self._owner_generation[owner] = self._owner_generation.get(owner, 0) + 1
            owner_generation = (owner, self._owner_generation[owner])
            self._owner_running[owner] = True
            other_owner = (
                SHADOW_OWNER_MEDIA
                if owner == SHADOW_OWNER_LISTENER
                else SHADOW_OWNER_LISTENER
            )
            self._owner_running[other_owner] = False
            stale_owners = {
                stale_owner
                for stale_owner in (SHADOW_OWNER_LISTENER, SHADOW_OWNER_MEDIA)
                if not self._owner_running[stale_owner]
            }
            stale_owners.add(owner)
            if self._last_started_owner is None:
                pass
            elif self._last_started_owner == owner:
                self._guard.reset_owner_lifecycle(owner, stale_owners)
            else:
                self._handoff_context_epoch += 1
                self._guard.note_owner_handoff(owner, owner_generation)
            self._last_started_owner = owner
            return
        if state == "supervisor_pause":
            self._owner_running[SHADOW_OWNER_LISTENER] = False
            return
        if (
            (owner == SHADOW_OWNER_LISTENER and state == "listener_stop")
            or (owner == SHADOW_OWNER_MEDIA and state == "media_transport_stop")
            or state == "supervisor_stop"
        ):
            self._owner_running[owner] = False
            return
        if state == "integration_unload":
            self._owner_running[SHADOW_OWNER_LISTENER] = False
            self._owner_running[SHADOW_OWNER_MEDIA] = False
            self._guard = RingEmitGuard()
            self._probe_parser = RingProbeParser()
            self._decisions.clear()
            self._last_started_owner = None
            self._handoff_context_epoch = 0

    def reset(self) -> None:
        self._batchers = {
            SHADOW_OWNER_LISTENER: RingMarkerBatcher(),
            SHADOW_OWNER_MEDIA: RingMarkerBatcher(),
        }
        self._probe_parser = RingProbeParser()
        self._guard = RingEmitGuard()
        self._decisions.clear()
        self._states.clear()
        self._owner_generation = {
            SHADOW_OWNER_LISTENER: 0,
            SHADOW_OWNER_MEDIA: 0,
        }
        self._owner_running = {
            SHADOW_OWNER_LISTENER: False,
            SHADOW_OWNER_MEDIA: False,
        }
        self._last_started_owner = None
        self._handoff_context_epoch = 0
        self._malformed_batch_count = 0

    def note_watchdog_boundary_crossed(self, owner: str) -> None:
        self._guard.note_watchdog_boundary_crossed(owner)

    def _batcher_snapshot(self) -> dict[str, object]:
        return {
            SHADOW_OWNER_LISTENER: self._batchers[SHADOW_OWNER_LISTENER].snapshot(),
            SHADOW_OWNER_MEDIA: self._batchers[SHADOW_OWNER_MEDIA].snapshot(),
        }

    def snapshot_view(self) -> dict[str, object]:
        guard = self._guard.snapshot()
        live_entries = guard["live"]
        batchers = self._batcher_snapshot()
        probe = self._probe_parser.snapshot()
        return {
            "owner_kind": {
                SHADOW_OWNER_LISTENER: SHADOW_OWNER_LISTENER,
                SHADOW_OWNER_MEDIA: SHADOW_OWNER_MEDIA,
            },
            "owner_generation": {
                SHADOW_OWNER_LISTENER: self._owner_generation[SHADOW_OWNER_LISTENER],
                SHADOW_OWNER_MEDIA: self._owner_generation[SHADOW_OWNER_MEDIA],
            },
            "handoff_state": tuple(
                {
                    "owner_kind": live["current_owner_kind"],
                    "owner_generation": live["current_owner_generation"],
                    "previous_owner_kind": live["previous_owner_kind"],
                    "previous_owner_generation": live["previous_owner_generation"],
                    "handoff_epoch": live["handoff_epoch"],
                    "handoff_token": live["handoff_token"],
                }
                for live in live_entries
            ),
            "shadow_classification": tuple(
                {
                    "decision": decision["decision"],
                    "reason": decision["reason"],
                    "owner": decision["owner"],
                    "owner_generation": decision["owner_generation"],
                    "handoff_epoch": decision["handoff_epoch"],
                    "handoff_token": decision["handoff_token"],
                    "retransmit": decision["retransmit"],
                    "production_effect": decision["production_effect"],
                    "new_call_proven": decision["new_call_proven"],
                }
                for decision in tuple(decision.as_dict() for decision in self._decisions)
            ),
            "live_state": {
                "count": len(live_entries),
                "door_kind": tuple(
                    live["door"] if live["door"] in ("entrance", "gate") else "unknown"
                    for live in live_entries
                ),
            },
            "interaction_seen": tuple(
                bool(live["interaction_seen"]) for live in live_entries
            ),
            "batcher_state": {
                SHADOW_OWNER_LISTENER: {
                    "completed_count": len(
                        batchers[SHADOW_OWNER_LISTENER]["completed"]
                    ),
                    "pending": batchers[SHADOW_OWNER_LISTENER]["pending"] is not None,
                    "malformed_count": batchers[SHADOW_OWNER_LISTENER]["malformed_count"],
                    "eviction_count": batchers[SHADOW_OWNER_LISTENER]["eviction_count"],
                },
                SHADOW_OWNER_MEDIA: {
                    "completed_count": len(
                        batchers[SHADOW_OWNER_MEDIA]["completed"]
                    ),
                    "pending": batchers[SHADOW_OWNER_MEDIA]["pending"] is not None,
                    "malformed_count": batchers[SHADOW_OWNER_MEDIA]["malformed_count"],
                    "eviction_count": batchers[SHADOW_OWNER_MEDIA]["eviction_count"],
                },
            },
            "probe_state": {
                "records": tuple(probe["records"]),
                "pending": probe["pending"],
                "malformed_count": probe["malformed_count"],
                "eviction_count": probe["eviction_count"],
                "missing_status_count": probe["missing_status_count"],
                "record_count": probe["record_count"],
                "records_maxlen": SHADOW_MAX_PROBE_RECORDS,
                "owner_generation_is_call_identity": OWNER_GENERATION_IS_CALL_IDENTITY,
                "handoff_epoch_is_call_identity": HANDOFF_EPOCH_IS_CALL_IDENTITY,
                "full_frame_sha_used_as_call_identity": FULL_FRAME_SHA_USED_AS_CALL_IDENTITY,
            },
            "unresolved_reason": tuple(
                decision["reason"]
                for decision in tuple(decision.as_dict() for decision in self._decisions)
                if decision["decision"] == SHADOW_DECISION_OPEN_UNRESOLVED
            ),
            "bounded_counters": {
                "decision_count": len(self._decisions),
                "state_count": len(self._states),
                "malformed_batch_count": self._malformed_batch_count,
                "reset_count": guard["reset_count"],
                "resets_total": guard["resets_total"],
                "probe_record_count": probe["record_count"],
                "probe_malformed_count": probe["malformed_count"],
            },
        }

    def snapshot(self) -> dict[str, object]:
        return {
            "batcher": self._batchers[SHADOW_OWNER_LISTENER].snapshot(),
            "batchers": self._batcher_snapshot(),
            "probe": self._probe_parser.snapshot(),
            "guard": self._guard.snapshot(),
            "decisions": tuple(decision.as_dict() for decision in self._decisions),
            "states": tuple(self._states),
            "owner_generation": {
                SHADOW_OWNER_LISTENER: self._owner_generation[SHADOW_OWNER_LISTENER],
                SHADOW_OWNER_MEDIA: self._owner_generation[SHADOW_OWNER_MEDIA],
            },
            "owner_running": {
                SHADOW_OWNER_LISTENER: self._owner_running[SHADOW_OWNER_LISTENER],
                SHADOW_OWNER_MEDIA: self._owner_running[SHADOW_OWNER_MEDIA],
            },
            "last_started_owner": self._last_started_owner,
            "handoff_context_epoch": self._handoff_context_epoch,
            "malformed_batch_count": self._malformed_batch_count,
        }


class RingShadowHook:
    """The only containment point. Production path never sees exceptions."""

    __slots__ = ("_controller", "_owner", "_failures", "_latched")

    def __init__(self, controller: RingShadowController | None, owner: str) -> None:
        self._controller = controller
        self._owner = owner
        self._failures = 0
        self._latched = controller is None

    def _invoke(self, method: str, *args: str) -> None:
        if self._latched:
            return
        controller = self._controller
        if controller is None:
            self._latched = True
            return
        try:
            getattr(controller, method)(self._owner, *args)
        except Exception:
            self._failures += 1
            if self._failures >= SHADOW_FAILURE_LATCH_LIMIT:
                self._latched = True

    def observe_line(self, line: str | None) -> None:
        if line is None:
            return
        self._invoke("observe_native_line", line)

    def note_state(self, state: str) -> None:
        self._invoke("note_state", state)

    @property
    def latched(self) -> bool:
        return self._latched
