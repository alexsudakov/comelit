"""Local candidate tests exercising real supervisor and transport release method.

Hermes' independent VERIFY must rerun these against the complete repository.
"""
from __future__ import annotations

import asyncio
import ast
import importlib.util
from pathlib import Path
import unittest

from test_p116_r65_recovery_state_correction import _load_supervisor_module

ROOT = Path(__file__).resolve().parents[2]


class FakeRuntime:
    def __init__(self, results: list[str]):
        self.results = list(results)
        self.running = False
        self.listener_ready = False
        self.last_error = None
        self.start_count = 0
        self.stop_count = 0
        self.concurrent = 0
        self.max_concurrent = 0
        self.pending_ready: asyncio.Event | None = None
        self.attached_media_busy = False
        self.stop_raises = False

    async def async_start(self):
        assert not self.running
        self.running = True
        self.start_count += 1
        self.concurrent += 1
        self.max_concurrent = max(self.max_concurrent, self.concurrent)

    async def async_wait_ready(self, timeout):
        current = self.results.pop(0)
        if current == "wait":
            self.pending_ready = asyncio.Event()
            await self.pending_ready.wait()
            return True
        if current == "raise_timeout":
            raise TimeoutError("readiness wait failed")
        if current == "http_status:504_running":
            # A cloud admission failure may arrive before native exits.
            # Recovery must stop that process before starting another.
            self.last_error = "http_status:504"
            return False
        if current == "ok":
            self.listener_ready = True
            self.last_error = None
            return True
        self.last_error = current
        self.listener_ready = False
        self.running = False
        self.concurrent -= 1
        return False

    async def async_stop(self):
        self.stop_count += 1
        if self.stop_raises:
            raise RuntimeError("native_stop_unconfirmed")
        if self.concurrent:
            self.concurrent -= 1
        self.running = False
        self.listener_ready = False

    def status(self):
        return {"running": self.running, "listener_ready": self.listener_ready,
                "attached_media_busy": False, "last_error": self.last_error,
                "last_native_exit_code": None, "last_native_failure_markers": []}


class FakeEntry:
    def async_create_background_task(self, hass, coro, name):
        # Let only the deferred-recovery task execute.  The ordinary listener
        # polling loop is intentionally held in this deterministic fake.
        if name == "comelit resume after canceled media acquire":
            return asyncio.create_task(coro)
        coro.close()
        class Completed:
            def done(self): return True
            def cancel(self): pass
        return Completed()


