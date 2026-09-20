from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
import re
import time

_PROGRESS_MARKER_RE = re.compile(
    r"^P80_(VIDEO|AUDIO)_RTP_PACKETS=([0-9]{1,20})$"
)
_GUINT64_MAX = (1 << 64) - 1

# Bounded scalar markers for the R42-b attached-media canary. Deliberately a
# narrower, dedicated key/value contract from runtime.py's native marker tail
# regex: reusing that shared regex/prefix set here would also pull every
# P80_/P116_ RTP telemetry line into runtime.py's failure-diagnostic tail
# (bounded to its own last-20 window) and crowd out Door/ring evidence there.
_MEDIA_DIAGNOSTIC_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]{2,63}$")
_MEDIA_DIAGNOSTIC_VALUE_RE = re.compile(r"^(?:true|false|PASS|FAIL|[0-9]{1,20})$")
_MEDIA_DIAGNOSTIC_PREFIXES = ("R42_", "P80_", "P116_")
_H264_EVIDENCE_KEYS = (
    "P116_VIDEO_SPS_COUNT",
    "P116_VIDEO_PPS_COUNT",
    "P116_VIDEO_SINGLE_NAL_COUNT",
    "P116_VIDEO_FUA_COUNT",
)
# P116_VIDEO_PT_SET is printed by p116_print_pt_set() as either the literal
# "NONE" or a comma-joined list of every payload type observed so far
# (e.g. "8,99"). Only a lone 1-3 digit value is a single unambiguous runtime
# payload type; RTP PT is a 7-bit field (0-127), enforced separately.
_VIDEO_PT_SET_SINGLE_RE = re.compile(r"^[0-9]{1,3}$")

CHANNEL_SOURCE_RUNTIME_CALL_BOUND = "RUNTIME_CALL_BOUND"

