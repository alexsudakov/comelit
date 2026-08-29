from __future__ import annotations

from dataclasses import dataclass
from .errors import AmbiguousSend, DefinitelyNotSent, SimulatedProcessCrash
from .model import Operation, State, TERMINAL_STATES
from .store import Journal
from .transport import Transport


@dataclass(frozen=True)
class Policy:
    min_interval_seconds: int = 10


class OneShotExecutor:
    """Exactly-one-attempt executor with conservative crash recovery.

    There is intentionally no retry method. A second invocation with the same
    operation_id returns the persisted result and never calls the transport.
    """

    def __init__(self, journal: Journal, transport: Transport, policy: Policy | None = None):
        self.journal = journal
        self.transport = transport
        self.policy = policy or Policy()

    def execute(self, *, operation_id: str, target: str, fault: str | None = None) -> Operation:
        existing = self.journal.maybe_get(operation_id)
        if existing is not None:
            return existing

        try:
            op = self.journal.create(operation_id, target)
        except Exception:
            # A concurrent invocation may have inserted the same id after maybe_get().
            existing = self.journal.maybe_get(operation_id)
            if existing is not None:
                return existing
            raise

        if fault == "crash_pre_arm":
            raise SimulatedProcessCrash("simulated crash while PREPARED")

        op = self.journal.arm_if_allowed(operation_id, self.policy.min_interval_seconds)
        if op.state == State.FAILED_SAFE:
            return op

        if fault == "crash_after_arm":
            raise SimulatedProcessCrash("simulated crash after SEND_ARMED")

        try:
            receipt = self.transport.send_once(operation_id=operation_id, target=target)
        except DefinitelyNotSent as exc:
            return self.journal.transition(operation_id, State.FAILED_SAFE, str(exc))
        except AmbiguousSend as exc:
            return self.journal.transition(operation_id, State.UNKNOWN_OUTCOME, str(exc))
        except Exception as exc:
            # Generic transport errors after SEND_ARMED are conservative: a caller
            # cannot safely infer whether the side effect occurred.
            return self.journal.transition(
                operation_id, State.UNKNOWN_OUTCOME, f"ambiguous transport failure: {type(exc).__name__}"
            )

        if not receipt.accepted:
            return self.journal.transition(
                operation_id, State.FAILED_SAFE, receipt.detail
            )

        op = self.journal.transition(operation_id, State.SENT, receipt.detail)

        if fault == "crash_after_sent":
            raise SimulatedProcessCrash("simulated crash after SENT")

        if receipt.acked:
            return self.journal.transition(
                operation_id, State.ACKED, "protocol acknowledgement proven; physical effect not asserted"
            )
        return self.journal.transition(
            operation_id, State.UNKNOWN_OUTCOME, "send accepted but protocol acknowledgement absent"
        )

    def recover(self) -> list[Operation]:
        recovered: list[Operation] = []
        for op in self.journal.nonterminal():
            if op.state == State.PREPARED:
                recovered.append(
                    self.journal.transition(
                        op.operation_id, State.FAILED_SAFE,
                        "restart recovery before SEND_ARMED: no automatic retry"
                    )
                )
            elif op.state in {State.SEND_ARMED, State.SENT}:
                recovered.append(
                    self.journal.transition(
                        op.operation_id, State.UNKNOWN_OUTCOME,
                        "restart recovery after uncertainty boundary: retry forbidden"
                    )
                )
        return recovered
