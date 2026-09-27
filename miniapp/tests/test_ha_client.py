import asyncio
import json

import httpx
import pytest

from app.ha_client import HomeAssistantClient, HomeAssistantError


ENTITY_REGISTRY = [
    {
        "entity_id": "camera.comelit_entrance",
        "platform": "comelit",
        "unique_id": "comelit_entrance_camera",
        "labels": [],
        "name": None,
        "original_name": "Entrance",
    },
    {
        "entity_id": "button.comelit_main_entrance_open_door",
        "platform": "comelit",
        "unique_id": "comelit_main_entrance_open_door",
        "labels": [],
        "name": None,
        "original_name": "Open entrance",
    },
    {
        "entity_id": "button.comelit_main_gate_open_door",
        "platform": "comelit",
        "unique_id": "comelit_main_gate_open_door",
        "labels": [],
        "name": None,
        "original_name": "Open gate",
    },
    {
        "entity_id": "sensor.comelit_call_state",
        "platform": "comelit",
        "unique_id": "comelit_call_state",
        "labels": [],
        "name": None,
        "original_name": "Call state",
    },
    {
        "entity_id": "camera.driveway",
        "platform": "generic",
        "unique_id": "driveway",
        "labels": ["outside"],
        "name": "Driveway",
        "original_name": "Driveway",
    },
    {
        "entity_id": "person.secret",
        "platform": "person",
        "unique_id": "secret",
        "labels": [],
    },
]


class TestClient(HomeAssistantClient):
    async def entity_registry(self):
        return ENTITY_REGISTRY

    async def stream_camera(self, entity_id):
        return {"mjpeg_path": f"/api/camera_proxy_stream/{entity_id}"}


def run(coro):
    return asyncio.run(coro)


def test_bootstrap_uses_bearer_token_and_filters_state_surface():
    requests = []

    def handler(request: httpx.Request):
        requests.append(request)
        assert request.headers["authorization"] == "Bearer HA_SECRET"
        assert request.url.path == "/api/states"
        return httpx.Response(
            200,
            json=[
                {
                    "entity_id": "camera.comelit_entrance",
                    "state": "streaming",
                    "attributes": {
                        "friendly_name": "Entrance",
                        "entity_picture": "/api/camera_proxy/x",
                        "secret": "do-not-leak",
                    },
                },
                {
                    "entity_id": "sensor.comelit_call_state",
                    "state": "ringing",
                    "attributes": {
                        "panel": "entrance",
                        "event_id": "evt-1",
                        "media_attached": True,
                        "unknown_private_field": "hidden",
                    },
                },
                {
                    "entity_id": "camera.driveway",
                    "state": "idle",
                    "attributes": {"friendly_name": "Driveway"},
                },
                {
                    "entity_id": "person.secret",
                    "state": "home",
                    "attributes": {"friendly_name": "Secret Person"},
                },
            ],
        )

    async def scenario():
        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        client = TestClient(
            "http://ha.local:8123",
            "HA_SECRET",
            surveillance_entities=("camera.driveway",),
            http_client=http,
        )
        try:
            result = await client.bootstrap()
        finally:
            await http.aclose()
        return result

    result = run(scenario())
    assert len(requests) == 1
    assert set(result["states"]) == {
        "camera.comelit_entrance",
        "sensor.comelit_call_state",
        "camera.driveway",
    }
    assert result["surveillance_entities"] == ["camera.driveway"]
    assert result["states"]["sensor.comelit_call_state"]["attributes"] == {
        "panel": "entrance",
        "event_id": "evt-1",
        "media_attached": True,
    }
    serialized = json.dumps(result)
    assert "HA_SECRET" not in serialized
    assert "person.secret" not in serialized
    assert "do-not-leak" not in serialized


def test_door_press_is_exactly_one_allowed_ha_service_call():
    calls = []

    def handler(request: httpx.Request):
        calls.append(request)
        assert request.url.path == "/api/services/button/press"
        assert request.headers["authorization"] == "Bearer HA_SECRET"
        assert json.loads(request.content) == {
            "entity_id": "button.comelit_main_entrance_open_door"
        }
        return httpx.Response(200, json=[])

    async def scenario():
        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        client = TestClient(
            "http://ha.local:8123",
            "HA_SECRET",
            http_client=http,
        )
        try:
            return await client.press_door(
                "button.comelit_main_entrance_open_door"
            )
        finally:
            await http.aclose()

    result = run(scenario())
    assert result["accepted"] is True
    assert len(calls) == 1


def test_door_failure_is_not_retried():
    calls = []

    def handler(request: httpx.Request):
        calls.append(request)
        return httpx.Response(500, json={"error": "failed"})

    async def scenario():
        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        client = TestClient(
            "http://ha.local:8123",
            "HA_SECRET",
            http_client=http,
        )
        try:
            with pytest.raises(HomeAssistantError, match="HTTP 500"):
                await client.press_door(
                    "button.comelit_main_gate_open_door"
                )
        finally:
            await http.aclose()

    run(scenario())
    assert len(calls) == 1


def test_arbitrary_entity_cannot_be_pressed():
    calls = []

    def handler(request: httpx.Request):
        calls.append(request)
        return httpx.Response(200, json=[])

    async def scenario():
        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        client = TestClient(
            "http://ha.local:8123",
            "HA_SECRET",
            http_client=http,
        )
        try:
            with pytest.raises(HomeAssistantError, match="not allowed"):
                await client.press_door("button.some_other_device")
        finally:
            await http.aclose()

    run(scenario())
    assert calls == []


def test_camera_proxy_is_limited_to_allowed_camera_entities():
    seen = []

    def handler(request: httpx.Request):
        seen.append(request)
        assert request.headers["authorization"] == "Bearer HA_SECRET"
        return httpx.Response(
            200,
            content=b"frame",
            headers={"content-type": "multipart/x-mixed-replace;boundary=frame"},
        )

    async def scenario():
        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        client = TestClient(
            "http://ha.local:8123",
            "HA_SECRET",
            surveillance_entities=("camera.driveway",),
            http_client=http,
        )
        try:
            stream = await client.open_camera_mjpeg("camera.driveway")
            body = await stream.response.aread()
            await stream.response.aclose()
            with pytest.raises(HomeAssistantError, match="not allowed"):
                await client.open_camera_mjpeg("camera.unlisted")
            return body
        finally:
            await http.aclose()

    assert run(scenario()) == b"frame"
    assert len(seen) == 1
