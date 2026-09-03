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
    CONF_DEVICE_UUID,
    CONF_OAUTH_ACCESS_TOKEN,
    CONF_SHARED_SECRET,
    CONF_VIP_TOKEN,
    DOMAIN,
    PLATFORMS,
    SERVICE_OPEN_DOOR,
)
from .runtime import ComelitRingRuntime
from .signing import validate_operation_id

_RING_RUNTIMES = "ring_runtimes"


def _operation_id(value: object) -> str:
    try:
        return validate_operation_id(str(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise vol.Invalid("operation_id must be p13-hermes-<uuid4>") from exc


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the protected transitional Door entity action."""
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
    """Set up direct incoming-ring runtime and optional transitional Door bridge."""
    session = async_get_clientsession(hass)
    domain_data = hass.data.setdefault(DOMAIN, {})

    has_bridge = all(
        entry.data.get(key) for key in (CONF_BRIDGE_URL, CONF_SHARED_SECRET)
    )
    if has_bridge:
        client = ComelitBridgeClient(
            session,
            bridge_url=str(entry.data[CONF_BRIDGE_URL]),
            shared_secret=str(entry.data[CONF_SHARED_SECRET]),
        )
        domain_data[entry.entry_id] = client

    has_ring_credentials = all(
        entry.data.get(key)
        for key in (CONF_DEVICE_UUID, CONF_VIP_TOKEN, CONF_OAUTH_ACCESS_TOKEN)
    )
    if has_ring_credentials:
        runtime = ComelitRingRuntime(
            hass,
            session,
            device_uuid=str(entry.data[CONF_DEVICE_UUID]),
            vip_token=str(entry.data[CONF_VIP_TOKEN]),
            oauth_access_token=str(entry.data[CONF_OAUTH_ACCESS_TOKEN]),
        )
        runtimes = domain_data.setdefault(_RING_RUNTIMES, {})
        runtimes[entry.entry_id] = runtime
        await runtime.async_start()

    if has_bridge:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    domain_data = hass.data.get(DOMAIN, {})
    runtimes = domain_data.get(_RING_RUNTIMES, {})
    runtime = runtimes.pop(entry.entry_id, None)
    if runtime is not None:
        await runtime.async_stop()

    has_bridge = all(
        entry.data.get(key) for key in (CONF_BRIDGE_URL, CONF_SHARED_SECRET)
    )
    unloaded = True
    if has_bridge:
        unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unloaded:
        domain_data.pop(entry.entry_id, None)
        if not runtimes:
            domain_data.pop(_RING_RUNTIMES, None)
    return unloaded
