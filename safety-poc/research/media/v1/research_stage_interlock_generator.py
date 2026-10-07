#!/usr/bin/env python3
"""Research-only generator entrypoint for the stage-interlock media helper."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import entrance_research_stage_interlock_transform as interlock
from entrance_p116_r65_production_media_refresh_transform import DEFAULT_SOURCE


def _under_forbidden_native_path(path: Path) -> bool:
    resolved = path.resolve()
    for parent in (resolved, *resolved.parents):
        if parent.name == "native" and parent.parent.name == "comelit":
            return True
    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--include-p116", action="store_true")
    parser.add_argument("--no-include-p116", action="store_true")
    args = parser.parse_args(argv)

    if _under_forbidden_native_path(args.output):
        raise SystemExit("RESEARCH_GENERATOR_OUTPUT_FORBIDDEN=custom_components/comelit/native")

    generated = interlock.transform(args.source.read_text(encoding="utf-8"), research=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(generated, encoding="utf-8")
    print("RESEARCH_GENERATOR=RESEARCH_ONLY")
    print(f"RESEARCH_GENERATED_SOURCE_SHA256={hashlib.sha256(generated.encode('utf-8')).hexdigest()}")
    print("NETWORK_IO_PERFORMED=false")
    print("CANDIDATE_EXECUTED=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
