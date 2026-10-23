"""Bounded, read-only evidence for Issue #319 Ring/video episodes.

This module is deliberately a sink.  Production lifecycle code may append
facts, but must never consult this ledger when deciding whether to emit a Ring,
write to the protocol, stop media, or resume the listener.

Generation model
----------------
Every Ring episode is opened with an explicit owner generation and receives an
internal, monotonically increasing episode id.  Facts are accepted only while
that episode is open and only when the caller's generation matches.  Anything
else is counted as ``unattributed`` instead of mutating a newer episode.  An
episode is sealed deterministically on listener resume (or replacement), after
which late facts are rejected.
"""

from __future__ import annotations

from collections import deque
import re
import time
from typing import Callable, Deque

RING_EPISODE_MAX_EPISODES = 8
RING_EPISODE_MAX_EVENTS = 32
RING_EPISODE_MAX_SEALED_EVENTS = 16

_ACK_VALUES = frozenset({"STRUCTURAL_ACK", "AMBIGUOUS", "ABSENT"})
_ACK_CLASSIFICATION_VALUES = frozenset(
    {"STATE_SCOPED_STRUCTURAL", "STRUCTURAL_ACK", "AMBIGUOUS", "ABSENT"}
)
_SAFE_REASON_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,63}$")
_UINT_RE = re.compile(r"^[0-9]{1,20}$")
_SEAL_REASONS = frozenset(
    {"listener_resumed", "resume_failed", "replaced", "reset", "native_exit_terminal"}
)


