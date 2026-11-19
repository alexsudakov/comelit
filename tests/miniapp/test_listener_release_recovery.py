from __future__ import annotations

import asyncio
from pathlib import Path
import sys
import time
import types


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests" / "miniapp" / "tools"))
from optionf_pr1a_replay import _load_component_module


class _Entry:
    def __init__(self) -> None:
        self.tasks: list[asyncio.Task[None]] = []

    def async_create_background_task(self, hass, coro, name):
        task = asyncio.create_task(coro, name=name)
        self.tasks.append(task)
        return task


class _Runtime:
    def __init__(self, outcomes: list[str | None]) -> None:
        self.outcomes = list(outcomes)
        self.running = False
        self.listener_ready = False
        self.attached_media_busy = False
        self.last_error: str | None = None
        self.start_calls = 0
        self.stop_calls = 0
        self.concurrent = 0
        self.max_concurrent = 0

    async def async_start(self) -> None:
        self.start_calls += 1
        self.running = True
        self.listener_ready = False
        self.concurrent += 1
        self.max_concurrent = max(self.max_concurrent, self.concurrent)

    async def async_wait_ready(self, timeout: float) -> bool:
        outcome = self.outcomes.pop(0)
        if outcome is None:
            self.last_error = None
            self.listener_ready = True
            return True
        self.last_error = outcome
        self.running = False
        self.listener_ready = False
        self.concurrent = max(0, self.concurrent - 1)
        return False

    async def async_stop(self) -> None:
        self.stop_calls += 1
        self.running = False
        self.listener_ready = False
        self.concurrent = 0

    def status(self) -> dict[str, object]:
        return {
            "running": self.running,
            "listener_ready": self.listener_ready,
            "attached_media_busy": self.attached_media_busy,
            "last_error": self.last_error,
        }


def _module():
    module = _load_component_module(str(ROOT), "supervisor")
    module.RECONNECT_INITIAL_DELAY_SECONDS = 0
    module.RECONNECT_MAX_DELAY_SECONDS = 0
    module.MEDIA_RELEASE_RECOVERY_DEADLINE_SECONDS = 30
    return module


async def _paused_supervisor(outcomes: list[str | None]):
    module = _module()
    runtime = _Runtime(outcomes)
    supervisor = module.ComelitRuntimeSupervisor(
        object(), runtime, entry=_Entry()
    )
    supervisor._media_paused = True
    supervisor._state = module.LISTENER_STATE_PAUSED_MEDIA
    return module, runtime, supervisor


async def _confirm(supervisor, **overrides) -> None:
    values = {
        "phase": "stopping",
        "transport_active": False,
        "leases_empty": True,
        "teardown_confirmed": True,
    }
    values.update(overrides)
    await supervisor.async_confirm_media_owner_released(**values)


def test_504_after_confirmed_teardown_recovers_ready_once() -> None:
    async def run() -> None:
        _, runtime, supervisor = await _paused_supervisor(
            ["http_status:504", None]
        )
        await _confirm(supervisor)
        await supervisor.async_resume_after_media()
        assert supervisor.state == "ready"
        assert runtime.start_calls == 2
        assert runtime.max_concurrent == 1
        assert supervisor.status()["recovery_attempts"] == 1

    asyncio.run(run())


def test_remote_sdp_missing_recovers_ready() -> None:
    async def run() -> None:
        _, runtime, supervisor = await _paused_supervisor(
            ["remote_sdp_missing", None]
        )
        await _confirm(supervisor)
        await supervisor.async_resume_after_media()
        assert supervisor.listener_dispatch_ready
        assert runtime.start_calls == 2

    asyncio.run(run())


def test_unconfirmed_teardown_never_restarts_listener() -> None:
    async def run() -> None:
        _, runtime, supervisor = await _paused_supervisor(
            ["http_status:504"]
        )
        await _confirm(supervisor, teardown_confirmed=False)
        try:
            await supervisor.async_resume_after_media()
        except RuntimeError as exc:
            assert str(exc) == "listener_ready_not_confirmed"
        else:
            raise AssertionError("resume unexpectedly succeeded")
        assert runtime.start_calls == 1
        assert supervisor.status()["recovery_last_reason"] == "release_not_proven"

    asyncio.run(run())


def test_401_oauth_and_arbitrary_errors_are_terminal() -> None:
    async def run(reason: str) -> None:
        _, runtime, supervisor = await _paused_supervisor([reason])
        await _confirm(supervisor)
        try:
            await supervisor.async_resume_after_media()
        except RuntimeError:
            pass
        assert supervisor.state == "error"
        assert runtime.start_calls == 1
        assert supervisor.status()["recovery_last_reason"] == "non_transient"

    for reason in ("http_status:401", "oauth_reauth_required", "offer_timeout"):
        asyncio.run(run(reason))


