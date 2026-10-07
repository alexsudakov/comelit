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
    DATA_MINIAPP_ATTACHED_MEDIA_PROVIDERS,
    DATA_MINIAPP,
    DATA_RING_MEDIA,
    DATA_RUNTIMES,
    DATA_SYNTHETIC_RING_MEDIA,
    DATA_SUPERVISORS,
    DOMAIN,
    DOOR_ENTRANCE,
    DOOR_GATE,
    EVENT_RING_INTERACTION,
    PLATFORMS,
    RING_INTERACTION_OUTCOMES,
    SERVICE_EMIT_RING_INTERACTION,
    SERVICE_OPEN_DOOR,
    SUPPORTED_DOORS,
)
from .media_session import ComelitMediaSessionManager
from .miniapp import ComelitMiniAppController, async_register_miniapp_views
from .media_transport import ComelitEntranceMediaTransport
from .oauth import ComelitOAuthManager
from .ring_media import HAStreamMediaProvider, RingMediaCoordinator
from .runtime import ComelitRingRuntime
from .supervisor import ComelitRuntimeSupervisor

_LOGGER = logging.getLogger(__name__)

_FRONTEND_URL = "/api/comelit/frontend"
_FRONTEND_DIR = Path(__file__).resolve().parent / "frontend"


