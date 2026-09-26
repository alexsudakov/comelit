#!/usr/bin/env python3
"""Generate deterministic MSL-V5 startup-settle candidates."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import entrance_p116_r66_startup_settle_transform as r66
from entrance_p116_r66_startup_settle_transform import DEFAULT_SOURCE


SETTLE_VALUES = (2000, 1000, 500, 0)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output-dir", type=Path, default=Path("/tmp/msl-v5-settle-candidates"))
    args = parser.parse_args(argv)

    source_path = args.source
    if not source_path.exists() and str(source_path).startswith("safety-poc/"):
        source_path = Path(str(source_path)[len("safety-poc/"):])
    source = source_path.read_text(encoding="utf-8")
    args.output_dir.mkdir(parents=True, exist_ok=True)

    control = r66.transform(source, include_p116=True, settle_ms=4000)
    control_sha = _sha256(control)
    control_path = args.output_dir / "comelit-media-v5-settle-4000.c"
    control_path.write_text(control, encoding="utf-8")
    print(f"V5_SETTLE_MS=4000 CANDIDATE_FILE={control_path} GENERATED_SOURCE_SHA256={control_sha}")

    seen = {control_sha}
    for value in SETTLE_VALUES:
        first = r66.transform(source, include_p116=True, settle_ms=value)
        second = r66.transform(source, include_p116=True, settle_ms=value)
        first_sha = _sha256(first)
        second_sha = _sha256(second)
        if first_sha != second_sha or first != second:
            raise RuntimeError(f"candidate {value}: deterministic repeat failed")
        if first_sha in seen:
            raise RuntimeError(f"candidate {value}: SHA duplicates another candidate")
        seen.add(first_sha)
        path = args.output_dir / f"comelit-media-v5-settle-{value}.c"
        path.write_text(first, encoding="utf-8")
        print(
            f"V5_SETTLE_MS={value} CANDIDATE_FILE={path} "
            f"GENERATED_SOURCE_SHA256={first_sha} REPEAT_SHA256={second_sha}"
        )
    print("V5_CANDIDATE_DETERMINISM=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
