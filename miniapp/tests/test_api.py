import hashlib
import hmac
import json
from pathlib import Path
from urllib.parse import urlencode

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


BOT_TOKEN = "123456:TEST_BOT_TOKEN"
SESSION_SECRET = "s" * 48
ALLOWED_USER = 424242


class FakeHA:
    configured = True

    def __init__(self):
        self.press_calls = []
        self.closed = False

    async def bootstrap(self):
        return {
            "states": {
                "sensor.comelit_call_state": {
                    "entity_id": "sensor.comelit_call_state",
                    "state": "idle",
                    "attributes": {},
                }
            },
            "entity_registry": [
                {
                    "entity_id": "sensor.comelit_call_state",
                    "platform": "comelit",
                    "unique_id": "comelit_call_state",
                    "labels": [],
                    "name": None,
                    "original_name": "Call state",
                }
            ],
            "label_registry": [],
            "surveillance_entities": [],
        }

    async def press_door(self, entity_id):
        self.press_calls.append(entity_id)
        return {"accepted": True, "ha_result": []}

    async def close(self):
        self.closed = True


def settings():
    return Settings(
        telegram_bot_token=BOT_TOKEN,
        allowed_user_ids=frozenset({ALLOWED_USER}),
        session_secret=SESSION_SECRET,
        ha_base_url="http://ha.local:8123",
        ha_token="HA_SECRET",
        cookie_secure=False,
        auth_max_age_seconds=300,
        session_ttl_seconds=900,
    )


def signed_init_data():
    import time

    fields = {
        "auth_date": str(int(time.time())),
        "query_id": "AAE-test",
        "user": json.dumps(
            {"id": ALLOWED_USER, "first_name": "Test"},
            separators=(",", ":"),
        ),
    }
    data_check = "\n".join(f"{key}={fields[key]}" for key in sorted(fields))
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


def make_client(tmp_path: Path):
    card_path = tmp_path / "comelit-card.js"
    card_path.write_text(
        'customElements.define("comelit-card", class extends HTMLElement {});',
        encoding="utf-8",
    )
    fake = FakeHA()
    app = create_app(settings(), fake, card_path=card_path)
    return TestClient(app), fake


def authenticate(client):
    response = client.post(
        "/api/auth/telegram",
        json={"init_data": signed_init_data()},
    )
    assert response.status_code == 200
    assert response.json()["authenticated"] is True
    return response


def test_health_and_shared_card_asset_do_not_leak_secrets(tmp_path):
    client, _ = make_client(tmp_path)
    with client:
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json()["shared_card_present"] is True
        assert BOT_TOKEN not in health.text
        assert "HA_SECRET" not in health.text
        assert SESSION_SECRET not in health.text

        index = client.get("/")
        assert index.status_code == 200
        assert '<comelit-card id="comelitCard">' in index.text
        assert "/assets/comelit-card.js" in index.text
        assert "Открыть дверь" not in index.text

        asset = client.get("/assets/comelit-card.js")
        assert asset.status_code == 200
        assert 'customElements.define("comelit-card"' in asset.text


def test_unauthenticated_ha_bootstrap_fails_closed(tmp_path):
    client, _ = make_client(tmp_path)
    with client:
        response = client.get("/api/ha/bootstrap")
        assert response.status_code == 401


def test_authentication_sets_httponly_cookie_then_bootstrap_works(tmp_path):
    client, _ = make_client(tmp_path)
    with client:
        response = authenticate(client)
        cookie = response.headers["set-cookie"].lower()
        assert "httponly" in cookie
        assert "samesite=lax" in cookie

        bootstrap = client.get("/api/ha/bootstrap")
        assert bootstrap.status_code == 200
        assert bootstrap.json()["states"]["sensor.comelit_call_state"]["state"] == "idle"


def test_door_endpoint_requires_same_origin_marker_and_is_one_shot(tmp_path):
    client, fake = make_client(tmp_path)
    with client:
        authenticate(client)

        blocked = client.post(
            "/api/ha/button-press",
            json={"entity_id": "button.comelit_main_entrance_open_door"},
        )
        assert blocked.status_code == 403
        assert fake.press_calls == []

        accepted = client.post(
            "/api/ha/button-press",
            headers={"X-Comelit-MiniApp-Request": "1"},
            json={"entity_id": "button.comelit_main_entrance_open_door"},
        )
        assert accepted.status_code == 200
        assert accepted.json()["accepted"] is True
        assert fake.press_calls == ["button.comelit_main_entrance_open_door"]


def test_tokens_are_not_present_in_frontend_files():
    root = Path(__file__).resolve().parents[1] / "app" / "static"
    content = "\n".join(
        path.read_text(encoding="utf-8")
        for path in root.iterdir()
        if path.is_file()
    )
    assert BOT_TOKEN not in content
    assert "HA_SECRET" not in content
    assert SESSION_SECRET not in content