def test_shutdown_invalidates_proof_and_prevents_recovery() -> None:
    async def run() -> None:
        _, runtime, supervisor = await _paused_supervisor(["http_status:504"])
        await _confirm(supervisor)
        await supervisor.async_stop()
        await supervisor.async_resume_after_media()
        status = supervisor.status()
        assert runtime.start_calls == 0
        assert status["state"] == "stopped"
        assert status["recovery_pending"] is False
        assert status["recovery_last_reason"] == "shutdown"

    asyncio.run(run())


def test_unload_during_inflight_recovery_stops_before_another_attempt() -> None:
    class Transport:
        active = False

        async def async_stop(self) -> None:
            self.active = False

    async def run() -> None:
        supervisor_module, runtime, supervisor = await _paused_supervisor(
            ["http_status:504"]
        )
        supervisor_module.RECONNECT_INITIAL_DELAY_SECONDS = 0.1
        supervisor_module.RECONNECT_MAX_DELAY_SECONDS = 0.1
        media_module = _load_component_module(str(ROOT), "media_session")
        manager = media_module.ComelitMediaSessionManager(
            supervisor, Transport()
        )
        manager._phase = media_module.MEDIA_PHASE_ACTIVE
        manager._leases = {"camera": 1}

        release = asyncio.create_task(manager.async_release(reason="camera"))
        while supervisor.status()["recovery_pending"] is not True:
            await asyncio.sleep(0)

        await manager.async_shutdown()
        await release

        await asyncio.sleep(0.11)
        status = supervisor.status()
        assert runtime.start_calls == 1
        assert status["state"] == "stopped"
        assert status["recovery_pending"] is False
        assert status["recovery_last_reason"] == "shutdown"

    asyncio.run(run())


def test_parallel_resume_is_single_flight() -> None:
    async def run() -> None:
        _, runtime, supervisor = await _paused_supervisor(
            ["http_status:504", None]
        )
        await _confirm(supervisor)
        await asyncio.gather(
            supervisor.async_resume_after_media(),
            supervisor.async_resume_after_media(),
        )
        assert runtime.start_calls == 2
        assert supervisor.status()["recovery_attempts"] == 1

    asyncio.run(run())


def test_recovery_budget_exhaustion_is_explicit_and_never_overlaps() -> None:
    async def run() -> None:
        module, runtime, supervisor = await _paused_supervisor(
            ["http_status:504"] * 4
        )
        await _confirm(supervisor)
        try:
            await supervisor.async_resume_after_media()
        except RuntimeError as exc:
            assert str(exc) == "listener_recovery_failed"
        else:
            raise AssertionError("budget unexpectedly succeeded")
        status = supervisor.status()
        assert status["state"] == "error"
        assert status["recovery_attempts"] == module.MEDIA_RELEASE_RECOVERY_MAX_ATTEMPTS
        assert status["recovery_last_reason"] == "budget_exhausted"
        assert status["recovery_pending"] is False
        assert status["recovery_deadline_seconds"] == 0
        assert runtime.max_concurrent == 1

    asyncio.run(run())


def test_release_recovery_reason_classification_boundaries() -> None:
    module = _module()
    classify = module.ComelitRuntimeSupervisor._transient_release_recovery_reason

    for status in range(500, 600):
        reason = f"http_status:{status}"
        assert classify(reason) == reason

    assert classify("remote_sdp_missing") == "remote_sdp_missing"

    for reason in (
        "http_status:499",
        "http_status:600",
        "http_status:401",
        "http_status:403",
        "http_status:404",
        "http_status:400",
        "http_status:0500",
        "http_status:000500",
        "http_status:5000",
        "http_status:5",
        "http_status:",
        "http_status:" + "5" * 5000,
        "http_status:5o0",
        "https_status:500",
        "",
        None,
        500,
        b"http_status:500",
    ):
        assert classify(reason) is None, reason


def test_recovery_deadline_bounds_attempts_and_readiness_waits() -> None:
    observed: list[tuple[float, float, float | None]] = []

    async def run() -> None:
        module = _module()
        module.MEDIA_RELEASE_RECOVERY_DEADLINE_SECONDS = 0.2
        module.RECONNECT_INITIAL_DELAY_SECONDS = 0.05
        module.RECONNECT_MAX_DELAY_SECONDS = 0.05

        class TimeoutAwareRuntime(_Runtime):
            async def async_wait_ready(self, timeout: float) -> bool:
                observed.append(
                    (time.monotonic(), timeout, supervisor._recovery_deadline)
                )
                await asyncio.sleep(min(0.05, timeout))
                self.last_error = "http_status:500"
                self.running = False
                self.listener_ready = False
                self.concurrent = max(0, self.concurrent - 1)
                return False

        runtime = TimeoutAwareRuntime([])
        supervisor = module.ComelitRuntimeSupervisor(
            object(), runtime, entry=_Entry()
        )
        supervisor._media_paused = True
        supervisor._state = module.LISTENER_STATE_PAUSED_MEDIA
        await _confirm(supervisor)

        started = time.monotonic()
        try:
            await supervisor.async_resume_after_media()
        except RuntimeError:
            pass
        elapsed = time.monotonic() - started

        status = supervisor.status()
        # The first readiness wait belongs to the entry attempt, not the
        # bounded recovery budget; every later wait must fit the deadline.
        assert observed and observed[0][1] == 30.0, observed
        recovery = observed[1:]
        assert recovery, "recovery never attempted"
        assert len(recovery) <= module.MEDIA_RELEASE_RECOVERY_MAX_ATTEMPTS
        assert all(0 < timeout <= 0.2 for _, timeout, _ in recovery), recovery
        assert all(
            deadline is not None and at <= deadline + 0.02
            for at, _, deadline in recovery
        ), recovery
        assert elapsed < 0.4
        assert status["recovery_last_reason"] == "budget_exhausted"
        assert status["recovery_pending"] is False

    asyncio.run(run())


