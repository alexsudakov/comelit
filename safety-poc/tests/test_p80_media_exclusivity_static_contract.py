#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
SUPERVISOR = ROOT / "custom_components" / "comelit" / "supervisor.py"
BUTTON = ROOT / "custom_components" / "comelit" / "button.py"
INIT = ROOT / "custom_components" / "comelit" / "__init__.py"
SENSOR = ROOT / "custom_components" / "comelit" / "sensor.py"


class P80MediaExclusivityStaticContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.supervisor = SUPERVISOR.read_text(encoding="utf-8")
        cls.button = BUTTON.read_text(encoding="utf-8")
        cls.init = INIT.read_text(encoding="utf-8")
        cls.sensor = SENSOR.read_text(encoding="utf-8")

    def test_supervisor_has_explicit_media_pause_state(self) -> None:
        self.assertIn('LISTENER_STATE_PAUSED_MEDIA = "paused_media"', self.supervisor)
        self.assertIn("async def async_pause_for_media", self.supervisor)
        self.assertIn("async def async_resume_after_media", self.supervisor)
        self.assertIn('"media_paused": self._media_paused', self.supervisor)

    def test_pause_stops_runtime_before_media_can_continue(self) -> None:
        pause = self.supervisor.split("async def async_pause_for_media", 1)[1]
        pause = pause.split("async def async_resume_after_media", 1)[0]
        self.assertIn("await self._async_stop_locked(LISTENER_STATE_PAUSED_MEDIA)", pause)
        self.assertIn("self._runtime.running or self._runtime.listener_ready", pause)
        self.assertIn("listener_pause_not_confirmed", pause)

    def test_automatic_reconnect_exits_while_media_paused(self) -> None:
        run = self.supervisor.split("async def _async_run", 1)[1]
        self.assertIn("not self._media_paused", run)
        self.assertIn("self._stopping or self._media_paused", run)
        self.assertIn("async with self._lifecycle_lock:", run)

    def test_entrance_door_dispatches_only_to_active_media_owner_during_pause(self) -> None:
        self.assertIn("async_open_entrance_door", self.button)
        self.assertIn("transport is not None and transport.active", self.button)
        self.assertIn("return await media_transport.async_open_door(event_id=event_id)", self.supervisor)
        self.assertIn('"ON_DEMAND_MEDIA_SINGLE"', self.button)
        self.assertIn(
            "self._supervisor.media_paused and not media_door_available",
            self.button,
        )

    def test_direct_door_service_uses_active_media_owner_for_entrance_only(self) -> None:
        self.assertIn("async_open_entrance_door", self.init)
        self.assertIn("door == DOOR_ENTRANCE", self.init)
        self.assertIn("await supervisor.async_open_entrance_door(", self.init)
        self.assertIn("return await media_transport.async_open_door(event_id=event_id)", self.supervisor)
        self.assertNotIn(
            "supervisor.media_paused or supervisor.attached_media_busy",
            self.init,
        )
        self.assertIn(
            '"Comelit Door is unavailable while the on-demand media "',
            self.init,
        )
        self.assertIn(
            '"session owns the exclusive connection"',
            self.init,
        )

    def test_gate_remains_fail_closed_during_media_pause(self) -> None:
        gate = self.button.split("class ComelitGateDoorButton", 1)[1]
        self.assertIn("media_paused=self._supervisor.media_paused", gate)
        self.assertIn("async_open_gate_door", gate)
        self.assertIn('raise RuntimeError("media_owns_connection")', self.supervisor)
        self.assertNotIn("media_transport", gate)

    def test_listener_sensor_exposes_media_pause(self) -> None:
        self.assertIn('"media_paused": status["media_paused"]', self.sensor)


if __name__ == "__main__":
    unittest.main()
