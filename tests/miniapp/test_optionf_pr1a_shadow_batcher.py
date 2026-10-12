from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests" / "miniapp" / "tools"))
from optionf_pr1a_replay import load_plain_module
from optionf_pr1a_replay import run_listener_replay
from optionf_pr1a_replay import run_media_replay
from optionf_pr1a_replay import _FakeProcess
from optionf_pr1a_replay import _listener_instance
from optionf_pr1a_replay import _load_component_module

ring_shadow = load_plain_module(
    str(ROOT), "custom_components/comelit/ring_shadow.py", "ring_shadow"
)
ring_event = load_plain_module(
    str(ROOT), "custom_components/comelit/ring_event.py", "ring_event"
)
_RING_KEYS = ring_event._RING_KEYS
FIXTURES = ROOT / "tests" / "miniapp" / "fixtures" / "optionf_pr1a"


def _lines(name: str) -> list[str]:
    return (FIXTURES / name).read_text(encoding="utf-8").splitlines()


def _completed_batch(lines: tuple[str, ...]):
    batcher = ring_shadow.RingMarkerBatcher()
    completed = ()
    for line in lines:
        completed = batcher.observe(line)
    assert len(completed) == 1
    return completed[0]


def test_media_owner_ring_batch_produces_shadow_decision_only():
    snapshots: list[dict[str, object]] = []
    enabled = run_media_replay(
        str(ROOT),
        _lines("03_media_owner_ring.golden.txt"),
        shadow_enabled=True,
        shadow_snapshots=snapshots,
    )
    disabled = run_media_replay(
        str(ROOT),
        _lines("03_media_owner_ring.golden.txt"),
        shadow_enabled=False,
    )

    assert enabled == disabled
    assert len(snapshots) == 1
    snapshot = snapshots[0]
    completed = snapshot["batcher"]["completed"]
    decisions = snapshot["decisions"]
    assert len(completed) == 1
    assert completed[0]["markers"] == (
        "V4_RING_OBSERVED=true",
        "V4_RING_DIRECTION=DEVICE_TO_CLIENT",
        "V4_RING_KIND=CALL_INIT",
        "V4_RING_DOOR=entrance",
        "V4_RING_SOURCE=00000643",
    )
    assert len(decisions) == 1
    assert decisions[0]["decision"] == ring_shadow.SHADOW_DECISION_SHADOW
    assert decisions[0]["production_effect"] is False


def test_retransmit_batch_shadow_suppression_only():
    controller = ring_shadow.RingShadowController()
    completed = ()
    batcher = ring_shadow.RingMarkerBatcher()
    for line in _lines("04_retransmit_batch.golden.txt"):
        controller.observe_native_line(ring_shadow.SHADOW_OWNER_MEDIA, line)
        observed = batcher.observe(line)
        if observed:
            completed += observed

    enabled = run_listener_replay(
        str(ROOT),
        _lines("04_retransmit_batch.golden.txt"),
        shadow_enabled=True,
    )
    disabled = run_listener_replay(
        str(ROOT),
        _lines("04_retransmit_batch.golden.txt"),
        shadow_enabled=False,
    )

    snapshot = controller.snapshot()
    decisions = snapshot["decisions"]
    live = snapshot["guard"]["live"]
    assert any(batch.retransmit is True for batch in completed)
    assert completed[1].retransmit is True
    assert completed[1].identity_source == "last_completed_batch"
    assert decisions[-1]["decision"] == ring_shadow.SHADOW_DECISION_SUPPRESS
    assert decisions[-1]["reason"] == ring_shadow.SHADOW_REASON_SAME_PROCESS_MEDIA_RETRANSMIT
    assert decisions[-1]["production_effect"] is False
    assert enabled == disabled
    assert len(live) == 1
    assert live[0]["generations"] == (0,)


def test_retransmit_without_identity_is_fail_closed():
    controller = ring_shadow.RingShadowController()
    batcher = ring_shadow.RingMarkerBatcher()
    completed = batcher.observe("V4_RING_RETRANSMIT_SUPPRESSED=true")
    controller.observe_native_line(
        ring_shadow.SHADOW_OWNER_MEDIA,
        "V4_RING_RETRANSMIT_SUPPRESSED=true",
    )

    snapshot = controller.snapshot()
    decisions = snapshot["decisions"]
    assert len(completed) == 1
    assert completed[0].retransmit is True
    assert completed[0].identity_source == "none"
    assert decisions[-1]["decision"] == ring_shadow.SHADOW_DECISION_SHADOW
    assert decisions[-1]["reason"] == ring_shadow.SHADOW_REASON_INCOMPLETE
    assert decisions[-1]["missing_identity"] is True
    assert snapshot["guard"]["live"] == ()