def _register_attached_media_providers(
    hass: HomeAssistant,
    domain_data: dict[str, object],
    entry: ConfigEntry,
    attached_session: ComelitAttachedRingMediaSession,
    attached_transport: ComelitAttachedRingMediaTransport,
) -> tuple[HAStreamMediaProvider, HAStreamMediaProvider]:
    """Register Ring Media and Mini App providers for the attached stream."""
    ring_media_provider = HAStreamMediaProvider(
        hass,
        attached_session,
        attached_transport,
        stream_label="comelit_attached",
    )
    attached_providers = domain_data.setdefault(
        DATA_ATTACHED_MEDIA_PROVIDERS, {}
    )
    attached_providers[entry.entry_id] = ring_media_provider
    miniapp_attached_provider = HAStreamMediaProvider(
        hass,
        attached_session,
        attached_transport,
        local_sdp_path_attr="miniapp_local_sdp_path",
        local_sdp_ready_attr="miniapp_local_sdp_ready",
        stream_label="comelit_miniapp_attached",
    )
    miniapp_attached_providers = domain_data.setdefault(
        DATA_MINIAPP_ATTACHED_MEDIA_PROVIDERS, {}
    )
    miniapp_attached_providers[entry.entry_id] = miniapp_attached_provider
    return ring_media_provider, miniapp_attached_provider


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

    domain_data = hass.data.setdefault(DOMAIN, {})
    miniapp = ComelitMiniAppController(hass, _FRONTEND_DIR)
    domain_data[DATA_MINIAPP] = miniapp
    async_register_miniapp_views(hass, miniapp)

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
        door = str(call.data[ATTR_DOOR])
        event_id = call.data.get(ATTR_EVENT_ID)
        if door == DOOR_ENTRANCE:
            media_transports = domain_data.get(DATA_MEDIA_TRANSPORTS, {})
            media_transport: ComelitEntranceMediaTransport | None = (
                media_transports.get(entry_id)
            )
            try:
                return await supervisor.async_open_entrance_door(
                    media_transport,
                    event_id=str(event_id) if event_id else None,
                )
            except RuntimeError as exc:
                raise HomeAssistantError(
                    "Comelit Door is unavailable while the on-demand media "
                    "session owns the exclusive connection"
                ) from exc

        if door == DOOR_GATE:
            try:
                return await supervisor.async_open_gate_door(
                    event_id=str(event_id) if event_id else None,
                )
            except RuntimeError as exc:
                raise HomeAssistantError(
                    "Comelit Door is unavailable while the on-demand media "
                    "session owns the exclusive connection"
                ) from exc
        raise HomeAssistantError("Unsupported Comelit Door target")

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
    miniapp: ComelitMiniAppController | None = domain_data.get(DATA_MINIAPP)
    if miniapp is not None:
        miniapp.set_entry(entry)

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
        attached_session.set_stop_failure_recovery(
            supervisor.async_recover_attached_media_stop_failure
        )
        attached_sessions = domain_data.setdefault(DATA_ATTACHED_MEDIA_SESSIONS, {})
        attached_sessions[entry.entry_id] = attached_session

        # Physical CALL_INIT events use the already-live persistent call
        # transaction. No listener pause and no second cloud/P2P bootstrap.
        ring_media_provider, _miniapp_attached_provider = (
            _register_attached_media_providers(
                hass,
                domain_data,
                entry,
                attached_session,
                attached_transport,
            )
        )
        ring_media = RingMediaCoordinator(
            hass,
            attached_session,
            snapshot_provider=ring_media_provider,
            recording_provider=ring_media_provider,
            remote_close_waiter=attached_session.async_wait_inactive,
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
    miniapp_attached_providers = domain_data.get(
        DATA_MINIAPP_ATTACHED_MEDIA_PROVIDERS, {}
    )
    attached_transports = domain_data.get(DATA_ATTACHED_MEDIA_TRANSPORTS, {})
    ring_media_lifecycles = domain_data.get(DATA_RING_MEDIA, {})
    synthetic_lifecycles = domain_data.get(DATA_SYNTHETIC_RING_MEDIA, {})

    runtime = runtimes.get(entry.entry_id)
    supervisor = supervisors.get(entry.entry_id)
    media_manager = media_sessions.get(entry.entry_id)
    media_transport = media_transports.get(entry.entry_id)
    media_provider = media_providers.get(entry.entry_id)
    attached_session = attached_sessions.get(entry.entry_id)
    attached_provider = attached_providers.get(entry.entry_id)
    miniapp_attached_provider = miniapp_attached_providers.get(entry.entry_id)
    ring_media = ring_media_lifecycles.get(entry.entry_id)
    synthetic_ring_media = synthetic_lifecycles.get(entry.entry_id)

    if runtime is None:
        return True

    unloaded = True

    async def attempt(label: str, awaitable: object) -> None:
        nonlocal unloaded
        try:
            await awaitable  # type: ignore[misc]
        except Exception:
            unloaded = False
            _LOGGER.exception("Failed to %s during Comelit unload", label)

    # Tear down every independently owned media surface even when an earlier
    # one fails. Do not remove objects from hass.data until the whole teardown
    # and platform unload have succeeded.
    if ring_media is not None:
        await attempt("shut down Ring media", ring_media.async_shutdown())
    if synthetic_ring_media is not None:
        await attempt(
            "shut down synthetic Ring media",
            synthetic_ring_media.async_shutdown(),
        )
    if attached_session is not None:
        await attempt("shut down attached media", attached_session.async_shutdown())
    if media_manager is not None:
        await attempt("shut down on-demand media", media_manager.async_shutdown())
    elif media_transport is not None:
        await attempt("stop on-demand media transport", media_transport.async_stop())

    for label, provider in (
        ("dispose on-demand HA Stream", media_provider),
        ("dispose attached HA Stream", attached_provider),
        ("dispose Mini App attached HA Stream", miniapp_attached_provider),
    ):
        if provider is not None:
            dispose = getattr(provider, "async_dispose", None)
            if callable(dispose):
                await attempt(label, dispose())

    if supervisor is not None:
        await attempt("stop runtime supervisor", supervisor.async_stop())
    else:
        await attempt("stop runtime", runtime.async_stop())

    if not unloaded:
        return False

    try:
        platforms_unloaded = await hass.config_entries.async_unload_platforms(
            entry, PLATFORMS
        )
    except Exception:
        _LOGGER.exception("Failed to unload Comelit platforms")
        return False
    if not platforms_unloaded:
        return False

    miniapp: ComelitMiniAppController | None = domain_data.get(DATA_MINIAPP)
    if miniapp is not None:
        miniapp.clear_entry(entry)

    runtimes.pop(entry.entry_id, None)
    supervisors.pop(entry.entry_id, None)
    media_sessions.pop(entry.entry_id, None)
    media_transports.pop(entry.entry_id, None)
    media_providers.pop(entry.entry_id, None)
    attached_sessions.pop(entry.entry_id, None)
    attached_providers.pop(entry.entry_id, None)
    miniapp_attached_providers.pop(entry.entry_id, None)
    attached_transports.pop(entry.entry_id, None)
    ring_media_lifecycles.pop(entry.entry_id, None)
    synthetic_lifecycles.pop(entry.entry_id, None)
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
    if not miniapp_attached_providers:
        domain_data.pop(DATA_MINIAPP_ATTACHED_MEDIA_PROVIDERS, None)
    if not ring_media_lifecycles:
        domain_data.pop(DATA_RING_MEDIA, None)
    if not synthetic_lifecycles:
        domain_data.pop(DATA_SYNTHETIC_RING_MEDIA, None)
    return True
