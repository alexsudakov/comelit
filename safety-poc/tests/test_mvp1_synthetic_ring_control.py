from __future__ import annotations

import ast
import asyncio
import importlib.util
from pathlib import Path
import sys
import types
import unittest

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "custom_components" / "comelit" / "runtime.py"
RING_MEDIA = ROOT / "custom_components" / "comelit" / "ring_media.py"
TEST_CONTROL = ROOT / "custom_components" / "comelit" / "test_control.py"
CONST = ROOT / "custom_components" / "comelit" / "const.py"
SERVICES = ROOT / "custom_components" / "comelit" / "services.yaml"


def _method_source(path: Path, class_name: str, method_name: str) -> str:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or node.name != class_name:
            continue
        for child in node.body:
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name == method_name:
                return ast.unparse(child)
    raise AssertionError(f"{class_name}.{method_name} not found")


def _load_runtime_module() -> types.ModuleType:
    for name in (
        "aiohttp",
        "homeassistant",
        "homeassistant.config_entries",
        "homeassistant.core",
        "custom_components",
        "custom_components.comelit",
        "custom_components.comelit.cloud",
        "custom_components.comelit.oauth",
        "custom_components.comelit.ring_media",
        "custom_components.comelit.sdp",
    ):
        sys.modules.pop(name, None)

    aiohttp = types.ModuleType("aiohttp")
    aiohttp.ClientSession = object
    sys.modules["aiohttp"] = aiohttp

    homeassistant = types.ModuleType("homeassistant")
    config_entries = types.ModuleType("homeassistant.config_entries")
    config_entries.ConfigEntry = object
    core = types.ModuleType("homeassistant.core")
    core.HomeAssistant = object
    sys.modules["homeassistant"] = homeassistant
    sys.modules["homeassistant.config_entries"] = config_entries
    sys.modules["homeassistant.core"] = core

    custom_components = types.ModuleType("custom_components")
    custom_components.__path__ = [str(ROOT / "custom_components")]
    comelit = types.ModuleType("custom_components.comelit")
    comelit.__path__ = [str(ROOT / "custom_components" / "comelit")]
    sys.modules["custom_components"] = custom_components
    sys.modules["custom_components.comelit"] = comelit

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

    sys.modules.pop("custom_components.comelit.runtime", None)
    spec = importlib.util.spec_from_file_location(
        "custom_components.comelit.runtime",
        RUNTIME,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _FakeDoneTask:
    def done(self) -> bool:
        return False


class _FakeBus:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, object]]] = []

    def async_fire(self, event_type: str, event: dict[str, object]) -> None:
        self.events.append((event_type, dict(event)))


class _FakeHass:
    def __init__(self) -> None:
        self.bus = _FakeBus()


class _FakeEntry:
    def __init__(self) -> None:
        self.tasks: list[tuple[str, object]] = []

    def async_create_background_task(
        self,
        hass: object,
        coro: object,
        name: str,
    ) -> object:
        del hass
        self.tasks.append((name, coro))
        return asyncio.create_task(coro)


class _FakeCoordinator:
    def __init__(self, *, running: bool = False, start_result: bool = True) -> None:
        self.running = running
        self.start_result = start_result
        self.events: list[dict[str, object]] = []

    async def async_start_for_ring(self, event: dict[str, object]) -> bool:
        self.events.append(dict(event))
        return self.start_result


class _FakeStdout:
    def __init__(self, lines: list[str]) -> None:
        self._lines = [line.encode() for line in lines]

    async def readline(self) -> bytes:
        if self._lines:
            return self._lines.pop(0)
        return b""


class _FakeProcess:
    def __init__(self, lines: list[str]) -> None:
        self.stdout = _FakeStdout(lines)


def _runtime_instance(module: types.ModuleType) -> object:
    runtime = module.ComelitRingRuntime.__new__(module.ComelitRingRuntime)
    runtime._hass = _FakeHass()
    runtime._entry = _FakeEntry()
    runtime._task = _FakeDoneTask()
    runtime._listener_ready = asyncio.Event()
    runtime._listener_ready.set()
    runtime._ring_media = _FakeCoordinator()
    runtime._ring_lines = []
    runtime._last_ring_event = None
    runtime._native_marker_tail = []
    runtime._door_diagnostic = {}
    runtime._door_result_future = None
    return runtime


