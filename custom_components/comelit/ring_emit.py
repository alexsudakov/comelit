from __future__ import annotations

from collections import deque
from collections.abc import Sequence
from datetime import UTC, datetime
import logging
import re
from threading import Lock
from uuid import uuid4

from homeassistant.core import HomeAssistant

from . import const as _const
from .ring_event import RingObservationError, parse_v4_safe_ring

# Same event name as const.EVENT_RING; resolved defensively so the
# safety-poc transport harness (which injects a minimal const stub) can
# still import this module.
EVENT_RING = getattr(_const, "EVENT_RING", "comelit_ring")

_LOGGER = logging.getLogger(__name__)

_FRAME_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_FRAME_SHA256_KEY = "V4_RING_FRAME_SHA256"
# A session (600 s hard limit) carries a handful of distinct ring frames; the
# registry is bounded so an unexpected marker stream cannot grow it without
# limit. A frame content token that is evicted can be published again.
_DEFAULT_MAX_TOKENS = 256


class RingEmitDedup:
    """Remember published frame content tokens for one media transport."""

    def __init__(self, max_tokens: int = _DEFAULT_MAX_TOKENS) -> None:
        if max_tokens < 1:
            raise ValueError("max_tokens must be positive")
        self._max_tokens = max_tokens
        self._published: deque[str] = deque()
        self._published_set: set[str] = set()
        self._lock = Lock()

    def claim(self, frame_sha256: str) -> bool:
        """Claim a frame content token, returning true only to its first claimant."""
        with self._lock:
            if frame_sha256 in self._published_set:
                return False
            while len(self._published) >= self._max_tokens:
                evicted = self._published.popleft()
                self._published_set.discard(evicted)
            self._published.append(frame_sha256)
            self._published_set.add(frame_sha256)
            return True

    def reset(self) -> None:
        """Clear all remembered frame content tokens."""
        with self._lock:
            self._published.clear()
            self._published_set.clear()


class RingMarkerBatcher:
    """Assemble one bounded V4 ring marker batch from native stdout lines.

    The native helper prints ``V4_RING_FRAME_SHA256`` before the observation
    markers of a new frame and never prints observation markers for a
    suppressed retransmission, so a batch completes once every observation
    key has been seen. Anything else is dropped without side effects.
    """

    OBSERVATION_KEYS = frozenset(
        {
            "V4_RING_OBSERVED",
            "V4_RING_DIRECTION",
            "V4_RING_KIND",
            "V4_RING_DOOR",
            "V4_RING_SOURCE",
        }
    )
    LINE_LIMIT = 16

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._lines: list[str] = []
        self._keys: set[str] = set()

    def feed(self, line: str | None) -> tuple[str, ...] | None:
        """Feed one line and return a completed batch, if any."""
        if line is None or not line.startswith("V4_RING_"):
            return None
        key = line.partition("=")[0]
        if key == "V4_RING_OBSERVED":
            # Every observation starts a new batch. The native helper prints
            # V4_RING_FRAME_SHA256, then the R68 probe markers, and only then
            # the observation markers, so keep the most recent frame token
            # anywhere in the buffer and drop everything older.
            tokens = [
                marker
                for marker in self._lines
                if marker.startswith(_FRAME_SHA256_KEY + "=")
            ]
            self._lines = tokens[-1:]
            self._keys.clear()
        self._lines.append(line)
        if len(self._lines) > self.LINE_LIMIT:
            self._lines.pop(0)
        if key in self.OBSERVATION_KEYS:
            self._keys.add(key)
        if not self.OBSERVATION_KEYS.issubset(self._keys):
            return None
        batch = tuple(self._lines)
        self.reset()
        return batch


class MediaRingEmitter:
    """Publish normalized ring events observed by the on-demand media owner.

    One event is published per distinct frame content token for as long as that
    token stays in the bounded per-session registry. This is not a logical call
    identity: a frame re-observed after eviction, or by another owner, can be
    published again.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        dedup: RingEmitDedup | None = None,
    ) -> None:
        self._hass = hass
        self._dedup = dedup if dedup is not None else RingEmitDedup()

    def reset(self) -> None:
        """Start a new media session with no remembered frame tokens."""
        self._dedup.reset()

    @staticmethod
    def _suppress(reason: str) -> None:
        if reason == "duplicate_frame":
            # Retransmission of an already published frame is expected noise.
            _LOGGER.debug("OWNER_RING_EMIT_SUPPRESSED=%s", reason)
            return
        _LOGGER.warning("OWNER_RING_EMIT_SUPPRESSED=%s", reason)

    @staticmethod
    def _frame_sha256(lines: Sequence[str]) -> tuple[str | None, bool]:
        values: set[str] = set()
        for raw in lines:
            line = raw.strip()
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            if key == _FRAME_SHA256_KEY:
                values.add(value.strip())
        if len(values) > 1:
            return None, True
        return (next(iter(values)) if values else None), False

    def emit_from_markers(self, lines: Sequence[str]) -> dict[str, object] | None:
        """Publish one event per distinct frame content token in the registry."""
        try:
            ring = parse_v4_safe_ring(lines)
        except RingObservationError:
            self._suppress("parse_error")
            return None

        if ring is None:
            # A batch without a ring observation is not an error.
            return None

        frame_sha256, conflicting_sha = self._frame_sha256(lines)
        if conflicting_sha:
            self._suppress("parse_error")
            return None
        if frame_sha256 is None or _FRAME_SHA256_RE.fullmatch(frame_sha256) is None:
            self._suppress("identity_incomplete")
            return None
        if not self._dedup.claim(frame_sha256):
            self._suppress("duplicate_frame")
            return None

        payload: dict[str, object] = {
            **ring.as_dict(),
            "event_id": str(uuid4()),
            "timestamp": datetime.now(UTC).isoformat(),
            "owner": "on_demand_media",
        }
        self._hass.bus.async_fire(EVENT_RING, payload)
        return payload
