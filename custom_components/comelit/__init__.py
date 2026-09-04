from __future__ import annotations

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .client import ComelitBridgeClient
from .const import (
    ATTR_DOOR,
    CONF_BRIDGE_URL,
    CONF_DEVICE_UUID,
    CONF_OAUTH_ACCESS_TOKEN,
    CONF_SHARED_SECRET,
    CONF_VIP_TOKEN,
    DATA_RUNTIMES,
    DOMAIN,
    PLATFORMS,
    SERVICE_OPEN_DOOR,
    SUPPORTED_DOORS,
)
from .runtime import ComelitRingRuntime
from .test_control import async_register_test_control, async_unregister_test_control


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register direct Comelit services."""

    async def handle_open_door(call: ServiceCall) -> dict[str, object]:
        runtimes = hass.data.get(DOMAIN, {}).get(DATA_RUNTIMES, {})
        if len(runtimes) != 1:
            raise HomeAssistantError("Comelit direct runtime is not uniquely available")
        runtime: ComelitRingRuntime = next(iter(runtimes.values()))
        return await runtime.async_open_door(str(call.data[ATTR_DOOR]))

    hass.services.async_register(
        DOMAIN,
        SERVICE_OPEN_DOOR,
        handle_open_door,
        schema=vol.Schema({vol.Required(ATTR_DOOR): vol.In(SUPPORTED_DOORS)}),
        supports_response=SupportsResponse.OPTIONAL,
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up direct Ring/Door runtime and optional legacy bridge client."""
    session = async_get_clientsession(hass)
    domain_data = hass.data.setdefault(DOMAIN, {})

    has_bridge = all(
        entry.data.get(key) for key in (CONF_BRIDGE_URL, CONF_SHARED_SECRET)
    )
    if has_bridge:
        domain_data[entry.entry_id] = ComelitBridgeClient(
            session,
            bridge_url=str(entry.data[CONF_BRIDGE_URL]),
            shared_secret=str(entry.data[CONF_SHARED_SECRET]),
        )

    has_direct_credentials = all(
        entry.data.get(key)
        for key in (CONF_DEVICE_UUID, CONF_VIP_TOKEN, CONF_OAUTH_ACCESS_TOKEN)
    )
    if has_direct_credentials:
        runtime = ComelitRingRuntime(
            hass,
            session,
            device_uuid=str(entry.data[CONF_DEVICE_UUID]),
            vip_token=str(entry.data[CONF_VIP_TOKEN]),
            oauth_access_token=str(entry.data[CONF_OAUTH_ACCESS_TOKEN]),
        )
        runtimes = domain_data.setdefault(DATA_RUNTIMES, {})
        runtimes[entry.entry_id] = runtime

        # Keep explicit validation start/stop until the reconnect supervisor is
        # enabled. Door actions may start the same runtime on demand.
        async_register_test_control(hass, runtime)
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    domain_data = hass.data.get(DOMAIN, {})
    runtimes = domain_data.get(DATA_RUNTIMES, {})
    runtime = runtimes.pop(entry.entry_id, None)

    unloaded = True
    if runtime is not None:
        async_unregister_test_control(hass)
        await runtime.async_stop()
        unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unloaded:
        domain_data.pop(entry.entry_id, None)
        if not runtimes:
            domain_data.pop(DATA_RUNTIMES, None)
    return unloaded
