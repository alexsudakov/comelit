from __future__ import annotations

DOMAIN = "comelit"
PLATFORMS = ["button", "sensor"]
DATA_RUNTIMES = "ring_runtimes"
DATA_SUPERVISORS = "runtime_supervisors"

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

MAIN_ENTRANCE_UNIQUE_ID = "comelit_main_entrance_open_door"
MAIN_ENTRANCE_ENTITY_ID = "button.comelit_main_entrance_open_door"
MAIN_GATE_UNIQUE_ID = "comelit_main_gate_open_door"
MAIN_GATE_ENTITY_ID = "button.comelit_main_gate_open_door"
LISTENER_STATUS_UNIQUE_ID = "comelit_listener_status"
LISTENER_STATUS_ENTITY_ID = "sensor.comelit_listener_status"
LISTENER_CYCLE_SECONDS = 3300

BRIDGE_PROTOCOL_VERSION = 1
BRIDGE_PORT = 18014
BRIDGE_REQUEST_TIMEOUT_SECONDS = 175
