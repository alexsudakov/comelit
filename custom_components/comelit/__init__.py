from __future__ import annotations

from datetime import UTC, datetime
import logging
from pathlib import Path

import voluptuous as vol

from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .attached_media import (
    ComelitAttachedRingMediaSession,
    ComelitAttachedRingMediaTransport,
)
from .client import ComelitBridgeClient
from .const import (
    ATTR_DOOR,
    ATTR_CHAT_ID,
    ATTR_EVENT_ID,
    ATTR_MESSAGE_ID,
    ATTR_OUTCOME,
    CONF_BRIDGE_URL,
    CONF_DEVICE_UUID,
    CONF_OAUTH_ACCESS_TOKEN,
    CONF_SHARED_SECRET,
    CONF_VIP_TOKEN,
    DATA_ATTACHED_MEDIA_PROVIDERS,
    DATA_ATTACHED_MEDIA_SESSIONS,
    DATA_ATTACHED_MEDIA_TRANSPORTS,
    DATA_MEDIA_PROVIDERS,
    DATA_MEDIA_SESSIONS,
    DATA_MEDIA_TRANSPORTS,
    DATA_RING_MEDIA,
    DATA_RUNTIMES,
    DATA_SYNTHETIC_RING_MEDIA,
    DATA_SUPERVISORS,
    DOMAIN,
    EVENT_RING_INTERACTION,
    PLATFORMS,
    RING_INTERACTION_OUTCOMES,
    SERVICE_EMIT_RING_INTERACTION,
    SERVICE_OPEN_DOOR,
    SUPPORTED_DOORS,
)
from .media_session import ComelitMediaSessionManager
from .media_transport import ComelitEntranceMediaTransport
from .oauth import ComelitOAuthManager
from .ring_media import HAStreamMediaProvider, RingMediaCoordinator
from .runtime import ComelitRingRuntime
from .supervisor import ComelitRuntimeSupervisor
from .test_control import async_register_test_control, async_unregister_test_control

_LOGGER = logging.getLogger(__name__)

