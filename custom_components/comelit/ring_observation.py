"""Streaming reader for the native, retransmission-suppressed Ring observation.

The native helper prints the five-key observation only after
``v4_ring_is_retransmit()`` accepted the frame: the same body SHA256 inside the
helper's sliding 15-second window is suppressed and printed as a probe only.
The window is refreshed while the retransmission train continues, so the
guarantee is "one observation per frame within that window", **not** "one per
physical call".  Cross-owner repetition is handled by the runtime publication
latch, not here.

The probe lines (``V4_RING_PHASE``, ``V4_RING_PEER_CONNECTION``, ...) are
printed for every attempt and therefore must never be used as a call signal.

This module only re-assembles that already-suppressed observation so the media
owner can publish the same event the listener publishes.  It introduces no
identity of its own.
"""

from __future__ import annotations

from .ring_event import RingEvent, RingObservationError, parse_v4_safe_ring

_OBSERVED_KEY = "V4_RING_OBSERVED"
_FRAME_SHA_KEY = "V4_RING_FRAME_SHA256"
_FRAME_SHA_RE = __import__("re").compile(r"^[0-9a-f]{64}$")
_BATCH_KEYS = (
    "V4_RING_OBSERVED",
    "V4_RING_DIRECTION",
    "V4_RING_KIND",
    "V4_RING_DOOR",
    "V4_RING_SOURCE",
)
_MAX_BATCH_LINES = 16


class RingObservationBuffer:
    """Re-assemble one native observation batch from the raw stdout stream."""

    def __init__(self) -> None:
        self._lines: list[str] = []
        self.frame_sha256: str | None = None

    def take_frame_sha(self) -> str | None:
        """Return the digest of the batch just emitted and forget it."""
        digest = self.frame_sha256
        self.frame_sha256 = None
        return digest

    def reset(self) -> None:
        self._lines.clear()
        self.frame_sha256 = None

    def feed(self, line: str) -> RingEvent | None:
        """Consume one raw line; return the event when a batch completes."""
        line = line.strip()
        if "=" not in line:
            return None
        key, _sep, raw_value = line.partition("=")
        if key == _FRAME_SHA_KEY:
            if _FRAME_SHA_RE.fullmatch(raw_value):
                self.frame_sha256 = raw_value
            return None
        if key == _OBSERVED_KEY:
            # A new observation always starts a new batch.  ``false`` is the
            # native listener timeout marker and never produces an event.
            self._lines = [line]
            if raw_value != "true":
                self._lines = []
                return None
            return None
        if key not in _BATCH_KEYS or not self._lines:
            return None
        self._lines.append(line)
        if len(self._lines) > _MAX_BATCH_LINES:
            self._lines = []
            return None
        if not all(
            any(item.startswith(f"{wanted}=") for item in self._lines)
            for wanted in _BATCH_KEYS
        ):
            return None
        batch, self._lines = self._lines, []
        try:
            return parse_v4_safe_ring(batch)
        except RingObservationError:
            return None
