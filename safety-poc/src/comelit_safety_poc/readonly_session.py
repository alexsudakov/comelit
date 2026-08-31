from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ReadonlyStep(str, Enum):
    CONNECT = "CONNECT"
    AUTHENTICATE = "AUTHENTICATE"
    LOAD_CONFIGURATION = "LOAD_CONFIGURATION"
    DISCOVER_TARGETS = "DISCOVER_TARGETS"
    CLOSE = "CLOSE"


READONLY_SESSION_PLAN: tuple[ReadonlyStep, ...] = (
    ReadonlyStep.CONNECT,
    ReadonlyStep.AUTHENTICATE,
    ReadonlyStep.LOAD_CONFIGURATION,
    ReadonlyStep.DISCOVER_TARGETS,
    ReadonlyStep.CLOSE,
)


@dataclass(frozen=True)
class ReadonlyCapabilityContract:
    session_control_io_allowed: bool = True
    configuration_queries_allowed: bool = True
    target_discovery_allowed: bool = True
    actuator_command_allowed: bool = False
    credential_export_allowed: bool = False
    automatic_retry_allowed: bool = False
    physical_effect_assertion_allowed: bool = False

    def validate(self) -> None:
        if not self.session_control_io_allowed:
            raise ValueError("read-only proof requires session control I/O")
        if not self.configuration_queries_allowed:
            raise ValueError("read-only proof requires configuration queries")
        if not self.target_discovery_allowed:
            raise ValueError("read-only proof requires target discovery")
        if self.actuator_command_allowed:
            raise ValueError("read-only proof cannot permit actuator commands")
        if self.credential_export_allowed:
            raise ValueError("read-only proof cannot export credential material")
        if self.automatic_retry_allowed:
            raise ValueError("read-only proof cannot permit automatic retries")
        if self.physical_effect_assertion_allowed:
            raise ValueError("read-only proof cannot assert a physical effect")


@dataclass(frozen=True)
class ReadonlySessionEvidence:
    connected: bool
    authenticated: bool
    configuration_observed: bool
    targets_observed: bool
    closed_cleanly: bool
    actuator_command_attempted: bool = False
    credential_material_emitted: bool = False
    automatic_retry_observed: bool = False
    physical_effect_asserted: bool = False

    @property
    def session_proof_complete(self) -> bool:
        return (
            self.connected
            and self.authenticated
            and self.configuration_observed
            and self.targets_observed
            and self.closed_cleanly
            and not self.actuator_command_attempted
            and not self.credential_material_emitted
            and not self.automatic_retry_observed
            and not self.physical_effect_asserted
        )


def validate_readonly_plan(steps: tuple[ReadonlyStep, ...]) -> None:
    if steps != READONLY_SESSION_PLAN:
        raise ValueError("read-only session plan must match the fixed five-step plan")


def default_readonly_contract() -> ReadonlyCapabilityContract:
    contract = ReadonlyCapabilityContract()
    contract.validate()
    return contract
