#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path


def canonical_payload_bytes(payload: dict) -> bytes:
    """Return the exact byte representation expected by the generated holder."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def canonicalize_payload(path: Path) -> str:
    """Rewrite only JSON formatting so runtime bytes match the holder's pinned SHA.

    Door body values and metadata are not changed.  The replacement is atomic,
    retains the original uid/gid, and leaves the root-only payload at mode 0600.
    """
    path = Path(path)
    stat_before = path.stat()
    payload = json.loads(path.read_text(encoding="utf-8"))
    canonical = canonical_payload_bytes(payload)

    if path.read_bytes() != canonical:
        tmp = path.with_name(path.name + ".canonical.tmp")
        try:
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            try:
                with os.fdopen(fd, "wb", closefd=True) as handle:
                    handle.write(canonical)
                    handle.flush()
                    os.fsync(handle.fileno())
            except Exception:
                raise
            os.chown(tmp, stat_before.st_uid, stat_before.st_gid)
            os.chmod(tmp, 0o600)
            os.replace(tmp, path)
        finally:
            try:
                tmp.unlink()
            except FileNotFoundError:
                pass

    os.chmod(path, 0o600)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Canonicalize the root-only P13 payload byte representation")
    parser.add_argument("--payload", type=Path, required=True)
    args = parser.parse_args()

    digest = canonicalize_payload(args.payload)
    print("P13_PAYLOAD_CANONICALIZATION=PASS")
    print(f"P13_PAYLOAD_RUNTIME_SHA256={digest}")
    print("NETWORK_ACTION_PERFORMED=false")
    print("ACTUATOR_COMMAND_ATTEMPTED=false")
    print("PHYSICAL_DOOR_ACTION=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
