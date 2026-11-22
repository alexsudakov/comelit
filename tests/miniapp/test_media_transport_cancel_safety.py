"""Cancellation safety for the Comelit media transport.

Cancelling an asyncio Future does not stop the executor job behind it, and a
cancelled ``await`` does not prove that a reader task finished.  These tests pin
the contract that makes teardown confirmation sound:

* the stop marker and the runtime-file cleanup run as tracked tasks, so a
  repeated stop observes the running work instead of starting a second job and
  confirming a release that is still in progress;
* a reader is forgotten only after it is actually done;
* an unfinished executor job or reader makes ``async_stop`` fail closed with
  ``media_teardown_not_confirmed``.

No HA instance, network or native helper is involved.
"""

from __future__ import annotations

import asyncio
from collections import deque
from contextlib import contextmanager
import gc
from types import SimpleNamespace
from pathlib import Path
import sys
import threading

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests" / "miniapp" / "tools"))
from optionf_pr1a_replay import _load_component_module  # noqa: E402


class Hass:
    """Run executor jobs on a real thread, like HA does."""

    async def async_add_executor_job(self, func, *args):
        return await asyncio.get_running_loop().run_in_executor(None, func, *args)


class Hook:
    def note_state(self, *_args, **_kwargs) -> None:
        return

    def note_native_exit(self, *_args, **_kwargs) -> None:
        return


@contextmanager
def _runtime_files(media, secret=None, sdp=None):
    original = media._remove_helper_secret, media._remove_local_sdp
    media._remove_helper_secret = secret or (lambda: None)
    media._remove_local_sdp = sdp or (lambda: None)
    try:
        yield
    finally:
        media._remove_helper_secret, media._remove_local_sdp = original


async def _wait_started(event: threading.Event, timeout: float = 3.0) -> None:
    """Wait for the executor job to start without hanging the test."""

    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not event.is_set():
        if loop.time() > deadline:
            raise AssertionError("executor job did not start")
        await asyncio.sleep(0.01)


def _transport(media, hass):
    transport = media.ComelitEntranceMediaTransport.__new__(
        media.ComelitEntranceMediaTransport
    )
    transport._hass = hass
    transport._shadow_hook = Hook()
    transport._process = None
    transport._task = None
    transport._reader_task = None
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
    transport._stopping = False
    transport._last_error = None
    transport._stop_marker_confirmed = None
    transport._stop_marker_error = None
    return transport


def test_cancelled_stop_keeps_the_stop_marker_tracked() -> None:
    async def run() -> None:
        media = _load_component_module(str(ROOT), "media_transport")
        media._EXECUTOR_JOIN_TIMEOUT_SECONDS = 0.2
        started = threading.Event()
        release = threading.Event()
        calls: list[int] = []

        def touch() -> None:
            calls.append(1)
            started.set()
            release.wait(2)

        transport = _transport(media, Hass())
        original = media._touch_stop
        media._touch_stop = touch
        try:
            stop = asyncio.create_task(transport._async_run_stop_signal())
            await _wait_started(started)
            stop.cancel()
            try:
                await stop
            except asyncio.CancelledError:
                pass

            task = transport._stop_signal_task
            assert task is not None and not task.done()

            try:
                await transport._async_run_stop_signal()
            except media.ComelitMediaTransportError as exc:
                assert "media_teardown_not_confirmed" in str(exc)
            else:
                raise AssertionError("a running stop marker was reported as done")

            assert transport._stop_signal_task is task
            assert calls == [1], calls

            release.set()
            await task
            assert calls == [1], calls
        finally:
            media._touch_stop = original

    asyncio.run(run())


def test_cancelled_stop_keeps_the_file_cleanup_tracked() -> None:
    async def run() -> None:
        media = _load_component_module(str(ROOT), "media_transport")
        media._EXECUTOR_JOIN_TIMEOUT_SECONDS = 0.2
        started = threading.Event()
        release = threading.Event()
        removed: list[str] = []

        def remove_secret() -> None:
            started.set()
            release.wait(2)
            removed.append("secret")

        def remove_sdp() -> None:
            removed.append("sdp")

        transport = _transport(media, Hass())
        with _runtime_files(media, remove_secret, remove_sdp):
            stop = asyncio.create_task(transport._async_join_cleanup())
            await _wait_started(started)
            stop.cancel()
            try:
                await stop
            except asyncio.CancelledError:
                pass

            cleanup = transport._cleanup_task
            assert cleanup is not None and not cleanup.done()

            try:
                await transport._async_join_cleanup()
            except media.ComelitMediaTransportError as exc:
                assert "media_teardown_not_confirmed" in str(exc)
            else:
                raise AssertionError("a running cleanup was reported as done")

            release.set()
            await cleanup
            assert removed == ["secret", "sdp"], removed

    asyncio.run(run())


def test_stop_refuses_to_confirm_while_the_cleanup_is_unfinished() -> None:
    async def run() -> None:
        media = _load_component_module(str(ROOT), "media_transport")
        media._EXECUTOR_JOIN_TIMEOUT_SECONDS = 0.2
        started = threading.Event()
        release = threading.Event()

        def remove_secret() -> None:
            started.set()
            release.wait(2)

        transport = _transport(media, Hass())
        with _runtime_files(media, remove_secret):
            stop = asyncio.create_task(transport.async_stop())
            await _wait_started(started)
            stop.cancel()
            try:
                await stop
            except asyncio.CancelledError:
                pass

            try:
                await transport.async_stop()
            except media.ComelitMediaTransportError as exc:
                assert str(exc) == "media_teardown_not_confirmed"
            else:
                raise AssertionError("a repeated stop confirmed unfinished cleanup")

            release.set()
            await transport._cleanup_task
            await transport.async_stop()

    asyncio.run(run())


