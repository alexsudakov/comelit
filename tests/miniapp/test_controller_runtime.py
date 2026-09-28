from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
import sys
import types

import pytest


ROOT = Path(__file__).resolve().parents[2]
PKG_ROOT = ROOT / "custom_components" / "comelit"
MINIAPP_ROOT = PKG_ROOT / "miniapp"


def _install_module(name: str, **attrs):
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    sys.modules[name] = module
    return module


class _HomeAssistantError(Exception):
    pass


class _ConfigEntry:
    def __init__(self, options=None):
        self.options = options or {}


class _HomeAssistant:
    pass


_stream_requests: list[tuple[object, str, str]] = []


async def _async_request_stream(hass, entity_id, fmt):
    _stream_requests.append((hass, entity_id, fmt))
    return "/api/hls/deadbeef/master_playlist.m3u8"


_install_module("homeassistant").__path__ = []
_install_module("homeassistant.components").__path__ = []
_camera_module = _install_module(
    "homeassistant.components.camera",
    async_request_stream=_async_request_stream,
)
_camera_module.__path__ = []


class _StreamType:
    WEB_RTC = "web_rtc"


def _get_camera_from_entity_id(hass, entity_id):
    return hass.cameras[entity_id]


_install_module(
    "homeassistant.components.camera.const",
    StreamType=_StreamType,
)
_install_module(
    "homeassistant.components.camera.helper",
    get_camera_from_entity_id=_get_camera_from_entity_id,
)
_install_module(
    "homeassistant.components.stream",
    HLS_PROVIDER="hls",
)
_install_module(
    "homeassistant.config_entries",
    ConfigEntry=_ConfigEntry,
)
_install_module(
    "homeassistant.const",
    STATE_UNAVAILABLE="unavailable",
)
_install_module(
    "homeassistant.core",
    HomeAssistant=_HomeAssistant,
)
_install_module(
    "homeassistant.exceptions",
    HomeAssistantError=_HomeAssistantError,
)
_helpers = _install_module("homeassistant.helpers")
_helpers.__path__ = []
_entity_registry_module = _install_module("homeassistant.helpers.entity_registry")
_label_registry_module = _install_module("homeassistant.helpers.label_registry")

_custom_components = _install_module("custom_components")
_custom_components.__path__ = [str(ROOT / "custom_components")]
_comelit = _install_module("custom_components.comelit")
_comelit.__path__ = [str(PKG_ROOT)]
_miniapp = _install_module("custom_components.comelit.miniapp")
_miniapp.__path__ = [str(MINIAPP_ROOT)]


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_load(PKG_ROOT / "const.py", "custom_components.comelit.const")
session_mod = _load(
    MINIAPP_ROOT / "session.py",
    "custom_components.comelit.miniapp.session",
)
controller_mod = _load(
    MINIAPP_ROOT / "controller.py",
    "custom_components.comelit.miniapp.controller",
)


class FakeState:
    def __init__(self, state: str, attributes: dict | None = None):
        self.state = state
        self.attributes = attributes or {}


class FakeStates:
    def __init__(self, values: dict[str, FakeState]):
        self._values = values

    def get(self, entity_id: str):
        return self._values.get(entity_id)


class FakeRegistryEntry:
    def __init__(
        self,
        entity_id: str,
        platform: str,
        unique_id: str,
        *,
        labels: set[str] | None = None,
        name: str | None = None,
        original_name: str | None = None,
    ):
        self.entity_id = entity_id
        self.platform = platform
        self.unique_id = unique_id
        self.labels = labels or set()
        self.name = name
        self.original_name = original_name


class FakeEntityRegistry:
    def __init__(self, entries: list[FakeRegistryEntry]):
        self.entities = {entry.entity_id: entry for entry in entries}

    def async_get(self, entity_id: str):
        return self.entities.get(entity_id)

    def async_get_entity_id(self, domain: str, platform: str, unique_id: str):
        prefix = domain + "."
        for entry in self.entities.values():
            if (
                entry.entity_id.startswith(prefix)
                and entry.platform == platform
                and entry.unique_id == unique_id
            ):
                return entry.entity_id
        return None


class FakeLabel:
    def __init__(self, label_id: str, name: str):
        self.label_id = label_id
        self.name = name


class FakeLabelRegistry:
    def __init__(self, labels: list[FakeLabel] | None = None):
        self._labels = labels or []

    def async_get_label(self, value: str):
        return next((label for label in self._labels if label.label_id == value), None)

    def async_get_label_by_name(self, value: str):
        return next((label for label in self._labels if label.name == value), None)




