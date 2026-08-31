from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import TextSelector, TextSelectorConfig, TextSelectorType

from .client import ComelitBridgeClient
from .const import CONF_BRIDGE_URL, CONF_SHARED_SECRET, DOMAIN


def _normalize_bridge_url(value: str) -> str:
    value = (value or "").strip().rstrip("/")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("invalid bridge URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("bridge URL must not contain credentials/query/fragment")
    return value


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
                if not await client.async_health():
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
