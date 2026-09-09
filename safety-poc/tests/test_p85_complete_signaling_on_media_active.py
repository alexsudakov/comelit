from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MEDIA = ROOT / "research" / "media" / "v1"
if str(MEDIA) not in sys.path:
    sys.path.insert(0, str(MEDIA))

from entrance_p85_complete_signaling_on_media_active_transform import (  # noqa: E402
    report,
    transform,
)

SOURCE = ROOT / "research" / "door" / "v1_5_7" / "comelit-v4-persistent-ctpp-door.c"


class P85CompleteSignalingOnMediaActiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.generated = transform(SOURCE.read_text(encoding="utf-8"))

    def test_media_active_completes_inherited_signaling_state(self) -> None:
        generated = self.generated
        start = generated.index("static gboolean\nentrance_signal_begin_media_observation(void)")
        end = generated.index("return TRUE;", start)
        block = generated[start:end]
        self.assertIn("entrance_signal_stage = ENTRANCE_SIGNAL_DONE;", block)
        self.assertIn("entrance_signaling_result = TRUE;", block)
        self.assertIn("p80_media_forwarding_enabled = TRUE;", block)
        self.assertNotIn("entrance_signal_stage = ENTRANCE_SIGNAL_OBSERVE_MEDIA;", block)
        self.assertIn('P80_SIGNALING_WATCHDOG_DISARMED=true', block)

    def test_inherited_timeout_callback_keeps_original_done_success_path(self) -> None:
        generated = self.generated
        start = generated.index("entrance_signal_timeout_cb(gpointer data)")
        end = generated.index("static void\np12_tx_completed", start)
        block = generated[start:end]
        done = block.index("if (entrance_signal_stage == ENTRANCE_SIGNAL_DONE)")
        remove = block.index("return G_SOURCE_REMOVE;", done)
        timeout = block.index("ENTRANCE_SIGNALING_TIMEOUT=true", remove)
        self.assertLess(done, remove)
        self.assertLess(remove, timeout)

    def test_rtpc_success_gate_is_still_required_before_media_active(self) -> None:
        generated = self.generated
        start = generated.index("static gboolean\nentrance_signal_begin_media_observation(void)")
        end = generated.index("return TRUE;", start)
        block = generated[start:end]
        self.assertIn("p78_rtpc_stage != P78_RTPC_COMPLETE", block)
        self.assertIn("!entrance_device_video_ack_sent", block)
        self.assertIn("!pseudotcp_open", block)

    def test_p83_response_before_open_corrective_is_preserved(self) -> None:
        generated = self.generated
        self.assertIn("p76_rtpc_response_is_valid(body, body_len)", generated)
        self.assertIn("P83_RTPC_EARLY_DEVICE_RESPONSE_%u=PASS", generated)
        self.assertIn("P78_RTPC_SIGNALING_RESULT=PASS", generated)

    def test_media_lifetime_and_safety_invariants_are_preserved(self) -> None:
        generated = self.generated
        self.assertIn("P80_MEDIA_LIFETIME_OWNER=HOME_ASSISTANT", generated)
        self.assertIn("P80_MEDIA_AUTO_CLOSE_3000MS=false", generated)
        self.assertIn("P78_SECOND_CTPP_OPEN=false", generated)
        self.assertIn("P80_DOOR_SIGNAL_ENTRYPOINT=false", generated)
        self.assertNotIn("signal(SIGUSR1, v4_door_signal_handler);", generated)

        text = report()
        self.assertIn("P85_MEDIA_HARD_LIMIT_SECONDS=180", text)
        self.assertIn("P85_AUTOMATIC_RETRY=false", text)
        self.assertIn("P85_SECOND_CTPP_OPEN=false", text)
        self.assertIn("P85_DOOR_ACTION_SENT=false", text)
        self.assertIn("NETWORK_IO_PERFORMED=false", text)
        self.assertIn("CANDIDATE_EXECUTED=false", text)


if __name__ == "__main__":
    unittest.main()
