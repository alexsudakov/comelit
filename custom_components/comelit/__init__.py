from __future__ import annotations

import voluptuous as vol

from homeassistant.components.button import DOMAIN as BUTTON_DOMAIN
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, SupportsResponse
from homeassistant.helpers import service
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .client import ComelitBridgeClient
from .const import (
    ATTR_OPERATION_ID,
    CONF_BRIDGE_URL,
    CONF_SHARED_SECRET,
    DOMAIN,
    PLATFORMS,
    SERVICE_OPEN_DOOR,
)
from .signing import validate_operation_id


def _operation_id(value: object) -> str:
    try:
        return validate_operation_id(str(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise vol.Invalid("operation_id must be p13-hermes-<uuid4>") from exc


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the protected response-required entity action."""
    service.async_register_platform_entity_service(
        hass,
        DOMAIN,
        SERVICE_OPEN_DOOR,
        entity_domain=BUTTON_DOMAIN,
        schema={vol.Required(ATTR_OPERATION_ID): _operation_id},
        func="async_open_door",
        supports_response=SupportsResponse.ONLY,
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up one private CT120 bridge config entry."""
    client = ComelitBridgeClient(
        async_get_clientsession(hass),
        bridge_url=str(entry.data[CONF_BRIDGE_URL]),
        shared_secret=str(entry.data[CONF_SHARED_SECRET]),
    )
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = client
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    return unloaded