def test_recovery_deadline_bounds_lifecycle_lock_wait() -> None:
    async def run() -> None:
        module = _module()
        module.MEDIA_RELEASE_RECOVERY_DEADLINE_SECONDS = 0.15
        module.RECONNECT_INITIAL_DELAY_SECONDS = 0
        module.RECONNECT_MAX_DELAY_SECONDS = 0
        runtime = _Runtime([])
        supervisor = module.ComelitRuntimeSupervisor(
            object(), runtime, entry=_Entry()
        )
        supervisor._media_release_proven = True
        supervisor._media_paused = False
        supervisor._shutdown_requested = False
        supervisor._attached_stop_recovery_required = False
        supervisor._state = module.LISTENER_STATE_RECONNECTING

        await supervisor._lifecycle_lock.acquire()
        started = time.monotonic()
        try:
            await asyncio.wait_for(
                supervisor._async_recover_released_listener("http_status:500"),
                timeout=1.0,
            )
        finally:
            elapsed = time.monotonic() - started

        status = supervisor.status()
        assert elapsed < 0.5, elapsed
        assert runtime.start_calls == 0
        assert status["recovery_last_reason"] == "budget_exhausted"
        # The recovery never owned this lock, so it must not release it.
        assert supervisor._lifecycle_lock.locked() is True
        supervisor._lifecycle_lock.release()

    asyncio.run(run())


def test_native_stop_after_kill_is_hard_bounded() -> None:
    async def run() -> None:
        module = _load_component_module(str(ROOT), "runtime")
        module._NATIVE_STOP_FLUSH_SECONDS = 0.01
        module._NATIVE_STOP_TERMINATE_SECONDS = 0.01
        module._NATIVE_STOP_KILL_SECONDS = 0.05
        module._touch_stop = lambda: None

        class HungProcess:
            pid = 424242
            returncode = None

            def __init__(self) -> None:
                self.killed = False

            def terminate(self) -> None:
                return None

            def kill(self) -> None:
                self.killed = True

            async def wait(self):
                await asyncio.sleep(30)
                return 0

        class Hass:
            async def async_add_executor_job(self, func, *args):
                return func(*args)

        class Stub:
            _hass = Hass()

        process = HungProcess()
        started = time.monotonic()
        confirmed = await module.ComelitRingRuntime._async_stop_native_process(
            Stub(), process
        )
        elapsed = time.monotonic() - started

        assert process.killed is True
        assert confirmed is False
        assert elapsed < 0.5, elapsed

    asyncio.run(run())


