#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys


POC_ROOT = Path(__file__).resolve().parents[1]
SRC = POC_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from comelit_safety_poc.readiness import (  # noqa: E402
    LIVE_GATES,
    READONLY_GATES,
    REPOSITORY_GATES,
    evaluate_readiness,
    parse_markers,
)


def _require_expected(markers: dict[str, str], gates: tuple[tuple[str, str], ...], label: str) -> None:
    for marker, expected in gates:
        actual = markers.get(marker)
        if actual != expected:
            raise RuntimeError(
                f"{label} gate {marker} expected {expected!r}, got {actual if actual is not None else 'missing'!r}"
            )


def finalize(repository_text: str, live_text: str) -> tuple[dict[str, str], bool, bool, bool]:
    repository = parse_markers(repository_text)
    live = parse_markers(live_text)

    _require_expected(repository, REPOSITORY_GATES, "repository")
    _require_expected(live, READONLY_GATES, "read-only")
    if live.get("P12_READONLY_LIVE_GATES") != "PASS":
        raise RuntimeError("live evidence is missing P12_READONLY_LIVE_GATES=PASS")

    forbidden = {
        "ACTUATION_TRANSPORT_IMPLEMENTED": "true",
        "EXPLICIT_LIVE_TEST_APPROVAL": "true",
        "PHYSICAL_DOOR_ACTION": "true",
        "PHYSICAL_EFFECT_ASSERTED": "true",
        "ACTUATOR_COMMAND_ATTEMPTED": "true",
    }
    combined = dict(repository)
    combined.update(live)
    for marker, unsafe in forbidden.items():
        if combined.get(marker) == unsafe:
            raise RuntimeError(f"forbidden P12 readiness marker {marker}={unsafe}")

    result = evaluate_readiness(combined)
    if not result.repository_ready:
        raise RuntimeError("repository readiness unexpectedly false after repository gate validation")
    if not result.readonly_transport_ready:
        raise RuntimeError("read-only transport readiness unexpectedly false after gate validation")
    if result.live_test_ready:
        raise RuntimeError("P12 must not open the actuation live-test gate")
    return combined, result.repository_ready, result.readonly_transport_ready, result.live_test_ready


def write_report(path: Path, repository_text: str, live_text: str) -> None:
    combined, repository_ready, readonly_ready, live_ready = finalize(repository_text, live_text)
    lines = [
        "P12_READONLY_FINAL_SCHEMA=1",
    ]
    for marker, expected in REPOSITORY_GATES + READONLY_GATES:
        lines.append(f"{marker}={combined[marker]}")
    lines.extend(
        (
            "P12_READONLY_LIVE_GATES=PASS",
            f"REPOSITORY_READY={'true' if repository_ready else 'false'}",
            f"READONLY_TRANSPORT_READY={'true' if readonly_ready else 'false'}",
            f"LIVE_TEST_READY={'true' if live_ready else 'false'}",
            "ACTUATION_TRANSPORT_IMPLEMENTED=false",
            "EXPLICIT_LIVE_TEST_APPROVAL=false",
            "PHYSICAL_DOOR_ACTION=false",
            "PHYSICAL_EFFECT_ASSERTED=false",
            "P12_READONLY_FINALIZATION=PASS",
        )
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.chmod(path, 0o600)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Combine independent repository and P12 live-readonly gate evidence."
    )
    parser.add_argument("--repository-report", type=Path, required=True)
    parser.add_argument("--live-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    write_report(
        args.output,
        args.repository_report.read_text(encoding="utf-8"),
        args.live_report.read_text(encoding="utf-8"),
    )
    print("P12_READONLY_FINALIZATION=PASS")
    print("REPOSITORY_READY=true")
    print("READONLY_TRANSPORT_READY=true")
    print("LIVE_TEST_READY=false")
    print("PHYSICAL_DOOR_ACTION=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
