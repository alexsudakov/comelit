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
_MIN_VERSION = (1, 9, 13)
_MAX_VERSION = (2, 0, 0)


class MiniAppGo2RTCError(RuntimeError):
    """Bounded go2rtc adapter failure."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _parse_version(value: object) -> tuple[int, int, int] | None:
    if not isinstance(value, str):
        return None
    parts = value.split(".")
    if len(parts) < 3:
        return None
    try:
        return tuple(int(part) for part in parts[:3])
    except ValueError:
        return None


class MiniAppGo2RTCAdapter:
    """Narrow client for the Home Assistant-managed go2rtc instance."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass

    def _base_url(self) -> str | None:
        value = getattr(self._hass, "data", {}).get("go2rtc")
        if not isinstance(value, str):
            _LOGGER.debug("Mini App MSE unavailable: go2rtc_unavailable")
            return None
        base = value.strip()
        if not (base.startswith("http://") or base.startswith("https://")):
            _LOGGER.debug("Mini App MSE unavailable: go2rtc_unavailable")
            return None
        return base.rstrip("/") + "/"

    async def _ensure_available(self) -> str:
        base = self._base_url()
        if base is None:
            raise MiniAppGo2RTCError("go2rtc_unavailable")

        client = async_get_clientsession(self._hass)
        try:
            async with client.get(urljoin(base, "/api"), timeout=_TIMEOUT) as response:
                if response.status >= 500:
                    raise MiniAppGo2RTCError("go2rtc_http_error")
                try:
                    info: Any = await response.json()
                except (ClientError, ValueError, TypeError):
                    return base
        except MiniAppGo2RTCError:
            raise
        except (asyncio.TimeoutError, ClientError):
            raise MiniAppGo2RTCError("go2rtc_unavailable") from None

        version = _parse_version(info.get("version") if isinstance(info, dict) else None)
        if version is not None and not (_MIN_VERSION <= version < _MAX_VERSION):
            raise MiniAppGo2RTCError("go2rtc_incompatible")
        return base

    async def register_stream(self, internal_name: str, source: str) -> None:
        base = await self._ensure_available()
        client = async_get_clientsession(self._hass)
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
        base = self._base_url()
        if base is None:
            return
        client = async_get_clientsession(self._hass)
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
        base = await self._ensure_available()
        client = async_get_clientsession(self._hass)
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
