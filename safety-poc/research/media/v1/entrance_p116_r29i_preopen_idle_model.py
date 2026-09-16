#!/usr/bin/env python3
"""Deterministic P116/R29I pre-open idle lifetime model.

This model captures the research-only contract needed after the no-CALL_INIT
live attempt: once the persistent research listener is READY, the inherited
entrance signaling timeout must not terminate an otherwise healthy listener
merely because no human ring has arrived yet. Real transport/registration
failures remain fatal. No network I/O is performed here.
"""
from __future__ import annotations

from dataclasses import dataclass


class R29IModelError(RuntimeError):
    """Raised on invalid model transitions."""


@dataclass
class R29IPreopenIdleModel:
    ready_state: bool = False
    call_init: bool = False
    open_sent_count: int = 0
    now_ms: int = 0
    process_valid: bool = True
    inherited_idle_timeouts_suppressed: int = 0
    terminal_reason: str | None = None

    def ready(self) -> None:
        self.ready_state = True
        self.call_init = False
        self.open_sent_count = 0
        self.now_ms = 0
        self.process_valid = True
        self.terminal_reason = None

    def advance(self, duration_ms: int) -> None:
        if duration_ms < 0:
            raise R29IModelError("NEGATIVE_TIME")
        self.now_ms += duration_ms

    def inherited_signaling_timeout(self) -> None:
        if not self.ready_state or not self.process_valid:
            self.process_valid = False
            self.terminal_reason = "ENTRANCE_SIGNALING_TIMEOUT_NOT_READY"
            return
        if self.open_sent_count == 0:
            self.inherited_idle_timeouts_suppressed += 1
            return
        self.terminal_reason = "ENTRANCE_SIGNALING_TIMEOUT_AFTER_OPEN"

    def entrance_call_init(self) -> None:
        if not self.ready_state or not self.process_valid:
            raise R29IModelError("CALL_INIT_WITHOUT_LIVE_LISTENER")
        if self.call_init:
            raise R29IModelError("SECOND_CALL_INIT")
        self.call_init = True

    def send_open(self) -> None:
        if not self.call_init:
            raise R29IModelError("OPEN_BEFORE_CALL_INIT")
        if self.open_sent_count:
            raise R29IModelError("OPEN_RETRY_FORBIDDEN")
        self.open_sent_count = 1

    def transport_failure(self) -> None:
        self.process_valid = False
        self.terminal_reason = "TRANSPORT_FAILURE"

    def registration_failure(self) -> None:
        self.process_valid = False
        self.terminal_reason = "REGISTRATION_FAILURE"

    @property
    def waiting_for_ring(self) -> bool:
        return self.ready_state and self.process_valid and not self.call_init


def reproduce_long_idle_call_sequence() -> dict[str, object]:
    model = R29IPreopenIdleModel()
    model.ready()
    model.advance(30_000)
    model.inherited_signaling_timeout()
    after_30s = {
        "alive": model.process_valid,
        "waiting_for_ring": model.waiting_for_ring,
        "timeouts_suppressed": model.inherited_idle_timeouts_suppressed,
    }
    model.advance(30_000)
    model.entrance_call_init()
    model.send_open()
    after_call = {
        "alive": model.process_valid,
        "call_init": model.call_init,
        "open_sent_count": model.open_sent_count,
        "now_ms": model.now_ms,
    }
    return {"after_30s": after_30s, "after_call": after_call}