def test_reader_that_delays_cancellation_is_not_forgotten() -> None:
    async def run() -> None:
        media = _load_component_module(str(ROOT), "media_transport")

        async def stubborn_read() -> None:
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                await asyncio.sleep(0.3)

        transport = _transport(media, Hass())
        with _runtime_files(media):
            reader = asyncio.create_task(stubborn_read())
            transport._reader_task = reader
            await asyncio.sleep(0)
            reader.cancel()

            try:
                await transport.async_stop()
            except media.ComelitMediaTransportError as exc:
                assert str(exc) == "media_teardown_not_confirmed"
            else:
                raise AssertionError("a running reader was reported as released")

            assert transport._reader_task is reader

            await asyncio.sleep(0.4)
            assert reader.done()
            await transport.async_stop()
            assert transport._reader_task is None

    asyncio.run(run())


def test_run_once_finally_keeps_an_unfinished_cleanup() -> None:
    async def run() -> None:
        media = _load_component_module(str(ROOT), "media_transport")
        media._EXECUTOR_JOIN_TIMEOUT_SECONDS = 5.0
        started = threading.Event()
        release = threading.Event()

        def remove_secret() -> None:
            started.set()
            release.wait(2)

        transport = _transport(media, Hass())
        with _runtime_files(media, remove_secret):

            async def failing_cycle() -> None:
                raise media.ComelitMediaTransportError("media_signaling_timeout")

            transport._async_run_cycle = failing_cycle
            run_once = asyncio.create_task(transport._async_run_once())
            await _wait_started(started)
            run_once.cancel()
            try:
                await run_once
            except asyncio.CancelledError:
                pass

            cleanup = transport._cleanup_task
            assert cleanup is not None and not cleanup.done()

            release.set()
            await cleanup

    asyncio.run(run())


def test_reader_teardown_keeps_a_task_that_delays_cancellation() -> None:
    async def run() -> None:
        media = _load_component_module(str(ROOT), "media_transport")

        async def stubborn_read() -> None:
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                await asyncio.sleep(0.3)

        transport = _transport(media, Hass())
        with _runtime_files(media):
            reader = asyncio.create_task(stubborn_read())
            transport._reader_task = reader
            await asyncio.sleep(0)

            teardown = asyncio.create_task(transport._async_stop_reader())
            await asyncio.sleep(0.05)
            assert not teardown.done()
            assert transport._reader_task is reader

            for _ in range(100):
                if teardown.done():
                    break
                await asyncio.sleep(0.02)
            assert teardown.done()
            assert reader.done()
            assert transport._reader_task is None

    asyncio.run(run())


class _LiveProcess:
    """Native child that stays alive until it is terminated or times out."""

    def __init__(self, exit_after: float | None = None) -> None:
        self.returncode = None
        self._exit_after = exit_after
        self._done = asyncio.Event()

    async def wait(self):
        if self._exit_after is not None:
            try:
                await asyncio.wait_for(self._done.wait(), self._exit_after)
            except TimeoutError:
                self.returncode = -15
                return self.returncode
        await self._done.wait()
        return self.returncode

    def terminate(self) -> None:
        self.returncode = -15
        self._done.set()

    def kill(self) -> None:
        self.returncode = -9
        self._done.set()


def test_run_once_keeps_a_live_process_when_the_cleanup_times_out() -> None:
    """A failed cleanup must not forget the native child that still runs."""

    async def run() -> None:
        media = _load_component_module(str(ROOT), "media_transport")
        media._EXECUTOR_JOIN_TIMEOUT_SECONDS = 0.2
        started = threading.Event()
        release = threading.Event()

        def remove_secret() -> None:
            started.set()
            release.wait(2)

        transport = _transport(media, Hass())
        process = _LiveProcess()
        with _runtime_files(media, remove_secret):

            async def failing_cycle() -> None:
                transport._process = process
                process.terminate()
                raise media.ComelitMediaTransportError("media_signaling_timeout")

            transport._async_run_cycle = failing_cycle
            try:
                await transport._async_run_once()
            except media.ComelitMediaTransportError as exc:
                assert str(exc) == "media_teardown_not_confirmed"
            else:
                raise AssertionError("an unfinished cleanup was reported as done")
            assert transport._last_error == "media_teardown_not_confirmed"

            # the child exited (returncode known), so the reference may go
            assert transport._process is None

    asyncio.run(run())


def test_run_once_does_not_forget_a_process_that_is_still_running() -> None:
    async def run() -> None:
        media = _load_component_module(str(ROOT), "media_transport")
        media._EXECUTOR_JOIN_TIMEOUT_SECONDS = 5.0
        transport = _transport(media, Hass())
        process = _LiveProcess()
        with _runtime_files(media):

            async def failing_cycle() -> None:
                transport._process = process
                raise media.ComelitMediaTransportError("media_signaling_timeout")

            transport._async_run_cycle = failing_cycle
            await transport._async_run_once()

            assert transport._process is process
            assert transport._process.returncode is None

    asyncio.run(run())


