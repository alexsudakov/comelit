#!/usr/bin/env python3
from __future__ import annotations

import ast
import asyncio
import importlib.util
from pathlib import Path
import re
import sys
import tempfile
import types
import unittest

ROOT = Path(__file__).resolve().parents[2]
SAFE_REASON = re.compile(r"^(?:[a-z0-9_]{1,64}|[a-z0-9_]{1,64}:[0-9]{1,4})$")
RETAINED_KEYS = (
    "last_start_failure",
    "last_start_failure_stage",
    "last_start_failure_at",
    "transport_last_error",
    "transport_native_exit_code",
)


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _install_ha_stubs() -> None:
    homeassistant = sys.modules.setdefault("homeassistant", types.ModuleType("homeassistant"))
    homeassistant.__path__ = []
    core = types.ModuleType("homeassistant.core")
    core.HomeAssistant = object
    sys.modules["homeassistant.core"] = core


def _load_media_session():
    return _load_module(
        "p116_r31_media_session",
        ROOT / "custom_components" / "comelit" / "media_session.py",
    )


def _load_ring_modules():
    _install_ha_stubs()
    custom_components = sys.modules.setdefault(
        "custom_components",
        types.ModuleType("custom_components"),
    )
    custom_components.__path__ = [str(ROOT / "custom_components")]
    package = sys.modules.setdefault(
        "custom_components.comelit",
        types.ModuleType("custom_components.comelit"),
    )
    package.__path__ = [str(ROOT / "custom_components" / "comelit")]
    const = _load_module(
        "custom_components.comelit.const",
        ROOT / "custom_components" / "comelit" / "const.py",
    )
    media_session = _load_module(
        "custom_components.comelit.media_session",
        ROOT / "custom_components" / "comelit" / "media_session.py",
    )
    ring_media = _load_module(
        "custom_components.comelit.ring_media",
        ROOT / "custom_components" / "comelit" / "ring_media.py",
    )
    return const, media_session, ring_media


media = _load_media_session()


class FakeListener:
    def __init__(self) -> None:
        self._paused = False
        self.fail_pause = False

    @property
    def media_paused(self) -> bool:
        return self._paused

    async def async_pause_for_media(self) -> None:
        if self.fail_pause:
            raise RuntimeError("VIP_TOKEN=deadbeef")
        self._paused = True

    async def async_resume_after_media(self) -> None:
        self._paused = False


class TransportStartError(RuntimeError):
    pass


class FakeTransport:
    def __init__(self) -> None:
        self._active = False
        self.fail_start = False
        self.last_error: str | None = None
        self.last_native_exit_code: object = None

    @property
    def active(self) -> bool:
        return self._active

    async def async_start(self, panel: str) -> None:
        if self.fail_start:
            raise TransportStartError(self.last_error or "ComelitMediaTransportError")
        self._active = True

    async def async_stop(self) -> None:
        self._active = False


def _quiet_task_factory(coro, name):
    coro.close()
    return None


