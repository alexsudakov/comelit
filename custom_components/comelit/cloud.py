from __future__ import annotations

import base64
import json

from aiohttp import ClientError, ClientSession

ENDPOINT = "https://api.comelitgroup.com/servicerest/p2p/start"


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

    try:
        obj = json.loads(raw.decode("utf-8", errors="replace"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ComelitCloudError("response_not_json") from exc

    if not 200 <= status < 300:
        raise ComelitCloudHttpError(status)
    if not isinstance(obj, dict):
        raise ComelitCloudError("response_not_object")

    data = obj.get("data")
    if not isinstance(data, dict):
        raise ComelitCloudError("data_not_object")

    encoded_remote = data.get("sdp")
    if not isinstance(encoded_remote, str) or not encoded_remote:
        raise ComelitCloudError("remote_sdp_missing")

    try:
        remote_bytes = base64.b64decode(encoded_remote, validate=True)
        remote = remote_bytes.decode("utf-8")
    except (ValueError, UnicodeError) as exc:
        raise ComelitCloudError("remote_sdp_decode_failed") from exc

    _validate_remote_sdp(remote)
    return remote
