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
        cls.ring_media = (COMPONENT / "ring_media.py").read_text(encoding="utf-8")
        cls.session = (COMPONENT / "media_session.py").read_text(encoding="utf-8")
        cls.manifest = json.loads(
            (COMPONENT / "manifest.json").read_text(encoding="utf-8")
        )

    def test_platforms_and_runtime_data_are_registered(self) -> None:
        # The switch remains forwarded for one transition release, but is
        # disabled by default and is no longer the normal media owner.
        self.assertIn('PLATFORMS = ["button", "sensor", "switch", "camera"]', self.const)
        self.assertIn('DATA_MEDIA_TRANSPORTS = "media_transports"', self.const)
        self.assertIn('DATA_MEDIA_SESSIONS = "media_sessions"', self.const)
        self.assertIn('DATA_MEDIA_PROVIDERS = "media_providers"', self.const)
        self.assertIn(
            'DATA_ATTACHED_MEDIA_PROVIDERS = "attached_media_providers"', self.const
        )
        self.assertIn('ENTRANCE_CAMERA_ENTITY_ID = "camera.comelit_entrance"', self.const)

    def test_setup_wires_sessions_and_shared_stream_providers_before_platforms(self) -> None:
        transport = self.init.index("media_transport = ComelitEntranceMediaTransport(")
        manager = self.init.index("media_manager = ComelitMediaSessionManager(")
        attached = self.init.index("attached_session = ComelitAttachedRingMediaSession(")
        media_provider = self.init.index("synthetic_ring_media_provider = HAStreamMediaProvider(")
        attached_provider = self.init.index("ring_media_provider = HAStreamMediaProvider(")
        forward = self.init.index("async_forward_entry_setups(entry, PLATFORMS)")
        self.assertLess(transport, manager)
        self.assertLess(manager, forward)
        self.assertLess(attached, forward)
        self.assertLess(media_provider, forward)
        self.assertLess(attached_provider, forward)
        self.assertIn("media_providers[entry.entry_id] = synthetic_ring_media_provider", self.init)
        self.assertIn("attached_providers[entry.entry_id] = ring_media_provider", self.init)

    def test_unload_stops_media_before_supervisor_without_listener_resume(self) -> None:
        shutdown = self.init.index("await media_manager.async_shutdown()")
        supervisor_stop = self.init.index("await supervisor.async_stop()", shutdown)
        self.assertLess(shutdown, supervisor_stop)
        shutdown_method = self.session.split("async def async_shutdown", 1)[1].split(
            "async def _async_expire_after_deadline", 1
        )[0]
        self.assertIn("await self._transport.async_stop()", shutdown_method)
        self.assertNotIn("async_resume_after_media", shutdown_method)

    def test_camera_is_normal_ha_start_stop_owner(self) -> None:
        self.assertIn("async def _async_acquire_camera_view_media", self.camera)
        self.assertIn(
            'await self._manager.async_acquire(\n                    panel="entrance",\n'
            '                    reason=_CAMERA_VIEW_LEASE_REASON,',
            self.camera,
        )
        self.assertIn("await owner.async_release(reason=_CAMERA_VIEW_LEASE_REASON)", self.camera)
        self.assertIn('"automatic_session_start": True', self.camera)
        self.assertIn(
            '"automatic_session_start_trigger": "ha_stream_request"', self.camera
        )
        for forbidden in (
            "async_negotiate_p2p",
            "async_pause_for_media",
            "async_resume_after_media",
            "async_open_door",
            "SIGUSR1",
        ):
            self.assertNotIn(forbidden, self.camera)

    def test_camera_reuses_attached_ring_owner_when_claimed(self) -> None:
        self.assertIn("attached_session.claimed", self.camera)
        self.assertIn('owner_kind="attached_inbound"', self.camera)
        self.assertIn("await self._async_wait_for_attached_claim()", self.camera)
        self.assertIn("attached_inbound_media_busy", self.camera)

    def test_switch_is_deprecated_disabled_debug_fallback(self) -> None:
        self.assertIn("_attr_entity_registry_enabled_default = False", self.switch)
        self.assertIn('"deprecated": True', self.switch)
        self.assertIn('"replacement_entity_id": ENTRANCE_CAMERA_ENTITY_ID', self.switch)
        self.assertIn(
            'await self._manager.async_acquire(panel="entrance", reason="ha_switch")',
            self.switch,
        )
        self.assertIn(
            'await self._manager.async_force_stop(reason="ha_switch_off")',
            self.switch,
        )

    def test_thumbnail_and_still_requests_never_start_media(self) -> None:
        stills = self.camera.split("def use_stream_for_stills", 1)[1].split(
            "@property", 1
        )[0]
        self.assertIn("return False", stills)
        image_method = self.camera.split("async def async_camera_image", 1)[1].split(
            "async def async_added_to_hass", 1
        )[0]
        self.assertNotIn("async_create_stream(", image_method)
        self.assertNotIn("async_acquire", image_method)
        self.assertIn("if owner is None or not owner.active or stream is None:", image_method)
        self.assertIn("return None", image_method)

    def test_preload_is_persistently_forced_off_and_startup_race_fails_closed(self) -> None:
        self.assertIn("async def _async_disable_preload_stream", self.camera)
        self.assertIn("preload_stream=False", self.camera)
        self.assertIn('"preload_stream_allowed": False', self.camera)
        create_method = self.camera.split("async def async_create_stream", 1)[1].split(
            "async def async_camera_image", 1
        )[0]
        self.assertIn("if not self._automatic_start_ready:", create_method)
        self.assertIn("return None", create_method)

    def test_shared_ha_stream_is_owned_by_named_consumers(self) -> None:
        self.assertIn("async def async_acquire_consumer", self.ring_media)
        self.assertIn("async def async_release_consumer", self.ring_media)
        self.assertIn("async def async_get_stream", self.ring_media)
        self.assertIn("_SAFE_STREAM_CONSUMER", self.ring_media)
        self.assertIn("provider.async_acquire_consumer", self.camera)
        self.assertIn("provider.async_release_consumer", self.camera)
        self.assertIn("provider.async_get_stream()", self.camera)

    def test_camera_release_follows_ha_stream_provider_lifecycle(self) -> None:
        self.assertIn("async def _async_monitor_camera_view", self.camera)
        self.assertIn("outputs = stream.outputs()", self.camera)
        self.assertIn('reason = "last_stream_provider_removed"', self.camera)
        self.assertIn('reason = "hls_idle"', self.camera)
        self.assertIn('reason = "provider_never_started"', self.camera)
        self.assertIn('reason = "camera_view_absolute_timeout"', self.camera)
        self.assertIn("await self._async_release_camera_view_media()", self.camera)

    def test_stream_adapter_stays_in_shared_provider_not_camera_bootstrap(self) -> None:
        self.assertIn(
            'pyav_options={"protocol_whitelist": "file,udp,rtp"}',
            self.ring_media,
        )
        self.assertIn("self._hass.data[STREAM_DOMAIN][ATTR_STREAMS].append(stream)", self.ring_media)
        create_method = self.camera.split("async def async_create_stream", 1)[1].split(
            "async def async_camera_image", 1
        )[0]
        self.assertNotIn("Stream(", create_method)
        self.assertNotIn("pyav_options", create_method)

    def test_camera_exposes_bounded_runtime_progress_diagnostics(self) -> None:
        self.assertIn('"video_packet_count": self._transport.video_packet_count', self.camera)
        self.assertIn('"audio_packet_count": self._transport.audio_packet_count', self.camera)
        self.assertIn('"video_last_packet_age_seconds":', self.camera)
        self.assertIn('"audio_last_packet_age_seconds":', self.camera)
        self.assertIn("self._transport.async_add_status_listener", self.camera)
        self.assertNotIn("should_poll = True", self.camera)

    def test_stream_dependency_is_explicit(self) -> None:
        self.assertIn("webhook", self.manifest["dependencies"])
        self.assertIn("stream", self.manifest["dependencies"])

    def test_hard_limit_and_no_hidden_retry_remain_explicit(self) -> None:
        self.assertIn("MEDIA_SESSION_HARD_LIMIT_SECONDS = 600", self.session)
        self.assertIn("_CAMERA_VIEW_ABSOLUTE_LIMIT_SECONDS = 600.0", self.camera)
        self.assertIn('"automatic_retry_allowed": False', self.switch)
        self.assertIn(
            '"hard_limit_seconds": self._manager.hard_limit_seconds',
            self.camera,
        )


if __name__ == "__main__":
    unittest.main()
