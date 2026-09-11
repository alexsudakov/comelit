from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime, timedelta
import math
from typing import Any, Protocol

MEDIA_SESSION_HARD_LIMIT_SECONDS = 600
MEDIA_TRANSPORT_WATCH_INTERVAL_SECONDS = 0.5
MEDIA_PHASE_INACTIVE = "inactive"
MEDIA_PHASE_STARTING = "starting"
MEDIA_PHASE_ACTIVE = "active"
MEDIA_PHASE_STOPPING = "stopping"
MEDIA_PHASE_ERROR = "error"
MEDIA_PHASES = (
    MEDIA_PHASE_INACTIVE,
    MEDIA_PHASE_STARTING,
    MEDIA_PHASE_ACTIVE,
    MEDIA_PHASE_STOPPING,
    MEDIA_PHASE_ERROR,
)


class ComelitMediaSessionError(RuntimeError):
    """The on-demand Comelit media lifecycle cannot complete safely."""


class ListenerController(Protocol):
    """Minimal listener lifecycle contract required by media."""

    @property
    def media_paused(self) -> bool: ...

    async def async_pause_for_media(self) -> None: ...

    async def async_resume_after_media(self) -> None: ...


class MediaTransport(Protocol):
    """Upstream media transport owned exclusively by the session manager."""

    @property
    def active(self) -> bool: ...

    async def async_start(self, panel: str) -> None: ...

    async def async_stop(self) -> None: ...


TaskFactory = Callable[
    [Coroutine[Any, Any, None], str],
    asyncio.Task[None],
]


def _default_task_factory(
    coro: Coroutine[Any, Any, None],
    name: str,
) -> asyncio.Task[None]:
    return asyncio.create_task(coro, name=name)


