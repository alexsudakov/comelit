#!/usr/bin/env python3
"""Standalone read-only observer for Comelit listener evidence in HA logs.

The deployment exposes logs-follow as the only useful content channel.  This
observer consumes a log file or stream capture; it never calls HA services,
never opens sockets, and never talks to Comelit.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import re
import sys
from typing import Iterable


READY_TRUE = ("listener_ready': True", '"listener_ready": true', "listener_ready=true", "V4_RING_LISTENER_READY=true")
READY_FALSE = (
    "listener_ready': False",
    '"listener_ready": false',
    "listener_ready=false",
    "listener_status': 'starting'",
    '"listener_status": "starting"',
    "listener_status=starting",
)
RESEARCH_HELPER_MARKERS = ("RESEARCH_STAGE_", "RESEARCH_STAGE_6_LOCAL_OFFER_READY", "RESEARCH_STAGE_INTERLOCK")
PROCESS_RESTART_MARKERS = ("Home Assistant Core restarted", "Starting Home Assistant", "comelit integration setup")
RECONNECT_MARKERS = ("listener reconnect", "ViperSocketReaderRun:E", "native_exit", "Comelit ring listener READY")
PID_RE = re.compile(r"(?:listener_pid|process_pid|pid)[:=]\s*['\"]?([0-9]+)")
SOCKET_RE = re.compile(r"(?:socket_fingerprint|socket_inode|transport_id)[:=]\s*['\"]?([A-Za-z0-9_:\-\[\].]+)")
ERROR_RE = re.compile(r"(?:last_error|listener_error)[:=]\s*['\"]?([^,'\"}]+)")


@dataclass
class Observation:
    ready_events: int = 0
    non_ready_events: int = 0
    recovery_events: int = 0
    observer_generation: int = 0
    last_ready: bool | None = None
    last_error: str = "NONE"
    pid_values: list[str] | None = None
    socket_values: list[str] | None = None
    research_helper_lines: int = 0

    def __post_init__(self) -> None:
        if self.pid_values is None:
            self.pid_values = []
        if self.socket_values is None:
            self.socket_values = []


def _contains_any(line: str, needles: Iterable[str]) -> bool:
    return any(needle in line for needle in needles)


def _safe(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "._:-[]" else "_" for ch in value)[:80] or "NONE"


def observe_lines(lines: Iterable[str]) -> dict[str, str]:
    obs = Observation()
    seen_non_ready = False
    last_pid: str | None = None
    last_socket: str | None = None

    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        if _contains_any(line, RESEARCH_HELPER_MARKERS):
            obs.research_helper_lines += 1
            continue

        if _contains_any(line, PROCESS_RESTART_MARKERS):
            obs.observer_generation += 1

        pid_match = PID_RE.search(line)
        if pid_match:
            pid = pid_match.group(1)
            obs.pid_values.append(pid)
            if last_pid is not None and pid != last_pid:
                obs.observer_generation += 1
            last_pid = pid

        socket_match = SOCKET_RE.search(line)
        if socket_match:
            socket = _safe(socket_match.group(1))
            obs.socket_values.append(socket)
            if last_socket is not None and socket != last_socket:
                obs.observer_generation += 1
            last_socket = socket

        error_match = ERROR_RE.search(line)
        if error_match:
            obs.last_error = _safe(error_match.group(1))

        ready = _contains_any(line, READY_TRUE)
        non_ready = _contains_any(line, READY_FALSE)
        if non_ready:
            obs.non_ready_events += 1
            obs.last_ready = False
            seen_non_ready = True
        if ready:
            obs.ready_events += 1
            if seen_non_ready:
                obs.recovery_events += 1
                obs.observer_generation += 1
                seen_non_ready = False
            if _contains_any(line, RECONNECT_MARKERS):
                obs.observer_generation += 1
            obs.last_ready = True

    pid_observable = bool(obs.pid_values)
    socket_observable = bool(obs.socket_values)
    out = {
        "LISTENER_READY_SOURCE": "logs-follow recorder state_changed attributes/native marker",
        "LISTENER_READY_OBSERVABLE": "true" if obs.ready_events or obs.non_ready_events else "false",
        "LISTENER_READY": "true" if obs.last_ready is True else "false" if obs.last_ready is False else "UNKNOWN",
        "LISTENER_READY_TRANSITIONS": str(obs.ready_events + obs.non_ready_events),
        "LISTENER_RECOVERY_OBSERVABLE": "true" if obs.recovery_events else "false",
        "LISTENER_LAST_ERROR": obs.last_error,
        "OBSERVER_RECONNECT_GENERATION": str(obs.observer_generation),
        "LISTENER_PID_OBSERVABLE": "true" if pid_observable else "false",
        "LISTENER_PROCESS_PID": obs.pid_values[-1] if pid_observable else "NOT_OBSERVABLE",
        "LISTENER_SOCKET_IDENTITY_OBSERVABLE": "true" if socket_observable else "false",
        "LISTENER_SOCKET_IDENTITY": obs.socket_values[-1] if socket_observable else "NOT_OBSERVABLE",
        "MISSING_CAPABILITY": (
            "read-only route exposing listener process pid and socket inode/transport identity"
            if not (pid_observable and socket_observable)
            else "NONE"
        ),
        "RESEARCH_HELPER_IGNORED_LINES": str(obs.research_helper_lines),
        "CONFLICT_DETECTION_SUFFICIENT": "false",
    }
    return out


def parse_key_value_lines(lines: Iterable[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in lines:
        line = raw.strip()
        if not line or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if re.fullmatch(r"[A-Z0-9_]+", key):
            out[key] = value
    return out


def read_key_value_capture(path: Path | None) -> dict[str, str]:
    if path is None:
        return {}
    if str(path) == "-":
        return parse_key_value_lines(sys.stdin)
    return parse_key_value_lines(path.read_text(encoding="utf-8").splitlines())


def _readable_identity(value: str | None) -> bool:
    return bool(value and value not in {"UNKNOWN", "NOT_OBSERVABLE", "NONE"})


def identity_observation(capture: dict[str, str]) -> dict[str, str]:
    if not capture:
        return {}
    generation = capture.get("LISTENER_PROCESS_GENERATION", "")
    fingerprint = capture.get("LISTENER_SOCKET_FINGERPRINT_SHA256", "")
    ready = capture.get("LISTENER_READY", "UNKNOWN") or "UNKNOWN"
    missing: list[str] = []
    if not _readable_identity(ready):
        missing.append("listener readiness")
    if not _readable_identity(generation):
        missing.append("listener process generation")
    if not _readable_identity(fingerprint):
        missing.append("listener socket fingerprint")
    return {
        "LISTENER_READY": ready,
        "LISTENER_PROCESS_GENERATION": generation or "NOT_OBSERVABLE",
        "LISTENER_SOCKET_FINGERPRINT": fingerprint or "NOT_OBSERVABLE",
        "LISTENER_PID_OBSERVABLE": "true" if _readable_identity(capture.get("LISTENER_PID")) else "false",
        "LISTENER_PROCESS_GENERATION_OBSERVABLE": "true" if _readable_identity(generation) else "false",
        "LISTENER_SOCKET_IDENTITY_OBSERVABLE": "true" if _readable_identity(fingerprint) else "false",
        "CONFLICT_DETECTION_SUFFICIENT": "true" if not missing else "false",
        "MISSING_CAPABILITY": ", ".join(missing) if missing else "NONE",
    }


def compare_identity_captures(before: dict[str, str], after: dict[str, str]) -> dict[str, str]:
    before_obs = identity_observation(before)
    after_obs = identity_observation(after)
    out = dict(after_obs)
    before_generation = before.get("LISTENER_PROCESS_GENERATION", "")
    after_generation = after.get("LISTENER_PROCESS_GENERATION", "")
    before_socket = before.get("LISTENER_SOCKET_FINGERPRINT_SHA256", "")
    after_socket = after.get("LISTENER_SOCKET_FINGERPRINT_SHA256", "")
    generation_readable = _readable_identity(before_generation) and _readable_identity(after_generation)
    socket_readable = _readable_identity(before_socket) and _readable_identity(after_socket)
    generation_changed = generation_readable and before_generation != after_generation
    socket_changed = socket_readable and before_socket != after_socket
    ready_recovered = before.get("LISTENER_READY") == "false" and after.get("LISTENER_READY") == "true"
    out.update(
        {
            "PROCESS_GENERATION_CHANGED": "true" if generation_changed else "false" if generation_readable else "UNKNOWN",
            "SOCKET_FINGERPRINT_CHANGED": "true" if socket_changed else "false" if socket_readable else "UNKNOWN",
            "LISTENER_RECOVERY_OBSERVED": "true" if ready_recovered or generation_changed or socket_changed else "false",
        }
    )
    return out


def sample(path: Path) -> dict[str, str]:
    if path.suffix == ".json":
        obj = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(obj, dict):
            lines = [json.dumps(obj, separators=(",", ":"))]
        elif isinstance(obj, list):
            lines = [json.dumps(item, separators=(",", ":")) for item in obj]
        else:
            lines = []
    else:
        lines = path.read_text(encoding="utf-8").splitlines()
    return observe_lines(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log-file", type=Path)
    parser.add_argument("--status-json", type=Path, help="compatibility alias for fixture input")
    parser.add_argument("--identity-file", type=Path, help="KEY=VALUE output from readonly-listener-identity, or '-' for stdin")
    parser.add_argument("--identity-before", type=Path, help="first KEY=VALUE listener identity capture")
    parser.add_argument("--identity-after", type=Path, help="second KEY=VALUE listener identity capture")
    args = parser.parse_args(argv)
    path = args.log_file or args.status_json
    if (args.identity_before is None) != (args.identity_after is None):
        parser.error("--identity-before and --identity-after must be supplied together")
    if args.identity_before and args.identity_after:
        out = compare_identity_captures(read_key_value_capture(args.identity_before), read_key_value_capture(args.identity_after))
    elif args.identity_file:
        out = identity_observation(read_key_value_capture(args.identity_file))
    elif path is not None:
        out = sample(path)
    else:
        parser.error("--log-file or --identity-file is required")
    for key, value in out.items():
        print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
