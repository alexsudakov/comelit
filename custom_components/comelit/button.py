from __future__ import annotations

from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .client import (
    ComelitBridgeClient,
    ComelitBridgeOutcomeUnknown,
    ComelitBridgeRejected,
)
from .const import DOMAIN, MAIN_ENTRANCE_ENTITY_ID, MAIN_ENTRANCE_UNIQUE_ID


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    client: ComelitBridgeClient = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([ComelitMainEntranceDoorButton(entry, client)])


class ComelitMainEntranceDoorButton(ButtonEntity):
    """Target entity for the protected comelit.open_door action.

    The standard button.press surface is intentionally disabled. The only
    actuation-capable HA surface is the custom entity service, which requires an
    upstream-generated one-shot operation_id.
    """

    _attr_name = "Comelit main entrance open door"
    _attr_unique_id = MAIN_ENTRANCE_UNIQUE_ID
    _attr_icon = "mdi:door-open"
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry, client: ComelitBridgeClient):
        self._entry = entry
        self._client = client
        self.entity_id = MAIN_ENTRANCE_ENTITY_ID
        self._last_operation_id: str | None = None
        self._last_protocol_state: str | None = None
        self._last_reason: str | None = None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "standard_press_allowed": False,
            "one_shot_operation_required": True,
            "automatic_retry_allowed": False,
            "physical_effect_asserted": False,
            "last_operation_id": self._last_operation_id,
            "last_protocol_state": self._last_protocol_state,
            "last_reason": self._last_reason,
        }

    async def async_press(self) -> None:
        raise HomeAssistantError(
            "button.press is disabled for Comelit Door; use comelit.open_door with operation_id"
        )

    async def async_open_door(self, operation_id: str) -> None:
        try:
            result = await self._client.async_open_door(operation_id)
        except ComelitBridgeRejected as exc:
            raise HomeAssistantError(f"Comelit bridge rejected request before execution: {exc}") from exc
        except ComelitBridgeOutcomeUnknown as exc:
            # This wording is intentional: HA/LLM callers must not convert a
            # transport ambiguity into a second physical attempt.
            raise HomeAssistantError(
                f"Comelit Door outcome unknown; do not retry automatically: {exc}"
            ) from exc

        self._last_operation_id = result.operation_id
        self._last_protocol_state = result.state
        self._last_reason = result.reason
        self.async_write_ha_state()
