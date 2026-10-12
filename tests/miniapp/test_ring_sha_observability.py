from __future__ import annotations

import asyncio
import importlib.util
import logging
from pathlib import Path
import sys
import types


ROOT = Path(__file__).resolve().parents[2]
PKG_ROOT = ROOT / "custom_components/comelit"
FAKE_PACKAGE = "comelit_ring_sha_testpkg"

HEX64 = "0123456789abcdef" * 4


def _install_module(name: str, **attrs):
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    sys.modules[name] = module
    return module


def _install_import_stubs() -> None:
    restored_modules = {}
    for name in ("aiohttp", "homeassistant.config_entries", "homeassistant.core"):
        restored_modules[name] = sys.modules.get(name)
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
    _install_module(
        f"{FAKE_PACKAGE}.ring_media",
        RingMediaCoordinator=object,
    )
    _install_module(
        f"{FAKE_PACKAGE}.h264_recovery",
        H264RecoveryRtpShim=object,
    )
    _install_module(
        f"{FAKE_PACKAGE}.media_diagnostics",
        MediaCallDiagnostics=object,
        MediaProgressDiagnostics=object,
    )
    _install_module(
        f"{FAKE_PACKAGE}.sdp",
        ComelitSdpError=Exception,
        transform_offer=None,
    )
    for name, previous in restored_modules.items():
        if previous is not None:
            sys.modules[name] = previous


