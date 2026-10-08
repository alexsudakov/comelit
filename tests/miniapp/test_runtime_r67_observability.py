from __future__ import annotations

import importlib.util
import logging
from pathlib import Path
import sys
import types


ROOT = Path(__file__).resolve().parents[2]
PKG_ROOT = ROOT / "custom_components/comelit"
FAKE_PACKAGE = "comelit_runtime_r67_testpkg"


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


runtime = _load_runtime()


def _runtime_instance():
    instance = object.__new__(runtime.ComelitRingRuntime)
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
    return instance


R67_MARKER_VALUES = {
    "R67_ATTACHED_REFRESH_CALL_GENERATION": "42",
    "R67_ATTACHED_REFRESH_SESSION_RESET": "true",
    "R67_ATTACHED_REFRESH_SESSION_RESET_REASON": "new-session",
    "R67_ATTACHED_REFRESH_CHANNEL_GENERATION": "7",
    "R67_ATTACHED_REFRESH_TIMER_ARMED": "true",
    "R67_ATTACHED_REFRESH_TIMER_SOURCE_ID": "123",
    "R67_ATTACHED_REFRESH_QUEUED": "true",
    "R67_ATTACHED_REFRESH_QUEUED_COUNT": "1",
    "R67_ATTACHED_REFRESH_SENT_COUNT": "1",
    "R67_ATTACHED_REFRESH_FIRST_AGE_SECONDS": "15",
    "R67_ATTACHED_REFRESH_LAST_AGE_SECONDS": "15",
    "R67_ATTACHED_REFRESH_LAST_RESULT": "SENT",
    "R67_ATTACHED_REFRESH_LAST_ERROR": "NONE",
    "R67_ATTACHED_REFRESH_OUTSTANDING": "false",
    "R67_ATTACHED_REFRESH_OPCODE": "0x0011",
    "R67_ATTACHED_REFRESH_FRAME": "MEDIAREQ26_OPEN",
    "R67_ATTACHED_REFRESH_TIMER_REMOVED": "true",
    "R67_ATTACHED_REFRESH_TIMER_REMOVE_REASON": "tx-complete",
    "R67_ATTACHED_REFRESH_CANCELLED": "true",
    "R67_ATTACHED_REFRESH_CANCEL_REASON": "call-teardown",
    "R67_ATTACHED_REFRESH_STALE_TIMER_IGNORED": "true",
    "R67_ATTACHED_REFRESH_CANCELLED_COMPLETION_IGNORED": "true",
    "R67_ATTACHED_REFRESH_STALE_GENERATION": "true",
}


def test_r67_allowlisted_markers_reach_tail_and_canary_log(caplog):
    instance = _runtime_instance()

    with caplog.at_level(logging.INFO, logger=runtime.__name__):
        for key, value in R67_MARKER_VALUES.items():
            line = f"{key}={value}"
            instance._remember_native_marker(line)
            instance._observe_canary_log_marker(line)

    messages = "\n".join(record.message for record in caplog.records)
    for key, value in R67_MARKER_VALUES.items():
        assert f"marker={key} value={value}" in messages

        tail_instance = _runtime_instance()
        tail_instance._remember_native_marker(f"{key}={value}")
        assert tail_instance._native_marker_tail == [f"{key}={value}"]


def test_unknown_r67_marker_is_dropped_from_tail_and_canary_log(caplog):
    instance = _runtime_instance()

    with caplog.at_level(logging.INFO, logger=runtime.__name__):
        instance._remember_native_marker("R67_ATTACHED_REFRESH_SEQUENCE_AFTER=9")
        instance._observe_canary_log_marker("R67_ATTACHED_REFRESH_SEQUENCE_AFTER=9")

    assert instance._native_marker_tail == []
    assert not caplog.records


def test_r67_string_vocabulary_rejects_free_text(caplog):
    instance = _runtime_instance()

    with caplog.at_level(logging.INFO, logger=runtime.__name__):
        instance._remember_native_marker("R67_ATTACHED_REFRESH_LAST_ERROR=token=secret")
        instance._observe_canary_log_marker("R67_ATTACHED_REFRESH_LAST_ERROR=token=secret")

    assert instance._native_marker_tail == [
        "R67_ATTACHED_REFRESH_LAST_ERROR=<redacted>"
    ]
    assert not caplog.records
    assert "secret" not in "\n".join(instance._native_marker_tail)


def test_r67_value_aware_dedup_is_bounded_per_generation(caplog):
    instance = _runtime_instance()

    with caplog.at_level(logging.INFO, logger=runtime.__name__):
        instance._observe_canary_log_marker("R67_ATTACHED_REFRESH_CALL_GENERATION=1")
        for value in range(10):
            instance._observe_canary_log_marker(
                f"R67_ATTACHED_REFRESH_LAST_AGE_SECONDS={value}"
            )
        instance._observe_canary_log_marker("R67_ATTACHED_REFRESH_LAST_AGE_SECONDS=7")

    age_records = [
        record.message
        for record in caplog.records
        if "marker=R67_ATTACHED_REFRESH_LAST_AGE_SECONDS " in record.message
    ]
    assert len(age_records) == runtime._R67_VALUE_AWARE_DEDUP_LIMIT_PER_GENERATION
    assert "value=0" in age_records[0]
    assert "value=7" in age_records[-1]
    assert all(
        "value=8" not in record and "value=9" not in record
        for record in age_records
    )


def test_existing_native_marker_safety_and_dedup_still_hold(caplog):
    instance = _runtime_instance()

    with caplog.at_level(logging.INFO, logger=runtime.__name__):
        instance._remember_native_marker("P116_NATIVE_FAILURE_ID=PSEUDOTCP_CLOSED")
        instance._remember_native_marker("P116_NATIVE_FAILURE_ID=token=secret")
        instance._observe_canary_log_marker("R58_STOP_PHASE=REQUESTED")
        instance._observe_canary_log_marker("R58_STOP_PHASE=CLOSED")
        instance._observe_canary_log_marker("R58_STOP_PHASE=CLOSED")

    assert instance._native_marker_tail == [
        "P116_NATIVE_FAILURE_ID=PSEUDOTCP_CLOSED",
        "P116_NATIVE_FAILURE_ID=<redacted>",
    ]
    messages = [record.message for record in caplog.records]
    assert sum("marker=R58_STOP_PHASE" in message for message in messages) == 2
    assert any("value=REQUESTED" in message for message in messages)
    assert any("value=CLOSED" in message for message in messages)
