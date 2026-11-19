"""Issue #319: at most one Ring publication per native frame, across owners."""

from __future__ import annotations

import asyncio
from pathlib import Path
import sys
import types

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests" / "miniapp" / "tools"))
from optionf_pr1a_replay import _load_component_module


runtime_mod = _load_component_module(str(ROOT), "runtime")
RingEvent = runtime_mod.RingEvent
SHA_A = "a" * 64
SHA_B = "b" * 64


class _RuntimeStub:
    """Minimal stand-in exposing exactly what the emit path touches."""

    listener_ready = False

    def __init__(self) -> None:
        self._ring_publish_latch: dict[str, dict] = {}
        self.emitted: list[tuple[dict, bool, bool]] = []
        self.fired: list[dict] = []
        for name in (
            "_ring_latch_find",
            "_ring_latch_write",
            "_ring_latch_mark",
            "_ring_latch_set",
            "_ring_apply_missing_effects",
        ):
            setattr(
                self,
                name,
                types.MethodType(
                    getattr(runtime_mod.ComelitRingRuntime, name), self
                ),
            )

    # -- sink used by async_emit_media_owner_ring --------------------------
    async def _async_emit_ring_event(
        self,
        event,
        *,
        require_media_start: bool = False,
        start_ring_media: bool = True,
        begin_call_state: bool = True,
        frame_sha256: str | None = None,
    ):
        self.emitted.append((dict(event), start_ring_media, begin_call_state))
        return dict(event)


class _FullStub(_RuntimeStub):
    """Enough plumbing to exercise the real publication point."""

    def __init__(self) -> None:
        super().__init__()
        self._last_ring_event = None
        self.media_starts: list[dict] = []
        self.call_states: list[dict] = []
        self._entry = types.SimpleNamespace(
            async_create_background_task=self._background_task
        )
        self._hass = types.SimpleNamespace(
            bus=types.SimpleNamespace(async_fire=self._fire)
        )
        self._async_emit_ring_event = types.MethodType(
            runtime_mod.ComelitRingRuntime._async_emit_ring_event, self
        )

    def _background_task(self, hass, coro, name):
        coro.close()
        return None

    def _fire(self, event_type, payload):
        self.fired.append({"type": event_type, "payload": dict(payload)})

    def _call_state_tracker(self):
        def begin(**kwargs):
            self.call_states.append(kwargs)
            return False

        return types.SimpleNamespace(begin=begin)

    def _schedule_call_state_timeout(self, event_id):
        return None

    def _notify_status(self):
        return None

    def _ring_media_for_event(self, event):
        async def start(payload):
            self.media_starts.append(dict(payload))
            return True

        return types.SimpleNamespace(async_start_for_ring=start)

    async def _async_start_ring_media(self, event):
        return None


def _ring(door: str = "entrance", source: str = "00000643") -> "RingEvent":
    return RingEvent(
        direction="DEVICE_TO_CLIENT",
        kind="CALL_INIT",
        door=door,
        source=source,
    )


def _emit(stub, sha=SHA_A) -> None:
    asyncio.run(
        runtime_mod.ComelitRingRuntime.async_emit_media_owner_ring(
            stub, _ring(), sha
        )
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


def test_same_frame_is_suppressed_on_a_second_observation():
    stub = _FullStub()
    _emit(stub, SHA_A)
    _emit(stub, SHA_A)
    assert len(stub.fired) == 1


def test_a_different_frame_is_a_different_call():
    stub = _FullStub()
    _emit(stub, SHA_A)
    _emit(stub, SHA_B)
    assert len(stub.fired) == 2


def test_latch_expires_after_the_native_window(monkeypatch):
    stub = _FullStub()
    _emit(stub, SHA_A)
    for key in stub._ring_publish_latch:
        stub._ring_publish_latch[key]["deadline"] = 0.0
    _emit(stub, SHA_A)
    assert len(stub.fired) == 2


def test_latch_does_not_grow_without_bound():
    stub = _FullStub()
    for index in range(5):
        stub._ring_publish_latch[f"stale-{index}"] = {
            "deadline": 0.0,
            "payload": {},
            "call_state": False,
            "media": False,
        }
    _emit(stub, SHA_A)
    assert all(
        entry["deadline"] > 0.0 for entry in stub._ring_publish_latch.values()
    )


def test_listener_path_consults_the_same_latch():
    stub = _FullStub()
    event = {"door": "entrance", "source": "00000643", "kind": "CALL_INIT"}
    asyncio.run(
        runtime_mod.ComelitRingRuntime._async_emit_ring_event(
            stub, dict(event), frame_sha256=SHA_A
        )
    )
    asyncio.run(
        runtime_mod.ComelitRingRuntime._async_emit_ring_event(
            stub, dict(event), frame_sha256=SHA_A
        )
    )
    assert len(stub.fired) == 1


def test_synthetic_ring_is_never_latched():
    stub = _FullStub()
    event = {
        "door": "entrance",
        "source": "synthetic_test",
        "kind": "CALL_INIT",
        "synthetic": True,
    }
    asyncio.run(runtime_mod.ComelitRingRuntime._async_emit_ring_event(stub, dict(event)))
    asyncio.run(runtime_mod.ComelitRingRuntime._async_emit_ring_event(stub, dict(event)))
    assert len(stub.fired) == 2
    assert stub._ring_publish_latch == {}


def test_listener_runs_the_effects_the_media_owner_skipped():
    stub = _FullStub()
    _emit(stub, SHA_A)
    assert stub.fired and stub.media_starts == [] and stub.call_states == []
    asyncio.run(
        runtime_mod.ComelitRingRuntime._async_emit_ring_event(
            stub,
            {"door": "entrance", "source": "00000643", "kind": "CALL_INIT"},
            frame_sha256=SHA_A,
        )
    )
    assert len(stub.fired) == 1
    assert len(stub.media_starts) == 1
    assert len(stub.call_states) == 1


def test_suppressed_observation_reuses_the_first_event_id():
    stub = _FullStub()
    _emit(stub, SHA_A)
    first = stub.fired[0]["payload"]["event_id"]
    asyncio.run(
        runtime_mod.ComelitRingRuntime._async_emit_ring_event(
            stub,
            {"door": "entrance", "source": "00000643", "kind": "CALL_INIT"},
            frame_sha256=SHA_A,
        )
    )
    assert len(stub.fired) == 1
    assert stub.fired[0]["payload"]["event_id"] == first
    assert stub.call_states[0]["event_id"] == first


def test_digest_and_tuple_windows_differ():
    stub = _FullStub()
    _emit(stub, SHA_A)
    deadlines = {
        key: entry["deadline"] for key, entry in stub._ring_publish_latch.items()
    }
    sha = next(value for key, value in deadlines.items() if key.startswith("sha:"))
    call = next(value for key, value in deadlines.items() if key.startswith("call:"))
    assert sha - call == pytest.approx(75.0, abs=1.0)


def test_release_clears_only_the_released_call():
    stub = _FullStub()
    _emit(stub, SHA_A)
    released = stub.fired[0]["payload"]["event_id"]
    stub._last_ring_event = {"event_id": released}
    other = dict(stub._ring_publish_latch)
    runtime_mod.ComelitRingRuntime._ring_latch_forget_released(stub)
    assert stub._ring_publish_latch == {}
    assert other  # sanity: there was something to clear
