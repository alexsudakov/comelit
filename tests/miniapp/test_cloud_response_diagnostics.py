from __future__ import annotations

import asyncio
import base64
import importlib.util
import json
import logging
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
MODULE_NAME = "comelit_cloud_response_diagnostics_test"
SPEC = importlib.util.spec_from_file_location(
    MODULE_NAME, ROOT / "custom_components/comelit/cloud.py"
)
assert SPEC is not None and SPEC.loader is not None
cloud = importlib.util.module_from_spec(SPEC)
sys.modules[MODULE_NAME] = cloud
SPEC.loader.exec_module(cloud)


class _Response:
    def __init__(self, status: int, raw: bytes) -> None:
        self.status = status
        self._raw = raw

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        return None

    async def read(self) -> bytes:
        return self._raw


class _Session:
    def __init__(self, status: int, raw: bytes) -> None:
        self.response = _Response(status, raw)

    def post(self, *args, **kwargs) -> _Response:
        return self.response


def _negotiate(status: int, raw: bytes) -> str:
    return asyncio.run(
        cloud.async_negotiate_p2p(
            _Session(status, raw),
            device_uuid="fixture-device-uuid",
            vip_token="fixture-vip-token",
            oauth_access_token="fixture-oauth-token",
            offer_sdp="fixture-offer-sdp",
        )
    )


def _json_raw(value: object) -> bytes:
    return json.dumps(value, separators=(",", ":")).encode()


def _valid_remote() -> str:
    return "v=0\r\na=ice-ufrag:u\r\na=ice-pwd:p\r\na=candidate:1 1 UDP 1 127.0.0.1 9 typ host\r\n"


def test_success_returns_remote_sdp_without_logging(caplog) -> None:
    remote = _valid_remote()
    raw = _json_raw(
        {
            "result": "SUCCESS",
            "data": {"sdp": base64.b64encode(remote.encode()).decode()},
        }
    )

    with caplog.at_level(logging.WARNING, logger=MODULE_NAME):
        assert _negotiate(200, raw) == remote

    assert not caplog.records


@pytest.mark.parametrize(
    ("payload", "expected_error", "expected_enum"),
    [
        ({"result": "TIMEOUT"}, "data_not_object", "TIMEOUT"),
        ({"result": "SOMETHING_NEW"}, "data_not_object", "UNKNOWN"),
        ({"result": "eyJhbGciOiJIUzI1NiJ9.secret.signature"}, "data_not_object", "UNKNOWN"),
        ({"data": None}, "data_not_object", "UNKNOWN"),
        ({"result": "SUCCESS", "data": "invalid"}, "data_not_object", "SUCCESS"),
    ],
)
def test_invalid_responses_emit_one_bounded_warning(
    caplog, payload, expected_error, expected_enum
) -> None:
    raw = _json_raw(payload)

    with caplog.at_level(logging.WARNING, logger=MODULE_NAME):
        with pytest.raises(cloud.ComelitCloudError, match=expected_error):
            _negotiate(200, raw)

    warnings = [record for record in caplog.records if record.levelno == logging.WARNING]
    assert len(warnings) == 1
    message = warnings[0].getMessage()
    for field in (
        "response_bytes=",
        "result_present=",
        "result_type=",
        f"result_enum={expected_enum}",
        "data_present=",
        "data_type=",
        "sdp_present=",
        "top_level_field_count=",
    ):
        assert field in message
    assert f"response_bytes={len(raw)}" in message
    assert raw.decode() not in message
    assert "SOMETHING_NEW" not in message
    assert "eyJhbGciOiJIUzI1NiJ9" not in message


def test_warning_does_not_disclose_server_fields_values_uuid_token_or_sdp(caplog) -> None:
    uuid = "8d86de35-3be7-451b-b32b-cc11aa22bb33"
    token = "eyJhbGciOiJIUzI1NiJ9.private.signature"
    encoded_sdp = "dj0wDQphPWljZS11ZnJhZzpzZWNyZXQ="
    raw = _json_raw(
        {
            "result": token,
            "data": {"sdp": encoded_sdp, "privateServerKey": uuid},
            "arbitraryTopLevelKey": "arbitrary-server-value",
        }
    )

    with caplog.at_level(logging.WARNING, logger=MODULE_NAME):
        with pytest.raises(cloud.ComelitCloudError, match="remote_sdp_incomplete"):
            _negotiate(200, raw)

    warnings = [record.getMessage() for record in caplog.records]
    assert len(warnings) == 1
    assert "result_enum=UNKNOWN" in warnings[0]
    assert "sdp_present=True" in warnings[0]
    assert "top_level_field_count=3" in warnings[0]
    for forbidden in (
        uuid,
        token,
        encoded_sdp,
        "privateServerKey",
        "arbitraryTopLevelKey",
        "arbitrary-server-value",
        raw.decode(),
    ):
        assert forbidden not in warnings[0]


@pytest.mark.parametrize("status", [401, 403])
def test_http_error_preserves_status_before_json_decode(caplog, status) -> None:
    raw = b"not-json and must not be logged"

    with caplog.at_level(logging.WARNING, logger=MODULE_NAME):
        with pytest.raises(cloud.ComelitCloudHttpError) as raised:
            _negotiate(status, raw)

    assert raised.value.status == status
    assert not caplog.records


def test_malformed_json_emits_one_bounded_warning(caplog) -> None:
    raw = b'{"result":"SUCCESS","secret":"raw-body-leak-check"'

    with caplog.at_level(logging.WARNING, logger=MODULE_NAME):
        with pytest.raises(cloud.ComelitCloudError, match="response_not_json"):
            _negotiate(200, raw)

    warnings = [record.getMessage() for record in caplog.records]
    assert len(warnings) == 1
    assert f"response_bytes={len(raw)}" in warnings[0]
    assert "result_present=False" in warnings[0]
    assert "result_type=missing" in warnings[0]
    assert "result_enum=UNKNOWN" in warnings[0]
    assert "data_present=False" in warnings[0]
    assert "data_type=missing" in warnings[0]
    assert "sdp_present=False" in warnings[0]
    assert "top_level_field_count=0" in warnings[0]
    assert "raw-body-leak-check" not in warnings[0]
