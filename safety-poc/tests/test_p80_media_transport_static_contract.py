#!/usr/bin/env python3
from __future__ import annotations

import ast
import hashlib
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
TRANSPORT = ROOT / "custom_components" / "comelit" / "media_transport.py"
BINARY = ROOT / "custom_components" / "comelit" / "native" / "comelit-media"
EXPECTED_SHA256 = "36b795c8bf204da87d67a34a1e214fcf33609c06013057088b23bb2b546089aa"


class P80MediaTransportStaticContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = TRANSPORT.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source)

    def test_uses_dedicated_binary_and_run_directory(self) -> None:
        self.assertIn('/ "comelit-media"', self.source)
        self.assertIn('Path("/run/comelit-media")', self.source)
        self.assertNotIn('Path("/run/comelit-p2p")', self.source)

    def test_packaged_binary_sha256_is_pinned_and_matches_repository_artifact(self) -> None:
        self.assertIn("MEDIA_NATIVE_BINARY_SHA256 = (", self.source)
        self.assertIn(EXPECTED_SHA256, self.source)
        self.assertTrue(BINARY.is_file())
        self.assertEqual(hashlib.sha256(BINARY.read_bytes()).hexdigest(), EXPECTED_SHA256)

    def test_native_gate_hashes_before_chmod_or_process_launch(self) -> None:
        gate_start = self.source.index("def _native_gate() -> None:")
        gate_end = self.source.index("\n\n\nclass ComelitEntranceMediaTransport", gate_start)
        gate = self.source[gate_start:gate_end]
        self.assertIn("actual_sha256 = _sha256_file(_MEDIA_NATIVE_BINARY)", gate)
        self.assertIn("media_native_binary_sha256_unreadable", gate)
        self.assertIn("media_native_binary_sha256_mismatch", gate)
        self.assertLess(
            gate.index("actual_sha256 = _sha256_file(_MEDIA_NATIVE_BINARY)"),
            gate.index("os.chmod(_MEDIA_NATIVE_BINARY, 0o700)"),
        )
        cycle_start = self.source.index("async def _async_run_cycle(self) -> None:")
        cycle = self.source[cycle_start:]
        self.assertLess(
            cycle.index("await self._hass.async_add_executor_job(_native_gate)"),
            cycle.index("asyncio.create_subprocess_exec("),
        )

    def test_local_rtp_sdp_matches_native_forward_ports_and_codecs(self) -> None:
        self.assertIn("MEDIA_VIDEO_RTP_PORT = 17899", self.source)
        self.assertIn("MEDIA_AUDIO_RTP_PORT = 17808", self.source)
        self.assertIn("RTP/AVP 99", self.source)
        self.assertIn("a=rtpmap:99 H264/90000", self.source)
        self.assertIn("RTP/AVP 8", self.source)
        self.assertIn("a=rtpmap:8 PCMA/8000/1", self.source)
        self.assertIn("127.0.0.1", self.source)

    def test_media_bootstrap_has_exactly_one_cloud_negotiation(self) -> None:
        method = next(
            node
            for node in ast.walk(self.tree)
            if isinstance(node, ast.AsyncFunctionDef)
            and node.name == "_async_run_cycle"
        )
        calls = [
            node
            for node in ast.walk(method)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "async_negotiate_p2p"
        ]
        self.assertEqual(len(calls), 1)
        self.assertNotIn("force_refresh=True", self.source)
        self.assertNotIn("for attempt", self.source)
        self.assertNotIn("while True:\n            remote = await async_negotiate_p2p", self.source)

    def test_transport_has_no_door_or_listener_control_surface(self) -> None:
        for forbidden in (
            "async_open_door",
            "SIGUSR1",
            "async_pause_for_media",
            "async_resume_after_media",
            "action\":\"stop",
            "action\":\"start",
        ):
            self.assertNotIn(forbidden, self.source)

    def test_helper_secret_remains_mode_600_and_is_removed(self) -> None:
        self.assertIn("os.chmod(tmp, 0o600)", self.source)
        self.assertIn("_remove_helper_secret", self.source)
        self.assertIn("COMELIT_VIP_TOKEN=", self.source)
        self.assertNotIn("_LOGGER.info(self._vip_token", self.source)

    def test_start_waits_for_protocol_media_active_marker(self) -> None:
        self.assertIn('line == "P80_MEDIA_ACTIVE=true"', self.source)
        self.assertIn("self._media_active.set()", self.source)
        self.assertIn("media_signaling_timeout", self.source)

    def test_stop_is_bounded_and_escalates_process_only(self) -> None:
        self.assertIn("await asyncio.wait_for(process.wait(), timeout=8)", self.source)
        self.assertIn("process.terminate()", self.source)
        self.assertIn("process.kill()", self.source)
        self.assertNotIn("homeassistant.restart", self.source.lower())
        self.assertNotIn("systemctl", self.source.lower())

    def test_only_safe_native_markers_drive_media_state(self) -> None:
        self.assertIn('line == "P80_VIDEO_RTP_FORWARDING=PASS"', self.source)
        self.assertIn('line == "P80_AUDIO_RTP_FORWARDING=PASS"', self.source)
        self.assertIn('"P80_WRAPPER_PROFILE_MISMATCH=true"', self.source)
        self.assertNotIn("print(raw", self.source)

    def test_native_failure_diagnostics_are_allowlisted_redacted_and_bounded(self) -> None:
        self.assertIn("_MEDIA_NATIVE_MARKER_SAFE_VALUE_RE", self.source)
        self.assertIn('"P78_",', self.source)
        self.assertIn('"P80_",', self.source)
        self.assertIn('"PSEUDOTCP_",', self.source)
        self.assertIn('else "<redacted>"', self.source)
        self.assertIn("_MEDIA_NATIVE_MARKER_TAIL_LIMIT = 40", self.source)
        self.assertIn("self._remember_native_marker(line)", self.source)
        self.assertIn("self._capture_native_failure(process.returncode)", self.source)
        self.assertIn("self._capture_native_failure(rc)", self.source)
        self.assertIn("safe_native_markers=%s", self.source)
        self.assertIn("last_native_failure_markers", self.source)
        self.assertNotIn("_LOGGER.error(line", self.source)
        self.assertNotIn("_LOGGER.info(line", self.source)


if __name__ == "__main__":
    unittest.main()
