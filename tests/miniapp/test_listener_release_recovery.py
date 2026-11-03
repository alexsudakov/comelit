from __future__ import annotations

import asyncio
from pathlib import Path
import sys


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
