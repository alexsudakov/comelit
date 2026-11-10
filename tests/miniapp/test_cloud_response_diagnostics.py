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
CLOUD_MODULE_NAME = "comelit_cloud_response_diagnostics_test_module"
try:
    import aiohttp  # noqa: F401
except ModuleNotFoundError:
    aiohttp_stub = types.ModuleType("aiohttp")
    aiohttp_stub.ClientError = type("ClientError", (Exception,), {})
    aiohttp_stub.ClientSession = object
    sys.modules["aiohttp"] = aiohttp_stub
spec = importlib.util.spec_from_file_location(
    CLOUD_MODULE_NAME, ROOT / "custom_components/comelit/cloud.py"
)
assert spec is not None and spec.loader is not None
cloud = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = cloud
spec.loader.exec_module(cloud)

ComelitCloudError = cloud.ComelitCloudError
ComelitCloudHttpError = cloud.ComelitCloudHttpError
async_negotiate_p2p = cloud.async_negotiate_p2p


REMOTE_SDP = "\r\n".join(
    (
        "v=0",
        "a=ice-ufrag:remote-user",
        "a=ice-pwd:remote-password",
        "a=candidate:1 1 UDP 1 192.0.2.1 5000 typ host",
    )
)
DEVICE_UUID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
VIP_TOKEN = "vip-secret-token-value"
OAUTH_TOKEN = "oauth-secret-token-value"
OFFER_SDP = "v=0\r\na=ice-ufrag:local-secret"


class _Response:
    def __init__(self, status: int, raw: bytes) -> None:
        self.status = status
        self._raw = raw

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def read(self) -> bytes:
        return self._raw


class _Session:
    def __init__(self, status: int, raw: bytes) -> None:
        self._response = _Response(status, raw)

    def post(self, *args, **kwargs):
        return self._response


def _call(raw: bytes, *, status: int = 200) -> str:
    return asyncio.run(
        async_negotiate_p2p(
            _Session(status, raw),
            device_uuid=DEVICE_UUID,
            vip_token=VIP_TOKEN,
            oauth_access_token=OAUTH_TOKEN,
            offer_sdp=OFFER_SDP,
        )
    )


def _diagnostics(caplog) -> dict[str, object]:
    records = [
        record
        for record in caplog.records
        if record.message.startswith("Comelit cloud P2P response diagnostics: ")
    ]
    assert len(records) == 1
    return json.loads(records[0].message.split(": ", 1)[1])


def _assert_secrets_absent(caplog, raw: bytes) -> None:
    log_text = "\n".join(record.getMessage() for record in caplog.records)
    for forbidden in (
        DEVICE_UUID,
        VIP_TOKEN,
        OAUTH_TOKEN,
        OFFER_SDP,
        REMOTE_SDP,
        base64.b64encode(REMOTE_SDP.encode()).decode(),
        raw.decode(errors="ignore"),
    ):
        if forbidden:
            assert forbidden not in log_text


def test_success_preserves_remote_sdp_behavior_and_logs_only_shape(caplog):
    encoded = base64.b64encode(REMOTE_SDP.encode()).decode()
    raw = json.dumps(
        {"result": "SUCCESS", "data": {"sdp": encoded}}, separators=(",", ":")
    ).encode()

    with caplog.at_level(logging.INFO, logger=CLOUD_MODULE_NAME):
        assert _call(raw) == REMOTE_SDP

    assert _diagnostics(caplog) == {
        "data_present": True,
        "data_type": "object",
        "response_bytes": len(raw),
        "result_enum": "SUCCESS",
        "result_present": True,
        "result_type": "string",
        "sdp_present": True,
        "top_level_field_count": 2,
    }
    _assert_secrets_absent(caplog, raw)


@pytest.mark.parametrize(
    ("body", "expected_error", "expected"),
    [
        (
            {"result": "TIMEOUT"},
            "data_not_object",
            {"result_enum": "TIMEOUT", "data_present": False},
        ),
        (
            {"result": "UNRECOGNIZED_SERVER_VALUE"},
            "data_not_object",
            {"result_enum": "UNKNOWN", "result_type": "string"},
        ),
        (
            {
                "result": "TIMEOUT",
                "private_server_field": "private-server-value",
            },
            "data_not_object",
            {"result_enum": "TIMEOUT", "top_level_field_count": 2},
        ),
        (
            {"result": "eyJhbGciOiJIUzI1NiJ9.secret.signature"},
            "data_not_object",
            {"result_enum": "UNKNOWN", "result_type": "string"},
        ),
        (
            {"data": {}},
            "remote_sdp_missing",
            {"result_present": False, "result_type": "missing"},
        ),
        (
            {"result": "SUCCESS", "data": "arbitrary-server-value"},
            "data_not_object",
            {"data_present": True, "data_type": "string"},
        ),
    ],
)
def test_error_responses_remain_fail_closed_and_values_are_redacted(
    caplog, body, expected_error, expected
):
    raw = json.dumps(body, separators=(",", ":")).encode()

    with caplog.at_level(logging.INFO, logger=CLOUD_MODULE_NAME):
        with pytest.raises(ComelitCloudError, match=f"^{expected_error}$"):
            _call(raw)

    diagnostics = _diagnostics(caplog)
    assert diagnostics.items() >= expected.items()
    _assert_secrets_absent(caplog, raw)
    for value in body.values():
        if isinstance(value, str) and value not in {"SUCCESS", "TIMEOUT"}:
            assert value not in "\n".join(r.getMessage() for r in caplog.records)
    for key in body:
        if key not in {"result", "data"}:
            assert key not in "\n".join(r.getMessage() for r in caplog.records)


@pytest.mark.parametrize("status", [401, 403])
def test_http_auth_errors_keep_status_boundary_without_logging_body(caplog, status):
    raw = b'{"result":"SUCCESS","server":"private-server-value"}'

    with caplog.at_level(logging.INFO, logger=CLOUD_MODULE_NAME):
        with pytest.raises(ComelitCloudHttpError) as raised:
            _call(raw, status=status)

    assert raised.value.status == status
    assert _diagnostics(caplog) == {
        "data_present": False,
        "data_type": "missing",
        "response_bytes": len(raw),
        "result_enum": "UNKNOWN",
        "result_present": False,
        "result_type": "missing",
        "sdp_present": False,
        "top_level_field_count": 0,
    }
    _assert_secrets_absent(caplog, raw)


def test_malformed_json_remains_fail_closed_without_logging_raw_response(caplog):
    raw = b'{"result":"SUCCESS","secret":"unterminated-token-value"'

    with caplog.at_level(logging.INFO, logger=CLOUD_MODULE_NAME):
        with pytest.raises(ComelitCloudError, match="^response_not_json$"):
            _call(raw)

    assert _diagnostics(caplog)["response_bytes"] == len(raw)
    _assert_secrets_absent(caplog, raw)
