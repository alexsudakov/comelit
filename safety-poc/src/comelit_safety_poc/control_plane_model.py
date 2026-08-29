from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ControlState(str, Enum):
    CLOSED = "CLOSED"
    OPEN_REQUESTED = "OPEN_REQUESTED"
    OPENED = "OPENED"
    CLOSE_REQUESTED = "CLOSE_REQUESTED"
    UNKNOWN = "UNKNOWN"


class ControlOutcome(str, Enum):
    PROVEN_NOT_OPENED = "PROVEN_NOT_OPENED"
    OPENED = "OPENED"
    REJECTED = "REJECTED"
    AMBIGUOUS = "AMBIGUOUS"


@dataclass(frozen=True)
class ChannelBinding:
    channel_name: str
    channel_id: int

    def __post_init__(self) -> None:
        if self.channel_name != "CTPP":
            raise ValueError("Door transaction requires CTPP channel")
        if self.channel_id <= 0:
            raise ValueError("channel_id must be positive")


@dataclass(frozen=True)
class ControlEvidence:
    outcome: ControlOutcome
    state: ControlState
    binding: ChannelBinding | None
    protocol_acknowledged: bool = False
    physical_effect_asserted: bool = False

    def __post_init__(self) -> None:
        if self.physical_effect_asserted:
            raise ValueError("control-plane evidence cannot assert physical effect")
        if self.outcome == ControlOutcome.OPENED:
            if self.state != ControlState.OPENED or self.binding is None:
                raise ValueError("OPENED evidence requires an opened channel binding")
        elif self.binding is not None:
            raise ValueError("non-opened evidence cannot carry an active binding")
        if self.protocol_acknowledged and self.outcome != ControlOutcome.OPENED:
            raise ValueError("protocol ACK is meaningful only for OPENED outcome")


@dataclass
class SyntheticCtppControlPlane:
    """Pure fixture model. It never imports or calls a network transport."""

    channel_id: int = 7449
    open_outcome: ControlOutcome = ControlOutcome.OPENED
    close_ambiguous: bool = False
    open_calls: int = 0
    close_calls: int = 0
    state: ControlState = ControlState.CLOSED

    def open_once(self) -> ControlEvidence:
        self.open_calls += 1
        if self.open_calls > 1:
            raise AssertionError("CTPP open attempted more than once")
        self.state = ControlState.OPEN_REQUESTED
        if self.open_outcome == ControlOutcome.PROVEN_NOT_OPENED:
            self.state = ControlState.CLOSED
            return ControlEvidence(self.open_outcome, self.state, None)
        if self.open_outcome == ControlOutcome.REJECTED:
            self.state = ControlState.CLOSED
            return ControlEvidence(self.open_outcome, self.state, None)
        if self.open_outcome == ControlOutcome.AMBIGUOUS:
            self.state = ControlState.UNKNOWN
            return ControlEvidence(self.open_outcome, self.state, None)
        if self.open_outcome != ControlOutcome.OPENED:
            raise AssertionError(f"unhandled outcome: {self.open_outcome}")
        self.state = ControlState.OPENED
        return ControlEvidence(
            outcome=ControlOutcome.OPENED,
            state=self.state,
            binding=ChannelBinding("CTPP", self.channel_id),
            protocol_acknowledged=True,
        )

    def close_once(self) -> ControlState:
        self.close_calls += 1
        if self.close_calls > 1:
            raise AssertionError("CTPP close attempted more than once")
        if self.state != ControlState.OPENED:
            raise ValueError("CTPP close requires OPENED state")
        self.state = ControlState.CLOSE_REQUESTED
        self.state = ControlState.UNKNOWN if self.close_ambiguous else ControlState.CLOSED
        return self.state
