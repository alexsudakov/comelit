from __future__ import annotations

import base64
import json
import logging
from typing import Any

from aiohttp import ClientError, ClientSession

ENDPOINT = "https://api.comelitgroup.com/servicerest/p2p/start"

_LOGGER = logging.getLogger(__name__)
_KNOWN_RESULT_ENUMS = frozenset({"SUCCESS", "TIMEOUT"})


class ComelitCloudError(RuntimeError):
    """Comelit cloud P2P negotiation failed."""


class ComelitCloudHttpError(ComelitCloudError):
    """Comelit cloud P2P negotiation returned a non-success HTTP status."""

    def __init__(self, status: int) -> None:
        self.status = status
        super().__init__(f"http_status:{status}")


def _json_type(value: Any, *, present: bool = True) -> str:
    """Return a closed JSON type name without disclosing a value."""
    if not present:
        return "missing"
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "array"
    if isinstance(value, str):
        return "string"
    if isinstance(value, (int, float)):
        return "number"
    return "missing"


def _log_response_validation_failure(raw: bytes, obj: Any = None) -> None:
    """Log one bounded summary of a response that failed validation."""
    is_object = isinstance(obj, dict)
    result_present = is_object and "result" in obj
    result = obj.get("result") if result_present else None
    data_present = is_object and "data" in obj
    data = obj.get("data") if data_present else None
    result_enum = (
        result
        if isinstance(result, str) and result in _KNOWN_RESULT_ENUMS
        else "UNKNOWN"
    )

    try:
        _LOGGER.warning(
            "Comelit P2P response validation failed: "
            "response_bytes=%d result_present=%s result_type=%s "
            "result_enum=%s data_present=%s data_type=%s "
            "sdp_present=%s top_level_field_count=%d",
            len(raw),
            result_present,
            _json_type(result, present=result_present),
            result_enum,
            data_present,
            _json_type(data, present=data_present),
            isinstance(data, dict) and "sdp" in data,
            len(obj) if is_object else 0,
        )
    except Exception:  # pragma: no cover - diagnostics must never affect P2P
        pass


def _validate_remote_sdp(remote: str) -> None:
    lines = [
        line.strip()
        for line in remote.replace("\r\n", "\n").split("\n")
        if line.strip()
    ]
    has_ufrag = any(line.startswith("a=ice-ufrag:") for line in lines)
    has_pwd = any(line.startswith("a=ice-pwd:") for line in lines)
    has_candidate = any(line.startswith("a=candidate:") for line in lines)
    if not (has_ufrag and has_pwd and has_candidate):
        raise ComelitCloudError("remote_sdp_incomplete")


async def async_negotiate_p2p(
    session: ClientSession,
    *,
    device_uuid: str,
    vip_token: str,
    oauth_access_token: str,
    offer_sdp: str,
) -> str:
    """Perform the capture-proven Comelit cloud P2P start exchange."""
    encoded_sdp = base64.b64encode(offer_sdp.encode("utf-8")).decode("ascii")

    payload = {
        "deviceUuid": device_uuid,
        "data": {
            "authMode": "user_viper_token",
            "secret": vip_token,
            "timeout": 10,
            "sdp": encoded_sdp,
        },
        "protocol": {
            "name": "viper_p2p_v2",
            "version": 1,
        },
    }

    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    headers = {
        "Authorization": "bearer " + oauth_access_token,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    try:
        async with session.post(
            ENDPOINT,
            data=body,
            headers=headers,
            timeout=20,
        ) as response:
            status = response.status
            raw = await response.read()
    except (ClientError, TimeoutError) as exc:
        raise ComelitCloudError(f"http_exception:{type(exc).__name__}") from exc

    # Preserve the HTTP status boundary before decoding the body. In
    # particular, a 401 must remain observable even if its body is empty or
    # not JSON so the runtime can perform exactly one OAuth refresh and retry
    # only this P2P bootstrap request.
    if not 200 <= status < 300:
        raise ComelitCloudHttpError(status)

    try:
        obj = json.loads(raw.decode("utf-8", errors="replace"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        _log_response_validation_failure(raw)
        raise ComelitCloudError("response_not_json") from exc

    if not isinstance(obj, dict):
        _log_response_validation_failure(raw, obj)
        raise ComelitCloudError("response_not_object")

    data = obj.get("data")
    if not isinstance(data, dict):
        _log_response_validation_failure(raw, obj)
        raise ComelitCloudError("data_not_object")

    encoded_remote = data.get("sdp")
    if not isinstance(encoded_remote, str) or not encoded_remote:
        _log_response_validation_failure(raw, obj)
        raise ComelitCloudError("remote_sdp_missing")

    try:
        remote_bytes = base64.b64decode(encoded_remote, validate=True)
        remote = remote_bytes.decode("utf-8")
    except (ValueError, UnicodeError) as exc:
        _log_response_validation_failure(raw, obj)
        raise ComelitCloudError("remote_sdp_decode_failed") from exc

    try:
        _validate_remote_sdp(remote)
    except ComelitCloudError:
        _log_response_validation_failure(raw, obj)
        raise
    return remote
