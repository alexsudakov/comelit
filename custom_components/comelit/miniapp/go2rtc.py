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


def _bounded_int(value: object, *, divisor: int = 1) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        return 0
    return min(value // divisor, 1_000_000)


def _media_has(medias: object, token: str) -> int:
    if not isinstance(medias, list):
        return 0
    token = token.lower()
    return int(any(isinstance(item, str) and token in item.lower() for item in medias))


def summarize_stream_state(payload: object) -> dict[str, int]:
    """Reduce raw go2rtc stream JSON to a closed, secret-free counter set."""
    if not isinstance(payload, dict):
        return {"inspect_ok": 0}

    producers = payload.get("producers")
    consumers = payload.get("consumers")
    producer_list = producers if isinstance(producers, list) else []
    consumer_list = consumers if isinstance(consumers, list) else []

    counters: dict[str, int] = {
        "inspect_ok": 1,
        "producer_count": min(len(producer_list), 1_000_000),
        "consumer_count": min(len(consumer_list), 1_000_000),
    }

    for index in (0, 1):
        producer = producer_list[index] if index < len(producer_list) else None
        prefix = f"p{index}_"
        if not isinstance(producer, dict):
            counters.update(
                {
                    prefix + "active": 0,
                    prefix + "media": 0,
                    prefix + "receivers": 0,
                    prefix + ("pcma" if index == 0 else "opus"): 0,
                    prefix + "h264": 0,
                    prefix + "recv_kb": 0,
                }
            )
            continue

        medias = producer.get("medias")
        receivers = producer.get("receivers")
        active = int(any(key != "url" for key in producer))
        counters[prefix + "active"] = active
        counters[prefix + "media"] = min(len(medias), 1_000_000) if isinstance(medias, list) else 0
        counters[prefix + "receivers"] = (
            min(len(receivers), 1_000_000) if isinstance(receivers, list) else 0
        )
        counters[prefix + "h264"] = _media_has(medias, "h264")
        if index == 0:
            counters[prefix + "pcma"] = max(
                _media_has(medias, "pcma"),
                _media_has(medias, "pcm_alaw"),
            )
        else:
            counters[prefix + "opus"] = _media_has(medias, "opus")
        counters[prefix + "recv_kb"] = _bounded_int(
            producer.get("bytes_recv"),
            divisor=1024,
        )

    consumer_senders = 0
    for consumer in consumer_list:
        if not isinstance(consumer, dict):
            continue
        senders = consumer.get("senders")
        if isinstance(senders, list):
            consumer_senders += len(senders)
    counters["consumer_senders"] = min(consumer_senders, 1_000_000)
    return counters


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

    async def register_stream(self, internal_name: str, sources: list[str]) -> None:
        # The concrete operation is the compatibility check. Avoid a separate
        # /api health/version round-trip on every cold viewer startup.
        if not sources:
            raise MiniAppGo2RTCError("go2rtc_http_error")
        base, client = self._require_runtime()
        params = urlencode({"name": internal_name, "src": sources}, doseq=True)
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

    async def inspect_stream(self, internal_name: str) -> dict[str, int]:
        """Return only closed counters derived from go2rtc stream state."""
        base, client = self._require_runtime()
        params = urlencode({"src": internal_name})
        try:
            async with client.get(
                urljoin(base, "/api/streams") + "?" + params,
                timeout=_TIMEOUT,
            ) as response:
                if response.status >= 400:
                    raise MiniAppGo2RTCError("go2rtc_http_error")
                payload = await response.json(content_type=None)
        except MiniAppGo2RTCError:
            raise
        except (asyncio.TimeoutError, ClientError, ValueError, TypeError):
            raise MiniAppGo2RTCError("go2rtc_http_error") from None
        return summarize_stream_state(payload)

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
