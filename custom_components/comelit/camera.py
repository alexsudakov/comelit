from __future__ import annotations

import asyncio
import copy
import logging
import re
from typing import Any

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


_LOGGER = logging.getLogger(__name__)
_DIAGNOSTIC_SAFE_STRING = re.compile(r"^[A-Za-z0-9_.-]{1,32}$")
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
_HLS_WORKER_ERROR_COUNT_KEYS = (
    "stream_worker_error_count",
    "worker_error_count",
    "error_count",
)
_HLS_START_WORKER_COUNT_KEYS = (
    "start_worker_count",
    "stream_start_worker_count",
    "worker_start_count",
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
        return attrs

    def _hls_runtime_diagnostics(self) -> dict[str, Any]:
        diagnostics: dict[str, Any] = dict.fromkeys(_HLS_DIAGNOSTIC_FIELDS)
        stream = None
        try:
            stream = self.stream
        except Exception:
            stream = None

        diagnostics["ha_stream_created"] = stream is not None
        diagnostics["hls_provider_present"] = False
        if stream is not None:
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

            output_diagnostics_available = False
            worker_error_count = 0
            start_worker_count = 0
            try:
                outputs = stream.outputs()
            except Exception:
                outputs = ()
            try:
                for index, output in enumerate(outputs):
                    if index >= 16:
                        break
                    try:
                        output_diagnostics = output.get_diagnostics()
                    except Exception:
                        continue
                    if not isinstance(output_diagnostics, dict):
                        continue
                    output_diagnostics_available = True
                    for candidate in _HLS_WORKER_ERROR_COUNT_KEYS:
                        value = output_diagnostics.get(candidate)
                        if (
                            isinstance(value, int)
                            and not isinstance(value, bool)
                            and value >= 0
                        ):
                            worker_error_count += value
                            break
                    for candidate in _HLS_START_WORKER_COUNT_KEYS:
                        value = output_diagnostics.get(candidate)
                        if (
                            isinstance(value, int)
                            and not isinstance(value, bool)
                            and value >= 0
                        ):
                            start_worker_count += value
                            break
            except Exception:
                output_diagnostics_available = False
            if output_diagnostics_available:
                diagnostics["ha_stream_worker_error_count"] = worker_error_count
                diagnostics["ha_stream_start_worker_count"] = start_worker_count

        provider = None
        try:
            stream_data = self.hass.data[STREAM_DOMAIN]
            provider = stream_data.get(HLS_PROVIDER)
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
        self._log_hls_runtime_diagnostics_if_changed()
        self.async_write_ha_state()

    async def _async_reset_stream(self) -> None:
        self._last_hls_diagnostics_signature = None
        stream = self.stream
        if stream is None:
            return
        await stream.stop()
        if self.stream is stream:
            self.stream = None
