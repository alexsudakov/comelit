#!/usr/bin/env python3
from __future__ import annotations

import ast
import hashlib
from pathlib import Path
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[2]
COMPONENT = ROOT / "custom_components" / "comelit"
CAMERA = COMPONENT / "camera.py"
TRANSPORT = COMPONENT / "media_transport.py"
BUTTON = COMPONENT / "button.py"
RUNTIME = COMPONENT / "runtime.py"
NATIVE_BINARY = COMPONENT / "native" / "comelit-media"

EXPECTED_MEDIA_TRANSPORT_SHA256 = (
    "0437a4bbdec1fd407d35961683dc7bb69fc29419286cb8a2078fda258b996f3a"
)
EXPECTED_NATIVE_SHA256 = (
    "35a9a1604c4bef3667713e3487b68aadc79501c4630748d7143ee9ee7cd85622"
)
EXPECTED_BUTTON_SHA256 = (
    "c0eb307d66a63f9be8fc6f74e1ea64b9a11e69b573cffec581d63393e7517090"
)
EXPECTED_RUNTIME_SHA256 = (
    "5b8cde1c438d09352ed56db8d7cc8208a0fb01e97dddfb1e679c35e34ec5648f"
)

R20_FIELDS = (
    "hls_endpoint_generated",
    "hls_probe_mode",
    "hls_probe_completed",
    "hls_http_routing_proven",
    "hls_master_probe_attempted",
    "hls_master_http_status",
    "hls_master_content_type_ok",
    "hls_master_bytes",
    "hls_master_has_extm3u",
    "hls_master_has_stream_inf",
    "hls_master_has_playlist_reference",
    "hls_master_codec_string",
    "hls_media_probe_attempted",
    "hls_media_http_status",
    "hls_media_content_type_ok",
    "hls_media_bytes",
    "hls_media_has_extm3u",
    "hls_media_has_map",
    "hls_media_has_part",
    "hls_media_has_extinf",
    "hls_media_part_reference_count",
    "hls_media_segment_reference_count",
    "hls_init_probe_attempted",
    "hls_init_http_status",
    "hls_init_content_type_ok",
    "hls_init_bytes_http",
    "hls_part_probe_attempted",
    "hls_part_http_status",
    "hls_part_content_type_ok",
    "hls_part_bytes_http",
    "camera_frontend_hls_supported",
    "camera_frontend_webrtc_supported",
    "camera_webrtc_provider_present",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _function_source(tree: ast.AST, source: str, name: str) -> str:
    node = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name
    )
    return ast.get_source_segment(source, node) or ""


def _tuple_strings(tree: ast.AST, name: str) -> tuple[str, ...]:
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
            continue
        if isinstance(node.value, ast.Tuple):
            return tuple(
                elt.value
                for elt in node.value.elts
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
            )
    raise AssertionError(f"{name} not found")


