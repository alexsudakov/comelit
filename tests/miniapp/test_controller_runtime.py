from __future__ import annotations

import asyncio
import importlib.util
import json
import logging
from pathlib import Path
import sys
import time
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
    def __init__(self, options=None, entry_id="entry-1"):
        self.options = options or {}
        self.entry_id = entry_id


class _HomeAssistant:
    pass


_stream_requests: list[tuple[object, str, str]] = []


async def _async_request_stream(hass, entity_id, fmt):
    _stream_requests.append((hass, entity_id, fmt))
    return "/api/hls/deadbeef/master_playlist.m3u8"


_install_module("homeassistant").__path__ = []
_install_module("homeassistant.components").__path__ = []


class _HTTPException(Exception):
    status = 500


class _HTTPForbidden(_HTTPException):
    status = 403


class _HTTPNotFound(_HTTPException):
    status = 404


class _HTTPBadRequest(_HTTPException):
    status = 400


class _HTTPConflict(_HTTPException):
    status = 409

    def __init__(self, text: str = ""):
        super().__init__(text)
        self.text = text


class _HTTPServiceUnavailable(_HTTPException):
    status = 503


class _HTTPGatewayTimeout(_HTTPException):
    status = 504


class _HTTPBadGateway(_HTTPException):
    status = 502


class _HTTPRequestEntityTooLarge(_HTTPException):
    status = 413

    def __init__(self, *, max_size: int, actual_size: int):
        super().__init__(max_size, actual_size)


class _FakeResponse:
    def __init__(self, data=None, *, status=200, text=""):
        self.data = data
        self.status = status
        self.text = text or (json.dumps(data) if data is not None else "")
        self.headers = {}

    def set_cookie(self, *args, **kwargs):
        pass

    def del_cookie(self, *args, **kwargs):
        pass


class _FakeWebSocketResponse:
    closed = True

    def __init__(self, *args, **kwargs):
        pass


_aiohttp_web = types.SimpleNamespace(
    StreamResponse=_FakeResponse,
    Response=_FakeResponse,
    FileResponse=lambda *args, **kwargs: _FakeResponse(),
    WebSocketResponse=_FakeWebSocketResponse,
    json_response=lambda data, status=200: _FakeResponse(data, status=status),
    HTTPForbidden=_HTTPForbidden,
    HTTPNotFound=_HTTPNotFound,
    HTTPBadRequest=_HTTPBadRequest,
    HTTPConflict=_HTTPConflict,
    HTTPServiceUnavailable=_HTTPServiceUnavailable,
    HTTPGatewayTimeout=_HTTPGatewayTimeout,
    HTTPBadGateway=_HTTPBadGateway,
    HTTPRequestEntityTooLarge=_HTTPRequestEntityTooLarge,
)
_install_module(
    "aiohttp",
    ClientError=Exception,
    ClientSession=object,
    ClientTimeout=lambda **kwargs: kwargs,
    WSMsgType=types.SimpleNamespace(
        ERROR="error",
        TEXT="text",
        BINARY="binary",
        CLOSE="close",
        CLOSED="closed",
    ),
    web=_aiohttp_web,
)
_install_module("mashumaro", MissingField=ValueError)


def _get_camera_from_entity_id(hass, entity_id):
    return hass.cameras[entity_id]


_camera_module = _install_module(
    "homeassistant.components.camera",
    async_request_stream=_async_request_stream,
    Camera=object,
    CameraEntityFeature=types.SimpleNamespace(STREAM=1),
    get_camera_from_entity_id=_get_camera_from_entity_id,
    get_dynamic_camera_stream_settings=lambda *args, **kwargs: None,
)
_camera_module.__path__ = []


class _StreamType:
    WEB_RTC = "web_rtc"


