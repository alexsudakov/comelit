#!/usr/bin/env python3
from __future__ import annotations

import ast
import hashlib
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
COMPONENT = ROOT / "custom_components" / "comelit"
SAFETY = ROOT / "safety-poc"
MEDIA = SAFETY / "research" / "media" / "v1"
if str(MEDIA) not in sys.path:
    sys.path.insert(0, str(MEDIA))

import entrance_p80_ha_media_runtime_transform as p80

TRANSPORT = COMPONENT / "media_transport.py"
CAMERA = COMPONENT / "camera.py"
SESSION = COMPONENT / "media_session.py"
SWITCH = COMPONENT / "switch.py"
BUTTON = COMPONENT / "button.py"
SERVICES = COMPONENT / "services.yaml"
BINARY = COMPONENT / "native" / "comelit-media"
SOURCE = SAFETY / "research" / "door" / "v1_5_7" / "comelit-v4-persistent-ctpp-door.c"
HARNESS = MEDIA / "entrance_p116_sdp_rtp_bridge_harness.py"
EXPECTED_SHA256 = "35a9a1604c4bef3667713e3487b68aadc79501c4630748d7143ee9ee7cd85622"


class P116HaStreamRtpBridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.transport = TRANSPORT.read_text(encoding="utf-8")
        cls.camera = CAMERA.read_text(encoding="utf-8")
        cls.session = SESSION.read_text(encoding="utf-8")
        cls.switch = SWITCH.read_text(encoding="utf-8")
        cls.button = BUTTON.read_text(encoding="utf-8")
        cls.services = SERVICES.read_text(encoding="utf-8")
        cls.harness = HARNESS.read_text(encoding="utf-8")
        cls.candidate = p80.transform(SOURCE.read_text(encoding="utf-8"))

    def test_t1_sdp_declares_non_interleaved_h264_packetization(self) -> None:
        self.assertIn("a=fmtp:99 packetization-mode=1", self.transport)
        self.assertEqual(self.transport.count("a=fmtp:99"), 1)
        self.assertIn("_LOCAL_RTP_SDP.encode(\"ascii\")", self.transport)
        self.assertIn('"""v=0\\r', self.transport)

    def test_t2_helper_rtp_contract_matches_sdp_ports_payload_types_and_forms(self) -> None:
        self.assertIn("MEDIA_VIDEO_RTP_PORT = 17899", self.transport)
        self.assertIn("MEDIA_VIDEO_HA_RTP_PORT = 17999", self.transport)
        self.assertIn("MEDIA_AUDIO_RTP_PORT = 17808", self.transport)
        self.assertIn("m=video {MEDIA_VIDEO_HA_RTP_PORT} RTP/AVP 99", self.transport)
        self.assertIn("m=audio {MEDIA_AUDIO_RTP_PORT} RTP/AVP 8", self.transport)
        self.assertIn("a=rtpmap:99 H264/90000", self.transport)
        self.assertIn("a=rtpmap:8 PCMA/8000/1", self.transport)
        self.assertIn("a=recvonly", self.transport)
        self.assertIn("P80_VIDEO_RTP_PORT 17899", self.candidate)
        self.assertIn("P80_AUDIO_RTP_PORT 17808", self.candidate)
        self.assertIn("payload_type != 99u && payload_type != 8u", self.candidate)
        self.assertIn("nal_type in {1, 5}", self.harness)
        self.assertIn("_packetize_single", self.harness)
        self.assertIn("_packetize_fu_a", self.harness)

    def test_t3_no_capture_specific_sps_pps_or_historical_profile_literals(self) -> None:
        committed = [
            TRANSPORT,
            CAMERA,
            MEDIA / "entrance_p80_ha_media_runtime_transform.py",
            HARNESS,
        ]
        forbidden_literals = {
            "Z0" + "LA",
            "Z0" + "IA",
            "a" + "M4",
            "42" + "e01e",
            "42" + "c015",
            "42" + "8015",
        }
        for path in committed:
            text = path.read_text(encoding="utf-8")
            for literal in forbidden_literals:
                self.assertNotIn(literal, text, path)
        self.assertNotRegex(
            self.transport,
            r"sprop-parameter-sets=[A-Za-z0-9+/=]+,[A-Za-z0-9+/=]+",
        )

    def test_t5_sdp_publication_is_fail_closed_until_ready(self) -> None:
        self.assertIn("def _write_local_sdp() -> None:", self.transport)
        self.assertIn("_atomic_write(_MEDIA_LOCAL_SDP_FILE", self.transport)
        self.assertIn("def _remove_local_sdp() -> None:", self.transport)
        self.assertIn("await self._hass.async_add_executor_job(_remove_local_sdp)", self.transport)
        self.assertIn("def local_sdp_ready(self) -> bool:", self.transport)
        self.assertIn("shim.running", self.transport)
        self.assertIn("_MEDIA_LOCAL_SDP_FILE.is_file()", self.transport)
        run_cycle = self.transport.split("async def _async_run_cycle", 1)[1].split(
            "async def _async_read_output", 1
        )[0]
        self.assertLess(
            run_cycle.index("active_wait = asyncio.create_task(self._media_active.wait())"),
            run_cycle.index("await self._hass.async_add_executor_job(_write_local_sdp)"),
        )
        self.assertIn("self._transport.local_sdp_ready", self.camera)
        self.assertIn("if not ready:\n            return None", self.camera)

    def test_t6_camera_stream_gate_does_not_start_or_duplicate_sessions(self) -> None:
        self.assertIn("if self.stream is None:", self.camera)
        self.assertIn("self.hass.data[STREAM_DOMAIN][ATTR_STREAMS].append(stream)", self.camera)
        self.assertNotIn(".async_acquire(", self.camera)
        for forbidden in (
            "async_negotiate_p2p",
            "async_pause_for_media",
            "async_resume_after_media",
            "SIGUSR1",
        ):
            self.assertNotIn(forbidden, self.camera)
            self.assertNotIn(forbidden, self.switch)

    def test_t7_hard_limit_and_door_gate_paths_are_unchanged(self) -> None:
        self.assertIn("MEDIA_SESSION_HARD_LIMIT_SECONDS = 600", self.session)
        self.assertNotIn("gate", self.services.lower())
        self.assertNotIn("async_open_door(DOOR_GATE", self.button)
        self.assertIn('ENTRANCE_CAMERA_ENTITY_ID = "camera.comelit_entrance"', (COMPONENT / "const.py").read_text(encoding="utf-8"))

    def test_t8_native_binary_pin_matches_installed_artifact_and_transform_invariants_remain(self) -> None:
        self.assertIn(EXPECTED_SHA256, self.transport)
        self.assertEqual(hashlib.sha256(BINARY.read_bytes()).hexdigest(), EXPECTED_SHA256)
        intercept = self.candidate.index("p80_try_forward_wrapped_rtp")
        notify = self.candidate.index("pseudo_tcp_socket_notify_packet", intercept)
        self.assertLess(intercept, notify)
        for invariant in (
            "inner_len + 8u != len",
            "(packet[0] >> 6) != 2",
            "payload_type != 99u && payload_type != 8u",
            "raw media bytes are never printed",
        ):
            self.assertIn(invariant, self.candidate if invariant != "raw media bytes are never printed" else p80.__doc__)

    def test_t9_harness_is_offline_stdlib_and_reports_red_green_scalars(self) -> None:
        tree = ast.parse(self.harness)
        imports = {
            alias.name.split(".", 1)[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        from_imports = {
            node.module.split(".", 1)[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        }
        self.assertLessEqual(
            imports | from_imports,
            {
                "argparse",
                "base64",
                "json",
                "pathlib",
                "shutil",
                "socket",
                "subprocess",
                "tempfile",
                "threading",
                "time",
                "__future__",
            },
        )
        for marker in (
            "HARNESS_RED_",
            "HARNESS_GREEN_",
            "HARNESS_SPROP_",
            "packetization.upper()",
            "HOST_RUN_COMMAND=",
            "HOST_RUN_DESCRIPTION=",
        ):
            self.assertIn(marker, self.harness)
        self.assertNotIn("async_negotiate_p2p", self.harness)
        self.assertNotIn("homeassistant", self.harness.lower())

    def test_t10_harness_is_bounded_repeating_and_has_production_shaped_variant(self) -> None:
        for marker in (
            "while time.monotonic() < deadline",
            "process.terminate()",
            "process.kill()",
            "terminated",
            "ffmpeg_rc",
            "reassembled_aus",
            "m=audio {AUDIO_PORT} RTP/AVP 8",
            "a=rtpmap:8 PCMA/8000/1",
            "--video-silence-after-keyframe-ms",
            "HARNESS_AUDIO_SILENCE_VARIANT",
        ):
            self.assertIn(marker, self.harness)
        self.assertNotIn("TimeoutExpired: Command", self.harness)


if __name__ == "__main__":
    unittest.main()
