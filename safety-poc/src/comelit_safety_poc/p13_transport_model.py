from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class P13TransportStage(str, Enum):
    CLOUD_SIGNALING = "CLOUD_SIGNALING"
    ICE_CONNECTED = "ICE_CONNECTED"
    PSEUDOTCP_OPEN = "PSEUDOTCP_OPEN"
    VIP_ECHO_ACK = "VIP_ECHO_ACK"
    UAUT_OPEN = "UAUT_OPEN"
    UAUT_AUTH = "UAUT_AUTH"
    CTPP_OPEN = "CTPP_OPEN"
    DOOR_WRITES = "DOOR_WRITES"
    CTPP_CLOSE = "CTPP_CLOSE"
    CLEAN_TEARDOWN = "CLEAN_TEARDOWN"


# The proven P12 session path plus the reconciled CTPP Door transaction.
# Order is fixed: the read-only session foundation must complete before the
# actuation channel opens, and the actuation transaction must finish before
# teardown.  No retry of any stage is permitted.
P13_ACTUATION_P2P_PLAN: tuple[P13TransportStage, ...] = (
    P13TransportStage.CLOUD_SIGNALING,
    P13TransportStage.ICE_CONNECTED,
    P13TransportStage.PSEUDOTCP_OPEN,
    P13TransportStage.VIP_ECHO_ACK,
    P13TransportStage.UAUT_OPEN,
    P13TransportStage.UAUT_AUTH,
    P13TransportStage.CTPP_OPEN,
    P13TransportStage.DOOR_WRITES,
    P13TransportStage.CTPP_CLOSE,
    P13TransportStage.CLEAN_TEARDOWN,
)


@dataclass(frozen=True)
class P13ActuationContract:
    """Capability contract for the one-shot actuation transport.

    P13 reuses the proven P2P/session path from P12 and adds exactly the CTPP
    Door transaction.  Every safety property that P12 enforced remains enforced:
    no direct-TCP primary path, no automatic retry, no credential export, no
    physical-effect assertion.
    """

    direct_tcp_primary_path_allowed: bool = False
    cloud_signaling_allowed: bool = True
    ice_allowed: bool = True
    pseudotcp_allowed: bool = True
    vip_session_control_allowed: bool = True
    authentication_allowed: bool = True
    ctpp_channel_allowed: bool = True
    door_write_allowed: bool = True
    automatic_retry_allowed: bool = False
    credential_export_allowed: bool = False
    physical_effect_assertion_allowed: bool = False
    attempt_number_fixed: int = 1

    def validate(self) -> None:
        if self.direct_tcp_primary_path_allowed:
            raise ValueError("P13 must keep the proven cloud P2P path as primary transport")
        required = (
            self.cloud_signaling_allowed,
            self.ice_allowed,
            self.pseudotcp_allowed,
            self.vip_session_control_allowed,
            self.authentication_allowed,
            self.ctpp_channel_allowed,
            self.door_write_allowed,
        )
        if not all(required):
            raise ValueError("P13 actuation proof requires the complete P2P/session/CTPP/Door path")
        if self.automatic_retry_allowed:
            raise ValueError("P13 cannot permit automatic retry")
        if self.credential_export_allowed:
            raise ValueError("P13 cannot export credential material")
        if self.physical_effect_assertion_allowed:
            raise ValueError("P13 cannot assert a physical effect")
        if self.attempt_number_fixed != 1:
            raise ValueError("P13 permits exactly one transport attempt")


@dataclass(frozen=True)
class P13ActuationEvidence:
    """Evidence produced by a single actuation transport invocation."""

    cloud_signaling: bool
    ice_connected: bool
    pseudotcp_open: bool
    vip_echo_ack: bool
    uaut_open: bool
    uaut_auth_200: bool
    ctpp_open: bool
    door_write_count: int
    ctpp_close: bool
    clean_teardown: bool
    protocol_acknowledged: bool = False
    actuator_command_attempted: bool = False
    automatic_retry_observed: bool = False
    credential_material_emitted: bool = False
    physical_effect_asserted: bool = False

    @property
    def actuation_transaction_complete(self) -> bool:
        return (
            self.cloud_signaling
            and self.ice_connected
            and self.pseudotcp_open
            and self.vip_echo_ack
            and self.uaut_open
            and self.uaut_auth_200
            and self.ctpp_open
            and self.door_write_count >= 1
            and self.ctpp_close
            and self.clean_teardown
            and not self.automatic_retry_observed
            and not self.credential_material_emitted
            and not self.physical_effect_asserted
        )


def default_p13_contract() -> P13ActuationContract:
    contract = P13ActuationContract()
    contract.validate()
    return contract


def validate_p13_plan(stages: tuple[P13TransportStage, ...]) -> None:
    if stages != P13_ACTUATION_P2P_PLAN:
        raise ValueError("P13 transport plan must match the fixed actuation P2P sequence")
