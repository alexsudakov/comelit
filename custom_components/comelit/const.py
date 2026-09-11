from __future__ import annotations

from typing import NamedTuple

DOMAIN = "comelit"
PLATFORMS = ["button", "sensor", "switch", "camera"]
DATA_RUNTIMES = "ring_runtimes"
DATA_SUPERVISORS = "runtime_supervisors"
DATA_MEDIA_TRANSPORTS = "media_transports"
DATA_MEDIA_SESSIONS = "media_sessions"

CONF_DEVICE_UUID = "device_uuid"
CONF_VIP_TOKEN = "vip_token"
CONF_OAUTH_ACCESS_TOKEN = "oauth_access_token"
CONF_OAUTH_REFRESH_TOKEN = "oauth_refresh_token"
CONF_OAUTH_EXPIRES_AT = "oauth_expires_at"
CONF_OAUTH_SCOPE = "oauth_scope"

# Transitional bridge keys retained only for migration compatibility.
CONF_BRIDGE_URL = "bridge_url"
CONF_SHARED_SECRET = "shared_secret"

EVENT_RING = "comelit_ring"
SERVICE_OPEN_DOOR = "open_door"
ATTR_DOOR = "door"
DOOR_ENTRANCE = "entrance"
DOOR_GATE = "gate"

# Only targets with a separately proven actuation profile may be accepted by
# the public Door service. Gate ring identity is proven, gate actuation is not.
SUPPORTED_DOORS = (DOOR_ENTRANCE,)


class DoorCapability(NamedTuple):
    """Resolved HA exposure and actuation capability for a door target."""

    configured: bool
    ring_source_validated: bool
    actuation_profile_validated: bool
    press_allowed: bool
    available: bool
    blocked_reason: str | None
    ring_source: str | None


_DOOR_TOPOLOGY_CAPABILITIES: dict[str, dict[str, object]] = {
    DOOR_ENTRANCE: {
        "configured": True,
        "ring_source_validated": True,
        "actuation_profile_validated": True,
        "ring_source": None,
    },
    DOOR_GATE: {
        "configured": True,
        "ring_source_validated": True,
        "actuation_profile_validated": False,
        "ring_source": "00000610",
    },
}


def resolve_door_capability(
    door: str,
    *,
    media_paused: bool,
) -> DoorCapability:
    """Return deterministic HA visibility and press capability for a door."""
    raw = _DOOR_TOPOLOGY_CAPABILITIES.get(door)
    if raw is None:
        return DoorCapability(
            configured=False,
            ring_source_validated=False,
            actuation_profile_validated=False,
            press_allowed=False,
            available=False,
            blocked_reason="door_target_not_configured",
            ring_source=None,
        )

    configured = bool(raw["configured"])
    ring_source_validated = bool(raw["ring_source_validated"])
    actuation_profile_validated = bool(raw["actuation_profile_validated"])
    available = configured and ring_source_validated and not media_paused
    press_allowed = available and actuation_profile_validated

    blocked_reason = None
    if media_paused:
        blocked_reason = "media_session_exclusive_connection"
    elif not configured:
        blocked_reason = "door_target_not_configured"
    elif not ring_source_validated:
        blocked_reason = "ring_source_not_validated"
    elif not actuation_profile_validated:
        blocked_reason = "gate_actuation_profile_not_validated"

    ring_source = raw["ring_source"]
    return DoorCapability(
        configured=configured,
        ring_source_validated=ring_source_validated,
        actuation_profile_validated=actuation_profile_validated,
        press_allowed=press_allowed,
        available=available,
        blocked_reason=blocked_reason,
        ring_source=ring_source if isinstance(ring_source, str) else None,
    )

MAIN_ENTRANCE_UNIQUE_ID = "comelit_main_entrance_open_door"
MAIN_ENTRANCE_ENTITY_ID = "button.comelit_main_entrance_open_door"
MAIN_GATE_UNIQUE_ID = "comelit_main_gate_open_door"
MAIN_GATE_ENTITY_ID = "button.comelit_main_gate_open_door"
LISTENER_STATUS_UNIQUE_ID = "comelit_listener_status"
LISTENER_STATUS_ENTITY_ID = "sensor.comelit_listener_status"
ENTRANCE_MEDIA_SWITCH_UNIQUE_ID = "comelit_entrance_media_session"
ENTRANCE_MEDIA_SWITCH_ENTITY_ID = "switch.comelit_entrance_camera"
ENTRANCE_CAMERA_UNIQUE_ID = "comelit_entrance_camera"
ENTRANCE_CAMERA_ENTITY_ID = "camera.comelit_entrance"
LISTENER_CYCLE_SECONDS = 3300

BRIDGE_PROTOCOL_VERSION = 1
BRIDGE_PORT = 18014
BRIDGE_REQUEST_TIMEOUT_SECONDS = 175
