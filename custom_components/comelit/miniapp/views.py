from __future__ import annotations

import asyncio
import contextlib
from http import HTTPStatus
import json
import logging
import time
from urllib.parse import urljoin
from uuid import uuid4

from aiohttp import ClientError, WSMsgType, web
from mashumaro import MissingField

from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.network import NoURLAvailableError, get_url
from homeassistant.exceptions import HomeAssistantError
from webrtc_models import RTCIceCandidateInit

from ..const import DOOR_ENTRANCE, DOOR_GATE
from .auth import TelegramAuthenticationError, validate_telegram_init_data
from .controller import ComelitMiniAppController, MiniAppOperationError
from .diagnostics import (
    MiniAppDiagnosticsRateLimiter,
    MiniAppDiagnosticsError,
    format_go2rtc_state_json_line,
    format_go2rtc_state_line,
    format_go2rtc_ws_line,
    format_log_line,
    format_server_log_line,
    loads_limited,
)
from .go2rtc import MiniAppGo2RTCError
from .session import MiniAppSession, MiniAppSessionError
from . import webcodecs as webcodecs_mod


_LOGGER = logging.getLogger(__name__)
_WEBSOCKET_SEND_ERRORS = (ConnectionError, BrokenPipeError, RuntimeError) + (
    () if ClientError is Exception else (ClientError,)
)
COOKIE_NAME = "comelit_miniapp_session"
AUTH_MAX_AGE_SECONDS = 300
AUTH_FUTURE_SKEW_SECONDS = 30
MAX_AUTH_BODY_BYTES = 20_000
MINIAPP_MARKER_HEADER = "X-Comelit-MiniApp-Request"
ACTION_NONCE_HEADER = "X-Comelit-Action-Nonce"
MSE_MAX_COMMAND_BYTES = 256
_MSE_CODECS = frozenset(
    {
        "avc1.640029",
        "avc1.64002a",
        "avc1.640033",
        "hvc1.1.6.l153.b0",
        "mp4a.40.2",
        "mp4a.40.5",
        "flac",
        "opus",
    }
)


def _security_headers(response: web.StreamResponse) -> web.StreamResponse:
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


def _json_response(
    data: dict[str, object],
    *,
    status: int = HTTPStatus.OK,
) -> web.Response:
    return _security_headers(web.json_response(data, status=status))


class _MiniAppView(HomeAssistantView):
    requires_auth = False

    def __init__(self, controller: ComelitMiniAppController) -> None:
        self.controller = controller

    def _require_configured(self) -> None:
        if not self.controller.settings.configured:
            raise web.HTTPNotFound

    def _session_token(self, request: web.Request) -> str:
        return request.cookies.get(COOKIE_NAME, "")

    def _require_session(
        self, request: web.Request
    ) -> tuple[str, MiniAppSession]:
        self._require_configured()
        token = self._session_token(request)
        try:
            session = self.controller.sessions.get(token)
        except MiniAppSessionError as exc:
            # Do not raise HTTPUnauthorized here. Home Assistant's global
            # HTTP ban middleware treats raised 401 responses as failed HA
            # login attempts. Mini App sessions are integration-owned and an
            # expired/restarted WebView must not poison HA's IP-ban counter.
            raise web.HTTPForbidden from exc
        if not self.controller.session_is_allowed(session):
            self.controller.sessions.delete(token)
            raise web.HTTPForbidden
        return token, session

    @staticmethod
    def _require_miniapp_marker(request: web.Request) -> None:
        if request.headers.get(MINIAPP_MARKER_HEADER) != "1":
            raise web.HTTPForbidden


class MiniAppIndexView(_MiniAppView):
    url = "/api/comelit/miniapp"
    name = "api:comelit:miniapp:index"

    async def get(self, request: web.Request) -> web.StreamResponse:
        self._require_configured()
        if not self.controller.index_path.is_file():
            raise web.HTTPNotFound

        response = web.FileResponse(self.controller.index_path)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' https://telegram.org; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob:; "
            "media-src 'self' blob:; "
            "connect-src 'self'; "
            "object-src 'none'; base-uri 'none'; form-action 'none'"
        )
        return response