class RecoverySupervisorTests(unittest.IsolatedAsyncioTestCase):
    def make_supervisor(self, results):
        mod = _load_supervisor_module()
        mod.RECONNECT_INITIAL_DELAY_SECONDS = 0
        mod.RECONNECT_MAX_DELAY_SECONDS = 0
        runtime = FakeRuntime(results)
        sup = mod.ComelitRuntimeSupervisor(None, runtime, entry=FakeEntry())
        sup._media_paused = True
        sup._set_state(mod.LISTENER_STATE_PAUSED_MEDIA)
        return mod, sup, runtime

    async def test_504_then_ready_uses_one_upstream_at_a_time(self):
        mod,sup,runtime = self.make_supervisor(["http_status:504", "ok"])
        await sup.async_resume_after_media()
        self.assertEqual(sup.state, mod.LISTENER_STATE_READY)
        self.assertEqual(runtime.start_count, 2)
        self.assertEqual(runtime.max_concurrent, 1)
        self.assertEqual(sup.status()["recovery_attempts"], 2)
        self.assertFalse(sup.status()["recovery_pending"])

    async def test_504_with_old_process_still_running_stops_before_retry(self):
        mod, sup, runtime = self.make_supervisor(["http_status:504_running", "ok"])
        await sup.async_resume_after_media()
        self.assertEqual(sup.state, mod.LISTENER_STATE_READY)
        self.assertEqual(runtime.stop_count, 1)
        self.assertEqual(runtime.max_concurrent, 1)

    async def test_cancellation_of_ready_wait_cleans_listener(self):
        mod, sup, runtime = self.make_supervisor(["wait"])
        task = asyncio.create_task(sup.async_resume_after_media())
        for _ in range(10):
            if runtime.pending_ready is not None:
                break
            await asyncio.sleep(0)
        self.assertIsNotNone(runtime.pending_ready)
        self.assertTrue(runtime.running)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(runtime.stop_count, 1)
        self.assertFalse(runtime.running)
        self.assertEqual(sup.state, mod.LISTENER_STATE_ERROR)
        self.assertFalse(sup.status()["recovery_pending"])

    async def test_parallel_resume_is_single_flight(self):
        mod, sup, runtime = self.make_supervisor(["wait"])
        first = asyncio.create_task(sup.async_resume_after_media())
        for _ in range(10):
            if runtime.pending_ready is not None:
                break
            await asyncio.sleep(0)
        self.assertIsNotNone(runtime.pending_ready)
        second = asyncio.create_task(sup.async_resume_after_media())
        await asyncio.sleep(0)
        self.assertEqual(runtime.start_count, 1)
        runtime.listener_ready = True
        runtime.pending_ready.set()
        await asyncio.gather(first, second)
        self.assertEqual(runtime.start_count, 1)
        self.assertEqual(runtime.max_concurrent, 1)
        self.assertEqual(sup.state, mod.LISTENER_STATE_READY)

    async def test_readiness_exception_stops_runtime_and_never_retries(self):
        mod, sup, runtime = self.make_supervisor(["raise_timeout", "ok"])
        with self.assertRaises(TimeoutError):
            await sup.async_resume_after_media()
        self.assertEqual(runtime.stop_count, 1)
        self.assertEqual(runtime.start_count, 1)
        self.assertFalse(runtime.running)
        self.assertEqual(sup.state, mod.LISTENER_STATE_ERROR)

    async def test_remote_sdp_missing_then_ready(self):
        mod,sup,runtime = self.make_supervisor(["remote_sdp_missing", "ok"])
        await sup.async_resume_after_media()
        self.assertEqual(sup.state, mod.LISTENER_STATE_READY)
        self.assertEqual(runtime.start_count, 2)

    async def test_oauth_not_retried(self):
        mod,sup,runtime = self.make_supervisor(["oauth_reauth_required", "ok"])
        with self.assertRaisesRegex(RuntimeError, "listener_ready_not_confirmed"):
            await sup.async_resume_after_media()
        self.assertEqual(runtime.start_count, 1)
        self.assertEqual(sup.state, mod.LISTENER_STATE_ERROR)

    async def test_other_error_not_retried(self):
        mod,sup,runtime = self.make_supervisor(["http_status:500", "ok"])
        with self.assertRaises(RuntimeError):
            await sup.async_resume_after_media()
        self.assertEqual(runtime.start_count, 1)

    async def test_exhaustion_is_bounded(self):
        mod,sup,runtime = self.make_supervisor(["http_status:504"] * 5)
        with self.assertRaisesRegex(RuntimeError, "listener_recovery_exhausted"):
            await sup.async_resume_after_media()
        self.assertEqual(runtime.start_count, 3)
        self.assertEqual(runtime.stop_count, 3)
        self.assertEqual(runtime.max_concurrent, 1)
        self.assertEqual(sup.state, mod.LISTENER_STATE_ERROR)
        self.assertEqual(sup.status()["recovery_attempts"], 3)

    async def test_media_pause_is_idempotent_when_already_paused(self):
        mod,sup,runtime = self.make_supervisor(["ok"])
        await sup.async_pause_for_media()
        self.assertEqual(runtime.start_count, 0)

    async def test_media_priority_aborts_wait_and_reaps_listener(self):
        mod, sup, runtime = self.make_supervisor(["wait"])
        resumer = asyncio.create_task(sup.async_resume_after_media())
        for _ in range(15):
            if runtime.pending_ready is not None:
                break
            await asyncio.sleep(0)
        self.assertIsNotNone(runtime.pending_ready)
        sup.request_media_priority()
        self.assertIs(await asyncio.wait_for(resumer, 1), False)
        self.assertEqual(runtime.start_count, 1)
        self.assertEqual(runtime.stop_count, 1)
        self.assertFalse(runtime.running)
        self.assertEqual(sup.state, mod.LISTENER_STATE_STOPPED)
        self.assertTrue(sup._resume_deferred_for_media)
        # Pending request obtains exclusive media pause; no fallback listener
        # may be scheduled between the release and a successful media acquire.
        await sup.async_pause_for_media()
        sup.release_media_priority()
        await asyncio.sleep(0)
        self.assertTrue(sup.media_paused)
        self.assertEqual(runtime.start_count, 1)
        self.assertFalse(sup._resume_deferred_for_media)
        self.assertEqual(runtime.max_concurrent, 1)

    async def test_canceled_camera_request_restores_idle_listener(self):
        mod, sup, runtime = self.make_supervisor(["wait", "ok"])
        resumer = asyncio.create_task(sup.async_resume_after_media())
        for _ in range(15):
            if runtime.pending_ready is not None:
                break
            await asyncio.sleep(0)
        self.assertIsNotNone(runtime.pending_ready)
        sup.request_media_priority()
        self.assertIs(await asyncio.wait_for(resumer, 1), False)
        # Camera canceled before obtaining exclusive pause. Restore the
        # existing supervisor instead of leaving the connection STOPPED.
        sup.release_media_priority()
        self.assertIsNotNone(sup._deferred_resume_task)
        await asyncio.wait_for(sup._deferred_resume_task, 1)
        self.assertTrue(runtime.running)
        self.assertEqual(runtime.start_count, 2)
        self.assertFalse(sup.media_paused)
        self.assertFalse(sup._resume_deferred_for_media)
        self.assertEqual(runtime.max_concurrent, 1)

    async def _preempt_and_cancel_camera(self, results):
        mod, sup, runtime = self.make_supervisor(["wait", *results])
        resumer = asyncio.create_task(sup.async_resume_after_media())
        for _ in range(20):
            if runtime.pending_ready is not None:
                break
            await asyncio.sleep(0)
        self.assertIsNotNone(runtime.pending_ready)
        sup.request_media_priority()
        self.assertIs(await asyncio.wait_for(resumer, 1), False)
        self.assertEqual(runtime.stop_count, 1)
        sup.release_media_priority()
        self.assertIsNotNone(sup._deferred_resume_task)
        await asyncio.wait_for(sup._deferred_resume_task, 1)
        return mod, sup, runtime

    async def test_deferred_resume_retries_504_after_camera_cancel(self):
        mod, sup, runtime = await self._preempt_and_cancel_camera(
            ["http_status:504", "ok"])
        self.assertEqual(sup.state, mod.LISTENER_STATE_READY)
        self.assertEqual(sup.status()["recovery_attempts"], 2)
        self.assertEqual(runtime.start_count, 3)
        self.assertEqual(runtime.max_concurrent, 1)

    async def test_deferred_resume_oauth_is_terminal_after_camera_cancel(self):
        mod, sup, runtime = await self._preempt_and_cancel_camera(
            ["oauth_reauth_required", "ok"])
        self.assertEqual(sup.state, mod.LISTENER_STATE_ERROR)
        self.assertEqual(runtime.start_count, 2)
        self.assertEqual(runtime.max_concurrent, 1)
        self.assertFalse(sup.status()["recovery_pending"])

    async def test_deferred_resume_cancellation_stops_new_listener(self):
        mod, sup, runtime = self.make_supervisor(["wait", "wait"])
        resumer = asyncio.create_task(sup.async_resume_after_media())
        for _ in range(20):
            if runtime.pending_ready is not None:
                break
            await asyncio.sleep(0)
        self.assertIsNotNone(runtime.pending_ready)
        prior_wait = runtime.pending_ready
        sup.request_media_priority()
        self.assertIs(await asyncio.wait_for(resumer, 1), False)
        sup.release_media_priority()
        deferred = sup._deferred_resume_task
        self.assertIsNotNone(deferred)
        for _ in range(30):
            if runtime.pending_ready is not prior_wait:
                break
            await asyncio.sleep(0)
        self.assertIsNot(runtime.pending_ready, prior_wait)
        self.assertEqual(runtime.start_count, 2)
        deferred.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await deferred
        self.assertFalse(runtime.running)
        self.assertEqual(runtime.stop_count, 2)
        self.assertEqual(sup.state, mod.LISTENER_STATE_ERROR)
        self.assertFalse(sup.status()["recovery_pending"])
        self.assertEqual(runtime.max_concurrent, 1)

    async def test_deferred_resume_504_exhaustion_is_bounded(self):
        mod, sup, runtime = await self._preempt_and_cancel_camera(
            ["http_status:504"] * 5)
        self.assertEqual(sup.state, mod.LISTENER_STATE_ERROR)
        self.assertEqual(sup.status()["recovery_attempts"], 3)
        self.assertEqual(runtime.start_count, 4)
        self.assertEqual(runtime.max_concurrent, 1)

    async def test_camera_acquire_preempts_manager_held_resume(self):
        from test_p80_media_session_manager import media, FakeTransport
        mod, sup, runtime = self.make_supervisor(["wait"])
        transport = FakeTransport([])
        mgr = media.ComelitMediaSessionManager(
            sup, transport, hard_limit_seconds=600,
            transport_watch_interval_seconds=0.01,
        )
        await mgr.async_acquire(panel="entrance", reason="first")
        force = asyncio.create_task(mgr.async_force_stop(reason="first_stopped"))
        for _ in range(20):
            if runtime.pending_ready is not None:
                break
            await asyncio.sleep(0)
        self.assertIsNotNone(runtime.pending_ready)
        acquire = asyncio.create_task(
            mgr.async_acquire(panel="entrance", reason="second"))
        await asyncio.wait_for(asyncio.gather(force, acquire), timeout=2)
        self.assertEqual(mgr.phase, media.MEDIA_PHASE_ACTIVE)
        self.assertTrue(sup.media_paused)
        self.assertEqual(runtime.start_count, 1)
        # One stop for preempting listener; another idempotent stop while
        # acquiring the exclusive media pause.
        self.assertEqual(runtime.stop_count, 2)
        self.assertFalse(runtime.running)
        self.assertEqual(runtime.max_concurrent, 1)
        await mgr.async_shutdown()

    async def test_camera_start_failure_after_preemption_resumes_listener(self):
        from test_p80_media_session_manager import media, FakeTransport
        mod, sup, runtime = self.make_supervisor(["wait", "ok"])
        transport = FakeTransport([])
        mgr = media.ComelitMediaSessionManager(
            sup, transport, hard_limit_seconds=600,
            transport_watch_interval_seconds=0.01,
        )
        await mgr.async_acquire(panel="entrance", reason="first")
        force = asyncio.create_task(mgr.async_force_stop(reason="first_stopped"))
        for _ in range(20):
            if runtime.pending_ready is not None:
                break
            await asyncio.sleep(0)
        self.assertIsNotNone(runtime.pending_ready)
        transport.fail_start = True
        acquire = asyncio.create_task(
            mgr.async_acquire(panel="entrance", reason="second"))
        await asyncio.wait_for(force, 2)
        with self.assertRaises(media.ComelitMediaSessionError):
            await asyncio.wait_for(acquire, 2)
        self.assertEqual(mgr.phase, media.MEDIA_PHASE_INACTIVE)
        self.assertEqual(sup.state, mod.LISTENER_STATE_READY)
        self.assertEqual(runtime.start_count, 2)
        self.assertEqual(runtime.max_concurrent, 1)
        await mgr.async_shutdown()

    async def test_camera_queued_before_resume_never_starts_listener(self):
        from test_p80_media_session_manager import media, FakeTransport
        _, sup, runtime = self.make_supervisor(["ok"])
        transport = FakeTransport([])
        mgr = media.ComelitMediaSessionManager(sup, transport)
        await mgr.async_acquire(panel="entrance", reason="first")
        gate = asyncio.Event()
        transport.cleanup_gate = gate
        force = asyncio.create_task(mgr.async_force_stop(reason="stop"))
        for _ in range(20):
            if mgr.phase == media.MEDIA_PHASE_STOPPING:
                break
            await asyncio.sleep(0)
        self.assertEqual(mgr.phase, media.MEDIA_PHASE_STOPPING)
        acquire = asyncio.create_task(
            mgr.async_acquire(panel="entrance", reason="second"))
        for _ in range(20):
            if sup._media_priority_waiters:
                break
            await asyncio.sleep(0)
        self.assertEqual(sup._media_priority_waiters, 1)
        gate.set()
        await asyncio.wait_for(asyncio.gather(force, acquire), 2)
        self.assertTrue(mgr.active)
        self.assertEqual(runtime.start_count, 0)
        self.assertEqual(sup._media_priority_waiters, 0)
        self.assertTrue(sup.media_paused)
        await mgr.async_shutdown()

    async def test_queued_camera_canceled_before_resume_restores_listener(self):
        from test_p80_media_session_manager import media, FakeTransport
        mod, sup, runtime = self.make_supervisor(["ok"])
        transport = FakeTransport([])
        mgr = media.ComelitMediaSessionManager(sup, transport)
        await mgr.async_acquire(panel="entrance", reason="first")
        gate = asyncio.Event()
        transport.cleanup_gate = gate
        force = asyncio.create_task(mgr.async_force_stop(reason="stop"))
        for _ in range(20):
            if mgr.phase == media.MEDIA_PHASE_STOPPING:
                break
            await asyncio.sleep(0)
        acquire = asyncio.create_task(
            mgr.async_acquire(panel="entrance", reason="second"))
        for _ in range(20):
            if sup._media_priority_waiters:
                break
            await asyncio.sleep(0)
        self.assertEqual(sup._media_priority_waiters, 1)
        acquire.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await acquire
        self.assertEqual(sup._media_priority_waiters, 0)
        gate.set()
        await asyncio.wait_for(force, 2)
        self.assertEqual(mgr.phase, media.MEDIA_PHASE_INACTIVE)
        self.assertEqual(sup.state, mod.LISTENER_STATE_READY)
        self.assertEqual(runtime.start_count, 1)
        self.assertEqual(runtime.max_concurrent, 1)

    async def test_media_priority_stop_failure_remains_fail_closed(self):
        mod, sup, runtime = self.make_supervisor(["wait"])
        resumer = asyncio.create_task(sup.async_resume_after_media())
        for _ in range(20):
            if runtime.pending_ready is not None:
                break
            await asyncio.sleep(0)
        self.assertIsNotNone(runtime.pending_ready)
        runtime.stop_raises = True
        sup.request_media_priority()
        with self.assertRaisesRegex(RuntimeError, "native_stop_unconfirmed"):
            await asyncio.wait_for(resumer, 1)
        self.assertEqual(sup.state, mod.LISTENER_STATE_ERROR)
        self.assertTrue(runtime.running)
        self.assertFalse(sup._resume_deferred_for_media)
        sup.release_media_priority()
        self.assertIsNone(sup._deferred_resume_task)

    async def test_new_camera_preempts_deferred_recovery_when_media_inactive(self):
        from test_p80_media_session_manager import media, FakeTransport
        mod, sup, runtime = self.make_supervisor(["wait"])
        sup._media_paused = False
        sup._set_state(mod.LISTENER_STATE_STOPPED)
        sup._resume_deferred_for_media = True
        sup._schedule_deferred_resume_if_idle()
        for _ in range(25):
            if runtime.pending_ready is not None:
                break
            await asyncio.sleep(0)
        self.assertIsNotNone(runtime.pending_ready)
        self.assertTrue(sup.status()["recovery_pending"])
        mgr = media.ComelitMediaSessionManager(sup, FakeTransport([]))
        self.assertEqual(mgr.phase, media.MEDIA_PHASE_INACTIVE)
        acquire = asyncio.create_task(mgr.async_acquire(panel="entrance", reason="new"))
        try:
            for _ in range(25):
                if sup._media_priority_waiters > 0 or acquire.done():
                    break
                await asyncio.sleep(0)
            self.assertEqual(sup._media_priority_waiters, 1)
            await asyncio.wait_for(acquire, timeout=1)
            self.assertEqual(mgr.phase, media.MEDIA_PHASE_ACTIVE)
            self.assertTrue(sup.media_paused)
            self.assertFalse(runtime.running)
            self.assertEqual(runtime.start_count, 1)
            self.assertEqual(runtime.max_concurrent, 1)
            await mgr.async_shutdown()
        finally:
            deferred = sup._deferred_resume_task
            if deferred is not None and not deferred.done():
                deferred.cancel()
                await asyncio.gather(deferred, return_exceptions=True)
            if not acquire.done():
                acquire.cancel()
                await asyncio.gather(acquire, return_exceptions=True)

    async def test_media_pause_failure_after_preemption_never_schedules_restart(self):
        mod, sup, runtime = self.make_supervisor(["wait"])
        resumer = asyncio.create_task(sup.async_resume_after_media())
        for _ in range(20):
            if runtime.pending_ready is not None:
                break
            await asyncio.sleep(0)
        self.assertIsNotNone(runtime.pending_ready)
        sup.request_media_priority()
        self.assertIs(await asyncio.wait_for(resumer, 1), False)
        self.assertEqual(sup.state, mod.LISTENER_STATE_STOPPED)
        # This time the second cooperative stop needed to acquire media
        # cannot be confirmed.  The deferred restart must not outlive ERROR.
        runtime.stop_raises = True
        with self.assertRaisesRegex(RuntimeError, "native_stop_unconfirmed"):
            await sup.async_pause_for_media()
        self.assertEqual(sup.state, mod.LISTENER_STATE_ERROR)
        sup.release_media_priority()
        self.assertFalse(sup._resume_deferred_for_media)
        self.assertIsNone(sup._deferred_resume_task)
        self.assertEqual(runtime.start_count, 1)
        self.assertEqual(runtime.max_concurrent, 1)

    async def test_shutdown_skips_resume(self):
        mod,sup,runtime = self.make_supervisor(["ok"])
        sup._shutdown_requested = True
        await sup.async_resume_after_media()
        self.assertEqual(runtime.start_count, 0)
        self.assertEqual(sup.state, mod.LISTENER_STATE_STOPPED)


class TransportProofTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        text = (ROOT / "custom_components/comelit/media_transport.py").read_text()
        tree = ast.parse(text)
        klass = next(x for x in tree.body if isinstance(x, ast.ClassDef) and x.name == "ComelitEntranceMediaTransport")
        methods = [x for x in klass.body if isinstance(x, ast.AsyncFunctionDef)
                   and x.name in {"async_confirm_stopped", "_async_run_once"}]
        klass.body = methods
        tree.body = [klass]
        class ComelitMediaTransportError(Exception): pass
        class FakeCloudError(Exception): pass
        ns = {"asyncio": asyncio, "ComelitMediaTransportError": ComelitMediaTransportError,
              "ComelitCloudError": FakeCloudError, "ComelitOAuthError": FakeCloudError,
              "ComelitSdpError": FakeCloudError,
              "_remove_helper_secret": lambda: None,
              "_remove_local_sdp": lambda: None}
        exec(compile(ast.fix_missing_locations(tree), "media_transport.py", "exec"), ns)
        cls.method = ns[klass.name].async_confirm_stopped
        cls.run_once = ns[klass.name]._async_run_once
        cls.error = ComelitMediaTransportError

    def make_state(self, generation, completed, *, task=None):
        class State: pass
        s = State()
        s._generation = generation
        s._cleanup_complete_generation = completed
        s._task = task
        s._native_reaped = True
        s._reader_task = None
        s._video_recovery_shim = None
        s._media_active = asyncio.Event()
        s._process = None
        return s

    async def test_release_proof_waits_for_finally_cleanup(self):
        """Actual production finally/proof bodies: no early listener handoff."""
        s = self.make_state(7, 6)
        gate = asyncio.Event()
        events = []

        async def cycle():
            events.append("native_reaped")
            s._native_reaped = True
            s._reader_task = None

        async def stop_shim():
            events.append("shim_cleanup_started")
            await gate.wait()
            s._video_recovery_shim = None

        class Hass:
            async def async_add_executor_job(self, func):
                events.append("file_cleanup")

        s._hass = Hass()
        s._async_run_cycle = cycle
        s._async_stop_video_recovery_shim = stop_shim
        s._local_sdp_ready_event = asyncio.Event()
        s._media_active.set()
        runner = asyncio.create_task(type(self).run_once(s))
        s._task = runner
        await asyncio.sleep(0)
        proof = asyncio.create_task(type(self).method(s))
        await asyncio.sleep(0)
        self.assertFalse(proof.done())
        self.assertEqual(s._cleanup_complete_generation, 6)
        gate.set()
        self.assertEqual(await proof, 7)
        self.assertEqual(events, ["native_reaped", "shim_cleanup_started",
                                  "file_cleanup", "file_cleanup"])

    async def test_cleanup_failure_never_produces_release_proof(self):
        """An exception during local deletion fails closed, never marks cleanup."""
        s = self.make_state(9, 8)
        async def cycle():
            s._reader_task = None
        async def stop_shim():
            s._video_recovery_shim = None
        class Hass:
            async def async_add_executor_job(self, func):
                raise OSError("local cleanup failed")
        s._hass = Hass()
        s._async_run_cycle = cycle
        s._async_stop_video_recovery_shim = stop_shim
        s._local_sdp_ready_event = asyncio.Event()
        s._task = asyncio.create_task(type(self).run_once(s))
        with self.assertRaises(OSError):
            await type(self).method(s)
        self.assertNotEqual(s._cleanup_complete_generation, 9)

    async def test_same_generation_cleaned(self):
        s = self.make_state(3,3)
        self.assertEqual(await type(self).method(s), 3)

    async def test_older_generation_cannot_authorize_release(self):
        s = self.make_state(4,3)
        with self.assertRaises(self.error): await type(self).method(s)

    async def test_native_dead_but_runner_still_cleaning_is_not_release(self):
        gate = asyncio.Event()
        async def background(): await gate.wait()
        task = asyncio.create_task(background())
        s = self.make_state(4,3,task=task)
        check = asyncio.create_task(type(self).method(s))
        await asyncio.sleep(0)
        self.assertFalse(check.done())
        gate.set()
        with self.assertRaises(self.error): await check

    async def test_done_runner_without_cleanup_marker_is_not_release(self):
        s = self.make_state(2, 1)
        finished = asyncio.create_task(asyncio.sleep(0))
        await finished
        s._task = finished
        with self.assertRaises(self.error):
            await type(self).method(s)

    async def test_generation_change_during_proof_is_not_release(self):
        gate = asyncio.Event()
        async def background(): await gate.wait()
        task = asyncio.create_task(background())
        s = self.make_state(2, 2, task=task)
        check = asyncio.create_task(type(self).method(s))
        await asyncio.sleep(0)
        s._generation = 3
        gate.set()
        with self.assertRaises(self.error):
            await check

    async def test_live_reader_or_native_blocks_release(self):
        s = self.make_state(4,4)
        s._reader_task = object()
        with self.assertRaises(self.error): await type(self).method(s)
        s._reader_task = None
        s._native_reaped = False
        with self.assertRaises(self.error): await type(self).method(s)


if __name__ == '__main__': unittest.main()
