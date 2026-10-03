from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hashlib
import logging
from pathlib import Path
import re
import time
from typing import Any, Callable

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
    DATA_MEDIA_SESSIONS,
    DATA_MEDIA_TRANSPORTS,
    DATA_ATTACHED_MEDIA_SESSIONS,
    DATA_MINIAPP_ATTACHED_MEDIA_PROVIDERS,
    DATA_RING_MEDIA,
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
WEBCODECS_INTERCOM_UNIQUE_IDS = INTERCOM_UNIQUE_IDS | {"comelit_gate_camera"}
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
_WEBCODECS_HLS_FALLBACK_CLEANUP_SECONDS = 5.0
_WEBCODECS_ENTRANCE_PARK_SECONDS = 60.0
_WEBCODECS_ENTRANCE_VIEWER_REASON = "miniapp_webcodecs"
_WEBCODECS_ENTRANCE_PARK_REASON = "miniapp_webcodecs_park"
_MINIAPP_ATTACHED_VIEW_REASON = "miniapp_attached_view"
ATTACHED_VIEWER_HEARTBEAT_INTERVAL_SECONDS = 5
ATTACHED_VIEWER_LEASE_EXPIRY_SECONDS = 15
_ATTACHED_VIEWER_ACTIONS = frozenset({"open", "heartbeat", "close"})

_LOGGER = logging.getLogger(__name__)


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


@dataclass(frozen=True, slots=True)
class MiniAppWebCodecsTarget:
    entity_id: str
    kind: str
    camera: Any | None = None


@dataclass(slots=True)
class MiniAppWebCodecsEntranceLease:
    manager: Any
    transport: Any
    reason: str
    released: bool = False

    @property
    def local_sdp_path(self) -> Path:
        return Path(self.transport.local_sdp_path)

    async def release(self) -> None:
        if self.released:
            return
        self.released = True
        await self.manager.async_release(reason=self.reason)


@dataclass(slots=True)
class _AttachedViewerLease:
    token: str
    viewer_id: str
    expires_at: float
    task: asyncio.Task[None]
    heartbeat_logged: bool = False


