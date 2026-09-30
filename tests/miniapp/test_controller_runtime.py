from __future__ import annotations

import asyncio
import importlib.util
import json
import logging
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
    get_camera_from_entity_id=_get_camera_from_entity_id,
)
_camera_module.__path__ = []


class _StreamType:
    WEB_RTC = "web_rtc"


_install_module(
    "homeassistant.components.camera.const",
    StreamType=_StreamType,
)
_install_module(
    "homeassistant.components.http",
    HomeAssistantView=object,
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
_install_module(
    "homeassistant.helpers.aiohttp_client",
    async_get_clientsession=lambda hass: None,
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
diagnostics_mod = _load(
    MINIAPP_ROOT / "diagnostics.py",
    "custom_components.comelit.miniapp.diagnostics",
)
views_mod = _load(
    MINIAPP_ROOT / "views.py",
    "custom_components.comelit.miniapp.views",
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

    async def stream_source(self):
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

    def async_create_task(self, coro):
        return asyncio.create_task(coro)


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
        self.registers: list[tuple[str, str]] = []
        self.unregisters: list[str] = []

    async def register_stream(self, internal_name: str, source: str):
        self.registers.append((internal_name, source))

    async def unregister_stream(self, internal_name: str):
        self.unregisters.append(internal_name)


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

    assert fake_go2rtc.registers == [
        (controller.mse_internal_stream_name("camera.driveway"), source)
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


def test_mse_protocol_accepts_only_closed_codec_command():
    validate = views_mod._validate_mse_command

    assert validate('{"type":"mse","value":"h264,aac"}') == "h264,aac"

    for unsafe in (
        '{"type":"webrtc","value":"h264"}',
        '{"type":"mse","value":"h264,delete"}',
        '{"type":"mse","value":"h264,h265,hevc,av1,vp8,vp9,aac,mp4a,opus"}',
        '{"type":"mse","value":"rtsp://test-user:test-password@192.0.2.10/example"}',
        '{"type":"mse","value":"h264","extra":1}',
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
