#!/usr/bin/env python3
"""Standalone read-only listener status sampler for future live research.

The observer reads a sanitized JSON status snapshot exported by the operator or
future read-only diagnostics.  It does not call Home Assistant services and has
no control path.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


FIELDS = {
    "LISTENER_SUPERVISOR_RUNNING": "supervisor_running",
    "LISTENER_READY": "listener_ready",
    "LISTENER_MEDIA_PAUSED": "media_paused",
    "LISTENER_RECONNECT_COUNT": "reconnect_count",
    "LISTENER_LAST_ERROR": "last_error",
    "LISTENER_PROCESS_PID": "process_pid",
    "LISTENER_SOCKET_PRESENT": "socket_present",
    "LISTENER_CTPP_REGISTERED": "ctpp_registered",
    "LISTENER_REGISTRATION_GENERATION": "registration_generation",
    "LISTENER_TRANSPORT_ID": "transport_id",
}


def _safe_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if value is None:
        return "NONE"
    text = str(value)
    if len(text) > 64:
        text = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    return "".join(ch if ch.isalnum() or ch in "._:-" else "_" for ch in text)[:80]


def sample(path: Path) -> dict[str, str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    out = {marker: _safe_value(data.get(key)) for marker, key in FIELDS.items()}
    identity_material = "|".join(
        _safe_value(data.get(key, ""))
        for key in ("process_pid", "socket_inode", "transport_id", "registration_generation")
    )
    out["LISTENER_SOCKET_IDENTITY"] = hashlib.sha256(
        identity_material.encode("utf-8")
    ).hexdigest()[:16]
    ready = out["LISTENER_READY"] == "true"
    displaced = bool(data.get("socket_inode_changed") or data.get("transport_id_changed"))
    out["LISTENER_CONFLICT_DETECTED"] = "true" if ready and displaced else "false"
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--status-json", type=Path, required=True)
    args = parser.parse_args()
    for key, value in sample(args.status_json).items():
        print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
