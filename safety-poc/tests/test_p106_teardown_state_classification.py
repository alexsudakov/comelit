#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
MEDIA = ROOT / "research" / "media" / "v1"
sys.path.insert(0, str(MEDIA))

from entrance_p101_offline_harness import recv_harness_source
from entrance_p105_len24_fallback_diagnostic_transform import transform as p105_transform
from entrance_p106_teardown_state_classification_transform import report, transform


SOURCE = ROOT / "research" / "door" / "v1_5_7" / "comelit-v4-persistent-ctpp-door.c"
CC = shutil.which("cc")


def _compile_and_run(source: str) -> subprocess.CompletedProcess[str]:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        c_path = tmp_path / "harness.c"
        bin_path = tmp_path / "harness"
        c_path.write_text(source, encoding="utf-8")
        subprocess.run(
            [CC, "-std=c99", "-Wall", "-Wextra", str(c_path), "-o", str(bin_path)],
            check=True,
            text=True,
            capture_output=True,
        )
        return subprocess.run([str(bin_path)], check=True, text=True, capture_output=True)


TEST_LIB = r'''
static void recv_reset(void)
{
    failed = FALSE;
    loop = (gpointer)0x1;
    p101_harness_loop_quit_calls = 0;
    p101_harness_sendto_calls = 0;
    p101_harness_notify_calls = 0;
    p101_harness_notify_result = FALSE;
    p101_harness_socket_closed = FALSE;
    pseudotcp_packets_in = 0;
    pseudo_tcp = (gpointer)0x1;
    p80_media_forwarding_enabled = TRUE;
    p99_preactive_media_demux_armed = FALSE;
    pseudotcp_graceful_stop_started = FALSE;
    len24_fallback_seen_count = 0;
}

static int expect(int ok, const char *name)
{
    if (!ok) {
        fprintf(stderr, "EXPECT_FAIL=%s\n", name);
        return 1;
    }
    return 0;
}

static int drive(guint len, int graceful_started, int socket_closed)
{
    guint8 packet[1200];
    memset(packet, 0, sizeof(packet));
    recv_reset();
    pseudotcp_graceful_stop_started = graceful_started ? TRUE : FALSE;
    p101_harness_socket_closed = socket_closed ? TRUE : FALSE;
    recv_cb(NULL, 1u, 1u, len, (gchar *)packet, NULL);
    printf(
        "RESULT len=%u failed=%d loop=%u notify=%u\n",
        len,
        failed,
        p101_harness_loop_quit_calls,
        p101_harness_notify_calls
    );
    return 0;
}
'''


