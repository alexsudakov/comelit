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
    DATA_SUPERVISORS,
    DOMAIN,
    PLATFORMS,
    SERVICE_OPEN_DOOR,
    SUPPORTED_DOORS,
)
from .oauth import ComelitOAuthManager
from .runtime import ComelitRingRuntime
from .supervisor import ComelitRuntimeSupervisor
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
        oauth = ComelitOAuthManager(hass, session, entry)
        runtime = ComelitRingRuntime(
            hass,
            session,
            entry=entry,
            device_uuid=str(entry.data[CONF_DEVICE_UUID]),
            vip_token=str(entry.data[CONF_VIP_TOKEN]),
            oauth=oauth,
        )
        runtimes = domain_data.setdefault(DATA_RUNTIMES, {})
        runtimes[entry.entry_id] = runtime

        supervisor = ComelitRuntimeSupervisor(
            hass,
            runtime,
            entry=entry,
        )
        supervisors = domain_data.setdefault(DATA_SUPERVISORS, {})
        supervisors[entry.entry_id] = supervisor

        # Transitional validation endpoint remains available, but normal
        # operation no longer depends on CT120/Hermes: the supervisor starts
        # with the config entry and reconnects entirely inside Home Assistant.
        async_register_test_control(hass, runtime, supervisor)
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
        await supervisor.async_start()

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    domain_data = hass.data.get(DOMAIN, {})
    runtimes = domain_data.get(DATA_RUNTIMES, {})
    supervisors = domain_data.get(DATA_SUPERVISORS, {})
    runtime = runtimes.pop(entry.entry_id, None)
    supervisor = supervisors.pop(entry.entry_id, None)

    unloaded = True
    if runtime is not None:
        async_unregister_test_control(hass)
        if supervisor is not None:
            await supervisor.async_stop()
        else:
            await runtime.async_stop()
        unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unloaded:
        domain_data.pop(entry.entry_id, None)
        if not runtimes:
            domain_data.pop(DATA_RUNTIMES, None)
        if not supervisors:
            domain_data.pop(DATA_SUPERVISORS, None)
    return unloaded