class MiniAppSessionView(_MiniAppView):
    url = "/api/comelit/miniapp/session"
    name = "api:comelit:miniapp:session"

    async def post(self, request: web.Request) -> web.Response:
        self._require_configured()
        body_parts: list[bytes] = []
        body_size = 0
        while True:
            chunk = await request.content.read(4096)
            if not chunk:
                break
            body_size += len(chunk)
            if body_size > MAX_AUTH_BODY_BYTES:
                raise web.HTTPRequestEntityTooLarge(
                    max_size=MAX_AUTH_BODY_BYTES,
                    actual_size=body_size,
                )
            body_parts.append(chunk)
        body = b"".join(body_parts)
        try:
            payload = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
            raise web.HTTPBadRequest from None
        init_data = payload.get("init_data") if isinstance(payload, dict) else None
        if not isinstance(init_data, str) or not init_data:
            raise web.HTTPBadRequest

        settings = self.controller.settings
        assert settings.bot_id is not None
        try:
            identity = validate_telegram_init_data(
                init_data,
                bot_id=settings.bot_id,
                allowed_user_ids=settings.allowed_user_ids,
                max_age_seconds=AUTH_MAX_AGE_SECONDS,
                future_skew_seconds=AUTH_FUTURE_SKEW_SECONDS,
            )
        except TelegramAuthenticationError as exc:
            # This is Telegram Mini App authentication, not Home Assistant
            # user authentication. Avoid HA's global raised-401 ban path.
            raise web.HTTPForbidden from exc

        token, session = self.controller.sessions.create(
            identity.user_id,
            settings.bot_id,
        )
        response = _json_response(
            {
                "authenticated": True,
                "expires_at": session.expires_at,
            }
        )
        response.set_cookie(
            COOKIE_NAME,
            token,
            max_age=session.expires_at - session.issued_at,
            httponly=True,
            secure=True,
            samesite="Strict",
            path="/api/comelit/miniapp",
        )
        return response

    async def delete(self, request: web.Request) -> web.Response:
        token = self._session_token(request)
        if token:
            self.controller.sessions.delete(token)
        response = _json_response({"authenticated": False})
        response.del_cookie(COOKIE_NAME, path="/api/comelit/miniapp")
        return response


class MiniAppBootstrapView(_MiniAppView):
    url = "/api/comelit/miniapp/bootstrap"
    name = "api:comelit:miniapp:bootstrap"

    async def get(self, request: web.Request) -> web.Response:
        _token, session = self._require_session(request)
        return _json_response(self.controller.bootstrap(session))


class MiniAppStateView(_MiniAppView):
    url = "/api/comelit/miniapp/state"
    name = "api:comelit:miniapp:state"

    async def get(self, request: web.Request) -> web.Response:
        self._require_session(request)
        return _json_response(self.controller.state_payload())


class MiniAppDoorView(_MiniAppView):
    url = "/api/comelit/miniapp/door/{door}"
    name = "api:comelit:miniapp:door"

    async def post(self, request: web.Request, door: str) -> web.Response:
        self._require_miniapp_marker(request)
        token, _session = self._require_session(request)
        nonce = request.headers.get(ACTION_NONCE_HEADER, "")
        try:
            session = self.controller.sessions.consume_action_nonce(token, nonce)
        except MiniAppSessionError as exc:
            return _json_response(
                {"error": "invalid_action_nonce"},
                status=HTTPStatus.CONFLICT,
            )

        if door not in (DOOR_ENTRANCE, DOOR_GATE):
            raise web.HTTPNotFound

        try:
            await self.controller.async_press_door(door)
        except MiniAppOperationError as exc:
            return _json_response(
                {
                    "accepted": False,
                    "error": str(exc),
                    "action_nonce": session.action_nonce,
                },
                status=HTTPStatus.CONFLICT,
            )
        except HomeAssistantError:
            return _json_response(
                {
                    "accepted": False,
                    "error": "Home Assistant rejected the Door action",
                    "action_nonce": session.action_nonce,
                },
                status=HTTPStatus.BAD_GATEWAY,
            )

        return _json_response(
            {
                "accepted": True,
                "physical_effect_asserted": False,
                "action_nonce": session.action_nonce,
            }
        )


class MiniAppEntranceParkView(_MiniAppView):
    url = "/api/comelit/miniapp/entrance/park"
    name = "api:comelit:miniapp:entrance_park"

    async def post(self, request: web.Request) -> web.Response:
        self._require_miniapp_marker(request)
        self._require_session(request)
        try:
            result = await self.controller.async_park_webcodecs_entrance()
        except MiniAppOperationError as exc:
            return _json_response(
                {"error": str(exc)},
                status=HTTPStatus.CONFLICT,
            )
        return _json_response(result)


class MiniAppCameraStreamView(_MiniAppView):
    url = r"/api/comelit/miniapp/camera/{entity_id}/stream"
    name = "api:comelit:miniapp:camera_stream"

    async def post(self, request: web.Request, entity_id: str) -> web.Response:
        self._require_miniapp_marker(request)
        token, session = self._require_session(request)
        if not entity_id.startswith("camera."):
            raise web.HTTPNotFound

        try:
            url = await self.controller.async_create_camera_media(
                token,
                session,
                entity_id,
            )
        except (MiniAppOperationError, HomeAssistantError, TimeoutError):
            return _json_response(
                {"error": "camera_stream_unavailable"},
                status=HTTPStatus.CONFLICT,
            )
        return _json_response({"url": url})


