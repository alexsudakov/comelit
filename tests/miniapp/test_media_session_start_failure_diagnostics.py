from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "comelit_media_session_failure_test",
    ROOT / "custom_components/comelit/media_session.py",
)
assert SPEC is not None and SPEC.loader is not None
media_session = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(media_session)


class _Listener:
    def __init__(self, *, pause_error: Exception | None = None) -> None:
        self.media_paused = False
        self.pause_error = pause_error
        self.resume_calls = 0

    async def async_pause_for_media(self) -> None:
        if self.pause_error is not None:
            raise self.pause_error
        self.media_paused = True

    async def async_resume_after_media(self) -> None:
        self.resume_calls += 1
        self.media_paused = False


class _Transport:
    def __init__(
        self,
        *,
        start_error: Exception | None = None,
        last_error: object = None,
        exit_code: object = None,
    ) -> None:
        self.active = False
        self.start_error = start_error
        self.last_error = last_error
        self.last_native_exit_code = exit_code

    async def async_start(self, panel: str) -> None:
        if self.start_error is not None:
            raise self.start_error
        self.active = True

    async def async_stop(self) -> None:
        self.active = False


def _manager(listener: _Listener, transport: _Transport):
    return media_session.ComelitMediaSessionManager(listener, transport)


def test_listener_pause_failure_is_retained_separately_from_current_error() -> None:
    async def exercise() -> None:
        listener = _Listener(pause_error=RuntimeError("private detail"))
        manager = _manager(listener, _Transport())

        with pytest.raises(media_session.ComelitMediaSessionError):
            await manager.async_acquire(panel="entrance", reason="camera_view")

        status = manager.status()
        assert status["phase"] == "inactive"
        assert status["last_error"] is None
        assert status["last_start_failure"]["reason"] == "start_failed:RuntimeError"
        assert status["last_start_failure"]["stage"] == "listener_pause"
        assert status["last_start_failure"]["transport_last_error"] is None
        assert status["last_start_failure"]["transport_native_exit_code"] is None
        failed_at = datetime.fromisoformat(status["last_start_failure"]["at"])
        assert failed_at.tzinfo is not None
        assert failed_at.utcoffset() == UTC.utcoffset(failed_at)
        assert listener.resume_calls == 1

    asyncio.run(exercise())


def test_transport_failure_retains_only_bounded_safe_transport_evidence() -> None:
    async def exercise() -> None:
        listener = _Listener()
        transport = _Transport(
            start_error=RuntimeError("contains secret"),
            last_error="https://user:secret@example.invalid/private",
            exit_code=True,
        )
        manager = _manager(listener, transport)

        with pytest.raises(media_session.ComelitMediaSessionError):
            await manager.async_acquire(panel="entrance", reason="camera_view")

        failure = manager.status()["last_start_failure"]
        assert failure["stage"] == "transport_start"
        assert failure["transport_last_error"] == "<redacted>"
        assert failure["transport_native_exit_code"] is None
        assert "secret" not in repr(failure)
        assert listener.resume_calls == 1

    asyncio.run(exercise())


def test_last_start_failure_is_a_defensive_historical_snapshot() -> None:
    async def exercise() -> None:
        listener = _Listener()
        transport = _Transport(
            start_error=RuntimeError("boom"),
            last_error="media_native_exited_before_active:-9",
            exit_code=-9,
        )
        manager = _manager(listener, transport)

        with pytest.raises(media_session.ComelitMediaSessionError):
            await manager.async_acquire(panel="entrance", reason="camera_view")

        first = manager.status()["last_start_failure"]
        first["reason"] = "tampered"
        transport.start_error = None
        await manager.async_acquire(panel="entrance", reason="camera_view")
        after_retry = manager.status()["last_start_failure"]

        assert after_retry["reason"] == "start_failed:RuntimeError"
        assert after_retry["transport_last_error"] == (
            "media_native_exited_before_active:-9"
        )
        assert after_retry["transport_native_exit_code"] == -9
        await manager.async_force_stop(reason="test_cleanup")
        assert manager.status()["last_start_failure"] == after_retry

    asyncio.run(exercise())
