from __future__ import annotations

DOMAIN = "comelit"
PLATFORMS = ["button"]
DATA_RUNTIMES = "ring_runtimes"

CONF_DEVICE_UUID = "device_uuid"
CONF_VIP_TOKEN = "vip_token"
CONF_OAUTH_ACCESS_TOKEN = "oauth_access_token"
CONF_OAUTH_REFRESH_TOKEN = "oauth_refresh_token"
CONF_OAUTH_EXPIRES_AT = "oauth_expires_at"

# Transitional bridge keys retained only for migration compatibility.
CONF_BRIDGE_URL = "bridge_url"
CONF_SHARED_SECRET = "shared_secret"

EVENT_RING = "comelit_ring"
SERVICE_OPEN_DOOR = "open_door"
ATTR_DOOR = "door"
DOOR_ENTRANCE = "entrance"
SUPPORTED_DOORS = (DOOR_ENTRANCE,)

MAIN_ENTRANCE_UNIQUE_ID = "comelit_main_entrance_open_door"
MAIN_ENTRANCE_ENTITY_ID = "button.comelit_main_entrance_open_door"

BRIDGE_PROTOCOL_VERSION = 1
BRIDGE_PORT = 18014
BRIDGE_REQUEST_TIMEOUT_SECONDS = 175
