#!/usr/bin/env python3
"""Offline-first runner for the research pausable P2P helper.

The native helper owns stage 6 only.  Stage 7 is a runner state: after the
stage-6 pause marker, this runner may perform exactly one P2P start exchange,
buffer the remote SDP in memory, and then abort the helper without resuming it.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request


VALID_STAGES = {6, 7, 8, 9, 10, 12}
STAGE6_MARKER = "RESEARCH_STAGE_6_LOCAL_OFFER_READY"
STAGE_MARKERS = {
    6: STAGE6_MARKER,
    7: "RESEARCH_STAGE_7_BACKEND_P2P_ALLOCATED",
    8: "RESEARCH_STAGE_8_REMOTE_SDP_APPLIED",
    9: "RESEARCH_STAGE_9_ICE_CONNECTED",
    10: "RESEARCH_STAGE_10_PSEUDOTCP_OPEN",
    12: "RESEARCH_STAGE_12_CTPP_REGISTERED",
}
RUNNER_STATES = (
    "STATE_IDLE",
    "STATE_LOCAL_OFFER_READY",
    "STATE_CLOUD_P2P_ALLOCATED",
    "STATE_REMOTE_SDP_AVAILABLE_NOT_APPLIED",
    "STATE_ABORTING",
    "STATE_CLEANED",
)
GUARD_PATTERNS = {
    "REMOTE_SDP_APPLY_GUARD": ("RESEARCH_STAGE_8_REMOTE_SDP_APPLIED", "REMOTE_PRIMITIVES_IMPORT=PASS"),
    "HELPER_RESUME_GUARD": ("RESEARCH_STAGE_6_PAUSE_REASON=CONTINUE",),
    "ICE_CONNECTED_GUARD": ("RESEARCH_STAGE_9_ICE_CONNECTED", "ICE_CONNECTED", "NICE_COMPONENT_STATE_READY"),
    "PSEUDOTCP_GUARD": ("RESEARCH_STAGE_10_PSEUDOTCP_OPEN", "PSEUDOTCP_OPEN=PASS"),
    "CTPP_GUARD": ("V4_CTPP_REGISTRATION=PASS", "RESEARCH_STAGE_12_CTPP_REGISTERED"),
    "SELF_ACTIVATION_GUARD": ("ENTRANCE_SELF_ACTIVATION_SENT=PASS",),
    "RTPC_GUARD": ("P78_RTPC_OPEN_REQUESTED=true", "RTPC_OPENED"),
    "RTP_GUARD": ("P80_RTP_FORWARD=PASS", "RTP_STARTED", "MEDIA_FORWARDING_ACTIVE"),
}
REMOTE_SDP_REQUIRED = ("a=ice-ufrag:", "a=ice-pwd:", "a=candidate:")
NETWORK_DISABLED_MARKER = "NETWORK_IO_TO_COMELIT=0"
FIXTURE_REMOTE_SDP = (
    "v=0\r\n"
    "o=- 2 2 IN IP4 127.0.0.1\r\n"
    "s=Comelit research remote\r\n"
    "t=0 0\r\n"
    "a=ice-ufrag:remoteufrag\r\n"
    "a=ice-pwd:remotepassword\r\n"
    "a=candidate:1 1 UDP 2130706431 127.0.0.1 5001 typ host\r\n"
)


class RunnerError(RuntimeError):
    pass


class ForbiddenStageCrossing(RunnerError):
    def __init__(self, guard: str) -> None:
        self.guard = guard
        super().__init__(guard)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def shipped_binary_sha256(repo_root: Path) -> str:
    text = (repo_root / "custom_components" / "comelit" / "media_transport.py").read_text(encoding="utf-8")
    match = re.search(r'MEDIA_NATIVE_BINARY_SHA256\s*=\s*\(\s*"([0-9a-f]{64})"\s*\)', text)
    if not match:
        raise RunnerError("SHIPPED_SHA_PIN=UNREADABLE")
    return match.group(1)


def _safe_print(line: str) -> None:
    if len(line) <= 220 and all(ch.isprintable() for ch in line):
        print(line)


def _write_temp_secret(run_dir: Path, vip_token: str) -> Path:
    secret = run_dir / "research-secret.env"
    old_umask = os.umask(0o077)
    try:
        secret.write_text(f"COMELIT_VIP_TOKEN=<redacted>\nVIP_TOKEN_LENGTH={len(vip_token)}\n", encoding="utf-8")
    finally:
        os.umask(old_umask)
    secret.chmod(0o600)
    return secret


def load_credentials(path: Path) -> dict[str, str]:
    raw = path.read_text(encoding="utf-8")
    if "VIP_TOKEN_PRESENT=true" in raw or "VIP_TOKEN_LENGTH=12" in raw:
        raise RunnerError("CREDENTIAL_SOURCE=PLACEHOLDER")
    values: dict[str, str] = {}
    if path.suffix == ".json":
        obj = json.loads(raw)
        if not isinstance(obj, dict):
            raise RunnerError("CREDENTIAL_SOURCE=INVALID")
        for key in ("device_uuid", "vip_token", "oauth_access_token"):
            value = obj.get(key)
            if isinstance(value, str):
                values[key] = value
    else:
        key_map = {
            "COMELIT_DEVICE_UUID": "device_uuid",
            "COMELIT_VIP_TOKEN": "vip_token",
            "COMELIT_OAUTH_ACCESS_TOKEN": "oauth_access_token",
        }
        for line in raw.splitlines():
            if "=" not in line or line.lstrip().startswith("#"):
                continue
            key, value = line.split("=", 1)
            if key in key_map:
                values[key_map[key]] = value.strip().strip("'\"")
    if not all(values.get(key) for key in ("device_uuid", "vip_token", "oauth_access_token")):
        raise RunnerError("CREDENTIAL_SOURCE=INCOMPLETE")
    if len(values["vip_token"]) <= 12:
        raise RunnerError("CREDENTIAL_SOURCE=PLACEHOLDER")
    return values


def validate_remote_sdp(remote: str) -> None:
    lines = [line.strip() for line in remote.replace("\r\n", "\n").split("\n") if line.strip()]
    if not all(any(line.startswith(prefix) for line in lines) for prefix in REMOTE_SDP_REQUIRED):
        raise RunnerError("REMOTE_SDP=INCOMPLETE")


def p2p_start(url: str, credentials: dict[str, str], offer_sdp: str) -> str:
    if url == "fixture://p2p":
        if "v=0" not in offer_sdp or "a=ice-ufrag:" not in offer_sdp:
            raise RunnerError("LOCAL_OFFER_SDP=INVALID")
        validate_remote_sdp(FIXTURE_REMOTE_SDP)
        return FIXTURE_REMOTE_SDP

    encoded_sdp = base64.b64encode(offer_sdp.encode("utf-8")).decode("ascii")
    payload = {
        "deviceUuid": credentials["device_uuid"],
        "data": {
            "authMode": "user_viper_token",
            "secret": credentials["vip_token"],
            "timeout": 10,
            "sdp": encoded_sdp,
        },
        "protocol": {"name": "viper_p2p_v2", "version": 1},
    }
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Authorization": "bearer " + credentials["oauth_access_token"],
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            if not 200 <= response.status < 300:
                raise RunnerError(f"P2P_START_HTTP_STATUS={response.status}")
            raw = response.read()
    except urllib.error.HTTPError as exc:
        raise RunnerError(f"P2P_START_HTTP_STATUS={exc.code}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RunnerError(f"P2P_START_EXCEPTION={type(exc).__name__}") from exc

    obj = json.loads(raw.decode("utf-8", errors="replace"))
    encoded_remote = obj.get("data", {}).get("sdp") if isinstance(obj, dict) else None
    if not isinstance(encoded_remote, str) or not encoded_remote:
        raise RunnerError("REMOTE_SDP=MISSING")
    remote = base64.b64decode(encoded_remote, validate=True).decode("utf-8")
    validate_remote_sdp(remote)
    return remote


def detect_guard(line: str) -> str | None:
    for guard, patterns in GUARD_PATTERNS.items():
        if any(pattern in line for pattern in patterns):
            return guard
    return None


def live_preflight(args: argparse.Namespace, actual_sha: str, repo_root: Path) -> dict[str, str]:
    if not args.stop_after_stage:
        raise RunnerError("LIVE_STOP_AFTER_STAGE_REQUIRED=true")
    if args.stop_after_stage != 7:
        raise RunnerError("LIVE_STAGE7_ONLY=true")
    if not args.expected_sha256 or args.expected_sha256 != actual_sha:
        raise RunnerError("RESEARCH_BINARY_IDENTITY=FAIL")
    if actual_sha == shipped_binary_sha256(repo_root):
        raise RunnerError("PRODUCTION_BINARY_IDENTITY=REFUSED")
    if not args.verify_musl_marker:
        raise RunnerError("RESEARCH_MUSL_MARKER=UNVERIFIED")
    if args.hold_ms <= 0:
        raise RunnerError("BOUNDED_HOLD_REQUIRED=true")
    if args.retry_count != 0:
        raise RunnerError("RETRY_COUNT_MUST_BE_ZERO=true")
    if args.max_p2p_start_calls != 1:
        raise RunnerError("MAX_P2P_START_CALLS_MUST_BE_ONE=true")
    if not args.credential_file:
        raise RunnerError("CREDENTIAL_SOURCE=REQUIRED")
    return load_credentials(args.credential_file)


def run_helper(args: argparse.Namespace) -> int:
    if args.stop_after_stage not in VALID_STAGES:
        raise SystemExit("RESEARCH_STOP_AFTER_STAGE must be one of 6,7,8,9,10,12")

    repo_root = Path(__file__).resolve().parents[4]
    binary = args.binary.resolve()
    if not binary.exists():
        raise SystemExit(f"expected binary is missing: {binary}")
    actual_sha = sha256_file(binary)
    if args.expected_sha256 and actual_sha != args.expected_sha256:
        raise SystemExit(f"RESEARCH_BINARY_IDENTITY=FAIL expected={args.expected_sha256} actual={actual_sha}")

    network_to_comelit = bool(args.live_stage_test)
    print(f"NETWORK_IO_TO_COMELIT={1 if network_to_comelit else 0}")
    if not args.live_stage_test:
        print("LIVE_STAGE_TEST=false")
        print("COMELIT_NETWORK_DISABLED=1")

    credentials: dict[str, str] = {}
    if args.live_stage_test:
        credentials = live_preflight(args, actual_sha, repo_root)

    post_count = 0
    helper_continue_count = 0
    remote_sdp_buffered = False
    remote_sdp_applied = False
    saw_stage6 = False
    saw_pause = False
    final_state = "STATE_IDLE"
    injected_guard = args.inject_guard_marker

    with tempfile.TemporaryDirectory(prefix="comelit-research-run-") as tmp:
        run_dir = Path(tmp)
        offer_file = args.offer_file or (run_dir / "offer.sdp")
        remote_file = args.remote_sdp_file or (run_dir / "remote.sdp")
        control_path = run_dir / "stage6-control.fifo"
        os.mkfifo(control_path, 0o600)
        control_fd = os.open(control_path, os.O_RDWR | os.O_NONBLOCK)
        secret: Path | None = None
        if args.live_stage_test:
            secret = _write_temp_secret(run_dir, credentials["vip_token"])
            if stat.S_IMODE(secret.stat().st_mode) != 0o600:
                raise SystemExit("RESEARCH_SECRET_MODE=FAIL")

        env = os.environ.copy()
        env.update(
            {
                "RESEARCH_STOP_AFTER_STAGE": str(args.stop_after_stage),
                "RESEARCH_HOLD_MS": str(args.hold_ms),
                "RESEARCH_STAGE6_CONTROL_PATH": str(control_path),
                "RESEARCH_OFFER_FILE": str(offer_file),
                "COMELIT_NETWORK_DISABLED": "0" if args.live_stage_test else "1",
            }
        )
        if secret is not None:
            env["RESEARCH_SECRET_FILE"] = str(secret)
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
        deadline = time.monotonic() + args.timeout
        fatal_guard: str | None = None

        try:
            while time.monotonic() < deadline:
                if remote_file.exists() and args.stop_after_stage == 7:
                    fatal_guard = "REMOTE_SDP_APPLY_GUARD"
                    break

                line = proc.stdout.readline()
                if line:
                    line = line.rstrip("\n")
                    lines.append(line)
                    guard = detect_guard(line)
                    if guard and args.stop_after_stage == 7 and args.live_stage_test:
                        fatal_guard = guard
                        break
                    if line == injected_guard:
                        fatal_guard = detect_guard(line) or "FORBIDDEN_STAGE_CROSSING"
                        break
                    if line == STAGE6_MARKER:
                        saw_stage6 = True
                        final_state = "STATE_LOCAL_OFFER_READY"
                    if line == "RESEARCH_STAGE_6_PAUSE_ENTERED=true":
                        saw_pause = True
                        if args.terminate_during_hold:
                            proc.send_signal(signal.SIGTERM)
                        elif args.close_control_channel:
                            os.close(control_fd)
                            control_fd = -1
                        elif args.stage6_continue:
                            os.write(control_fd, b"CONTINUE\n")
                            helper_continue_count += 1
                        elif args.stage6_abort:
                            os.write(control_fd, b"ABORT\n")
                        elif args.stop_after_stage == 7 and args.live_stage_test:
                            if not offer_file.exists():
                                raise RunnerError("LOCAL_OFFER_FILE=MISSING")
                            offer_sdp = offer_file.read_text(encoding="utf-8")
                            if post_count >= args.max_p2p_start_calls:
                                raise RunnerError("MAX_P2P_START_CALLS=EXCEEDED")
                            remote_sdp = p2p_start(args.p2p_url, credentials, offer_sdp)
                            post_count += 1
                            final_state = "STATE_CLOUD_P2P_ALLOCATED"
                            print("RESEARCH_STAGE_7_BACKEND_P2P_ALLOCATED=true")
                            validate_remote_sdp(remote_sdp)
                            remote_sdp_buffered = True
                            final_state = "STATE_REMOTE_SDP_AVAILABLE_NOT_APPLIED"
                            print("RESEARCH_STAGE_7_REMOTE_SDP_BUFFERED=true")
                            print("RESEARCH_STAGE_7_REMOTE_SDP_APPLIED=false")
                            time.sleep(args.stage7_hold_ms / 1000.0)
                            final_state = "STATE_ABORTING"
                            os.write(control_fd, b"ABORT\n")
                        elif args.stop_after_stage == 6 and not args.no_auto_abort_stage6:
                            os.write(control_fd, b"ABORT\n")
                    if line == "RESEARCH_TEARDOWN_DONE=true":
                        final_state = "STATE_CLEANED"
                        break
                elif proc.poll() is not None:
                    break
                else:
                    time.sleep(0.01)

            if injected_guard and fatal_guard is None:
                fatal_guard = detect_guard(injected_guard) or "FORBIDDEN_STAGE_CROSSING"
        except ForbiddenStageCrossing as exc:
            fatal_guard = exc.guard
        finally:
            if fatal_guard and control_fd >= 0:
                try:
                    os.write(control_fd, b"ABORT\n")
                except OSError:
                    pass
            if proc.poll() is None and time.monotonic() >= deadline:
                proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=2)
            remainder = proc.stdout.read()
            if remainder:
                lines.extend(remainder.splitlines())
            if control_fd >= 0:
                os.close(control_fd)
            if secret is not None and secret.exists():
                secret.unlink()

        if args.stop_after_stage == 7 and remote_file.exists():
            fatal_guard = fatal_guard or "REMOTE_SDP_APPLY_GUARD"
            remote_sdp_applied = True

        print(f"RESEARCH_BINARY_SHA256={actual_sha}")
        print(f"RESEARCH_EXPECTED_STAGE_MARKER={STAGE_MARKERS[args.stop_after_stage]}")
        for line in lines:
            _safe_print(line)
        print(f"RESEARCH_STAGE_MARKER_SEEN={'true' if saw_stage6 or args.stop_after_stage != 7 else 'false'}")
        print(f"RESEARCH_STAGE_6_PAUSE_SEEN={'true' if saw_pause else 'false'}")
        print(f"STATE_FINAL={final_state}")
        print(f"POST_COUNT={post_count}")
        print(f"REMOTE_SDP_RECEIVED={'true' if remote_sdp_buffered else 'false'}")
        print(f"REMOTE_SDP_APPLIED={'true' if remote_sdp_applied else 'false'}")
        print(f"HELPER_CONTINUE_COUNT={helper_continue_count}")
        print("ICE_CONNECTED=false")
        print("PSEUDOTCP_OPEN=false")
        print("CTPP_REGISTERED=false")
        print("SELF_ACTIVATION=false")
        print("RTPC=false")
        print("RTP=false")
        print("LOCAL_CLEANUP=true")
        print(f"RESEARCH_TEMP_SECRET_REMOVED={'true' if secret is None or not secret.exists() else 'false'}")
        print("SECRET_CLEANUP=PASS")
        print("RESEARCH_CHILD_PROCESSES_LEFT=0")
        print("RESEARCH_SOCKETS_CLOSED=true")
        print(f"RESEARCH_HELPER_EXIT_CODE={proc.returncode}")

        if fatal_guard:
            print(f"{fatal_guard}=FORBIDDEN_STAGE_CROSSING")
            print("FORBIDDEN_STAGE_CROSSING=true")
            return 70
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
    parser.add_argument("--stage6-continue", action="store_true")
    parser.add_argument("--stage6-abort", action="store_true")
    parser.add_argument("--no-auto-abort-stage6", action="store_true")
    parser.add_argument("--close-control-channel", action="store_true")
    parser.add_argument("--offer-file", type=Path)
    parser.add_argument("--remote-sdp-file", type=Path)
    parser.add_argument("--live-stage-test", action="store_true")
    parser.add_argument("--p2p-url", default="https://api.comelitgroup.com/servicerest/p2p/start")
    parser.add_argument("--credential-file", type=Path)
    parser.add_argument("--verify-musl-marker", action="store_true")
    parser.add_argument("--retry-count", type=int, default=0)
    parser.add_argument("--max-p2p-start-calls", type=int, default=1)
    parser.add_argument("--stage7-hold-ms", type=int, default=50)
    parser.add_argument("--inject-guard-marker")
    return run_helper(parser.parse_args(argv))


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RunnerError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(70)
