#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "custom_components" / "comelit" / "media_session.py"
spec = importlib.util.spec_from_file_location("comelit_media_session", MODULE_PATH)
media = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(media)


class FakeListener:
    def __init__(self, events: list[str]) -> None:
        self._paused = False
        self.events = events
        self.fail_resume = False

    @property
    def media_paused(self) -> bool:
        return self._paused

    async def async_pause_for_media(self) -> None:
        self.events.append("listener_pause")
        self._paused = True

    async def async_resume_after_media(self) -> None:
        self.events.append("listener_resume")
        if self.fail_resume:
            raise RuntimeError("resume failed")
        self._paused = False


class FakeTransport:
    def __init__(self, events: list[str]) -> None:
        self._active = False
        self.events = events
        self.fail_start = False
        self.fail_stop = False

    @property
    def active(self) -> bool:
        return self._active

    async def async_start(self, panel: str) -> None:
        self.events.append(f"media_start:{panel}")
        if self.fail_start:
            raise RuntimeError("start failed")
        self._active = True

    async def async_stop(self) -> None:
        self.events.append("media_stop")
        if self.fail_stop:
            raise RuntimeError("stop failed")
        self._active = False

    def simulate_process_exit(self) -> None:
        self.events.append("media_process_exit")
        self._active = False


class P80MediaSessionManagerTests(unittest.IsolatedAsyncioTestCase):
    def make_manager(
        self,
        *,
        hard_limit_seconds: float = 180,
        watch_interval_seconds: float = 0.01,
    ):
        events: list[str] = []
        listener = FakeListener(events)
        transport = FakeTransport(events)
        manager = media.ComelitMediaSessionManager(
            listener,
            transport,
            hard_limit_seconds=hard_limit_seconds,
            transport_watch_interval_seconds=watch_interval_seconds,
        )
        return manager, listener, transport, events

    async def test_listener_is_paused_before_media_and_restored_after_stop(self) -> None:
        manager, listener, transport, events = self.make_manager()

        await manager.async_acquire(panel="entrance", reason="manual")
        self.assertTrue(manager.active)
        self.assertTrue(listener.media_paused)
        self.assertEqual(events[:2], ["listener_pause", "media_start:entrance"])

        await manager.async_force_stop(reason="manual_off")
        self.assertFalse(manager.active)
        self.assertFalse(listener.media_paused)
        self.assertEqual(events[-2:], ["media_stop", "listener_resume"])
        self.assertEqual(manager.phase, media.MEDIA_PHASE_INACTIVE)

    async def test_new_lease_does_not_extend_absolute_deadline(self) -> None:
        manager, _, _, _ = self.make_manager()
        first = await manager.async_acquire(panel="entrance", reason="manual")
        await asyncio.sleep(0)
        second = await manager.async_acquire(panel="entrance", reason="snapshot")

        self.assertEqual(first["expires_at"], second["expires_at"])
        self.assertEqual(second["leases"], {"manual": 1, "snapshot": 1})

        await manager.async_force_stop(reason="test_cleanup")

    async def test_last_lease_release_tears_down_and_restores_listener(self) -> None:
        manager, listener, _, events = self.make_manager()
        await manager.async_acquire(panel="entrance", reason="manual")
        await manager.async_acquire(panel="entrance", reason="snapshot")

        await manager.async_release(reason="snapshot")
        self.assertTrue(manager.active)
        self.assertTrue(listener.media_paused)

        await manager.async_release(reason="manual")
        self.assertFalse(manager.active)
        self.assertFalse(listener.media_paused)
        self.assertEqual(events[-2:], ["media_stop", "listener_resume"])

    async def test_failed_start_restores_listener(self) -> None:
        manager, listener, transport, events = self.make_manager()
        transport.fail_start = True

        with self.assertRaises(media.ComelitMediaSessionError):
            await manager.async_acquire(panel="entrance", reason="manual")

        self.assertFalse(listener.media_paused)
        self.assertFalse(transport.active)
        self.assertEqual(manager.phase, media.MEDIA_PHASE_INACTIVE)
        self.assertEqual(events, ["listener_pause", "media_start:entrance", "listener_resume"])

    async def test_failed_teardown_keeps_listener_paused_fail_closed(self) -> None:
        manager, listener, transport, events = self.make_manager()
        await manager.async_acquire(panel="entrance", reason="manual")
        transport.fail_stop = True

        status = await manager.async_force_stop(reason="manual_off")

        self.assertEqual(status["phase"], media.MEDIA_PHASE_ERROR)
        self.assertTrue(listener.media_paused)
        self.assertTrue(transport.active)
        self.assertNotIn("listener_resume", events)

    async def test_hard_timeout_is_absolute_and_forces_teardown(self) -> None:
        manager, listener, transport, _ = self.make_manager(hard_limit_seconds=0.02)
        await manager.async_acquire(panel="entrance", reason="manual")
        await asyncio.sleep(0.06)

        self.assertEqual(manager.phase, media.MEDIA_PHASE_INACTIVE)
        self.assertFalse(listener.media_paused)
        self.assertFalse(transport.active)

    async def test_confirmed_transport_exit_restores_listener_before_hard_timeout(self) -> None:
        manager, listener, transport, events = self.make_manager(
            hard_limit_seconds=10,
            watch_interval_seconds=0.005,
        )
        await manager.async_acquire(panel="entrance", reason="manual")
        transport.simulate_process_exit()
        await asyncio.sleep(0.03)

        self.assertEqual(manager.phase, media.MEDIA_PHASE_INACTIVE)
        self.assertFalse(listener.media_paused)
        self.assertFalse(transport.active)
        self.assertIn("media_process_exit", events)
        self.assertEqual(events[-1], "listener_resume")

    async def test_unsupported_panel_fails_before_listener_pause(self) -> None:
        manager, listener, transport, events = self.make_manager()
        with self.assertRaises(media.ComelitMediaSessionError):
            await manager.async_acquire(panel="gate", reason="manual")
        self.assertFalse(listener.media_paused)
        self.assertFalse(transport.active)
        self.assertEqual(events, [])


if __name__ == "__main__":
    unittest.main()
