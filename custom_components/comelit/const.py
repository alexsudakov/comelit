from __future__ import annotations

DOMAIN = "comelit"
PLATFORMS = ["button"]

# Direct Comelit P2P credentials used by the incoming-ring runtime.
CONF_DEVICE_UUID = "device_uuid"
CONF_VIP_TOKEN = "vip_token"
CONF_OAUTH_ACCESS_TOKEN = "oauth_access_token"

# Transitional P14 Door bridge settings retained for the later Door migration.
CONF_BRIDGE_URL = "bridge_url"
CONF_SHARED_SECRET = "shared_secret"

EVENT_RING = "comelit_ring"

SERVICE_OPEN_DOOR = "open_door"
ATTR_OPERATION_ID = "operation_id"

MAIN_ENTRANCE_UNIQUE_ID = "comelit_main_entrance_open_door"
MAIN_ENTRANCE_ENTITY_ID = "button.comelit_main_entrance_open_door"

BRIDGE_PROTOCOL_VERSION = 1
BRIDGE_PORT = 18014
BRIDGE_REQUEST_TIMEOUT_SECONDS = 175
