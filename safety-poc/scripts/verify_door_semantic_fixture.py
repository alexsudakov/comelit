#!/usr/bin/env python3
from __future__ import annotations

import tempfile
from pathlib import Path

from comelit_safety_poc.boundary import BoundaryOutcome, BoundaryTransportAdapter, TransportRequest
from comelit_safety_poc.door_semantics import CanonicalDoorSemanticFixtureBoundary, DoorSemanticPlan
from comelit_safety_poc.executor import OneShotExecutor, Policy
from comelit_safety_poc.model import State
from comelit_safety_poc.store import Journal


def main() -> int:
    plan = DoorSemanticPlan()
    if len(plan.steps) != 9 or len(plan.write_steps) != 6 or len(plan.optional_wait_steps) != 2:
        raise SystemExit("unexpected semantic plan shape")

    boundary = CanonicalDoorSemanticFixtureBoundary()
    direct = boundary.attempt_once(
        TransportRequest(operation_id="semantic-direct", target="fixture-only")
    )
    if direct.outcome != BoundaryOutcome.ACCEPTED_NO_ACK:
        raise SystemExit(f"unexpected direct outcome: {direct.outcome.value}")
    snap = boundary.last_snapshot
    if snap is None or snap.write_count != 6:
        raise SystemExit("semantic fixture plan did not produce six writes")
    if snap.channel_open_executed:
        raise SystemExit("v0.4 must not execute canonical channel open")
    if snap.protocol_ack_observed or snap.physical_effect_asserted:
        raise SystemExit("v0.4 must not claim ACK or physical effect")

    partial = CanonicalDoorSemanticFixtureBoundary(fail_after_write_index=3)
    partial_evidence = partial.attempt_once(
        TransportRequest(operation_id="semantic-partial", target="fixture-only")
    )
    if partial_evidence.outcome != BoundaryOutcome.AMBIGUOUS:
        raise SystemExit("partial semantic emission must be ambiguous")
    if partial.last_snapshot is None or partial.last_snapshot.write_count != 3:
        raise SystemExit("partial fault did not stop after three writes")

    with tempfile.TemporaryDirectory() as tmp:
        journal = Journal(Path(tmp) / "state.sqlite3")
        exec_boundary = CanonicalDoorSemanticFixtureBoundary()
        executor = OneShotExecutor(journal, BoundaryTransportAdapter(exec_boundary), Policy(0))
        first = executor.execute(operation_id="semantic-exec", target="fixture-only")
        second = executor.execute(operation_id="semantic-exec", target="fixture-only")
        if first.state != State.UNKNOWN_OUTCOME or second.state != State.UNKNOWN_OUTCOME:
            raise SystemExit("complete semantic fixture emission must map to UNKNOWN_OUTCOME")
        if exec_boundary.calls != 1:
            raise SystemExit("duplicate operation_id caused a second semantic boundary invocation")
        if exec_boundary.last_snapshot is None or exec_boundary.last_snapshot.write_count != 6:
            raise SystemExit("executor semantic plan did not produce exactly six writes")

    print("DOOR_SEMANTIC_PLAN_STEPS=9")
    print("DOOR_SEMANTIC_WRITE_STEPS=6")
    print("DOOR_SEMANTIC_OPTIONAL_WAITS=2")
    print("DOOR_SEMANTIC_CHANNEL_NAME=CTPP")
    print("DOOR_SEMANTIC_CHANNEL_OPEN_EXECUTED=false")
    print("DOOR_SEMANTIC_FIXTURE_WRITES=6")
    print("DOOR_SEMANTIC_PARTIAL_WRITE_OUTCOME=AMBIGUOUS")
    print("DOOR_SEMANTIC_BOUNDARY_OUTCOME=ACCEPTED_NO_ACK")
    print("DOOR_SEMANTIC_EXECUTOR_STATE=UNKNOWN_OUTCOME")
    print("DOOR_SEMANTIC_DUPLICATE_NO_SECOND_PLAN=PASS")
    print("DOOR_SEMANTIC_PROTOCOL_ACK=false")
    print("DOOR_SEMANTIC_PHYSICAL_EFFECT=false")
    print("DOOR_SEMANTIC_REAL_PAYLOAD_PRESENT=false")
    print("DOOR_SEMANTIC_NETWORK_ACTION=false")
    print("DOOR_SEMANTIC_FIXTURE_GATE=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
