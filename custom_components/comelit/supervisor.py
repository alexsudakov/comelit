from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOOR_ENTRANCE, DOOR_GATE, LISTENER_CYCLE_SECONDS
from .media_transport import ComelitEntranceMediaTransport
from .runtime import ComelitRingRuntime

_LOGGER = logging.getLogger(__name__)

RECONNECT_INITIAL_DELAY_SECONDS = 5
RECONNECT_MAX_DELAY_SECONDS = 300
RECONNECT_NORMAL_DELAY_SECONDS = 1
POLL_INTERVAL_SECONDS = 1
DOOR_LIFECYCLE_LOCK_TIMEOUT_SECONDS = 0.5

LISTENER_STATE_STARTING = "starting"
LISTENER_STATE_READY = "ready"
LISTENER_STATE_RECONNECTING = "reconnecting"
LISTENER_STATE_PAUSED_MEDIA = "paused_media"
LISTENER_STATE_STOPPED = "stopped"
LISTENER_STATE_ERROR = "error"
ATTACHED_STOP_RECOVERY_ERROR = "attached_stop_recovery_failed"
_ATTACHED_STOP_FAILURE_STAGES = frozenset(
    {
        "NONE",
        "SIGNAL",
        "STALE_CALL",
        "QUEUE",
        "WRITE",
        "FLUSH_TIMEOUT",
        "DISPOSE",
        "REMOTE_RACE",
        "OTHER",
    }
)
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
        self._consecutive_failures = 0
        self._reconnect_delay_seconds = 0
        self._state = LISTENER_STATE_STOPPED
        self._last_ready: datetime | None = None
        self._status_listeners: set[Callable[[], None]] = set()
        self._attached_stop_recovery_required = False
        self._last_attached_stop_recovery_error: str | None = None
        self._last_attached_stop_failure_stage: str | None = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    @property
    def media_paused(self) -> bool:
        return self._media_paused

    @property
    def listener_dispatch_ready(self) -> bool:
        return (
            self._state == LISTENER_STATE_READY
            and self._runtime.running
            and self._runtime.listener_ready
        )

    @property
    def attached_media_busy(self) -> bool:
        return self._runtime.attached_media_busy

    @property
    def reconnect_count(self) -> int:
        return self._reconnect_count

    @property
    def state(self) -> str:
        return self._state

    def status(self) -> dict[str, object]:
        runtime_status = self._runtime.status()
        runtime_stop_failure_stage = runtime_status.get(
            "last_attached_stop_failure_stage"
        )
        if (
            isinstance(runtime_stop_failure_stage, str)
            and runtime_stop_failure_stage in _ATTACHED_STOP_FAILURE_STAGES
        ):
            last_attached_stop_failure_stage = runtime_stop_failure_stage
        else:
            last_attached_stop_failure_stage = self._last_attached_stop_failure_stage
        return {
            "state": self._state,
            "supervisor_running": self.running,
            "runtime_running": bool(runtime_status.get("running")),
            "listener_ready": bool(runtime_status.get("listener_ready")),
            "attached_media_busy": bool(
                runtime_status.get("attached_media_busy")
            ),
            "media_paused": self._media_paused,
            "reconnect_count": self._reconnect_count,
            "consecutive_failures": self._consecutive_failures,
            "reconnect_delay_seconds": self._reconnect_delay_seconds,
            "last_ready": self._last_ready.isoformat() if self._last_ready else None,
            "last_error": runtime_status.get("last_error"),
            "last_native_exit_code": runtime_status.get("last_native_exit_code"),
            "last_native_failure_markers": runtime_status.get(
                "last_native_failure_markers"
            ),
            "last_attached_stop_failure_stage": last_attached_stop_failure_stage,
            "attached_stop_recovery_required": (
                self._attached_stop_recovery_required
            ),
            "last_attached_stop_recovery_error": (
                self._last_attached_stop_recovery_error
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
        if state == LISTENER_STATE_READY:
            self._consecutive_failures = 0
            self._reconnect_delay_seconds = 0
        if state == self._state:
            return
        self._state = state
        if state == LISTENER_STATE_READY:
            self._last_ready = datetime.now(UTC)
        self._notify_status()

    def _capture_attached_stop_failure_stage(self) -> None:
        """Retain the bounded native stop-failure cause across runtime recycle."""
        value = self._runtime.status().get("last_attached_stop_failure_stage")
        if isinstance(value, str) and value in _ATTACHED_STOP_FAILURE_STAGES:
            self._last_attached_stop_failure_stage = value

    def _raise_if_attached_stop_recovery_blocked(self) -> None:
        if not self._attached_stop_recovery_required:
            return
        self._set_state(LISTENER_STATE_ERROR)
        raise RuntimeError(ATTACHED_STOP_RECOVERY_ERROR)

    async def _async_acquire_door_lifecycle_lock(self, door: str) -> None:
        """Acquire the shared connection-owner lock or fail the one-shot request."""
        try:
            await asyncio.wait_for(
                self._lifecycle_lock.acquire(),
                timeout=DOOR_LIFECYCLE_LOCK_TIMEOUT_SECONDS,
            )
        except TimeoutError as exc:
            _LOGGER.warning(
                "DOOR_DISPATCH_REJECT_REASON=LIFECYCLE_BUSY door=%s",
                door,
            )
            raise RuntimeError("lifecycle_busy") from exc
        _LOGGER.warning("DOOR_LIFECYCLE_LOCK_ACQUIRED door=%s", door)

    async def async_start(self) -> None:
        async with self._lifecycle_lock:
            if self.running or self._media_paused:
                return
            self._raise_if_attached_stop_recovery_blocked()
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
            self._raise_if_attached_stop_recovery_blocked()
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

    async def async_open_entrance_door(
        self,
        media_transport: ComelitEntranceMediaTransport | None,
        *,
        event_id: str | None = None,
    ) -> dict[str, object]:
        """Open Entrance through the current exclusive connection owner."""
        _LOGGER.warning("DOOR_DISPATCH_REQUESTED door=%s", DOOR_ENTRANCE)
        await self._async_acquire_door_lifecycle_lock(DOOR_ENTRANCE)
        try:
            if self._attached_stop_recovery_required:
                _LOGGER.warning(
                    "DOOR_DISPATCH_REJECT_REASON=RECOVERY_BLOCKED door=%s",
                    DOOR_ENTRANCE,
                )
                self._raise_if_attached_stop_recovery_blocked()
            if self._media_paused:
                if media_transport is None or not media_transport.active:
                    _LOGGER.warning(
                        "DOOR_DISPATCH_REJECT_REASON=MEDIA_NOT_READY door=%s",
                        DOOR_ENTRANCE,
                    )
                    raise RuntimeError("media_door_not_ready")
                _LOGGER.warning(
                    "DOOR_DISPATCH_OWNER=ON_DEMAND_MEDIA door=%s",
                    DOOR_ENTRANCE,
                )
                return await media_transport.async_open_door(event_id=event_id)
            if not self.listener_dispatch_ready:
                _LOGGER.warning(
                    "DOOR_DISPATCH_REJECT_REASON=LISTENER_NOT_READY door=%s",
                    DOOR_ENTRANCE,
                )
                raise RuntimeError("listener_not_ready")
            _LOGGER.warning("DOOR_DISPATCH_OWNER=LISTENER door=%s", DOOR_ENTRANCE)
            return await self._runtime.async_open_door(DOOR_ENTRANCE, event_id=event_id)
        finally:
            self._lifecycle_lock.release()

    async def async_open_gate_door(
        self,
        *,
        event_id: str | None = None,
    ) -> dict[str, object]:
        """Open Gate only when the persistent listener owns the connection."""
        _LOGGER.warning("DOOR_DISPATCH_REQUESTED door=%s", DOOR_GATE)
        await self._async_acquire_door_lifecycle_lock(DOOR_GATE)
        try:
            if self._attached_stop_recovery_required:
                _LOGGER.warning(
                    "DOOR_DISPATCH_REJECT_REASON=RECOVERY_BLOCKED door=%s",
                    DOOR_GATE,
                )
                self._raise_if_attached_stop_recovery_blocked()
            if self._media_paused:
                _LOGGER.warning(
                    "DOOR_DISPATCH_REJECT_REASON=MEDIA_NOT_READY door=%s",
                    DOOR_GATE,
                )
                raise RuntimeError("media_owns_connection")
            if not self.listener_dispatch_ready:
                _LOGGER.warning(
                    "DOOR_DISPATCH_REJECT_REASON=LISTENER_NOT_READY door=%s",
                    DOOR_GATE,
                )
                raise RuntimeError("listener_not_ready")
            _LOGGER.warning("DOOR_DISPATCH_OWNER=LISTENER door=%s", DOOR_GATE)
            return await self._runtime.async_open_door(DOOR_GATE, event_id=event_id)
        finally:
            self._lifecycle_lock.release()

    async def async_recover_attached_media_stop_failure(self) -> None:
        """Recycle the listener after attached media stop was not confirmed."""
        async with self._lifecycle_lock:
            self._attached_stop_recovery_required = True
            self._last_attached_stop_recovery_error = None
            self._capture_attached_stop_failure_stage()
            self._set_state(LISTENER_STATE_ERROR)
            self._notify_status()

            try:
                await self._async_stop_locked(LISTENER_STATE_ERROR)
            except Exception as exc:
                self._last_attached_stop_recovery_error = (
                    "runtime_stop_not_confirmed"
                )
                self._set_state(LISTENER_STATE_ERROR)
                self._notify_status()
                raise RuntimeError(ATTACHED_STOP_RECOVERY_ERROR) from exc
            if self._runtime.running or self._runtime.listener_ready:
                self._last_attached_stop_recovery_error = (
                    "runtime_stop_not_confirmed"
                )
                self._set_state(LISTENER_STATE_ERROR)
                self._notify_status()
                raise RuntimeError(ATTACHED_STOP_RECOVERY_ERROR)

            if self._shutdown_requested:
                self._set_state(LISTENER_STATE_STOPPED)
                return

            try:
                await self._async_start_locked()
            except Exception as exc:
                self._last_attached_stop_recovery_error = "listener_start_failed"
                self._set_state(LISTENER_STATE_ERROR)
                self._notify_status()
                raise RuntimeError(ATTACHED_STOP_RECOVERY_ERROR) from exc

            ready = await self._runtime.async_wait_ready(timeout=30.0)
            if not ready:
                try:
                    await self._async_stop_locked(LISTENER_STATE_ERROR)
                except Exception as exc:
                    self._last_attached_stop_recovery_error = (
                        "listener_ready_not_confirmed_stop_failed"
                    )
                    self._set_state(LISTENER_STATE_ERROR)
                    self._notify_status()
                    raise RuntimeError(ATTACHED_STOP_RECOVERY_ERROR) from exc
                self._last_attached_stop_recovery_error = (
                    "listener_ready_not_confirmed"
                )
                self._set_state(LISTENER_STATE_ERROR)
                self._notify_status()
                raise RuntimeError(ATTACHED_STOP_RECOVERY_ERROR)

            self._attached_stop_recovery_required = False
            self._last_attached_stop_recovery_error = None
            self._set_state(LISTENER_STATE_READY)
            self._notify_status()

    async def async_resume_after_media(self) -> None:
        """Release media exclusivity and restore the persistent listener."""
        async with self._lifecycle_lock:
            self._raise_if_attached_stop_recovery_blocked()
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
                if self._attached_stop_recovery_required:
                    self._set_state(LISTENER_STATE_ERROR)
                    return

                self._reconnect_count += 1
                runtime_status = self._runtime.status()
                last_error = runtime_status.get("last_error")
                if (
                    isinstance(last_error, str)
                    and last_error.startswith(
                        ("native_exit:", "native_exited_before_offer:")
                    )
                ):
                    reconnect_reason = "NATIVE_FAILURE_EXIT"
                elif last_error:
                    reconnect_reason = "UNKNOWN"
                else:
                    reconnect_reason = "LISTENER_CYCLE_ENDED"
                if last_error == "oauth_reauth_required":
                    self._set_state(LISTENER_STATE_ERROR)
                    self._reconnect_delay_seconds = 0
                    self._notify_status()
                    _LOGGER.error(
                        "Comelit listener requires OAuth reauthentication; "
                        "automatic reconnect stopped"
                    )
                    return

                if runtime_status.get("last_error"):
                    self._set_state(LISTENER_STATE_ERROR)
                    self._consecutive_failures += 1
                    self._reconnect_delay_seconds = min(
                        RECONNECT_INITIAL_DELAY_SECONDS
                        * (2 ** max(0, self._consecutive_failures - 1)),
                        RECONNECT_MAX_DELAY_SECONDS,
                    )
                else:
                    self._set_state(LISTENER_STATE_RECONNECTING)
                    self._consecutive_failures = 0
                    self._reconnect_delay_seconds = RECONNECT_NORMAL_DELAY_SECONDS
                # reconnect_count/delay may change even when visible state does not.
                self._notify_status()

                _LOGGER.warning("RECONNECT_ATTEMPT=%s", self._reconnect_count)
                _LOGGER.warning("RECONNECT_REASON=%s", reconnect_reason)
                _LOGGER.warning(
                    "Comelit listener cycle ended; reconnecting in %ss (count=%s)",
                    self._reconnect_delay_seconds,
                    self._reconnect_count,
                )
                await asyncio.sleep(self._reconnect_delay_seconds)

                if (
                    self._stopping
                    or self._media_paused
                    or self._attached_stop_recovery_required
                ):
                    return
                self._set_state(LISTENER_STATE_STARTING)
                async with self._lifecycle_lock:
                    if (
                        self._stopping
                        or self._media_paused
                        or self._attached_stop_recovery_required
                    ):
                        return
                    await self._runtime.async_start()
        except asyncio.CancelledError:
            raise
        except Exception:
            _LOGGER.exception("Comelit runtime supervisor stopped unexpectedly")
            self._set_state(LISTENER_STATE_ERROR)
