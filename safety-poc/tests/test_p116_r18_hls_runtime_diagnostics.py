#!/usr/bin/env python3
from __future__ import annotations

import ast
import hashlib
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
COMPONENT = ROOT / "custom_components" / "comelit"
CAMERA = COMPONENT / "camera.py"
TRANSPORT = COMPONENT / "media_transport.py"
SESSION = COMPONENT / "media_session.py"
NATIVE_BINARY = COMPONENT / "native" / "comelit-media"

EXPECTED_MEDIA_TRANSPORT_SHA256 = (
    "65ceb05be045922f2359ed8a8dbc4ffb8678e5ad91f144dc9976b2f0975c8879"
)
EXPECTED_MEDIA_SESSION_SHA256 = (
    "65fe703f5a33207502fc6a2984d5edd0712813b174d41b48c6e3e5b10423d7bc"
)
EXPECTED_NATIVE_SHA256 = (
    "35a9a1604c4bef3667713e3487b68aadc79501c4630748d7143ee9ee7cd85622"
)

DIAGNOSTIC_FIELDS = (
    "ha_stream_created",
    "ha_stream_available",
    "ha_stream_worker_error_count",
    "ha_stream_start_worker_count",
    "ha_stream_container_format",
    "ha_stream_video_codec",
    "hls_provider_present",
    "hls_segment_count",
    "hls_part_count",
    "hls_init_bytes",
    "hls_first_part_bytes",
    "hls_first_part_has_keyframe",
    "hls_first_segment_complete",
    "hls_second_segment_created",
)

DIAGNOSTIC_METHODS = (
    "_hls_runtime_diagnostics",
    "_log_hls_runtime_diagnostics_if_changed",
)

WORKER_ERROR_COUNT_KEYS = (
    "stream_worker_error_count",
    "worker_error_count",
    "error_count",
)

START_WORKER_COUNT_KEYS = (
    "start_worker_count",
    "stream_start_worker_count",
    "worker_start_count",
)