_FRONTEND_URL = "/api/comelit/frontend"
_FRONTEND_DIR = Path(__file__).resolve().parent / "frontend"


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register direct Comelit services and the bundled Lovelace card."""

    await hass.http.async_register_static_paths(
        [
            StaticPathConfig(
                _FRONTEND_URL,
                str(_FRONTEND_DIR),
                cache_headers=False,
            )
        ]
    )

    async def handle_open_door(call: ServiceCall) -> dict[str, object]:
        domain_data = hass.data.get(DOMAIN, {})
        runtimes = domain_data.get(DATA_RUNTIMES, {})
        supervisors = domain_data.get(DATA_SUPERVISORS, {})
        if len(runtimes) != 1:
            raise HomeAssistantError("Comelit direct runtime is not uniquely available")

        entry_id, runtime = next(iter(runtimes.items()))
        supervisor: ComelitRuntimeSupervisor | None = supervisors.get(entry_id)
        if supervisor is None:
            raise HomeAssistantError("Comelit runtime supervisor is unavailable")
        if supervisor.media_paused or supervisor.attached_media_busy:
            raise HomeAssistantError(
                "Comelit Door is temporarily unavailable while an intercom "
                "media lifecycle owns the Comelit connection"
            )

        event_id = call.data.get(ATTR_EVENT_ID)
        return await runtime.async_open_door(
            str(call.data[ATTR_DOOR]),
            event_id=str(event_id) if event_id else None,
        )

    async def handle_emit_ring_interaction(call: ServiceCall) -> None:
        payload: dict[str, object] = {
            ATTR_EVENT_ID: str(call.data[ATTR_EVENT_ID]),
            ATTR_DOOR: str(call.data[ATTR_DOOR]),
            ATTR_OUTCOME: str(call.data[ATTR_OUTCOME]),
            "timestamp": datetime.now(UTC).isoformat(),
        }
        for key in (ATTR_CHAT_ID, ATTR_MESSAGE_ID):
            if key in call.data:
                payload[key] = call.data[key]

        hass.bus.async_fire(EVENT_RING_INTERACTION, payload)

    hass.services.async_register(
        DOMAIN,
        SERVICE_OPEN_DOOR,
        handle_open_door,
        schema=vol.Schema(
            {
                vol.Required(ATTR_DOOR): vol.In(SUPPORTED_DOORS),
                vol.Optional(ATTR_EVENT_ID): str,
            }
        ),
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_EMIT_RING_INTERACTION,
        handle_emit_ring_interaction,
        schema=vol.Schema(
            {
                vol.Required(ATTR_EVENT_ID): str,
                vol.Required(ATTR_DOOR): vol.In(SUPPORTED_DOORS),
                vol.Required(ATTR_OUTCOME): vol.In(RING_INTERACTION_OUTCOMES),
                vol.Optional(ATTR_CHAT_ID): object,
                vol.Optional(ATTR_MESSAGE_ID): object,
            }
        ),
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
        device_uuid = str(entry.data[CONF_DEVICE_UUID])
        vip_token = str(entry.data[CONF_VIP_TOKEN])

        runtime = ComelitRingRuntime(
            hass,
            session,
            entry=entry,
            device_uuid=device_uuid,
            vip_token=vip_token,
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

        media_transport = ComelitEntranceMediaTransport(
            hass,
            session,
            entry=entry,
            device_uuid=device_uuid,
            vip_token=vip_token,
            oauth=oauth,
        )
        media_transports = domain_data.setdefault(DATA_MEDIA_TRANSPORTS, {})
        media_transports[entry.entry_id] = media_transport

        media_manager = ComelitMediaSessionManager(
            supervisor,
            media_transport,
            task_factory=lambda coro, name: entry.async_create_background_task(
                hass, coro, name
            ),
        )
        media_sessions = domain_data.setdefault(DATA_MEDIA_SESSIONS, {})
        media_sessions[entry.entry_id] = media_manager

        attached_transport = ComelitAttachedRingMediaTransport(runtime)
        attached_transports = domain_data.setdefault(
            DATA_ATTACHED_MEDIA_TRANSPORTS, {}
        )
        attached_transports[entry.entry_id] = attached_transport

        attached_session = ComelitAttachedRingMediaSession(attached_transport)
        attached_sessions = domain_data.setdefault(DATA_ATTACHED_MEDIA_SESSIONS, {})
        attached_sessions[entry.entry_id] = attached_session

        # Physical CALL_INIT events use the already-live persistent call
        # transaction. No listener pause and no second cloud/P2P bootstrap.
        ring_media_provider = HAStreamMediaProvider(
            hass,
            attached_session,
            attached_transport,
        )
        attached_providers = domain_data.setdefault(
            DATA_ATTACHED_MEDIA_PROVIDERS, {}
        )
        attached_providers[entry.entry_id] = ring_media_provider
        ring_media = RingMediaCoordinator(
            hass,
            attached_session,
            snapshot_provider=ring_media_provider,
            recording_provider=ring_media_provider,
            task_factory=lambda coro, name: entry.async_create_background_task(
                hass, coro, name
            ),
        )
        ring_media_lifecycles = domain_data.setdefault(DATA_RING_MEDIA, {})
        ring_media_lifecycles[entry.entry_id] = ring_media
        runtime.set_ring_media_coordinator(ring_media)

        # Preserve the bounded local synthetic-ring canary on the already
        # production-validated P115 self-activation lifecycle. Synthetic
        # events do not contain a real inbound call transaction to attach to.
        synthetic_ring_media_provider = HAStreamMediaProvider(
            hass,
            media_manager,
            media_transport,
        )
        media_providers = domain_data.setdefault(DATA_MEDIA_PROVIDERS, {})
        media_providers[entry.entry_id] = synthetic_ring_media_provider
        synthetic_ring_media = RingMediaCoordinator(
            hass,
            media_manager,
            snapshot_provider=synthetic_ring_media_provider,
            recording_provider=synthetic_ring_media_provider,
            task_factory=lambda coro, name: entry.async_create_background_task(
                hass, coro, name
            ),
        )
        synthetic_lifecycles = domain_data.setdefault(
            DATA_SYNTHETIC_RING_MEDIA, {}
        )
        synthetic_lifecycles[entry.entry_id] = synthetic_ring_media
        runtime.set_synthetic_ring_media_coordinator(synthetic_ring_media)

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
    media_sessions = domain_data.get(DATA_MEDIA_SESSIONS, {})
    media_transports = domain_data.get(DATA_MEDIA_TRANSPORTS, {})
    media_providers = domain_data.get(DATA_MEDIA_PROVIDERS, {})
    attached_sessions = domain_data.get(DATA_ATTACHED_MEDIA_SESSIONS, {})
    attached_providers = domain_data.get(DATA_ATTACHED_MEDIA_PROVIDERS, {})
    attached_transports = domain_data.get(DATA_ATTACHED_MEDIA_TRANSPORTS, {})
    ring_media_lifecycles = domain_data.get(DATA_RING_MEDIA, {})
    synthetic_lifecycles = domain_data.get(DATA_SYNTHETIC_RING_MEDIA, {})

    runtime = runtimes.pop(entry.entry_id, None)
    supervisor = supervisors.pop(entry.entry_id, None)
    media_manager = media_sessions.pop(entry.entry_id, None)
    media_transport = media_transports.pop(entry.entry_id, None)
    media_providers.pop(entry.entry_id, None)
    attached_session = attached_sessions.pop(entry.entry_id, None)
    attached_providers.pop(entry.entry_id, None)
    attached_transports.pop(entry.entry_id, None)
    ring_media = ring_media_lifecycles.pop(entry.entry_id, None)
    synthetic_ring_media = synthetic_lifecycles.pop(entry.entry_id, None)

    unloaded = True
    if runtime is not None:
        async_unregister_test_control(hass)

        # Tear down media first without resuming the listener; then stop the
        # supervisor. This avoids creating a short-lived replacement listener
        # during config-entry unload.
        try:
            if ring_media is not None:
                await ring_media.async_shutdown()
            if synthetic_ring_media is not None:
                await synthetic_ring_media.async_shutdown()
            if attached_session is not None:
                await attached_session.async_shutdown()
            if media_manager is not None:
                await media_manager.async_shutdown()
            elif media_transport is not None:
                await media_transport.async_stop()
        except Exception:
            _LOGGER.exception("Failed to shut down Comelit media during unload")
            unloaded = False

        if supervisor is not None:
            await supervisor.async_stop()
        else:
            await runtime.async_stop()

        platforms_unloaded = await hass.config_entries.async_unload_platforms(
            entry, PLATFORMS
        )
        unloaded = unloaded and platforms_unloaded

    if unloaded:
        domain_data.pop(entry.entry_id, None)
        if not runtimes:
            domain_data.pop(DATA_RUNTIMES, None)
        if not supervisors:
            domain_data.pop(DATA_SUPERVISORS, None)
        if not media_sessions:
            domain_data.pop(DATA_MEDIA_SESSIONS, None)
        if not media_transports:
            domain_data.pop(DATA_MEDIA_TRANSPORTS, None)
        if not media_providers:
            domain_data.pop(DATA_MEDIA_PROVIDERS, None)
        if not attached_sessions:
            domain_data.pop(DATA_ATTACHED_MEDIA_SESSIONS, None)
        if not attached_transports:
            domain_data.pop(DATA_ATTACHED_MEDIA_TRANSPORTS, None)
        if not attached_providers:
            domain_data.pop(DATA_ATTACHED_MEDIA_PROVIDERS, None)
        if not ring_media_lifecycles:
            domain_data.pop(DATA_RING_MEDIA, None)
        if not synthetic_lifecycles:
            domain_data.pop(DATA_SYNTHETIC_RING_MEDIA, None)
    return unloaded
