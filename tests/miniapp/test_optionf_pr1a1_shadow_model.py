from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests" / "miniapp" / "tools"))
from optionf_pr1a_replay import load_plain_module
from optionf_pr1a_replay import run_listener_replay

ring_shadow = load_plain_module(
    str(ROOT), "custom_components/comelit/ring_shadow.py", "ring_shadow"
)
FIXTURES = ROOT / "tests" / "miniapp" / "fixtures" / "optionf_pr1a"


def _lines(name: str) -> list[str]:
    return (FIXTURES / name).read_text(encoding="utf-8").splitlines()


def _ring(controller, owner):
    for line in _lines("01_listener_ring_call1.golden.txt"):
        controller.observe_native_line(owner, line)


def _ring_key(controller, owner, door, source):
    for line in (
        "V4_RING_OBSERVED=true",
        "V4_RING_DIRECTION=DEVICE_TO_CLIENT",
        "V4_RING_KIND=CALL_INIT",
        f"V4_RING_DOOR={door}",
        f"V4_RING_SOURCE={source}",
    ):
        controller.observe_native_line(owner, line)


def _decision_constants():
    return {
        value
        for name, value in vars(ring_shadow).items()
        if name.startswith("SHADOW_DECISION_")
    }


def _reason_constants():
    return {
        value
        for name, value in vars(ring_shadow).items()
        if name.startswith("SHADOW_REASON_")
    }


def test_t1_t2_listener_replay_production_visible_parity():
    one = _lines("01_listener_ring_call1.golden.txt")
    two = _lines("07_two_calls_sequence.golden.txt")

    assert run_listener_replay(str(ROOT), one, shadow_enabled=True) == run_listener_replay(
        str(ROOT), one, shadow_enabled=False
    )
    assert run_listener_replay(str(ROOT), two, shadow_enabled=True) == run_listener_replay(
        str(ROOT), two, shadow_enabled=False
    )


def test_t3_t4_handoff_replays_are_not_g1():
    controller = ring_shadow.RingShadowController()
    controller.note_state(ring_shadow.SHADOW_OWNER_LISTENER, "listener_start")
    _ring(controller, ring_shadow.SHADOW_OWNER_LISTENER)
    controller.note_state(ring_shadow.SHADOW_OWNER_LISTENER, "listener_stop")
    controller.note_state(ring_shadow.SHADOW_OWNER_MEDIA, "media_transport_start")
    _ring(controller, ring_shadow.SHADOW_OWNER_MEDIA)
    decision = controller.snapshot()["decisions"][-1]

    assert decision["decision"] == ring_shadow.SHADOW_DECISION_HANDOFF_REPLAY
    assert decision["reason"] == ring_shadow.SHADOW_REASON_HANDOFF_REPLAY
    assert decision["new_call_proven"] is False
    assert decision["handoff_epoch"] == 1
    assert decision["handoff_token"] == 1

    controller.note_state(ring_shadow.SHADOW_OWNER_MEDIA, "media_transport_stop")
    controller.note_state(ring_shadow.SHADOW_OWNER_LISTENER, "listener_start")
    _ring(controller, ring_shadow.SHADOW_OWNER_LISTENER)
    decision = controller.snapshot()["decisions"][-1]

    assert decision["decision"] == ring_shadow.SHADOW_DECISION_HANDOFF_REPLAY
    assert decision["reason"] == ring_shadow.SHADOW_REASON_HANDOFF_REPLAY
    assert decision["new_call_proven"] is False


def test_t5_t18_high_a2_canonical_open_unresolved():
    guard = ring_shadow.RingEmitGuard()
    guard.decide(
        door="entrance",
        source="00000643",
        owner=ring_shadow.SHADOW_OWNER_LISTENER,
        owner_generation=(ring_shadow.SHADOW_OWNER_LISTENER, 1),
    )
    guard.observe_interaction(ring_shadow.SHADOW_OWNER_LISTENER)
    decision = guard.decide(
        door="entrance",
        source="00000643",
        owner=ring_shadow.SHADOW_OWNER_LISTENER,
        owner_generation=(ring_shadow.SHADOW_OWNER_LISTENER, 2),
    )

    assert decision.decision == ring_shadow.SHADOW_DECISION_OPEN_UNRESOLVED
    assert decision.reason == ring_shadow.SHADOW_REASON_HIGH_A2
    assert decision.new_call_proven is False