def test_malformed_then_retransmit_does_not_inherit_identity(monkeypatch):
    guard_calls = 0
    original_decide = ring_shadow.RingEmitGuard.decide

    def spy_decide(self, **kwargs):
        nonlocal guard_calls
        guard_calls += 1
        return original_decide(self, **kwargs)

    monkeypatch.setattr(ring_shadow.RingEmitGuard, "decide", spy_decide)
    controller = ring_shadow.RingShadowController()
    batcher = ring_shadow.RingMarkerBatcher()
    completed = ()
    for line in (
        "V4_RING_OBSERVED=true",
        "V4_RING_DIRECTION=DEVICE_TO_CLIENT",
        "V4_RING_KIND=CALL_INIT",
        "V4_RING_DOOR=17",
        "V4_RING_SOURCE=2",
        "V4_RING_RETRANSMIT_SUPPRESSED=true",
    ):
        controller.observe_native_line(ring_shadow.SHADOW_OWNER_LISTENER, line)
        observed = batcher.observe(line)
        if observed:
            completed += observed

    snapshot = controller.snapshot()
    assert completed[0].malformed is True
    assert completed[1].retransmit is True
    assert completed[1].identity_source == "none"
    assert completed[1].door is None
    assert completed[1].source is None
    assert guard_calls == 0
    assert snapshot["guard"]["live"] == ()
    assert snapshot["decisions"][-1]["reason"] == ring_shadow.SHADOW_REASON_INCOMPLETE


def test_sha_presence_flags_follow_native_marker_order():
    frame_batcher = ring_shadow.RingMarkerBatcher()
    for line in _lines("01_listener_ring_call1.golden.txt"):
        frame_batcher.observe(line)
    frame_completed = frame_batcher.snapshot()["completed"]

    retransmit_batcher = ring_shadow.RingMarkerBatcher()
    for line in _lines("04_retransmit_batch.golden.txt"):
        retransmit_batcher.observe(line)
    retransmit_completed = retransmit_batcher.snapshot()["completed"]

    assert frame_completed[0]["frame_sha_present"] is True
    assert retransmit_completed[1]["retransmit"] is True
    assert retransmit_completed[1]["retransmit_sha_present"] is True


def test_media_replay_harness_covers_media_reader_path():
    digest = run_media_replay(
        str(ROOT),
        _lines("03_media_owner_ring.golden.txt"),
        shadow_enabled=False,
    )

    assert "error" not in digest
    assert "P80_MEDIA_ACTIVE=true" in digest["marker_tail"]
    assert "V4_RING_OBSERVED=true" in digest["marker_tail"]


def test_conflicting_duplicate_marker_is_fail_closed():
    batch = _completed_batch((
        "V4_RING_OBSERVED=true",
        "V4_RING_DIRECTION=DEVICE_TO_CLIENT",
        "V4_RING_KIND=CALL_INIT",
        "V4_RING_DOOR=entrance",
        "V4_RING_DOOR=gate",
        "V4_RING_SOURCE=00000643",
    ))

    assert batch.malformed is True
    assert batch.door == "entrance"
    assert batch.source == "00000643"


def test_unknown_source_and_door_mismatch_are_fail_closed():
    unknown_source = _completed_batch((
        "V4_RING_OBSERVED=true",
        "V4_RING_DIRECTION=DEVICE_TO_CLIENT",
        "V4_RING_KIND=CALL_INIT",
        "V4_RING_DOOR=17",
        "V4_RING_SOURCE=2",
    ))
    door_mismatch = _completed_batch((
        "V4_RING_OBSERVED=true",
        "V4_RING_DIRECTION=DEVICE_TO_CLIENT",
        "V4_RING_KIND=CALL_INIT",
        "V4_RING_DOOR=entrance",
        "V4_RING_SOURCE=00000610",
    ))
    unsupported_direction = _completed_batch((
        "V4_RING_OBSERVED=true",
        "V4_RING_DIRECTION=CLIENT_TO_DEVICE",
        "V4_RING_KIND=CALL_INIT",
        "V4_RING_DOOR=entrance",
        "V4_RING_SOURCE=00000643",
    ))
    unsupported_kind = _completed_batch((
        "V4_RING_OBSERVED=true",
        "V4_RING_DIRECTION=DEVICE_TO_CLIENT",
        "V4_RING_KIND=OTHER",
        "V4_RING_DOOR=entrance",
        "V4_RING_SOURCE=00000643",
    ))

    assert unknown_source.malformed is True
    assert door_mismatch.malformed is True
    assert unsupported_direction.malformed is True
    assert unsupported_kind.malformed is True


