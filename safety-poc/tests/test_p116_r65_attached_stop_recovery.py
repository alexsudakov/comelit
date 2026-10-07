#!/usr/bin/env python3
"""P116/R65 attached Ring media stop recovery contracts."""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
import re
import sys
import types
import unittest

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "custom_components" / "comelit" / "runtime.py"
SUPERVISOR = ROOT / "custom_components" / "comelit" / "supervisor.py"
ATTACHED = ROOT / "custom_components" / "comelit" / "attached_media.py"
INIT = ROOT / "custom_components" / "comelit" / "__init__.py"
SENSOR = ROOT / "custom_components" / "comelit" / "sensor.py"


def _function_source(source: str, name: str) -> str:
    marker = f"    async def {name}("
    start = source.index(marker)
    match = re.search(r"\n    (?:async )?def |\nclass ", source[start + 1 :])
    if match is None:
        return source[start:]
    return source[start : start + 1 + match.start()]


def _install_package_stubs() -> None:
    for name in list(sys.modules):
        if name == "custom_components" or name.startswith("custom_components.comelit"):
            sys.modules.pop(name, None)
    custom_components = types.ModuleType("custom_components")
    custom_components.__path__ = [str(ROOT / "custom_components")]
    comelit = types.ModuleType("custom_components.comelit")
    comelit.__path__ = [str(ROOT / "custom_components" / "comelit")]
    sys.modules["custom_components"] = custom_components
    sys.modules["custom_components.comelit"] = comelit


