from __future__ import annotations

from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DATA_RUNTIMES,
    DATA_SUPERVISORS,
    DOMAIN,
    DOOR_ENTRANCE,
    DOOR_GATE,
    MAIN_ENTRANCE_ENTITY_ID,
    MAIN_ENTRANCE_UNIQUE_ID,
    MAIN_GATE_ENTITY_ID,
    MAIN_GATE_UNIQUE_ID,
    resolve_door_capability,
)
from .runtime import ComelitRingRuntime
from .supervisor import ComelitRuntimeSupervisor


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    runtime: ComelitRingRuntime | None = (
        hass.data.get(DOMAIN, {}).get(DATA_RUNTIMES, {}).get(entry.entry_id)
    )
    supervisor: ComelitRuntimeSupervisor | None = (
        hass.data.get(DOMAIN, {}).get(DATA_SUPERVISORS, {}).get(entry.entry_id)
    )
    if runtime is not None and supervisor is not None:
        async_add_entities(
            [
                ComelitEntranceDoorButton(runtime, supervisor),
                ComelitGateDoorButton(runtime, supervisor),
            ]
        )


class ComelitEntranceDoorButton(ButtonEntity):
    """One-shot entrance Door command through the direct HA runtime."""

    _attr_name = "Comelit — Открыть подъезд"
    _attr_unique_id = MAIN_ENTRANCE_UNIQUE_ID
    _attr_icon = "mdi:door-open"
    _attr_should_poll = False

    def __init__(
        self,
        runtime: ComelitRingRuntime,
        supervisor: ComelitRuntimeSupervisor,
    ) -> None:
        self._runtime = runtime
        self._supervisor = supervisor
        self.entity_id = MAIN_ENTRANCE_ENTITY_ID
        self._last_result: dict[str, object] | None = None

    @property
    def available(self) -> bool:
        # Media owns the only allowed Comelit session while the listener is
        # intentionally paused. Door must fail closed rather than restarting
        # the Ring/Door runtime behind the media manager's back.
        # Legacy static contract equivalent: return not self._supervisor.media_paused
        return resolve_door_capability(
            DOOR_ENTRANCE,
            media_paused=self._supervisor.media_paused,
        ).available

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        result = self._last_result or self._runtime.last_door_result or {}
        capability = resolve_door_capability(
            DOOR_ENTRANCE,
            media_paused=self._supervisor.media_paused,
        )
        return {
            "standard_press_allowed": capability.press_allowed,
            "blocked_by_media_session": self._supervisor.media_paused,
            "one_shot_operation_required": True,
            "automatic_retry_allowed": False,
            "physical_effect_asserted": False,
            "physical_door_state": "UNKNOWN",
            "actuation_profile_validated": capability.actuation_profile_validated,
            "last_operation_id": result.get("operation_id"),
            "last_protocol_state": result.get("state"),
            "last_protocol_acked": result.get("protocol_acked"),
            "last_write_count": result.get("write_count"),
            "last_door_specific_ack_proven": result.get(
                "door_specific_ack_proven"
            ),
            "last_existing_ctpp_reused": result.get(
                "existing_ctpp_reused"
            ),
            "last_one_shot_sequence_sent": result.get(
                "one_shot_sequence_sent"
            ),
            "last_ctpp_channel_id": result.get("ctpp_channel_id"),
            "last_reject_stage": result.get("reject_stage"),
            "last_reject_response_word": result.get("reject_response_word"),
            "last_requested_channel_id": result.get("requested_channel_id"),
            "last_response_channel_id": result.get("response_channel_id"),
        }

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            self._supervisor.async_add_status_listener(self._handle_status_update)
        )

    def _handle_status_update(self) -> None:
        self.async_write_ha_state()

    async def async_press(self) -> None:
        if self._supervisor.media_paused:
            raise HomeAssistantError(
                "Comelit Door is temporarily unavailable while the intercom "
                "media session owns the exclusive Comelit connection"
            )

        result = await self._runtime.async_open_door(DOOR_ENTRANCE)
        self._last_result = dict(result)
        self.async_write_ha_state()
        # A complete one-shot TX without a proven Door-specific ACK is an
        # unconfirmed outcome, not a transport failure.  Do not claim the
        # physical effect, but do not show a false HA error after all five
        # validated Door writes crossed the local PseudoTCP TX boundary.
        if (
            result.get("protocol_acked") is True
            or result.get("one_shot_sequence_sent") is True
        ):
            return

        raise HomeAssistantError(
            "Comelit Door command did not complete the validated one-shot "
            "transmission; automatic retry is forbidden. "
            f"state={result.get('state')} "
            f"write_count={result.get('write_count')} "
            f"protocol_acked={result.get('protocol_acked')}"
        )


