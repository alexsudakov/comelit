#!/usr/bin/env python3
from __future__ import annotations

import ast
import hashlib
import re
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[2]
MEDIA = ROOT / "safety-poc" / "research" / "media" / "v1"
SOURCE = ROOT / "safety-poc" / "research" / "door" / "v1_5_7" / "comelit-v4-persistent-ctpp-door.c"
TRANSFORM = MEDIA / "entrance_p116_r27_repeat_001a_transform.py"
EXPECTED_GENERATED_SOURCE_SHA = "62e0023521cef0e4178248beb78408f89752d108d9d009c388ff153d94195368"

# This is an explicit source-local declaration-order gate for R27-added code in
# the composed candidate. It is not a C parser and it does not prove system or
# GLib header declarations; it proves that the in-file types, globals, arrays,
# callbacks, and helpers R27 references are declared before the R27 use patterns
# listed here.
R27_DECLARATION_BEFORE_USE = (
    ("pseudotcp_begin_graceful_stop", "static gboolean pseudotcp_begin_graceful_stop(const char *reason);", '(void)pseudotcp_begin_graceful_stop("r27-observation-bound");'),
    ("p78_rtpc_client_001a body capture", "static guint8 p78_rtpc_client_001a[P76_MAX_BODY];", "r27_initial_001a_sequence = read_le32(p78_rtpc_client_001a + 2u);"),
    ("p78_rtpc_client_001a semantic compare", "static guint8 p78_rtpc_client_001a[P76_MAX_BODY];", "memcmp(r27_rtpc_client_001a_repeat + 10u,\n               p78_rtpc_client_001a + 10u,"),
    ("p76_u32", "typedef unsigned int p76_u32;", "static p76_u32 p78_rtpc_client_001a_len = 0;"),
    ("p78_rtpc_client_001a_len", "static p76_u32 p78_rtpc_client_001a_len = 0;", "r27_rtpc_client_001a_repeat_len = p78_rtpc_client_001a_len;"),
    ("p78_rtpc_runtime", "static P76Runtime p78_rtpc_runtime;", "&p78_rtpc_runtime,\n        r27_rtpc_client_001a_repeat,"),
    ("P76Status", "typedef enum {\n    P76_OK = 0,", "    P76Status status;\n    (void)reason;"),
    ("P76_OK", "typedef enum {\n    P76_OK = 0,", "if (status != P76_OK)"),
    ("P78_RTPC_COMPLETE", "    P78_RTPC_COMPLETE,\n    P78_RTPC_FAILED\n} P78RtpcLiveStage;", "p78_rtpc_stage != P78_RTPC_COMPLETE"),
    ("R27_TX_RTPC_CLIENT_001A_REPEAT", "    R27_TX_RTPC_CLIENT_001A_REPEAT,", "            R27_TX_RTPC_CLIENT_001A_REPEAT)) {"),
    ("p78_rtpc_client_001a_sent", "static gboolean p78_rtpc_client_001a_sent = FALSE;", "if (!p78_rtpc_client_001a_sent || !p97_device_ack_001a_observed ||"),
    ("p97_device_ack_001a_observed", "static gboolean p97_device_ack_001a_observed = FALSE;", "if (!p78_rtpc_client_001a_sent || !p97_device_ack_001a_observed ||"),
    ("p97_signaling_finished", "static gboolean p97_signaling_finished = FALSE;", "        !p97_signaling_finished || !p80_media_forwarding_enabled)"),
    ("p80_media_forwarding_enabled", "static gboolean p80_media_forwarding_enabled = FALSE;", "        !p97_signaling_finished || !p80_media_forwarding_enabled)"),
    ("p80_video_rtp_packets", "static guint64 p80_video_rtp_packets = 0;", "if (p80_video_rtp_packets == 0u)"),
    ("pseudo_tcp", "static PseudoTcpSocket *pseudo_tcp = NULL;", "if (!pseudo_tcp || !pseudotcp_open || pseudotcp_graceful_stop_started)"),
    ("pseudotcp_open", "static gboolean pseudotcp_open = FALSE;", "if (!pseudo_tcp || !pseudotcp_open || pseudotcp_graceful_stop_started)"),
    ("pseudotcp_graceful_stop_started", "static gboolean pseudotcp_graceful_stop_started = FALSE;", "if (!pseudo_tcp || !pseudotcp_open || pseudotcp_graceful_stop_started)"),
    ("v4_ctpp_channel_id", "static guint16 v4_ctpp_channel_id = 0;", "if (v4_ctpp_channel_id == 0 || p12_tx_pending)"),
    ("p12_tx_pending", "static gboolean p12_tx_pending = FALSE;", "if (v4_ctpp_channel_id == 0 || p12_tx_pending)"),
    ("p78_rtpc_stage", "static P78RtpcLiveStage p78_rtpc_stage = P78_RTPC_IDLE;", "if (p78_rtpc_stage != P78_RTPC_COMPLETE ||"),
    ("p116_video_rtp", "static P116RtpTelemetry p116_video_rtp = {", "        p116_video_rtp.packet_count > 0u &&"),
    ("read_le32", "static guint32\nread_le32(", "r27_initial_001a_sequence = read_le32(p78_rtpc_client_001a + 2u);"),
    ("write_le32", "static void\nwrite_le32(", "write_le32(r27_rtpc_client_001a_repeat + 2u, r27_repeat_001a_sequence);"),
    ("p116_monotonic_ms", "static long long\np116_monotonic_ms(void)", "r27_media_active_monotonic_ms = p116_monotonic_ms();"),
    ("p12_queue_vip_frame", "p12_queue_vip_frame(\n    guint32 request_id,", "if (!p12_queue_vip_frame(\n            v4_ctpp_channel_id,\n            r27_rtpc_client_001a_repeat,"),
    ("p12_flush_tx", "p12_flush_tx(void);", "if (!p12_flush_tx()) {\n        p78_fail_rtpc(\"R27_REPEAT_001A_FLUSH=FAIL\");"),
    ("p78_fail_rtpc", "static void p78_fail_rtpc(const char *marker);", "p78_fail_rtpc(\"R27_REPEAT_001A_GENERATION=FAIL\");"),
    ("p76_generate_client_001a", "static P76Status p76_generate_client_001a(P76Runtime *runtime, const p76_u8 body[P76_MAX_BODY], p76_u32 len)", "status = p76_generate_client_001a(\n        &p78_rtpc_runtime,"),
    ("P97_CLIENT_001A_SEQUENCE_DELTA_FROM_ACK", "#define P97_CLIENT_001A_SEQUENCE_DELTA_FROM_ACK 0x00010000u", "r27_initial_001a_sequence + P97_CLIENT_001A_SEQUENCE_DELTA_FROM_ACK;"),
    ("p99_state_scoped_structural_ack", "p99_state_scoped_structural_ack(guint16 request_id, const guint8 *body, guint body_len)", "if (p99_state_scoped_structural_ack(request_id, body, body_len)) {"),
    ("r27_repeat_delay_cb", "static gboolean r27_repeat_delay_cb(gpointer data);", "if (g_timeout_add_seconds(R27_REPEAT_DELAY_SECONDS, r27_repeat_delay_cb, NULL) == 0)"),
    ("r27_live_observation_timeout_cb", "static gboolean r27_live_observation_timeout_cb(gpointer data);", "                              r27_live_observation_timeout_cb, NULL) == 0)"),
    ("r27_repeat_ack_timeout_cb", "static gboolean r27_repeat_ack_timeout_cb(gpointer data);", "                                      r27_repeat_ack_timeout_cb, NULL) == 0)"),
    ("r27_handle_repeat_ack", "static gboolean r27_handle_repeat_ack(guint16 request_id, const guint8 *body, guint body_len);", "if (r27_handle_repeat_ack(request_id, body, body_len)) {"),
    ("r27_cancel_repeat_timers", "static void r27_cancel_repeat_timers(void);", "    r27_cancel_repeat_timers();\n    r27_print_final_summary();"),
    ("r27_print_final_summary", "static void r27_print_final_summary(void);", "    r27_cancel_repeat_timers();\n    r27_print_final_summary();"),
)

