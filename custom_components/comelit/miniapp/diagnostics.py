from __future__ import annotations

from dataclasses import dataclass, field
import json
import re
from typing import Any


EVENTS = (
    "config",
    "offer",
    "answer",
    "track",
    "ice",
    "rtp",
    "first_frame",
    "first_moving_frame",
    "mse_connect",
    "mse_ready",
    "mse_first_chunk",
    "mse_first_frame",
    "mse_error",
    "mse_fallback",
    "fallback",
    "hls_manifest",
    "hls_play",
    "hls_state",
    "hls_first_frame",
    "hls_seek",
    "hls_error",
    "hls_blocked",
)
SERVER_EVENTS = (
    "mse_command_received",
    "mse_source_resolved",
    "mse_stream_registered",
    "mse_upstream_ws_open",
    "mse_negotiation_forwarded",
    "mse_upstream_reply",
    "mse_upstream_chunk",
)
GO2RTC_STATE_EVENTS = (
    "stream_state_250ms",
    "stream_state_4000ms",
    "stream_state_7000ms",
)
GO2RTC_STATE_COUNTERS = frozenset(
    {
        "inspect_ok",
        "producer_count",
        "consumer_count",
        "p0_active",
        "p0_media",
        "p0_receivers",
        "p0_h264",
        "p0_pcma",
        "p0_recv_kb",
        "p1_active",
        "p1_media",
        "p1_receivers",
        "p1_h264",
        "p1_opus",
        "p1_recv_kb",
        "consumer_senders",
    }
)

PLAYER_STATES = (
    "new",
    "checking",
    "connected",
    "completed",
    "disconnected",
    "failed",
    "closed",
    "unknown",
    "resolved",
    "rejected",
    "NotAllowedError",
    "AbortError",
    "NotSupportedError",
    "NotReadableError",
    "SecurityError",
    "TypeError",
    "paused",
    "playing",
    "ended",
    "loadeddata",
    "seeking",
    "seeked",
)
FALLBACK_REASONS = (
    "stats_deadline_checking",
    "stats_deadline_other",
    "ice_failed",
    "connection_failed",
    "websocket_error",
    "websocket_closed",
    "offer_error",
    "answer_error",
    "candidate_error",
    "no_rtcpeerconnection",
    "session_expired",
    "navigate",
    "no_mediasource",
    "mse_ws_error",
    "mse_ws_closed",
    "mse_negotiation_failed",
    "mse_unsupported_codec",
    "mse_first_chunk_timeout",
    "mse_first_frame_timeout",
    "mse_append_error",
    "go2rtc_unavailable",
    "go2rtc_incompatible",
    "go2rtc_http_error",
    "go2rtc_ws_error",
    "stream_source_unavailable",
    "invalid_mse_command",
    "mse_registry_full",
)
HLS_ERROR_KINDS = (
    "networkError",
    "mediaError",
    "muxError",
    "keySystemError",
    "otherError",
    "manifestLoadError",
    "manifestLoadTimeOut",
    "manifestParsingError",
    "levelLoadError",
    "levelLoadTimeOut",
    "fragLoadError",
    "fragLoadTimeOut",
    "bufferStalledError",
    "bufferSeekOverHole",
    "bufferNudgeOnStall",
    "internalException",
    "fatal",
    "nonfatal",
)

MAX_BODY_BYTES = 2048
MAX_COUNTERS = 16
MAX_MS = 600_000
MAX_COUNTER_VALUE = 1_000_000
MAX_EVENTS_PER_SESSION = 160
MAX_EVENTS_PER_SESSION_ENTITY = 80
MAX_RATE_LIMIT_SESSIONS = 128
MAX_RATE_LIMIT_ENTITIES_PER_SESSION = 8
MAX_GO2RTC_STATE_LOG_CHARS = 16_384
_GO2RTC_SECRET_KEYS = frozenset(
    {
        "url",
        "source",
        "remote_addr",
        "sdp",
        "user_agent",
        "username",
        "password",
        "token",
        "cookie",
        "authorization",
    }
)
_GO2RTC_URL_RE = re.compile(
    r"(?i)\b(?:rtsp|rtsps|http|https|ws|wss)://[^\s\"']+"
)
_GO2RTC_IPV4_RE = re.compile(
    r"(?<![0-9])(?:[0-9]{1,3}\.){3}[0-9]{1,3}(?::[0-9]{1,5})?"
)
_MAX_GO2RTC_WS_VALUE_CHARS = 2048
_ALLOWED_KEYS = frozenset(
    {"event", "elapsed_ms", "stage_ms", "state", "reason", "counters"}
)
_COUNTER_KEY = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
_REDACTION_GUARD = re.compile(
    r"(?i)(sdp|a=candidate|\d{1,3}(\.\d{1,3}){3}|https?://|wss?://|"
    r"rtsp://|bearer|cookie|initdata|token|ice-ufrag|ice-pwd|v=0|"
    r"o=-|m=audio|m=video|hash=|signature|candidate:)"
)


