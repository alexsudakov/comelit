from __future__ import annotations

from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DATA_RUNTIMES,
    DOMAIN,
    DOOR_ENTRANCE,
    MAIN_ENTRANCE_ENTITY_ID,
    MAIN_ENTRANCE_UNIQUE_ID,
)
from .runtime import ComelitRingRuntime


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    runtime: ComelitRingRuntime | None = (
        hass.data.get(DOMAIN, {}).get(DATA_RUNTIMES, {}).get(entry.entry_id)
    )
    if runtime is not None:
        async_add_entities([ComelitEntranceDoorButton(runtime)])


class ComelitEntranceDoorButton(ButtonEntity):
    """One-shot entrance Door command through the direct HA runtime."""

    _attr_name = "Comelit — Подъезд"
    _attr_unique_id = MAIN_ENTRANCE_UNIQUE_ID
    _attr_icon = "mdi:door-open"
    _attr_should_poll = False

    def __init__(self, runtime: ComelitRingRuntime) -> None:
        self._runtime = runtime
        self.entity_id = MAIN_ENTRANCE_ENTITY_ID
        self._last_result: dict[str, object] | None = None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        result = self._last_result or self._runtime.last_door_result or {}
        return {
            "standard_press_allowed": True,
            "one_shot_operation_required": True,
            "automatic_retry_allowed": False,
            "physical_effect_asserted": False,
            "physical_door_state": "UNKNOWN",
            "last_operation_id": result.get("operation_id"),
            "last_protocol_state": result.get("state"),
            "last_protocol_acked": result.get("protocol_acked"),
        }

    async def async_press(self) -> None:
        result = await self._runtime.async_open_door(DOOR_ENTRANCE)
        self._last_result = dict(result)
        self.async_write_ha_state()
        if result.get("state") != "ACKED":
            raise HomeAssistantError(
                "Comelit Door was not protocol-ACKED; automatic retry is forbidden. "
                f"state={result.get('state')}"
            )
