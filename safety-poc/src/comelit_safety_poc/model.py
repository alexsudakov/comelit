from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class State(str, Enum):
    PREPARED = "PREPARED"
    SEND_ARMED = "SEND_ARMED"
    SENT = "SENT"
    ACKED = "ACKED"
    FAILED_SAFE = "FAILED_SAFE"
    UNKNOWN_OUTCOME = "UNKNOWN_OUTCOME"


TERMINAL_STATES = {State.ACKED, State.FAILED_SAFE, State.UNKNOWN_OUTCOME}


@dataclass(frozen=True)
class Operation:
    operation_id: str
    target: str
    state: State
    created_at: str
    updated_at: str
    detail: str | None = None


@dataclass(frozen=True)
class SendReceipt:
    """Result returned by a transport after exactly one send attempt.

    accepted=True means the transport cannot prove that no side effect occurred.
    acked=True is a protocol-level acknowledgement only; it does not claim a
    physical actuator changed state.
    """

    accepted: bool
    acked: bool
    detail: str
