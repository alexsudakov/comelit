from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MEDIA = ROOT / "safety-poc" / "research" / "media" / "v1"
if str(MEDIA) not in sys.path:
    sys.path.insert(0, str(MEDIA))

from entrance_p95_wait_device_0002_before_rtpc_transform import transform


class P95WaitDevice0002BeforeRtpcTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        source = (
            ROOT
            / "safety-poc"
            / "research"
            / "door"
            / "v1_5_7"
            / "comelit-v4-persistent-ctpp-door.c"
        )
        cls.candidate = transform(source.read_text(encoding="utf-8"))

    def test_device_video_ack_no_longer_starts_rtpc_immediately(self) -> None:
        case_start = self.candidate.index("case P12_TX_ENTRANCE_DEVICE_VIDEO_ACK:")
        case_end = self.candidate.index("case P95_TX_DEVICE_0002_ACK:", case_start)
        block = self.candidate[case_start:case_end]
        self.assertIn("p95_wait_device_0002 = TRUE;", block)
        self.assertIn("P80_DEVICE_0002_GATE_ARMED=true", block)
        self.assertNotIn("p78_begin_rtpc_control()", block)

    def test_rtpc_starts_only_after_device_0002_ack_completion(self) -> None:
        case_start = self.candidate.index("case P95_TX_DEVICE_0002_ACK:")
        case_end = self.candidate.index("case P78_TX_RTPC_OPEN_1:", case_start)
        block = self.candidate[case_start:case_end]
        self.assertIn("p95_device_0002_ack_sent = TRUE;", block)
        self.assertIn("P80_DEVICE_0002_GATE=PASS", block)
        self.assertIn("p78_begin_rtpc_control()", block)

    def test_device_0002_validator_matches_observed_structure(self) -> None:
        start = self.candidate.index("p95_device_0002_is_valid(")
        end = self.candidate.index("p95_queue_device_0002_ack", start)
        block = self.candidate[start:end]
        for token in (
            "body_len == 36u",
            "read_le16(body + 0) == 0x1840u",
            "body[7] == 0x02u",
            "body[9] == 0x0cu",
            "memcmp(body + 16u, V4_ENTRANCE, 8u) == 0",
            "memcmp(body + 26u, V4_FULL_ADDRESS, 9u) == 0",
        ):
            self.assertIn(token, block)

    def test_ack_is_single_send_and_live_state_derived(self) -> None:
        start = self.candidate.index("p95_queue_device_0002_ack(")
        end = self.candidate.index("p95_handle_device_0002", start)
        block = self.candidate[start:end]
        self.assertIn("p95_device_0002_ack_queued", block)
        self.assertIn("p95_device_0002_ack_sent", block)
        self.assertIn("entrance_device_video_ack_sequence +", block)
        self.assertIn("P95_DEVICE_0002_ACK_SEQUENCE_DELTA_FROM_PREVIOUS_ACK", block)
        self.assertIn("P80_DEVICE_0002_ACK_SEQUENCE_SOURCE=LIVE_SESSION_STATE", block)

    def test_retransmit_does_not_queue_second_ack(self) -> None:
        start = self.candidate.index("p95_handle_device_0002(")
        end = self.candidate.index("p92_device_000a_is_valid", start)
        block = self.candidate[start:end]
        self.assertIn("if (p95_device_0002_observed)", block)
        self.assertIn("P80_DEVICE_0002_RETRANSMIT_CONSUMED=true", block)
        self.assertEqual(block.count("p95_queue_device_0002_ack()"), 1)

    def test_safety_invariants_remain_explicit(self) -> None:
        self.assertIn("P78_SECOND_CTPP_OPEN=false", self.candidate)
        self.assertIn("P80_DOOR_SIGNAL_ENTRYPOINT=false", self.candidate)
        self.assertNotIn("signal(SIGUSR1, v4_door_signal_handler);", self.candidate)


if __name__ == "__main__":
    unittest.main()