def test_recovery_teardown_has_separate_bounded_budget() -> None:
    async def run_teardown_after_retry_deadline() -> None:
        module = _module()
        module.MEDIA_RELEASE_RECOVERY_DEADLINE_SECONDS = 0.1
        module.MEDIA_RELEASE_SAFE_STOP_DEADLINE_SECONDS = 0.5
        module.RECONNECT_INITIAL_DELAY_SECONDS = 0.01
        module.RECONNECT_MAX_DELAY_SECONDS = 0.01

        class LockHoldingRuntime(_Runtime):
            lock = None
            waits = 0

            async def async_wait_ready(self, timeout: float) -> bool:
                self.waits += 1
                # The entry readiness wait must not hold the lifecycle lock.
                # The first recovery wait holds it past the retry deadline so
                # only a separate safe-stop budget can still stop the helper.
                if self.waits >= 2:
                    await self.lock.acquire()
                    asyncio.get_running_loop().call_later(0.2, self.lock.release)
                self.last_error = "http_status:500"
                self.running = False
                self.listener_ready = False
                self.concurrent = max(0, self.concurrent - 1)
                return False

        runtime = LockHoldingRuntime([])
        supervisor = module.ComelitRuntimeSupervisor(
            object(), runtime, entry=_Entry()
        )
        runtime.lock = supervisor._lifecycle_lock
        supervisor._media_paused = True
        supervisor._state = module.LISTENER_STATE_PAUSED_MEDIA
        await _confirm(supervisor)

        started = time.monotonic()
        try:
            await supervisor.async_resume_after_media()
        except RuntimeError:
            pass
        elapsed = time.monotonic() - started

        status = supervisor.status()
        assert runtime.waits >= 2
        assert status["recovery_attempts"] == 1
        # entry stop + recovery teardown, performed after the retry deadline
        assert runtime.stop_calls == 2
        assert elapsed >= 0.15, elapsed
        assert status["recovery_last_reason"] == "budget_exhausted"
        assert status["recovery_pending"] is False

    async def run_teardown_deadline_is_bounded() -> None:
        module = _module()
        module.MEDIA_RELEASE_RECOVERY_DEADLINE_SECONDS = 5
        module.MEDIA_RELEASE_SAFE_STOP_DEADLINE_SECONDS = 0.15
        module.RECONNECT_INITIAL_DELAY_SECONDS = 0.01
        module.RECONNECT_MAX_DELAY_SECONDS = 0.01

        class StuckLockRuntime(_Runtime):
            lock = None
            waits = 0

            async def async_wait_ready(self, timeout: float) -> bool:
                self.waits += 1
                if self.waits >= 2:
                    await self.lock.acquire()
                    asyncio.get_running_loop().call_later(0.6, self.lock.release)
                self.last_error = "http_status:500"
                self.running = False
                self.listener_ready = False
                self.concurrent = max(0, self.concurrent - 1)
                return False

        runtime = StuckLockRuntime([])
        supervisor = module.ComelitRuntimeSupervisor(
            object(), runtime, entry=_Entry()
        )
        runtime.lock = supervisor._lifecycle_lock
        supervisor._media_paused = True
        supervisor._state = module.LISTENER_STATE_PAUSED_MEDIA
        await _confirm(supervisor)

        started = time.monotonic()
        try:
            await supervisor.async_resume_after_media()
        except RuntimeError:
            pass
        elapsed = time.monotonic() - started

        status = supervisor.status()
        assert runtime.waits >= 2
        assert status["recovery_attempts"] == 1
        # teardown never acquired the lock: fail closed instead of waiting
        assert runtime.stop_calls == 1
        assert elapsed < 0.45, elapsed
        assert status["recovery_last_reason"] == "teardown_unconfirmed"
        assert status["recovery_pending"] is False
        assert supervisor._media_release_proven is False

    asyncio.run(run_teardown_after_retry_deadline())
    asyncio.run(run_teardown_deadline_is_bounded())


def test_recovery_teardown_stop_itself_is_bounded() -> None:
    async def run() -> None:
        module = _module()
        module.MEDIA_RELEASE_RECOVERY_DEADLINE_SECONDS = 5
        module.MEDIA_RELEASE_SAFE_STOP_DEADLINE_SECONDS = 0.15
        module.RECONNECT_INITIAL_DELAY_SECONDS = 0.01
        module.RECONNECT_MAX_DELAY_SECONDS = 0.01

        class HangingStopRuntime(_Runtime):
            async def async_stop(self) -> None:
                self.stop_calls += 1
                if self.stop_calls >= 2:
                    # The teardown after a failed recovery wait never returns;
                    # the safe-stop budget must still bound the whole stop.
                    await asyncio.sleep(5)
                self.running = False
                self.listener_ready = False

        runtime = HangingStopRuntime(["http_status:500", "http_status:500"])
        supervisor = module.ComelitRuntimeSupervisor(
            object(), runtime, entry=_Entry()
        )
        supervisor._media_paused = True
        supervisor._state = module.LISTENER_STATE_PAUSED_MEDIA
        await _confirm(supervisor)

        started = time.monotonic()
        try:
            await supervisor.async_resume_after_media()
        except RuntimeError:
            pass
        elapsed = time.monotonic() - started

        status = supervisor.status()
        assert status["recovery_attempts"] == 1
        assert runtime.stop_calls == 2
        assert elapsed < 0.6, elapsed
        assert status["recovery_last_reason"] == "teardown_unconfirmed"
        assert status["recovery_pending"] is False
        assert supervisor._media_release_proven is False

    asyncio.run(run())


def test_stop_locked_propagates_external_cancellation() -> None:
    async def run() -> None:
        module = _module()
        supervisor = module.ComelitRuntimeSupervisor(
            object(), _Runtime([]), entry=_Entry()
        )

        async def stubborn() -> None:
            try:
                await asyncio.sleep(5)
            except asyncio.CancelledError:
                # Ignores the child cancellation; only a cancellation of the
                # caller itself may end this await.
                await asyncio.sleep(5)

        task = asyncio.create_task(stubborn())
        # Let the task enter its try block so the cancellation is swallowed
        # exactly as intended by this regression scenario.
        await asyncio.sleep(0)
        supervisor._task = task
        timed_out = False
        started = time.monotonic()
        try:
            async with asyncio.timeout(0.1):
                await supervisor._async_stop_locked(module.LISTENER_STATE_ERROR)
        except TimeoutError:
            timed_out = True
        elapsed = time.monotonic() - started

        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

        assert timed_out is True
        assert elapsed < 0.5, elapsed
        assert supervisor._lifecycle_lock.locked() is False

    asyncio.run(run())


