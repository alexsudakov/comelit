from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
import uuid
from typing import Mapping

PROTOCOL_VERSION = "1"
OPEN_DOOR_PATH = "/v1/open-door"
RESPONSE_SIGNATURE_HEADER = "X-Comelit-Response-Signature"
_OPERATION_PREFIX = "p13-hermes-"


def validate_operation_id(value: str) -> str:
    value = (value or "").strip()
    if not value.startswith(_OPERATION_PREFIX):
        raise ValueError("invalid operation_id")
    suffix = value[len(_OPERATION_PREFIX) :]
    parsed = uuid.UUID(suffix)
    if parsed.version != 4 or str(parsed) != suffix.lower():
        raise ValueError("invalid operation_id")
    canonical = f"{_OPERATION_PREFIX}{parsed}"
    if canonical != value.lower():
        raise ValueError("invalid operation_id")
    return canonical


def _signature_payload(
    *, method: str, path: str, timestamp: str, nonce: str, body: bytes
) -> bytes:
    body_sha = hashlib.sha256(body).hexdigest()
    return (
        f"v{PROTOCOL_VERSION}\n"
        f"{method.upper()}\n"
        f"{path}\n"
        f"{timestamp}\n"
        f"{nonce}\n"
        f"{body_sha}"
    ).encode("utf-8")


def _sign(
    secret: bytes,
    *,
    method: str,
    path: str,
    timestamp: str,
    nonce: str,
    body: bytes,
) -> str:
    return hmac.new(
        secret,
        _signature_payload(
            method=method,
            path=path,
            timestamp=timestamp,
            nonce=nonce,
            body=body,
        ),
        hashlib.sha256,
    ).hexdigest()


def build_signed_open_door_request(
    *,
    shared_secret: str,
    operation_id: str,
    now: int | None = None,
    nonce: str | None = None,
) -> tuple[bytes, dict[str, str]]:
    secret = shared_secret.encode("utf-8")
    if len(secret) < 32:
        raise ValueError("shared secret must be at least 32 bytes")
    operation_id = validate_operation_id(operation_id)
    timestamp = str(int(time.time()) if now is None else int(now))
    nonce_value = nonce or secrets.token_urlsafe(24)
    if len(nonce_value) < 22 or len(nonce_value) > 64:
        raise ValueError("invalid nonce")

    body = json.dumps(
        {"operation_id": operation_id},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    signature = _sign(
        secret,
        method="POST",
        path=OPEN_DOOR_PATH,
        timestamp=timestamp,
        nonce=nonce_value,
        body=body,
    )
    headers = {
        "Content-Type": "application/json",
        "X-Comelit-Version": PROTOCOL_VERSION,
        "X-Comelit-Timestamp": timestamp,
        "X-Comelit-Nonce": nonce_value,
        "X-Comelit-Signature": signature,
    }
    return body, headers


def verify_signed_open_door_response(
    *,
    shared_secret: str,
    request_headers: Mapping[str, str],
    response_headers: Mapping[str, str],
    body: bytes,
) -> bool:
    secret = shared_secret.encode("utf-8")
    if len(secret) < 32:
        return False
    timestamp = str(request_headers.get("X-Comelit-Timestamp") or "")
    nonce = str(request_headers.get("X-Comelit-Nonce") or "")
    provided = str(response_headers.get(RESPONSE_SIGNATURE_HEADER) or "").lower()
    if len(provided) != 64:
        return False
    expected = _sign(
        secret,
        method="RESPONSE",
        path=OPEN_DOOR_PATH,
        timestamp=timestamp,
        nonce=nonce,
        body=body,
    )
    return hmac.compare_digest(provided, expected)
