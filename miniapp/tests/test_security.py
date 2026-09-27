import hashlib
import hmac
import json
from urllib.parse import urlencode

import pytest

from app.config import Settings
from app.security import (
    AuthenticationError,
    AuthenticationNotConfigured,
    issue_session_token,
    validate_telegram_init_data,
    verify_session_token,
)


BOT_TOKEN = "123456:TEST_BOT_TOKEN"
SESSION_SECRET = "s" * 48
ALLOWED_USER = 424242
NOW = 1_800_000_000


def settings(**overrides):
    base = dict(
        telegram_bot_token=BOT_TOKEN,
        allowed_user_ids=frozenset({ALLOWED_USER}),
        session_secret=SESSION_SECRET,
        ha_base_url="http://ha.local:8123",
        ha_token="ha-test-token",
        auth_max_age_seconds=300,
        session_ttl_seconds=900,
        future_skew_seconds=30,
        cookie_secure=False,
    )
    base.update(overrides)
    return Settings(**base)


def signed_init_data(*, user_id=ALLOWED_USER, auth_date=NOW, token=BOT_TOKEN):
    fields = {
        "auth_date": str(auth_date),
        "query_id": "AAE-test",
        "user": json.dumps(
            {"id": user_id, "first_name": "Test"},
            separators=(",", ":"),
        ),
    }
    data_check = "\n".join(f"{key}={fields[key]}" for key in sorted(fields))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


def test_valid_telegram_init_data():
    identity = validate_telegram_init_data(signed_init_data(), settings(), now=NOW)
    assert identity.user_id == ALLOWED_USER
    assert identity.auth_date == NOW


def test_invalid_hash_fails_closed():
    raw = signed_init_data().replace("hash=", "hash=0", 1)
    with pytest.raises(AuthenticationError):
        validate_telegram_init_data(raw, settings(), now=NOW)


def test_expired_init_data_fails_closed():
    with pytest.raises(AuthenticationError, match="expired"):
        validate_telegram_init_data(
            signed_init_data(auth_date=NOW - 301),
            settings(),
            now=NOW,
        )


def test_disallowed_user_fails_closed():
    with pytest.raises(AuthenticationError, match="not allowed"):
        validate_telegram_init_data(
            signed_init_data(user_id=999999),
            settings(),
            now=NOW,
        )


def test_malformed_query_fails_closed():
    with pytest.raises(AuthenticationError, match="query"):
        validate_telegram_init_data("broken-field", settings(), now=NOW)


def test_missing_configuration_fails_closed():
    with pytest.raises(AuthenticationNotConfigured):
        validate_telegram_init_data(signed_init_data(), Settings(), now=NOW)


def test_session_round_trip_and_expiry():
    token, issued = issue_session_token(ALLOWED_USER, settings(), now=NOW)
    assert verify_session_token(token, settings(), now=NOW + 1) == issued

    with pytest.raises(AuthenticationError, match="expired"):
        verify_session_token(token, settings(), now=issued.expires_at)


def test_session_tampering_is_rejected():
    token, _ = issue_session_token(ALLOWED_USER, settings(), now=NOW)
    payload, signature = token.split(".")
    with pytest.raises(AuthenticationError):
        verify_session_token(f"{payload}x.{signature}", settings(), now=NOW)


def test_settings_repr_hides_both_tokens_and_session_secret():
    value = repr(settings())
    assert BOT_TOKEN not in value
    assert "ha-test-token" not in value
    assert SESSION_SECRET not in value
