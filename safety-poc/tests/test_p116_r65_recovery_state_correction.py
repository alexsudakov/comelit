#!/usr/bin/env python3
"""Regression contracts for attached-stop recovery state preservation."""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
import sys
import types
import unittest

ROOT = Path(__file__).resolve().parents[2]
SUPERVISOR = ROOT / "custom_components" / "comelit" / "supervisor.py"


def _load_supervisor_module() -> types.ModuleType:
    for name in list(sys.modules):
        if name == "homeassistant" or name.startswith("homeassistant."):
            sys.modules.pop(name, None)
        if name == "custom_components" or name.startswith("custom_components.comelit"):
            sys.modules.pop(name, None)

    custom_components = types.ModuleType("custom_components")
    custom_components.__path__ = [str(ROOT / "custom_components")]
    comelit = types.ModuleType("custom_components.comelit")
    comelit.__path__ = [str(ROOT / "custom_components" / "comelit")]
    sys.modules["custom_components"] = custom_components
    sys.modules["custom_components.comelit"] = comelit

    homeassistant = types.ModuleType("homeassistant")
    config_entries = types.ModuleType("homeassistant.config_entries")
    config_entries.ConfigEntry = object
    core = types.ModuleType("homeassistant.core")
    core.HomeAssistant = object
    sys.modules["homeassistant"] = homeassistant
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


class _DoneTask:
    def done(self) -> bool:
        return True

    def cancel(self) -> None:
        return None


class _Entry:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def async_create_background_task(
        self,
        hass: object,
        coro: object,
        name: str,
    ) -> _DoneTask:
        self.events.append(f"task:{name}")
        close = getattr(coro, "close", None)
        if close is not None:
            close()
        return _DoneTask()


class _Runtime:
    def __init__(
        self,
        events: list[str],
        *,
        stop_failure_stage: str | None = "QUEUE",
        fail_stop: bool = False,
        ready_after_start: bool = True,
    ) -> None:
        self.events = events
        self.stop_failure_stage = stop_failure_stage
        self.fail_stop = fail_stop
        self.ready_after_start = ready_after_start
        self.running = True
        self.listener_ready = True
        self.attached_media_busy = True
        self.supervisor: object | None = None
        self.start_count = 0
        self.recovery_required_observed: list[bool] = []

    def status(self) -> dict[str, object]:
        return {
            "running": self.running,
            "listener_ready": self.listener_ready,
            "attached_media_busy": self.attached_media_busy,
            "last_error": None,
            "last_native_exit_code": None,
            "last_native_failure_markers": [],
            "last_attached_stop_failure_stage": self.stop_failure_stage,
        }

    async def async_stop(self) -> None:
        self.events.append("runtime_stop")
        if self.fail_stop:
            raise RuntimeError("runtime_stop_not_confirmed")
        self.running = False
        self.listener_ready = False
        self.attached_media_busy = False

    async def async_start(self) -> None:
        self.events.append("runtime_start")
        self.start_count += 1
        if self.supervisor is not None:
            self.recovery_required_observed.append(
                bool(self.supervisor._attached_stop_recovery_required)
            )
        # Match the production runtime: a fresh start clears its current-cycle
        # R58 marker, so the supervisor must retain the historical cause.
        self.stop_failure_stage = None
        self.running = True
        self.listener_ready = self.ready_after_start

    async def async_wait_ready(self, timeout: float) -> bool:
        self.events.append("runtime_wait_ready")
        if self.supervisor is not None:
            self.recovery_required_observed.append(
                bool(self.supervisor._attached_stop_recovery_required)
            )
        return self.listener_ready

    async def async_open_door(self, door: str, *, event_id: str | None = None) -> dict[str, object]:
        self.events.append(f"door:{door}")
        return {"door": door, "event_id": event_id}


