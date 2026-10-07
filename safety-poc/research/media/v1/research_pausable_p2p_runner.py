#!/usr/bin/env python3
"""Offline-capable runner for the research pausable P2P helper."""
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import signal
import stat
import subprocess
import sys
import tempfile
import time


VALID_STAGES = {6, 7, 8, 9, 10, 12}
STAGE_MARKERS = {
    6: "RESEARCH_STAGE_6_LOCAL_OFFER_READY",
    7: "RESEARCH_STAGE_7_BACKEND_P2P_ALLOCATED",
    8: "RESEARCH_STAGE_8_REMOTE_SDP_APPLIED",
    9: "RESEARCH_STAGE_9_ICE_CONNECTED",
    10: "RESEARCH_STAGE_10_PSEUDOTCP_OPEN",
    12: "RESEARCH_STAGE_12_CTPP_REGISTERED",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_temp_secret(run_dir: Path) -> Path:
    secret = run_dir / "research-secret.env"
    old_umask = os.umask(0o077)
    try:
        secret.write_text("VIP_TOKEN_PRESENT=true\nVIP_TOKEN_LENGTH=12\n", encoding="utf-8")
    finally:
        os.umask(old_umask)
    secret.chmod(0o600)
    return secret


def run_helper(args: argparse.Namespace) -> int:
    if args.stop_after_stage not in VALID_STAGES:
        raise SystemExit("RESEARCH_STOP_AFTER_STAGE must be one of 6,7,8,9,10,12")

    binary = args.binary.resolve()
    if not binary.exists():
        raise SystemExit(f"expected binary is missing: {binary}")
    actual_sha = sha256_file(binary)
    if args.expected_sha256 and actual_sha != args.expected_sha256:
        raise SystemExit(
            "RESEARCH_BINARY_IDENTITY=FAIL "
            f"expected={args.expected_sha256} actual={actual_sha}"
        )

    with tempfile.TemporaryDirectory(prefix="comelit-research-run-") as tmp:
        run_dir = Path(tmp)
        secret = _write_temp_secret(run_dir)
        if stat.S_IMODE(secret.stat().st_mode) != 0o600:
            raise SystemExit("RESEARCH_SECRET_MODE=FAIL")

        env = os.environ.copy()
        env.update(
            {
                "RESEARCH_STOP_AFTER_STAGE": str(args.stop_after_stage),
                "RESEARCH_HOLD_MS": str(args.hold_ms),
                "RESEARCH_SECRET_FILE": str(secret),
                "COMELIT_NETWORK_DISABLED": "1",
            }
        )
        if args.force_forbidden:
            env["RESEARCH_FORCE_FORBIDDEN_STAGE13"] = "1"

        proc = subprocess.Popen(
            [str(binary)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=env,
        )
        assert proc.stdout is not None

        lines: list[str] = []
        expected = STAGE_MARKERS[args.stop_after_stage]
        saw_expected = False
        saw_hold = False
        deadline = time.monotonic() + args.timeout

        while time.monotonic() < deadline:
            line = proc.stdout.readline()
            if line:
                line = line.rstrip("\n")
                lines.append(line)
                if line == expected:
                    saw_expected = True
                if line == "RESEARCH_HOLD_ENTERED=true":
                    saw_hold = True
                    if args.terminate_during_hold:
                        proc.send_signal(signal.SIGTERM)
                if line == "RESEARCH_TEARDOWN_DONE=true":
                    break
            elif proc.poll() is not None:
                break
            else:
                time.sleep(0.01)

        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=2)

        remainder = proc.stdout.read()
        if remainder:
            lines.extend(remainder.splitlines())

        if secret.exists():
            secret.unlink()

        print(f"RESEARCH_BINARY_SHA256={actual_sha}")
        print(f"RESEARCH_EXPECTED_STAGE_MARKER={expected}")
        for line in lines:
            if len(line) <= 160 and all(ch.isprintable() for ch in line):
                print(line)
        print(f"RESEARCH_STAGE_MARKER_SEEN={'true' if saw_expected else 'false'}")
        print(f"RESEARCH_HOLD_SEEN={'true' if saw_hold else 'false'}")
        print(f"RESEARCH_TEMP_SECRET_REMOVED={'true' if not secret.exists() else 'false'}")
        print("RESEARCH_NO_COMELIT_NETWORK=true")
        print(f"RESEARCH_HELPER_EXIT_CODE={proc.returncode}")
        return proc.returncode or 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--expected-sha256")
    parser.add_argument("--stop-after-stage", type=int, required=True)
    parser.add_argument("--hold-ms", type=int, default=300)
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument("--terminate-during-hold", action="store_true")
    parser.add_argument("--force-forbidden", action="store_true")
    return run_helper(parser.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
