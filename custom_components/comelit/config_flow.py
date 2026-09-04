from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.helpers.selector import TextSelector, TextSelectorConfig, TextSelectorType

from .const import (
    CONF_DEVICE_UUID,
    CONF_OAUTH_ACCESS_TOKEN,
    CONF_OAUTH_REFRESH_TOKEN,
    CONF_VIP_TOKEN,
    DOMAIN,
)


def _clean_required(value: object) -> str:
    result = str(value or "").strip()
    if not result:
        raise ValueError("required value is empty")
    return result


def _vip_token(value: object) -> str:
    result = _clean_required(value)
    if len(result) != 32 or any(ch not in "0123456789abcdefABCDEF" for ch in result):
        raise ValueError("VIP token must be 32 hex characters")
    return result


class ComelitConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Configure the direct Home Assistant Comelit P2P ring listener."""

    VERSION = 2

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                device_uuid = _clean_required(user_input[CONF_DEVICE_UUID])
                vip_token = _vip_token(user_input[CONF_VIP_TOKEN])
                oauth_access_token = _clean_required(
                    user_input[CONF_OAUTH_ACCESS_TOKEN]
                )
                oauth_refresh_token = str(
                    user_input.get(CONF_OAUTH_REFRESH_TOKEN) or ""
                ).strip()
            except (ValueError, KeyError):
                errors["base"] = "invalid_config"
            else:
                await self.async_set_unique_id(device_uuid)
                self._abort_if_unique_id_configured()
                data = {
                    CONF_DEVICE_UUID: device_uuid,
                    CONF_VIP_TOKEN: vip_token,
                    CONF_OAUTH_ACCESS_TOKEN: oauth_access_token,
                }
                if oauth_refresh_token:
                    data[CONF_OAUTH_REFRESH_TOKEN] = oauth_refresh_token
                return self.async_create_entry(title="Comelit", data=data)

        schema = vol.Schema(
            {
                vol.Required(CONF_DEVICE_UUID): TextSelector(
                    TextSelectorConfig(type=TextSelectorType.TEXT)
                ),
                vol.Required(CONF_VIP_TOKEN): TextSelector(
                    TextSelectorConfig(type=TextSelectorType.PASSWORD)
                ),
                vol.Required(CONF_OAUTH_ACCESS_TOKEN): TextSelector(
                    TextSelectorConfig(type=TextSelectorType.PASSWORD)
                ),
                vol.Optional(CONF_OAUTH_REFRESH_TOKEN): TextSelector(
                    TextSelectorConfig(type=TextSelectorType.PASSWORD)
                ),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)
