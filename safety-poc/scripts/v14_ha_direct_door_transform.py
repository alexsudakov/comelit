#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CC = ROOT / "custom_components" / "comelit"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)


def patch_runtime() -> None:
    p = CC / "runtime.py"
    s = p.read_text(encoding="utf-8")
    if "async def async_open_door(" in s:
        raise RuntimeError("runtime already contains direct Door")

    s = replace_once(s, "import re\n", "import re\nimport signal\n", "signal import")
    s = replace_once(
        s,
        "_STOP_FILE = _RUN_DIR / \"stop\"\n",
        "_STOP_FILE = _RUN_DIR / \"stop\"\n\n"
        "_DOOR_STATES = {\n"
        "    \"ACKED\",\n"
        "    \"REJECTED\",\n"
        "    \"REJECTED_NOT_READY\",\n"
        "    \"FAILED_SAFE\",\n"
        "    \"UNKNOWN_OUTCOME\",\n"
        "}\n",
        "Door states",
    )
    s = replace_once(
        s,
        "        self._last_error: str | None = None\n        self._stopping = False\n",
        "        self._last_error: str | None = None\n"
        "        self._stopping = False\n"
        "        self._door_lock = asyncio.Lock()\n"
        "        self._door_result_future: asyncio.Future[str] | None = None\n"
        "        self._last_door_result: dict[str, object] | None = None\n",
        "Door runtime state",
    )
    s = replace_once(
        s,
        "    @property\n    def ring_observed(self) -> bool:\n        return self._last_ring_event is not None\n",
        "    @property\n    def ring_observed(self) -> bool:\n"
        "        return self._last_ring_event is not None\n\n"
        "    @property\n    def last_door_result(self) -> dict[str, object] | None:\n"
        "        return dict(self._last_door_result) if self._last_door_result else None\n",
        "Door result property",
    )
    s = replace_once(
        s,
        "            \"last_error\": self._last_error,\n        }\n",
        "            \"last_error\": self._last_error,\n"
        "            \"door_last_operation_id\": (self._last_door_result or {}).get(\"operation_id\"),\n"
        "            \"door_last_state\": (self._last_door_result or {}).get(\"state\"),\n"
        "        }\n",
        "Door status fields",
    )

    stop_old = """        self._task = None
        self._process = None
        await self._hass.async_add_executor_job(_remove_helper_secret)
"""
    stop_new = """        self._task = None
        self._process = None
        self._listener_ready.clear()
        await self._hass.async_add_executor_job(_remove_helper_secret)
"""
    if stop_old in s:
        s = replace_once(s, stop_old, stop_new, "listener clear on stop")
    elif stop_new not in s:
        raise RuntimeError("listener clear on stop anchor missing")

    final_old = """        finally:
            self._process = None
            await self._hass.async_add_executor_job(_remove_helper_secret)
"""
    final_new = """        finally:
            self._process = None
            self._listener_ready.clear()
            future = self._door_result_future
            if future is not None and not future.done():
                future.set_result("UNKNOWN_OUTCOME")
            await self._hass.async_add_executor_job(_remove_helper_secret)
"""
    if final_old in s:
        s = replace_once(s, final_old, final_new, "listener clear on runtime exit")
    elif final_new not in s:
        raise RuntimeError("runtime finalizer anchor missing")

    door_method = '''    async def async_open_door(self, door: str) -> dict[str, object]:
        """Execute exactly one direct Door attempt on the persistent session."""
        if door != "entrance":
            raise ComelitRingRuntimeError("unsupported_door")

        async with self._door_lock:
            if not self.running:
                await self.async_start()

            if not await self.async_wait_ready(timeout=30):
                result = {
                    "operation_id": None,
                    "door": door,
                    "state": "FAILED_SAFE",
                    "protocol_acked": False,
                    "write_count": None,
                    "automatic_retry_allowed": False,
                    "physical_effect_asserted": False,
                }
                self._last_door_result = dict(result)
                return result

            process = self._process
            if process is None or process.returncode is not None:
                result = {
                    "operation_id": None,
                    "door": door,
                    "state": "FAILED_SAFE",
                    "protocol_acked": False,
                    "write_count": None,
                    "automatic_retry_allowed": False,
                    "physical_effect_asserted": False,
                }
                self._last_door_result = dict(result)
                return result

            loop = asyncio.get_running_loop()
            future: asyncio.Future[str] = loop.create_future()
            self._door_result_future = future

            # Generate the operation id immediately before the irreversible
            # one-shot boundary.  It is HA-local and is never caller supplied.
            operation_id = f"comelit-ha-{uuid4()}"
            try:
                os.kill(process.pid, signal.SIGUSR1)
            except ProcessLookupError:
                self._door_result_future = None
                result = {
                    "operation_id": operation_id,
                    "door": door,
                    "state": "FAILED_SAFE",
                    "protocol_acked": False,
                    "write_count": None,
                    "automatic_retry_allowed": False,
                    "physical_effect_asserted": False,
                }
                self._last_door_result = dict(result)
                return result

            try:
                state = await asyncio.wait_for(asyncio.shield(future), timeout=10)
            except TimeoutError:
                state = "UNKNOWN_OUTCOME"
            finally:
                if self._door_result_future is future:
                    self._door_result_future = None

            result = {
                "operation_id": operation_id,
                "door": door,
                "state": state,
                "protocol_acked": state == "ACKED",
                "write_count": 6 if state == "ACKED" else None,
                "automatic_retry_allowed": False,
                "physical_effect_asserted": False,
            }
            self._last_door_result = dict(result)
            return result

'''
    s = replace_once(
        s,
        "    async def _async_run_once(self) -> None:\n",
        door_method + "    async def _async_run_once(self) -> None:\n",
        "Door method",
    )

    output_anchor = '''            if line == "V4_RING_LISTENER_READY=true":
                self._listener_ready.set()
                _LOGGER.warning(
                    "Comelit ring listener READY for persistent 3300s cycle"
                )
                continue

'''
    output_new = output_anchor + '''            if line.startswith("V4_DOOR_RESULT="):
                state = line.split("=", 1)[1]
                if state not in _DOOR_STATES:
                    state = "UNKNOWN_OUTCOME"
                future = self._door_result_future
                if future is not None and not future.done():
                    future.set_result(state)
                _LOGGER.warning("Comelit Door protocol result: %s", state)
                continue

'''
    s = replace_once(s, output_anchor, output_new, "Door native result parser")
    p.write_text(s, encoding="utf-8")


