from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .boundary import BoundaryEvidence, BoundaryOutcome, TransportRequest
from .control_plane_model import ControlOutcome, SyntheticCtppControlPlane


class TransactionStep(str, Enum):
    OPEN_CTPP = "OPEN_CTPP"
    INIT_A = "INIT_A"
    OPTIONAL_WAIT_A = "OPTIONAL_WAIT_A"
    COMMAND_PRIMARY = "COMMAND_PRIMARY"
    CONFIRM_PRIMARY = "CONFIRM_PRIMARY"
    INIT_B = "INIT_B"
    OPTIONAL_WAIT_B = "OPTIONAL_WAIT_B"
    COMMAND_FINAL = "COMMAND_FINAL"
    CONFIRM_FINAL = "CONFIRM_FINAL"
    CLOSE_CTPP = "CLOSE_CTPP"


DOOR_WRITE_STEPS = (
    TransactionStep.INIT_A,
    TransactionStep.COMMAND_PRIMARY,
    TransactionStep.CONFIRM_PRIMARY,
    TransactionStep.INIT_B,
    TransactionStep.COMMAND_FINAL,
    TransactionStep.CONFIRM_FINAL,
)


@dataclass(frozen=True)
class TransactionSnapshot:
    completed_steps: tuple[TransactionStep, ...]
    door_write_count: int
    channel_open_calls: int
    channel_close_calls: int
    protocol_ack_observed: bool
    physical_effect_asserted: bool = False

    def __post_init__(self) -> None:
        if self.physical_effect_asserted:
            raise ValueError("transaction snapshot cannot assert physical effect")


@dataclass
class SyntheticDoorTransactionBoundary:
    """Full offline transaction model with one typed boundary invocation.

    The model is intentionally incapable of network I/O. Channel open/close and
    six Door writes are symbolic fixture events only. Conservative boundary
    semantics are preserved even for control-plane uncertainty: an ambiguous
    channel-open attempt is never downgraded to PROVEN_NOT_SENT.
    """

    fail_before_open: bool = False
    fail_after_door_write: int | None = None
    control_open_outcome: ControlOutcome = ControlOutcome.OPENED
    calls: int = 0
    last_snapshot: TransactionSnapshot | None = None

    def __post_init__(self) -> None:
        if self.fail_after_door_write is not None and not 1 <= self.fail_after_door_write <= 6:
            raise ValueError("fail_after_door_write must be between 1 and 6")

    def _snapshot(self, completed: list[TransactionStep], door_write_count: int, control: SyntheticCtppControlPlane, protocol_ack: bool) -> None:
        self.last_snapshot = TransactionSnapshot(
            completed_steps=tuple(completed),
            door_write_count=door_write_count,
            channel_open_calls=control.open_calls,
            channel_close_calls=control.close_calls,
            protocol_ack_observed=protocol_ack,
            physical_effect_asserted=False,
        )

    def attempt_once(self, request: TransportRequest) -> BoundaryEvidence:
        self.calls += 1
        if self.calls > 1:
            raise AssertionError("transaction boundary called more than once")
        completed: list[TransactionStep] = []
        writes = 0
        control = SyntheticCtppControlPlane(open_outcome=self.control_open_outcome)
        protocol_ack = False
        try:
            if self.fail_before_open:
                raise RuntimeError("synthetic failure before channel open")

            open_evidence = control.open_once()
            completed.append(TransactionStep.OPEN_CTPP)
            protocol_ack = open_evidence.protocol_acknowledged

            if open_evidence.outcome in {ControlOutcome.PROVEN_NOT_OPENED, ControlOutcome.REJECTED}:
                self._snapshot(completed, writes, control, protocol_ack)
                return BoundaryEvidence(
                    outcome=BoundaryOutcome.REJECTED,
                    detail="CTPP open was rejected/not-opened before any Door payload emission",
                    protocol_acknowledged=False,
                )
            if open_evidence.outcome == ControlOutcome.AMBIGUOUS:
                self._snapshot(completed, writes, control, protocol_ack)
                return BoundaryEvidence(
                    outcome=BoundaryOutcome.AMBIGUOUS,
                    detail="CTPP open attempt is ambiguous; retry is unsafe even though no Door payload was emitted",
                    protocol_acknowledged=False,
                )

            for step in TransactionStep:
                if step in {TransactionStep.OPEN_CTPP, TransactionStep.CLOSE_CTPP}:
                    continue
                completed.append(step)
                if step not in DOOR_WRITE_STEPS:
                    continue
                writes += 1
                if self.fail_after_door_write == writes:
                    raise RuntimeError("synthetic failure after Door write")

            control.close_once()
            completed.append(TransactionStep.CLOSE_CTPP)
            self._snapshot(completed, writes, control, protocol_ack)
            return BoundaryEvidence(
                outcome=BoundaryOutcome.ACCEPTED_NO_ACK,
                detail="synthetic full Door transaction emitted six fixture writes; Door ACK unproven",
                protocol_acknowledged=False,
            )
        except Exception as exc:
            self._snapshot(completed, writes, control, protocol_ack)
            # Only a failure before open_once() is provably pre-send. Once a
            # control-plane attempt has occurred, generic failure is conservative.
            outcome = (
                BoundaryOutcome.PROVEN_NOT_SENT
                if control.open_calls == 0 and writes == 0
                else BoundaryOutcome.AMBIGUOUS
            )
            return BoundaryEvidence(
                outcome=outcome,
                detail=f"synthetic transaction failed: {type(exc).__name__}",
                protocol_acknowledged=False,
            )
