from __future__ import annotations

from pathlib import Path
import re
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
MEDIA = ROOT / "safety-poc" / "research" / "media" / "v1"
PCAP = ROOT / ".p116-evidence" / "private" / "pcapdroid-r14" / "PCAPdroid_12_сент._14_19_14.pcap"
DOC = ROOT / "safety-poc" / "docs" / "P116_HA_STREAM_RTP_BRIDGE.md"

if str(MEDIA) not in sys.path:
    sys.path.insert(0, str(MEDIA))

import p116_r14_official_app_pcap_forensics as r14


class P116R14OfficialAppPcapForensicsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.analysis = r14.analyze(PCAP)
        cls.report = r14.render_report(cls.analysis)

    def test_parser_accepts_verified_raw_ip_pcap_without_dependencies(self) -> None:
        self.assertEqual(self.analysis.sha256, r14.EXPECTED_PCAP_SHA256)
        self.assertEqual(self.analysis.size, r14.EXPECTED_PCAP_SIZE)
        self.assertEqual(self.analysis.packet_count, 6296)
        self.assertGreater(self.analysis.capture_end, 80.0)

    def test_offset8_rtp_media_and_h264_scalars_are_extracted(self) -> None:
        self.assertEqual(self.analysis.video_packet_count, 2720)
        self.assertEqual(self.analysis.audio_packet_count, 2959)
        self.assertAlmostEqual(self.analysis.video_first_at, 12.970, places=2)
        self.assertAlmostEqual(self.analysis.video_last_at, 71.689, places=2)
        self.assertAlmostEqual(self.analysis.audio_first_at, 12.380, places=2)
        self.assertAlmostEqual(self.analysis.audio_last_at, 71.579, places=2)
        self.assertEqual(self.analysis.sps_count, 16)
        self.assertEqual(self.analysis.pps_count, 16)
        self.assertEqual(len(self.analysis.idr_times), 2)
        self.assertTrue(all(item < self.analysis.first_video_rtp + 1.0 for item in self.analysis.idr_times))

    def test_periodic_5s_candidate_is_pseudotcp_application_data(self) -> None:
        candidate = self.analysis.candidate_5s
        self.assertIsNotNone(candidate)
        assert candidate is not None
        self.assertEqual(candidate.alias, "PSEUDOTCP_APP_DATA_18_FLAGS_0")
        self.assertEqual(candidate.outer_length, 42)
        self.assertEqual(candidate.inner_length, 18)
        self.assertEqual(candidate.repeat_count, 18)
        self.assertAlmostEqual(candidate.cadence_median, 5.010, places=2)
        self.assertTrue(candidate.continues_after_36s)
        self.assertTrue(candidate.server_response_present)
        self.assertAlmostEqual(candidate.response_latency_median, 0.092, places=2)

    def test_report_is_scalar_only_and_contains_required_decisions(self) -> None:
        for required in (
            "AUDIO_USER_ENABLED=false",
            "AUDIO_RTP_DEFAULT_COMPONENT_STATUS=OBSERVED_FOR_THIS_CAPTURE",
            "PERIODIC_5S_CONTROL_FAMILY=PSEUDOTCP_APPLICATION_TRAFFIC",
            "CONTROL_IS_PSEUDOTCP_APP=PROVEN_OFFLINE",
            "CONTROL_IS_RTPC=UNRESOLVED",
            "OUR_HELPER_SENDS_EQUIVALENT_5S_CONTROL=false",
            "MISSING_PERIODIC_CONTROL_DIFFERENCE=PROVEN",
            "MISSING_PERIODIC_CONTROL_CAN_EXPLAIN_36S_STOP=PLAUSIBLE",
            "FUNCTIONAL_FIX_IMPLEMENTED=false",
            "HA_DEPLOY=NOT_RUN",
            "DOOR_ACTIONS_SENT=0",
            "GATE_ACTIONS_SENT=0",
        ):
            self.assertIn(required, self.report)
        self.assertIsNone(re.search(r"\b(?:192|10|172)\.\d{1,3}\.", self.report))
        for forbidden in ("token", "credential", "session_id", "payload=", "base64", "hex="):
            self.assertNotIn(forbidden, self.report.lower())

    def test_document_records_r14_official_app_findings(self) -> None:
        doc = DOC.read_text(encoding="utf-8")
        for required in (
            "R14 official-app PCAPdroid forensics",
            "PSEUDOTCP_APPLICATION_TRAFFIC",
            "PERIODIC_5S_CONTROL_OUTER_LENGTH=42",
            "AUDIO_USER_ENABLED=false",
            "MISSING_PERIODIC_CONTROL_DIFFERENCE=PROVEN",
            "COMMON_D1_D2_CAUSE=UNRESOLVED",
        ):
            self.assertIn(required, doc)


if __name__ == "__main__":
    unittest.main()
