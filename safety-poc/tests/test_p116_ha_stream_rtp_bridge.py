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
RING_MEDIA = COMPONENT / "ring_media.py"
ATTACHED = COMPONENT / "attached_media.py"
SESSION = COMPONENT / "media_session.py"
SWITCH = COMPONENT / "switch.py"
BUTTON = COMPONENT / "button.py"
SERVICES = COMPONENT / "services.yaml"
BINARY = COMPONENT / "native" / "comelit-media"
SOURCE = SAFETY / "research" / "door" / "v1_5_7" / "comelit-v4-persistent-ctpp-door.c"
HARNESS = MEDIA / "entrance_p116_sdp_rtp_bridge_harness.py"
EXPECTED_SHA256 = "76218861c72e9a2b87283df6c5c7e0b03a4d7fb11bee4364f59be1513acd6129"


class P116HaStreamRtpBridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.transport = TRANSPORT.read_text(encoding="utf-8")
        cls.camera = CAMERA.read_text(encoding="utf-8")
        cls.ring_media = RING_MEDIA.read_text(encoding="utf-8")
        cls.attached = ATTACHED.read_text(encoding="utf-8")
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

    def test_t6_camera_owns_bounded_live_view_without_raw_bootstrap(self) -> None:
        self.assertIn("async def _async_acquire_camera_view_media", self.camera)
        self.assertIn('reason=_CAMERA_VIEW_LEASE_REASON', self.camera)
        self.assertIn('owner_kind="on_demand"', self.camera)
        self.assertIn("_CAMERA_VIEW_ABSOLUTE_LIMIT_SECONDS = 600.0", self.camera)
        self.assertIn("provider.async_acquire_consumer", self.camera)
        self.assertIn("provider.async_release_consumer", self.camera)
        self.assertIn("provider.async_get_stream()", self.camera)
        for forbidden in (
            "async_negotiate_p2p",
            "async_pause_for_media",
            "async_resume_after_media",
            "SIGUSR1",
        ):
            self.assertNotIn(forbidden, self.camera)
            self.assertNotIn(forbidden, self.switch)

    def test_t6b_thumbnail_and_preload_cannot_bootstrap_media(self) -> None:
        stills = self.camera.split(
            "def use_stream_for_stills", 1
        )[1].split("@property", 1)[0]
        self.assertIn("return False", stills)
        image_method = self.camera.split(
            "async def async_camera_image", 1
        )[1].split("async def async_added_to_hass", 1)[0]
        self.assertNotIn("async_create_stream(", image_method)
        self.assertIn("async def _async_disable_preload_stream", self.camera)
        self.assertIn("preload_stream=False", self.camera)
        self.assertIn('"preload_stream_allowed": False', self.camera)

    def test_t6c_real_ring_reuses_attached_session_and_shared_ha_stream(self) -> None:
        self.assertIn("attached_session.claimed", self.camera)
        self.assertIn('owner_kind="attached_inbound"', self.camera)
        self.assertIn("DATA_ATTACHED_MEDIA_PROVIDERS", self.camera)
        self.assertIn("async def async_acquire_consumer", self.ring_media)
        self.assertIn("async def async_release_consumer", self.ring_media)
        self.assertIn("async def async_get_stream", self.ring_media)
        self.assertIn("stream_consumer_acquired = False", self.ring_media)
        self.assertIn("self.active or bool(self._leases)", self.attached)

    def test_t6d_camera_view_release_follows_ha_provider_lifecycle(self) -> None:
        self.assertIn("async def _async_monitor_camera_view", self.camera)
        self.assertIn("outputs = stream.outputs()", self.camera)
        self.assertIn('reason = "last_stream_provider_removed"', self.camera)
        self.assertIn('reason = "hls_idle"', self.camera)
        self.assertIn('reason = "provider_never_started"', self.camera)
        self.assertIn('reason = "camera_view_absolute_timeout"', self.camera)
        self.assertIn("await self._async_release_camera_view_media()", self.camera)

    def test_t7_hard_limit_and_r63_gate_path_remains_bounded(self) -> None:
        self.assertIn("MEDIA_SESSION_HARD_LIMIT_SECONDS = 600", self.session)
        self.assertIn("- gate", self.services.lower())
        self.assertIn("async_open_door(DOOR_GATE", self.button)
        self.assertIn('"automatic_retry_allowed": False', self.button)
        self.assertIn('"physical_effect_asserted": False', self.button)
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
