"""P116 R41 v4 -- safe in-memory cursor for one persistent filtered logcat stream.

This module is offline-safe: it opens no process, socket or device.  A live runner owns the
single long-lived ``adb logcat`` process and passes each textual line to ``SafeLogEventBuffer``.

The attempt boundary is NOT an adb ``-T`` timestamp.  Freshness is represented only by the
host-local monotonically increasing sequence assigned to accepted, reduced safe events in this
one uninterrupted stream.  The runner captures ``PRE_PAUSE_LOG_CURSOR`` immediately before the
listener stop request; only events with a larger sequence are eligible for R40H freshness.

Raw logcat lines are never retained.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

_LOG_MODEL_PATH = Path(__file__).resolve().parent / "entrance_p116_r40h_registration_log_model.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:  # pragma: no cover
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(spec.name, module)
    spec.loader.exec_module(module)
    return module


_log_model = _load(_LOG_MODEL_PATH, "p116_r40h_registration_log_model_dep_from_r41_v4")

# Android logcat "-v brief" is normally "I/Tag( pid): message".
# Some builds omit the pid decoration; accept both shapes, but only the two load-bearing tags.
_BRIEF_WITH_PID_RE = re.compile(
    r"^[VDIWEF]/(?P<tag>[A-Za-z0-9_.-]+)\(\s*\d+\):\s?(?P<message>.*)$"
)
_BRIEF_NO_PID_RE = re.compile(
    r"^[VDIWEF]/(?P<tag>[A-Za-z0-9_.-]+):\s?(?P<message>.*)$"
)
_ALLOWED_TAGS = frozenset({"ComelitStatus", "ViperSocketReaderRun"})


def parse_brief_logcat_line(line: str) -> tuple[str, str] | None:
    """Return ``(tag, message)`` for one allowed brief-format line, else ``None``.

    No timestamp, pid or raw line is returned or stored.
    """

    text = line.rstrip("\r\n")
    match = _BRIEF_WITH_PID_RE.match(text) or _BRIEF_NO_PID_RE.match(text)
    if match is None:
        return None
    tag = match.group("tag")
    if tag not in _ALLOWED_TAGS:
        return None
    return tag, match.group("message")


class SafeLogEventBuffer:
    """Store only R40H ``ReducedLogEvent`` objects and a host-local sequence."""

    def __init__(self) -> None:
        self._events: list[object] = []
        self._monotonic_seq = 0

    @property
    def cursor(self) -> int:
        return self._monotonic_seq

    @property
    def event_count(self) -> int:
        return len(self._events)

    def ingest_brief_line(self, line: str) -> bool:
        parsed = parse_brief_logcat_line(line)
        if parsed is None:
            return False

        tag, message = parsed
        next_seq = self._monotonic_seq + 1
        reduced = _log_model.reduce_raw_line(tag, message, next_seq)
        if reduced is None:
            return False

        self._monotonic_seq = next_seq
        self._events.append(reduced)
        return True

    def capture_cursor(self) -> int:
        return self._monotonic_seq

    def evaluate_after(self, pre_pause_log_cursor: int):
        return _log_model.evaluate_fresh_registration(
            tuple(self._events),
            pre_pause_log_cursor=pre_pause_log_cursor,
        )

    def safe_snapshot(self) -> tuple[object, ...]:
        """Return only reduced safe events; never raw log text."""
        return tuple(self._events)