def test_shadow_ring_vocabulary_matches_production():
    assert ring_shadow.SHADOW_RING_SOURCE_TO_DOOR == ring_event.SOURCE_TO_DOOR
    assert ring_shadow.SHADOW_RING_DEVICE_TO_CLIENT == ring_event.DEVICE_TO_CLIENT
    assert ring_shadow.SHADOW_RING_CALL_INIT == ring_event.CALL_INIT


def test_malformed_batch_reader_survives(monkeypatch):
    guard_calls = 0
    original_decide = ring_shadow.RingEmitGuard.decide

    def spy_decide(self, **kwargs):
        nonlocal guard_calls
        guard_calls += 1
        return original_decide(self, **kwargs)

    monkeypatch.setattr(ring_shadow.RingEmitGuard, "decide", spy_decide)
    controller = ring_shadow.RingShadowController()
    for line in _lines("05_malformed_incomplete.golden.txt"):
        controller.observe_native_line(ring_shadow.SHADOW_OWNER_LISTENER, line)

    snapshot = controller.snapshot()
    batcher = snapshot["batcher"]
    live = snapshot["guard"]["live"]
    digest = run_listener_replay(
        str(ROOT),
        _lines("05_malformed_incomplete.golden.txt"),
        shadow_enabled=True,
    )

    assert guard_calls == 1
    assert batcher["malformed_count"] >= 2
    assert len(batcher["completed"]) >= 1
    assert ("17", "2") not in tuple((item["door"], item["source"]) for item in live)
    assert "entrance" not in tuple(item["door"] for item in live)
    assert len(digest["events"]) == 1
    assert digest["events"][0]["door"] == "gate"
    assert snapshot["decisions"][-1]["production_effect"] is False


def test_incomplete_batch_reader_survives():
    batcher = ring_shadow.RingMarkerBatcher()
    batcher.observe("V4_RING_OBSERVED=true")
    batcher.observe("V4_RING_DIRECTION=DEVICE_TO_CLIENT")

    pending = batcher.pending()
    assert pending is not None
    assert pending.complete is False
    assert pending.door is None


def test_unknown_marker_interleaving_parser_survives():
    batcher = ring_shadow.RingMarkerBatcher()
    assert batcher.observe("V4_RING_UNKNOWN_KEY=1") == ()
    assert batcher.observe("plain stdout") == ()
    snapshot = batcher.snapshot()
    assert snapshot["unknown_marker_count"] == 1
    assert snapshot["no_separator_count"] == 1


def test_batch_cap_deterministic_eviction_reader_alive():
    batcher = ring_shadow.RingMarkerBatcher()
    for index in range(ring_shadow.SHADOW_MAX_COMPLETED_BATCHES + 4):
        for line in (
            "V4_RING_OBSERVED=true",
            "V4_RING_DIRECTION=DEVICE_TO_CLIENT",
            "V4_RING_KIND=CALL_INIT",
            "V4_RING_DOOR=entrance",
            f"V4_RING_SOURCE={index:08d}",
        ):
            batcher.observe(line)

    completed = batcher.snapshot()["completed"]
    assert len(completed) == ring_shadow.SHADOW_MAX_COMPLETED_BATCHES
    assert completed[0]["source"] == "00000004"

    evicting = ring_shadow.RingMarkerBatcher()
    evicting.observe("V4_RING_OBSERVED=true")
    for index in range(ring_shadow.SHADOW_MAX_LINES_PER_BATCH + 2):
        evicting.observe(f"V4_RING_DIRECTION={index}")
    assert evicting.snapshot()["eviction_count"] > 0


def test_batcher_source_is_live_stdout_not_diagnostic_fifo():
    import asyncio

    runtime = _load_component_module(str(ROOT), "runtime")
    controller = runtime.RingShadowController()
    instance, events, call_state = _listener_instance(runtime, shadow_enabled=False)
    instance._shadow_hook = runtime.RingShadowHook(
        controller,
        runtime.SHADOW_OWNER_LISTENER,
    )
    instance._native_marker_tail.clear()
    instance._ring_lines.clear()

    asyncio.run(instance._async_read_output(_FakeProcess([
        "V4_RING_OBSERVED=true",
        "V4_RING_DIRECTION=DEVICE_TO_CLIENT",
        "V4_RING_KIND=CALL_INIT",
        "V4_RING_DOOR=entrance",
        "V4_RING_SOURCE=00000643",
    ])))

    assert len(controller.snapshot()["batcher"]["completed"]) == 1