def test_caller_cancellation_during_the_child_join_propagates() -> None:
    """Cancelling the stop must not be confused with cancelling its child task."""

    async def run() -> None:
        media = _load_component_module(str(ROOT), "media_transport")
        media._EXECUTOR_JOIN_TIMEOUT_SECONDS = 0.05
        entered = asyncio.Event()

        async def stubborn_child() -> None:
            try:
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                entered.set()
                await asyncio.sleep(30)

        transport = _transport(media, Hass())
        with _runtime_files(media):
            transport._task = asyncio.create_task(stubborn_child())
            await asyncio.sleep(0)
            stop = asyncio.create_task(transport.async_stop())
            await asyncio.wait_for(entered.wait(), 3)
            stop.cancel()
            try:
                await stop
            except asyncio.CancelledError:
                pass
            else:
                raise AssertionError("caller cancellation was swallowed")

    asyncio.run(run())


def test_a_second_stop_cannot_confirm_a_task_that_never_finished() -> None:
    """A child that outlives the join timeout must stay referenced."""

    async def run() -> None:
        media = _load_component_module(str(ROOT), "media_transport")
        media._EXECUTOR_JOIN_TIMEOUT_SECONDS = 0.05

        async def stubborn_child() -> None:
            try:
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                await asyncio.sleep(0.5)

        transport = _transport(media, Hass())
        with _runtime_files(media):
            transport._task = asyncio.create_task(stubborn_child())
            await asyncio.sleep(0)

            try:
                await transport.async_stop()
            except media.ComelitMediaTransportError as exc:
                assert str(exc) == "media_teardown_not_confirmed"
            else:
                raise AssertionError("stop confirmed a live child")

            # the child outlived the join: it must still be referenced, so a
            # later stop cannot mistake it for a finished teardown
            assert transport._task is not None
            assert not transport._task.done()

            for _ in range(200):
                if transport._task.done():
                    break
                await asyncio.sleep(0.02)
            await transport.async_stop()
            assert transport._task is None

    asyncio.run(run())


def test_cycle_teardown_survives_a_marker_timeout_and_keeps_the_original_error() -> None:
    """A slow marker must not skip the child teardown or mask the cycle error."""

    async def run() -> None:
        media = _load_component_module(str(ROOT), "media_transport")
        media._EXECUTOR_JOIN_TIMEOUT_SECONDS = 0.2
        started = threading.Event()
        release = threading.Event()

        def touch() -> None:
            started.set()
            release.wait(2)

        transport = _transport(media, Hass())
        process = _LiveProcess(exit_after=0.3)
        original_touch = media._touch_stop
        media._touch_stop = touch
        try:
            with _runtime_files(media):
                transport._process = process
                transport._last_error = "media_offer_timeout"

                await transport._async_finish_cycle(process)

                assert started.is_set()
                assert process.returncode == -15, process.returncode
                # the cycle error is not replaced by the marker timeout
                assert transport._last_error == "media_offer_timeout"
                # and the unfinished marker keeps the teardown unconfirmed
                assert transport._stop_signal_task is not None
                assert not transport._stop_signal_task.done()
                release.set()
                await transport._stop_signal_task
        finally:
            media._touch_stop = original_touch

    asyncio.run(run())


def test_a_failing_marker_does_not_skip_the_child_teardown() -> None:
    """A filesystem error in the stop marker must not abort the teardown."""

    async def run() -> None:
        media = _load_component_module(str(ROOT), "media_transport")
        media._EXECUTOR_JOIN_TIMEOUT_SECONDS = 0.2

        def touch() -> None:
            raise PermissionError("stop marker not writable")

        transport = _transport(media, Hass())
        process = _LiveProcess(exit_after=0.2)
        original_touch = media._touch_stop
        media._touch_stop = touch
        try:
            with _runtime_files(media):
                transport._process = process
                transport._last_error = "media_offer_timeout"

                await transport._async_finish_cycle(process)

                assert process.returncode == -15
                assert transport._last_error == "media_offer_timeout"
        finally:
            media._touch_stop = original_touch

    asyncio.run(run())


def test_cleanup_failure_keeps_the_pending_cancellation_and_the_teardown_marked() -> None:
    """A filesystem error in the cleanup must not mask the cycle cancellation."""

    async def run() -> None:
        media = _load_component_module(str(ROOT), "media_transport")
        media._EXECUTOR_JOIN_TIMEOUT_SECONDS = 0.2
        removed: list[str] = []

        def remove_secret() -> None:
            raise PermissionError("secret not writable")

        def remove_sdp() -> None:
            removed.append("sdp")

        transport = _transport(media, Hass())
        with _runtime_files(media, remove_secret, remove_sdp):

            async def cancelled_cycle() -> None:
                raise asyncio.CancelledError

            transport._async_run_cycle = cancelled_cycle
            try:
                await transport._async_run_once()
            except asyncio.CancelledError:
                pass
            else:
                raise AssertionError("the cancellation was replaced")

            assert removed == ["sdp"], removed
            assert transport._last_error == "media_teardown_not_confirmed"

    asyncio.run(run())


