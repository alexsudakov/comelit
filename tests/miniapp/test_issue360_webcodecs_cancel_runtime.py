from __future__ import annotations

import asyncio
import importlib.util
import logging
from pathlib import Path
import sys

import pytest


_HELPER_PATH = Path(__file__).with_name("test_controller_runtime.py")
_HELPER_NAME = "comelit_test_controller_runtime_issue360_live_handler"
_spec = importlib.util.spec_from_file_location(_HELPER_NAME, _HELPER_PATH)
assert _spec is not None and _spec.loader is not None
base = importlib.util.module_from_spec(_spec)
sys.modules[_HELPER_NAME] = base
_spec.loader.exec_module(base)


class _PausedSource:
    def __init__(self):
        self.read_started = asyncio.Event()
        self.closed = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        self.read_started.set()
        await asyncio.Event().wait()

    async def aclose(self):
        self.closed = True


class _RaceSocket(base._CaptureWebSocket):
    """The socket state is unrelated to receive-watcher provenance."""

    instances = []
    next_first = base._FakeWSMessage(
        base.views_mod.WSMsgType.TEXT, '{"type":"webcodecs","value":"h264"}'
    )
    next_messages = []

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.watch_started = asyncio.Event()

    async def __anext__(self):
        # No receive-side CLOSE frame: closed alone must not imply a peer.
        self.watch_started.set()
        await asyncio.Event().wait()


def _setup(monkeypatch, socket_type, source):
    controller, hass = base._controller(surveillance_label="Outside")
    manager, transport = base._install_webcodecs_entrance_runtime(hass)
    token, _ = controller.sessions.create(424242, 12345678)

    async def open_sdp(_source):
        return source

    monkeypatch.setattr(
        base.views_mod.webcodecs_mod,
        "open_h264_sdp_access_unit_source",
        open_sdp,
    )
    socket_type.instances = []
    monkeypatch.setattr(base.views_mod.web, "WebSocketResponse", socket_type)
    view = base.views_mod.MiniAppCameraWebCodecsView(controller)
    return view, token, manager, transport


@pytest.mark.parametrize(
    ("socket_closed", "expected_reason"),
    [(False, "cancelled"), (True, "cancelled")],
)
def test_actual_webcodecs_stream_cancel_never_infers_peer_from_socket_state(
    monkeypatch, caplog, socket_closed, expected_reason
):
    """Cancel the actual handler while it awaits RTP, before watcher close."""
    source = _PausedSource()
    view, token, manager, transport = _setup(monkeypatch, _RaceSocket, source)

    async def run():
        task = asyncio.create_task(
            view.get(base._mse_request(view.controller, token), "camera.comelit_entrance")
        )
        await asyncio.wait_for(source.read_started.wait(), 2)
        socket = _RaceSocket.instances[-1]
        await asyncio.wait_for(socket.watch_started.wait(), 2)
        socket.closed = socket_closed
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        return socket

    with caplog.at_level(logging.INFO, logger="custom_components.comelit.miniapp.views"):
        socket = asyncio.run(run())

    assert socket.closed is socket_closed
    assert source.closed
    assert manager.release_calls == ["miniapp_webcodecs"]
    assert manager.phase == "inactive"
    assert transport.active is False
    summaries = [
        record.getMessage() for record in caplog.records
        if "COMELIT_MINIAPP_WEBCODECS_SUMMARY" in record.getMessage()
    ]
    assert len(summaries) == 1
    assert f"reason={expected_reason}" in summaries[0]


def test_actual_webcodecs_teardown_cancel_after_server_socket_close(
    monkeypatch, caplog
):
    """An externally/server-closed socket is not proof the peer closed."""
    source = _PausedSource()
    class _SocketClosedOnSourceReady(_RaceSocket):
        instances = []

        async def send_json(self, payload):
            await super().send_json(payload)
            if payload.get("type") == "source_open":
                self.closed = True

    view, token, manager, transport = _setup(
        monkeypatch, _SocketClosedOnSourceReady, source
    )
    release_started = asyncio.Event()
    finish_release = asyncio.Event()
    release_done = asyncio.Event()
    original_release = manager.async_release

    async def delayed_release(*, reason):
        release_started.set()
        await finish_release.wait()
        result = await original_release(reason=reason)
        release_done.set()
        return result

    monkeypatch.setattr(manager, "async_release", delayed_release)

    async def run():
        task = asyncio.create_task(
            view.get(base._mse_request(view.controller, token), "camera.comelit_entrance")
        )
        try:
            await asyncio.wait_for(release_started.wait(), 2)
            socket = _SocketClosedOnSourceReady.instances[-1]
            assert socket.closed
            await asyncio.wait_for(socket.watch_started.wait(), 2)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            return socket
        finally:
            # Detached lease-release remains its original single owner.
            finish_release.set()
            await asyncio.wait_for(release_done.wait(), 2)

    with caplog.at_level(logging.INFO, logger="custom_components.comelit.miniapp.views"):
        socket = asyncio.run(run())

    assert socket.closed
    assert source.closed
    assert manager.release_calls == ["miniapp_webcodecs"]
    assert manager.phase == "inactive"
    assert transport.active is False
    summaries = [
        record.getMessage() for record in caplog.records
        if "COMELIT_MINIAPP_WEBCODECS_SUMMARY" in record.getMessage()
    ]
    assert len(summaries) == 1
    assert "reason=cancelled" in summaries[0]
    assert any(
        "phase=handler_cancelled" in record.getMessage()
        for record in caplog.records
    )



