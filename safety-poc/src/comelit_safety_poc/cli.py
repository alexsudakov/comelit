from __future__ import annotations

import argparse
import json
import sys

from .audit import AuditSink, AuditedExecutorTransport
from .errors import SimulatedProcessCrash
from .executor import OneShotExecutor, Policy
from .p13_actuation_boundary import (
    FixtureP13DoorSession,
    P13BodyFileLoader,
    P13PayloadBundle,
    RealDoorActuationBoundary,
)
from .store import Journal
from .transport import DisabledRealTransport, MockTransport


def _operation_json(op, events=None):
    data = {
        "operation_id": op.operation_id,
        "target": op.target,
        "state": op.state.value,
        "created_at": op.created_at,
        "updated_at": op.updated_at,
        "detail": op.detail,
    }
    if events is not None:
        data["events"] = events
    return data


def _load_p13_bundle(path: str) -> P13PayloadBundle:
    from pathlib import Path as _Path

    with _Path(path).open(encoding="utf-8") as fh:
        raw = json.load(fh)
    return P13PayloadBundle(
        schema=int(raw["schema"]),
        ucfg_sha256=str(raw["ucfg_sha256"]),
        target_index=int(raw["target_index"]),
        target_fingerprint=str(raw["target_fingerprint"]),
        target_name=str(raw["target_name"]),
        channel_id_fixture=int(raw["channel_id_fixture"]),
        write_count=int(raw["write_count"]),
        write_sha256=tuple(str(b["sha256"]) for b in raw["bodies"]),
        write_bytes=tuple(int(b["bytes"]) for b in raw["bodies"]),
    )


def _p13_boundary_transport(boundary: RealDoorActuationBoundary):
    from .boundary import BoundaryTransportAdapter

    return BoundaryTransportAdapter(boundary)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Offline one-shot safety PoC")
    p.add_argument("--db", default="./state/poc.sqlite3")
    sub = p.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run", help="execute one operation against mock/disabled backend")
    run.add_argument("--operation-id", required=True)
    run.add_argument("--target", default="demo-door")
    run.add_argument(
        "--backend",
        choices=["mock", "real-disabled", "p13-fixture"],
        default="mock",
    )
    run.add_argument(
        "--scenario",
        choices=["ack", "definitely_not_sent", "timeout_after_accept", "rejected", "accepted_no_ack"],
        default="ack",
    )
    run.add_argument("--fault", choices=["crash_pre_arm", "crash_after_arm", "crash_after_sent"])
    run.add_argument("--min-interval-seconds", type=int, default=10)
    run.add_argument(
        "--audit",
        help="append-only audit journal path (JSONL); enables durable audit recording",
    )
    run.add_argument(
        "--p13-payload",
        help="P13 prepared payload JSON path (root-only, mode 0600) for backend p13-fixture",
    )

    show = sub.add_parser("show")
    show.add_argument("--operation-id", required=True)

    sub.add_parser("recover")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    journal = Journal(args.db)

    if args.cmd == "show":
        op = journal.get(args.operation_id)
        print(json.dumps(_operation_json(op, journal.events(op.operation_id)), indent=2))
        return 0

    if args.cmd == "recover":
        executor = OneShotExecutor(journal, MockTransport("ack"))
        ops = executor.recover()
        print(json.dumps([_operation_json(o) for o in ops], indent=2))
        return 0

    if args.backend == "mock":
        transport = MockTransport(args.scenario)
    elif args.backend == "real-disabled":
        transport = DisabledRealTransport()
    else:
        if not args.p13_payload:
            print(json.dumps({"error": "P13_FIXTURE_REQUIRES_PAYLOAD=true"}, indent=2))
            return 2
        bundle = _load_p13_bundle(args.p13_payload)
        session = FixtureP13DoorSession()
        boundary = RealDoorActuationBoundary(session, bundle)
        transport = _p13_boundary_transport(boundary)

    if args.audit:
        sink = AuditSink(args.audit)
        transport = AuditedExecutorTransport(transport, sink)

    executor = OneShotExecutor(journal, transport, Policy(args.min_interval_seconds))
    try:
        op = executor.execute(
            operation_id=args.operation_id,
            target=args.target,
            fault=args.fault,
        )
    except SimulatedProcessCrash as exc:
        print(json.dumps({"simulated_crash": str(exc), "operation_id": args.operation_id}, indent=2))
        return 75

    print(json.dumps(_operation_json(op, journal.events(op.operation_id)), indent=2))
    return 0 if op.state.value in {"ACKED", "FAILED_SAFE", "UNKNOWN_OUTCOME"} else 1


if __name__ == "__main__":
    sys.exit(main())