class MiniAppCameraWebRTCView(_MiniAppView):
    url = r"/api/comelit/miniapp/camera/{entity_id}/webrtc"
    name = "api:comelit:miniapp:camera_webrtc"

    async def get(
        self,
        request: web.Request,
        entity_id: str,
    ) -> web.StreamResponse:
        _token, session = self._require_session(request)
        if not entity_id.startswith("camera."):
            raise web.HTTPNotFound

        try:
            camera = self.controller.get_webrtc_surveillance_camera(entity_id)
        except MiniAppOperationError as exc:
            raise web.HTTPConflict(text=str(exc)) from exc

        websocket = web.WebSocketResponse(
            heartbeat=20,
            max_msg_size=64 * 1024,
        )
        await websocket.prepare(request)

        session_id = uuid4().hex
        offer_seen = False
        pending_sends: set[asyncio.Task[None]] = set()

        def send_message(message) -> None:
            async def _send() -> None:
                if not websocket.closed:
                    await websocket.send_json(message.as_dict())

            task = self.controller.hass.async_create_task(_send())
            pending_sends.add(task)
            task.add_done_callback(pending_sends.discard)

        try:
            config = camera.async_get_webrtc_client_configuration().to_frontend_dict()
            await websocket.send_json(
                {
                    "type": "config",
                    **config,
                }
            )

            remaining = max(0.0, float(session.expires_at) - time.time())
            async with asyncio.timeout(remaining):
                async for message in websocket:
                    if message.type == WSMsgType.ERROR:
                        break
                    if message.type != WSMsgType.TEXT:
                        continue

                    try:
                        payload = json.loads(message.data)
                    except (json.JSONDecodeError, TypeError):
                        await websocket.send_json(
                            {"type": "error", "code": "invalid_message"}
                        )
                        continue

                    if not isinstance(payload, dict):
                        continue

                    message_type = payload.get("type")
                    if message_type == "close":
                        break

                    if message_type == "offer":
                        sdp = payload.get("sdp")
                        if offer_seen or not isinstance(sdp, str) or not sdp:
                            await websocket.send_json(
                                {"type": "error", "code": "invalid_offer"}
                            )
                            continue
                        offer_seen = True

                        # Mirror Home Assistant core exactly: expose the
                        # session id before provider offer handling begins so
                        # trickled local ICE candidates can arrive while the
                        # provider/go2rtc offer path is still being established.
                        await websocket.send_json(
                            {
                                "type": "session",
                                "session_id": session_id,
                            }
                        )
                        try:
                            await camera.async_handle_async_webrtc_offer(
                                sdp,
                                session_id,
                                send_message,
                            )
                        except HomeAssistantError as exc:
                            await websocket.send_json(
                                {
                                    "type": "error",
                                    "code": "webrtc_offer_failed",
                                    "message": str(exc),
                                }
                            )
                        continue

                    if message_type == "candidate":
                        candidate = payload.get("candidate")
                        if not offer_seen or not isinstance(candidate, dict):
                            continue
                        try:
                            candidate_init = RTCIceCandidateInit.from_dict(candidate)
                            await camera.async_on_webrtc_candidate(
                                session_id,
                                candidate_init,
                            )
                        except (
                            HomeAssistantError,
                            MissingField,
                            ValueError,
                            TypeError,
                        ):
                            await websocket.send_json(
                                {
                                    "type": "error",
                                    "code": "webrtc_candidate_failed",
                                }
                            )
                        continue
        except TimeoutError:
            if not websocket.closed:
                await websocket.send_json(
                    {"type": "error", "code": "miniapp_session_expired"}
                )
        finally:
            camera.close_webrtc_session(session_id)
            if pending_sends:
                await asyncio.gather(*tuple(pending_sends), return_exceptions=True)

        return websocket


def _validate_mse_command(data: str) -> str | None:
    if len(data.encode("utf-8", "ignore")) > MSE_MAX_COMMAND_BYTES:
        return None
    try:
        payload = json.loads(data)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(payload, dict) or set(payload) != {"type", "value"}:
        return None
    if payload.get("type") != "mse":
        return None
    value = payload.get("value")
    if not isinstance(value, str) or len(value) > 128:
        return None
    tokens = [token.strip() for token in value.split(",") if token.strip()]
    if not tokens or len(tokens) > 8:
        return None
    if any(token.lower() not in _MSE_CODECS for token in tokens):
        return None
    return ",".join(tokens)


