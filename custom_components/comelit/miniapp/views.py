from __future__ import annotations

from http import HTTPStatus
import json

from aiohttp import web

from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from ..const import DOOR_ENTRANCE, DOOR_GATE
from .auth import TelegramAuthenticationError, validate_telegram_init_data
from .controller import ComelitMiniAppController, MiniAppOperationError
from .session import MiniAppSession, MiniAppSessionError


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
            raise web.HTTPUnauthorized from exc
        if not self.controller.session_is_allowed(session):
            self.controller.sessions.delete(token)
            raise web.HTTPUnauthorized
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
        body = await request.read()
        if len(body) > MAX_AUTH_BODY_BYTES:
            raise web.HTTPRequestEntityTooLarge(
                max_size=MAX_AUTH_BODY_BYTES,
                actual_size=len(body),
            )
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
            raise web.HTTPUnauthorized from exc

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
        self._require_session(request)
        if not entity_id.startswith("camera."):
            raise web.HTTPNotFound

        try:
            url = await self.controller.async_camera_stream_url(entity_id)
        except (MiniAppOperationError, HomeAssistantError):
            return _json_response(
                {"error": "camera_stream_unavailable"},
                status=HTTPStatus.CONFLICT,
            )
        return _json_response({"url": url})


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
