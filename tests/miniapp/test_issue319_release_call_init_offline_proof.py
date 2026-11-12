from __future__ import annotations

from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests" / "miniapp" / "tools"))
from optionf_pr1a_replay import load_plain_module


ring_shadow = load_plain_module(
    str(ROOT), "custom_components/comelit/ring_shadow.py", "ring_shadow_release_proof"
)

LISTENER = ring_shadow.SHADOW_OWNER_LISTENER
MEDIA = ring_shadow.SHADOW_OWNER_MEDIA


def _decide(guard, owner, generation, **kwargs):
    return guard.decide(
        door="entrance",
        source="00000643",
        owner=owner,
        owner_generation=(owner, generation),
        **kwargs,
    )


def _batch(door="entrance", source="00000643", direction="DEVICE_TO_CLIENT"):
    return (
        "V4_RING_OBSERVED=true",
        f"V4_RING_DIRECTION={direction}",
        "V4_RING_KIND=CALL_INIT",
        f"V4_RING_DOOR={door}",
        f"V4_RING_SOURCE={source}",
    )


def _feed(controller, owner, lines):
    for line in lines:
        controller.observe_native_line(owner, line)


def _decisions(controller):
    return controller.snapshot()["decisions"]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


# Scenario 1: RELEASE -> CALL_INIT while old media completion is in flight.
def test_release_then_call_init_never_emits_without_call_identity() -> None:
    # Official-app PCAP: panel RELEASE precedes the new CALL_INIT while the old
    # media STOP is still in flight. Even with the emit flag, no discriminator
    # means no production effect.
    guard = ring_shadow.RingEmitGuard()
    guard.observe_interaction(MEDIA)
    decision = _decide(guard, MEDIA, 1, production_emit_allowed=True)
    assert decision.decision == ring_shadow.SHADOW_DECISION_SHADOW
    assert decision.production_effect is False
    assert decision.new_call_proven is False


def test_controller_release_line_between_call_inits_never_emits() -> None:
    controller = ring_shadow.RingShadowController()
    controller.note_state(MEDIA, "media_transport_start")
    _feed(controller, MEDIA, _batch())
    _feed(controller, MEDIA, ("R37_REMOTE_RELEASE_OBSERVED=true",))
    _feed(controller, MEDIA, _batch())
    decisions = _decisions(controller)
    assert len(decisions) == 2
    for decision in decisions:
        assert decision["decision"] != ring_shadow.SHADOW_DECISION_EMIT
        assert decision["production_effect"] is False
        assert decision["new_call_proven"] is False


# Scenario 2: CALL_INIT with an outstanding refresh (no answer yet).
def test_call_init_with_outstanding_refresh_stays_shadow() -> None:
    controller = ring_shadow.RingShadowController()
    controller.note_state(MEDIA, "media_transport_start")
    controller.observe_native_line(MEDIA, "P80_MEDIA_ACTIVE=true")
    controller.observe_native_line(MEDIA, "P80_VIDEO_RTP_PACKETS=5")
    # Refresh response markers are not Ring batch keys: they must neither
    # complete nor corrupt a Ring batch and carry no call identity.
    lines = list(_batch())
    lines.insert(2, "SECOND_001A_RESPONSE=DEFERRED")
    _feed(controller, MEDIA, lines)
    decision = _decisions(controller)[-1]
    assert decision["decision"] == ring_shadow.SHADOW_DECISION_SHADOW
    assert decision["reason"] == ring_shadow.SHADOW_REASON_NO_LIVE_CALL
    assert decision["production_effect"] is False
    assert decision["new_call_proven"] is False