class ComelitGateDoorButton(ButtonEntity):
    """One-shot Gate command through the validated peer/TAP runtime profile."""

    _attr_name = "Comelit — Калитка"
    _attr_unique_id = MAIN_GATE_UNIQUE_ID
    _attr_icon = "mdi:gate"
    _attr_should_poll = False

    def __init__(
        self,
        runtime: ComelitRingRuntime,
        supervisor: ComelitRuntimeSupervisor,
    ) -> None:
        self._runtime = runtime
        self._supervisor = supervisor
        self.entity_id = MAIN_GATE_ENTITY_ID
        self._last_result: dict[str, object] | None = None

    @property
    def available(self) -> bool:
        return resolve_door_capability(
            DOOR_GATE,
            media_paused=self._supervisor.media_paused,
        ).available

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        result = self._last_result or {}
        capability = resolve_door_capability(
            DOOR_GATE,
            media_paused=self._supervisor.media_paused,
        )
        return {
            "door": DOOR_GATE,
            "standard_press_allowed": capability.press_allowed,
            "blocked_by_media_session": self._supervisor.media_paused,
            "one_shot_operation_required": True,
            "automatic_retry_allowed": False,
            "physical_effect_asserted": False,
            "physical_door_state": "UNKNOWN",
            "configured": capability.configured,
            "actuation_profile_validated": capability.actuation_profile_validated,
            "ring_source_validated": capability.ring_source_validated,
            "ring_source": capability.ring_source,
            "blocked_reason": capability.blocked_reason,
            "last_operation_id": result.get("operation_id"),
            "last_protocol_state": result.get("state"),
            "last_protocol_acked": result.get("protocol_acked"),
            "last_write_count": result.get("write_count"),
            "last_door_specific_ack_proven": result.get(
                "door_specific_ack_proven"
            ),
            "last_existing_ctpp_reused": result.get("existing_ctpp_reused"),
            "last_one_shot_sequence_sent": result.get(
                "one_shot_sequence_sent"
            ),
            "last_ctpp_channel_id": result.get("ctpp_channel_id"),
            "last_reject_stage": result.get("reject_stage"),
            "last_reject_response_word": result.get("reject_response_word"),
        }

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            self._supervisor.async_add_status_listener(self._handle_status_update)
        )

    def _handle_status_update(self) -> None:
        self.async_write_ha_state()

    async def async_press(self) -> None:
        if self._supervisor.media_paused:
            raise HomeAssistantError(
                "Comelit Gate is temporarily unavailable while the intercom "
                "media session owns the exclusive Comelit connection"
            )

        result = await self._runtime.async_open_door(DOOR_GATE)
        self._last_result = dict(result)
        self.async_write_ha_state()

        # Same conservative outcome contract as Entrance: a fully transmitted
        # one-shot is not a transport failure, but it is never promoted to a
        # physical-effect assertion without a target-specific protocol ACK.
        if (
            result.get("protocol_acked") is True
            or result.get("one_shot_sequence_sent") is True
        ):
            return

        raise HomeAssistantError(
            "Comelit Gate command did not complete the validated one-shot "
            "transmission; automatic retry is forbidden. "
            f"state={result.get('state')} "
            f"write_count={result.get('write_count')} "
            f"protocol_acked={result.get('protocol_acked')}"
        )