def test_helper_secret_failure_leaves_the_teardown_unconfirmed() -> None:
    """A failed secret removal must not report a finished teardown."""

    async def run() -> None:
        media = _load_component_module(str(ROOT), "media_transport")
        media._EXECUTOR_JOIN_TIMEOUT_SECONDS = 0.2
        removed: list[str] = []

        def secret() -> None:
            raise PermissionError("secret not writable")

        def sdp() -> None:
            removed.append("sdp")

        transport = _transport(media, Hass())
        with _runtime_files(media, secret, sdp):
            try:
                await transport.async_stop()
            except media.ComelitMediaTransportError as exc:
                assert str(exc) == "media_teardown_not_confirmed", str(exc)
                assert isinstance(exc.__cause__, PermissionError), exc.__cause__
            else:
                raise AssertionError("a failed cleanup was reported as confirmed")

        assert transport._last_error == "media_teardown_not_confirmed"
        assert removed == ["sdp"], removed

    asyncio.run(run())


def test_sdp_failure_leaves_the_teardown_unconfirmed() -> None:
    """A failed SDP removal is enough to leave the teardown unconfirmed."""

    async def run() -> None:
        media = _load_component_module(str(ROOT), "media_transport")
        media._EXECUTOR_JOIN_TIMEOUT_SECONDS = 0.2
        removed: list[str] = []

        def secret() -> None:
            removed.append("secret")

        def sdp() -> None:
            raise OSError("sdp not writable")

        transport = _transport(media, Hass())
        with _runtime_files(media, secret, sdp):
            try:
                await transport.async_stop()
            except media.ComelitMediaTransportError as exc:
                assert str(exc) == "media_teardown_not_confirmed", str(exc)
                assert isinstance(exc.__cause__, OSError), exc.__cause__
            else:
                raise AssertionError("a failed cleanup was reported as confirmed")

        assert transport._last_error == "media_teardown_not_confirmed"
        assert removed == ["secret"], removed

    asyncio.run(run())


def test_two_cleanup_failures_keep_the_first_as_primary() -> None:
    """The first removal failure stays primary; the second is only diagnosed."""

    async def run() -> None:
        media = _load_component_module(str(ROOT), "media_transport")
        media._EXECUTOR_JOIN_TIMEOUT_SECONDS = 0.2

        def secret() -> None:
            raise PermissionError("secret first")

        def sdp() -> None:
            raise OSError("sdp second")

        transport = _transport(media, Hass())
        transport._teardown_secondary_error = None
        with _runtime_files(media, secret, sdp):
            try:
                await transport.async_stop()
            except media.ComelitMediaTransportError as exc:
                cause = exc.__cause__
                assert isinstance(cause, PermissionError), cause
                assert str(cause) == "secret first", str(cause)
            else:
                raise AssertionError("a failed cleanup was reported as confirmed")

        assert transport._teardown_secondary_error == "OSError"

    asyncio.run(run())


def test_cleanup_failure_through_the_run_once_finally_surfaces_the_error() -> None:
    """A failing cleanup after a silent cycle raises instead of passing."""

    async def run() -> None:
        media = _load_component_module(str(ROOT), "media_transport")
        media._EXECUTOR_JOIN_TIMEOUT_SECONDS = 0.2

        def secret() -> None:
            raise PermissionError("secret not writable")

        transport = _transport(media, Hass())

        async def silent_cycle() -> None:
            return None

        transport._async_run_cycle = silent_cycle
        with _runtime_files(media, secret, lambda: None):
            try:
                await transport._async_run_once()
            except PermissionError:
                pass
            else:
                raise AssertionError("the cleanup failure was swallowed")

        assert transport._last_error == "media_teardown_not_confirmed"

    asyncio.run(run())


def test_repeat_stop_after_a_failed_cleanup_does_not_confirm() -> None:
    """The first stop fails, the second retries, the third may confirm."""

    async def run() -> None:
        media = _load_component_module(str(ROOT), "media_transport")
        media._EXECUTOR_JOIN_TIMEOUT_SECONDS = 0.2
        fail = {"on": True}
        removed: list[str] = []

        def secret() -> None:
            if fail["on"]:
                raise PermissionError("secret not writable")
            removed.append("secret")

        def sdp() -> None:
            removed.append("sdp")

        transport = _transport(media, Hass())
        with _runtime_files(media, secret, sdp):
            for attempt in (1, 2):
                try:
                    await transport.async_stop()
                except media.ComelitMediaTransportError as exc:
                    assert str(exc) == "media_teardown_not_confirmed"
                else:
                    raise AssertionError(f"stop {attempt} confirmed a failed cleanup")

            fail["on"] = False
            await transport.async_stop()

        assert removed[-2:] == ["secret", "sdp"], removed

    asyncio.run(run())


