from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests" / "miniapp" / "tools"))
from optionf_pr1a_replay import load_plain_module


ring_shadow = load_plain_module(
    str(ROOT), "custom_components/comelit/ring_shadow.py", "ring_shadow"
)


def _ring(controller, owner: str) -> None:
    for line in (
        "V4_RING_PHASE=INITIAL",
        "V4_RING_PEER_CONNECTION=000a",
        "V4_RING_BODY_32_35=1234abcd",
        "V4_RING_PARSE_STATUS=OK",
        "V4_RING_OBSERVED=true",
        "V4_RING_DIRECTION=DEVICE_TO_CLIENT",
        "V4_RING_KIND=CALL_INIT",
        "V4_RING_DOOR=entrance",
        "V4_RING_SOURCE=00000643",
    ):
        controller.observe_native_line(owner, line)


def test_issue319_qualification_is_explicitly_fail_closed() -> None:
    controller = ring_shadow.RingShadowController()
    view = controller.snapshot_view()

    assert view["qualification"] == {
        "independent_native_call_identity_proven": False,
        "production_emit_gate_proven": False,
        "production_effect_enabled": False,
        "functional_acceptance": "BLOCKED_NOT_FIXED",
        "body_32_35_semantics": "UNKNOWN",
        "body_32_35_live_verified": False,
    }


def test_issue319_media_call_init_remains_diagnostic_only() -> None:
    controller = ring_shadow.RingShadowController()
    controller.note_state(ring_shadow.SHADOW_OWNER_MEDIA, "media_transport_start")
    _ring(controller, ring_shadow.SHADOW_OWNER_MEDIA)

    decision = controller.snapshot()["decisions"][-1]
    assert decision["owner"] == ring_shadow.SHADOW_OWNER_MEDIA
    assert decision["decision"] == ring_shadow.SHADOW_DECISION_SHADOW
    assert decision["production_effect"] is False
    assert decision["new_call_proven"] is False


def test_issue319_real_watchdog_hook_marks_unresolved_boundary() -> None:
    controller = ring_shadow.RingShadowController()
    controller.note_state(ring_shadow.SHADOW_OWNER_LISTENER, "listener_start")
    _ring(controller, ring_shadow.SHADOW_OWNER_LISTENER)

    hook = ring_shadow.RingShadowHook(
        controller, ring_shadow.SHADOW_OWNER_LISTENER
    )
    hook.note_watchdog_boundary_crossed()
    controller.note_state(ring_shadow.SHADOW_OWNER_MEDIA, "media_transport_start")
    _ring(controller, ring_shadow.SHADOW_OWNER_MEDIA)

    decision = controller.snapshot()["decisions"][-1]
    assert decision["decision"] == ring_shadow.SHADOW_DECISION_OPEN_UNRESOLVED
    assert decision["reason"] == ring_shadow.SHADOW_REASON_HIGH_3
    assert decision["production_effect"] is False


def test_issue319_runtime_timeout_wires_shadow_boundary_before_failure() -> None:
    source = (ROOT / "custom_components/comelit/runtime.py").read_text(
        encoding="utf-8"
    )
    start = source.index("    async def _async_expire_call_state(")
    end = source.index("\n    def call_status(", start)
    method = source[start:end]

    boundary = "shadow_hook.note_watchdog_boundary_crossed()"
    failure = 'self._call_state_tracker().fail_active("call_state_timeout")'
    assert method.count(boundary) == 1
    assert method.count(failure) == 1
    assert method.index(boundary) < method.index(failure)
