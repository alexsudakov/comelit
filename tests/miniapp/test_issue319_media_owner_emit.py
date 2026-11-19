"""Issue #319: the media owner publishes at most one Ring per observed call."""

from __future__ import annotations

import asyncio
from pathlib import Path
import sys
import types


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests" / "miniapp" / "tools"))
from optionf_pr1a_replay import _load_component_module


runtime_mod = _load_component_module(str(ROOT), "runtime")
RingEvent = runtime_mod.RingEvent


class _RuntimeStub:
    """Minimal stand-in exposing exactly what the emit path touches."""

    listener_ready = False

    def __init__(self) -> None:
        self._ring_publish_latch: dict[tuple[str, str, str], float] = {}
        self.emitted: list[tuple[dict, bool, bool]] = []
        for name in ("_note_ring_publish", "_ring_publish_is_duplicate"):
            setattr(
                self,
                name,
                types.MethodType(
                    getattr(runtime_mod.ComelitRingRuntime, name), self
                ),
            )

    async def _async_emit_ring_event(
        self,
        event,
        *,
        require_media_start: bool = False,
        start_ring_media: bool = True,
        begin_call_state: bool = True,
    ):
        self.emitted.append((dict(event), start_ring_media, begin_call_state))
        return dict(event)


def _ring(door: str = "entrance", source: str = "00000643") -> "RingEvent":
    return RingEvent(
        direction="DEVICE_TO_CLIENT",
        kind="CALL_INIT",
        door=door,
        source=source,
    )


def _emit(stub) -> None:
    asyncio.run(
        runtime_mod.ComelitRingRuntime.async_emit_media_owner_ring(stub, _ring())
    )


def test_listener_ready_owns_publication():
    stub = _RuntimeStub()
    stub.listener_ready = True
    _emit(stub)
    assert stub.emitted == []


def test_media_owner_publishes_once_without_ring_media_or_call_state():
    stub = _RuntimeStub()
    _emit(stub)
    assert len(stub.emitted) == 1
    _event, start_ring_media, begin_call_state = stub.emitted[0]
    assert start_ring_media is False
    assert begin_call_state is False


def test_second_observation_of_the_same_call_is_suppressed():
    stub = _RuntimeStub()
    _emit(stub)
    _emit(stub)
    assert len(stub.emitted) == 1


def test_a_different_call_is_published_after_the_latch_expires():
    stub = _RuntimeStub()
    _emit(stub)
    stub._ring_publish_latch.clear()
    _emit(stub)
    assert len(stub.emitted) == 2


def test_latch_does_not_grow_without_bound():
    stub = _RuntimeStub()
    for index in range(5):
        stub._ring_publish_latch[("entrance", f"{index:08d}", "CALL_INIT")] = 0.0
    _emit(stub)
    assert all(deadline > 0.0 for deadline in stub._ring_publish_latch.values())


def test_gate_returns_before_any_emit_when_listener_is_ready():
    stub = _RuntimeStub()
    stub.listener_ready = True
    _emit(stub)
    assert stub._ring_publish_latch == {}
