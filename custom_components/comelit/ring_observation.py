"""Reader for the native Ring observation printed on the media owner's stdout.

The native helper prints probe lines (``V4_RING_PHASE``, ``PEER_CONNECTION``,
``BODY_32_35``, ``PARSE_STATUS``) for every attempt of a call, and prints the
five-key observation only after its retransmission filter accepted the frame.

This module only re-assembles that observation.  It adds no identity, no
timestamp and no deduplication of its own: whatever the helper suppressed is
not seen here, and whatever it printed is passed through once.
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
    """Turn the media owner's raw stdout into at most one event per batch."""

    def __init__(self) -> None:
        self._lines: list[str] = []

    def reset(self) -> None:
        self._lines.clear()

    def feed(self, line: str) -> RingEvent | None:
        """Consume one raw line; return the event when a batch completes."""
        line = line.strip()
        if "=" not in line:
            return None
        key, _sep, value = line.partition("=")
        if key == _OBSERVED_KEY:
            # A new observation always starts a new batch; ``false`` is the
            # listener timeout marker and never produces an event.
            self._lines = [line] if value == "true" else []
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
