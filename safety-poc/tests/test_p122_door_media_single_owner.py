#!/usr/bin/env python3
"""P122 Door/media single-owner arbitration contracts."""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
import re
import signal
import sys
import types
import unittest

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "custom_components" / "comelit" / "runtime.py"
SUPERVISOR = ROOT / "custom_components" / "comelit" / "supervisor.py"
BUTTON = ROOT / "custom_components" / "comelit" / "button.py"
INIT = ROOT / "custom_components" / "comelit" / "__init__.py"
MEDIA_TRANSPORT = ROOT / "custom_components" / "comelit" / "media_transport.py"


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


def _install_ha_core_stubs() -> type[Exception]:
    sys.modules["homeassistant"] = types.ModuleType("homeassistant")
    config_entries = types.ModuleType("homeassistant.config_entries")
    config_entries.ConfigEntry = object
    core = types.ModuleType("homeassistant.core")
    core.HomeAssistant = object
    exc = types.ModuleType("homeassistant.exceptions")
    HomeAssistantError = type("HomeAssistantError", (Exception,), {})
    exc.HomeAssistantError = HomeAssistantError
    sys.modules["homeassistant.config_entries"] = config_entries
    sys.modules["homeassistant.core"] = core
    sys.modules["homeassistant.exceptions"] = exc
    return HomeAssistantError


def _load_supervisor_module() -> types.ModuleType:
    _install_package_stubs()
    _install_ha_core_stubs()
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
    _install_package_stubs()
    aiohttp = types.ModuleType("aiohttp")
    aiohttp.ClientSession = object
    sys.modules["aiohttp"] = aiohttp
    _install_ha_core_stubs()
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


