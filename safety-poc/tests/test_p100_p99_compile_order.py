#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
MEDIA = ROOT / "research" / "media" / "v1"
sys.path.insert(0, str(MEDIA))

from entrance_p100_p99_compile_order_transform import transform


SOURCE = ROOT / "research" / "door" / "v1_5_7" / "comelit-v4-persistent-ctpp-door.c"


class P100P99CompileOrderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.candidate = transform(SOURCE.read_text(encoding="utf-8"))

    def test_p99_state_is_defined_once_and_before_first_classifier_use(self) -> None:
        text = self.candidate
        armed_def = "static gboolean p99_preactive_media_demux_armed = FALSE;"
        packets_def = "static guint64 p99_preactive_media_packets = 0;"
        armed_use = "if (!p99_active_forward && !p99_preactive_media_demux_armed)"
        packets_use = "p99_preactive_media_packets++;"

        self.assertEqual(text.count(armed_def), 1)
        self.assertEqual(text.count(packets_def), 1)
        self.assertLess(text.index(armed_def), text.index(armed_use))
        self.assertLess(text.index(packets_def), text.index(packets_use))

    def test_p99_behavior_and_safety_markers_remain(self) -> None:
        text = self.candidate
        for marker in (
            "P80_DEVICE_ACK_000A_BINDING=STATE_SCOPED_STRUCTURAL",
            "P80_DEVICE_ACK_001A_BINDING=STATE_SCOPED_STRUCTURAL",
            "P80_PREACTIVE_MEDIA_DEMUX_ARMED=true",
            "P80_PREACTIVE_MEDIA_DEMUX=PASS",
            "P80_PREACTIVE_MEDIA_PAYLOAD_EMITTED=false",
            "P80_POST_001A_ACK_GATE=PASS",
            "P78_RTPC_SIGNALING_RESULT=PASS",
            "P80_MEDIA_ACTIVE=true",
            "P80_DOOR_SIGNAL_ENTRYPOINT=false",
        ):
            self.assertIn(marker, text)
        self.assertNotIn("signal(SIGUSR1, v4_door_signal_handler);", text)


if __name__ == "__main__":
    unittest.main()
