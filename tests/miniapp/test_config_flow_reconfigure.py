import asyncio
import importlib.util
import logging
from dataclasses import dataclass, field
from pathlib import Path
import sys
from types import ModuleType
from typing import Any

import pytest


ROOT = Path(__file__).resolve().parents[2]
CONFIG_FLOW = ROOT / "custom_components/comelit/config_flow.py"
CONST = ROOT / "custom_components/comelit/const.py"


@dataclass
class _Entry:
    data: dict[str, Any]
    options: dict[str, Any]
    unique_id: str
    entry_id: str


@dataclass
class _Harness:
    entry: _Entry
    entries: list[_Entry] = field(init=False)
    reloads: int = 0

    def __post_init__(self) -> None:
        self.entries = [self.entry]


@pytest.fixture
def config_flow_module(monkeypatch):
    """Load config_flow with small offline stand-ins for the HA flow API."""
    package_name = "_comelit_reconfigure_test"
    package = ModuleType(package_name)
    package.__path__ = []
    monkeypatch.setitem(sys.modules, package_name, package)

    const_spec = importlib.util.spec_from_file_location(f"{package_name}.const", CONST)
    assert const_spec and const_spec.loader
    const_module = importlib.util.module_from_spec(const_spec)
    monkeypatch.setitem(sys.modules, const_spec.name, const_module)
    const_spec.loader.exec_module(const_module)

    voluptuous = ModuleType("voluptuous")

    class Schema:
        def __init__(self, schema):
            self.schema = schema

    class Marker:
        def __init__(self, schema, default=None):
            self.schema = schema
            self.default = default

        def __hash__(self):
            return hash((type(self), self.schema))

    class Required(Marker):
        pass

    class Optional(Marker):
        pass

    voluptuous.Schema = Schema
    voluptuous.Required = Required
    voluptuous.Optional = Optional
    monkeypatch.setitem(sys.modules, "voluptuous", voluptuous)

    homeassistant = ModuleType("homeassistant")
    config_entries = ModuleType("homeassistant.config_entries")
    core = ModuleType("homeassistant.core")
    helpers = ModuleType("homeassistant.helpers")
    selector = ModuleType("homeassistant.helpers.selector")

    class ConfigFlow:
        def __init_subclass__(cls, **kwargs):
            super().__init_subclass__()

        def _get_reconfigure_entry(self):
            return self.harness.entry

        def async_abort(self, *, reason):
            return {"type": "abort", "reason": reason}

        def async_update_reload_and_abort(self, entry, *, data_updates):
            entry.data = {**entry.data, **data_updates}
            self.harness.reloads += 1
            return {"type": "abort", "reason": "reconfigure_successful"}

        def async_show_form(self, *, step_id, data_schema, errors):
            return {
                "type": "form",
                "step_id": step_id,
                "data_schema": data_schema,
                "errors": errors,
            }

    class OptionsFlow:
        pass

    class TextSelectorType:
        PASSWORD = "password"
        TEXT = "text"

    @dataclass
    class TextSelectorConfig:
        type: str

    @dataclass
    class TextSelector:
        config: TextSelectorConfig

    config_entries.ConfigFlow = ConfigFlow
    config_entries.ConfigEntry = _Entry
    config_entries.OptionsFlow = OptionsFlow
    core.callback = lambda function: function
    selector.TextSelector = TextSelector
    selector.TextSelectorConfig = TextSelectorConfig
    selector.TextSelectorType = TextSelectorType
    homeassistant.config_entries = config_entries
    homeassistant.core = core
    homeassistant.helpers = helpers
    helpers.selector = selector
    monkeypatch.setitem(sys.modules, "homeassistant", homeassistant)
    monkeypatch.setitem(sys.modules, "homeassistant.config_entries", config_entries)
    monkeypatch.setitem(sys.modules, "homeassistant.core", core)
    monkeypatch.setitem(sys.modules, "homeassistant.helpers", helpers)
    monkeypatch.setitem(sys.modules, "homeassistant.helpers.selector", selector)

    flow_spec = importlib.util.spec_from_file_location(
        f"{package_name}.config_flow", CONFIG_FLOW
    )
    assert flow_spec and flow_spec.loader
    flow_module = importlib.util.module_from_spec(flow_spec)
    monkeypatch.setitem(sys.modules, flow_spec.name, flow_module)
    flow_spec.loader.exec_module(flow_module)
    return flow_module


