from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class P12TransportStage(str, Enum):
    CLOUD_SIGNALING = "CLOUD_SIGNALING"
    ICE_CONNECTED = "ICE_CONNECTED"
    PSEUDOTCP_OPEN = "PSEUDOTCP_OPEN"
    VIP_ECHO_ACK = "VIP_ECHO_ACK"
    UAUT_OPEN = "UAUT_OPEN"
    UAUT_AUTH = "UAUT_AUTH"
    UCFG_READ = "UCFG_READ"
    CLEAN_TEARDOWN = "CLEAN_TEARDOWN"


P12_READONLY_P2P_PLAN: tuple[P12TransportStage, ...] = (
    P12TransportStage.CLOUD_SIGNALING,
    P12TransportStage.ICE_CONNECTED,
    P12TransportStage.PSEUDOTCP_OPEN,
    P12TransportStage.VIP_ECHO_ACK,
    P12TransportStage.UAUT_OPEN,
    P12TransportStage.UAUT_AUTH,
    P12TransportStage.UCFG_READ,
    P12TransportStage.CLEAN_TEARDOWN,
)


@dataclass(frozen=True)
class P12P2PContract:
    direct_tcp_primary_path_allowed: bool = False
    cloud_signaling_allowed: bool = True
    ice_allowed: bool = True
    pseudotcp_allowed: bool = True
    vip_session_control_allowed: bool = True
    authentication_allowed: bool = True
    configuration_read_allowed: bool = True
    target_discovery_allowed: bool = True
    actuator_command_allowed: bool = False
    media_activation_allowed: bool = False
    automatic_retry_allowed: bool = False
    credential_export_allowed: bool = False
    physical_effect_assertion_allowed: bool = False

    def validate(self) -> None:
        if self.direct_tcp_primary_path_allowed:
            raise ValueError("P12 must use the proven cloud P2P transport path, not direct TCP as primary")
        required = (
            self.cloud_signaling_allowed,
            self.ice_allowed,
            self.pseudotcp_allowed,
            self.vip_session_control_allowed,
            self.authentication_allowed,
            self.configuration_read_allowed,
            self.target_discovery_allowed,
        )
        if not all(required):
            raise ValueError("P12 read-only proof requires the complete P2P/session/configuration path")
        if self.actuator_command_allowed:
            raise ValueError("P12 cannot permit actuator commands")
        if self.media_activation_allowed:
            raise ValueError("P12 transport proof cannot activate media")
        if self.automatic_retry_allowed:
            raise ValueError("P12 cannot permit automatic retry")
        if self.credential_export_allowed:
            raise ValueError("P12 cannot export credential material")
        if self.physical_effect_assertion_allowed:
            raise ValueError("P12 cannot assert physical effect")


@dataclass(frozen=True)
class P12P2PEvidence:
    cloud_signaling: bool
    ice_connected: bool
    pseudotcp_open: bool
    vip_echo_ack: bool
    uaut_open: bool
    uaut_auth_200: bool
    ucfg_observed: bool
    clean_teardown: bool
    actuator_command_attempted: bool = False
    media_activation_attempted: bool = False
    automatic_retry_observed: bool = False
    credential_material_emitted: bool = False
    physical_effect_asserted: bool = False

    @property
    def readonly_transport_proof_complete(self) -> bool:
        return (
            self.cloud_signaling
            and self.ice_connected
            and self.pseudotcp_open
            and self.vip_echo_ack
            and self.uaut_open
            and self.uaut_auth_200
            and self.ucfg_observed
            and self.clean_teardown
            and not self.actuator_command_attempted
            and not self.media_activation_attempted
            and not self.automatic_retry_observed
            and not self.credential_material_emitted
            and not self.physical_effect_asserted
        )


def default_p12_contract() -> P12P2PContract:
    contract = P12P2PContract()
    contract.validate()
    return contract


def validate_p12_plan(stages: tuple[P12TransportStage, ...]) -> None:
    if stages != P12_READONLY_P2P_PLAN:
        raise ValueError("P12 transport plan must match the fixed read-only P2P sequence")
