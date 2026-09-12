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


def _write_tsv(lines: list[str]) -> Path:
    path = Path(tempfile.mkdtemp(prefix="p116-r13e-test-", dir="/tmp")) / "fields.tsv"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _sample_row(
    epoch: float,
    src: str,
    dst: str,
    protocol: str,
    *,
    length: int = 100,
    udp_src: str = "50000",
    udp_dst: str = "64100",
    rtp_pt: str = "",
    rtp_ssrc: str = "",
    rtp_ts: str = "",
    rtcp_pt: str = "",
    h264: str = "",
) -> str:
    return (
        f"{epoch:.6f}\t{length}\t{src}\t{dst}\t\t\t{udp_src}\t{udp_dst}\t\t\t{protocol}\t"
        f"{rtp_pt}\t{rtp_ssrc}\t{rtp_ts}\t{rtcp_pt}\t{h264}\t\t{max(length - 12, 0)}"
    )


def _rows(lines: list[str], *, client: str = "10.0.0.10", view: float = 100.0) -> tuple[Path, list[extractor.Row]]:
    path = _write_tsv(lines)
    return path, extractor.read_rows(path, client_ip=client, operator_view_start_epoch=view)


def _summary(lines: list[str], *, client: str = "10.0.0.10", view: float = 100.0, capture_start: float | None = None, capture_end: float | None = None, max_rows: int = 200) -> dict[str, object]:
    path, rows = _rows(lines, client=client, view=view)
    return extractor.summarize(
        rows,
        input_path=path,
        max_message_rows=max_rows,
        operator_view_start_epoch=view,
        capture_start_epoch=capture_start,
        capture_end_epoch=capture_end,
    )


