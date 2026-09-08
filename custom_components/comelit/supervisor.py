from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import LISTENER_CYCLE_SECONDS
from .runtime import ComelitRingRuntime

_LOGGER = logging.getLogger(__name__)

RECONNECT_DELAY_SECONDS = 5
POLL_INTERVAL_SECONDS = 1

LISTENER_STATE_STARTING = "starting"
LISTENER_STATE_READY = "ready"
LISTENER_STATE_RECONNECTING = "reconnecting"
LISTENER_STATE_PAUSED_MEDIA = "paused_media"
LISTENER_STATE_STOPPED = "stopped"
LISTENER_STATE_ERROR = "error"
LISTENER_STATES = (
    LISTENER_STATE_STARTING,
    LISTENER_STATE_READY,
    LISTENER_STATE_RECONNECTING,
    LISTENER_STATE_PAUSED_MEDIA,
    LISTENER_STATE_STOPPED,
    LISTENER_STATE_ERROR,
)


class ComelitRuntimeSupervisor:
    """Keep the direct Comelit listener alive inside Home Assistant.

    Reconnects only the passive Ring/P2P session. It never invokes a Door
    action and therefore cannot retry an actuation attempt.

    The media lifecycle may acquire an exclusive pause. While that pause is
    held, the persistent native listener is fully stopped and automatic
    reconnect is disabled. The listener is restarted only after media teardown
    is confirmed by the media-session owner.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        runtime: ComelitRingRuntime,
        *,
        entry: ConfigEntry,
    ) -> None:
        self._hass = hass
        self._entry = entry
        self._runtime = runtime
        self._task: asyncio.Task[None] | None = None
        self._stopping = False
        self._shutdown_requested = False
        self._media_paused = False
        self._lifecycle_lock = asyncio.Lock()
        self._reconnect_count = 0
        self._state = LISTENER_STATE_STOPPED
        self._last_ready: datetime | None = None
        self._status_listeners: set[Callable[[], None]] = set()

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    @property
    def media_paused(self) -> bool:
        return self._media_paused

    @property
    def reconnect_count(self) -> int:
        return self._reconnect_count

    @property
    def state(self) -> str:
        return self._state

    def status(self) -> dict[str, object]:
        runtime_status = self._runtime.status()
        return {
            "state": self._state,
            "supervisor_running": self.running,
            "runtime_running": bool(runtime_status.get("running")),
            "listener_ready": bool(runtime_status.get("listener_ready")),
            "media_paused": self._media_paused,
            "reconnect_count": self._reconnect_count,
            "last_ready": self._last_ready.isoformat() if self._last_ready else None,
            "last_error": runtime_status.get("last_error"),
            "last_native_exit_code": runtime_status.get("last_native_exit_code"),
            "last_native_failure_markers": runtime_status.get(
                "last_native_failure_markers"
            ),
            "cycle_duration_seconds": LISTENER_CYCLE_SECONDS,
        }

    def async_add_status_listener(self, callback: Callable[[], None]) -> Callable[[], None]:
        """Register an in-process HA status listener and return its remover."""
        self._status_listeners.add(callback)

        def remove() -> None:
            self._status_listeners.discard(callback)

        return remove

    def _notify_status(self) -> None:
        for callback in tuple(self._status_listeners):
            callback()

    def _set_state(self, state: str) -> None:
        if state == self._state:
            return
        self._state = state
        if state == LISTENER_STATE_READY:
            self._last_ready = datetime.now(UTC)
        self._notify_status()

    async def async_start(self) -> None:
        async with self._lifecycle_lock:
            if self.running or self._media_paused:
                return
            self._shutdown_requested = False
            await self._async_start_locked()

    async def _async_start_locked(self) -> None:
        if self.running or self._media_paused or self._shutdown_requested:
            return

        self._stopping = False
        self._set_state(LISTENER_STATE_STARTING)
        await self._runtime.async_start()
        self._task = self._entry.async_create_background_task(
            self._hass,
            self._async_run(),
            "comelit runtime supervisor",
        )

    async def async_stop(self) -> None:
        """Stop the listener for config-entry unload/shutdown."""
        async with self._lifecycle_lock:
            self._shutdown_requested = True
            self._media_paused = False
            await self._async_stop_locked(LISTENER_STATE_STOPPED)

    async def async_pause_for_media(self) -> None:
        """Acquire the exclusive listener pause required by media bootstrap."""
        async with self._lifecycle_lock:
            if self._shutdown_requested:
                raise RuntimeError("listener_shutdown_in_progress")
            if self._media_paused:
                return

            self._media_paused = True
            try:
                await self._async_stop_locked(LISTENER_STATE_PAUSED_MEDIA)
            except Exception:
                self._media_paused = False
                self._set_state(LISTENER_STATE_ERROR)
                raise

            if self._runtime.running or self._runtime.listener_ready:
                self._media_paused = False
                self._set_state(LISTENER_STATE_ERROR)
                raise RuntimeError("listener_pause_not_confirmed")

    async def async_resume_after_media(self) -> None:
        """Release media exclusivity and restore the persistent listener."""
        async with self._lifecycle_lock:
            if not self._media_paused:
                return

            self._media_paused = False
            if self._shutdown_requested:
                self._set_state(LISTENER_STATE_STOPPED)
                return

            await self._async_start_locked()

    async def _async_stop_locked(self, final_state: str) -> None:
        self._stopping = True

        task = self._task
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        self._task = None
        await self._runtime.async_stop()
        self._set_state(final_state)

    async def _async_run(self) -> None:
        try:
            while not self._stopping and not self._media_paused:
                while (
                    self._runtime.running
                    and not self._stopping
                    and not self._media_paused
                ):
                    if self._runtime.listener_ready:
                        self._set_state(LISTENER_STATE_READY)
                    else:
                        self._set_state(LISTENER_STATE_STARTING)
                    await asyncio.sleep(POLL_INTERVAL_SECONDS)

                if self._stopping or self._media_paused:
                    return

                self._reconnect_count += 1
                runtime_status = self._runtime.status()
                if runtime_status.get("last_error"):
                    self._set_state(LISTENER_STATE_ERROR)
                else:
                    self._set_state(LISTENER_STATE_RECONNECTING)
                # reconnect_count may change even when the visible state does not.
                self._notify_status()

                _LOGGER.warning(
                    "Comelit listener cycle ended; reconnecting in %ss (count=%s)",
                    RECONNECT_DELAY_SECONDS,
                    self._reconnect_count,
                )
                await asyncio.sleep(RECONNECT_DELAY_SECONDS)

                if self._stopping or self._media_paused:
                    return
                self._set_state(LISTENER_STATE_STARTING)
                await self._runtime.async_start()
        except asyncio.CancelledError:
            raise
        except Exception:
            _LOGGER.exception("Comelit runtime supervisor stopped unexpectedly")
            self._set_state(LISTENER_STATE_ERROR)