def write_const() -> None:
    (CC / "const.py").write_text('''from __future__ import annotations

DOMAIN = "comelit"
PLATFORMS = ["button"]
DATA_RUNTIMES = "ring_runtimes"

CONF_DEVICE_UUID = "device_uuid"
CONF_VIP_TOKEN = "vip_token"
CONF_OAUTH_ACCESS_TOKEN = "oauth_access_token"

# Transitional bridge keys retained only for migration compatibility.
CONF_BRIDGE_URL = "bridge_url"
CONF_SHARED_SECRET = "shared_secret"

EVENT_RING = "comelit_ring"
SERVICE_OPEN_DOOR = "open_door"
ATTR_DOOR = "door"
DOOR_ENTRANCE = "entrance"
SUPPORTED_DOORS = (DOOR_ENTRANCE,)

MAIN_ENTRANCE_UNIQUE_ID = "comelit_main_entrance_open_door"
MAIN_ENTRANCE_ENTITY_ID = "button.comelit_main_entrance_open_door"

BRIDGE_PROTOCOL_VERSION = 1
BRIDGE_PORT = 18014
BRIDGE_REQUEST_TIMEOUT_SECONDS = 175
''', encoding="utf-8")


def write_init() -> None:
    (CC / "__init__.py").write_text('''from __future__ import annotations

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .client import ComelitBridgeClient
from .const import (
    ATTR_DOOR,
    CONF_BRIDGE_URL,
    CONF_DEVICE_UUID,
    CONF_OAUTH_ACCESS_TOKEN,
    CONF_SHARED_SECRET,
    CONF_VIP_TOKEN,
    DATA_RUNTIMES,
    DOMAIN,
    PLATFORMS,
    SERVICE_OPEN_DOOR,
    SUPPORTED_DOORS,
)
from .runtime import ComelitRingRuntime
from .test_control import async_register_test_control, async_unregister_test_control


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register direct Comelit services."""

    async def handle_open_door(call: ServiceCall) -> dict[str, object]:
        runtimes = hass.data.get(DOMAIN, {}).get(DATA_RUNTIMES, {})
        if len(runtimes) != 1:
            raise HomeAssistantError("Comelit direct runtime is not uniquely available")
        runtime: ComelitRingRuntime = next(iter(runtimes.values()))
        return await runtime.async_open_door(str(call.data[ATTR_DOOR]))

    hass.services.async_register(
        DOMAIN,
        SERVICE_OPEN_DOOR,
        handle_open_door,
        schema=vol.Schema({vol.Required(ATTR_DOOR): vol.In(SUPPORTED_DOORS)}),
        supports_response=SupportsResponse.OPTIONAL,
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up direct Ring/Door runtime and optional legacy bridge client."""
    session = async_get_clientsession(hass)
    domain_data = hass.data.setdefault(DOMAIN, {})

    has_bridge = all(
        entry.data.get(key) for key in (CONF_BRIDGE_URL, CONF_SHARED_SECRET)
    )
    if has_bridge:
        domain_data[entry.entry_id] = ComelitBridgeClient(
            session,
            bridge_url=str(entry.data[CONF_BRIDGE_URL]),
            shared_secret=str(entry.data[CONF_SHARED_SECRET]),
        )

    has_direct_credentials = all(
        entry.data.get(key)
        for key in (CONF_DEVICE_UUID, CONF_VIP_TOKEN, CONF_OAUTH_ACCESS_TOKEN)
    )
    if has_direct_credentials:
        runtime = ComelitRingRuntime(
            hass,
            session,
            device_uuid=str(entry.data[CONF_DEVICE_UUID]),
            vip_token=str(entry.data[CONF_VIP_TOKEN]),
            oauth_access_token=str(entry.data[CONF_OAUTH_ACCESS_TOKEN]),
        )
        runtimes = domain_data.setdefault(DATA_RUNTIMES, {})
        runtimes[entry.entry_id] = runtime

        # Keep explicit validation start/stop until the reconnect supervisor is
        # enabled. Door actions may start the same runtime on demand.
        async_register_test_control(hass, runtime)
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    domain_data = hass.data.get(DOMAIN, {})
    runtimes = domain_data.get(DATA_RUNTIMES, {})
    runtime = runtimes.pop(entry.entry_id, None)

    unloaded = True
    if runtime is not None:
        async_unregister_test_control(hass)
        await runtime.async_stop()
        unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unloaded:
        domain_data.pop(entry.entry_id, None)
        if not runtimes:
            domain_data.pop(DATA_RUNTIMES, None)
    return unloaded
''', encoding="utf-8")


