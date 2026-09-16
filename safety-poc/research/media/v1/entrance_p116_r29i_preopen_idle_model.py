#!/usr/bin/env python3
"""Deterministic offline model for P116/R29I waiting-for-ring ownership."""
from __future__ import annotations

from dataclasses import dataclass

from entrance_p116_r29h_lifetime_model import LifetimeError, R29HLifetimeModel


@dataclass
class R29IPreOpenIdleModel(R29HLifetimeModel):
    registered_ready: bool = False
    waiting_for_ring: bool = False
    transport_alive: bool = True
    legacy_signaling_timeout_armed: bool = False
    runner_ring_timeout_active: bool = False

    def ready(self) -> None:
        super().ready()
        self.registered_ready = True
        self.waiting_for_ring = True
        self.transport_alive = True
        # R29I does not arm the old self-activation transaction timeout at
        # registration.  The outer runner owns the bounded human ring window.
        self.legacy_signaling_timeout_armed = False
        self.runner_ring_timeout_active = True

    def advance_waiting_for_ring(self, duration_ms: int) -> None:
        if duration_ms < 0:
            raise LifetimeError("NEGATIVE_IDLE_DURATION")
        if not self.registered_ready or not self.waiting_for_ring:
            raise LifetimeError("NOT_WAITING_FOR_RING")
        self.now_ms += duration_ms

    def entrance_call_init(self) -> None:
        super().entrance_call_init()
        self.waiting_for_ring = False
        self.runner_ring_timeout_active = False

    def transport_hard_failure(self) -> None:
        if self.open_sent_count == 0:
            self.transport_alive = False
            self.process_valid = False
            self.controlled_exit = True
            self.abort_class = "TRANSPORT_HARD_FAILURE_PRE_OPEN"
            self.terminal_reason = self.abort_class
            return
        super().transport_hard_failure()

    def registration_hard_failure(self) -> None:
        if self.open_sent_count == 0:
            self.transport_alive = False
            self.process_valid = False
            self.controlled_exit = True
            self.abort_class = "REGISTRATION_HARD_FAILURE_PRE_OPEN"
            self.terminal_reason = self.abort_class
            return
        super().transport_hard_failure()

    def evidence(self) -> dict[str, object]:
        evidence = super().evidence()
        evidence.update(
            {
                "REGISTERED_READY": self.registered_ready,
                "WAITING_FOR_RING": self.waiting_for_ring,
                "TRANSPORT_ALIVE": self.transport_alive,
                "LEGACY_SIGNALING_TIMEOUT_ARMED": self.legacy_signaling_timeout_armed,
                "RUNNER_RING_TIMEOUT_ACTIVE": self.runner_ring_timeout_active,
            }
        )
        return evidence
