from __future__ import annotations

import asyncio
import logging
from typing import Any
from urllib.parse import urlencode, urljoin

from aiohttp import ClientError, ClientTimeout

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession


_LOGGER = logging.getLogger(__name__)
_TIMEOUT = ClientTimeout(total=5)


class MiniAppGo2RTCError(RuntimeError):
    """Bounded go2rtc adapter failure."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _normalize_base(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    base = value.strip()
    if not (base.startswith("http://") or base.startswith("https://")):
        return None
    return base.rstrip("/") + "/"


class MiniAppGo2RTCAdapter:
    """Narrow client for the Home Assistant-managed go2rtc instance."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass

    def _runtime(self) -> tuple[str, Any] | None:
        value = getattr(self._hass, "data", {}).get("go2rtc")

        # Current Home Assistant stores a Go2RtcConfig object in hass.data.
        # Its ClientSession is authoritative: for HA-managed go2rtc it carries
        # the UnixConnector and generated Basic auth while the TCP HTTP listener
        # is intentionally disabled.
        base = _normalize_base(getattr(value, "url", None))
        session = getattr(value, "session", None)
        if base is not None and session is not None:
            return base, session

        # Keep a bounded compatibility path for older/test runtimes that exposed
        # only a URL string.
        base = _normalize_base(value)
        if base is not None:
            return base, async_get_clientsession(self._hass)

        _LOGGER.debug("Mini App MSE unavailable: go2rtc_unavailable")
        return None

    def _require_runtime(self) -> tuple[str, Any]:
        runtime = self._runtime()
        if runtime is None:
            raise MiniAppGo2RTCError("go2rtc_unavailable")
        return runtime

    async def register_stream(self, internal_name: str, source: str) -> None:
        # The concrete operation is the compatibility check. Avoid a separate
        # /api health/version round-trip on every cold viewer startup.
        base, client = self._require_runtime()
        params = urlencode({"name": internal_name, "src": source})
        try:
            async with client.put(
                urljoin(base, "/api/streams") + "?" + params,
                timeout=_TIMEOUT,
            ) as response:
                if response.status >= 400:
                    raise MiniAppGo2RTCError("go2rtc_http_error")
        except MiniAppGo2RTCError:
            raise
        except (asyncio.TimeoutError, ClientError):
            raise MiniAppGo2RTCError("go2rtc_http_error") from None

    async def unregister_stream(self, internal_name: str) -> None:
        runtime = self._runtime()
        if runtime is None:
            return
        base, client = runtime
        params = urlencode({"src": internal_name})
        try:
            async with client.delete(
                urljoin(base, "/api/streams") + "?" + params,
                timeout=_TIMEOUT,
            ) as response:
                if response.status >= 400:
                    _LOGGER.debug("Mini App MSE unregister failed: go2rtc_http_error")
        except (asyncio.TimeoutError, ClientError):
            _LOGGER.debug("Mini App MSE unregister failed: go2rtc_http_error")

    async def open_mse_ws(self, internal_name: str):
        base, client = self._require_runtime()
        params = urlencode({"src": internal_name})
        try:
            return await client.ws_connect(
                urljoin(base, "/api/ws") + "?" + params,
                heartbeat=20,
                max_msg_size=2 * 1024 * 1024,
                timeout=_TIMEOUT,
            )
        except (asyncio.TimeoutError, ClientError):
            raise MiniAppGo2RTCError("go2rtc_ws_error") from None
