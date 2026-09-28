from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import re
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
DIAGNOSTICS_PATH = ROOT / "custom_components/comelit/miniapp/diagnostics.py"
HOST_PATH = ROOT / "custom_components/comelit/frontend/miniapp/host.js"


def _load():
    spec = importlib.util.spec_from_file_location(
        "comelit_miniapp_diagnostics_test",
        DIAGNOSTICS_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


diagnostics = _load()


def _rejects(payload, code: str) -> None:
    with pytest.raises(diagnostics.MiniAppDiagnosticsError) as exc:
        diagnostics.validate_payload(payload)
    assert exc.value.code == code


def test_valid_event_formats_single_closed_log_line():
    payload = diagnostics.validate_payload(
        {
            "event": "rtp",
            "elapsed_ms": 5000,
            "stage_ms": 1000,
            "state": "checking",
            "counters": {"bytes_received": 0, "frames_decoded": 0},
        }
    )

    assert diagnostics.format_log_line("camera.parking_6048", payload) == (
        "COMELIT_MINIAPP_DIAG entity=camera.parking_6048 event=rtp "
        "elapsed_ms=5000 stage_ms=1000 state=checking reason=- "
        "counters=bytes_received=0,frames_decoded=0"
    )
    assert diagnostics.format_summary_line("camera.parking_6048", payload).startswith(
        "COMELIT_MINIAPP_DIAG_SUMMARY "
    )


def test_schema_rejects_unknown_types_bounds_and_extra_structures():
    _rejects([], "payload_not_dict")
    _rejects({}, "missing_event")
    _rejects({"event": "bogus"}, "invalid_event")
    _rejects({"event": "rtp", "extra": 1}, "unknown_key")
    _rejects({"event": "rtp", "elapsed_ms": True}, "invalid_type")
    _rejects({"event": "rtp", "elapsed_ms": 600001}, "out_of_bounds")
    _rejects({"event": "rtp", "state": "sdp"}, "invalid_state")
    _rejects({"event": "fallback", "reason": "bogus"}, "invalid_reason")
    _rejects({"event": "rtp", "counters": []}, "invalid_counters")
    _rejects({"event": "rtp", "counters": {"bad-key": 1}}, "invalid_counter_key")
    _rejects({"event": "rtp", "counters": {"ok": {}}}, "invalid_counter_value")
    _rejects(
        {"event": "rtp", "counters": {"ok": 1000001}},
        "counter_out_of_bounds",
    )
    _rejects(
        {
            "event": "rtp",
            "counters": {f"k{i}": i for i in range(diagnostics.MAX_COUNTERS + 1)},
        },
        "too_many_counters",
    )


def test_body_limit_and_fixed_error_codes():
    assert diagnostics.loads_limited(json.dumps({"event": "config"}).encode()) == {
        "event": "config"
    }
    with pytest.raises(diagnostics.MiniAppDiagnosticsError) as exc:
        diagnostics.loads_limited(b"{" + (b'"x":1,' * 400) + b'"event":"config"}')
    assert exc.value.code == "payload_too_large"
    with pytest.raises(diagnostics.MiniAppDiagnosticsError) as exc:
        diagnostics.loads_limited(b"{")
    assert exc.value.code == "invalid_json"


def test_no_free_text_or_sensitive_values_can_reach_serialized_lines():
    hostile = (
        "sdp",
        "a=candidate:1 1 udp",
        "192.168.1.10",
        "https://example.invalid",
        "wss://example.invalid",
        "rtsp://camera",
        "bearer abc",
        "cookie",
        "initData",
        "token",
    )
    for value in hostile:
        _rejects({"event": value}, "invalid_event")
        _rejects({"event": "rtp", "state": value}, "invalid_state")
        _rejects({"event": "fallback", "reason": value}, "invalid_reason")
        with pytest.raises(diagnostics.MiniAppDiagnosticsError) as exc:
            diagnostics.validate_payload({"event": "rtp", "counters": {value: 1}})
        assert exc.value.code in {"invalid_counter_key", "redacted_value"}
        with pytest.raises(diagnostics.MiniAppDiagnosticsError) as exc:
            diagnostics.format_log_line(value, {"event": "config"})
        assert exc.value.code == "redacted_value"


def test_redaction_guard_refuses_sdp_and_telegram_auth_backstop_tokens():
    hostile = (
        "a=ice-ufrag:abcd",
        "a=ice-pwd:abcd",
        "v=0",
        "o=- 1 2 IN IP4 127.0.0.1",
        "m=audio 9 UDP/TLS/RTP/SAVPF 111",
        "m=video 9 UDP/TLS/RTP/SAVPF 96",
        "hash=abcdef",
        "signature=abcdef",
        "candidate:1 1 udp",
    )
    for value in hostile:
        with pytest.raises(diagnostics.MiniAppDiagnosticsError) as exc:
            diagnostics.format_log_line(value, {"event": "config"})
        assert exc.value.code == "redacted_value"


def _js_array_length(source: str, name: str) -> int:
    match = re.search(rf"const {name} = \[(.*?)\];", source, re.S)
    assert match is not None
    return len(re.findall(r'"[a-z0-9_]+"', match.group(1)))


def test_client_counter_budget_is_derived_from_server_schema_limit():
    host = HOST_PATH.read_text(encoding="utf-8")
    max_match = re.search(r"const MAX_DIAGNOSTICS_COUNTERS = ([0-9]+);", host)
    assert max_match is not None
    assert int(max_match.group(1)) == diagnostics.MAX_COUNTERS

    family_counts = {
        "webrtc": _js_array_length(host, "WEBRTC_COUNTER_PRIORITY"),
        "hls": _js_array_length(host, "HLS_COUNTER_PRIORITY"),
    }
    assert max(family_counts.values()) <= diagnostics.MAX_COUNTERS


def test_rate_limiter_prunes_expired_session_state():
    limiter = diagnostics.MiniAppDiagnosticsRateLimiter()

    assert limiter.accept(
        "session-a",
        "camera.driveway",
        expires_at=10.0,
        now=1.0,
    )
    assert limiter.bucket_count == 1

    limiter.prune(now=11.0)

    assert limiter.bucket_count == 0

def test_rate_limiter_existing_session_does_not_evict_at_capacity():
    limiter = diagnostics.MiniAppDiagnosticsRateLimiter()

    for index in range(diagnostics.MAX_RATE_LIMIT_SESSIONS):
        assert limiter.accept(
            f"session-{index}",
            "camera.driveway",
            expires_at=10_000.0,
            now=float(index + 1),
        )

    oldest = limiter._buckets["session-0"]
    existing = limiter._buckets[f"session-{diagnostics.MAX_RATE_LIMIT_SESSIONS - 1}"]

    assert limiter.accept(
        f"session-{diagnostics.MAX_RATE_LIMIT_SESSIONS - 1}",
        "camera.driveway",
        expires_at=10_000.0,
        now=999.0,
    )

    assert limiter.bucket_count == diagnostics.MAX_RATE_LIMIT_SESSIONS
    assert limiter._buckets["session-0"] is oldest
    assert oldest.total == 1
    assert existing.total == 2
