from __future__ import annotations

import asyncio
import copy
import inspect
import logging
import re
from typing import Any
from urllib.parse import urljoin

from homeassistant.components.camera import (
    Camera,
    CameraEntityFeature,
    get_dynamic_camera_stream_settings,
)
from homeassistant.components.stream import (
    ATTR_SETTINGS,
    ATTR_STREAMS,
    DOMAIN as STREAM_DOMAIN,
    Stream,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DATA_MEDIA_SESSIONS,
    DATA_MEDIA_TRANSPORTS,
    DOMAIN,
    ENTRANCE_CAMERA_ENTITY_ID,
    ENTRANCE_CAMERA_UNIQUE_ID,
)
from .media_session import MEDIA_PHASE_ERROR, ComelitMediaSessionManager
from .media_transport import ComelitEntranceMediaTransport

try:  # pragma: no cover - import-shape guard around HA internals
    from homeassistant.components.stream import HLS_PROVIDER
except Exception:  # pragma: no cover - keeps the integration importable
    HLS_PROVIDER = "hls_provider"

try:  # pragma: no cover - optional HA runtime helper
    from homeassistant.components.camera.const import StreamType
except Exception:  # pragma: no cover - import-shape guard around HA internals
    try:
        from homeassistant.components.camera import StreamType
    except Exception:  # pragma: no cover - keeps static tooling importable
        StreamType = None

try:  # pragma: no cover - optional HA runtime helper
    from homeassistant.helpers.aiohttp_client import async_get_clientsession
except Exception:  # pragma: no cover - self-HTTP unavailable
    async_get_clientsession = None

try:  # pragma: no cover - optional HA runtime helper
    from homeassistant.helpers.network import NoURLAvailableError, get_url
except Exception:  # pragma: no cover - self-HTTP unavailable
    NoURLAvailableError = Exception
    get_url = None

try:  # pragma: no cover - optional HA runtime helper
    from aiohttp import ClientTimeout
except Exception:  # pragma: no cover - self-HTTP unavailable
    ClientTimeout = None

try:  # pragma: no cover - HA private implementation guard
    from homeassistant.components.stream.hls import HlsMasterPlaylistView, HlsPlaylistView
except Exception:  # pragma: no cover - direct render unavailable
    HlsMasterPlaylistView = None
    HlsPlaylistView = None


_LOGGER = logging.getLogger(__name__)
_DIAGNOSTIC_SAFE_STRING = re.compile(r"^[A-Za-z0-9_.-]{1,32}$")
_HLS_CODEC_STRING = re.compile(
    r"^(avc1|avc3|hvc1|hev1|mp4a|opus|mp4v)\.[0-9A-Fa-f.]+$"
)
_HLS_DIAGNOSTIC_FIELDS = (
    "ha_stream_created",
    "ha_stream_available",
    "ha_stream_worker_error_count",
    "ha_stream_start_worker_count",
    "ha_stream_container_format",
    "ha_stream_video_codec",
    "hls_provider_present",
    "hls_segment_count",
    "hls_part_count",
    "hls_init_bytes",
    "hls_first_part_bytes",
    "hls_first_part_has_keyframe",
    "hls_first_segment_complete",
    "hls_second_segment_created",
)
_HLS_HTTP_DIAGNOSTIC_FIELDS = (
    "hls_endpoint_generated",
    "hls_probe_mode",
    "hls_probe_completed",
    "hls_http_routing_proven",
    "hls_master_probe_attempted",
    "hls_master_http_status",
    "hls_master_content_type_ok",
    "hls_master_bytes",
    "hls_master_has_extm3u",
    "hls_master_has_stream_inf",
    "hls_master_has_playlist_reference",
    "hls_master_codec_string",
    "hls_media_probe_attempted",
    "hls_media_http_status",
    "hls_media_content_type_ok",
    "hls_media_bytes",
    "hls_media_has_extm3u",
    "hls_media_has_map",
    "hls_media_has_part",
    "hls_media_has_extinf",
    "hls_media_part_reference_count",
    "hls_media_segment_reference_count",
    "hls_init_probe_attempted",
    "hls_init_http_status",
    "hls_init_content_type_ok",
    "hls_init_bytes_http",
    "hls_part_probe_attempted",
    "hls_part_http_status",
    "hls_part_content_type_ok",
    "hls_part_bytes_http",
    "camera_frontend_hls_supported",
    "camera_frontend_webrtc_supported",
    "camera_webrtc_provider_present",
)
_HLS_PLAYLIST_CONTENT_TYPES = (
    "application/vnd.apple.mpegurl",
    "application/x-mpegurl",
    "audio/mpegurl",
)
_HLS_MEDIA_CONTENT_TYPES = (
    "video/mp4",
    "application/mp4",
    "application/octet-stream",
)


