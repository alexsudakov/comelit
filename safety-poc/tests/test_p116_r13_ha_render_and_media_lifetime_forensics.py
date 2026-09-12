#!/usr/bin/env python3
from __future__ import annotations

import ast
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / ".p116-evidence"
STREAM = EVIDENCE / "stream"
MEDIA = ROOT / "safety-poc" / "research" / "media" / "v1"
TRANSPORT = ROOT / "custom_components" / "comelit" / "media_transport.py"


SAFE_REDACTION_EXPANSION = (
    r"^(?:PASS|FAIL|true|false|READY|OPEN|CLOSED|UNKNOWN_OUTCOME|"
    r"REJECTED|REJECTED_NOT_READY|FAILED_SAFE|EXPECTED_TERMINAL_SHUTDOWN|"
    r"FATAL|NONE|HOME_ASSISTANT|STATE_SCOPED_STRUCTURAL|NOT_MATCHED|"
    r"ACTIVE|PREACTIVE|DISCONNECTED|GATHERING|CONNECTING|CONNECTED|READY|"
    r"FAILED|[0-9]{1,20}|[0-9]{1,3}(?:,[0-9]{1,3}){0,127})$"
)


def _safe_value_regex() -> re.Pattern[str]:
    source = TRANSPORT.read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(target, ast.Name)
            and target.id == "_MEDIA_NATIVE_MARKER_SAFE_VALUE_RE"
            for target in node.targets
        ):
            continue
        return re.compile(ast.literal_eval(node.value.args[0]))
    raise AssertionError("_MEDIA_NATIVE_MARKER_SAFE_VALUE_RE not found")


class P116R13HaRenderAndMediaLifetimeForensicsTests(unittest.TestCase):
    def test_required_missing_inputs_are_not_silently_present(self) -> None:
        for rel in (
            "stream/hls.py",
            "stream/init.py",
            "camera/camera.py",
        ):
            self.assertFalse((EVIDENCE / rel).exists(), rel)

    def test_ha_stream_drops_pcma_audio_as_unsupported_codec(self) -> None:
        const_source = (STREAM / "const.py").read_text(encoding="utf-8")
        worker_source = (STREAM / "worker.py").read_text(encoding="utf-8")
        self.assertIn('AUDIO_CODECS = {"aac", "mp3"}', const_source)
        self.assertIn("if audio_stream and audio_stream.name not in AUDIO_CODECS:", worker_source)
        self.assertIn("audio_stream = None", worker_source)
        self.assertNotIn("pcma", const_source.lower())

    def test_ll_hls_defaults_and_muxer_first_part_boundary_are_static(self) -> None:
        init_source = (STREAM / "__init__.py").read_text(encoding="utf-8")
        worker_source = (STREAM / "worker.py").read_text(encoding="utf-8")
        core_source = (STREAM / "core.py").read_text(encoding="utf-8")
        self.assertIn("vol.Optional(CONF_LL_HLS, default=True)", init_source)
        self.assertIn("vol.Optional(CONF_SEGMENT_DURATION, default=6)", init_source)
        self.assertIn("vol.Optional(CONF_PART_DURATION, default=1)", init_source)
        self.assertIn("min_segment_duration=conf[CONF_SEGMENT_DURATION]", init_source)
        self.assertIn("frag_duration", worker_source)
        self.assertIn("part_target_duration * 9e5", worker_source)
        self.assertIn("delay_moov", worker_source)
        self.assertIn("def async_add_part", core_source)
        self.assertIn("Part(", worker_source)
        self.assertIn("has_keyframe=self._part_has_keyframe", worker_source)

    def test_timestamp_validator_drop_rules_are_static(self) -> None:
        worker_source = (STREAM / "worker.py").read_text(encoding="utf-8")
        self.assertIn("MAX_MISSING_DTS", worker_source)
        self.assertIn("if packet.dts is None:", worker_source)
        self.assertIn("return False", worker_source)
        self.assertIn("if packet.dts <= prev_dts:", worker_source)
        self.assertIn("raise StreamWorkerError(", worker_source)
        self.assertIn("filter(dts_validator.is_valid, unvalidated_packets)", worker_source)
        self.assertIn("first_keyframe = next(", worker_source)
        self.assertIn("first_keyframe.dts = first_keyframe.pts = start_dts", worker_source)

    def test_redaction_expansion_is_narrow_and_keeps_secret_shapes_redacted(self) -> None:
        current = _safe_value_regex()
        proposed = re.compile(SAFE_REDACTION_EXPANSION)
        for value in (
            "HOME_ASSISTANT",
            "STATE_SCOPED_STRUCTURAL",
            "NOT_MATCHED",
            "ACTIVE",
            "PREACTIVE",
            "CONNECTED",
            "FAILED",
        ):
            self.assertIsNone(current.fullmatch(value), value)
            self.assertIsNotNone(proposed.fullmatch(value), value)
        for secretish in (
            "abc123TOKEN456secret",
            "192.168.1.50:3478",
            "ufrag:password",
            "STATE_SCOPED_STRUCTURAL extra",
        ):
            self.assertIsNone(proposed.fullmatch(secretish), secretish)

    def test_p116_loopback_harness_reports_blocked_udp_without_capture_substitute(self) -> None:
        harness = (MEDIA / "entrance_p116_sdp_rtp_bridge_harness.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("socket_create:{exc.__class__.__name__}", harness)
        self.assertIn("HARNESS_STATUS=NOT_RUN", harness)
        self.assertIn("HOST_RUN_COMMAND=", harness)
        self.assertNotIn("media/video.rtpdatagrams", harness)


if __name__ == "__main__":
    unittest.main()
