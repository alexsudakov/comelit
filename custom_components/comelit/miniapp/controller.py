from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from homeassistant.components.camera import async_request_stream
from homeassistant.components.stream import HLS_PROVIDER
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import label_registry as lr

from ..const import (
    CONF_MINIAPP_ALLOWED_USER_IDS,
    CONF_MINIAPP_BOT_ID,
    CONF_MINIAPP_ENABLED,
    CONF_MINIAPP_SURVEILLANCE_LABEL,
    DOMAIN,
    DOOR_ENTRANCE,
    DOOR_GATE,
    ENTRANCE_CAMERA_UNIQUE_ID,
    MAIN_ENTRANCE_UNIQUE_ID,
    MAIN_GATE_UNIQUE_ID,
)
from .session import MiniAppSession, MiniAppSessionStore


INTERCOM_UNIQUE_IDS = frozenset(
    {
        "comelit_entrance_camera",
        "comelit_entrance_media_session",
        "comelit_main_entrance_open_door",
        "comelit_main_gate_open_door",
        "comelit_listener_status",
        "comelit_call_state",
    }
)
SAFE_STATE_ATTRIBUTES = frozenset(
    {
        "friendly_name",
        "panel",
        "event_id",
        "media_attached",
        "standard_press_allowed",
        "blocked_by_media_session",
    }
)
DOOR_UNIQUE_IDS = {
    DOOR_ENTRANCE: MAIN_ENTRANCE_UNIQUE_ID,
    DOOR_GATE: MAIN_GATE_UNIQUE_ID,
}


class MiniAppOperationError(HomeAssistantError):
    """A Mini App operation is rejected by the embedded safety boundary."""


@dataclass(frozen=True, slots=True)
class MiniAppSettings:
    """Current Mini App settings read from the Comelit config entry."""

    enabled: bool
    bot_id: int | None
    allowed_user_ids: frozenset[int]
    surveillance_label: str

    @property
    def configured(self) -> bool:
        return (
            self.enabled
            and self.bot_id is not None
            and self.bot_id > 0
            and bool(self.allowed_user_ids)
        )


def _parse_allowed_user_ids(value: object) -> frozenset[int]:
    if isinstance(value, (list, tuple, set, frozenset)):
        raw_items = value
    else:
        raw_items = str(value or "").split(",")

    result: set[int] = set()
    for raw in raw_items:
        item = str(raw).strip()
        if not item:
            continue
        try:
            user_id = int(item)
        except ValueError:
            continue
        if user_id > 0:
            result.add(user_id)
    return frozenset(result)


def _parse_bot_id(value: object) -> int | None:
    try:
        bot_id = int(str(value or "").strip())
    except ValueError:
        return None
    return bot_id if bot_id > 0 else None


