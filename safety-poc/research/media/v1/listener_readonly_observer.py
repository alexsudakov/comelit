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
    args = parser.parse_args(argv)
    path = args.log_file or args.status_json
    if path is None:
        parser.error("--log-file is required")
    for key, value in sample(path).items():
        print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
