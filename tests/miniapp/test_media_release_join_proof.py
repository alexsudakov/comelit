"""Regression tests for local media teardown before listener recovery.

Uses the public session boundary plus a real transport stop method; no network,
HA reload, live Ring or native helper is invoked.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests" / "miniapp" / "tools"))
from optionf_pr1a_replay import _load_component_module


class Listener:
    def __init__(self):
        self.media_paused = False
        self.resume_count = 0
        self.proofs = []

    async def async_pause_for_media(self):
        self.media_paused = True

    async def async_resume_after_media(self):
        self.resume_count += 1
        self.media_paused = False

    async def async_confirm_media_owner_released(self, **values):
        self.proofs.append(values)


class ExitDuringCleanupTransport:
    """Simulates a dead native process with async cleanup still running."""
    def __init__(self, *, fail_cleanup=False):
        self.active = False
        self.stop_called = False
        self.cleanup_finished = asyncio.Event()
        self.cleanup_allowed = asyncio.Event()
        self.fail_cleanup = fail_cleanup

    async def async_start(self, panel):
        self.active = True

    async def async_stop(self):
        self.stop_called = True
        self.active = False  # native already exited
        await self.cleanup_allowed.wait()
        if self.fail_cleanup:
            raise RuntimeError("local_cleanup_failed")
        self.cleanup_finished.set()


def test_native_exit_does_not_resume_listener_before_transport_cleanup():
    async def run():
        media = _load_component_module(str(ROOT), "media_session")
        listener = Listener()
        transport = ExitDuringCleanupTransport()
        manager = media.ComelitMediaSessionManager(listener, transport)
        await manager.async_acquire(panel="entrance", reason="camera")
        transport.active = False  # process exits before background cleanup
        release = asyncio.create_task(manager.async_release(reason="camera"))
        try:
            for _ in range(100):
                if transport.stop_called:
                    break
                await asyncio.sleep(0)
            assert transport.stop_called
            assert listener.resume_count == 0
            assert listener.proofs == []
        finally:
            transport.cleanup_allowed.set()
        await release
        assert transport.cleanup_finished.is_set()
        assert listener.resume_count == 1
        assert listener.proofs[0]["teardown_confirmed"] is True
        assert manager.phase == media.MEDIA_PHASE_INACTIVE
    asyncio.run(run())


def test_failed_cleanup_after_native_exit_never_issues_release_proof():
    async def run():
        media = _load_component_module(str(ROOT), "media_session")
        listener = Listener()
        transport = ExitDuringCleanupTransport(fail_cleanup=True)
        transport.cleanup_allowed.set()
        manager = media.ComelitMediaSessionManager(listener, transport)
        await manager.async_acquire(panel="entrance", reason="camera")
        transport.active = False
        await manager.async_release(reason="camera")
        assert transport.stop_called
        assert listener.resume_count == 0
        assert listener.proofs == []
        assert manager.phase == media.MEDIA_PHASE_ERROR
        assert listener.media_paused
    asyncio.run(run())


def test_failed_start_still_requires_cleanup_even_when_native_inactive():
    class FailedStartTransport(ExitDuringCleanupTransport):
        async def async_start(self, panel):
            self.active = False
            raise RuntimeError("failed_to_start")
    async def run():
        media = _load_component_module(str(ROOT), "media_session")
        listener = Listener()
        transport = FailedStartTransport(fail_cleanup=True)
        transport.cleanup_allowed.set()
        manager = media.ComelitMediaSessionManager(listener, transport)
        try:
            await manager.async_acquire(panel="entrance", reason="camera")
        except media.ComelitMediaSessionError:
            pass
        else:
            raise AssertionError("start unexpectedly succeeded")
        assert transport.stop_called
        assert manager.phase == media.MEDIA_PHASE_ERROR
        assert listener.resume_count == 0
        assert listener.proofs == []
    asyncio.run(run())


def test_concrete_transport_stop_joins_exited_task_and_shim_cleanup():
    async def run():
        media = _load_component_module(str(ROOT), "media_transport")
        task_allowed = asyncio.Event()
        shim_allowed = asyncio.Event()
        completed = []
        async def cleanup_task():
            await task_allowed.wait()
            completed.append("task")
        class Shim:
            async def async_stop(self):
                await shim_allowed.wait()
                completed.append("shim")
        class Hass:
            async def async_add_executor_job(self, func, *args):
                func(*args)
        transport = media.ComelitEntranceMediaTransport.__new__(
            media.ComelitEntranceMediaTransport
        )
        transport._hass = Hass()
        transport._shadow_hook = SimpleNamespace(note_state=lambda reason: None)
        transport._process = None  # native already exited
        transport._reader_task = None
        transport._task = asyncio.create_task(cleanup_task())
        transport._media_active = asyncio.Event()
        transport._local_sdp_ready_event = asyncio.Event()
        transport._offer_ready = asyncio.Event()
        transport._video_forwarding = asyncio.Event()
        transport._audio_forwarding = asyncio.Event()
        transport._door_result_future = None
        transport._door_diagnostics = {}
        transport._video_recovery_shim = Shim()
        transport._latency_timeline = None
        transport._cancel_status_notify = lambda: None
        media._remove_helper_secret = lambda: completed.append("secret")
        media._remove_local_sdp = lambda: completed.append("sdp")
        stop = asyncio.create_task(transport.async_stop())
        try:
            for _ in range(20):
                await asyncio.sleep(0)
            assert not stop.done()
            task_allowed.set()
            for _ in range(20):
                await asyncio.sleep(0)
            assert not stop.done()   # shim still cleaning
        finally:
            task_allowed.set()
            shim_allowed.set()
        await stop
        assert completed == ["task", "shim", "secret", "sdp"]
        assert transport._task is None
        assert transport._process is None
        assert transport._reader_task is None
    asyncio.run(run())


def test_concrete_transport_stop_rejects_stray_reader():
    async def run():
        media = _load_component_module(str(ROOT), "media_transport")
        reader_gate = asyncio.Event()
        class Hass:
            async def async_add_executor_job(self, func, *args):
                func(*args)
        class Hook:
            def note_state(self, reason):
                pass
        transport = media.ComelitEntranceMediaTransport.__new__(media.ComelitEntranceMediaTransport)
        transport._hass = Hass()
        transport._shadow_hook = Hook()
        transport._process = None
        transport._task = None
        transport._reader_task = asyncio.create_task(reader_gate.wait())
        transport._media_active = asyncio.Event()
        transport._local_sdp_ready_event = asyncio.Event()
        transport._offer_ready = asyncio.Event()
        transport._video_forwarding = asyncio.Event()
        transport._audio_forwarding = asyncio.Event()
        transport._door_result_future = None
        transport._door_diagnostics = {}
        transport._video_recovery_shim = None
        transport._latency_timeline = None
        transport._cancel_status_notify = lambda: None
        media._remove_helper_secret = lambda: None
        media._remove_local_sdp = lambda: None
        try:
            await transport.async_stop()
        except media.ComelitMediaTransportError as exc:
            assert str(exc) == "media_teardown_not_confirmed"
        else:
            raise AssertionError("undrained reader incorrectly proved released")
        transport._reader_task.cancel()
        try:
            await transport._reader_task
        except asyncio.CancelledError:
            pass
    asyncio.run(run())
