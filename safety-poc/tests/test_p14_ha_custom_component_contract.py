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

    def test_manifest_is_single_direct_config_flow(self):
        manifest = json.loads(
            (ROOT / "custom_components/comelit/manifest.json").read_text()
        )
        self.assertEqual(manifest["domain"], "comelit")
        self.assertEqual(manifest["version"], "1.5.4")
        self.assertTrue(manifest["config_flow"])
        self.assertTrue(manifest["single_config_entry"])
        self.assertEqual(manifest["requirements"], [])

    def test_hacs_native_binary_exec_bit_is_repaired_before_launch(self):
        runtime = (ROOT / "custom_components/comelit/runtime.py").read_text()
        self.assertIn("os.chmod(_NATIVE_BINARY, 0o700)", runtime)
        self.assertIn("native_binary_chmod_failed", runtime)
        self.assertIn("native_binary_not_executable", runtime)

    def test_production_supervisor_autostarts_and_never_invokes_door(self):
        init = (ROOT / "custom_components/comelit/__init__.py").read_text()
        supervisor = (ROOT / "custom_components/comelit/supervisor.py").read_text()
        test_control = (ROOT / "custom_components/comelit/test_control.py").read_text()
        self.assertIn("await supervisor.async_start()", init)
        self.assertIn("ComelitRuntimeSupervisor", init)
        self.assertIn("RECONNECT_DELAY_SECONDS = 5", supervisor)
        self.assertIn("await self._runtime.async_start()", supervisor)
        self.assertIn("await self._runtime.async_stop()", supervisor)
        self.assertNotIn("async_open_door", supervisor)
        self.assertIn("await supervisor.async_stop()", test_control)
        self.assertIn('status["supervisor_running"]', test_control)

    def test_listener_status_sensor_is_diagnostic_and_event_driven(self):
        const = (ROOT / "custom_components/comelit/const.py").read_text()
        supervisor = (ROOT / "custom_components/comelit/supervisor.py").read_text()
        sensor = (ROOT / "custom_components/comelit/sensor.py").read_text()
        ast.parse(supervisor)
        ast.parse(sensor)
        self.assertIn('PLATFORMS = ["button", "sensor"]', const)
        self.assertIn(
            'LISTENER_STATUS_ENTITY_ID = "sensor.comelit_listener_status"', const
        )
        self.assertIn("LISTENER_CYCLE_SECONDS = 3300", const)
        self.assertIn("SensorDeviceClass.ENUM", sensor)
        self.assertIn("EntityCategory.DIAGNOSTIC", sensor)
        self.assertIn("_attr_should_poll = False", sensor)
        self.assertIn("async_add_status_listener", sensor)
        self.assertIn("async_add_status_listener", supervisor)
        for state in ("starting", "ready", "reconnecting", "stopped", "error"):
            self.assertIn(f'"{state}"', supervisor)
        self.assertIn('"reconnect_count": self._reconnect_count', supervisor)
        self.assertIn('"last_ready":', supervisor)
        self.assertNotIn("async_open_door", sensor)

    def test_intercom_media_session_contract_is_strictly_on_demand(self):
        doc = (
            ROOT / "docs/intercom-media-session-architecture.md"
        ).read_text()
        self.assertIn("on-demand only", doc)
        self.assertIn("180 seconds", doc)
        self.assertIn("deadline is absolute", doc)
        self.assertIn(
            "at most one active intercom media session across the whole Comelit integration",
            doc,
        )
        self.assertIn("switch.comelit_entrance_camera", doc)
        self.assertIn("binary_sensor.comelit_entrance_camera_active", doc)
        self.assertIn("sensor.comelit_entrance_camera_session_remaining", doc)
        self.assertIn("camera.comelit_entrance", doc)
        self.assertIn("official Comelit application can connect again", doc)
        self.assertIn("must not stop or recreate the persistent Ring/Door listener", doc)

    def test_gate_entity_is_exposed_but_actuation_remains_fail_closed(self):
        const = (ROOT / "custom_components/comelit/const.py").read_text()
        button = (ROOT / "custom_components/comelit/button.py").read_text()
        services = (ROOT / "custom_components/comelit/services.yaml").read_text()
        self.assertIn('DOOR_GATE = "gate"', const)
        self.assertIn(
            'MAIN_GATE_ENTITY_ID = "button.comelit_main_gate_open_door"', const
        )
        self.assertIn("SUPPORTED_DOORS = (DOOR_ENTRANCE,)", const)
        self.assertIn("ComelitGateDoorButton", button)
        self.assertIn('_attr_name = "Comelit — Калитка"', button)
        self.assertIn("_attr_available = False", button)
        self.assertIn('"actuation_profile_validated": False', button)
        self.assertIn('"ring_source": "00000610"', button)
        self.assertNotIn(
            "await self._runtime.async_open_door(DOOR_GATE)", button
        )
        self.assertNotIn("- gate", services)

    def test_direct_service_uses_logical_door_and_internal_operation_id(self):
        text = (ROOT / "custom_components/comelit/__init__.py").read_text()
        runtime = (ROOT / "custom_components/comelit/runtime.py").read_text()
        self.assertIn("hass.services.async_register", text)
        self.assertIn("SERVICE_OPEN_DOOR", text)
        self.assertIn("vol.Required(ATTR_DOOR): vol.In(SUPPORTED_DOORS)", text)
        self.assertIn("supports_response=SupportsResponse.OPTIONAL", text)
        self.assertIn('operation_id = f"comelit-ha-{uuid4()}"', runtime)
        self.assertNotIn("validate_operation_id", text)

    def test_standard_button_delegates_to_direct_runtime_and_fails_closed(self):
        path = ROOT / "custom_components/comelit/button.py"
        source = path.read_text()
        tree = ast.parse(source)
        press = next(
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.AsyncFunctionDef) and n.name == "async_press"
        )
        self.assertTrue(any(isinstance(n, ast.Raise) for n in ast.walk(press)))
        self.assertIn("await self._runtime.async_open_door(DOOR_ENTRANCE)", source)
        self.assertIn('"automatic_retry_allowed": False', source)
        self.assertIn('"physical_effect_asserted": False', source)
        self.assertIn('"physical_door_state": "UNKNOWN"', source)

    def test_config_flow_is_direct_and_refresh_token_is_optional(self):
        source = (ROOT / "custom_components/comelit/config_flow.py").read_text()
        self.assertIn("CONF_DEVICE_UUID", source)
        self.assertIn("CONF_VIP_TOKEN", source)
        self.assertIn("CONF_OAUTH_ACCESS_TOKEN", source)
        self.assertIn("CONF_OAUTH_REFRESH_TOKEN", source)
        self.assertIn("CONF_OAUTH_SCOPE", source)
        self.assertIn("vol.Optional(CONF_OAUTH_REFRESH_TOKEN)", source)
        self.assertIn("vol.Optional(CONF_OAUTH_SCOPE)", source)
        self.assertNotIn("async_health(require_live=True)", source)
        self.assertNotIn("parsed.port != BRIDGE_PORT", source)

    def test_oauth_refresh_contract_is_single_form_post_and_persisted(self):
        source = (ROOT / "custom_components/comelit/oauth.py").read_text()
        tree = ast.parse(source)
        refresh = next(
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.AsyncFunctionDef) and n.name == "async_refresh_oauth"
        )
        posts = [
            n
            for n in ast.walk(refresh)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr == "post"
        ]
        self.assertEqual(len(posts), 1)
        self.assertIn('"grant_type": "refresh_token"', source)
        self.assertIn('"client_id": CLIENT_ID', source)
        self.assertIn('"refresh_token": refresh_token', source)
        self.assertIn('fields["scope"] = scope', source)
        self.assertIn("scope=scope", source)
        self.assertIn("CONF_OAUTH_SCOPE", source)
        self.assertIn("REFRESH_SKEW_SECONDS = 300", source)
        self.assertIn("async_update_entry", source)
        self.assertNotIn('SCOPE = "all"', source)
        self.assertNotIn("print(", source)
        self.assertNotIn("_LOGGER", source)

    def test_runtime_retries_only_p2p_bootstrap_once_after_401(self):
        source = (ROOT / "custom_components/comelit/runtime.py").read_text()
        tree = ast.parse(source)
        cycle = next(
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.AsyncFunctionDef) and n.name == "_async_run_cycle"
        )
        calls = [
            n
            for n in ast.walk(cycle)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name)
            and n.func.id == "async_negotiate_p2p"
        ]
        self.assertEqual(len(calls), 2)
        self.assertEqual(
            [n for n in ast.walk(cycle) if isinstance(n, ast.While)], []
        )
        self.assertIn("except ComelitCloudHttpError as exc", source)
        self.assertIn("if exc.status != 401", source)
        self.assertIn("force_refresh=True", source)
        self.assertIn('"automatic_retry_allowed": False', source)
        self.assertIn('"physical_effect_asserted": False', source)

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

    def test_canonical_entity_and_service_names(self):
        text = (ROOT / "custom_components/comelit/const.py").read_text()
        self.assertIn('SERVICE_OPEN_DOOR = "open_door"', text)
        self.assertIn(
            'MAIN_ENTRANCE_ENTITY_ID = "button.comelit_main_entrance_open_door"', text
        )
        self.assertIn(
            'MAIN_GATE_ENTITY_ID = "button.comelit_main_gate_open_door"', text
        )

    def test_success_server_response_is_hmac_signed(self):
        source = (ROOT / "safety-poc/scripts/p14_ha_bridge_server.py").read_text()
        self.assertIn('method="RESPONSE"', source)
        self.assertIn('"X-Comelit-Response-Signature"', source)
        self.assertIn('"X-Comelit-Version", P14_PROTOCOL_VERSION', source)


if __name__ == "__main__":
    unittest.main()