def test_unconfirmed_teardown_blocks_unload_and_a_second_owner() -> None:
    """A failed cleanup fails unload and refuses a new upstream owner."""

    async def run() -> None:
        media = _load_component_module(str(ROOT), "media_transport")
        media._EXECUTOR_JOIN_TIMEOUT_SECONDS = 0.2
        fail = {"on": True}

        def secret() -> None:
            if fail["on"]:
                raise PermissionError("secret not writable")

        transport = _transport(media, Hass())

        # mirrors the unload contract: any failing teardown means "not unloaded"
        unloaded = True

        async def attempt(awaitable) -> None:
            nonlocal unloaded
            try:
                await awaitable
            except Exception:
                unloaded = False

        with _runtime_files(media, secret, lambda: None):
            await attempt(transport.async_stop())
            assert unloaded is False
            assert transport._cleanup_confirmed(transport._cleanup_task) is False

            try:
                await transport.async_start("entrance")
            except media.ComelitMediaTransportError as exc:
                assert str(exc) == "media_teardown_not_confirmed", str(exc)
            else:
                raise AssertionError("a second owner was admitted after a failed teardown")

            fail["on"] = False
            await transport.async_stop()
            # the retried cleanup is confirmed, so the start guard no longer
            # refuses a new owner (same predicate async_start uses)
            assert transport._cleanup_confirmed(transport._cleanup_task) is True

    asyncio.run(run())


def test_stop_waiting_on_a_failing_cycle_reports_the_canonical_error() -> None:
    """The cycle's cleanup error must not escape a concurrent stop raw."""

    async def run() -> None:
        media = _load_component_module(str(ROOT), "media_transport")
        media._EXECUTOR_JOIN_TIMEOUT_SECONDS = 0.2

        def secret() -> None:
            raise PermissionError("secret not writable")

        transport = _transport(media, Hass())

        async def silent_cycle() -> None:
            return None

        transport._async_run_cycle = silent_cycle
        with _runtime_files(media, secret, lambda: None):
            cycle_task = asyncio.create_task(transport._async_run_once())
            transport._task = cycle_task
            await asyncio.sleep(0)
            try:
                await transport.async_stop()
            except media.ComelitMediaTransportError as exc:
                assert str(exc) == "media_teardown_not_confirmed", str(exc)
                assert isinstance(exc.__cause__, PermissionError), exc.__cause__
            else:
                raise AssertionError("a failed cleanup was reported as confirmed")

            assert transport._last_error == "media_teardown_not_confirmed"
            try:
                await cycle_task
            except Exception:
                pass

    asyncio.run(run())


def test_cancellation_during_the_cleanup_join_marks_the_teardown() -> None:
    """Cancelling the join keeps the reference and the unconfirmed marker."""

    async def run() -> None:
        media = _load_component_module(str(ROOT), "media_transport")
        media._EXECUTOR_JOIN_TIMEOUT_SECONDS = 2.0
        started = threading.Event()
        release = threading.Event()

        def secret() -> None:
            started.set()
            release.wait(2)

        transport = _transport(media, Hass())
        with _runtime_files(media, secret, lambda: None):
            stop = asyncio.create_task(transport.async_stop())
            await _wait_started(started)
            stop.cancel()
            try:
                await stop
            except asyncio.CancelledError:
                pass
            else:
                raise AssertionError("the cancellation was swallowed")

            assert transport._last_error == "media_teardown_not_confirmed"
            assert transport._cleanup_task is not None
            assert not transport._cleanup_task.done()
            release.set()
            await transport._cleanup_task

    asyncio.run(run())


def test_a_successful_cleanup_retry_does_not_hide_the_cycle_failure() -> None:
    """The stop observed a failed cleanup; its own retry must not clear it."""

    async def run() -> None:
        media = _load_component_module(str(ROOT), "media_transport")
        media._EXECUTOR_JOIN_TIMEOUT_SECONDS = 0.2
        calls = {"secret": 0}

        def secret() -> None:
            calls["secret"] += 1
            if calls["secret"] == 1:
                raise PermissionError("secret first attempt")

        transport = _transport(media, Hass())

        async def silent_cycle() -> None:
            return None

        transport._async_run_cycle = silent_cycle
        with _runtime_files(media, secret, lambda: None):
            cycle_task = asyncio.create_task(transport._async_run_once())
            transport._task = cycle_task

            try:
                await transport.async_stop()
            except media.ComelitMediaTransportError as exc:
                assert str(exc) == "media_teardown_not_confirmed", str(exc)
            else:
                raise AssertionError("a retried cleanup hid the cycle failure")

            assert calls["secret"] == 2, calls
            try:
                await cycle_task
            except Exception:
                pass

    asyncio.run(run())


def test_an_already_finished_cycle_result_is_retrieved_and_kept() -> None:
    """A cycle that failed before the stop starts still fails the stop closed."""

    async def run() -> None:
        media = _load_component_module(str(ROOT), "media_transport")
        media._EXECUTOR_JOIN_TIMEOUT_SECONDS = 0.2

        def secret() -> None:
            raise PermissionError("secret not writable")

        transport = _transport(media, Hass())

        async def silent_cycle() -> None:
            return None

        transport._async_run_cycle = silent_cycle
        with _runtime_files(media, secret, lambda: None):
            cycle_task = asyncio.create_task(transport._async_run_once())
            transport._task = cycle_task
            try:
                await cycle_task
            except Exception:
                pass
            assert cycle_task.done()
            assert transport._last_error == "media_teardown_not_confirmed"

            try:
                await transport.async_stop()
            except media.ComelitMediaTransportError as exc:
                assert str(exc) == "media_teardown_not_confirmed", str(exc)
            else:
                raise AssertionError("an unconfirmed teardown was reported as released")

    asyncio.run(run())


