#!/usr/bin/env python3
from __future__ import annotations

import ast
import hashlib
from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
SAFETY = ROOT / "safety-poc"
MEDIA = SAFETY / "research" / "media" / "v1"
COMPONENT = ROOT / "custom_components" / "comelit"
if str(MEDIA) not in sys.path:
    sys.path.insert(0, str(MEDIA))

import entrance_p80_ha_media_runtime_transform as p80

SOURCE = SAFETY / "research" / "door" / "v1_5_7" / "comelit-v4-persistent-ctpp-door.c"
TRANSPORT = COMPONENT / "media_transport.py"
BINARY = COMPONENT / "native" / "comelit-media"
EXPECTED_SHA256 = "91335b4490bc58910c78cb58b9c2d3eccc13f40dcfff7651995ad428cd71ddc7"

VIDEO_MARKERS = (
    "P116_VIDEO_COUNT",
    "P116_VIDEO_FIRST_SEQ",
    "P116_VIDEO_LAST_SEQ",
    "P116_VIDEO_SEQ_GAPS",
    "P116_VIDEO_DUPLICATES",
    "P116_VIDEO_OUT_OF_ORDER",
    "P116_VIDEO_FIRST_TS",
    "P116_VIDEO_LAST_TS",
    "P116_VIDEO_TIMESTAMP_REGRESSIONS",
    "P116_VIDEO_SSRC_COUNT",
    "P116_VIDEO_SSRC_CHANGES",
    "P116_VIDEO_PT_SET",
    "P116_VIDEO_MARKER_COUNT",
    "P116_VIDEO_FIRST_MONOTONIC_MS",
    "P116_VIDEO_LAST_MONOTONIC_MS",
    "P116_VIDEO_FIRST_KEYFRAME_MONOTONIC_MS",
    "P116_VIDEO_SPS_COUNT",
    "P116_VIDEO_PPS_COUNT",
    "P116_VIDEO_FUA_COUNT",
    "P116_VIDEO_SINGLE_NAL_COUNT",
)
AUDIO_MARKERS = (
    "P116_AUDIO_COUNT",
    "P116_AUDIO_FIRST_SEQ",
    "P116_AUDIO_LAST_SEQ",
    "P116_AUDIO_SEQ_GAPS",
    "P116_AUDIO_DUPLICATES",
    "P116_AUDIO_OUT_OF_ORDER",
    "P116_AUDIO_FIRST_TS",
    "P116_AUDIO_LAST_TS",
    "P116_AUDIO_TIMESTAMP_REGRESSIONS",
    "P116_AUDIO_SSRC_COUNT",
    "P116_AUDIO_SSRC_CHANGES",
    "P116_AUDIO_PT_SET",
    "P116_AUDIO_FIRST_MONOTONIC_MS",
    "P116_AUDIO_LAST_MONOTONIC_MS",
)


def _literal_tuple(source: str, name: str) -> tuple[str, ...]:
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
            return tuple(ast.literal_eval(node.value))
    raise AssertionError(f"{name} not found")


def _regex_literal(source: str, name: str) -> re.Pattern[str]:
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
            return re.compile(ast.literal_eval(node.value.args[0]))
    raise AssertionError(f"{name} not found")


