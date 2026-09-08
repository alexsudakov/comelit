#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
MEDIA = ROOT / "research" / "media" / "v1"
SOURCE = ROOT / "research" / "door" / "v1_5_7" / "comelit-v4-persistent-ctpp-door.c"
sys.path.insert(0, str(MEDIA))

import entrance_p78_rtpc_media_live_stage_transform as p78


class P78RtpcMediaLiveStageTransformTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.original = SOURCE.read_text(encoding="utf-8")
        cls.transform_text = Path(p78.__file__).read_text(encoding="utf-8")
        cls.composed = p78.composed_p76(cls.original)
        cls.candidate = p78.transform(cls.original)

    def test_replace_once_anchor_counts_against_composed_candidate(self) -> None:
        self.assertEqual(
            p78.anchor_counts(self.original),
            {
                "tx_enum": 1,
                "state": 1,
                "ack_completion": 1,
                "frame_hook": 1,
                "p76_helper_tail": 1,
            },
        )

    def test_generated_candidate_contains_p76_and_p78_bridge_markers(self) -> None:
        for marker in (
            "P76_RTPC_CONTROL_MEDIA_RUNTIME_BEGIN",
            "P78_RTPC_MEDIA_LIVE_STAGE_BEGIN",
            "P78_TX_RTPC_OPEN_1",
            "P78_TX_RTPC_OPEN_2",
            "P78_TX_RTPC_CLIENT_RESPONSE",
            "P78_TX_RTPC_CLIENT_000A",
            "P78_TX_RTPC_CLIENT_001A",
            "P78_DEVICE_0008_ACK_GATE_PROVEN=false",
            "P78_RTPC_SIGNALING_RESULT=PASS",
        ):
            self.assertIn(marker, self.candidate)

    def test_old_terminal_observation_transition_is_replaced(self) -> None:
        self.assertIn("return entrance_signal_queue_device_video_ack();", self.candidate)
        self.assertNotIn(p78.ACK_COMPLETION_ANCHOR, self.candidate)
        self.assertIn("if (!p78_begin_rtpc_control())", self.candidate)
        self.assertIn("p12_queue_vip_frame(0, p78_rtpc_open_1", self.candidate)
        self.assertIn("p12_queue_vip_frame(0, p78_rtpc_open_2", self.candidate)
        self.assertIn("p12_queue_vip_frame(0, p78_rtpc_client_response", self.candidate)
        self.assertIn("p12_queue_vip_frame(v4_ctpp_channel_id, p78_rtpc_client_000a", self.candidate)
        self.assertIn("p12_queue_vip_frame(v4_ctpp_channel_id, p78_rtpc_client_001a", self.candidate)

    def test_p78_stage_does_not_add_ctpp_open_or_door_entrypoint(self) -> None:
        p78_section = self.candidate.split("P78_RTPC_MEDIA_LIVE_STAGE_BEGIN", 1)[1]
        self.assertNotIn("v4_queue_open_ctpp", p78_section)
        self.assertNotIn("open_ctpp", p78_section)
        self.assertNotIn("P12_TX_V4_DOOR_WRITE", p78_section)
        self.assertNotIn("v4_door_signal_handler", p78_section)
        self.assertIn("SECOND_CTPP_OPEN=false", p78_section)
        self.assertIn("DOOR_ACTION_SENT=false", p78_section)

    def test_no_raw_payload_emission_in_p78_outputs(self) -> None:
        for text in (p78.report(), self.candidate.split("P78_RTPC_MEDIA_LIVE_STAGE_BEGIN", 1)[1]):
            self.assertIn("RAW_PAYLOAD_EMITTED=false", text)
            self.assertIn("HEX_PAYLOAD_EMITTED=false", text)
            self.assertIn("BASE64_PAYLOAD_EMITTED=false", text)
            self.assertNotIn("printf(\"%02x", text)
            self.assertNotIn("print_hex", text)
            self.assertNotIn("BASE64_ENCODE", text)

    def test_report_mode_documents_review_pin_and_offline_context(self) -> None:
        text = p78.report()
        self.assertIn("P78_REVIEW_COMMIT_SHA_SET=false", text)
        self.assertIn("LIVE_INVOCATIONS=0", text)
        self.assertIn("RTPC_CONTROL_REQUEST_ID=0", text)
        self.assertIn("RTPC_CTPP_MEDIA_REQUEST_ID=v4_ctpp_channel_id", text)


if __name__ == "__main__":
    unittest.main()
