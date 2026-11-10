from __future__ import annotations

import base64
import json
import logging

from aiohttp import ClientError, ClientSession

ENDPOINT = "https://api.comelitgroup.com/servicerest/p2p/start"

_LOGGER = logging.getLogger(__name__)
_MISSING = object()
_RESULT_ENUMS = frozenset({"SUCCESS", "TIMEOUT"})


class ComelitCloudError(RuntimeError):
    """Comelit cloud P2P negotiation failed."""


class ComelitCloudHttpError(ComelitCloudError):
    """Comelit cloud P2P negotiation returned a non-success HTTP status."""

    def __init__(self, status: int) -> None:
        self.status = status
        super().__init__(f"http_status:{status}")


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


def _log_response_validation_failure(
    reason: str,
    *,
    status: int,
    response_bytes: int,
    obj: object = _MISSING,
) -> None:
    """Log bounded structural evidence without response keys or values."""
    is_object = isinstance(obj, dict)
    result = obj.get("result", _MISSING) if is_object else _MISSING
    data = obj.get("data", _MISSING) if is_object else _MISSING
    result_present = result is not _MISSING
    data_present = data is not _MISSING
    result_type = _json_type(result)
    data_type = _json_type(data)
    result_enum = (
        result
        if isinstance(result, str) and result in _RESULT_ENUMS
        else "UNKNOWN"
    )
    sdp_present = isinstance(data, dict) and "sdp" in data

    _LOGGER.warning(
        "Comelit cloud P2P response validation failed: "
        "reason=%s status=%d response_bytes=%d "
        "result_present=%s result_type=%s result_enum=%s "
        "data_present=%s data_type=%s sdp_present=%s "
        "top_level_field_count=%d data_field_present=%s "
        "error_field_present=%s code_field_present=%s",
        reason,
        status,
        response_bytes,
        result_present,
        result_type,
        result_enum,
        data_present,
        data_type,
        sdp_present,
        len(obj) if is_object else 0,
        data_present,
        is_object and "error" in obj,
        is_object and "code" in obj,
    )


def _json_type(value: object) -> str:
    """Return a bounded JSON type label without rendering the value."""
    if value is _MISSING:
        return "missing"
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, str):
        return "string"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    # json.loads() cannot produce any other type. Keep the diagnostic label
    # inside the closed vocabulary even if this helper is called directly.
    return "missing"


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
        _log_response_validation_failure(
            "response_not_json", status=status, response_bytes=len(raw)
        )
        raise ComelitCloudError("response_not_json") from exc

    if not isinstance(obj, dict):
        _log_response_validation_failure(
            "response_not_object",
            status=status,
            response_bytes=len(raw),
            obj=obj,
        )
        raise ComelitCloudError("response_not_object")

    data = obj.get("data")
    if not isinstance(data, dict):
        _log_response_validation_failure(
            "data_not_object", status=status, response_bytes=len(raw), obj=obj
        )
        raise ComelitCloudError("data_not_object")

    encoded_remote = data.get("sdp")
    if not isinstance(encoded_remote, str) or not encoded_remote:
        _log_response_validation_failure(
            "remote_sdp_missing", status=status, response_bytes=len(raw), obj=obj
        )
        raise ComelitCloudError("remote_sdp_missing")

    try:
        remote_bytes = base64.b64decode(encoded_remote, validate=True)
        remote = remote_bytes.decode("utf-8")
    except (ValueError, UnicodeError) as exc:
        _log_response_validation_failure(
            "remote_sdp_decode_failed",
            status=status,
            response_bytes=len(raw),
            obj=obj,
        )
        raise ComelitCloudError("remote_sdp_decode_failed") from exc

    try:
        _validate_remote_sdp(remote)
    except ComelitCloudError:
        _log_response_validation_failure(
            "remote_sdp_incomplete",
            status=status,
            response_bytes=len(raw),
            obj=obj,
        )
        raise
    return remote