EXISTING_EXTRA_STATE_KEYS = (
    "media_active",
    "media_phase",
    "expires_at",
    "remaining_seconds",
    "listener_paused",
    "video_forwarding",
    "audio_forwarding",
    "video_packet_count",
    "audio_packet_count",
    "video_last_packet_age_seconds",
    "audio_last_packet_age_seconds",
    "automatic_session_start",
    "hard_limit_seconds",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _parent_map(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    parents: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent
    return parents


def _is_direct_len_arg(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> bool:
    parent = parents.get(node)
    return (
        isinstance(parent, ast.Call)
        and isinstance(parent.func, ast.Name)
        and parent.func.id == "len"
        and len(parent.args) == 1
        and parent.args[0] is node
    )


def _function_source(tree: ast.AST, source: str, name: str) -> str:
    node = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == name
    )
    return ast.get_source_segment(source, node) or ""


class P116R18HlsRuntimeDiagnosticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.camera = CAMERA.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.camera)
        cls.parents = _parent_map(cls.tree)

    def test_all_14_diagnostic_fields_are_present(self) -> None:
        for field in DIAGNOSTIC_FIELDS:
            self.assertIn(f'"{field}"', self.camera)
        self.assertIn("_HLS_DIAGNOSTIC_FIELDS", self.camera)
        self.assertIn("attrs.update(self._hls_runtime_diagnostics())", self.camera)

    def test_hls_provider_and_ha_stream_public_diagnostics_are_used(self) -> None:
        self.assertIn("from homeassistant.components.stream import HLS_PROVIDER", self.camera)
        self.assertIn('HLS_PROVIDER = "hls_provider"', self.camera)
        self.assertIn("self.hass.data[STREAM_DOMAIN]", self.camera)
        self.assertIn(".get(HLS_PROVIDER)", self.camera)
        self.assertIn("stream.get_diagnostics()", self.camera)
        self.assertIn("stream.outputs()", self.camera)
        self.assertIn("provider.get_segments()", self.camera)

    def test_per_output_counter_candidates_are_defensive(self) -> None:
        for key in WORKER_ERROR_COUNT_KEYS:
            self.assertIn(f'"{key}"', self.camera)
        for key in START_WORKER_COUNT_KEYS:
            self.assertIn(f'"{key}"', self.camera)
        self.assertIn("_HLS_WORKER_ERROR_COUNT_KEYS", self.camera)
        self.assertIn("_HLS_START_WORKER_COUNT_KEYS", self.camera)

        diagnostic_source = _function_source(
            self.tree, self.camera, "_hls_runtime_diagnostics"
        )
        self.assertIn("for candidate in _HLS_WORKER_ERROR_COUNT_KEYS", diagnostic_source)
        self.assertIn("for candidate in _HLS_START_WORKER_COUNT_KEYS", diagnostic_source)
        self.assertIn("output_diagnostics.get(candidate)", diagnostic_source)
        self.assertIn("not isinstance(value, bool)", diagnostic_source)
        self.assertIn("value >= 0", diagnostic_source)

    def test_stream_outputs_are_only_read_through_public_diagnostics(self) -> None:
        diagnostic_method = next(
            node
            for node in ast.walk(self.tree)
            if isinstance(node, ast.FunctionDef)
            and node.name == "_hls_runtime_diagnostics"
        )
        output_reads = [
            node
            for node in ast.walk(diagnostic_method)
            if isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "output"
        ]
        self.assertEqual(["get_diagnostics"], [node.attr for node in output_reads])

    def test_init_and_part_data_lengths_are_exported_without_bytes(self) -> None:
        for node in ast.walk(self.tree):
            if not isinstance(node, ast.Attribute) or node.attr not in {"init", "data"}:
                continue
            segment = ast.get_source_segment(self.camera, node) or ""
            if segment.endswith("hass.data"):
                continue
            self.assertTrue(_is_direct_len_arg(node, self.parents), segment)

    def test_has_keyframe_is_exported_only_as_bool(self) -> None:
        seen = False
        for node in ast.walk(self.tree):
            if not isinstance(node, ast.Attribute) or node.attr != "has_keyframe":
                continue
            seen = True
            parent = self.parents.get(node)
            self.assertIsInstance(parent, ast.Call)
            self.assertIsInstance(parent.func, ast.Name)
            self.assertEqual(parent.func.id, "bool")
        self.assertTrue(seen)

    def test_sensitive_strings_and_protocol_paths_are_absent_from_camera(self) -> None:
        for forbidden in ("access_token", "endpoint_url"):
            self.assertNotIn(forbidden, self.camera)

        diagnostic_source = "\n".join(
            _function_source(self.tree, self.camera, name) for name in DIAGNOSTIC_METHODS
        )
        for forbidden in (
            "open_door",
            "gate",
            "CTPP",
            "RTPC",
            "pseudo",
            "socket",
            "SDP",
            "oauth",
            "access_token",
            "endpoint_url",
            "requests",
            "subprocess",
            "urllib",
            "aiohttp",
        ):
            self.assertNotIn(forbidden, diagnostic_source)

    def test_logger_payload_is_bounded_scalars_only(self) -> None:
        log_source = _function_source(
            self.tree, self.camera, "_log_hls_runtime_diagnostics_if_changed"
        )
        self.assertIn('payload["video_packet_count"]', log_source)
        for field in DIAGNOSTIC_FIELDS:
            self.assertIn(field, self.camera)
        self.assertNotIn(".init", log_source)
        self.assertNotIn(".data", log_source)
        self.assertNotIn("repr(", log_source)
        self.assertIn("_format_diagnostic_value(value)", log_source)
        self.assertIn('" ".join(', log_source)

    def test_observation_boundary_has_no_media_mutators_or_entity_identity_changes(self) -> None:
        for key in EXISTING_EXTRA_STATE_KEYS:
            self.assertIn(f'"{key}"', self.camera)
        for identity in (
            "_attr_name",
            "_attr_unique_id = ENTRANCE_CAMERA_UNIQUE_ID",
            '_attr_icon = "mdi:video"',
            "self.entity_id = ENTRANCE_CAMERA_ENTITY_ID",
        ):
            self.assertIn(identity, self.camera)
        diagnostic_source = "\n".join(
            _function_source(self.tree, self.camera, name) for name in DIAGNOSTIC_METHODS
        )
        for forbidden in (
            "request_keyframe",
            "generate_idr",
            "StreamSettings(",
            "configure_ll_hls",
            "async_acquire",
            "async_pause_for_media",
            "async_resume_after_media",
        ):
            self.assertNotIn(forbidden, diagnostic_source)
        self.assertIn("self._transport.video_packet_count", self.camera)

    def test_media_transport_session_and_native_binary_are_unchanged(self) -> None:
        self.assertEqual(_sha256(TRANSPORT), EXPECTED_MEDIA_TRANSPORT_SHA256)
        self.assertEqual(_sha256(SESSION), EXPECTED_MEDIA_SESSION_SHA256)
        self.assertEqual(_sha256(NATIVE_BINARY), EXPECTED_NATIVE_SHA256)


if __name__ == "__main__":
    unittest.main()