def test_shadow_ring_keys_match_production_ring_keys():
    assert ring_shadow.SHADOW_RING_BATCH_KEYS == _RING_KEYS


def test_shadow_does_not_create_second_upstream_session():
    import asyncio

    runtime = _load_component_module(str(ROOT), "runtime")
    counters = {"fake_processes": 0, "negotiate_p2p": 0}

    async def counted_negotiate(*args, **kwargs):
        counters["negotiate_p2p"] += 1
        raise AssertionError("shadow must not negotiate a second upstream session")

    if hasattr(runtime, "async_negotiate_p2p"):
        runtime.async_negotiate_p2p = counted_negotiate

    class CountedProcess(_FakeProcess):
        def __init__(self, lines):
            counters["fake_processes"] += 1
            super().__init__(lines)

    instance, events, call_state = _listener_instance(runtime, shadow_enabled=True)
    asyncio.run(
        instance._async_read_output(
            CountedProcess(_lines("01_listener_ring_call1.golden.txt"))
        )
    )

    assert counters == {"fake_processes": 1, "negotiate_p2p": 0}
    assert len(events) == 1


def test_listener_second_call_stays_same_owner_generation_until_restart():
    controller = ring_shadow.RingShadowController()
    controller.note_state(ring_shadow.SHADOW_OWNER_LISTENER, "listener_start")
    for line in _lines("07_two_calls_sequence.golden.txt"):
        controller.observe_native_line(ring_shadow.SHADOW_OWNER_LISTENER, line)

    decisions = controller.snapshot()["decisions"]
    assert decisions[0]["reason"] == ring_shadow.SHADOW_REASON_NO_LIVE_CALL
    assert decisions[1]["decision"] == ring_shadow.SHADOW_DECISION_SHADOW
    assert decisions[1]["reason"] == ring_shadow.SHADOW_REASON_SAME_PROCESS_LISTENER
    assert decisions[1]["generation"] == 1


def test_listener_restart_changes_owner_generation_and_replay_branch():
    controller = ring_shadow.RingShadowController()
    controller.note_state(ring_shadow.SHADOW_OWNER_LISTENER, "listener_start")
    for line in _lines("01_listener_ring_call1.golden.txt"):
        controller.observe_native_line(ring_shadow.SHADOW_OWNER_LISTENER, line)
    controller.note_state(ring_shadow.SHADOW_OWNER_LISTENER, "listener_start")
    for line in _lines("01_listener_ring_call1.golden.txt"):
        controller.observe_native_line(ring_shadow.SHADOW_OWNER_LISTENER, line)

    decision = controller.snapshot()["decisions"][-1]
    assert decision["generation"] == 2
    assert decision["decision"] == ring_shadow.SHADOW_DECISION_SUPPRESS
    assert decision["reason"] == ring_shadow.SHADOW_REASON_LIVE_CALL_REPLAY


def test_listener_generation_change_resets_controller_interaction_latch():
    controller = ring_shadow.RingShadowController()
    controller.note_state(ring_shadow.SHADOW_OWNER_LISTENER, "listener_start")
    controller.observe_native_line(
        ring_shadow.SHADOW_OWNER_LISTENER,
        "R37_REMOTE_RELEASE_OBSERVED=true",
    )
    controller.note_state(ring_shadow.SHADOW_OWNER_LISTENER, "listener_start")

    assert controller.snapshot()["interaction_seen"] is False


def test_interaction_seen_live_call_generation_change_is_high_a2():
    controller = ring_shadow.RingShadowController()
    controller.note_state(ring_shadow.SHADOW_OWNER_LISTENER, "listener_start")
    controller.observe_native_line(
        ring_shadow.SHADOW_OWNER_LISTENER,
        "R37_REMOTE_RELEASE_OBSERVED=true",
    )
    for line in _lines("01_listener_ring_call1.golden.txt"):
        controller.observe_native_line(ring_shadow.SHADOW_OWNER_LISTENER, line)
    controller.note_state(ring_shadow.SHADOW_OWNER_LISTENER, "listener_start")
    for line in _lines("01_listener_ring_call1.golden.txt"):
        controller.observe_native_line(ring_shadow.SHADOW_OWNER_LISTENER, line)

    decision = controller.snapshot()["decisions"][-1]
    assert decision["generation"] == 2
    assert decision["decision"] == ring_shadow.SHADOW_DECISION_OPEN_UNRESOLVED
    assert decision["reason"] == ring_shadow.SHADOW_REASON_HIGH_A2
