from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Deque

SHADOW_OWNER_LISTENER = "listener"
SHADOW_OWNER_MEDIA = "on_demand_media"

SHADOW_DECISION_EMIT = "EMIT"
SHADOW_DECISION_SUPPRESS = "SUPPRESS"
SHADOW_DECISION_REATTACH = "REATTACH"
SHADOW_DECISION_OPEN_UNRESOLVED = "OPEN_UNRESOLVED"
SHADOW_DECISION_SHADOW = "SHADOW"

SHADOW_REASON_NO_LIVE_CALL = "no_live_call"
SHADOW_REASON_SAME_PROCESS_LISTENER = "same_process_listener_current_main"
SHADOW_REASON_SAME_PROCESS_MEDIA_RETRANSMIT = "same_process_media_retransmit"
SHADOW_REASON_SAME_PROCESS_MEDIA_NOT_ORIGIN = "same_process_media_not_origin"
SHADOW_REASON_SAME_PROCESS_MEDIA_CLOSED_ROUTE = "same_process_media_closed_route"
SHADOW_REASON_LIVE_CALL_REPLAY = "live_call_replay"
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
SHADOW_FAILURE_LATCH_LIMIT = 3

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
    reattach: bool = False
    record: bool = False
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
            "reattach": self.reattach,
            "record": self.record,
            "rearm_watchdog": self.rearm_watchdog,
            "terminal_retry": self.terminal_retry,
            "missing_identity": self.missing_identity,
        }


@dataclass
class _ShadowLive:
    door: str
    source: str
    generations: Deque[int]
    active_event_id: str | None
    origin_owner: str
    origin_generation: int
    interaction_seen: bool
    recording_completed: bool = False
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


def _value_from(markers: tuple[str, ...], wanted: str) -> str | None:
    prefix = wanted + "="
    for marker in markers:
        if marker.startswith(prefix):
            value = marker.split("=", 1)[1].strip()
            if value:
                return value
    return None


class RingMarkerBatcher:
    def __init__(self) -> None:
        self._buffer: Deque[str] = deque(maxlen=SHADOW_MAX_LINES_PER_BATCH)
        self._completed: Deque[RingMarkerBatch] = deque(maxlen=SHADOW_MAX_COMPLETED_BATCHES)
        self._present_mask = 0
        self._sequence = 0
        self._generation = 0
        self._malformed = False
        self._retransmit = False
        self._frame_sha_present = False
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

    def _reset_current(self) -> None:
        self._buffer.clear()
        self._present_mask = 0
        self._malformed = False
        self._retransmit = False
        self._frame_sha_present = False
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
        if previous is None:
            self._generation += 1
            generation = self._generation
            door = None
            source = None
            identity_source = "none"
        else:
            generation = previous.generation
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

    def observe(self, line: str) -> tuple[RingMarkerBatch, ...]:
        if "=" not in line:
            self._no_separator_count += 1
            return ()
        key, value = line.split("=", 1)
        value = value.strip()

        if key == "V4_RING_OBSERVED":
            if value == "true":
                self._reset_current()
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
                self._frame_sha_present = True
            else:
                self._retransmit_sha_present = True
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