def test_recovery_does_not_start_when_deadline_expires_during_lock_acquire() -> None:
    async def run() -> None:
        module = _module()
        module.MEDIA_RELEASE_RECOVERY_DEADLINE_SECONDS = 0.05
        module.RECONNECT_INITIAL_DELAY_SECONDS = 0
        module.RECONNECT_MAX_DELAY_SECONDS = 0
        runtime = _Runtime([])
        supervisor = module.ComelitRuntimeSupervisor(
            object(), runtime, entry=_Entry()
        )
        supervisor._media_release_proven = True
        supervisor._media_paused = False
        supervisor._shutdown_requested = False
        supervisor._attached_stop_recovery_required = False
        supervisor._state = module.LISTENER_STATE_RECONNECTING

        async def slow_acquire(deadline):
            await supervisor._lifecycle_lock.acquire()
            # The retry budget expires while the lock is being acquired.
            await asyncio.sleep(0.1)
            return True

        supervisor._async_acquire_lifecycle = slow_acquire
        await supervisor._async_recover_released_listener("http_status:500")

        status = supervisor.status()
        assert runtime.start_calls == 0
        assert status["recovery_attempts"] == 0
        assert status["recovery_last_reason"] == "budget_exhausted"
        # The recovery acquired the lock, so it must also release it.
        assert supervisor._lifecycle_lock.locked() is False

    asyncio.run(run())


def test_teardown_not_confirmed_stops_retries_and_keeps_release_unproven() -> None:
    async def run() -> None:
        module = _module()
        module.MEDIA_RELEASE_RECOVERY_DEADLINE_SECONDS = 30
        module.RECONNECT_INITIAL_DELAY_SECONDS = 0.01
        module.RECONNECT_MAX_DELAY_SECONDS = 0.01

        class FailingStopRuntime(_Runtime):
            async def async_stop(self) -> None:
                self.stop_calls += 1
                self.running = False
                self.listener_ready = False
                # The entry stop must succeed; the teardown after a failed
                # recovery readiness wait is the one that cannot be confirmed.
                if self.stop_calls >= 2:
                    raise RuntimeError("runtime_stop_not_confirmed")

        runtime = FailingStopRuntime(
            ["http_status:500", "http_status:500", "http_status:500"]
        )
        supervisor = module.ComelitRuntimeSupervisor(
            object(), runtime, entry=_Entry()
        )
        supervisor._media_paused = True
        supervisor._state = module.LISTENER_STATE_PAUSED_MEDIA
        await _confirm(supervisor)

        try:
            await supervisor.async_resume_after_media()
        except RuntimeError:
            pass
        else:
            raise AssertionError("resume unexpectedly succeeded")

        status = supervisor.status()
        assert status["recovery_attempts"] == 1
        assert runtime.stop_calls == 2
        assert status["recovery_last_reason"] == "teardown_unconfirmed"
        assert status["recovery_pending"] is False
        assert supervisor._media_release_proven is False

    asyncio.run(run())


def test_release_proof_requires_all_local_owner_invariants() -> None:
    async def run(field: str, value: object) -> None:
        _, runtime, supervisor = await _paused_supervisor(["http_status:504"])
        await _confirm(supervisor, **{field: value})
        try:
            await supervisor.async_resume_after_media()
        except RuntimeError:
            pass
        assert runtime.start_calls == 1

    invalid = (
        ("phase", "active"),
        ("transport_active", True),
        ("leases_empty", False),
        ("teardown_confirmed", False),
    )
    for field, value in invalid:
        asyncio.run(run(field, value))


def test_media_pause_during_recovery_cancels_before_retry() -> None:
    async def run() -> None:
        module, runtime, supervisor = await _paused_supervisor(
            ["http_status:504"]
        )
        module.RECONNECT_INITIAL_DELAY_SECONDS = 0.05
        module.RECONNECT_MAX_DELAY_SECONDS = 0.05
        await _confirm(supervisor)
        resume = asyncio.create_task(supervisor.async_resume_after_media())
        await asyncio.sleep(0)
        await supervisor.async_cancel_listener_recovery_for_media()
        try:
            await resume
        except RuntimeError:
            pass
        assert supervisor.media_paused is True
        assert runtime.start_calls == 1
        assert runtime.max_concurrent == 1
        assert supervisor.status()["recovery_last_reason"] == "media_acquire"

    asyncio.run(run())


