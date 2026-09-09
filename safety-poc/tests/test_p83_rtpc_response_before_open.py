from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MEDIA = ROOT / "research" / "media" / "v1"
if str(MEDIA) not in sys.path:
    sys.path.insert(0, str(MEDIA))

from entrance_p83_rtpc_response_before_open_transform import (  # noqa: E402
    report,
    transform,
)

SOURCE = ROOT / "research" / "door" / "v1_5_7" / "comelit-v4-persistent-ctpp-door.c"


class P83RtpcResponseBeforeOpenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.generated = transform(SOURCE.read_text(encoding="utf-8"))

    def test_wait_device_open_classifies_response_before_open(self) -> None:
        generated = self.generated
        wait = generated.index("if (p78_rtpc_stage == P78_RTPC_WAIT_DEVICE_OPEN)")
        response = generated.index("if (p76_rtpc_response_is_valid(body, body_len))", wait)
        observe_response = generated.index(
            "p76_observe_device_response(&p78_rtpc_runtime, body, body_len)",
            response,
        )
        open_check = generated.index("if (!p76_rtpc_open_is_valid(body, body_len))", wait)
        observe_open = generated.index(
            "p76_observe_device_open(&p78_rtpc_runtime, body, body_len)",
            open_check,
        )
        self.assertLess(response, open_check)
        self.assertLess(response, observe_response)
        self.assertLess(observe_response, open_check)
        self.assertLess(open_check, observe_open)
        self.assertIn("P83_RTPC_EARLY_DEVICE_RESPONSE_%u=PASS", generated)

    def test_early_response_does_not_advance_to_media(self) -> None:
        generated = self.generated
        wait = generated.index("if (p78_rtpc_stage == P78_RTPC_WAIT_DEVICE_OPEN)")
        early_marker = generated.index("P83_RTPC_EARLY_DEVICE_RESPONSE_%u=PASS", wait)
        open_check = generated.index("if (!p76_rtpc_open_is_valid(body, body_len))", early_marker)
        early_block = generated[wait:open_check]
        self.assertIn("p78_rtpc_device_response_count++", early_block)
        self.assertNotIn("P78_RTPC_CLIENT_000A", early_block)
        self.assertNotIn("P78_RTPC_CLIENT_001A", early_block)
        self.assertNotIn("entrance_signal_begin_media_observation", early_block)

    def test_client_response_completion_handles_two_early_responses(self) -> None:
        generated = self.generated
        start = generated.index("case P78_TX_RTPC_CLIENT_RESPONSE:")
        end = generated.index("case P78_TX_RTPC_CLIENT_000A:", start)
        block = generated[start:end]
        self.assertIn("p78_rtpc_client_response_sent = TRUE", block)
        self.assertIn("p78_rtpc_device_response_count >= 2u", block)
        self.assertIn("p83_queue_client_media_after_responses()", block)
        self.assertIn("p78_rtpc_stage = P78_RTPC_WAIT_DEVICE_RESPONSES", block)

    def test_media_start_requires_both_paired_responses_and_client_response(self) -> None:
        generated = self.generated
        start = generated.index("p83_queue_client_media_after_responses(void)")
        end = generated.index(
            "static gboolean\np78_handle_rtpc_control_frame",
            start,
        )
        block = generated[start:end]
        self.assertIn("!p78_rtpc_client_response_sent", block)
        self.assertIn("p78_rtpc_device_response_count < 2u", block)
        self.assertIn(
            "p78_rtpc_runtime.facts.device_response_1_seen != P76_FACT_PAIRED",
            block,
        )
        self.assertIn(
            "p78_rtpc_runtime.facts.device_response_2_seen != P76_FACT_PAIRED",
            block,
        )
        self.assertIn("P83_RTPC_MEDIA_START_PRECONDITION=FAIL", block)

    def test_late_responses_use_same_pairing_and_same_media_gate(self) -> None:
        generated = self.generated
        start = generated.index("if (p78_rtpc_stage == P78_RTPC_WAIT_DEVICE_RESPONSES)")
        end = generated.index("return FALSE;", start)
        block = generated[start:end]
        self.assertIn("p76_rtpc_response_is_valid", block)
        self.assertIn("p76_observe_device_response", block)
        self.assertIn("p78_rtpc_device_response_count++", block)
        self.assertIn("p83_queue_client_media_after_responses()", block)

    def test_safety_invariants_are_preserved(self) -> None:
        generated = self.generated
        self.assertIn("P78_SECOND_CTPP_OPEN=false", generated)
        self.assertIn("P80_DOOR_SIGNAL_ENTRYPOINT=false", generated)
        self.assertNotIn("signal(SIGUSR1, v4_door_signal_handler);", generated)
        text = report()
        self.assertIn("P83_AUTOMATIC_RETRY=false", text)
        self.assertIn("P83_SECOND_CTPP_OPEN=false", text)
        self.assertIn("P83_DOOR_ACTION_SENT=false", text)
        self.assertIn("P83_NETWORK_IO_PERFORMED=false", text)
        self.assertIn("P83_CANDIDATE_EXECUTED=false", text)


if __name__ == "__main__":
    unittest.main()
