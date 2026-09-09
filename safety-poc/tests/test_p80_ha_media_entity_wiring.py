#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
COMPONENT = ROOT / "custom_components" / "comelit"


class P80HaMediaEntityWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.init = (COMPONENT / "__init__.py").read_text(encoding="utf-8")
        cls.const = (COMPONENT / "const.py").read_text(encoding="utf-8")
        cls.switch = (COMPONENT / "switch.py").read_text(encoding="utf-8")
        cls.camera = (COMPONENT / "camera.py").read_text(encoding="utf-8")
        cls.session = (COMPONENT / "media_session.py").read_text(encoding="utf-8")
        cls.manifest = json.loads(
            (COMPONENT / "manifest.json").read_text(encoding="utf-8")
        )

    def test_platforms_and_runtime_data_are_registered(self) -> None:
        self.assertIn('PLATFORMS = ["button", "sensor", "switch", "camera"]', self.const)
        self.assertIn('DATA_MEDIA_TRANSPORTS = "media_transports"', self.const)
        self.assertIn('DATA_MEDIA_SESSIONS = "media_sessions"', self.const)
        self.assertIn('ENTRANCE_MEDIA_SWITCH_ENTITY_ID = "switch.comelit_entrance_camera"', self.const)
        self.assertIn('ENTRANCE_CAMERA_ENTITY_ID = "camera.comelit_entrance"', self.const)

    def test_setup_wires_one_transport_and_one_session_before_platforms(self) -> None:
        transport = self.init.index("media_transport = ComelitEntranceMediaTransport(")
        manager = self.init.index("media_manager = ComelitMediaSessionManager(")
        forward = self.init.index("async_forward_entry_setups(entry, PLATFORMS)")
        self.assertLess(transport, manager)
        self.assertLess(manager, forward)
        self.assertIn("media_transports[entry.entry_id] = media_transport", self.init)
        self.assertIn("media_sessions[entry.entry_id] = media_manager", self.init)

    def test_unload_stops_media_before_supervisor_without_listener_resume(self) -> None:
        shutdown = self.init.index("await media_manager.async_shutdown()")
        supervisor_stop = self.init.index("await supervisor.async_stop()", shutdown)
        self.assertLess(shutdown, supervisor_stop)
        shutdown_method = self.session.split("async def async_shutdown", 1)[1].split(
            "async def _async_expire_after_deadline", 1
        )[0]
        self.assertIn("await self._transport.async_stop()", shutdown_method)
        self.assertNotIn("async_resume_after_media", shutdown_method)

    def test_switch_is_the_only_ha_start_stop_owner(self) -> None:
        self.assertIn(
            'await self._manager.async_acquire(panel="entrance", reason="ha_switch")',
            self.switch,
        )
        self.assertIn(
            'await self._manager.async_force_stop(reason="ha_switch_off")',
            self.switch,
        )
        for forbidden in (
            "async_negotiate_p2p",
            "async_pause_for_media",
            "async_resume_after_media",
            "async_open_door",
            "SIGUSR1",
        ):
            self.assertNotIn(forbidden, self.switch)

    def test_camera_never_starts_or_extends_comelit_session(self) -> None:
        self.assertIn("CameraEntityFeature.STREAM", self.camera)
        self.assertIn(
            'self.stream_options["protocol_whitelist"] = "file,udp,rtp"',
            self.camera,
        )
        self.assertIn("if not self._manager.active:\n            return None", self.camera)
        self.assertIn("return str(path)", self.camera)
        self.assertIn('"automatic_session_start": False', self.camera)
        for forbidden in (
            ".async_acquire(",
            "async_negotiate_p2p",
            "async_pause_for_media",
            "async_resume_after_media",
            "async_open_door",
            "SIGUSR1",
        ):
            self.assertNotIn(forbidden, self.camera)

    def test_camera_stream_is_reset_when_explicit_media_session_ends(self) -> None:
        self.assertIn("if not self._manager.active and self.stream is not None:", self.camera)
        self.assertIn("await stream.stop()", self.camera)
        self.assertIn("self.stream = None", self.camera)

    def test_stream_dependency_is_explicit(self) -> None:
        self.assertIn("webhook", self.manifest["dependencies"])
        self.assertIn("stream", self.manifest["dependencies"])

    def test_hard_limit_and_no_hidden_retry_remain_explicit(self) -> None:
        self.assertIn("MEDIA_SESSION_HARD_LIMIT_SECONDS = 180", self.session)
        self.assertIn('"hard_limit_seconds": 180', self.switch)
        self.assertIn('"automatic_retry_allowed": False', self.switch)
        self.assertIn('"hard_limit_seconds": 180', self.camera)


if __name__ == "__main__":
    unittest.main()