def _load_module(module_name: str):
    package = sys.modules.get(FAKE_PACKAGE) or _install_module(FAKE_PACKAGE)
    package.__path__ = [str(PKG_ROOT)]
    _install_import_stubs()
    spec = importlib.util.spec_from_file_location(
        f"{FAKE_PACKAGE}.{module_name}",
        PKG_ROOT / f"{module_name}.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


runtime = _load_module("runtime")
media_transport = _load_module("media_transport")


class _NoopDiagnostics:
    def observe_line(self, _line: str) -> None:
        return None


def _runtime_instance():
    instance = object.__new__(runtime.ComelitRingRuntime)
    instance._native_marker_tail = []
    instance._ring_lines = []
    instance._media_diagnostics = _NoopDiagnostics()
    instance._last_attached_stop_failure_stage = None
    instance._observe_canary_log_marker = lambda _line: None
    instance._observe_door_log_marker = lambda _line: None
    instance._record_r64_snapshot_marker = lambda _line: None
    instance._record_post_call_transport_marker = lambda _line: None
    instance._emit_post_call_transport_state_once = lambda: None
    instance._cancel_call_state_timeout = lambda: None
    instance._notify_status = lambda: None
    instance._call_state_tracker = lambda: types.SimpleNamespace(
        remote_release=lambda: False
    )
    instance._offer_ready = asyncio.Event()
    instance._listener_ready = asyncio.Event()
    instance._attached_media_busy = asyncio.Event()
    instance._attached_media_closed = asyncio.Event()
    instance._attached_media_open = asyncio.Event()
    instance._door_diagnostic = {}
    instance._door_result_future = None
    instance.emitted_events = []

    async def _emit(event):
        instance.emitted_events.append(dict(event))
        return event

    instance._async_emit_ring_event = _emit
    return instance


def _media_instance():
    instance = object.__new__(media_transport.ComelitEntranceMediaTransport)
    instance._native_marker_tail = []
    instance._native_protocol_markers = []
    instance._native_protocol_markers_seen_total = 0
    instance._native_protocol_markers_evicted = 0
    instance._native_refresh_diagnostics = {}
    instance._native_ack_diagnostics = {}
    return instance


def _remember_runtime(line: str) -> list[str]:
    instance = _runtime_instance()
    assert instance._remember_native_marker(line) is None
    return instance._native_marker_tail


def _remember_media(line: str) -> list[str]:
    instance = _media_instance()
    assert instance._remember_native_marker(line) is None
    return instance._native_marker_tail


def _ring_fingerprint_messages(caplog):
    return [
        record.message
        for record in caplog.records
        if record.message.startswith("Comelit ring fingerprint marker;")
    ]


def test_a1_runtime_target_sha_is_scalar_observable_but_not_collected(caplog):
    instance = _runtime_instance()

    with caplog.at_level(logging.INFO, logger=runtime.__name__):
        instance._remember_native_marker(f"V4_RING_FRAME_SHA256={HEX64}")

    assert _ring_fingerprint_messages(caplog) == [
        f"Comelit ring fingerprint marker; V4_RING_FRAME_SHA256={HEX64}"
    ]
    assert instance._native_marker_tail == ["V4_RING_FRAME_SHA256=<redacted>"]
    assert HEX64 not in repr(instance._native_marker_tail)


def test_a2_media_target_sha_is_scalar_observable_but_not_collected(caplog):
    instance = _media_instance()

    with caplog.at_level(logging.INFO, logger=media_transport.__name__):
        instance._remember_native_marker(f"V4_RING_RETRANSMIT_SHA256={HEX64.upper()}")

    assert _ring_fingerprint_messages(caplog) == [
        "Comelit ring fingerprint marker; "
        f"V4_RING_RETRANSMIT_SHA256={HEX64.upper()}"
    ]
    assert instance._native_marker_tail == [
        "V4_RING_RETRANSMIT_SHA256=<redacted>"
    ]
    assert instance._native_protocol_markers == [
        "V4_RING_RETRANSMIT_SHA256=<redacted>"
    ]
    assert HEX64.upper() not in repr(instance._native_marker_tail)
    assert HEX64.upper() not in repr(instance._native_protocol_markers)


def test_a3_target_sha63_is_redacted_without_scalar_log(caplog):
    line = f"V4_RING_FRAME_SHA256={HEX64[:-1]}"

    with caplog.at_level(logging.INFO):
        assert _remember_runtime(line) == ["V4_RING_FRAME_SHA256=<redacted>"]
        assert _remember_media(line) == ["V4_RING_FRAME_SHA256=<redacted>"]

    assert _ring_fingerprint_messages(caplog) == []


def test_a4_target_sha65_is_redacted_without_scalar_log(caplog):
    line = f"V4_RING_FRAME_SHA256={HEX64}0"

    with caplog.at_level(logging.INFO):
        assert _remember_runtime(line) == ["V4_RING_FRAME_SHA256=<redacted>"]
        assert _remember_media(line) == ["V4_RING_FRAME_SHA256=<redacted>"]

    assert _ring_fingerprint_messages(caplog) == []


def test_a5_target_non_hex_sha64_is_redacted_without_scalar_log(caplog):
    line = f"V4_RING_RETRANSMIT_SHA256={'g' * 64}"

    with caplog.at_level(logging.INFO):
        assert _remember_runtime(line) == [
            "V4_RING_RETRANSMIT_SHA256=<redacted>"
        ]
        assert _remember_media(line) == [
            "V4_RING_RETRANSMIT_SHA256=<redacted>"
        ]

    assert _ring_fingerprint_messages(caplog) == []


def test_a6_non_target_hex64_keys_are_redacted_without_scalar_log(caplog):
    lines = [
        f"UNKNOWN_KEY={HEX64}",
        f"TOKEN={HEX64}",
        f"V4_RING_DOOR={HEX64}",
    ]

    with caplog.at_level(logging.INFO):
        for line in lines:
            key = line.split("=", 1)[0]
            expected = [] if key in {"UNKNOWN_KEY", "TOKEN"} else [f"{key}=<redacted>"]
            assert _remember_runtime(line) == expected
            assert _remember_media(line) == expected

    assert _ring_fingerprint_messages(caplog) == []


def test_a7_existing_bool_int_and_enum_safe_values_still_pass():
    instance = _runtime_instance()

    instance._remember_native_marker("V4_RING_OBSERVED=true")
    instance._remember_native_marker("V4_DOOR_WRITE_COUNT=17")
    instance._remember_native_marker("P116_NATIVE_FAILURE_ID=PSEUDOTCP_CLOSED")

    assert instance._native_marker_tail == [
        "V4_RING_OBSERVED=true",
        "V4_DOOR_WRITE_COUNT=17",
        "P116_NATIVE_FAILURE_ID=PSEUDOTCP_CLOSED",
    ]


def test_a8_runtime_and_media_transport_sha_observability_parity(caplog):
    lines = [
        f"V4_RING_FRAME_SHA256={HEX64}",
        f"V4_RING_RETRANSMIT_SHA256={HEX64.upper()}",
        f"V4_RING_FRAME_SHA256={HEX64[:-1]}",
        f"V4_RING_FRAME_SHA256={HEX64}0",
        f"V4_RING_RETRANSMIT_SHA256={'g' * 64}",
        f"UNKNOWN_KEY={HEX64}",
        f"TOKEN={HEX64}",
        f"V4_RING_DOOR={HEX64}",
    ]

    with caplog.at_level(logging.INFO):
        for line in lines:
            assert _remember_runtime(line) == _remember_media(line)

    assert _ring_fingerprint_messages(caplog) == [
        f"Comelit ring fingerprint marker; V4_RING_FRAME_SHA256={HEX64}",
        f"Comelit ring fingerprint marker; V4_RING_FRAME_SHA256={HEX64}",
        "Comelit ring fingerprint marker; "
        f"V4_RING_RETRANSMIT_SHA256={HEX64.upper()}",
        "Comelit ring fingerprint marker; "
        f"V4_RING_RETRANSMIT_SHA256={HEX64.upper()}",
    ]


def test_a9_sha_marker_retention_shape_and_return_values_are_unchanged():
    runtime_instance = _runtime_instance()
    media_instance = _media_instance()

    assert (
        runtime_instance._remember_native_marker(f"V4_RING_FRAME_SHA256={HEX64}")
        is None
    )
    assert runtime_instance._native_marker_tail == [
        "V4_RING_FRAME_SHA256=<redacted>"
    ]
    assert runtime_instance._last_attached_stop_failure_stage is None

    assert (
        media_instance._remember_native_marker(f"V4_RING_FRAME_SHA256={HEX64}")
        is None
    )
    assert media_instance._native_marker_tail == ["V4_RING_FRAME_SHA256=<redacted>"]
    assert media_instance._native_protocol_markers == [
        "V4_RING_FRAME_SHA256=<redacted>"
    ]
    assert media_instance._native_protocol_markers_seen_total == 1
    assert media_instance._native_protocol_markers_evicted == 0


def test_b1_runtime_logs_frame_sha_fingerprint_scalar_only(caplog):
    instance = _runtime_instance()

    with caplog.at_level(logging.INFO, logger=runtime.__name__):
        instance._remember_native_marker(f"V4_RING_FRAME_SHA256={HEX64}")

    assert _ring_fingerprint_messages(caplog) == [
        f"Comelit ring fingerprint marker; V4_RING_FRAME_SHA256={HEX64}"
    ]
    assert instance._native_marker_tail == ["V4_RING_FRAME_SHA256=<redacted>"]


def test_b2_runtime_logs_retransmit_sha_fingerprint_scalar_only(caplog):
    instance = _runtime_instance()
    retransmit_sha = HEX64.upper()

    with caplog.at_level(logging.INFO, logger=runtime.__name__):
        instance._remember_native_marker(
            f"V4_RING_RETRANSMIT_SHA256={retransmit_sha}"
        )

    assert _ring_fingerprint_messages(caplog) == [
        "Comelit ring fingerprint marker; "
        f"V4_RING_RETRANSMIT_SHA256={retransmit_sha}"
    ]
    assert instance._native_marker_tail == [
        "V4_RING_RETRANSMIT_SHA256=<redacted>"
    ]


def test_b3_runtime_does_not_log_invalid_target_sha_values(caplog):
    instance = _runtime_instance()
    lines = [
        f"V4_RING_FRAME_SHA256={HEX64[:-1]}",
        f"V4_RING_FRAME_SHA256={HEX64}0",
        f"V4_RING_RETRANSMIT_SHA256={'g' * 64}",
    ]

    with caplog.at_level(logging.INFO, logger=runtime.__name__):
        for line in lines:
            instance._remember_native_marker(line)

    assert _ring_fingerprint_messages(caplog) == []
    assert instance._native_marker_tail == [
        "V4_RING_FRAME_SHA256=<redacted>",
        "V4_RING_FRAME_SHA256=<redacted>",
        "V4_RING_RETRANSMIT_SHA256=<redacted>",
    ]


def test_b4_runtime_does_not_log_non_target_keys_with_hex64(caplog):
    instance = _runtime_instance()
    lines = [
        f"UNKNOWN_KEY={HEX64}",
        f"TOKEN={HEX64}",
        f"V4_RING_DOOR={HEX64}",
    ]

    with caplog.at_level(logging.INFO, logger=runtime.__name__):
        for line in lines:
            instance._remember_native_marker(line)

    assert _ring_fingerprint_messages(caplog) == []
    assert instance._native_marker_tail == ["V4_RING_DOOR=<redacted>"]


def test_b5_media_transport_classifier_logs_and_returns_redacted_marker(caplog):
    instance = _media_instance()

    with caplog.at_level(logging.INFO, logger=media_transport.__name__):
        safe_marker = instance._safe_native_marker(
            f"V4_RING_FRAME_SHA256={HEX64}"
        )

    assert _ring_fingerprint_messages(caplog) == [
        f"Comelit ring fingerprint marker; V4_RING_FRAME_SHA256={HEX64}"
    ]
    assert safe_marker == ("V4_RING_FRAME_SHA256", "V4_RING_FRAME_SHA256=<redacted>")


def test_b6_runtime_fingerprint_log_has_no_tail_or_collection_dump(caplog):
    instance = _runtime_instance()

    with caplog.at_level(logging.INFO, logger=runtime.__name__):
        instance._remember_native_marker("V4_RING_OBSERVED=true")
        instance._remember_native_marker(f"V4_RING_FRAME_SHA256={HEX64}")
        instance._remember_native_marker("V4_RING_DOOR=entrance")

    messages = _ring_fingerprint_messages(caplog)
    assert messages == [
        f"Comelit ring fingerprint marker; V4_RING_FRAME_SHA256={HEX64}"
    ]
    log_line = messages[0]
    assert "safe_native_markers" not in log_line
    assert "[" not in log_line
    assert "V4_RING_OBSERVED" not in log_line
    assert "V4_RING_DOOR" not in log_line


def test_b7_media_collections_and_summary_logs_do_not_contain_target_sha(caplog):
    instance = _media_instance()

    with caplog.at_level(logging.INFO, logger=media_transport.__name__):
        instance._remember_native_marker(f"V4_RING_FRAME_SHA256={HEX64}")
        instance._emit_native_success_summary()

    assert instance._native_marker_tail == ["V4_RING_FRAME_SHA256=<redacted>"]
    assert instance._native_protocol_markers == ["V4_RING_FRAME_SHA256=<redacted>"]
    assert HEX64 not in repr(instance._native_marker_tail)
    assert HEX64 not in repr(instance._native_protocol_markers)

    summary_messages = [
        record.message
        for record in caplog.records
        if "safe_native_markers=" in record.message
        or "protocol_native_markers=" in record.message
    ]
    assert summary_messages
    assert all(HEX64 not in message for message in summary_messages)
    assert all("<redacted>" in message for message in summary_messages)


def test_b8_runtime_tail_after_target_marker_does_not_contain_sha_value():
    instance = _runtime_instance()

    instance._remember_native_marker(f"V4_RING_FRAME_SHA256={HEX64}")

    assert instance._native_marker_tail == ["V4_RING_FRAME_SHA256=<redacted>"]
    assert HEX64 not in repr(instance._native_marker_tail)


def test_c1_ring_probe_values_are_not_retained_in_runtime_or_media_tail(caplog):
    decimal_value = "123456"
    hex_value = "1234abcd"
    lines = [
        f"V4_RING_PHASE={decimal_value}",
        f"V4_RING_PEER_CONNECTION={decimal_value}",
        f"V4_RING_BODY_32_35={hex_value}",
        f"V4_RING_PARSE_STATUS={hex_value}",
    ]
    runtime_instance = _runtime_instance()
    media_instance = _media_instance()

    with caplog.at_level(logging.INFO):
        for line in lines:
            runtime_instance._remember_native_marker(line)
            media_instance._remember_native_marker(line)
        media_instance._emit_native_success_summary()

    assert runtime_instance._native_marker_tail == []
    assert media_instance._native_marker_tail == []
    assert media_instance._native_protocol_markers == []
    rendered = "\n".join(
        [
            repr(runtime_instance._native_marker_tail),
            repr(media_instance._native_marker_tail),
            repr(media_instance._native_protocol_markers),
            *(record.message for record in caplog.records),
        ]
    )
    assert decimal_value not in rendered
    assert hex_value not in rendered


def test_c2_ring_probe_markers_do_not_displace_failure_tail_entries():
    probe_lines = [
        "V4_RING_PHASE=INITIAL",
        "V4_RING_PEER_CONNECTION=000a",
        "V4_RING_BODY_32_35=1234abcd",
        "V4_RING_PARSE_STATUS=OK",
        "V4_RING_PHASE=RETRANSMIT",
        "V4_RING_PEER_CONNECTION=10",
    ]

    def runtime_tail(include_probes: bool) -> list[str]:
        instance = _runtime_instance()
        for index in range(runtime._NATIVE_MARKER_TAIL_LIMIT + 5):
            instance._remember_native_marker(f"P116_NATIVE_FAILURE_CODE={index}")
            if include_probes:
                for line in probe_lines:
                    instance._remember_native_marker(line)
        return list(instance._native_marker_tail)

    def media_tail(include_probes: bool) -> list[str]:
        instance = _media_instance()
        for index in range(media_transport._MEDIA_NATIVE_MARKER_TAIL_LIMIT + 5):
            instance._remember_native_marker(f"P116_NATIVE_FAILURE_CODE={index}")
            if include_probes:
                for line in probe_lines:
                    instance._remember_native_marker(line)
        return list(instance._native_marker_tail)

    runtime_with_probes = runtime_tail(include_probes=True)
    media_with_probes = media_tail(include_probes=True)

    assert runtime_with_probes == runtime_tail(include_probes=False)
    assert media_with_probes == media_tail(include_probes=False)
    assert all("V4_RING_PHASE" not in marker for marker in runtime_with_probes)
    assert all("V4_RING_PEER_CONNECTION" not in marker for marker in media_with_probes)
    assert all("V4_RING_BODY_32_35" not in marker for marker in runtime_with_probes)
    assert all("V4_RING_PARSE_STATUS" not in marker for marker in media_with_probes)
