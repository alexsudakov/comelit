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

    def test_door_button_fails_closed_during_media_pause(self) -> None:
        self.assertIn("if self._supervisor.media_paused:", self.button)
        self.assertIn('"blocked_by_media_session": self._supervisor.media_paused', self.button)
        self.assertIn("return not self._supervisor.media_paused", self.button)

    def test_direct_door_service_also_fails_closed(self) -> None:
        self.assertIn("if supervisor.media_paused:", self.init)
        self.assertIn("media session owns the exclusive Comelit connection", self.init)

    def test_listener_sensor_exposes_media_pause(self) -> None:
        self.assertIn('"media_paused": status["media_paused"]', self.sensor)


if __name__ == "__main__":
    unittest.main()
