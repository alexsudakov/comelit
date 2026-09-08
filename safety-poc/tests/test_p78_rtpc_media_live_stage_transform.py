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
        cls.candidate = p78.transform(cls.original)
        cls.p78_section = cls.candidate.split(
            "P78_RTPC_MEDIA_LIVE_STAGE_BEGIN", 1
        )[1]

    def test_replace_once_anchor_counts(self) -> None:
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

    def test_generated_candidate_contains_serialized_states(self) -> None:
        for marker in (
            "P78_RTPC_OPEN_1_TX",
            "P78_RTPC_OPEN_2_TX",
            "P78_RTPC_CLIENT_RESPONSE_TX",
            "P78_RTPC_CLIENT_000A_TX",
            "P78_RTPC_CLIENT_001A_TX",
            "P78_TX_SERIALIZATION=PASS",
            "TX_SERIALIZATION=SINGLE_PENDING_COMPLETION_CHAIN",
        ):
            self.assertIn(marker, self.candidate)

    def test_open_pair_is_completion_chained_not_back_to_back(self) -> None:
        begin = self.p78_section.split(
            "static gboolean\np78_begin_rtpc_control(void)", 1
        )[1].split(
            "static gboolean\np78_handle_rtpc_control_frame", 1
        )[0]
        self.assertIn("P78_TX_RTPC_OPEN_1", begin)
        self.assertIn("p12_flush_tx()", begin)
        self.assertNotIn("P78_TX_RTPC_OPEN_2", begin)

        open1_case = self.candidate.split(
            "case P78_TX_RTPC_OPEN_1:", 1
        )[1].split("case P78_TX_RTPC_OPEN_2:", 1)[0]
        self.assertIn("p78_queue_rtpc_open_2()", open1_case)

        open2_helper = self.p78_section.split(
            "p78_queue_rtpc_open_2(void)", 1
        )[1].split("p78_queue_rtpc_client_001a(void)", 1)[0]
        self.assertIn("P78_TX_RTPC_OPEN_2", open2_helper)
        self.assertIn("p12_flush_tx()", open2_helper)

        open2_case = self.candidate.split(
            "case P78_TX_RTPC_OPEN_2:", 1
        )[1].split("case P78_TX_RTPC_CLIENT_RESPONSE:", 1)[0]
        self.assertIn("P78_RTPC_WAIT_DEVICE_OPEN", open2_case)

    def test_media_pair_is_completion_chained_not_back_to_back(self) -> None:
        handler = self.p78_section.split(
            "p78_handle_rtpc_control_frame", 1
        )[1]
        media_start = handler.split("P78_RTPC_CLIENT_000A_TX", 1)[1]
        queue_000a = media_start.split("return TRUE;", 1)[0]
        self.assertIn("P78_TX_RTPC_CLIENT_000A", queue_000a)
        self.assertIn("p12_flush_tx()", queue_000a)
        self.assertNotIn("P78_TX_RTPC_CLIENT_001A", queue_000a)

        case_000a = self.candidate.split(
            "case P78_TX_RTPC_CLIENT_000A:", 1
        )[1].split("case P78_TX_RTPC_CLIENT_001A:", 1)[0]
        self.assertIn("p78_queue_rtpc_client_001a()", case_000a)

        helper_001a = self.p78_section.split(
            "p78_queue_rtpc_client_001a(void)", 1
        )[1].split("p78_begin_rtpc_control(void)", 1)[0]
        self.assertIn("P78_TX_RTPC_CLIENT_001A", helper_001a)
        self.assertIn("p12_flush_tx()", helper_001a)

        case_001a = self.candidate.split(
            "case P78_TX_RTPC_CLIENT_001A:", 1
        )[1].split("default:", 1)[0]
        self.assertIn("P78_RTPC_COMPLETE", case_001a)
        self.assertIn("entrance_signal_begin_media_observation()", case_001a)

    def test_client_response_waits_for_tx_completion(self) -> None:
        handler = self.p78_section.split(
            "p78_handle_rtpc_control_frame", 1
        )[1]
        self.assertIn("p78_rtpc_stage = P78_RTPC_CLIENT_RESPONSE_TX", handler)
        self.assertIn("P78_TX_RTPC_CLIENT_RESPONSE", handler)
        self.assertIn("p12_flush_tx()", handler)

        completed = self.candidate.split(
            "case P78_TX_RTPC_CLIENT_RESPONSE:", 1
        )[1].split("case P78_TX_RTPC_CLIENT_000A:", 1)[0]
        self.assertIn("P78_RTPC_WAIT_DEVICE_RESPONSES", completed)

    def test_p78_stage_does_not_add_ctpp_open_or_door_entrypoint(self) -> None:
        self.assertNotIn("v4_queue_open_ctpp", self.p78_section)
        self.assertNotIn("open_ctpp", self.p78_section)
        self.assertNotIn("P12_TX_V4_DOOR_WRITE", self.p78_section)
        self.assertNotIn("v4_door_signal_handler", self.p78_section)
        self.assertIn("SECOND_CTPP_OPEN=false", self.p78_section)
        self.assertIn("DOOR_ACTION_SENT=false", self.p78_section)

    def test_no_raw_payload_emission(self) -> None:
        for text in (p78.report(), self.p78_section):
            self.assertIn("RAW_PAYLOAD_EMITTED=false", text)
            self.assertIn("HEX_PAYLOAD_EMITTED=false", text)
            self.assertIn("BASE64_PAYLOAD_EMITTED=false", text)
            self.assertNotIn('printf("%02x', text)
            self.assertNotIn("print_hex", text)

    def test_report_documents_runtime_review_pin_source(self) -> None:
        text = p78.report()
        self.assertIn("P78_REVIEW_COMMIT_SHA_SOURCE=LAUNCHER_ENV", text)
        self.assertIn("LIVE_INVOCATIONS=0", text)
        self.assertIn("RTPC_CONTROL_REQUEST_ID=0", text)
        self.assertIn("RTPC_CTPP_MEDIA_REQUEST_ID=v4_ctpp_channel_id", text)


if __name__ == "__main__":
    unittest.main()
