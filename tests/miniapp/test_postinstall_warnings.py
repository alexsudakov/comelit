"""Post-install Home Assistant event-loop and Python 3.14 regressions.

No live Comelit connection, protocol writes, or Home Assistant restart.
"""
from __future__ import annotations

import ast
import asyncio
from pathlib import Path
import sys
import threading
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests" / "miniapp" / "tools"))
from optionf_pr1a_replay import _load_component_module


def test_native_identity_state_accessor_never_hashes_or_stats_disk():
    module = _load_component_module(str(ROOT), "media_transport")
    transport = object.__new__(module.ComelitEntranceMediaTransport)
    old_cache = module._NATIVE_BINARY_IDENTITY_CACHE
    try:
        module._NATIVE_BINARY_IDENTITY_CACHE = None
        with patch.object(
            module, "_native_binary_identity_diagnostics",
            side_effect=AssertionError("blocking disk access in event loop"),
        ):
            pending = transport.native_runtime_identity_diagnostics()
            assert pending["native_binary_sha256_match"] is False
            assert pending["native_binary_sha256"] == "not_checked"

            cached = {
                "native_binary_sha256": "0" * 64,
                "native_binary_expected_sha256": module.MEDIA_NATIVE_BINARY_SHA256,
                "native_binary_sha256_match": False,
            }
            module._NATIVE_BINARY_IDENTITY_CACHE = ((123, 456), cached)
            identity = transport.native_runtime_identity_diagnostics()
            assert identity == cached
            identity["native_binary_sha256"] = "tampered"
            assert transport.native_runtime_identity_diagnostics() == cached
    finally:
        module._NATIVE_BINARY_IDENTITY_CACHE = old_cache


def test_native_identity_hash_is_prepared_in_executor_not_event_loop():
    module = _load_component_module(str(ROOT), "media_transport")
    caller_thread = threading.get_ident()
    worker_threads = []
    executor_calls = []

    class Hass:
        async def async_add_executor_job(self, function, *args):
            executor_calls.append(function)
            return await asyncio.to_thread(function, *args)

    def read_identity():
        worker_threads.append(threading.get_ident())
        return {}

    async def run():
        transport = object.__new__(module.ComelitEntranceMediaTransport)
        transport._hass = Hass()
        with patch.object(
            module, "_native_binary_identity_diagnostics", read_identity,
        ):
            await transport.async_prepare_native_identity_diagnostics()
        assert executor_calls == [read_identity]
        assert worker_threads
        assert all(thread != caller_thread for thread in worker_threads)

    asyncio.run(run())


def test_identity_prewarmed_before_first_camera_state():
    source = (ROOT / "custom_components/comelit/__init__.py").read_text()
    assert source.index(
        "await media_transport.async_prepare_native_identity_diagnostics()"
    ) < source.index("await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)")


def test_hls_probe_has_no_control_flow_return_in_finally():
    source = (ROOT / "custom_components/comelit/camera.py").read_text()
    tree = ast.parse(source)
    probe = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef)
        and node.name == "_async_probe_hls_http_boundary"
    )
    for node in ast.walk(probe):
        if isinstance(node, (ast.Try, ast.TryStar)):
            for final_stmt in node.finalbody:
                assert not any(
                    isinstance(child, (ast.Return, ast.Break, ast.Continue))
                    for child in ast.walk(final_stmt)
                ), "Python 3.14 warns and return-in-finally discards exceptions"


def test_remote_sdp_missing_reconnect_reason_is_not_unknown():
    source = (ROOT / "custom_components/comelit/supervisor.py").read_text()
    assert 'last_error == "remote_sdp_missing"' in source
    assert 'reconnect_reason = "REMOTE_SDP_MISSING"' in source