def test_t6_t7_owner_lifecycle_reset_clears_stale_state_without_new_call_proof():
    controller = ring_shadow.RingShadowController()
    controller.note_state(ring_shadow.SHADOW_OWNER_LISTENER, "listener_start")
    _ring(controller, ring_shadow.SHADOW_OWNER_LISTENER)
    controller.note_state(ring_shadow.SHADOW_OWNER_LISTENER, "listener_start")
    snapshot = controller.snapshot()

    assert snapshot["guard"]["live"][0]["reset_reason"] == "owner_lifecycle_reset"
    assert snapshot["guard"]["decisions"][-1]["reason"] == ring_shadow.SHADOW_REASON_LIVE_STATE_RESET
    assert snapshot["guard"]["decisions"][-1]["new_call_proven"] is False

    _ring(controller, ring_shadow.SHADOW_OWNER_LISTENER)
    decision = controller.snapshot()["decisions"][-1]
    assert decision["reason"] == ring_shadow.SHADOW_REASON_LIVE_STATE_RESET
    assert decision["decision"] == ring_shadow.SHADOW_DECISION_OPEN_UNRESOLVED


def test_t8_known_retransmit_can_never_emit_new_event():
    guard = ring_shadow.RingEmitGuard()
    no_live = guard.decide(
        door="entrance",
        source="00000643",
        owner=ring_shadow.SHADOW_OWNER_LISTENER,
        owner_generation=(ring_shadow.SHADOW_OWNER_LISTENER, 1),
        retransmit=True,
        production_emit_allowed=True,
        has_new_physical_call_discriminator=True,
    )
    same_generation = guard.decide(
        door="entrance",
        source="00000643",
        owner=ring_shadow.SHADOW_OWNER_LISTENER,
        owner_generation=(ring_shadow.SHADOW_OWNER_LISTENER, 1),
        retransmit=True,
        production_emit_allowed=True,
        has_new_physical_call_discriminator=True,
    )
    different_generation = guard.decide(
        door="entrance",
        source="00000643",
        owner=ring_shadow.SHADOW_OWNER_LISTENER,
        owner_generation=(ring_shadow.SHADOW_OWNER_LISTENER, 2),
        retransmit=True,
        production_emit_allowed=True,
        has_new_physical_call_discriminator=True,
    )

    assert no_live.decision != ring_shadow.SHADOW_DECISION_EMIT
    assert same_generation.decision != ring_shadow.SHADOW_DECISION_EMIT
    assert different_generation.decision != ring_shadow.SHADOW_DECISION_EMIT


def test_t9_equal_generation_numbers_are_owner_qualified():
    guard = ring_shadow.RingEmitGuard()
    guard.decide(
        door="entrance",
        source="00000643",
        owner=ring_shadow.SHADOW_OWNER_LISTENER,
        owner_generation=(ring_shadow.SHADOW_OWNER_LISTENER, 1),
    )
    decision = guard.decide(
        door="entrance",
        source="00000643",
        owner=ring_shadow.SHADOW_OWNER_MEDIA,
        owner_generation=(ring_shadow.SHADOW_OWNER_MEDIA, 1),
    )

    assert decision.decision == ring_shadow.SHADOW_DECISION_HANDOFF_REPLAY
    assert decision.reason == ring_shadow.SHADOW_REASON_HANDOFF_REPLAY


def test_t10_generation_number_change_does_not_prove_new_call():
    guard = ring_shadow.RingEmitGuard()
    guard.decide(
        door="entrance",
        source="00000643",
        owner=ring_shadow.SHADOW_OWNER_LISTENER,
        owner_generation=(ring_shadow.SHADOW_OWNER_LISTENER, 1),
    )
    decision = guard.decide(
        door="entrance",
        source="00000643",
        owner=ring_shadow.SHADOW_OWNER_LISTENER,
        owner_generation=(ring_shadow.SHADOW_OWNER_LISTENER, 99),
    )

    assert decision.decision == ring_shadow.SHADOW_DECISION_SUPPRESS
    assert decision.reason == ring_shadow.SHADOW_REASON_LIVE_CALL_REPLAY
    assert decision.new_call_proven is False


