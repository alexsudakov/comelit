from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests" / "miniapp" / "tools"))
from optionf_pr1a_replay import (
    load_fixture_lines,
    load_plain_module,
    run_listener_replay,
)

ring_shadow = load_plain_module(
    str(ROOT), "custom_components/comelit/ring_shadow.py", "ring_shadow"
)
FIXTURES = ROOT / "tests" / "miniapp" / "fixtures" / "optionf_pr1a"


def _run(name: str, enabled: bool):
    return run_listener_replay(
        str(ROOT),
        load_fixture_lines(str(FIXTURES / name)),
        shadow_enabled=enabled,
    )


def test_normal_listener_initial_ring_production_unchanged():
    assert _run("01_listener_ring_call1.golden.txt", True) == _run(
        "01_listener_ring_call1.golden.txt", False
    )


def test_normal_listener_second_legitimate_ring_production_unchanged():
    enabled = _run("07_two_calls_sequence.golden.txt", True)
    disabled = _run("07_two_calls_sequence.golden.txt", False)
    assert enabled == disabled
    assert len(enabled["events"]) == 2


def test_batcher_exception_production_event_unaffected(monkeypatch):
    def broken_observe(self, owner, line):
        raise RuntimeError("boom")

    monkeypatch.setattr(
        ring_shadow.RingShadowController,
        "observe_native_line",
        broken_observe,
    )
    digest = _run("01_listener_ring_call1.golden.txt", True)
    assert len(digest["events"]) == 1


def test_golden_replay_existing_listener_log_identical():
    for name in (
        "01_listener_ring_call1.golden.txt",
        "02_listener_ring_call2.golden.txt",
        "05_malformed_incomplete.golden.txt",
        "06_unrelated_native_stdout.golden.txt",
        "07_two_calls_sequence.golden.txt",
    ):
        assert _run(name, True) == _run(name, False)


def test_golden_replay_t15_marker_sequence_identical():
    lines = load_fixture_lines(str(FIXTURES / "01_listener_ring_call1.golden.txt"))
    lines += load_fixture_lines(str(FIXTURES / "02_listener_ring_call2.golden.txt"))
    assert run_listener_replay(str(ROOT), lines, shadow_enabled=True) == run_listener_replay(
        str(ROOT), lines, shadow_enabled=False
    )


def test_shadow_observation_runs_after_production_handling():
    order: list[str] = []

    class Controller:
        def observe_native_line(self, owner, line):
            order.append(f"shadow:{line}")

    hook = ring_shadow.RingShadowHook(Controller(), ring_shadow.SHADOW_OWNER_LISTENER)
    previous = None
    for line in ("a=1", "b=2"):
        order.append(f"production:{line}")
        if previous is not None:
            hook.observe_line(previous)
        previous = line
    hook.observe_line(previous)

    assert order == ["production:a=1", "production:b=2", "shadow:a=1", "shadow:b=2"]
