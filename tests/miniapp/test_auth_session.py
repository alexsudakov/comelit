from __future__ import annotations

import base64
import importlib.util
import json
import sys
from pathlib import Path
from urllib.parse import urlencode

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import pytest


ROOT = Path(__file__).resolve().parents[2]
AUTH_PATH = ROOT / "custom_components" / "comelit" / "miniapp" / "auth.py"
SESSION_PATH = ROOT / "custom_components" / "comelit" / "miniapp" / "session.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


auth = _load(AUTH_PATH, "comelit_miniapp_auth_test")
session_mod = _load(SESSION_PATH, "comelit_miniapp_session_test")


BOT_ID = 12345678
USER_ID = 424242
NOW = 1_800_000_000


def _signed_init_data(
    private_key: Ed25519PrivateKey,
    *,
    user_id: int = USER_ID,
    auth_date: int = NOW,
) -> str:
    fields = {
        "auth_date": str(auth_date),
        "query_id": "AAE-test",
        "user": json.dumps(
            {"id": user_id, "first_name": "Test"},
            separators=(",", ":"),
        ),
        "hash": "not-used-by-third-party-validation",
    }
    signed_fields = {
        key: value
        for key, value in fields.items()
        if key not in {"hash", "signature"}
    }
    data_check = (
        f"{BOT_ID}:WebAppData\n"
        + "\n".join(
            f"{key}={signed_fields[key]}"
            for key in sorted(signed_fields)
        )
    )
    signature = private_key.sign(data_check.encode("utf-8"))
    fields["signature"] = (
        base64.urlsafe_b64encode(signature).rstrip(b"=").decode("ascii")
    )
    return urlencode(fields)


def _public_bytes(private_key: Ed25519PrivateKey) -> bytes:
    return private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )


def test_official_production_public_key_is_pinned():
    assert (
        auth.TELEGRAM_PRODUCTION_PUBLIC_KEY_HEX
        == "e7bf03a2fa4602af4580703d88dda5bb59f32ed8b02a56c187fe7d34caed242d"
    )


def test_valid_third_party_signature_is_accepted():
    private_key = Ed25519PrivateKey.generate()
    identity = auth.validate_telegram_init_data(
        _signed_init_data(private_key),
        bot_id=BOT_ID,
        allowed_user_ids=frozenset({USER_ID}),
        now=NOW,
        public_key_bytes=_public_bytes(private_key),
    )
    assert identity.user_id == USER_ID
    assert identity.auth_date == NOW


def test_tampering_breaks_signature():
    private_key = Ed25519PrivateKey.generate()
    raw = _signed_init_data(private_key).replace("Test", "Mallory")
    with pytest.raises(auth.TelegramAuthenticationError):
        auth.validate_telegram_init_data(
            raw,
            bot_id=BOT_ID,
            allowed_user_ids=frozenset({USER_ID}),
            now=NOW,
            public_key_bytes=_public_bytes(private_key),
        )


def test_expired_and_disallowed_init_data_fail_closed():
    private_key = Ed25519PrivateKey.generate()
    public = _public_bytes(private_key)

    with pytest.raises(auth.TelegramAuthenticationError, match="expired"):
        auth.validate_telegram_init_data(
            _signed_init_data(private_key, auth_date=NOW - 301),
            bot_id=BOT_ID,
            allowed_user_ids=frozenset({USER_ID}),
            now=NOW,
            public_key_bytes=public,
        )

    with pytest.raises(auth.TelegramAuthenticationError, match="not allowed"):
        auth.validate_telegram_init_data(
            _signed_init_data(private_key, user_id=999999),
            bot_id=BOT_ID,
            allowed_user_ids=frozenset({USER_ID}),
            now=NOW,
            public_key_bytes=public,
        )


def test_action_nonce_is_one_shot_and_rotates_before_action():
    store = session_mod.MiniAppSessionStore(ttl_seconds=900)
    token, created = store.create(USER_ID, BOT_ID, now=NOW)
    first_nonce = created.action_nonce

    consumed = store.consume_action_nonce(token, first_nonce, now=NOW + 1)
    assert consumed.user_id == USER_ID
    assert consumed.bot_id == BOT_ID
    assert consumed.action_nonce != first_nonce

    with pytest.raises(session_mod.MiniAppSessionError):
        store.consume_action_nonce(token, first_nonce, now=NOW + 2)


def test_session_expires_without_persistence():
    store = session_mod.MiniAppSessionStore(ttl_seconds=10)
    token, _created = store.create(USER_ID, BOT_ID, now=NOW)
    assert store.get(token, now=NOW + 9).user_id == USER_ID
    with pytest.raises(session_mod.MiniAppSessionError):
        store.get(token, now=NOW + 10)


def test_session_carries_bot_identity():
    store = session_mod.MiniAppSessionStore(ttl_seconds=900)
    token, created = store.create(USER_ID, BOT_ID, now=NOW)
    assert created.bot_id == BOT_ID
    assert store.get(token, now=NOW + 1).bot_id == BOT_ID