def test_t11_owner_scoped_batchers_prevent_cross_owner_interleaving():
    controller = ring_shadow.RingShadowController()
    controller.observe_native_line(ring_shadow.SHADOW_OWNER_LISTENER, "V4_RING_OBSERVED=true")
    controller.observe_native_line(
        ring_shadow.SHADOW_OWNER_LISTENER, "V4_RING_DIRECTION=DEVICE_TO_CLIENT"
    )
    _ring(controller, ring_shadow.SHADOW_OWNER_MEDIA)
    snapshot = controller.snapshot()

    assert snapshot["batchers"][ring_shadow.SHADOW_OWNER_LISTENER]["pending"] is not None
    assert snapshot["batchers"][ring_shadow.SHADOW_OWNER_LISTENER]["completed"] == ()
    assert len(snapshot["batchers"][ring_shadow.SHADOW_OWNER_MEDIA]["completed"]) == 1


def test_t14_t19_watchdog_boundary_replay_open_unresolved():
    controller = ring_shadow.RingShadowController()
    controller.note_state(ring_shadow.SHADOW_OWNER_LISTENER, "listener_start")
    _ring(controller, ring_shadow.SHADOW_OWNER_LISTENER)
    controller.note_watchdog_boundary_crossed(ring_shadow.SHADOW_OWNER_LISTENER)
    controller.note_state(ring_shadow.SHADOW_OWNER_LISTENER, "listener_stop")
    controller.note_state(ring_shadow.SHADOW_OWNER_MEDIA, "media_transport_start")
    _ring(controller, ring_shadow.SHADOW_OWNER_MEDIA)
    decision = controller.snapshot()["decisions"][-1]

    assert decision["decision"] == ring_shadow.SHADOW_DECISION_OPEN_UNRESOLVED
    assert decision["reason"] == ring_shadow.SHADOW_REASON_HIGH_3
    assert decision["new_call_proven"] is False

    _ring(controller, ring_shadow.SHADOW_OWNER_MEDIA)
    repeat = controller.snapshot()["decisions"][-1]
    assert repeat["decision"] == ring_shadow.SHADOW_DECISION_SUPPRESS
    assert repeat["reason"] == ring_shadow.SHADOW_REASON_LIVE_CALL_REPLAY


def test_cycle_restart_without_stop_tombstones_and_first_observation_is_unresolved():
    controller = ring_shadow.RingShadowController()
    controller.note_state(ring_shadow.SHADOW_OWNER_LISTENER, "listener_start")
    _ring(controller, ring_shadow.SHADOW_OWNER_LISTENER)

    controller.note_state(ring_shadow.SHADOW_OWNER_LISTENER, "listener_start")
    live = controller.snapshot()["guard"]["live"]
    assert live[0]["reset_reason"] == "owner_lifecycle_reset"

    _ring(controller, ring_shadow.SHADOW_OWNER_LISTENER)
    decision = controller.snapshot()["decisions"][-1]
    assert decision["decision"] == ring_shadow.SHADOW_DECISION_OPEN_UNRESOLVED
    assert decision["reason"] == ring_shadow.SHADOW_REASON_LIVE_STATE_RESET
    assert decision["new_call_proven"] is False

    _ring(controller, ring_shadow.SHADOW_OWNER_LISTENER)
    repeat = controller.snapshot()["decisions"][-1]
    assert repeat["decision"] == ring_shadow.SHADOW_DECISION_SHADOW
    assert repeat["reason"] == ring_shadow.SHADOW_REASON_SAME_PROCESS_LISTENER


def test_listener_media_listener_real_handoffs_preserve_state_for_replay():
    controller = ring_shadow.RingShadowController()
    controller.note_state(ring_shadow.SHADOW_OWNER_LISTENER, "listener_start")
    _ring(controller, ring_shadow.SHADOW_OWNER_LISTENER)

    controller.note_state(ring_shadow.SHADOW_OWNER_LISTENER, "listener_stop")
    controller.note_state(ring_shadow.SHADOW_OWNER_MEDIA, "media_transport_start")
    _ring(controller, ring_shadow.SHADOW_OWNER_MEDIA)
    media_decision = controller.snapshot()["decisions"][-1]
    assert media_decision["decision"] == ring_shadow.SHADOW_DECISION_HANDOFF_REPLAY
    assert media_decision["reason"] == ring_shadow.SHADOW_REASON_HANDOFF_REPLAY

    controller.note_state(ring_shadow.SHADOW_OWNER_MEDIA, "media_transport_stop")
    controller.note_state(ring_shadow.SHADOW_OWNER_LISTENER, "supervisor_resume")
    controller.note_state(ring_shadow.SHADOW_OWNER_LISTENER, "listener_start")
    _ring(controller, ring_shadow.SHADOW_OWNER_LISTENER)
    listener_decision = controller.snapshot()["decisions"][-1]
    assert listener_decision["decision"] == ring_shadow.SHADOW_DECISION_HANDOFF_REPLAY
    assert listener_decision["reason"] == ring_shadow.SHADOW_REASON_HANDOFF_REPLAY


