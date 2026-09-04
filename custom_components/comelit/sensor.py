from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DATA_SUPERVISORS,
    DOMAIN,
    LISTENER_STATUS_ENTITY_ID,
    LISTENER_STATUS_UNIQUE_ID,
)
from .supervisor import ComelitRuntimeSupervisor, LISTENER_STATES


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    supervisor: ComelitRuntimeSupervisor | None = (
        hass.data.get(DOMAIN, {}).get(DATA_SUPERVISORS, {}).get(entry.entry_id)
    )
    if supervisor is not None:
        async_add_entities([ComelitListenerStatusSensor(supervisor)])


class ComelitListenerStatusSensor(SensorEntity):
    """Diagnostic state of the persistent Comelit Ring/Door listener."""

    _attr_name = "Comelit — Listener"
    _attr_unique_id = LISTENER_STATUS_UNIQUE_ID
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = list(LISTENER_STATES)
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:connection"
    _attr_should_poll = False

    def __init__(self, supervisor: ComelitRuntimeSupervisor) -> None:
        self._supervisor = supervisor
        self.entity_id = LISTENER_STATUS_ENTITY_ID

    @property
    def native_value(self) -> str:
        return self._supervisor.state

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        status = self._supervisor.status()
        return {
            "supervisor_running": status["supervisor_running"],
            "runtime_running": status["runtime_running"],
            "listener_ready": status["listener_ready"],
            "reconnect_count": status["reconnect_count"],
            "last_ready": status["last_ready"],
            "last_error": status["last_error"],
            "cycle_duration_seconds": status["cycle_duration_seconds"],
        }

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            self._supervisor.async_add_status_listener(self._handle_status_update)
        )

    def _handle_status_update(self) -> None:
        self.async_write_ha_state()
