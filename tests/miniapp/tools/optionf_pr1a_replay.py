from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
import sys
import types
from uuid import uuid4


def load_fixture_lines(fixture_path: str) -> list[str]:
    return Path(fixture_path).read_text(encoding="utf-8").splitlines()


def load_plain_module(repo_root: str, relative_path: str, module_name: str):
    spec = importlib.util.spec_from_file_location(
        f"optionf_pr1a_plain_{module_name}_{uuid4().hex}",
        Path(repo_root) / relative_path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _install_module(name: str, **attrs):
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    sys.modules[name] = module
    return module


def _load_component_module(repo_root: str, module_name: str):
    root = Path(repo_root)
    pkg_root = root / "custom_components" / "comelit"
    package_name = f"optionf_pr1a_{module_name}_{uuid4().hex}"
    package = _install_module(package_name)
    package.__path__ = [str(pkg_root)]

    restored = {}
    for name in (
        "aiohttp",
        "homeassistant.config_entries",
        "homeassistant.core",
        f"{package_name}.cloud",
        f"{package_name}.oauth",
        f"{package_name}.ring_media",
        f"{package_name}.h264_recovery",
    ):
        restored[name] = sys.modules.get(name)

    _install_module("aiohttp", ClientSession=object)
    _install_module("homeassistant.config_entries", ConfigEntry=object)
    _install_module("homeassistant.core", HomeAssistant=object)
    _install_module(
        f"{package_name}.cloud",
        ComelitCloudError=Exception,
        ComelitCloudHttpError=Exception,
        async_negotiate_p2p=None,
    )
    _install_module(
        f"{package_name}.oauth",
        ComelitOAuthError=Exception,
        ComelitOAuthManager=object,
    )
    _install_module(f"{package_name}.ring_media", RingMediaCoordinator=object)
    _install_module(f"{package_name}.h264_recovery", H264RecoveryRtpShim=object)

    spec = importlib.util.spec_from_file_location(
        f"{package_name}.{module_name}",
        pkg_root / f"{module_name}.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
        return module
    finally:
        for name, previous in restored.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous


class _FakeStdout:
    def __init__(self, lines: list[str]) -> None:
        self._lines = [line.encode("utf-8") + b"\n" for line in lines]
        self._index = 0

    async def readline(self) -> bytes:
        if self._index >= len(self._lines):
            return b""
        line = self._lines[self._index]
        self._index += 1
        return line


class _FakeProcess:
    def __init__(self, lines: list[str]) -> None:
        self.stdout = _FakeStdout(lines)


class _FakeEvent:
    def __init__(self) -> None:
        self._set = False

    def set(self) -> None:
        self._set = True

    def clear(self) -> None:
        self._set = False

    def is_set(self) -> bool:
        return self._set


class _FakeCallState:
    def __init__(self, snapshots: list[dict[str, object]]) -> None:
        self._snapshots = snapshots

    def reset(self) -> None:
        self._snapshots.append({"state": "reset"})

    def remote_release(self) -> bool:
        self._snapshots.append({"state": "remote_release"})
        return True

    def ring_observed(self, event_id: str, door: str) -> None:
        self._snapshots.append({"event_id": event_id, "door": door})


class _FakeDiagnostics:
    def observe_line(self, line: str) -> None:
        return None


def _normalize(value):
    if isinstance(value, dict):
        return {key: _normalize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_normalize(item) for item in value)
    if isinstance(value, str) and len(value) >= 20 and "-" in value:
        return "<EVENT_ID>"
    return value


def _normalize_event(event: dict[str, object]) -> dict[str, object]:
    normalized = dict(event)
    if "event_id" in normalized:
        normalized["event_id"] = "<EVENT_ID>"
    if "timestamp" in normalized:
        normalized["timestamp"] = "<TIMESTAMP>"
    return _normalize(normalized)


def _digest(instance, events: list[dict[str, object]], call_state: list[dict[str, object]]):
    return {
        "events": [_normalize_event(event) for event in events],
        "call_state": [_normalize_event(event) for event in call_state],
        "marker_tail": list(getattr(instance, "_native_marker_tail", [])),
        "ring_lines": list(getattr(instance, "_ring_lines", [])),
        "warnings": [],
    }


def _listener_instance(runtime, shadow_enabled: bool):
    instance = object.__new__(runtime.ComelitRingRuntime)
    events: list[dict[str, object]] = []
    call_state: list[dict[str, object]] = []
    shadow = runtime.RingShadowController() if shadow_enabled else None
    instance._shadow_hook = runtime.RingShadowHook(shadow, runtime.SHADOW_OWNER_LISTENER)
    instance._native_marker_tail = []
    instance._canary_log_generation = None
    instance._canary_log_seen = set()
    instance._canary_log_value_emissions = {}
    instance._post_call_transport_flags = {}
    instance._post_call_transport_emitted = False
    instance._r64_post_call_snapshot = {}
    instance._r64_terminal_snapshot = {}
    instance._r64_pseudotcp_closed_before_open = False
    instance._r64_pseudotcp_closed_after_open = False
    instance._last_attached_stop_failure_stage = None
    instance._ring_lines = []
    instance._offer_ready = _FakeEvent()
    instance._listener_ready = _FakeEvent()
    instance._attached_media_busy = _FakeEvent()
    instance._attached_media_open = _FakeEvent()
    instance._attached_media_closed = _FakeEvent()
    instance._door_diagnostic = {}
    instance._door_result_future = None
    instance._media_diagnostics = _FakeDiagnostics()
    instance._call_state = _FakeCallState(call_state)
    instance._call_state_timeout_task = None
    instance._ring_media = None
    instance._synthetic_ring_media = None
    instance._notify_status = lambda: None
    instance._cancel_call_state_timeout = lambda: None
    instance._emit_post_call_transport_state_once = lambda: None

    async def emit(event):
        payload = dict(event)
        payload.setdefault("event_id", "<EVENT_ID>")
        events.append(payload)
        instance._last_ring_event = payload
        instance._call_state.ring_observed(payload["event_id"], payload.get("door", ""))

    instance._async_emit_ring_event = emit
    return instance, events, call_state


def _media_instance(media_transport, shadow_enabled: bool):
    instance = object.__new__(media_transport.ComelitEntranceMediaTransport)
    shadow = media_transport.RingShadowController() if shadow_enabled else None
    instance._shadow_hook = media_transport.RingShadowHook(shadow, media_transport.SHADOW_OWNER_MEDIA)
    instance._native_marker_tail = []
    instance._native_protocol_markers = []
    instance._native_protocol_markers_seen_total = 0
    instance._native_protocol_markers_evicted = 0
    instance._native_refresh_diagnostics = {}
    instance._native_ack_diagnostics = {}
    instance._progress = media_transport.MediaProgressDiagnostics(clock=lambda: 0.0)
    instance._process = None
    instance._offer_ready = _FakeEvent()
    instance._media_active = _FakeEvent()
    instance._video_forwarding = _FakeEvent()
    instance._audio_forwarding = _FakeEvent()
    instance._local_sdp_ready_event = _FakeEvent()
    instance._latency_timeline = None
    instance._status_listeners = set()
    instance._status_notify_handle = None
    instance._last_status_notify_monotonic = None
    instance._door_diagnostics = {}
    instance._door_result_future = None
    instance._last_error = None
    instance._ring_lines = []
    return instance, [], [], shadow


def run_listener_replay(repo_root: str, lines: list[str], *, shadow_enabled: bool) -> dict:
    runtime = _load_component_module(repo_root, "runtime")
    instance, events, call_state = _listener_instance(runtime, shadow_enabled)
    asyncio.run(instance._async_read_output(_FakeProcess(lines)))
    return _digest(instance, events, call_state)


def run_media_replay(
    repo_root: str,
    lines: list[str],
    *,
    shadow_enabled: bool,
    shadow_snapshots: list[dict[str, object]] | None = None,
) -> dict:
    media_transport = _load_component_module(repo_root, "media_transport")
    instance, events, call_state, shadow = _media_instance(media_transport, shadow_enabled)
    asyncio.run(instance._async_read_output(_FakeProcess(lines)))
    if shadow_snapshots is not None and shadow is not None:
        shadow_snapshots.append(shadow.snapshot())
    return _digest(instance, events, call_state)