class ComelitMiniAppController:
    """Bridge Telegram Mini App HTTP views directly to Home Assistant internals."""

    def __init__(self, hass: HomeAssistant, frontend_dir: Path) -> None:
        self.hass = hass
        self.frontend_dir = frontend_dir
        self.sessions = MiniAppSessionStore()
        self._entry: ConfigEntry | None = None

    def set_entry(self, entry: ConfigEntry) -> None:
        self._entry = entry

    def clear_entry(self, entry: ConfigEntry) -> None:
        if self._entry is entry:
            self._entry = None

    @property
    def settings(self) -> MiniAppSettings:
        options = self._entry.options if self._entry is not None else {}
        return MiniAppSettings(
            enabled=bool(options.get(CONF_MINIAPP_ENABLED, False)),
            bot_id=_parse_bot_id(options.get(CONF_MINIAPP_BOT_ID)),
            allowed_user_ids=_parse_allowed_user_ids(
                options.get(CONF_MINIAPP_ALLOWED_USER_IDS, "")
            ),
            surveillance_label=str(
                options.get(CONF_MINIAPP_SURVEILLANCE_LABEL, "") or ""
            ).strip(),
        )

    @property
    def index_path(self) -> Path:
        return self.frontend_dir / "miniapp" / "index.html"

    def session_is_allowed(self, session: MiniAppSession) -> bool:
        settings = self.settings
        return settings.configured and session.user_id in settings.allowed_user_ids

    def _resolve_surveillance_label_id(self) -> str | None:
        requested = self.settings.surveillance_label
        if not requested:
            return None
        registry = lr.async_get(self.hass)
        entry = registry.async_get_label(requested)
        if entry is None:
            entry = registry.async_get_label_by_name(requested)
        return entry.label_id if entry is not None else None

    def _allowed_registry_entries(self) -> list[dict[str, Any]]:
        registry = er.async_get(self.hass)
        label_id = self._resolve_surveillance_label_id()
        result: list[dict[str, Any]] = []

        for entry in registry.entities.values():
            entity_id = entry.entity_id
            unique_id = entry.unique_id
            is_comelit = (
                entry.platform == DOMAIN and unique_id in INTERCOM_UNIQUE_IDS
            )
            is_surveillance = (
                label_id is not None
                and entity_id.startswith("camera.")
                and label_id in entry.labels
            )
            if not is_comelit and not is_surveillance:
                continue

            result.append(
                {
                    "entity_id": entity_id,
                    "platform": entry.platform,
                    "unique_id": unique_id,
                    "labels": sorted(entry.labels),
                    "name": entry.name,
                    "original_name": entry.original_name,
                }
            )

        return result

    @staticmethod
    def _safe_state(entity_id: str, state: Any) -> dict[str, Any]:
        attributes = state.attributes if state is not None else {}
        safe_attributes = {
            key: attributes[key]
            for key in SAFE_STATE_ATTRIBUTES
            if key in attributes
        }
        return {
            "entity_id": entity_id,
            "state": state.state if state is not None else STATE_UNAVAILABLE,
            "attributes": safe_attributes,
        }

    def _state_payload_for_entries(
        self, entries: list[dict[str, Any]]
    ) -> dict[str, dict[str, Any]]:
        return {
            entity_id: self._safe_state(entity_id, self.hass.states.get(entity_id))
            for entry in entries
            if (entity_id := str(entry["entity_id"]))
        }

    def bootstrap(self, session: MiniAppSession) -> dict[str, Any]:
        entries = self._allowed_registry_entries()
        surveillance_entities = [
            str(entry["entity_id"])
            for entry in entries
            if str(entry["entity_id"]).startswith("camera.")
            and not (
                entry.get("platform") == DOMAIN
                and entry.get("unique_id") == ENTRANCE_CAMERA_UNIQUE_ID
            )
        ]
        return {
            "states": self._state_payload_for_entries(entries),
            "entity_registry": entries,
            "label_registry": [],
            "surveillance_entities": surveillance_entities,
            "action_nonce": session.action_nonce,
        }

    def state_payload(self) -> dict[str, Any]:
        entries = self._allowed_registry_entries()
        return {"states": self._state_payload_for_entries(entries)}

    def _resolve_door_entity_id(self, door: str) -> str:
        unique_id = DOOR_UNIQUE_IDS.get(door)
        if unique_id is None:
            raise MiniAppOperationError("unsupported Door target")

        registry = er.async_get(self.hass)
        entity_id = registry.async_get_entity_id("button", DOMAIN, unique_id)
        if entity_id is None:
            raise MiniAppOperationError("Comelit Door entity is unavailable")
        return entity_id

    async def async_press_door(self, door: str) -> None:
        """Invoke exactly one existing Comelit ButtonEntity press."""
        entity_id = self._resolve_door_entity_id(door)
        state = self.hass.states.get(entity_id)
        if (
            state is None
            or state.state == STATE_UNAVAILABLE
            or state.attributes.get("standard_press_allowed") is not True
        ):
            raise MiniAppOperationError("Comelit Door action is currently unavailable")

        # The embedded boundary intentionally converges on the already accepted
        # production ButtonEntity path. One request means one service call and
        # this method never retries.
        await self.hass.services.async_call(
            "button",
            "press",
            {"entity_id": entity_id},
            blocking=True,
        )

    def _allowed_camera_entity_ids(self) -> frozenset[str]:
        entries = self._allowed_registry_entries()
        return frozenset(
            str(entry["entity_id"])
            for entry in entries
            if str(entry["entity_id"]).startswith("camera.")
        )

    async def async_camera_stream_url(self, entity_id: str) -> str:
        if entity_id not in self._allowed_camera_entity_ids():
            raise MiniAppOperationError("camera is not allowed for the Mini App")

        state = self.hass.states.get(entity_id)
        if state is None or state.state == STATE_UNAVAILABLE:
            raise MiniAppOperationError("camera is unavailable")

        # Use Home Assistant's normal camera stream API. For
        # camera.comelit_entrance this enters ComelitEntranceCamera's existing
        # camera-owned lifecycle and returns HA Stream's capability URL.
        return await async_request_stream(self.hass, entity_id, HLS_PROVIDER)
