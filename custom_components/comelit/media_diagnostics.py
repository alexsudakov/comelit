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
_MEDIA_DIAGNOSTIC_PREFIXES = ("R42_", "R54_", "P80_", "P116_")
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

# COMELIT-P116-R42B-CANARY-OBSERVABILITY-001 round 2 (failure forensic):
# bounded observability for the CAPABILITIES trigger candidate-frame
# classification (R42_TRIGGER_REJECT_STAGE enum), plus the transport-level
# attach failure reason. Additive to MEDIA_DIAGNOSTICS_FIELDS above; none of
# the original 16 fields/semantics change.
CAPABILITIES_TRIGGER_FIELDS = (
    "capabilities_seen",
    "capabilities_parse_ok",
    "capabilities_call_match",
    "capabilities_video_requested",
    "trigger_reject_stage",
    "capabilities_candidate_count",
    "attach_failure_reason",
)

CALL_ADOPTION_FIELDS = (
    "call_adoption_started",
    "invite_ack_sent",
    "local_capabilities_sent",
    "local_capability_word",
    "local_alerting_sent",
    "waiting_peer_capabilities",
    "peer_capabilities_seen",
    "peer_capability_word",
    "peer_video_requested",
    "peer_data_ack_sent",
    "call_adoption_failure_stage",
)

# R42_TRIGGER_REJECT_STAGE is a native-printed enum classifying exactly where
# a CAPABILITIES-opcode candidate frame was rejected (or NONE/terminal
# outcome). Values do not fit the generic true/false/PASS/FAIL/digits gate,
# so they get their own whitelist; anything else is dropped, not stored.
_TRIGGER_REJECT_STAGES = frozenset(
    {
        "NONE",
        "NO_WRITER",
        "ENVELOPE",
        "FLAG",
        "OPCODE",
        "LENGTH",
        "NO_LIVE_CALL",
        "CONNECTION_MISMATCH",
        "VIDEO_BIT_CLEAR",
        "QUEUE_REJECTED",
        "OPEN_SENT",
    }
)

# Deeper trigger evidence is monotonic within one call generation. Native
# diagnostics deliberately continue observing later frames, including
# unrelated traffic, so a late pre-candidate rejection must never erase a
# previously proven real CAPABILITIES match or OPEN result from status().
_TRIGGER_REJECT_STAGE_PRIORITY = {
    "NO_WRITER": 10,
    "ENVELOPE": 20,
    "FLAG": 30,
    "OPCODE": 40,
    "LENGTH": 50,
    "NO_LIVE_CALL": 60,
    "CONNECTION_MISMATCH": 70,
    "VIDEO_BIT_CLEAR": 80,
    "NONE": 90,
    "QUEUE_REJECTED": 100,
    "OPEN_SENT": 110,
}

# attach_failure_reason is populated by the caller from existing Python
# transport state (ComelitEntranceMediaTransport.last_error), never from a
# native marker; whitelisted the same way so an unexpected exception-derived
# string never reaches the status payload verbatim.
_ATTACH_FAILURE_REASONS = frozenset(
    {
        "attached_media_open_not_confirmed",
        "listener_not_ready",
        "media_start_not_confirmed",
        "unsupported_attached_media_panel",
        "media_session_state_mismatch",
        "media_session_transition_busy",
        "attached_inbound_media_busy",
        "listener_pause_not_confirmed",
        "unsupported_media_panel",
        "invalid_media_reason",
        "invalid_stop_reason",
        "unknown",
    }
)

