from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .errors import AmbiguousSend, DefinitelyNotSent, RealTransportDisabled
from .model import SendReceipt


class Transport(Protocol):
    def send_once(self, *, operation_id: str, target: str) -> SendReceipt: ...


@dataclass
class MockTransport:
    """Deterministic backend for offline tests only."""

    scenario: str = "ack"
    calls: int = 0

    def send_once(self, *, operation_id: str, target: str) -> SendReceipt:
        self.calls += 1
        if self.calls > 1:
            raise AssertionError("mock transport called more than once for one executor instance")

        if self.scenario == "definitely_not_sent":
            raise DefinitelyNotSent("mock proved no send occurred")
        if self.scenario == "timeout_after_accept":
            raise AmbiguousSend("mock accepted send then lost outcome")
        if self.scenario == "rejected":
            return SendReceipt(accepted=False, acked=False, detail="mock rejected before side effect")
        if self.scenario == "accepted_no_ack":
            return SendReceipt(accepted=True, acked=False, detail="mock accepted; no ack")
        if self.scenario == "ack":
            return SendReceipt(accepted=True, acked=True, detail="mock protocol ack")
        raise ValueError(f"unknown mock scenario: {self.scenario}")


class DisabledRealTransport:
    """Explicit fail-closed placeholder. It performs no network I/O."""

    def send_once(self, *, operation_id: str, target: str) -> SendReceipt:
        raise RealTransportDisabled(
            "real Comelit/access-control transport is intentionally not implemented in this PoC"
        )
