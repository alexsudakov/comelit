from __future__ import annotations

import asyncio
import base64
import importlib.util
import json
import logging
from pathlib import Path
import sys
import types

import pytest


ROOT = Path(__file__).resolve().parents[2]
_previous_aiohttp = sys.modules.get("aiohttp")
_aiohttp_stub = types.ModuleType("aiohttp")
_aiohttp_stub.ClientError = type("ClientError", (Exception,), {})
_aiohttp_stub.ClientSession = object
sys.modules["aiohttp"] = _aiohttp_stub
SPEC = importlib.util.spec_from_file_location(
    "comelit_cloud_response_diagnostics_test",
    ROOT / "custom_components/comelit/cloud.py",
)
assert SPEC is not None and SPEC.loader is not None
cloud = importlib.util.module_from_spec(SPEC)
try:
    SPEC.loader.exec_module(cloud)
finally:
    if _previous_aiohttp is None:
        del sys.modules["aiohttp"]
    else:
        sys.modules["aiohttp"] = _previous_aiohttp

REMOTE_SDP = (
    "v=0\r\n"
    "a=ice-ufrag:remote-user\r\n"
    "a=ice-pwd:remote-password\r\n"
    "a=candidate:1 1 UDP 1 192.0.2.1 12345 typ host\r\n"
)
SECRET_MARKERS = (
    "marker-oauth-secret",
    "marker-vip-secret",
    "marker-device-uuid",
    "marker-entry-id",
    "marker-response-secret",
    "unknown-secret-key",
    "marker-code",
    "hidden",
    "123e4567-e89b-12d3-a456-426614174000",
    REMOTE_SDP,
    base64.b64encode(REMOTE_SDP.encode()).decode(),
)


class _Response:
    def __init__(self, status: int, body: bytes) -> None:
        self.status = status
        self._body = body

    async def __aenter__(self):
        return self

    async def __aexit__(self, _exc_type, _exc, _traceback) -> None:
        return None

    async def read(self) -> bytes:
        return self._body


class _Session:
    def __init__(self, status: int, body: bytes) -> None:
        self.status = status
        self.body = body
        self.post_calls = 0

    def post(self, *_args, **_kwargs) -> _Response:
        self.post_calls += 1
        return _Response(self.status, self.body)


def _negotiate(status: int, payload: object) -> tuple[str, _Session]:
    body = json.dumps(payload).encode()
    session = _Session(status, body)
    result = asyncio.run(
        cloud.async_negotiate_p2p(
            session,
            device_uuid="marker-device-uuid",
            vip_token="marker-vip-secret",
            oauth_access_token="marker-oauth-secret",
            offer_sdp="marker-offer-sdp",
        )
    )
    return result, session


def _warning_messages(caplog) -> list[str]:
    return [
        record.getMessage()
        for record in caplog.records
        if record.levelno == logging.WARNING
        and record.name == cloud.__name__
    ]


def _assert_safe_warning(caplog, **expected: object) -> str:
    messages = _warning_messages(caplog)
    assert len(messages) == 1
    message = messages[0]
    for field in (
        "response_bytes",
        "result_present",
        "result_type",
        "result_enum",
        "data_present",
        "data_type",
        "sdp_present",
        "top_level_field_count",
    ):
        assert f"{field}=" in message
    for field, value in expected.items():
        assert f"{field}={value}" in message
    for marker in SECRET_MARKERS:
        assert marker not in message
    return message


def test_success_returns_remote_sdp_without_diagnostic_warning(caplog) -> None:
    encoded = base64.b64encode(REMOTE_SDP.encode()).decode()

    with caplog.at_level(logging.WARNING, logger=cloud.__name__):
        remote, session = _negotiate(
            200, {"result": "SUCCESS", "data": {"sdp": encoded}}
        )

    assert remote == REMOTE_SDP
    assert session.post_calls == 1
    assert _warning_messages(caplog) == []