# Scenario 3: malformed / absent identity batches fail closed.
def test_malformed_batch_variants_fail_closed() -> None:
    variants = (
        _batch(door="gate", source="00000643"),
        _batch(door="entrance", source="00000610"),
        _batch(source="deadbeef"),
        _batch(direction="CLIENT_TO_DEVICE"),
    )
    for lines in variants:
        controller = ring_shadow.RingShadowController()
        controller.note_state(MEDIA, "media_transport_start")
        _feed(controller, MEDIA, lines)
        decision = _decisions(controller)[-1]
        assert decision["decision"] == ring_shadow.SHADOW_DECISION_SHADOW
        assert decision["reason"] == ring_shadow.SHADOW_REASON_MALFORMED
        assert decision["production_effect"] is False


def test_malformed_and_absent_identity_batches_fail_closed() -> None:
    controller = ring_shadow.RingShadowController()
    controller.note_state(MEDIA, "media_transport_start")
    for line in (
        "V4_RING_OBSERVED=true",
        "V4_RING_DIRECTION=DEVICE_TO_CLIENT",
        "V4_RING_KIND=CALL_INIT",
        "V4_RING_DOOR=gate",
        "V4_RING_SOURCE=00000643",
    ):
        controller.observe_native_line(MEDIA, line)
    decision = controller.snapshot()["decisions"][-1]
    assert decision["decision"] == ring_shadow.SHADOW_DECISION_SHADOW
    assert decision["reason"] == ring_shadow.SHADOW_REASON_MALFORMED
    assert decision["production_effect"] is False


def test_retransmit_marker_without_prior_identity_fails_closed() -> None:
    controller = ring_shadow.RingShadowController()
    controller.note_state(MEDIA, "media_transport_start")
    controller.observe_native_line(MEDIA, "V4_RING_RETRANSMIT_SUPPRESSED=true")
    decision = _decisions(controller)[-1]
    assert decision["decision"] == ring_shadow.SHADOW_DECISION_SHADOW
    assert decision["reason"] == ring_shadow.SHADOW_REASON_INCOMPLETE
    assert decision["production_effect"] is False


def test_incomplete_identity_never_emits_even_when_allowed() -> None:
    guard = ring_shadow.RingEmitGuard()
    decision = guard.decide(
        door=None,
        source=None,
        owner=MEDIA,
        owner_generation=(MEDIA, 1),
        has_new_physical_call_discriminator=True,
        production_emit_allowed=True,
    )
    assert decision.decision == ring_shadow.SHADOW_DECISION_SHADOW
    assert decision.reason == ring_shadow.SHADOW_REASON_INCOMPLETE
    assert decision.production_effect is False


# Scenario 4: retransmit of one call.
def test_retransmit_of_one_call_is_suppressed_not_emitted() -> None:
    guard = ring_shadow.RingEmitGuard()
    _decide(guard, LISTENER, 1)
    decision = _decide(guard, LISTENER, 1, retransmit=True)
    assert decision.decision == ring_shadow.SHADOW_DECISION_SUPPRESS
    assert decision.reason == ring_shadow.SHADOW_REASON_LIVE_CALL_REPLAY
    assert decision.production_effect is False


def test_controller_retransmit_marker_is_suppressed() -> None:
    controller = ring_shadow.RingShadowController()
    controller.note_state(MEDIA, "media_transport_start")
    _feed(controller, MEDIA, _batch())
    controller.observe_native_line(MEDIA, "V4_RING_RETRANSMIT_SUPPRESSED=true")
    decision = _decisions(controller)[-1]
    assert decision["decision"] == ring_shadow.SHADOW_DECISION_SUPPRESS
    assert decision["reason"] == ring_shadow.SHADOW_REASON_LIVE_CALL_REPLAY
    assert decision["production_effect"] is False


# Scenario 5: two sequential distinct calls from one panel.
def test_sequential_calls_in_listener_generation_are_not_suppressed() -> None:
    guard = ring_shadow.RingEmitGuard()
    _decide(guard, LISTENER, 1)
    second = _decide(guard, LISTENER, 1)
    assert second.decision != ring_shadow.SHADOW_DECISION_SUPPRESS
    assert second.reason == ring_shadow.SHADOW_REASON_SAME_PROCESS_LISTENER


