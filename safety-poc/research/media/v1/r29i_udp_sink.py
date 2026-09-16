#!/usr/bin/env python3
"""Deterministic UDP sink used by the P116/R29I research runner.

The sink owns its finalization evidence: on SIGTERM/SIGINT or deadline it writes
the final datagram count atomically and only then atomically writes a done marker.
The runner may therefore use a bounded done-file join even when the sink was
started from a command-substitution subshell and is not a direct shell child.
"""
from __future__ import annotations

import argparse
import signal
import socket
import time
from pathlib import Path


def atomic_write(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def run(port: int, count_file: Path, first_file: Path, done_file: Path, timeout_seconds: float) -> int:
    stop = False

    def handle(_signum: int, _frame: object) -> None:
        nonlocal stop
        stop = True

    signal.signal(signal.SIGTERM, handle)
    signal.signal(signal.SIGINT, handle)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", port))
    sock.settimeout(0.2)
    deadline = time.monotonic() + timeout_seconds
    count = 0
    try:
        while not stop and time.monotonic() < deadline:
            try:
                sock.recvfrom(65535)
            except socket.timeout:
                continue
            count += 1
            if count == 1:
                atomic_write(first_file, f"{time.time():.6f}\n")
    finally:
        sock.close()
        atomic_write(count_file, f"{count}\n")
        atomic_write(done_file, "done\n")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--count-file", type=Path, required=True)
    parser.add_argument("--first-file", type=Path, required=True)
    parser.add_argument("--done-file", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=float, required=True)
    args = parser.parse_args()
    return run(args.port, args.count_file, args.first_file, args.done_file, args.timeout_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