def _sanitize_mse_upstream_text(data: str) -> dict[str, object] | None:
    try:
        payload = json.loads(data)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("type") != "mse":
        return None
    value = payload.get("value")
    if not isinstance(value, str) or len(value) > 128:
        return None
    if not value.startswith("video/mp4; codecs="):
        return None
    return {"type": "mse", "value": value}


def _parse_go2rtc_upstream_text(data: str) -> tuple[str, object]:
    try:
        payload = json.loads(data)
    except (json.JSONDecodeError, TypeError, ValueError):
        return "non_json", data
    if not isinstance(payload, dict):
        return "non_object", payload
    message_type = payload.get("type")
    if not isinstance(message_type, str):
        message_type = "unknown"
    return message_type, payload.get("value")


class MiniAppCameraMSEView(_MiniAppView):
    url = r"/api/comelit/miniapp/camera/{entity_id}/mse"
    name = "api:comelit:miniapp:camera_mse"

    async def get(
        self,
        request: web.Request,
        entity_id: str,
    ) -> web.StreamResponse:
        _token, session = self._require_session(request)
        if not entity_id.startswith("camera."):
            raise web.HTTPNotFound

        websocket = web.WebSocketResponse(
            heartbeat=20,
            max_msg_size=MSE_MAX_COMMAND_BYTES,
        )
        await websocket.prepare(request)

        server_started = time.monotonic()
        server_last = server_started

        def log_server_milestone(event: str) -> None:
            nonlocal server_last
            now = time.monotonic()
            elapsed_ms = max(0, round((now - server_started) * 1000))
            stage_ms = max(0, round((now - server_last) * 1000))
            server_last = now
            _LOGGER.info(
                format_server_log_line(
                    entity_id,
                    event,
                    elapsed_ms=elapsed_ms,
                    stage_ms=stage_ms,
                )
            )

        lease = None
        upstream = None
        pump_task: asyncio.Task[None] | None = None
        state_tasks: list[asyncio.Task[None]] = []

        async def log_go2rtc_state(delay: float, event: str) -> None:
            await asyncio.sleep(delay)
            if lease is None:
                return
            try:
                counters, raw_state = await self.controller.go2rtc.inspect_stream(
                    lease.internal_name
                )
            except MiniAppGo2RTCError:
                counters = {"inspect_ok": 0}
                raw_state = {"inspect_error": "go2rtc_http_error"}
            elapsed_ms = max(0, round((time.monotonic() - server_started) * 1000))
            _LOGGER.info(
                format_go2rtc_state_line(
                    entity_id,
                    event,
                    elapsed_ms=elapsed_ms,
                    counters=counters,
                )
            )
            _LOGGER.info(
                format_go2rtc_state_json_line(
                    entity_id,
                    event,
                    elapsed_ms=elapsed_ms,
                    state=raw_state,
                )
            )

        async def close_with_error(code: str) -> None:
            if not websocket.closed:
                await websocket.send_json({"type": "error", "code": code})
                await websocket.close()

        async def pump_upstream() -> None:
            assert upstream is not None
            reply_logged = False
            chunk_logged = False
            async for message in upstream:
                if websocket.closed:
                    break
                if message.type == WSMsgType.BINARY:
                    if not chunk_logged:
                        chunk_logged = True
                        log_server_milestone("mse_upstream_chunk")
                    await websocket.send_bytes(message.data)
                    continue
                if message.type == WSMsgType.TEXT:
                    message_type, value = _parse_go2rtc_upstream_text(message.data)
                    elapsed_ms = max(
                        0,
                        round((time.monotonic() - server_started) * 1000),
                    )
                    _LOGGER.info(
                        format_go2rtc_ws_line(
                            entity_id,
                            elapsed_ms=elapsed_ms,
                            frame_type=message_type,
                            value=value,
                        )
                    )
                    payload = _sanitize_mse_upstream_text(message.data)
                    if payload is not None:
                        if not reply_logged:
                            reply_logged = True
                            log_server_milestone("mse_upstream_reply")
                        await websocket.send_json(payload)
                    continue
                if message.type in (WSMsgType.CLOSE, WSMsgType.CLOSED, WSMsgType.ERROR):
                    await close_with_error("mse_ws_closed")
                    break

        try:
            try:
                first = await websocket.receive(timeout=5)
            except TimeoutError:
                await close_with_error("mse_negotiation_failed")
                return websocket
            if first.type != WSMsgType.TEXT:
                await close_with_error("invalid_mse_command")
                return websocket
            codecs = _validate_mse_command(first.data)
            if codecs is None:
                await close_with_error("invalid_mse_command")
                return websocket
            log_server_milestone("mse_command_received")

            try:
                lease = await self.controller.acquire_mse_stream(
                    entity_id,
                    progress=log_server_milestone,
                )
                upstream = await self.controller.go2rtc.open_mse_ws(
                    lease.internal_name
                )
                log_server_milestone("mse_upstream_ws_open")
            except MiniAppOperationError as exc:
                await close_with_error(str(exc))
                return websocket
            except MiniAppGo2RTCError as exc:
                await close_with_error(exc.code)
                return websocket
            except (HomeAssistantError, TimeoutError):
                await close_with_error("stream_source_unavailable")
                return websocket

            await upstream.send_json({"type": "mse", "value": codecs})
            log_server_milestone("mse_negotiation_forwarded")
            pump_task = self.controller.hass.async_create_task(pump_upstream())
            state_tasks = [
                self.controller.hass.async_create_task(
                    log_go2rtc_state(0.25, "stream_state_250ms")
                ),
                self.controller.hass.async_create_task(
                    log_go2rtc_state(4.0, "stream_state_4000ms")
                ),
                self.controller.hass.async_create_task(
                    log_go2rtc_state(7.0, "stream_state_7000ms")
                ),
            ]

            remaining = max(0.0, float(session.expires_at) - time.time())
            async with asyncio.timeout(remaining):
                async for message in websocket:
                    if message.type in (WSMsgType.ERROR, WSMsgType.CLOSE, WSMsgType.CLOSED):
                        break
                    if message.type != WSMsgType.TEXT:
                        await close_with_error("invalid_mse_command")
                        break
                    payload = json.loads(message.data) if message.data else {}
                    if isinstance(payload, dict) and payload.get("type") == "close":
                        break
                    await close_with_error("invalid_mse_command")
                    break
        except (json.JSONDecodeError, ValueError, TimeoutError):
            await close_with_error("mse_ws_closed")
        finally:
            for task in state_tasks:
                task.cancel()
            if state_tasks:
                await asyncio.gather(*state_tasks, return_exceptions=True)
            if pump_task is not None:
                pump_task.cancel()
                await asyncio.gather(pump_task, return_exceptions=True)
            if upstream is not None and not upstream.closed:
                await upstream.close()
            if lease is not None:
                await self.controller.release_mse_stream(lease.entity_id)

        return websocket


