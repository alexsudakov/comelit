#!/usr/bin/env python3
"""P116/R68 listener ring opaque body probe transform."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import entrance_p116_r67_attached_media_refresh_transform as r67
import entrance_p116_r68_ringid_probe_core as core

BASE_SOURCE_SHA256 = "5827d9fd043b85fc0c59a31661a1a125c6b239771e2a70c3e5afdd95f1a03c73"
INPUT_SOURCE_SHA256 = "f996c073a3ad49619e801d16d1f95aa20c818af388fe8c00dd8c7974f467a4de"


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def transform(source: str) -> str:
    base_sha = _sha256_text(source)
    if base_sha != BASE_SOURCE_SHA256:
        raise RuntimeError(f"R68_BASE_SOURCE_SHA_GATE=FAIL actual={base_sha}")
    input_source = r67.transform(source)
    input_sha = _sha256_text(input_source)
    if input_sha != INPUT_SOURCE_SHA256:
        raise RuntimeError(f"R68_INPUT_SOURCE_SHA_GATE=FAIL actual={input_sha}")
    return core.apply_probe(input_source)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    generated = transform(args.source.read_text(encoding="utf-8"))
    args.output.write_text(generated, encoding="utf-8")
    print("R68_RINGID_PROBE_TRANSFORM=PASS")
    print("RINGID_PROBE_SOURCE_SHA256=" + _sha256_text(generated))
    print("RAW_RING_PAYLOAD_EMITTED=false")
    print("NETWORK_ACTION_PERFORMED=false")
    print("PHYSICAL_DOOR_ACTION=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