@pytest.mark.parametrize(
    (
        "payload",
        "result_type",
        "result_enum",
        "data_type",
        "expected_count",
        "existing_fields",
    ),
    [
        (
            {"result": "TIMEOUT", "data": None},
            "string",
            "TIMEOUT",
            "null",
            2,
            {"error_field_present": False, "code_field_present": False},
        ),
        (
            {
                "result": "UNEXPECTED",
                "error": "123e4567-e89b-12d3-a456-426614174000",
            },
            "string",
            "UNKNOWN",
            "missing",
            2,
            {"error_field_present": True, "code_field_present": False},
        ),
        (
            {"result": "token-looking.marker-response-secret", "data": []},
            "string",
            "UNKNOWN",
            "array",
            2,
            {"error_field_present": False, "code_field_present": False},
        ),
        (
            {"data": "marker-response-secret"},
            "missing",
            "UNKNOWN",
            "string",
            1,
            {"error_field_present": False, "code_field_present": False},
        ),
        (
            {"data": None, "error": "marker-response-secret"},
            "missing",
            "UNKNOWN",
            "null",
            2,
            {"error_field_present": True, "code_field_present": False},
        ),
        (
            {"error": "marker-response-secret", "code": "marker-code"},
            "missing",
            "UNKNOWN",
            "missing",
            2,
            {"error_field_present": True, "code_field_present": True},
        ),
        (
            {"data": ["marker-response-secret"], "unknown-secret-key": "hidden"},
            "missing",
            "UNKNOWN",
            "array",
            2,
            {"error_field_present": False, "code_field_present": False},
        ),
    ],
)
def test_result_and_invalid_data_log_only_bounded_structure(
    caplog,
    payload,
    result_type,
    result_enum,
    data_type,
    expected_count,
    existing_fields,
) -> None:
    with caplog.at_level(logging.WARNING, logger=cloud.__name__):
        with pytest.raises(cloud.ComelitCloudError, match="^data_not_object$"):
            _negotiate(200, payload)

    body = json.dumps(payload).encode()
    _assert_safe_warning(
        caplog,
        reason="data_not_object",
        status=200,
        response_bytes=len(body),
        result_present=str("result" in payload),
        result_type=result_type,
        result_enum=result_enum,
        data_present=str("data" in payload),
        data_type=data_type,
        sdp_present=False,
        top_level_field_count=expected_count,
        **existing_fields,
    )


@pytest.mark.parametrize(
    ("body", "error", "reason", "expected"),
    [
        (
            b'{"result":"SUCCESS",broken',
            "response_not_json",
            "response_not_json",
            {"result_present": False, "result_type": "missing"},
        ),
        (
            json.dumps(["marker-response-secret"]).encode(),
            "response_not_object",
            "response_not_object",
            {"top_level_field_count": 0},
        ),
    ],
)
def test_malformed_or_non_object_response_logs_one_safe_warning(
    caplog, body, error, reason, expected
) -> None:
    session = _Session(200, body)
    with caplog.at_level(logging.WARNING, logger=cloud.__name__):
        with pytest.raises(cloud.ComelitCloudError, match=f"^{error}$"):
            asyncio.run(
                cloud.async_negotiate_p2p(
                    session,
                    device_uuid="marker-device-uuid",
                    vip_token="marker-vip-secret",
                    oauth_access_token="marker-oauth-secret",
                    offer_sdp="marker-offer-sdp",
                )
            )

    _assert_safe_warning(
        caplog,
        reason=reason,
        response_bytes=len(body),
        result_enum="UNKNOWN",
        data_present=False,
        data_type="missing",
        sdp_present=False,
        **expected,
    )


def test_invalid_sdp_does_not_log_sdp_or_raw_body(caplog) -> None:
    encoded = base64.b64encode(REMOTE_SDP.encode()).decode()[:-1] + "!"
    payload = {
        "result": "SUCCESS",
        "data": {"sdp": encoded},
        "unknown-secret-key": "marker-response-secret",
    }

    with caplog.at_level(logging.WARNING, logger=cloud.__name__):
        with pytest.raises(cloud.ComelitCloudError, match="remote_sdp_decode_failed"):
            _negotiate(200, payload)

    _assert_safe_warning(
        caplog,
        reason="remote_sdp_decode_failed",
        result_present=True,
        result_type="string",
        result_enum="SUCCESS",
        data_present=True,
        data_type="object",
        sdp_present=True,
        top_level_field_count=3,
    )
    assert json.dumps(payload) not in _warning_messages(caplog)[0]


@pytest.mark.parametrize("status", [401, 403, 429, 500])
def test_http_errors_precede_body_parsing_and_emit_no_validation_warning(
    caplog, status
) -> None:
    session = _Session(status, b"marker-response-secret:not-json")

    with caplog.at_level(logging.WARNING, logger=cloud.__name__):
        with pytest.raises(cloud.ComelitCloudHttpError) as caught:
            asyncio.run(
                cloud.async_negotiate_p2p(
                    session,
                    device_uuid="marker-device-uuid",
                    vip_token="marker-vip-secret",
                    oauth_access_token="marker-oauth-secret",
                    offer_sdp="marker-offer-sdp",
                )
            )

    assert caught.value.status == status
    assert str(caught.value) == f"http_status:{status}"
    assert session.post_calls == 1
    assert _warning_messages(caplog) == []
