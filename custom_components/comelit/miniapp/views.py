from __future__ import annotations

import asyncio
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
    MiniAppDiagnosticsError,
    format_log_line,
    loads_limited,
)
from .session import MiniAppSession, MiniAppSessionError


_LOGGER = logging.getLogger(__name__)
COOKIE_NAME = "comelit_miniapp_session"
AUTH_MAX_AGE_SECONDS = 300
AUTH_FUTURE_SKEW_SECONDS = 30
MAX_AUTH_BODY_BYTES = 20_000
MINIAPP_MARKER_HEADER = "X-Comelit-MiniApp-Request"
ACTION_NONCE_HEADER = "X-Comelit-Action-Nonce"


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


class MiniAppCameraDiagnosticsView(_MiniAppView):
    url = r"/api/comelit/miniapp/camera/{entity_id}/diagnostics"
    name = "api:comelit:miniapp:camera_diagnostics"

    async def post(self, request: web.Request, entity_id: str) -> web.Response:
        self._require_miniapp_marker(request)
        self._require_session(request)
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
    hass.http.register_view(MiniAppCameraStreamView(controller))
    hass.http.register_view(MiniAppCameraWebRTCView(controller))
    hass.http.register_view(MiniAppCameraDiagnosticsView(controller))
    hass.http.register_view(MiniAppMediaView(controller))
