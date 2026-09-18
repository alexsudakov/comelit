from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MEDIA = ROOT / "research" / "media" / "v1"
MODEL_SOURCE = MEDIA / "entrance_p116_r33_offline_scalar_trace_model.py"
DOC_SOURCE = MEDIA / "P116_R33_ATTACHED_INBOUND_MEDIA_PRIMITIVE_CLOSURE.md"

sys.path.insert(0, str(MEDIA))
from entrance_p116_r33_offline_scalar_trace_model import (  # noqa: E402
    R33TraceRejected,
    create_trace_at_call_barrier,
    report,
    run_offline_scalar_trace,
    verify_trace,
)


class P116R33OfflineScalarTrace(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.model_source = MODEL_SOURCE.read_text(encoding="utf-8")
        cls.doc_source = DOC_SOURCE.read_text(encoding="utf-8")

    def test_happy_path_models_only_proven_scalar_order(self) -> None:
        trace = run_offline_scalar_trace()
        self.assertEqual(
            trace.events,
            [
                "CALL_INIT_CAPTURED",
                "CALL_CTP_CAPTURED",
                "MEDIA_RX_LOCAL_CHANNEL_ALLOCATE",
                "CALL_BOUND_MEDIAREQ26_OPEN",
                "CHANNEL_OPEN_RESPONSE_PASS",
                "RTP_ENABLED",
                "CALL_BOUND_MEDIAREQ26_STOP",
                "MEDIA_RX_CHANNEL_DISPOSE",
                "LISTENER_CALL_TRANSACTION_PRESERVED",
            ],
        )
        evidence = verify_trace(trace)
        self.assertTrue(evidence["ORDER"])
        self.assertEqual(evidence["NETWORK_TX"], 0)
        self.assertEqual(evidence["NEW_ICE"], 0)
        self.assertEqual(evidence["NEW_CLOUD"], 0)
        self.assertEqual(evidence["NEW_PSEUDOTCP"], 0)
        self.assertEqual(evidence["NEW_REGISTRATION"], 0)
        self.assertLessEqual(evidence["OPEN_COUNT"], 1)
        self.assertLessEqual(evidence["STOP_COUNT"], 1)
        self.assertEqual(evidence["DOOR"], 0)
        self.assertEqual(evidence["GATE"], 0)
        self.assertEqual(evidence["DISPOSED_CHANNEL_COUNT"], 1)
        self.assertFalse(evidence["FINAL_CHANNEL_PRESENT"])
        self.assertFalse(evidence["RTP_SINK_ENABLED"])

    def test_report_exposes_bounded_markers_only(self) -> None:
        marker_text = report()
        for marker in (
            "CALL_INIT_CAPTURED=PASS",
            "CALL_CTP_CAPTURED=PASS",
            "MEDIA_RX_LOCAL_CHANNEL_ALLOCATE=PASS",
            "CALL_BOUND_MEDIAREQ26_OPEN_COUNT=1",
            "CHANNEL_OPEN_RESPONSE=PASS",
            "RTP_ENABLED=PASS",
            "CALL_BOUND_MEDIAREQ26_STOP_COUNT=1",
            "MEDIA_RX_CHANNEL_DISPOSE_COUNT=1",
            "LISTENER_CALL_TRANSACTION_PRESERVED=PASS",
            "NETWORK_TX=0",
            "NEW_ICE=0",
            "NEW_CLOUD=0",
            "NEW_PSEUDOTCP=0",
            "NEW_REGISTRATION=0",
            "DOOR=0",
            "GATE=0",
            "OFFLINE_SCALAR_TRACE=PASS",
        ):
            self.assertIn(marker, marker_text)

    def test_stop_before_open_fails_closed_without_wire_action(self) -> None:
        trace = create_trace_at_call_barrier()
        trace.allocate_media_rx_channel(0x3456)
        before = trace.stop_count
        with self.assertRaises(R33TraceRejected):
            trace.send_stop(channel_id=0x3456)
        self.assertEqual(trace.stop_count, before)

    def test_second_open_fails_closed_without_second_write(self) -> None:
        trace = create_trace_at_call_barrier()
        trace.allocate_media_rx_channel(0x3456)
        trace.send_open()
        before = trace.open_count
        with self.assertRaises(R33TraceRejected):
            trace.send_open()
        self.assertEqual(trace.open_count, before)

    def test_wrong_channel_id_fails_closed_for_response_stop_and_dispose(self) -> None:
        trace = create_trace_at_call_barrier()
        trace.allocate_media_rx_channel(0x3456)
        trace.send_open()
        with self.assertRaises(R33TraceRejected):
            trace.observe_channel_open_response(ok=True, channel_id=0x3457)
        trace.observe_channel_open_response(ok=True, channel_id=0x3456)
        trace.enable_rtp(channel_id=0x3456)
        with self.assertRaises(R33TraceRejected):
            trace.send_stop(channel_id=0x3457)
        trace.send_stop(channel_id=0x3456)
        with self.assertRaises(R33TraceRejected):
            trace.dispose_media_rx_channel(channel_id=0x3457)
        trace.dispose_media_rx_channel(channel_id=0x3456)

    def test_open_on_registration_handle_fails_closed(self) -> None:
        trace = create_trace_at_call_barrier()
        trace.allocate_media_rx_channel(0x3456)
        with self.assertRaises(R33TraceRejected):
            trace.send_open(use_registration_handle=True)
        self.assertEqual(trace.open_count, 0)

    def test_dispose_before_stop_fails_closed(self) -> None:
        trace = create_trace_at_call_barrier()
        trace.allocate_media_rx_channel(0x3456)
        trace.send_open()
        with self.assertRaises(R33TraceRejected):
            trace.dispose_media_rx_channel(channel_id=0x3456)

    def test_reuses_r30b_call_transaction_model(self) -> None:
        self.assertIn("from entrance_p116_r30b_call_transaction_model import", self.model_source)
        self.assertIn("create_call_transaction", self.model_source)
        self.assertIn("intercept_media_open", self.model_source)
        self.assertIn("intercept_media_stop", self.model_source)

    def test_model_and_doc_keep_offline_no_live_boundaries(self) -> None:
        combined = self.model_source + "\n" + self.doc_source
        forbidden_patterns = (
            r"(^|\n)\s*(import|from)\s+" + "so" + r"cket\b",
            r"\b" + "so" + r"cket\.",
            r"(^|\n)\s*(import|from)\s+" + "sub" + r"process\b",
            r"(^|\n)\s*(import|from)\s+" + "ur" + r"llib\b",
            r"(^|\n)\s*(import|from)\s+" + "req" + r"uests\b",
            r"(?<![A-Za-z0-9_])" + "cu" + r"rl\s",
            r"(?<![A-Za-z0-9_])" + "nc" + r"\s",
            r"Pseudo" + r"TCP open",
            r"ha\." + r"services",
        )
        for pattern in forbidden_patterns:
            self.assertIsNone(re.search(pattern, combined, flags=re.MULTILINE))

    def test_document_placeholders_removed_and_closure_block_present(self) -> None:
        self.assertNotIn("PENDING_R33_RUN2", self.doc_source)
        self.assertIn("=== COMELIT P116 R33 PRIMITIVE CLOSURE (REPO DOC) ===", self.doc_source)
        self.assertIn("=== END COMELIT P116 R33 PRIMITIVE CLOSURE (REPO DOC) ===", self.doc_source)


if __name__ == "__main__":
    unittest.main()
