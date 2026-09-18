from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
import copy
from dataclasses import dataclass
from datetime import UTC, datetime
import logging
import os
from pathlib import Path
import re
from time import monotonic
from typing import Any, Protocol

from homeassistant.core import HomeAssistant

try:  # pragma: no cover - import-shape guard around HA internals
    from homeassistant.components.stream import (
        ATTR_SETTINGS,
        ATTR_STREAMS,
        DOMAIN as STREAM_DOMAIN,
        Stream,
    )
    from homeassistant.components.camera import get_dynamic_camera_stream_settings
except Exception:  # pragma: no cover - keeps static tooling importable
    ATTR_SETTINGS = "settings"
    ATTR_STREAMS = "streams"
    STREAM_DOMAIN = "stream"
    Stream = None
    get_dynamic_camera_stream_settings = None

from .const import (
    ATTR_CAMERA_ENTITY,
    ATTR_DOOR,
    ATTR_DURATION_ACTUAL_SECONDS,
    ATTR_DURATION_TARGET_SECONDS,
    ATTR_EVENT_ID,
    ATTR_RECORDING_PATH,
    ATTR_SEQUENCE,
    ATTR_SNAPSHOT_PATH,
    ATTR_STATE,
    ATTR_TIMESTAMP,
    DOOR_ENTRANCE,
    ENTRANCE_CAMERA_ENTITY_ID,
    EVENT_RECORDING_COMPLETE,
    EVENT_SNAPSHOT_UPDATED,
    RECORDING_STATE_COMPLETED,
    RECORDING_STATE_FAILED,
    RECORDING_STATE_TRUNCATED,
    RECORDING_TARGET_SECONDS,
    SNAPSHOT_REFRESH_TARGET_SECONDS,
)
from .media_session import ComelitMediaSessionError, ComelitMediaSessionManager

_LOGGER = logging.getLogger(__name__)

_SAFE_EVENT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")
_RING_MEDIA_REASON = "ring_media"
_JPEG_SOI = b"\xff\xd8"
_JPEG_EOI = b"\xff\xd9"


class SnapshotProvider(Protocol):
    async def async_capture_jpeg(self) -> bytes | None: ...


class RecordingProvider(Protocol):
    async def async_record_mp4(
        self,
        path: Path,
        *,
        target_seconds: int,
        stop_event: asyncio.Event,
    ) -> str: ...


TaskFactory = Callable[
    [Coroutine[Any, Any, None], str],
    asyncio.Task[None],
]


@dataclass(frozen=True)
class RingMediaPaths:
    root: Path
    snapshot_path: Path
    recording_path: Path


def _default_task_factory(
    coro: Coroutine[Any, Any, None],
    name: str,
) -> asyncio.Task[None]:
    return asyncio.create_task(coro, name=name)


def safe_ring_media_paths(media_root: Path, event_id: str) -> RingMediaPaths:
    """Return stable per-event paths derived only from a safe event id."""
    if not _SAFE_EVENT_ID.fullmatch(event_id) or ".." in event_id:
        raise ValueError("unsafe_event_id")
    root = media_root / "comelit" / "rings" / event_id
    return RingMediaPaths(
        root=root,
        snapshot_path=root / "latest.jpg",
        recording_path=root / "recording.mp4",
    )