class RingEpisodeLedger:
    """Retain bounded scalar evidence without affecting production behavior."""

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        max_episodes: int = RING_EPISODE_MAX_EPISODES,
        max_events: int = RING_EPISODE_MAX_EVENTS,
    ) -> None:
        if max_episodes <= 0 or max_events <= 0:
            raise ValueError("ring episode caps must be positive")
        self._clock = clock
        self._max_episodes = max_episodes
        self._max_events = max_events
        self._episodes: Deque[dict[str, object]] = deque()
        self._events: Deque[dict[str, object]] = deque()
        self._episode_events: list[dict[str, object]] = []
        self._episode_events_id: object = None
        self._latest_sealed_events: tuple[dict[str, object], ...] = ()
        self._sequence = 0
        self._next_episode_id = 1
        self._started_monotonic: float | None = None
        self._episodes_seen_total = 0
        self._episodes_evicted = 0
        self._events_seen_total = 0
        self._events_evicted = 0
        self._dropped_invalid = 0
        self._unattributed = 0
        self._active: dict[str, object] | None = None

    # -- internal helpers -------------------------------------------------
    def _offset_ms(self) -> int:
        now = self._clock()
        if self._started_monotonic is None:
            self._started_monotonic = now
        return max(0, int((now - self._started_monotonic) * 1000))

    def _event(
        self,
        kind: str,
        value: object,
        episode: dict[str, object] | None = None,
    ) -> None:
        if episode is None:
            episode = self._current()
        self._events_seen_total += 1
        if len(self._events) >= self._max_events:
            self._events.popleft()
            self._events_evicted += 1
        event = {
            "seq": self._sequence,
            "kind": kind,
            "value": value,
            "offset_ms": self._offset_ms(),
            "episode_id": (
                episode.get("episode_id")
                if isinstance(episode, dict)
                else None
            ),
        }
        self._events.append(event)
        if event["episode_id"] == self._episode_events_id:
            self._episode_events.append(event)
            same_kind = [
                index
                for index, item in enumerate(self._episode_events)
                if item["kind"] == kind
            ]
            if len(same_kind) > 2:
                self._episode_events.pop(same_kind[1])
            # Preserve at least one event of every observed kind while keeping
            # the protected sealed readback within its strict count budget.
            # Repeated observations retain their first and latest samples; in
            # practice this coalesces high-frequency RTP progress without
            # losing Ring/001A ordering.
            while len(self._episode_events) > RING_EPISODE_MAX_SEALED_EVENTS:
                kinds = [item["kind"] for item in self._episode_events]
                duplicate = next(
                    (
                        index
                        for index, item in enumerate(self._episode_events)
                        if item["kind"] in kinds[index + 1 :]
                    ),
                    None,
                )
                if duplicate is None:
                    self._episode_events.pop(0)
                else:
                    self._episode_events.pop(duplicate)
        self._sequence += 1

    def _current(self) -> dict[str, object] | None:
        active = self._active
        if active is None or active.get("sealed"):
            return None
        return active

    def _matching(self, generation: int | None) -> dict[str, object] | None:
        """Return the open episode only if the caller's generation matches."""
        if type(generation) is not int or generation < 0:
            self._unattributed += 1
            return None
        episode = self._current()
        if episode is None or episode.get("generation") != generation:
            self._unattributed += 1
            return None
        return episode

    def _record(self, key: str, value: object) -> None:
        episode = self._current()
        if episode is None:
            self._unattributed += 1
            return
        episode[key] = value

    # -- lifecycle --------------------------------------------------------
    def note_media_start(self, generation: int) -> None:
        """Open a new generation-scoped episode; seal any still-open one."""
        if type(generation) is not int or generation < 0:
            self._dropped_invalid += 1
            return
        previous = self._current()
        if previous is not None:
            self._seal(previous, "replaced")
        episode: dict[str, object] = {
            "episode_id": self._next_episode_id,
            "generation": generation,
            "opened_offset_ms": self._offset_ms(),
            "sealed_offset_ms": None,
            "seal_reason": None,
            "ring_observed_offset_ms": None,
            "second_001a_response": None,
            "ack_classification": None,
            "refresh_fail_closed": None,
            "last_video_rtp_packets": None,
            "video_progress_after_ring": False,
            "native_exit_code": None,
            "stop_reason": None,
            "teardown_confirmed": None,
            "listener_resumed": None,
            "sealed": False,
        }
        self._next_episode_id += 1
        self._episodes_seen_total += 1
        if len(self._episodes) >= self._max_episodes:
            self._episodes.popleft()
            self._episodes_evicted += 1
        self._episodes.append(episode)
        self._active = episode
        self._episode_events = []
        self._episode_events_id = episode["episode_id"]
        self._event("MEDIA_START", generation, episode)

    def _seal(self, episode: dict[str, object], reason: str) -> None:
        if episode.get("sealed"):
            return
        if reason not in _SEAL_REASONS:
            reason = "reset"
        episode["sealed"] = True
        episode["sealed_offset_ms"] = self._offset_ms()
        episode["seal_reason"] = reason
        if self._active is episode:
            self._active = None
        self._event("SEAL", reason, episode)
        if episode.get("episode_id") == self._episode_events_id:
            self._latest_sealed_events = tuple(
                dict(event) for event in self._episode_events
            )

    def seal_episode(self, reason: str = "reset") -> None:
        active = self._current()
        if active is not None:
            self._seal(active, reason)

    def observe_native_line(self, line: object, generation: int | None = None) -> None:
        """Accept only an allowlist of scalar native markers; payloads are dropped."""
        if not isinstance(line, str) or len(line) > 160:
            self._dropped_invalid += 1
            return
        episode = self._matching(generation)
        if episode is None:
            return
        if line == "V4_RING_KIND=CALL_INIT":
            if episode["ring_observed_offset_ms"] is None:
                episode["ring_observed_offset_ms"] = self._offset_ms()
            self._event("CALL_INIT", True)
            return
        key, separator, value = line.partition("=")
        if not separator:
            return
        if key in {
            "SECOND_001A_RESPONSE",
            "ACK_CLASSIFICATION",
            "SECOND_001A_ACK_CLASSIFICATION",
        }:
            if key == "SECOND_001A_RESPONSE":
                if value not in _ACK_VALUES:
                    self._dropped_invalid += 1
                    return
                field = key.lower()
            else:
                if value not in _ACK_CLASSIFICATION_VALUES:
                    self._dropped_invalid += 1
                    return
                field = "ack_classification"
            episode[field] = value
            self._event(key, value)
            return
        if key == "REFRESH_FAIL_CLOSED" and value in {"true", "false"}:
            parsed = value == "true"
            episode["refresh_fail_closed"] = parsed
            self._event(key, parsed)
            return
        if key == "P80_VIDEO_RTP_PACKETS" and _UINT_RE.fullmatch(value):
            count = int(value)
            previous_raw = episode["last_video_rtp_packets"]
            previous = previous_raw if isinstance(previous_raw, int) else None
            if previous is None or count >= previous:
                episode["last_video_rtp_packets"] = count
                if (
                    episode["ring_observed_offset_ms"] is not None
                    and previous is not None
                    and count > previous
                ):
                    episode["video_progress_after_ring"] = True
                self._event(key, count)
            return

    def note_native_exit(self, returncode: object, generation: int | None = None) -> None:
        episode = self._matching(generation)
        if episode is None:
            return
        if type(returncode) is not int or not -(2**31) <= returncode < 2**31:
            self._dropped_invalid += 1
            return
        episode["native_exit_code"] = returncode
        self._event("NATIVE_EXIT", returncode)

    def note_stop_reason(self, reason: object, generation: int | None = None) -> None:
        episode = self._matching(generation)
        if episode is None:
            return
        if not isinstance(reason, str) or not _SAFE_REASON_RE.fullmatch(reason):
            self._dropped_invalid += 1
            return
        episode["stop_reason"] = reason
        self._event("STOP_REASON", reason)

    def note_teardown(self, confirmed: object, generation: int | None = None) -> None:
        episode = self._matching(generation)
        if episode is None:
            return
        if type(confirmed) is not bool:
            self._dropped_invalid += 1
            return
        episode["teardown_confirmed"] = confirmed
        self._event("TEARDOWN", confirmed)

    def note_listener_resume(
        self, resumed: object, generation: int | None = None
    ) -> None:
        episode = self._matching(generation)
        if episode is None:
            return
        if type(resumed) is not bool:
            self._dropped_invalid += 1
            return
        episode["listener_resumed"] = resumed
        self._event("LISTENER_RESUME", resumed)
        self._seal(episode, "listener_resumed" if resumed else "resume_failed")

    def reset(self) -> None:
        """Seal the open episode and clear all bounded state symmetrically."""
        self.seal_episode("reset")
        self._episodes.clear()
        self._events.clear()
        self._episode_events.clear()
        self._episode_events_id = None
        self._latest_sealed_events = ()
        self._sequence = 0
        self._next_episode_id = 1
        self._started_monotonic = None
        self._episodes_seen_total = 0
        self._episodes_evicted = 0
        self._events_seen_total = 0
        self._events_evicted = 0
        self._dropped_invalid = 0
        self._unattributed = 0
        self._active = None

    def snapshot(self) -> dict[str, object]:
        active = self._current()
        accounting = {
            "episodes_seen_total": self._episodes_seen_total,
            "episodes_evicted": self._episodes_evicted,
            "events_seen_total": self._events_seen_total,
            "events_evicted": self._events_evicted,
            "dropped_invalid": self._dropped_invalid,
            "unattributed": self._unattributed,
        }
        return {
            "episodes": tuple(dict(episode) for episode in self._episodes),
            "events": tuple(dict(event) for event in self._events),
            "latest_sealed_events": tuple(
                dict(event) for event in self._latest_sealed_events
            ),
            "active_episode_id": None if active is None else active["episode_id"],
            "active_generation": None if active is None else active["generation"],
            "accounting": accounting,
            **accounting,
            "production_effect": False,
            "protocol_write_performed": False,
            "call_identity_claimed": False,
        }
