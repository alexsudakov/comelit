from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from urllib.parse import urljoin

from aiohttp import ClientError, ClientSession, ClientTimeout

from .const import BRIDGE_PROTOCOL_VERSION, BRIDGE_REQUEST_TIMEOUT_SECONDS
from .signing import (
    OPEN_DOOR_PATH,
    build_signed_open_door_request,
    verify_signed_open_door_response,
)


class ComelitBridgeError(RuntimeError):
    """Base bridge client error."""


class ComelitBridgeCannotConnect(ComelitBridgeError):
    """Connection failed before a health check completed."""


class ComelitBridgeOutcomeUnknown(ComelitBridgeError):
    """The open-door request may have reached the bridge; retry is forbidden."""


class ComelitBridgeRejected(ComelitBridgeError):
    """The authenticated bridge rejected the request without a physical claim."""


@dataclass(frozen=True)
class ComelitBridgeResult:
    operation_id: str
    state: str
    reason: str
    retry_allowed: bool
    physical_effect_asserted: bool


class ComelitBridgeClient:
    def __init__(self, session: ClientSession, *, bridge_url: str, shared_secret: str):
        self._session = session
        self._base_url = bridge_url.rstrip("/") + "/"
        self._shared_secret = shared_secret

    async def async_health(self) -> bool:
        url = urljoin(self._base_url, "healthz")
        try:
            async with self._session.get(url, timeout=ClientTimeout(total=5)) as response:
                if response.status != 200:
                    return False
                payload = await response.json()
        except (ClientError, asyncio.TimeoutError, ValueError):
            return False
        return bool(
            payload.get("ok")
            and int(payload.get("protocol_version", 0)) == BRIDGE_PROTOCOL_VERSION
        )

    async def async_open_door(self, operation_id: str) -> ComelitBridgeResult:
        body, headers = build_signed_open_door_request(
            shared_secret=self._shared_secret,
            operation_id=operation_id,
        )
        url = urljoin(self._base_url, OPEN_DOOR_PATH.lstrip("/"))

        # Deliberately one HTTP attempt. aiohttp itself does not retry this POST.
        try:
            async with self._session.post(
                url,
                data=body,
                headers=headers,
                timeout=ClientTimeout(total=BRIDGE_REQUEST_TIMEOUT_SECONDS),
            ) as response:
                try:
                    raw_response = await response.read()
                    payload = json.loads(raw_response.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError, ClientError) as exc:
                    raise ComelitBridgeOutcomeUnknown(
                        "bridge response unreadable; do not retry"
                    ) from exc

                if response.status != 200:
                    # Authentication/validation failures occur before the canonical
                    # runner. Replay/5xx are ambiguous and must not be retried.
                    if response.status in {400, 401, 404, 411, 413}:
                        raise ComelitBridgeRejected(
                            str(payload.get("error") or "bridge rejected request")
                        )
                    raise ComelitBridgeOutcomeUnknown(
                        "bridge outcome unknown; do not retry"
                    )

                if not verify_signed_open_door_response(
                    shared_secret=self._shared_secret,
                    request_headers=headers,
                    response_headers=response.headers,
                    body=raw_response,
                ):
                    raise ComelitBridgeOutcomeUnknown(
                        "bridge response authentication failed; do not retry"
                    )
        except ComelitBridgeError:
            raise
        except (ClientError, asyncio.TimeoutError) as exc:
            raise ComelitBridgeOutcomeUnknown(
                "bridge request outcome unknown; do not retry"
            ) from exc

        if not isinstance(payload, dict):
            raise ComelitBridgeOutcomeUnknown("invalid bridge response; do not retry")
        if payload.get("operation_id") != operation_id:
            raise ComelitBridgeOutcomeUnknown("operation identity mismatch; do not retry")
        state = str(payload.get("state") or "")
        if state not in {"ACKED", "FAILED_SAFE", "UNKNOWN_OUTCOME"}:
            raise ComelitBridgeOutcomeUnknown("invalid bridge state; do not retry")
        if bool(payload.get("retry_allowed")):
            raise ComelitBridgeOutcomeUnknown("unsafe retry flag from bridge")
        if bool(payload.get("physical_effect_asserted")):
            raise ComelitBridgeOutcomeUnknown("unsafe physical-effect assertion from bridge")

        return ComelitBridgeResult(
            operation_id=operation_id,
            state=state,
            reason=str(payload.get("reason") or ""),
            retry_allowed=False,
            physical_effect_asserted=False,
        )