class P116R20HlsHttpBoundaryDiagnosticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.camera = CAMERA.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.camera)
        cls.handle_status = _function_source(cls.tree, cls.camera, "_handle_status_update")
        cls.probe_source = "\n".join(
            _function_source(cls.tree, cls.camera, name)
            for name in (
                "_async_probe_hls_http_boundary",
                "_async_build_hls_http_boundary_result",
                "_hls_endpoint_fragment",
                "_async_self_http_hls_probe",
                "_async_fetch_hls_scalar",
                "_async_direct_render_hls_probe",
                "_camera_frontend_capability_diagnostics",
            )
        )

    def test_probe_trigger_requires_stream_provider_and_two_segments(self) -> None:
        self.assertIn('hls_diagnostics["ha_stream_created"]', self.handle_status)
        self.assertIn('hls_diagnostics["hls_provider_present"]', self.handle_status)
        self.assertIn('hls_diagnostics["hls_segment_count"] >= 2', self.handle_status)
        self.assertIn("self.hass.async_create_task", self.handle_status)

    def test_exactly_one_probe_per_stream_generation_and_no_retry_loop(self) -> None:
        for marker in (
            "self._hls_http_probe_task",
            "self._hls_http_probe_done",
            "self._hls_http_probe_result",
            "self._reset_hls_http_probe_state()",
        ):
            self.assertIn(marker, self.camera)
        self.assertIn("self._hls_http_probe_done = False", self.camera)
        self.assertIn("self._hls_http_probe_result = None", self.camera)
        self.assertIn("self._hls_http_probe_task = None", self.camera)
        reset_source = _function_source(self.tree, self.camera, "_async_reset_stream")
        create_source = _function_source(self.tree, self.camera, "async_create_stream")
        self.assertIn("self._reset_hls_http_probe_state()", reset_source)
        self.assertLess(
            create_source.index("self.stream = stream"),
            create_source.index("self._reset_hls_http_probe_state()"),
        )
        probe_tree = ast.parse(self.probe_source)
        self.assertFalse(any(isinstance(node, ast.While) for node in ast.walk(probe_tree)))
        self.assertNotIn("while True", self.probe_source)
        self.assertNotIn("retry", self.probe_source.lower())

    def test_stream_key_material_is_never_named_stored_or_logged(self) -> None:
        self.assertNotIn("access_token", self.camera)
        log_calls = [
            ast.get_source_segment(self.camera, node) or ""
            for node in ast.walk(self.tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in {"info", "warning", "error", "debug"}
        ]
        for call in log_calls:
            self.assertNotIn("token", call.lower())
            self.assertNotIn("endpoint", call.lower())
            self.assertNotIn("address", call.lower())

    def test_master_body_is_not_exposed(self) -> None:
        self.assertIn('"hls_master_has_extm3u"', self.probe_source)
        self.assertIn('"hls_master_has_stream_inf"', self.probe_source)
        self.assertIn('"hls_master_has_playlist_reference"', self.probe_source)
        self.assertIn('"hls_master_codec_string"', self.probe_source)
        for forbidden in ("hls_master_body", "hls_master_text", "master_body"):
            self.assertNotIn(forbidden, self.camera)

    def test_media_body_is_not_exposed(self) -> None:
        self.assertIn('"hls_media_has_extm3u"', self.probe_source)
        self.assertIn('"hls_media_has_map"', self.probe_source)
        self.assertIn('"hls_media_has_part"', self.probe_source)
        self.assertIn('"hls_media_has_extinf"', self.probe_source)
        for forbidden in ("hls_media_body", "hls_media_text", "media_body"):
            self.assertNotIn(forbidden, self.camera)

    def test_init_and_part_media_bytes_are_lengths_only(self) -> None:
        self.assertIn('"hls_init_bytes_http": init["bytes"]', self.probe_source)
        self.assertIn('"hls_part_bytes_http": part["bytes"]', self.probe_source)
        self.assertIn("scalar[\"bytes\"] = len(body)", self.probe_source)
        for forbidden in (
            "hls_init_body",
            "hls_part_body",
            "hls_init_data",
            "hls_part_data",
            "repr(body)",
            "hashlib",
        ):
            self.assertNotIn(forbidden, self.probe_source)

    def test_safe_field_allowlist_is_exact(self) -> None:
        self.assertEqual(_tuple_strings(self.tree, "_HLS_HTTP_DIAGNOSTIC_FIELDS"), R20_FIELDS)
        for field in R20_FIELDS:
            self.assertIn(f'"{field}"', self.camera)
            self.assertFalse(
                field.endswith(("_body", "_url", "_token", "_path", "_sdp", "_payload")),
                field,
            )

    def test_codec_string_uses_strict_allowlist_and_unknown_fallback(self) -> None:
        self.assertIn("avc1|avc3|hvc1|hev1|mp4a|opus|mp4v", self.camera)
        codec_source = _function_source(self.tree, self.camera, "_extract_hls_codec_string")
        self.assertIn('return "unknown"', codec_source)
        self.assertIn("len(joined) > 64", codec_source)
        self.assertIn("_HLS_CODEC_STRING.fullmatch(token)", codec_source)

    def test_probe_reset_assignment_exists_in_async_reset_stream(self) -> None:
        reset_source = _function_source(self.tree, self.camera, "_async_reset_stream")
        self.assertIn("self._reset_hls_http_probe_state()", reset_source)
        reset_helper = _function_source(self.tree, self.camera, "_reset_hls_http_probe_state")
        self.assertIn("self._hls_http_probe_task = None", reset_helper)
        self.assertIn("self._hls_http_probe_done = False", reset_helper)
        self.assertIn("self._hls_http_probe_result = None", reset_helper)

    def test_no_comelit_signaling_change_in_r20_probe_segments(self) -> None:
        for forbidden in (
            "CTPP",
            "RTPC",
            "pseudo",
            "socket",
            "offer",
            "negotiate",
            "oauth",
        ):
            self.assertNotIn(forbidden, self.probe_source)

    def test_media_transport_is_unchanged(self) -> None:
        self.assertEqual(_sha256(TRANSPORT), EXPECTED_MEDIA_TRANSPORT_SHA256)

    def test_native_helper_is_unchanged(self) -> None:
        self.assertEqual(_sha256(NATIVE_BINARY), EXPECTED_NATIVE_SHA256)

    def test_door_and_gate_surfaces_are_untouched(self) -> None:
        self.assertEqual(_sha256(BUTTON), EXPECTED_BUTTON_SHA256)
        self.assertEqual(_sha256(RUNTIME), EXPECTED_RUNTIME_SHA256)
        for forbidden in ("open_door", "gate"):
            self.assertNotIn(forbidden, self.probe_source.lower())

    def test_direct_render_never_claims_http_routing(self) -> None:
        direct_source = _function_source(
            self.tree,
            self.camera,
            "_async_direct_render_hls_probe",
        )
        self.assertIn('result["hls_probe_mode"] = "direct_render"', direct_source)
        self.assertIn('result["hls_http_routing_proven"] = False', direct_source)
        self.assertIn("outputs = stream.outputs()", direct_source)
        self.assertIn("track = outputs.get(HLS_PROVIDER)", direct_source)
        self.assertIn("HlsMasterPlaylistView.render(track)", direct_source)
        self.assertIn("HlsPlaylistView.render(track)", direct_source)
        self.assertIn("inspect.isawaitable(master_text)", direct_source)
        self.assertIn("inspect.isawaitable(media_text)", direct_source)
        self.assertNotIn(".text", direct_source)
        direct_dedented = textwrap.dedent(direct_source)
        direct_tree = ast.parse(direct_dedented)
        render_calls = [
            ast.get_source_segment(direct_dedented, node) or ""
            for node in ast.walk(direct_tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "render"
        ]
        self.assertEqual(
            render_calls,
            [
                "HlsMasterPlaylistView.render(track)",
                "HlsPlaylistView.render(track)",
            ],
        )
        for field in (
            "hls_master_http_status",
            "hls_media_http_status",
            "hls_init_http_status",
            "hls_part_http_status",
        ):
            self.assertIn(f'result["{field}"] = None', direct_source)

    def test_webrtc_diagnostics_are_observation_only(self) -> None:
        frontend_source = _function_source(
            self.tree,
            self.camera,
            "_camera_frontend_capability_diagnostics",
        )
        self.assertIn("from homeassistant.components.camera.const import StreamType", self.camera)
        self.assertIn("from homeassistant.components.camera import StreamType", self.camera)
        self.assertIn("capabilities = self.camera_capabilities", frontend_source)
        self.assertIn("stream_types = capabilities.frontend_stream_types", frontend_source)
        self.assertIn("StreamType.HLS in stream_types", frontend_source)
        self.assertIn("StreamType.WEB_RTC in stream_types", frontend_source)
        self.assertIn("isinstance(stream_types, (set, frozenset, list, tuple))", frontend_source)
        self.assertNotIn("self.frontend_stream_types", frontend_source)
        self.assertNotIn("FrontendStreamType", self.camera)
        self.assertIn('getattr(self, "webrtc_provider", None) is not None', frontend_source)
        frontend_dedented = textwrap.dedent(frontend_source)
        frontend_tree = ast.parse(frontend_dedented)
        self.assertFalse(any(isinstance(node, ast.Await) for node in ast.walk(frontend_tree)))
        for node in ast.walk(frontend_tree):
            if not isinstance(node, ast.Call):
                continue
            segment = ast.get_source_segment(frontend_dedented, node) or ""
            self.assertTrue(
                segment.startswith(("getattr(", "isinstance(")),
                segment,
            )

    def test_self_http_uses_internal_only_get_url_without_hardcoded_address(self) -> None:
        build_source = _function_source(
            self.tree,
            self.camera,
            "_async_build_hls_http_boundary_result",
        )
        expected_call = """get_url(
                self.hass,
                allow_internal=True,
                allow_external=False,
                prefer_external=False,
                allow_cloud=False,
            )"""
        self.assertIn(expected_call, build_source)
        self.assertEqual(self.camera.count("get_url("), 1)

        for node in ast.walk(self.tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                lower_value = node.value.lower()
                for forbidden in ("127.0.0.1", "localhost", ":8123"):
                    self.assertNotIn(forbidden, lower_value)
                if "://" in lower_value:
                    self.assertNotIn("nabu", lower_value)
                    self.assertNotIn("cloud", lower_value)

    def test_self_http_supported_failure_paths_use_direct_render_without_retry(self) -> None:
        build_source = _function_source(
            self.tree,
            self.camera,
            "_async_build_hls_http_boundary_result",
        )
        self.assertEqual(self.camera.count("get_url("), 1)

        build_dedented = textwrap.dedent(build_source)
        build_tree = ast.parse(build_dedented)
        handlers = [
            node
            for node in ast.walk(build_tree)
            if isinstance(node, ast.ExceptHandler)
        ]
        handler_types = [
            handler.type.id
            for handler in handlers
            if isinstance(handler.type, ast.Name)
        ]
        self.assertIn("NoURLAvailableError", handler_types)
        self.assertIn("Exception", handler_types)

        for handler in handlers:
            if not isinstance(handler.type, ast.Name):
                continue
            if handler.type.id not in {"NoURLAvailableError", "Exception"}:
                continue
            self.assertEqual(len(handler.body), 1)
            statement = handler.body[0]
            self.assertIsInstance(statement, ast.Return)
            statement_source = ast.get_source_segment(build_dedented, statement) or ""
            self.assertIn(
                "return await self._async_direct_render_hls_probe(",
                statement_source,
            )

    def test_part_uri_matches_exact_ha_relative_shape_only(self) -> None:
        helper = _function_source(self.tree, self.camera, "_first_relative_part_name")
        self.assertIn("_HLS_PART_URI.fullmatch(name)", helper)
        self.assertIn(
            're.compile(r"^(?:\\./)?segment/[0-9]+\\.[0-9]+\\.m4s$")',
            self.camera,
        )
        for accepted in ("./segment/0.0.m4s", "./segment/12.3.m4s"):
            self.assertRegex(accepted, r"^(?:\./)?segment/[0-9]+\.[0-9]+\.m4s$")
        for rejected in (
            "https://example.com/segment/0.0.m4s",
            "//example.com/segment/0.0.m4s",
            "../segment/0.0.m4s",
            "./other/0.0.m4s",
            "./segment/abc.0.m4s",
            "./segment/0.0.m4s?x=1",
        ):
            self.assertNotRegex(rejected, r"^(?:\./)?segment/[0-9]+\.[0-9]+\.m4s$")

    def test_part_probe_uses_exact_ha_content_type_and_safe_url_join(self) -> None:
        self_http = _function_source(self.tree, self.camera, "_async_self_http_hls_probe")
        self.assertIn('_HLS_PART_CONTENT_TYPES = ("video/iso.segment",)', self.camera)
        self.assertIn("part_address = urljoin(media_address, part_name)", self_http)
        self.assertIn("_HLS_PART_CONTENT_TYPES", self_http)

    def test_http_routing_proof_requires_master_media_init_and_part(self) -> None:
        self_http = _function_source(self.tree, self.camera, "_async_self_http_hls_probe")
        for field in (
            "hls_master_probe_attempted",
            "hls_media_probe_attempted",
            "hls_init_probe_attempted",
            "hls_part_probe_attempted",
            "hls_master_http_status",
            "hls_media_http_status",
            "hls_init_http_status",
            "hls_part_http_status",
        ):
            self.assertIn(f'"{field}"', self_http)
        self.assertIn("result.get(field) is True for field in attempt_fields", self_http)
        self.assertIn("for field in status_fields", self_http)


if __name__ == "__main__":
    unittest.main()