def test_sequential_listener_calls_do_not_emit_without_emit_gate() -> None:
    guard = ring_shadow.RingEmitGuard()
    _decide(guard, LISTENER, 1)
    second = _decide(guard, LISTENER, 1)
    assert second.decision == ring_shadow.SHADOW_DECISION_SHADOW
    assert second.production_effect is False
    assert second.new_call_proven is False


# Required extra: two DIFFERENT physical calls inside one media generation.
def test_media_owner_second_call_init_is_pinned_as_unproven_gap() -> None:
    # A second distinct CALL_INIT inside one media-owner generation is treated
    # as retransmit by the shadow model. That is exactly why production emit
    # cannot be enabled: identity is NOT_PROVEN. Pin the gap, do not hide it.
    guard = ring_shadow.RingEmitGuard()
    _decide(guard, MEDIA, 1)
    second = _decide(guard, MEDIA, 1)
    assert second.decision == ring_shadow.SHADOW_DECISION_SUPPRESS
    assert second.reason == ring_shadow.SHADOW_REASON_SAME_PROCESS_MEDIA_RETRANSMIT
    assert ring_shadow.INDEPENDENT_NATIVE_CALL_IDENTITY_PROVEN is False
    assert ring_shadow.PRODUCTION_EMIT_GATE_PROVEN is False


def test_media_generation_differing_frame_sha_is_not_call_identity() -> None:
    controller = ring_shadow.RingShadowController()
    controller.note_state(MEDIA, "media_transport_start")
    controller.observe_native_line(MEDIA, "V4_RING_FRAME_SHA256=" + "a" * 64)
    _feed(controller, MEDIA, _batch())
    controller.observe_native_line(MEDIA, "V4_RING_FRAME_SHA256=" + "b" * 64)
    _feed(controller, MEDIA, _batch())
    first, second = _decisions(controller)[-2:]
    assert first["decision"] == ring_shadow.SHADOW_DECISION_SHADOW
    assert second["decision"] == ring_shadow.SHADOW_DECISION_SUPPRESS
    assert second["reason"] == ring_shadow.SHADOW_REASON_SAME_PROCESS_MEDIA_RETRANSMIT
    assert second["new_call_proven"] is False
    assert ring_shadow.FULL_FRAME_SHA_USED_AS_CALL_IDENTITY is False
    assert ring_shadow.V4_RING_BODY_32_35_SEMANTICS == "UNKNOWN"
    assert ring_shadow.V4_RING_BODY_32_35_LIVE_VERIFIED is False


# Scenario 6: owner generation change.
def test_owner_generation_change_is_never_proof_of_new_call() -> None:
    guard = ring_shadow.RingEmitGuard()
    _decide(guard, LISTENER, 1)
    guard.note_owner_handoff(MEDIA, (MEDIA, 1))
    decision = _decide(guard, MEDIA, 1)
    assert decision.decision == ring_shadow.SHADOW_DECISION_HANDOFF_REPLAY
    assert decision.new_call_proven is False
    assert decision.production_effect is False
    assert ring_shadow.OWNER_GENERATION_IS_CALL_IDENTITY is False
    assert ring_shadow.HANDOFF_EPOCH_IS_CALL_IDENTITY is False


def test_new_media_generation_after_listener_never_emits() -> None:
    controller = ring_shadow.RingShadowController()
    controller.note_state(LISTENER, "listener_start")
    _feed(controller, LISTENER, _batch())
    controller.note_state(MEDIA, "media_transport_start")
    _feed(controller, MEDIA, _batch())
    for decision in _decisions(controller):
        assert decision["decision"] != ring_shadow.SHADOW_DECISION_EMIT
        assert decision["production_effect"] is False
        assert decision["new_call_proven"] is False


