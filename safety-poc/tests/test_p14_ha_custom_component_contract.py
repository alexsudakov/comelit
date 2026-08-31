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


def load_signing_module():
    path = ROOT / "custom_components" / "comelit" / "signing.py"
    spec = importlib.util.spec_from_file_location("p14_ha_signing_contract", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class P14HomeAssistantContractTests(unittest.TestCase):
    def test_ha_signer_is_wire_compatible_with_ct120_verifier(self):
        signing = load_signing_module()
        op_id = f"p13-hermes-{uuid.uuid4()}"
        nonce = "abcdefghijklmnopqrstuvwx"
        body, headers = signing.build_signed_open_door_request(
            shared_secret=SECRET,
            operation_id=op_id,
            now=NOW,
            nonce=nonce,
        )
        with tempfile.TemporaryDirectory() as td:
            verifier = P14SignedRequestVerifier(
                shared_secret=SECRET.encode(),
                replay_store=P14ReplayStore(Path(td) / "replay.sqlite3"),
                max_clock_skew_seconds=30,
            )
            self.assertEqual(
                verifier.verify_open_door(headers=headers, body=body, now=NOW),
                op_id,
            )
        self.assertEqual(json.loads(body), {"operation_id": op_id})

    def test_ct120_response_signature_is_verified_by_ha_signer(self):
        signing = load_signing_module()
        nonce = "abcdefghijklmnopqrstuvwx"
        request_headers = {
            "X-Comelit-Timestamp": str(NOW),
            "X-Comelit-Nonce": nonce,
        }
        response_body = json.dumps(
            {
                "ok": True,
                "operation_id": f"p13-hermes-{uuid.uuid4()}",
                "state": "UNKNOWN_OUTCOME",
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
            body=response_body,
        )
        response_headers = {"X-Comelit-Response-Signature": signature}
        self.assertTrue(
            signing.verify_signed_open_door_response(
                shared_secret=SECRET,
                request_headers=request_headers,
                response_headers=response_headers,
                body=response_body,
            )
        )
        tampered = response_body.replace(b"UNKNOWN_OUTCOME", b"FAILED_SAFE")
        self.assertFalse(
            signing.verify_signed_open_door_response(
                shared_secret=SECRET,
                request_headers=request_headers,
                response_headers=response_headers,
                body=tampered,
            )
        )

    def test_manifest_is_single_local_config_flow(self):
        manifest = json.loads(
            (ROOT / "custom_components" / "comelit" / "manifest.json").read_text()
        )
        self.assertEqual(manifest["domain"], "comelit")
        self.assertTrue(manifest["config_flow"])
        self.assertTrue(manifest["single_config_entry"])
        self.assertEqual(manifest["iot_class"], "local_push")
        self.assertEqual(manifest["requirements"], [])

    def test_service_registration_is_entity_scoped_and_requires_operation_id(self):
        text = (ROOT / "custom_components" / "comelit" / "__init__.py").read_text()
        self.assertIn("async_register_platform_entity_service", text)
        self.assertIn("entity_domain=BUTTON_DOMAIN", text)
        self.assertIn("vol.Required(ATTR_OPERATION_ID)", text)
        self.assertIn('func="async_open_door"', text)

    def test_standard_button_press_is_fail_closed(self):
        path = ROOT / "custom_components" / "comelit" / "button.py"
        source = path.read_text()
        tree = ast.parse(source)
        press = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "async_press"
        )
        self.assertTrue(
            any(isinstance(node, ast.Raise) for node in ast.walk(press)),
            "async_press must raise instead of invoking the bridge",
        )
        press_text = ast.get_source_segment(source, press) or ""
        self.assertNotIn("async_open_door", press_text)
        self.assertNotIn("_client", press_text)

    def test_ha_client_open_door_has_no_retry_loop(self):
        path = ROOT / "custom_components" / "comelit" / "client.py"
        tree = ast.parse(path.read_text())
        method = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "async_open_door"
        )
        loops = [node for node in ast.walk(method) if isinstance(node, (ast.For, ast.While))]
        self.assertEqual(loops, [])

    def test_canonical_entity_and_service_names_match_dialog_service_contract(self):
        text = (ROOT / "custom_components" / "comelit" / "const.py").read_text()
        self.assertIn('SERVICE_OPEN_DOOR = "open_door"', text)
        self.assertIn(
            'MAIN_ENTRANCE_ENTITY_ID = "button.comelit_main_entrance_open_door"',
            text,
        )

    def test_successful_server_response_is_hmac_signed(self):
        source = (ROOT / "safety-poc" / "scripts" / "p14_ha_bridge_server.py").read_text()
        self.assertIn('method="RESPONSE"', source)
        self.assertIn('"X-Comelit-Response-Signature"', source)
        self.assertIn("response_auth=(", source)


if __name__ == "__main__":
    unittest.main()
