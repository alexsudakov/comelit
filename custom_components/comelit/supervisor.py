from __future__ import annotations

import asyncio
import logging

from homeassistant.core import HomeAssistant

from .runtime import ComelitRingRuntime

_LOGGER = logging.getLogger(__name__)

RECONNECT_DELAY_SECONDS = 5
POLL_INTERVAL_SECONDS = 1


class ComelitRuntimeSupervisor:
    """Keep the direct Comelit listener alive inside Home Assistant.

    Reconnects only the passive Ring/P2P session. It never invokes a Door
    action and therefore cannot retry an actuation attempt.
    """

    def __init__(self, hass: HomeAssistant, runtime: ComelitRingRuntime) -> None:
        self._hass = hass
        self._runtime = runtime
        self._task: asyncio.Task[None] | None = None
        self._stopping = False
        self._reconnect_count = 0

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    @property
    def reconnect_count(self) -> int:
        return self._reconnect_count

    async def async_start(self) -> None:
        if self.running:
            return

        self._stopping = False
        await self._runtime.async_start()
        self._task = self._hass.async_create_task(
            self._async_run(),
            "comelit runtime supervisor",
        )

    async def async_stop(self) -> None:
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

    async def _async_run(self) -> None:
        try:
            while not self._stopping:
                while self._runtime.running and not self._stopping:
                    await asyncio.sleep(POLL_INTERVAL_SECONDS)

                if self._stopping:
                    return

                self._reconnect_count += 1
                _LOGGER.warning(
                    "Comelit listener cycle ended; reconnecting in %ss (count=%s)",
                    RECONNECT_DELAY_SECONDS,
                    self._reconnect_count,
                )
                await asyncio.sleep(RECONNECT_DELAY_SECONDS)

                if self._stopping:
                    return
                await self._runtime.async_start()
        except asyncio.CancelledError:
            raise