def test_a_failed_cleanup_on_a_cancelled_cycle_still_fails_the_stop() -> None:
    """A cancelled cycle that failed to clean up keeps the stop unconfirmed."""

    async def run() -> None:
        media = _load_component_module(str(ROOT), "media_transport")
        media._EXECUTOR_JOIN_TIMEOUT_SECONDS = 0.2
        calls = {"secret": 0}

        def secret() -> None:
            calls["secret"] += 1
            if calls["secret"] == 1:
                raise PermissionError("cycle cleanup failed")

        transport = _transport(media, Hass())

        async def long_cycle() -> None:
            await asyncio.sleep(30)

        transport._async_run_cycle = long_cycle
        with _runtime_files(media, secret, lambda: None):
            cycle_task = asyncio.create_task(transport._async_run_once())
            transport._task = cycle_task
            await asyncio.sleep(0.05)

            try:
                await transport.async_stop()
            except media.ComelitMediaTransportError as exc:
                assert str(exc) == "media_teardown_not_confirmed", str(exc)
            else:
                raise AssertionError("a cancelled cycle's cleanup failure was hidden")

            assert cycle_task.cancelled()
            assert calls["secret"] >= 2, calls

    asyncio.run(run())


def test_a_stale_marker_does_not_fail_a_later_clean_cycle() -> None:
    """A failure from an earlier stop must not stick to the next clean cycle."""

    async def run() -> None:
        media = _load_component_module(str(ROOT), "media_transport")
        media._EXECUTOR_JOIN_TIMEOUT_SECONDS = 0.05
        started = asyncio.Event()
        release = asyncio.Event()
        calls = {"secret": 0}

        async def cycle() -> None:
            started.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                await release.wait()

        def secret() -> None:
            calls["secret"] += 1
            if calls["secret"] == 1:
                raise PermissionError("first stop cleanup")

        transport = _transport(media, Hass())
        transport._async_run_cycle = cycle
        with _runtime_files(media, secret, lambda: None):
            cycle_task = asyncio.create_task(transport._async_run_once())
            transport._task = cycle_task
            await started.wait()

            try:
                await transport.async_stop()
            except media.ComelitMediaTransportError as exc:
                assert str(exc) == "media_teardown_not_confirmed", str(exc)
            else:
                raise AssertionError("the first stop hid its cleanup failure")
            assert not cycle_task.done()

            release.set()
            await cycle_task

            # the cycle ended cleanly and its cleanup succeeded; no stale marker
            await transport.async_stop()

    asyncio.run(run())


def test_a_reader_that_failed_between_stops_is_retrieved() -> None:
    """A reader finishing with an error after a stop is not dropped unseen.

    The first stop cannot join the reader and reports an unconfirmed teardown.
    The reader is then allowed to fail, and the second stop must retrieve that
    result: otherwise asyncio reports "Task exception was never retrieved" when
    the task is collected.  The failure is gated on an event, so no wall-clock
    race decides which path the stop takes.
    """

    async def run() -> None:
        media = _load_component_module(str(ROOT), "media_transport")
        media._EXECUTOR_JOIN_TIMEOUT_SECONDS = 0.2
        transport = _transport(media, Hass())
        loop = asyncio.get_running_loop()
        unretrieved: list[str] = []
        loop.set_exception_handler(
            lambda _loop, ctx: unretrieved.append(str(ctx.get("message", "")))
        )
        fail_now = asyncio.Event()

        async def gated_failing_reader() -> None:
            await fail_now.wait()
            raise RuntimeError("reader broke")

        reader = asyncio.create_task(gated_failing_reader())
        transport._reader_task = reader
        await asyncio.sleep(0)

        with _runtime_files(media):
            try:
                await transport.async_stop()
            except media.ComelitMediaTransportError as exc:
                assert str(exc) == "media_teardown_not_confirmed", str(exc)
            else:
                raise AssertionError("a live reader was reported as stopped")
            assert transport._reader_task is reader

            # the first stop has returned; now let the reader fail on its own
            fail_now.set()
            await asyncio.wait({reader}, timeout=2.0)
            assert reader.done()

            await transport.async_stop()

        assert transport._reader_task is None
        del reader
        gc.collect()
        await asyncio.sleep(0)
        assert not [m for m in unretrieved if "never retrieved" in m], unretrieved

    asyncio.run(run())


def test_a_failed_stop_marker_fails_the_stop_even_when_the_child_exits() -> None:
    """A dead child is not proof that the upstream channel was released.

    ``_touch_stop`` is the only stop signal the helper understands.  When that
    job fails, terminating the child afterwards proves nothing about the
    device-side session: the stop must fail closed instead of reporting a
    clean release.
    """

    async def run() -> None:
        media = _load_component_module(str(ROOT), "media_transport")
        media._EXECUTOR_JOIN_TIMEOUT_SECONDS = 0.2

        def touch() -> None:
            raise PermissionError("stop marker not writable")

        transport = _transport(media, Hass())
        process = _LiveProcess(exit_after=0.2)
        original_touch = media._touch_stop
        media._touch_stop = touch
        try:
            with _runtime_files(media):
                transport._process = process

                try:
                    await transport.async_stop()
                except media.ComelitMediaTransportError as exc:
                    assert str(exc) == "media_teardown_not_confirmed", str(exc)
                else:
                    raise AssertionError(
                        "a failed stop marker was reported as a confirmed release"
                    )

                # the child was still reaped, and the reason stays visible
                assert process.returncode == -15, process.returncode
                assert transport._stop_marker_confirmed is False
                assert transport.last_error == "media_stop_marker_not_confirmed"
        finally:
            media._touch_stop = original_touch

    asyncio.run(run())


