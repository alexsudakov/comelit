#!/usr/bin/env python3
"""P125 active-media ring opaque body probe transform."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import entrance_p116_r68_ringid_probe_core as core
import entrance_p122_on_demand_media_door_transform as p122

BASE_SOURCE_SHA256 = "5827d9fd043b85fc0c59a31661a1a125c6b239771e2a70c3e5afdd95f1a03c73"
P122_TRANSFORM = "entrance_p122_on_demand_media_door_transform.py"
INPUT_SOURCE_SHA256 = "92e12f5a27dd728231e073076429863cdc059825819f4f600d5d3dd50138ca26"


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def transform(source: str) -> str:
    base_sha = _sha256_text(source)
    if base_sha != BASE_SOURCE_SHA256:
        raise RuntimeError(f"P125_BASE_SOURCE_SHA_GATE=FAIL actual={base_sha}")
    input_source = p122.transform(source, include_p116=True)
    input_sha = _sha256_text(input_source)
    if input_sha != INPUT_SOURCE_SHA256:
        raise RuntimeError(f"P125_INPUT_SOURCE_SHA_GATE=FAIL actual={input_sha}")
    return core.apply_probe(input_source)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    generated = transform(args.source.read_text(encoding="utf-8"))
    args.output.write_text(generated, encoding="utf-8")
    print("P125_RINGID_PROBE_MEDIA_TRANSFORM=PASS")
    print("P125_P122_TRANSFORM=" + P122_TRANSFORM)
    print("P125_INPUT_SOURCE_SHA256=" + INPUT_SOURCE_SHA256)
    print("RINGID_PROBE_SOURCE_SHA256=" + _sha256_text(generated))
    print("RAW_RING_PAYLOAD_EMITTED=false")
    print("NETWORK_ACTION_PERFORMED=false")
    print("PHYSICAL_DOOR_ACTION=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