class MiniAppCameraWebCodecsView(_MiniAppView):
    url = r"/api/comelit/miniapp/camera/{entity_id}/webcodecs"
    name = "api:comelit:miniapp:camera_webcodecs"

    async def get(
        self,
        request: web.Request,
        entity_id: str,
    ) -> web.StreamResponse:
        _token, session = self._require_session(request)
        if not entity_id.startswith("camera."):
            raise web.HTTPNotFound

        try:
            target = self.controller.get_webcodecs_camera_target(entity_id)
        except MiniAppOperationError as exc:
            return _json_response({"error": str(exc)}, status=HTTPStatus.CONFLICT)

        websocket = web.WebSocketResponse(
            heartbeat=20,
            max_msg_size=webcodecs_mod.WEBCODECS_MAX_UNIT_BYTES
            + webcodecs_mod.WEBCODECS_HEADER_BYTES,
        )
        await websocket.prepare(request)

        started = time.monotonic()
        units = 0
        keyframes = 0
        bytes_sent = 0
        errors = 0
        reason = "client_close"
        first_source_logged = False
        first_binary_logged = False
        source_task: asyncio.Task[None] | None = None
        client_watch_task: asyncio.Task[None] | None = None
        entrance_lease = None
        queued_bytes = 0
        queued_units = 0
        queue: asyncio.Queue[object] = asyncio.Queue(
            maxsize=webcodecs_mod.WEBCODECS_MAX_QUEUE_UNITS + 4
        )

        def log_event(event: str) -> None:
            _LOGGER.info(
                webcodecs_mod.webcodecs_log_line(
                    entity_id,
                    event,
                    elapsed_ms=webcodecs_mod.monotonic_ms(started),
                    units=units,
                    bytes_sent=bytes_sent,
                )
            )

        async def send_json(payload: dict[str, object]) -> bool:
            nonlocal reason
            if websocket.closed:
                reason = "client_close"
                return False
            try:
                await websocket.send_json(payload)
            except _WEBSOCKET_SEND_ERRORS:
                reason = "client_close"
                return False
            return True

        async def send_bytes(payload: bytes) -> bool:
            nonlocal reason
            if websocket.closed:
                reason = "client_close"
                return False
            try:
                await websocket.send_bytes(payload)
            except _WEBSOCKET_SEND_ERRORS:
                reason = "client_close"
                return False
            return True

        async def close_with_error(code: str) -> None:
            nonlocal errors, reason
            errors += 1
            if code in {
                "session_limit",
                "backlog_exceeded",
                "source_open_failed",
                "intercom_media_busy",
                "intercom_media_start_failed",
                "intercom_media_unavailable",
            }:
                reason = code
            if not websocket.closed:
                await send_json({"type": "error", "code": code})
                with contextlib.suppress(*_WEBSOCKET_SEND_ERRORS):
                    await websocket.close()

        async def send_eos(eos_reason: str) -> None:
            nonlocal reason
            reason = eos_reason
            if not websocket.closed:
                await send_json({"type": "eos", "reason": eos_reason})
                with contextlib.suppress(*_WEBSOCKET_SEND_ERRORS):
                    await websocket.close()

        try:
            try:
                first = await websocket.receive(timeout=5)
            except TimeoutError:
                await close_with_error("invalid_webcodecs_command")
                return websocket
            if (
                first.type != WSMsgType.TEXT
                or not webcodecs_mod.validate_webcodecs_command(first.data)
            ):
                await close_with_error("invalid_webcodecs_command")
                return websocket

            try:
                lease = await webcodecs_mod.SESSION_REGISTRY.acquire(entity_id)
            except webcodecs_mod.WebCodecsSourceError:
                log_event("session_limit")
                await close_with_error("session_limit")
                return websocket

            async with lease:
                log_event("session_open")
                source_kind = "ordinary_rtsp"
                source_opener = webcodecs_mod.open_h264_access_unit_source
                if target.kind == "entrance":
                    try:
                        entrance_lease = await self.controller.acquire_webcodecs_entrance(
                            target
                        )
                    except MiniAppOperationError as exc:
                        await close_with_error(str(exc))
                        return websocket
                    source = str(entrance_lease.local_sdp_path)
                    source_kind = "comelit_entrance_rtp"
                    source_opener = webcodecs_mod.open_h264_sdp_access_unit_source
                    log_event("intercom_media_ready")
                    if not await send_json(
                        {
                            "type": "intercom_media_ready",
                            "server_elapsed_ms": webcodecs_mod.monotonic_ms(started),
                        }
                    ):
                        return websocket

                else:
                    camera = target.camera
                    if camera is None:
                        await close_with_error("source_open_failed")
                        return websocket
                    try:
                        source = await camera.stream_source()
                    except Exception:
                        log_event("source_open_failed")
                        await close_with_error("source_open_failed")
                        return websocket
                    if not webcodecs_mod.is_rtsp_source(source):
                        await close_with_error("source_not_h264_rtsp")
                        return websocket

                async def watch_webcodecs_client_close() -> None:
                    try:
                        async for message in websocket:
                            if message.type in {
                                WSMsgType.CLOSE,
                                WSMsgType.CLOSED,
                                WSMsgType.ERROR,
                            }:
                                break
                            # No post-start commands are accepted for either
                            # Entrance or ordinary WebCodecs sessions. Treat
                            # any further client message as a fail-closed
                            # termination request.
                            break
                    except _WEBSOCKET_SEND_ERRORS:
                        pass
                    log_event("client_close")
                    await queue.put(("client_close", "client_close"))

                # Exactly one receive-side owner is created after the initial
                # WebCodecs command. This keeps ordinary RTSP sessions from
                # waiting for a later send failure before noticing that the
                # embedded viewer has left the DOM.
                client_watch_task = self.controller.hass.async_create_task(
                    watch_webcodecs_client_close()
                )
                log_event("source_resolved")

                async def produce_units() -> None:
                    nonlocal queued_bytes, queued_units
                    unit_source: webcodecs_mod.H264AccessUnitSource | None = None
                    send_source_eof = True
                    first_source_packet_queued = False
                    try:
                        unit_source = await source_opener(source)
                        await queue.put(
                            ("source_open", webcodecs_mod.monotonic_ms(started))
                        )
                        async for unit in unit_source:
                            if not first_source_packet_queued:
                                first_source_packet_queued = True
                                await queue.put(
                                    (
                                        "source_packet",
                                        webcodecs_mod.monotonic_ms(started),
                                    )
                                )
                            size = len(unit.payload)
                            if size > webcodecs_mod.WEBCODECS_MAX_UNIT_BYTES:
                                send_source_eof = False
                                await queue.put(("error", "unit_too_large"))
                                return
                            if (
                                queued_units
                                >= webcodecs_mod.WEBCODECS_MAX_QUEUE_UNITS
                                or queued_bytes + size
                                > webcodecs_mod.WEBCODECS_MAX_QUEUE_BYTES
                            ):
                                send_source_eof = False
                                await queue.put(("error", "backlog_exceeded"))
                                return
                            await queue.put(unit)
                            queued_units += 1
                            queued_bytes += size
                    except asyncio.CancelledError:
                        send_source_eof = False
                        raise
                    except webcodecs_mod.WebCodecsSourceError as exc:
                        send_source_eof = False
                        await queue.put(("error", exc.code))
                    except Exception:
                        send_source_eof = False
                        await queue.put(("error", "source_open_failed"))
                    finally:
                        if unit_source is not None:
                            await unit_source.aclose()
                        if send_source_eof:
                            await queue.put(("eos", "source_eof"))

                source_task = self.controller.hass.async_create_task(produce_units())
                target_session_max_seconds = (
                    webcodecs_mod.WEBCODECS_ENTRANCE_MAX_SESSION_SECONDS
                    if target.kind == "entrance"
                    else webcodecs_mod.WEBCODECS_MAX_SESSION_SECONDS
                )
                duration = min(
                    target_session_max_seconds,
                    max(0.0, float(session.expires_at) - time.time()),
                )
                codec: str | None = None
                sequence = 0
                send_origin_ns: int | None = None

                try:
                    async with asyncio.timeout(duration):
                        while not websocket.closed:
                            item = await queue.get()
                            if isinstance(item, tuple):
                                kind, code = item
                                if kind == "source_open":
                                    log_event("source_open")
                                    if not await send_json(
                                        {
                                            "type": "source_open",
                                            "server_elapsed_ms": int(code),
                                        }
                                    ):
                                        break
                                    continue
                                if kind == "source_packet":
                                    if not await send_json(
                                        {
                                            "type": "source_packet",
                                            "server_elapsed_ms": int(code),
                                        }
                                    ):
                                        break
                                    continue
                                if kind == "client_close":
                                    reason = "client_close"
                                    break
                                if kind == "error":
                                    if code == "unit_too_large":
                                        log_event("unit_too_large")
                                    elif code == "backlog_exceeded":
                                        log_event("backlog_exceeded")
                                    else:
                                        log_event("source_open_failed")
                                    await close_with_error(str(code))
                                    break
                                if kind == "eos":
                                    log_event("source_eof")
                                    await send_eos(str(code))
                                    break
                                continue

                            assert isinstance(item, webcodecs_mod.H264AccessUnit)
                            queued_units = max(0, queued_units - 1)
                            queued_bytes = max(0, queued_bytes - len(item.payload))
                            if not first_source_logged:
                                first_source_logged = True
                                log_event("first_source_packet")
                            if item.codec:
                                codec = item.codec
                            if codec is None:
                                sps, _pps = webcodecs_mod.split_sps_pps(item.payload)
                                codec = webcodecs_mod.derive_avc1_codec_from_sps(
                                    sps[0] if sps else None
                                )
                            if codec is None:
                                await close_with_error("source_open_failed")
                                break
                            if sequence == 0:
                                if not await send_json(
                                    {
                                        "type": "hello",
                                        "protocol": webcodecs_mod.WEBCODECS_PROTOCOL_VERSION,
                                        "entity_id": entity_id,
                                        "codec": codec,
                                        "max_unit_bytes": webcodecs_mod.WEBCODECS_MAX_UNIT_BYTES,
                                        "session_max_seconds": target_session_max_seconds,
                                        "zero_transcode": True,
                                        "source_kind": source_kind,
                                        "comelit_entrance_open": target.kind == "entrance",
                                        "comelit_media_started": target.kind == "entrance",
                                    }
                                ):
                                    break
                            sequence += 1
                            send_now_ns = time.monotonic_ns()
                            if send_origin_ns is None:
                                send_origin_ns = send_now_ns
                            send_elapsed_us = max(
                                0,
                                (send_now_ns - send_origin_ns) // 1000,
                            )
                            frame = webcodecs_mod.WebCodecsFrame(
                                sequence=sequence,
                                media_pts_us=item.media_pts_us or 0,
                                pts_valid=item.media_pts_us is not None,
                                keyframe=item.keyframe,
                                payload=item.payload,
                                source_elapsed_us=item.source_elapsed_us,
                                send_elapsed_us=send_elapsed_us,
                            )
                            if not await send_bytes(
                                webcodecs_mod.encode_webcodecs_frame(frame)
                            ):
                                break
                            units += 1
                            bytes_sent += len(item.payload)
                            if item.keyframe:
                                keyframes += 1
                            if not first_binary_logged:
                                first_binary_logged = True
                                log_event("first_binary")
                except TimeoutError:
                    await send_eos("duration_limit")
        finally:
            if source_task is not None:
                source_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await source_task
            if client_watch_task is not None:
                client_watch_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await client_watch_task
            if entrance_lease is not None:
                try:
                    await entrance_lease.release()
                except Exception:
                    errors += 1
                    _LOGGER.exception(
                        "Comelit Mini App WebCodecs entrance media release failed"
                    )
            log_event("session_close")
            _LOGGER.info(
                webcodecs_mod.webcodecs_summary_line(
                    entity_id,
                    units=units,
                    keyframes=keyframes,
                    bytes_sent=bytes_sent,
                    errors=errors,
                    reason=reason,
                )
            )

        return websocket


