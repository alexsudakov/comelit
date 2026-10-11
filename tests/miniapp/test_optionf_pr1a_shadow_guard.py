from __future__ import annotations

import ast
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests" / "miniapp" / "tools"))
from optionf_pr1a_replay import load_plain_module

ring_shadow = load_plain_module(
    str(ROOT), "custom_components/comelit/ring_shadow.py", "ring_shadow"
)
SHADOW_PATH = ROOT / "custom_components" / "comelit" / "ring_shadow.py"


def _import_roots_and_calls():
    tree = ast.parse(SHADOW_PATH.read_text(encoding="utf-8"))
    imports: set[str] = set()
    calls: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module.split(".")[0])
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                calls.add(func.id)
            elif isinstance(func, ast.Attribute):
                calls.add(func.attr)
    return imports, calls


def test_full_frame_sha_not_used_for_cross_owner_identity():
    guard = ring_shadow.RingEmitGuard()
    first = guard.decide(
        door="entrance",
        source="00000643",
        owner=ring_shadow.SHADOW_OWNER_LISTENER,
        generation=1,
    )
    second = guard.decide(
        door="entrance",
        source="00000643",
        owner=ring_shadow.SHADOW_OWNER_LISTENER,
        generation=2,
    )
    imports, calls = _import_roots_and_calls()

    assert first.reason == ring_shadow.SHADOW_REASON_NO_LIVE_CALL
    assert second.reason == ring_shadow.SHADOW_REASON_LIVE_CALL_REPLAY
    assert "hashlib" not in imports
    assert "sha256" not in calls


def test_wall_clock_not_used_as_call_identity():
    imports, calls = _import_roots_and_calls()
    assert not ({"time", "datetime", "uuid"} & imports)
    assert "monotonic" not in calls


def test_high_a2_path_shadow_open_unresolved_no_production_event():
    guard = ring_shadow.RingEmitGuard()
    guard.decide(
        door="entrance",
        source="00000643",
        owner=ring_shadow.SHADOW_OWNER_LISTENER,
        generation=1,
        interaction_seen=True,
    )
    decision = guard.decide(
        door="entrance",
        source="00000643",
        owner=ring_shadow.SHADOW_OWNER_LISTENER,
        generation=2,
        interaction_seen=True,
    )
    assert decision.decision == ring_shadow.SHADOW_DECISION_OPEN_UNRESOLVED
    assert decision.reason == ring_shadow.SHADOW_REASON_HIGH_A2
    assert decision.production_effect is False


def test_high_3_path_shadow_open_unresolved_no_production_event():
    guard = ring_shadow.RingEmitGuard()
    guard.decide(
        door="entrance",
        source="00000643",
        owner=ring_shadow.SHADOW_OWNER_LISTENER,
        generation=1,
    )
    decision = guard.decide(
        door="entrance",
        source="00000643",
        owner=ring_shadow.SHADOW_OWNER_LISTENER,
        generation=2,
        watchdog_expired_without_lifecycle_evidence=True,
    )
    assert decision.decision == ring_shadow.SHADOW_DECISION_OPEN_UNRESOLVED
    assert decision.reason == ring_shadow.SHADOW_REASON_HIGH_3
    assert decision.production_effect is False


def test_guard_key_is_door_source_tuple():
    guard = ring_shadow.RingEmitGuard()
    first = guard.decide(
        door="entrance",
        source="00000643",
        owner=ring_shadow.SHADOW_OWNER_LISTENER,
        generation=1,
    )
    other_source = guard.decide(
        door="entrance",
        source="00000610",
        owner=ring_shadow.SHADOW_OWNER_LISTENER,
        generation=1,
    )
    assert first.reason == ring_shadow.SHADOW_REASON_NO_LIVE_CALL
    assert other_source.reason == ring_shadow.SHADOW_REASON_NO_LIVE_CALL


def test_production_emit_disabled_in_pr1a():
    guard = ring_shadow.RingEmitGuard()
    decision = guard.decide(
        door="entrance",
        source="00000643",
        owner=ring_shadow.SHADOW_OWNER_LISTENER,
        generation=1,
        production_emit_allowed=False,
    )
    assert decision.decision == ring_shadow.SHADOW_DECISION_SHADOW
    assert decision.production_effect is False


def test_missing_source_is_fail_closed_shadow():
    guard = ring_shadow.RingEmitGuard()
    decision = guard.decide(
        door="entrance",
        source=None,
        owner=ring_shadow.SHADOW_OWNER_LISTENER,
        generation=1,
    )
    assert decision.decision == ring_shadow.SHADOW_DECISION_SHADOW
    assert decision.reason == ring_shadow.SHADOW_REASON_INCOMPLETE
    assert decision.missing_identity is True