def test_actual_teardown_cancel_with_socket_open_is_not_client_close(
    monkeypatch, caplog
):
    """The second cancellation guard must execute with closed=False."""
    source = _PausedSource()

    class _SendStallsBeforeRtp(_RaceSocket):
        instances = []

        async def send_json(self, payload):
            if payload.get("type") == "source_open":
                await asyncio.Event().wait()
            await super().send_json(payload)

    view, token, manager, transport = _setup(
        monkeypatch, _SendStallsBeforeRtp, source
    )
    monkeypatch.setattr(
        base.views_mod.webcodecs_mod,
        "WEBCODECS_SEND_TIMEOUT_SECONDS",
        0.01,
    )
    release_started = asyncio.Event()
    release_allowed = asyncio.Event()
    release_finished = asyncio.Event()
    original_release = manager.async_release

    async def delayed_release(*, reason):
        release_started.set()
        await release_allowed.wait()
        result = await original_release(reason=reason)
        release_finished.set()
        return result

    monkeypatch.setattr(manager, "async_release", delayed_release)

    async def run():
        task = asyncio.create_task(
            view.get(base._mse_request(view.controller, token), "camera.comelit_entrance")
        )
        try:
            await asyncio.wait_for(release_started.wait(), 2)
            socket = _SendStallsBeforeRtp.instances[-1]
            assert not socket.closed
            assert socket.watch_started.is_set()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            return socket
        finally:
            release_allowed.set()
            await asyncio.wait_for(release_finished.wait(), 2)

    with caplog.at_level(logging.INFO, logger="custom_components.comelit.miniapp.views"):
        socket = asyncio.run(run())

    assert not socket.closed
    assert source.closed
    assert manager.release_calls == ["miniapp_webcodecs"]
    assert manager.phase == "inactive"
    assert transport.active is False
    summaries = [
        record.getMessage() for record in caplog.records
        if "COMELIT_MINIAPP_WEBCODECS_SUMMARY" in record.getMessage()
    ]
    assert len(summaries) == 1
    assert "reason=cancelled" in summaries[0]
    assert any(
        "phase=handler_cancelled" in record.getMessage()
        for record in caplog.records
    )


@pytest.mark.parametrize("fail_error_send", [False, True])
def test_server_initiated_websocket_close_does_not_forge_client_close(
    monkeypatch, caplog, fail_error_send
):
    """The receive watcher must not interpret our close() as peer evidence."""

    class _FailingSource(_PausedSource):
        async def __anext__(self):
            self.read_started.set()
            raise base.webcodecs_mod.WebCodecsSourceError("source_open_failed")

    class _ServerCloseWakesWatcher(_RaceSocket):
        instances = []

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.server_closed = asyncio.Event()

        async def send_json(self, payload):
            if fail_error_send and payload.get("type") == "error":
                raise ConnectionResetError("error-send interrupted")
            await super().send_json(payload)

        async def close(self):
            await super().close()
            self.server_closed.set()

        async def __anext__(self):
            self.watch_started.set()
            await self.server_closed.wait()
            raise StopAsyncIteration

    source = _FailingSource()
    view, token, manager, transport = _setup(
        monkeypatch, _ServerCloseWakesWatcher, source
    )

    async def run():
        await asyncio.wait_for(
            view.get(base._mse_request(view.controller, token), "camera.comelit_entrance"),
            timeout=2,
        )
        return _ServerCloseWakesWatcher.instances[-1]

    with caplog.at_level(logging.INFO, logger="custom_components.comelit.miniapp.views"):
        socket = asyncio.run(run())

    assert socket.closed
    assert socket.server_closed.is_set()
    assert socket.watch_started.is_set()
    assert source.closed
    assert manager.release_calls == ["miniapp_webcodecs"]
    assert manager.phase == "inactive"
    assert transport.active is False
    logs = [record.getMessage() for record in caplog.records]
    summaries = [s for s in logs if "COMELIT_MINIAPP_WEBCODECS_SUMMARY" in s]
    assert len(summaries) == 1
    assert "reason=source_open_failed" in summaries[0]
    assert not any(
        "COMELIT_MINIAPP_WEBCODECS" in s and "event=client_close" in s
        for s in logs
    )


def test_actual_received_close_frame_is_proven_client_close(monkeypatch, caplog):
    """A receive-side CLOSE is evidence even if aiohttp.closed is false."""
    source = _PausedSource()

    class _PeerCloseFrameSocket(_RaceSocket):
        instances = []

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.sent_close_frame = False

        async def __anext__(self):
            self.watch_started.set()
            await source.read_started.wait()
            if self.sent_close_frame:
                raise StopAsyncIteration
            self.sent_close_frame = True
            return base._FakeWSMessage(base.views_mod.WSMsgType.CLOSE)

    view, token, manager, transport = _setup(
        monkeypatch, _PeerCloseFrameSocket, source
    )

    async def run():
        await asyncio.wait_for(
            view.get(base._mse_request(view.controller, token), "camera.comelit_entrance"),
            timeout=2,
        )
        return _PeerCloseFrameSocket.instances[-1]

    with caplog.at_level(logging.INFO, logger="custom_components.comelit.miniapp.views"):
        socket = asyncio.run(run())

    assert socket.sent_close_frame
    assert source.closed
    assert manager.release_calls == ["miniapp_webcodecs"]
    assert manager.phase == "inactive"
    assert transport.active is False
    logs = [record.getMessage() for record in caplog.records]
    summaries = [s for s in logs if "COMELIT_MINIAPP_WEBCODECS_SUMMARY" in s]
    assert len(summaries) == 1
    assert "reason=client_close" in summaries[0]
    assert any(
        "COMELIT_MINIAPP_WEBCODECS" in s and "event=client_close" in s
        for s in logs
    )