MEDIA_DIAGNOSTICS_FIELDS = (
    "call_generation",
    "media_channel",
    "channel_source",
    "mediareq26_open_sent",
    "mediareq26_open_channel",
    "rtp_received",
    "rtp_packet_count",
    "rtp_payload_type",
    "h264_detected",
    "video_width",
    "video_height",
    "first_rtp_at",
    "stop_sent",
    "stop_channel",
    "channel_closed",
    "cleanup_complete",
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
        if count > _GUINT64_MAX:
            return False
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


class MediaCallDiagnostics:
    """Bounded, call-generation-scoped R42-b attached-media canary evidence.

    Every field is armed/reset whenever a strictly newer
    ``R42_CALL_GENERATION`` marker is observed (or the caller forces a reset,
    e.g. on listener process restart), so a prior call's evidence can never
    read as belonging to the current call. Values are populated only from
    already-proven native markers (``R42_*`` channel-lifecycle markers,
    ``P80_VIDEO_RTP_*`` forwarding progress, ``P116_VIDEO_*`` RTP telemetry);
    nothing here invents a literal or performs new native control flow.
    ``rtp_payload_type`` is parsed from the native ``P116_VIDEO_PT_SET``
    marker only (never a historical/capture-profile constant); ``first_rtp_at``
    is the wall-clock time this integration *observed* the first RTP marker,
    not a value produced by the native runtime, and must never be confused
    with the native monotonic-ms clock used elsewhere on the wire.
    """

    def __init__(self, *, clock: Callable[[], str] | None = None) -> None:
        # `clock` returns the observation-time timestamp for `first_rtp_at`;
        # it is deliberately wall-clock (ISO 8601), not the native runtime's
        # monotonic-ms clock, since it records when the integration saw the
        # marker rather than a value the native process itself produced.
        self._now = clock or (lambda: datetime.now(UTC).isoformat())
        self.reset()

    def reset(self) -> None:
        """Discard all evidence. Used on listener (re)start, not per-call."""
        self._call_generation: int | None = None
        self._media_channel: int | None = None
        self._mediareq26_open_sent = False
        self._mediareq26_open_channel: int | None = None
        self._rtp_received = False
        self._rtp_packet_count: int | None = None
        self._rtp_payload_type: int | None = None
        self._h264_detected = False
        self._first_rtp_at: str | None = None
        self._stop_sent = False
        self._stop_channel: int | None = None
        self._channel_closed = False
        self._rtp_disarmed = False

    def _arm_for_generation(self, generation: int) -> None:
        # A strictly newer generation always starts a fresh call; a
        # same-or-older generation is either the current call re-announcing
        # itself or stale replay and must never wipe live evidence.
        if self._call_generation is None or generation > self._call_generation:
            self.reset()
            self._call_generation = generation

    def observe_line(self, line: str) -> bool:
        """Apply one native stdout line if it is a recognized bounded marker."""
        if "=" not in line:
            return False
        key, raw_value = line.split("=", 1)
        if not _MEDIA_DIAGNOSTIC_KEY_RE.fullmatch(key):
            return False
        if not key.startswith(_MEDIA_DIAGNOSTIC_PREFIXES):
            return False

        if key == "R42_CALL_GENERATION":
            if not _MEDIA_DIAGNOSTIC_VALUE_RE.fullmatch(raw_value):
                return True
            try:
                generation = int(raw_value)
            except ValueError:
                return True
            self._arm_for_generation(generation)
            return True

        if key not in _RECOGNIZED_MEDIA_DIAGNOSTIC_KEYS:
            return False

        # Every other recognized key is meaningless without a bound call
        # generation: fail closed rather than attribute orphan evidence.
        if self._call_generation is None:
            return True

        # P116_VIDEO_PT_SET has its own value shape (a comma-joined bitmask
        # dump, or the literal NONE) that the generic true/false/PASS/FAIL/
        # digits gate below does not model, so it is parsed on its own terms
        # rather than through the shared safe_value gate.
        if key == "P116_VIDEO_PT_SET":
            self._rtp_payload_type = self._parse_single_video_payload_type(
                raw_value
            )
            return True

        safe_value = (
            raw_value if _MEDIA_DIAGNOSTIC_VALUE_RE.fullmatch(raw_value) else None
        )
        if safe_value is None:
            return True

        if key == "R42_MEDIA_CHANNEL_ID":
            self._media_channel = self._safe_int(safe_value)
        elif key == "R42_MEDIAREQ26_OPEN_CHANNEL":
            self._mediareq26_open_sent = True
            self._mediareq26_open_channel = self._safe_int(safe_value)
        elif key == "R42_MEDIA_STOP_CHANNEL":
            self._stop_sent = True
            self._stop_channel = self._safe_int(safe_value)
        elif key == "R42_MEDIA_CHANNEL_CLOSED" and safe_value == "true":
            self._channel_closed = True
        elif key == "R42_LISTENER_RTP_FORWARDING_ARMED" and safe_value == "false":
            self._rtp_disarmed = True
        elif key == "P80_VIDEO_RTP_FORWARDING" and safe_value == "PASS":
            if not self._rtp_received:
                self._rtp_received = True
                # Wall-clock observation time recorded by the integration,
                # not a value produced by the native runtime; never mix
                # this with the native monotonic-ms clock used on the wire.
                self._first_rtp_at = self._now()
        elif key == "P80_VIDEO_RTP_PACKETS":
            self._rtp_packet_count = self._safe_int(safe_value)
        elif key in _H264_EVIDENCE_KEYS:
            count = self._safe_int(safe_value)
            if count is not None and count > 0:
                self._h264_detected = True
        return True

    @staticmethod
    def _safe_int(value: str) -> int | None:
        try:
            return int(value)
        except ValueError:
            return None

    @staticmethod
    def _parse_single_video_payload_type(raw_value: str) -> int | None:
        """Return the one observed video RTP payload type, if unambiguous.

        ``P116_VIDEO_PT_SET`` is a comma-joined dump of every payload type
        bit observed so far (or the literal ``NONE``). Only a single
        observed value is a meaningful runtime scalar for
        ``rtp_payload_type`` (RTP PT is a 7-bit field: 0-127); ``NONE``, an
        empty value, or more than one observed PT all mean there is no
        single runtime value to report, so the field must read as unknown
        rather than guess or fall back to a historical/capture literal.
        """
        if not _VIDEO_PT_SET_SINGLE_RE.fullmatch(raw_value):
            return None
        value = int(raw_value)
        if value > 127:
            return None
        return value

    def snapshot(self) -> dict[str, object]:
        channel_source = (
            CHANNEL_SOURCE_RUNTIME_CALL_BOUND
            if self._media_channel is not None
            else None
        )
        return {
            "call_generation": self._call_generation,
            "media_channel": self._media_channel,
            "channel_source": channel_source,
            "mediareq26_open_sent": self._mediareq26_open_sent,
            "mediareq26_open_channel": self._mediareq26_open_channel,
            "rtp_received": self._rtp_received,
            "rtp_packet_count": self._rtp_packet_count,
            "rtp_payload_type": self._rtp_payload_type,
            "h264_detected": self._h264_detected,
            "video_width": None,
            "video_height": None,
            "first_rtp_at": self._first_rtp_at,
            "stop_sent": self._stop_sent,
            "stop_channel": self._stop_channel,
            "channel_closed": self._channel_closed,
            "cleanup_complete": self._channel_closed and self._rtp_disarmed,
        }


_RECOGNIZED_MEDIA_DIAGNOSTIC_KEYS = frozenset(
    {
        "R42_MEDIA_CHANNEL_ID",
        "R42_MEDIAREQ26_OPEN_CHANNEL",
        "R42_MEDIA_STOP_CHANNEL",
        "R42_MEDIA_CHANNEL_CLOSED",
        "R42_LISTENER_RTP_FORWARDING_ARMED",
        "P80_VIDEO_RTP_FORWARDING",
        "P80_VIDEO_RTP_PACKETS",
        "P116_VIDEO_PT_SET",
        *_H264_EVIDENCE_KEYS,
    }
)