def test_cycle_restart_after_media_listener_handoff_stales_inactive_media_record():
    controller = ring_shadow.RingShadowController()
    controller.note_state(ring_shadow.SHADOW_OWNER_LISTENER, "listener_start")
    _ring(controller, ring_shadow.SHADOW_OWNER_LISTENER)
    controller.note_state(ring_shadow.SHADOW_OWNER_LISTENER, "listener_stop")
    controller.note_state(ring_shadow.SHADOW_OWNER_MEDIA, "media_transport_start")
    _ring(controller, ring_shadow.SHADOW_OWNER_MEDIA)
    _ring_key(controller, ring_shadow.SHADOW_OWNER_MEDIA, "gate", "00000610")

    controller.note_state(ring_shadow.SHADOW_OWNER_MEDIA, "media_transport_stop")
    controller.note_state(ring_shadow.SHADOW_OWNER_LISTENER, "supervisor_resume")
    controller.note_state(ring_shadow.SHADOW_OWNER_LISTENER, "listener_start")
    _ring(controller, ring_shadow.SHADOW_OWNER_LISTENER)
    handoff = controller.snapshot()["decisions"][-1]
    assert handoff["decision"] == ring_shadow.SHADOW_DECISION_HANDOFF_REPLAY

    controller.note_state(ring_shadow.SHADOW_OWNER_LISTENER, "listener_start")
    live = controller.snapshot()["guard"]["live"]
    assert {entry["reset_reason"] for entry in live} == {"owner_lifecycle_reset"}
    assert {
        entry["current_owner_kind"] for entry in live
    } == {ring_shadow.SHADOW_OWNER_LISTENER, ring_shadow.SHADOW_OWNER_MEDIA}


def test_seen_owner_generation_replay_does_not_bump_handoff_token_again():
    guard = ring_shadow.RingEmitGuard()
    guard.decide(
        door="entrance",
        source="00000643",
        owner=ring_shadow.SHADOW_OWNER_LISTENER,
        owner_generation=(ring_shadow.SHADOW_OWNER_LISTENER, 1),
    )
    first_media = guard.decide(
        door="entrance",
        source="00000643",
        owner=ring_shadow.SHADOW_OWNER_MEDIA,
        owner_generation=(ring_shadow.SHADOW_OWNER_MEDIA, 1),
    )
    repeat_media = guard.decide(
        door="entrance",
        source="00000643",
        owner=ring_shadow.SHADOW_OWNER_MEDIA,
        owner_generation=(ring_shadow.SHADOW_OWNER_MEDIA, 1),
    )

    assert first_media.decision == ring_shadow.SHADOW_DECISION_HANDOFF_REPLAY
    assert repeat_media.decision == ring_shadow.SHADOW_DECISION_SUPPRESS
    assert repeat_media.reason == ring_shadow.SHADOW_REASON_LIVE_CALL_REPLAY
    assert repeat_media.handoff_token == first_media.handoff_token


def test_reattach_is_once_and_record_tracks_recording_completed():
    guard = ring_shadow.RingEmitGuard()
    guard.decide(
        door="entrance",
        source="00000643",
        owner=ring_shadow.SHADOW_OWNER_LISTENER,
        owner_generation=(ring_shadow.SHADOW_OWNER_LISTENER, 1),
    )
    first = guard.decide(
        door="entrance",
        source="00000643",
        owner=ring_shadow.SHADOW_OWNER_LISTENER,
        owner_generation=(ring_shadow.SHADOW_OWNER_LISTENER, 2),
    )
    second = guard.decide(
        door="entrance",
        source="00000643",
        owner=ring_shadow.SHADOW_OWNER_LISTENER,
        owner_generation=(ring_shadow.SHADOW_OWNER_LISTENER, 3),
    )

    assert first.reattach is True
    assert first.record is True
    assert second.reattach is False
    assert second.record is True