_CALL_ADOPTION_FAILURE_STAGES = frozenset(
    {
        "NONE",
        "ACK_BUILD_FAILED",
        "ACK_WRITE_FAILED",
        "CAPABILITIES_BUILD_FAILED",
        "CAPABILITIES_WRITE_FAILED",
        "ALERTING_BUILD_FAILED",
        "ALERTING_WRITE_FAILED",
        "WAITING_PEER_CAPABILITIES",
        "PEER_CAPABILITIES_REJECTED",
        "MEDIA_TRIGGER_REJECTED",
    }
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

    The CAPABILITIES-trigger candidate fields (``capabilities_*``,
    ``trigger_reject_stage``, ``capabilities_candidate_count``) only read
    results already computed by the existing, unmodified R35/R36/R42
    predicates -- they do not add a second decision surface.
    ``attach_failure_reason`` is set explicitly by the caller from existing
    Python transport state, never parsed from a native marker.
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
        self._capabilities_seen = False
        self._capabilities_parse_ok = False
        self._capabilities_call_match = False
        self._capabilities_video_requested = False
        self._trigger_reject_stage: str | None = None
        self._capabilities_candidate_count: int | None = None
        self._attach_failure_reason: str | None = None
        self._reset_call_adoption_fields()

    def _reset_call_adoption_fields(self) -> None:
        self._call_adoption_started = False
        self._invite_ack_sent = False
        self._local_capabilities_sent = False
        self._local_capability_word: int | None = None
        self._local_alerting_sent = False
        self._waiting_peer_capabilities = False
        self._peer_capabilities_seen = False
        self._peer_capability_word: int | None = None
        self._peer_video_requested = False
        self._peer_data_ack_sent = False
        self._call_adoption_failure_stage: str | None = None

    def _arm_for_generation(self, generation: int) -> None:
        # A strictly newer generation always starts a fresh call; a
        # same-or-older generation is either the current call re-announcing
        # itself or stale replay and must never wipe live evidence.
        if self._call_generation is None or generation > self._call_generation:
            self.reset()
            self._call_generation = generation
            self._reset_call_adoption_fields()

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

        # R42_TRIGGER_REJECT_STAGE is an uppercase enum word (e.g.
        # "NO_LIVE_CALL"), which the generic true/false/PASS/FAIL/digits
        # gate below does not model either.
        if key == "R42_TRIGGER_REJECT_STAGE":
            if raw_value not in _TRIGGER_REJECT_STAGES:
                # Invalid diagnostic input is ignored fail-closed; it must not
                # erase a previously proven valid stage for this generation.
                return True

            current = self._trigger_reject_stage
            if (
                current is None
                or _TRIGGER_REJECT_STAGE_PRIORITY[raw_value]
                >= _TRIGGER_REJECT_STAGE_PRIORITY[current]
            ):
                self._trigger_reject_stage = raw_value

            # These terminal outcomes are emitted only by the existing
            # functional trigger after parse/current-call/video predicates
            # have all passed. They therefore imply the four booleans even
            # when the bounded candidate-detail log budget was exhausted.
            if raw_value in {"QUEUE_REJECTED", "OPEN_SENT"}:
                self._capabilities_seen = True
                self._capabilities_parse_ok = True
                self._capabilities_call_match = True
                self._capabilities_video_requested = True
            return True

        if key == "R54_CALL_ADOPTION_FAILURE_STAGE":
            if raw_value in _CALL_ADOPTION_FAILURE_STAGES:
                self._call_adoption_failure_stage = raw_value
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
        elif key == "R42_CAPABILITIES_CANDIDATE_SEEN":
            self._capabilities_seen = (
                self._capabilities_seen or safe_value == "true"
            )
        elif key == "R42_CAPABILITIES_PARSE_OK":
            self._capabilities_parse_ok = (
                self._capabilities_parse_ok or safe_value == "true"
            )
        elif key == "R42_CAPABILITIES_CALL_MATCH":
            self._capabilities_call_match = (
                self._capabilities_call_match or safe_value == "true"
            )
        elif key == "R42_CAPABILITIES_VIDEO_REQUESTED":
            self._capabilities_video_requested = (
                self._capabilities_video_requested or safe_value == "true"
            )
        elif key == "R42_CAPABILITIES_CANDIDATE_COUNT":
            count = self._safe_int(safe_value)
            if count is not None:
                if self._capabilities_candidate_count is None:
                    self._capabilities_candidate_count = count
                else:
                    self._capabilities_candidate_count = max(
                        self._capabilities_candidate_count, count
                    )
        elif key == "R54_CALL_ADOPTION_STARTED":
            self._call_adoption_started = (
                self._call_adoption_started or safe_value == "true"
            )
        elif key == "R54_INVITE_ACK_SENT":
            self._invite_ack_sent = self._invite_ack_sent or safe_value == "true"
        elif key == "R54_LOCAL_CAPABILITIES_SENT":
            self._local_capabilities_sent = (
                self._local_capabilities_sent or safe_value == "true"
            )
        elif key == "R54_LOCAL_CAPABILITY_WORD":
            self._local_capability_word = self._safe_int(safe_value)
        elif key == "R54_LOCAL_ALERTING_SENT":
            self._local_alerting_sent = (
                self._local_alerting_sent or safe_value == "true"
            )
        elif key == "R54_WAITING_PEER_CAPABILITIES":
            self._waiting_peer_capabilities = (
                self._waiting_peer_capabilities or safe_value == "true"
            )
        elif key == "R54_PEER_CAPABILITIES_SEEN":
            self._peer_capabilities_seen = (
                self._peer_capabilities_seen or safe_value == "true"
            )
        elif key == "R54_PEER_CAPABILITY_WORD":
            self._peer_capability_word = self._safe_int(safe_value)
        elif key == "R54_PEER_VIDEO_REQUESTED":
            self._peer_video_requested = (
                self._peer_video_requested or safe_value == "true"
            )
        elif key == "R54_PEER_DATA_ACK_SENT":
            self._peer_data_ack_sent = (
                self._peer_data_ack_sent or safe_value == "true"
            )
        return True

    def set_attach_failure_reason(self, reason: str | None) -> None:
        """Record the transport-level attach failure reason for this call.

        Populated by the caller from existing Python transport state (e.g.
        ``ComelitEntranceMediaTransport.last_error``), never from a native
        marker. Any value outside the known whitelist is dropped (``None``)
        rather than stored verbatim, since ``last_error`` can also carry
        unexpected exception-derived strings.
        """
        self._attach_failure_reason = (
            reason if reason in _ATTACH_FAILURE_REASONS else None
        )

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
            "capabilities_seen": self._capabilities_seen,
            "capabilities_parse_ok": self._capabilities_parse_ok,
            "capabilities_call_match": self._capabilities_call_match,
            "capabilities_video_requested": self._capabilities_video_requested,
            "trigger_reject_stage": self._trigger_reject_stage,
            "capabilities_candidate_count": self._capabilities_candidate_count,
            "attach_failure_reason": self._attach_failure_reason,
            "call_adoption_started": self._call_adoption_started,
            "invite_ack_sent": self._invite_ack_sent,
            "local_capabilities_sent": self._local_capabilities_sent,
            "local_capability_word": self._local_capability_word,
            "local_alerting_sent": self._local_alerting_sent,
            "waiting_peer_capabilities": self._waiting_peer_capabilities,
            "peer_capabilities_seen": self._peer_capabilities_seen,
            "peer_capability_word": self._peer_capability_word,
            "peer_video_requested": self._peer_video_requested,
            "peer_data_ack_sent": self._peer_data_ack_sent,
            "call_adoption_failure_stage": self._call_adoption_failure_stage,
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
        "R42_CAPABILITIES_CANDIDATE_SEEN",
        "R42_CAPABILITIES_PARSE_OK",
        "R42_CAPABILITIES_CALL_MATCH",
        "R42_CAPABILITIES_VIDEO_REQUESTED",
        "R42_CAPABILITIES_CANDIDATE_COUNT",
        "R42_TRIGGER_REJECT_STAGE",
        "R54_CALL_ADOPTION_STARTED",
        "R54_INVITE_ACK_SENT",
        "R54_LOCAL_CAPABILITIES_SENT",
        "R54_LOCAL_CAPABILITY_WORD",
        "R54_LOCAL_ALERTING_SENT",
        "R54_WAITING_PEER_CAPABILITIES",
        "R54_PEER_CAPABILITIES_SEEN",
        "R54_PEER_CAPABILITY_WORD",
        "R54_PEER_VIDEO_REQUESTED",
        "R54_PEER_DATA_ACK_SENT",
        "R54_CALL_ADOPTION_FAILURE_STAGE",
        *_H264_EVIDENCE_KEYS,
    }
)