class MediaStartFailureDiagnosticsTests(unittest.IsolatedAsyncioTestCase):
    def make_manager(self):
        listener = FakeListener()
        transport = FakeTransport()
        manager = media.ComelitMediaSessionManager(
            listener,
            transport,
            hard_limit_seconds=30,
            transport_watch_interval_seconds=0.01,
            task_factory=_quiet_task_factory,
        )
        return manager, listener, transport

    async def test_nested_transport_failure_reason_retained(self) -> None:
        manager, _, transport = self.make_manager()
        transport.fail_start = True
        transport.last_error = "media_native_exited_before_active:6"
        transport.last_native_exit_code = 6

        with self.assertRaises(media.ComelitMediaSessionError) as raised:
            await manager.async_acquire(panel="entrance", reason="manual")

        self.assertEqual(str(raised.exception), "media_native_exited_before_active:6")
        self.assertNotEqual(str(raised.exception), "media_start_failed")
        status = manager.status()
        self.assertEqual(
            status["transport_last_error"],
            "media_native_exited_before_active:6",
        )
        self.assertEqual(status["transport_native_exit_code"], 6)
        self.assertEqual(
            status["last_start_failure_stage"],
            media.MEDIA_START_STAGE_TRANSPORT_START,
        )

    async def test_recovery_to_inactive_keeps_historical_diagnostic(self) -> None:
        manager, listener, transport = self.make_manager()
        transport.fail_start = True
        transport.last_error = "media_native_exited_before_active:6"
        transport.last_native_exit_code = 6

        with self.assertRaises(media.ComelitMediaSessionError):
            await manager.async_acquire(panel="entrance", reason="manual")

        status = manager.status()
        self.assertEqual(status["phase"], media.MEDIA_PHASE_INACTIVE)
        self.assertIsNone(status["last_error"])
        self.assertEqual(status["last_start_failure"], "media_native_exited_before_active:6")
        self.assertEqual(status["transport_last_error"], "media_native_exited_before_active:6")
        self.assertFalse(status["listener_paused"])
        self.assertFalse(listener.media_paused)

    async def test_listener_pause_failure_does_not_report_stale_transport_error(self) -> None:
        manager, listener, transport = self.make_manager()
        stale_error = "media_native_exited_before_active:6"
        transport.fail_start = True
        transport.last_error = stale_error
        transport.last_native_exit_code = 6

        with self.assertRaises(media.ComelitMediaSessionError):
            await manager.async_acquire(panel="entrance", reason="manual")

        transport.fail_start = False
        listener.fail_pause = True
        with self.assertRaises(media.ComelitMediaSessionError) as raised:
            await manager.async_acquire(panel="entrance", reason="manual")

        reason = str(raised.exception)
        self.assertRegex(reason, SAFE_REASON)
        self.assertNotEqual(reason, stale_error)
        status = manager.status()
        self.assertEqual(
            status["last_start_failure_stage"],
            media.MEDIA_START_STAGE_LISTENER_PAUSE,
        )
        self.assertIsNone(status["transport_last_error"])
        self.assertIsNone(status["transport_native_exit_code"])
        self.assertNotIn(stale_error, repr(status))

    async def test_current_state_and_historical_failure_are_not_mixed(self) -> None:
        manager, _, transport = self.make_manager()
        transport.fail_start = True
        transport.last_error = "media_native_exited_before_active:6"
        transport.last_native_exit_code = 6
        with self.assertRaises(media.ComelitMediaSessionError):
            await manager.async_acquire(panel="entrance", reason="manual")
        failed_status = manager.status()

        transport.fail_start = False
        await manager.async_acquire(panel="entrance", reason="manual")
        active_status = manager.status()

        self.assertEqual(failed_status["phase"], media.MEDIA_PHASE_INACTIVE)
        self.assertIsNone(failed_status["last_error"])
        self.assertIsNotNone(failed_status["last_start_failure"])
        self.assertEqual(active_status["phase"], media.MEDIA_PHASE_ACTIVE)
        self.assertIsNone(active_status["last_error"])
        for key in RETAINED_KEYS:
            self.assertEqual(active_status[key], failed_status[key])

    async def test_raw_transport_values_are_suppressed(self) -> None:
        raw_values = (
            "VIP_TOKEN=deadbeefcafebabe",
            "a=candidate 1 1 UDP 1 192.168.1.85 5000 typ host",
            "/run/comelit-media/remote.sdp",
            "SomeExceptionClass",
        )
        for raw in raw_values:
            with self.subTest(raw=raw):
                manager, _, transport = self.make_manager()
                transport.fail_start = True
                transport.last_error = raw
                transport.last_native_exit_code = True

                with self.assertRaises(media.ComelitMediaSessionError) as raised:
                    await manager.async_acquire(panel="entrance", reason="manual")

                self.assertRegex(str(raised.exception), SAFE_REASON)
                status = manager.status()
                rendered = repr(status)
                self.assertNotIn(raw, rendered)
                self.assertEqual(status["last_start_failure"], "transport_error")
                self.assertIsNone(status["transport_last_error"])
                self.assertIsNone(status["transport_native_exit_code"])
                for key in (
                    "last_start_failure",
                    "last_start_failure_stage",
                    "transport_last_error",
                ):
                    value = status[key]
                    if isinstance(value, str):
                        self.assertRegex(value, SAFE_REASON)

    async def test_successful_next_start_preserves_history_unchanged(self) -> None:
        manager, _, transport = self.make_manager()
        transport.fail_start = True
        transport.last_error = "media_native_exited_before_active:6"
        transport.last_native_exit_code = 6
        with self.assertRaises(media.ComelitMediaSessionError):
            await manager.async_acquire(panel="entrance", reason="manual")
        historical = {key: manager.status()[key] for key in RETAINED_KEYS}

        transport.fail_start = False
        await manager.async_acquire(panel="entrance", reason="manual")

        for key, value in historical.items():
            self.assertEqual(manager.status()[key], value)


