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
    REMOTE_SDP,
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


def test_success_returns_remote_sdp_without_diagnostic_warning(caplog) -> None:
    encoded = base64.b64encode(REMOTE_SDP.encode()).decode()

    with caplog.at_level(logging.WARNING, logger=cloud.__name__):
        remote, session = _negotiate(200, {"data": {"sdp": encoded}})

    assert remote == REMOTE_SDP
    assert session.post_calls == 1
    assert _warning_messages(caplog) == []


@pytest.mark.parametrize(
    ("payload", "expected_type", "expected_count", "expected_fields"),
    [
        (
            {"data": None, "error": "marker-response-secret"},
            "NoneType",
            2,
            ("True", "True", "False"),
        ),
        (
            {"error": "marker-response-secret", "code": "marker-code"},
            "missing",
            2,
            ("False", "True", "True"),
        ),
        (
            {"data": ["marker-response-secret"], "unknown-secret-key": "hidden"},
            "list",
            2,
            ("True", "False", "False"),
        ),
        (
            {"data": "marker-response-secret"},
            "str",
            1,
            ("True", "False", "False"),
        ),
    ],
)
def test_data_not_object_logs_only_bounded_structure(
    caplog, payload, expected_type, expected_count, expected_fields
) -> None:
    with caplog.at_level(logging.WARNING, logger=cloud.__name__):
        with pytest.raises(cloud.ComelitCloudError, match="^data_not_object$"):
            _negotiate(200, payload)

    assert len(_warning_messages(caplog)) == 1
    message = _warning_messages(caplog)[0]
    data_present, error_present, code_present = expected_fields
    assert message == (
        "Comelit cloud P2P response validation failed: "
        f"reason=data_not_object status=200 data_present={data_present} "
        f"data_type={expected_type} top_level_field_count={expected_count} "
        f"data_field_present={data_present} "
        f"error_field_present={error_present} code_field_present={code_present}"
    )
    assert "unknown-secret-key" not in message
    for marker in SECRET_MARKERS:
        assert marker not in message


@pytest.mark.parametrize("status", [401, 429, 500])
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