# Scenario 7: single writer / no second upstream owner.
def test_single_media_owner_running_at_a_time() -> None:
    controller = ring_shadow.RingShadowController()
    controller.note_state(LISTENER, "listener_start")
    controller.note_state(MEDIA, "media_transport_start")
    running = controller.snapshot()["owner_running"]
    assert running == {LISTENER: False, MEDIA: True}
    controller.note_state(MEDIA, "media_transport_stop")
    controller.note_state(LISTENER, "listener_start")
    running = controller.snapshot()["owner_running"]
    assert running == {LISTENER: True, MEDIA: False}


def test_shadow_module_has_only_two_owner_kinds() -> None:
    owners = {
        name: value
        for name, value in vars(ring_shadow).items()
        if name.startswith("SHADOW_OWNER_")
    }
    assert set(owners.values()) == {LISTENER, MEDIA}


# Scenario 9: call-state timeout 120 s and media hard limit 600 s (source pins).
def test_call_state_timeout_and_media_hard_limit_are_pinned() -> None:
    runtime = _read("custom_components/comelit/runtime.py")
    assert re.search(r"^_CALL_STATE_TIMEOUT_SECONDS = 120\.0$", runtime, re.M)
    const = _read("custom_components/comelit/const.py")
    assert re.search(r"^RING_MEDIA_HARD_LIMIT_SECONDS = 600$", const, re.M)
    session = _read("custom_components/comelit/media_session.py")
    assert re.search(r"^MEDIA_SESSION_HARD_LIMIT_SECONDS = 600$", session, re.M)


def test_watchdog_boundary_yields_unresolved_never_emit() -> None:
    guard = ring_shadow.RingEmitGuard()
    _decide(guard, LISTENER, 1)
    guard.note_watchdog_boundary_crossed(LISTENER)
    guard.note_owner_handoff(MEDIA, (MEDIA, 1))
    decision = _decide(guard, MEDIA, 1)
    assert decision.decision == ring_shadow.SHADOW_DECISION_OPEN_UNRESOLVED
    assert decision.decision != ring_shadow.SHADOW_DECISION_EMIT
    assert decision.production_effect is False
    assert decision.new_call_proven is False


# Scenario 10: Door/Gate non-retry and fail-closed.
def test_gate_batches_never_retry_or_emit() -> None:
    controller = ring_shadow.RingShadowController()
    controller.note_state(MEDIA, "media_transport_start")
    _feed(controller, MEDIA, _batch(door="gate", source="00000610"))
    _feed(controller, MEDIA, _batch(door="gate", source="00000610"))
    decisions = _decisions(controller)
    assert len(decisions) == 2
    for decision in decisions:
        assert decision["decision"] != ring_shadow.SHADOW_DECISION_EMIT
        assert decision["production_effect"] is False


def test_guard_decisions_never_request_terminal_retry() -> None:
    guard = ring_shadow.RingEmitGuard()
    for door, source in (("entrance", "00000643"), ("gate", "00000610")):
        for retransmit in (False, True):
            decision = guard.decide(
                door=door,
                source=source,
                owner=MEDIA,
                owner_generation=(MEDIA, 1),
                retransmit=retransmit,
                production_emit_allowed=True,
            )
            assert decision.terminal_retry is False
            assert decision.production_effect is False


def test_guard_never_enables_production_effect_or_tx() -> None:
    source = _read("custom_components/comelit/ring_shadow.py")
    assert "production_effect=False" in source
    assert "production_emit_allowed=False" in source
    assert "production_effect=True" not in source


def test_p0_status_remains_not_fixed() -> None:
    assert ring_shadow.P0_A_STATUS == "NOT_FIXED"
    assert ring_shadow.P0_B_STATUS == "NOT_FIXED"
    assert ring_shadow.P0_A_PROOF == "NOT_PROVEN"
    assert ring_shadow.P0_B_PROOF == "NOT_PROVEN"
    assert ring_shadow.P0_FUNCTIONAL_ACCEPTANCE == "BLOCKED_NOT_FIXED"
