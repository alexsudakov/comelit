from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

POC_ROOT = Path(__file__).resolve().parents[1]
SRC = POC_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from comelit_safety_poc.audit import AuditSink, AuditedExecutorTransport
from comelit_safety_poc.boundary import BoundaryTransportAdapter
from comelit_safety_poc.ct120_real_session import Ct120ArtifactSpec, Ct120RealP13Session
from comelit_safety_poc.executor import OneShotExecutor, Policy
from comelit_safety_poc.model import Operation, State
from comelit_safety_poc.p13_actuation_boundary import (
    P13BodyFileLoader,
    P13PayloadBundle,
    RealDoorActuationBoundary,
)
from comelit_safety_poc.store import Journal

APPROVAL_TOKEN = "I_APPROVE_P13_ONE_SHOT_PHYSICAL_DOOR_TEST"


def load_bundle(path: Path) -> P13PayloadBundle:
    raw = json.loads(path.read_text(encoding="utf-8"))
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


def _operation_json(op: Operation, events: list[dict] | None = None) -> dict:
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="P13 operator-gated one-shot physical runner")
    parser.add_argument("--db", required=True)
    parser.add_argument("--operation-id", required=True)
    parser.add_argument("--target-fingerprint", required=True)
    parser.add_argument("--min-interval-seconds", type=int, default=10)
    parser.add_argument("--wrapper", required=True)
    parser.add_argument("--wrapper-sha256", required=True)
    parser.add_argument("--wrapper-mode", default="700")
    parser.add_argument("--payload", required=True)
    parser.add_argument("--payload-sha256", required=True)
    parser.add_argument("--audit", required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--tree", required=True)
    parser.add_argument("--run-dir", default="/root/comelit-p13-run")
    args = parser.parse_args(argv)
    # uid=0 enforcement on wrapper/payload is on by default (production path);
    # tests running as non-root opt out via the environment.
    require_root_owner = os.environ.get("P13_REQUIRE_ROOT_OWNER", "1") != "0"

    # Operator gate: the exact token must be present in the environment at
    # execution time.  It is never persisted and never implied by this task.
    if os.environ.get("P13_APPROVAL") != APPROVAL_TOKEN:
        print(json.dumps({"error": "P13_ONE_SHOT_APPROVAL=FAIL"}, indent=2))
        return 66

    payload_path = Path(args.payload)
    actual_payload_sha = __import__("hashlib").sha256(payload_path.read_bytes()).hexdigest()
    if actual_payload_sha != args.payload_sha256:
        print(json.dumps({"error": "P13_PAYLOAD_SHA_MISMATCH=true"}, indent=2))
        return 65

    bundle = load_bundle(payload_path)
    bundle.verify()
    if bundle.target_fingerprint != args.target_fingerprint:
        print(json.dumps({"error": "P13_TARGET_BINDING_MISMATCH=true"}, indent=2))
        return 65

    spec = Ct120ArtifactSpec(
        wrapper=Path(args.wrapper),
        wrapper_sha256=args.wrapper_sha256,
        wrapper_mode=args.wrapper_mode,
        payload_file=payload_path,
        require_root_owner=require_root_owner,
    )
    spec.verify()

    # The real session performs the proven P2P -> ViP -> UAUT -> CTPP path and
    # the six prepared Door writes in exactly one invocation.
    session = Ct120RealP13Session(
        spec,
        bundle,
        run_dir=Path(args.run_dir),
        dry_init=True,
    )
    boundary = RealDoorActuationBoundary(
        session,
        bundle,
        body_loader=P13BodyFileLoader(payload_path),
    )

    journal = Journal(args.db)
    sink = AuditSink(args.audit)
    executor = OneShotExecutor(
        journal,
        AuditedExecutorTransport(BoundaryTransportAdapter(boundary), sink),
        Policy(args.min_interval_seconds),
    )

    op = executor.execute(operation_id=args.operation_id, target=args.target_fingerprint)
    events = journal.events(args.operation_id)
    result = _operation_json(op, events)
    result["P13_ONE_SHOT_MAX_INVOCATIONS"] = 1
    result["P13_AUTO_RETRY_ALLOWED"] = False
    result["P13_PHYSICAL_EFFECT_ASSERTED"] = False
    result["P13_HEAD"] = args.head
    result["P13_TREE"] = args.tree
    print(json.dumps(result, indent=2))

    if op.state == State.FAILED_SAFE:
        return 0
    if op.state == State.UNKNOWN_OUTCOME:
        return 0
    if op.state == State.ACKED:
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
