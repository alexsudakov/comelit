import ast
import importlib.util
import json
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "safety-poc" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from comelit_safety_poc.p14_ha_bridge import (
    P14ReplayStore,
    P14SignedRequestVerifier,
    sign_request,
)

SECRET = "0123456789abcdef0123456789abcdef"
NOW = 1_800_000_000


def load_module(name: str):
    path = ROOT / "custom_components" / "comelit" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"p14_ha_{name}_contract", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class P14HomeAssistantContractTests(unittest.TestCase):
    def test_ha_signer_is_wire_compatible_with_ct120_verifier(self):
        signing = load_module("signing")
        op_id = f"p13-hermes-{uuid.uuid4()}"
        nonce = "abcdefghijklmnopqrstuvwx"
        body, headers = signing.build_signed_open_door_request(
            shared_secret=SECRET, operation_id=op_id, now=NOW, nonce=nonce
        )
        with tempfile.TemporaryDirectory() as td:
            verifier = P14SignedRequestVerifier(
                shared_secret=SECRET.encode(),
                replay_store=P14ReplayStore(Path(td) / "replay.sqlite3"),
                max_clock_skew_seconds=30,
            )
            self.assertEqual(
                verifier.verify_open_door(headers=headers, body=body, now=NOW), op_id
            )
        self.assertEqual(json.loads(body), {"operation_id": op_id})

    def test_response_signature_requires_protocol_version_and_rejects_tamper(self):
        signing = load_module("signing")
        nonce = "abcdefghijklmnopqrstuvwx"
        request_headers = {
            "X-Comelit-Timestamp": str(NOW),
            "X-Comelit-Nonce": nonce,
        }
        body = json.dumps(
            {
                "ok": True,
                "operation_id": f"p13-hermes-{uuid.uuid4()}",
                "state": "UNKNOWN_OUTCOME",
                "reason": "x",
                "runner_invoked": True,
                "retry_allowed": False,
                "physical_effect_asserted": False,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        signature = sign_request(
            SECRET.encode(),
            method="RESPONSE",
            path="/v1/open-door",
            timestamp=str(NOW),
            nonce=nonce,
            body=body,
        )
        headers = {
            "X-Comelit-Version": "1",
            "X-Comelit-Response-Signature": signature,
        }
        self.assertTrue(
            signing.verify_signed_open_door_response(
                shared_secret=SECRET,
                request_headers=request_headers,
                response_headers=headers,
                body=body,
            )
        )
        bad = dict(headers)
        bad["X-Comelit-Version"] = "2"
        self.assertFalse(
            signing.verify_signed_open_door_response(
                shared_secret=SECRET,
                request_headers=request_headers,
                response_headers=bad,
                body=body,
            )
        )
        self.assertFalse(
            signing.verify_signed_open_door_response(
                shared_secret=SECRET,
                request_headers=request_headers,
                response_headers=headers,
                body=body + b" ",
            )
        )

    def test_manifest_is_single_local_config_flow(self):
        manifest = json.loads(
            (ROOT / "custom_components/comelit/manifest.json").read_text()
        )
        self.assertEqual(manifest["domain"], "comelit")
        self.assertEqual(manifest["version"], "1.0.0")
        self.assertTrue(manifest["config_flow"])
        self.assertTrue(manifest["single_config_entry"])
        self.assertEqual(manifest["requirements"], [])

    def test_service_is_response_required_and_operation_id_is_strict(self):
        text = (ROOT / "custom_components/comelit/__init__.py").read_text()
        self.assertIn("async_register_platform_entity_service", text)
        self.assertIn("supports_response=SupportsResponse.ONLY", text)
        self.assertIn("validate_operation_id", text)
        self.assertNotIn("cv.string", text)

    def test_standard_button_press_is_fail_closed_and_action_returns_result(self):
        path = ROOT / "custom_components/comelit/button.py"
        source = path.read_text()
        tree = ast.parse(source)
        press = next(
            n
            for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            and n.name == "async_press"
        )
        self.assertTrue(any(isinstance(n, ast.Raise) for n in ast.walk(press)))
        action = next(
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.AsyncFunctionDef) and n.name == "async_open_door"
        )
        self.assertTrue(any(isinstance(n, ast.Return) for n in ast.walk(action)))
        self.assertIn("physical_door_state", source)

    def test_ha_client_open_door_has_no_retry_loop_and_requires_exact_safety_flags(self):
        path = ROOT / "custom_components/comelit/client.py"
        source = path.read_text()
        tree = ast.parse(source)
        method = next(
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.AsyncFunctionDef) and n.name == "async_open_door"
        )
        self.assertEqual(
            [n for n in ast.walk(method) if isinstance(n, (ast.For, ast.While))], []
        )
        self.assertIn('payload.get("retry_allowed") is not False', source)
        self.assertIn('payload.get("physical_effect_asserted") is not False', source)
        self.assertIn('payload.get("ok") is not True', source)
        self.assertIn('isinstance(payload.get("runner_invoked"), bool)', source)

    def test_ha_client_rejects_invalid_input_before_post(self):
        source = (ROOT / "custom_components/comelit/client.py").read_text()
        build = source.index("body, headers = build_signed_open_door_request")
        rejected = source.index("invalid open-door request before send")
        post = source.index("async with self._session.post")
        self.assertLess(build, rejected)
        self.assertLess(rejected, post)
        self.assertIn("raise ComelitBridgeRejected", source)

    def test_ha_health_protocol_version_is_strict_and_non_throwing(self):
        source = (ROOT / "custom_components/comelit/client.py").read_text()
        self.assertIn(
            'payload.get("protocol_version") != BRIDGE_PROTOCOL_VERSION', source
        )
        self.assertNotIn('int(payload.get("protocol_version", 0))', source)

    def test_ha_client_never_treats_unsigned_http_error_as_proven_safe_rejection(self):
        source = (ROOT / "custom_components/comelit/client.py").read_text()
        self.assertIn("unsigned bridge error after request send", source)
        self.assertIn("ComelitBridgeOutcomeUnknown", source)
        self.assertNotIn("response.status in {400, 401, 404, 411, 413}", source)
        self.assertNotIn("Only syntactic/auth failures are known to precede runner", source)

    def test_config_flow_accepts_only_private_ipv4_http_port_18014(self):
        source = (ROOT / "custom_components/comelit/config_flow.py").read_text()
        self.assertIn('parsed.scheme != "http"', source)
        self.assertIn("parsed.port != BRIDGE_PORT", source)
        self.assertIn("ipaddress.ip_address", source)
        self.assertIn("not addr.is_private", source)
        self.assertIn("addr.is_link_local", source)
        self.assertIn("async_health(require_live=True)", source)

    def test_canonical_entity_and_service_names(self):
        text = (ROOT / "custom_components/comelit/const.py").read_text()
        self.assertIn('SERVICE_OPEN_DOOR = "open_door"', text)
        self.assertIn(
            'MAIN_ENTRANCE_ENTITY_ID = "button.comelit_main_entrance_open_door"', text
        )

    def test_success_server_response_is_hmac_signed(self):
        source = (ROOT / "safety-poc/scripts/p14_ha_bridge_server.py").read_text()
        self.assertIn('method="RESPONSE"', source)
        self.assertIn('"X-Comelit-Response-Signature"', source)
        self.assertIn('"X-Comelit-Version", P14_PROTOCOL_VERSION', source)


if __name__ == "__main__":
    unittest.main()