def _make_flow(module, harness):
    flow = module.ComelitConfigFlow()
    flow.harness = harness
    return flow


def _entry(module, vip_token="a" * 32):
    return _Entry(
        data={
            module.CONF_DEVICE_UUID: "device-uuid",
            module.CONF_VIP_TOKEN: vip_token,
            module.CONF_OAUTH_ACCESS_TOKEN: "oauth-access",
            module.CONF_OAUTH_REFRESH_TOKEN: "oauth-refresh",
            module.CONF_OAUTH_SCOPE: "openid offline_access",
            module.CONF_OAUTH_EXPIRES_AT: 1234567890,
            "bridge": "bridge-value",
            "shared_secret": "shared-secret-value",
        },
        options={"miniapp_enabled": True, "miniapp_bot_id": "12345"},
        unique_id="stable-unique-id",
        entry_id="stable-entry-id",
    )


def test_reconfigure_updates_only_vip_token(config_flow_module, caplog):
    module = config_flow_module
    entry = _entry(module)
    harness = _Harness(entry)
    flow = _make_flow(module, harness)
    original_data = dict(entry.data)
    original_options = dict(entry.options)
    new_token = "b" * 32

    with caplog.at_level(logging.DEBUG):
        result = asyncio.run(
            flow.async_step_reconfigure({module.CONF_VIP_TOKEN: new_token})
        )

    assert result == {"type": "abort", "reason": "reconfigure_successful"}
    assert entry.data == {**original_data, module.CONF_VIP_TOKEN: new_token}
    assert entry.options == original_options
    assert entry.unique_id == "stable-unique-id"
    assert entry.entry_id == "stable-entry-id"
    assert harness.reloads == 1
    assert harness.entries == [entry]
    assert new_token not in caplog.text
    assert new_token not in repr(result)


def test_reconfigure_unchanged_token_does_not_reload(config_flow_module):
    module = config_flow_module
    entry = _entry(module)
    harness = _Harness(entry)
    flow = _make_flow(module, harness)
    original_data = dict(entry.data)
    original_options = dict(entry.options)

    result = asyncio.run(
        flow.async_step_reconfigure(
            {module.CONF_VIP_TOKEN: entry.data[module.CONF_VIP_TOKEN]}
        )
    )

    assert result == {"type": "abort", "reason": "vip_token_unchanged"}
    assert entry.data == original_data
    assert entry.options == original_options
    assert harness.reloads == 0
    assert harness.entries == [entry]


@pytest.mark.parametrize("invalid_token", ["abc", "g" * 32, ""])
def test_reconfigure_rejects_invalid_token(config_flow_module, invalid_token, caplog):
    module = config_flow_module
    entry = _entry(module)
    harness = _Harness(entry)
    flow = _make_flow(module, harness)
    original_data = dict(entry.data)
    original_options = dict(entry.options)

    with caplog.at_level(logging.DEBUG):
        result = asyncio.run(
            flow.async_step_reconfigure({module.CONF_VIP_TOKEN: invalid_token})
        )

    assert result["type"] == "form"
    assert result["step_id"] == "reconfigure"
    assert result["errors"] == {"base": "invalid_config"}
    assert entry.data == original_data
    assert entry.options == original_options
    assert harness.reloads == 0
    assert harness.entries == [entry]
    if invalid_token:
        assert invalid_token not in caplog.text
        assert invalid_token not in repr(result)


def test_reconfigure_form_has_only_blank_password_field(config_flow_module):
    module = config_flow_module
    entry = _entry(module)
    flow = _make_flow(module, _Harness(entry))

    result = asyncio.run(flow.async_step_reconfigure())

    fields = list(result["data_schema"].schema.items())
    assert len(fields) == 1
    marker, selector = fields[0]
    assert type(marker).__name__ == "Required"
    assert marker.schema == module.CONF_VIP_TOKEN
    assert marker.default is None
    assert selector.config.type == "password"
    assert entry.data[module.CONF_VIP_TOKEN] not in repr(result)
