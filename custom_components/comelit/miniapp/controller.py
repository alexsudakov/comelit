from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
from typing import Any

from homeassistant.components.camera import async_request_stream, get_camera_from_entity_id
from homeassistant.components.camera.const import StreamType
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
from .session import (
    MiniAppMediaGrantStore,
    MiniAppSession,
    MiniAppSessionError,
    MiniAppSessionStore,
)
from .go2rtc import MiniAppGo2RTCAdapter


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
_HLS_MASTER_PATH = re.compile(
    r"^/api/hls/[a-f0-9]+/master_playlist\.m3u8$"
)
_HLS_PROXY_TAIL = re.compile(
    r"^(?:master_playlist\.m3u8|playlist\.m3u8|init\.mp4|"
    r"segment/[0-9]+(?:\.[0-9]+)?\.m4s)$"
)
_DIRECT_SOURCE = re.compile(r"^(?:rtsp|rtsps|http|https)://[^\r\n\t ]+$")
_MAX_MSE_STREAMS = 32


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


@dataclass(slots=True)
class _MiniAppMSEStream:
    internal_name: str
    register_task: asyncio.Task[None]
    refcount: int = 0


@dataclass(frozen=True, slots=True)
class MiniAppMSEStreamLease:
    entity_id: str
    internal_name: str


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
        self.media_grants = MiniAppMediaGrantStore()
        self.go2rtc = MiniAppGo2RTCAdapter(hass)
        self._mse_lock = asyncio.Lock()
        self._mse_streams: dict[str, _MiniAppMSEStream] = {}
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
        return Path(__file__).resolve().parent / "index.html"

    def session_is_allowed(self, session: MiniAppSession) -> bool:
        settings = self.settings
        return (
            settings.configured
            and settings.bot_id == session.bot_id
            and session.user_id in settings.allowed_user_ids
        )

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

    def get_webrtc_surveillance_camera(self, entity_id: str):
        """Return an allowed ordinary camera with Home Assistant WebRTC support.

        The intercom camera keeps its separately validated HLS/media lifecycle.
        Ordinary surveillance cameras may use Home Assistant's registered WebRTC
        provider (normally the HA-managed go2rtc instance) on demand.
        """
        if entity_id not in self._allowed_camera_entity_ids():
            raise MiniAppOperationError("camera is not allowed for the Mini App")

        registry = er.async_get(self.hass)
        entry = registry.async_get(entity_id)
        if (
            entry is not None
            and entry.platform == DOMAIN
            and entry.unique_id in INTERCOM_UNIQUE_IDS
        ):
            raise MiniAppOperationError("intercom camera WebRTC is not enabled")

        state = self.hass.states.get(entity_id)
        if state is None or state.state == STATE_UNAVAILABLE:
            raise MiniAppOperationError("camera is unavailable")

        camera = get_camera_from_entity_id(self.hass, entity_id)
        if StreamType.WEB_RTC not in camera.camera_capabilities.frontend_stream_types:
            raise MiniAppOperationError("camera WebRTC is unavailable")
        return camera

    def _get_allowed_ordinary_camera(self, entity_id: str):
        if entity_id not in self._allowed_camera_entity_ids():
            raise MiniAppOperationError("camera is not allowed for the Mini App")

        registry = er.async_get(self.hass)
        entry = registry.async_get(entity_id)
        if (
            entry is not None
            and entry.platform == DOMAIN
            and entry.unique_id in INTERCOM_UNIQUE_IDS
        ):
            raise MiniAppOperationError("intercom camera direct stream is not enabled")

        state = self.hass.states.get(entity_id)
        if state is None or state.state == STATE_UNAVAILABLE:
            raise MiniAppOperationError("camera is unavailable")

        return get_camera_from_entity_id(self.hass, entity_id)

    @staticmethod
    def mse_internal_stream_name(entity_id: str) -> str:
        digest = hashlib.sha256(entity_id.encode("utf-8")).hexdigest()[:16]
        return f"comelit_miniapp_{digest}"

    async def acquire_mse_stream(self, entity_id: str) -> MiniAppMSEStreamLease:
        camera = self._get_allowed_ordinary_camera(entity_id)
        stream_source = await camera.stream_source()
        if not isinstance(stream_source, str) or not _DIRECT_SOURCE.fullmatch(stream_source):
            raise MiniAppOperationError("stream_source_unavailable")

        internal_name = self.mse_internal_stream_name(entity_id)
        async with self._mse_lock:
            stream = self._mse_streams.get(entity_id)
            if stream is None:
                if len(self._mse_streams) >= _MAX_MSE_STREAMS:
                    raise MiniAppOperationError("mse_registry_full")
                stream = _MiniAppMSEStream(
                    internal_name=internal_name,
                    register_task=self.hass.async_create_task(
                        self.go2rtc.register_stream(internal_name, stream_source)
                    ),
                    refcount=0,
                )
                self._mse_streams[entity_id] = stream
            stream.refcount += 1

        try:
            await stream.register_task
        except Exception:
            await self.release_mse_stream(entity_id)
            raise
        return MiniAppMSEStreamLease(entity_id=entity_id, internal_name=internal_name)

    async def release_mse_stream(self, entity_id: str) -> None:
        unregister_name: str | None = None
        async with self._mse_lock:
            stream = self._mse_streams.get(entity_id)
            if stream is None:
                return
            stream.refcount = max(0, stream.refcount - 1)
            if stream.refcount == 0:
                self._mse_streams.pop(entity_id, None)
                unregister_name = stream.internal_name

        if unregister_name is not None:
            await self.go2rtc.unregister_stream(unregister_name)

    async def async_create_camera_media(
        self,
        session_token: str,
        session: MiniAppSession,
        entity_id: str,
    ) -> str:
        if entity_id not in self._allowed_camera_entity_ids():
            raise MiniAppOperationError("camera is not allowed for the Mini App")

        state = self.hass.states.get(entity_id)
        if state is None or state.state == STATE_UNAVAILABLE:
            raise MiniAppOperationError("camera is unavailable")

        # Use Home Assistant's normal camera stream API. For
        # camera.comelit_entrance this enters ComelitEntranceCamera's existing
        # camera-owned lifecycle. The HA HLS capability itself remains inside
        # Home Assistant; the WebView receives only a session-bound proxy path.
        upstream_master = await async_request_stream(
            self.hass,
            entity_id,
            HLS_PROVIDER,
        )
        if _HLS_MASTER_PATH.fullmatch(upstream_master) is None:
            raise MiniAppOperationError("unexpected Home Assistant HLS path")

        upstream_base = upstream_master.rsplit("/", 1)[0] + "/"
        media_id = self.media_grants.create(
            session_token,
            upstream_base,
            session.expires_at,
        )
        return (
            f"/api/comelit/miniapp/media/{media_id}/master_playlist.m3u8"
        )

    def resolve_media_upstream_path(
        self,
        media_id: str,
        session_token: str,
        tail: str,
    ) -> str:
        if _HLS_PROXY_TAIL.fullmatch(tail) is None:
            raise MiniAppOperationError("unsupported HLS resource")
        try:
            grant = self.media_grants.get(media_id, session_token)
        except MiniAppSessionError as exc:
            raise MiniAppOperationError("Mini App media grant is unavailable") from exc
        return grant.upstream_base_path + tail
