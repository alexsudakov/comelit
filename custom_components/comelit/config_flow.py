from __future__ import annotations

import ipaddress
from typing import Any
from urllib.parse import urlparse

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import TextSelector, TextSelectorConfig, TextSelectorType

from .client import ComelitBridgeClient
from .const import BRIDGE_PORT, CONF_BRIDGE_URL, CONF_SHARED_SECRET, DOMAIN


def _normalize_bridge_url(value: str) -> str:
    value = (value or "").strip().rstrip("/")
    parsed = urlparse(value)
    if parsed.scheme != "http" or not parsed.hostname:
        raise ValueError("bridge must use private HTTP")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("bridge URL must not contain credentials/query/fragment")
    if parsed.path not in {"", "/"}:
        raise ValueError("bridge URL path must be root")
    if parsed.port != BRIDGE_PORT:
        raise ValueError("bridge port mismatch")
    try:
        addr = ipaddress.ip_address(parsed.hostname)
    except ValueError as exc:
        raise ValueError("bridge hostname must be private IPv4") from exc
    if (
        addr.version != 4
        or not addr.is_private
        or addr.is_loopback
        or addr.is_unspecified
        or addr.is_multicast
        or addr.is_link_local
    ):
        raise ValueError("bridge address must be private IPv4")
    return f"http://{addr}:{BRIDGE_PORT}"


class ComelitConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                bridge_url = _normalize_bridge_url(str(user_input[CONF_BRIDGE_URL]))
                shared_secret = str(user_input[CONF_SHARED_SECRET])
                if len(shared_secret.encode("utf-8")) < 32:
                    raise ValueError("shared secret too short")
            except (ValueError, KeyError):
                errors["base"] = "invalid_config"
            else:
                client = ComelitBridgeClient(
                    async_get_clientsession(self.hass),
                    bridge_url=bridge_url,
                    shared_secret=shared_secret,
                )
                # Config entries are created only after the CT120 backend has
                # been deliberately live-promoted and its runner identity passes.
                # No open-door request is used for this connectivity check.
                if not await client.async_health(require_live=True):
                    errors["base"] = "cannot_connect"
                else:
                    await self.async_set_unique_id(bridge_url)
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(
                        title="Comelit Door Bridge",
                        data={
                            CONF_BRIDGE_URL: bridge_url,
                            CONF_SHARED_SECRET: shared_secret,
                        },
                    )

        schema = vol.Schema(
            {
                vol.Required(CONF_BRIDGE_URL): TextSelector(
                    TextSelectorConfig(type=TextSelectorType.URL)
                ),
                vol.Required(CONF_SHARED_SECRET): TextSelector(
                    TextSelectorConfig(type=TextSelectorType.PASSWORD)
                ),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)