def _safe_diagnostic_string(value: Any) -> str | None:
    if isinstance(value, str) and _DIAGNOSTIC_SAFE_STRING.fullmatch(value):
        return value
    return None


def _format_diagnostic_value(value: Any) -> str:
    if value is None:
        return "unknown"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int) and value >= 0:
        return str(value)
    safe = _safe_diagnostic_string(value)
    if safe is not None:
        return safe
    return "unknown"


def _bounded_non_bool_int(value: Any, *, maximum: int | None = None) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        if maximum is not None:
            return min(value, maximum)
        return value
    return None


def _content_type_matches(value: str | None, prefixes: tuple[str, ...]) -> bool:
    if value is None:
        return False
    normalized = value.split(";", 1)[0].strip().lower()
    return any(normalized.startswith(prefix) for prefix in prefixes)


def _extract_hls_codec_string(playlist: str) -> str:
    match = re.search(r'CODECS="([^"]{1,128})"', playlist)
    if match is None:
        return "unknown"
    tokens = [token.strip() for token in match.group(1).split(",")]
    joined = ",".join(tokens)
    if not tokens or len(joined) > 64:
        return "unknown"
    if all(_HLS_CODEC_STRING.fullmatch(token) for token in tokens):
        return joined
    return "unknown"


def _count_bounded(pattern: str, text: str) -> int:
    return min(len(re.findall(pattern, text)), 64)


def _first_relative_part_name(playlist: str) -> str | None:
    match = re.search(r'#EXT-X-PART:[^\n]*URI="([^"]+)"', playlist)
    if match is None:
        return None
    name = match.group(1)
    if "://" in name or name.startswith("//") or "/" in name or not name.endswith(".m4s"):
        return None
    return name


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
        async_add_entities([ComelitEntranceCamera(manager, transport)])