def _load_attached_module() -> types.ModuleType:
    _install_package_stubs()
    h264 = types.ModuleType("custom_components.comelit.h264_recovery")
    h264.H264RecoveryRtpShim = object
    sys.modules["custom_components.comelit.h264_recovery"] = h264
    media_transport = types.ModuleType("custom_components.comelit.media_transport")
    media_transport.MEDIA_AUDIO_RTP_PORT = 17808
    media_transport.MEDIA_VIDEO_HA_RTP_PORT = 17999
    media_transport.MEDIA_VIDEO_MINIAPP_RTP_PORT = 18099
    media_transport.MEDIA_VIDEO_RTP_PORT = 17899
    sys.modules["custom_components.comelit.media_transport"] = media_transport
    spec = importlib.util.spec_from_file_location(
        "custom_components.comelit.attached_media",
        ATTACHED,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_supervisor_module() -> types.ModuleType:
    _install_package_stubs()
    ha = types.ModuleType("homeassistant")
    config_entries = types.ModuleType("homeassistant.config_entries")
    config_entries.ConfigEntry = object
    core = types.ModuleType("homeassistant.core")
    core.HomeAssistant = object
    sys.modules["homeassistant"] = ha
    sys.modules["homeassistant.config_entries"] = config_entries
    sys.modules["homeassistant.core"] = core
    const = types.ModuleType("custom_components.comelit.const")
    const.DOOR_ENTRANCE = "entrance"
    const.DOOR_GATE = "gate"
    const.LISTENER_CYCLE_SECONDS = 3300
    sys.modules["custom_components.comelit.const"] = const
    media_transport = types.ModuleType("custom_components.comelit.media_transport")
    media_transport.ComelitEntranceMediaTransport = object
    sys.modules["custom_components.comelit.media_transport"] = media_transport
    runtime = types.ModuleType("custom_components.comelit.runtime")
    runtime.ComelitRingRuntime = object
    sys.modules["custom_components.comelit.runtime"] = runtime
    spec = importlib.util.spec_from_file_location(
        "custom_components.comelit.supervisor",
        SUPERVISOR,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_runtime_module() -> types.ModuleType:
    for name in (
        "aiohttp",
        "homeassistant",
        "homeassistant.config_entries",
        "homeassistant.core",
        "custom_components.comelit.cloud",
        "custom_components.comelit.oauth",
        "custom_components.comelit.ring_media",
        "custom_components.comelit.sdp",
    ):
        sys.modules.pop(name, None)
    _install_package_stubs()
    aiohttp = types.ModuleType("aiohttp")
    aiohttp.ClientSession = object
    sys.modules["aiohttp"] = aiohttp
    config_entries = types.ModuleType("homeassistant.config_entries")
    config_entries.ConfigEntry = object
    core = types.ModuleType("homeassistant.core")
    core.HomeAssistant = object
    sys.modules["homeassistant"] = types.ModuleType("homeassistant")
    sys.modules["homeassistant.config_entries"] = config_entries
    sys.modules["homeassistant.core"] = core
    cloud = types.ModuleType("custom_components.comelit.cloud")
    cloud.ComelitCloudError = RuntimeError
    cloud.ComelitCloudHttpError = type(
        "ComelitCloudHttpError",
        (RuntimeError,),
        {"__init__": lambda self, status: setattr(self, "status", status)},
    )
    async def async_negotiate_p2p(*args: object, **kwargs: object) -> str:
        return ""
    cloud.async_negotiate_p2p = async_negotiate_p2p
    sys.modules["custom_components.comelit.cloud"] = cloud
    oauth = types.ModuleType("custom_components.comelit.oauth")
    oauth.ComelitOAuthError = RuntimeError
    oauth.ComelitOAuthManager = object
    sys.modules["custom_components.comelit.oauth"] = oauth
    ring_media = types.ModuleType("custom_components.comelit.ring_media")
    ring_media.RingMediaCoordinator = object
    sys.modules["custom_components.comelit.ring_media"] = ring_media
    sdp = types.ModuleType("custom_components.comelit.sdp")
    sdp.ComelitSdpError = RuntimeError
    sdp.transform_offer = lambda raw: raw
    sys.modules["custom_components.comelit.sdp"] = sdp
    spec = importlib.util.spec_from_file_location(
        "custom_components.comelit.runtime",
        RUNTIME,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _DoneTask:
    def done(self) -> bool:
        return True

    def cancel(self) -> None:
        return None


class _Entry:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def async_create_background_task(self, hass: object, coro: object, name: str) -> _DoneTask:
        self.events.append(f"task:{name}")
        close = getattr(coro, "close", None)
        if close is not None:
            close()
        return _DoneTask()


class _RuntimeForRecovery:
    def __init__(
        self,
        events: list[str],
        *,
        fail_stop: bool = False,
        ready_after_start: bool = True,
    ) -> None:
        self.events = events
        self.fail_stop = fail_stop
        self.ready_after_start = ready_after_start
        self.running = True
        self.listener_ready = True
        self.attached_media_open = True
        self.attached_media_busy = True
        self.call_state = "active"
        self.start_count = 0

    def status(self) -> dict[str, object]:
        return {
            "running": self.running,
            "listener_ready": self.listener_ready,
            "attached_media_busy": self.attached_media_busy,
            "last_error": None,
            "last_native_exit_code": None,
            "last_native_failure_markers": [],
            "last_attached_stop_failure_stage": None,
        }

    async def async_stop(self) -> None:
        self.events.append("runtime_stop_begin")
        if self.fail_stop:
            self.events.append("runtime_stop_unconfirmed")
            raise RuntimeError("runtime_stop_not_confirmed")
        self.running = False
        self.listener_ready = False
        self.attached_media_open = False
        self.attached_media_busy = False
        self.call_state = "idle"
        self.events.append("runtime_stop_confirmed")

    async def async_start(self) -> None:
        self.events.append("runtime_start")
        self.start_count += 1
        self.running = True
        self.listener_ready = self.ready_after_start

    async def async_wait_ready(self, timeout: float) -> bool:
        self.events.append("runtime_wait_ready")
        return self.listener_ready


class _Transport:
    def __init__(self, events: list[str], module: types.ModuleType, *, fail: bool = False) -> None:
        self.events = events
        self.module = module
        self.fail = fail
        self.active = True
        self.local_sdp_path = Path("/tmp/missing-comelit-attached.sdp")

    async def async_stop(self) -> None:
        self.events.append("transport_stop")
        if self.fail:
            raise self.module.ComelitAttachedMediaError(
                "attached_media_stop_not_confirmed"
            )
        self.active = False


class _FakeHass:
    def __init__(self, events: list[str] | None = None) -> None:
        self.events = events

    async def async_add_executor_job(self, func: object, *args: object) -> None:
        if self.events is not None:
            self.events.append("touch_stop")
        return None


class _FakeProcess:
    def __init__(self, events: list[str], mode: str) -> None:
        self.events = events
        self.mode = mode
        self.returncode: int | None = None
        self.wait_calls = 0

    async def wait(self) -> int | None:
        self.wait_calls += 1
        self.events.append(f"wait:{self.wait_calls}")
        if self.mode == "graceful":
            self.returncode = 0
            return self.returncode
        if self.mode == "terminate" and self.wait_calls == 1:
            raise TimeoutError
        if self.mode == "kill" and self.wait_calls in {1, 2}:
            raise TimeoutError
        self.returncode = 0
        return self.returncode

    def terminate(self) -> None:
        self.events.append("terminate")

    def kill(self) -> None:
        self.events.append("kill")


class AttachedStopRecoveryContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.runtime = RUNTIME.read_text(encoding="utf-8")
        cls.supervisor = SUPERVISOR.read_text(encoding="utf-8")
        cls.attached = ATTACHED.read_text(encoding="utf-8")
        cls.init = INIT.read_text(encoding="utf-8")
        cls.sensor = SENSOR.read_text(encoding="utf-8")

    def test_r58_stop_failure_stage_is_bounded_runtime_status(self) -> None:
        self.assertIn("_R58_STOP_FAILURE_STAGES = frozenset(", self.runtime)
        self.assertIn('"R58_STOP_FAILURE_STAGE": _R58_STOP_FAILURE_STAGES', self.runtime)
        self.assertIn("self._last_attached_stop_failure_stage", self.runtime)
        self.assertIn('"last_attached_stop_failure_stage"', self.runtime)
        self.assertIn("safe_value if safe_value in _R58_STOP_FAILURE_STAGES else None", self.runtime)
        self.assertIn('"last_attached_stop_failure_stage": status.get(', self.sensor)

    def test_attached_stop_success_leaves_recovery_uninvoked(self) -> None:
        module = _load_attached_module()
        events: list[str] = []
        session = module.ComelitAttachedRingMediaSession(_Transport(events, module))
        session._leases = {"ring_media": 1}
        async def recovery() -> None:
            events.append("recovery")
        session.set_stop_failure_recovery(recovery)
        status = asyncio.run(session.async_release(reason="ring_media"))
        self.assertEqual(events, ["transport_stop"])
        self.assertFalse(status["claimed"])

    def test_attached_stop_not_confirmed_invokes_recovery_once(self) -> None:
        module = _load_attached_module()
        events: list[str] = []
        session = module.ComelitAttachedRingMediaSession(
            _Transport(events, module, fail=True)
        )
        session._leases = {"ring_media": 1}
        async def recovery() -> None:
            events.append("recovery")
        session.set_stop_failure_recovery(recovery)
        with self.assertRaises(module.ComelitAttachedMediaError):
            asyncio.run(session.async_release(reason="ring_media"))
        self.assertEqual(events, ["transport_stop", "recovery"])

    def test_recovery_stops_old_runtime_before_new_start(self) -> None:
        module = _load_supervisor_module()
        events: list[str] = []
        runtime = _RuntimeForRecovery(events)
        supervisor = module.ComelitRuntimeSupervisor(
            object(),
            runtime,
            entry=_Entry(events),
        )
        asyncio.run(supervisor.async_recover_attached_media_stop_failure())
        self.assertEqual(
            events,
            [
                "runtime_stop_begin",
                "runtime_stop_confirmed",
                "runtime_start",
                "task:comelit runtime supervisor",
                "runtime_wait_ready",
            ],
        )

    def test_successful_recycle_clears_stale_flags_and_restarts_once(self) -> None:
        module = _load_supervisor_module()
        events: list[str] = []
        runtime = _RuntimeForRecovery(events)
        supervisor = module.ComelitRuntimeSupervisor(
            object(),
            runtime,
            entry=_Entry(events),
        )
        asyncio.run(supervisor.async_recover_attached_media_stop_failure())
        self.assertFalse(runtime.attached_media_open)
        self.assertFalse(runtime.attached_media_busy)
        self.assertEqual(runtime.call_state, "idle")
        self.assertEqual(runtime.start_count, 1)
        self.assertEqual(supervisor.state, module.LISTENER_STATE_READY)

    def test_failed_old_runtime_stop_does_not_restart(self) -> None:
        module = _load_supervisor_module()
        events: list[str] = []
        runtime = _RuntimeForRecovery(events, fail_stop=True)
        supervisor = module.ComelitRuntimeSupervisor(
            object(),
            runtime,
            entry=_Entry(events),
        )
        with self.assertRaises(RuntimeError):
            asyncio.run(supervisor.async_recover_attached_media_stop_failure())
        self.assertEqual(events, ["runtime_stop_begin", "runtime_stop_unconfirmed"])
        self.assertEqual(runtime.start_count, 0)
        self.assertEqual(supervisor.state, module.LISTENER_STATE_ERROR)
        self.assertTrue(supervisor.status()["attached_stop_recovery_required"])

    def test_r58_stop_failure_stage_accepts_only_allowlist(self) -> None:
        module = _load_runtime_module()
        runtime = module.ComelitRingRuntime.__new__(module.ComelitRingRuntime)
        runtime._task = None
        runtime._listener_ready = asyncio.Event()
        runtime._attached_media_busy = asyncio.Event()
        runtime._attached_media_open = asyncio.Event()
        runtime._last_ring_event = None
        runtime._last_error = None
        runtime._last_native_exit_code = None
        runtime._last_native_failure_markers = []
        runtime._last_door_result = None
        runtime._native_marker_tail = []
        runtime._ring_media = None
        runtime._media_diagnostics = types.SimpleNamespace(snapshot=lambda: {})
        runtime._call_state = types.SimpleNamespace(
            snapshot=lambda: types.SimpleNamespace(
                state="idle",
                panel=None,
                event_id=None,
                started_at=None,
                conversation_active=False,
                last_error=None,
            )
        )
        for value in module._R58_STOP_FAILURE_STAGES:
            runtime._remember_native_marker(f"R58_STOP_FAILURE_STAGE={value}")
            self.assertEqual(runtime.status()["last_attached_stop_failure_stage"], value)
        runtime._remember_native_marker("R58_STOP_FAILURE_STAGE=raw-secret-value")
        self.assertIsNone(runtime.status()["last_attached_stop_failure_stage"])

    def test_process_stop_ladder_has_bounded_terminate_escalation(self) -> None:
        module = _load_runtime_module()
        for mode, expected in {
            "graceful": ["touch_stop", "wait:1"],
            "terminate": ["touch_stop", "wait:1", "terminate", "wait:2"],
            "kill": ["touch_stop", "wait:1", "terminate", "wait:2", "kill", "wait:3"],
        }.items():
            with self.subTest(mode=mode):
                events: list[str] = []
                runtime = module.ComelitRingRuntime.__new__(module.ComelitRingRuntime)
                runtime._hass = _FakeHass(events)
                stopped = asyncio.run(
                    runtime._async_stop_native_process(_FakeProcess(events, mode))
                )
                self.assertTrue(stopped)
                self.assertEqual(events, expected)

    def test_repeated_ring_after_recovery_is_not_blocked_by_stale_attached_busy(self) -> None:
        module = _load_supervisor_module()
        events: list[str] = []
        runtime = _RuntimeForRecovery(events)
        supervisor = module.ComelitRuntimeSupervisor(
            object(),
            runtime,
            entry=_Entry(events),
        )
        asyncio.run(supervisor.async_recover_attached_media_stop_failure())
        self.assertFalse(supervisor.attached_media_busy)
        if supervisor.attached_media_busy:
            raise RuntimeError("stale_attached_busy_blocks_next_ring")
        self.assertEqual(runtime.call_state, "idle")

    def test_attached_stop_failure_marks_recovery_and_recycles_listener_static(self) -> None:
        recovery = _function_source(
            self.supervisor,
            "async_recover_attached_media_stop_failure",
        )
        self.assertIn("self._attached_stop_recovery_required = True", recovery)
        self.assertIn("runtime_stop_not_confirmed", recovery)
        self.assertIn("self._attached_stop_recovery_required = False", recovery)

    def test_recovery_is_wired_from_exact_attached_stop_not_confirmed_failure(self) -> None:
        self.assertIn("set_stop_failure_recovery", self.attached)
        self.assertIn("attached_media_stop_not_confirmed", self.attached)
        self.assertIn("await self._async_recover_stop_not_confirmed()", self.attached)
        self.assertIn(
            "supervisor.async_recover_attached_media_stop_failure",
            self.init,
        )

    def test_runtime_reset_remains_the_only_attached_flag_cleanup_on_recycle(self) -> None:
        transport_stop = self.attached.split("async def async_stop", 1)[1].split(
            "class ComelitAttachedRingMediaSession",
            1,
        )[0]
        self.assertNotIn("_attached_media_open.clear()", transport_stop)
        self.assertNotIn("_attached_media_busy.clear()", transport_stop)
        runtime_stop = _function_source(self.runtime, "async_stop")
        self.assertIn("self._attached_media_busy.clear()", runtime_stop)
        self.assertIn("self._attached_media_open.clear()", runtime_stop)
        self.assertIn("self._call_state_tracker().reset()", runtime_stop)


if __name__ == "__main__":
    unittest.main()