class FakeCameraCapabilities:
    def __init__(self, frontend_stream_types):
        self.frontend_stream_types = set(frontend_stream_types)


class FakeCamera:
    def __init__(self, frontend_stream_types):
        self.camera_capabilities = FakeCameraCapabilities(frontend_stream_types)


class FakeServices:
    def __init__(self):
        self.calls: list[tuple[str, str, dict, bool]] = []

    async def async_call(self, domain: str, service: str, data: dict, *, blocking: bool):
        self.calls.append((domain, service, data, blocking))


class FakeHass:
    def __init__(
        self,
        *,
        states: dict[str, FakeState],
        entries: list[FakeRegistryEntry],
        labels: list[FakeLabel] | None = None,
    ):
        self.states = FakeStates(states)
        self.entity_registry = FakeEntityRegistry(entries)
        self.label_registry = FakeLabelRegistry(labels)
        self.services = FakeServices()
        self.cameras = {}


_entity_registry_module.async_get = lambda hass: hass.entity_registry
_label_registry_module.async_get = lambda hass: hass.label_registry


def _controller(*, surveillance_label: str = ""):
    entries = [
        FakeRegistryEntry(
            "camera.comelit_entrance",
            "comelit",
            "comelit_entrance_camera",
            original_name="Entrance camera",
        ),
        FakeRegistryEntry(
            "button.comelit_main_entrance_open_door",
            "comelit",
            "comelit_main_entrance_open_door",
            original_name="Open entrance",
        ),
        FakeRegistryEntry(
            "button.comelit_main_gate_open_door",
            "comelit",
            "comelit_main_gate_open_door",
            original_name="Open gate",
        ),
        FakeRegistryEntry(
            "sensor.comelit_call_state",
            "comelit",
            "comelit_call_state",
            original_name="Call state",
        ),
        FakeRegistryEntry(
            "camera.driveway",
            "generic",
            "driveway",
            labels={"outside"},
            original_name="Driveway",
        ),
        FakeRegistryEntry(
            "person.private",
            "person",
            "private",
            labels={"outside"},
            original_name="Private person",
        ),
    ]
    states = {
        "camera.comelit_entrance": FakeState(
            "idle",
            {
                "friendly_name": "Entrance",
                "secret_transport_detail": "must-not-leak",
            },
        ),
        "button.comelit_main_entrance_open_door": FakeState(
            "unknown",
            {
                "friendly_name": "Entrance",
                "standard_press_allowed": True,
                "blocked_by_media_session": False,
                "physical_door_state": "UNKNOWN",
            },
        ),
        "button.comelit_main_gate_open_door": FakeState(
            "unknown",
            {
                "friendly_name": "Gate",
                "standard_press_allowed": True,
                "blocked_by_media_session": False,
            },
        ),
        "sensor.comelit_call_state": FakeState(
            "ringing",
            {
                "panel": "entrance",
                "event_id": "evt-1",
                "media_attached": True,
                "private_runtime_field": "must-not-leak",
            },
        ),
        "camera.driveway": FakeState(
            "idle",
            {"friendly_name": "Driveway", "entity_picture": "/secret/path"},
        ),
        "person.private": FakeState("home", {"friendly_name": "Private"}),
    }
    labels = [FakeLabel("outside", "Outside")]
    hass = FakeHass(states=states, entries=entries, labels=labels)
    controller = controller_mod.ComelitMiniAppController(hass, PKG_ROOT / "frontend")
    controller.set_entry(
        _ConfigEntry(
            {
                "miniapp_enabled": True,
                "miniapp_bot_id": "12345678",
                "miniapp_allowed_user_ids": "424242",
                "miniapp_surveillance_label": surveillance_label,
            }
        )
    )
    return controller, hass


def test_bootstrap_filters_registry_and_state_attributes():
    controller, _hass = _controller(surveillance_label="Outside")
    token, session = controller.sessions.create(424242, 12345678, now=1_800_000_000)

    payload = controller.bootstrap(session)

    assert token
    assert set(payload["states"]) == {
        "camera.comelit_entrance",
        "button.comelit_main_entrance_open_door",
        "button.comelit_main_gate_open_door",
        "sensor.comelit_call_state",
        "camera.driveway",
    }
    assert payload["surveillance_entities"] == ["camera.driveway"]
    assert payload["states"]["sensor.comelit_call_state"]["attributes"] == {
        "panel": "entrance",
        "event_id": "evt-1",
        "media_attached": True,
    }
    assert payload["states"]["button.comelit_main_entrance_open_door"]["attributes"] == {
        "friendly_name": "Entrance",
        "standard_press_allowed": True,
        "blocked_by_media_session": False,
    }
    serialized = repr(payload)
    assert "person.private" not in serialized
    assert "must-not-leak" not in serialized
    assert "/secret/path" not in serialized


