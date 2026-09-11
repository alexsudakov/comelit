from __future__ import annotations

from collections.abc import Callable
import re
import time

_PROGRESS_MARKER_RE = re.compile(
    r"^P80_(VIDEO|AUDIO)_RTP_PACKETS=([0-9]{1,10})$"
)


class MediaProgressDiagnostics:
    """Track bounded native RTP progress markers using a monotonic clock."""

    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self.reset()

    def reset(self) -> None:
        """Reset diagnostics for a new upstream media cycle."""
        self._video_packet_count = 0
        self._audio_packet_count = 0
        self._last_video_progress_monotonic: float | None = None
        self._last_audio_progress_monotonic: float | None = None

    @property
    def video_packet_count(self) -> int:
        return self._video_packet_count

    @property
    def audio_packet_count(self) -> int:
        return self._audio_packet_count

    @property
    def last_video_progress_monotonic(self) -> float | None:
        return self._last_video_progress_monotonic

    @property
    def last_audio_progress_monotonic(self) -> float | None:
        return self._last_audio_progress_monotonic

    @property
    def video_last_packet_age_seconds(self) -> float | None:
        return self._age(self._last_video_progress_monotonic)

    @property
    def audio_last_packet_age_seconds(self) -> float | None:
        return self._age(self._last_audio_progress_monotonic)

    def _age(self, last_progress: float | None) -> float | None:
        if last_progress is None:
            return None
        return max(0.0, self._clock() - last_progress)

    def update_marker(self, line: str) -> bool:
        """Apply one exact safe progress marker if it advances a counter."""
        match = _PROGRESS_MARKER_RE.fullmatch(line)
        if match is None:
            return False

        media_kind, raw_count = match.groups()
        count = int(raw_count)
        now = self._clock()

        if media_kind == "VIDEO":
            if count <= self._video_packet_count:
                return False
            self._video_packet_count = count
            self._last_video_progress_monotonic = now
            return True

        if count <= self._audio_packet_count:
            return False
        self._audio_packet_count = count
        self._last_audio_progress_monotonic = now
        return True
