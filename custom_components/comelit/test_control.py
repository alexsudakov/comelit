from __future__ import annotations

from aiohttp.web import Request, Response, json_response

from homeassistant.components import webhook
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .runtime import ComelitRingRuntime

WEBHOOK_ID = "comelit-ha-ring-test-control-v1"
_ALLOWED_REMOTE = "192.168.1.85"


def _status_payload(runtime: ComelitRingRuntime) -> dict[str, object]:
    status = runtime.status()
    status["press_panel_now"] = bool(
        status["running"]
        and status["listener_ready"]
    )
    status["network_door_action_performed"] = False
    status["physical_door_action"] = False
    status["p13_executed"] = False
    status["p14_executed"] = False
    return status


async def _handle(
    hass: HomeAssistant,
    webhook_id: str,
    request: Request,
    *,
    runtime: ComelitRingRuntime,
) -> Response:
    del hass, webhook_id

    if request.remote != _ALLOWED_REMOTE:
        return json_response({"ok": False, "error": "forbidden"}, status=403)

    try:
        payload = await request.json()
    except Exception:
        return json_response({"ok": False, "error": "invalid_json"}, status=400)

    if not isinstance(payload, dict):
        return json_response({"ok": False, "error": "invalid_payload"}, status=400)

    action = payload.get("action")

    if action == "start":
        await runtime.async_start()
        ready = await runtime.async_wait_ready(timeout=30)
        result = _status_payload(runtime)
        result["ok"] = bool(ready)
        result["action"] = "start"
        if not ready and not result.get("last_error"):
            result["error"] = "ready_timeout"
        return json_response(result, status=200 if ready else 503)

    if action == "status":
        result = _status_payload(runtime)
        result["ok"] = True
        result["action"] = "status"
        return json_response(result)

    if action == "stop":
        await runtime.async_stop()
        result = _status_payload(runtime)
        result["ok"] = True
        result["action"] = "stop"
        return json_response(result)

    return json_response({"ok": False, "error": "unsupported_action"}, status=400)


def async_register_test_control(
    hass: HomeAssistant,
    runtime: ComelitRingRuntime,
) -> None:
    async def handler(
        handler_hass: HomeAssistant,
        webhook_id: str,
        request: Request,
    ) -> Response:
        return await _handle(
            handler_hass,
            webhook_id,
            request,
            runtime=runtime,
        )

    webhook.async_register(
        hass,
        DOMAIN,
        "Comelit HA ring test control",
        WEBHOOK_ID,
        handler,
        local_only=True,
        allowed_methods=("POST",),
    )


def async_unregister_test_control(hass: HomeAssistant) -> None:
    webhook.async_unregister(hass, WEBHOOK_ID)