def test_door_press_maps_semantic_target_to_exactly_one_service_call():
    controller, hass = _controller()

    asyncio.run(controller.async_press_door("entrance"))

    assert hass.services.calls == [
        (
            "button",
            "press",
            {"entity_id": "button.comelit_main_entrance_open_door"},
            True,
        )
    ]


def test_door_press_fails_closed_before_service_call_when_unavailable():
    controller, hass = _controller()
    hass.states._values["button.comelit_main_gate_open_door"] = FakeState(
        "unavailable",
        {"standard_press_allowed": True},
    )

    with pytest.raises(controller_mod.MiniAppOperationError, match="unavailable"):
        asyncio.run(controller.async_press_door("gate"))

    assert hass.services.calls == []


def test_door_press_rejects_unknown_semantic_target_without_service_call():
    controller, hass = _controller()

    with pytest.raises(controller_mod.MiniAppOperationError, match="unsupported"):
        asyncio.run(controller.async_press_door("garage"))

    assert hass.services.calls == []


def test_camera_uses_one_ha_hls_request_and_returns_only_proxy_capability():
    controller, hass = _controller()
    _stream_requests.clear()
    token, session = controller.sessions.create(424242, 12345678)

    proxy_url = asyncio.run(
        controller.async_create_camera_media(
            token,
            session,
            "camera.comelit_entrance",
        )
    )

    assert _stream_requests == [(hass, "camera.comelit_entrance", "hls")]
    assert proxy_url.startswith("/api/comelit/miniapp/media/")
    assert proxy_url.endswith("/master_playlist.m3u8")
    assert "/api/hls/" not in proxy_url

    media_id = proxy_url.split("/")[5]
    assert (
        controller.resolve_media_upstream_path(
            media_id,
            token,
            "playlist.m3u8",
        )
        == "/api/hls/deadbeef/playlist.m3u8"
    )
    assert (
        controller.resolve_media_upstream_path(
            media_id,
            token,
            "segment/12.3.m4s",
        )
        == "/api/hls/deadbeef/segment/12.3.m4s"
    )


def test_camera_rejects_unlisted_entity_without_starting_stream():
    controller, _hass = _controller()
    _stream_requests.clear()
    token, session = controller.sessions.create(424242, 12345678)

    with pytest.raises(controller_mod.MiniAppOperationError, match="not allowed"):
        asyncio.run(
            controller.async_create_camera_media(
                token,
                session,
                "camera.unlisted",
            )
        )

    assert _stream_requests == []


def test_media_proxy_tail_is_closed_set():
    controller, _hass = _controller()
    token, session = controller.sessions.create(424242, 12345678)
    media_id = controller.media_grants.create(
        token,
        "/api/hls/deadbeef/",
        session.expires_at,
    )

    for unsafe in (
        "../config/.storage",
        "../../api/states",
        "segment/1.ts",
        "segment/not-a-number.m4s",
        "anything",
    ):
        with pytest.raises(controller_mod.MiniAppOperationError, match="unsupported"):
            controller.resolve_media_upstream_path(media_id, token, unsafe)


def test_webrtc_surveillance_camera_allows_ordinary_labeled_camera():
    controller, hass = _controller(surveillance_label="Outside")
    camera = FakeCamera({_StreamType.WEB_RTC})
    hass.cameras["camera.driveway"] = camera

    assert controller.get_webrtc_surveillance_camera("camera.driveway") is camera


def test_webrtc_surveillance_camera_rejects_intercom_camera():
    controller, hass = _controller(surveillance_label="Outside")
    hass.cameras["camera.comelit_entrance"] = FakeCamera({_StreamType.WEB_RTC})

    with pytest.raises(
        controller_mod.MiniAppOperationError,
        match="intercom camera WebRTC is not enabled",
    ):
        controller.get_webrtc_surveillance_camera("camera.comelit_entrance")


def test_webrtc_surveillance_camera_falls_back_when_provider_missing():
    controller, hass = _controller(surveillance_label="Outside")
    hass.cameras["camera.driveway"] = FakeCamera(set())

    with pytest.raises(
        controller_mod.MiniAppOperationError,
        match="camera WebRTC is unavailable",
    ):
        controller.get_webrtc_surveillance_camera("camera.driveway")
