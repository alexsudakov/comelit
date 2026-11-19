"""Issue #319: the media owner publishes without taking over the lifecycle."""

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


class _Stub:
    def __init__(self) -> None:
        self.calls: list[tuple[dict, bool, bool]] = []
        self.fired: list[dict] = []
        self.media_starts = 0
        self.call_states = 0
        self._last_ring_event = None
        self._hass = types.SimpleNamespace(
            bus=types.SimpleNamespace(async_fire=self._fire)
        )
        self._entry = types.SimpleNamespace(
            async_create_background_task=self._background_task
        )
        self._async_emit_ring_event = types.MethodType(
            runtime_mod.ComelitRingRuntime._async_emit_ring_event, self
        )

    def _background_task(self, hass, coro, name):
        self.media_starts += 1
        coro.close()
        return None

    def _fire(self, event_type, payload):
        self.fired.append({"type": event_type, "payload": dict(payload)})

    def _call_state_tracker(self):
        def begin(**kwargs):
            self.call_states += 1
            return False

        return types.SimpleNamespace(begin=begin)

    def _schedule_call_state_timeout(self, event_id):
        return None

    def _notify_status(self):
        return None

    def _ring_media_for_event(self, event):
        return None


def _ring() -> "RingEvent":
    return RingEvent(
        direction="DEVICE_TO_CLIENT",
        kind="CALL_INIT",
        door="entrance",
        source="00000643",
    )


def _emit(stub) -> None:
    asyncio.run(
        runtime_mod.ComelitRingRuntime.async_emit_media_owner_ring(stub, _ring())
    )


def test_media_owner_publishes_one_event_per_observation():
    stub = _Stub()
    _emit(stub)
    assert len(stub.fired) == 1
    assert stub.fired[0]["payload"]["door"] == "entrance"


def test_media_owner_does_not_start_ring_media_or_call_state():
    stub = _Stub()
    _emit(stub)
    assert stub.media_starts == 0
    assert stub.call_states == 0


def test_media_owner_keeps_the_standard_payload():
    stub = _Stub()
    _emit(stub)
    payload = stub.fired[0]["payload"]
    assert payload["kind"] == "CALL_INIT"
    assert payload["direction"] == "DEVICE_TO_CLIENT"
    assert payload["source"] == "00000643"
    assert "event_id" in payload
    assert "timestamp" in payload