_install_module(
    "homeassistant.components.camera.const",
    DATA_CAMERA_PREFS="camera_prefs",
    StreamType=_StreamType,
)
_install_module(
    "homeassistant.components.http",
    HomeAssistantView=object,
)
_install_module(
    "homeassistant.components.stream",
    HLS_PROVIDER="hls",
    Stream=object,
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
_install_module(
    "homeassistant.helpers.aiohttp_client",
    async_get_clientsession=lambda hass: None,
)
_install_module(
    "homeassistant.helpers.entity_platform",
    AddEntitiesCallback=object,
)
_entity_registry_module = _install_module("homeassistant.helpers.entity_registry")
_label_registry_module = _install_module("homeassistant.helpers.label_registry")
_install_module(
    "homeassistant.helpers.network",
    NoURLAvailableError=ValueError,
    get_url=lambda *args, **kwargs: "http://127.0.0.1:8123",
)
_install_module(
    "webrtc_models",
    RTCIceCandidateInit=types.SimpleNamespace(
        from_dict=lambda value: value,
    ),
)

_custom_components = _install_module("custom_components")
_custom_components.__path__ = [str(ROOT / "custom_components")]
_comelit = _install_module("custom_components.comelit")
_comelit.__path__ = [str(PKG_ROOT)]
_miniapp = _install_module("custom_components.comelit.miniapp")
_miniapp.__path__ = [str(MINIAPP_ROOT)]
_install_module(
    "custom_components.comelit.media_transport",
    ComelitEntranceMediaTransport=object,
    H264RecoveryRtpShim=object,
    MEDIA_VIDEO_RTP_PORT=17899,
    MEDIA_VIDEO_HA_RTP_PORT=17999,
    MEDIA_AUDIO_RTP_PORT=17808,
)


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _read_file(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


_load(PKG_ROOT / "const.py", "custom_components.comelit.const")
session_mod = _load(
    MINIAPP_ROOT / "session.py",
    "custom_components.comelit.miniapp.session",
)
controller_mod = _load(
    MINIAPP_ROOT / "controller.py",
    "custom_components.comelit.miniapp.controller",
)
diagnostics_mod = _load(
    MINIAPP_ROOT / "diagnostics.py",
    "custom_components.comelit.miniapp.diagnostics",
)
webcodecs_mod = _load(
    MINIAPP_ROOT / "webcodecs.py",
    "custom_components.comelit.miniapp.webcodecs",
)
views_mod = _load(
    MINIAPP_ROOT / "views.py",
    "custom_components.comelit.miniapp.views",
)
go2rtc_mod = sys.modules["custom_components.comelit.miniapp.go2rtc"]


def _ring_media_mod():
    module = sys.modules.get("custom_components.comelit.ring_media")
    if module is not None:
        return module
    return _load(
        PKG_ROOT / "ring_media.py",
        "custom_components.comelit.ring_media",
    )


def _attached_media_mod():
    module = sys.modules.get("custom_components.comelit.attached_media")
    if module is not None:
        return module
    return _load(
        PKG_ROOT / "attached_media.py",
        "custom_components.comelit.attached_media",
    )


def _camera_mod():
    module = sys.modules.get("custom_components.comelit.camera")
    if module is not None:
        return module
    _ring_media_mod()
    _attached_media_mod()
    return _load(
        PKG_ROOT / "camera.py",
        "custom_components.comelit.camera",
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
    def __init__(self, frontend_stream_types, stream_source: str | None = None):
        self.camera_capabilities = FakeCameraCapabilities(frontend_stream_types)
        self.stream_source_value = stream_source
        self.stream_source_calls = 0

    async def stream_source(self):
        self.stream_source_calls += 1
        return self.stream_source_value


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
        self.data = {}
        self.bus = types.SimpleNamespace(async_fire=lambda *args, **kwargs: None)

    def async_create_task(self, coro):
        return asyncio.create_task(coro)

    async def async_add_executor_job(self, func, /, *args, **kwargs):
        return func(*args, **kwargs)


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


class FakeGo2RTC:
    def __init__(self):
        self.registers: list[tuple[str, list[str]]] = []
        self.unregisters: list[str] = []

    async def register_stream(self, internal_name: str, sources: list[str]):
        self.registers.append((internal_name, list(sources)))

    async def unregister_stream(self, internal_name: str):
        self.unregisters.append(internal_name)


def test_mse_stream_progress_marks_source_and_registration():
    controller, hass = _controller(surveillance_label="Outside")
    fake_go2rtc = FakeGo2RTC()
    controller.go2rtc = fake_go2rtc
    hass.cameras["camera.driveway"] = FakeCamera(
        set(),
        "rtsp://192.0.2.10/example",
    )
    progress: list[str] = []

    async def run():
        lease = await controller.acquire_mse_stream(
            "camera.driveway",
            progress=progress.append,
        )
        await controller.release_mse_stream("camera.driveway")

    asyncio.run(run())

    assert progress == ["mse_source_resolved", "mse_stream_registered"]


def test_mse_stream_uses_public_stream_source_and_opaque_refcounted_name():
    controller, hass = _controller(surveillance_label="Outside")
    fake_go2rtc = FakeGo2RTC()
    controller.go2rtc = fake_go2rtc
    source = "rtsp://test-user:test-password@192.0.2.10/example"
    hass.cameras["camera.driveway"] = FakeCamera(set(), source)

    async def run():
        first = await controller.acquire_mse_stream("camera.driveway")
        second = await controller.acquire_mse_stream("camera.driveway")
        assert first.internal_name == second.internal_name
        assert first.internal_name.startswith("comelit_miniapp_")
        assert "driveway" not in first.internal_name
        assert "test-user" not in first.internal_name
        await controller.release_mse_stream("camera.driveway")
        assert fake_go2rtc.unregisters == []
        await controller.release_mse_stream("camera.driveway")
        assert fake_go2rtc.unregisters == [first.internal_name]

    asyncio.run(run())

    internal_name = controller.mse_internal_stream_name("camera.driveway")
    assert fake_go2rtc.registers == [(internal_name, [source + "#backchannel=0"])]


def test_mse_stream_disables_generic_rtsp_backchannel_only():
    controller, hass = _controller(surveillance_label="Outside")
    fake_go2rtc = FakeGo2RTC()
    controller.go2rtc = fake_go2rtc
    source = "rtsp://192.0.2.10/example"
    hass.cameras["camera.driveway"] = FakeCamera(set(), source)

    async def acquire_and_release():
        lease = await controller.acquire_mse_stream("camera.driveway")
        await controller.release_mse_stream("camera.driveway")
        return lease.internal_name

    internal_name = asyncio.run(acquire_and_release())
    assert fake_go2rtc.registers == [
        (internal_name, [source + "#backchannel=0"])
    ]

    fake_go2rtc.registers.clear()
    hass.entity_registry.entities["camera.driveway"].platform = "other"
    internal_name = asyncio.run(acquire_and_release())
    assert fake_go2rtc.registers == [(internal_name, [source])]


def test_mse_stream_preserves_existing_go2rtc_fragment_when_disabling_backchannel():
    controller, hass = _controller(surveillance_label="Outside")
    fake_go2rtc = FakeGo2RTC()
    controller.go2rtc = fake_go2rtc
    source = "rtsp://192.0.2.10/example#transport=tcp"
    hass.cameras["camera.driveway"] = FakeCamera(set(), source)

    async def run():
        lease = await controller.acquire_mse_stream("camera.driveway")
        await controller.release_mse_stream("camera.driveway")
        return lease.internal_name

    internal_name = asyncio.run(run())
    assert fake_go2rtc.registers == [
        (internal_name, [source + "&backchannel=0"])
    ]


def test_mse_stream_rejects_intercom_unlisted_none_and_unsupported_source():
    controller, hass = _controller(surveillance_label="Outside")
    controller.go2rtc = FakeGo2RTC()
    hass.cameras["camera.comelit_entrance"] = FakeCamera(set(), "rtsp://example/live")
    hass.cameras["camera.driveway"] = FakeCamera(set(), None)

    async def run():
        with pytest.raises(controller_mod.MiniAppOperationError, match="intercom"):
            await controller.acquire_mse_stream("camera.comelit_entrance")
        with pytest.raises(controller_mod.MiniAppOperationError, match="not allowed"):
            await controller.acquire_mse_stream("camera.unlisted")
        with pytest.raises(controller_mod.MiniAppOperationError, match="stream_source"):
            await controller.acquire_mse_stream("camera.driveway")
        hass.cameras["camera.driveway"] = FakeCamera(set(), "ffmpeg:camera.driveway")
        with pytest.raises(controller_mod.MiniAppOperationError, match="stream_source"):
            await controller.acquire_mse_stream("camera.driveway")

    asyncio.run(run())


def test_intercom_unique_ids_preserve_existing_mse_gate_camera_admission():
    assert "comelit_gate_camera" not in controller_mod.INTERCOM_UNIQUE_IDS
    assert "comelit_gate_camera" in controller_mod.WEBCODECS_INTERCOM_UNIQUE_IDS

    controller, hass = _controller(surveillance_label="Outside")
    controller.go2rtc = FakeGo2RTC()
    source = "rtsp://192.0.2.10/gate"
    hass.entity_registry.entities["camera.comelit_gate"] = FakeRegistryEntry(
        "camera.comelit_gate",
        "comelit",
        "comelit_gate_camera",
        labels={"outside"},
    )
    hass.states._values["camera.comelit_gate"] = FakeState("idle")
    hass.cameras["camera.comelit_gate"] = FakeCamera(set(), source)

    async def run():
        lease = await controller.acquire_mse_stream("camera.comelit_gate")
        await controller.release_mse_stream("camera.comelit_gate")
        return lease.internal_name

    internal_name = asyncio.run(run())
    assert controller.go2rtc.registers == [(internal_name, [source])]


def test_server_mse_diagnostics_are_closed_and_secret_free():
    line = diagnostics_mod.format_server_log_line(
        "camera.driveway",
        "mse_stream_registered",
        elapsed_ms=12,
        stage_ms=7,
    )
    assert line == (
        "COMELIT_MINIAPP_DIAG_SERVER entity=camera.driveway "
        "event=mse_stream_registered elapsed_ms=12 stage_ms=7 "
        "state=- reason=- counters=-"
    )
    with pytest.raises(diagnostics_mod.MiniAppDiagnosticsError):
        diagnostics_mod.format_server_log_line(
            "camera.driveway",
            "rtsp://secret",
            elapsed_ms=12,
            stage_ms=7,
        )


def test_go2rtc_stream_state_summary_is_closed_and_secret_free():
    raw = {
        "producers": [
            {
                "id": 7,
                "url": "rtsp://test-user:test-password@192.0.2.10/example",
                "remote_addr": "192.0.2.10:554",
                "medias": [
                    "video, recvonly, H264",
                    "audio, recvonly, PCMA/8000",
                ],
                "receivers": [{}, {}],
                "bytes_recv": 32768,
            },
            {
                "id": 8,
                "source": "ffmpeg:opaque-stream#audio=opus",
                "medias": [
                    "video, recvonly, H264",
                    "audio, recvonly, OPUS/48000/2",
                ],
                "receivers": [{}],
                "bytes_recv": 8192,
            },
        ],
        "consumers": [
            {
                "remote_addr": "secret",
                "senders": [{}, {}],
            }
        ],
    }

    summary = go2rtc_mod.summarize_stream_state(raw)

    assert summary == {
        "inspect_ok": 1,
        "producer_count": 2,
        "consumer_count": 1,
        "p0_active": 1,
        "p0_media": 2,
        "p0_receivers": 2,
        "p0_h264": 1,
        "p0_pcma": 1,
        "p0_recv_kb": 32,
        "p1_active": 1,
        "p1_media": 2,
        "p1_receivers": 1,
        "p1_h264": 1,
        "p1_opus": 1,
        "p1_recv_kb": 8,
        "consumer_senders": 2,
    }
    text = repr(summary)
    assert "test-user" not in text
    assert "test-password" not in text
    assert "192.0.2.10" not in text
    assert "rtsp://" not in text


def test_go2rtc_state_json_log_preserves_media_but_redacts_secrets():
    raw = {
        "producers": [
            {
                "id": 7,
                "format_name": "rtsp",
                "protocol": "tcp",
                "url": "rtsp://test-user:test-password@192.0.2.10/example",
                "remote_addr": "192.0.2.10:554",
                "sdp": "v=0\\r\\nm=video 0 RTP/AVP 96",
                "debug": "rtsp://test-user:test-password@192.0.2.10/example",
                "medias": [
                    "video, recvonly, H264",
                    "audio, recvonly, PCMA/8000",
                ],
                "receivers": [
                    {
                        "id": 11,
                        "codec": {
                            "codec_name": "h264",
                            "codec_type": "video",
                            "profile": "High",
                            "level": 41,
                        },
                        "bytes": 12345,
                        "packets": 123,
                    }
                ],
            }
        ],
        "consumers": [
            {
                "id": 22,
                "format_name": "mp4",
                "protocol": "ws",
                "remote_addr": "192.0.2.20:12345",
                "senders": [
                    {
                        "id": 23,
                        "codec": {"codec_name": "h264", "codec_type": "video"},
                        "bytes": 4096,
                        "packets": 40,
                        "drops": 1,
                    }
                ],
            }
        ],
    }

    line = diagnostics_mod.format_go2rtc_state_json_line(
        "camera.driveway",
        "stream_state_250ms",
        elapsed_ms=333,
        state=raw,
    )

    assert "format_name" in line
    assert "rtsp" in line
    assert "H264" in line
    assert "PCMA/8000" in line
    assert "receivers" in line
    assert "senders" in line
    assert "12345" in line
    assert "<redacted>" in line
    assert '"url"' not in line
    assert '"remote_addr"' not in line
    assert '"sdp"' not in line
    assert "test-user" not in line
    assert "test-password" not in line
    assert "192.0.2.10" not in line
    assert "192.0.2.20" not in line
    assert "rtsp://" not in line
    assert "v=0" not in line


def test_go2rtc_state_log_schema_rejects_unknown_counters():
    line = diagnostics_mod.format_go2rtc_state_line(
        "camera.driveway",
        "stream_state_250ms",
        elapsed_ms=310,
        counters={
            "inspect_ok": 1,
            "producer_count": 2,
            "consumer_count": 1,
            "p0_active": 1,
        },
    )
    assert line.startswith(
        "COMELIT_MINIAPP_DIAG_GO2RTC entity=camera.driveway "
        "event=stream_state_250ms elapsed_ms=310"
    )
    with pytest.raises(diagnostics_mod.MiniAppDiagnosticsError):
        diagnostics_mod.format_go2rtc_state_line(
            "camera.driveway",
            "stream_state_250ms",
            elapsed_ms=310,
            counters={"url": 1},
        )


def test_go2rtc_ws_log_preserves_error_and_redacts_network_material():
    line = diagnostics_mod.format_go2rtc_ws_line(
        "camera.driveway",
        elapsed_ms=777,
        frame_type="error",
        value=(
            "mse: streams: dial rtsp://user:pass@192.0.2.10/live failed; "
            "connect 192.0.2.10:554"
        ),
    )
    assert "type=error" in line
    assert "mse: streams: dial" in line
    assert "failed" in line
    assert "rtsp://" not in line
    assert "user:pass" not in line
    assert "192.0.2.10" not in line
    assert "<url_redacted>" in line


def test_go2rtc_ws_parser_keeps_error_type_and_value():
    assert views_mod._parse_go2rtc_upstream_text(
        '{"type":"error","value":"mse: streams: codecs not matched"}'
    ) == ("error", "mse: streams: codecs not matched")
    assert views_mod._parse_go2rtc_upstream_text("not-json") == (
        "non_json",
        "not-json",
    )


def test_mse_protocol_accepts_only_closed_codec_command():
    validate = views_mod._validate_mse_command

    assert validate('{"type":"mse","value":"avc1.640029,mp4a.40.2"}') == "avc1.640029,mp4a.40.2"

    for unsafe in (
        '{"type":"webrtc","value":"h264"}',
        '{"type":"mse","value":"h264,delete"}',
        '{"type":"mse","value":"h264,h265,hevc,av1,vp8,vp9,aac,mp4a,opus"}',
        '{"type":"mse","value":"rtsp://test-user:test-password@192.0.2.10/example"}',
        '{"type":"mse","value":"avc1.640029","extra":1}',
        "x" * 300,
    ):
        assert validate(unsafe) is None


def test_mse_upstream_text_sanitizer_never_relays_free_text_or_urls():
    sanitize = views_mod._sanitize_mse_upstream_text

    assert sanitize('{"type":"mse","value":"video/mp4; codecs=\\"avc1\\""}') == {
        "type": "mse",
        "value": 'video/mp4; codecs="avc1"',
    }

    for unsafe in (
        '{"type":"log","value":"rtsp://test-user:test-password@192.0.2.10/example"}',
        '{"type":"error","value":"go2rtc said http://127.0.0.1:11984"}',
        '{"type":"mse","value":"rtsp://test-user:test-password@192.0.2.10/example"}',
    ):
        assert sanitize(unsafe) is None


def test_mse_view_happy_path_relays_text_binary_and_releases(monkeypatch):
    controller, hass = _controller(surveillance_label="Outside")
    token, _session = controller.sessions.create(424242, 12345678)
    source = "rtsp://192.0.2.10/example"
    hass.cameras["camera.driveway"] = FakeCamera(set(), source)
    upstream = _FakeUpstreamWebSocket(
        [
            _FakeWSMessage(
                views_mod.WSMsgType.TEXT,
                '{"type":"mse","value":"video/mp4; codecs=\\"avc1.42E01E\\""}',
            ),
            _FakeWSMessage(views_mod.WSMsgType.TEXT, '{"type":"log","value":"no"}'),
            _FakeWSMessage(views_mod.WSMsgType.BINARY, b"\x00\x01fmp4"),
        ]
    )
    go2rtc = _FakeGo2RTCWithUpstream(upstream)
    controller.go2rtc = go2rtc
    view = views_mod.MiniAppCameraMSEView(controller)

    async def run():
        with _MSEWebSocketPatch(
            monkeypatch,
            _FakeWSMessage(views_mod.WSMsgType.TEXT, '{"type":"mse","value":"avc1.640029,mp4a.40.2"}'),
            [
                ("sleep", 0.01),
                _FakeWSMessage(views_mod.WSMsgType.TEXT, '{"type":"close"}'),
            ],
        ) as capture:
            websocket = await view.get(_mse_request(controller, token), "camera.driveway")
            assert websocket is capture.instances[0]

    asyncio.run(run())

    websocket = _CaptureWebSocket.instances[0]
    internal_name = controller.mse_internal_stream_name("camera.driveway")
    assert go2rtc.registers == [(internal_name, [source + "#backchannel=0"])]
    assert go2rtc.opened == [controller.mse_internal_stream_name("camera.driveway")]
    assert upstream.sent_json == [{"type": "mse", "value": "avc1.640029,mp4a.40.2"}]
    assert _json_texts(websocket) == [
        {"type": "mse", "value": 'video/mp4; codecs="avc1.42E01E"'}
    ]
    assert websocket.binaries == [b"\x00\x01fmp4"]
    assert upstream.close_count == 1
    assert go2rtc.unregisters == [controller.mse_internal_stream_name("camera.driveway")]


def test_mse_view_expired_session_rejects_without_acquiring(monkeypatch):
    controller, hass = _controller(surveillance_label="Outside")
    token, _session = controller.sessions.create(
        424242,
        12345678,
        now=int(time.time()) - session_mod.SESSION_TTL_SECONDS - 10,
    )
    hass.cameras["camera.driveway"] = FakeCamera(set(), "rtsp://192.0.2.10/example")
    go2rtc = _FakeGo2RTCWithUpstream()
    controller.go2rtc = go2rtc
    view = views_mod.MiniAppCameraMSEView(controller)

    with pytest.raises(Exception) as exc:
        with _MSEWebSocketPatch(
            monkeypatch,
            _FakeWSMessage(views_mod.WSMsgType.TEXT, '{"type":"mse","value":"avc1.640029"}'),
        ):
            asyncio.run(view.get(_mse_request(controller, token), "camera.driveway"))

    assert exc.value.status == 403
    assert go2rtc.registers == []
    assert _CaptureWebSocket.instances == []


def test_mse_view_session_expiry_midstream_releases_lease(monkeypatch):
    controller, hass = _controller(surveillance_label="Outside")
    token, session = controller.sessions.create(424242, 12345678)
    session.expires_at = int(time.time()) + 1
    hass.cameras["camera.driveway"] = FakeCamera(set(), "rtsp://192.0.2.10/example")
    upstream = _FakeUpstreamWebSocket([("sleep", 2)])
    go2rtc = _FakeGo2RTCWithUpstream(upstream)
    controller.go2rtc = go2rtc
    view = views_mod.MiniAppCameraMSEView(controller)

    async def run():
        with _MSEWebSocketPatch(
            monkeypatch,
            _FakeWSMessage(views_mod.WSMsgType.TEXT, '{"type":"mse","value":"avc1.640029"}'),
            ["wait_forever"],
        ):
            await view.get(_mse_request(controller, token), "camera.driveway")

    asyncio.run(run())

    websocket = _CaptureWebSocket.instances[0]
    assert _json_texts(websocket)[-1] == {"type": "error", "code": "mse_ws_closed"}
    assert websocket.closed
    assert upstream.close_count == 1
    assert go2rtc.unregisters == [controller.mse_internal_stream_name("camera.driveway")]


def test_mse_view_upstream_close_releases_and_reports_bounded_error(monkeypatch):
    controller, hass = _controller(surveillance_label="Outside")
    token, _session = controller.sessions.create(424242, 12345678)
    hass.cameras["camera.driveway"] = FakeCamera(set(), "rtsp://192.0.2.10/example")
    upstream = _FakeUpstreamWebSocket([
        _FakeWSMessage(views_mod.WSMsgType.CLOSED),
    ])
    go2rtc = _FakeGo2RTCWithUpstream(upstream)
    controller.go2rtc = go2rtc
    view = views_mod.MiniAppCameraMSEView(controller)

    async def run():
        with _MSEWebSocketPatch(
            monkeypatch,
            _FakeWSMessage(views_mod.WSMsgType.TEXT, '{"type":"mse","value":"avc1.640029"}'),
            ["wait_forever"],
        ):
            await view.get(_mse_request(controller, token), "camera.driveway")

    asyncio.run(run())

    websocket = _CaptureWebSocket.instances[0]
    assert _json_texts(websocket) == [{"type": "error", "code": "mse_ws_closed"}]
    assert websocket.closed is True
    assert go2rtc.unregisters == [controller.mse_internal_stream_name("camera.driveway")]


def test_mse_view_client_disconnect_without_close_frame_cleans_up(monkeypatch):
    controller, hass = _controller(surveillance_label="Outside")
    token, _session = controller.sessions.create(424242, 12345678)
    hass.cameras["camera.driveway"] = FakeCamera(set(), "rtsp://192.0.2.10/example")
    upstream = _FakeUpstreamWebSocket([("sleep", 1)])
    go2rtc = _FakeGo2RTCWithUpstream(upstream)
    controller.go2rtc = go2rtc
    view = views_mod.MiniAppCameraMSEView(controller)

    async def run():
        with _MSEWebSocketPatch(
            monkeypatch,
            _FakeWSMessage(views_mod.WSMsgType.TEXT, '{"type":"mse","value":"avc1.640029"}'),
            [],
        ):
            await view.get(_mse_request(controller, token), "camera.driveway")

    asyncio.run(run())

    assert upstream.close_count == 1
    assert go2rtc.unregisters == [controller.mse_internal_stream_name("camera.driveway")]


def test_mse_view_rejects_missing_and_unsupported_stream_source_without_leak(monkeypatch):
    controller, hass = _controller(surveillance_label="Outside")
    token, _session = controller.sessions.create(424242, 12345678)
    go2rtc = _FakeGo2RTCWithUpstream()
    controller.go2rtc = go2rtc
    view = views_mod.MiniAppCameraMSEView(controller)

    for source in (None, "ffmpeg:camera.driveway"):
        hass.cameras["camera.driveway"] = FakeCamera(set(), source)
        with _MSEWebSocketPatch(
            monkeypatch,
            _FakeWSMessage(views_mod.WSMsgType.TEXT, '{"type":"mse","value":"avc1.640029"}'),
        ):
            asyncio.run(view.get(_mse_request(controller, token), "camera.driveway"))
        assert _json_texts(_CaptureWebSocket.instances[-1]) == [
            {"type": "error", "code": "stream_source_unavailable"}
        ]

    assert go2rtc.registers == []
    assert go2rtc.opened == []
    assert go2rtc.unregisters == []


def test_go2rtc_adapter_uses_home_assistant_runtime_session(monkeypatch):
    controller, hass = _controller(surveillance_label="Outside")
    calls: list[tuple[str, str]] = []

    class _Response:
        status = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def json(self):
            return {"version": "1.9.14"}

    class _RuntimeSession:
        def get(self, url, **kwargs):
            calls.append(("get", url))
            return _Response()

        def put(self, url, **kwargs):
            calls.append(("put", url))
            return _Response()

        def delete(self, url, **kwargs):
            calls.append(("delete", url))
            return _Response()

        async def ws_connect(self, url, **kwargs):
            calls.append(("ws_connect", url))
            return object()

    runtime_session = _RuntimeSession()
    hass.data["go2rtc"] = types.SimpleNamespace(
        url="http://localhost:11984/",
        session=runtime_session,
    )

    def unexpected_default_session(_hass):
        raise AssertionError("HA-managed go2rtc must reuse Go2RtcConfig.session")

    monkeypatch.setattr(
        go2rtc_mod,
        "async_get_clientsession",
        unexpected_default_session,
    )
    adapter = go2rtc_mod.MiniAppGo2RTCAdapter(hass)

    async def run():
        await adapter.register_stream(
            "opaque-stream",
            ["rtsp://test-user:test-password@192.0.2.10/example"],
        )
        upstream = await adapter.open_mse_ws("opaque-stream")
        await adapter.unregister_stream("opaque-stream")
        return upstream

    upstream = asyncio.run(run())

    assert upstream is not None
    assert [method for method, _url in calls] == [
        "put",
        "ws_connect",
        "delete",
    ]
    assert all(url.startswith("http://localhost:11984/") for _method, url in calls)

    calls.clear()
    asyncio.run(
        adapter.register_stream(
            "opaque-stream",
            [
                "ffmpeg:rtsp://192.0.2.10/example",
                "ffmpeg:opaque-stream#audio=opus#query=log_level=debug",
            ],
        )
    )
    put_url = calls[0][1]
    assert put_url.count("src=") == 2
    assert "name=opaque-stream" in put_url


def test_go2rtc_unavailable_and_operation_errors_are_bounded(monkeypatch):
    controller, hass = _controller(surveillance_label="Outside")
    adapter = go2rtc_mod.MiniAppGo2RTCAdapter(hass)

    async def unavailable():
        with pytest.raises(go2rtc_mod.MiniAppGo2RTCError) as exc:
            await adapter.register_stream(
                "internal",
                ["rtsp://test-user:test-password@192.0.2.10/example"],
            )
        assert exc.value.code == "go2rtc_unavailable"
        assert str(exc.value) == "go2rtc_unavailable"

    asyncio.run(unavailable())

    class _FailingResponse:
        status = 503

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class _FakeClient:
        def get(self, *args, **kwargs):
            raise AssertionError("hot path must not perform a separate /api probe")

        def put(self, *args, **kwargs):
            return _FailingResponse()

    hass.data["go2rtc"] = "http://127.0.0.1:1984"
    monkeypatch.setattr(go2rtc_mod, "async_get_clientsession", lambda hass: _FakeClient())

    async def operation_error():
        with pytest.raises(go2rtc_mod.MiniAppGo2RTCError) as exc:
            await adapter.register_stream(
                "internal",
                ["rtsp://test-user:test-password@192.0.2.10/example"],
            )
        assert exc.value.code == "go2rtc_http_error"
        message = str(exc.value)
        assert message == "go2rtc_http_error"
        assert "test-user" not in message
        assert "test-password" not in message
        assert "192.0.2.10" not in message

    asyncio.run(operation_error())


def test_mse_view_protocol_rejects_bad_commands_and_filters_upstream_text(
    monkeypatch,
    caplog,
):
    controller, hass = _controller(surveillance_label="Outside")
    token, _session = controller.sessions.create(424242, 12345678)
    hass.cameras["camera.driveway"] = FakeCamera(set(), "rtsp://192.0.2.10/example")
    view = views_mod.MiniAppCameraMSEView(controller)

    bad_first_frames = [
        _FakeWSMessage(views_mod.WSMsgType.TEXT, '{"type":"webrtc","value":"h264"}'),
        _FakeWSMessage(views_mod.WSMsgType.TEXT, '{"type":"streams","value":"h264"}'),
        _FakeWSMessage(views_mod.WSMsgType.TEXT, '{"type":"add","value":"h264"}'),
        _FakeWSMessage(views_mod.WSMsgType.TEXT, "x" * (views_mod.MSE_MAX_COMMAND_BYTES + 1)),
        _FakeWSMessage(views_mod.WSMsgType.TEXT, "{not json"),
        _FakeWSMessage(views_mod.WSMsgType.BINARY, b"\x00"),
    ]
    for first in bad_first_frames:
        go2rtc = _FakeGo2RTCWithUpstream()
        controller.go2rtc = go2rtc
        with _MSEWebSocketPatch(monkeypatch, first):
            asyncio.run(view.get(_mse_request(controller, token), "camera.driveway"))
        assert _json_texts(_CaptureWebSocket.instances[-1]) == [
            {"type": "error", "code": "invalid_mse_command"}
        ]
        assert go2rtc.registers == []

    upstream = _FakeUpstreamWebSocket(
        [
            _FakeWSMessage(
                views_mod.WSMsgType.TEXT,
                '{"type":"error","value":"mse: streams: codecs not matched"}',
            ),
            _FakeWSMessage(views_mod.WSMsgType.TEXT, '{"type":"log","value":"secret"}'),
            _FakeWSMessage(views_mod.WSMsgType.TEXT, '{"type":"mse","value":"rtsp://secret"}'),
        ]
    )
    controller.go2rtc = _FakeGo2RTCWithUpstream(upstream)
    with caplog.at_level(
        logging.INFO,
        logger="custom_components.comelit.miniapp.views",
    ):
        with _MSEWebSocketPatch(
            monkeypatch,
            _FakeWSMessage(
                views_mod.WSMsgType.TEXT,
                '{"type":"mse","value":"avc1.640029"}',
            ),
            [
                ("sleep", 0.01),
                _FakeWSMessage(views_mod.WSMsgType.TEXT, '{"type":"close"}'),
            ],
        ):
            asyncio.run(view.get(_mse_request(controller, token), "camera.driveway"))
    assert _json_texts(_CaptureWebSocket.instances[-1]) == []
    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert "COMELIT_MINIAPP_DIAG_GO2RTC_WS" in logged
    assert "type=error" in logged
    assert "codecs not matched" in logged


def test_mse_lease_name_has_no_secrets_or_entity_and_is_stable():
    controller, hass = _controller(surveillance_label="Outside")
    fake_go2rtc = FakeGo2RTC()
    controller.go2rtc = fake_go2rtc
    source = "rtsp://test-user:test-password@192.0.2.10/example"
    hass.cameras["camera.driveway"] = FakeCamera(set(), source)

    async def run():
        first = await controller.acquire_mse_stream("camera.driveway")
        await controller.release_mse_stream("camera.driveway")
        second = await controller.acquire_mse_stream("camera.driveway")
        await controller.release_mse_stream("camera.driveway")
        return first.internal_name, second.internal_name

    first_name, second_name = asyncio.run(run())

    assert first_name == second_name
    assert "camera.driveway" not in first_name
    assert "driveway" not in first_name
    assert "test-user" not in first_name
    assert "test-password" not in first_name
    expected_source = source + "#backchannel=0"
    assert fake_go2rtc.registers == [
        (first_name, [expected_source]),
        (second_name, [expected_source]),
    ]


def _assert_no_fixture_secret(values):
    text = "\n".join(str(value) for value in values)
    forbidden = [
        "test-user",
        "test-password",
        "rtsp://test-user:test-password@192.0.2.10/example",
    ]
    leaked = [secret for secret in forbidden if secret in text]
    assert not leaked, leaked


def test_fixture_camera_secret_never_reaches_payloads_logs_or_serializer(monkeypatch, caplog):
    fixture_url = "rtsp://test-user:test-password@192.0.2.10/example"
    controller, hass = _controller(surveillance_label="Outside")
    token, _session = controller.sessions.create(424242, 12345678)
    hass.cameras["camera.driveway"] = FakeCamera(set(), fixture_url)
    upstream = _FakeUpstreamWebSocket(
        [
            _FakeWSMessage(
                views_mod.WSMsgType.TEXT,
                '{"type":"mse","value":"video/mp4; codecs=\\"avc1.42E01E\\""}',
            ),
            _FakeWSMessage(views_mod.WSMsgType.TEXT, '{"type":"log","value":"' + fixture_url + '"}'),
        ]
    )
    go2rtc = _FakeGo2RTCWithUpstream(upstream)
    controller.go2rtc = go2rtc
    mse_view = views_mod.MiniAppCameraMSEView(controller)
    diagnostics_view = views_mod.MiniAppCameraDiagnosticsView(controller)
    serializer_values: list[object] = []
    websocket_texts: list[str] = []
    original_loads_limited = views_mod.loads_limited

    def capture_serializer(body):
        serializer_values.append(body)
        payload = original_loads_limited(body)
        serializer_values.append(payload)
        return payload

    monkeypatch.setattr(views_mod, "loads_limited", capture_serializer)

    async def run():
        with _MSEWebSocketPatch(
            monkeypatch,
            _FakeWSMessage(views_mod.WSMsgType.TEXT, '{"type":"mse","value":"avc1.640029"}'),
            [("sleep", 0.01), _FakeWSMessage(views_mod.WSMsgType.TEXT, '{"type":"close"}')],
        ):
            await mse_view.get(_mse_request(controller, token), "camera.driveway")
            websocket_texts.extend(_CaptureWebSocket.instances[0].texts)
        class _FailOpenGo2RTC(_FakeGo2RTCWithUpstream):
            async def open_mse_ws(self, internal_name: str):
                self.opened.append(internal_name)
                raise go2rtc_mod.MiniAppGo2RTCError("go2rtc_ws_error")

        failing_go2rtc = _FailOpenGo2RTC()
        controller.go2rtc = failing_go2rtc
        with _MSEWebSocketPatch(
            monkeypatch,
            _FakeWSMessage(views_mod.WSMsgType.TEXT, '{"type":"mse","value":"avc1.640029"}'),
        ):
            await mse_view.get(_mse_request(controller, token), "camera.driveway")
            websocket_texts.extend(_CaptureWebSocket.instances[0].texts)
        invalid_response = await diagnostics_view.post(
            _FakeRequest({"event": "rtp", "state": "invalid_state"}, token=token),
            "camera.driveway",
        )
        with caplog.at_level(logging.INFO, logger="custom_components.comelit.miniapp.views"):
            ok_response = await diagnostics_view.post(
                _FakeRequest(
                    {
                        "event": "mse_fallback",
                        "reason": "mse_ws_error",
                        "counters": {"bytes": 7},
                    },
                    token=token,
                ),
                "camera.driveway",
            )
        return invalid_response, ok_response

    invalid_response, ok_response = asyncio.run(run())

    internal_name = controller.mse_internal_stream_name("camera.driveway")
    expected_source = fixture_url + "#backchannel=0"
    assert go2rtc.registers == [(internal_name, [expected_source])]
    assert expected_source == go2rtc.registers[0][1][0]
    compared = [
        invalid_response.text,
        ok_response.text,
        *websocket_texts,
        diagnostics_mod.format_log_line(
            "camera.driveway",
            {"event": "mse_fallback", "reason": "mse_ws_error", "counters": {"bytes": 7}},
        ),
        *[record.getMessage() for record in caplog.records],
        *serializer_values,
    ]
    assert json.loads(invalid_response.text) == {"error": "invalid_diagnostics_event"}
    assert json.loads(ok_response.text) == {"ok": True}
    _assert_no_fixture_secret(compared)
    with pytest.raises(AssertionError):
        _assert_no_fixture_secret([*compared, "deliberate leak " + fixture_url])


def test_webcodecs_framing_round_trip_and_malformed_rejection():
    frame = webcodecs_mod.WebCodecsFrame(
        sequence=1,
        media_pts_us=123456,
        pts_valid=True,
        keyframe=True,
        payload=b"\x00\x00\x00\x01\x65idr",
        source_elapsed_us=12000,
        send_elapsed_us=12500,
    )
    encoded = webcodecs_mod.encode_webcodecs_frame(frame)
    assert len(encoded) == webcodecs_mod.WEBCODECS_HEADER_BYTES + len(frame.payload)
    assert encoded[:4] == b"\x02\x05\x00\x00"
    decoded = webcodecs_mod.decode_webcodecs_frame(encoded)
    assert decoded == frame

    second = webcodecs_mod.decode_webcodecs_frame(
        webcodecs_mod.encode_webcodecs_frame(
            webcodecs_mod.WebCodecsFrame(
                sequence=2,
                media_pts_us=0,
                pts_valid=False,
                keyframe=False,
                payload=b"\x00\x00\x00\x01\x41p",
            )
        )
    )
    assert second.sequence == decoded.sequence + 1

    malformed = [
        b"\x01" + encoded[1:],
        encoded[:2] + b"\x00\x01" + encoded[4:],
        b"\x02\x03" + encoded[2:],
        encoded[:-1],
        encoded[:32] + (webcodecs_mod.WEBCODECS_MAX_UNIT_BYTES + 1).to_bytes(4, "big"),
    ]
    for payload in malformed:
        with pytest.raises(webcodecs_mod.WebCodecsProtocolError):
            webcodecs_mod.decode_webcodecs_frame(payload)


def test_webcodecs_annexb_avcc_extradata_sps_pps_and_codec_derivation():
    sps = b"\x67\x64\x00\x29\xac"
    pps = b"\x68\xee\x3c"
    idr = b"\x65\x88\x84"
    annexb = b"\x00\x00\x00\x01" + idr
    avcc = len(idr).to_bytes(4, "big") + idr
    extradata = (
        b"\x01\x64\x00\x29\xff\xe1"
        + len(sps).to_bytes(2, "big")
        + sps
        + b"\x01"
        + len(pps).to_bytes(2, "big")
        + pps
    )

    assert webcodecs_mod.annexb_normalize(annexb) == annexb
    assert webcodecs_mod.annexb_normalize(avcc) == annexb
    parsed_sps, parsed_pps = webcodecs_mod.avcc_extradata_to_annexb_nals(extradata)
    assert parsed_sps == [sps]
    assert parsed_pps == [pps]
    injected = webcodecs_mod.prepend_parameter_sets(annexb, parsed_sps, parsed_pps)
    assert injected == (
        b"\x00\x00\x00\x01" + sps
        + b"\x00\x00\x00\x01" + pps
        + annexb
    )
    assert webcodecs_mod.derive_avc1_codec_from_sps(sps) == "avc1.640029"


def test_webcodecs_endpoint_requires_session_before_upgrade(monkeypatch):
    controller, _hass = _controller(surveillance_label="Outside")
    view = views_mod.MiniAppCameraWebCodecsView(controller)

    with pytest.raises(Exception) as exc:
        with _MSEWebSocketPatch(
            monkeypatch,
            _FakeWSMessage(views_mod.WSMsgType.TEXT, '{"type":"webcodecs","value":"h264"}'),
        ):
            asyncio.run(view.get(_mse_request(controller, ""), "camera.driveway"))

    assert exc.value.status == 403
    assert _CaptureWebSocket.instances == []


def test_webcodecs_endpoint_rejects_camera_guard_errors_as_closed_json():
    controller, hass = _controller(surveillance_label="Outside")
    token, _session = controller.sessions.create(424242, 12345678)
    view = views_mod.MiniAppCameraWebCodecsView(controller)

    response = asyncio.run(view.get(_mse_request(controller, token), "camera.unlisted"))
    assert response.status == 409
    assert json.loads(response.text) == {"error": "camera_not_allowed"}

    entrance = controller.get_webcodecs_camera_target("camera.comelit_entrance")
    assert entrance.kind == "entrance"
    assert entrance.camera is None

    hass.entity_registry.entities["camera.comelit_gate"] = FakeRegistryEntry(
        "camera.comelit_gate",
        "comelit",
        "comelit_gate_camera",
        labels={"outside"},
    )
    hass.states._values["camera.comelit_gate"] = FakeState("idle")
    hass.cameras["camera.comelit_gate"] = FakeCamera(set(), "rtsp://example/live")
    response = asyncio.run(
        view.get(_mse_request(controller, token), "camera.comelit_gate")
    )
    assert json.loads(response.text) == {"error": "intercom_camera_not_allowed"}

    hass.states._values["camera.driveway"] = FakeState("unavailable")
    response = asyncio.run(view.get(_mse_request(controller, token), "camera.driveway"))
    assert json.loads(response.text) == {"error": "camera_unavailable"}


def test_webcodecs_invalid_or_missing_start_command_does_not_open_camera(monkeypatch):
    controller, hass = _controller(surveillance_label="Outside")
    token, _session = controller.sessions.create(424242, 12345678)
    source = "rtsp://" + "alpha" + ":" + "bravo" + "@example.invalid/live"
    camera = FakeCamera(set(), source)
    hass.cameras["camera.driveway"] = camera
    view = views_mod.MiniAppCameraWebCodecsView(controller)

    for first in (
        _FakeWSMessage(views_mod.WSMsgType.TEXT, '{"type":"mse","value":"h264"}'),
        _FakeWSMessage(views_mod.WSMsgType.TEXT, '{"type":"webcodecs","value":"vp8"}'),
        _FakeWSMessage(views_mod.WSMsgType.BINARY, b"\x00"),
    ):
        with _MSEWebSocketPatch(monkeypatch, first):
            asyncio.run(view.get(_mse_request(controller, token), "camera.driveway"))
        assert _json_texts(_CaptureWebSocket.instances[-1]) == [
            {"type": "error", "code": "invalid_webcodecs_command"}
        ]
    assert camera.stream_source_calls == 0


async def _single_webcodecs_unit(_source):
    yield webcodecs_mod.H264AccessUnit(
        payload=(
            b"\x00\x00\x00\x01\x67\x64\x00\x29"
            b"\x00\x00\x00\x01\x68\xee\x3c"
            b"\x00\x00\x00\x01\x65\x88"
        ),
        keyframe=True,
        media_pts_us=33333,
        codec="avc1.640029",
    )


class _AsyncUnitSource:
    def __init__(self, units):
        self.units = list(units)
        self.closed = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self.units:
            raise StopAsyncIteration
        return self.units.pop(0)

    async def aclose(self):
        self.closed = True


async def _single_webcodecs_source(_source):
    return _AsyncUnitSource([unit async for unit in _single_webcodecs_unit(_source)])


class _FakeWebCodecsMediaTransport:
    def __init__(self):
        self.active = False
        self.local_sdp_ready = False
        self.local_sdp_path = Path("/run/comelit-media/local-rtp.sdp")


class _FakeWebCodecsMediaManager:
    def __init__(self, transport):
        self.transport = transport
        self.phase = "inactive"
        self.active = False
        self.acquire_calls = []
        self.release_calls = []
        self.leases = {}
        self.start_count = 0

    def status(self):
        return {
            "phase": self.phase,
            "active": self.active,
            "leases": dict(self.leases),
        }

    async def async_acquire(self, *, panel, reason):
        self.acquire_calls.append((panel, reason))
        if self.phase != "active":
            self.start_count += 1
        self.leases[reason] = self.leases.get(reason, 0) + 1
        self.phase = "active"
        self.active = True
        self.transport.active = True
        self.transport.local_sdp_ready = True
        return self.status()

    async def async_release(self, *, reason):
        self.release_calls.append(reason)
        count = self.leases.get(reason, 0)
        if count <= 1:
            self.leases.pop(reason, None)
        else:
            self.leases[reason] = count - 1
        if not self.leases:
            self.phase = "inactive"
            self.active = False
            self.transport.active = False
            self.transport.local_sdp_ready = False
        return self.status()


def _install_webcodecs_entrance_runtime(hass):
    transport = _FakeWebCodecsMediaTransport()
    manager = _FakeWebCodecsMediaManager(transport)
    domain_data = hass.data.setdefault(controller_mod.DOMAIN, {})
    domain_data.setdefault(controller_mod.DATA_MEDIA_SESSIONS, {})["entry-1"] = manager
    domain_data.setdefault(controller_mod.DATA_MEDIA_TRANSPORTS, {})["entry-1"] = transport
    return manager, transport


def test_webcodecs_entrance_invalid_command_never_acquires_media(monkeypatch):
    controller, hass = _controller(surveillance_label="Outside")
    manager, _transport = _install_webcodecs_entrance_runtime(hass)
    token, _session = controller.sessions.create(424242, 12345678)
    view = views_mod.MiniAppCameraWebCodecsView(controller)

    with _MSEWebSocketPatch(
        monkeypatch,
        _FakeWSMessage(views_mod.WSMsgType.TEXT, '{"type":"webcodecs","value":"vp8"}'),
    ):
        asyncio.run(
            view.get(_mse_request(controller, token), "camera.comelit_entrance")
        )

    assert manager.acquire_calls == []
    assert _json_texts(_CaptureWebSocket.instances[-1]) == [
        {"type": "error", "code": "invalid_webcodecs_command"}
    ]


def test_webcodecs_entrance_live_path_uses_manager_local_sdp_and_releases(monkeypatch):
    controller, hass = _controller(surveillance_label="Outside")
    manager, transport = _install_webcodecs_entrance_runtime(hass)
    token, _session = controller.sessions.create(424242, 12345678)
    opened_sources = []

    async def open_sdp(source):
        opened_sources.append(source)
        return _AsyncUnitSource(
            [unit async for unit in _single_webcodecs_unit(source)]
        )

    monkeypatch.setattr(
        views_mod.webcodecs_mod,
        "open_h264_sdp_access_unit_source",
        open_sdp,
    )
    view = views_mod.MiniAppCameraWebCodecsView(controller)

    with _MSEWebSocketPatch(
        monkeypatch,
        _FakeWSMessage(views_mod.WSMsgType.TEXT, '{"type":"webcodecs","value":"h264"}'),
        messages=("wait_forever",),
    ):
        asyncio.run(
            view.get(_mse_request(controller, token), "camera.comelit_entrance")
        )

    websocket = _CaptureWebSocket.instances[-1]
    texts = _json_texts(websocket)
    assert texts[0]["type"] == "intercom_media_ready"
    assert isinstance(texts[0]["server_elapsed_ms"], int)
    assert texts[1]["type"] == "source_open"
    assert texts[2]["type"] == "source_packet"
    hello = texts[3]
    assert hello["type"] == "hello"
    assert hello["protocol"] == 2
    assert hello["entity_id"] == "camera.comelit_entrance"
    assert hello["source_kind"] == "comelit_entrance_rtp"
    assert hello["zero_transcode"] is True
    assert hello["comelit_entrance_open"] is True
    assert hello["comelit_media_started"] is True
    assert texts[-1] == {"type": "eos", "reason": "source_eof"}
    assert opened_sources == [str(transport.local_sdp_path)]
    assert manager.acquire_calls == [("entrance", "miniapp_webcodecs")]
    assert manager.release_calls == ["miniapp_webcodecs"]
    assert manager.phase == "inactive"
    assert manager.active is False
    assert transport.active is False


def test_webcodecs_entrance_park_holds_transport_and_reuses_without_restart():
    controller, hass = _controller(surveillance_label="Outside")
    manager, transport = _install_webcodecs_entrance_runtime(hass)

    async def run():
        first = await controller.acquire_webcodecs_entrance(
            controller.get_webcodecs_camera_target("camera.comelit_entrance")
        )
        assert manager.start_count == 1
        assert manager.leases == {"miniapp_webcodecs": 1}

        parked = await controller.async_park_webcodecs_entrance()
        assert parked == {"parked": True, "timeout_seconds": 60}
        assert manager.leases == {
            "miniapp_webcodecs": 1,
            "miniapp_webcodecs_park": 1,
        }

        await first.release()
        assert manager.phase == "active"
        assert manager.active is True
        assert transport.active is True
        assert manager.leases == {"miniapp_webcodecs_park": 1}

        second = await controller.acquire_webcodecs_entrance(
            controller.get_webcodecs_camera_target("camera.comelit_entrance")
        )
        assert manager.start_count == 1
        assert manager.phase == "active"
        assert manager.leases == {"miniapp_webcodecs": 1}
        assert "miniapp_webcodecs_park" in manager.release_calls

        await second.release()
        assert manager.phase == "inactive"
        assert manager.active is False
        assert transport.active is False

    asyncio.run(run())


def test_webcodecs_entrance_park_expires_after_60_seconds(monkeypatch):
    controller, hass = _controller(surveillance_label="Outside")
    manager, transport = _install_webcodecs_entrance_runtime(hass)
    monkeypatch.setattr(controller_mod, "_WEBCODECS_ENTRANCE_PARK_SECONDS", 0.0)

    async def run():
        lease = await controller.acquire_webcodecs_entrance(
            controller.get_webcodecs_camera_target("camera.comelit_entrance")
        )
        parked = await controller.async_park_webcodecs_entrance()
        assert parked == {"parked": True, "timeout_seconds": 0}
        await lease.release()
        assert manager.phase == "active"
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert manager.phase == "inactive"
        assert manager.active is False
        assert transport.active is False
        assert "miniapp_webcodecs_park" in manager.release_calls

    asyncio.run(run())


def test_webcodecs_entrance_client_close_releases_manager_immediately(monkeypatch):
    controller, hass = _controller(surveillance_label="Outside")
    manager, _transport = _install_webcodecs_entrance_runtime(hass)
    token, _session = controller.sessions.create(424242, 12345678)

    async def slow_sdp(_source):
        class _SlowSource(_AsyncUnitSource):
            async def __anext__(self):
                await asyncio.sleep(10)
                raise StopAsyncIteration

        return _SlowSource([])

    monkeypatch.setattr(
        views_mod.webcodecs_mod,
        "open_h264_sdp_access_unit_source",
        slow_sdp,
    )
    view = views_mod.MiniAppCameraWebCodecsView(controller)

    with _MSEWebSocketPatch(
        monkeypatch,
        _FakeWSMessage(views_mod.WSMsgType.TEXT, '{"type":"webcodecs","value":"h264"}'),
        messages=(_FakeWSMessage(views_mod.WSMsgType.CLOSE),),
    ):
        asyncio.run(
            view.get(_mse_request(controller, token), "camera.comelit_entrance")
        )

    assert manager.acquire_calls == [("entrance", "miniapp_webcodecs")]
    assert manager.release_calls == ["miniapp_webcodecs"]
    assert manager.phase == "inactive"
    assert manager.active is False


def test_webcodecs_view_happy_path_secret_free_logs_and_messages(monkeypatch, caplog):
    fixture_url = "rtsp://" + "alpha" + ":" + "bravo" + "@example.invalid/live"
    controller, hass = _controller(surveillance_label="Outside")
    token, _session = controller.sessions.create(424242, 12345678)
    hass.cameras["camera.driveway"] = FakeCamera(set(), fixture_url)
    monkeypatch.setattr(
        views_mod.webcodecs_mod,
        "open_h264_access_unit_source",
        _single_webcodecs_source,
    )
    view = views_mod.MiniAppCameraWebCodecsView(controller)

    with caplog.at_level(logging.INFO, logger="custom_components.comelit.miniapp.views"):
        with _MSEWebSocketPatch(
            monkeypatch,
            _FakeWSMessage(views_mod.WSMsgType.TEXT, '{"type":"webcodecs","value":"h264"}'),
            messages=("wait_forever",),
        ):
            asyncio.run(view.get(_mse_request(controller, token), "camera.driveway"))

    websocket = _CaptureWebSocket.instances[0]
    texts = _json_texts(websocket)
    assert texts[0]["type"] == "source_open"
    assert isinstance(texts[0]["server_elapsed_ms"], int)
    assert texts[1]["type"] == "source_packet"
    assert isinstance(texts[1]["server_elapsed_ms"], int)
    assert texts[2] == {
        "type": "hello",
        "protocol": 2,
        "entity_id": "camera.driveway",
        "codec": "avc1.640029",
        "max_unit_bytes": webcodecs_mod.WEBCODECS_MAX_UNIT_BYTES,
        "session_max_seconds": webcodecs_mod.WEBCODECS_MAX_SESSION_SECONDS,
        "zero_transcode": True,
        "source_kind": "ordinary_rtsp",
        "comelit_entrance_open": False,
        "comelit_media_started": False,
    }
    assert texts[-1] == {"type": "eos", "reason": "source_eof"}
    frame = webcodecs_mod.decode_webcodecs_frame(websocket.binaries[0])
    assert frame.sequence == 1
    assert frame.keyframe is True
    assert frame.pts_valid is True
    assert frame.source_elapsed_us == 0
    assert frame.send_elapsed_us == 0
    compared = [
        *websocket.texts,
        *[record.getMessage() for record in caplog.records],
    ]
    _assert_no_fixture_secret(compared)


def test_webcodecs_non_rtsp_unit_too_large_duration_and_source_failure(monkeypatch):
    controller, hass = _controller(surveillance_label="Outside")
    token, session = controller.sessions.create(424242, 12345678)
    view = views_mod.MiniAppCameraWebCodecsView(controller)

    hass.cameras["camera.driveway"] = FakeCamera(set(), "http://example.invalid/live")
    with _MSEWebSocketPatch(
        monkeypatch,
        _FakeWSMessage(views_mod.WSMsgType.TEXT, '{"type":"webcodecs","value":"h264"}'),
        messages=("wait_forever",),
    ):
        asyncio.run(view.get(_mse_request(controller, token), "camera.driveway"))
    assert _json_texts(_CaptureWebSocket.instances[-1]) == [
        {"type": "error", "code": "source_not_h264_rtsp"}
    ]

    async def too_large(_source):
        return _AsyncUnitSource(
            [
                webcodecs_mod.H264AccessUnit(
                    payload=b"x" * (webcodecs_mod.WEBCODECS_MAX_UNIT_BYTES + 1),
                    keyframe=True,
                    media_pts_us=1,
                    codec="avc1.640029",
                )
            ]
        )

    hass.cameras["camera.driveway"] = FakeCamera(set(), "rtsp://192.0.2.10/live")
    monkeypatch.setattr(
        views_mod.webcodecs_mod,
        "open_h264_access_unit_source",
        too_large,
    )
    with _MSEWebSocketPatch(
        monkeypatch,
        _FakeWSMessage(views_mod.WSMsgType.TEXT, '{"type":"webcodecs","value":"h264"}'),
        messages=("wait_forever",),
    ):
        asyncio.run(view.get(_mse_request(controller, token), "camera.driveway"))
    too_large_texts = _json_texts(_CaptureWebSocket.instances[-1])
    assert too_large_texts[0]["type"] == "source_open"
    assert too_large_texts[1]["type"] == "source_packet"
    assert too_large_texts[-1] == {"type": "error", "code": "unit_too_large"}

    async def failing(_source):
        raise webcodecs_mod.WebCodecsSourceError("source_open_failed")

    monkeypatch.setattr(
        views_mod.webcodecs_mod,
        "open_h264_access_unit_source",
        failing,
    )
    with _MSEWebSocketPatch(
        monkeypatch,
        _FakeWSMessage(views_mod.WSMsgType.TEXT, '{"type":"webcodecs","value":"h264"}'),
        messages=("wait_forever",),
    ):
        asyncio.run(view.get(_mse_request(controller, token), "camera.driveway"))
    assert _json_texts(_CaptureWebSocket.instances[-1]) == [
        {"type": "error", "code": "source_open_failed"}
    ]

    async def slow_after_one(_source):
        class _SlowSource(_AsyncUnitSource):
            async def __anext__(self):
                if self.units:
                    return self.units.pop(0)
                await asyncio.sleep(1)
                raise StopAsyncIteration

        return _SlowSource([unit async for unit in _single_webcodecs_unit(_source)])

    session.expires_at = int(time.time()) + 60
    monkeypatch.setattr(views_mod.webcodecs_mod, "WEBCODECS_MAX_SESSION_SECONDS", 0.01)
    monkeypatch.setattr(
        views_mod.webcodecs_mod,
        "open_h264_access_unit_source",
        slow_after_one,
    )
    with _MSEWebSocketPatch(
        monkeypatch,
        _FakeWSMessage(views_mod.WSMsgType.TEXT, '{"type":"webcodecs","value":"h264"}'),
        messages=("wait_forever",),
    ):
        asyncio.run(view.get(_mse_request(controller, token), "camera.driveway"))
    assert _json_texts(_CaptureWebSocket.instances[-1])[-1] == {
        "type": "eos",
        "reason": "duration_limit",
    }


def test_webcodecs_session_limit_and_backlog_cleanup(monkeypatch):
    controller, hass = _controller(surveillance_label="Outside")
    token, _session = controller.sessions.create(424242, 12345678)
    hass.cameras["camera.driveway"] = FakeCamera(set(), "rtsp://192.0.2.10/live")
    registry = webcodecs_mod.WebCodecsSessionRegistry(max_sessions=1)
    monkeypatch.setattr(views_mod.webcodecs_mod, "SESSION_REGISTRY", registry)
    view = views_mod.MiniAppCameraWebCodecsView(controller)

    async def session_limited():
        lease = await registry.acquire("camera.driveway")
        try:
            with _MSEWebSocketPatch(
                monkeypatch,
                _FakeWSMessage(views_mod.WSMsgType.TEXT, '{"type":"webcodecs","value":"h264"}'),
                messages=("wait_forever",),
            ):
                await view.get(_mse_request(controller, token), "camera.driveway")
        finally:
            await lease.release()

    asyncio.run(session_limited())
    assert _json_texts(_CaptureWebSocket.instances[-1]) == [
        {"type": "error", "code": "session_limit"}
    ]

    async def many_units(_source):
        return _AsyncUnitSource(
            [
                webcodecs_mod.H264AccessUnit(
                    payload=b"\x00\x00\x00\x01\x67\x64\x00\x29"
                    if index == 0
                    else b"\x00\x00\x00\x01\x41\x9a",
                    keyframe=index == 0,
                    media_pts_us=index * 33333,
                    codec="avc1.640029",
                )
                for index in range(webcodecs_mod.WEBCODECS_MAX_QUEUE_UNITS + 4)
            ]
        )

    monkeypatch.setattr(
        views_mod.webcodecs_mod,
        "open_h264_access_unit_source",
        many_units,
    )
    with _MSEWebSocketPatch(
        monkeypatch,
        _FakeWSMessage(views_mod.WSMsgType.TEXT, '{"type":"webcodecs","value":"h264"}'),
        messages=("wait_forever",),
    ):
        _CaptureWebSocket.send_delay = 0.02
        asyncio.run(view.get(_mse_request(controller, token), "camera.driveway"))
    assert {"type": "error", "code": "backlog_exceeded"} in _json_texts(
        _CaptureWebSocket.instances[-1]
    )
    assert registry.active_count() == 0


def test_webcodecs_send_connection_error_is_clean_client_close(monkeypatch):
    controller, hass = _controller(surveillance_label="Outside")
    token, _session = controller.sessions.create(424242, 12345678)
    hass.cameras["camera.driveway"] = FakeCamera(set(), "rtsp://192.0.2.10/live")
    monkeypatch.setattr(
        views_mod.webcodecs_mod,
        "open_h264_access_unit_source",
        _single_webcodecs_source,
    )
    view = views_mod.MiniAppCameraWebCodecsView(controller)

    class _ClosingWebSocket(_CaptureWebSocket):
        async def send_bytes(self, payload):
            raise ConnectionResetError("closed")

    with _MSEWebSocketPatch(
        monkeypatch,
        _FakeWSMessage(views_mod.WSMsgType.TEXT, '{"type":"webcodecs","value":"h264"}'),
        messages=("wait_forever",),
    ):
        monkeypatch.setattr(views_mod.web, "WebSocketResponse", _ClosingWebSocket)
        asyncio.run(view.get(_mse_request(controller, token), "camera.driveway"))

    websocket = _ClosingWebSocket.instances[-1]
    texts = _json_texts(websocket)
    assert texts[0]["type"] == "source_open"
    assert texts[1]["type"] == "source_packet"
    assert texts[2] == {
        "type": "hello",
        "protocol": 2,
        "entity_id": "camera.driveway",
        "codec": "avc1.640029",
        "max_unit_bytes": webcodecs_mod.WEBCODECS_MAX_UNIT_BYTES,
        "session_max_seconds": webcodecs_mod.WEBCODECS_MAX_SESSION_SECONDS,
        "zero_transcode": True,
        "source_kind": "ordinary_rtsp",
        "comelit_entrance_open": False,
        "comelit_media_started": False,
    }
    assert websocket.binaries == []


def test_h264_sdp_access_unit_source_uses_local_rtp_whitelist(monkeypatch):
    calls = []

    class _CodecContext:
        name = "h264"
        extradata = None

    class _Stream:
        type = "video"
        codec_context = _CodecContext()

    class _Container:
        streams = [_Stream()]

        def demux(self, _stream):
            return iter(())

        def close(self):
            pass

    def fake_open(source, **kwargs):
        calls.append((source, kwargs))
        return _Container()

    monkeypatch.setitem(
        sys.modules,
        "av",
        types.SimpleNamespace(open=fake_open),
    )

    async def immediate_to_thread(func, /, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(webcodecs_mod.asyncio, "to_thread", immediate_to_thread)

    async def run():
        source = await webcodecs_mod.open_h264_sdp_access_unit_source(
            "/run/comelit-media/local-rtp.sdp"
        )
        await source.aclose()

    asyncio.run(run())
    assert calls == [
        (
            "/run/comelit-media/local-rtp.sdp",
            {
                "mode": "r",
                "format": "sdp",
                "options": {"protocol_whitelist": "file,udp,rtp"},
                "timeout": 5.0,
            },
        )
    ]


def test_webcodecs_entrance_busy_fails_before_second_media_acquire():
    controller, hass = _controller(surveillance_label="Outside")
    manager, _transport = _install_webcodecs_entrance_runtime(hass)
    manager.phase = "active"
    manager.active = True
    target = controller.get_webcodecs_camera_target("camera.comelit_entrance")

    with pytest.raises(controller_mod.MiniAppOperationError, match="intercom_media_busy"):
        asyncio.run(controller.acquire_webcodecs_entrance(target))

    assert manager.acquire_calls == []


def test_h264_access_unit_source_closes_container_once_on_cancel(monkeypatch):
    close_count = 0

    class _Packet:
        pts = 1
        time_base = 1 / 90000
        is_keyframe = True

        def __bytes__(self):
            return b"\x00\x00\x00\x01\x67\x64\x00\x29\x00\x00\x00\x01\x65\x88"

    class _CodecContext:
        name = "h264"
        extradata = None

    class _Stream:
        type = "video"
        codec_context = _CodecContext()

    class _Container:
        streams = [_Stream()]

        def demux(self, _stream):
            return iter([_Packet(), _Packet()])

        def close(self):
            nonlocal close_count
            close_count += 1

    monkeypatch.setitem(
        sys.modules,
        "av",
        types.SimpleNamespace(open=lambda *args, **kwargs: _Container()),
    )

    async def immediate_to_thread(func, /, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(webcodecs_mod.asyncio, "to_thread", immediate_to_thread)

    async def run():
        started = asyncio.Event()

        async def consume():
            source = await webcodecs_mod.open_h264_access_unit_source(
                "rtsp://192.0.2.10/live"
            )
            try:
                await source.__anext__()
                started.set()
                await asyncio.sleep(10)
            finally:
                await source.aclose()

        task = asyncio.create_task(consume())
        deadline = asyncio.get_running_loop().time() + 10
        while not started.is_set():
            if task.done():
                task.result()
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise TimeoutError("source did not yield first unit")
            await asyncio.sleep(min(0.05, remaining))
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(run())
    assert close_count == 1


def test_webcodecs_zero_transcode_and_no_forbidden_media_paths_static():
    backend = _read_file("custom_components/comelit/miniapp/webcodecs.py")
    frontend = _read_file("custom_components/comelit/frontend/miniapp/webcodecs.js")
    view_slice = _read_file("custom_components/comelit/miniapp/views.py").split(
        "class MiniAppCameraWebCodecsView", 1
    )[1].split("class MiniAppCameraDiagnosticsView", 1)[0]

    forbidden_backend = ("decode(", "libx264", "scale=", "async_request_stream", "HLS_PROVIDER")
    for token in forbidden_backend:
        assert token not in backend
        assert token not in view_slice
    assert "container.demux(video_stream)" in backend
    assert "import av" in backend

    forbidden_frontend = (
        "MediaSource",
        "Hls",
        "RTCPeerConnection",
        "/mse",
        "/webrtc",
        "button.press",
        "async_press_door",
    )
    for token in forbidden_frontend:
        assert token not in frontend


class _FakeContent:
    def __init__(self, body: bytes):
        self._body = body

    async def read(self, _size: int = -1):
        body = self._body
        self._body = b""
        return body


class _FakeRequest:
    def __init__(
        self,
        body: dict | bytes,
        *,
        token: str = "",
        marker: bool = True,
    ):
        self.cookies = {views_mod.COOKIE_NAME: token} if token else {}
        self.headers = {views_mod.MINIAPP_MARKER_HEADER: "1"} if marker else {}
        raw = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
        self.content = _FakeContent(raw)


class _FakeWSMessage:
    def __init__(self, message_type, data=None):
        self.type = message_type
        self.data = data


class _CaptureWebSocket:
    instances: list["_CaptureWebSocket"] = []
    next_first = _FakeWSMessage("close")
    next_messages: list[object] = []
    send_delay = 0.0

    def __init__(self, *args, **kwargs):
        self.closed = False
        self.prepared = False
        self.texts: list[str] = []
        self.binaries: list[bytes] = []
        self.close_count = 0
        self.first = self.__class__.next_first
        self.messages = list(self.__class__.next_messages)
        self.__class__.instances.append(self)

    async def prepare(self, request):
        self.prepared = True

    async def receive(self, timeout=None):
        return self.first

    async def send_json(self, payload):
        self.texts.append(json.dumps(payload, separators=(",", ":")))

    async def send_bytes(self, payload):
        if self.__class__.send_delay:
            await asyncio.sleep(self.__class__.send_delay)
        self.binaries.append(bytes(payload))

    async def close(self):
        self.closed = True
        self.close_count += 1

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self.messages:
            raise StopAsyncIteration
        message = self.messages.pop(0)
        if isinstance(message, tuple) and message[0] == "sleep":
            await asyncio.sleep(message[1])
            return await self.__anext__()
        if message == "wait_forever":
            while not self.closed:
                await asyncio.sleep(0.01)
            raise StopAsyncIteration
        return message


class _FakeUpstreamWebSocket:
    def __init__(self, messages=None):
        self.closed = False
        self.messages = list(messages or [])
        self.sent_json: list[dict] = []
        self.close_count = 0

    async def send_json(self, payload):
        self.sent_json.append(payload)

    async def close(self):
        self.closed = True
        self.close_count += 1

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self.messages:
            raise StopAsyncIteration
        message = self.messages.pop(0)
        if isinstance(message, tuple) and message[0] == "sleep":
            await asyncio.sleep(message[1])
            return await self.__anext__()
        return message


class _MSEWebSocketPatch:
    def __init__(self, monkeypatch, first, messages=()):
        self.monkeypatch = monkeypatch
        self.first = first
        self.messages = list(messages)

    def __enter__(self):
        _CaptureWebSocket.instances = []
        _CaptureWebSocket.next_first = self.first
        _CaptureWebSocket.next_messages = self.messages
        _CaptureWebSocket.send_delay = 0.0
        self.monkeypatch.setattr(views_mod.web, "WebSocketResponse", _CaptureWebSocket)
        return _CaptureWebSocket

    def __exit__(self, exc_type, exc, tb):
        return False


class _FakeGo2RTCWithUpstream:
    def __init__(self, upstream: _FakeUpstreamWebSocket | None = None):
        self.registers: list[tuple[str, str]] = []
        self.unregisters: list[str] = []
        self.upstream = upstream or _FakeUpstreamWebSocket()
        self.opened: list[str] = []

    async def register_stream(self, internal_name: str, sources: list[str]):
        self.registers.append((internal_name, list(sources)))

    async def unregister_stream(self, internal_name: str):
        self.unregisters.append(internal_name)

    async def open_mse_ws(self, internal_name: str):
        self.opened.append(internal_name)
        return self.upstream


def _mse_request(controller, token: str):
    return _FakeRequest({}, token=token, marker=True)


def _json_texts(websocket: _CaptureWebSocket):
    return [json.loads(text) for text in websocket.texts]


async def _wait_for(predicate, *, ticks: int = 20):
    for _ in range(ticks):
        value = predicate()
        if value:
            return value
        await asyncio.sleep(0)
    raise AssertionError("condition was not reached")


def test_diagnostics_endpoint_requires_session():
    controller, _hass = _controller(surveillance_label="Outside")
    view = views_mod.MiniAppCameraDiagnosticsView(controller)

    with pytest.raises(Exception) as exc:
        asyncio.run(
            view.post(
                _FakeRequest({"event": "config"}, token="", marker=True),
                "camera.driveway",
            )
        )

    assert exc.value.status == 403


def test_diagnostics_endpoint_rejects_unknown_entity():
    controller, _hass = _controller(surveillance_label="Outside")
    token, _session = controller.sessions.create(424242, 12345678)
    view = views_mod.MiniAppCameraDiagnosticsView(controller)

    with pytest.raises(Exception) as exc:
        asyncio.run(
            view.post(
                _FakeRequest({"event": "config"}, token=token),
                "camera.unlisted",
            )
        )

    assert exc.value.status == 404


def test_diagnostics_endpoint_invalid_payload_returns_fixed_error_without_echo():
    controller, _hass = _controller(surveillance_label="Outside")
    token, _session = controller.sessions.create(424242, 12345678)
    view = views_mod.MiniAppCameraDiagnosticsView(controller)

    response = asyncio.run(
        view.post(
            _FakeRequest(
                {"event": "rtp", "extra": "https://secret.invalid"},
                token=token,
            ),
            "camera.driveway",
        )
    )

    assert response.status == 400
    assert json.loads(response.text) == {"error": "invalid_diagnostics_event"}
    assert "secret" not in response.text


def test_diagnostics_endpoint_logs_one_closed_line(caplog):
    controller, _hass = _controller(surveillance_label="Outside")
    token, _session = controller.sessions.create(424242, 12345678)
    view = views_mod.MiniAppCameraDiagnosticsView(controller)

    with caplog.at_level(logging.INFO, logger="custom_components.comelit.miniapp.views"):
        response = asyncio.run(
            view.post(
                _FakeRequest(
                    {
                        "event": "fallback",
                        "elapsed_ms": 5000,
                        "stage_ms": 1000,
                        "reason": "stats_deadline_checking",
                        "counters": {"bytes_received": 0},
                    },
                    token=token,
                ),
                "camera.driveway",
            )
        )

    assert response.status == 200
    assert json.loads(response.text) == {"ok": True}
    records = [
        record.message
        for record in caplog.records
        if record.message.startswith("COMELIT_MINIAPP_DIAG ")
    ]
    assert records == [
        "COMELIT_MINIAPP_DIAG entity=camera.driveway event=fallback "
        "elapsed_ms=5000 stage_ms=1000 state=- reason=stats_deadline_checking "
        "counters=bytes_received=0"
    ]


def test_diagnostics_endpoint_rate_limits_per_session_entity_without_echo():
    controller, _hass = _controller(surveillance_label="Outside")
    token, _session = controller.sessions.create(424242, 12345678)
    view = views_mod.MiniAppCameraDiagnosticsView(controller)

    for index in range(diagnostics_mod.MAX_EVENTS_PER_SESSION_ENTITY):
        response = asyncio.run(
            view.post(
                _FakeRequest(
                    {"event": "config", "elapsed_ms": index},
                    token=token,
                ),
                "camera.driveway",
            )
        )
        assert response.status == 200

    response = asyncio.run(
        view.post(
            _FakeRequest(
                {"event": "config", "elapsed_ms": 1, "extra": "secret"},
                token=token,
            ),
            "camera.driveway",
        )
    )

    assert response.status == 400
    assert json.loads(response.text) == {"error": "invalid_diagnostics_event"}
    assert "secret" not in response.text

    response = asyncio.run(
        view.post(
            _FakeRequest({"event": "config", "elapsed_ms": 1}, token=token),
            "camera.driveway",
        )
    )

    assert response.status == 429
    assert json.loads(response.text) == {"error": "diagnostics_rate_limited"}


def test_diagnostics_endpoint_rate_limit_does_not_cross_sessions():
    controller, _hass = _controller(surveillance_label="Outside")
    token, _session = controller.sessions.create(424242, 12345678)
    fresh_token, _fresh_session = controller.sessions.create(424242, 12345678)
    view = views_mod.MiniAppCameraDiagnosticsView(controller)

    for _index in range(diagnostics_mod.MAX_EVENTS_PER_SESSION_ENTITY):
        response = asyncio.run(
            view.post(
                _FakeRequest({"event": "config"}, token=token),
                "camera.driveway",
            )
        )
        assert response.status == 200

    response = asyncio.run(
        view.post(
            _FakeRequest({"event": "config"}, token=fresh_token),
            "camera.driveway",
        )
    )

    assert response.status == 200


def test_diagnostics_rate_limiter_store_stays_bounded_under_overflow():
    controller, _hass = _controller(surveillance_label="Outside")
    view = views_mod.MiniAppCameraDiagnosticsView(controller)

    for _index in range(diagnostics_mod.MAX_RATE_LIMIT_SESSIONS + 12):
        token, _session = controller.sessions.create(424242, 12345678)
        response = asyncio.run(
            view.post(
                _FakeRequest({"event": "config"}, token=token),
                "camera.driveway",
            )
        )
        assert response.status == 200

    assert view._rate_limiter.bucket_count <= diagnostics_mod.MAX_RATE_LIMIT_SESSIONS


def test_entrance_hls_fallback_waits_for_webcodecs_cleanup(monkeypatch):
    controller, hass = _controller(surveillance_label="Outside")
    manager, _transport = _install_webcodecs_entrance_runtime(hass)
    token, session = controller.sessions.create(424242, 12345678)
    manager.phase = "stopping"
    manager.active = False
    manager.status = lambda: {
        "phase": manager.phase,
        "leases": {},
    }
    stream_phases = []

    async def fake_request_stream(_hass, entity_id, provider):
        stream_phases.append((manager.phase, entity_id, provider))
        return "/api/hls/abc123/master_playlist.m3u8"

    monkeypatch.setattr(controller_mod, "async_request_stream", fake_request_stream)

    async def run():
        async def finish_cleanup():
            await asyncio.sleep(0)
            manager.phase = "inactive"

        cleanup = asyncio.create_task(finish_cleanup())
        result = await controller.async_create_camera_media(
            token,
            session,
            "camera.comelit_entrance",
        )
        await cleanup
        return result

    result = asyncio.run(run())
    assert stream_phases == [
        ("inactive", "camera.comelit_entrance", controller_mod.HLS_PROVIDER)
    ]
    assert result.startswith("/api/comelit/miniapp/media/")


def test_entrance_hls_fallback_fails_closed_on_media_error(monkeypatch):
    controller, hass = _controller(surveillance_label="Outside")
    manager, _transport = _install_webcodecs_entrance_runtime(hass)
    token, session = controller.sessions.create(424242, 12345678)
    manager.phase = "error"
    manager.active = False
    manager.status = lambda: {
        "phase": manager.phase,
        "leases": {},
    }
    stream_calls = []

    async def fake_request_stream(*args, **kwargs):
        stream_calls.append((args, kwargs))
        return "/api/hls/abc123/master_playlist.m3u8"

    monkeypatch.setattr(controller_mod, "async_request_stream", fake_request_stream)

    with pytest.raises(
        controller_mod.MiniAppOperationError,
        match="webcodecs_cleanup_failed",
    ):
        asyncio.run(
            controller.async_create_camera_media(
                token,
                session,
                "camera.comelit_entrance",
            )
        )

    assert stream_calls == []


def test_webcodecs_entrance_reopen_waits_for_previous_cleanup(monkeypatch):
    controller, hass = _controller(surveillance_label="Outside")
    manager, _transport = _install_webcodecs_entrance_runtime(hass)
    manager.phase = "stopping"
    manager.active = False
    manager.status = lambda: {
        "phase": manager.phase,
        "leases": {},
    }
    acquire_phases = []
    original_acquire = manager.async_acquire

    async def guarded_acquire(*, panel, reason):
        acquire_phases.append(manager.phase)
        return await original_acquire(panel=panel, reason=reason)

    manager.async_acquire = guarded_acquire

    async def run():
        async def finish_cleanup():
            await asyncio.sleep(0)
            manager.phase = "inactive"

        cleanup = asyncio.create_task(finish_cleanup())
        lease = await controller.acquire_webcodecs_entrance(
            controller.get_webcodecs_camera_target("camera.comelit_entrance")
        )
        await cleanup
        await lease.release()

    asyncio.run(run())
    assert acquire_phases == ["inactive"]
    assert manager.acquire_calls == [("entrance", "miniapp_webcodecs")]
    assert manager.release_calls == ["miniapp_webcodecs"]


class _FakeAttachedRingCoordinator:
    def __init__(self, *, requested: bool = True):
        self.requests: list[str] = []
        self.requested = requested

    async def async_request_stop(self, reason: str):
        self.requests.append(reason)
        return self.requested


def _install_attached_ring_coordinator(hass, *, requested: bool = True):
    coordinator = _FakeAttachedRingCoordinator(requested=requested)
    domain_data = hass.data.setdefault(controller_mod.DOMAIN, {})
    domain_data.setdefault(controller_mod.DATA_RING_MEDIA, {})["entry-1"] = coordinator
    return coordinator


def test_attached_viewer_open_and_explicit_close_requests_ring_stop_once():
    controller, hass = _controller(surveillance_label="Outside")
    coordinator = _install_attached_ring_coordinator(hass)
    token, session = controller.sessions.create(424242, 12345678)

    async def run():
        opened = await controller.async_attached_viewer_event(
            token,
            session,
            action="open",
            viewer_id="viewer_001",
        )
        assert opened["viewer_count"] == 1
        closed = await controller.async_attached_viewer_event(
            token,
            session,
            action="close",
            viewer_id="viewer_001",
        )
        assert closed["viewer_count"] == 0
        duplicate = await controller.async_attached_viewer_event(
            token,
            session,
            action="close",
            viewer_id="viewer_001",
        )
        assert duplicate["viewer_count"] == 0
        await controller.async_close_attached_viewers_for_shutdown()

    asyncio.run(run())
    assert coordinator.requests == ["viewer_closed"]


def test_attached_viewer_expiry_requests_single_teardown(monkeypatch):
    controller, hass = _controller(surveillance_label="Outside")
    coordinator = _install_attached_ring_coordinator(hass)
    token, session = controller.sessions.create(424242, 12345678)
    monkeypatch.setattr(controller_mod, "ATTACHED_VIEWER_LEASE_EXPIRY_SECONDS", 0)

    async def run():
        await controller.async_attached_viewer_event(
            token,
            session,
            action="open",
            viewer_id="viewer_002",
        )
        await asyncio.wait_for(_wait_for(lambda: coordinator.requests), timeout=1)

    asyncio.run(run())
    assert coordinator.requests == ["viewer_lease_expired"]


def test_attached_viewer_heartbeats_keep_lease_alive_until_close(monkeypatch):
    controller, hass = _controller(surveillance_label="Outside")
    coordinator = _install_attached_ring_coordinator(hass)
    token, session = controller.sessions.create(424242, 12345678)
    monkeypatch.setattr(controller_mod, "ATTACHED_VIEWER_LEASE_EXPIRY_SECONDS", 100)

    async def run():
        await controller.async_attached_viewer_event(
            token,
            session,
            action="open",
            viewer_id="viewer_003",
        )
        await controller.async_attached_viewer_event(
            token,
            session,
            action="heartbeat",
            viewer_id="viewer_003",
        )
        await asyncio.sleep(0)
        assert coordinator.requests == []
        await controller.async_attached_viewer_event(
            token,
            session,
            action="close",
            viewer_id="viewer_003",
        )

    asyncio.run(run())
    assert coordinator.requests == ["viewer_closed"]


def test_attached_viewer_two_viewers_release_last_only():
    controller, hass = _controller(surveillance_label="Outside")
    coordinator = _install_attached_ring_coordinator(hass)
    token, session = controller.sessions.create(424242, 12345678)

    async def run():
        await controller.async_attached_viewer_event(
            token, session, action="open", viewer_id="viewer_a1"
        )
        await controller.async_attached_viewer_event(
            token, session, action="open", viewer_id="viewer_b2"
        )
        await controller.async_attached_viewer_event(
            token, session, action="close", viewer_id="viewer_a1"
        )
        assert coordinator.requests == []
        await controller.async_attached_viewer_event(
            token, session, action="close", viewer_id="viewer_b2"
        )

    asyncio.run(run())
    assert coordinator.requests == ["viewer_closed"]


def test_attached_viewer_http_view_does_not_bypass_coordinator():
    views_source = _read_file("custom_components/comelit/miniapp/views.py")
    view_slice = views_source.split("class MiniAppAttachedViewerView", 1)[1].split(
        "class MiniAppCameraStreamView", 1
    )[0]
    assert "async_force_stop" not in view_slice
    assert "async_stop_attached_media" not in view_slice
    assert "async_request_stop" not in view_slice


def test_attached_viewer_endpoint_uses_session_and_is_idempotent():
    controller, hass = _controller(surveillance_label="Outside")
    coordinator = _install_attached_ring_coordinator(hass)
    token, _session = controller.sessions.create(424242, 12345678)
    view = views_mod.MiniAppAttachedViewerView(controller)

    async def run():
        response = await view.post(
            _FakeRequest(
                {"action": "open", "viewer_id": "viewer_http1"},
                token=token,
            )
        )
        assert response.status == 200
        response = await view.post(
            _FakeRequest(
                {"action": "close", "viewer_id": "viewer_http1"},
                token=token,
            )
        )
        assert response.status == 200
        response = await view.post(
            _FakeRequest(
                {"action": "close", "viewer_id": "viewer_http1"},
                token=token,
            )
        )
        assert response.status == 200

    asyncio.run(run())
    assert coordinator.requests == ["viewer_closed"]


def test_attached_viewer_cleanup_never_invokes_door_gate_or_retry(monkeypatch):
    controller, hass = _controller(surveillance_label="Outside")
    coordinator = _install_attached_ring_coordinator(hass)
    token, session = controller.sessions.create(424242, 12345678)
    door_invocations = 0
    gate_invocations = 0
    automatic_door_retry = False
    door_last_operation_id = None

    async def forbidden_door_press(door):
        nonlocal door_invocations, gate_invocations, automatic_door_retry
        if door == "gate":
            gate_invocations += 1
        else:
            door_invocations += 1
        automatic_door_retry = True
        raise AssertionError("viewer cleanup must not invoke Door/Gate")

    monkeypatch.setattr(controller, "async_press_door", forbidden_door_press)

    async def run():
        await controller.async_attached_viewer_event(
            token, session, action="open", viewer_id="viewer_door1"
        )
        await controller.async_attached_viewer_event(
            token, session, action="close", viewer_id="viewer_door1"
        )
        await _wait_for(lambda: coordinator.requests == ["viewer_closed"])

        await controller.async_attached_viewer_event(
            token, session, action="open", viewer_id="viewer_door2"
        )
        lease = controller._attached_viewers[(token, "viewer_door2")]
        lease.task.cancel()

        async def instant_sleep(_delay):
            return None

        monkeypatch.setattr(controller_mod.asyncio, "sleep", instant_sleep)
        await controller._expire_attached_viewer(
            token,
            "viewer_door2",
            lease.expires_at,
        )

    asyncio.run(run())

    assert coordinator.requests == ["viewer_closed", "viewer_lease_expired"]
    assert door_invocations == 0
    assert gate_invocations == 0
    assert automatic_door_retry is False
    assert door_last_operation_id is None
    assert hass.services.calls == []


def test_attached_viewer_shutdown_clears_leases_tasks_and_is_idempotent(monkeypatch):
    controller, hass = _controller(surveillance_label="Outside")
    coordinator = _install_attached_ring_coordinator(hass)
    token, session = controller.sessions.create(424242, 12345678)

    async def run_shutdown_path():
        await controller.async_attached_viewer_event(
            token, session, action="open", viewer_id="viewer_sda1"
        )
        await controller.async_attached_viewer_event(
            token, session, action="open", viewer_id="viewer_sdb2"
        )
        saved_tasks = [lease.task for lease in controller._attached_viewers.values()]
        await controller.async_close_attached_viewers_for_shutdown()
        assert controller._attached_viewers == {}
        assert all(task.done() for task in saved_tasks)
        pending = [
            task
            for task in asyncio.all_tasks()
            if task is not asyncio.current_task()
            and (
                task.get_name() == "Comelit attached viewer lease expiry"
                or "_expire_attached_viewer" in repr(task.get_coro())
            )
        ]
        assert pending == []
        await controller.async_close_attached_viewers_for_shutdown()

    asyncio.run(run_shutdown_path())
    assert coordinator.requests == ["shutdown"]

    controller, hass = _controller(surveillance_label="Outside")
    coordinator = _install_attached_ring_coordinator(hass)
    token, session = controller.sessions.create(424242, 12345678)

    async def run_close_path():
        await controller.async_attached_viewer_event(
            token, session, action="open", viewer_id="viewer_close1"
        )
        task = controller._attached_viewers[(token, "viewer_close1")].task
        await controller.async_attached_viewer_event(
            token, session, action="close", viewer_id="viewer_close1"
        )
        await _wait_for(task.done)
        await controller.async_close_attached_viewers_for_shutdown()

    asyncio.run(run_close_path())
    assert coordinator.requests == ["viewer_closed"]

    controller, hass = _controller(surveillance_label="Outside")
    coordinator = _install_attached_ring_coordinator(hass)
    token, session = controller.sessions.create(424242, 12345678)

    async def run_expiry_path():
        await controller.async_attached_viewer_event(
            token, session, action="open", viewer_id="viewer_exp1"
        )
        lease = controller._attached_viewers[(token, "viewer_exp1")]
        lease.task.cancel()

        async def instant_sleep(_delay):
            return None

        monkeypatch.setattr(controller_mod.asyncio, "sleep", instant_sleep)
        await controller._expire_attached_viewer(
            token,
            "viewer_exp1",
            lease.expires_at,
        )
        await controller.async_close_attached_viewers_for_shutdown()

    asyncio.run(run_expiry_path())
    assert coordinator.requests == ["viewer_lease_expired"]


def test_attached_viewer_endpoint_reports_lease_constants():
    controller, _hass = _controller(surveillance_label="Outside")
    token, _session = controller.sessions.create(424242, 12345678)
    view = views_mod.MiniAppAttachedViewerView(controller)

    async def run():
        response = await view.post(
            _FakeRequest(
                {"action": "open", "viewer_id": "viewer_const1"},
                token=token,
            )
        )
        await controller.async_close_attached_viewers_for_shutdown()
        return response

    response = asyncio.run(run())
    assert controller_mod.ATTACHED_VIEWER_HEARTBEAT_INTERVAL_SECONDS == 5
    assert controller_mod.ATTACHED_VIEWER_LEASE_EXPIRY_SECONDS == 15
    assert response.data["heartbeat_interval_seconds"] == 5
    assert response.data["lease_expiry_seconds"] == 15


def test_attached_viewer_heartbeat_and_silent_expiry_use_server_clock(monkeypatch):
    controller, hass = _controller(surveillance_label="Outside")
    coordinator = _install_attached_ring_coordinator(hass)
    clock = types.SimpleNamespace(now=1_800_000_000.0)
    token, session = controller.sessions.create(
        424242,
        12345678,
        now=int(clock.now),
    )
    created: list[tuple[str, float, asyncio.Task]] = []
    sleep_delays: list[float] = []
    monkeypatch.setattr(controller_mod.time, "time", lambda: clock.now)

    async def dormant_expiry_task():
        await asyncio.Event().wait()

    def create_dormant_task(session_token, viewer_id, expires_at):
        task = asyncio.create_task(
            dormant_expiry_task(),
            name="Comelit attached viewer lease expiry",
        )
        created.append((viewer_id, expires_at, task))
        return task

    monkeypatch.setattr(
        controller,
        "_create_attached_viewer_expiry_task",
        create_dormant_task,
    )

    async def run():
        loop = asyncio.get_running_loop()
        opened_at = loop.time()
        await controller.async_attached_viewer_event(
            token, session, action="open", viewer_id="viewer_clock"
        )
        first_task = created[-1][2]
        assert created[-1][1] == pytest.approx(opened_at + 15, abs=0.1)

        clock.now += 5
        heartbeat_at = loop.time()
        await controller.async_attached_viewer_event(
            token, session, action="heartbeat", viewer_id="viewer_clock"
        )
        await _wait_for(first_task.cancelled)
        assert created[-1][1] == pytest.approx(heartbeat_at + 15, abs=0.1)
        assert coordinator.requests == []

        clock.now += 16
        created[-1][2].cancel()

        async def instant_sleep(delay):
            sleep_delays.append(delay)
            return None

        monkeypatch.setattr(controller_mod.asyncio, "sleep", instant_sleep)
        await controller._expire_attached_viewer(
            token,
            "viewer_clock",
            created[-1][1],
        )

    asyncio.run(run())
    assert sleep_delays == pytest.approx([15], abs=0.1)
    assert coordinator.requests == ["viewer_lease_expired"]


def test_attached_viewer_session_expiry_bounds_lease_and_rejects_heartbeat(monkeypatch):
    controller, hass = _controller(surveillance_label="Outside")
    coordinator = _install_attached_ring_coordinator(hass)
    clock = types.SimpleNamespace(now=1_800_000_000.0)
    token, session = controller.sessions.create(
        424242,
        12345678,
        now=int(clock.now),
    )
    session.expires_at = int(clock.now) + 3
    created: list[tuple[str, float, asyncio.Task]] = []
    sleep_delays: list[float] = []
    monkeypatch.setattr(controller_mod.time, "time", lambda: clock.now)

    async def dormant_expiry_task():
        await asyncio.Event().wait()

    def create_dormant_task(session_token, viewer_id, expires_at):
        task = asyncio.create_task(
            dormant_expiry_task(),
            name="Comelit attached viewer lease expiry",
        )
        created.append((viewer_id, expires_at, task))
        return task

    monkeypatch.setattr(
        controller,
        "_create_attached_viewer_expiry_task",
        create_dormant_task,
    )

    async def run():
        loop = asyncio.get_running_loop()
        opened_at = loop.time()
        await controller.async_attached_viewer_event(
            token, session, action="open", viewer_id="viewer_sess1"
        )
        assert created[-1][1] == pytest.approx(opened_at + 3, abs=0.1)
        created[-1][2].cancel()

        async def instant_sleep(delay):
            sleep_delays.append(delay)
            return None

        monkeypatch.setattr(controller_mod.asyncio, "sleep", instant_sleep)
        await controller._expire_attached_viewer(
            token,
            "viewer_sess1",
            created[-1][1],
        )

        clock.now = float(session.expires_at)
        with pytest.raises(controller_mod.MiniAppOperationError, match="expired"):
            await controller.async_attached_viewer_event(
                token,
                session,
                action="heartbeat",
                viewer_id="viewer_sess1",
            )

    asyncio.run(run())
    assert sleep_delays == pytest.approx([3], abs=0.1)
    assert coordinator.requests == ["viewer_lease_expired"]


def test_attached_viewer_stop_marker_includes_requested_result(caplog):
    controller, hass = _controller(surveillance_label="Outside")
    _install_attached_ring_coordinator(hass, requested=False)
    token, session = controller.sessions.create(424242, 12345678)

    async def run():
        await controller.async_attached_viewer_event(
            token, session, action="open", viewer_id="viewer_log1"
        )
        with caplog.at_level(
            logging.INFO,
            logger="custom_components.comelit.miniapp.controller",
        ):
            await controller.async_attached_viewer_event(
                token, session, action="close", viewer_id="viewer_log1"
            )

    asyncio.run(run())
    messages = [record.getMessage() for record in caplog.records]
    assert any(
        message.startswith(
            "Comelit ring_media_stop_requested reason=viewer_closed "
            "viewer_count=0 elapsed_ms="
        )
        and message.endswith(" requested=False")
        for message in messages
    )
    assert not any("ring_media_stop_completed" in message for message in messages)


class _FakeRingManager:
    def __init__(self):
        self.active = False
        self.acquire_calls = []
        self.release_calls = []
        self.force_stop_calls = []

    async def async_acquire(self, *, panel, reason):
        self.acquire_calls.append((panel, reason))
        self.active = True
        return {"active": True}

    async def async_release(self, *, reason):
        self.release_calls.append(reason)
        self.active = False
        return {"active": False}

    async def async_force_stop(self, *, reason):
        self.force_stop_calls.append(reason)
        self.active = False
        return {"active": False}


class _FakeSnapshotProvider:
    async def async_capture_jpeg(self):
        return None


class _FakeAttachedTransport:
    def __init__(self):
        self.active = False
        self.local_sdp_ready = False
        self.local_sdp_path = Path("/run/comelit-attached/local.sdp")
        self.start_calls = 0
        self.stop_calls = 0
        self.fail_next_start: str | None = None

    async def async_start(self, panel):
        self.start_calls += 1
        if self.fail_next_start is not None:
            reason = self.fail_next_start
            self.fail_next_start = None
            raise _attached_media_mod().ComelitAttachedMediaError(reason)
        assert panel == "entrance"
        self.active = True
        self.local_sdp_ready = True

    async def async_stop(self):
        self.stop_calls += 1
        self.active = False
        self.local_sdp_ready = False

    async def async_wait_inactive(self, _timeout):
        return not self.active


class _FakeAttachedStreamProvider:
    def __init__(self):
        self.consumers = {}
        self.release_calls = []
        self.close_calls = 0

    async def async_acquire_consumer(self, reason):
        self.consumers[reason] = self.consumers.get(reason, 0) + 1

    async def async_release_consumer(self, reason):
        self.release_calls.append(reason)
        count = self.consumers.get(reason, 0)
        if count <= 1:
            self.consumers.pop(reason, None)
        else:
            self.consumers[reason] = count - 1
        if not self.consumers:
            await self.async_close()

    async def async_get_stream(self):
        return types.SimpleNamespace(
            set_update_callback=lambda _callback: None,
            outputs=lambda: {},
            stop=lambda: None,
        )

    async def async_capture_jpeg(self):
        return None

    async def async_record_mp4(self, path, *, target_seconds, stop_event):
        await stop_event.wait()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"truncated")
        raise asyncio.CancelledError

    async def async_close(self):
        self.close_calls += 1


class _BlockingRecordingProvider:
    def __init__(self):
        self.started = asyncio.Event()
        self.last_failure_reason = None

    async def async_record_mp4(self, path, *, target_seconds, stop_event):
        self.started.set()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"partial")
        await stop_event.wait()
        raise asyncio.CancelledError


class _ImmediateRecordingProvider:
    last_failure_reason = None

    async def async_record_mp4(self, path, *, target_seconds, stop_event):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"complete")
        return "completed"


def test_ring_media_viewer_close_during_recording_truncates_and_releases(tmp_path):
    controller, hass = _controller()
    manager = _FakeRingManager()
    recorder = _BlockingRecordingProvider()
    ring_media_mod = _ring_media_mod()
    coordinator = ring_media_mod.RingMediaCoordinator(
        hass,
        manager,
        snapshot_provider=_FakeSnapshotProvider(),
        recording_provider=recorder,
        media_root=tmp_path,
        recording_target_seconds=20,
        hard_limit_seconds=600,
        task_factory=lambda coro, name: asyncio.create_task(coro, name=name),
    )

    async def run():
        assert await coordinator.async_start_for_ring(
            {"door": "entrance", "event_id": "evt_recording_cancel"}
        )
        await asyncio.wait_for(recorder.started.wait(), timeout=1)
        assert await coordinator.async_request_stop("viewer_closed")
        await asyncio.wait_for(_wait_for(lambda: not coordinator.running), timeout=1)

    asyncio.run(run())
    status = coordinator.status()
    assert status["ring_end_reason"] == "viewer_closed"
    assert status["recording_result"]["state"] == "truncated"
    assert manager.release_calls == ["ring_media"]
    assert manager.force_stop_calls == []


def test_ring_media_remote_close_race_with_viewer_close_has_one_release(tmp_path):
    controller, hass = _controller()
    manager = _FakeRingManager()
    remote_closed = asyncio.Event()
    ring_media_mod = _ring_media_mod()

    async def remote_waiter(_timeout):
        await remote_closed.wait()
        return True

    coordinator = ring_media_mod.RingMediaCoordinator(
        hass,
        manager,
        snapshot_provider=_FakeSnapshotProvider(),
        recording_provider=_ImmediateRecordingProvider(),
        media_root=tmp_path,
        remote_close_waiter=remote_waiter,
        hard_limit_seconds=600,
        task_factory=lambda coro, name: asyncio.create_task(coro, name=name),
    )

    async def run():
        assert await coordinator.async_start_for_ring(
            {"door": "entrance", "event_id": "evt_remote_race"}
        )
        await asyncio.sleep(0)
        remote_closed.set()
        await coordinator.async_request_stop("viewer_closed")
        await asyncio.wait_for(_wait_for(lambda: not coordinator.running), timeout=1)

    asyncio.run(run())
    assert coordinator.status()["ring_end_reason"] in {"remote_closed", "viewer_closed"}
    assert manager.release_calls == ["ring_media"]
    assert manager.force_stop_calls == []


def test_ring_media_hard_limit_reason_still_uses_existing_force_stop(tmp_path):
    controller, hass = _controller()
    manager = _FakeRingManager()
    ticks = iter([0.0, 0.0, 2.0, 2.0, 2.0])
    ring_media_mod = _ring_media_mod()

    async def remote_waiter(_timeout):
        return False

    coordinator = ring_media_mod.RingMediaCoordinator(
        hass,
        manager,
        snapshot_provider=_FakeSnapshotProvider(),
        recording_provider=_ImmediateRecordingProvider(),
        media_root=tmp_path,
        remote_close_waiter=remote_waiter,
        hard_limit_seconds=1,
        task_factory=lambda coro, name: asyncio.create_task(coro, name=name),
        monotonic_clock=lambda: next(ticks, 2.0),
    )

    async def run():
        assert await coordinator.async_start_for_ring(
            {"door": "entrance", "event_id": "evt_hard_limit"}
        )
        await asyncio.wait_for(_wait_for(lambda: not coordinator.running), timeout=1)

    asyncio.run(run())
    assert coordinator.status()["ring_end_reason"] == "hard_limit"
    assert manager.release_calls == ["ring_media"]
    assert manager.force_stop_calls == ["ring_media_hard_limit"]


def _attached_camera_lifecycle(tmp_path, hass):
    attached_media_mod = _attached_media_mod()
    camera_mod = _camera_mod()
    ring_media_mod = _ring_media_mod()
    attached_transport = _FakeAttachedTransport()
    attached_session = attached_media_mod.ComelitAttachedRingMediaSession(
        attached_transport
    )
    attached_provider = _FakeAttachedStreamProvider()
    on_demand_transport = _FakeWebCodecsMediaTransport()
    on_demand_manager = _FakeWebCodecsMediaManager(on_demand_transport)
    camera = camera_mod.ComelitEntranceCamera(
        on_demand_manager,
        on_demand_transport,
        media_provider=_FakeAttachedStreamProvider(),
        attached_session=attached_session,
        attached_transport=attached_transport,
        attached_provider=attached_provider,
    )
    recorder = _BlockingRecordingProvider()
    coordinator = ring_media_mod.RingMediaCoordinator(
        hass,
        attached_session,
        snapshot_provider=attached_provider,
        recording_provider=recorder,
        media_root=tmp_path,
        recording_target_seconds=20,
        hard_limit_seconds=600,
        task_factory=lambda coro, name: asyncio.create_task(coro, name=name),
    )
    coordinator.set_camera_view_release_callback(
        camera.async_release_attached_camera_view_if_idle
    )
    domain_data = hass.data.setdefault(controller_mod.DOMAIN, {})
    domain_data.setdefault(controller_mod.DATA_RING_MEDIA, {})["entry-1"] = coordinator
    return coordinator, recorder, camera, attached_session, attached_transport, attached_provider


def test_camera_setup_entry_wires_ring_media_release_callback_to_created_camera(
    tmp_path,
):
    controller, hass = _controller(surveillance_label="Outside")
    camera_mod = _camera_mod()
    attached_media_mod = _attached_media_mod()
    ring_media_mod = _ring_media_mod()
    attached_transport = _FakeAttachedTransport()
    attached_session = attached_media_mod.ComelitAttachedRingMediaSession(
        attached_transport
    )
    attached_provider = _FakeAttachedStreamProvider()
    on_demand_transport = _FakeWebCodecsMediaTransport()
    on_demand_manager = _FakeWebCodecsMediaManager(on_demand_transport)
    recorder = _BlockingRecordingProvider()
    coordinator = ring_media_mod.RingMediaCoordinator(
        hass,
        attached_session,
        snapshot_provider=attached_provider,
        recording_provider=recorder,
        media_root=tmp_path,
        recording_target_seconds=20,
        hard_limit_seconds=600,
        task_factory=lambda coro, name: asyncio.create_task(coro, name=name),
    )
    domain_data = hass.data.setdefault(camera_mod.DOMAIN, {})
    entry = _ConfigEntry(entry_id="entry-setup")
    domain_data.setdefault(camera_mod.DATA_MEDIA_SESSIONS, {})[entry.entry_id] = (
        on_demand_manager
    )
    domain_data.setdefault(camera_mod.DATA_MEDIA_TRANSPORTS, {})[entry.entry_id] = (
        on_demand_transport
    )
    domain_data.setdefault(camera_mod.DATA_MEDIA_PROVIDERS, {})[entry.entry_id] = (
        _FakeAttachedStreamProvider()
    )
    domain_data.setdefault(camera_mod.DATA_ATTACHED_MEDIA_SESSIONS, {})[
        entry.entry_id
    ] = attached_session
    domain_data.setdefault(camera_mod.DATA_ATTACHED_MEDIA_TRANSPORTS, {})[
        entry.entry_id
    ] = attached_transport
    domain_data.setdefault(camera_mod.DATA_ATTACHED_MEDIA_PROVIDERS, {})[
        entry.entry_id
    ] = attached_provider
    domain_data.setdefault(camera_mod.DATA_RING_MEDIA, {})[entry.entry_id] = (
        coordinator
    )
    added = []

    async def run():
        await camera_mod.async_setup_entry(hass, entry, added.extend)
        assert len(added) == 1
        camera = added[0]
        assert isinstance(camera, camera_mod.ComelitEntranceCamera)

        assert await coordinator.async_start_for_ring(
            {"door": "entrance", "event_id": "evt_setup_wiring"}
        )
        await asyncio.wait_for(recorder.started.wait(), timeout=1)
        await camera._async_acquire_camera_view_media()
        assert attached_session.status()["leases"] == {
            "ring_media": 1,
            "camera_view": 1,
        }
        assert await coordinator.async_request_stop("viewer_closed")
        await asyncio.wait_for(_wait_for(lambda: not coordinator.running), timeout=1)

    asyncio.run(run())
    assert attached_session.status()["leases"] == {}
    assert attached_session.status()["active"] is False
    assert attached_transport.stop_calls == 1
    assert attached_provider.release_calls == ["ring_media", "camera_view"]


def test_camera_setup_entry_without_ring_media_still_adds_camera():
    _controller_obj, hass = _controller(surveillance_label="Outside")
    camera_mod = _camera_mod()
    entry = _ConfigEntry(entry_id="entry-no-ring-media")
    domain_data = hass.data.setdefault(camera_mod.DOMAIN, {})
    on_demand_transport = _FakeWebCodecsMediaTransport()
    domain_data.setdefault(camera_mod.DATA_MEDIA_SESSIONS, {})[entry.entry_id] = (
        _FakeWebCodecsMediaManager(on_demand_transport)
    )
    domain_data.setdefault(camera_mod.DATA_MEDIA_TRANSPORTS, {})[entry.entry_id] = (
        on_demand_transport
    )
    domain_data.setdefault(camera_mod.DATA_MEDIA_PROVIDERS, {})[entry.entry_id] = (
        _FakeAttachedStreamProvider()
    )
    added = []

    asyncio.run(camera_mod.async_setup_entry(hass, entry, added.extend))

    assert len(added) == 1
    assert isinstance(added[0], camera_mod.ComelitEntranceCamera)


async def _start_attached_ring_with_camera_view(
    coordinator,
    recorder,
    camera,
    attached_session,
):
    assert await coordinator.async_start_for_ring(
        {"door": "entrance", "event_id": "evt_attached_lifecycle"}
    )
    await asyncio.wait_for(recorder.started.wait(), timeout=1)
    await camera._async_acquire_camera_view_media()
    status = attached_session.status()
    assert status["leases"] == {"ring_media": 1, "camera_view": 1}
    assert status["active"] is True


def test_attached_ring_close_releases_camera_view_and_stops_once(tmp_path):
    controller, hass = _controller(surveillance_label="Outside")
    coordinator, recorder, camera, session, transport, provider = (
        _attached_camera_lifecycle(tmp_path, hass)
    )
    token, miniapp_session = controller.sessions.create(424242, 12345678)

    async def run():
        await _start_attached_ring_with_camera_view(
            coordinator, recorder, camera, session
        )
        await controller.async_attached_viewer_event(
            token, miniapp_session, action="open", viewer_id="viewer_full1"
        )
        await controller.async_attached_viewer_event(
            token, miniapp_session, action="close", viewer_id="viewer_full1"
        )
        await asyncio.wait_for(_wait_for(lambda: not coordinator.running), timeout=1)

    asyncio.run(run())
    assert session.status()["leases"] == {}
    assert session.status()["active"] is False
    assert transport.stop_calls == 1
    assert provider.release_calls == ["ring_media", "camera_view"]


def test_attached_camera_view_release_preserves_new_lease_after_toctou_attach(
    tmp_path,
    monkeypatch,
):
    controller, hass = _controller(surveillance_label="Outside")
    coordinator, recorder, camera, session, transport, provider = (
        _attached_camera_lifecycle(tmp_path, hass)
    )
    on_demand_manager = camera._manager
    on_demand_transport = camera._transport
    on_demand_provider = camera._media_provider
    original_end_camera_view = camera._async_end_camera_view

    async def acquire_new_lease_before_original_release(reason, **kwargs):
        assert await camera._async_release_camera_view_media(
            expected_owner=session,
            expected_provider=provider,
            expected_owner_kind="attached_inbound",
        )
        assert session.status()["leases"] == {}
        await on_demand_manager.async_acquire(panel="entrance", reason="camera_view")
        await on_demand_provider.async_acquire_consumer("camera_view")
        async with camera._camera_view_lock:
            camera._camera_view_owner = on_demand_manager
            camera._camera_view_transport = on_demand_transport
            camera._camera_view_provider = on_demand_provider
            camera._camera_view_owner_kind = "on_demand"
        assert on_demand_manager.status()["leases"] == {"camera_view": 1}
        assert on_demand_transport.active is True
        return await original_end_camera_view(reason, **kwargs)

    monkeypatch.setattr(
        camera,
        "_async_end_camera_view",
        acquire_new_lease_before_original_release,
    )

    async def run():
        await _start_attached_ring_with_camera_view(
            coordinator, recorder, camera, session
        )
        assert await coordinator.async_request_stop("viewer_closed")
        await asyncio.wait_for(_wait_for(lambda: not coordinator.running), timeout=1)

    asyncio.run(run())
    assert session.status()["leases"] == {}
    assert transport.stop_calls == 1
    assert on_demand_manager.status()["leases"] == {"camera_view": 1}
    assert on_demand_transport.active is True
    assert on_demand_manager.release_calls == []


def test_attached_camera_view_release_without_toctou_releases_original_lease(
    tmp_path,
):
    controller, hass = _controller(surveillance_label="Outside")
    coordinator, recorder, camera, session, transport, provider = (
        _attached_camera_lifecycle(tmp_path, hass)
    )

    async def run():
        await _start_attached_ring_with_camera_view(
            coordinator, recorder, camera, session
        )
        assert await coordinator.async_request_stop("viewer_closed")
        await asyncio.wait_for(_wait_for(lambda: not coordinator.running), timeout=1)

    asyncio.run(run())
    assert session.status()["leases"] == {}
    assert session.status()["active"] is False
    assert transport.stop_calls == 1
    assert provider.release_calls == ["ring_media", "camera_view"]


def test_camera_view_expected_identity_mismatch_preserves_stream_and_lease(
    tmp_path,
):
    controller, hass = _controller(surveillance_label="Outside")
    _coordinator, _recorder, camera, session, _transport, provider = (
        _attached_camera_lifecycle(tmp_path, hass)
    )
    wrong_owner = camera._manager
    wrong_provider = camera._media_provider
    stream = object()

    async def run():
        await session.async_acquire(panel="entrance", reason="ring_media")
        try:
            await camera._async_acquire_camera_view_media()
            camera.stream = stream
            released = await camera._async_end_camera_view(
                "attached_viewer_released",
                expected_owner=wrong_owner,
                expected_provider=wrong_provider,
                expected_owner_kind="on_demand",
            )
            assert released is False
            assert camera.stream is stream
            assert session.status()["leases"] == {
                "ring_media": 1,
                "camera_view": 1,
            }
            assert provider.release_calls == []
        finally:
            await camera._async_release_camera_view_media()
            await session.async_release(reason="ring_media")

    asyncio.run(run())
    assert camera.stream is stream


def test_attached_ring_lease_expiry_releases_camera_view_and_stops_once(
    tmp_path,
    monkeypatch,
):
    controller, hass = _controller(surveillance_label="Outside")
    coordinator, recorder, camera, session, transport, provider = (
        _attached_camera_lifecycle(tmp_path, hass)
    )
    token, miniapp_session = controller.sessions.create(424242, 12345678)

    async def run():
        await _start_attached_ring_with_camera_view(
            coordinator, recorder, camera, session
        )
        await controller.async_attached_viewer_event(
            token, miniapp_session, action="open", viewer_id="viewer_expfull"
        )
        lease = controller._attached_viewers[(token, "viewer_expfull")]
        lease.task.cancel()
        original_sleep = controller_mod.asyncio.sleep

        async def instant_sleep(_delay):
            return None

        monkeypatch.setattr(controller_mod.asyncio, "sleep", instant_sleep)
        await controller._expire_attached_viewer(
            token,
            "viewer_expfull",
            lease.expires_at,
        )
        monkeypatch.setattr(controller_mod.asyncio, "sleep", original_sleep)
        await asyncio.wait_for(_wait_for(lambda: not coordinator.running), timeout=1)

    asyncio.run(run())
    assert session.status()["leases"] == {}
    assert session.status()["active"] is False
    assert transport.stop_calls == 1
    assert provider.release_calls == ["ring_media", "camera_view"]


def test_attached_ring_close_defers_camera_view_release_for_other_provider_consumer(
    tmp_path,
):
    controller, hass = _controller(surveillance_label="Outside")
    coordinator, recorder, camera, session, transport, provider = (
        _attached_camera_lifecycle(tmp_path, hass)
    )
    token, miniapp_session = controller.sessions.create(424242, 12345678)

    async def run():
        await _start_attached_ring_with_camera_view(
            coordinator, recorder, camera, session
        )
        provider.consumers["ha_camera_consumer"] = 1
        await controller.async_attached_viewer_event(
            token, miniapp_session, action="open", viewer_id="viewer_multi"
        )
        await controller.async_attached_viewer_event(
            token, miniapp_session, action="close", viewer_id="viewer_multi"
        )
        await asyncio.wait_for(_wait_for(lambda: not coordinator.running), timeout=1)
        assert session.status()["leases"] == {"camera_view": 1}
        assert session.status()["active"] is True
        assert transport.stop_calls == 0
        provider.consumers.pop("ha_camera_consumer", None)
        await camera._async_release_camera_view_media()

    asyncio.run(run())
    assert transport.stop_calls == 1
    assert provider.release_calls == ["ring_media", "camera_view"]


def test_attached_ring_reopen_after_teardown_fails_closed_with_exact_reason(tmp_path):
    controller, hass = _controller(surveillance_label="Outside")
    coordinator, recorder, camera, session, transport, _provider = (
        _attached_camera_lifecycle(tmp_path, hass)
    )
    token, miniapp_session = controller.sessions.create(424242, 12345678)

    async def run():
        await _start_attached_ring_with_camera_view(
            coordinator, recorder, camera, session
        )
        await controller.async_attached_viewer_event(
            token, miniapp_session, action="open", viewer_id="viewer_reopen"
        )
        await controller.async_attached_viewer_event(
            token, miniapp_session, action="close", viewer_id="viewer_reopen"
        )
        await asyncio.wait_for(_wait_for(lambda: not coordinator.running), timeout=1)
        assert session.status()["leases"] == {}
        assert session.status()["active"] is False

        transport.fail_next_start = "attached_media_open_not_confirmed"
        with pytest.raises(
            _attached_media_mod().ComelitAttachedMediaError,
            match="attached_media_open_not_confirmed",
        ):
            await session.async_acquire(panel="entrance", reason="camera_view")

    asyncio.run(run())
    assert session.status()["last_error"] == "attached_media_open_not_confirmed"
    assert "intercom_media_busy" != session.status()["last_error"]


def test_ring_end_reason_is_not_constant_after_viewer_stop(tmp_path):
    source = _read_file("custom_components/comelit/ring_media.py")
    assert 'self._ring_end_reason = "hard_limit"' not in source
    assert "async_request_stop" in source
