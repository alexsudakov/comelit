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
    """Bridge health/configuration validation failed."""


class ComelitBridgeOutcomeUnknown(ComelitBridgeError):
    """No trustworthy signed result exists; retry is forbidden."""


class ComelitBridgeRejected(ComelitBridgeError):
    """The authenticated request was rejected before a trusted result existed."""


@dataclass(frozen=True)
class ComelitBridgeResult:
    operation_id: str
    state: str
    reason: str
    runner_invoked: bool
    retry_allowed: bool
    physical_effect_asserted: bool

    def as_service_response(self) -> dict[str, object]:
        return {
            "operation_id": self.operation_id,
            "state": self.state,
            "reason": self.reason,
            "runner_invoked": self.runner_invoked,
            "retry_allowed": False,
            "physical_effect_asserted": False,
            "protocol_acknowledged": self.state == "ACKED",
            "physical_door_state": "UNKNOWN",
        }


class ComelitBridgeClient:
    def __init__(self, session: ClientSession, *, bridge_url: str, shared_secret: str):
        self._session = session
        self._base_url = bridge_url.rstrip("/") + "/"
        self._shared_secret = shared_secret

    async def async_health(self, *, require_live: bool = False) -> bool:
        url = urljoin(self._base_url, "healthz")
        try:
            async with self._session.get(url, timeout=ClientTimeout(total=5)) as response:
                if response.status != 200:
                    return False
                payload = await response.json()
        except (ClientError, asyncio.TimeoutError, ValueError, TypeError):
            return False
        if not isinstance(payload, dict):
            return False
        if payload.get("ok") is not True:
            return False
        if int(payload.get("protocol_version", 0)) != BRIDGE_PROTOCOL_VERSION:
            return False
        if require_live and payload.get("live_enabled") is not True:
            return False
        if payload.get("live_enabled") is True and payload.get("runner_identity") != "pass":
            return False
        return True

    async def async_open_door(self, operation_id: str) -> ComelitBridgeResult:
        body, headers = build_signed_open_door_request(
            shared_secret=self._shared_secret,
            operation_id=operation_id,
        )
        url = urljoin(self._base_url, OPEN_DOOR_PATH.lstrip("/"))

        # Deliberately one HTTP attempt.  No timeout/replay error is converted
        # into a second POST.
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

                if not isinstance(payload, dict):
                    raise ComelitBridgeOutcomeUnknown("invalid bridge response; do not retry")

                if response.status != 200:
                    # Only syntactic/auth failures are known to precede runner
                    # execution. Replay and 5xx remain ambiguous.
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

        if payload.get("ok") is not True:
            raise ComelitBridgeOutcomeUnknown("invalid signed success response; do not retry")
        if payload.get("operation_id") != operation_id:
            raise ComelitBridgeOutcomeUnknown("operation identity mismatch; do not retry")
        state = payload.get("state")
        if state not in {"ACKED", "FAILED_SAFE", "UNKNOWN_OUTCOME"}:
            raise ComelitBridgeOutcomeUnknown("invalid bridge state; do not retry")
        if payload.get("retry_allowed") is not False:
            raise ComelitBridgeOutcomeUnknown("unsafe or missing retry flag from bridge")
        if payload.get("physical_effect_asserted") is not False:
            raise ComelitBridgeOutcomeUnknown(
                "unsafe or missing physical-effect assertion from bridge"
            )
        if not isinstance(payload.get("runner_invoked"), bool):
            raise ComelitBridgeOutcomeUnknown("invalid runner_invoked flag; do not retry")
        if not isinstance(payload.get("reason"), str):
            raise ComelitBridgeOutcomeUnknown("invalid reason; do not retry")

        return ComelitBridgeResult(
            operation_id=operation_id,
            state=str(state),
            reason=payload["reason"],
            runner_invoked=payload["runner_invoked"],
            retry_allowed=False,
            physical_effect_asserted=False,
        )