@dataclass(slots=True)
class _MiniAppAttachedResource:
    session: Any
    provider: Any
    refcount: int = 0
    stream: Any | None = None


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
        self._webcodecs_entrance_lock = asyncio.Lock()
        self._webcodecs_entrance_park_task: asyncio.Task[None] | None = None
        self._webcodecs_entrance_park_manager: Any | None = None
        self._webcodecs_entrance_park_held = False
        self._attached_viewer_lock = asyncio.Lock()
        self._attached_viewers: dict[tuple[str, str], _AttachedViewerLease] = {}
        self._miniapp_attached_resource: _MiniAppAttachedResource | None = None

    def set_entry(self, entry: ConfigEntry) -> None:
        self._entry = entry

    def clear_entry(self, entry: ConfigEntry) -> None:
        if self._entry is entry:
            self._entry = None
            self.hass.async_create_task(
                self.async_close_attached_viewers_for_shutdown()
            )

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

    def _attached_ring_media_coordinator(self) -> Any | None:
        entry = self._entry
        entry_id = getattr(entry, "entry_id", None) if entry is not None else None
        if not isinstance(entry_id, str) or not entry_id:
            return None
        return (
            self.hass.data.get(DOMAIN, {})
            .get(DATA_RING_MEDIA, {})
            .get(entry_id)
        )

    def _miniapp_attached_runtime(self) -> tuple[Any, Any]:
        entry = self._entry
        entry_id = getattr(entry, "entry_id", None) if entry is not None else None
        if not isinstance(entry_id, str) or not entry_id:
            raise MiniAppOperationError("attached_media_unavailable")
        domain_data = self.hass.data.get(DOMAIN, {})
        session = domain_data.get(DATA_ATTACHED_MEDIA_SESSIONS, {}).get(entry_id)
        provider = domain_data.get(DATA_MINIAPP_ATTACHED_MEDIA_PROVIDERS, {}).get(
            entry_id
        )
        if session is None or provider is None:
            raise MiniAppOperationError("attached_media_unavailable")
        return session, provider

    async def _ensure_miniapp_attached_resource_locked(self) -> None:
        resource = self._miniapp_attached_resource
        if resource is not None:
            resource.refcount += 1
            _LOGGER.info(
                "miniapp_attached_stream_reused miniapp_attached_viewers=%s "
                "miniapp_attached_stream_active=true",
                resource.refcount,
            )
            return

        session, provider = self._miniapp_attached_runtime()
        lease_acquired = False
        consumer_acquired = False
        try:
            await session.async_acquire(
                panel="entrance",
                reason=_MINIAPP_ATTACHED_VIEW_REASON,
            )
            lease_acquired = True
            await provider.async_acquire_consumer(_MINIAPP_ATTACHED_VIEW_REASON)
            consumer_acquired = True
            stream = await provider.async_get_stream()
            if stream is None:
                raise MiniAppOperationError("attached_media_stream_unavailable")
            add_provider = getattr(stream, "add_provider", None)
            if callable(add_provider):
                result = add_provider(HLS_PROVIDER)
                if asyncio.iscoroutine(result):
                    await result
            start = getattr(stream, "start", None)
            if callable(start):
                result = start()
                if asyncio.iscoroutine(result):
                    await result
            activate_miniapp_output = getattr(
                session,
                "async_activate_miniapp_output",
                None,
            )
            if callable(activate_miniapp_output):
                await activate_miniapp_output()
        except Exception:
            if consumer_acquired:
                try:
                    release_consumer = getattr(
                        provider,
                        "async_release_consumer",
                        None,
                    )
                    if not callable(release_consumer):
                        raise MiniAppOperationError(
                            "attached_media_stream_unavailable"
                        )
                    await release_consumer(_MINIAPP_ATTACHED_VIEW_REASON)
                except Exception:
                    _LOGGER.exception("Mini App attached stream consumer cleanup failed")
            if lease_acquired:
                await session.async_release(reason=_MINIAPP_ATTACHED_VIEW_REASON)
            raise

        self._miniapp_attached_resource = _MiniAppAttachedResource(
            session=session,
            provider=provider,
            refcount=1,
            stream=stream,
        )
        _LOGGER.info(
            "miniapp_attached_stream_created miniapp_attached_viewers=1 "
            "miniapp_attached_stream_active=true"
        )

    async def _release_miniapp_attached_resource_locked(self) -> None:
        resource = self._miniapp_attached_resource
        if resource is None:
            return
        resource.refcount = max(0, resource.refcount - 1)
        if resource.refcount > 0:
            return

        self._miniapp_attached_resource = None
        try:
            await resource.provider.async_release_consumer(
                _MINIAPP_ATTACHED_VIEW_REASON
            )
        finally:
            await resource.session.async_release(reason=_MINIAPP_ATTACHED_VIEW_REASON)
        deactivate_miniapp_output = getattr(
            resource.session,
            "async_deactivate_miniapp_output",
            None,
        )
        if callable(deactivate_miniapp_output):
            try:
                await deactivate_miniapp_output()
            except Exception as err:
                _LOGGER.warning(
                    "Mini App attached sink deactivate failed: %s",
                    err,
                )
        _LOGGER.info(
            "miniapp_attached_stream_closed miniapp_attached_viewers=0 "
            "miniapp_attached_stream_active=false"
        )

    def _miniapp_attached_hls_master_path_locked(self) -> str | None:
        resource = self._miniapp_attached_resource
        stream = resource.stream if resource is not None else None
        if stream is None:
            return None
        endpoint_url = getattr(stream, "endpoint_url", None)
        if not callable(endpoint_url):
            return None
        upstream_master = endpoint_url(HLS_PROVIDER)
        if not isinstance(upstream_master, str):
            return None
        return upstream_master

    async def _request_attached_ring_stop(
        self,
        reason: str,
        *,
        viewer_count: int,
    ) -> bool:
        coordinator = self._attached_ring_media_coordinator()
        request_stop = getattr(coordinator, "async_request_stop", None)
        if not callable(request_stop):
            return False
        started = asyncio.get_running_loop().time()
        _LOGGER.info(
            "Comelit attached_viewer_last_released reason=%s viewer_count=%s elapsed_ms=0",
            reason,
            viewer_count,
        )
        requested = await request_stop(reason)
        elapsed_ms = max(0, round((asyncio.get_running_loop().time() - started) * 1000))
        _LOGGER.info(
            "Comelit ring_media_stop_requested reason=%s viewer_count=%s elapsed_ms=%s requested=%s",
            reason,
            viewer_count,
            elapsed_ms,
            bool(requested),
        )
        return bool(requested)

    async def _expire_attached_viewer(
        self,
        token: str,
        viewer_id: str,
        expires_at: float,
    ) -> None:
        delay = max(0.0, expires_at - asyncio.get_running_loop().time())
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            raise

        request_stop = False
        async with self._attached_viewer_lock:
            key = (token, viewer_id)
            lease = self._attached_viewers.get(key)
            if lease is None or lease.expires_at != expires_at:
                return
            self._attached_viewers.pop(key, None)
            request_stop = not self._attached_viewers
            viewer_count = len(self._attached_viewers)
            await self._release_miniapp_attached_resource_locked()

        _LOGGER.info(
            "Comelit attached_viewer_expired viewer_count=%s",
            viewer_count,
        )
        if request_stop:
            await self._request_attached_ring_stop(
                "viewer_lease_expired",
                viewer_count=viewer_count,
            )

    def _create_attached_viewer_expiry_task(
        self,
        session_token: str,
        viewer_id: str,
        expires_at: float,
    ) -> asyncio.Task[None]:
        task = self.hass.async_create_task(
            self._expire_attached_viewer(session_token, viewer_id, expires_at)
        )
        set_name = getattr(task, "set_name", None)
        if callable(set_name):
            set_name("Comelit attached viewer lease expiry")

        def consume_result(done: asyncio.Task[None]) -> None:
            try:
                done.result()
            except asyncio.CancelledError:
                pass
            except Exception:
                _LOGGER.exception("Comelit attached viewer expiry task failed")

        task.add_done_callback(consume_result)
        return task

    async def async_attached_viewer_event(
        self,
        session_token: str,
        session: MiniAppSession,
        *,
        action: str,
        viewer_id: str,
    ) -> dict[str, object]:
        """Maintain a bounded Mini App Entrance viewer lease for attached media."""
        if action not in _ATTACHED_VIEWER_ACTIONS:
            raise MiniAppOperationError("invalid_attached_viewer_action")
        if not re.fullmatch(r"[A-Za-z0-9_-]{8,64}", viewer_id):
            raise MiniAppOperationError("invalid_attached_viewer_id")
        epoch_now = time.time()
        if float(session.expires_at) <= epoch_now:
            raise MiniAppOperationError("Mini App session is expired")

        key = (session_token, viewer_id)
        loop = asyncio.get_running_loop()
        loop_now = loop.time()
        session_remaining = max(0.0, float(session.expires_at) - epoch_now)
        expires_at = min(
            loop_now + session_remaining,
            loop_now + ATTACHED_VIEWER_LEASE_EXPIRY_SECONDS,
        )
        request_stop = False
        viewer_count = 0

        async with self._attached_viewer_lock:
            existing = self._attached_viewers.pop(key, None)
            heartbeat_logged = bool(existing.heartbeat_logged) if existing else False
            if existing is not None:
                existing.task.cancel()

            if action in {"open", "heartbeat"}:
                heartbeat_logged = heartbeat_logged or action == "heartbeat"
                task = self._create_attached_viewer_expiry_task(
                    session_token,
                    viewer_id,
                    expires_at,
                )
                if existing is None:
                    try:
                        await self._ensure_miniapp_attached_resource_locked()
                    except Exception:
                        task.cancel()
                        raise
                self._attached_viewers[key] = _AttachedViewerLease(
                    token=session_token,
                    viewer_id=viewer_id,
                    expires_at=expires_at,
                    task=task,
                    heartbeat_logged=heartbeat_logged,
                )
                viewer_count = len(self._attached_viewers)
            else:
                viewer_count = len(self._attached_viewers)
                request_stop = existing is not None and viewer_count == 0
                if existing is not None:
                    await self._release_miniapp_attached_resource_locked()

        if action == "open":
            _LOGGER.info("Comelit attached_viewer_open viewer_count=%s", viewer_count)
        elif action == "close":
            _LOGGER.info("Comelit attached_viewer_close viewer_count=%s", viewer_count)
        elif not existing or not existing.heartbeat_logged:
            _LOGGER.info(
                "Comelit attached_viewer_heartbeat viewer_count=%s",
                viewer_count,
            )

        if request_stop:
            await self._request_attached_ring_stop(
                "viewer_closed",
                viewer_count=viewer_count,
            )

        return {
            "ok": True,
            "viewer_count": viewer_count,
            "heartbeat_interval_seconds": ATTACHED_VIEWER_HEARTBEAT_INTERVAL_SECONDS,
            "lease_expiry_seconds": ATTACHED_VIEWER_LEASE_EXPIRY_SECONDS,
        }

    async def async_close_attached_viewers_for_shutdown(self) -> None:
        async with self._attached_viewer_lock:
            leases = list(self._attached_viewers.values())
            self._attached_viewers.clear()
            for _lease in leases:
                await self._release_miniapp_attached_resource_locked()
        for lease in leases:
            lease.task.cancel()
        if leases:
            await asyncio.gather(
                *(lease.task for lease in leases),
                return_exceptions=True,
            )
            await self._request_attached_ring_stop("shutdown", viewer_count=0)

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

    def get_webcodecs_camera_target(self, entity_id: str) -> MiniAppWebCodecsTarget:
        if entity_id not in self._allowed_camera_entity_ids():
            raise MiniAppOperationError("camera_not_allowed")

        registry = er.async_get(self.hass)
        entry = registry.async_get(entity_id)
        state = self.hass.states.get(entity_id)
        if state is None or state.state == STATE_UNAVAILABLE:
            raise MiniAppOperationError("camera_unavailable")

        if (
            entry is not None
            and entry.platform == DOMAIN
            and entry.unique_id == ENTRANCE_CAMERA_UNIQUE_ID
        ):
            return MiniAppWebCodecsTarget(entity_id=entity_id, kind="entrance")

        if (
            entry is not None
            and entry.platform == DOMAIN
            and entry.unique_id in WEBCODECS_INTERCOM_UNIQUE_IDS
        ):
            raise MiniAppOperationError("intercom_camera_not_allowed")

        return MiniAppWebCodecsTarget(
            entity_id=entity_id,
            kind="ordinary",
            camera=get_camera_from_entity_id(self.hass, entity_id),
        )

    def _webcodecs_entrance_runtime(self) -> tuple[Any, Any]:
        entry = self._entry
        entry_id = getattr(entry, "entry_id", None) if entry is not None else None
        if not isinstance(entry_id, str) or not entry_id:
            raise MiniAppOperationError("intercom_media_unavailable")

        domain_data = self.hass.data.get(DOMAIN, {})
        manager = domain_data.get(DATA_MEDIA_SESSIONS, {}).get(entry_id)
        transport = domain_data.get(DATA_MEDIA_TRANSPORTS, {}).get(entry_id)
        if manager is None or transport is None:
            raise MiniAppOperationError("intercom_media_unavailable")
        return manager, transport

    async def _cancel_webcodecs_entrance_park_timer_locked(self) -> None:
        task = self._webcodecs_entrance_park_task
        self._webcodecs_entrance_park_task = None
        if task is None or task is asyncio.current_task():
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def _expire_webcodecs_entrance_park(self, manager: Any) -> None:
        try:
            await asyncio.sleep(_WEBCODECS_ENTRANCE_PARK_SECONDS)
        except asyncio.CancelledError:
            raise

        async with self._webcodecs_entrance_lock:
            if (
                not self._webcodecs_entrance_park_held
                or self._webcodecs_entrance_park_manager is not manager
            ):
                return
            self._webcodecs_entrance_park_task = None
            self._webcodecs_entrance_park_manager = None
            self._webcodecs_entrance_park_held = False
            try:
                await manager.async_release(reason=_WEBCODECS_ENTRANCE_PARK_REASON)
            except Exception:
                _LOGGER.exception(
                    "Comelit Mini App Entrance warm park release failed"
                )

    async def async_park_webcodecs_entrance(self) -> dict[str, object]:
        """Keep the active Entrance media session warm for a bounded tab switch.

        The browser WSS/PyAV/VideoDecoder consumer is still disconnected.  Only
        an additional manager lease is retained for 60 seconds so a return to
        the Entrance tab can reuse the already-established Comelit media
        transport without another cold P2P/CTPP bootstrap.
        """
        async with self._webcodecs_entrance_lock:
            manager, transport = self._webcodecs_entrance_runtime()
            if (
                getattr(manager, "phase", None) != "active"
                or not getattr(manager, "active", False)
                or not getattr(transport, "active", False)
                or not getattr(transport, "local_sdp_ready", False)
            ):
                raise MiniAppOperationError("intercom_media_unavailable")

            if (
                self._webcodecs_entrance_park_held
                and self._webcodecs_entrance_park_manager is manager
            ):
                await self._cancel_webcodecs_entrance_park_timer_locked()
            else:
                if self._webcodecs_entrance_park_held:
                    stale_manager = self._webcodecs_entrance_park_manager
                    await self._cancel_webcodecs_entrance_park_timer_locked()
                    self._webcodecs_entrance_park_manager = None
                    self._webcodecs_entrance_park_held = False
                    if stale_manager is not None:
                        try:
                            await stale_manager.async_release(
                                reason=_WEBCODECS_ENTRANCE_PARK_REASON
                            )
                        except Exception:
                            _LOGGER.exception(
                                "Comelit Mini App stale Entrance park release failed"
                            )
                try:
                    await manager.async_acquire(
                        panel="entrance",
                        reason=_WEBCODECS_ENTRANCE_PARK_REASON,
                    )
                except Exception as exc:
                    raise MiniAppOperationError("intercom_media_busy") from exc
                self._webcodecs_entrance_park_manager = manager
                self._webcodecs_entrance_park_held = True

            self._webcodecs_entrance_park_task = self.hass.async_create_task(
                self._expire_webcodecs_entrance_park(manager)
            )
            return {
                "parked": True,
                "timeout_seconds": int(_WEBCODECS_ENTRANCE_PARK_SECONDS),
            }

    async def acquire_webcodecs_entrance(
        self,
        target: MiniAppWebCodecsTarget,
    ) -> MiniAppWebCodecsEntranceLease:
        if target.kind != "entrance":
            raise MiniAppOperationError("invalid_webcodecs_target")

        async with self._webcodecs_entrance_lock:
            manager, transport = self._webcodecs_entrance_runtime()

            # Fast return from Surveillance: acquire the new viewer lease before
            # dropping the warm park lease, so the manager never reaches zero
            # leases and therefore never tears down the established transport.
            if (
                self._webcodecs_entrance_park_held
                and self._webcodecs_entrance_park_manager is manager
                and getattr(manager, "phase", None) == "active"
                and getattr(manager, "active", False)
                and getattr(transport, "active", False)
                and getattr(transport, "local_sdp_ready", False)
            ):
                try:
                    await manager.async_acquire(
                        panel="entrance",
                        reason=_WEBCODECS_ENTRANCE_VIEWER_REASON,
                    )
                except Exception as exc:
                    raise MiniAppOperationError("intercom_media_busy") from exc

                await self._cancel_webcodecs_entrance_park_timer_locked()
                self._webcodecs_entrance_park_manager = None
                self._webcodecs_entrance_park_held = False
                try:
                    await manager.async_release(
                        reason=_WEBCODECS_ENTRANCE_PARK_REASON
                    )
                except Exception as exc:
                    # Avoid leaking a fresh viewer lease if the ownership
                    # hand-off cannot be completed coherently.
                    await manager.async_release(
                        reason=_WEBCODECS_ENTRANCE_VIEWER_REASON
                    )
                    raise MiniAppOperationError("intercom_media_busy") from exc

                return MiniAppWebCodecsEntranceLease(
                    manager=manager,
                    transport=transport,
                    reason=_WEBCODECS_ENTRANCE_VIEWER_REASON,
                )

            if self._webcodecs_entrance_park_held:
                # The manager watchdog/hard timeout may have invalidated a warm
                # lease while the browser was away. Clear only local park state;
                # the manager is the source of truth for its own lease table.
                await self._cancel_webcodecs_entrance_park_timer_locked()
                self._webcodecs_entrance_park_manager = None
                self._webcodecs_entrance_park_held = False

            try:
                await self._await_webcodecs_manager_cleanup(manager)
            except MiniAppOperationError as exc:
                raise MiniAppOperationError("intercom_media_busy") from exc
            if getattr(manager, "phase", None) != "inactive":
                raise MiniAppOperationError("intercom_media_busy")

            try:
                await manager.async_acquire(
                    panel="entrance",
                    reason=_WEBCODECS_ENTRANCE_VIEWER_REASON,
                )
            except Exception as exc:
                code = (
                    "intercom_media_busy"
                    if str(exc) in {
                        "attached_inbound_media_busy",
                        "media_session_transition_busy",
                    }
                    else "intercom_media_start_failed"
                )
                raise MiniAppOperationError(code) from exc

            lease = MiniAppWebCodecsEntranceLease(
                manager=manager,
                transport=transport,
                reason=_WEBCODECS_ENTRANCE_VIEWER_REASON,
            )
            if not getattr(manager, "active", False):
                await lease.release()
                raise MiniAppOperationError("intercom_media_start_failed")
            if not getattr(transport, "active", False) or not getattr(
                transport, "local_sdp_ready", False
            ):
                await lease.release()
                raise MiniAppOperationError("intercom_media_unavailable")
            return lease

    @staticmethod
    def mse_internal_stream_name(entity_id: str) -> str:
        digest = hashlib.sha256(entity_id.encode("utf-8")).hexdigest()[:16]
        return f"comelit_miniapp_{digest}"

    async def acquire_mse_stream(
        self,
        entity_id: str,
        *,
        progress: Callable[[str], None] | None = None,
    ) -> MiniAppMSEStreamLease:
        camera = self._get_allowed_ordinary_camera(entity_id)
        stream_source = await camera.stream_source()
        if not isinstance(stream_source, str) or not _DIRECT_SOURCE.fullmatch(stream_source):
            raise MiniAppOperationError("stream_source_unavailable")

        internal_name = self.mse_internal_stream_name(entity_id)

        # Mini App MSE uses the resolved camera source directly inside the
        # HA-managed go2rtc instance. For Generic Camera RTSP sources, explicitly
        # disable go2rtc's ONVIF backchannel probe: the default probe sends an
        # ONVIF-backchannel DESCRIBE first and may consume a full RTSP response
        # timeout before reconnecting without backchannel. Ordinary surveillance
        # viewing does not need a camera backchannel.
        registry = er.async_get(self.hass)
        entry = registry.async_get(entity_id)
        if (
            entry is not None
            and entry.platform == "generic"
            and stream_source.startswith(("rtsp://", "rtsps://"))
        ):
            separator = "&" if "#" in stream_source else "#"
            stream_source = f"{stream_source}{separator}backchannel=0"

        # The source remains server-side and is never serialized to the browser.
        stream_sources = [stream_source]
        if progress is not None:
            progress("mse_source_resolved")

        async with self._mse_lock:
            stream = self._mse_streams.get(entity_id)
            if stream is None:
                if len(self._mse_streams) >= _MAX_MSE_STREAMS:
                    raise MiniAppOperationError("mse_registry_full")
                stream = _MiniAppMSEStream(
                    internal_name=internal_name,
                    register_task=self.hass.async_create_task(
                        self.go2rtc.register_stream(internal_name, stream_sources)
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
        if progress is not None:
            progress("mse_stream_registered")
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

    async def _await_webcodecs_manager_cleanup(self, manager: Any) -> None:
        """Synchronize with one in-flight miniapp_webcodecs teardown.

        Waiting is a local ownership barrier only. It never re-sends or retries
        a Comelit operation.
        """
        status_getter = getattr(manager, "status", None)
        if manager is None or not callable(status_getter):
            return

        def snapshot() -> tuple[str, bool]:
            status = status_getter()
            if not isinstance(status, dict):
                return str(getattr(manager, "phase", "unknown")), False
            phase = str(status.get("phase") or getattr(manager, "phase", "unknown"))
            leases = status.get("leases")
            webcodecs_owned = (
                isinstance(leases, dict)
                and bool(leases.get("miniapp_webcodecs"))
            )
            return phase, webcodecs_owned

        phase, webcodecs_owned = snapshot()
        if phase == "error":
            raise MiniAppOperationError("webcodecs_cleanup_failed")
        if phase == "inactive":
            return
        if not webcodecs_owned and phase != "stopping":
            return

        loop = asyncio.get_running_loop()
        deadline = loop.time() + _WEBCODECS_HLS_FALLBACK_CLEANUP_SECONDS
        while True:
            phase, webcodecs_owned = snapshot()
            if phase == "inactive":
                return
            if phase == "error":
                raise MiniAppOperationError("webcodecs_cleanup_failed")
            if phase == "active" and not webcodecs_owned:
                raise MiniAppOperationError("webcodecs_cleanup_conflict")

            remaining = deadline - loop.time()
            if remaining <= 0:
                raise MiniAppOperationError("webcodecs_cleanup_timeout")
            await asyncio.sleep(min(0.05, remaining))

    async def _await_webcodecs_entrance_cleanup(
        self,
        entity_id: str,
    ) -> None:
        """Wait for prior Entrance WebCodecs ownership before HLS fallback."""
        registry = er.async_get(self.hass)
        registry_entry = registry.async_get(entity_id)
        if (
            registry_entry is None
            or registry_entry.platform != DOMAIN
            or registry_entry.unique_id != ENTRANCE_CAMERA_UNIQUE_ID
        ):
            return

        config_entry = self._entry
        entry_id = (
            getattr(config_entry, "entry_id", None)
            if config_entry is not None
            else None
        )
        if not isinstance(entry_id, str) or not entry_id:
            return

        manager = (
            self.hass.data.get(DOMAIN, {})
            .get(DATA_MEDIA_SESSIONS, {})
            .get(entry_id)
        )
        await self._await_webcodecs_manager_cleanup(manager)

    def _is_entrance_camera_entity(self, entity_id: str) -> bool:
        registry = er.async_get(self.hass)
        registry_entry = registry.async_get(entity_id)
        return (
            registry_entry is not None
            and registry_entry.platform == DOMAIN
            and registry_entry.unique_id == ENTRANCE_CAMERA_UNIQUE_ID
        )

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

        if self._is_entrance_camera_entity(entity_id):
            async with self._attached_viewer_lock:
                upstream_master = self._miniapp_attached_hls_master_path_locked()
            if upstream_master is None:
                raise MiniAppOperationError("attached_media_stream_unavailable")
        else:
            await self._await_webcodecs_entrance_cleanup(entity_id)

            # Use Home Assistant's normal camera stream API for ordinary
            # cameras. The WebView receives only a session-bound proxy path.
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