def test_a_repeat_stop_keeps_an_unconfirmed_marker_verdict() -> None:
    """A later stop must not confirm a release the earlier marker never proved."""

    async def run() -> None:
        media = _load_component_module(str(ROOT), "media_transport")
        media._EXECUTOR_JOIN_TIMEOUT_SECONDS = 0.2

        def touch() -> None:
            raise PermissionError("stop marker not writable")

        transport = _transport(media, Hass())
        process = _LiveProcess(exit_after=0.2)
        original_touch = media._touch_stop
        media._touch_stop = touch
        try:
            with _runtime_files(media):
                transport._process = process
                try:
                    await transport.async_stop()
                except media.ComelitMediaTransportError:
                    pass
                else:
                    raise AssertionError("first stop confirmed a failed marker")

                # the child and its references are gone; only the marker verdict
                # remains, and it must keep the teardown unconfirmed
                assert transport._process is None
                assert transport._task is None

                try:
                    await transport.async_stop()
                except media.ComelitMediaTransportError as exc:
                    assert str(exc) == "media_teardown_not_confirmed", str(exc)
                else:
                    raise AssertionError(
                        "a repeat stop confirmed an unproven release"
                    )
        finally:
            media._touch_stop = original_touch

    asyncio.run(run())


def test_a_confirmed_marker_stop_still_reports_success() -> None:
    """The new verdict must not turn a healthy stop into a failure."""

    async def run() -> None:
        media = _load_component_module(str(ROOT), "media_transport")
        media._EXECUTOR_JOIN_TIMEOUT_SECONDS = 0.2
        touched: list[int] = []

        def touch() -> None:
            touched.append(1)

        transport = _transport(media, Hass())
        process = _LiveProcess(exit_after=0.2)
        original_touch = media._touch_stop
        media._touch_stop = touch
        try:
            with _runtime_files(media):
                transport._process = process

                await transport.async_stop()

                assert touched, "the stop marker was never written"
                assert transport._stop_marker_confirmed is True
                assert transport._process is None
        finally:
            media._touch_stop = original_touch

    asyncio.run(run())


def test_a_cancelled_stop_cannot_admit_a_new_owner() -> None:
    """Cancelling mid-marker must not open the channel for a new owner.

    The stop was cancelled before the marker job proved the release, so the
    verdict stays unresolved: a new upstream owner may only start once the
    marker either confirms the release or the teardown fails closed.
    """

    async def run() -> None:
        media = _load_component_module(str(ROOT), "media_transport")
        media._EXECUTOR_JOIN_TIMEOUT_SECONDS = 2.0
        started = threading.Event()
        fail = threading.Event()

        def touch() -> None:
            started.set()
            fail.wait(3)
            raise PermissionError("stop marker not writable")

        transport = _transport(media, Hass())
        process = _LiveProcess(exit_after=0.2)
        admitted: list[str] = []

        class Entry:
            def async_create_background_task(self, _hass, coro, name):
                admitted.append(name)
                return asyncio.create_task(coro)

        transport._entry = Entry()
        transport._native_marker_tail = deque(maxlen=8)
        transport._native_p116_marker_tail = deque(maxlen=8)
        transport._native_protocol_markers = {}
        transport._native_protocol_markers_seen_total = 0
        transport._native_protocol_markers_evicted = 0
        transport._native_refresh_diagnostics = {}
        transport._native_ack_diagnostics = {}
        transport._last_native_exit_code = None
        transport._last_native_failure_markers = []
        transport._progress = SimpleNamespace(reset=lambda: None)
        transport._ring_observation = None
        transport._ring_observed = False
        transport._ring_observed_at = None
        transport._session_started_at = None
        transport._last_status_notify_monotonic = None

        async def run_once() -> None:
            raise media.ComelitMediaTransportError("media_native_exit:1")

        transport._async_run_once = run_once
        original_touch = media._touch_stop
        media._touch_stop = touch
        try:
            with _runtime_files(media):
                transport._process = process
                stop = asyncio.create_task(transport.async_stop())
                await _wait_started(started)
                stop.cancel()
                try:
                    await stop
                except asyncio.CancelledError:
                    pass

                # the marker job now finishes with a failure
                fail.set()
                marker = transport._stop_signal_task
                for _ in range(300):
                    if marker.done():
                        break
                    await asyncio.sleep(0.01)
                assert marker.done(), "marker job never finished"
                await process.wait()
                assert process.returncode is not None

                # admission for a new upstream owner stays closed
                try:
                    await transport.async_start("entrance")
                except media.ComelitMediaTransportError:
                    pass
                assert not admitted, (
                    "a new upstream owner was admitted after a cancelled stop"
                )

                # and a repeat stop still completes the teardown, fail closed
                try:
                    await transport.async_stop()
                except media.ComelitMediaTransportError as exc:
                    assert str(exc) == "media_teardown_not_confirmed", str(exc)
                else:
                    raise AssertionError(
                        "a repeat stop confirmed a release the cancelled stop "
                        "never proved"
                    )
                assert transport._stop_marker_confirmed is False
        finally:
            media._touch_stop = original_touch

    asyncio.run(run())


