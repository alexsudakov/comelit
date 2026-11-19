"""Streaming reader for the native, retransmission-suppressed Ring observation.

The native helper prints one five-key observation per physical call, and it
prints it *after* ``v4_ring_is_retransmit()`` has dropped every retransmission
of the same frame (same SHA256 inside the helper's dedup window).  The probe
lines (``V4_RING_PHASE``, ``V4_RING_PEER_CONNECTION``, ...) are printed for
every attempt and therefore must never be used as a call signal.

This module only re-assembles that already-suppressed observation so the media
owner can publish the same event the listener publishes.  It introduces no
identity, no time window and no frame-hash comparison of its own.
"""

from __future__ import annotations

from .ring_event import RingEvent, RingObservationError, parse_v4_safe_ring

_OBSERVED_KEY = "V4_RING_OBSERVED"
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

    def reset(self) -> None:
        self._lines.clear()

    def feed(self, line: str) -> RingEvent | None:
        """Consume one raw line; return the event when a batch completes."""
        line = line.strip()
        if "=" not in line:
            return None
        key = line.split("=", 1)[0]
        if key == _OBSERVED_KEY:
            # A new observation always starts a new batch.  ``false`` is the
            # native listener timeout marker and never produces an event.
            self._lines = [line]
            if line.split("=", 1)[1] != "true":
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
