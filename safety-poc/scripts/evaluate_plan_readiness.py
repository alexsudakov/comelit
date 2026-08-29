#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from comelit_safety_poc.readiness import evaluate_readiness, parse_markers


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate repository and live-test gates from one or more marker reports.")
    parser.add_argument("reports", nargs="+", type=Path)
    args = parser.parse_args()

    markers: dict[str, str] = {}
    for report in args.reports:
        markers.update(parse_markers(report.read_text(encoding="utf-8")))

    result = evaluate_readiness(markers)
    for gate in result.gates:
        print(f"GATE marker={gate.marker} status={gate.status.value} expected={gate.expected} actual={gate.actual if gate.actual is not None else 'missing'}")
    print(f"REPOSITORY_READY={'true' if result.repository_ready else 'false'}")
    print(f"LIVE_TEST_READY={'true' if result.live_test_ready else 'false'}")
    print("REAL_TRANSPORT_ACTION_PERFORMED=false")
    print("PHYSICAL_DOOR_ACTION=false")
    return 0 if result.repository_ready else 2


if __name__ == "__main__":
    raise SystemExit(main())
