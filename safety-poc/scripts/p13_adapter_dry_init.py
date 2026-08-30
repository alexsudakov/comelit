#!/usr/bin/env python3
"""Non-actuating dry-initialization proof for the real P13 CT120 adapter.

This script never performs a network or actuator command.  It proves that the
concrete real session adapter can be constructed from the pinned artifacts and
prepared payload bundle, which is a precondition for emitting
ACTUATION_TRANSPORT_IMPLEMENTED=true.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

POC_ROOT = Path(__file__).resolve().parents[1]
SRC = POC_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from comelit_safety_poc.ct120_real_session import Ct120ArtifactSpec, Ct120RealP13Session
from comelit_safety_poc.p13_actuation_boundary import P13PayloadBundle


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


def main() -> int:
    parser = argparse.ArgumentParser(description="P13 real adapter dry-initialization proof")
    parser.add_argument("--payload", type=Path, required=True)
    parser.add_argument("--wrapper", type=Path, required=True)
    parser.add_argument("--wrapper-sha256", required=True)
    parser.add_argument("--wrapper-mode", default="700")
    args = parser.parse_args()

    bundle = load_bundle(args.payload)
    bundle.verify()
    spec = Ct120ArtifactSpec(
        wrapper=args.wrapper,
        wrapper_sha256=args.wrapper_sha256,
        wrapper_mode=args.wrapper_mode,
        payload_file=args.payload,
    )
    session = Ct120RealP13Session(spec, bundle, dry_init=True)
    markers = session.dry_initialize()
    print("P13_PAYLOAD_BUNDLE_VALID=true")
    for key, value in sorted(markers.items()):
        print(f"{key}={value}")
    print("P13_REAL_ADAPTER_DRY_INIT=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
