from __future__ import annotations

import asyncio
import gc
import importlib.util
import os
from pathlib import Path
import queue
import sys
import threading
import time
import types

import pytest


ROOT = Path(__file__).resolve().parents[2]
WEBCODECS_PATH = ROOT / "custom_components" / "comelit" / "miniapp" / "webcodecs.py"


def _load_webcodecs():
    name = "custom_components.comelit.miniapp.webcodecs_lifecycle_test"
    spec = importlib.util.spec_from_file_location(name, WEBCODECS_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


webcodecs_mod = _load_webcodecs()


class _Packet:
    pts = 90
    time_base = 1 / 90000
    is_keyframe = True

    def __bytes__(self):
        return b"\x00\x00\x00\x01\x67\x64\x00\x29\x00\x00\x00\x01\x65\x88"


class _BaseExceptionPacket(_Packet):
    def __bytes__(self):
        raise SystemExit("packet copy died")


class _CodecContext:
    name = "h264"
    extradata = None


class _Stream:
    type = "video"
    codec_context = _CodecContext()


class _AudioStream:
    type = "audio"
    codec_context = _CodecContext()


class _BlockingDemux:
    def __init__(
        self,
        container: "_FakeContainer",
        *,
        packets: list[_Packet] | None = None,
        block_reads: set[int] | None = None,
        fail_read: int | None = None,
        read_delay: float = 0,
    ) -> None:
        self._container = container
        self._packets = list(packets if packets is not None else [_Packet()])
        self._block_reads = block_reads or set()
        self._fail_read = fail_read
        self._read_delay = read_delay
        self._index = 0

    def __iter__(self):
        return self

    def __next__(self):
        index = self._index
        self._index += 1
        self._container.read_thread_id = threading.get_ident()
        self._container.read_in_progress = True
        self._container.events.append("read_start")
        self._container.read_started.set()
        try:
            if index in self._block_reads:
                self._container.release_read.wait()
            if self._read_delay:
                time.sleep(self._read_delay)
            if self._fail_read == index:
                raise RuntimeError("read failed")
            if index >= len(self._packets):
                raise StopIteration
            return self._packets[index]
        finally:
            self._container.events.append("read_end")
            self._container.read_in_progress = False
            self._container.read_ended.set()


class _FakeContainer:
    streams = [_Stream()]

    def __init__(
        self,
        *,
        packets: list[_Packet] | None = None,
        block_reads: set[int] | None = None,
        fail_read: int | None = None,
        read_delay: float = 0,
        streams: list[object] | None = None,
        block_close: bool = False,
        fail_close: bool = False,
    ) -> None:
        self.packets = packets
        self.block_reads = block_reads
        self.fail_read = fail_read
        self.read_delay = read_delay
        self.streams = streams if streams is not None else [_Stream()]
        self.block_close = block_close
        self.fail_close = fail_close
        self.read_started = threading.Event()
        self.release_read = threading.Event()
        self.read_ended = threading.Event()
        self.close_started = threading.Event()
        self.release_close = threading.Event()
        self.close_called = threading.Event()
        self.read_in_progress = False
        self.close_count = 0
        self.close_thread_id: int | None = None
        self.read_thread_id: int | None = None
        self.events: list[str] = []
        self.concurrent_close = False

    def demux(self, _stream):
        return _BlockingDemux(
            self,
            packets=self.packets,
            block_reads=self.block_reads,
            fail_read=self.fail_read,
            read_delay=self.read_delay,
        )

    def close(self):
        self.close_thread_id = threading.get_ident()
        self.concurrent_close = self.read_in_progress
        assert not self.read_in_progress
        self.close_started.set()
        if self.block_close:
            self.release_close.wait()
        self.close_count += 1
        self.events.append("close")
        self.close_called.set()
        if self.fail_close:
            raise RuntimeError("close failed")


def _install_av(monkeypatch, container: _FakeContainer, open_block: threading.Event | None = None):
    def fake_open(*_args, **_kwargs):
        if open_block is not None:
            open_block.wait()
        return container

    monkeypatch.setitem(sys.modules, "av", types.SimpleNamespace(open=fake_open))


def _run(coro):
    return asyncio.run(coro)


async def _wait_event(event: threading.Event, timeout: float = 1.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if event.is_set():
            return True
        await asyncio.sleep(0)
    return event.is_set()


async def _wait_thread_exit(thread: threading.Thread, timeout: float = 1.0) -> bool:
    deadline = time.monotonic() + timeout
    while thread.is_alive() and time.monotonic() < deadline:
        await asyncio.sleep(0)
    return not thread.is_alive()


async def _collect_loop_garbage() -> None:
    for _ in range(4):
        await asyncio.sleep(0)
        gc.collect()
    await asyncio.sleep(0)


def _future_exception_warnings(contexts: list[dict[str, object]]) -> list[dict[str, object]]:
    return [
        context
        for context in contexts
        if context.get("message") == "Future exception was never retrieved"
    ]


def test_cancelled_consumer_cleanup_waits_for_read_before_close(monkeypatch):
    container = _FakeContainer(block_reads={0})
    _install_av(monkeypatch, container)
    monkeypatch.setattr(webcodecs_mod, "WEBCODECS_SOURCE_CLOSE_JOIN_TIMEOUT", 0.05)

    async def run():
        source = await webcodecs_mod.open_h264_access_unit_source("rtsp://example/live")
        task = asyncio.create_task(source.__anext__())
        assert await _wait_event(container.read_started)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        close_task = asyncio.create_task(source.aclose())
        await asyncio.sleep(0)
        assert container.close_count == 0
        assert container.read_in_progress
        container.release_read.set()
        await asyncio.wait_for(close_task, timeout=1)
        assert await _wait_event(container.close_called)
        assert container.close_count == 1
        assert container.close_thread_id == container.read_thread_id
        assert container.events == ["read_start", "read_end", "close"]
        assert await _wait_thread_exit(source._owner._thread)

    _run(run())
    assert not container.concurrent_close


def test_fast_reads_are_not_delayed_by_polling_bridge(monkeypatch):
    container = _FakeContainer(packets=[_Packet() for _ in range(25)])
    _install_av(monkeypatch, container)

    async def run():
        source = await webcodecs_mod.open_h264_access_unit_source("rtsp://example/live")
        started = time.monotonic()
        for _ in range(25):
            assert (await asyncio.wait_for(source.__anext__(), timeout=1)).payload
        elapsed = time.monotonic() - started
        await asyncio.wait_for(source.aclose(), timeout=1)
        assert elapsed < 0.15
        assert container.close_count == 1
        assert await _wait_thread_exit(source._owner._thread)

    _run(run())


def test_delayed_read_uses_single_bridge_await_without_tiny_timeout(monkeypatch):
    container = _FakeContainer(read_delay=0.02)
    _install_av(monkeypatch, container)
    real_asyncio = webcodecs_mod.asyncio

    class _CountingAsyncio:
        def __init__(self, wrapped):
            self._wrapped = wrapped
            self.wait_for_calls = 0
            self.shield_calls = 0
            self.timeouts: list[float | None] = []

        def __getattr__(self, name):
            return getattr(self._wrapped, name)

        async def wait_for(self, aw, timeout=None):
            self.wait_for_calls += 1
            self.timeouts.append(timeout)
            return await self._wrapped.wait_for(aw, timeout=timeout)

        def shield(self, arg):
            self.shield_calls += 1
            return self._wrapped.shield(arg)

    counting_asyncio = _CountingAsyncio(real_asyncio)
    monkeypatch.setattr(webcodecs_mod, "asyncio", counting_asyncio)

    async def run():
        source = await webcodecs_mod.open_h264_access_unit_source("rtsp://example/live")
        counting_asyncio.wait_for_calls = 0
        counting_asyncio.shield_calls = 0
        counting_asyncio.timeouts.clear()

        assert (await real_asyncio.wait_for(source.__anext__(), timeout=1)).payload

        assert counting_asyncio.shield_calls == 1
        assert counting_asyncio.wait_for_calls == 0
        assert not [
            timeout
            for timeout in counting_asyncio.timeouts
            if timeout is not None and timeout <= 0.002
        ]
        await real_asyncio.wait_for(source.aclose(), timeout=1)
        assert container.close_count == 1
        assert await _wait_thread_exit(source._owner._thread)

    _run(run())


def test_packet_read_creates_no_file_descriptors_or_private_future_bridge(monkeypatch):
    container = _FakeContainer()
    _install_av(monkeypatch, container)

    async def run():
        bridge = webcodecs_mod._LoopFutureBridge(asyncio.get_running_loop())
        assert not hasattr(bridge, "_notify_reader")
        assert not hasattr(bridge, "_notify_writer")
        assert not hasattr(bridge.future, "_webcodecs_bridge")
        bridge.set_result(None)
        await asyncio.sleep(0)
        assert bridge.future.done()
        assert not hasattr(bridge.future, "_webcodecs_bridge")

        source = await webcodecs_mod.open_h264_access_unit_source("rtsp://example/live")
        fds_before = len(os.listdir("/proc/self/fd"))
        assert (await source.__anext__()).payload
        fds_after = len(os.listdir("/proc/self/fd"))
        await source.aclose()

        assert fds_after == fds_before
        assert container.close_count == 1
        assert await _wait_thread_exit(source._owner._thread)

    _run(run())


def test_normal_eos_closes_owner_thread_once(monkeypatch):
    container = _FakeContainer(packets=[])
    _install_av(monkeypatch, container)

    async def run():
        source = await webcodecs_mod.open_h264_access_unit_source("rtsp://example/live")
        with pytest.raises(StopAsyncIteration):
            await source.__anext__()
        await source.aclose()
        assert container.close_count == 1
        assert container.close_thread_id == container.read_thread_id
        assert await _wait_thread_exit(source._owner._thread)

    _run(run())


def test_cancellation_during_open_closes_after_open_finishes(monkeypatch):
    container = _FakeContainer(packets=[])
    open_block = threading.Event()
    _install_av(monkeypatch, container, open_block=open_block)

    async def run():
        task = asyncio.create_task(
            webcodecs_mod.open_h264_access_unit_source("rtsp://example/live")
        )
        await asyncio.sleep(0)
        task.cancel()
        open_block.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert await _wait_event(container.close_called)
        assert container.close_count == 1
        assert container.close_thread_id is not None

    _run(run())


def test_cancel_close_before_first_packet_closes_without_read(monkeypatch):
    container = _FakeContainer()
    _install_av(monkeypatch, container)

    async def run():
        source = await webcodecs_mod.open_h264_access_unit_source("rtsp://example/live")
        await source.aclose()
        assert container.close_count == 1
        assert container.events == ["close"]
        assert not container.read_started.is_set()
        assert await _wait_thread_exit(source._owner._thread)

    _run(run())


def test_cancellation_during_active_packet_read_is_safe(monkeypatch):
    container = _FakeContainer(block_reads={0})
    _install_av(monkeypatch, container)
    monkeypatch.setattr(webcodecs_mod, "WEBCODECS_SOURCE_CLOSE_JOIN_TIMEOUT", 0.05)

    async def run():
        source = await webcodecs_mod.open_h264_sdp_access_unit_source("/tmp/source.sdp")
        task = asyncio.create_task(source.__anext__())
        assert await _wait_event(container.read_started)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await source.aclose()
        assert container.close_count == 0
        container.release_read.set()
        assert await _wait_event(container.close_called)
        assert container.close_count == 1
        assert container.close_thread_id == container.read_thread_id
        assert not container.concurrent_close

    _run(run())


def test_owner_thread_death_after_open_resolves_close_without_full_bound(
    monkeypatch, caplog
):
    class _ExplodingCommands:
        def __init__(self):
            self._queued: queue.Queue[object] = queue.Queue()

        def get(self):
            raise SystemExit("command loop died")

        def get_nowait(self):
            return self._queued.get_nowait()

        def put(self, command):
            self._queued.put(command)

    container = _FakeContainer()
    _install_av(monkeypatch, container)
    monkeypatch.setattr(webcodecs_mod, "WEBCODECS_SOURCE_CLOSE_JOIN_TIMEOUT", 0.5)

    async def run():
        source = await webcodecs_mod.open_h264_access_unit_source("rtsp://example/live")
        original_commands = source._owner._commands
        source._owner._commands = _ExplodingCommands()
        original_commands.put(("ignored", object()))
        assert await _wait_event(container.close_called)
        assert await _wait_thread_exit(source._owner._thread)
        assert container.close_count == 1
        assert not container.concurrent_close
        started = time.monotonic()
        await source.aclose()
        elapsed = time.monotonic() - started
        assert elapsed < 0.1
        assert container.close_count == 1
        assert "owner did not stop" not in caplog.text

    _run(run())


def test_teardown_drain_error_does_not_escape_owner_thread(monkeypatch):
    class _DrainExplodingCommands:
        def get(self):
            raise SystemExit("command loop died")

        def get_nowait(self):
            raise RuntimeError("drain failed")

        def put(self, _command):
            pass

    container = _FakeContainer()
    _install_av(monkeypatch, container)
    monkeypatch.setattr(webcodecs_mod, "WEBCODECS_SOURCE_CLOSE_JOIN_TIMEOUT", 0.5)

    async def run():
        loop = asyncio.get_running_loop()
        contexts: list[dict[str, object]] = []
        previous_handler = loop.get_exception_handler()
        loop.set_exception_handler(lambda _loop, context: contexts.append(context))
        try:
            source = await webcodecs_mod.open_h264_access_unit_source(
                "rtsp://example/live"
            )
            owner = source._owner
            original_commands = owner._commands
            owner._commands = _DrainExplodingCommands()
            original_commands.put(("ignored", object()))
            assert await _wait_event(container.close_called)
            assert owner.join(1)
            assert container.close_count == 1
            assert owner._terminated
            started = time.monotonic()
            await asyncio.wait_for(source.aclose(), timeout=1)
            elapsed = time.monotonic() - started
            assert elapsed < 0.1
            assert container.close_count == 1
            assert contexts == []
        finally:
            loop.set_exception_handler(previous_handler)

    _run(run())


def test_read_failure_keeps_close_serialized(monkeypatch):
    container = _FakeContainer(fail_read=0)
    _install_av(monkeypatch, container)

    async def run():
        source = await webcodecs_mod.open_h264_access_unit_source("rtsp://example/live")
        with pytest.raises(RuntimeError, match="read failed"):
            await source.__anext__()
        await source.aclose()
        assert container.close_count == 1
        assert container.events == ["read_start", "read_end", "close"]
        assert container.close_thread_id == container.read_thread_id

    _run(run())


def test_owner_base_exception_during_next_resolves_waiters(monkeypatch):
    container = _FakeContainer(packets=[_BaseExceptionPacket()])
    _install_av(monkeypatch, container)
    monkeypatch.setattr(webcodecs_mod, "WEBCODECS_SOURCE_CLOSE_JOIN_TIMEOUT", 0.05)

    async def run():
        loop = asyncio.get_running_loop()
        contexts: list[dict[str, object]] = []
        previous_handler = loop.get_exception_handler()
        loop.set_exception_handler(lambda _loop, context: contexts.append(context))
        source = await webcodecs_mod.open_h264_access_unit_source("rtsp://example/live")
        owner = source._owner
        thread = owner._thread
        try:
            with pytest.raises(webcodecs_mod.WebCodecsSourceError) as exc_info:
                await asyncio.wait_for(source.__anext__(), timeout=1)
            assert exc_info.value.code == "source_open_failed"
            assert isinstance(exc_info.value.__cause__, SystemExit)
            assert await _wait_event(container.close_called)
            assert container.close_count == 1
            assert await _wait_thread_exit(thread)

            with pytest.raises(webcodecs_mod.WebCodecsSourceError):
                await asyncio.wait_for(source.__anext__(), timeout=1)
            await asyncio.wait_for(source.aclose(), timeout=1)
            assert container.close_count == 1
            del source, owner
            await _collect_loop_garbage()
            assert contexts == []
            assert _future_exception_warnings(contexts) == []
        finally:
            loop.set_exception_handler(previous_handler)

    _run(run())


def test_next_packet_during_owner_terminal_drain_resolves_waiter(monkeypatch):
    class _DrainBlockingCommands:
        def __init__(self):
            self.drain_started = threading.Event()
            self.release_drain = threading.Event()
            self.put_commands: list[object] = []
            self._first_drain = True

        def get(self):
            raise SystemExit("command loop died")

        def get_nowait(self):
            if self._first_drain:
                self._first_drain = False
                self.drain_started.set()
                self.release_drain.wait()
            raise queue.Empty

        def put(self, command):
            self.put_commands.append(command)

    container = _FakeContainer()
    _install_av(monkeypatch, container)
    monkeypatch.setattr(webcodecs_mod, "WEBCODECS_SOURCE_CLOSE_JOIN_TIMEOUT", 0.05)

    async def run():
        loop = asyncio.get_running_loop()
        contexts: list[dict[str, object]] = []
        previous_handler = loop.get_exception_handler()
        loop.set_exception_handler(lambda _loop, context: contexts.append(context))
        source = await webcodecs_mod.open_h264_access_unit_source("rtsp://example/live")
        owner = source._owner
        thread = owner._thread
        commands = _DrainBlockingCommands()
        try:
            original_commands = owner._commands
            owner._commands = commands
            original_commands.put(("ignored", object()))
            assert await _wait_event(commands.drain_started)

            next_future = owner.next_packet()
            with pytest.raises(webcodecs_mod.WebCodecsSourceError):
                await asyncio.wait_for(next_future, timeout=0.2)
            assert commands.put_commands == []

            commands.release_drain.set()
            assert await _wait_event(container.close_called)
            assert container.close_count == 1
            assert await _wait_thread_exit(thread)
            await asyncio.wait_for(source.aclose(), timeout=1)
            assert container.close_count == 1
            del source, owner
            await _collect_loop_garbage()
            assert contexts == []
            assert _future_exception_warnings(contexts) == []
        finally:
            commands.release_drain.set()
            loop.set_exception_handler(previous_handler)

    _run(run())


def test_late_read_error_after_cancel_is_retrieved(monkeypatch):
    container = _FakeContainer(block_reads={0}, fail_read=0)
    _install_av(monkeypatch, container)
    monkeypatch.setattr(webcodecs_mod, "WEBCODECS_SOURCE_CLOSE_JOIN_TIMEOUT", 0.05)

    async def run():
        loop = asyncio.get_running_loop()
        contexts: list[dict[str, object]] = []
        previous_handler = loop.get_exception_handler()
        loop.set_exception_handler(lambda _loop, context: contexts.append(context))
        source = await webcodecs_mod.open_h264_access_unit_source("rtsp://example/live")
        owner = source._owner
        thread = owner._thread
        task = asyncio.create_task(source.__anext__())
        try:
            assert await _wait_event(container.read_started)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            container.release_read.set()
            await source.aclose()
            assert await _wait_event(container.close_called)
            assert container.close_count == 1
            assert await _wait_thread_exit(thread)
            del source, owner, task
            await _collect_loop_garbage()
            assert contexts == []
            assert _future_exception_warnings(contexts) == []
        finally:
            loop.set_exception_handler(previous_handler)

    _run(run())


def test_late_open_error_after_cancel_is_retrieved(monkeypatch):
    container = _FakeContainer(streams=[_AudioStream()])
    open_block = threading.Event()
    _install_av(monkeypatch, container, open_block=open_block)
    monkeypatch.setattr(webcodecs_mod, "WEBCODECS_SOURCE_CLOSE_JOIN_TIMEOUT", 0.05)
    owners: list[object] = []
    original_init = webcodecs_mod._H264PyAVOwner.__init__

    def init_spy(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        owners.append(self)

    monkeypatch.setattr(webcodecs_mod._H264PyAVOwner, "__init__", init_spy)

    async def run():
        loop = asyncio.get_running_loop()
        contexts: list[dict[str, object]] = []
        previous_handler = loop.get_exception_handler()
        loop.set_exception_handler(lambda _loop, context: contexts.append(context))
        task = asyncio.create_task(
            webcodecs_mod.open_h264_access_unit_source("rtsp://example/live")
        )
        try:
            await asyncio.sleep(0)
            assert owners
            owner = owners[0]
            thread = owner._thread
            task.cancel()
            open_block.set()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert await _wait_event(container.close_called)
            assert container.close_count == 1
            assert await _wait_thread_exit(thread)
            owners.clear()
            del owner, task
            await _collect_loop_garbage()
            assert contexts == []
            assert _future_exception_warnings(contexts) == []
        finally:
            loop.set_exception_handler(previous_handler)

    _run(run())


def test_late_close_error_after_cancel_is_retrieved(monkeypatch):
    container = _FakeContainer(block_close=True, fail_close=True)
    _install_av(monkeypatch, container)
    monkeypatch.setattr(webcodecs_mod, "WEBCODECS_SOURCE_CLOSE_JOIN_TIMEOUT", 0.05)

    async def run():
        loop = asyncio.get_running_loop()
        contexts: list[dict[str, object]] = []
        previous_handler = loop.get_exception_handler()
        loop.set_exception_handler(lambda _loop, context: contexts.append(context))
        source = await webcodecs_mod.open_h264_access_unit_source("rtsp://example/live")
        owner = source._owner
        thread = owner._thread
        task = asyncio.create_task(source.aclose())
        try:
            assert await _wait_event(container.close_started)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            container.release_close.set()
            assert await _wait_event(container.close_called)
            assert container.close_count == 1
            assert not container.concurrent_close
            assert await _wait_thread_exit(thread)
            del source, owner, task
            await _collect_loop_garbage()
            assert contexts == []
            assert _future_exception_warnings(contexts) == []
        finally:
            loop.set_exception_handler(previous_handler)

    _run(run())


def test_repeated_close_is_idempotent(monkeypatch):
    container = _FakeContainer(packets=[])
    _install_av(monkeypatch, container)

    async def run():
        source = await webcodecs_mod.open_h264_access_unit_source("rtsp://example/live")
        await source.aclose()
        await source.aclose()
        await source.aclose()
        assert container.close_count == 1
        assert await _wait_thread_exit(source._owner._thread)

    _run(run())


def test_repeated_close_after_cancel_waits_for_native_close(monkeypatch):
    container = _FakeContainer(block_close=True)
    _install_av(monkeypatch, container)
    monkeypatch.setattr(webcodecs_mod, "WEBCODECS_SOURCE_CLOSE_JOIN_TIMEOUT", 0.5)

    async def run():
        source = await webcodecs_mod.open_h264_access_unit_source("rtsp://example/live")
        first_close = asyncio.create_task(source.aclose())
        assert await _wait_event(container.close_started)
        first_close.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first_close

        second_close = asyncio.create_task(source.aclose())
        await asyncio.sleep(0)
        assert not second_close.done()
        assert container.close_count == 0
        container.release_close.set()
        await asyncio.wait_for(second_close, timeout=1)
        assert container.close_count == 1
        assert await _wait_thread_exit(source._owner._thread)

    _run(run())


def test_repeated_start_cancel_close_cycles_leave_no_owner_thread(monkeypatch):
    created: list[_FakeContainer] = []

    def fake_open_tracked(*_args, **_kwargs):
        container = _FakeContainer(block_reads={0})
        created.append(container)
        return container

    monkeypatch.setitem(sys.modules, "av", types.SimpleNamespace(open=fake_open_tracked))

    async def tracked_run():
        for _ in range(4):
            source = await webcodecs_mod.open_h264_access_unit_source("rtsp://example/live")
            container = created[-1]
            task = asyncio.create_task(source.__anext__())
            assert await _wait_event(container.read_started)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            close_task = asyncio.create_task(source.aclose())
            await asyncio.sleep(0)
            container.release_read.set()
            await asyncio.wait_for(close_task, timeout=1)
            assert container.close_count == 1
            assert await _wait_thread_exit(source._owner._thread)

    _run(tracked_run())


def test_worker_lifecycle_finishes_after_eos_cleanup(monkeypatch):
    container = _FakeContainer(packets=[])
    _install_av(monkeypatch, container)

    async def run():
        source = await webcodecs_mod.open_h264_access_unit_source("rtsp://example/live")
        assert source._owner._thread.is_alive()
        with pytest.raises(StopAsyncIteration):
            await source.__anext__()
        await source.aclose()
        assert container.close_count == 1
        assert container.close_called.is_set()
        assert await _wait_thread_exit(source._owner._thread)

    _run(run())


def test_bounded_teardown_returns_without_concurrent_close(monkeypatch):
    container = _FakeContainer(block_reads={0})
    _install_av(monkeypatch, container)
    monkeypatch.setattr(webcodecs_mod, "WEBCODECS_SOURCE_CLOSE_JOIN_TIMEOUT", 0.05)

    async def run():
        source = await webcodecs_mod.open_h264_access_unit_source("rtsp://example/live")
        task = asyncio.create_task(source.__anext__())
        assert await _wait_event(container.read_started)
        started = time.monotonic()
        await source.aclose()
        elapsed = time.monotonic() - started
        assert elapsed < 0.5
        assert container.close_count == 0
        assert container.read_in_progress
        container.release_read.set()
        result = await asyncio.wait_for(task, timeout=1)
        assert result.payload
        assert await _wait_event(container.close_called)
        assert container.close_count == 1
        assert container.close_thread_id == container.read_thread_id
        assert not container.concurrent_close

    _run(run())


def test_negative_control_legacy_to_thread_close_race_trips_fake_container(monkeypatch):
    container = _FakeContainer(block_reads={0})
    iterator = iter(container.demux(_Stream()))
    read_result: list[_Packet] = []

    def legacy_worker_read():
        read_result.append(next(iterator))

    async def run():
        read_thread = threading.Thread(target=legacy_worker_read)
        read_thread.start()
        assert await _wait_event(container.read_started)
        assert container.read_in_progress
        with pytest.raises(AssertionError):
            container.close()
        assert container.concurrent_close
        assert container.close_count == 0
        container.release_read.set()
        assert await _wait_thread_exit(read_thread)
        assert read_result
        assert container.events == ["read_start", "read_end"]

    _run(run())