def test_media_manager_acquire_during_recovery_cancels_before_retry() -> None:
    class Transport:
        active = False

        async def async_start(self, panel: str) -> None:
            self.active = True

        async def async_stop(self) -> None:
            self.active = False

    async def run() -> None:
        supervisor_module, runtime, supervisor = await _paused_supervisor(
            ["http_status:504"]
        )
        supervisor_module.RECONNECT_INITIAL_DELAY_SECONDS = 0.1
        supervisor_module.RECONNECT_MAX_DELAY_SECONDS = 0.1
        media_module = _load_component_module(str(ROOT), "media_session")
        transport = Transport()
        manager = media_module.ComelitMediaSessionManager(
            supervisor, transport
        )
        manager._phase = media_module.MEDIA_PHASE_ACTIVE
        manager._leases = {"previous": 1}

        release = asyncio.create_task(manager.async_release(reason="previous"))
        while supervisor.status()["recovery_pending"] is not True:
            await asyncio.sleep(0)

        acquired = await manager.async_acquire(
            panel="entrance", reason="camera"
        )
        await release

        await asyncio.sleep(0.11)
        assert acquired["phase"] == "active"
        assert transport.active is True
        assert supervisor.media_paused is True
        assert runtime.start_calls == 1
        assert supervisor.status()["recovery_last_reason"] == "media_acquire"

        await manager.async_shutdown()

    asyncio.run(run())


def test_media_manager_issues_proof_only_after_confirmed_transport_stop() -> None:
    class Listener:
        media_paused = False
        attached_media_busy = False

        def __init__(self) -> None:
            self.proofs: list[dict[str, object]] = []
            self.resume_calls = 0

        async def async_pause_for_media(self) -> None:
            self.media_paused = True

        async def async_confirm_media_owner_released(self, **proof) -> None:
            self.proofs.append(proof)

        async def async_resume_after_media(self) -> None:
            assert self.proofs
            self.resume_calls += 1
            self.media_paused = False

    class Transport:
        active = False

        async def async_start(self, panel: str) -> None:
            self.active = True

        async def async_stop(self) -> None:
            self.active = False

    async def run() -> None:
        module = _load_component_module(str(ROOT), "media_session")
        listener = Listener()
        transport = Transport()
        manager = module.ComelitMediaSessionManager(listener, transport)
        await manager.async_acquire(panel="entrance", reason="camera")
        await manager.async_release(reason="camera")
        assert listener.proofs == [{
            "phase": "stopping",
            "transport_active": False,
            "leases_empty": True,
            "teardown_confirmed": True,
        }]
        assert listener.resume_calls == 1
        assert manager.status()["phase"] == "inactive"

    asyncio.run(run())


def test_media_manager_never_issues_proof_when_teardown_is_unconfirmed() -> None:
    class Listener:
        media_paused = False
        attached_media_busy = False

        def __init__(self) -> None:
            self.proof_calls = 0
            self.resume_calls = 0

        async def async_pause_for_media(self) -> None:
            self.media_paused = True

        async def async_confirm_media_owner_released(self, **proof) -> None:
            self.proof_calls += 1

        async def async_resume_after_media(self) -> None:
            self.resume_calls += 1

    class Transport:
        active = False

        async def async_start(self, panel: str) -> None:
            self.active = True

        async def async_stop(self) -> None:
            raise RuntimeError("stop_not_confirmed")

    async def run() -> None:
        module = _load_component_module(str(ROOT), "media_session")
        listener = Listener()
        manager = module.ComelitMediaSessionManager(listener, Transport())
        await manager.async_acquire(panel="entrance", reason="camera")
        await manager.async_release(reason="camera")
        assert listener.proof_calls == 0
        assert listener.resume_calls == 0
        assert manager.status()["phase"] == "error"

    asyncio.run(run())


def test_lifecycle_lock_wait_is_bounded_with_queued_waiter() -> None:
    """A released fair lock may already belong to a queued waiter.

    ``locked()`` can read ``False`` while the lock is committed to a previously
    queued acquirer; a check-then-acquire must not be treated as a no-suspend
    guarantee.
    """

    async def run() -> None:
        _, _runtime, supervisor = await _paused_supervisor([None])
        lock = supervisor._lifecycle_lock
        await lock.acquire()
        holding = asyncio.Event()

        async def prior_waiter() -> None:
            await lock.acquire()
            holding.set()
            await asyncio.sleep(0.15)
            lock.release()

        waiter = asyncio.create_task(prior_waiter())
        for _ in range(1000):
            if getattr(lock, "_waiters", None):
                break
            await asyncio.sleep(0)
        else:
            raise AssertionError("prior waiter was not queued")

        lock.release()
        assert not lock.locked()
        started = time.monotonic()
        acquired = await supervisor._async_acquire_lifecycle(started + 0.05)
        elapsed = time.monotonic() - started
        assert acquired is False
        assert elapsed < 0.12, elapsed
        await waiter
        assert not lock.locked()

    asyncio.run(run())