class ComelitMediaSessionManager:
    """Own exactly one on-demand intercom media session.

    The persistent Ring/Door listener and the media transport cannot be active
    at the same time. The listener is paused before media bootstrap and is
    restored only after media teardown is confirmed. The absolute deadline is
    measured from successful upstream media start and is never extended by new
    leases.
    """

    def __init__(
        self,
        listener: ListenerController,
        transport: MediaTransport,
        *,
        hard_limit_seconds: float = MEDIA_SESSION_HARD_LIMIT_SECONDS,
        transport_watch_interval_seconds: float = (
            MEDIA_TRANSPORT_WATCH_INTERVAL_SECONDS
        ),
        task_factory: TaskFactory | None = None,
    ) -> None:
        if hard_limit_seconds <= 0:
            raise ValueError("hard_limit_seconds must be positive")
        if transport_watch_interval_seconds <= 0:
            raise ValueError("transport_watch_interval_seconds must be positive")

        self._listener = listener
        self._transport = transport
        self._hard_limit_seconds = hard_limit_seconds
        self._transport_watch_interval_seconds = transport_watch_interval_seconds
        self._task_factory = task_factory or _default_task_factory
        self._lock = asyncio.Lock()
        self._phase = MEDIA_PHASE_INACTIVE
        self._panel: str | None = None
        self._leases: dict[str, int] = {}
        self._started_at: datetime | None = None
        self._expires_at: datetime | None = None
        self._deadline_monotonic: float | None = None
        self._expiry_task: asyncio.Task[None] | None = None
        self._watchdog_task: asyncio.Task[None] | None = None
        self._last_error: str | None = None
        self._status_listeners: set[Callable[[], None]] = set()

    @property
    def phase(self) -> str:
        return self._phase

    @property
    def panel(self) -> str | None:
        return self._panel

    @property
    def active(self) -> bool:
        return self._phase == MEDIA_PHASE_ACTIVE and self._transport.active

    @property
    def last_error(self) -> str | None:
        return self._last_error

    @property
    def hard_limit_seconds(self) -> float:
        return self._hard_limit_seconds

    @property
    def remaining_seconds(self) -> int:
        deadline = self._deadline_monotonic
        if deadline is None or self._phase != MEDIA_PHASE_ACTIVE:
            return 0
        remaining = deadline - asyncio.get_running_loop().time()
        return max(0, math.ceil(remaining))

    def status(self) -> dict[str, object]:
        return {
            "panel": self._panel,
            "phase": self._phase,
            "active": self.active,
            "started_at": self._started_at.isoformat() if self._started_at else None,
            "expires_at": self._expires_at.isoformat() if self._expires_at else None,
            "remaining_seconds": self.remaining_seconds,
            "leases": dict(self._leases),
            "last_error": self._last_error,
            "listener_paused": self._listener.media_paused,
        }

    def async_add_status_listener(self, callback: Callable[[], None]) -> Callable[[], None]:
        """Register an in-process entity status listener and return its remover."""
        self._status_listeners.add(callback)

        def remove() -> None:
            self._status_listeners.discard(callback)

        return remove

    def _notify_status(self) -> None:
        for callback in tuple(self._status_listeners):
            callback()

    def _set_phase(self, phase: str) -> None:
        if phase == self._phase:
            return
        self._phase = phase
        self._notify_status()

    async def async_acquire(self, *, panel: str, reason: str) -> dict[str, object]:
        if panel != "entrance":
            raise ComelitMediaSessionError("unsupported_media_panel")
        if not reason or len(reason) > 64:
            raise ComelitMediaSessionError("invalid_media_reason")

        async with self._lock:
            if self._phase == MEDIA_PHASE_ACTIVE:
                if self._panel != panel or not self._transport.active:
                    raise ComelitMediaSessionError("media_session_state_mismatch")
                self._leases[reason] = self._leases.get(reason, 0) + 1
                self._notify_status()
                return self.status()

            if self._phase in {MEDIA_PHASE_STARTING, MEDIA_PHASE_STOPPING}:
                raise ComelitMediaSessionError("media_session_transition_busy")

            self._panel = panel
            self._leases = {reason: 1}
            self._last_error = None
            self._set_phase(MEDIA_PHASE_STARTING)

            try:
                await self._listener.async_pause_for_media()
                if not self._listener.media_paused:
                    raise ComelitMediaSessionError("listener_pause_not_confirmed")

                await self._transport.async_start(panel)
                if not self._transport.active:
                    raise ComelitMediaSessionError("media_start_not_confirmed")
            except Exception as exc:
                await self._recover_failed_start(exc)
                raise ComelitMediaSessionError(self._last_error or "media_start_failed") from exc

            now = datetime.now(UTC)
            self._started_at = now
            self._expires_at = now + timedelta(seconds=self._hard_limit_seconds)
            self._deadline_monotonic = (
                asyncio.get_running_loop().time() + self._hard_limit_seconds
            )
            self._set_phase(MEDIA_PHASE_ACTIVE)
            self._expiry_task = self._task_factory(
                self._async_expire_after_deadline(),
                "comelit media hard timeout",
            )
            self._watchdog_task = self._task_factory(
                self._async_watch_transport(),
                "comelit media transport watchdog",
            )
            return self.status()

    async def async_release(self, *, reason: str) -> dict[str, object]:
        async with self._lock:
            count = self._leases.get(reason, 0)
            if count <= 1:
                self._leases.pop(reason, None)
            else:
                self._leases[reason] = count - 1

            if self._phase == MEDIA_PHASE_ACTIVE and not self._leases:
                await self._async_stop_locked("last_lease_released")
            else:
                self._notify_status()
            return self.status()

    async def async_force_stop(self, *, reason: str) -> dict[str, object]:
        if not reason or len(reason) > 64:
            raise ComelitMediaSessionError("invalid_stop_reason")
        async with self._lock:
            self._leases.clear()
            await self._async_stop_locked(reason)
            return self.status()

    async def async_shutdown(self) -> None:
        """Tear media down for config-entry unload without restarting listener."""
        async with self._lock:
            self._leases.clear()
            expiry_task = self._expiry_task
            watchdog_task = self._watchdog_task
            self._expiry_task = None
            self._watchdog_task = None
            await self._cancel_background_task(expiry_task)
            await self._cancel_background_task(watchdog_task)

            if self._phase != MEDIA_PHASE_INACTIVE:
                self._set_phase(MEDIA_PHASE_STOPPING)
            try:
                await self._transport.async_stop()
            except Exception as exc:
                self._last_error = f"shutdown_teardown_failed:{type(exc).__name__}"
                self._set_phase(MEDIA_PHASE_ERROR)
                raise
            self._reset_inactive()

    async def _async_expire_after_deadline(self) -> None:
        try:
            deadline = self._deadline_monotonic
            if deadline is None:
                return
            delay = max(0.0, deadline - asyncio.get_running_loop().time())
            await asyncio.sleep(delay)
            await self.async_force_stop(reason="hard_timeout")
        except asyncio.CancelledError:
            raise

    async def _async_watch_transport(self) -> None:
        """Restore the listener promptly when the native media process is gone."""
        try:
            while True:
                await asyncio.sleep(self._transport_watch_interval_seconds)
                async with self._lock:
                    if self._phase != MEDIA_PHASE_ACTIVE:
                        return
                    if self._transport.active:
                        continue

                    # active=False is defined by the concrete transport only
                    # after the media process is no longer alive, so local
                    # socket ownership has been released. Restore normal
                    # listener ownership instead of waiting for the hard limit.
                    self._leases.clear()
                    self._last_error = "transport_ended"
                    await self._async_stop_locked("transport_ended")
                    return
        except asyncio.CancelledError:
            raise

    async def _recover_failed_start(self, exc: Exception) -> None:
        self._last_error = f"start_failed:{type(exc).__name__}"

        if self._transport.active:
            try:
                await self._transport.async_stop()
            except Exception as stop_exc:
                self._last_error = f"start_cleanup_failed:{type(stop_exc).__name__}"
                self._set_phase(MEDIA_PHASE_ERROR)
                return

        try:
            await self._listener.async_resume_after_media()
        except Exception as resume_exc:
            self._last_error = f"listener_restore_failed:{type(resume_exc).__name__}"
            self._set_phase(MEDIA_PHASE_ERROR)
            return

        self._reset_inactive()

    async def _cancel_background_task(
        self,
        task: asyncio.Task[None] | None,
    ) -> None:
        current_task = asyncio.current_task()
        if task is None or task is current_task:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def _async_stop_locked(self, reason: str) -> None:
        if self._phase == MEDIA_PHASE_INACTIVE:
            if self._listener.media_paused:
                await self._listener.async_resume_after_media()
            return

        self._set_phase(MEDIA_PHASE_STOPPING)
        expiry_task = self._expiry_task
        watchdog_task = self._watchdog_task
        self._expiry_task = None
        self._watchdog_task = None
        await self._cancel_background_task(expiry_task)
        await self._cancel_background_task(watchdog_task)

        try:
            if self._transport.active:
                await self._transport.async_stop()
            if self._transport.active:
                raise ComelitMediaSessionError("media_stop_not_confirmed")
        except Exception as exc:
            # Fail closed: if upstream media teardown is not confirmed, do not
            # restart the persistent listener and create two concurrent Comelit
            # sessions. Manual recovery can inspect the error state instead.
            self._last_error = f"teardown_failed:{type(exc).__name__}"
            self._set_phase(MEDIA_PHASE_ERROR)
            return

        try:
            await self._listener.async_resume_after_media()
        except Exception as exc:
            self._last_error = f"listener_restore_failed:{type(exc).__name__}"
            self._set_phase(MEDIA_PHASE_ERROR)
            return

        self._reset_inactive()

    def _reset_inactive(self) -> None:
        self._panel = None
        self._leases.clear()
        self._started_at = None
        self._expires_at = None
        self._deadline_monotonic = None
        self._expiry_task = None
        self._watchdog_task = None
        self._last_error = None
        self._set_phase(MEDIA_PHASE_INACTIVE)
