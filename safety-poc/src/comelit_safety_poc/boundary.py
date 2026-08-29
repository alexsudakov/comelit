from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from .errors import AmbiguousSend, DefinitelyNotSent, RealTransportDisabled
from .model import SendReceipt


class BoundaryOutcome(str, Enum):
    PROVEN_NOT_SENT = "PROVEN_NOT_SENT"
    REJECTED = "REJECTED"
    ACCEPTED_NO_ACK = "ACCEPTED_NO_ACK"
    ACKED = "ACKED"
    AMBIGUOUS = "AMBIGUOUS"


@dataclass(frozen=True)
class TransportRequest:
    operation_id: str
    target: str
    attempt_number: int = 1

    def __post_init__(self) -> None:
        if not self.operation_id:
            raise ValueError("operation_id is required")
        if not self.target:
            raise ValueError("target is required")
        if self.attempt_number != 1:
            raise ValueError("safety contract permits exactly one transport attempt")


@dataclass(frozen=True)
class BoundaryEvidence:
    outcome: BoundaryOutcome
    detail: str
    protocol_acknowledged: bool
    physical_effect_asserted: bool = False

    def __post_init__(self) -> None:
        if self.physical_effect_asserted:
            raise ValueError("transport evidence must not assert physical actuator state")
        if self.protocol_acknowledged != (self.outcome == BoundaryOutcome.ACKED):
            raise ValueError("protocol_acknowledged must match ACKED outcome exactly")


class TransportBoundary(Protocol):
    def attempt_once(self, request: TransportRequest) -> BoundaryEvidence: ...


class BoundaryTransportAdapter:
    """Adapts a typed one-attempt boundary to the executor Transport protocol.

    This class contains no network implementation.  It preserves the executor's
    conservative semantics while making the future backend contract explicit.
    """

    def __init__(self, boundary: TransportBoundary):
        self.boundary = boundary
        self.last_request: TransportRequest | None = None
        self.last_evidence: BoundaryEvidence | None = None

    def send_once(self, *, operation_id: str, target: str) -> SendReceipt:
        request = TransportRequest(operation_id=operation_id, target=target, attempt_number=1)
        self.last_request = request
        evidence = self.boundary.attempt_once(request)
        self.last_evidence = evidence

        if evidence.outcome == BoundaryOutcome.PROVEN_NOT_SENT:
            raise DefinitelyNotSent(evidence.detail)
        if evidence.outcome == BoundaryOutcome.AMBIGUOUS:
            raise AmbiguousSend(evidence.detail)
        if evidence.outcome == BoundaryOutcome.REJECTED:
            return SendReceipt(accepted=False, acked=False, detail=evidence.detail)
        if evidence.outcome == BoundaryOutcome.ACCEPTED_NO_ACK:
            return SendReceipt(accepted=True, acked=False, detail=evidence.detail)
        if evidence.outcome == BoundaryOutcome.ACKED:
            return SendReceipt(accepted=True, acked=True, detail=evidence.detail)
        raise AssertionError(f"unhandled boundary outcome: {evidence.outcome}")


@dataclass
class MockBoundary:
    """Deterministic offline implementation of the typed transport boundary."""

    outcome: BoundaryOutcome = BoundaryOutcome.ACKED
    calls: int = 0
    last_request: TransportRequest | None = None

    def attempt_once(self, request: TransportRequest) -> BoundaryEvidence:
        self.calls += 1
        self.last_request = request
        if self.calls > 1:
            raise AssertionError("boundary called more than once")
        detail = f"mock boundary outcome={self.outcome.value}"
        return BoundaryEvidence(
            outcome=self.outcome,
            detail=detail,
            protocol_acknowledged=(self.outcome == BoundaryOutcome.ACKED),
            physical_effect_asserted=False,
        )


class DisabledBoundary:
    """Fail-closed placeholder for a future real backend. No network I/O."""

    def attempt_once(self, request: TransportRequest) -> BoundaryEvidence:
        raise RealTransportDisabled(
            "real Comelit/access-control boundary is intentionally not implemented"
        )