def _is_decodable_jpeg(data: bytes | None) -> bool:
    return (
        isinstance(data, bytes)
        and len(data) >= 4
        and data.startswith(_JPEG_SOI)
        and data.endswith(_JPEG_EOI)
    )


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    with tmp.open("wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def _timestamp() -> str:
    return datetime.now(UTC).isoformat()


class HAStreamMediaProvider:
    """Capture snapshots and recordings from the active local HA Stream path."""

    def __init__(
        self,
        hass: HomeAssistant,
        manager: ComelitMediaSessionManager,
        transport: Any,
        *,
        camera_entity: str = ENTRANCE_CAMERA_ENTITY_ID,
    ) -> None:
        self._hass = hass
        self._manager = manager
        self._transport = transport
        self._camera_entity = camera_entity
        self._stream: Any | None = None
        self._create_stream_lock: asyncio.Lock | None = None
        self.last_failure_reason: str | None = None

    async def _async_stream_source(self) -> str | None:
        if not self._manager.active:
            return None
        path = self._transport.local_sdp_path
        ready = await self._hass.async_add_executor_job(
            lambda: self._transport.local_sdp_ready
        )
        if not ready:
            return None
        return str(path)

    async def _async_create_stream(self) -> Any | None:
        if self._stream is not None:
            return self._stream
        if Stream is None or get_dynamic_camera_stream_settings is None:
            return None
        if not self._create_stream_lock:
            self._create_stream_lock = asyncio.Lock()
        async with self._create_stream_lock:
            if self._stream is not None:
                return self._stream
            source = await self._async_stream_source()
            if source is None:
                return None
            stream = Stream(
                self._hass,
                source,
                pyav_options={"protocol_whitelist": "file,udp,rtp"},
                stream_settings=copy.copy(
                    self._hass.data[STREAM_DOMAIN][ATTR_SETTINGS]
                ),
                dynamic_stream_settings=await get_dynamic_camera_stream_settings(
                    self._hass,
                    self._camera_entity,
                ),
                stream_label=self._camera_entity,
            )
            self._hass.data[STREAM_DOMAIN][ATTR_STREAMS].append(stream)
            self._stream = stream
            return stream

    async def async_capture_jpeg(self) -> bytes | None:
        stream = await self._async_create_stream()
        if stream is None:
            return None
        return await stream.async_get_image()

    async def async_close(self) -> None:
        stream = self._stream
        self._stream = None
        if stream is not None and hasattr(stream, "stop"):
            await stream.stop()

    async def async_record_mp4(
        self,
        path: Path,
        *,
        target_seconds: int,
        stop_event: asyncio.Event,
    ) -> str:
        self.last_failure_reason = None
        config = getattr(self._hass, "config", None)
        is_allowed_path = getattr(config, "is_allowed_path", None)
        if callable(is_allowed_path) and not is_allowed_path(str(path)):
            self.last_failure_reason = "recording_path_not_allowlisted"
            return RECORDING_STATE_FAILED

        stream = await self._async_create_stream()
        if stream is None:
            self.last_failure_reason = "stream_unavailable"
            return RECORDING_STATE_FAILED

        record = getattr(stream, "async_record", None)
        if record is None:
            _LOGGER.warning("HA Stream recording API is unavailable for Comelit MVP recording")
            self.last_failure_reason = "recording_api_unavailable"
            return RECORDING_STATE_FAILED

        try:
            await record(str(path), duration=target_seconds, lookback=0)
        except Exception:
            self.last_failure_reason = "recorder_exception"
            if path.is_file() and path.stat().st_size > 0:
                return RECORDING_STATE_TRUNCATED
            return RECORDING_STATE_FAILED
        if path.is_file() and path.stat().st_size > 0:
            return RECORDING_STATE_COMPLETED
        self.last_failure_reason = "recording_file_missing"
        return RECORDING_STATE_FAILED


class RingMediaCoordinator:
    """Own the bounded snapshot and recording lifecycle for one active ring."""

    def __init__(
        self,
        hass: HomeAssistant,
        manager: ComelitMediaSessionManager,
        *,
        snapshot_provider: SnapshotProvider,
        recording_provider: RecordingProvider,
        media_root: Path = Path("/media"),
        camera_entity: str = ENTRANCE_CAMERA_ENTITY_ID,
        snapshot_refresh_seconds: int = SNAPSHOT_REFRESH_TARGET_SECONDS,
        recording_target_seconds: int = RECORDING_TARGET_SECONDS,
        task_factory: TaskFactory | None = None,
        monotonic_clock: Callable[[], float] = monotonic,
    ) -> None:
        if snapshot_refresh_seconds <= 0:
            raise ValueError("snapshot_refresh_seconds must be positive")
        if recording_target_seconds <= 0:
            raise ValueError("recording_target_seconds must be positive")

        self._hass = hass
        self._manager = manager
        self._snapshot_provider = snapshot_provider
        self._recording_provider = recording_provider
        self._media_root = media_root
        self._camera_entity = camera_entity
        self._snapshot_refresh_seconds = snapshot_refresh_seconds
        self._recording_target_seconds = recording_target_seconds
        self._task_factory = task_factory or _default_task_factory
        self._monotonic = monotonic_clock
        self._active_event_id: str | None = None
        self._task: asyncio.Task[None] | None = None
        self._stop_event: asyncio.Event | None = None
        self._snapshot_event_count = 0
        self._snapshot_sequence_last = 0
        self._snapshot_first_monotonic: float | None = None
        self._snapshot_last_monotonic: float | None = None
        self._last_snapshot_path: str | None = None
        self._recording_event_count = 0
        self._last_recording_result: dict[str, object] | None = None

    @property
    def active_event_id(self) -> str | None:
        return self._active_event_id

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def status(self) -> dict[str, object]:
        average_interval: float | None = None
        if (
            self._snapshot_event_count > 1
            and self._snapshot_first_monotonic is not None
            and self._snapshot_last_monotonic is not None
        ):
            average_interval = round(
                (self._snapshot_last_monotonic - self._snapshot_first_monotonic)
                / (self._snapshot_event_count - 1),
                3,
            )
        return {
            "running": self.running,
            "active_event_id": self._active_event_id,
            "snapshot_event_count": self._snapshot_event_count,
            "snapshot_sequence_last": self._snapshot_sequence_last,
            "snapshot_average_interval_seconds": average_interval,
            "snapshot_path": self._last_snapshot_path,
            "recording_event_count": self._recording_event_count,
            "recording_result": (
                dict(self._last_recording_result)
                if self._last_recording_result is not None
                else None
            ),
        }

    async def async_start_for_ring(self, event: dict[str, object]) -> bool:
        """Start background media work for one entrance ring without blocking listener."""
        if event.get(ATTR_DOOR) != DOOR_ENTRANCE:
            return False
        event_id = event.get(ATTR_EVENT_ID)
        if not isinstance(event_id, str):
            return False
        if self.running:
            return False

        paths = safe_ring_media_paths(self._media_root, event_id)
        self._active_event_id = event_id
        self._snapshot_event_count = 0
        self._snapshot_sequence_last = 0
        self._snapshot_first_monotonic = None
        self._snapshot_last_monotonic = None
        self._last_snapshot_path = str(paths.snapshot_path)
        self._recording_event_count = 0
        self._last_recording_result = None
        self._stop_event = asyncio.Event()
        self._task = self._task_factory(
            self._async_run_lifecycle(
                event_id=event_id,
                door=DOOR_ENTRANCE,
                paths=paths,
                stop_event=self._stop_event,
            ),
            "comelit ring media lifecycle",
        )
        return True

    async def async_shutdown(self) -> None:
        stop_event = self._stop_event
        if stop_event is not None:
            stop_event.set()
        task = self._task
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._task = None
        self._stop_event = None
        self._active_event_id = None

    async def _async_run_lifecycle(
        self,
        *,
        event_id: str,
        door: str,
        paths: RingMediaPaths,
        stop_event: asyncio.Event,
    ) -> None:
        acquired = False
        recording_state = RECORDING_STATE_FAILED
        recording_started: float | None = None
        recording_actual = 0.0
        recording_failure_reason: str | None = None
        try:
            await self._manager.async_acquire(panel=door, reason=_RING_MEDIA_REASON)
            acquired = True
            snapshot_task = asyncio.create_task(
                self._async_snapshot_loop(event_id, door, paths, stop_event)
            )
            recording_started = self._monotonic()
            recording_state = await self._async_recording(
                paths,
                stop_event=stop_event,
            )
            recording_actual = max(0.0, self._monotonic() - recording_started)
            if (
                recording_state == RECORDING_STATE_COMPLETED
                and recording_actual < self._recording_target_seconds
            ):
                recording_state = RECORDING_STATE_TRUNCATED
            recording_failure_reason = self._recording_failure_reason()
            stop_event.set()
            try:
                await snapshot_task
            except asyncio.CancelledError:
                raise
            except Exception:
                _LOGGER.exception("Comelit snapshot loop failed")
        except (ComelitMediaSessionError, ValueError):
            recording_state = RECORDING_STATE_FAILED
            recording_failure_reason = "media_start_failed"
        except asyncio.CancelledError:
            stop_event.set()
            recording_state = RECORDING_STATE_TRUNCATED
            if recording_started is not None:
                recording_actual = max(0.0, self._monotonic() - recording_started)
            raise
        except Exception:
            _LOGGER.exception("Comelit ring media lifecycle failed")
            recording_state = RECORDING_STATE_FAILED
            recording_failure_reason = (
                self._recording_failure_reason() or "recorder_exception"
            )
            if recording_started is not None:
                recording_actual = max(0.0, self._monotonic() - recording_started)
        finally:
            self._fire_recording_complete(
                event_id,
                door,
                paths,
                recording_state,
                recording_actual,
                reason=recording_failure_reason,
            )
            if acquired:
                try:
                    await self._manager.async_release(reason=_RING_MEDIA_REASON)
                except Exception:
                    _LOGGER.exception("Comelit ring media release failed")
            close = getattr(self._snapshot_provider, "async_close", None)
            if close is not None:
                try:
                    await close()
                except Exception:
                    _LOGGER.exception("Comelit ring media stream cleanup failed")
            if self._active_event_id == event_id:
                self._active_event_id = None
                self._stop_event = None

    async def _async_snapshot_loop(
        self,
        event_id: str,
        door: str,
        paths: RingMediaPaths,
        stop_event: asyncio.Event,
    ) -> None:
        sequence = 0
        while not stop_event.is_set() and self._manager.active:
            jpeg = await self._snapshot_provider.async_capture_jpeg()
            if _is_decodable_jpeg(jpeg):
                sequence += 1
                await self._hass.async_add_executor_job(
                    _atomic_write,
                    paths.snapshot_path,
                    jpeg,
                )
                now = self._monotonic()
                self._snapshot_event_count += 1
                self._snapshot_sequence_last = sequence
                if self._snapshot_first_monotonic is None:
                    self._snapshot_first_monotonic = now
                self._snapshot_last_monotonic = now
                self._last_snapshot_path = str(paths.snapshot_path)
                self._hass.bus.async_fire(
                    EVENT_SNAPSHOT_UPDATED,
                    {
                        ATTR_EVENT_ID: event_id,
                        ATTR_DOOR: door,
                        ATTR_CAMERA_ENTITY: self._camera_entity,
                        ATTR_SNAPSHOT_PATH: str(paths.snapshot_path),
                        ATTR_TIMESTAMP: _timestamp(),
                        ATTR_SEQUENCE: sequence,
                    },
                )
            try:
                await asyncio.wait_for(
                    stop_event.wait(),
                    timeout=self._snapshot_refresh_seconds,
                )
            except TimeoutError:
                pass

    async def _async_recording(
        self,
        paths: RingMediaPaths,
        *,
        stop_event: asyncio.Event,
    ) -> str:
        state = await self._recording_provider.async_record_mp4(
            paths.recording_path,
            target_seconds=self._recording_target_seconds,
            stop_event=stop_event,
        )
        if state in {
            RECORDING_STATE_COMPLETED,
            RECORDING_STATE_TRUNCATED,
            RECORDING_STATE_FAILED,
        }:
            return state
        return RECORDING_STATE_FAILED

    def _recording_failure_reason(self) -> str | None:
        reason = getattr(self._recording_provider, "last_failure_reason", None)
        if isinstance(reason, str) and re.fullmatch(r"[a-z0-9_]{1,64}", reason):
            return reason
        return None

    def _fire_recording_complete(
        self,
        event_id: str,
        door: str,
        paths: RingMediaPaths,
        state: str,
        actual_seconds: float,
        *,
        reason: str | None = None,
    ) -> None:
        payload: dict[str, object] = {
            ATTR_EVENT_ID: event_id,
            ATTR_DOOR: door,
            ATTR_RECORDING_PATH: str(paths.recording_path),
            ATTR_DURATION_TARGET_SECONDS: self._recording_target_seconds,
            ATTR_DURATION_ACTUAL_SECONDS: round(actual_seconds, 3),
            ATTR_STATE: state,
            ATTR_TIMESTAMP: _timestamp(),
        }
        if state == RECORDING_STATE_FAILED and reason:
            payload["reason"] = reason
        self._recording_event_count += 1
        self._last_recording_result = dict(payload)
        self._hass.bus.async_fire(EVENT_RECORDING_COMPLETE, payload)
