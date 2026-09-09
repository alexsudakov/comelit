from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MEDIA = ROOT / "research" / "media" / "v1"
if str(MEDIA) not in sys.path:
    sys.path.insert(0, str(MEDIA))

from entrance_p88_disarm_v4_listener_timeout_transform import (  # noqa: E402
    report,
    transform,
)

SOURCE = ROOT / "research" / "door" / "v1_5_7" / "comelit-v4-persistent-ctpp-door.c"


class P88DisarmV4ListenerTimeoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.generated = transform(SOURCE.read_text(encoding="utf-8"))

    def test_legacy_45_second_v4_listener_timeout_is_not_scheduled(self) -> None:
        generated = self.generated
        self.assertNotIn(
            "g_timeout_add_seconds(\n        45,\n        absolute_timeout_cb,\n        NULL\n    );",
            generated,
        )
        self.assertIn("static gboolean\nabsolute_timeout_cb(gpointer data)", generated)

    def test_active_media_reports_timeout_disarmed(self) -> None:
        generated = self.generated
        start = generated.index("static gboolean\nentrance_signal_begin_media_observation(void)")
        end = generated.index("return TRUE;", start)
        block = generated[start:end]
        self.assertIn("P80_MEDIA_ACTIVE=true", block)
        self.assertIn("P80_SIGNALING_WATCHDOG_DISARMED=true", block)
        self.assertIn("P80_V4_LISTENER_TIMEOUT_DISARMED=true", block)
        self.assertIn("p80_media_forwarding_enabled = TRUE;", block)

    def test_protocol_and_safety_gates_are_unchanged(self) -> None:
        generated = self.generated
        self.assertIn("P78_RTPC_SIGNALING_RESULT=PASS", generated)
        self.assertIn("p76_rtpc_response_is_valid(body, body_len)", generated)
        self.assertIn("P78_SECOND_CTPP_OPEN=false", generated)
        self.assertIn("P80_MEDIA_LIFETIME_OWNER=HOME_ASSISTANT", generated)
        self.assertIn("P80_MEDIA_AUTO_CLOSE_3000MS=false", generated)
        self.assertIn("P80_DOOR_SIGNAL_ENTRYPOINT=false", generated)
        self.assertNotIn("signal(SIGUSR1, v4_door_signal_handler);", generated)

    def test_report_keeps_ha_180_second_lifetime_contract(self) -> None:
        text = report()
        self.assertIn("P88_LEGACY_V4_LISTENER_TIMEOUT_45S=DISARMED", text)
        self.assertIn("P88_MEDIA_LIFETIME_OWNER=HOME_ASSISTANT", text)
        self.assertIn("P88_MEDIA_HARD_LIMIT_SECONDS=180", text)
        self.assertIn("P88_AUTOMATIC_RETRY=false", text)
        self.assertIn("P88_SECOND_CTPP_OPEN=false", text)
        self.assertIn("P88_DOOR_ACTION_SENT=false", text)
        self.assertIn("NETWORK_IO_PERFORMED=false", text)
        self.assertIn("CANDIDATE_EXECUTED=false", text)


if __name__ == "__main__":
    unittest.main()
