from __future__ import annotations

import asyncio
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests" / "miniapp" / "tools"))
from optionf_pr1a_replay import load_plain_module
from optionf_pr1a_replay import run_listener_replay
from optionf_pr1a_replay import run_media_replay
from optionf_pr1a_replay import _FakeProcess
from optionf_pr1a_replay import _digest
from optionf_pr1a_replay import _listener_instance
from optionf_pr1a_replay import _media_instance
from optionf_pr1a_replay import _load_component_module

ring_shadow = load_plain_module(
    str(ROOT), "custom_components/comelit/ring_shadow.py", "ring_shadow"
)
FIXTURES = ROOT / "tests" / "miniapp" / "fixtures" / "optionf_pr1a"


def _lines(name: str) -> list[str]:
    return (FIXTURES / name).read_text(encoding="utf-8").splitlines()


def test_t12_listener_batcher_failure_does_not_change_listener_replay(monkeypatch):
    runtime = _load_component_module(str(ROOT), "runtime")
    baseline = run_listener_replay(
        str(ROOT),
        _lines("01_listener_ring_call1.golden.txt"),
        shadow_enabled=False,
    )

    original_init = runtime.RingShadowController.__init__

    class BrokenBatcher:
        def observe(self, line):
            raise RuntimeError("listener batcher failed")

    def broken_init(self):
        original_init(self)
        self._batchers[runtime.SHADOW_OWNER_LISTENER] = BrokenBatcher()

    monkeypatch.setattr(runtime.RingShadowController, "__init__", broken_init)
    instance, events, call_state = _listener_instance(runtime, shadow_enabled=True)
    asyncio.run(
        instance._async_read_output(
            _FakeProcess(_lines("01_listener_ring_call1.golden.txt"))
        )
    )
    candidate = _digest(instance, events, call_state)

    assert candidate == baseline


def test_t13_media_batcher_failure_does_not_change_media_replay(monkeypatch):
    media_transport = _load_component_module(str(ROOT), "media_transport")
    baseline = run_media_replay(
        str(ROOT),
        _lines("03_media_owner_ring.golden.txt"),
        shadow_enabled=False,
    )

    original_init = media_transport.RingShadowController.__init__

    class BrokenBatcher:
        def observe(self, line):
            raise RuntimeError("media batcher failed")

    def broken_init(self):
        original_init(self)
        self._batchers[media_transport.SHADOW_OWNER_MEDIA] = BrokenBatcher()

    monkeypatch.setattr(media_transport.RingShadowController, "__init__", broken_init)
    instance, events, call_state, shadow = _media_instance(
        media_transport, shadow_enabled=True
    )
    asyncio.run(
        instance._async_read_output(
            _FakeProcess(_lines("03_media_owner_ring.golden.txt"))
        )
    )
    candidate = _digest(instance, events, call_state)

    assert candidate == baseline


def test_handoff_tracker_failure_is_latched_inside_shadow_hook():
    class BrokenController:
        calls = 0

        def note_state(self, owner, state):
            self.calls += 1
            raise RuntimeError("handoff tracker failed")

    controller = BrokenController()
    hook = ring_shadow.RingShadowHook(controller, ring_shadow.SHADOW_OWNER_LISTENER)
    for _ in range(ring_shadow.SHADOW_FAILURE_LATCH_LIMIT + 1):
        hook.note_state("listener_start")

    assert controller.calls == ring_shadow.SHADOW_FAILURE_LATCH_LIMIT
    assert hook.latched is True


def test_owner_reset_failure_is_latched_inside_shadow_hook():
    class BrokenController:
        calls = 0

        def note_state(self, owner, state):
            self.calls += 1
            raise RuntimeError("owner reset failed")

    controller = BrokenController()
    hook = ring_shadow.RingShadowHook(controller, ring_shadow.SHADOW_OWNER_LISTENER)
    for _ in range(ring_shadow.SHADOW_FAILURE_LATCH_LIMIT + 1):
        hook.note_state("listener_stop")

    assert controller.calls == ring_shadow.SHADOW_FAILURE_LATCH_LIMIT
    assert hook.latched is True


def test_snapshot_generation_failure_does_not_touch_shadow_state():
    class BrokenSnapshot(ring_shadow.RingShadowController):
        def snapshot_view(self):
            raise RuntimeError("snapshot failed")

    controller = BrokenSnapshot()
    controller.note_state(ring_shadow.SHADOW_OWNER_LISTENER, "listener_start")
    for line in _lines("01_listener_ring_call1.golden.txt"):
        controller.observe_native_line(ring_shadow.SHADOW_OWNER_LISTENER, line)
    before = controller.snapshot()
    try:
        controller.snapshot_view()
    except RuntimeError:
        pass
    after = controller.snapshot()

    assert after == before
