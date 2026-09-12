from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
MEDIA = ROOT / "safety-poc" / "research" / "media" / "v1"
RUNNER = MEDIA / "p116_official_app_trace_runner.sh"
EXTRACTOR = MEDIA / "p116_official_app_trace_extractor.py"
DOC = ROOT / "safety-poc" / "docs" / "P116_HA_STREAM_RTP_BRIDGE.md"

if str(MEDIA) not in sys.path:
    sys.path.insert(0, str(MEDIA))

import p116_official_app_trace_extractor as extractor


class P116R13DOfficialAppCaptureToolingTests(unittest.TestCase):
    def test_runner_is_dry_run_by_default_and_requires_operator_flag(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        self.assertIn("DRY_RUN=1", source)
        self.assertIn("AUTHORIZED=0", source)
        self.assertIn("--authorize-passive-capture", source)
        self.assertIn("CAPTURE_NOT_STARTED=DRY_RUN_REQUIRES_OPERATOR_FLAG", source)
        self.assertIn("PASSIVE_ONLY=true", source)
        self.assertIn("CAPTURE_POINT_MISSING=FAILED_SAFE", source)
        self.assertIn("OPERATOR_MARKER_TIMEOUT=FAILED_SAFE", source)
        self.assertIn("OPERATOR_VIEW_START_EPOCH", source)
        self.assertIn("CAPTURE_ARMED=true", source)

    def test_runner_has_bounded_duration_size_message_and_raw_artifact_policy(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        for required in (
            "PRE_SECONDS=5",
            "POST_SECONDS=90",
            "MARKER_WAIT_SECONDS=120",
            "HARD_CAP_SECONDS=125",
            "MAX_FILE_MB=256",
            "MAX_MESSAGE_ROWS=200",
            "chmod 600 \"$RAW_PCAP\"",
            "sha256sum",
            "RAW_ARTIFACT_PATH_INSIDE_REPO=FAILED_SAFE",
            "RAW_ARTIFACT_POLICY=outside_git_mode_600_sha256_retain_raw_for_one_shot",
        ):
            self.assertIn(required, source)

    def test_tooling_contains_no_payload_printing_or_replay_switches(self) -> None:
        combined = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (RUNNER, EXTRACTOR)
        )
        forbidden = (
            " -A ",
            "\t-A ",
            " -X ",
            "\t-X ",
            "-w -",
            "payload.hex",
            "get_data",
            "raw replay",
        )
        for item in forbidden:
            self.assertNotIn(item, combined)

    def test_extractor_scalar_summary_shape_and_privacy_gate(self) -> None:
        sample_rows = [
            "100.000000\t100\t10.0.0.10\t10.0.0.20\t\t\t50000\t64100\t\t\tRTP\t99\t111\t90000\t\t7\t\t88",
            "101.000000\t101\t10.0.0.20\t10.0.0.10\t\t\t64100\t50000\t\t\tRTP\t99\t111\t180000\t\t8\t\t89",
            "110.000000\t90\t10.0.0.10\t10.0.0.20\t\t\t50000\t64100\t\t\tRTCP\t\t\t\t206\t\t\t78",
            "120.000000\t80\t10.0.0.10\t10.0.0.20\t\t\t50000\t64100\t\t\tRTP\t99\t111\t270000\t\t5\t\t68",
            "140.000000\t70\t10.0.0.10\t10.0.0.20\t\t\t50000\t64100\t\t\tTLS\t\t\t\t\t\t50\t",
        ]
        with tempfile.TemporaryDirectory(prefix="p116-r13d-test-", dir="/tmp") as tmp:
            path = Path(tmp) / "fields.tsv"
            path.write_text("\n".join(sample_rows) + "\n", encoding="utf-8")
            rows = extractor.read_rows(
                path,
                client_ip="10.0.0.10",
                device_ip="10.0.0.20",
                operator_view_start_epoch=100.0,
            )
            summary = extractor.summarize(
                rows,
                input_path=path,
                max_message_rows=50,
                operator_view_start_epoch=100.0,
            )
        for key in extractor.SUMMARY_KEYS:
            self.assertIn(key, summary)
        for row in summary["MESSAGE_FAMILY_ROWS"]:
            for key in extractor.REQUIRED_MESSAGE_FIELDS:
                self.assertIn(key, row)
        self.assertEqual(summary["CLIENT_TO_REMOTE_RECORDS"], 4)
        self.assertEqual(summary["REMOTE_TO_CLIENT_RECORDS"], 1)
        self.assertEqual(summary["POST36_CLIENT_TO_REMOTE_RECORDS"], 1)
        self.assertEqual(summary["VIDEO_PACKET_COUNT"], 3)
        self.assertEqual(summary["VIDEO_PT_SET"], "99")
        self.assertEqual(summary["SPS_COUNT"], 1)
        self.assertEqual(summary["PPS_COUNT"], 1)
        self.assertEqual(summary["IDR_COUNT"], 1)
        self.assertTrue(summary["RTCP_PRESENT"])
        self.assertTrue(summary["COMPARISON_TEMPLATE_READY"])
        rendered = json.dumps(summary, sort_keys=True).lower()
        for forbidden_key in ("token", "credential", "session_id", "session-id"):
            self.assertNotIn(forbidden_key, rendered)

    def test_runner_dry_run_refuses_missing_capture_point_without_starting_capture(self) -> None:
        env = os.environ.copy()
        env["PATH"] = f"{Path('/bin')}:{Path('/usr/bin')}:{env.get('PATH', '')}"
        completed = subprocess.run(
            [
                "bash",
                str(RUNNER),
                "--dry-run",
                "--marker-file",
                "/tmp/p116-r13d-marker",
                "--client-ip",
                "10.0.0.10",
                "--device-ip",
                "10.0.0.20",
            ],
            cwd=ROOT,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("CAPTURE_POINT_MISSING=FAILED_SAFE", completed.stderr)
        self.assertNotIn("tcpdump -i", completed.stdout + completed.stderr)

    def test_document_records_r13d_feasibility_protocol_privacy_and_comparison(self) -> None:
        doc = DOC.read_text(encoding="utf-8")
        for required in (
            "P116 R13D official-app trace capture tooling",
            "OBSERVABLE_AT",
            "VISIBLE_LAYERS",
            "CAN_SEE_P2P/UDP_MEDIA",
            "TLS_RECORD_METADATA",
            "start capture first",
            "hold it >=60-90 s",
            "RELATIVE_TIME",
            "DIRECTION",
            "SAFE_MESSAGE_TYPE",
            "MISSING_CLIENT_FEEDBACK_COULD_EXPLAIN_D1",
            "COMMON_D1_D2_CAUSE",
            "Privacy gate",
            "mode `600`",
        ):
            self.assertIn(required, doc)


if __name__ == "__main__":
    unittest.main()