def test_recovery_budget_expiry_after_start_tears_down_owner() -> None:
    """The budget may expire inside a started attempt, not only in a wait."""

    async def run() -> None:
        module = _module()
        module.MEDIA_RELEASE_RECOVERY_DEADLINE_SECONDS = 0.05
        module.RECONNECT_INITIAL_DELAY_SECONDS = 0
        module.RECONNECT_MAX_DELAY_SECONDS = 0

        class _SlowStartRuntime(_Runtime):
            async def async_start(self) -> None:
                if self.start_calls >= 1:
                    # Consumes the whole recovery budget inside the attempt.
                    await asyncio.sleep(0.08)
                self.start_calls += 1
                self.running = True
                self.listener_ready = False
                self.concurrent += 1
                self.max_concurrent = max(self.max_concurrent, self.concurrent)

            async def async_wait_ready(self, timeout: float) -> bool:
                self.last_error = "http_status:500"
                self.listener_ready = False
                return False

        runtime = _SlowStartRuntime([])
        supervisor = module.ComelitRuntimeSupervisor(
            object(), runtime, entry=_Entry()
        )
        supervisor._media_paused = True
        supervisor._state = module.LISTENER_STATE_PAUSED_MEDIA
        await _confirm(supervisor)

        try:
            await supervisor.async_resume_after_media()
        except RuntimeError:
            pass
        else:
            raise AssertionError("resume unexpectedly succeeded")

        status = supervisor.status()
        assert runtime.start_calls == 2
        assert runtime.stop_calls == 2, runtime.stop_calls
        assert runtime.running is False
        assert status["recovery_last_reason"] == "budget_exhausted"
        assert status["recovery_pending"] is False

    asyncio.run(run())


def test_recovery_budget_expiry_with_unconfirmed_teardown_fails_closed() -> None:
    async def run() -> None:
        module = _module()
        module.MEDIA_RELEASE_RECOVERY_DEADLINE_SECONDS = 0.05
        module.RECONNECT_INITIAL_DELAY_SECONDS = 0
        module.RECONNECT_MAX_DELAY_SECONDS = 0

        class _StuckStartRuntime(_Runtime):
            async def async_start(self) -> None:
                if self.start_calls >= 1:
                    await asyncio.sleep(0.08)
                self.start_calls += 1
                self.running = True
                self.listener_ready = False

            async def async_wait_ready(self, timeout: float) -> bool:
                self.last_error = "http_status:500"
                self.listener_ready = False
                return False

            async def async_stop(self) -> None:
                self.stop_calls += 1
                if self.stop_calls >= 2:
                    raise RuntimeError("runtime_stop_not_confirmed")
                self.running = False
                self.listener_ready = False

        runtime = _StuckStartRuntime([])
        supervisor = module.ComelitRuntimeSupervisor(
            object(), runtime, entry=_Entry()
        )
        supervisor._media_paused = True
        supervisor._state = module.LISTENER_STATE_PAUSED_MEDIA
        await _confirm(supervisor)

        try:
            await supervisor.async_resume_after_media()
        except RuntimeError:
            pass
        else:
            raise AssertionError("resume unexpectedly succeeded")

        status = supervisor.status()
        assert status["recovery_last_reason"] == "teardown_unconfirmed"
        assert supervisor._media_release_proven is False
        assert status["recovery_pending"] is False
        assert runtime.start_calls == 2
        assert runtime.running is True

    asyncio.run(run())


def test_recovery_refuses_new_owner_when_previous_exit_unproven() -> None:
    async def run() -> None:
        module = _module()
        module.MEDIA_RELEASE_RECOVERY_DEADLINE_SECONDS = 30
        module.RECONNECT_INITIAL_DELAY_SECONDS = 0
        module.RECONNECT_MAX_DELAY_SECONDS = 0

        class _RetainedOwnerRuntime(_Runtime):
            def __init__(self) -> None:
                super().__init__([])
                self.ready_calls = 0

            async def async_wait_ready(self, timeout: float) -> bool:
                self.ready_calls += 1
                self.last_error = "http_status:500"
                return False

            async def async_start(self) -> None:
                if self.ready_calls:
                    raise RuntimeError("runtime_previous_owner_unconfirmed")
                await super().async_start()

        runtime = _RetainedOwnerRuntime()
        supervisor = module.ComelitRuntimeSupervisor(
            object(), runtime, entry=_Entry()
        )
        supervisor._media_paused = True
        supervisor._state = module.LISTENER_STATE_PAUSED_MEDIA
        await _confirm(supervisor)

        try:
            await supervisor.async_resume_after_media()
        except RuntimeError:
            pass
        else:
            raise AssertionError("resume unexpectedly succeeded")

        status = supervisor.status()
        assert runtime.start_calls == 1
        assert status["recovery_last_reason"] == "teardown_unconfirmed"
        assert supervisor._media_release_proven is False
        assert status["recovery_pending"] is False

    asyncio.run(run())


class _FakeHass:
    async def async_add_executor_job(self, func, *args):
        try:
            return func(*args)
        except OSError:
            return None


