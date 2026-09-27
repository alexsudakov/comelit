from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from urllib.parse import parse_qsl

from .config import Settings


class AuthenticationError(ValueError):
    """Raised when Telegram or Mini App session authentication fails."""


class AuthenticationNotConfigured(AuthenticationError):
    """Raised when mandatory authentication settings are absent."""


@dataclass(frozen=True)
class TelegramIdentity:
    user_id: int
    auth_date: int
    query_id: str | None = None


@dataclass(frozen=True)
class SessionIdentity:
    user_id: int
    issued_at: int
    expires_at: int


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    try:
        return base64.urlsafe_b64decode(data + padding)
    except Exception as exc:
        raise AuthenticationError("invalid session encoding") from exc


def validate_telegram_init_data(
    init_data: str,
    settings: Settings,
    *,
    now: int | None = None,
) -> TelegramIdentity:
    if not settings.telegram_auth_configured:
        raise AuthenticationNotConfigured("Telegram authentication is not configured")
    if not init_data:
        raise AuthenticationError("missing initData")

    try:
        pairs = parse_qsl(init_data, keep_blank_values=True, strict_parsing=True)
    except ValueError as exc:
        raise AuthenticationError("invalid initData query") from exc

    fields: dict[str, str] = {}
    for key, value in pairs:
        if key in fields:
            raise AuthenticationError("duplicate initData field")
        fields[key] = value

    received_hash = fields.pop("hash", "")
    if len(received_hash) != 64:
        raise AuthenticationError("invalid initData hash")
    try:
        bytes.fromhex(received_hash)
    except ValueError as exc:
        raise AuthenticationError("invalid initData hash") from exc

    data_check_string = "\n".join(
        f"{key}={fields[key]}" for key in sorted(fields)
    )
    secret_key = hmac.new(
        b"WebAppData",
        settings.telegram_bot_token.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    calculated_hash = hmac.new(
        secret_key,
        data_check_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(calculated_hash, received_hash):
        raise AuthenticationError("invalid initData signature")

    try:
        auth_date = int(fields["auth_date"])
    except (KeyError, TypeError, ValueError) as exc:
        raise AuthenticationError("invalid auth_date") from exc

    current = int(time.time()) if now is None else int(now)
    if auth_date > current + settings.future_skew_seconds:
        raise AuthenticationError("auth_date is in the future")
    if current - auth_date > settings.auth_max_age_seconds:
        raise AuthenticationError("initData expired")

    try:
        user = json.loads(fields["user"])
        user_id = int(user["id"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise AuthenticationError("invalid Telegram user") from exc

    if user_id not in settings.allowed_user_ids:
        raise AuthenticationError("Telegram user is not allowed")

    return TelegramIdentity(
        user_id=user_id,
        auth_date=auth_date,
        query_id=fields.get("query_id"),
    )


def issue_session_token(
    user_id: int,
    settings: Settings,
    *,
    now: int | None = None,
) -> tuple[str, SessionIdentity]:
    if not settings.telegram_auth_configured:
        raise AuthenticationNotConfigured("Telegram authentication is not configured")

    issued_at = int(time.time()) if now is None else int(now)
    identity = SessionIdentity(
        user_id=user_id,
        issued_at=issued_at,
        expires_at=issued_at + settings.session_ttl_seconds,
    )
    payload = json.dumps(
        {
            "v": 1,
            "uid": identity.user_id,
            "iat": identity.issued_at,
            "exp": identity.expires_at,
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    payload_part = _b64url_encode(payload)
    signature = hmac.new(
        settings.session_secret.encode("utf-8"),
        payload_part.encode("ascii"),
        hashlib.sha256,
    ).digest()
    return f"{payload_part}.{_b64url_encode(signature)}", identity


def verify_session_token(
    token: str,
    settings: Settings,
    *,
    now: int | None = None,
) -> SessionIdentity:
    if not settings.telegram_auth_configured:
        raise AuthenticationNotConfigured("Telegram authentication is not configured")
    if not token:
        raise AuthenticationError("missing session")

    parts = token.split(".")
    if len(parts) != 2:
        raise AuthenticationError("invalid session")
    payload_part, signature_part = parts

    expected = hmac.new(
        settings.session_secret.encode("utf-8"),
        payload_part.encode("ascii"),
        hashlib.sha256,
    ).digest()
    received = _b64url_decode(signature_part)
    if not hmac.compare_digest(expected, received):
        raise AuthenticationError("invalid session signature")

    try:
        payload = json.loads(_b64url_decode(payload_part))
        if payload.get("v") != 1:
            raise AuthenticationError("unsupported session version")
        identity = SessionIdentity(
            user_id=int(payload["uid"]),
            issued_at=int(payload["iat"]),
            expires_at=int(payload["exp"]),
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise AuthenticationError("invalid session payload") from exc

    current = int(time.time()) if now is None else int(now)
    if identity.expires_at <= current:
        raise AuthenticationError("session expired")
    if identity.issued_at > current + settings.future_skew_seconds:
        raise AuthenticationError("invalid session time")
    if identity.user_id not in settings.allowed_user_ids:
        raise AuthenticationError("session user is not allowed")
    return identity