class MiniAppCameraDiagnosticsView(_MiniAppView):
    url = r"/api/comelit/miniapp/camera/{entity_id}/diagnostics"
    name = "api:comelit:miniapp:camera_diagnostics"

    def __init__(self, controller: ComelitMiniAppController) -> None:
        super().__init__(controller)
        self._rate_limiter = MiniAppDiagnosticsRateLimiter()

    async def post(self, request: web.Request, entity_id: str) -> web.Response:
        self._require_miniapp_marker(request)
        token, session = self._require_session(request)
        if (
            not entity_id.startswith("camera.")
            or entity_id not in self.controller._allowed_camera_entity_ids()
        ):
            raise web.HTTPNotFound

        body = await request.content.read(2049)
        try:
            payload = loads_limited(body)
            line = format_log_line(entity_id, payload)
        except MiniAppDiagnosticsError:
            return _json_response(
                {"error": "invalid_diagnostics_event"},
                status=HTTPStatus.BAD_REQUEST,
            )
        if not self._rate_limiter.accept(
            token,
            entity_id,
            expires_at=float(session.expires_at),
            now=time.time(),
        ):
            return _json_response(
                {"error": "diagnostics_rate_limited"},
                status=HTTPStatus.TOO_MANY_REQUESTS,
            )

        _LOGGER.info(line)
        return _json_response({"ok": True})


