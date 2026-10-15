from __future__ import annotations

import importlib.util
import asyncio
import logging
from pathlib import Path
import sys
import types


ROOT = Path(__file__).resolve().parents[2]
PKG_ROOT = ROOT / "custom_components/comelit"
FAKE_PACKAGE = "comelit_upstream_obs_testpkg"


def _install_module(name: str, **attrs):
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    sys.modules[name] = module
    return module


def _load_runtime():
    package = _install_module(FAKE_PACKAGE)
    package.__path__ = [str(PKG_ROOT)]
    restored_modules = {}
    for name in ("aiohttp", "homeassistant.config_entries", "homeassistant.core"):
        restored_modules[name] = sys.modules.get(name)
        sys.modules.pop(name, None)
    _install_module("aiohttp", ClientSession=object)
    _install_module("homeassistant.config_entries", ConfigEntry=object)
    _install_module("homeassistant.core", HomeAssistant=object)
    _install_module(
        f"{FAKE_PACKAGE}.cloud",
        ComelitCloudError=Exception,
        ComelitCloudHttpError=Exception,
        async_negotiate_p2p=None,
    )
    _install_module(
        f"{FAKE_PACKAGE}.oauth",
        ComelitOAuthError=Exception,
        ComelitOAuthManager=object,
    )
    _install_module(f"{FAKE_PACKAGE}.ring_media", RingMediaCoordinator=object)

    spec = importlib.util.spec_from_file_location(
        f"{FAKE_PACKAGE}.runtime",
        PKG_ROOT / "runtime.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        for name, previous in restored_modules.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous
    return module


def _load_media_transport():
    package_name = f"{FAKE_PACKAGE}_media"
    package = _install_module(package_name)
    package.__path__ = [str(PKG_ROOT)]
    restored_modules = {}
    for name in (
        "aiohttp",
        "homeassistant.config_entries",
        "homeassistant.core",
    ):
        restored_modules[name] = sys.modules.get(name)
        sys.modules.pop(name, None)
    _install_module("aiohttp", ClientSession=object)
    _install_module("homeassistant.config_entries", ConfigEntry=object)
    _install_module("homeassistant.core", HomeAssistant=object)
    _install_module(
        f"{package_name}.cloud",
        ComelitCloudError=Exception,
        async_negotiate_p2p=None,
    )
    _install_module(
        f"{package_name}.oauth",
        ComelitOAuthError=Exception,
        ComelitOAuthManager=object,
    )
    _install_module(f"{package_name}.h264_recovery", H264RecoveryRtpShim=object)

    spec = importlib.util.spec_from_file_location(
        f"{package_name}.media_transport",
        PKG_ROOT / "media_transport.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        for name, previous in restored_modules.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous
    return module


def _load_plain(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


runtime = _load_runtime()
media_transport = _load_media_transport()
media_diagnostics = _load_plain(PKG_ROOT / "media_diagnostics.py", "obs_media_diag")
ring_shadow = _load_plain(PKG_ROOT / "ring_shadow.py", "obs_ring_shadow")


def _runtime_instance():
    instance = object.__new__(runtime.ComelitRingRuntime)
    instance._native_marker_tail = []
    instance._native_marker_protected_tail = []
    instance._native_marker_high_rate_tail = []
    instance._native_marker_ctpp_trace_tail = []
    instance._native_marker_ctpp_trace_frames = []
    instance._canary_log_generation = None
    instance._canary_log_seen = set()
    instance._canary_log_value_emissions = {}
    instance._post_call_transport_flags = {}
    instance._post_call_transport_emitted = False
    instance._post_call_transport_emitted_state = None
    instance._r64_post_call_snapshot = {}
    instance._r64_terminal_snapshot = {}
    instance._r64_pseudotcp_closed_before_open = False
    instance._r64_pseudotcp_closed_after_open = False
    instance._last_native_failure_markers = []
    instance._last_attached_stop_failure_stage = None
    return instance


def _media_transport_instance():
    instance = object.__new__(media_transport.ComelitEntranceMediaTransport)
    instance._native_marker_tail = []
    instance._native_p116_marker_tail = []
    instance._native_protocol_markers = []
    instance._native_protocol_markers_seen_total = 0
    instance._native_protocol_markers_evicted = 0
    instance._native_refresh_diagnostics = {}
    instance._native_ack_diagnostics = {}
    instance._last_native_failure_markers = []
    instance._ring_probe_disclosure = None
    return instance


class _FakeHass:
    async def async_add_executor_job(self, func, *args):
        return func(*args)


class _FakeShadowHook:
    def note_state(self, _state):
        return None

    def observe_line(self, _line):
        return None


class _FakeEvent:
    def __init__(self) -> None:
        self._event = asyncio.Event()

    def set(self) -> None:
        self._event.set()

    def clear(self) -> None:
        if self._event.is_set():
            self._event = asyncio.Event()

    def is_set(self) -> bool:
        return self._event.is_set()

    async def wait(self) -> bool:
        await self._event.wait()
        return True


class _DelayedFinalStdout:
    def __init__(self, ready: asyncio.Event) -> None:
        self._ready = ready
        self._index = 0

    async def readline(self) -> bytes:
        self._index += 1
        if self._index == 1:
            return b"R42_MEDIA_CHANNEL_CLOSED=true\n"
        if self._index == 2:
            await self._ready.wait()
            return b"P116_NATIVE_EXIT_INTENTIONAL_STOP=true\n"
        return b""


class _StopProcess:
    pid = 12345

    def __init__(self) -> None:
        self.returncode = None
        self._ready = asyncio.Event()
        self.stdout = _DelayedFinalStdout(self._ready)

    async def wait(self) -> int:
        self.returncode = 0
        self._ready.set()
        return 0


def test_real_failure_and_intentional_pause_are_distinguishable():
    failed = _runtime_instance()
    failed._remember_native_marker("P116_NATIVE_EXIT_INTENTIONAL_STOP=false")
    failed._remember_native_marker("P116_NATIVE_FAILURE_ID=PSEUDOTCP_CLOSED")
    failed._capture_native_failure(6)

    paused = _runtime_instance()
    paused._remember_native_marker("P116_NATIVE_EXIT_INTENTIONAL_STOP=true")
    paused._capture_native_failure(6)

    assert "P116_NATIVE_FAILURE_ID=PSEUDOTCP_CLOSED" in failed._last_native_failure_markers
    assert "P116_NATIVE_EXIT_INTENTIONAL_STOP=true" in paused._last_native_failure_markers
    assert not any(
        marker.startswith("P116_NATIVE_FAILURE_ID=")
        for marker in paused._last_native_failure_markers
    )


def test_async_stop_drains_final_intentional_pause_line_and_real_failure_remains_visible(
    caplog, monkeypatch
):
    async def run_stop_path():
        instance = _runtime_instance()
        instance._hass = _FakeHass()
        instance._shadow_hook = _FakeShadowHook()
        instance._cancel_call_state_timeout = lambda: None
        instance._call_state_tracker = lambda: types.SimpleNamespace(reset=lambda: None)
        instance._notify_status = lambda: None
        instance._media_diagnostics = types.SimpleNamespace(observe_line=lambda _line: None)
        instance._listener_ready = _FakeEvent()
        instance._attached_media_busy = _FakeEvent()
        instance._attached_media_open = _FakeEvent()
        instance._attached_media_closed = _FakeEvent()
        instance._process = _StopProcess()
        instance._task = asyncio.create_task(instance._async_read_output(instance._process))

        await instance.async_stop()
        return instance

    monkeypatch.setattr(runtime, "_touch_stop", lambda: None)
    monkeypatch.setattr(runtime, "_remove_door_target", lambda: None)
    monkeypatch.setattr(runtime, "_remove_helper_secret", lambda: None)

    caplog.clear()
    with caplog.at_level(logging.INFO, logger=runtime.__name__):
        instance = asyncio.run(run_stop_path())

    rendered = "\n".join(record.message for record in caplog.records)
    assert "marker=P116_NATIVE_EXIT_INTENTIONAL_STOP value=true" in rendered
    assert "marker=POST_CALL_TRANSPORT_STATE value=MEDIA_CLOSED_CALL_OPEN" in rendered
    assert "P116_NATIVE_EXIT_INTENTIONAL_STOP=true" in instance._native_marker_tail
    assert not any(
        marker.startswith("P116_NATIVE_FAILURE_ID=PSEUDOTCP_CLOSED")
        for marker in instance._native_marker_tail
    )

    with caplog.at_level(logging.INFO, logger=runtime.__name__):
        instance._record_post_call_transport_marker(
            "P116_NATIVE_EXIT_INTENTIONAL_STOP=false"
        )
        instance._record_post_call_transport_marker(
            "P116_NATIVE_FAILURE_ID=PSEUDOTCP_CLOSED"
        )
        instance._remember_native_marker("P116_NATIVE_FAILURE_ID=PSEUDOTCP_CLOSED")
        instance._remember_native_marker("P116_NATIVE_FAILURE_COUNT=1")
        instance._emit_post_call_transport_state_once()
        instance._capture_native_failure(6)

    rerendered = "\n".join(record.message for record in caplog.records)
    assert "marker=POST_CALL_TRANSPORT_STATE value=TRANSPORT_CLOSED" not in rerendered
    assert "P116_NATIVE_FAILURE_ID=PSEUDOTCP_CLOSED" in (
        instance._last_native_failure_markers
    )


def test_bounded_pseudotcp_error_serialization_rejects_free_text():
    instance = _runtime_instance()
    instance._remember_native_marker("PSEUDOTCP_CLOSED_CALLBACK_ERROR=104")
    instance._remember_native_marker("PSEUDOTCP_CLOSED_CALLBACK_ERROR=errno=104")

    assert "PSEUDOTCP_CLOSED_CALLBACK_ERROR=104" in instance._native_marker_tail
    assert "PSEUDOTCP_CLOSED_CALLBACK_ERROR=<redacted>" in instance._native_marker_tail
    assert "errno=104" not in "\n".join(instance._native_marker_tail)


def test_media_rtp_freshness_markers_reach_snapshot():
    diag = media_diagnostics.MediaCallDiagnostics()
    for line in (
        "R42_CALL_GENERATION=7",
        "VIDEO_PACKET_COUNT_AT_REPEAT=12",
        "AUDIO_PACKET_COUNT_AT_REPEAT=4",
        "LAST_VIDEO_RTP_MONOTONIC_MS=123456",
        "LAST_AUDIO_RTP_MONOTONIC_MS=123400",
    ):
        assert diag.observe_line(line)

    snapshot = diag.snapshot()
    assert snapshot["video_packet_count_at_repeat"] == 12
    assert snapshot["audio_packet_count_at_repeat"] == 4
    assert snapshot["last_video_rtp_monotonic_ms"] == 123456
    assert snapshot["last_audio_rtp_monotonic_ms"] == 123400


def test_rx_stalled_is_diagnostic_only_and_does_not_close_session():
    diag = media_diagnostics.MediaCallDiagnostics()
    for line in (
        "R42_CALL_GENERATION=9",
        "RX_STALLED=true",
        "RTP_STALL_SECONDS=8",
    ):
        assert diag.observe_line(line)

    snapshot = diag.snapshot()
    assert snapshot["rx_stalled"] is True
    assert snapshot["rtp_stall_seconds"] == 8
    assert snapshot["channel_closed"] is False
    assert snapshot["cleanup_complete"] is False


def test_ctpp_header_trace_is_headers_only_and_sanitized():
    instance = _runtime_instance()
    for line in (
        "CTPP_TRACE_DIRECTION=IN",
        "CTPP_TRACE_OPCODE=17",
        "CTPP_TRACE_TYPE=26",
        "CTPP_TRACE_CHANNEL=7449",
        "CTPP_TRACE_LENGTH=72",
        "CTPP_TRACE_MONOTONIC_MS=555",
        "CTPP_TRACE_PAYLOAD=deadbeef",
        "CTPP_TRACE_HEX=001122",
    ):
        instance._remember_native_marker(line)

    rendered = "\n".join(instance._native_marker_ctpp_trace_tail)
    assert "CTPP_TRACE_DIRECTION=IN" in rendered
    assert "CTPP_TRACE_LENGTH=72" in rendered
    assert "deadbeef" not in rendered
    assert "001122" not in rendered
    assert "CTPP_TRACE_PAYLOAD" not in rendered
    assert "CTPP_TRACE_HEX" not in rendered


def test_long_uptime_monotonic_values_survive_scoped_validation():
    instance = _runtime_instance()
    long_value = "10000000000"
    for line in (
        f"LAST_VIDEO_RTP_MONOTONIC_MS={long_value}",
        f"LAST_AUDIO_RTP_MONOTONIC_MS={long_value}",
        f"CTPP_TRACE_MONOTONIC_MS={long_value}",
        f"V4_RING_MONOTONIC_MS={long_value}",
        f"P116_NATIVE_FAILURE_COUNT={long_value}",
    ):
        instance._remember_native_marker(line)

    rendered = "\n".join(instance._native_marker_tail)
    high_rate = "\n".join(instance._native_marker_high_rate_tail)
    assert f"LAST_VIDEO_RTP_MONOTONIC_MS={long_value}" in high_rate
    assert f"LAST_AUDIO_RTP_MONOTONIC_MS={long_value}" in high_rate
    assert f"CTPP_TRACE_MONOTONIC_MS={long_value}" in "\n".join(
        instance._native_marker_ctpp_trace_tail
    )
    assert f"V4_RING_MONOTONIC_MS={long_value}" in high_rate
    assert f"V4_RING_MONOTONIC_MS={long_value}" not in rendered
    assert f"P116_NATIVE_FAILURE_COUNT={long_value}" not in rendered


def test_protected_retention_survives_tail_eviction():
    instance = _runtime_instance()
    instance._remember_native_marker("PSEUDOTCP_CLOSED_CALLBACK_ERROR=104")
    instance._remember_native_marker("RX_STALLED=true")
    for index in range(runtime._NATIVE_MARKER_TAIL_LIMIT + 5):
        instance._remember_native_marker(f"P116_NATIVE_FAILURE_COUNT={index}")
    instance._capture_native_failure(6)

    assert "PSEUDOTCP_CLOSED_CALLBACK_ERROR=104" in instance._last_native_failure_markers
    assert "RX_STALLED=true" in instance._last_native_failure_markers


def test_ctpp_trace_cannot_evict_non_trace_failure_window():
    instance = _runtime_instance()
    instance._remember_native_marker("PSEUDOTCP_CLOSED_CALLBACK_ERROR=104")
    instance._remember_native_marker("VIDEO_PACKET_COUNT_AT_REPEAT=12")
    instance._remember_native_marker("RX_STALLED=true")
    for index in range(runtime._NATIVE_MARKER_CTPP_TRACE_LIMIT + 10):
        for line in (
            "CTPP_TRACE_DIRECTION=IN",
            f"CTPP_TRACE_OPCODE={index}",
            "CTPP_TRACE_TYPE=26",
            "CTPP_TRACE_CHANNEL=7449",
            "CTPP_TRACE_LENGTH=72",
            f"CTPP_TRACE_MONOTONIC_MS={1000 + index}",
        ):
            instance._remember_native_marker(line)
    instance._capture_native_failure(6)

    assert "PSEUDOTCP_CLOSED_CALLBACK_ERROR=104" in instance._last_native_failure_markers
    assert "VIDEO_PACKET_COUNT_AT_REPEAT=12" in instance._last_native_failure_markers
    assert "RX_STALLED=true" in instance._last_native_failure_markers
    assert "PSEUDOTCP_CLOSED_CALLBACK_ERROR=104" in instance._native_marker_tail
    assert not any(
        marker.startswith("CTPP_TRACE_")
        for marker in instance._native_marker_tail
    )
    assert len(instance._native_marker_ctpp_trace_tail) == runtime._NATIVE_MARKER_CTPP_TRACE_LIMIT


def test_failure_window_self_flood_is_coalesced_without_unbounded_storage():
    instance = _runtime_instance()
    instance._remember_native_marker("PSEUDOTCP_CLOSED_CALLBACK_ERROR=104")
    for index in range(80):
        instance._remember_native_marker(f"VIDEO_PACKET_COUNT_AT_REPEAT={index}")
        instance._remember_native_marker(f"AUDIO_PACKET_COUNT_AT_REPEAT={index}")
        instance._remember_native_marker(f"LAST_VIDEO_RTP_MONOTONIC_MS={1000 + index}")
        instance._remember_native_marker(f"LAST_AUDIO_RTP_MONOTONIC_MS={1000 + index}")
        instance._remember_native_marker("RX_STALLED=true")
        instance._remember_native_marker("RTP_STALL_SECONDS=8")
        instance._remember_native_marker(f"V4_RING_MONOTONIC_MS={1000 + index}")
    instance._capture_native_failure(6)

    assert "PSEUDOTCP_CLOSED_CALLBACK_ERROR=104" in instance._last_native_failure_markers
    assert len(instance._native_marker_high_rate_tail) <= (
        runtime._NATIVE_MARKER_HIGH_RATE_DIAGNOSTIC_LIMIT
    )
    assert len(instance._native_marker_tail) <= runtime._NATIVE_MARKER_TAIL_LIMIT
    assert instance._native_marker_tail == ["PSEUDOTCP_CLOSED_CALLBACK_ERROR=104"]


def test_high_rate_diagnostics_do_not_evict_failure_window_markers():
    instance = _runtime_instance()
    for index in range(runtime._NATIVE_MARKER_TAIL_LIMIT):
        instance._remember_native_marker(f"P116_NATIVE_FAILURE_COUNT={index}")
    original_tail = list(instance._native_marker_tail)
    for index in range(80):
        instance._remember_native_marker(f"VIDEO_PACKET_COUNT_AT_REPEAT={index}")
        instance._remember_native_marker(f"AUDIO_PACKET_COUNT_AT_REPEAT={index}")
        instance._remember_native_marker(f"LAST_VIDEO_RTP_MONOTONIC_MS={1000 + index}")
        instance._remember_native_marker(f"LAST_AUDIO_RTP_MONOTONIC_MS={1000 + index}")
        instance._remember_native_marker("RX_STALLED=true")
        instance._remember_native_marker("RTP_STALL_SECONDS=8")

    assert instance._native_marker_tail == original_tail
    assert len(instance._native_marker_high_rate_tail) <= (
        runtime._NATIVE_MARKER_HIGH_RATE_DIAGNOSTIC_LIMIT
    )


def test_ctpp_trace_retention_preserves_frame_grouping_with_repeated_values():
    instance = _runtime_instance()
    for index in range(runtime._NATIVE_MARKER_CTPP_TRACE_FRAME_LIMIT + 2):
        for line in (
            "CTPP_TRACE_DIRECTION=IN",
            "CTPP_TRACE_OPCODE=17",
            "CTPP_TRACE_TYPE=26",
            f"CTPP_TRACE_CHANNEL={7400 + index}",
            "CTPP_TRACE_LENGTH=72",
            f"CTPP_TRACE_MONOTONIC_MS={5000 + index}",
        ):
            instance._remember_native_marker(line)
    instance._capture_native_failure(6)

    trace = [
        marker
        for marker in instance._last_native_failure_markers
        if marker.startswith("CTPP_TRACE_")
    ]
    assert len(instance._native_marker_ctpp_trace_frames) == (
        runtime._NATIVE_MARKER_CTPP_TRACE_FRAME_LIMIT
    )
    assert trace[0].startswith("CTPP_TRACE_DIRECTION=")
    assert trace[6].startswith("CTPP_TRACE_DIRECTION=")
    assert trace.count("CTPP_TRACE_DIRECTION=IN") == (
        runtime._NATIVE_MARKER_CTPP_TRACE_FRAME_LIMIT
    )


def test_status_failure_marker_attribute_is_public_bounded_projection():
    instance = _runtime_instance()
    for index in range(25):
        instance._last_native_failure_markers.append(f"P116_NATIVE_FAILURE_COUNT={index}")
    instance._last_native_failure_markers.extend(
        [
            "LAST_VIDEO_RTP_MONOTONIC_MS=10000000000",
            "CTPP_TRACE_DIRECTION=IN",
            "CTPP_TRACE_MONOTONIC_MS=10000000001",
            "P116_NATIVE_FAILURE_ID=PSEUDOTCP_CLOSED",
        ]
    )

    public = instance._public_native_failure_markers()

    assert len(public) <= 20
    assert public[-1] == "P116_NATIVE_FAILURE_ID=PSEUDOTCP_CLOSED"
    assert not any("_MONOTONIC_MS=" in marker for marker in public)
    assert not any(marker.startswith("CTPP_TRACE_") for marker in public)


def test_status_failure_marker_attribute_uses_persisted_failure_snapshot():
    instance = _runtime_instance()
    instance._remember_native_marker("R54_CALL_ADOPTION_STARTED=true")
    instance._remember_native_marker("P116_NATIVE_FAILURE_COUNT=0")

    assert instance._public_native_failure_markers() == []

    instance._remember_native_marker("P116_NATIVE_FAILURE_ID=PSEUDOTCP_CLOSED")
    instance._capture_native_failure(6)
    instance._native_marker_tail.clear()
    instance._remember_native_marker("R54_INVITE_ACK_SENT=true")
    instance._remember_native_marker("P116_NATIVE_FAILURE_COUNT=0")

    public = instance._public_native_failure_markers()

    # The failure-time window is published as on base; markers of the
    # restarted healthy session are not.
    assert public == [
        "R54_CALL_ADOPTION_STARTED=true",
        "P116_NATIVE_FAILURE_ID=PSEUDOTCP_CLOSED",
    ]


def test_status_failure_marker_attribute_uses_chronological_failure_snapshot():
    instance = _runtime_instance()
    for index in range(1, 19):
        instance._remember_native_marker(f"P116_NATIVE_FAILURE_COUNT={index}")
    instance._remember_native_marker("P116_NATIVE_EXIT_CODE=6")
    instance._remember_native_marker("P116_NATIVE_FAILURE_ID=PSEUDOTCP_CLOSED")
    instance._native_marker_protected_tail.extend(
        [
            "VIDEO_PACKET_COUNT_AT_REPEAT=0",
            "P116_NATIVE_FAILURE_COUNT=older-copy",
        ]
    )
    instance._capture_native_failure(6)

    public = instance._public_native_failure_markers()

    assert len(public) == runtime._NATIVE_PUBLIC_FAILURE_MARKER_LIMIT
    assert public[-2:] == [
        "P116_NATIVE_EXIT_CODE=6",
        "P116_NATIVE_FAILURE_ID=PSEUDOTCP_CLOSED",
    ]
    assert "VIDEO_PACKET_COUNT_AT_REPEAT=0" not in public
    assert "P116_NATIVE_FAILURE_COUNT=older-copy" not in public


def test_status_failure_marker_attribute_publishes_r54_r64_failure_evidence():
    instance = _runtime_instance()
    evidence = [
        "R54_CALL_ADOPTION_STARTED=true",
        "R54_TX_STATE=WAIT_PEER_DATA_ACK_FLUSH",
        "R54_TX_SUBJECT=MEDIA_STOP",
        "R54_TX_QUEUE_FAIL_COUNT=1",
        "ICE_HOLDER_STOP=true",
        "SELECTED_PAIR_COUNT=1",
        "PSEUDOTCP_CLOSED_CALLBACK=true",
        "PSEUDOTCP_GRACEFUL_CLOSE_TIMEOUT=true",
        "R64_TERMINAL_SNAPSHOT=true",
        "R64_TERMINAL_TX_STATE=TERMINAL_FAILURE",
        "R64_POST_CALL_SNAPSHOT=true",
        "R64_POST_CALL_REMOTE_RELEASE_OBSERVED=true",
        "P116_NATIVE_FAILURE_ID=PSEUDOTCP_CLOSED",
    ]
    for line in evidence:
        instance._remember_native_marker(line)
    for line in (
        "VIDEO_PACKET_COUNT_AT_REPEAT=12",
        "LAST_VIDEO_RTP_MONOTONIC_MS=10000000000",
        "CTPP_TRACE_DIRECTION=IN",
        "CTPP_TRACE_MONOTONIC_MS=10000000001",
        "V4_RING_MONOTONIC_MS=10000000002",
    ):
        instance._remember_native_marker(line)
    instance._capture_native_failure(6)

    public = instance._public_native_failure_markers()

    assert public == evidence
    assert not any("_MONOTONIC_MS=" in marker for marker in public)
    assert not any(marker.startswith("CTPP_TRACE_") for marker in public)


def test_status_failure_marker_attribute_bound_keeps_protected_copies():
    instance = _runtime_instance()
    instance._remember_native_marker("PSEUDOTCP_CLOSED_CALLBACK_ERROR=104")
    instance._remember_native_marker("P116_NATIVE_EXIT_INTENTIONAL_STOP=false")
    for index in range(1, runtime._NATIVE_MARKER_TAIL_LIMIT + 1):
        instance._remember_native_marker(f"R54_TX_QUEUE_FAIL_COUNT={index}")
    instance._capture_native_failure(6)

    public = instance._public_native_failure_markers()

    assert len(public) == runtime._NATIVE_PUBLIC_FAILURE_MARKER_LIMIT
    assert public[:2] == [
        "PSEUDOTCP_CLOSED_CALLBACK_ERROR=104",
        "P116_NATIVE_EXIT_INTENTIONAL_STOP=false",
    ]
    assert public[-1] == (
        f"R54_TX_QUEUE_FAIL_COUNT={runtime._NATIVE_MARKER_TAIL_LIMIT}"
    )


def test_public_failure_marker_whitelist_removed():
    assert not hasattr(runtime, "_PUBLIC_NATIVE_FAILURE_MARKER_KEYS")


def test_new_observability_fields_are_canary_log_reachable(caplog):
    caplog.set_level("INFO", logger=runtime.__name__)
    instance = _runtime_instance()
    for line in (
        "PSEUDOTCP_CLOSED_CALLBACK_ERROR=104",
        "P116_NATIVE_EXIT_INTENTIONAL_STOP=true",
        "VIDEO_PACKET_COUNT_AT_REPEAT=12",
        "AUDIO_PACKET_COUNT_AT_REPEAT=4",
        "LAST_VIDEO_RTP_MONOTONIC_MS=10000000000",
        "LAST_AUDIO_RTP_MONOTONIC_MS=10000000001",
        "RX_STALLED=true",
        "RTP_STALL_SECONDS=16",
        "CTPP_TRACE_DIRECTION=IN",
        "CTPP_TRACE_OPCODE=17",
        "CTPP_TRACE_TYPE=26",
        "CTPP_TRACE_CHANNEL=7449",
        "CTPP_TRACE_LENGTH=72",
        "CTPP_TRACE_MONOTONIC_MS=10000000002",
        "V4_RING_MONOTONIC_MS=10000000003",
    ):
        instance._observe_canary_log_marker(line)

    rendered = "\n".join(record.message for record in caplog.records)
    for key in (
        "PSEUDOTCP_CLOSED_CALLBACK_ERROR",
        "P116_NATIVE_EXIT_INTENTIONAL_STOP",
        "VIDEO_PACKET_COUNT_AT_REPEAT",
        "AUDIO_PACKET_COUNT_AT_REPEAT",
        "LAST_VIDEO_RTP_MONOTONIC_MS",
        "LAST_AUDIO_RTP_MONOTONIC_MS",
        "RX_STALLED",
        "RTP_STALL_SECONDS",
        "CTPP_TRACE_DIRECTION",
        "CTPP_TRACE_OPCODE",
        "CTPP_TRACE_TYPE",
        "CTPP_TRACE_CHANNEL",
        "CTPP_TRACE_LENGTH",
        "CTPP_TRACE_MONOTONIC_MS",
        "V4_RING_MONOTONIC_MS",
    ):
        assert f"marker={key}" in rendered


def test_observability_canary_repeated_identical_events_keep_ordered_lines(caplog):
    caplog.set_level("INFO", logger=runtime.__name__)
    instance = _runtime_instance()
    for _index in range(3):
        instance._observe_canary_log_marker("RX_STALLED=true")

    records = [
        record.message
        for record in caplog.records
        if "marker=RX_STALLED value=true" in record.message
    ]
    assert records == [
        "Comelit canary evidence RX_STALLED marker=RX_STALLED value=true",
        "Comelit canary evidence RX_STALLED marker=RX_STALLED value=true",
        "Comelit canary evidence RX_STALLED marker=RX_STALLED value=true",
    ]


def test_observability_canary_repeated_events_are_bounded(caplog):
    caplog.set_level("INFO", logger=runtime.__name__)
    instance = _runtime_instance()
    for _index in range(runtime._OBSERVABILITY_CANARY_EVENT_LIMIT_PER_KEY + 5):
        instance._observe_canary_log_marker("RX_STALLED=true")

    records = [
        record.message
        for record in caplog.records
        if "marker=RX_STALLED value=true" in record.message
    ]
    assert len(records) == runtime._OBSERVABILITY_CANARY_EVENT_LIMIT_PER_KEY


def test_media_transport_new_prefixes_are_retained_and_sanitized():
    instance = _media_transport_instance()
    for line in (
        "VIDEO_PACKET_COUNT_AT_REPEAT=12",
        "AUDIO_PACKET_COUNT_AT_REPEAT=4",
        "LAST_VIDEO_RTP_MONOTONIC_MS=10000000000",
        "LAST_AUDIO_RTP_MONOTONIC_MS=10000000001",
        "RX_STALLED=true",
        "RTP_STALL_SECONDS=8",
        "VIDEO_PACKET_COUNT_AT_REPEAT=secret",
    ):
        instance._remember_native_marker(line)

    rendered = "\n".join(instance._native_marker_tail)
    assert "VIDEO_PACKET_COUNT_AT_REPEAT=12" in rendered
    assert "AUDIO_PACKET_COUNT_AT_REPEAT=4" in rendered
    assert "LAST_VIDEO_RTP_MONOTONIC_MS=10000000000" in rendered
    assert "LAST_AUDIO_RTP_MONOTONIC_MS=10000000001" in rendered
    assert "RX_STALLED=true" in rendered
    assert "RTP_STALL_SECONDS=8" in rendered
    assert "VIDEO_PACKET_COUNT_AT_REPEAT=<redacted>" in rendered
    assert "secret" not in rendered


def test_media_transport_p116_markers_survive_widened_prefix_tail_pressure(caplog):
    instance = _media_transport_instance()
    instance._remember_native_marker("P116_VIDEO_SPS_COUNT=1")
    instance._remember_native_marker("P116_AUDIO_COUNT=2")
    for index in range(media_transport._MEDIA_NATIVE_MARKER_TAIL_LIMIT + 20):
        instance._remember_native_marker(f"VIDEO_PACKET_COUNT_AT_REPEAT={index}")

    instance._capture_native_failure(6)
    assert "P116_VIDEO_SPS_COUNT=1" in instance._last_native_failure_markers
    assert "P116_AUDIO_COUNT=2" in instance._last_native_failure_markers

    with caplog.at_level(logging.INFO, logger=media_transport.__name__):
        instance._emit_native_success_summary()
    rendered = "\n".join(record.message for record in caplog.records)
    assert "p116_native_markers=['P116_VIDEO_SPS_COUNT=1', " in rendered
    assert "P116_AUDIO_COUNT=2" in rendered


def test_media_transport_failure_marker_attribute_keeps_base_bound():
    instance = _media_transport_instance()
    for index in range(media_transport._MEDIA_NATIVE_MARKER_TAIL_LIMIT + 20):
        instance._last_native_failure_markers.append(f"P116_NATIVE_FAILURE_COUNT={index}")

    public = instance.last_native_failure_markers

    assert len(public) == media_transport._MEDIA_NATIVE_MARKER_TAIL_LIMIT
    assert public[0] == "P116_NATIVE_FAILURE_COUNT=20"
    assert public[-1] == "P116_NATIVE_FAILURE_COUNT=59"


def test_media_transport_failure_snapshot_is_chronological_and_keeps_p116_copies():
    instance = _media_transport_instance()
    instance._remember_native_marker("P116_VIDEO_SPS_COUNT=1")
    instance._remember_native_marker("P116_AUDIO_COUNT=2")
    limit = media_transport._MEDIA_NATIVE_MARKER_TAIL_LIMIT
    for index in range(limit):
        instance._remember_native_marker(f"VIDEO_PACKET_COUNT_AT_REPEAT={index}")
    instance._remember_native_marker("P116_NATIVE_FAILURE_COUNT=3")

    instance._capture_native_failure(6)
    snapshot = instance._last_native_failure_markers

    assert len(snapshot) == limit
    # Evicted (older) P116 copies precede every fresher tail marker.
    assert snapshot[:2] == ["P116_VIDEO_SPS_COUNT=1", "P116_AUDIO_COUNT=2"]
    assert snapshot[-1] == "P116_NATIVE_FAILURE_COUNT=3"
    # The bound drops the oldest non-P116 tail entries (V0 already left the
    # 40-entry tail; V1/V2 make room for the two P116 copies).
    assert snapshot[2] == "VIDEO_PACKET_COUNT_AT_REPEAT=3"


def test_t16_ring_probe_identity_semantics_unchanged_with_monotonic_timestamp():
    controller = ring_shadow.RingShadowController()
    controller.note_state(ring_shadow.SHADOW_OWNER_LISTENER, "listener_start")
    for line in (
        "V4_RING_PHASE=INITIAL",
        "V4_RING_MONOTONIC_MS=123",
        "V4_RING_PEER_CONNECTION=000a",
        "V4_RING_BODY_32_35=1234abcd",
        "V4_RING_PARSE_STATUS=OK",
        "V4_RING_OBSERVED=true",
        "V4_RING_DIRECTION=DEVICE_TO_CLIENT",
        "V4_RING_KIND=CALL_INIT",
        "V4_RING_DOOR=entrance",
        "V4_RING_SOURCE=00000643",
    ):
        controller.observe_native_line(ring_shadow.SHADOW_OWNER_LISTENER, line)

    record = controller.snapshot()["probe"]["records"][-1]
    assert record["peer_connection_present"] is True
    assert record["body_32_35_present"] is True
    assert record["monotonic_ms"] == 123
    assert ring_shadow.OWNER_GENERATION_IS_CALL_IDENTITY is False
    assert ring_shadow.HANDOFF_EPOCH_IS_CALL_IDENTITY is False
