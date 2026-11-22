"""Regression tests for startup recovery: cancellation and native exit before ACTIVE.

Field evidence (2026-11-21, installed acd779d): the Mini App reopened the camera
after a call hand-off, the native helper exited with code 6 before media became
ACTIVE, the browser closed the socket, and ``media_phase`` stayed ``starting``
for the rest of the session.  The card gate then refused every later open until
HA was restarted.

Root cause: ``async_acquire`` only had ``except Exception``, so a startup
cancelled by the closing WebSocket (``asyncio.CancelledError`` is a
``BaseException``) skipped ``_recover_failed_start`` entirely and left the
manager in its transitional phase.

These tests use the public session boundary with fake listener/transport; no
network, HA instance or native helper is involved.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests" / "miniapp" / "tools"))
from optionf_pr1a_replay import _load_component_module


class Listener:
    def __init__(self) -> None:
        self.media_paused = False
        self.resume_count = 0
        self.proofs = []

    async def async_pause_for_media(self) -> None:
        self.media_paused = True

    async def async_resume_after_media(self) -> None:
        self.resume_count += 1
        self.media_paused = False

    async def async_confirm_media_owner_released(self, **values) -> None:
        self.proofs.append(values)


class HangingStartTransport:
    """Native comes up but never reaches ACTIVE; startup blocks until cancelled."""

    def __init__(self) -> None:
        self.active = False
        self.stop_called = 0
        self.started = asyncio.Event()
        self.stop_release: asyncio.Event | None = None

    async def async_start(self, panel: str) -> None:
        self.active = True
        self.started.set()
        await asyncio.Event().wait()

    async def async_stop(self) -> None:
        self.stop_called += 1
        if self.stop_release is not None:
            await self.stop_release.wait()
        self.active = False


class ExitBeforeActiveTransport:
    """Native exits with code 6 while the session is still starting."""

    def __init__(self) -> None:
        self.active = False
        self.stop_called = 0
        self.last_error = "media_native_exited_before_active:6"
        self.last_native_exit_code = 6

    async def async_start(self, panel: str) -> None:
        self.active = False
        raise RuntimeError("media_native_exited_before_active:6")

    async def async_stop(self) -> None:
        self.stop_called += 1
        self.active = False


class HangingResumeListener(Listener):
    def __init__(self) -> None:
        super().__init__()
        self.resume_started = asyncio.Event()
        self.resume_release = asyncio.Event()
        self.cancel_calls = 0

    async def async_resume_after_media(self) -> None:
        self.resume_count += 1
        self.resume_started.set()
        await self.resume_release.wait()
        self.media_paused = False

    async def async_cancel_listener_recovery_for_media(self) -> None:
        self.cancel_calls += 1


def test_cancelled_start_reaches_terminal_phase_and_restores_listener() -> None:
    async def run() -> None:
        media = _load_component_module(str(ROOT), "media_session")
        listener = Listener()
        transport = HangingStartTransport()
        manager = media.ComelitMediaSessionManager(listener, transport)

        task = asyncio.create_task(
            manager.async_acquire(panel="entrance", reason="camera")
        )
        await transport.started.wait()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        else:
            raise AssertionError("cancelled acquire must raise CancelledError")

        assert manager.phase == media.MEDIA_PHASE_INACTIVE
        assert transport.stop_called >= 1
        assert listener.resume_count == 1
        assert manager.status()["leases"] == {}
        failure = manager.last_start_failure
        assert failure is not None
        assert failure["reason"] == "start_failed:CancelledError"

        # The gate must accept the next attempt without an HA restart.
        transport.started.clear()
        follow_up = asyncio.create_task(
            manager.async_acquire(panel="entrance", reason="camera")
        )
        await transport.started.wait()
        follow_up.cancel()
        try:
            await follow_up
        except asyncio.CancelledError:
            pass
        assert manager.phase == media.MEDIA_PHASE_INACTIVE

    asyncio.run(run())


def test_native_exit_before_active_is_terminal_and_records_exit_code() -> None:
    async def run() -> None:
        media = _load_component_module(str(ROOT), "media_session")
        listener = Listener()
        transport = ExitBeforeActiveTransport()
        manager = media.ComelitMediaSessionManager(listener, transport)

        try:
            await manager.async_acquire(panel="entrance", reason="camera")
        except media.ComelitMediaSessionError:
            pass
        else:
            raise AssertionError("start unexpectedly succeeded")

        assert manager.phase == media.MEDIA_PHASE_INACTIVE
        assert transport.stop_called == 1
        assert listener.resume_count == 1
        failure = manager.last_start_failure
        assert failure is not None
        assert failure["stage"] == "transport_start"
        assert failure["transport_native_exit_code"] == 6
        assert failure["transport_last_error"] == "media_native_exited_before_active:6"

    asyncio.run(run())


def test_cancelled_start_with_unconfirmed_teardown_stays_failed_closed() -> None:
    async def run() -> None:
        media = _load_component_module(str(ROOT), "media_session")
        listener = Listener()
        transport = HangingStartTransport()
        transport.stop_release = asyncio.Event()  # never released in time
        manager = media.ComelitMediaSessionManager(
            listener, transport, recovery_timeout_seconds=0.05
        )

        task = asyncio.create_task(
            manager.async_acquire(panel="entrance", reason="camera")
        )
        await transport.started.wait()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        else:
            raise AssertionError("cancelled acquire must raise CancelledError")

        assert manager.phase == media.MEDIA_PHASE_ERROR
        assert manager.last_error == "start_cleanup_timeout"
        assert listener.resume_count == 0
        assert listener.media_paused is True

        # A second upstream owner must stay impossible while teardown is open.
        try:
            await manager.async_acquire(panel="entrance", reason="camera")
        except media.ComelitMediaSessionError as exc:
            assert str(exc) == "media_teardown_unconfirmed"
        else:
            raise AssertionError("second acquire must be refused")

        transport.stop_release.set()
        for _ in range(50):
            await asyncio.sleep(0)
            if transport.active is False and transport.stop_called:
                break

    asyncio.run(run())


def test_recovery_timeout_on_listener_resume_is_terminal() -> None:
    async def run() -> None:
        media = _load_component_module(str(ROOT), "media_session")
        listener = HangingResumeListener()
        transport = ExitBeforeActiveTransport()
        manager = media.ComelitMediaSessionManager(
            listener, transport, recovery_timeout_seconds=0.05
        )

        try:
            await manager.async_acquire(panel="entrance", reason="camera")
        except media.ComelitMediaSessionError:
            pass
        else:
            raise AssertionError("start unexpectedly succeeded")

        assert manager.phase == media.MEDIA_PHASE_ERROR
        assert manager.last_error == "listener_restore_timeout"
        assert listener.resume_count == 1

        # The timed-out resume is still running: a new media start would let
        # it resume the listener next to an active session.  The refusal must
        # happen before the listener recovery cancel hook can block.
        listener.cancel_calls = 0
        try:
            await manager.async_acquire(panel="entrance", reason="camera")
        except media.ComelitMediaSessionError as exc:
            assert str(exc) == "media_listener_recovery_busy"
        else:
            raise AssertionError("admission must stay closed while resume runs")
        assert listener.cancel_calls == 0

        listener.resume_release.set()
        for _ in range(50):
            await asyncio.sleep(0)
            if not listener.media_paused:
                break

    asyncio.run(run())


class SlowStopExitTransport(ExitBeforeActiveTransport):
    """Native exit before ACTIVE with a slow, successful local cleanup."""

    def __init__(self) -> None:
        super().__init__()
        self.stop_started = asyncio.Event()
        self.stop_release = asyncio.Event()

    async def async_stop(self) -> None:
        self.stop_called += 1
        self.stop_started.set()
        await self.stop_release.wait()
        self.active = False


def test_cancel_during_failed_start_recovery_still_reaches_terminal_phase() -> None:
    """A client cancel while recovery awaits cleanup must not wedge STARTING."""

    async def run() -> None:
        media = _load_component_module(str(ROOT), "media_session")
        listener = Listener()
        transport = SlowStopExitTransport()
        manager = media.ComelitMediaSessionManager(listener, transport)

        task = asyncio.create_task(
            manager.async_acquire(panel="entrance", reason="camera")
        )
        await transport.stop_started.wait()
        task.cancel()
        await asyncio.sleep(0)
        transport.stop_release.set()
        try:
            await task
        except asyncio.CancelledError:
            pass
        else:
            raise AssertionError("cancelled acquire must raise CancelledError")

        assert manager.phase == media.MEDIA_PHASE_INACTIVE
        assert listener.resume_count == 1
        assert manager.status()["leases"] == {}

    asyncio.run(run())


def test_cancelled_recovery_task_keeps_admission_closed_until_stop_confirms() -> None:
    """Unload-time cancellation of the recovery must not reopen admission."""

    async def run() -> None:
        media = _load_component_module(str(ROOT), "media_session")
        created: list[asyncio.Task] = []

        def factory(coro, name):
            task = asyncio.create_task(coro, name=name)
            created.append(task)
            return task

        listener = Listener()
        transport = SlowStopExitTransport()
        manager = media.ComelitMediaSessionManager(
            listener, transport, task_factory=factory
        )

        task = asyncio.create_task(
            manager.async_acquire(panel="entrance", reason="camera")
        )
        await transport.stop_started.wait()
        created[0].cancel()  # recovery task itself is cancelled (entry unload)
        try:
            await task
        except (asyncio.CancelledError, media.ComelitMediaSessionError):
            pass

        assert manager.phase == media.MEDIA_PHASE_ERROR
        assert listener.resume_count == 0

        try:
            await manager.async_acquire(panel="entrance", reason="camera")
        except media.ComelitMediaSessionError as exc:
            assert str(exc) == "media_teardown_unconfirmed"
        else:
            raise AssertionError("admission must stay closed while teardown is open")

        transport.stop_release.set()
        for _ in range(200):
            await asyncio.sleep(0.001)
            try:
                await manager.async_acquire(panel="entrance", reason="camera")
            except media.ComelitMediaSessionError as exc:
                if str(exc) != "media_teardown_unconfirmed":
                    return
            else:
                return
        raise AssertionError("guard did not clear after a confirmed stop")

    asyncio.run(run())


def test_recovery_task_factory_failure_keeps_admission_closed() -> None:
    """If the task factory refuses the recovery, admission must stay closed."""

    async def run() -> None:
        media = _load_component_module(str(ROOT), "media_session")

        def factory(coro, name):
            if "recovery" in name:
                raise RuntimeError("tasks_refused")
            return asyncio.create_task(coro, name=name)

        listener = Listener()
        transport = SlowStopExitTransport()
        transport.stop_release.set()
        manager = media.ComelitMediaSessionManager(
            listener, transport, task_factory=factory
        )

        try:
            await manager.async_acquire(panel="entrance", reason="camera")
        except (media.ComelitMediaSessionError, RuntimeError):
            pass
        else:
            raise AssertionError("start unexpectedly succeeded")

        assert manager.phase == media.MEDIA_PHASE_ERROR
        try:
            await manager.async_acquire(panel="entrance", reason="camera")
        except media.ComelitMediaSessionError as exc:
            assert str(exc) == "media_teardown_unconfirmed"
        else:
            raise AssertionError("admission must stay closed")

    asyncio.run(run())


class FailingStopTransport:
    """Starts fine, but its teardown always fails (e.g. shim cleanup error)."""

    def __init__(self) -> None:
        self.active = False
        self.stop_called = 0

    async def async_start(self, panel: str) -> None:
        if self.stop_called:
            raise RuntimeError("media_teardown_not_confirmed")
        self.active = True

    async def async_stop(self) -> None:
        self.stop_called += 1
        raise RuntimeError("media_teardown_not_confirmed")


def test_failed_release_closes_admission() -> None:
    """A failed ordinary release must also close media admission."""

    async def run() -> None:
        media = _load_component_module(str(ROOT), "media_session")
        listener = Listener()
        transport = FailingStopTransport()
        manager = media.ComelitMediaSessionManager(listener, transport)

        await manager.async_acquire(panel="entrance", reason="camera")
        assert manager.phase == media.MEDIA_PHASE_ACTIVE

        status = await manager.async_force_stop(reason="test_release")
        assert status["phase"] == media.MEDIA_PHASE_ERROR

        try:
            await manager.async_acquire(panel="entrance", reason="camera")
        except media.ComelitMediaSessionError as exc:
            assert str(exc) == "media_teardown_unconfirmed"
        else:
            raise AssertionError("admission must be closed after a failed release")

    asyncio.run(run())


def test_failed_unload_is_not_reported_as_success() -> None:
    """An unconfirmed teardown must fail the unload, never return success."""

    async def run() -> None:
        media = _load_component_module(str(ROOT), "media_session")
        listener = Listener()
        transport = FailingStopTransport()
        manager = media.ComelitMediaSessionManager(listener, transport)

        await manager.async_acquire(panel="entrance", reason="camera")
        try:
            await manager.async_shutdown()
        except RuntimeError:
            pass
        else:
            raise AssertionError("a failed teardown must fail the unload")
        assert manager.phase == media.MEDIA_PHASE_ERROR

    asyncio.run(run())


def test_repeated_unload_cannot_confirm_a_failed_teardown() -> None:
    """A second unload must not turn an unconfirmed release into a success."""

    async def run() -> None:
        media = _load_component_module(str(ROOT), "media_session")
        listener = Listener()
        transport = FailingStopTransport()
        manager = media.ComelitMediaSessionManager(listener, transport)

        await manager.async_acquire(panel="entrance", reason="camera")
        for attempt in range(2):
            try:
                await manager.async_shutdown()
            except RuntimeError:
                continue
            raise AssertionError(f"unload attempt {attempt} must not succeed")

        assert manager.phase == media.MEDIA_PHASE_ERROR
        try:
            await manager.async_acquire(panel="entrance", reason="camera")
        except media.ComelitMediaSessionError as exc:
            assert str(exc) == "media_teardown_unconfirmed"
        else:
            raise AssertionError("a second owner must stay forbidden")

    asyncio.run(run())


class _ShimStub:
    def __init__(self) -> None:
        self.calls = 0

    async def async_stop(self) -> None:
        self.calls += 1
        raise RuntimeError("shim_stop_failed")


def test_failed_shim_stop_keeps_the_owner_for_the_next_attempt() -> None:
    """A retried teardown must re-attempt the same shim, not find nothing."""

    async def run() -> None:
        media_transport = _load_component_module(str(ROOT), "media_transport")
        transport = media_transport.ComelitEntranceMediaTransport.__new__(
            media_transport.ComelitEntranceMediaTransport
        )
        shim = _ShimStub()
        transport._video_recovery_shim = shim

        for attempt in range(2):
            try:
                await transport._async_stop_video_recovery_shim()
            except RuntimeError:
                pass
            else:
                raise AssertionError(f"attempt {attempt} must raise")
            assert transport._video_recovery_shim is shim

        assert shim.calls == 2

    asyncio.run(run())


class _TransportStub:
    def __init__(self, fail_times: int) -> None:
        self.fail_times = fail_times
        self.calls = 0

    def close(self) -> None:
        self.calls += 1
        if self.calls <= self.fail_times:
            raise RuntimeError("close_failed")


def test_shim_stop_keeps_sockets_until_they_are_closed() -> None:
    """A failed close must leave the socket referenced for the next attempt."""

    async def run() -> None:
        module = _load_component_module(str(ROOT), "h264_recovery")
        shim = module.H264RecoveryRtpShim.__new__(module.H264RecoveryRtpShim)
        stub = _TransportStub(fail_times=2)
        shim._input_transport = stub
        shim._output_transports = ()
        shim._protocol = None

        for attempt in range(2):
            try:
                await shim.async_stop()
            except RuntimeError:
                pass
            else:
                raise AssertionError(f"attempt {attempt} must raise")
            assert shim._input_transport is stub

        await shim.async_stop()
        assert shim._input_transport is None
        assert stub.calls == 3

    asyncio.run(run())


def test_unload_fails_while_a_recovery_stop_is_still_running() -> None:
    """An unload must not succeed while a timed-out stop can still run."""

    async def run() -> None:
        media = _load_component_module(str(ROOT), "media_session")

        class SlowExitTransport(ExitBeforeActiveTransport):
            def __init__(self) -> None:
                super().__init__()
                self.release = asyncio.Event()

            async def async_stop(self) -> None:
                self.stop_called += 1
                await self.release.wait()

        listener = Listener()
        transport = SlowExitTransport()
        manager = media.ComelitMediaSessionManager(
            listener, transport, recovery_timeout_seconds=0.05
        )

        try:
            await manager.async_acquire(panel="entrance", reason="camera")
        except media.ComelitMediaSessionError:
            pass
        assert manager.phase == media.MEDIA_PHASE_ERROR

        try:
            await asyncio.wait_for(manager.async_shutdown(), timeout=1.0)
        except TimeoutError:
            raise AssertionError(
                "unload must fail fast while a recovery stop is in flight"
            ) from None
        except media.ComelitMediaSessionError as exc:
            assert "teardown" in str(exc)
        else:
            raise AssertionError("unload must fail while a stop is in flight")
        assert manager.phase == media.MEDIA_PHASE_ERROR

        transport.release.set()
        await asyncio.sleep(0.1)

    asyncio.run(run())


def test_unload_rejects_a_stop_that_leaves_the_transport_active() -> None:
    """A stop that returns without releasing the transport is not confirmed."""

    async def run() -> None:
        media = _load_component_module(str(ROOT), "media_session")

        class SilentTransport:
            def __init__(self) -> None:
                self.active = False

            async def async_start(self, panel: str) -> None:
                self.active = True

            async def async_stop(self) -> None:
                return

        manager = media.ComelitMediaSessionManager(Listener(), SilentTransport())
        await manager.async_acquire(panel="entrance", reason="camera")
        try:
            await manager.async_shutdown()
        except media.ComelitMediaSessionError as exc:
            assert "not_confirmed" in str(exc) or "teardown" in str(exc)
        else:
            raise AssertionError("an active transport must fail the unload")
        assert manager.phase == media.MEDIA_PHASE_ERROR

    asyncio.run(run())


def test_shim_start_keeps_created_sockets_when_cleanup_fails() -> None:
    """A failed shim start must leave its created sockets reachable."""

    async def run() -> None:
        module = _load_component_module(str(ROOT), "h264_recovery")

        class ClosingFails:
            def close(self) -> None:
                raise RuntimeError("close_failed")

        class ClosingOk:
            def close(self) -> None:
                return

        shim = module.H264RecoveryRtpShim.__new__(module.H264RecoveryRtpShim)
        shim._host = "127.0.0.1"
        shim._input_port = 17008
        shim._output_ports = (17099,)
        shim._inactive_output_ports = ()
        shim._rewriter = object()
        shim._bootstrap_max_packets = 1
        shim._bootstrap_max_bytes = 1
        shim._bootstrap_au_timeout_seconds = 0.1
        shim._input_transport = None
        shim._output_transports = ()
        shim._protocol = None

        created = ClosingFails()

        async def factory(protocol, local_addr=None, remote_addr=None):
            if local_addr is not None:
                if local_addr[1] == shim._input_port:
                    raise RuntimeError("input_endpoint_failed")
                return ClosingOk(), None
            return created, None

        shim._endpoint_factory = factory

        try:
            await shim.async_start()
        except RuntimeError as exc:
            assert "close_failed" in str(exc)
        else:
            raise AssertionError("the failed start must propagate")

        assert shim._output_transports == (created,)

    asyncio.run(run())


def test_check_socket_is_kept_until_its_close_is_confirmed() -> None:
    """A failing check-socket close must leave it reachable for a retry."""

    async def run() -> None:
        module = _load_component_module(str(ROOT), "h264_recovery")

        class ClosingFails:
            def __init__(self) -> None:
                self.calls = 0

            def close(self) -> None:
                self.calls += 1
                raise RuntimeError("check_close_failed")

        shim = module.H264RecoveryRtpShim.__new__(module.H264RecoveryRtpShim)
        shim._host = "127.0.0.1"
        shim._input_port = 17108
        shim._output_ports = (17199,)
        shim._inactive_output_ports = ()
        shim._rewriter = object()
        shim._bootstrap_max_packets = 1
        shim._bootstrap_max_bytes = 1
        shim._bootstrap_au_timeout_seconds = 0.1
        shim._input_transport = None
        shim._output_transports = ()
        shim._check_transport = None
        shim._protocol = None

        created = ClosingFails()

        async def factory(protocol, local_addr=None, remote_addr=None):
            return created, None

        shim._endpoint_factory = factory
        try:
            await shim.async_start()
        except RuntimeError as exc:
            assert "check_close_failed" in str(exc)
        else:
            raise AssertionError("the failing check close must propagate")
        assert shim._check_transport is created

        try:
            await shim.async_stop()
        except RuntimeError:
            pass
        else:
            raise AssertionError("the retry must re-attempt the same close")
        assert created.calls == 2

    asyncio.run(run())


def test_transport_stop_keeps_resources_when_not_confirmed() -> None:
    """An unconfirmed teardown must not forget its task or process."""

    async def run() -> None:
        media_transport = _load_component_module(str(ROOT), "media_transport")

        class Hook:
            def note_state(self, *_args, **_kwargs) -> None:
                return

            def note_native_exit(self, *_args, **_kwargs) -> None:
                return

        class Hass:
            async def async_add_executor_job(self, func, *args):
                return func(*args)

        transport = media_transport.ComelitEntranceMediaTransport.__new__(
            media_transport.ComelitEntranceMediaTransport
        )
        done_task = asyncio.create_task(asyncio.sleep(0))
        await done_task
        transport._stopping = False
        transport._shadow_hook = Hook()
        transport._process = None
        transport._task = done_task
        pending_reader = asyncio.create_task(asyncio.sleep(30))
        transport._reader_task = pending_reader
        transport._video_recovery_shim = None
        transport._media_active = asyncio.Event()
        transport._local_sdp_ready_event = asyncio.Event()
        transport._offer_ready = asyncio.Event()
        transport._video_forwarding = asyncio.Event()
        transport._audio_forwarding = asyncio.Event()
        transport._door_result_future = None
        transport._door_diagnostics = {}
        transport._latency_timeline = None
        transport._cancel_status_notify = lambda: None
        transport._hass = Hass()

        module = media_transport
        original = module._remove_helper_secret, module._remove_local_sdp
        module._remove_helper_secret = lambda: None
        module._remove_local_sdp = lambda: None
        try:
            try:
                await transport.async_stop()
            except media_transport.ComelitMediaTransportError as exc:
                assert "not_confirmed" in str(exc)
            else:
                raise AssertionError("an unconfirmed teardown must raise")
            # The live resource stays referenced; the finished task is not a
            # resource and is released only after its result was retrieved.
            assert transport._reader_task is pending_reader
            assert transport._task is None

            # A repeated stop must not report a release it cannot prove.
            try:
                await transport.async_stop()
            except media_transport.ComelitMediaTransportError:
                pass
            else:
                raise AssertionError("a second stop must not confirm the release")
            assert transport._reader_task is pending_reader
        finally:
            module._remove_helper_secret, module._remove_local_sdp = original
            pending_reader.cancel()

    asyncio.run(run())


def test_release_keeps_background_tasks_when_cancel_fails() -> None:
    """A failed background-task join must keep the reference for a retry."""

    async def run() -> None:
        media = _load_component_module(str(ROOT), "media_session")
        listener = Listener()
        transport = FailingStopTransport()
        manager = media.ComelitMediaSessionManager(listener, transport)

        await manager.async_acquire(panel="entrance", reason="camera")
        expiry_task = manager._expiry_task
        assert expiry_task is not None

        async def failing_cancel(task) -> None:
            raise RuntimeError("join_failed")

        manager._cancel_background_task = failing_cancel
        try:
            await manager.async_force_stop(reason="test_release")
        except RuntimeError:
            pass
        else:
            raise AssertionError("the failing join must propagate")

        assert manager._expiry_task is expiry_task

    asyncio.run(run())


def test_shutdown_keeps_background_tasks_when_cancel_fails() -> None:
    """A failed unload must keep expiry/watchdog tracked for the next attempt."""

    async def run() -> None:
        media = _load_component_module(str(ROOT), "media_session")
        manager = media.ComelitMediaSessionManager(Listener(), FailingStopTransport())

        await manager.async_acquire(panel="entrance", reason="camera")
        expiry_task = manager._expiry_task
        assert expiry_task is not None

        async def failing_cancel(task) -> None:
            raise RuntimeError("join_failed")

        manager._cancel_background_task = failing_cancel
        try:
            await manager.async_shutdown()
        except RuntimeError:
            pass
        else:
            raise AssertionError("the failing join must fail the unload")

        assert manager._expiry_task is expiry_task

    asyncio.run(run())


def test_forget_background_task_keeps_a_task_that_can_still_run() -> None:
    """A task that is not finished must stay referenced."""

    async def run() -> None:
        media = _load_component_module(str(ROOT), "media_session")
        manager = media.ComelitMediaSessionManager(
            Listener(), ExitBeforeActiveTransport()
        )
        task = asyncio.create_task(asyncio.sleep(10))
        manager._expiry_task = task

        manager._forget_background_task("_expiry_task", task)
        assert manager._expiry_task is task

        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        manager._forget_background_task("_expiry_task", task)
        assert manager._expiry_task is None

    asyncio.run(run())


def test_recovery_reuses_a_still_running_stop() -> None:
    """A second recovery must not replace the reference to a running stop."""

    async def run() -> None:
        media = _load_component_module(str(ROOT), "media_session")

        class SlowTransport(ExitBeforeActiveTransport):
            def __init__(self) -> None:
                super().__init__()
                self.release = asyncio.Event()

            async def async_stop(self) -> None:
                self.stop_called += 1
                await self.release.wait()

        listener = Listener()
        transport = SlowTransport()
        manager = media.ComelitMediaSessionManager(
            listener, transport, recovery_timeout_seconds=0.05
        )

        try:
            await manager.async_acquire(panel="entrance", reason="camera")
        except media.ComelitMediaSessionError:
            pass
        pending = manager._stop_task
        assert pending is not None and not pending.done()

        await manager._recover_failed_start(RuntimeError("second_failure"))
        assert manager._stop_task is pending
        assert transport.stop_called == 1

        transport.release.set()
        await asyncio.sleep(0.1)

    asyncio.run(run())


def test_reset_inactive_keeps_the_task_that_is_running_it() -> None:
    """A self-triggered release must keep its own task tracked until it ends."""

    async def run() -> None:
        media = _load_component_module(str(ROOT), "media_session")
        manager = media.ComelitMediaSessionManager(
            Listener(), ExitBeforeActiveTransport()
        )
        current = asyncio.current_task()
        assert current is not None
        manager._expiry_task = current

        manager._reset_inactive()
        assert manager._expiry_task is current

        manager._expiry_task = None

    asyncio.run(run())


def test_unload_fails_while_a_listener_recovery_is_still_running() -> None:
    """An unload must not succeed while a timed-out resume still runs."""

    async def run() -> None:
        media = _load_component_module(str(ROOT), "media_session")
        listener = HangingResumeListener()
        transport = ExitBeforeActiveTransport()
        manager = media.ComelitMediaSessionManager(
            listener, transport, recovery_timeout_seconds=0.05
        )

        try:
            await manager.async_acquire(panel="entrance", reason="camera")
        except media.ComelitMediaSessionError:
            pass
        else:
            raise AssertionError("start unexpectedly succeeded")

        resume = manager._resume_task
        assert resume is not None and not resume.done()

        try:
            await asyncio.wait_for(manager.async_shutdown(), timeout=2.0)
        except TimeoutError:
            raise AssertionError("unload must fail fast, not hang") from None
        except media.ComelitMediaSessionError as exc:
            assert "listener_recovery" in str(exc)
        else:
            raise AssertionError("unload must fail while resume is running")
        assert manager.phase == media.MEDIA_PHASE_ERROR

        listener.resume_release.set()
        await asyncio.sleep(0.1)

    asyncio.run(run())


def test_release_waits_for_a_stop_left_by_a_recovery_timeout() -> None:
    """A release must not clear the guard while an older stop still runs."""

    async def run() -> None:
        media = _load_component_module(str(ROOT), "media_session")

        class SlowTransport(ExitBeforeActiveTransport):
            def __init__(self) -> None:
                super().__init__()
                self.release = asyncio.Event()

            async def async_stop(self) -> None:
                self.stop_called += 1
                await self.release.wait()

        listener = Listener()
        transport = SlowTransport()
        manager = media.ComelitMediaSessionManager(
            listener, transport, recovery_timeout_seconds=0.05
        )

        try:
            await manager.async_acquire(panel="entrance", reason="camera")
        except media.ComelitMediaSessionError:
            pass
        assert manager._stop_task is not None and not manager._stop_task.done()

        try:
            await asyncio.wait_for(manager.async_force_stop(reason="release"), timeout=1.0)
        except TimeoutError:
            raise AssertionError("release must fail fast, not hang") from None
        except media.ComelitMediaSessionError as exc:
            assert "teardown_in_flight" in str(exc)
        else:
            raise AssertionError("release must not confirm an in-flight teardown")
        assert manager.phase == media.MEDIA_PHASE_ERROR
        assert transport.stop_called == 1

        transport.release.set()
        await asyncio.sleep(0.1)

    asyncio.run(run())


def test_cancelled_stop_keeps_the_file_cleanup_tracked() -> None:
    """A cancelled stop must leave its executor cleanup tracked and joinable."""

    async def run() -> None:
        media_transport = _load_component_module(str(ROOT), "media_transport")
        started = asyncio.Event()
        gate = asyncio.Event()

        class Hook:
            def note_state(self, *_args, **_kwargs) -> None:
                return

            def note_native_exit(self, *_args, **_kwargs) -> None:
                return

        class Hass:
            async def async_add_executor_job(self, func, *args):
                started.set()
                await gate.wait()
                return func(*args)

        transport = media_transport.ComelitEntranceMediaTransport.__new__(
            media_transport.ComelitEntranceMediaTransport
        )
        transport._stopping = False
        transport._shadow_hook = Hook()
        transport._process = None
        transport._task = None
        transport._reader_task = None
        transport._video_recovery_shim = None
        transport._media_active = asyncio.Event()
        transport._local_sdp_ready_event = asyncio.Event()
        transport._offer_ready = asyncio.Event()
        transport._video_forwarding = asyncio.Event()
        transport._audio_forwarding = asyncio.Event()
        transport._door_result_future = None
        transport._door_diagnostics = {}
        transport._latency_timeline = None
        transport._cancel_status_notify = lambda: None
        transport._hass = Hass()

        module = media_transport
        original = module._remove_helper_secret, module._remove_local_sdp
        module._remove_helper_secret = lambda: None
        module._remove_local_sdp = lambda: None
        try:
            stop = asyncio.create_task(transport.async_stop())
            await started.wait()
            stop.cancel()
            try:
                await stop
            except asyncio.CancelledError:
                pass

            cleanup = transport._cleanup_task
            assert cleanup is not None and not cleanup.done()

            gate.set()
            await cleanup
            await transport.async_stop()
        finally:
            module._remove_helper_secret, module._remove_local_sdp = original

    asyncio.run(run())
