#!/usr/bin/env python3
from __future__ import annotations

import tempfile
from pathlib import Path

from comelit_safety_poc.boundary import BoundaryOutcome, BoundaryTransportAdapter, TransportRequest
from comelit_safety_poc.executor import OneShotExecutor, Policy
from comelit_safety_poc.model import State
from comelit_safety_poc.store import Journal
from comelit_safety_poc.wire_reconciliation import CanonicalDoorWireFixtureBoundary


def main() -> int:
    boundary = CanonicalDoorWireFixtureBoundary()
    direct = boundary.attempt_once(
        TransportRequest(operation_id="wire-direct", target="synthetic-fixture-only")
    )
    if direct.outcome != BoundaryOutcome.ACCEPTED_NO_ACK:
        raise SystemExit(f"unexpected wire outcome: {direct.outcome.value}")
    snap = boundary.last_snapshot
    if snap is None:
        raise SystemExit("wire reconciliation snapshot missing")
    if snap.write_count != 6 or snap.frame_equivalence_count != 6:
        raise SystemExit("wire reconciliation did not prove six frames")
    if snap.request_ids != (7449,) * 6:
        raise SystemExit("wire reconciliation did not use one CTPP channel id")
    if not snap.byte_exact_equal or snap.header_bytes != 8:
        raise SystemExit("legacy/canonical framing equivalence failed")
    if not snap.double_framing_adds_header or snap.negative_control_extra_bytes != 8:
        raise SystemExit("double-framing negative control failed")
    if snap.channel_open_executed or snap.protocol_ack_observed:
        raise SystemExit("wire fixture must not open a channel or claim ACK")
    if snap.physical_effect_asserted or snap.real_payload_present:
        raise SystemExit("wire fixture must not claim physical effect or real payload")

    partial = CanonicalDoorWireFixtureBoundary(fail_after_write_index=3)
    partial_evidence = partial.attempt_once(
        TransportRequest(operation_id="wire-partial", target="synthetic-fixture-only")
    )
    if partial_evidence.outcome != BoundaryOutcome.AMBIGUOUS:
        raise SystemExit("partial wire emission must be ambiguous")
    if partial.last_snapshot is None or partial.last_snapshot.write_count != 3:
        raise SystemExit("partial wire fault did not stop after three writes")

    with tempfile.TemporaryDirectory() as tmp:
        journal = Journal(Path(tmp) / "state.sqlite3")
        exec_boundary = CanonicalDoorWireFixtureBoundary()
        executor = OneShotExecutor(journal, BoundaryTransportAdapter(exec_boundary), Policy(0))
        first = executor.execute(operation_id="wire-exec", target="synthetic-fixture-only")
        second = executor.execute(operation_id="wire-exec", target="synthetic-fixture-only")
        if first.state != State.UNKNOWN_OUTCOME or second.state != State.UNKNOWN_OUTCOME:
            raise SystemExit("complete wire reconciliation must map to UNKNOWN_OUTCOME")
        if exec_boundary.calls != 1:
            raise SystemExit("duplicate operation_id caused a second wire boundary invocation")

    print("WIRE_RECONCILIATION_CHANNEL_NAME=CTPP")
    print("WIRE_RECONCILIATION_CHANNEL_ID=7449")
    print("WIRE_RECONCILIATION_REQUEST_IDS_ALL_EQUAL=true")
    print("WIRE_RECONCILIATION_MAIN_WRITES=6")
    print("WIRE_RECONCILIATION_EQUIVALENT_FRAMES=6")
    print("WIRE_RECONCILIATION_BYTE_EXACT_EQUAL=true")
    print("WIRE_RECONCILIATION_HEADER_BYTES=8")
    print("WIRE_RECONCILIATION_DOUBLE_FRAME_EXTRA_BYTES=8")
    print("WIRE_RECONCILIATION_DOUBLE_FRAMING_ADDS_HEADER=true")
    print("WIRE_RECONCILIATION_PARTIAL_WRITE_OUTCOME=AMBIGUOUS")
    print("WIRE_RECONCILIATION_BOUNDARY_OUTCOME=ACCEPTED_NO_ACK")
    print("WIRE_RECONCILIATION_EXECUTOR_STATE=UNKNOWN_OUTCOME")
    print("WIRE_RECONCILIATION_DUPLICATE_NO_SECOND_RUN=PASS")
    print("WIRE_RECONCILIATION_CHANNEL_OPEN_EXECUTED=false")
    print("WIRE_RECONCILIATION_PROTOCOL_ACK=false")
    print("WIRE_RECONCILIATION_PHYSICAL_EFFECT=false")
    print("WIRE_RECONCILIATION_REAL_PAYLOAD_PRESENT=false")
    print("WIRE_RECONCILIATION_NETWORK_ACTION=false")
    print("WIRE_RECONCILIATION_FIXTURE_GATE=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
