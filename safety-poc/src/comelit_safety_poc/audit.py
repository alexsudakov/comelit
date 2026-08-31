from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .model import Operation, State

AUDIT_EVENT_TYPES = frozenset(
    {
        "operation_created",
        "operation_recovered",
        "transport_attempt",
        "transport_outcome",
        "audit_sink_verify",
        "preflight",
    }
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


@dataclass(frozen=True)
class AuditEntry:
    ts: str
    operation_id: str
    event_type: str
    state: str
    detail: str = ""
    target: str = ""
    attempt_number: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class AuditSink:
    """Append-only durable audit journal.

    Every record is written with fsync before the write is acknowledged, so a
    crash cannot silently drop an already-reported transition.  The journal is
    append-only JSONL; no in-place mutation API exists.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_append_only()

    def _ensure_append_only(self) -> None:
        if self.path.exists():
            mode = self.path.stat().st_mode & 0o777
            if mode & 0o222 == 0:
                raise ValueError("audit journal must be writable (append-only)")

    def _append(self, entry: AuditEntry) -> None:
        line = json.dumps(entry.to_dict(), sort_keys=True) + "\n"
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(line)
            fh.flush()
            os.fsync(fh.fileno())

    def record_transition(self, operation: Operation, event_type: str, detail: str = "") -> None:
        if event_type not in AUDIT_EVENT_TYPES:
            raise ValueError(f"unexpected audit event type: {event_type}")
        self._append(
            AuditEntry(
                ts=utc_now(),
                operation_id=operation.operation_id,
                event_type=event_type,
                state=operation.state.value,
                detail=detail,
                target=operation.target,
                attempt_number=1,
            )
        )

    def record_raw(self, entry: AuditEntry) -> None:
        if entry.event_type not in AUDIT_EVENT_TYPES:
            raise ValueError(f"unexpected audit event type: {entry.event_type}")
        self._append(entry)

    def verify_durable(self) -> bool:
        """Reopen the journal and reparse every line; returns True only when all
        records are valid JSON and the final line ends with a newline (i.e. the
        last fsync was fully flushed)."""
        if not self.path.is_file():
            return False
        count = 0
        with self.path.open("r", encoding="utf-8") as fh:
            data = fh.read()
        if not data.endswith("\n"):
            return False
        for line in data.splitlines():
            obj = json.loads(line)
            if obj.get("event_type") not in AUDIT_EVENT_TYPES:
                return False
            if "ts" not in obj or "operation_id" not in obj or "state" not in obj:
                return False
            count += 1
        return count > 0

    def entries(self) -> list[AuditEntry]:
        if not self.path.is_file():
            return []
        out: list[AuditEntry] = []
        with self.path.open("r", encoding="utf-8") as fh:
            for line in fh:
                raw = json.loads(line)
                out.append(
                    AuditEntry(
                        ts=raw["ts"],
                        operation_id=raw["operation_id"],
                        event_type=raw["event_type"],
                        state=raw["state"],
                        detail=raw.get("detail", ""),
                        target=raw.get("target", ""),
                        attempt_number=raw.get("attempt_number"),
                    )
                )
        return out


class AuditedExecutorTransport:
    """Wraps a transport so every attempt and outcome is recorded durably."""

    def __init__(self, transport, sink: AuditSink):
        self.transport = transport
        self.sink = sink

    def send_once(self, *, operation_id: str, target: str):
        self.sink.record_raw(
            AuditEntry(
                ts=utc_now(),
                operation_id=operation_id,
                event_type="transport_attempt",
                state=State.SEND_ARMED.value,
                detail="single transport attempt started",
                target=target,
                attempt_number=1,
            )
        )
        try:
            receipt = self.transport.send_once(operation_id=operation_id, target=target)
        except BaseException as exc:
            self.sink.record_raw(
                AuditEntry(
                    ts=utc_now(),
                    operation_id=operation_id,
                    event_type="transport_outcome",
                    state=State.UNKNOWN_OUTCOME.value,
                    detail=f"transport raised {type(exc).__name__}; outcome ambiguous",
                    target=target,
                    attempt_number=1,
                )
            )
            raise
        self.sink.record_raw(
            AuditEntry(
                ts=utc_now(),
                operation_id=operation_id,
                event_type="transport_outcome",
                state=State.SENT.value if receipt.accepted else State.FAILED_SAFE.value,
                detail=f"accepted={receipt.accepted} acked={receipt.acked}",
                target=target,
                attempt_number=1,
            )
        )
        return receipt