class RingEmitGuard:
    def __init__(self) -> None:
        self._live: Deque[_ShadowLive] = deque(maxlen=SHADOW_MAX_LIVE_KEYS)
        self._decisions: Deque[ShadowDecision] = deque(maxlen=SHADOW_MAX_DECISIONS)

    def _find_live(self, door: str, source: str) -> _ShadowLive | None:
        for live in self._live:
            if live.door == door and live.source == source:
                return live
        return None

    def _remember_decision(self, decision: ShadowDecision) -> ShadowDecision:
        self._decisions.append(decision)
        return decision

    def _make_decision(
        self,
        decision: str,
        reason: str,
        owner: str,
        generation: int,
        *,
        reattach: bool = False,
        record: bool = False,
        rearm_watchdog: bool = False,
        missing_identity: bool = False,
    ) -> ShadowDecision:
        return self._remember_decision(ShadowDecision(
            decision=decision,
            reason=reason,
            production_effect=False,
            owner=owner,
            generation=generation,
            reattach=reattach,
            record=record,
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
        generation: int,
        route: str = "listener",
        stage: str = "pr1a_shadow",
        interaction_seen: bool = False,
        watchdog_expired_without_lifecycle_evidence: bool = False,
        has_new_physical_call_discriminator: bool = False,
        production_emit_allowed: bool = False,
    ) -> ShadowDecision:
        if door is None or source is None:
            return self._make_decision(
                SHADOW_DECISION_SHADOW,
                SHADOW_REASON_INCOMPLETE,
                owner,
                generation,
                missing_identity=True,
            )

        live = self._find_live(door, source)
        if live is None:
            generations: Deque[int] = deque(maxlen=SHADOW_MAX_GENERATIONS)
            generations.append(generation)
            self._live.append(_ShadowLive(
                door=door,
                source=source,
                generations=generations,
                active_event_id=None,
                origin_owner=owner,
                origin_generation=generation,
                interaction_seen=interaction_seen,
            ))
            decision = SHADOW_DECISION_EMIT if production_emit_allowed else SHADOW_DECISION_SHADOW
            return self._make_decision(decision, SHADOW_REASON_NO_LIVE_CALL, owner, generation)

        if interaction_seen:
            live.interaction_seen = True

        for known_generation in live.generations:
            if known_generation != generation:
                continue
            if owner == SHADOW_OWNER_LISTENER:
                decision = SHADOW_DECISION_EMIT if production_emit_allowed else SHADOW_DECISION_SHADOW
                return self._make_decision(
                    decision,
                    SHADOW_REASON_SAME_PROCESS_LISTENER,
                    owner,
                    generation,
                )
            if owner == SHADOW_OWNER_MEDIA:
                if (
                    live.origin_owner == SHADOW_OWNER_MEDIA
                    and live.origin_generation == generation
                    and not has_new_physical_call_discriminator
                ):
                    return self._make_decision(
                        SHADOW_DECISION_SUPPRESS,
                        SHADOW_REASON_SAME_PROCESS_MEDIA_RETRANSMIT,
                        owner,
                        generation,
                    )
                return self._make_decision(
                    SHADOW_DECISION_SHADOW,
                    SHADOW_REASON_SAME_PROCESS_MEDIA_NOT_ORIGIN,
                    owner,
                    generation,
                )

        live.generations.append(generation)
        if live.interaction_seen:
            return self._make_decision(
                SHADOW_DECISION_OPEN_UNRESOLVED,
                SHADOW_REASON_HIGH_A2,
                owner,
                generation,
            )
        if watchdog_expired_without_lifecycle_evidence:
            return self._make_decision(
                SHADOW_DECISION_OPEN_UNRESOLVED,
                SHADOW_REASON_HIGH_3,
                owner,
                generation,
            )
        return self._make_decision(
            SHADOW_DECISION_SUPPRESS,
            SHADOW_REASON_LIVE_CALL_REPLAY,
            owner,
            generation,
            reattach=True,
            record=True,
            rearm_watchdog=True,
        )

    def snapshot(self) -> dict[str, object]:
        return {
            "live": tuple(
                {
                    "door": live.door,
                    "source": live.source,
                    "generations": tuple(live.generations),
                    "active_event_id": live.active_event_id,
                    "origin_owner": live.origin_owner,
                    "origin_generation": live.origin_generation,
                    "interaction_seen": live.interaction_seen,
                    "recording_completed": live.recording_completed,
                    "reattached": live.reattached,
                }
                for live in self._live
            ),
            "decisions": tuple(decision.as_dict() for decision in self._decisions),
        }


class RingShadowController:
    """Config-entry-level shadow state. Pure sync. Never awaits, never does I/O."""

    def __init__(self) -> None:
        self._batcher = RingMarkerBatcher()
        self._guard = RingEmitGuard()
        self._decisions: Deque[ShadowDecision] = deque(maxlen=SHADOW_MAX_DECISIONS)
        self._states: Deque[tuple[str, str]] = deque(maxlen=SHADOW_MAX_DECISIONS)
        self._interaction_seen = False
        self._malformed_batch_count = 0

    def observe_native_line(self, owner: str, line: str) -> None:
        batches = self._batcher.observe(line)
        if line in SHADOW_REMOTE_RELEASE_LINES:
            self._interaction_seen = True
        for batch in batches:
            if batch.malformed:
                self._malformed_batch_count += 1
                self._decisions.append(ShadowDecision(
                    decision=SHADOW_DECISION_SHADOW,
                    reason=SHADOW_REASON_MALFORMED,
                    production_effect=False,
                    owner=owner,
                    generation=batch.generation,
                    missing_identity=(batch.door is None or batch.source is None),
                ))
                continue
            if batch.retransmit and batch.identity_source == "none":
                self._decisions.append(ShadowDecision(
                    decision=SHADOW_DECISION_SHADOW,
                    reason=SHADOW_REASON_INCOMPLETE,
                    production_effect=False,
                    owner=owner,
                    generation=batch.generation,
                    missing_identity=True,
                ))
                continue
            decision = self._guard.decide(
                door=batch.door,
                source=batch.source,
                owner=owner,
                generation=batch.generation,
                production_emit_allowed=False,
                interaction_seen=self._interaction_seen,
            )
            self._decisions.append(decision)

    def note_state(self, owner: str, state: str) -> None:
        self._states.append((owner, state))

    def reset(self) -> None:
        self._batcher = RingMarkerBatcher()
        self._guard = RingEmitGuard()
        self._decisions.clear()
        self._states.clear()
        self._interaction_seen = False
        self._malformed_batch_count = 0

    def snapshot(self) -> dict[str, object]:
        return {
            "batcher": self._batcher.snapshot(),
            "guard": self._guard.snapshot(),
            "decisions": tuple(decision.as_dict() for decision in self._decisions),
            "states": tuple(self._states),
            "interaction_seen": self._interaction_seen,
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
