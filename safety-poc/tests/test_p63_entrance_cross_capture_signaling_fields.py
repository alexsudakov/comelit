#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
MEDIA = ROOT / "research" / "media" / "v1"
sys.path.insert(0, str(MEDIA))

from entrance_cross_capture_signaling_fields_pcap_forensic import (
    SessionEvidence,
    compare_sessions,
    report,
)


def session(
    *,
    request_id: int,
    seq_a: int,
    seq_b: int,
    field_a: bytes,
    field_b: bytes,
    field_c: bytes,
    device_field_a: bytes,
    rtp_seq: int,
    rtp_ts: int,
    rtp_ssrc: int,
    wrapper: bytes,
) -> SessionEvidence:
    return SessionEvidence(
        request_id=request_id,
        client_000a_sequence=seq_a,
        client_001a_sequence=seq_b,
        client_000a_field_10_11=field_a,
        client_001a_field_10_11=field_b,
        client_001a_field_24_32=field_c,
        device_000a_field_10_11=device_field_a,
        uplink_rtp_sequence=rtp_seq,
        uplink_rtp_timestamp=rtp_ts,
        uplink_rtp_ssrc=rtp_ssrc,
        uplink_wrapper=wrapper,
    )


class P63CrossCaptureTests(unittest.TestCase):
    def test_independent_sessions_with_constant_targets(self) -> None:
        baseline = session(
            request_id=100,
            seq_a=1000,
            seq_b=2000,
            field_a=b"AA",
            field_b=b"BB",
            field_c=b"123456789",
            device_field_a=b"AA",
            rtp_seq=3000,
            rtp_ts=4000,
            rtp_ssrc=5000,
            wrapper=b"abcdefgh",
        )
        second = session(
            request_id=101,
            seq_a=1001,
            seq_b=2001,
            field_a=b"AA",
            field_b=b"BB",
            field_c=b"123456789",
            device_field_a=b"AA",
            rtp_seq=3001,
            rtp_ts=4001,
            rtp_ssrc=5001,
            wrapper=b"abcdEfgh",
        )
        result = compare_sessions(baseline, second)
        self.assertTrue(result.independence_pass)
        self.assertEqual(len(result.changed_session_markers), 7)
        self.assertTrue(all(field.same_across_captures for field in result.fields))
        text = report(result)
        self.assertIn("CROSS_CAPTURE_CONSTANT_EVIDENCE=PASS", text)
        self.assertIn("LIVE_BODY_GENERATION_CONTRACT=REVIEW_REQUIRED", text)
        self.assertIn("FIELD_VALUES_EMITTED=false", text)
        self.assertNotIn("123456789", text)

    def test_changed_target_is_session_dependent_candidate(self) -> None:
        baseline = session(
            request_id=1,
            seq_a=10,
            seq_b=20,
            field_a=b"AA",
            field_b=b"BB",
            field_c=b"123456789",
            device_field_a=b"AA",
            rtp_seq=30,
            rtp_ts=40,
            rtp_ssrc=50,
            wrapper=b"abcdefgh",
        )
        second = session(
            request_id=2,
            seq_a=11,
            seq_b=21,
            field_a=b"AZ",
            field_b=b"BB",
            field_c=b"123456789",
            device_field_a=b"AZ",
            rtp_seq=31,
            rtp_ts=41,
            rtp_ssrc=51,
            wrapper=b"abcdEfgh",
        )
        result = compare_sessions(baseline, second)
        self.assertTrue(result.independence_pass)
        self.assertFalse(result.fields[0].same_across_captures)
        text = report(result)
        self.assertIn("classification=SESSION_DEPENDENT_CANDIDATE", text)
        self.assertIn("CROSS_CAPTURE_CONSTANT_EVIDENCE=PARTIAL", text)

    def test_independence_gate_fails_when_only_one_marker_changes(self) -> None:
        baseline = session(
            request_id=1,
            seq_a=10,
            seq_b=20,
            field_a=b"AA",
            field_b=b"BB",
            field_c=b"123456789",
            device_field_a=b"AA",
            rtp_seq=30,
            rtp_ts=40,
            rtp_ssrc=50,
            wrapper=b"abcdefgh",
        )
        second = session(
            request_id=2,
            seq_a=10,
            seq_b=20,
            field_a=b"AA",
            field_b=b"BB",
            field_c=b"123456789",
            device_field_a=b"AA",
            rtp_seq=30,
            rtp_ts=40,
            rtp_ssrc=50,
            wrapper=b"abcdefgh",
        )
        result = compare_sessions(baseline, second)
        self.assertFalse(result.independence_pass)
        text = report(result)
        self.assertIn("SESSION_INDEPENDENCE_GATE=FAIL", text)
        self.assertIn("classification=INCONCLUSIVE", text)


if __name__ == "__main__":
    unittest.main()