def test_controller_high_a2_real_release_handoff_open_unresolved():
    controller = ring_shadow.RingShadowController()
    controller.note_state(ring_shadow.SHADOW_OWNER_LISTENER, "listener_start")
    _ring(controller, ring_shadow.SHADOW_OWNER_LISTENER)
    controller.observe_native_line(
        ring_shadow.SHADOW_OWNER_LISTENER,
        "R37_REMOTE_RELEASE_OBSERVED=true",
    )
    controller.note_state(ring_shadow.SHADOW_OWNER_LISTENER, "listener_stop")
    controller.note_state(ring_shadow.SHADOW_OWNER_MEDIA, "media_transport_start")
    _ring(controller, ring_shadow.SHADOW_OWNER_MEDIA)
    decision = controller.snapshot()["decisions"][-1]

    assert decision["decision"] == ring_shadow.SHADOW_DECISION_OPEN_UNRESOLVED
    assert decision["reason"] == ring_shadow.SHADOW_REASON_HIGH_A2


def test_controller_high_3_real_watchdog_boundary_open_unresolved():
    controller = ring_shadow.RingShadowController()
    controller.note_state(ring_shadow.SHADOW_OWNER_LISTENER, "listener_start")
    _ring(controller, ring_shadow.SHADOW_OWNER_LISTENER)
    controller.note_watchdog_boundary_crossed(ring_shadow.SHADOW_OWNER_LISTENER)
    controller.note_state(ring_shadow.SHADOW_OWNER_LISTENER, "listener_stop")
    controller.note_state(ring_shadow.SHADOW_OWNER_MEDIA, "media_transport_start")
    _ring(controller, ring_shadow.SHADOW_OWNER_MEDIA)
    decision = controller.snapshot()["decisions"][-1]

    assert decision["decision"] == ring_shadow.SHADOW_DECISION_OPEN_UNRESOLVED
    assert decision["reason"] == ring_shadow.SHADOW_REASON_HIGH_3


def test_t15_snapshot_view_is_bounded_and_sanitized():
    controller = ring_shadow.RingShadowController()
    controller.note_state(ring_shadow.SHADOW_OWNER_LISTENER, "listener_start")
    _ring(controller, ring_shadow.SHADOW_OWNER_LISTENER)
    view = controller.snapshot_view()
    rendered = repr(view)

    assert "00000643" not in rendered
    assert "V4_RING_SOURCE" not in rendered
    assert view["live_state"]["count"] == 1
    assert view["live_state"]["door_kind"] == ("entrance",)
    assert len(view["shadow_classification"]) <= ring_shadow.SHADOW_MAX_DECISIONS


def test_t17_removed_media_closed_route_vocabulary_absent():
    assert not hasattr(ring_shadow, "SHADOW_REASON_SAME_PROCESS_MEDIA_CLOSED_ROUTE")
    assert not hasattr(ring_shadow, "SHADOW_REASON_SAME_PROCESS_MEDIA_NOT_ORIGIN")
    assert not hasattr(ring_shadow, "SHADOW_DECISION_REATTACH")


