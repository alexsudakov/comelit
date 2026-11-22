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
from contextlib import contextmanager
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
            release.wait(5)

        transport = _transport(media, Hass())
        original = media._touch_stop
        media._touch_stop = touch
        try:
            stop = asyncio.create_task(transport._async_run_stop_signal())
            while not started.is_set():
                await asyncio.sleep(0.01)
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
            release.wait(5)
            removed.append("secret")

        def remove_sdp() -> None:
            removed.append("sdp")

        transport = _transport(media, Hass())
        with _runtime_files(media, remove_secret, remove_sdp):
            stop = asyncio.create_task(transport._async_join_cleanup())
            while not started.is_set():
                await asyncio.sleep(0.01)
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
            release.wait(5)

        transport = _transport(media, Hass())
        with _runtime_files(media, remove_secret):
            stop = asyncio.create_task(transport.async_stop())
            while not started.is_set():
                await asyncio.sleep(0.01)
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
            release.wait(5)

        transport = _transport(media, Hass())
        with _runtime_files(media, remove_secret):

            async def failing_cycle() -> None:
                raise media.ComelitMediaTransportError("media_native_exit:6")

            transport._async_run_cycle = failing_cycle
            run_once = asyncio.create_task(transport._async_run_once())
            while not started.is_set():
                await asyncio.sleep(0.01)
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