class MiniAppDiagnosticsError(ValueError):
    """A client diagnostics event failed the closed schema."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(slots=True)
class _DiagnosticsRateBucket:
    expires_at: float
    total: int = 0
    entity_counts: dict[str, int] = field(default_factory=dict)
    entity_seen: dict[str, float] = field(default_factory=dict)
    last_seen: float = 0.0


class MiniAppDiagnosticsRateLimiter:
    """Bound accepted diagnostics events by Mini App session and entity."""

    def __init__(self) -> None:
        self._buckets: dict[str, _DiagnosticsRateBucket] = {}

    def accept(
        self,
        session_token: str,
        entity_id: str,
        *,
        expires_at: float,
        now: float,
    ) -> bool:
        self.prune(now=now)
        if (
            session_token not in self._buckets
            and len(self._buckets) >= MAX_RATE_LIMIT_SESSIONS
        ):
            oldest = min(
                self._buckets,
                key=lambda token: self._buckets[token].last_seen,
            )
            self._buckets.pop(oldest, None)

        bucket = self._buckets.get(session_token)
        if bucket is None:
            bucket = _DiagnosticsRateBucket(expires_at=expires_at)
            self._buckets[session_token] = bucket
        else:
            bucket.expires_at = max(bucket.expires_at, expires_at)

        bucket.last_seen = now
        bucket.entity_seen[entity_id] = now
        if len(bucket.entity_counts) >= MAX_RATE_LIMIT_ENTITIES_PER_SESSION:
            if entity_id not in bucket.entity_counts:
                oldest_entity = min(
                    bucket.entity_seen,
                    key=lambda item: bucket.entity_seen[item],
                )
                bucket.entity_counts.pop(oldest_entity, None)
                bucket.entity_seen.pop(oldest_entity, None)

        current_entity_count = bucket.entity_counts.get(entity_id, 0)
        if (
            bucket.total >= MAX_EVENTS_PER_SESSION
            or current_entity_count >= MAX_EVENTS_PER_SESSION_ENTITY
        ):
            return False

        bucket.total += 1
        bucket.entity_counts[entity_id] = current_entity_count + 1
        return True

    def prune(self, *, now: float) -> None:
        expired = [
            token
            for token, bucket in self._buckets.items()
            if bucket.expires_at <= now
        ]
        for token in expired:
            self._buckets.pop(token, None)

    @property
    def bucket_count(self) -> int:
        return len(self._buckets)


def loads_limited(body: bytes) -> dict[str, Any]:
    if len(body) > MAX_BODY_BYTES:
        raise MiniAppDiagnosticsError("payload_too_large")
    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
        raise MiniAppDiagnosticsError("invalid_json") from exc
    return validate_payload(payload)


def validate_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise MiniAppDiagnosticsError("payload_not_dict")
    unknown = set(payload) - _ALLOWED_KEYS
    if unknown:
        raise MiniAppDiagnosticsError("unknown_key")
    event = payload.get("event")
    if event is None:
        raise MiniAppDiagnosticsError("missing_event")
    if not isinstance(event, str) or event not in EVENTS:
        raise MiniAppDiagnosticsError("invalid_event")

    result: dict[str, Any] = {"event": event}
    for key in ("elapsed_ms", "stage_ms"):
        if key not in payload:
            continue
        value = payload[key]
        if not isinstance(value, int) or isinstance(value, bool):
            raise MiniAppDiagnosticsError("invalid_type")
        if value < 0 or value > MAX_MS:
            raise MiniAppDiagnosticsError("out_of_bounds")
        result[key] = value

    state = payload.get("state")
    if state is not None:
        if not isinstance(state, str) or state not in PLAYER_STATES:
            raise MiniAppDiagnosticsError("invalid_state")
        result["state"] = state

    reason = payload.get("reason")
    if reason is not None:
        allowed_reasons = HLS_ERROR_KINDS if event == "hls_error" else FALLBACK_REASONS
        if not isinstance(reason, str) or reason not in allowed_reasons:
            raise MiniAppDiagnosticsError("invalid_reason")
        result["reason"] = reason

    counters = payload.get("counters")
    if counters is not None:
        if not isinstance(counters, dict):
            raise MiniAppDiagnosticsError("invalid_counters")
        if len(counters) > MAX_COUNTERS:
            raise MiniAppDiagnosticsError("too_many_counters")
        clean_counters: dict[str, int] = {}
        for key, value in counters.items():
            if not isinstance(key, str) or _COUNTER_KEY.fullmatch(key) is None:
                raise MiniAppDiagnosticsError("invalid_counter_key")
            if not isinstance(value, int) or isinstance(value, bool):
                raise MiniAppDiagnosticsError("invalid_counter_value")
            if value < 0 or value > MAX_COUNTER_VALUE:
                raise MiniAppDiagnosticsError("counter_out_of_bounds")
            clean_counters[key] = value
        result["counters"] = clean_counters

    _assert_not_sensitive(result)
    return result


def format_log_line(entity_id: str, payload: dict[str, Any]) -> str:
    _assert_not_sensitive({"entity": entity_id, **payload})
    return _format_line("COMELIT_MINIAPP_DIAG", entity_id, payload)


def format_summary_line(entity_id: str, payload: dict[str, Any]) -> str:
    _assert_not_sensitive({"entity": entity_id, **payload})
    return _format_line("COMELIT_MINIAPP_DIAG_SUMMARY", entity_id, payload)


def format_server_log_line(
    entity_id: str,
    event: str,
    *,
    elapsed_ms: int,
    stage_ms: int,
) -> str:
    """Format a closed, secret-free server-side MSE milestone."""
    if event not in SERVER_EVENTS:
        raise MiniAppDiagnosticsError("invalid_server_event")
    if (
        not isinstance(elapsed_ms, int)
        or isinstance(elapsed_ms, bool)
        or not isinstance(stage_ms, int)
        or isinstance(stage_ms, bool)
        or elapsed_ms < 0
        or stage_ms < 0
        or elapsed_ms > MAX_MS
        or stage_ms > MAX_MS
    ):
        raise MiniAppDiagnosticsError("invalid_server_timing")
    payload = {
        "event": event,
        "elapsed_ms": elapsed_ms,
        "stage_ms": stage_ms,
    }
    _assert_not_sensitive({"entity": entity_id, **payload})
    return _format_line("COMELIT_MINIAPP_DIAG_SERVER", entity_id, payload)


def format_go2rtc_state_line(
    entity_id: str,
    event: str,
    *,
    elapsed_ms: int,
    counters: dict[str, int],
) -> str:
    """Format a closed, secret-free go2rtc stream-state snapshot."""
    if event not in GO2RTC_STATE_EVENTS:
        raise MiniAppDiagnosticsError("invalid_go2rtc_state_event")
    if (
        not isinstance(elapsed_ms, int)
        or isinstance(elapsed_ms, bool)
        or elapsed_ms < 0
        or elapsed_ms > MAX_MS
    ):
        raise MiniAppDiagnosticsError("invalid_go2rtc_state_timing")
    if not isinstance(counters, dict) or set(counters) - GO2RTC_STATE_COUNTERS:
        raise MiniAppDiagnosticsError("invalid_go2rtc_state_counters")
    clean: dict[str, int] = {}
    for key, value in counters.items():
        if (
            not isinstance(value, int)
            or isinstance(value, bool)
            or value < 0
            or value > MAX_COUNTER_VALUE
        ):
            raise MiniAppDiagnosticsError("invalid_go2rtc_state_counter")
        clean[key] = value
    payload = {
        "event": event,
        "elapsed_ms": elapsed_ms,
        "stage_ms": 0,
        "counters": clean,
    }
    _assert_not_sensitive({"entity": entity_id, **payload})
    return _format_line("COMELIT_MINIAPP_DIAG_GO2RTC", entity_id, payload)


def sanitize_go2rtc_state(value: Any, *, depth: int = 0) -> Any:
    """Preserve useful go2rtc state while removing network/credential material."""
    if depth > 8:
        return "<truncated>"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        if _REDACTION_GUARD.search(value):
            return "<redacted>"
        return value[:512]
    if isinstance(value, list):
        return [sanitize_go2rtc_state(item, depth=depth + 1) for item in value[:64]]
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in list(value.items())[:96]:
            key_text = str(key)[:128]
            if key_text.lower() in _GO2RTC_SECRET_KEYS:
                continue
            result[key_text] = sanitize_go2rtc_state(item, depth=depth + 1)
        return result
    return str(value)[:256]


def format_go2rtc_state_json_line(
    entity_id: str,
    event: str,
    *,
    elapsed_ms: int,
    state: Any,
) -> str:
    """Format a bounded, sanitized go2rtc stream JSON snapshot."""
    if event not in GO2RTC_STATE_EVENTS:
        raise MiniAppDiagnosticsError("invalid_go2rtc_state_event")
    if (
        not isinstance(elapsed_ms, int)
        or isinstance(elapsed_ms, bool)
        or elapsed_ms < 0
        or elapsed_ms > MAX_MS
    ):
        raise MiniAppDiagnosticsError("invalid_go2rtc_state_timing")
    safe = sanitize_go2rtc_state(state)
    serialized = json.dumps(
        safe,
        separators=(",", ":"),
        sort_keys=True,
        ensure_ascii=True,
    )
    if len(serialized) > MAX_GO2RTC_STATE_LOG_CHARS:
        serialized = serialized[:MAX_GO2RTC_STATE_LOG_CHARS] + "...<truncated>"
    # Assert the final line does not accidentally contain a raw secret pattern.
    _assert_not_sensitive(entity_id)
    if _REDACTION_GUARD.search(serialized):
        raise MiniAppDiagnosticsError("redacted_value")
    return (
        f"COMELIT_MINIAPP_DIAG_GO2RTC_STATE entity={entity_id} "
        f"event={event} elapsed_ms={elapsed_ms} snapshot={serialized}"
    )


def sanitize_go2rtc_ws_value(value: Any) -> str:
    """Preserve useful upstream text while removing network/credential material."""
    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, separators=(",", ":"), ensure_ascii=True)
        except (TypeError, ValueError):
            text = str(value)
    text = _GO2RTC_URL_RE.sub("<url_redacted>", text)
    text = _GO2RTC_IPV4_RE.sub("<ip_redacted>", text)
    # Remove common credential-style fragments that may occur outside URLs.
    text = re.sub(
        r"(?i)\\b(?:password|passwd|token|authorization|cookie)=?[^,;\\s]*",
        "<credential_redacted>",
        text,
    )
    return text[:_MAX_GO2RTC_WS_VALUE_CHARS]


def format_go2rtc_ws_line(
    entity_id: str,
    *,
    elapsed_ms: int,
    frame_type: str,
    value: Any,
) -> str:
    """Format sanitized upstream go2rtc WebSocket text."""
    if (
        not isinstance(elapsed_ms, int)
        or isinstance(elapsed_ms, bool)
        or elapsed_ms < 0
        or elapsed_ms > MAX_MS
    ):
        raise MiniAppDiagnosticsError("invalid_go2rtc_ws_timing")
    if not isinstance(frame_type, str):
        raise MiniAppDiagnosticsError("invalid_go2rtc_ws_type")
    safe_type = re.sub(r"[^a-zA-Z0-9_.-]", "_", frame_type[:64]) or "unknown"
    safe_value = sanitize_go2rtc_ws_value(value)
    return (
        f"COMELIT_MINIAPP_DIAG_GO2RTC_WS entity={entity_id} "
        f"elapsed_ms={elapsed_ms} type={safe_type} value={safe_value}"
    )


def _format_line(marker: str, entity_id: str, payload: dict[str, Any]) -> str:
    counters = payload.get("counters") or {}
    counter_text = (
        ",".join(f"{key}={counters[key]}" for key in sorted(counters)) or "-"
    )
    return (
        f"{marker} entity={entity_id} event={payload['event']} "
        f"elapsed_ms={payload.get('elapsed_ms', 0)} "
        f"stage_ms={payload.get('stage_ms', 0)} "
        f"state={payload.get('state') or '-'} "
        f"reason={payload.get('reason') or '-'} counters={counter_text}"
    )


def _assert_not_sensitive(value: Any) -> None:
    if isinstance(value, str):
        if _REDACTION_GUARD.search(value):
            raise MiniAppDiagnosticsError("redacted_value")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            _assert_not_sensitive(str(key))
            _assert_not_sensitive(item)
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _assert_not_sensitive(item)
