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
from entrance_p101_preactive_profile_gate_transform import transform as p101_transform
from entrance_p105_len24_fallback_diagnostic_transform import (
    LEN24_FALLBACK_MAX_SIGNATURES,
    report,
    transform,
)


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
    p101_harness_notify_result = TRUE;
    pseudotcp_packets_in = 0;
    pseudo_tcp = (gpointer)0x1;
    p80_media_forwarding_enabled = TRUE;
    p99_preactive_media_demux_armed = FALSE;
    len24_fallback_seen_count = 0;
}

static int expect(int ok, const char *name)
{
    if (!ok) {
        fprintf(stderr, "%s\n", name);
        return 1;
    }
    return 0;
}
'''


class P105DiagnosticTransformTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source_text = SOURCE.read_text(encoding="utf-8")
        cls.p101_candidate = p101_transform(cls.source_text)
        cls.candidate = transform(cls.source_text)

    @unittest.skipUnless(CC, "cc compiler not available")
    def test_recv_diagnostics_emit_without_behavior_change(self) -> None:
        result = _compile_and_run(recv_harness_source(self.candidate, TEST_LIB + r'''
int main(void)
{
    guint8 packet[24];
    memset(packet, 0, sizeof(packet));
    packet[13] = 2u;
    recv_reset();
    recv_cb(NULL, 1u, 1u, sizeof(packet), (gchar *)packet, NULL);
    return expect(p101_harness_notify_calls == 1u, "notify") ||
        expect(p101_harness_sendto_calls == 0u, "sendto") ||
        expect(failed == FALSE, "failed") ||
        expect(p101_harness_loop_quit_calls == 0u, "loop") ||
        expect(pseudotcp_packets_in == 1u, "packets");
}
'''))
        self.assertIn("LEN24_FALLBACK_LEN=24", result.stdout)
        self.assertIn("LEN24_FALLBACK_PSEUDOTCP_HEADER_SHAPE=true", result.stdout)
        self.assertIn("LEN24_FALLBACK_DIAGNOSTIC_ONLY=true", result.stdout)

    @unittest.skipUnless(CC, "cc compiler not available")
    def test_notify_failure_terminal_path_unchanged(self) -> None:
        result = _compile_and_run(recv_harness_source(self.candidate, TEST_LIB + r'''
int main(void)
{
    guint8 packet[24];
    memset(packet, 0, sizeof(packet));
    recv_reset();
    p101_harness_notify_result = FALSE;
    recv_cb(NULL, 1u, 1u, sizeof(packet), (gchar *)packet, NULL);
    return expect(p101_harness_notify_calls == 1u, "notify") ||
        expect(failed == TRUE, "failed") ||
        expect(p101_harness_loop_quit_calls == 1u, "loop") ||
        expect(p101_harness_sendto_calls == 0u, "sendto");
}
'''))
        self.assertIn("LEN24_FALLBACK_DIAGNOSTIC_ONLY=true", result.stdout)
        self.assertIn("PSEUDOTCP_NOTIFY_PACKET=FAIL LEN=24", result.stderr)

    @unittest.skipUnless(CC, "cc compiler not available")
    def test_distinct_signature_bound_is_respected(self) -> None:
        result = _compile_and_run(recv_harness_source(self.candidate, TEST_LIB + r'''
int main(void)
{
    guint8 packet[40];
    recv_reset();
    for (guint i = 0u; i < 12u; i++) {
        memset(packet, 0, sizeof(packet));
        packet[13] = (guint8)i;
        recv_cb(NULL, 1u, 1u, 24u + i, (gchar *)packet, NULL);
    }
    return expect(len24_fallback_seen_count == LEN24_FALLBACK_MAX_SIGNATURES, "bound");
}
'''))
        self.assertEqual(result.stdout.count("LEN24_FALLBACK_DIAGNOSTIC_ONLY=true"), LEN24_FALLBACK_MAX_SIGNATURES)

    def test_report_markers(self) -> None:
        text = report()
        self.assertIn("LEN24_FALLBACK_DIAGNOSTIC_TRANSFORM=PASS", text)
        self.assertIn("LEN24_FALLBACK_BEHAVIOUR_CHANGED=false", text)
        self.assertIn("LEN24_FALLBACK_RAW_BYTES_EMITTED=false", text)
        self.assertIn("LEN24_FALLBACK_AUTOMATIC_RETRY=false", text)
        self.assertIn("LEN24_FALLBACK_SECOND_CTPP_OPEN=false", text)
        self.assertIn("DOOR_ACTION_SENT=false", text)

    def test_static_no_forbidden_behavior_or_raw_byte_prints(self) -> None:
        self.assertNotIn("signal(SIGUSR1, v4_door_signal_handler);", self.candidate)
        self.assertEqual(
            len(re.findall(r"\bretry\b", self.candidate.lower())),
            len(re.findall(r"\bretry\b", self.p101_candidate.lower())),
        )
        self.assertEqual(self.candidate.count("v4_queue_open_ctpp("), 2)
        diagnostic_lines = [line for line in self.candidate.splitlines() if "LEN24_FALLBACK_" in line]
        self.assertFalse(any("%02x" in line or "%x" in line for line in diagnostic_lines))
        self.assertIn(f"#define LEN24_FALLBACK_MAX_SIGNATURES {LEN24_FALLBACK_MAX_SIGNATURES}u", self.candidate)

    def test_original_failure_block_is_preserved(self) -> None:
        pattern = re.compile(
            r"if \(!ok\) \{\s*fprintf\(\s*stderr,\s*\"PSEUDOTCP_NOTIFY_PACKET=FAIL \"\s*"
            r"\"LEN=%u\\n\",\s*len\s*\);\s*failed = TRUE;\s*if \(loop\)\s*g_main_loop_quit\(loop\);",
            re.MULTILINE,
        )
        self.assertRegex(self.candidate, pattern)


if __name__ == "__main__":
    unittest.main()
