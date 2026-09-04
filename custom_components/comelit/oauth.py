from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import time

from aiohttp import ClientError, ClientSession
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    CONF_OAUTH_ACCESS_TOKEN,
    CONF_OAUTH_EXPIRES_AT,
    CONF_OAUTH_REFRESH_TOKEN,
)

TOKEN_ENDPOINT = "https://api.comelitgroup.com/o-auth-2/token"
CLIENT_ID = "kgDV0WRlQcSF4jPsz887lOTPyVVtP7Oh"
SCOPE = "all"
REFRESH_SKEW_SECONDS = 300


class ComelitOAuthError(RuntimeError):
    """Comelit OAuth refresh failed without exposing token material."""


@dataclass(frozen=True)
class OAuthRefreshResult:
    access_token: str
    refresh_token: str | None
    expires_in: int
    token_type: str | None
    scope: str | None


def _parse_expires_at(value: object) -> int | None:
    if value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


async def async_refresh_oauth(
    session: ClientSession,
    *,
    refresh_token: str,
) -> OAuthRefreshResult:
    """Refresh a Comelit OAuth token using the app-proven refresh contract."""
    fields = {
        "grant_type": "refresh_token",
        "client_id": CLIENT_ID,
        "scope": SCOPE,
        "refresh_token": refresh_token,
    }
    headers = {"Accept": "application/json"}

    try:
        async with session.post(
            TOKEN_ENDPOINT,
            data=fields,
            headers=headers,
            timeout=20,
        ) as response:
            status = response.status
            raw = await response.read()
    except (ClientError, TimeoutError) as exc:
        raise ComelitOAuthError(f"oauth_http_exception:{type(exc).__name__}") from exc

    if not 200 <= status < 300:
        raise ComelitOAuthError(f"oauth_http_status:{status}")

    try:
        obj = json.loads(raw.decode("utf-8", errors="replace"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ComelitOAuthError("oauth_response_not_json") from exc

    if not isinstance(obj, dict):
        raise ComelitOAuthError("oauth_response_not_object")

    access = obj.get("access_token")
    if not isinstance(access, str) or not access:
        raise ComelitOAuthError("oauth_access_token_missing")

    expires_in = obj.get("expires_in")
    if (
        not isinstance(expires_in, int)
        or isinstance(expires_in, bool)
        or expires_in <= 0
    ):
        raise ComelitOAuthError("oauth_expires_in_invalid")

    refresh = obj.get("refresh_token")
    if refresh is not None and (not isinstance(refresh, str) or not refresh):
        raise ComelitOAuthError("oauth_refresh_token_invalid")

    token_type = obj.get("token_type")
    if token_type is not None and not isinstance(token_type, str):
        raise ComelitOAuthError("oauth_token_type_invalid")

    scope = obj.get("scope")
    if scope is not None and not isinstance(scope, str):
        raise ComelitOAuthError("oauth_scope_invalid")

    return OAuthRefreshResult(
        access_token=access,
        refresh_token=refresh,
        expires_in=expires_in,
        token_type=token_type,
        scope=scope,
    )


class ComelitOAuthManager:
    """Own the HA-persisted OAuth token lifecycle for one config entry."""

    def __init__(
        self,
        hass: HomeAssistant,
        session: ClientSession,
        entry: ConfigEntry,
    ) -> None:
        self._hass = hass
        self._session = session
        self._entry = entry
        self._lock = asyncio.Lock()

    async def async_get_access_token(self, *, force_refresh: bool = False) -> str:
        """Return a usable access token, refreshing once when required."""
        async with self._lock:
            data = self._entry.data
            access = str(data.get(CONF_OAUTH_ACCESS_TOKEN) or "")
            refresh = str(data.get(CONF_OAUTH_REFRESH_TOKEN) or "")
            expires_at = _parse_expires_at(data.get(CONF_OAUTH_EXPIRES_AT))
            now = int(time.time())

            if not force_refresh and access:
                if expires_at is None or now + REFRESH_SKEW_SECONDS < expires_at:
                    return access

            if not refresh:
                if not access:
                    raise ComelitOAuthError("oauth_access_token_missing")
                raise ComelitOAuthError("oauth_refresh_token_missing")

            refreshed = await async_refresh_oauth(
                self._session,
                refresh_token=refresh,
            )
            new_data = dict(self._entry.data)
            new_data[CONF_OAUTH_ACCESS_TOKEN] = refreshed.access_token
            new_data[CONF_OAUTH_REFRESH_TOKEN] = refreshed.refresh_token or refresh
            new_data[CONF_OAUTH_EXPIRES_AT] = int(time.time()) + refreshed.expires_in
            self._hass.config_entries.async_update_entry(self._entry, data=new_data)
            return refreshed.access_token