class P116NativeRtpTelemetryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.candidate = p80.transform(SOURCE.read_text(encoding="utf-8"))
        cls.transport = TRANSPORT.read_text(encoding="utf-8")

    def test_native_telemetry_markers_are_present_and_scalar_only(self) -> None:
        rtp_block = self.candidate.split(
            "/* === P80_HA_MEDIA_RTP_FORWARDING_BEGIN === */", 1
        )[1].split("/* === P80_HA_MEDIA_RTP_FORWARDING_END === */", 1)[0]
        for suffix in {
            marker.removeprefix("P116_VIDEO_").removeprefix("P116_AUDIO_")
            for marker in VIDEO_MARKERS + AUDIO_MARKERS
            if marker not in {
                "P116_VIDEO_MARKER_COUNT",
                "P116_VIDEO_FIRST_KEYFRAME_MONOTONIC_MS",
                "P116_VIDEO_SPS_COUNT",
                "P116_VIDEO_PPS_COUNT",
                "P116_VIDEO_FUA_COUNT",
                "P116_VIDEO_SINGLE_NAL_COUNT",
            }
        }:
            self.assertIn(f"P116_%s_{suffix}=", self.candidate)
        for marker in (
            "P116_VIDEO_MARKER_COUNT",
            "P116_VIDEO_FIRST_KEYFRAME_MONOTONIC_MS",
            "P116_VIDEO_SPS_COUNT",
            "P116_VIDEO_PPS_COUNT",
            "P116_VIDEO_FUA_COUNT",
            "P116_VIDEO_SINGLE_NAL_COUNT",
        ):
            self.assertIn(marker + "=", self.candidate)
        self.assertNotIn("base64", rtp_block.lower())
        self.assertNotIn("sprop-parameter-sets", rtp_block)
        self.assertNotIn("body_hex", rtp_block)
        self.assertNotIn("%02x", rtp_block)
        self.assertIn("nal_type = nal_header & 0x1fu", rtp_block)
        self.assertIn("fu_header = packet[payload_offset + 1u]", rtp_block)
        self.assertNotIn("P116_VIDEO_PAYLOAD", rtp_block)

    def test_native_emission_is_first_bounded_periodic_and_final(self) -> None:
        self.assertIn("#define P116_RTP_TELEMETRY_CADENCE 50u", self.candidate)
        self.assertIn("#define P116_RTP_TELEMETRY_MAX_PERIODIC_SUMMARIES 12u", self.candidate)
        self.assertIn("stream->packet_count == 1u", self.candidate)
        self.assertIn(
            "stream->periodic_summary_count < P116_RTP_TELEMETRY_MAX_PERIODIC_SUMMARIES",
            self.candidate,
        )
        self.assertIn("p116_print_final_rtp_summary();", self.candidate)
        self.assertNotIn('printf("P116_VIDEO_PACKET_', self.candidate)
        self.assertNotIn('printf("P116_AUDIO_PACKET_', self.candidate)

    def test_sendto_call_site_keeps_forwarded_bytes_target_and_order(self) -> None:
        block = self.candidate.split("ssize_t sent = sendto(", 1)[1].split(");", 1)[0]
        self.assertIn("*fd,\n        inner,\n        inner_len,\n        0,", block)
        self.assertIn("(const struct sockaddr *)target,\n        sizeof(*target)", block)
        send_end = self.candidate.index(");", self.candidate.index("ssize_t sent = sendto("))
        observe = self.candidate.index("p116_observe_rtp(inner, inner_len, payload_type);")
        p80_count = self.candidate.index("p80_video_rtp_packets++;")
        self.assertLess(send_end, observe)
        self.assertLess(observe, p80_count)

    def test_existing_p80_forwarding_invariants_are_preserved(self) -> None:
        intercept = self.candidate.index("p80_try_forward_wrapped_rtp")
        notify = self.candidate.index("pseudo_tcp_socket_notify_packet", intercept)
        self.assertLess(intercept, notify)
        for invariant in (
            "inner_len + 8u != len",
            "(packet[0] >> 6) != 2",
            "payload_type != 99u && payload_type != 8u",
            "P80_VIDEO_RTP_FORWARDING=PASS",
            "P80_VIDEO_RTP_PACKETS=%llu",
            "P80_AUDIO_RTP_PACKETS=%llu",
        ):
            self.assertIn(invariant, self.candidate)

    def test_python_accepts_bounded_p116_markers_without_driving_media_state(self) -> None:
        prefixes = _literal_tuple(self.transport, "_MEDIA_NATIVE_MARKER_PREFIXES")
        self.assertIn("P116_", prefixes)
        safe_value = _regex_literal(self.transport, "_MEDIA_NATIVE_MARKER_SAFE_VALUE_RE")
        for value in ("0", "18446744073709551615", "8,99", "NONE"):
            self.assertRegex(value, safe_value)
        for value in ("deadbeef" * 8, "Z0LA,abcd", "1 secret", "1/2"):
            self.assertNotRegex(value, safe_value)
        reader = self.transport.split("async def _async_read_output", 1)[1]
        self.assertIn('line == "P80_MEDIA_ACTIVE=true"', reader)
        self.assertNotIn('line == "P116_', reader)
        self.assertNotIn('line.startswith(("P116_', reader)

    def test_native_binary_and_sha_pin_are_unchanged_this_round(self) -> None:
        self.assertIn(EXPECTED_SHA256, self.transport)
        self.assertEqual(hashlib.sha256(BINARY.read_bytes()).hexdigest(), EXPECTED_SHA256)

    def test_builder_has_offline_cached_rootfs_mode_and_required_gates(self) -> None:
        script = (MEDIA / "ct120_build_p80_haos_media_helper.sh").read_text(encoding="utf-8")
        for marker in (
            "OFFLINE_BUILD=${OFFLINE_BUILD:-1}",
            "OFFLINE_ROOTFS=${OFFLINE_ROOTFS:-}",
            "P80_ALPINE_DOWNLOAD=SKIPPED_OFFLINE",
            "candidate_executed=false",
            "elf_build_id=",
            "NO_GLIBC_DEPENDENCY=",
            "NO_NEW_RUNTIME_DEPENDENCY=",
            "MUSL_INTERPRETER_GATE=",
            "LIB_IDENTICAL=",
            "pkg-config --modversion nice",
            "pkg-config --modversion glib-2.0",
            "pkg-config --modversion gobject-2.0",
        ):
            self.assertIn(marker, script)


if __name__ == "__main__":
    unittest.main()