class MiniAppMediaView(_MiniAppView):
    url = r"/api/comelit/miniapp/media/{media_id}/{tail:.*}"
    name = "api:comelit:miniapp:media"

    async def get(
        self,
        request: web.Request,
        media_id: str,
        tail: str,
    ) -> web.StreamResponse:
        token, _session = self._require_session(request)
        try:
            upstream_path = self.controller.resolve_media_upstream_path(
                media_id,
                token,
                tail,
            )
        except MiniAppOperationError as exc:
            raise web.HTTPNotFound from exc

        try:
            base = get_url(
                self.controller.hass,
                allow_internal=True,
                allow_external=False,
                prefer_external=False,
                allow_cloud=False,
            )
        except (NoURLAvailableError, ValueError) as exc:
            raise web.HTTPServiceUnavailable from exc

        upstream_url = urljoin(
            base.rstrip("/") + "/",
            upstream_path.lstrip("/"),
        )
        if request.query_string:
            upstream_url = f"{upstream_url}?{request.query_string}"

        forward_headers: dict[str, str] = {}
        if range_header := request.headers.get("Range"):
            forward_headers["Range"] = range_header

        client = async_get_clientsession(self.controller.hass)
        try:
            async with client.get(
                upstream_url,
                headers=forward_headers,
                allow_redirects=False,
            ) as upstream:
                headers = {
                    "Cache-Control": "no-store",
                    "X-Content-Type-Options": "nosniff",
                }
                for header in ("Content-Type", "Content-Range", "Accept-Ranges"):
                    if value := upstream.headers.get(header):
                        headers[header] = value

                response = web.StreamResponse(
                    status=upstream.status,
                    headers=headers,
                )
                await response.prepare(request)
                try:
                    async for chunk in upstream.content.iter_chunked(64 * 1024):
                        await response.write(chunk)
                except ConnectionResetError:
                    pass
                return response
        except TimeoutError as exc:
            raise web.HTTPGatewayTimeout from exc
        except ClientError as exc:
            raise web.HTTPBadGateway from exc


def async_register_miniapp_views(
    hass: HomeAssistant,
    controller: ComelitMiniAppController,
) -> None:
    """Register embedded Mini App views on Home Assistant's HTTP server."""
    hass.http.register_view(MiniAppIndexView(controller))
    hass.http.register_view(MiniAppSessionView(controller))
    hass.http.register_view(MiniAppBootstrapView(controller))
    hass.http.register_view(MiniAppStateView(controller))
    hass.http.register_view(MiniAppDoorView(controller))
    hass.http.register_view(MiniAppEntranceParkView(controller))
    hass.http.register_view(MiniAppCameraStreamView(controller))
    hass.http.register_view(MiniAppCameraMSEView(controller))
    hass.http.register_view(MiniAppCameraWebCodecsView(controller))
    hass.http.register_view(MiniAppCameraWebRTCView(controller))
    hass.http.register_view(MiniAppCameraDiagnosticsView(controller))
    hass.http.register_view(MiniAppMediaView(controller))
