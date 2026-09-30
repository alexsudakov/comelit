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
