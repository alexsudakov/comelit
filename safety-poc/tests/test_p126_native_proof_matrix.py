#!/usr/bin/env python3
"""Offline proof matrix for the preserved P126 native helper.

The behavioural gate compiles the real generated ACK/defer/timeout functions
into a receive-loop harness.  It never executes the packaged network helper.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[2]
MEDIA = ROOT / "safety-poc" / "research" / "media" / "v1"
SOURCE = ROOT / "safety-poc" / "research" / "door" / "v1_5_7" / "comelit-v4-persistent-ctpp-door.c"
BINARY = ROOT / "custom_components" / "comelit" / "native" / "comelit-media"
META = MEDIA / "p126_refresh_defer_build_meta.txt"
WHOLE_TU_STUB_INCLUDE = ROOT / "safety-poc" / "tests" / "native" / "whole_tu_stub_include"
EXPECTED_SHA = "b046e50bc9927c8947e9811cee20276d945c989389abe5ac37a6ee46a5416dab"
EXPECTED_NEEDED = [
    "libc.musl-x86_64.so.1",
    "libglib-2.0.so.0",
    "libgobject-2.0.so.0",
    "libnice.so.10",
]

sys.path.insert(0, str(MEDIA))
import entrance_p126_refresh_defer_transform as p126  # noqa: E402


def _function(source: str, name: str) -> str:
    match = re.search(rf"static gboolean\n{name}\([^\n]*\)\n\{{", source)
    if match is None:
        raise AssertionError(f"generated function missing: {name}")
    depth = 0
    for index in range(match.end() - 1, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[match.start() : index + 1]
    raise AssertionError(f"unterminated generated function: {name}")


def _metadata() -> dict[str, str]:
    return dict(
        line.split("=", 1)
        for line in META.read_text(encoding="utf-8").splitlines()
        if "=" in line
    )


def _binary_mode_acceptable(mode: int) -> bool:
    """Accept readable/executable owner modes unless the binary is world-writable."""
    return bool(mode & 0o400) and bool(mode & 0o100) and not bool(mode & 0o002)


def _readelf(*args: str) -> str:
    return subprocess.run(
        ["readelf", *args, str(BINARY)],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout


def _compile_receive_loop(candidate: str) -> str:
    cc = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")
    if not cc:
        raise unittest.SkipTest("C compiler unavailable")
    p99 = _function(candidate, "p99_state_scoped_structural_ack")
    handler = _function(candidate, "r27_handle_repeat_ack")
    timeout = _function(candidate, "r27_repeat_ack_timeout_cb")
    harness = textwrap.dedent(
        r'''
        #include <stdint.h>
        #include <stdio.h>
        #include <string.h>
        typedef int gboolean;
        typedef void *gpointer;
        typedef unsigned int guint;
        typedef uint8_t guint8;
        typedef uint16_t guint16;
        #define TRUE 1
        #define FALSE 0
        #define G_SOURCE_REMOVE 0

        static guint16 v4_ctpp_channel_id = 7u;
        static gboolean r27_repeat_outstanding;
        static gboolean r27_repeat_ack_observed;
        static gboolean r27_repeat_ack_timed_out;
        static gboolean r27_refresh_fail_closed;
        static guint r27_refresh_current_index;
        static guint r27_refresh_last_accepted_index;
        static guint r126_refresh_deferred_index;
        static int demux_count, call_init_count, consumed_count;
        static int schedule_count, graceful_stop_count, tx_count;
        static guint8 expected_frame[96];
        static guint expected_len;

        static guint16 read_le16(const guint8 *p) {
            return (guint16)((guint16)p[0] | ((guint16)p[1] << 8));
        }
        static gboolean r27_schedule_next_refresh(const char *reason) {
            (void)reason; schedule_count++; return TRUE;
        }
        static gboolean pseudotcp_begin_graceful_stop(const char *reason) {
            (void)reason; graceful_stop_count++; return TRUE;
        }
        __P99__
        __HANDLER__
        __TIMEOUT__

        static void regular_ctpp_demux(const guint8 *body, guint body_len) {
            demux_count++;
            if (body_len != expected_len ||
                (body_len && memcmp(body, expected_frame, body_len) != 0)) {
                puts("BYTE_IDENTICAL_REDELIVERY=FAIL");
                tx_count = 99;
                return;
            }
            if (body && body_len >= 8u && body[0] == 0xc0u && body[1] == 0x18u &&
                body[6] == 0x00u && body[7] == 0x28u) {
                call_init_count++;
                puts("CALL_INIT_OBSERVER=SEEN");
            }
        }
        static void receive_one(guint16 channel, const guint8 *body, guint body_len) {
            expected_len = body_len;
            if (body_len) memcpy(expected_frame, body, body_len);
            if (r27_handle_repeat_ack(channel, body, body_len)) {
                consumed_count++;
                return;
            }
            regular_ctpp_demux(body, body_len);
        }
        #define CHECK(x) do { if (!(x)) return __LINE__; } while (0)
        static void reset_outstanding(guint index) {
            r27_repeat_outstanding = TRUE;
            r27_repeat_ack_observed = FALSE;
            r27_refresh_current_index = index;
            r27_refresh_last_accepted_index = 0u;
            r126_refresh_deferred_index = 0u;
        }
        int main(void) {
            guint8 call_init[72] = {0};
            guint8 ack[32] = {0};
            guint8 release[12] = {0};
            guint8 wrong[12] = {0};
            guint8 tiny[4] = {0x40u, 0x18u, 0xa5u, 0x5au};
            guint before;
            call_init[0]=0xc0u; call_init[1]=0x18u;
            call_init[6]=0x00u; call_init[7]=0x28u;
            ack[0]=0x00u; ack[1]=0x18u;
            ack[8]=ack[9]=ack[10]=ack[11]=0xffu;
            release[0]=0x60u; release[1]=0x18u;
            release[6]=0x00u; release[7]=0x01u;
            wrong[0]=0x40u; wrong[1]=0x18u;
            wrong[6]=0x12u; wrong[7]=0x34u;

            reset_outstanding(1u);
            receive_one(7u, call_init, sizeof(call_init));
            CHECK(demux_count == 1 && call_init_count == 1 && consumed_count == 0);
            CHECK(r27_repeat_outstanding && !r27_repeat_ack_observed);
            CHECK(r27_refresh_last_accepted_index == 0u && schedule_count == 0);
            CHECK(graceful_stop_count == 0 && tx_count == 0);

            before = demux_count;
            receive_one(7u, NULL, 0u);
            receive_one(7u, tiny, 0u);
            receive_one(7u, tiny, 1u);
            receive_one(7u, tiny, 2u);
            receive_one(7u, tiny, 3u);
            receive_one(99u, ack, sizeof(ack));
            receive_one(7u, wrong, sizeof(wrong));
            CHECK(demux_count == (int)before + 7);
            CHECK(r27_repeat_outstanding && consumed_count == 0);
            CHECK(schedule_count == 0 && graceful_stop_count == 0 && tx_count == 0);

            before = demux_count;
            receive_one(7u, release, sizeof(release));
            CHECK(demux_count == (int)before + 1 && consumed_count == 0);
            CHECK(r27_repeat_outstanding && graceful_stop_count == 0 && tx_count == 0);

            receive_one(7u, ack, sizeof(ack));
            CHECK(consumed_count == 1 && !r27_repeat_outstanding);
            CHECK(r27_repeat_ack_observed && r27_refresh_last_accepted_index == 1u);
            CHECK(schedule_count == 1);
            receive_one(7u, ack, sizeof(ack));
            CHECK(consumed_count == 1 && schedule_count == 1);

            reset_outstanding(2u);
            r27_repeat_ack_timeout_cb(NULL);
            r27_repeat_ack_timeout_cb(NULL);
            CHECK(r27_repeat_ack_timed_out && r27_refresh_fail_closed);
            CHECK(!r27_repeat_outstanding && graceful_stop_count == 1);
            CHECK(tx_count == 0);
            puts("P126_NATIVE_PROOF_MATRIX_HARNESS=PASS");
            return 0;
        }
        '''
    ).replace("__P99__", p99).replace("__HANDLER__", handler).replace("__TIMEOUT__", timeout)
    with tempfile.TemporaryDirectory(prefix="p126-proof-") as tmp:
        source = Path(tmp) / "proof.c"
        executable = Path(tmp) / "proof"
        source.write_text(harness, encoding="utf-8")
        compiled = subprocess.run(
            [cc, "-std=c99", "-Wall", "-Wextra", "-pedantic", str(source), "-o", str(executable)],
            text=True,
            capture_output=True,
        )
        if compiled.returncode or compiled.stderr:
            raise AssertionError(compiled.stdout + compiled.stderr)
        run = subprocess.run([str(executable)], text=True, capture_output=True)
        if run.returncode:
            raise AssertionError(f"harness rc={run.returncode}\n{run.stdout}\n{run.stderr}")
        return run.stdout


def _compile_real_whole_tu_loop(candidate: str) -> str:
    """Compile the complete transformed TU and call its real post-UAUT loop."""
    cc = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")
    if not cc:
        raise AssertionError("C compiler unavailable for required whole-TU proof")
    if not WHOLE_TU_STUB_INCLUDE.is_dir():
        raise AssertionError("required whole-TU stub includes unavailable")

    stubs = textwrap.dedent(
        r'''
        #include <stdlib.h>
        #include <string.h>
        #include <stdint.h>
        #include <stdio.h>

        typedef int gboolean; typedef int gint; typedef long long gint64; typedef unsigned int guint;
        typedef char gchar; typedef void *gpointer; typedef size_t gsize; typedef uint32_t guint32;

        int proof_tx_action_count;
        static gint64 fake_us = 1000000;
        gint64 g_get_monotonic_time(void) { fake_us += 1000; return fake_us; }
        gint64 g_get_real_time(void) { return fake_us; }
        guint g_timeout_add(void *a, void *b, void *c) { (void)a;(void)b;(void)c; return 1; }
        guint g_timeout_add_seconds(void *a, void *b, void *c) { (void)a;(void)b;(void)c; return 1; }
        void g_main_loop_quit(void *a) { (void)a; }
        void g_free(void *p) { free(p); }
        gpointer g_strdup(const char *s) { return s ? strdup(s) : NULL; }
        gpointer g_strdup_printf(const char *f, ...) { (void)f; return strdup("stub"); }
        gint g_strcmp0(const char *a, const char *b) { if (a == b) return 0; if (!a) return -1; if (!b) return 1; return strcmp(a,b); }
        gsize g_strlcpy(char *d, const char *s, gsize n) { gsize l = s ? strlen(s) : 0; if (n) { gsize c = l < n-1 ? l : n-1; if (c) memcpy(d,s,c); d[c]=0; } return l; }
        gpointer g_strndup(const char *s, gsize n) { char *p = malloc(n+1); if (!p) return NULL; memcpy(p,s,n); p[n]=0; return p; }
        gpointer g_strstr_len(const char *h, long long n, const char *needle) { (void)n; return strstr(h, needle); }
        gboolean g_ascii_isprint(int c) { return c >= 32 && c < 127; }
        gboolean g_ascii_isspace(int c) { return c==' '||c=='\t'||c=='\n'||c=='\r'; }
        gpointer g_ascii_strdown(const char *s, long long n) { (void)n; return g_strdup(s); }
        gint64 g_ascii_strtoll(const char *s, char **e, int b) { return strtoll(s,e,b); }
        gpointer g_checksum_new(int t) { (void)t; return (gpointer)1; }
        void g_checksum_update(void *c, const void *d, long long n) { (void)c;(void)d;(void)n; }
        const gchar *g_checksum_get_string(void *c) { (void)c; return "stub"; }
        void g_checksum_free(void *c) { (void)c; }
        gchar *g_compute_checksum_for_data(int t, const void *d, unsigned long long n) { (void)t;(void)d;(void)n; return strdup("0000000000000000000000000000000000000000000000000000000000000000"); }
        void g_error_free(void *e) { (void)e; }
        gboolean g_file_set_contents(const char *p, const char *d, long long n, void *e) { (void)p;(void)d;(void)n;(void)e; return 1; }
        guint32 g_random_int(void) { return 4; }

        int pseudo_tcp_socket_close(void *s) { (void)s; return 0; }
        int pseudo_tcp_socket_get_error(void *s) { (void)s; return 0; }
        int pseudo_tcp_socket_get_next_clock(void *s, unsigned long long *c) { (void)s; if (c) *c = 0; return 0; }
        int pseudo_tcp_socket_recv(void *s, char *b, size_t n) { (void)s;(void)b;(void)n; return 0; }
        int pseudo_tcp_socket_send(void *s, const char *b, size_t n) { (void)s;(void)b; proof_tx_action_count++; return (int)n; }
        '''
    )
    harness = textwrap.dedent(
        r'''
        #define main comelit_candidate_main
        #include "candidate.c"
        #undef main

        #include <stdio.h>
        #include <string.h>

        extern int proof_tx_action_count;

        int main(void)
        {
            /* Synthetic VIP frame: 00 06 | body_len | request_id | body. */
            unsigned char frame[8 + 72];
            memset(frame, 0, sizeof(frame));
            frame[0] = 0x00; frame[1] = 0x06;
            frame[2] = 72; frame[3] = 0;
            frame[4] = 7; frame[5] = 0; frame[6] = 0; frame[7] = 0;
            frame[8] = 0xc0; frame[9] = 0x18;
            frame[14] = 0x00; frame[15] = 0x28;

            v4_ctpp_channel_id = 7;
            p12_stage = P12_STAGE_V4_LISTEN_RING;
            r27_repeat_outstanding = TRUE;
            r27_refresh_current_index = 1;
            r27_repeat_ack_observed = FALSE;
            r27_repeat_ack_timed_out = FALSE;
            r27_refresh_fail_closed = FALSE;
            post_ack_capture_len = sizeof(frame);
            memcpy(post_ack_capture, frame, sizeof(frame));

            gboolean rc = p12_process_post_uaut();
            printf("REAL_LOOP_RC=%d\n", (int)rc);
            printf("REAL_LOOP_CONSUMED=%u\n", (unsigned)post_ack_capture_len);
            printf("R27_OUTSTANDING=%d\n", (int)r27_repeat_outstanding);
            printf("R27_FAIL_CLOSED=%d\n", (int)r27_refresh_fail_closed);
            printf("PROOF_TX_ACTION_COUNT=%d\n", proof_tx_action_count);
            printf("P12_TX_KIND=%d\n", (int)p12_tx_kind);
            return 0;
        }
        '''
    )
    with tempfile.TemporaryDirectory(prefix="p126-whole-tu-") as tmp:
        tmp_path = Path(tmp)
        (tmp_path / "candidate.c").write_text(candidate, encoding="utf-8")
        (tmp_path / "stubs.c").write_text(stubs, encoding="utf-8")
        (tmp_path / "harness.c").write_text(harness, encoding="utf-8")
        executable = tmp_path / "real-loop"
        compiled = subprocess.run(
            [
                cc,
                "-std=gnu99",
                "-ffunction-sections",
                "-fdata-sections",
                f"-I{WHOLE_TU_STUB_INCLUDE}",
                str(tmp_path / "stubs.c"),
                str(tmp_path / "harness.c"),
                "-Wl,--gc-sections",
                "-o",
                str(executable),
            ],
            text=True,
            capture_output=True,
        )
        if compiled.returncode:
            raise AssertionError(compiled.stdout + compiled.stderr)
        run = subprocess.run([str(executable)], text=True, capture_output=True)
        if run.returncode:
            raise AssertionError(f"whole-TU harness rc={run.returncode}\n{run.stdout}\n{run.stderr}")
        return run.stdout


class P126NativeProofMatrix(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.base = SOURCE.read_text(encoding="utf-8")
        cls.candidate = p126.transform(cls.base)
        cls.p125_candidate = p126.p125.transform(cls.base)
        cls.meta = _metadata()

    def test_00_binary_mode_acceptance_regression(self) -> None:
        for mode in (0o555, 0o755, 0o775):
            with self.subTest(mode=oct(mode)):
                self.assertTrue(_binary_mode_acceptable(mode))
        for mode in (0o644, 0o777):
            with self.subTest(mode=oct(mode)):
                self.assertFalse(_binary_mode_acceptable(mode))

    def test_01_real_receive_loop_redelivers_non_ack_once_before_timeout(self) -> None:
        output = _compile_receive_loop(self.candidate)
        self.assertIn("P126_NATIVE_PROOF_MATRIX_HARNESS=PASS", output)
        self.assertEqual(output.count("CALL_INIT_OBSERVER=SEEN"), 1)
        self.assertEqual(output.count("SECOND_001A_RESPONSE=DEFERRED"), 1)
        self.assertEqual(output.count("SECOND_001A_RESPONSE=ABSENT"), 1)
        self.assertLess(output.index("CALL_INIT_OBSERVER=SEEN"), output.index("SECOND_001A_RESPONSE=ABSENT"))
        self.assertNotIn("BYTE_IDENTICAL_REDELIVERY=FAIL", output)

    def test_01b_real_whole_tu_post_uaut_falls_through_to_ring_handler(self) -> None:
        output = _compile_real_whole_tu_loop(self.candidate)
        for marker in (
            "SECOND_001A_RESPONSE=DEFERRED",
            "SECOND_001A_ACK_CLASSIFICATION=DEFERRED",
            "V4_RING_OBSERVED=true",
            "V4_RING_KIND=CALL_INIT",
            "V4_RING_DOOR=unknown",
            "REAL_LOOP_RC=1",
            "REAL_LOOP_CONSUMED=0",
            "R27_OUTSTANDING=1",
            "R27_FAIL_CLOSED=0",
            "NETWORK_DOOR_ACTION_PERFORMED=false",
            "PHYSICAL_DOOR_ACTION=false",
            "PROOF_TX_ACTION_COUNT=0",
            "P12_TX_KIND=0",
        ):
            self.assertIn(marker, output)
        self.assertEqual(output.count("V4_RING_OBSERVED=true"), 1)
        self.assertEqual(output.count("V4_RING_KIND=CALL_INIT"), 1)

    def test_02_strict_ack_validator_and_timeout_are_preserved(self) -> None:
        handler = _function(self.candidate, "r27_handle_repeat_ack")
        timeout = _function(self.candidate, "r27_repeat_ack_timeout_cb")
        self.assertEqual(handler.count("p99_state_scoped_structural_ack("), 1)
        self.assertIn("body_len != 32u", self.candidate)
        self.assertNotIn("AMBIGUOUS", handler)
        self.assertIn("SECOND_001A_ACK_CLASSIFICATION=ABSENT", timeout)
        self.assertIn("REFRESH_FAIL_CLOSED=true", timeout)
        self.assertIn("#define R27_REPEAT_ACK_TIMEOUT_SECONDS 5u", self.candidate)

    def test_03_no_new_tx_retry_upstream_or_adoption(self) -> None:
        p125_tx = set(re.findall(r"\b(?:P12|P78|R27|P122)_TX_[A-Z0-9_]+", self.p125_candidate))
        p126_tx = set(re.findall(r"\b(?:P12|P78|R27|P122)_TX_[A-Z0-9_]+", self.candidate))
        self.assertEqual(p126_tx, p125_tx)
        self.assertNotIn("R45_", self.candidate)
        self.assertNotIn("R54_CALL_ADOPTION", self.candidate)
        self.assertNotIn("MEDIAREQ26", _function(self.candidate, "r27_handle_repeat_ack"))
        self.assertEqual(self.meta["second_upstream_added"], "false")
        self.assertEqual(self.meta["automatic_retry_added"], "false")

    def test_04_release_is_deferred_to_demux_without_a_fabricated_handler(self) -> None:
        self.assertEqual(self.meta["release_parsing_added"], "false")
        self.assertEqual(self.meta["release_handler_present"], "false")
        self.assertNotIn("release", _function(self.candidate, "r27_handle_repeat_ack").lower())

    def test_05_p122_door_gate_one_shot_and_precedence_are_unchanged(self) -> None:
        for marker in (
            "if (p122_door_sent)",
            "p122_door_sent = TRUE;",
            "v4_ring_is_retransmit(",
            "} else if (p122_door_waiting_ack) {",
        ):
            self.assertEqual(self.candidate.count(marker), self.p125_candidate.count(marker), marker)
        hook = self.candidate.split("} else if (p122_door_waiting_ack) {", 1)[1]
        self.assertLess(hook.index("p122_note_control_frame"), hook.index("r27_repeat_outstanding"))

    def test_06_binary_identity_markers_and_musl_contract(self) -> None:
        data = BINARY.read_bytes()
        self.assertEqual(hashlib.sha256(data).hexdigest(), EXPECTED_SHA)
        self.assertEqual(BINARY.stat().st_size, 312400)
        self.assertIn(b"SECOND_001A_ACK_CLASSIFICATION=DEFERRED", data)
        self.assertNotIn(b"SECOND_001A_ACK_CLASSIFICATION=AMBIGUOUS", data)
        self.assertIn(b"SECOND_001A_ACK_CLASSIFICATION=ABSENT", data)
        self.assertIn(b"REFRESH_FAIL_CLOSED=true", data)
        self.assertEqual(data.count(b"R45_"), 0)
        self.assertEqual(data.count(b"R54_CALL_ADOPTION"), 0)
        interpreter = re.search(r"Requesting program interpreter: ([^\]]+)\]", _readelf("-l"))
        self.assertIsNotNone(interpreter)
        self.assertEqual(interpreter.group(1), "/lib/ld-musl-x86_64.so.1")
        needed = sorted(re.findall(r"Shared library: \[([^\]]+)\]", _readelf("-d")))
        self.assertEqual(needed, EXPECTED_NEEDED)
        self.assertFalse(any("glibc" in item for item in needed))

    def test_07_build_id_mode_and_operator_provenance(self) -> None:
        build_id = re.search(r"Build ID: ([0-9a-f]+)", _readelf("-n"))
        self.assertIsNotNone(build_id)
        self.assertEqual(build_id.group(1), "966bef966a04f208762d7948c5903430ac0f1c43")
        self.assertTrue(_binary_mode_acceptable(BINARY.stat().st_mode & 0o777))
        self.assertEqual(self.meta["NATIVE_BINARY_MODE"], "755")
        self.assertEqual(self.meta["produced_by"], "operator_controlled_build_not_developer")
        self.assertNotIn("CONTROL_BUILD_REPRODUCES_CURRENT_BINARY", self.meta)
        self.assertEqual(self.meta["operator_ab_records_are_input_evidence_not_independent_verify"], "true")

    def test_08_owner_addendum_and_known_r5_r6_limits_are_recorded(self) -> None:
        self.assertEqual(
            self.meta["item_3j_authority"],
            "owner_addendum_P126_OPTION_A_DEFERRED_present_AMBIGUOUS_absent",
        )
        self.assertIn("door_ack_precedence", self.meta["R5"])
        self.assertIn("ABSENT_fail_closed", self.meta["R5"])
        self.assertIn("5_second_timeout_remains_fail_closed", self.meta["R6"])
        self.assertEqual(self.meta["P0_A"], "NOT_FIXED")
        self.assertEqual(self.meta["P0_B"], "NOT_FIXED")
        self.assertEqual(self.meta["ISSUE319"], "OPEN")
        self.assertEqual(
            self.meta["P126_ACTUAL_STATUS"],
            "rebuilt and qualified in repository, NOT deployed",
        )

    def test_09_p126_changes_only_defer_handler_and_state_overlay(self) -> None:
        timeout_name = "static gboolean\nr27_repeat_ack_timeout_cb(gpointer data)"
        handler_name = "static gboolean\nr27_handle_repeat_ack(guint16 request_id, const guint8 *body, guint body_len)"
        p125_timeout = self.p125_candidate.split(timeout_name, 1)[1].split(handler_name, 1)[0]
        p126_timeout = self.candidate.split(timeout_name, 1)[1].split(handler_name, 1)[0]
        self.assertEqual(p126_timeout, p125_timeout)
        self.assertEqual(self.meta["same_channel_non_ack_consumed"], "false")
        self.assertEqual(self.meta["refresh_ack_validator"], "p99_state_scoped_structural_ack")


if __name__ == "__main__":
    unittest.main()