def _runtime_instance():
    module = _load_component_module(str(ROOT), "runtime")
    instance = module.ComelitRingRuntime(
        _FakeHass(),
        object(),
        entry=_Entry(),
        device_uuid="device",
        vip_token="0" * 32,
        oauth=object(),
    )
    return module, instance


class _LiveProcess:
    returncode = None
    pid = 4242


def test_runtime_refuses_second_owner_when_stop_unconfirmed() -> None:
    async def run() -> None:
        module, instance = _runtime_instance()
        live = _LiveProcess()
        instance._process = live
        instance._stop_unconfirmed = True

        try:
            await instance.async_start()
        except module.ComelitRingRuntimeError as exc:
            assert str(exc) == "runtime_previous_owner_unconfirmed"
        else:
            raise AssertionError("runtime admitted a second native owner")

        assert instance._process is live
        assert instance._task is None

    asyncio.run(run())


def test_run_once_retains_process_identity_when_stop_unconfirmed() -> None:
    async def run() -> None:
        module, instance = _runtime_instance()
        live = _LiveProcess()
        instance._process = live

        async def failing_cycle() -> None:
            instance._stop_unconfirmed = True
            raise module.ComelitRingRuntimeError("runtime_stop_not_confirmed")

        instance._async_run_cycle = failing_cycle

        await instance._async_run_once()

        assert instance._process is live
        assert instance._last_error == "runtime_stop_not_confirmed"
        assert instance._stop_unconfirmed is True

    asyncio.run(run())


def test_async_stop_failure_keeps_owner_and_blocks_restart() -> None:
    """The public stop path must retain the owner and close admission."""

    async def run() -> None:
        module, instance = _runtime_instance()
        live = _LiveProcess()
        instance._process = live
        instance._task = None

        async def _not_stopped(process) -> bool:
            return False

        instance._async_stop_native_process = _not_stopped

        try:
            await instance.async_stop()
        except module.ComelitRingRuntimeError as exc:
            assert str(exc) == "runtime_stop_not_confirmed"
        else:
            raise AssertionError("stop unexpectedly succeeded")

        assert instance._process is live
        assert instance._stop_unconfirmed is True

        try:
            await instance.async_start()
        except module.ComelitRingRuntimeError as exc:
            assert str(exc) == "runtime_previous_owner_unconfirmed"
        else:
            raise AssertionError("runtime admitted a second native owner")

        assert instance._task is None

    asyncio.run(run())


def test_confirmed_remote_release_clears_attached_media_open() -> None:
    """A released call must not keep the attached media channel selectable."""

    class _Stdout:
        def __init__(self, lines):
            self._lines = list(lines)

        async def readline(self):
            if not self._lines:
                return b""
            return (self._lines.pop(0) + "\n").encode()

    class _Process:
        def __init__(self, lines):
            self.stdout = _Stdout(lines)

    async def run() -> None:
        _module, instance = _runtime_instance()
        instance._attached_media_open.set()
        instance._attached_media_busy.set()
        instance._attached_media_closed.clear()
        instance._listener_ready.set()
        await instance._async_read_output(
            _Process(["R37_REMOTE_RELEASE_OBSERVED=true"])
        )
        assert instance.attached_media_open is False
        # Exclusivity is kept: the busy gate is released only by the native
        # CLOSED marker, never by a release assumption.
        assert instance.attached_media_busy is True

    asyncio.run(run())


def test_release_during_a_live_call_latches_the_attached_handoff() -> None:
    class _Stdout:
        def __init__(self, lines):
            self._lines = list(lines)

        async def readline(self):
            if not self._lines:
                return b""
            return (self._lines.pop(0) + "\n").encode()

    class _Process:
        def __init__(self, lines):
            self.stdout = _Stdout(lines)

    async def run() -> None:
        _module, instance = _runtime_instance()
        instance._call_state_tracker().begin(
            panel="entrance",
            event_id="event-1",
            started_at="2026-11-19T20:00:00+00:00",
        )
        await instance._async_read_output(
            _Process(["R37_REMOTE_RELEASE_OBSERVED=true"])
        )
        assert instance.attached_call_handoff is True

        # A fresh call-bound channel belongs to a new call.
        await instance._async_read_output(
            _Process(["R42_ATTACHED_MEDIA_ACTIVE=true"])
        )
        assert instance.attached_call_handoff is False

    asyncio.run(run())


def test_a_new_call_clears_the_previous_handoff_latch() -> None:
    async def run() -> None:
        _module, instance = _runtime_instance()
        instance._hass.bus = types.SimpleNamespace(async_fire=lambda *a, **k: None)
        instance._attached_call_handoff = True
        instance._call_state_tracker().begin(
            panel="entrance",
            event_id="event-2",
            started_at="2026-11-19T21:00:00+00:00",
        )
        await instance._async_emit_ring_event(
            {
                "direction": "inbound",
                "kind": "CALL_INIT",
                "door": "entrance",
                "source": "00000643",
            }
        )
        assert instance.attached_call_handoff is False

    asyncio.run(run())