def _load_media_transport_module() -> types.ModuleType:
    _install_package_stubs()
    aiohttp = types.ModuleType("aiohttp")
    aiohttp.ClientSession = object
    sys.modules["aiohttp"] = aiohttp
    _install_ha_core_stubs()
    cloud = types.ModuleType("custom_components.comelit.cloud")
    cloud.ComelitCloudError = RuntimeError
    async def async_negotiate_p2p(*args: object, **kwargs: object) -> str:
        return ""
    cloud.async_negotiate_p2p = async_negotiate_p2p
    sys.modules["custom_components.comelit.cloud"] = cloud
    const = types.ModuleType("custom_components.comelit.const")
    const.EVENT_DOOR_OPERATION = "comelit_door_operation"
    sys.modules["custom_components.comelit.const"] = const
    h264 = types.ModuleType("custom_components.comelit.h264_recovery")
    h264.H264RecoveryRtpShim = object
    sys.modules["custom_components.comelit.h264_recovery"] = h264
    latency = types.ModuleType("custom_components.comelit.latency_timeline")
    for name in (
        "G0_NATIVE_PROCESS_START_MONOTONIC_MS",
        "G1_NICE_AGENT_READY_MONOTONIC_MS",
        "G2_GATHER_CALL_MONOTONIC_MS",
        "G3_FIRST_HOST_CANDIDATE_MONOTONIC_MS",
        "G3_HOST_CANDIDATE_COUNT",
        "G4_FIRST_SRFLX_CANDIDATE_MONOTONIC_MS",
        "G4_SRFLX_CANDIDATE_COUNT",
        "G5_GATHER_DONE_MONOTONIC_MS",
        "G6_OFFER_WRITTEN_MONOTONIC_MS",
        "GATHER_INITIAL_TIMEOUT_RESTORED_MS",
        "GATHER_INITIAL_TIMEOUT_SET_MS",
        "RSP_LOADED_MONOTONIC_MS",
        "RSP_VISIBLE_MONOTONIC_MS",
        "T04_TRANSPORT_START_BEGIN",
        "T05_ICE_GATHER_DONE",
        "T06_CLOUD_NEGOTIATE_BEGIN",
        "T07_REMOTE_SDP_READY",
        "T08_ICE_CONNECTED",
        "T08B_ICE_READY",
        "T09_PSEUDOTCP_OPEN",
        "T10_CTPP_READY",
        "T11_SIGNALING_ARMED",
        "T12_SELF_ACTIVATION_SENT",
        "T13_RTPC_BEGIN",
        "T14_RTPC_CONTROL_COMPLETE",
        "T15_MEDIA_ACTIVE",
        "T16_FIRST_VIDEO_RTP",
        "T17_FIRST_DECODABLE_FRAME",
    ):
        setattr(latency, name, name)
    latency.CameraRequestLatencyTimeline = object
    sys.modules["custom_components.comelit.latency_timeline"] = latency
    media_diag = types.ModuleType("custom_components.comelit.media_diagnostics")
    media_diag.MediaProgressDiagnostics = object
    sys.modules["custom_components.comelit.media_diagnostics"] = media_diag
    oauth = types.ModuleType("custom_components.comelit.oauth")
    oauth.ComelitOAuthError = RuntimeError
    oauth.ComelitOAuthManager = object
    sys.modules["custom_components.comelit.oauth"] = oauth
    sdp = types.ModuleType("custom_components.comelit.sdp")
    sdp.ComelitSdpError = RuntimeError
    sdp.transform_offer = lambda raw: raw
    sys.modules["custom_components.comelit.sdp"] = sdp
    spec = importlib.util.spec_from_file_location(
        "custom_components.comelit.media_transport",
        MEDIA_TRANSPORT,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_button_module() -> tuple[types.ModuleType, type[Exception]]:
    _install_package_stubs()
    HomeAssistantError = _install_ha_core_stubs()
    button_component = types.ModuleType("homeassistant.components.button")
    class ButtonEntity:
        async def async_added_to_hass(self) -> None:
            return None
        def async_on_remove(self, callback: object) -> None:
            return None
        def async_write_ha_state(self) -> None:
            return None
    button_component.ButtonEntity = ButtonEntity
    sys.modules["homeassistant.components"] = types.ModuleType("homeassistant.components")
    sys.modules["homeassistant.components.button"] = button_component
    platform = types.ModuleType("homeassistant.helpers.entity_platform")
    platform.AddEntitiesCallback = object
    sys.modules["homeassistant.helpers"] = types.ModuleType("homeassistant.helpers")
    sys.modules["homeassistant.helpers.entity_platform"] = platform
    const = types.ModuleType("custom_components.comelit.const")
    const.DATA_MEDIA_TRANSPORTS = "media_transports"
    const.DATA_RUNTIMES = "runtimes"
    const.DATA_SUPERVISORS = "supervisors"
    const.DOMAIN = "comelit"
    const.DOOR_ENTRANCE = "entrance"
    const.DOOR_GATE = "gate"
    const.MAIN_ENTRANCE_ENTITY_ID = "button.entrance"
    const.MAIN_ENTRANCE_UNIQUE_ID = "entrance"
    const.MAIN_GATE_ENTITY_ID = "button.gate"
    const.MAIN_GATE_UNIQUE_ID = "gate"
    const.resolve_door_capability = lambda *args, **kwargs: types.SimpleNamespace(
        available=True,
        press_allowed=True,
        actuation_profile_validated=True,
        configured=True,
        ring_source_validated=True,
        ring_source="00000610",
        blocked_reason=None,
    )
    sys.modules["custom_components.comelit.const"] = const
    media_transport = types.ModuleType("custom_components.comelit.media_transport")
    media_transport.ComelitEntranceMediaTransport = object
    sys.modules["custom_components.comelit.media_transport"] = media_transport
    runtime = types.ModuleType("custom_components.comelit.runtime")
    runtime.ComelitRingRuntime = object
    sys.modules["custom_components.comelit.runtime"] = runtime
    supervisor = types.ModuleType("custom_components.comelit.supervisor")
    supervisor.ComelitRuntimeSupervisor = object
    sys.modules["custom_components.comelit.supervisor"] = supervisor
    spec = importlib.util.spec_from_file_location(
        "custom_components.comelit.button",
        BUTTON,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module, HomeAssistantError


class OwnerMeter:
    def __init__(self) -> None:
        self.current = 0
        self.maximum = 0

    async def enter(self, events: list[str], label: str) -> None:
        events.append(f"{label}:enter")
        self.current += 1
        self.maximum = max(self.maximum, self.current)
        await asyncio.sleep(0)

    async def exit(self, events: list[str], label: str) -> None:
        events.append(f"{label}:exit")
        await asyncio.sleep(0)
        self.current -= 1


class _DoneTask:
    def done(self) -> bool:
        return True
    def cancel(self) -> None:
        return None


class _Entry:
    def __init__(self, events: list[str], *, real_tasks: bool = False) -> None:
        self.events = events
        self.real_tasks = real_tasks
    def async_create_background_task(self, hass: object, coro: object, name: str) -> object:
        self.events.append(f"task:{name}")
        if self.real_tasks:
            return asyncio.create_task(coro)
        close = getattr(coro, "close", None)
        if close is not None:
            close()
        return _DoneTask()


class _RuntimeOwner:
    def __init__(self, events: list[str], meter: OwnerMeter) -> None:
        self.events = events
        self.meter = meter
        self.running = True
        self.listener_ready = True
        self.attached_media_busy = False
        self.start_calls = 0
        self.open_calls = 0
        self.stop_calls = 0
    def status(self) -> dict[str, object]:
        return {
            "running": self.running,
            "listener_ready": self.listener_ready,
            "attached_media_busy": self.attached_media_busy,
            "last_error": None,
            "last_native_exit_code": None,
            "last_native_failure_markers": [],
        }
    async def async_open_door(self, door: str, *, event_id: str | None = None) -> dict[str, object]:
        self.open_calls += 1
        await self.meter.enter(self.events, f"door:{door}")
        try:
            await asyncio.sleep(0)
            return {"state": "UNKNOWN_OUTCOME", "automatic_retry_allowed": False}
        finally:
            await self.meter.exit(self.events, f"door:{door}")
    async def async_stop(self) -> None:
        self.stop_calls += 1
        await self.meter.enter(self.events, "listener_stop")
        try:
            await asyncio.sleep(0)
            self.running = False
            self.listener_ready = False
        finally:
            await self.meter.exit(self.events, "listener_stop")
    async def async_start(self) -> None:
        self.start_calls += 1
        await self.meter.enter(self.events, "listener_start")
        try:
            await asyncio.sleep(0)
            self.running = True
            self.listener_ready = True
        finally:
            await self.meter.exit(self.events, "listener_start")


class _MediaTransportOwner:
    active = True
    def __init__(self, events: list[str], meter: OwnerMeter) -> None:
        self.events = events
        self.meter = meter
        self.open_calls = 0
    async def async_open_door(self, *, event_id: str | None = None) -> dict[str, object]:
        self.open_calls += 1
        await self.meter.enter(self.events, "media_door")
        try:
            await asyncio.sleep(0)
            return {"path": "ON_DEMAND_MEDIA_SINGLE", "state": "UNKNOWN_OUTCOME"}
        finally:
            await self.meter.exit(self.events, "media_door")


class _Bus:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, object]]] = []
    def async_fire(self, event: str, payload: dict[str, object]) -> None:
        self.events.append((event, payload))


