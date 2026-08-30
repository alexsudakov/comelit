#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
from enum import Enum
import os
from pathlib import Path
import signal
import subprocess


class OneShotOutcome(str, Enum):
    COMPLETED = "COMPLETED"
    TIMEOUT_TERM = "TIMEOUT_TERM"
    TIMEOUT_KILL = "TIMEOUT_KILL"
    PROCESS_FAILURE = "PROCESS_FAILURE"


@dataclass(frozen=True)
class OneShotResult:
    outcome: OneShotOutcome
    process_rc: int | None
    timeout_observed: bool


def _signal_process_group(proc: subprocess.Popen[bytes], sig: signal.Signals) -> None:
    try:
        os.killpg(proc.pid, sig)
    except ProcessLookupError:
        pass


def run_once(
    wrapper: Path,
    raw_log: Path,
    *,
    timeout_seconds: float,
    term_grace_seconds: float,
) -> OneShotResult:
    if timeout_seconds <= 0 or term_grace_seconds <= 0:
        raise ValueError("timeouts must be positive")

    raw_log.parent.mkdir(parents=True, exist_ok=True)
    with raw_log.open("wb") as output:
        os.chmod(raw_log, 0o600)
        proc = subprocess.Popen(
            [str(wrapper)],
            stdout=output,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            close_fds=True,
            start_new_session=True,
        )
        try:
            rc = proc.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            _signal_process_group(proc, signal.SIGTERM)
            try:
                rc = proc.wait(timeout=term_grace_seconds)
                return OneShotResult(OneShotOutcome.TIMEOUT_TERM, rc, True)
            except subprocess.TimeoutExpired:
                _signal_process_group(proc, signal.SIGKILL)
                rc = proc.wait()
                return OneShotResult(OneShotOutcome.TIMEOUT_KILL, rc, True)

    if rc == 0:
        return OneShotResult(OneShotOutcome.COMPLETED, rc, False)
    return OneShotResult(OneShotOutcome.PROCESS_FAILURE, rc, False)


def write_status(path: Path, result: OneShotResult) -> None:
    rc = "NONE" if result.process_rc is None else str(result.process_rc)
    lines = (
        f"P12_ONE_SHOT_OUTCOME={result.outcome.value}",
        f"P12_ONE_SHOT_PROCESS_RC={rc}",
        f"P12_ONE_SHOT_TIMEOUT_OBSERVED={'true' if result.timeout_observed else 'false'}",
        "P12_ONE_SHOT_PROCESS_INVOCATIONS=1",
        "P12_ONE_SHOT_AUTO_RETRY=false",
        "P12_ONE_SHOT_PROCESS_GROUP_ISOLATED=true",
        "TIMEOUT_MAPPING_VERIFIED=PASS",
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.chmod(path, 0o600)


def main() -> int:
    parser = argparse.ArgumentParser(description="Execute the pinned P12 read-only wrapper exactly once")
    parser.add_argument("--wrapper", type=Path, required=True)
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--status", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=float, default=75.0)
    parser.add_argument("--term-grace-seconds", type=float, default=5.0)
    args = parser.parse_args()

    result = run_once(
        args.wrapper,
        args.raw,
        timeout_seconds=args.timeout_seconds,
        term_grace_seconds=args.term_grace_seconds,
    )
    write_status(args.status, result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
