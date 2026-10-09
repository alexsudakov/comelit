#!/usr/bin/env python3
"""Door dispatch must fail closed while the connection lifecycle lock is busy."""

from __future__ import annotations

import asyncio
import importlib.util
import logging
from pathlib import Path
import sys
import types
import unittest


ROOT = Path(__file__).resolve().parents[2]
COMPONENT = ROOT / "custom_components" / "comelit"
SUPERVISOR = COMPONENT / "supervisor.py"
BUTTON = COMPONENT / "button.py"


def _install_package() -> None:
    for name in list(sys.modules):
        if name == "custom_components" or name.startswith("custom_components.comelit"):
            sys.modules.pop(name, None)
    package = types.ModuleType("custom_components")
    package.__path__ = [str(ROOT / "custom_components")]
    comelit = types.ModuleType("custom_components.comelit")
    comelit.__path__ = [str(COMPONENT)]
    sys.modules["custom_components"] = package
    sys.modules["custom_components.comelit"] = comelit


def _install_ha() -> type[Exception]:
    sys.modules["homeassistant"] = types.ModuleType("homeassistant")
    config_entries = types.ModuleType("homeassistant.config_entries")
    config_entries.ConfigEntry = object
    core = types.ModuleType("homeassistant.core")
    core.HomeAssistant = object
    exceptions = types.ModuleType("homeassistant.exceptions")
    HomeAssistantError = type("HomeAssistantError", (Exception,), {})
    exceptions.HomeAssistantError = HomeAssistantError
    sys.modules["homeassistant.config_entries"] = config_entries
    sys.modules["homeassistant.core"] = core
    sys.modules["homeassistant.exceptions"] = exceptions
    return HomeAssistantError


def _install_const() -> None:
    const = types.ModuleType("custom_components.comelit.const")
    const.DATA_MEDIA_TRANSPORTS = "media_transports"
    const.DATA_RUNTIMES = "runtimes"
    const.DATA_SUPERVISORS = "supervisors"
    const.DOMAIN = "comelit"
    const.DOOR_ENTRANCE = "entrance"
    const.DOOR_GATE = "gate"
    const.LISTENER_CYCLE_SECONDS = 3300
    const.MAIN_ENTRANCE_ENTITY_ID = "button.entrance"
    const.MAIN_ENTRANCE_UNIQUE_ID = "entrance"
    const.MAIN_GATE_ENTITY_ID = "button.gate"
    const.MAIN_GATE_UNIQUE_ID = "gate"

    def resolve_door_capability(door: str, *, media_paused: bool) -> object:
        available = not (door == "gate" and media_paused)
        return types.SimpleNamespace(
            available=available,
            press_allowed=available,
            configured=True,
            ring_source_validated=True,
            actuation_profile_validated=True,
            ring_source="00000610" if door == "gate" else None,
            blocked_reason=None,
        )

    const.resolve_door_capability = resolve_door_capability
    sys.modules["custom_components.comelit.const"] = const


def _load_supervisor() -> types.ModuleType:
    _install_package()
    _install_ha()
    _install_const()
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


def _load_button() -> tuple[types.ModuleType, type[Exception]]:
    _install_package()
    HomeAssistantError = _install_ha()
    _install_const()
    components = types.ModuleType("homeassistant.components")
    sys.modules["homeassistant.components"] = components
    button_component = types.ModuleType("homeassistant.components.button")

    class ButtonEntity:
        async def async_added_to_hass(self) -> None:
            return None

        def async_on_remove(self, callback: object) -> None:
            return None

        def async_write_ha_state(self) -> None:
            return None

    button_component.ButtonEntity = ButtonEntity
    sys.modules["homeassistant.components.button"] = button_component
    helpers = types.ModuleType("homeassistant.helpers")
    sys.modules["homeassistant.helpers"] = helpers
    entity_platform = types.ModuleType("homeassistant.helpers.entity_platform")
    entity_platform.AddEntitiesCallback = object
    sys.modules["homeassistant.helpers.entity_platform"] = entity_platform
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


class _Entry:
    def async_create_background_task(self, hass: object, coro: object, name: str) -> object:
        close = getattr(coro, "close", None)
        if close is not None:
            close()
        return types.SimpleNamespace(done=lambda: True, cancel=lambda: None)


class _Runtime:
    def __init__(self) -> None:
        self.running = True
        self.listener_ready = True
        self.attached_media_busy = False
        self.last_door_result = None
        self.open_calls = 0
        self.opened: list[str] = []

    def status(self) -> dict[str, object]:
        return {
            "running": self.running,
            "listener_ready": self.listener_ready,
            "attached_media_busy": False,
            "last_error": None,
            "last_native_exit_code": None,
            "last_native_failure_markers": [],
        }

    async def async_open_door(
        self,
        door: str,
        *,
        event_id: str | None = None,
    ) -> dict[str, object]:
        self.open_calls += 1
        self.opened.append(door)
        return {
            "state": "UNKNOWN_OUTCOME",
            "one_shot_sequence_sent": True,
            "automatic_retry_allowed": False,
        }


class _Media:
    active = True

    def __init__(self) -> None:
        self.open_calls = 0

    async def async_open_door(self, *, event_id: str | None = None) -> dict[str, object]:
        self.open_calls += 1
        return {
            "path": "ON_DEMAND_MEDIA_SINGLE",
            "state": "UNKNOWN_OUTCOME",
            "automatic_retry_allowed": False,
        }


class _Capture(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.WARNING)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


