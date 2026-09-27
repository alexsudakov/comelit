from __future__ import annotations

import base64
from dataclasses import dataclass
import json
import time
from urllib.parse import parse_qsl

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


TELEGRAM_PRODUCTION_PUBLIC_KEY_HEX = (
    "e7bf03a2fa4602af4580703d88dda5bb59f32ed8b02a56c187fe7d34caed242d"
)


class TelegramAuthenticationError(ValueError):
    """Raised when Telegram Mini App initData cannot be authenticated."""


@dataclass(frozen=True, slots=True)
class TelegramIdentity:
    """Authenticated Telegram Mini App identity."""

    user_id: int
    auth_date: int
    query_id: str | None = None


def _decode_base64url(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    try:
        decoded = base64.urlsafe_b64decode(value + padding)
    except Exception as exc:
        raise TelegramAuthenticationError("invalid Telegram signature encoding") from exc
    if len(decoded) != 64:
        raise TelegramAuthenticationError("invalid Telegram signature length")
    return decoded


def validate_telegram_init_data(
    init_data: str,
    *,
    bot_id: int,
    allowed_user_ids: frozenset[int],
    max_age_seconds: int = 300,
    future_skew_seconds: int = 30,
    now: int | None = None,
    public_key_bytes: bytes | None = None,
) -> TelegramIdentity:
    """Validate raw Telegram.WebApp.initData using Telegram's Ed25519 key."""
    if bot_id <= 0:
        raise TelegramAuthenticationError("invalid Telegram bot id")
    if not allowed_user_ids:
        raise TelegramAuthenticationError("Telegram user allowlist is empty")
    if not init_data:
        raise TelegramAuthenticationError("missing Telegram initData")

    try:
        pairs = parse_qsl(init_data, keep_blank_values=True, strict_parsing=True)
    except ValueError as exc:
        raise TelegramAuthenticationError("invalid Telegram initData query") from exc

    fields: dict[str, str] = {}
    for key, value in pairs:
        if key in fields:
            raise TelegramAuthenticationError("duplicate Telegram initData field")
        fields[key] = value

    signature_raw = fields.pop("signature", None)
    if not signature_raw:
        raise TelegramAuthenticationError("Telegram initData signature is missing")
    fields.pop("hash", None)

    data_check_string = (
        f"{bot_id}:WebAppData\n"
        + "\n".join(f"{key}={fields[key]}" for key in sorted(fields))
    )

    public_key = Ed25519PublicKey.from_public_bytes(
        public_key_bytes
        if public_key_bytes is not None
        else bytes.fromhex(TELEGRAM_PRODUCTION_PUBLIC_KEY_HEX)
    )
    try:
        public_key.verify(
            _decode_base64url(signature_raw),
            data_check_string.encode("utf-8"),
        )
    except InvalidSignature as exc:
        raise TelegramAuthenticationError("invalid Telegram initData signature") from exc

    try:
        auth_date = int(fields["auth_date"])
    except (KeyError, TypeError, ValueError) as exc:
        raise TelegramAuthenticationError("invalid Telegram auth_date") from exc

    current = int(time.time()) if now is None else int(now)
    if auth_date > current + future_skew_seconds:
        raise TelegramAuthenticationError("Telegram auth_date is in the future")
    if current - auth_date > max_age_seconds:
        raise TelegramAuthenticationError("Telegram initData expired")

    try:
        user = json.loads(fields["user"])
        user_id = int(user["id"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise TelegramAuthenticationError("invalid Telegram user") from exc

    if user_id <= 0 or user_id not in allowed_user_ids:
        raise TelegramAuthenticationError("Telegram user is not allowed")

    return TelegramIdentity(
        user_id=user_id,
        auth_date=auth_date,
        query_id=fields.get("query_id"),
    )