def test_reason_and_decision_vocabulary_fully_reachable():
    decisions = set()
    reasons = set()

    emitted = ring_shadow.RingEmitGuard().decide(
        door="entrance",
        source="00000643",
        owner=ring_shadow.SHADOW_OWNER_LISTENER,
        owner_generation=(ring_shadow.SHADOW_OWNER_LISTENER, 1),
        production_emit_allowed=True,
        has_new_physical_call_discriminator=True,
    )
    decisions.add(emitted.decision)
    reasons.add(emitted.reason)

    guard = ring_shadow.RingEmitGuard()
    scenarios = (
        guard.decide(
            door="entrance",
            source=None,
            owner=ring_shadow.SHADOW_OWNER_LISTENER,
            owner_generation=(ring_shadow.SHADOW_OWNER_LISTENER, 1),
        ),
        guard.decide(
            door="entrance",
            source="00000643",
            owner=ring_shadow.SHADOW_OWNER_LISTENER,
            owner_generation=(ring_shadow.SHADOW_OWNER_LISTENER, 1),
        ),
        guard.decide(
            door="entrance",
            source="00000643",
            owner=ring_shadow.SHADOW_OWNER_LISTENER,
            owner_generation=(ring_shadow.SHADOW_OWNER_LISTENER, 1),
        ),
        guard.decide(
            door="entrance",
            source="00000643",
            owner=ring_shadow.SHADOW_OWNER_MEDIA,
            owner_generation=(ring_shadow.SHADOW_OWNER_MEDIA, 1),
        ),
    )
    for decision in scenarios:
        decisions.add(decision.decision)
        reasons.add(decision.reason)

    replay_guard = ring_shadow.RingEmitGuard()
    replay_guard.decide(
        door="entrance",
        source="00000643",
        owner=ring_shadow.SHADOW_OWNER_LISTENER,
        owner_generation=(ring_shadow.SHADOW_OWNER_LISTENER, 1),
    )
    replay = replay_guard.decide(
        door="entrance",
        source="00000643",
        owner=ring_shadow.SHADOW_OWNER_LISTENER,
        owner_generation=(ring_shadow.SHADOW_OWNER_LISTENER, 2),
    )
    decisions.add(replay.decision)
    reasons.add(replay.reason)

    media_guard = ring_shadow.RingEmitGuard()
    media_guard.decide(
        door="entrance",
        source="00000643",
        owner=ring_shadow.SHADOW_OWNER_MEDIA,
        owner_generation=(ring_shadow.SHADOW_OWNER_MEDIA, 1),
    )
    media_same = media_guard.decide(
        door="entrance",
        source="00000643",
        owner=ring_shadow.SHADOW_OWNER_MEDIA,
        owner_generation=(ring_shadow.SHADOW_OWNER_MEDIA, 1),
    )
    decisions.add(media_same.decision)
    reasons.add(media_same.reason)

    high_a2 = ring_shadow.RingEmitGuard()
    high_a2.decide(
        door="entrance",
        source="00000643",
        owner=ring_shadow.SHADOW_OWNER_LISTENER,
        owner_generation=(ring_shadow.SHADOW_OWNER_LISTENER, 1),
    )
    high_a2.observe_interaction(ring_shadow.SHADOW_OWNER_LISTENER)
    high_a2_decision = high_a2.decide(
        door="entrance",
        source="00000643",
        owner=ring_shadow.SHADOW_OWNER_LISTENER,
        owner_generation=(ring_shadow.SHADOW_OWNER_LISTENER, 2),
    )
    decisions.add(high_a2_decision.decision)
    reasons.add(high_a2_decision.reason)

    high_3 = ring_shadow.RingEmitGuard()
    high_3.decide(
        door="entrance",
        source="00000643",
        owner=ring_shadow.SHADOW_OWNER_LISTENER,
        owner_generation=(ring_shadow.SHADOW_OWNER_LISTENER, 1),
    )
    high_3_decision = high_3.decide(
        door="entrance",
        source="00000643",
        owner=ring_shadow.SHADOW_OWNER_LISTENER,
        owner_generation=(ring_shadow.SHADOW_OWNER_LISTENER, 2),
        watchdog_boundary_crossed=True,
    )
    decisions.add(high_3_decision.decision)
    reasons.add(high_3_decision.reason)

    controller = ring_shadow.RingShadowController()
    for line in (
        "V4_RING_OBSERVED=true",
        "V4_RING_DIRECTION=DEVICE_TO_CLIENT",
        "V4_RING_KIND=CALL_INIT",
        "V4_RING_DOOR=bad",
        "V4_RING_SOURCE=bad",
    ):
        controller.observe_native_line(ring_shadow.SHADOW_OWNER_LISTENER, line)
    controller.note_state(ring_shadow.SHADOW_OWNER_LISTENER, "listener_start")
    _ring(controller, ring_shadow.SHADOW_OWNER_LISTENER)
    controller.note_state(ring_shadow.SHADOW_OWNER_LISTENER, "listener_start")
    _ring(controller, ring_shadow.SHADOW_OWNER_LISTENER)
    snapshot = controller.snapshot()
    for decision in snapshot["decisions"]:
        decisions.add(decision["decision"])
        reasons.add(decision["reason"])
    for decision in snapshot["guard"]["decisions"]:
        decisions.add(decision["decision"])
        reasons.add(decision["reason"])

    assert decisions == _decision_constants()
    assert reasons == _reason_constants()
