from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers.selector import TextSelector, TextSelectorConfig, TextSelectorType

from .const import (
    CONF_DEVICE_UUID,
    CONF_MINIAPP_ALLOWED_USER_IDS,
    CONF_MINIAPP_BOT_ID,
    CONF_MINIAPP_ENABLED,
    CONF_MINIAPP_SURVEILLANCE_LABEL,
    CONF_OAUTH_ACCESS_TOKEN,
    CONF_OAUTH_REFRESH_TOKEN,
    CONF_OAUTH_SCOPE,
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


def _normalized_user_ids(value: object) -> str:
    raw = str(value or "")
    result: set[int] = set()
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        user_id = int(item)
        if user_id <= 0:
            raise ValueError("Telegram user ids must be positive")
        result.add(user_id)
    if not result:
        raise ValueError("at least one Telegram user id is required")
    return ",".join(str(user_id) for user_id in sorted(result))


def _normalized_bot_id(value: object) -> str:
    bot_id = int(str(value or "").strip())
    if bot_id <= 0:
        raise ValueError("Telegram bot id must be positive")
    return str(bot_id)


class ComelitConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Configure the direct Home Assistant Comelit P2P ring listener."""

    VERSION = 2

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Return the Comelit options flow."""
        return ComelitOptionsFlow()

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
                oauth_scope = str(user_input.get(CONF_OAUTH_SCOPE) or "").strip()
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
                if oauth_scope:
                    data[CONF_OAUTH_SCOPE] = oauth_scope
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
                vol.Optional(CONF_OAUTH_SCOPE): TextSelector(
                    TextSelectorConfig(type=TextSelectorType.TEXT)
                ),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)


class ComelitOptionsFlow(config_entries.OptionsFlow):
    """Configure optional Comelit product surfaces."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        current = self.config_entry.options

        if user_input is not None:
            enabled = bool(user_input.get(CONF_MINIAPP_ENABLED, False))
            try:
                if enabled:
                    bot_id = _normalized_bot_id(user_input.get(CONF_MINIAPP_BOT_ID))
                    allowed_users = _normalized_user_ids(
                        user_input.get(CONF_MINIAPP_ALLOWED_USER_IDS)
                    )
                else:
                    bot_id = str(user_input.get(CONF_MINIAPP_BOT_ID) or "").strip()
                    allowed_users = str(
                        user_input.get(CONF_MINIAPP_ALLOWED_USER_IDS) or ""
                    ).strip()
                surveillance_label = str(
                    user_input.get(CONF_MINIAPP_SURVEILLANCE_LABEL) or ""
                ).strip()
            except (TypeError, ValueError):
                errors["base"] = "invalid_miniapp_config"
            else:
                return self.async_create_entry(
                    title="",
                    data={
                        CONF_MINIAPP_ENABLED: enabled,
                        CONF_MINIAPP_BOT_ID: bot_id,
                        CONF_MINIAPP_ALLOWED_USER_IDS: allowed_users,
                        CONF_MINIAPP_SURVEILLANCE_LABEL: surveillance_label,
                    },
                )

        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_MINIAPP_ENABLED,
                    default=bool(current.get(CONF_MINIAPP_ENABLED, False)),
                ): bool,
                vol.Optional(
                    CONF_MINIAPP_BOT_ID,
                    default=str(current.get(CONF_MINIAPP_BOT_ID, "")),
                ): TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT)),
                vol.Optional(
                    CONF_MINIAPP_ALLOWED_USER_IDS,
                    default=str(current.get(CONF_MINIAPP_ALLOWED_USER_IDS, "")),
                ): TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT)),
                vol.Optional(
                    CONF_MINIAPP_SURVEILLANCE_LABEL,
                    default=str(current.get(CONF_MINIAPP_SURVEILLANCE_LABEL, "")),
                ): TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT)),
            }
        )
        return self.async_show_form(
            step_id="init",
            data_schema=schema,
            errors=errors,
        )