class ComelitEntranceCamera(Camera):
    """HA camera view over the already-active local Comelit RTP session.

    The camera entity never starts a Comelit session itself. The explicit
    switch owns start/stop, so merely opening a dashboard card cannot create a
    hidden cloud session or extend the absolute media lifetime.
    """

    _attr_name = "Comelit — Камера подъезда"
    _attr_unique_id = ENTRANCE_CAMERA_UNIQUE_ID
    _attr_icon = "mdi:video"
    _attr_supported_features = CameraEntityFeature.STREAM
    _attr_should_poll = False

    def __init__(
        self,
        manager: ComelitMediaSessionManager,
        transport: ComelitEntranceMediaTransport,
    ) -> None:
        super().__init__()
        self._manager = manager
        self._transport = transport
        self._stream_reset_task: asyncio.Task[None] | None = None
        self._last_hls_diagnostics_signature: tuple[Any, ...] | None = None
        self._hls_http_probe_task: asyncio.Task[None] | None = None
        self._hls_http_probe_done = False
        self._hls_http_probe_result: dict[str, Any] | None = None
        self.entity_id = ENTRANCE_CAMERA_ENTITY_ID

    @property
    def use_stream_for_stills(self) -> bool:
        """Generate snapshots from the same H264 stream as live view."""
        return True

    @property
    def available(self) -> bool:
        return super().available and self._manager.phase != MEDIA_PHASE_ERROR

    @property
    def is_streaming(self) -> bool:
        return self._manager.active and self._transport.video_forwarding

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        status = self._manager.status()
        video_age = self._transport.video_last_packet_age_seconds
        audio_age = self._transport.audio_last_packet_age_seconds
        attrs = {
            "media_active": status["active"],
            "media_phase": status["phase"],
            "expires_at": status["expires_at"],
            "remaining_seconds": status["remaining_seconds"],
            "listener_paused": status["listener_paused"],
            "video_forwarding": self._transport.video_forwarding,
            "audio_forwarding": self._transport.audio_forwarding,
            "video_packet_count": self._transport.video_packet_count,
            "audio_packet_count": self._transport.audio_packet_count,
            "video_last_packet_age_seconds": (
                round(video_age, 1) if video_age is not None else None
            ),
            "audio_last_packet_age_seconds": (
                round(audio_age, 1) if audio_age is not None else None
            ),
            "automatic_session_start": False,
            "hard_limit_seconds": self._manager.hard_limit_seconds,
        }
        attrs.update(self._hls_runtime_diagnostics())
        attrs.update(self._hls_http_boundary_diagnostics())
        return attrs

    def _new_hls_http_probe_result(self) -> dict[str, Any]:
        result: dict[str, Any] = dict.fromkeys(_HLS_HTTP_DIAGNOSTIC_FIELDS)
        result.update(
            {
                "hls_endpoint_generated": False,
                "hls_probe_mode": "none",
                "hls_probe_completed": False,
                "hls_http_routing_proven": False,
                "hls_master_probe_attempted": False,
                "hls_master_codec_string": "unknown",
                "hls_media_probe_attempted": False,
                "hls_init_probe_attempted": False,
                "hls_part_probe_attempted": False,
            }
        )
        result.update(self._camera_frontend_capability_diagnostics())
        return result

    def _hls_http_boundary_diagnostics(self) -> dict[str, Any]:
        result = self._new_hls_http_probe_result()
        if self._hls_http_probe_result is not None:
            result.update(self._hls_http_probe_result)
        return result

    def _reset_hls_http_probe_state(self) -> None:
        if self._hls_http_probe_task is not None and not self._hls_http_probe_task.done():
            self._hls_http_probe_task.cancel()
        self._hls_http_probe_task = None
        self._hls_http_probe_done = False
        self._hls_http_probe_result = None

    def _camera_frontend_capability_diagnostics(self) -> dict[str, bool | None]:
        hls_supported: bool | None = None
        webrtc_supported: bool | None = None
        provider_present: bool | None = None
        try:
            capabilities = self.camera_capabilities
        except Exception:
            capabilities = None
        try:
            stream_types = capabilities.frontend_stream_types
        except Exception:
            stream_types = None
        if (
            StreamType is not None
            and isinstance(stream_types, (set, frozenset, list, tuple))
        ):
            try:
                hls_supported = StreamType.HLS in stream_types
                webrtc_supported = StreamType.WEB_RTC in stream_types
            except Exception:
                hls_supported = None
                webrtc_supported = None
        try:
            provider_present = getattr(self, "webrtc_provider", None) is not None
        except Exception:
            provider_present = None
        return {
            "camera_frontend_hls_supported": hls_supported,
            "camera_frontend_webrtc_supported": webrtc_supported,
            "camera_webrtc_provider_present": provider_present,
        }

    def _hls_runtime_diagnostics(self) -> dict[str, Any]:
        diagnostics: dict[str, Any] = dict.fromkeys(_HLS_DIAGNOSTIC_FIELDS)
        stream = None
        try:
            stream = self.stream
        except Exception:
            stream = None

        diagnostics["ha_stream_created"] = stream is not None
        diagnostics["hls_provider_present"] = False
        if stream is None:
            return diagnostics

        try:
            available = getattr(stream, "available", None)
            if isinstance(available, bool):
                diagnostics["ha_stream_available"] = available
        except Exception:
            pass

        try:
            stream_diagnostics = stream.get_diagnostics()
        except Exception:
            stream_diagnostics = None
        if isinstance(stream_diagnostics, dict):
            diagnostics["ha_stream_container_format"] = _safe_diagnostic_string(
                stream_diagnostics.get("container_format")
            )
            diagnostics["ha_stream_video_codec"] = _safe_diagnostic_string(
                stream_diagnostics.get("video_codec")
            )
            worker_error = stream_diagnostics.get("worker_error")
            if (
                isinstance(worker_error, int)
                and not isinstance(worker_error, bool)
                and worker_error >= 0
            ):
                diagnostics["ha_stream_worker_error_count"] = worker_error
            start_worker = stream_diagnostics.get("start_worker")
            if (
                isinstance(start_worker, int)
                and not isinstance(start_worker, bool)
                and start_worker >= 0
            ):
                diagnostics["ha_stream_start_worker_count"] = start_worker

        try:
            outputs = stream.outputs()
        except Exception:
            outputs = None
        provider = None
        if outputs is not None:
            try:
                provider = outputs.get(HLS_PROVIDER)
            except Exception:
                provider = None
        diagnostics["hls_provider_present"] = provider is not None

        segments = None
        if provider is not None:
            try:
                segments = provider.get_segments()
            except Exception:
                segments = None
        if segments is None:
            return diagnostics

        try:
            segment_count = len(segments)
        except Exception:
            segment_count = None

        segments_list = []
        try:
            for index, segment in enumerate(segments):
                if index >= 64:
                    break
                segments_list.append(segment)
        except Exception:
            return diagnostics
        if segment_count is None:
            segment_count = len(segments_list)

        diagnostics["hls_segment_count"] = segment_count
        diagnostics["hls_second_segment_created"] = segment_count >= 2
        part_count = 0
        first_parts = []
        for index, segment in enumerate(segments_list):
            try:
                parts = segment.parts
            except Exception:
                parts = ()
            try:
                part_count += len(parts)
            except Exception:
                bounded_parts = []
                try:
                    for part_index, part in enumerate(parts):
                        if part_index >= 256:
                            break
                        bounded_parts.append(part)
                except Exception:
                    bounded_parts = []
                parts = bounded_parts
                part_count += len(bounded_parts)
            if index == 0:
                try:
                    first_parts = list(parts[:256])
                except Exception:
                    first_parts = []
                    try:
                        for part_index, part in enumerate(parts):
                            if part_index >= 256:
                                break
                            first_parts.append(part)
                    except Exception:
                        first_parts = []
        diagnostics["hls_part_count"] = part_count
        if not segments_list:
            return diagnostics

        first_segment = segments_list[0]
        try:
            diagnostics["hls_init_bytes"] = len(first_segment.init)
        except Exception:
            diagnostics["hls_init_bytes"] = None
        try:
            diagnostics["hls_first_segment_complete"] = bool(first_segment.complete)
        except Exception:
            diagnostics["hls_first_segment_complete"] = None
        if not first_parts:
            return diagnostics

        first_part = first_parts[0]
        try:
            diagnostics["hls_first_part_bytes"] = len(first_part.data)
        except Exception:
            diagnostics["hls_first_part_bytes"] = None
        try:
            diagnostics["hls_first_part_has_keyframe"] = bool(first_part.has_keyframe)
        except Exception:
            diagnostics["hls_first_part_has_keyframe"] = None
        return diagnostics

    def _log_hls_runtime_diagnostics_if_changed(self) -> None:
        payload = self._hls_runtime_diagnostics()
        payload["video_packet_count"] = self._transport.video_packet_count
        signature = tuple((field, payload[field]) for field in sorted(payload))
        if signature == self._last_hls_diagnostics_signature:
            return
        self._last_hls_diagnostics_signature = signature
        _LOGGER.info(
            "Comelit HLS diagnostics: %s",
            " ".join(
                f"{key}={_format_diagnostic_value(value)}"
                for key, value in sorted(payload.items())
            ),
        )

    async def stream_source(self) -> str | None:
        """Return local SDP only while the explicit media switch owns a session."""
        if not self._manager.active:
            return None
        path = self._transport.local_sdp_path
        ready = await self.hass.async_add_executor_job(
            lambda: self._transport.local_sdp_ready
        )
        if not ready:
            return None
        return str(path)

    async def async_create_stream(self) -> Stream | None:
        """Create HA Stream while passing SDP protocol permissions to PyAV.

        Current Home Assistant validates camera ``stream_options`` and no longer
        accepts arbitrary FFmpeg/PyAV keys such as ``protocol_whitelist``.
        A local SDP file which references RTP/UDP still requires that whitelist
        at the libavformat layer, so construct the standard HA Stream directly
        with the required PyAV option instead of placing it in stream_options.
        """
        if not self._manager.active:
            return None
        if not self._create_stream_lock:
            self._create_stream_lock = asyncio.Lock()
        async with self._create_stream_lock:
            if self.stream is None:
                source = await self.stream_source()
                if source is None:
                    return None
                stream = Stream(
                    self.hass,
                    source,
                    pyav_options={"protocol_whitelist": "file,udp,rtp"},
                    stream_settings=copy.copy(
                        self.hass.data[STREAM_DOMAIN][ATTR_SETTINGS]
                    ),
                    dynamic_stream_settings=await get_dynamic_camera_stream_settings(
                        self.hass, self.entity_id
                    ),
                    stream_label=self.entity_id,
                )
                self.hass.data[STREAM_DOMAIN][ATTR_STREAMS].append(stream)
                stream.set_update_callback(self.async_write_ha_state)
                self.stream = stream
                self._reset_hls_http_probe_state()
                self._last_hls_diagnostics_signature = None
            return self.stream

    async def async_camera_image(
        self,
        width: int | None = None,
        height: int | None = None,
    ) -> bytes | None:
        """Return a still only from an already-active local media stream."""
        if not self._manager.active:
            return None
        stream = self.stream or await self.async_create_stream()
        if stream is None:
            return None
        return await stream.async_get_image(width=width, height=height)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            self._manager.async_add_status_listener(self._handle_status_update)
        )
        self.async_on_remove(
            self._transport.async_add_status_listener(self._handle_status_update)
        )

    async def async_will_remove_from_hass(self) -> None:
        await self._async_reset_stream()
        await super().async_will_remove_from_hass()

    def _handle_status_update(self) -> None:
        if not self._manager.active and self.stream is not None:
            if self._stream_reset_task is None or self._stream_reset_task.done():
                self._stream_reset_task = self.hass.async_create_task(
                    self._async_reset_stream(),
                    "reset Comelit entrance camera stream",
                )
        hls_diagnostics = self._hls_runtime_diagnostics()
        if (
            hls_diagnostics["ha_stream_created"]
            and hls_diagnostics["hls_provider_present"]
            and isinstance(hls_diagnostics["hls_segment_count"], int)
            and hls_diagnostics["hls_segment_count"] >= 2
            and not self._hls_http_probe_done
            and (
                self._hls_http_probe_task is None
                or self._hls_http_probe_task.done()
            )
        ):
            self._hls_http_probe_task = self.hass.async_create_task(
                self._async_probe_hls_http_boundary(),
                "probe Comelit HLS HTTP boundary",
            )
        self._log_hls_runtime_diagnostics_if_changed()
        self.async_write_ha_state()

    async def _async_reset_stream(self) -> None:
        self._reset_hls_http_probe_state()
        self._last_hls_diagnostics_signature = None
        stream = self.stream
        if stream is None:
            return
        await stream.stop()
        if self.stream is stream:
            self.stream = None

    async def _async_probe_hls_http_boundary(self) -> None:
        result = self._new_hls_http_probe_result()
        cancelled = False
        try:
            result.update(await self._async_build_hls_http_boundary_result())
        except asyncio.CancelledError:
            cancelled = True
        except Exception:
            result["hls_probe_mode"] = "unavailable"
        finally:
            if cancelled:
                return
            result["hls_probe_completed"] = True
            result.update(self._camera_frontend_capability_diagnostics())
            self._hls_http_probe_result = result
            self._hls_http_probe_done = True
            _LOGGER.info(
                "Comelit HLS HTTP diagnostics: %s",
                " ".join(
                    f"{key}={_format_diagnostic_value(result.get(key))}"
                    for key in _HLS_HTTP_DIAGNOSTIC_FIELDS
                ),
            )
            self.async_write_ha_state()

    async def _async_build_hls_http_boundary_result(self) -> dict[str, Any]:
        stream = self.stream
        if stream is None:
            result = self._new_hls_http_probe_result()
            result["hls_probe_mode"] = "unavailable"
            return result

        endpoint = self._hls_endpoint_fragment(stream)
        if endpoint is None:
            return await self._async_direct_render_hls_probe(
                stream,
                hls_endpoint_generated=False,
            )

        if get_url is None or async_get_clientsession is None or ClientTimeout is None:
            return await self._async_direct_render_hls_probe(
                stream,
                hls_endpoint_generated=True,
            )

        try:
            base = get_url(
                self.hass,
                allow_internal=True,
                prefer_external=False,
                allow_cloud=False,
            )
        except NoURLAvailableError:
            return await self._async_direct_render_hls_probe(
                stream,
                hls_endpoint_generated=True,
            )
        except Exception:
            return await self._async_direct_render_hls_probe(
                stream,
                hls_endpoint_generated=True,
            )

        return await self._async_self_http_hls_probe(base, endpoint)

    def _hls_endpoint_fragment(self, stream: Stream) -> str | None:
        try:
            endpoint = stream.endpoint_url(HLS_PROVIDER)
        except Exception:
            return None
        if not isinstance(endpoint, str) or not endpoint:
            return None
        return endpoint

    async def _async_self_http_hls_probe(
        self,
        base: str,
        endpoint: str,
    ) -> dict[str, Any]:
        result = self._new_hls_http_probe_result()
        result["hls_endpoint_generated"] = True
        result["hls_probe_mode"] = "self_http"
        session = async_get_clientsession(self.hass)
        timeout = ClientTimeout(total=10)
        master_address = urljoin(base.rstrip("/") + "/", endpoint.lstrip("/"))
        master = await self._async_fetch_hls_scalar(
            session,
            master_address,
            timeout,
            _HLS_PLAYLIST_CONTENT_TYPES,
            read_text=True,
        )
        result.update(
            {
                "hls_master_probe_attempted": True,
                "hls_master_http_status": master["status"],
                "hls_master_content_type_ok": master["content_type_ok"],
                "hls_master_bytes": master["bytes"],
            }
        )
        master_text = master["text"]
        if isinstance(master_text, str):
            result.update(
                {
                    "hls_master_has_extm3u": "#EXTM3U" in master_text,
                    "hls_master_has_stream_inf": "#EXT-X-STREAM-INF" in master_text,
                    "hls_master_has_playlist_reference": (
                        _count_bounded(r"\.m3u8(?:\?|$)", master_text) == 1
                    ),
                    "hls_master_codec_string": _extract_hls_codec_string(master_text),
                }
            )

        media_address = master_address.replace("master_playlist.m3u8", "playlist.m3u8")
        media = await self._async_fetch_hls_scalar(
            session,
            media_address,
            timeout,
            _HLS_PLAYLIST_CONTENT_TYPES,
            read_text=True,
        )
        result.update(
            {
                "hls_media_probe_attempted": True,
                "hls_media_http_status": media["status"],
                "hls_media_content_type_ok": media["content_type_ok"],
                "hls_media_bytes": media["bytes"],
            }
        )
        media_text = media["text"]
        part_name = None
        if isinstance(media_text, str):
            part_name = _first_relative_part_name(media_text)
            result.update(
                {
                    "hls_media_has_extm3u": "#EXTM3U" in media_text,
                    "hls_media_has_map": "#EXT-X-MAP" in media_text,
                    "hls_media_has_part": "#EXT-X-PART" in media_text,
                    "hls_media_has_extinf": "#EXTINF" in media_text,
                    "hls_media_part_reference_count": _count_bounded(
                        r'#EXT-X-PART:[^\n]*URI="[^"]+\.m4s"', media_text
                    ),
                    "hls_media_segment_reference_count": min(
                        _count_bounded(r"#EXTINF", media_text),
                        _count_bounded(r"(?m)^[^#\n][^\n]*\.m4s(?:\?|$)", media_text),
                    ),
                }
            )

        init_address = media_address.replace("playlist.m3u8", "init.mp4")
        init = await self._async_fetch_hls_scalar(
            session,
            init_address,
            timeout,
            _HLS_MEDIA_CONTENT_TYPES,
            read_text=False,
        )
        result.update(
            {
                "hls_init_probe_attempted": True,
                "hls_init_http_status": init["status"],
                "hls_init_content_type_ok": init["content_type_ok"],
                "hls_init_bytes_http": init["bytes"],
            }
        )

        if part_name is not None:
            part_address = media_address.rsplit("/", 1)[0] + "/" + part_name
            part = await self._async_fetch_hls_scalar(
                session,
                part_address,
                timeout,
                _HLS_MEDIA_CONTENT_TYPES,
                read_text=False,
            )
            result.update(
                {
                    "hls_part_probe_attempted": True,
                    "hls_part_http_status": part["status"],
                    "hls_part_content_type_ok": part["content_type_ok"],
                    "hls_part_bytes_http": part["bytes"],
                }
            )

        result["hls_http_routing_proven"] = all(
            _bounded_non_bool_int(result.get(field)) is not None
            and 200 <= result[field] < 300
            for field in (
                "hls_master_http_status",
                "hls_media_http_status",
                "hls_init_http_status",
            )
        )
        return result

    async def _async_fetch_hls_scalar(
        self,
        session: Any,
        address: str,
        timeout: Any,
        content_types: tuple[str, ...],
        *,
        read_text: bool,
    ) -> dict[str, Any]:
        scalar = {
            "status": None,
            "content_type_ok": None,
            "bytes": None,
            "text": None,
        }
        try:
            async with session.get(
                address,
                allow_redirects=False,
                timeout=timeout,
            ) as response:
                scalar["status"] = _bounded_non_bool_int(response.status)
                content_type_ok = _content_type_matches(
                    response.headers.get("Content-Type"),
                    content_types,
                )
                if 300 <= response.status < 400:
                    content_type_ok = False
                scalar["content_type_ok"] = content_type_ok
                body = await response.read()
                scalar["bytes"] = len(body)
                if read_text:
                    scalar["text"] = body[:65536].decode("utf-8", "replace")
        except Exception:
            pass
        return scalar

    async def _async_direct_render_hls_probe(
        self,
        stream: Stream,
        *,
        hls_endpoint_generated: bool,
    ) -> dict[str, Any]:
        result = self._new_hls_http_probe_result()
        result["hls_http_routing_proven"] = False
        if HlsMasterPlaylistView is None or HlsPlaylistView is None:
            result["hls_probe_mode"] = "unavailable"
            return result
        try:
            outputs = stream.outputs()
            track = outputs.get(HLS_PROVIDER)
        except Exception:
            track = None
        if track is None:
            result["hls_probe_mode"] = "unavailable"
            return result
        result["hls_probe_mode"] = "direct_render"
        result["hls_master_probe_attempted"] = True
        result["hls_media_probe_attempted"] = True
        result["hls_master_http_status"] = None
        result["hls_media_http_status"] = None
        result["hls_init_http_status"] = None
        result["hls_part_http_status"] = None
        try:
            master_text = HlsMasterPlaylistView.render(track)
            if inspect.isawaitable(master_text):
                master_text = await master_text
            media_text = HlsPlaylistView.render(track)
            if inspect.isawaitable(media_text):
                media_text = await media_text
            if not isinstance(master_text, str) or not isinstance(media_text, str):
                result["hls_probe_mode"] = "unavailable"
                return result
            result["hls_endpoint_generated"] = hls_endpoint_generated
            result["hls_master_bytes"] = len(master_text.encode("utf-8"))
            result["hls_media_bytes"] = len(media_text.encode("utf-8"))
            if master_text:
                result.update(
                    {
                        "hls_master_has_extm3u": "#EXTM3U" in master_text,
                        "hls_master_has_stream_inf": "#EXT-X-STREAM-INF" in master_text,
                        "hls_master_has_playlist_reference": (
                            _count_bounded(r"\.m3u8(?:\?|$)", master_text) == 1
                        ),
                        "hls_master_codec_string": _extract_hls_codec_string(
                            master_text
                        ),
                    }
                )
            if media_text:
                result.update(
                    {
                        "hls_media_has_extm3u": "#EXTM3U" in media_text,
                        "hls_media_has_map": "#EXT-X-MAP" in media_text,
                        "hls_media_has_part": "#EXT-X-PART" in media_text,
                        "hls_media_has_extinf": "#EXTINF" in media_text,
                        "hls_media_part_reference_count": _count_bounded(
                            r'#EXT-X-PART:[^\n]*URI="[^"]+\.m4s"', media_text
                        ),
                        "hls_media_segment_reference_count": min(
                            _count_bounded(r"#EXTINF", media_text),
                            _count_bounded(
                                r"(?m)^[^#\n][^\n]*\.m4s(?:\?|$)",
                                media_text,
                            ),
                        ),
                    }
                )
        except Exception:
            result["hls_probe_mode"] = "unavailable"
        result["hls_http_routing_proven"] = False
        result["hls_master_http_status"] = None
        result["hls_media_http_status"] = None
        result["hls_init_http_status"] = None
        result["hls_part_http_status"] = None
        return result