class AttachedRecoveryStateCorrectionTests(unittest.TestCase):
    def _make(
        self,
        *,
        stop_failure_stage: str | None = "QUEUE",
        fail_stop: bool = False,
        ready_after_start: bool = True,
    ) -> tuple[types.ModuleType, _Runtime, object, list[str]]:
        module = _load_supervisor_module()
        events: list[str] = []
        runtime = _Runtime(
            events,
            stop_failure_stage=stop_failure_stage,
            fail_stop=fail_stop,
            ready_after_start=ready_after_start,
        )
        supervisor = module.ComelitRuntimeSupervisor(
            object(),
            runtime,
            entry=_Entry(events),
        )
        runtime.supervisor = supervisor
        return module, runtime, supervisor, events

    def test_r58_failure_stage_survives_successful_recycle(self) -> None:
        _, runtime, supervisor, _ = self._make(stop_failure_stage="QUEUE")
        asyncio.run(supervisor.async_recover_attached_media_stop_failure())
        self.assertIsNone(runtime.stop_failure_stage)
        self.assertEqual(
            supervisor.status()["last_attached_stop_failure_stage"],
            "QUEUE",
        )

    def test_unknown_r58_failure_stage_is_not_retained(self) -> None:
        _, _, supervisor, _ = self._make(stop_failure_stage="raw-secret-value")
        asyncio.run(supervisor.async_recover_attached_media_stop_failure())
        self.assertIsNone(supervisor.status()["last_attached_stop_failure_stage"])

    def test_recovery_required_stays_true_through_fresh_start_and_ready_wait(self) -> None:
        _, runtime, supervisor, _ = self._make()
        asyncio.run(supervisor.async_recover_attached_media_stop_failure())
        self.assertEqual(runtime.recovery_required_observed, [True, True])
        self.assertFalse(supervisor.status()["attached_stop_recovery_required"])
        self.assertIsNone(supervisor.status()["last_attached_stop_recovery_error"])

    def test_ready_timeout_keeps_recovery_required_and_fails_closed(self) -> None:
        module, runtime, supervisor, events = self._make(ready_after_start=False)
        with self.assertRaisesRegex(RuntimeError, module.ATTACHED_STOP_RECOVERY_ERROR):
            asyncio.run(supervisor.async_recover_attached_media_stop_failure())
        self.assertTrue(supervisor.status()["attached_stop_recovery_required"])
        self.assertEqual(
            supervisor.status()["last_attached_stop_recovery_error"],
            "listener_ready_not_confirmed",
        )
        self.assertEqual(supervisor.state, module.LISTENER_STATE_ERROR)
        self.assertEqual(runtime.start_count, 1)
        self.assertEqual(events.count("runtime_stop"), 2)

    def test_old_runtime_stop_failure_never_starts_replacement(self) -> None:
        module, runtime, supervisor, events = self._make(fail_stop=True)
        with self.assertRaisesRegex(RuntimeError, module.ATTACHED_STOP_RECOVERY_ERROR):
            asyncio.run(supervisor.async_recover_attached_media_stop_failure())
        self.assertTrue(supervisor.status()["attached_stop_recovery_required"])
        self.assertEqual(runtime.start_count, 0)
        self.assertNotIn("runtime_start", events)

    def test_public_start_cannot_override_failed_recovery_gate(self) -> None:
        module, runtime, supervisor, _ = self._make()
        runtime.running = False
        runtime.listener_ready = False
        supervisor._attached_stop_recovery_required = True
        with self.assertRaisesRegex(RuntimeError, module.ATTACHED_STOP_RECOVERY_ERROR):
            asyncio.run(supervisor.async_start())
        self.assertEqual(runtime.start_count, 0)
        self.assertEqual(supervisor.state, module.LISTENER_STATE_ERROR)

    def test_door_and_media_pause_are_blocked_while_recovery_is_required(self) -> None:
        module, runtime, supervisor, _ = self._make()
        supervisor._attached_stop_recovery_required = True
        with self.assertRaisesRegex(RuntimeError, module.ATTACHED_STOP_RECOVERY_ERROR):
            asyncio.run(supervisor.async_pause_for_media())
        with self.assertRaisesRegex(RuntimeError, module.ATTACHED_STOP_RECOVERY_ERROR):
            asyncio.run(supervisor.async_open_gate_door())
        self.assertEqual(runtime.start_count, 0)

    def test_reconnect_path_contains_recovery_gate(self) -> None:
        source = SUPERVISOR.read_text(encoding="utf-8")
        self.assertIn("if self._attached_stop_recovery_required:", source)
        self.assertIn("or self._attached_stop_recovery_required", source)
        self.assertNotIn(
            "self._attached_stop_recovery_required = False\n        self._last_attached_stop_recovery_error = None\n        self._stopping = False",
            source,
        )


if __name__ == "__main__":
    unittest.main()