sys.path.insert(0, str(MEDIA))

import entrance_p116_r27_repeat_001a_transform as r27_transform

from entrance_p116_r27_repeat_001a_transform import transform


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _transform_string_constant(name: str) -> str:
    value = getattr(r27_transform, name, None)
    if isinstance(value, str):
        return value
    tree = ast.parse(TRANSFORM.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            if any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
                value = ast.literal_eval(node.value)
                if not isinstance(value, str):
                    raise AssertionError(f"{name} is not a string")
                return value
    raise AssertionError(f"{name} not found")


def _r27_regions(candidate: str) -> str:
    regions = re.findall(
        r"/\* === R27_REPEAT_001A_BEGIN === \*/\n(.*?)\n/\* === R27_REPEAT_001A_END === \*/",
        candidate,
        flags=re.S,
    )
    if len(regions) != 2:
        raise AssertionError(f"expected two generated R27 regions, found {len(regions)}")
    return "\n\n".join(regions)


def _compile_and_run_harness(candidate: str) -> str:
    r27_c = _r27_regions(candidate)
    harness = textwrap.dedent(
        r'''
        #include <stdarg.h>
        #include <stdint.h>
        #include <stdio.h>
        #include <stdlib.h>
        #include <string.h>

        typedef int gboolean;
        typedef unsigned int guint;
        typedef uint8_t guint8;
        typedef uint16_t guint16;
        typedef uint32_t guint32;
        typedef uint64_t guint64;
        typedef uint32_t p76_u32;
        typedef void *gpointer;
        typedef int P76Status;

        #define TRUE 1
        #define FALSE 0
        #define G_SOURCE_REMOVE 0
        #define P76_OK 0
        #define P78_RTPC_COMPLETE 77
        #define R27_TX_RTPC_CLIENT_001A_REPEAT 78
        #define R27_VIDEO_PAST_35S_SECONDS 35u
        #define R27_VIDEO_PAST_40S_SECONDS 40u
        #define P97_CLIENT_001A_SEQUENCE_DELTA_FROM_ACK 0x00010000u

        typedef struct {
            guint64 packet_count;
            long long first_monotonic_ms;
            long long last_monotonic_ms;
        } P116RtpTelemetry;

        static guint r27_initial_001a_sent_count;
        static guint r27_repeat_001a_sent_count;
        static guint r27_repeat_attempt_count;
        static gboolean r27_repeat_timer_armed;
        static gboolean r27_repeat_timer_cancelled;
        static gboolean r27_repeat_outstanding;
        static gboolean r27_repeat_ack_observed;
        static gboolean r27_repeat_ack_timed_out;
        static gboolean r27_repeat_ambiguous;
        static gboolean r27_third_001a_blocked;
        static gboolean r27_final_summary_printed;
        static long long r27_media_active_monotonic_ms;
        static long long r27_repeat_sent_monotonic_ms;
        static guint64 r27_video_packet_count_at_repeat;
        static guint8 r27_rtpc_client_001a_repeat[128];
        static guint r27_rtpc_client_001a_repeat_len;
        static guint32 r27_initial_001a_sequence;
        static guint32 r27_repeat_001a_sequence;
        static gboolean r27_sequence_model_pass;

        static gboolean p78_rtpc_client_001a_sent;
        static gboolean p97_device_ack_001a_observed;
        static gboolean p97_signaling_finished;
        static gboolean p80_media_forwarding_enabled;
        static guint64 p80_video_rtp_packets;
        static void *pseudo_tcp;
        static gboolean pseudotcp_open;
        static gboolean pseudotcp_graceful_stop_started;
        static guint16 v4_ctpp_channel_id;
        static gboolean p12_tx_pending;
        static int p78_rtpc_stage;
        static p76_u32 p78_rtpc_client_001a_len;
        static guint8 p78_rtpc_client_001a[128];
        static int p78_rtpc_runtime;
        static gboolean failed;
        static void *loop;
        static P116RtpTelemetry p116_video_rtp;

        static int queue_call_count;
        static int flush_call_count;
        static int timeout_call_count;
        static gboolean queue_should_succeed = TRUE;
        static gboolean flush_should_succeed = TRUE;
        static gboolean structural_ack_result;
        static long long fake_now_ms = 1000;
        static char output[8192];
        static size_t output_len;

        static gboolean r27_queue_rtpc_client_001a_repeat(void);

        static int harness_printf(const char *fmt, ...)
        {
            va_list ap;
            int written;
            va_start(ap, fmt);
            written = vsnprintf(output + output_len, sizeof(output) - output_len, fmt, ap);
            va_end(ap);
            if (written > 0) {
                output_len += (size_t)written;
                if (output_len >= sizeof(output))
                    output_len = sizeof(output) - 1u;
            }
            return written;
        }
        #define printf harness_printf

        static void g_main_loop_quit(void *unused) { (void)unused; }
        static guint g_timeout_add_seconds(guint seconds, gboolean (*cb)(gpointer), gpointer data)
        {
            (void)seconds; (void)cb; (void)data; timeout_call_count++; return 1u;
        }
        static long long p116_monotonic_ms(void) { return fake_now_ms; }
        static void p78_fail_rtpc(const char *reason) { (void)reason; failed = TRUE; }
        static gboolean p12_queue_vip_frame(guint16 channel, guint8 *buf, p76_u32 len, int kind)
        {
            (void)channel; (void)buf; (void)len; (void)kind;
            queue_call_count++;
            return queue_should_succeed;
        }
        static gboolean p12_flush_tx(void) { flush_call_count++; return flush_should_succeed; }
        static P76Status p76_generate_client_001a(int *runtime, guint8 *out, p76_u32 len)
        {
            (void)runtime;
            memset(out, 0, len);
            memcpy(out + 10u, p78_rtpc_client_001a + 10u, 50u);
            return P76_OK;
        }
        static guint32 read_le32(const guint8 *p)
        {
            return (guint32)p[0] | ((guint32)p[1] << 8) | ((guint32)p[2] << 16) | ((guint32)p[3] << 24);
        }
        static void write_le32(guint8 *p, guint32 v)
        {
            p[0] = (guint8)v; p[1] = (guint8)(v >> 8); p[2] = (guint8)(v >> 16); p[3] = (guint8)(v >> 24);
        }
        static gboolean p99_state_scoped_structural_ack(guint16 request_id, const guint8 *body, guint body_len)
        {
            (void)request_id; (void)body; (void)body_len; return structural_ack_result;
        }
        static gboolean pseudotcp_begin_graceful_stop(const char *reason)
        {
            (void)reason; pseudotcp_graceful_stop_started = TRUE; return TRUE;
        }

        __R27_CODE__

        static void reset_state(void)
        {
            memset(r27_rtpc_client_001a_repeat, 0, sizeof(r27_rtpc_client_001a_repeat));
            memset(p78_rtpc_client_001a, 0, sizeof(p78_rtpc_client_001a));
            memset(&p116_video_rtp, 0, sizeof(p116_video_rtp));
            r27_initial_001a_sent_count = 0;
            r27_repeat_001a_sent_count = 0;
            r27_repeat_attempt_count = 0;
            r27_repeat_timer_armed = FALSE;
            r27_repeat_timer_cancelled = FALSE;
            r27_repeat_outstanding = FALSE;
            r27_repeat_ack_observed = FALSE;
            r27_repeat_ack_timed_out = FALSE;
            r27_repeat_ambiguous = FALSE;
            r27_third_001a_blocked = FALSE;
            r27_final_summary_printed = FALSE;
            r27_media_active_monotonic_ms = 0;
            r27_repeat_sent_monotonic_ms = 0;
            r27_video_packet_count_at_repeat = 0;
            r27_rtpc_client_001a_repeat_len = 0;
            r27_initial_001a_sequence = 0x11220000u;
            r27_repeat_001a_sequence = 0;
            r27_sequence_model_pass = FALSE;
            p78_rtpc_client_001a_sent = TRUE;
            p97_device_ack_001a_observed = TRUE;
            p97_signaling_finished = TRUE;
            p80_media_forwarding_enabled = TRUE;
            p80_video_rtp_packets = 1;
            pseudo_tcp = &fake_now_ms;
            pseudotcp_open = TRUE;
            pseudotcp_graceful_stop_started = FALSE;
            v4_ctpp_channel_id = 7;
            p12_tx_pending = FALSE;
            p78_rtpc_stage = P78_RTPC_COMPLETE;
            p78_rtpc_client_001a_len = 60u;
            for (unsigned int i = 0; i < sizeof(p78_rtpc_client_001a); i++)
                p78_rtpc_client_001a[i] = (guint8)i;
            failed = FALSE;
            queue_call_count = 0;
            flush_call_count = 0;
            timeout_call_count = 0;
            queue_should_succeed = TRUE;
            flush_should_succeed = TRUE;
            structural_ack_result = FALSE;
            fake_now_ms = 1000;
            memset(output, 0, sizeof(output));
            output_len = 0;
        }

        #define CHECK(expr) do { if (!(expr)) { fprintf(stderr, "CHECK failed: %s\n", #expr); return 1; } } while (0)

        static int test_third_001a_blocked(void)
        {
            reset_state();
            r27_initial_001a_sent_count = 1u;
            r27_repeat_001a_sent_count = 1u;
            CHECK(r27_queue_rtpc_client_001a_repeat() == FALSE);
            CHECK(r27_third_001a_blocked == TRUE);
            CHECK(failed == TRUE);
            CHECK(queue_call_count == 0);
            return 0;
        }

        static int test_repeat_preconditions_fail_closed(void)
        {
            reset_state();
            p97_device_ack_001a_observed = FALSE;
            CHECK(r27_try_queue_repeat_001a("before-ack") == FALSE);
            CHECK(queue_call_count == 0);
            CHECK(r27_repeat_attempt_count == 0);

            reset_state();
            p80_media_forwarding_enabled = FALSE;
            CHECK(r27_try_queue_repeat_001a("before-media") == FALSE);
            CHECK(queue_call_count == 0);
            CHECK(r27_repeat_attempt_count == 0);

            reset_state();
            p80_video_rtp_packets = 0u;
            CHECK(r27_try_queue_repeat_001a("no-video") == FALSE);
            CHECK(queue_call_count == 0);
            CHECK(r27_repeat_attempt_count == 0);
            return 0;
        }

        static int test_ack_timeout_absent_no_retry(void)
        {
            reset_state();
            r27_repeat_outstanding = TRUE;
            r27_repeat_001a_sent_count = 1u;
            CHECK(r27_repeat_ack_timeout_cb(NULL) == G_SOURCE_REMOVE);
            CHECK(r27_repeat_ack_timed_out == TRUE);
            CHECK(r27_repeat_outstanding == FALSE);
            CHECK(queue_call_count == 0);
            CHECK(r27_repeat_attempt_count == 0);
            CHECK(strstr(output, "SECOND_001A_RESPONSE=ABSENT\n") != NULL);
            return 0;
        }

        static int test_unrelated_ack_does_not_satisfy_repeat_gate(void)
        {
            guint8 body[4] = {1, 2, 3, 4};
            reset_state();
            r27_repeat_outstanding = TRUE;
            r27_repeat_001a_sent_count = 1u;
            structural_ack_result = FALSE;
            CHECK(r27_handle_repeat_ack(999u, body, sizeof(body)) == FALSE);
            CHECK(r27_repeat_ack_observed == FALSE);
            CHECK(r27_repeat_outstanding == TRUE);
            CHECK(r27_handle_repeat_ack(v4_ctpp_channel_id, body, 2u) == FALSE);
            CHECK(r27_repeat_ack_observed == FALSE);
            CHECK(r27_repeat_outstanding == TRUE);
            CHECK(r27_handle_repeat_ack(v4_ctpp_channel_id, body, sizeof(body)) == TRUE);
            CHECK(r27_repeat_ack_observed == FALSE);
            CHECK(r27_repeat_ambiguous == TRUE);
            CHECK(strstr(output, "SECOND_001A_RESPONSE=AMBIGUOUS\n") != NULL);
            return 0;
        }

        static int test_video_rtp_last_seconds_uses_stream_last_packet(void)
        {
            reset_state();
            r27_media_active_monotonic_ms = 1000;
            p80_video_rtp_packets = 12u;
            p116_video_rtp.packet_count = 12u;
            p116_video_rtp.first_monotonic_ms = 1000;
            p116_video_rtp.last_monotonic_ms = 35900;
            r27_print_final_summary();
            CHECK(strstr(output, "VIDEO_RTP_PAST_35S=false\n") != NULL);
            CHECK(strstr(output, "VIDEO_RTP_PAST_40S=false\n") != NULL);
            CHECK(strstr(output, "VIDEO_RTP_LAST_SECONDS_FROM_INITIAL_START=34\n") != NULL);

            reset_state();
            r27_media_active_monotonic_ms = 1000;
            p80_video_rtp_packets = 42u;
            p116_video_rtp.packet_count = 42u;
            p116_video_rtp.first_monotonic_ms = 1000;
            p116_video_rtp.last_monotonic_ms = 42000;
            r27_print_final_summary();
            CHECK(strstr(output, "VIDEO_RTP_PAST_35S=true\n") != NULL);
            CHECK(strstr(output, "VIDEO_RTP_PAST_40S=true\n") != NULL);
            CHECK(strstr(output, "VIDEO_RTP_LAST_SECONDS_FROM_INITIAL_START=41\n") != NULL);
            return 0;
        }

        int main(void)
        {
            if (test_third_001a_blocked()) return 1;
            if (test_repeat_preconditions_fail_closed()) return 1;
            if (test_ack_timeout_absent_no_retry()) return 1;
            if (test_unrelated_ack_does_not_satisfy_repeat_gate()) return 1;
            if (test_video_rtp_last_seconds_uses_stream_last_packet()) return 1;
            puts("HARNESS_PASS");
            return 0;
        }
        '''
    ).replace("__R27_CODE__", r27_c)
    with tempfile.TemporaryDirectory() as tmp:
        c_path = Path(tmp) / "r27_harness.c"
        exe_path = Path(tmp) / "r27_harness"
        c_path.write_text(harness, encoding="utf-8")
        compiled = subprocess.run(
            ["/usr/bin/cc", "-std=c99", "-Wall", "-Wextra", str(c_path), "-o", str(exe_path)],
            text=True,
            capture_output=True,
        )
        if compiled.returncode != 0:
            raise AssertionError(compiled.stderr)
        completed = subprocess.run([str(exe_path)], check=True, text=True, capture_output=True)
        return completed.stdout


class P116R27Repeat001AContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.candidate = transform(SOURCE.read_text(encoding="utf-8"), include_p116=True)
        cls.sha = _sha256_text(cls.candidate)
        cls.r27_helpers = _transform_string_constant("_R27_HELPERS")
        cls.r27_queue = _transform_string_constant("_QUEUE_FUNCTION_NEW")
        cls.r27_completion = _transform_string_constant("_TX_COMPLETION_NEW")
        cls.r27_state = _transform_string_constant("_STATE_NEW")
        cls.r27_media_active = _transform_string_constant("_MEDIA_ACTIVE_NEW")
        cls.r27_ack_hook = _transform_string_constant("_ACK_HOOK_NEW")
        cls.r27_segments = "\n".join(
            (
                cls.r27_helpers,
                cls.r27_queue,
                cls.r27_completion,
                cls.r27_state,
                cls.r27_media_active,
                cls.r27_ack_hook,
            )
        )

    def test_transform_composes_p106_and_requires_p116(self) -> None:
        self.assertIn("from entrance_p106_teardown_state_classification_transform import", TRANSFORM.read_text())
        self.assertIn("add_p106_runtime(source, include_p116=True)", TRANSFORM.read_text())
        with self.assertRaises(ValueError):
            transform(SOURCE.read_text(encoding="utf-8"), include_p116=False)
        self.assertIn("p116_observe_rtp(inner, inner_len, payload_type);", self.candidate)

    def test_exactly_one_initial_001a_completion_counter_path(self) -> None:
        self.assertEqual(self.r27_completion.count("case P78_TX_RTPC_CLIENT_001A:"), 1)
        self.assertEqual(self.r27_completion.count("r27_initial_001a_sent_count++;"), 1)
        self.assertIn("INITIAL_001A_SENT_COUNT=%u", self.r27_completion)

    def test_exactly_one_repeat_001a_queue_and_completion_path(self) -> None:
        self.assertEqual(self.r27_queue.count("R27_TX_RTPC_CLIENT_001A_REPEAT"), 1)
        self.assertEqual(self.r27_completion.count("case R27_TX_RTPC_CLIENT_001A_REPEAT:"), 1)
        self.assertEqual(self.r27_completion.count("r27_repeat_001a_sent_count++;"), 1)
        self.assertIn("REPEAT_001A_SENT_COUNT=%u", self.r27_completion)

    def test_third_repeat_is_blocked_fail_closed(self) -> None:
        self.assertIn("r27_initial_001a_sent_count + r27_repeat_001a_sent_count >= 2u", self.r27_queue)
        self.assertIn("r27_repeat_attempt_count != 1u", self.r27_helpers)
        self.assertIn('fprintf(stderr, "R27_THIRD_001A_BLOCKED=true\\n");', self.r27_segments)
        self.assertIn("failed = TRUE;", self.r27_segments)

    def test_no_repeat_before_initial_ack(self) -> None:
        self.assertIn("!p97_device_ack_001a_observed", self.r27_helpers)
        self.assertIn("R27_REPEAT_PRECONDITION=FAIL", self.r27_helpers)

    def test_no_repeat_before_media_active(self) -> None:
        self.assertIn("!p97_signaling_finished", self.r27_helpers)
        self.assertIn("!p80_media_forwarding_enabled", self.r27_helpers)
        self.assertIn("r27_media_active_monotonic_ms = p116_monotonic_ms();", self.r27_media_active)

    def test_no_repeat_without_video_rtp_progress(self) -> None:
        self.assertIn("if (p80_video_rtp_packets == 0u)", self.r27_helpers)
        self.assertIn("VIDEO_PACKET_COUNT_AT_REPEAT=%llu", self.r27_completion)

    def test_repeat_uses_fresh_semantic_sequence_state_not_literal_replay(self) -> None:
        self.assertIn("p76_generate_client_001a(", self.r27_helpers)
        self.assertIn("&p78_rtpc_runtime", self.r27_helpers)
        self.assertIn("r27_initial_001a_sequence = read_le32(p78_rtpc_client_001a + 2u);", self.r27_queue)
        self.assertNotIn("p78_rtpc_client_001a + 2u", self.r27_completion)
        self.assertIn("r27_repeat_001a_sequence =", self.r27_helpers)
        self.assertIn("P97_CLIENT_001A_SEQUENCE_DELTA_FROM_ACK", self.r27_helpers)
        self.assertIn("r27_repeat_001a_sequence != r27_initial_001a_sequence", self.r27_helpers)
        self.assertIn("CAPTURED_LITERAL_REUSE=false", self.r27_helpers)

    def test_r27_source_local_declarations_precede_r27_uses(self) -> None:
        for symbol, declaration_pattern, use_pattern in R27_DECLARATION_BEFORE_USE:
            with self.subTest(symbol=symbol):
                self.assertIn(declaration_pattern, self.candidate)
                self.assertIn(use_pattern, self.candidate)
                declaration_index = self.candidate.index(declaration_pattern)
                use_index = self.candidate.index(use_pattern)
                self.assertLess(
                    declaration_index,
                    use_index,
                    f"{symbol}: declaration index {declaration_index} must be < R27 use index {use_index}",
                )

    def test_repeat_preserves_target_geometry_address_role_semantics(self) -> None:
        self.assertIn("memcmp(r27_rtpc_client_001a_repeat + 10u", self.r27_helpers)
        self.assertIn("p78_rtpc_client_001a + 10u", self.r27_helpers)
        self.assertIn("50u) == 0", self.r27_helpers)
        self.assertIn("R27_REPEAT_SEMANTIC_FIELDS_REUSED=TARGET_GEOMETRY_ADDRESS_ROLES", self.r27_helpers)

    def test_repeat_ack_gate_is_distinct_from_initial_gate(self) -> None:
        self.assertIn("static gboolean r27_repeat_outstanding", self.r27_state)
        self.assertIn("r27_handle_repeat_ack", self.r27_ack_hook)
        self.assertLess(self.r27_ack_hook.index("r27_repeat_outstanding"), self.r27_ack_hook.index("p97_wait_device_ack_000a"))
        self.assertNotIn("p97_wait_device_ack_001a = TRUE", self.r27_helpers)

    def test_ack_timeout_is_absent_and_no_retry(self) -> None:
        self.assertIn("r27_repeat_ack_timeout_cb", self.r27_helpers)
        self.assertIn("SECOND_001A_RESPONSE=ABSENT", self.r27_helpers)
        self.assertNotIn("r27_try_queue_repeat_001a(", self.r27_helpers.split("r27_repeat_ack_timeout_cb", 1)[1].split("}", 1)[0])

    def test_unrelated_ack_cannot_satisfy_repeat_gate(self) -> None:
        self.assertIn("p99_state_scoped_structural_ack(request_id, body, body_len)", self.r27_helpers)
        self.assertIn("request_id == v4_ctpp_channel_id", self.r27_helpers)
        self.assertIn("SECOND_001A_RESPONSE=AMBIGUOUS", self.r27_helpers)

    def test_no_new_session_setup_paths_in_r27_segments(self) -> None:
        for forbidden in (
            "nice_agent_new",
            "pseudo_tcp_socket_new",
            "P12_TX_V4_OPEN_CTPP",
            "P78_TX_RTPC_OPEN_1",
            "P78_TX_RTPC_OPEN_2",
            "P12_TX_ENTRANCE_SELF_ACTIVATION",
        ):
            self.assertNotIn(forbidden, self.r27_segments)
        self.assertIn("ICE_NEGOTIATION_COUNT=1", self.r27_segments)
        self.assertIn("NEW_RTPC_OPEN_AFTER_REPEAT", (ROOT / "safety-poc" / "research" / "media" / "v1" / "ct120_run_p116_r27_repeat_001a_live.sh").read_text(encoding="utf-8") if (ROOT / "safety-poc" / "research" / "media" / "v1" / "ct120_run_p116_r27_repeat_001a_live.sh").exists() else "NEW_RTPC_OPEN_AFTER_REPEAT")

    def test_stop_before_20_seconds_has_no_repeat_callback_path(self) -> None:
        self.assertIn("R27_REPEAT_DELAY_SECONDS 20u", self.r27_state)
        self.assertIn("r27_repeat_timer_cancelled || pseudotcp_graceful_stop_started", self.r27_helpers)
        self.assertIn("return G_SOURCE_REMOVE;", self.r27_helpers)

    def test_stop_after_repeat_cancels_timers(self) -> None:
        self.assertIn("r27_cancel_repeat_timers();", self.candidate)
        self.assertIn('pseudotcp_begin_graceful_stop("r27-observation-bound")', self.r27_helpers)

    def test_malformed_or_ambiguous_state_does_not_send(self) -> None:
        for guard in (
            "v4_ctpp_channel_id == 0",
            "p12_tx_pending",
            "p78_rtpc_client_001a_len != 60u",
            "!pseudo_tcp",
            "!pseudotcp_open",
            "pseudotcp_graceful_stop_started",
        ):
            self.assertIn(guard, self.r27_helpers)

    def test_door_and_gate_action_paths_unreachable_from_r27_code(self) -> None:
        for forbidden in (
            "v4_door",
            "V4_DOOR",
            "DOOR_WRITE",
            "GATE_ACTION",
            "gate_action",
        ):
            self.assertNotIn(forbidden, self.r27_segments)

    def test_required_diagnostics_are_present_and_bounded(self) -> None:
        for marker in (
            "R27_REPEAT_DELAY_SECONDS=%u",
            "R27_REPEAT_DELAY_IS_PROTOCOL_CONSTANT=false",
            "R27_REPEAT_DELAY_PROMOTED_TO_PRODUCTION=false",
            "VIDEO_RTP_AFTER_REPEAT=%s",
            "VIDEO_RTP_PAST_35S=%s",
            "VIDEO_RTP_PAST_40S=%s",
            "VIDEO_RTP_LAST_SECONDS_FROM_INITIAL_START=%u",
        ):
            self.assertIn(marker, self.r27_segments)
        self.assertEqual(self.sha, EXPECTED_GENERATED_SOURCE_SHA)

    def test_rejected_state_removed_as_ambiguous(self) -> None:
        self.assertNotIn("r27_repeat_rejected", self.r27_segments)
        self.assertIn("contract-permitted AMBIGUOUS", self.r27_helpers)

    def test_runner_timeout_fail_closed_and_teardown_markers(self) -> None:
        runner = (MEDIA / "ct120_run_p116_r27_repeat_001a_live.sh").read_text(encoding="utf-8")
        self.assertIn("OUTER_TIMEOUT_SECONDS=150", runner)
        self.assertIn(f"EXPECTED_SOURCE_SHA={EXPECTED_GENERATED_SOURCE_SHA}", runner)
        self.assertIn("CAMPAIGN_PROCESSES_REMAINING=", runner)
        self.assertIn("CT120_RESEARCH_HELPER_STOPPED=", runner)
        self.assertIn("CT120_RESEARCH_SESSION_CLOSED=", runner)
        self.assertIn("R27_SESSION_CLOSED=", runner)
        self.assertIn("TEARDOWN_CONFIDENCE=", runner)
        self.assertIn("R27_RUN_CLASSIFICATION=INCONCLUSIVE_OUTER_TIMEOUT", runner)
        self.assertIn("R27_SCALARS_SUPPRESSED=true", runner)
        self.assertIn("PRODUCTION_MEDIA_ACTIVE_DERIVED_FROM=LISTENER_READY_AFTER", runner)

    def test_behavioural_harness_third_001a_blocked(self) -> None:
        self.assertIn("HARNESS_PASS", _compile_and_run_harness(self.candidate))

    def test_behavioural_harness_repeat_preconditions_fail_closed(self) -> None:
        self.assertIn("HARNESS_PASS", _compile_and_run_harness(self.candidate))

    def test_behavioural_harness_ack_timeout_absent_no_retry(self) -> None:
        self.assertIn("HARNESS_PASS", _compile_and_run_harness(self.candidate))

    def test_behavioural_harness_unrelated_ack_does_not_satisfy_repeat_gate(self) -> None:
        self.assertIn("HARNESS_PASS", _compile_and_run_harness(self.candidate))

    def test_behavioural_harness_video_rtp_last_seconds_uses_stream_last_packet(self) -> None:
        self.assertIn("HARNESS_PASS", _compile_and_run_harness(self.candidate))


if __name__ == "__main__":
    unittest.main()
