#!/usr/bin/env python3
"""Door dispatch listener-ready availability and fail-fast guard contracts."""

from __future__ import annotations

import asyncio
import importlib.util
import logging
from pathlib import Path
import re
import sys
import types
import unittest


ROOT = Path(__file__).resolve().parents[2]
COMPONENT = ROOT / "custom_components" / "comelit"
SUPERVISOR = COMPONENT / "supervisor.py"
BUTTON = COMPONENT / "button.py"

LEAK_RE = re.compile(
    r"(?:comelit-ha-|comelit-media-|[0-9A-Fa-f]{16}|"
    r"\b(?:channel|payload|token|operation_id|event_id)=)",
)


def _install_package_stubs() -> None:
    for name in list(sys.modules):
        if name == "custom_components" or name.startswith("custom_components.comelit"):
            sys.modules.pop(name, None)
    custom_components = types.ModuleType("custom_components")
    custom_components.__path__ = [str(ROOT / "custom_components")]
    comelit = types.ModuleType("custom_components.comelit")
    comelit.__path__ = [str(COMPONENT)]
    sys.modules["custom_components"] = custom_components
    sys.modules["custom_components.comelit"] = comelit


def _install_ha_stubs() -> type[Exception]:
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


def _install_const_stub() -> None:
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
            actuation_profile_validated=True,
            configured=True,
            ring_source_validated=True,
            ring_source="00000610",
            blocked_reason=None if available else "media_session_active",
        )

    const.resolve_door_capability = resolve_door_capability
    sys.modules["custom_components.comelit.const"] = const


def _load_supervisor_module() -> types.ModuleType:
    _install_package_stubs()
    _install_ha_stubs()
    _install_const_stub()
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


def _load_button_module() -> tuple[types.ModuleType, type[Exception]]:
    HomeAssistantError = _install_ha_stubs()
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
    _install_const_stub()
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
    def __init__(self, *, running: bool = True, listener_ready: bool = True) -> None:
        self.running = running
        self.listener_ready = listener_ready
        self.attached_media_busy = False
        self.last_door_result = None
        self.open_calls = 0
        self.wait_ready_calls = 0
        self.opened: list[tuple[str, str | None]] = []

    def status(self) -> dict[str, object]:
        return {
            "running": self.running,
            "listener_ready": self.listener_ready,
            "attached_media_busy": self.attached_media_busy,
            "last_error": None,
            "last_native_exit_code": None,
            "last_native_failure_markers": [],
        }

    async def async_wait_ready(self, timeout: float) -> bool:
        self.wait_ready_calls += 1
        return self.listener_ready

    async def async_open_door(
        self,
        door: str,
        *,
        event_id: str | None = None,
    ) -> dict[str, object]:
        self.open_calls += 1
        self.opened.append((door, event_id))
        return {
            "door": door,
            "state": "UNKNOWN_OUTCOME",
            "protocol_acked": False,
            "one_shot_sequence_sent": True,
            "automatic_retry_allowed": False,
        }


class _MediaTransport:
    def __init__(self, *, active: bool) -> None:
        self.active = active
        self.open_calls = 0

    async def async_open_door(self, *, event_id: str | None = None) -> dict[str, object]:
        self.open_calls += 1
        return {
            "path": "ON_DEMAND_MEDIA_SINGLE",
            "state": "UNKNOWN_OUTCOME",
            "automatic_retry_allowed": False,
        }


class _LogCapture(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.WARNING)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


class DoorDispatchListenerReadyGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self._modules_before = dict(sys.modules)
        self._logger_names = [
            "custom_components.comelit.supervisor",
            "custom_components.comelit.button",
        ]
        self._logger_levels = {
            name: logging.getLogger(name).level for name in self._logger_names
        }
        self._logger_disabled = {
            name: logging.getLogger(name).disabled for name in self._logger_names
        }

    def tearDown(self) -> None:
        for name in list(sys.modules):
            if name not in self._modules_before:
                sys.modules.pop(name, None)
        for name, module in self._modules_before.items():
            sys.modules[name] = module
        for name, level in self._logger_levels.items():
            logger = logging.getLogger(name)
            logger.setLevel(level)
            logger.disabled = self._logger_disabled[name]

    def _load_modules(self) -> tuple[types.ModuleType, types.ModuleType, type[Exception]]:
        supervisor_module = _load_supervisor_module()
        button_module, HomeAssistantError = _load_button_module()
        return supervisor_module, button_module, HomeAssistantError

    def _make_supervisor(
        self,
        module: types.ModuleType,
        *,
        state: str,
        running: bool = True,
        listener_ready: bool = True,
    ) -> tuple[object, _Runtime]:
        runtime = _Runtime(running=running, listener_ready=listener_ready)
        supervisor = module.ComelitRuntimeSupervisor(object(), runtime, entry=_Entry())
        supervisor._set_state(state)
        return supervisor, runtime

    def _buttons(
        self,
        supervisor_module: types.ModuleType,
        button_module: types.ModuleType,
        *,
        state: str,
        running: bool = True,
        listener_ready: bool = True,
        media: _MediaTransport | None = None,
    ) -> tuple[object, object, object, _Runtime]:
        supervisor, runtime = self._make_supervisor(
            supervisor_module,
            state=state,
            running=running,
            listener_ready=listener_ready,
        )
        entrance = button_module.ComelitEntranceDoorButton(runtime, supervisor, media)
        gate = button_module.ComelitGateDoorButton(runtime, supervisor)
        return supervisor, entrance, gate, runtime

    def _capture_supervisor_logs(self) -> tuple[logging.Logger, _LogCapture]:
        logger = logging.getLogger("custom_components.comelit.supervisor")
        logger.setLevel(logging.WARNING)
        logger.disabled = False
        capture = _LogCapture()
        logger.addHandler(capture)
        return logger, capture

    def _assert_markers(self, messages: list[str], *markers: str) -> None:
        joined = "\n".join(messages)
        for marker in markers:
            with self.subTest(marker=marker):
                self.assertIn(marker, joined)
        self.assertNotRegex(joined, LEAK_RE)

    def test_ready_makes_entrance_and_gate_buttons_available(self) -> None:
        supervisor_module, button_module, _ = self._load_modules()
        _, entrance, gate, _ = self._buttons(
            supervisor_module,
            button_module,
            state=supervisor_module.LISTENER_STATE_READY,
        )
        self.assertTrue(entrance.available)
        self.assertTrue(gate.available)

    def test_starting_makes_entrance_and_gate_buttons_unavailable(self) -> None:
        supervisor_module, button_module, _ = self._load_modules()
        _, entrance, gate, _ = self._buttons(
            supervisor_module,
            button_module,
            state=supervisor_module.LISTENER_STATE_STARTING,
        )
        self.assertFalse(entrance.available)
        self.assertFalse(gate.available)

    def test_reconnecting_makes_entrance_and_gate_buttons_unavailable(self) -> None:
        supervisor_module, button_module, _ = self._load_modules()
        _, entrance, gate, _ = self._buttons(
            supervisor_module,
            button_module,
            state=supervisor_module.LISTENER_STATE_RECONNECTING,
        )
        self.assertFalse(entrance.available)
        self.assertFalse(gate.available)

    def test_error_and_stopped_make_entrance_and_gate_buttons_unavailable(self) -> None:
        supervisor_module, button_module, _ = self._load_modules()
        for state in (
            supervisor_module.LISTENER_STATE_ERROR,
            supervisor_module.LISTENER_STATE_STOPPED,
        ):
            with self.subTest(state=state):
                _, entrance, gate, _ = self._buttons(
                    supervisor_module,
                    button_module,
                    state=state,
                )
                self.assertFalse(entrance.available)
                self.assertFalse(gate.available)

    def test_media_paused_active_transport_keeps_entrance_available_and_uses_media_owner(self) -> None:
        supervisor_module, button_module, _ = self._load_modules()
        media = _MediaTransport(active=True)
        supervisor, entrance, _, runtime = self._buttons(
            supervisor_module,
            button_module,
            state=supervisor_module.LISTENER_STATE_STOPPED,
            running=False,
            listener_ready=False,
            media=media,
        )
        supervisor._media_paused = True
        self.assertTrue(entrance.available)
        logger, capture = self._capture_supervisor_logs()
        try:
            result = asyncio.run(supervisor.async_open_entrance_door(media))
        finally:
            logger.removeHandler(capture)
        self.assertEqual(result["path"], "ON_DEMAND_MEDIA_SINGLE")
        self.assertEqual(media.open_calls, 1)
        self.assertEqual(runtime.open_calls, 0)
        self._assert_markers(
            capture.messages,
            "DOOR_DISPATCH_REQUESTED",
            "DOOR_LIFECYCLE_LOCK_ACQUIRED",
            "DOOR_DISPATCH_OWNER=ON_DEMAND_MEDIA",
        )

    def test_media_paused_without_active_owner_makes_entrance_unavailable(self) -> None:
        supervisor_module, button_module, _ = self._load_modules()
        for media in (None, _MediaTransport(active=False)):
            with self.subTest(media=media):
                supervisor, entrance, _, _ = self._buttons(
                    supervisor_module,
                    button_module,
                    state=supervisor_module.LISTENER_STATE_READY,
                    media=media,
                )
                supervisor._media_paused = True
                self.assertFalse(entrance.available)
        supervisor, _, _, _ = self._buttons(
            supervisor_module,
            button_module,
            state=supervisor_module.LISTENER_STATE_READY,
            media=None,
        )
        supervisor._media_paused = True
        logger, capture = self._capture_supervisor_logs()
        try:
            with self.assertRaisesRegex(RuntimeError, "media_door_not_ready"):
                asyncio.run(supervisor.async_open_entrance_door(None))
        finally:
            logger.removeHandler(capture)
        self._assert_markers(
            capture.messages,
            "DOOR_DISPATCH_REQUESTED",
            "DOOR_LIFECYCLE_LOCK_ACQUIRED",
            "DOOR_DISPATCH_REJECT_REASON=MEDIA_NOT_READY",
        )

    def test_listener_dies_between_availability_and_press_rejects_fast_without_runtime_wait(self) -> None:
        supervisor_module, button_module, _ = self._load_modules()
        supervisor, entrance, _, runtime = self._buttons(
            supervisor_module,
            button_module,
            state=supervisor_module.LISTENER_STATE_READY,
        )
        self.assertTrue(entrance.available)
        runtime.listener_ready = False
        logger, capture = self._capture_supervisor_logs()
        try:
            with self.assertRaisesRegex(RuntimeError, "listener_not_ready"):
                asyncio.run(supervisor.async_open_entrance_door(None))
        finally:
            logger.removeHandler(capture)
        self.assertEqual(runtime.open_calls, 0)
        self.assertEqual(runtime.wait_ready_calls, 0)
        self._assert_markers(
            capture.messages,
            "DOOR_DISPATCH_REQUESTED",
            "DOOR_LIFECYCLE_LOCK_ACQUIRED",
            "DOOR_DISPATCH_REJECT_REASON=LISTENER_NOT_READY",
        )

    def test_stable_ready_invokes_listener_door_once_without_automatic_retry(self) -> None:
        supervisor_module, _, _ = self._load_modules()
        supervisor, runtime = self._make_supervisor(
            supervisor_module,
            state=supervisor_module.LISTENER_STATE_READY,
        )
        logger, capture = self._capture_supervisor_logs()
        try:
            result = asyncio.run(supervisor.async_open_entrance_door(None))
        finally:
            logger.removeHandler(capture)
        self.assertEqual(runtime.open_calls, 1)
        self.assertIs(result["automatic_retry_allowed"], False)
        self.assertEqual(runtime.opened, [("entrance", None)])
        self._assert_markers(
            capture.messages,
            "DOOR_DISPATCH_REQUESTED",
            "DOOR_LIFECYCLE_LOCK_ACQUIRED",
            "DOOR_DISPATCH_OWNER=LISTENER",
        )

    def test_gate_receives_same_listener_ready_guard(self) -> None:
        supervisor_module, _, _ = self._load_modules()
        supervisor, runtime = self._make_supervisor(
            supervisor_module,
            state=supervisor_module.LISTENER_STATE_READY,
        )
        result = asyncio.run(supervisor.async_open_gate_door())
        self.assertEqual(runtime.open_calls, 1)
        self.assertEqual(runtime.opened, [("gate", None)])
        self.assertIs(result["automatic_retry_allowed"], False)

        supervisor, runtime = self._make_supervisor(
            supervisor_module,
            state=supervisor_module.LISTENER_STATE_READY,
            listener_ready=False,
        )
        logger, capture = self._capture_supervisor_logs()
        try:
            with self.assertRaisesRegex(RuntimeError, "listener_not_ready"):
                asyncio.run(supervisor.async_open_gate_door())
        finally:
            logger.removeHandler(capture)
        self.assertEqual(runtime.open_calls, 0)
        self._assert_markers(
            capture.messages,
            "DOOR_DISPATCH_REQUESTED",
            "DOOR_LIFECYCLE_LOCK_ACQUIRED",
            "DOOR_DISPATCH_REJECT_REASON=LISTENER_NOT_READY",
        )

    def test_rejected_dispatch_has_no_retry_loop_and_recovery_reason_wins(self) -> None:
        supervisor_module, _, _ = self._load_modules()
        supervisor, runtime = self._make_supervisor(
            supervisor_module,
            state=supervisor_module.LISTENER_STATE_READY,
            listener_ready=False,
        )
        with self.assertRaisesRegex(RuntimeError, "listener_not_ready"):
            asyncio.run(supervisor.async_open_entrance_door(None))
        self.assertLessEqual(runtime.open_calls, 1)
        self.assertEqual(runtime.open_calls, 0)

        supervisor, runtime = self._make_supervisor(
            supervisor_module,
            state=supervisor_module.LISTENER_STATE_READY,
            listener_ready=False,
        )
        supervisor._attached_stop_recovery_required = True
        logger, capture = self._capture_supervisor_logs()
        try:
            with self.assertRaisesRegex(
                RuntimeError,
                supervisor_module.ATTACHED_STOP_RECOVERY_ERROR,
            ):
                asyncio.run(supervisor.async_open_entrance_door(None))
        finally:
            logger.removeHandler(capture)
        self.assertEqual(runtime.open_calls, 0)
        self._assert_markers(
            capture.messages,
            "DOOR_DISPATCH_REQUESTED",
            "DOOR_LIFECYCLE_LOCK_ACQUIRED",
            "DOOR_DISPATCH_REJECT_REASON=RECOVERY_BLOCKED",
        )

    def test_button_press_maps_listener_not_ready_to_distinct_home_assistant_error(self) -> None:
        supervisor_module, button_module, HomeAssistantError = self._load_modules()
        supervisor, entrance, gate, runtime = self._buttons(
            supervisor_module,
            button_module,
            state=supervisor_module.LISTENER_STATE_READY,
            listener_ready=False,
        )
        self.assertFalse(entrance.available)
        with self.assertRaisesRegex(HomeAssistantError, "listener is not ready"):
            asyncio.run(entrance.async_press())
        with self.assertRaisesRegex(HomeAssistantError, "listener is not ready"):
            asyncio.run(gate.async_press())
        self.assertEqual(runtime.open_calls, 0)
        self.assertFalse(supervisor.listener_dispatch_ready)


if __name__ == "__main__":
    unittest.main()
