from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class HaResultState(str, Enum):
    ACKED = "ACKED"
    FAILED_SAFE = "FAILED_SAFE"
    UNKNOWN_OUTCOME = "UNKNOWN_OUTCOME"


@dataclass(frozen=True)
class HaDoorRequest:
    operation_id: str
    target: str

    def __post_init__(self) -> None:
        if not self.operation_id:
            raise ValueError("operation_id is required")
        if not self.target:
            raise ValueError("target is required")


@dataclass(frozen=True)
class HaDoorResult:
    operation_id: str
    target: str
    state: HaResultState
    retry_allowed: bool
    physical_effect_asserted: bool = False

    def __post_init__(self) -> None:
        if self.retry_allowed:
            raise ValueError("automatic retry is forbidden for Door action")
        if self.physical_effect_asserted:
            raise ValueError("HA result cannot assert physical Door state")


@dataclass(frozen=True)
class HaServiceContract:
    domain: str = "comelit"
    service: str = "open_door"
    requires_operation_id: bool = True
    automatic_retry: bool = False
    exposes_unknown_outcome: bool = True
    physical_state_claims: bool = False

    def __post_init__(self) -> None:
        if self.domain != "comelit" or self.service != "open_door":
            raise ValueError("canonical HA service contract is comelit.open_door")
        if not self.requires_operation_id:
            raise ValueError("operation_id is mandatory")
        if self.automatic_retry:
            raise ValueError("automatic retry must stay disabled")
        if not self.exposes_unknown_outcome:
            raise ValueError("UNKNOWN_OUTCOME must be visible to HA")
        if self.physical_state_claims:
            raise ValueError("service contract cannot claim physical Door state")