class FakeBus:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, object]]] = []

    def async_fire(self, event_type: str, payload: dict[str, object]) -> None:
        self.events.append((event_type, dict(payload)))


class FakeHass:
    def __init__(self) -> None:
        self.bus = FakeBus()

    async def async_add_executor_job(self, func, *args):
        return func(*args)


class FakeRingManager:
    def __init__(self, media_session_module) -> None:
        self._media_session = media_session_module
        self.active = False
        self.fail_next = True
        self.last_start_failure_stage = "transport_start"
        self.last_start_failure_at = "2026-09-18T00:00:00+00:00"
        self.transport_last_error = "media_native_exited_before_active:6"
        self.transport_native_exit_code = 6

    async def async_acquire(self, *, panel: str, reason: str) -> dict[str, object]:
        if self.fail_next:
            self.fail_next = False
            raise self._media_session.ComelitMediaSessionError("transport_error")
        self.active = True
        return {"active": True}

    async def async_release(self, *, reason: str) -> dict[str, object]:
        self.active = False
        return {"active": False}


class FakeSnapshotProvider:
    async def async_capture_jpeg(self) -> bytes | None:
        return b"\xff\xd8frame\xff\xd9"

    async def async_close(self) -> None:
        pass


class FakeRecordingProvider:
    def __init__(self, state: str) -> None:
        self.state = state

    async def async_record_mp4(
        self,
        path: Path,
        *,
        target_seconds: int,
        stop_event: asyncio.Event,
    ) -> str:
        return self.state


class RingMediaDiagnosticsTests(unittest.IsolatedAsyncioTestCase):
    async def test_ring_media_snapshot_survives_later_success_and_event_reason_stable(self) -> None:
        const, media_session, ring_media = _load_ring_modules()
        with tempfile.TemporaryDirectory() as td:
            manager = FakeRingManager(media_session)
            coordinator = ring_media.RingMediaCoordinator(
                FakeHass(),
                manager,
                snapshot_provider=FakeSnapshotProvider(),
                recording_provider=FakeRecordingProvider(const.RECORDING_STATE_COMPLETED),
                media_root=Path(td),
                recording_target_seconds=1,
            )
            paths = ring_media.safe_ring_media_paths(Path(td), "event-failed")
            await coordinator._async_run_lifecycle(
                event_id="event-failed",
                door=const.DOOR_ENTRANCE,
                paths=paths,
                stop_event=asyncio.Event(),
            )
            failed_status = coordinator.status()
            self.assertEqual(failed_status["last_start_failure"], "transport_error")
            self.assertEqual(failed_status["last_start_failure_stage"], "transport_start")
            event = [
                payload
                for event_type, payload in coordinator._hass.bus.events
                if event_type == const.EVENT_RECORDING_COMPLETE
            ][0]
            self.assertEqual(event["reason"], "media_start_failed")

            paths = ring_media.safe_ring_media_paths(Path(td), "event-success")
            await coordinator._async_run_lifecycle(
                event_id="event-success",
                door=const.DOOR_ENTRANCE,
                paths=paths,
                stop_event=asyncio.Event(),
            )
            success_status = coordinator.status()
            for key in RETAINED_KEYS:
                self.assertEqual(success_status[key], failed_status[key])


class AttributePassthroughTests(unittest.TestCase):
    def test_switch_and_camera_source_expose_retained_keys(self) -> None:
        for relative in (
            "custom_components/comelit/switch.py",
            "custom_components/comelit/camera.py",
        ):
            with self.subTest(file=relative):
                tree = ast.parse((ROOT / relative).read_text())
                method = None
                for node in ast.walk(tree):
                    if isinstance(node, ast.FunctionDef) and node.name == "extra_state_attributes":
                        method = node
                self.assertIsNotNone(method)
                constants = {
                    node.value
                    for node in ast.walk(method)
                    if isinstance(node, ast.Constant) and isinstance(node.value, str)
                }
                for key in RETAINED_KEYS:
                    self.assertIn(key, constants)


if __name__ == "__main__":
    unittest.main()