def write_button() -> None:
    (CC / "button.py").write_text('''from __future__ import annotations

from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DATA_RUNTIMES,
    DOMAIN,
    DOOR_ENTRANCE,
    MAIN_ENTRANCE_ENTITY_ID,
    MAIN_ENTRANCE_UNIQUE_ID,
)
from .runtime import ComelitRingRuntime


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    runtime: ComelitRingRuntime | None = (
        hass.data.get(DOMAIN, {}).get(DATA_RUNTIMES, {}).get(entry.entry_id)
    )
    if runtime is not None:
        async_add_entities([ComelitEntranceDoorButton(runtime)])


class ComelitEntranceDoorButton(ButtonEntity):
    """One-shot entrance Door command through the direct HA runtime."""

    _attr_name = "Comelit — Подъезд"
    _attr_unique_id = MAIN_ENTRANCE_UNIQUE_ID
    _attr_icon = "mdi:door-open"
    _attr_should_poll = False

    def __init__(self, runtime: ComelitRingRuntime) -> None:
        self._runtime = runtime
        self.entity_id = MAIN_ENTRANCE_ENTITY_ID
        self._last_result: dict[str, object] | None = None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        result = self._last_result or self._runtime.last_door_result or {}
        return {
            "standard_press_allowed": True,
            "one_shot_operation_required": True,
            "automatic_retry_allowed": False,
            "physical_effect_asserted": False,
            "physical_door_state": "UNKNOWN",
            "last_operation_id": result.get("operation_id"),
            "last_protocol_state": result.get("state"),
            "last_protocol_acked": result.get("protocol_acked"),
        }

    async def async_press(self) -> None:
        result = await self._runtime.async_open_door(DOOR_ENTRANCE)
        self._last_result = dict(result)
        self.async_write_ha_state()
        if result.get("state") != "ACKED":
            raise HomeAssistantError(
                "Comelit Door was not protocol-ACKED; automatic retry is forbidden. "
                f"state={result.get('state')}"
            )
''', encoding="utf-8")


def write_services() -> None:
    (CC / "services.yaml").write_text('''open_door:
  name: Open Comelit door
  description: Execute one direct Comelit Door attempt. Protocol ACK does not prove physical opening.
  fields:
    door:
      name: Door
      required: true
      example: entrance
      selector:
        select:
          options:
            - entrance
''', encoding="utf-8")


def patch_manifest() -> None:
    p = CC / "manifest.json"
    s = p.read_text(encoding="utf-8")
    s = replace_once(s, '"version": "1.3.1"', '"version": "1.4.0"', "manifest version")
    p.write_text(s, encoding="utf-8")


def main() -> int:
    patch_runtime()
    write_const()
    write_init()
    write_button()
    write_services()
    patch_manifest()
    print("V14_HA_DIRECT_DOOR_TRANSFORM=PASS")
    print("V14_HA_DOOR_TARGET=entrance")
    print("V14_HA_OPERATION_ID_CALLER_SUPPLIED=false")
    print("V14_HA_AUTOMATIC_RETRY_ALLOWED=false")
    print("V14_HA_PHYSICAL_EFFECT_ASSERTED=false")
    print("NETWORK_ACTION_PERFORMED=false")
    print("PHYSICAL_DOOR_ACTION=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
