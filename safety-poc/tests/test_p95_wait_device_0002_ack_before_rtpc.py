#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
MEDIA = ROOT / "research" / "media" / "v1"
if str(MEDIA) not in sys.path:
    sys.path.insert(0, str(MEDIA))

from entrance_p95_wait_device_0002_ack_before_rtpc_transform import (  # noqa: E402
    report,
    transform,
)

SOURCE = ROOT / "research" / "door" / "v1_5_7" / "comelit-v4-persistent-ctpp-door.c"


class P95WaitDevice0002AckBeforeRtpcTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.generated = transform(SOURCE.read_text(encoding="utf-8"))

    def test_device_video_ack_completion_arms_0002_gate_instead_of_rtpc(self) -> None:
        generated = self.generated
        start = generated.index("case P12_TX_ENTRANCE_DEVICE_VIDEO_ACK:")
        end = generated.index("case P95_TX_DEVICE_0002_ACK:", start)
        block = generated[start:end]
        self.assertIn("p95_wait_device_0002 = TRUE;", block)
        self.assertIn("P95_WAIT_DEVICE_0002=true", block)
        self.assertIn("P95_DEVICE_0002_TIMEOUT_SECONDS", block)
        self.assertNotIn("p78_begin_rtpc_control()", block)

    def test_rtpc_begins_only_after_0002_ack_tx_completion(self) -> None:
        generated = self.generated
        start = generated.index("case P95_TX_DEVICE_0002_ACK:")
        end = generated.index("case P78_TX_RTPC_OPEN_1:", start)
        block = generated[start:end]
        self.assertIn("p95_device_0002_ack_sent = TRUE;", block)
        self.assertIn("P95_DEVICE_0002_GATE=PASS", block)
        self.assertIn("p78_begin_rtpc_control()", block)

        before = generated[:start]
        # The only earlier p78_begin call is the function declaration/definition;
        # the P12 device-video ACK completion itself must no longer invoke it.
        ack_start = before.index("case P12_TX_ENTRANCE_DEVICE_VIDEO_ACK:")
        ack_block = before[ack_start:]
        self.assertNotIn("p78_begin_rtpc_control()", ack_block)

    def test_device_0002_match_is_structural_and_session_bound(self) -> None:
        generated = self.generated
        start = generated.index("p95_device_0002_is_valid(")
        end = generated.index("static gboolean\np95_queue_device_0002_ack", start)
        block = generated[start:end]
        self.assertIn("request_id != v4_ctpp_channel_id", block)
        self.assertIn("body_len != 36u", block)
        self.assertIn("body[0] != 0x40u || body[1] != 0x18u", block)
        self.assertIn("body[6] != 0x00u || body[7] != 0x02u", block)
        self.assertIn("body[8] != 0x00u || body[9] != 0x0cu", block)
        self.assertIn("memcmp(body + 16u, V4_ENTRANCE, 8u)", block)
        self.assertIn("memcmp(body + 26u, V4_FULL_ADDRESS, 9u)", block)

    def test_0002_ack_is_generated_from_runtime_state_and_live_address_roles(self) -> None:
        generated = self.generated
        start = generated.index("p95_queue_device_0002_ack(")
        end = generated.index("static gboolean\np95_handle_device_0002", start)
        block = generated[start:end]
        self.assertIn("write_le16(ack + 0, 0x1800);", block)
        self.assertIn("entrance_device_video_ack_sequence +", block)
        self.assertIn("P95_DEVICE_0002_ACK_SEQUENCE_DELTA_FROM_PREVIOUS_ACK", block)
        self.assertIn("memcpy(ack + 12, device_body + 26u, 9u);", block)
        self.assertIn("memcpy(ack + 22, device_body + 16u, 9u);", block)
        self.assertIn("P95_TX_DEVICE_0002_ACK", block)
        self.assertIn("v4_ctpp_channel_id", block)
        self.assertNotIn("00000643", block)
        self.assertNotIn("000401177", block)

    def test_duplicate_device_0002_is_consumed_without_second_ack(self) -> None:
        generated = self.generated
        start = generated.index("p95_handle_device_0002(")
        end = generated.index("static gboolean\np83_queue_client_media_after_responses", start)
        block = generated[start:end]
        duplicate = block.index("if (p95_device_0002_observed)")
        queue = block.index("p95_queue_device_0002_ack(body, body_len)")
        self.assertLess(duplicate, queue)
        duplicate_block = block[duplicate:queue]
        self.assertIn("p95_device_0002_duplicate_count++", duplicate_block)
        self.assertIn("return TRUE;", duplicate_block)
        self.assertNotIn("p12_queue_vip_frame", duplicate_block)

    def test_missing_0002_fails_closed_with_bounded_timeout(self) -> None:
        generated = self.generated
        self.assertIn("#define P95_DEVICE_0002_TIMEOUT_SECONDS 3", generated)
        start = generated.index("p95_device_0002_timeout_cb(gpointer data)")
        end = generated.index("static gboolean\np95_device_0002_is_valid", start)
        block = generated[start:end]
        self.assertIn('p78_fail_rtpc("P95_DEVICE_0002_TIMEOUT=true")', block)
        self.assertIn("return G_SOURCE_REMOVE;", block)

    def test_p92_device_000a_gate_and_p91_media_diagnostics_remain(self) -> None:
        generated = self.generated
        self.assertIn("P92_DEVICE_000A_GATE=PASS", generated)
        self.assertIn("P92_WAIT_DEVICE_000A=true", generated)
        self.assertIn("P80_MEDIA_DIAGNOSTIC_TIMEOUT=true", generated)
        self.assertIn("P80_MEDIA_RX_TOTAL=%llu", generated)

    def test_no_second_ctpp_open_or_door_path_is_added(self) -> None:
        generated = self.generated
        p95_start = generated.index("/* P95 pre-RTPC device-0002 ACK gate. */")
        p95_end = generated.index("static gboolean\np83_queue_client_media_after_responses", p95_start)
        p95 = generated[p95_start:p95_end]
        self.assertNotIn("p12_queue_ctpp_open", p95)
        self.assertNotIn("v4_door", p95.lower())
        self.assertNotIn("SIGUSR1", p95)
        self.assertNotIn("automatic_retry", p95.lower())

    def test_report_preserves_safety_contract(self) -> None:
        text = report()
        self.assertIn("P95_DEVICE_0002_GATE_REQUIRED=true", text)
        self.assertIn("P95_DEVICE_0002_TIMEOUT_SECONDS=3", text)
        self.assertIn("P95_DEVICE_0002_ACK_MAX_SENDS=1", text)
        self.assertIn("P95_DEVICE_0002_DUPLICATES_REACKED=false", text)
        self.assertIn("P95_CAPTURE_SEQUENCE_VALUES_USED_AS_CONSTANTS=false", text)
        self.assertIn("P95_CAPTURE_ADDRESSES_USED_AS_CONSTANTS=false", text)
        self.assertIn("P95_P92_DEVICE_000A_GATE_PRESERVED=true", text)
        self.assertIn("P95_AUTOMATIC_RETRY=false", text)
        self.assertIn("P95_SECOND_CTPP_OPEN=false", text)
        self.assertIn("P95_DOOR_ACTION_SENT=false", text)
        self.assertIn("P95_MEDIA_HARD_LIMIT_SECONDS=180", text)
        self.assertIn("NETWORK_IO_PERFORMED=false", text)
        self.assertIn("CANDIDATE_EXECUTED=false", text)


if __name__ == "__main__":
    unittest.main()
