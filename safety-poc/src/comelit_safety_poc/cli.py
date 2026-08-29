from __future__ import annotations

import argparse
import json
import sys

from .errors import SimulatedProcessCrash
from .executor import OneShotExecutor, Policy
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


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Offline one-shot safety PoC")
    p.add_argument("--db", default="./state/poc.sqlite3")
    sub = p.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run", help="execute one operation against mock/disabled backend")
    run.add_argument("--operation-id", required=True)
    run.add_argument("--target", default="demo-door")
    run.add_argument("--backend", choices=["mock", "real-disabled"], default="mock")
    run.add_argument(
        "--scenario",
        choices=["ack", "definitely_not_sent", "timeout_after_accept", "rejected", "accepted_no_ack"],
        default="ack",
    )
    run.add_argument("--fault", choices=["crash_pre_arm", "crash_after_arm", "crash_after_sent"])
    run.add_argument("--min-interval-seconds", type=int, default=10)

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

    transport = MockTransport(args.scenario) if args.backend == "mock" else DisabledRealTransport()
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