class P106TeardownStateClassificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source_text = SOURCE.read_text(encoding="utf-8")
        cls.p105_candidate = p105_transform(cls.source_text)
        cls.candidate = transform(cls.source_text)

    @unittest.skipUnless(CC, "cc compiler not available")
    def test_notify_false_closed_without_graceful_start_is_fatal(self) -> None:
        result = _compile_and_run(recv_harness_source(self.candidate, TEST_LIB + r'''
int main(void)
{
    drive(31u, 0, 1);
    return expect(failed == TRUE, "failed") ||
        expect(p101_harness_loop_quit_calls == 1u, "loop");
}
'''))
        self.assertIn("PSEUDOTCP_NOTIFY_PACKET_SOCKET_CLOSED=true", result.stderr)
        self.assertIn("PSEUDOTCP_NOTIFY_PACKET_GRACEFUL_STARTED=false", result.stderr)
        self.assertIn("PSEUDOTCP_NOTIFY_PACKET_CLASS=FATAL", result.stderr)

    @unittest.skipUnless(CC, "cc compiler not available")
    def test_notify_false_graceful_without_closed_proof_is_fatal(self) -> None:
        result = _compile_and_run(recv_harness_source(self.candidate, TEST_LIB + r'''
int main(void)
{
    drive(1003u, 1, 0);
    return expect(failed == TRUE, "failed") ||
        expect(p101_harness_loop_quit_calls == 1u, "loop");
}
'''))
        self.assertIn("PSEUDOTCP_NOTIFY_PACKET_SOCKET_CLOSED=false", result.stderr)
        self.assertIn("PSEUDOTCP_NOTIFY_PACKET_GRACEFUL_STARTED=true", result.stderr)
        self.assertIn("PSEUDOTCP_NOTIFY_PACKET_CLASS=FATAL", result.stderr)

    @unittest.skipUnless(CC, "cc compiler not available")
    def test_closed_plus_graceful_is_expected_terminal_shutdown(self) -> None:
        result = _compile_and_run(recv_harness_source(self.candidate, TEST_LIB + r'''
int main(void)
{
    drive(31u, 1, 1);
    return expect(failed == FALSE, "failed") ||
        expect(p101_harness_loop_quit_calls == 0u, "loop") ||
        expect(p101_harness_notify_calls == 1u, "notify");
}
'''))
        self.assertIn("PSEUDOTCP_NOTIFY_PACKET_CLASS=EXPECTED_TERMINAL_SHUTDOWN", result.stderr)

    @unittest.skipUnless(CC, "cc compiler not available")
    def test_packet_length_does_not_change_classification(self) -> None:
        result = _compile_and_run(recv_harness_source(self.candidate, TEST_LIB + r'''
int main(void)
{
    drive(24u, 1, 1);
    int failed_24 = failed;
    guint loops_24 = p101_harness_loop_quit_calls;
    drive(31u, 1, 1);
    int failed_31 = failed;
    guint loops_31 = p101_harness_loop_quit_calls;
    drive(1003u, 1, 1);
    return expect(failed_24 == failed_31, "failed-same-31") ||
        expect(loops_24 == loops_31, "loop-same-31") ||
        expect(failed == failed_24, "failed-same-1003") ||
        expect(p101_harness_loop_quit_calls == loops_24, "loop-same-1003");
}
'''))
        self.assertEqual(
            result.stderr.count("PSEUDOTCP_NOTIFY_PACKET_CLASS=EXPECTED_TERMINAL_SHUTDOWN"),
            3,
        )

    def test_report_markers(self) -> None:
        text = report()
        for marker in (
            "P106_TEARDOWN_STATE_TRANSFORM=PASS",
            "P106_NOTIFY_CLASSIFIER=EVIDENCE_GATED",
            "P106_BLANKET_SUPPRESSION=false",
            "P106_LEN24_SPECIAL_CASE=false",
            "P106_AUTOMATIC_RETRY=false",
            "P106_SECOND_CTPP_OPEN=false",
            "DOOR_ACTION_SENT=false",
            "NETWORK_IO_PERFORMED=false",
            "CANDIDATE_EXECUTED=false",
        ):
            self.assertIn(marker, text)

    def test_static_safety_contracts(self) -> None:
        self.assertIn("pseudo_tcp_socket_is_closed(pseudo_tcp)", self.candidate)
        self.assertIn("pseudotcp_graceful_stop_started", self.candidate)
        self.assertIn("PSEUDOTCP_NOTIFY_PACKET=FAIL ", self.candidate)
        self.assertIn("LEN=%u\\n", self.candidate)
        self.assertIn("PSEUDOTCP_NOTIFY_PACKET_CLASS=%s", self.candidate)
        self.assertEqual(self.candidate.count("v4_queue_open_ctpp("), 2)
        self.assertNotIn("signal(SIGUSR1, v4_door_signal_handler);", self.candidate)
        self.assertEqual(
            len(re.findall(r"\bretry\b", self.candidate.lower())),
            len(re.findall(r"\bretry\b", self.p105_candidate.lower())),
        )
        for forbidden in ("OPEN_DOOR", "open_door", "create_door_message", "--door"):
            self.assertNotIn(forbidden, self.candidate)

    def test_p106_does_not_add_len24_branch(self) -> None:
        p105_lines = set(self.p105_candidate.splitlines())
        added_lines = [line for line in self.candidate.splitlines() if line not in p105_lines]
        added_text = "\n".join(added_lines)
        self.assertNotRegex(added_text, r"\blen\s*(==|!=|<|>|<=|>=)\s*24u?\b")
        self.assertNotRegex(added_text, r"\b24u?\s*(==|!=|<|>|<=|>=)\s*len\b")


if __name__ == "__main__":
    unittest.main()
