from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return int(raw)


def _parse_positive_ints(raw: str) -> frozenset[int]:
    result: set[int] = set()
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        value = int(item)
        if value <= 0:
            raise ValueError("Telegram user ids must be positive integers")
        result.add(value)
    return frozenset(result)


def _parse_camera_entities(raw: str) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for item in raw.split(","):
        entity_id = item.strip()
        if not entity_id:
            continue
        if not entity_id.startswith("camera.") or entity_id in seen:
            if not entity_id.startswith("camera."):
                raise ValueError("surveillance entities must be camera.* entity ids")
            continue
        seen.add(entity_id)
        result.append(entity_id)
    return tuple(result)


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str = field(default="", repr=False)
    allowed_user_ids: frozenset[int] = field(default_factory=frozenset)
    session_secret: str = field(default="", repr=False)
    ha_base_url: str = ""
    ha_token: str = field(default="", repr=False)
    surveillance_entities: tuple[str, ...] = ()
    auth_max_age_seconds: int = 300
    session_ttl_seconds: int = 900
    future_skew_seconds: int = 30
    cookie_name: str = "comelit_miniapp_session"
    cookie_secure: bool = True
    cookie_samesite: str = "lax"

    @classmethod
    def from_env(cls) -> "Settings":
        samesite = os.getenv("COMELIT_MINIAPP_COOKIE_SAMESITE", "lax").strip().lower()
        if samesite not in {"lax", "strict", "none"}:
            raise ValueError("COMELIT_MINIAPP_COOKIE_SAMESITE must be lax, strict or none")

        cookie_secure = _env_bool("COMELIT_MINIAPP_COOKIE_SECURE", True)
        if samesite == "none" and not cookie_secure:
            raise ValueError("SameSite=None requires Secure cookies")

        return cls(
            telegram_bot_token=os.getenv("COMELIT_MINIAPP_TELEGRAM_BOT_TOKEN", ""),
            allowed_user_ids=_parse_positive_ints(
                os.getenv("COMELIT_MINIAPP_ALLOWED_USER_IDS", "")
            ),
            session_secret=os.getenv("COMELIT_MINIAPP_SESSION_SECRET", ""),
            ha_base_url=os.getenv("COMELIT_MINIAPP_HA_BASE_URL", "").rstrip("/"),
            ha_token=os.getenv("COMELIT_MINIAPP_HA_TOKEN", ""),
            surveillance_entities=_parse_camera_entities(
                os.getenv("COMELIT_MINIAPP_SURVEILLANCE_ENTITIES", "")
            ),
            auth_max_age_seconds=_env_int(
                "COMELIT_MINIAPP_AUTH_MAX_AGE_SECONDS", 300
            ),
            session_ttl_seconds=_env_int(
                "COMELIT_MINIAPP_SESSION_TTL_SECONDS", 900
            ),
            future_skew_seconds=_env_int(
                "COMELIT_MINIAPP_FUTURE_SKEW_SECONDS", 30
            ),
            cookie_secure=cookie_secure,
            cookie_samesite=samesite,
        )

    @property
    def telegram_auth_configured(self) -> bool:
        return (
            bool(self.telegram_bot_token)
            and bool(self.allowed_user_ids)
            and len(self.session_secret.encode("utf-8")) >= 32
            and self.auth_max_age_seconds > 0
            and self.session_ttl_seconds > 0
            and self.future_skew_seconds >= 0
        )

    @property
    def ha_configured(self) -> bool:
        return bool(self.ha_base_url) and bool(self.ha_token)

    def safe_summary(self) -> dict[str, object]:
        return {
            "telegram_auth_configured": self.telegram_auth_configured,
            "ha_configured": self.ha_configured,
            "allowed_user_count": len(self.allowed_user_ids),
            "surveillance_entity_count": len(self.surveillance_entities),
            "auth_max_age_seconds": self.auth_max_age_seconds,
            "session_ttl_seconds": self.session_ttl_seconds,
            "cookie_secure": self.cookie_secure,
            "cookie_samesite": self.cookie_samesite,
        }
