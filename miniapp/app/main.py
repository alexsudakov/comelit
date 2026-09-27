from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import Cookie, Depends, FastAPI, Header, HTTPException, Response, status
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import Settings
from .ha_client import (
    HomeAssistantClient,
    HomeAssistantError,
    HomeAssistantNotConfigured,
)
from .security import (
    AuthenticationError,
    AuthenticationNotConfigured,
    SessionIdentity,
    issue_session_token,
    validate_telegram_init_data,
    verify_session_token,
)


STATIC_DIR = Path(__file__).with_name("static")
DEFAULT_CARD_PATH = (
    Path(__file__).resolve().parents[2]
    / "custom_components"
    / "comelit"
    / "frontend"
    / "comelit-card.js"
)


class TelegramAuthRequest(BaseModel):
    init_data: str = Field(min_length=1, max_length=16_384)


class TelegramAuthResponse(BaseModel):
    authenticated: bool
    expires_at: int


class ButtonPressRequest(BaseModel):
    entity_id: str = Field(min_length=1, max_length=255)


def create_app(
    settings: Settings | None = None,
    ha_client: HomeAssistantClient | None = None,
    *,
    card_path: Path | None = None,
) -> FastAPI:
    settings = settings or Settings.from_env()
    client = ha_client or HomeAssistantClient(
        settings.ha_base_url,
        settings.ha_token,
        surveillance_entities=settings.surveillance_entities,
    )
    card_path = card_path or Path(
        os.getenv("COMELIT_MINIAPP_CARD_PATH", str(DEFAULT_CARD_PATH))
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        close = getattr(app.state.ha_client, "close", None)
        if close is not None:
            await close()

    app = FastAPI(
        title="Comelit Telegram Mini App",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.ha_client = client
    app.state.card_path = card_path
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.middleware("http")
    async def security_headers(request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Cache-Control", "no-store")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; "
            "script-src 'self' https://telegram.org; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob:; "
            "connect-src 'self'; "
            "object-src 'none'; base-uri 'none'; form-action 'none'",
        )
        return response

    def current_session(
        session_cookie: str | None = Cookie(
            default=None,
            alias=settings.cookie_name,
        ),
    ) -> SessionIdentity:
        try:
            return verify_session_token(session_cookie or "", settings)
        except AuthenticationNotConfigured as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="telegram_authentication_not_configured",
            ) from exc
        except AuthenticationError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="authentication_required",
            ) from exc

    def require_miniapp_request(
        marker: str | None = Header(default=None, alias="X-Comelit-MiniApp-Request"),
    ) -> None:
        if marker != "1":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="miniapp_request_header_required",
            )

    def require_ha() -> HomeAssistantClient:
        if not settings.ha_configured or not client.configured:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="home_assistant_not_configured",
            )
        return client

    @app.get("/")
    async def index():
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/assets/comelit-card.js")
    async def comelit_card_asset():
        if not card_path.is_file():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="comelit_card_asset_missing",
            )
        return FileResponse(
            card_path,
            media_type="text/javascript",
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/health")
    async def health():
        return {
            "status": "ok",
            "service": "comelit-miniapp",
            "version": "0.1.0",
            "shared_card_present": card_path.is_file(),
            **settings.safe_summary(),
        }

    @app.post("/api/auth/telegram", response_model=TelegramAuthResponse)
    async def authenticate(payload: TelegramAuthRequest, response: Response):
        try:
            identity = validate_telegram_init_data(payload.init_data, settings)
            token, session = issue_session_token(identity.user_id, settings)
        except AuthenticationNotConfigured as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="telegram_authentication_not_configured",
            ) from exc
        except AuthenticationError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="telegram_authentication_failed",
            ) from exc

        response.set_cookie(
            settings.cookie_name,
            token,
            max_age=settings.session_ttl_seconds,
            expires=settings.session_ttl_seconds,
            path="/",
            secure=settings.cookie_secure,
            httponly=True,
            samesite=settings.cookie_samesite,
        )
        return TelegramAuthResponse(
            authenticated=True,
            expires_at=session.expires_at,
        )

    @app.post("/api/logout", status_code=status.HTTP_204_NO_CONTENT)
    async def logout(response: Response):
        response.delete_cookie(
            settings.cookie_name,
            path="/",
            secure=settings.cookie_secure,
            httponly=True,
            samesite=settings.cookie_samesite,
        )

    @app.get("/api/session")
    async def session(identity: SessionIdentity = Depends(current_session)):
        return {
            "authenticated": True,
            "user_id": identity.user_id,
            "expires_at": identity.expires_at,
        }

    @app.get("/api/ha/bootstrap")
    async def ha_bootstrap(
        identity: SessionIdentity = Depends(current_session),
        ha: HomeAssistantClient = Depends(require_ha),
    ):
        del identity
        try:
            return await ha.bootstrap()
        except HomeAssistantNotConfigured as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="home_assistant_not_configured",
            ) from exc
        except HomeAssistantError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=str(exc),
            ) from exc

    @app.post("/api/ha/button-press")
    async def ha_button_press(
        payload: ButtonPressRequest,
        identity: SessionIdentity = Depends(current_session),
        _request_marker: None = Depends(require_miniapp_request),
        ha: HomeAssistantClient = Depends(require_ha),
    ):
        del identity, _request_marker
        try:
            return await ha.press_door(payload.entity_id)
        except HomeAssistantError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=str(exc),
            ) from exc

    @app.get("/api/ha/camera/{entity_id}/mjpeg")
    async def ha_camera_mjpeg(
        entity_id: str,
        identity: SessionIdentity = Depends(current_session),
        ha: HomeAssistantClient = Depends(require_ha),
    ):
        del identity
        try:
            stream = await ha.open_camera_mjpeg(entity_id)
        except HomeAssistantError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=str(exc),
            ) from exc

        async def iter_upstream() -> AsyncIterator[bytes]:
            try:
                async for chunk in stream.response.aiter_raw():
                    yield chunk
            finally:
                await stream.response.aclose()

        return StreamingResponse(
            iter_upstream(),
            media_type=stream.media_type,
            headers={"Cache-Control": "no-store"},
        )

    return app


app = create_app()