class MVP1SyntheticRingControlTests(unittest.TestCase):
    def test_runtime_synthetic_ring_uses_normal_media_coordinator_without_door(self) -> None:
        source = _method_source(
            RUNTIME,
            "ComelitRingRuntime",
            "async_simulate_entrance_ring",
        )
        self.assertIn("'synthetic': True", source)
        self.assertIn("'door': 'entrance'", source)
        self.assertIn("'kind': 'CALL_INIT'", source)
        self.assertIn("'direction': 'DEVICE_TO_CLIENT'", source)
        self.assertIn("_async_emit_ring_event", source)
        self.assertIn("require_media_start=True", source)
        self.assertIn("listener_not_ready", source)
        self.assertIn("ring_media_busy", source)
        self.assertNotIn("async_open_door", source)
        self.assertNotIn("SIGUSR1", source)
        shared = _method_source(RUNTIME, "ComelitRingRuntime", "_async_emit_ring_event")
        self.assertIn("EVENT_RING", shared)
        self.assertIn("async_start_for_ring", shared)

    def test_synthetic_trigger_stays_on_local_restricted_test_control(self) -> None:
        source = TEST_CONTROL.read_text(encoding="utf-8")
        self.assertIn('_ALLOWED_REMOTE = "192.168.1.85"', source)
        self.assertIn('if action == "simulate_entrance_ring":', source)
        self.assertIn("await runtime.async_simulate_entrance_ring()", source)
        self.assertIn("local_only=True", source)
        self.assertIn('result["synthetic"] = True', source)

    def test_synthetic_trigger_is_not_public_ha_service(self) -> None:
        const_source = CONST.read_text(encoding="utf-8")
        services_source = SERVICES.read_text(encoding="utf-8")
        self.assertNotIn("SERVICE_SIMULATE", const_source)
        self.assertNotIn("simulate_entrance_ring:", services_source)

    def test_ring_media_status_exposes_safe_canary_scalars(self) -> None:
        source = _method_source(RING_MEDIA, "RingMediaCoordinator", "status")
        for key in (
            "running",
            "active_event_id",
            "snapshot_event_count",
            "snapshot_sequence_last",
            "snapshot_average_interval_seconds",
            "snapshot_path",
            "recording_event_count",
            "recording_result",
        ):
            self.assertIn(key, source)

    def test_runtime_status_includes_ring_media_diagnostics(self) -> None:
        source = _method_source(RUNTIME, "ComelitRingRuntime", "status")
        self.assertIn("'ring_media'", source)
        self.assertIn("self._ring_media.status()", source)

    def test_synthetic_and_call_init_reach_same_runtime_handler(self) -> None:
        async def run() -> None:
            module = _load_runtime_module()
            runtime = _runtime_instance(module)
            calls: list[tuple[dict[str, object], bool]] = []

            async def shared(
                event: dict[str, object],
                *,
                require_media_start: bool = False,
            ) -> dict[str, object]:
                event = dict(event)
                event.setdefault("event_id", f"event-{len(calls)}")
                event.setdefault("timestamp", "2026-09-18T00:00:00+00:00")
                calls.append((dict(event), require_media_start))
                return dict(event)

            runtime._async_emit_ring_event = shared
            synthetic = await runtime.async_simulate_entrance_ring()
            self.assertTrue(synthetic["synthetic"])
            self.assertEqual(calls[-1][0]["door"], "entrance")
            self.assertTrue(calls[-1][1])

            await runtime._async_read_output(
                _FakeProcess(
                    [
                        "V4_RING_OBSERVED=true\n",
                        "V4_RING_DIRECTION=DEVICE_TO_CLIENT\n",
                        "V4_RING_KIND=CALL_INIT\n",
                        "V4_RING_DOOR=entrance\n",
                        "V4_RING_SOURCE=00000643\n",
                    ]
                )
            )
            self.assertEqual(calls[-1][0]["kind"], "CALL_INIT")
            self.assertEqual(calls[-1][0]["door"], "entrance")
            self.assertFalse(calls[-1][1])

        asyncio.run(run())

    def test_synthetic_refuses_when_listener_not_ready_or_media_busy(self) -> None:
        async def run() -> None:
            module = _load_runtime_module()
            runtime = _runtime_instance(module)
            calls: list[dict[str, object]] = []

            async def shared(
                event: dict[str, object],
                *,
                require_media_start: bool = False,
            ) -> dict[str, object]:
                del require_media_start
                calls.append(dict(event))
                return dict(event)

            runtime._async_emit_ring_event = shared
            runtime._listener_ready.clear()
            with self.assertRaisesRegex(
                module.ComelitRingRuntimeError,
                "listener_not_ready",
            ):
                await runtime.async_simulate_entrance_ring()
            self.assertEqual(calls, [])

            runtime._listener_ready.set()
            runtime._ring_media = _FakeCoordinator(running=True)
            with self.assertRaisesRegex(
                module.ComelitRingRuntimeError,
                "ring_media_busy",
            ):
                await runtime.async_simulate_entrance_ring()
            self.assertEqual(calls, [])

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