class DoorLifecycleBusyTests(unittest.TestCase):
    def _make(self) -> tuple[types.ModuleType, object, _Runtime]:
        module = _load_supervisor()
        module.DOOR_LIFECYCLE_LOCK_TIMEOUT_SECONDS = 0.01
        runtime = _Runtime()
        supervisor = module.ComelitRuntimeSupervisor(object(), runtime, entry=_Entry())
        supervisor._set_state(module.LISTENER_STATE_READY)
        return module, supervisor, runtime

    def _capture(self) -> tuple[logging.Logger, _Capture]:
        logger = logging.getLogger("custom_components.comelit.supervisor")
        logger.setLevel(logging.WARNING)
        logger.disabled = False
        capture = _Capture()
        logger.addHandler(capture)
        return logger, capture

    def test_production_timeout_is_bounded(self) -> None:
        module = _load_supervisor()
        self.assertGreater(module.DOOR_LIFECYCLE_LOCK_TIMEOUT_SECONDS, 0)
        self.assertLessEqual(module.DOOR_LIFECYCLE_LOCK_TIMEOUT_SECONDS, 1.0)

    def test_entrance_busy_rejects_and_stale_request_never_actuates(self) -> None:
        _, supervisor, runtime = self._make()
        logger, capture = self._capture()

        async def scenario() -> None:
            await supervisor._lifecycle_lock.acquire()
            try:
                with self.assertRaisesRegex(RuntimeError, "lifecycle_busy"):
                    await supervisor.async_open_entrance_door(None)
                self.assertEqual(runtime.open_calls, 0)
            finally:
                supervisor._lifecycle_lock.release()
            await asyncio.sleep(0)
            self.assertEqual(runtime.open_calls, 0)

        try:
            asyncio.run(scenario())
        finally:
            logger.removeHandler(capture)
        joined = "\n".join(capture.messages)
        self.assertIn("DOOR_DISPATCH_REQUESTED", joined)
        self.assertIn("DOOR_DISPATCH_REJECT_REASON=LIFECYCLE_BUSY", joined)
        self.assertNotIn("DOOR_LIFECYCLE_LOCK_ACQUIRED", joined)
        self.assertNotIn("DOOR_DISPATCH_OWNER=", joined)

    def test_gate_busy_rejects_without_runtime_tx(self) -> None:
        _, supervisor, runtime = self._make()

        async def scenario() -> None:
            await supervisor._lifecycle_lock.acquire()
            try:
                with self.assertRaisesRegex(RuntimeError, "lifecycle_busy"):
                    await supervisor.async_open_gate_door()
            finally:
                supervisor._lifecycle_lock.release()
            await asyncio.sleep(0)

        asyncio.run(scenario())
        self.assertEqual(runtime.open_calls, 0)

    def test_new_press_after_busy_rejection_is_independent_and_works(self) -> None:
        _, supervisor, runtime = self._make()

        async def scenario() -> None:
            await supervisor._lifecycle_lock.acquire()
            try:
                with self.assertRaisesRegex(RuntimeError, "lifecycle_busy"):
                    await supervisor.async_open_entrance_door(None)
            finally:
                supervisor._lifecycle_lock.release()
            self.assertEqual(runtime.open_calls, 0)
            result = await supervisor.async_open_entrance_door(None)
            self.assertFalse(result["automatic_retry_allowed"])

        asyncio.run(scenario())
        self.assertEqual(runtime.open_calls, 1)
        self.assertEqual(runtime.opened, ["entrance"])

    def test_rejected_listener_request_cannot_switch_to_media_owner_after_release(self) -> None:
        _, supervisor, runtime = self._make()
        media = _Media()

        async def scenario() -> None:
            await supervisor._lifecycle_lock.acquire()
            try:
                task = asyncio.create_task(supervisor.async_open_entrance_door(media))
                await asyncio.sleep(0)
                supervisor._media_paused = True
                with self.assertRaisesRegex(RuntimeError, "lifecycle_busy"):
                    await task
            finally:
                supervisor._lifecycle_lock.release()
            await asyncio.sleep(0)
            self.assertEqual(runtime.open_calls, 0)
            self.assertEqual(media.open_calls, 0)
            result = await supervisor.async_open_entrance_door(media)
            self.assertEqual(result["path"], "ON_DEMAND_MEDIA_SINGLE")

        asyncio.run(scenario())
        self.assertEqual(runtime.open_calls, 0)
        self.assertEqual(media.open_calls, 1)

    def test_buttons_map_lifecycle_busy_to_distinct_ha_error(self) -> None:
        button_module, HomeAssistantError = _load_button()

        async def entrance_busy(media: object) -> dict[str, object]:
            raise RuntimeError("lifecycle_busy")

        async def gate_busy() -> dict[str, object]:
            raise RuntimeError("lifecycle_busy")

        supervisor = types.SimpleNamespace(
            media_paused=False,
            listener_dispatch_ready=True,
            async_add_status_listener=lambda callback: lambda: None,
            async_open_entrance_door=entrance_busy,
            async_open_gate_door=gate_busy,
        )
        runtime = types.SimpleNamespace(last_door_result=None)
        entrance = button_module.ComelitEntranceDoorButton(runtime, supervisor, None)
        gate = button_module.ComelitGateDoorButton(runtime, supervisor)
        with self.assertRaisesRegex(HomeAssistantError, "lifecycle is busy"):
            asyncio.run(entrance.async_press())
        with self.assertRaisesRegex(HomeAssistantError, "lifecycle is busy"):
            asyncio.run(gate.async_press())


if __name__ == "__main__":
    unittest.main()
