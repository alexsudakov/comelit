from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests" / "miniapp" / "tools"))
from optionf_pr1a_replay import load_plain_module

ring_shadow = load_plain_module(
    str(ROOT), "custom_components/comelit/ring_shadow.py", "ring_shadow"
)


class _BrokenController:
    def __init__(self) -> None:
        self.calls = 0

    def observe_native_line(self, owner: str, line: str) -> None:
        self.calls += 1
        raise RuntimeError("shadow failure")

    def note_state(self, owner: str, state: str) -> None:
        self.calls += 1
        raise RuntimeError("shadow failure")


def test_shadow_init_exception_integration_setup_unaffected(monkeypatch):
    def broken_init(self):
        raise RuntimeError("init failed")

    monkeypatch.setattr(ring_shadow.RingShadowController, "__init__", broken_init)
    shadow_controller = None
    try:
        shadow_controller = ring_shadow.RingShadowController()
    except Exception:
        shadow_controller = None

    hook = ring_shadow.RingShadowHook(shadow_controller, ring_shadow.SHADOW_OWNER_LISTENER)
    hook.observe_line("V4_RING_OBSERVED=true")
    assert hook.latched is True


def test_shadow_unload_exception_unload_unaffected():
    controller = _BrokenController()
    try:
        controller.note_state(ring_shadow.SHADOW_OWNER_LISTENER, "integration_unload")
    except Exception:
        pass
    assert controller.calls == 1


def test_shadow_supervisor_hook_exception_supervisor_unchanged():
    hook = ring_shadow.RingShadowHook(_BrokenController(), ring_shadow.SHADOW_OWNER_LISTENER)
    hook.note_state("supervisor_spawn")
    assert hook.latched is False


def test_shadow_media_hook_exception_media_unchanged():
    hook = ring_shadow.RingShadowHook(_BrokenController(), ring_shadow.SHADOW_OWNER_MEDIA)
    hook.note_state("media_transport_start")
    assert hook.latched is False


def test_shadow_hook_latches_after_bounded_failures():
    controller = _BrokenController()
    hook = ring_shadow.RingShadowHook(controller, ring_shadow.SHADOW_OWNER_LISTENER)
    for _ in range(ring_shadow.SHADOW_FAILURE_LATCH_LIMIT + 2):
        hook.observe_line("V4_RING_OBSERVED=true")

    assert hook.latched is True
    assert controller.calls == ring_shadow.SHADOW_FAILURE_LATCH_LIMIT
