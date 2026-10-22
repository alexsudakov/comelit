"""Safe host-local cursor for one persistent, filtered R41 logcat stream.

The live runner owns the process.  This module only reduces allowed lines to the
closed R40H event model; it never retains a raw log line, timestamp, PID, serial,
or device identifier.
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

_BRIEF_WITH_PID_RE = re.compile(
    r"^[VDIWEF]/(?P<tag>[A-Za-z0-9_.-]+)\(\s*\d+\):\s?(?P<message>.*)$"
)
_BRIEF_NO_PID_RE = re.compile(
    r"^[VDIWEF]/(?P<tag>[A-Za-z0-9_.-]+):\s?(?P<message>.*)$"
)
_ALLOWED_TAGS = frozenset({"ComelitStatus", "ViperSocketReaderRun"})
MAX_REDUCED_EVENTS = 4096


def parse_brief_logcat_line(line: str) -> tuple[str, str] | None:
    """Return only an allowed tag and message, otherwise ``None``."""

    text = line.rstrip("\r\n")
    match = _BRIEF_WITH_PID_RE.fullmatch(text) or _BRIEF_NO_PID_RE.fullmatch(text)
    if match is None or match.group("tag") not in _ALLOWED_TAGS:
        return None
    return match.group("tag"), match.group("message")


class SafeLogEventBuffer:
    """Keep only reduced R40H events and their local sequence."""

    def __init__(self) -> None:
        self._events: list[object] = []
        self._monotonic_seq = 0
        self._overflowed = False

    @property
    def healthy(self) -> bool:
        return not self._overflowed

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
        reduced = _log_model.reduce_raw_line(tag, message, self._monotonic_seq + 1)
        if reduced is None:
            return False
        if len(self._events) >= MAX_REDUCED_EVENTS:
            self._overflowed = True
            return False
        self._monotonic_seq += 1
        self._events.append(reduced)
        return True

    def capture_cursor(self) -> int:
        return self._monotonic_seq

    def evaluate_after(self, pre_pause_log_cursor: int):
        return _log_model.evaluate_fresh_registration(
            tuple(self._events), pre_pause_log_cursor=pre_pause_log_cursor
        )

    def safe_snapshot(self) -> tuple[object, ...]:
        return tuple(self._events)
