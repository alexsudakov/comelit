from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests" / "miniapp" / "tools"))
from optionf_pr1a_replay import (
    _FakeProcess,
    _listener_instance,
    _load_component_module,
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
    runtime = _load_component_module(str(ROOT), "runtime")
    calls = 0

    def broken_observe(self, owner, line):
        nonlocal calls
        calls += 1
        raise RuntimeError("boom")

    monkeypatch.setattr(
        runtime.RingShadowController,
        "observe_native_line",
        broken_observe,
    )
    instance, events, call_state = _listener_instance(runtime, shadow_enabled=True)
    import asyncio

    asyncio.run(
        instance._async_read_output(
            _FakeProcess(load_fixture_lines(str(FIXTURES / "01_listener_ring_call1.golden.txt")))
        )
    )
    digest = {
        "events": events,
        "call_state": call_state,
    }
    assert len(digest["events"]) == 1
    assert calls == ring_shadow.SHADOW_FAILURE_LATCH_LIMIT
    assert instance._shadow_hook.latched is True


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
    import asyncio

    runtime = _load_component_module(str(ROOT), "runtime")
    order: list[str] = []

    class Controller:
        def observe_native_line(self, owner, line):
            order.append(f"shadow:{line}")

    instance, events, call_state = _listener_instance(runtime, shadow_enabled=False)
    instance._shadow_hook = runtime.RingShadowHook(
        Controller(),
        runtime.SHADOW_OWNER_LISTENER,
    )

    async def emit(event):
        order.append("production:emit")
        events.append(event)

    instance._async_emit_ring_event = emit
    lines = [
        "V4_RING_OBSERVED=true",
        "V4_RING_DIRECTION=DEVICE_TO_CLIENT",
        "V4_RING_KIND=CALL_INIT",
        "V4_RING_DOOR=entrance",
        "V4_RING_SOURCE=00000643",
        "AFTER=1",
    ]
    asyncio.run(instance._async_read_output(_FakeProcess(lines)))

    assert order.index("production:emit") < order.index("shadow:V4_RING_SOURCE=00000643")
    assert order[-1] == "shadow:AFTER=1"