def test_a_second_stop_does_not_upgrade_a_failed_marker() -> None:
    """A negative verdict stays negative while the child is still alive."""

    async def run() -> None:
        media = _load_component_module(str(ROOT), "media_transport")
        media._EXECUTOR_JOIN_TIMEOUT_SECONDS = 0.2
        calls: list[int] = []
        first_failed = threading.Event()

        def touch() -> None:
            calls.append(1)
            if len(calls) == 1:
                first_failed.set()
                raise PermissionError("transient stop marker failure")

        transport = _transport(media, Hass())
        process = _LiveProcess(exit_after=1.0)
        original_touch = media._touch_stop
        media._touch_stop = touch
        try:
            with _runtime_files(media):
                transport._process = process
                first = asyncio.create_task(transport.async_stop())
                await _wait_started(first_failed)
                marker = transport._stop_signal_task
                for _ in range(300):
                    if marker.done():
                        break
                    await asyncio.sleep(0.01)
                assert marker.done(), "first marker job never finished"
                assert process.returncode is None, process.returncode

                try:
                    await transport.async_stop()
                except media.ComelitMediaTransportError as exc:
                    assert str(exc) == "media_teardown_not_confirmed", str(exc)
                else:
                    raise AssertionError(
                        "a second stop confirmed an unproven release"
                    )

                # the negative verdict was not retried into a positive one
                assert calls == [1], calls
                assert transport._stop_marker_confirmed is False

                # the first stop still owns its teardown and fails closed
                try:
                    await first
                except media.ComelitMediaTransportError as exc:
                    assert str(exc) == "media_teardown_not_confirmed", str(exc)
                else:
                    raise AssertionError("the first stop confirmed a failed marker")
                assert process.returncode is not None
        finally:
            media._touch_stop = original_touch

    asyncio.run(run())


def test_a_late_marker_success_does_not_upgrade_a_negative_verdict() -> None:
    """A join that timed out keeps its negative verdict, even if the job ends well.

    The bound that failed is the proof the owner has; a later success of the
    same job (observed by a second join) must not launder it into a release.
    """

    async def run() -> None:
        media = _load_component_module(str(ROOT), "media_transport")
        media._EXECUTOR_JOIN_TIMEOUT_SECONDS = 2.0
        started = threading.Event()
        release = threading.Event()

        def touch() -> None:
            started.set()
            release.wait(3)

        transport = _transport(media, Hass())
        process = _LiveProcess(exit_after=0.05)
        original_touch = media._touch_stop
        media._touch_stop = touch
        try:
            with _runtime_files(media):
                transport._process = process
                stop = asyncio.create_task(transport.async_stop())
                await _wait_started(started)
                # a concurrent join whose own bound elapsed first
                transport._stop_marker_confirmed = False
                transport._stop_marker_error = TimeoutError("join bound")
                release.set()
                try:
                    await stop
                except media.ComelitMediaTransportError as exc:
                    assert str(exc) == "media_teardown_not_confirmed", str(exc)
                else:
                    raise AssertionError(
                        "a late marker success upgraded an unconfirmed release"
                    )
                assert transport._stop_marker_confirmed is False
        finally:
            media._touch_stop = original_touch

    asyncio.run(run())


def test_a_proven_release_is_not_retried_by_a_later_stop() -> None:
    """Once the marker proved the release, a later stop must not re-signal it.

    Re-opening the same signal lets a transient failure downgrade a healthy
    release into an unconfirmed teardown the owner cannot recover from.
    """

    async def run() -> None:
        media = _load_component_module(str(ROOT), "media_transport")
        media._EXECUTOR_JOIN_TIMEOUT_SECONDS = 0.2
        calls: list[int] = []

        def touch() -> None:
            calls.append(1)
            raise PermissionError("marker dir read-only now")

        transport = _transport(media, Hass())
        process = _LiveProcess(exit_after=0.05)
        original_touch = media._touch_stop
        media._touch_stop = touch
        transport._stop_marker_confirmed = True
        try:
            with _runtime_files(media):
                transport._process = process
                await transport.async_stop()
                assert calls == [], f"the proven marker was re-sent: {calls}"
                assert transport._stop_marker_confirmed is True
        finally:
            media._touch_stop = original_touch

    asyncio.run(run())


def test_a_late_marker_failure_does_not_downgrade_a_proven_release() -> None:
    """Whichever terminal verdict lands first is the owner's answer.

    Two joins can disagree about a job that finished at their deadline: one
    observes its success, the other its own bound. A failure handler that runs
    after a proven release must not turn the stop into an unconfirmed teardown.
    """

    async def run() -> None:
        media = _load_component_module(str(ROOT), "media_transport")
        media._EXECUTOR_JOIN_TIMEOUT_SECONDS = 0.2
        transport = _transport(media, Hass())
        process = _LiveProcess(exit_after=0.05)

        async def join_then_time_out() -> None:
            # a concurrent join proves the release, then this one's bound lands
            transport._confirm_stop_marker()
            raise TimeoutError("join bound")

        transport._async_run_stop_signal = join_then_time_out
        with _runtime_files(media):
            transport._process = process
            await transport.async_stop()
            assert transport._stop_marker_confirmed is True
            assert transport._process is None

    asyncio.run(run())
