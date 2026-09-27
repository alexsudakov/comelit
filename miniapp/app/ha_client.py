from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse, urlunparse

import httpx
import websockets


COMELIT_UNIQUE_IDS = frozenset(
    {
        "comelit_entrance_camera",
        "comelit_entrance_media_session",
        "comelit_main_entrance_open_door",
        "comelit_main_gate_open_door",
        "comelit_listener_status",
        "comelit_call_state",
    }
)
DOOR_UNIQUE_IDS = frozenset(
    {
        "comelit_main_entrance_open_door",
        "comelit_main_gate_open_door",
    }
)
CAMERA_UNIQUE_IDS = frozenset({"comelit_entrance_camera"})
SAFE_STATE_ATTRIBUTES = frozenset(
    {
        "friendly_name",
        "panel",
        "event_id",
        "media_attached",
        "standard_press_allowed",
        "blocked_by_media_session",
    }
)


class HomeAssistantError(RuntimeError):
    """Home Assistant API failure."""


class HomeAssistantNotConfigured(HomeAssistantError):
    """Home Assistant API credentials are missing."""


@dataclass(frozen=True)
class CameraStream:
    response: httpx.Response
    media_type: str


class HomeAssistantClient:
    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        surveillance_entities: tuple[str, ...] = (),
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._surveillance_entities = tuple(surveillance_entities)
        self._owns_http_client = http_client is None
        self._http = http_client or httpx.AsyncClient(timeout=15.0)

    @property
    def configured(self) -> bool:
        return bool(self._base_url and self._token)

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"}

    def _url(self, path: str) -> str:
        return f"{self._base_url}{path}"

    def _websocket_url(self) -> str:
        parsed = urlparse(self._base_url)
        if parsed.scheme not in {"http", "https"}:
            raise HomeAssistantError("HA base URL must use http or https")
        scheme = "wss" if parsed.scheme == "https" else "ws"
        return urlunparse((scheme, parsed.netloc, "/api/websocket", "", "", ""))

    async def close(self) -> None:
        if self._owns_http_client:
            await self._http.aclose()

    async def _ws_command(self, command: dict[str, Any]) -> Any:
        if not self.configured:
            raise HomeAssistantNotConfigured("Home Assistant is not configured")

        try:
            async with websockets.connect(
                self._websocket_url(),
                open_timeout=10,
                close_timeout=5,
                max_size=4 * 1024 * 1024,
            ) as websocket:
                required = json.loads(await websocket.recv())
                if required.get("type") != "auth_required":
                    raise HomeAssistantError("unexpected HA WebSocket auth preamble")

                await websocket.send(
                    json.dumps({"type": "auth", "access_token": self._token})
                )
                auth_result = json.loads(await websocket.recv())
                if auth_result.get("type") != "auth_ok":
                    raise HomeAssistantError("HA WebSocket authentication failed")

                payload = {"id": 1, **command}
                await websocket.send(json.dumps(payload))
                while True:
                    result = json.loads(await websocket.recv())
                    if result.get("id") != 1:
                        continue
                    if result.get("type") != "result" or not result.get("success"):
                        raise HomeAssistantError(
                            f"HA WebSocket command failed: {result.get('error') or 'unknown'}"
                        )
                    return result.get("result")
        except HomeAssistantError:
            raise
        except Exception as exc:
            raise HomeAssistantError(
                f"HA WebSocket request failed: {exc.__class__.__name__}"
            ) from exc

    async def entity_registry(self) -> list[dict[str, Any]]:
        result = await self._ws_command({"type": "config/entity_registry/list"})
        if not isinstance(result, list):
            raise HomeAssistantError("invalid HA entity registry response")
        return result

    async def stream_camera(self, entity_id: str) -> dict[str, Any]:
        result = await self._ws_command(
            {
                "type": "stream_camera",
                "data": {"camera_entity_id": entity_id},
            }
        )
        if not isinstance(result, dict):
            raise HomeAssistantError("invalid HA camera stream response")
        return result

    def _filtered_registry(
        self, entries: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        configured_surveillance = set(self._surveillance_entities)
        filtered = []
        for entry in entries:
            entity_id = str(entry.get("entity_id") or "")
            platform = str(entry.get("platform") or "")
            unique_id = str(entry.get("unique_id") or "")
            is_comelit = platform == "comelit" and unique_id in COMELIT_UNIQUE_IDS
            is_surveillance = entity_id in configured_surveillance
            if not is_comelit and not is_surveillance:
                continue
            filtered.append(
                {
                    "entity_id": entity_id,
                    "platform": platform,
                    "unique_id": unique_id,
                    "labels": list(entry.get("labels") or []),
                    "name": entry.get("name"),
                    "original_name": entry.get("original_name"),
                }
            )
        return filtered

    @staticmethod
    def _safe_state(state: dict[str, Any]) -> dict[str, Any]:
        attributes = state.get("attributes")
        safe_attributes = {}
        if isinstance(attributes, dict):
            safe_attributes = {
                key: attributes[key]
                for key in SAFE_STATE_ATTRIBUTES
                if key in attributes
            }
        return {
            "entity_id": str(state.get("entity_id") or ""),
            "state": str(state.get("state") or "unknown"),
            "attributes": safe_attributes,
        }

    async def bootstrap(self) -> dict[str, Any]:
        if not self.configured:
            raise HomeAssistantNotConfigured("Home Assistant is not configured")

        registry = self._filtered_registry(await self.entity_registry())
        allowed_ids = {entry["entity_id"] for entry in registry}

        response = await self._http.get(
            self._url("/api/states"),
            headers=self._headers,
        )
        if response.status_code == 401:
            raise HomeAssistantError("Home Assistant token rejected")
        response.raise_for_status()
        raw_states = response.json()
        if not isinstance(raw_states, list):
            raise HomeAssistantError("invalid HA states response")

        states = {
            safe["entity_id"]: safe
            for item in raw_states
            if isinstance(item, dict)
            for safe in [self._safe_state(item)]
            if safe["entity_id"] in allowed_ids
        }

        visible_surveillance = [
            entity_id
            for entity_id in self._surveillance_entities
            if entity_id in allowed_ids
        ]
        return {
            "states": states,
            "entity_registry": registry,
            "label_registry": [],
            "surveillance_entities": visible_surveillance,
        }

    async def _allowed_door_ids(self) -> set[str]:
        entries = self._filtered_registry(await self.entity_registry())
        return {
            str(entry["entity_id"])
            for entry in entries
            if entry.get("platform") == "comelit"
            and entry.get("unique_id") in DOOR_UNIQUE_IDS
        }

    async def _allowed_camera_ids(self) -> set[str]:
        entries = self._filtered_registry(await self.entity_registry())
        configured = set(self._surveillance_entities)
        return {
            str(entry["entity_id"])
            for entry in entries
            if (
                entry.get("platform") == "comelit"
                and entry.get("unique_id") in CAMERA_UNIQUE_IDS
            )
            or entry.get("entity_id") in configured
        }

    async def press_door(self, entity_id: str) -> dict[str, Any]:
        if entity_id not in await self._allowed_door_ids():
            raise HomeAssistantError("Door entity is not allowed")

        # Safety invariant: one Mini App request maps to exactly one HA service call.
        response = await self._http.post(
            self._url("/api/services/button/press"),
            headers={**self._headers, "Content-Type": "application/json"},
            json={"entity_id": entity_id},
        )
        if response.status_code == 401:
            raise HomeAssistantError("Home Assistant token rejected")
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise HomeAssistantError(
                f"HA Door service failed with HTTP {response.status_code}"
            ) from exc
        result = response.json()
        return {"accepted": True, "ha_result": result}

    async def open_camera_mjpeg(self, entity_id: str) -> CameraStream:
        if entity_id not in await self._allowed_camera_ids():
            raise HomeAssistantError("Camera entity is not allowed")

        stream = await self.stream_camera(entity_id)
        path = stream.get("mjpeg_path")
        if not isinstance(path, str) or not path.startswith("/"):
            raise HomeAssistantError("HA camera did not provide an MJPEG path")

        request = self._http.build_request(
            "GET",
            self._url(path),
            headers=self._headers,
        )
        response = await self._http.send(request, stream=True)
        if response.status_code == 401:
            await response.aclose()
            raise HomeAssistantError("Home Assistant token rejected")
        if response.is_error:
            status = response.status_code
            await response.aclose()
            raise HomeAssistantError(f"HA camera stream failed with HTTP {status}")

        media_type = response.headers.get(
            "content-type", "multipart/x-mixed-replace"
        )
        return CameraStream(response=response, media_type=media_type)
