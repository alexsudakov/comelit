#!/usr/bin/env python3
"""Deterministic lifetime model for P116/R29I waiting-for-ring ownership.

This module performs no network I/O. It models only the ownership decision added by
R29I so long-idle timing can be tested without sleeping or running a live candidate.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto


class Action(Enum):
    CONTINUE_WAITING_FOR_RING = auto()
    FAIL_CLOSED = auto()
    DEFER_TO_R29H_BOUNDED_SECTION = auto()


@dataclass(frozen=True)
class State:
    listener_registered_ready: bool = True
    call_transaction_created: bool = False
    call_transaction_active: bool = False
    open_sent: bool = False
    post_open_bounded_section: bool = False
    transport_healthy: bool = True
    registration_healthy: bool = True


def entrance_signaling_timeout(state: State) -> Action:
    """Return the R29I ownership decision for an inherited signaling timeout."""
    if not state.transport_healthy or not state.registration_healthy:
        return Action.FAIL_CLOSED
    if (
        state.listener_registered_ready
        and not state.call_transaction_created
        and not state.call_transaction_active
        and not state.open_sent
        and not state.post_open_bounded_section
    ):
        return Action.CONTINUE_WAITING_FOR_RING
    if state.open_sent or state.post_open_bounded_section:
        return Action.DEFER_TO_R29H_BOUNDED_SECTION
    return Action.FAIL_CLOSED


def simulate_idle_then_call(
    *,
    ring_window_seconds: int = 90,
    inherited_timeout_seconds: int = 30,
    call_at_seconds: int = 60,
) -> tuple[list[tuple[int, Action]], Action]:
    """Virtually exercise inherited timeouts before a call, then one post-call timeout.

    No wall-clock sleep is used. Every inherited timeout before CALL_INIT must leave the
    registered listener waiting. Once the call transaction exists, the next pre-OPEN
    timeout must fail closed.
    """
    if not 0 < call_at_seconds <= ring_window_seconds:
        raise ValueError("call_at_seconds must be inside ring window")
    events: list[tuple[int, Action]] = []
    state = State()
    t = inherited_timeout_seconds
    while t < call_at_seconds:
        events.append((t, entrance_signaling_timeout(state)))
        t += inherited_timeout_seconds
    post_call = State(call_transaction_created=True, call_transaction_active=True)
    return events, entrance_signaling_timeout(post_call)