class P116R13EOfficialAppTraceHardeningTests(unittest.TestCase):
    def _dry_run(self, *args: str) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["PATH"] = f"{Path('/bin')}:{Path('/usr/bin')}:{env.get('PATH', '')}"
        return subprocess.run(
            ["bash", str(RUNNER), "--dry-run", "--iface", "lo", "--marker-file", "/tmp/p116-r13e-marker", *args],
            cwd=ROOT,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def test_client_only_filter_generation(self) -> None:
        completed = self._dry_run("--client-ip", "10.0.0.10")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("CAPTURE_FILTER_MODE=CLIENT_ONLY", completed.stdout)
        self.assertIn("DEVICE_IP_REQUIRED=false", completed.stdout)
        self.assertIn("FILTER_IP_TERM_COUNT=1", completed.stdout)
        self.assertNotIn("DEVICE_IP_MISSING", completed.stdout + completed.stderr)

    def test_optional_device_ip_narrowing(self) -> None:
        completed = self._dry_run("--client-ip", "10.0.0.10", "--device-ip", "10.0.0.20")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("CAPTURE_FILTER_MODE=CLIENT_DEVICE_NARROW", completed.stdout)
        self.assertIn("FILTER_IP_TERM_COUNT=2", completed.stdout)

    def test_multi_peer_direction(self) -> None:
        _, rows = _rows(
            [
                _sample_row(101, "10.0.0.10", "10.0.0.20", "UDP"),
                _sample_row(102, "10.0.0.30", "10.0.0.10", "UDP"),
                _sample_row(103, "10.0.0.40", "10.0.0.50", "UDP"),
            ]
        )
        self.assertEqual([row.direction for row in rows], ["CLIENT_TO_REMOTE", "REMOTE_TO_CLIENT", "UNKNOWN_DIRECTION"])

    def test_stable_per_trace_peer_alias(self) -> None:
        lines = [
            _sample_row(101, "10.0.0.30", "10.0.0.10", "UDP"),
            _sample_row(102, "10.0.0.10", "10.0.0.20", "UDP"),
            _sample_row(103, "10.0.0.20", "10.0.0.10", "UDP"),
        ]
        _, rows_a = _rows(lines)
        _, rows_b = _rows(lines)
        mapping_a = [row.peer_alias for row in rows_a]
        self.assertEqual(mapping_a, ["REMOTE_PEER_1", "REMOTE_PEER_2", "REMOTE_PEER_2"])
        self.assertEqual(mapping_a, [row.peer_alias for row in rows_b])
        rendered = json.dumps(mapping_a)
        for address in ("10.0.0.10", "10.0.0.20", "10.0.0.30"):
            self.assertNotIn(address, rendered)

    def test_no_raw_ip_in_sanitised_summary(self) -> None:
        lines = [
            _sample_row(101, "10.0.0.10", "10.0.0.20", "RTP", rtp_pt="99", rtp_ssrc="1", rtp_ts="90000"),
            _sample_row(102, "10.0.0.30", "10.0.0.10", "RTCP", rtcp_pt="206"),
        ]
        path, rows = _rows(lines)
        summary = extractor.summarize(rows, input_path=path, max_message_rows=20, operator_view_start_epoch=100.0)
        rendered = json.dumps(summary, sort_keys=True)
        for address in ("10.0.0.10", "10.0.0.20", "10.0.0.30"):
            self.assertNotIn(address, rendered)
        self.assertIs(summary["RAW_CLIENT_IP_IN_SANITISED_SUMMARY"], False)
        self.assertIs(summary["RAW_REMOTE_IP_IN_SANITISED_SUMMARY"], False)
        completed = subprocess.run(
            [
                sys.executable,
                str(EXTRACTOR),
                "--input-tsv",
                str(path),
                "--client-ip",
                "10.0.0.10",
                "--operator-view-start-epoch",
                "100.0",
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        for address in ("10.0.0.10", "10.0.0.20", "10.0.0.30"):
            self.assertNotIn(address, completed.stdout)

    def test_buckets_do_not_merge_different_peers(self) -> None:
        summary = _summary(
            [
                _sample_row(101, "10.0.0.10", "10.0.0.20", "RTP", rtp_pt="99", length=120),
                _sample_row(102, "10.0.0.10", "10.0.0.30", "RTP", rtp_pt="99", length=120),
            ]
        )
        self.assertEqual(summary["MESSAGE_FAMILY_BUCKET_COUNT"], 2)
        self.assertEqual({row["PEER_ALIAS"] for row in summary["MESSAGE_FAMILY_ROWS"]}, {"REMOTE_PEER_1", "REMOTE_PEER_2"})

    def test_pre_window_pass(self) -> None:
        summary = _summary([_sample_row(1007, "10.0.0.10", "10.0.0.20", "RTP", rtp_pt="99")], view=1006.0, capture_start=1000.0)
        self.assertEqual(summary["PRE_WINDOW_GATE"], "PASS")
        self.assertEqual(summary["PRE_WINDOW_SECONDS"], 6.0)

    def test_pre_window_fail(self) -> None:
        summary = _summary([_sample_row(1004, "10.0.0.10", "10.0.0.20", "RTP", rtp_pt="99")], view=1003.0, capture_start=1000.0)
        self.assertEqual(summary["PRE_WINDOW_GATE"], "FAIL")
        self.assertIn("PRE_WINDOW_TOO_SHORT=FAILED_SAFE", RUNNER.read_text(encoding="utf-8"))

    def test_first_rtp_after_view_derives_media_reference(self) -> None:
        summary = _summary(
            [
                _sample_row(99, "10.0.0.10", "10.0.0.20", "RTP", rtp_pt="99"),
                _sample_row(103, "10.0.0.20", "10.0.0.10", "RTP", rtp_pt="99"),
            ],
            view=100.0,
        )
        self.assertEqual(summary["MEDIA_ACTIVE_REFERENCE"], "FIRST_RTP_AFTER_VIEW")
        self.assertEqual(summary["VIEW_TO_FIRST_RTP_SECONDS"], 3.0)
        rtp_rows = [row for row in summary["MESSAGE_FAMILY_ROWS"] if row["PROTOCOL_FAMILY"] == "RTP"]
        self.assertEqual(rtp_rows[0]["RELATIVE_TIME"], 0.0)
        self.assertEqual(rtp_rows[0]["FIRST_AT"], 0.0)

    def test_no_rtp_unresolved(self) -> None:
        summary = _summary(
            [
                _sample_row(101, "10.0.0.10", "10.0.0.20", "UDP"),
                _sample_row(102, "10.0.0.20", "10.0.0.10", "TLS", udp_src="", udp_dst="", length=80),
            ],
            capture_end=200.0,
        )
        self.assertEqual(summary["MEDIA_ACTIVE_REFERENCE"], "UNRESOLVED_NO_RTP")
        self.assertEqual(summary["VIEW_TO_FIRST_RTP_SECONDS"], "UNRESOLVED")
        self.assertEqual(summary["POST_MEDIA_ACTIVE_90S_GATE"], "UNRESOLVED")
        self.assertEqual(summary["POST_MEDIA_ACTIVE_60S_GATE"], "UNRESOLVED")
        self.assertEqual(summary["POST36_ANY_RECORDS"], "UNRESOLVED")
        self.assertTrue(all(row["RELATIVE_TIME"] is None and row["FIRST_AT"] is None for row in summary["MESSAGE_FAMILY_ROWS"]))

    def test_actual_post_media_window_calculation(self) -> None:
        for end, seconds, gate90, gate60 in ((198.5, 95.5, "PASS", "PASS"), (178.0, 75.0, "FAIL", "PASS"), (133.0, 30.0, "FAIL", "FAIL")):
            summary = _summary([_sample_row(103, "10.0.0.10", "10.0.0.20", "RTP", rtp_pt="99")], capture_end=end)
            self.assertEqual(summary["POST_MEDIA_ACTIVE_CAPTURE_SECONDS"], seconds)
            self.assertEqual(summary["POST_MEDIA_ACTIVE_90S_GATE"], gate90)
            self.assertEqual(summary["POST_MEDIA_ACTIVE_60S_GATE"], gate60)

    def test_message_row_truncation_explicitly_reported(self) -> None:
        lines = [
            _sample_row(110, "10.0.0.10", "10.0.0.20", "UDP", length=60),
            _sample_row(120, "10.0.0.10", "10.0.0.20", "UDP", length=60),
            _sample_row(101, "10.0.0.10", "10.0.0.30", "RTP", rtp_pt="99", length=61),
            _sample_row(102, "10.0.0.10", "10.0.0.40", "RTCP", rtcp_pt="206", length=62),
        ]
        summary = _summary(lines, max_rows=2)
        self.assertGreater(summary["MESSAGE_FAMILY_BUCKET_COUNT"], summary["MESSAGE_FAMILY_ROWS_EMITTED"])
        self.assertIs(summary["MESSAGE_FAMILY_ROWS_TRUNCATED"], True)
        self.assertIn("UDP_METADATA", summary["REPEATING_LT36S_CLASSES"])

    def test_media_active_reference_is_not_operator_supplied(self) -> None:
        path = _write_tsv([_sample_row(101, "10.0.0.10", "10.0.0.20", "RTP", rtp_pt="99")])
        completed = subprocess.run(
            [
                sys.executable,
                str(EXTRACTOR),
                "--input-tsv",
                str(path),
                "--client-ip",
                "10.0.0.10",
                "--operator-view-start-epoch",
                "100.0",
                "--media-active-epoch",
                "100.0",
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertNotEqual(completed.returncode, 0)
        for source in (RUNNER.read_text(encoding="utf-8"), EXTRACTOR.read_text(encoding="utf-8")):
            self.assertNotIn("MEDIA_ACTIVE_EPOCH", source)
            self.assertNotIn("media_active_epoch", source)

    def test_raw_retention_recommended_for_one_shot(self) -> None:
        completed = self._dry_run("--client-ip", "10.0.0.10")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("RAW_RETENTION_POLICY=RECOMMENDED_RETAIN_RAW_FOR_ONE_SHOT", completed.stdout)
        source = RUNNER.read_text(encoding="utf-8")
        self.assertIn("RETAIN_RAW=0", source)
        self.assertIn("--authorize-passive-capture", source)
        self.assertIn("--retain-raw", DOC.read_text(encoding="utf-8"))

    def test_r13e_document_records_capture_point_preflight_and_gates(self) -> None:
        doc = DOC.read_text(encoding="utf-8")
        for required in (
            "P116 R13E official-app trace hardening",
            "CAPTURE_POINT_READY=false",
            "SEES_PHONE_TRAFFIC=UNRESOLVED",
            "CAPTURE_POINT_TYPE=UNRESOLVED",
            "OPERATOR_VIEW_START_EPOCH",
            "MEDIA_ACTIVE_REFERENCE",
            "FIRST_RTP_AFTER_VIEW",
            "UNRESOLVED_NO_RTP",
            "POST_MEDIA_ACTIVE_90S_GATE",
            "POST_MEDIA_ACTIVE_60S_GATE",
            "MESSAGE_FAMILY_ROWS_TRUNCATED",
            "--retain-raw",
            "RAW_CLIENT_IP_IN_SANITISED_SUMMARY=false",
            "RAW_REMOTE_IP_IN_SANITISED_SUMMARY=false",
            "tshark",
            "NEXT_REQUIRED_USER_ACTION=Подтвердить точку наблюдения, видящую phone<->panel traffic (SPAN/mirror на коммутаторе или AP, либо phone-side capture), — CT122/CT120 как обычные bridge-порты не годятся.",
        ):
            self.assertIn(required, doc)


if __name__ == "__main__":
    unittest.main()
