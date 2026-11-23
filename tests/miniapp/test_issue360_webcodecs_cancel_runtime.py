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
    """aiohttp reports closed before the receive watcher signals client_closed."""

    instances = []
    next_first = base._FakeWSMessage(
        base.views_mod.WSMsgType.TEXT, '{"type":"webcodecs","value":"h264"}'
    )
    next_messages = []

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.watch_started = asyncio.Event()

    async def __anext__(self):
        # No receive-side CLOSED frame: only websocket.closed is authoritative.
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
    [(False, "cancelled"), (True, "client_close")],
)
def test_actual_webcodecs_stream_cancel_preserves_socket_close(
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


def test_actual_webcodecs_teardown_cancel_preserves_socket_close(
    monkeypatch, caplog
):
    """Cancel during a pending media release, before the receive watcher exits."""
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
    assert "reason=client_close" in summaries[0]
    assert any(
        "phase=handler_cancelled" in record.getMessage()
        for record in caplog.records
    )
