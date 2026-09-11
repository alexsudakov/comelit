from __future__ import annotations

import asyncio
import copy
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
        return {
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
        self.async_write_ha_state()

    async def _async_reset_stream(self) -> None:
        stream = self.stream
        if stream is None:
            return
        await stream.stop()
        if self.stream is stream:
            self.stream = None
