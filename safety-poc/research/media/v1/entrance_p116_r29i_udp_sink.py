#!/usr/bin/env python3
"""Deterministic loopback UDP sink for P116/R29I evidence collection.

The helper binds only to 127.0.0.1, records STARTED after bind, counts datagrams,
and atomically materializes both the final count and FINALIZED status after a
clean SIGTERM/SIGINT or bounded deadline. It does not send network traffic.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import signal
import socket
import time


_STOP = False


def _handle_signal(_signum: int, _frame: object) -> None:
    global _STOP
    _STOP = True


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _write_status(path: Path, *, started: bool, finalized: bool, count: int) -> None:
    _atomic_write(
        path,
        json.dumps(
            {"started": started, "finalized": finalized, "count": count},
            sort_keys=True,
        )
        + "\n",
    )


def run(port: int, count_file: Path, first_file: Path, status_file: Path, deadline_seconds: int) -> int:
    global _STOP
    _STOP = False
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.bind(("127.0.0.1", port))
        sock.settimeout(0.25)
        count = 0
        _write_status(status_file, started=True, finalized=False, count=0)
        deadline = time.monotonic() + max(1, deadline_seconds)
        while not _STOP and time.monotonic() < deadline:
            try:
                sock.recvfrom(65535)
            except socket.timeout:
                continue
            count += 1
            if count == 1:
                _atomic_write(first_file, f"{time.time():.6f}\n")
    finally:
        sock.close()

    _atomic_write(count_file, f"{count}\n")
    _write_status(status_file, started=True, finalized=True, count=count)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--count-file", type=Path, required=True)
    parser.add_argument("--first-file", type=Path, required=True)
    parser.add_argument("--status-file", type=Path, required=True)
    parser.add_argument("--deadline-seconds", type=int, required=True)
    args = parser.parse_args()
    return run(
        args.port,
        args.count_file,
        args.first_file,
        args.status_file,
        args.deadline_seconds,
    )


if __name__ == "__main__":
    raise SystemExit(main())
