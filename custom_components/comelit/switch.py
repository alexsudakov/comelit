from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DATA_MEDIA_SESSIONS,
    DATA_MEDIA_TRANSPORTS,
    DOMAIN,
    ENTRANCE_MEDIA_SWITCH_ENTITY_ID,
    ENTRANCE_MEDIA_SWITCH_UNIQUE_ID,
)
from .media_session import ComelitMediaSessionError, ComelitMediaSessionManager
from .media_transport import ComelitEntranceMediaTransport


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    domain_data = hass.data.get(DOMAIN, {})
    manager: ComelitMediaSessionManager | None = domain_data.get(
        DATA_MEDIA_SESSIONS, {}
    ).get(entry.entry_id)
    transport: ComelitEntranceMediaTransport | None = domain_data.get(
        DATA_MEDIA_TRANSPORTS, {}
    ).get(entry.entry_id)
    if manager is not None and transport is not None:
        async_add_entities([ComelitEntranceMediaSwitch(manager, transport)])


class ComelitEntranceMediaSwitch(SwitchEntity):
    """Explicit owner of the on-demand entrance intercom media session."""

    _attr_name = "Comelit — Камера подъезда"
    _attr_unique_id = ENTRANCE_MEDIA_SWITCH_UNIQUE_ID
    _attr_icon = "mdi:video"
    _attr_should_poll = False

    def __init__(
        self,
        manager: ComelitMediaSessionManager,
        transport: ComelitEntranceMediaTransport,
    ) -> None:
        self._manager = manager
        self._transport = transport
        self.entity_id = ENTRANCE_MEDIA_SWITCH_ENTITY_ID

    @property
    def is_on(self) -> bool:
        return self._manager.active

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        status = self._manager.status()
        return {
            "panel": status["panel"],
            "phase": status["phase"],
            "started_at": status["started_at"],
            "expires_at": status["expires_at"],
            "remaining_seconds": status["remaining_seconds"],
            "listener_paused": status["listener_paused"],
            "last_error": status["last_error"] or self._transport.last_error,
            "video_forwarding": self._transport.video_forwarding,
            "audio_forwarding": self._transport.audio_forwarding,
            "hard_limit_seconds": 180,
            "automatic_retry_allowed": False,
            "door_action_available_during_media": False,
        }

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            self._manager.async_add_status_listener(self._handle_status_update)
        )

    def _handle_status_update(self) -> None:
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs: Any) -> None:
        try:
            await self._manager.async_acquire(panel="entrance", reason="ha_switch")
        except ComelitMediaSessionError as exc:
            raise HomeAssistantError(
                f"Cannot start Comelit entrance media session: {exc}"
            ) from exc
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        try:
            await self._manager.async_force_stop(reason="ha_switch_off")
        except ComelitMediaSessionError as exc:
            raise HomeAssistantError(
                f"Cannot stop Comelit entrance media session safely: {exc}"
            ) from exc
        self.async_write_ha_state()
