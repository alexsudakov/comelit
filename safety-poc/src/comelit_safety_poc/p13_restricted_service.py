from __future__ import annotations

"""Restricted operator / Home Assistant production path.

Everything a restricted operator or Home Assistant may invoke goes through the
existing one-shot state-machine boundary (OneShotExecutor + Journal + Policy +
audit).  This module deliberately exposes no arbitrary shell, no credential
reads, no raw transport, and no way to bypass ``operation_id`` / rate-limit /
audit semantics.

The production service is fail-closed: until the operator supplies
``EXPLICIT_LIVE_TEST_APPROVAL=true`` (at the physical execution step), the
service rejects every request with a controlled error and never reaches the
transport boundary.
"""

from dataclasses import dataclass
from enum import Enum

from .executor import OneShotExecutor, Policy
from .ha_contract import HaDoorRequest, HaDoorResult, HaResultState
from .model import Operation, State


class P13ServiceState(str, Enum):
    DISABLED = "DISABLED"
    ARMED = "ARMED"


@dataclass(frozen=True)
class P13ServiceConfig:
    journal_path: str
    audit_path: str
    min_interval_seconds: int = 10
    explicit_live_approval: bool = False
    physical_effect_asserted: bool = False

    def __post_init__(self) -> None:
        if self.explicit_live_approval and self.physical_effect_asserted:
            raise ValueError("approval must never imply physical-effect assertion")


class P13RestrictedDoorService:
    """Fail-closed restricted surface for comelit.open_door.

    ``explicit_live_approval`` defaults to False: every call is rejected before
    the executor is reached.  Only the operator may set it true at the final
    physical execution step, and even then the executor's one-shot semantics,
    rate limit, audit and UNKNOWN_OUTCOME behaviour remain authoritative.
    """

    def __init__(
        self,
        transport,
        config: P13ServiceConfig,
        *,
        journal=None,
        sink=None,
    ):
        from .audit import AuditSink, AuditedExecutorTransport
        from .store import Journal

        self.config = config
        self.journal = journal if journal is not None else Journal(config.journal_path)
        self.sink = sink if sink is not None else AuditSink(config.audit_path)
        self.transport = AuditedExecutorTransport(transport, self.sink)
        self.state = P13ServiceState.ARMED if config.explicit_live_approval else P13ServiceState.DISABLED
        self._executor = OneShotExecutor(
            self.journal,
            self.transport,
            Policy(config.min_interval_seconds),
        )

    @property
    def service_state(self) -> P13ServiceState:
        return self.state

    def open_door(self, request: HaDoorRequest) -> HaDoorResult:
        """Restricted one-shot open_door.

        Fail-closed: returns a controlled rejection while the service is
        DISABLED (no explicit operator approval), so the transport boundary is
        never reached.  When ARMED, executes exactly once through the
        one-shot executor and maps the terminal state conservatively.
        """
        if self.state == P13ServiceState.DISABLED:
            return HaDoorResult(
                operation_id=request.operation_id,
                target=request.target,
                state=HaResultState.FAILED_SAFE,
                retry_allowed=False,
                physical_effect_asserted=False,
            )

        op = self._executor.execute(
            operation_id=request.operation_id,
            target=request.target,
        )
        return self._map_operation(op)

    def _map_operation(self, op: Operation) -> HaDoorResult:
        if op.state == State.ACKED:
            state = HaResultState.ACKED
        elif op.state == State.FAILED_SAFE:
            state = HaResultState.FAILED_SAFE
        else:
            state = HaResultState.UNKNOWN_OUTCOME
        return HaDoorResult(
            operation_id=op.operation_id,
            target=op.target,
            state=state,
            retry_allowed=False,
            physical_effect_asserted=False,
        )
