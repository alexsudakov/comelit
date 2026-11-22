"""Owner exclusivity across the real session manager.

These pin the integration-level guarantee that no transport stop can overlap an
in-flight start and that a cancelled start keeps admission closed until its
teardown is proven.  They instrument the transport boundary, so a regression in
the session lock, the phase gates or the cancelled-start recovery shows up as
reordered enters/exits.
"""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "comelit_owner_exclusivity_test",
    ROOT / "custom_components/comelit/media_session.py",
)
assert SPEC is not None and SPEC.loader is not None
media_session = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(media_session)


class _Listener:
    def __init__(self) -> None:
        self.media_paused = False

    async def async_pause_for_media(self) -> None:
        self.media_paused = True

    async def async_resume_after_media(self) -> None:
        self.media_paused = False


class _GatedTransport:
    """Records every entry/exit at the transport boundary."""

    def __init__(self, *, gate_stop: bool = False) -> None:
        self.active = False
        self.last_error = None
        self.last_native_exit_code = None
        self.events: list[str] = []
        self.start_entered = asyncio.Event()
        self.start_release = asyncio.Event()
        self.stop_entered = asyncio.Event()
        self.stop_release = asyncio.Event()
        self.gate_stop = gate_stop

    async def async_start(self, panel: str) -> None:
        self.events.append("start_enter")
        self.start_entered.set()
        await self.start_release.wait()
        self.active = True
        self.events.append("start_exit")

    async def async_stop(self) -> None:
        self.events.append("stop_enter")
        self.stop_entered.set()
        if self.gate_stop:
            await self.stop_release.wait()
        self.active = False
        self.events.append("stop_exit")


def _manager(transport: _GatedTransport):
    return media_session.ComelitMediaSessionManager(
        _Listener(), transport, recovery_timeout_seconds=1.0
    )


async def _settle() -> None:
    for _ in range(20):
        await asyncio.sleep(0)


def test_a_stop_cannot_enter_the_transport_while_a_start_is_pending() -> None:
    async def exercise() -> None:
        transport = _GatedTransport()
        manager = _manager(transport)
        start = asyncio.create_task(
            manager.async_acquire(panel="entrance", reason="camera_view")
        )
        await asyncio.wait_for(transport.start_entered.wait(), 2)
        assert manager.status()["phase"] == "starting"

        stop = asyncio.create_task(manager.async_force_stop(reason="user"))
        await _settle()
        assert transport.events == ["start_enter"], transport.events

        transport.start_release.set()
        await asyncio.wait_for(start, 2)
        await asyncio.wait_for(stop, 2)
        assert transport.events == [
            "start_enter",
            "start_exit",
            "stop_enter",
            "stop_exit",
        ], transport.events

    asyncio.run(exercise())


def test_a_cancelled_pending_start_keeps_admission_closed_until_proof() -> None:
    async def exercise() -> None:
        transport = _GatedTransport(gate_stop=True)
        manager = _manager(transport)
        start = asyncio.create_task(
            manager.async_acquire(panel="entrance", reason="camera_view")
        )
        await asyncio.wait_for(transport.start_entered.wait(), 2)
        start.cancel()
        await asyncio.wait_for(transport.stop_entered.wait(), 2)
        await _settle()

        # The native child was never assigned and no marker ran, yet the
        # manager must still refuse a second owner while the stop is unproven.
        assert manager.status()["phase"] != "inactive"
        with pytest.raises(media_session.ComelitMediaSessionError) as exc:
            await manager.async_acquire(panel="entrance", reason="camera_view")
        assert str(exc.value) == "media_teardown_unconfirmed"

        transport.stop_release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(start, 2)
        assert transport.events == ["start_enter", "stop_enter", "stop_exit"]
        assert transport.active is False

        # Only a confirmed teardown admits the next owner.
        transport.start_release.set()
        await manager.async_acquire(panel="entrance", reason="camera_view")
        assert transport.active is True
        assert transport.events.count("start_enter") == 2

    asyncio.run(exercise())


def test_shutdown_waits_for_a_pending_start_before_stopping() -> None:
    async def exercise() -> None:
        transport = _GatedTransport()
        manager = _manager(transport)
        start = asyncio.create_task(
            manager.async_acquire(panel="entrance", reason="camera_view")
        )
        await asyncio.wait_for(transport.start_entered.wait(), 2)

        shutdown = asyncio.create_task(manager.async_shutdown())
        await _settle()
        assert transport.events == ["start_enter"], transport.events

        transport.start_release.set()
        await asyncio.wait_for(start, 2)
        await asyncio.wait_for(shutdown, 2)
        assert transport.events == [
            "start_enter",
            "start_exit",
            "stop_enter",
            "stop_exit",
        ], transport.events
        assert manager.status()["phase"] == "inactive"
        assert transport.active is False

    asyncio.run(exercise())
