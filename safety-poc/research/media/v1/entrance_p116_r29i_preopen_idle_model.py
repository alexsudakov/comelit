#!/usr/bin/env python3
"""Deterministic offline model for P116/R29I waiting-for-ring ownership."""
from __future__ import annotations

from dataclasses import dataclass

from entrance_p116_r29h_lifetime_model import LifetimeError, R29HLifetimeModel


@dataclass
class R29IPreOpenIdleModel(R29HLifetimeModel):
    registered_ready: bool = False
    waiting_for_ring: bool = False
    idle_timeout_deferred_count: int = 0
    transport_alive: bool = True

    def ready(self) -> None:
        super().ready()
        self.registered_ready = True
        self.waiting_for_ring = True
        self.transport_alive = True

    def advance_waiting_for_ring(self, duration_ms: int) -> None:
        if duration_ms < 0:
            raise LifetimeError("NEGATIVE_IDLE_DURATION")
        if not self.registered_ready or not self.waiting_for_ring:
            raise LifetimeError("NOT_WAITING_FOR_RING")
        self.now_ms += duration_ms

    def inherited_signaling_timeout(self) -> None:
        if (
            self.registered_ready
            and self.waiting_for_ring
            and not self.call_init
            and self.open_sent_count == 0
        ):
            self.idle_timeout_deferred_count += 1
            return
        super().inherited_signaling_timeout()

    def entrance_call_init(self) -> None:
        super().entrance_call_init()
        self.waiting_for_ring = False

    def transport_hard_failure(self) -> None:
        if self.open_sent_count == 0:
            self.transport_alive = False
            self.process_valid = False
            self.controlled_exit = True
            self.abort_class = "TRANSPORT_HARD_FAILURE_PRE_OPEN"
            self.terminal_reason = self.abort_class
            return
        super().transport_hard_failure()

    def evidence(self) -> dict[str, object]:
        evidence = super().evidence()
        evidence.update(
            {
                "REGISTERED_READY": self.registered_ready,
                "WAITING_FOR_RING": self.waiting_for_ring,
                "IDLE_TIMEOUT_DEFERRED_COUNT": self.idle_timeout_deferred_count,
                "TRANSPORT_ALIVE": self.transport_alive,
            }
        )
        return evidence