class _Stdout:
    def __init__(self, lines: list[str]) -> None:
        self.lines = [f"{line}\n".encode() for line in lines]
    async def readline(self) -> bytes:
        if self.lines:
            return self.lines.pop(0)
        return b""


class _ReadProcess:
    def __init__(self, lines: list[str]) -> None:
        self.stdout = _Stdout(lines)


class DoorMediaSingleOwnerContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.runtime = RUNTIME.read_text(encoding="utf-8")
        cls.supervisor = SUPERVISOR.read_text(encoding="utf-8")
        cls.button = BUTTON.read_text(encoding="utf-8")
        cls.init = INIT.read_text(encoding="utf-8")
        cls.transport = MEDIA_TRANSPORT.read_text(encoding="utf-8")

    def test_runtime_door_not_running_fails_safe_without_self_start(self) -> None:
        module = _load_runtime_module()
        events: list[str] = []
        runtime = module.ComelitRingRuntime.__new__(module.ComelitRingRuntime)
        runtime._task = None
        runtime._listener_ready = asyncio.Event()
        runtime._door_lock = asyncio.Lock()
        runtime._last_door_result = None
        runtime._hass = types.SimpleNamespace(bus=_Bus())
        async def forbidden_start() -> None:
            events.append("async_start")
        runtime.async_start = forbidden_start
        result = asyncio.run(runtime.async_open_door("entrance"))
        self.assertEqual(result["state"], "FAILED_SAFE")
        self.assertEqual(events, [])

    def test_listener_door_active_then_media_pause_keeps_one_owner(self) -> None:
        module = _load_supervisor_module()
        events: list[str] = []
        meter = OwnerMeter()
        runtime = _RuntimeOwner(events, meter)
        supervisor = module.ComelitRuntimeSupervisor(object(), runtime, entry=_Entry(events))
        supervisor._set_state(module.LISTENER_STATE_READY)
        async def race() -> None:
            await asyncio.gather(
                supervisor.async_open_entrance_door(None),
                supervisor.async_pause_for_media(),
            )
        asyncio.run(race())
        self.assertLessEqual(meter.maximum, 1)

    def test_media_first_then_listener_door_fails_without_listener_start(self) -> None:
        module = _load_supervisor_module()
        events: list[str] = []
        meter = OwnerMeter()
        runtime = _RuntimeOwner(events, meter)
        supervisor = module.ComelitRuntimeSupervisor(object(), runtime, entry=_Entry(events))
        async def run() -> None:
            await supervisor.async_pause_for_media()
            with self.assertRaises(RuntimeError):
                await supervisor.async_open_entrance_door(None)
        asyncio.run(run())
        self.assertEqual(runtime.open_calls, 0)
        self.assertEqual(runtime.start_calls, 0)
        self.assertLessEqual(meter.maximum, 1)

    def test_entrance_door_during_active_media_uses_media_transport(self) -> None:
        module = _load_supervisor_module()
        events: list[str] = []
        meter = OwnerMeter()
        runtime = _RuntimeOwner(events, meter)
        media = _MediaTransportOwner(events, meter)
        supervisor = module.ComelitRuntimeSupervisor(object(), runtime, entry=_Entry(events))
        async def run() -> dict[str, object]:
            await supervisor.async_pause_for_media()
            return await supervisor.async_open_entrance_door(media)
        result = asyncio.run(run())
        self.assertEqual(result["path"], "ON_DEMAND_MEDIA_SINGLE")
        self.assertEqual(media.open_calls, 1)
        self.assertEqual(runtime.open_calls, 0)
        self.assertEqual(runtime.start_calls, 0)

    def test_gate_during_media_fails_closed_and_button_maps_to_ha_error(self) -> None:
        module = _load_supervisor_module()
        events: list[str] = []
        meter = OwnerMeter()
        runtime = _RuntimeOwner(events, meter)
        supervisor = module.ComelitRuntimeSupervisor(object(), runtime, entry=_Entry(events))
        async def direct() -> None:
            await supervisor.async_pause_for_media()
            with self.assertRaisesRegex(RuntimeError, "media_owns_connection"):
                await supervisor.async_open_gate_door()
        asyncio.run(direct())
        button_module, HomeAssistantError = _load_button_module()
        async def raise_media_owner() -> None:
            raise RuntimeError("media_owns_connection")
        fake_supervisor = types.SimpleNamespace(
            media_paused=True,
            async_add_status_listener=lambda callback: lambda: None,
            async_open_gate_door=raise_media_owner,
        )
        button = button_module.ComelitGateDoorButton(object(), fake_supervisor)
        with self.assertRaises(HomeAssistantError):
            asyncio.run(button.async_press())

    def test_reconnect_cannot_start_on_top_of_in_flight_door(self) -> None:
        module = _load_supervisor_module()
        module.RECONNECT_INITIAL_DELAY_SECONDS = 0
        module.RECONNECT_MAX_DELAY_SECONDS = 0
        module.RECONNECT_NORMAL_DELAY_SECONDS = 0
        module.POLL_INTERVAL_SECONDS = 0
        events: list[str] = []
        meter = OwnerMeter()
        runtime = _RuntimeOwner(events, meter)
        supervisor = module.ComelitRuntimeSupervisor(
            object(),
            runtime,
            entry=_Entry(events, real_tasks=True),
        )
        supervisor._set_state(module.LISTENER_STATE_READY)
        async def run() -> None:
            door_entered = asyncio.Event()
            release_door = asyncio.Event()
            async def blocked_open_door(
                door: str,
                *,
                event_id: str | None = None,
            ) -> dict[str, object]:
                runtime.open_calls += 1
                await meter.enter(events, f"door:{door}")
                door_entered.set()
                try:
                    await release_door.wait()
                    return {
                        "state": "UNKNOWN_OUTCOME",
                        "automatic_retry_allowed": False,
                    }
                finally:
                    await meter.exit(events, f"door:{door}")
            runtime.async_open_door = blocked_open_door
            door = asyncio.create_task(supervisor.async_open_gate_door())
            await door_entered.wait()
            runtime.running = False
            runtime.listener_ready = False
            reconnect = asyncio.create_task(supervisor._async_run())
            await asyncio.sleep(0)
            self.assertEqual(runtime.start_calls, 0)
            release_door.set()
            for _ in range(20):
                if runtime.start_calls:
                    break
                await asyncio.sleep(0)
            supervisor._stopping = True
            reconnect.cancel()
            try:
                await reconnect
            except asyncio.CancelledError:
                pass
            await door
        asyncio.run(run())
        self.assertEqual(runtime.start_calls, 1)
        self.assertLessEqual(meter.maximum, 1)

    def test_p122_write_count_values_are_preserved_and_fail_closed(self) -> None:
        module = _load_media_transport_module()
        original_kill = module.os.kill
        observed: dict[str, dict[str, object]] = {}
        kill_events: list[tuple[int, signal.Signals | int]] = []
        module.os.kill = lambda pid, sig: kill_events.append((pid, sig))
        try:
            for value in ("0", "1", "2", "5", "abc"):
                transport = module.ComelitEntranceMediaTransport.__new__(
                    module.ComelitEntranceMediaTransport
                )
                transport._door_lock = asyncio.Lock()
                transport._process = types.SimpleNamespace(pid=123, returncode=None)
                transport._media_active = asyncio.Event()
                transport._media_active.set()
                transport._door_result_future = None
                transport._door_diagnostics = {}
                transport._hass = types.SimpleNamespace(bus=_Bus())
                transport._remember_native_marker = lambda line: None
                transport._observe_latency_marker = lambda line: None
                transport._observe_native_stage_marker = lambda line: None
                lines = [
                    "P122_ONDEMAND_DOOR_SENT=true",
                    f"P122_ONDEMAND_DOOR_WRITE_COUNT={value}",
                    "P122_ONDEMAND_DOOR_RESULT=UNKNOWN_OUTCOME",
                ]
                async def run_one() -> dict[str, object]:
                    task = asyncio.create_task(transport.async_open_door())
                    await asyncio.sleep(0)
                    await transport._async_read_output(_ReadProcess(lines))
                    return await task
                observed[value] = asyncio.run(run_one())
        finally:
            module.os.kill = original_kill

        self.assertEqual(observed["0"]["write_count"], 0)
        self.assertFalse(observed["0"]["one_shot_sequence_sent"])
        self.assertEqual(observed["1"]["write_count"], 1)
        self.assertTrue(observed["1"]["one_shot_sequence_sent"])
        for value in ("2", "5"):
            self.assertEqual(observed[value]["write_count"], int(value))
            self.assertFalse(observed[value]["one_shot_sequence_sent"])
            self.assertFalse(observed[value]["protocol_acked"])
            self.assertEqual(observed[value]["state"], "UNKNOWN_OUTCOME")
        self.assertIsNone(observed["abc"]["write_count"])
        self.assertFalse(observed["abc"]["one_shot_sequence_sent"])
        self.assertEqual(len(kill_events), 5)

    def test_no_automatic_retry_after_ambiguous_media_door_outcome(self) -> None:
        module = _load_media_transport_module()
        original_kill = module.os.kill
        kill_events: list[tuple[int, signal.Signals | int]] = []
        module.os.kill = lambda pid, sig: kill_events.append((pid, sig))
        try:
            transport = module.ComelitEntranceMediaTransport.__new__(
                module.ComelitEntranceMediaTransport
            )
            transport._door_lock = asyncio.Lock()
            transport._process = types.SimpleNamespace(pid=123, returncode=None)
            transport._media_active = asyncio.Event()
            transport._media_active.set()
            transport._door_result_future = None
            transport._door_diagnostics = {}
            transport._hass = types.SimpleNamespace(bus=_Bus())
            transport._remember_native_marker = lambda line: None
            transport._observe_latency_marker = lambda line: None
            transport._observe_native_stage_marker = lambda line: None
            async def run_one() -> dict[str, object]:
                task = asyncio.create_task(transport.async_open_door())
                await asyncio.sleep(0)
                await transport._async_read_output(
                    _ReadProcess(["P122_ONDEMAND_DOOR_RESULT=UNKNOWN_OUTCOME"])
                )
                return await task
            result = asyncio.run(run_one())
        finally:
            module.os.kill = original_kill
        self.assertEqual(result["state"], "UNKNOWN_OUTCOME")
        self.assertFalse(result["automatic_retry_allowed"])
        self.assertEqual(len(kill_events), 1)

    def test_static_dispatch_shape_still_uses_supervisor_arbiter(self) -> None:
        self.assertIn("await self._supervisor.async_open_entrance_door(", self.button)
        self.assertIn("await self._supervisor.async_open_gate_door()", self.button)
        self.assertNotIn("await self._runtime.async_open_door(DOOR_ENTRANCE)", self.button)
        self.assertNotIn("await self._runtime.async_open_door(DOOR_GATE)", self.button)
        self.assertIn("await supervisor.async_open_entrance_door(", self.init)
        self.assertIn("await supervisor.async_open_gate_door(", self.init)
        handle = _function_source(self.init, "handle_open_door")
        self.assertNotIn("return await runtime.async_open_door(", handle)


if __name__ == "__main__":
    unittest.main()
