#!/usr/bin/env python3
"""Deterministic P116/R29H candidate lifetime model.

This is an offline model of the research candidate contract only. It performs
no network I/O and models the R29G race by firing the inherited entrance
signaling timeout inside the post-OPEN observation window.
"""
from __future__ import annotations

from dataclasses import dataclass, field


class LifetimeError(RuntimeError):
    """Raised when the modeled candidate violates a fail-closed invariant."""


@dataclass
class R29HLifetimeModel:
    call_init: bool = False
    open_sent_count: int = 0
    stop_sent_count: int = 0
    observation_started_ms: int | None = None
    observation_ended_ms: int | None = None
    now_ms: int = 0
    waiting_for_stop: bool = False
    process_valid: bool = True
    controlled_exit: bool = False
    cleanup_done: bool = False
    deferred_paths: list[str] = field(default_factory=list)
    abort_class: str | None = None
    terminal_reason: str | None = None

    def ready(self) -> None:
        self.now_ms = 0
        self.terminal_reason = None

    def entrance_call_init(self) -> None:
        if self.terminal_reason:
            raise LifetimeError("CALL_INIT_AFTER_TERMINAL")
        self.call_init = True

    def send_open(self) -> None:
        if not self.call_init:
            raise LifetimeError("OPEN_BEFORE_CALL_INIT")
        if self.open_sent_count:
            raise LifetimeError("OPEN_RETRY_FORBIDDEN")
        self.open_sent_count = 1
        self.observation_started_ms = self.now_ms

    def inherited_signaling_timeout(self) -> None:
        if not self.call_init or self.open_sent_count == 0:
            self.terminal_reason = "ENTRANCE_SIGNALING_TIMEOUT_BEFORE_OPEN"
            self.process_valid = False
            return
        if not self.waiting_for_stop and self.stop_sent_count == 0:
            self.deferred_paths.append("ENTRANCE_SIGNALING_TIMEOUT")
            return
        self.terminal_reason = "ENTRANCE_SIGNALING_TIMEOUT_AFTER_STOP"

    def transport_hard_failure(self) -> None:
        self.abort_class = "TRANSPORT_HARD_FAILURE_AFTER_OPEN"
        if self.open_sent_count and self.stop_sent_count == 0:
            self.send_stop(send_ok=True)
        self.process_valid = False
        self.controlled_exit = True
        self.terminal_reason = self.abort_class

    def observation_timer_failure(self) -> None:
        if self.open_sent_count:
            self.abort_class = "OBSERVATION_TIMER_CALLBACK_FAILURE"
            if self.stop_sent_count == 0:
                self.send_stop(send_ok=True)
        self.process_valid = False
        self.controlled_exit = True
        self.terminal_reason = self.abort_class

    def advance_to_observation_end(self, duration_ms: int = 10_000) -> None:
        if self.observation_started_ms is None:
            raise LifetimeError("OBSERVATION_WITHOUT_OPEN")
        if duration_ms <= 0 or duration_ms > 10_500:
            raise LifetimeError("OBSERVATION_DURATION_OUT_OF_BOUNDS")
        self.now_ms = self.observation_started_ms + duration_ms
        self.observation_ended_ms = self.now_ms
        self.waiting_for_stop = True

    def send_stop(self, *, send_ok: bool = True) -> None:
        if self.open_sent_count != 1:
            raise LifetimeError("STOP_BEFORE_OPEN")
        if self.stop_sent_count:
            raise LifetimeError("SECOND_STOP_FORBIDDEN")
        self.stop_sent_count = 1
        self.waiting_for_stop = False
        if not send_ok:
            self.abort_class = "STOP_SEND_FAILURE"
            self.terminal_reason = self.abort_class

    def unexpected_exit(self) -> None:
        self.process_valid = False
        self.terminal_reason = "UNEXPECTED_EARLY_CANDIDATE_EXIT"

    def cleanup(self) -> None:
        self.cleanup_done = True
        if self.stop_sent_count == 1:
            self.controlled_exit = True
            self.process_valid = True
            self.terminal_reason = self.terminal_reason or "CONTROLLED_EXIT"

    @property
    def rtp_window_fully_observed(self) -> bool:
        return (
            self.observation_started_ms is not None
            and self.observation_ended_ms is not None
            and 0 < self.observation_ended_ms - self.observation_started_ms <= 10_500
        )

    def evidence(self) -> dict[str, object]:
        return {
            "OPEN_SENT": self.open_sent_count,
            "MAIN_LOOP_EXIT_BEFORE_OBSERVATION_END": False
            if self.deferred_paths
            else self.terminal_reason is not None and not self.rtp_window_fully_observed,
            "R29C_RTP_OBSERVATION_ENDED": self.observation_ended_ms is not None,
            "RTP_WINDOW_FULLY_OBSERVED": self.rtp_window_fully_observed,
            "R29C_WAITING_FOR_STOP": self.waiting_for_stop,
            "STOP_SENT_COUNT": self.stop_sent_count,
            "PROCESS_REMAINS_VALID_THROUGH_STOP": self.process_valid,
            "CONTROLLED_EXIT": self.controlled_exit,
            "ABORT_CLASS": self.abort_class,
            "DEFERRED_PATHS": tuple(self.deferred_paths),
        }


def reproduce_r29g_sequence() -> dict[str, object]:
    model = R29HLifetimeModel()
    model.ready()
    model.entrance_call_init()
    model.send_open()
    model.inherited_signaling_timeout()
    before_end = model.evidence()
    model.advance_to_observation_end()
    at_end = model.evidence()
    model.send_stop()
    model.cleanup()
    final = model.evidence()
    return {"before_end": before_end, "at_end": at_end, "final": final}
