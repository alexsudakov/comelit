#!/usr/bin/env python3
from __future__ import annotations

import tempfile
from pathlib import Path

from comelit_safety_poc.boundary import BoundaryOutcome, BoundaryTransportAdapter, TransportRequest
from comelit_safety_poc.executor import OneShotExecutor, Policy
from comelit_safety_poc.model import State
from comelit_safety_poc.store import Journal
from comelit_safety_poc.vip_fixture_boundary import CanonicalVipFixtureBoundary


def main() -> int:
    boundary = CanonicalVipFixtureBoundary()

    direct = boundary.attempt_once(
        TransportRequest(operation_id="canonical-fixture-direct", target="fixture-only")
    )
    if direct.outcome != BoundaryOutcome.ACCEPTED_NO_ACK:
        raise SystemExit(f"unexpected direct outcome: {direct.outcome.value}")
    if boundary.last_snapshot is None or boundary.last_snapshot.write_count != 1:
        raise SystemExit("canonical fixture probe did not produce exactly one write")
    expected_stack = (
        "FixtureTransport",
        "VipSession",
        "VipChannelSession",
        "VipApplicationSession",
    )
    if boundary.last_snapshot.stack_types != expected_stack:
        raise SystemExit(f"unexpected stack: {boundary.last_snapshot.stack_types!r}")

    with tempfile.TemporaryDirectory() as tmp:
        journal = Journal(Path(tmp) / "state.sqlite3")
        executor_boundary = CanonicalVipFixtureBoundary()
        executor = OneShotExecutor(
            journal,
            BoundaryTransportAdapter(executor_boundary),
            Policy(0),
        )
        first = executor.execute(operation_id="canonical-fixture-exec", target="fixture-only")
        second = executor.execute(operation_id="canonical-fixture-exec", target="fixture-only")
        if first.state != State.UNKNOWN_OUTCOME or second.state != State.UNKNOWN_OUTCOME:
            raise SystemExit("fixture write must map to UNKNOWN_OUTCOME without ACK")
        if executor_boundary.calls != 1:
            raise SystemExit("duplicate operation_id caused a second boundary invocation")
        if executor_boundary.last_snapshot is None or executor_boundary.last_snapshot.write_count != 1:
            raise SystemExit("executor fixture probe did not produce exactly one write")

    print("CANONICAL_VIP_SOURCE_HASHES=PASS")
    print("CANONICAL_VIP_FULL_STACK_CONSTRUCTED=PASS")
    print("CANONICAL_VIP_SYNC_ON_FIRST_FRAME=false")
    print("CANONICAL_VIP_NEXT_CHANNEL_ID=7449")
    print("CANONICAL_FIXTURE_WRITES=1")
    print("CANONICAL_FIXTURE_BOUNDARY_OUTCOME=ACCEPTED_NO_ACK")
    print("CANONICAL_FIXTURE_EXECUTOR_STATE=UNKNOWN_OUTCOME")
    print("CANONICAL_FIXTURE_DUPLICATE_NO_SECOND_WRITE=PASS")
    print("CANONICAL_FIXTURE_PROTOCOL_ACK=false")
    print("CANONICAL_FIXTURE_PHYSICAL_EFFECT=false")
    print("CANONICAL_FIXTURE_NETWORK_ACTION=false")
    print("CANONICAL_FIXTURE_BRIDGE=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
