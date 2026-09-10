#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[1]
MEDIA = ROOT / "research" / "media" / "v1"
sys.path.insert(0, str(MEDIA))

from entrance_p101_offline_harness import ack_harness_source, rtp_harness_source
from entrance_p101_preactive_profile_gate_transform import report, transform


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
        return subprocess.run(
            [str(bin_path)],
            check=True,
            text=True,
            capture_output=True,
        )


ACK_TEST_LIB = r'''
static void ack_reset(void)
{
    failed = FALSE;
    v4_ctpp_channel_id = 0x1234u;
    memset(p78_rtpc_client_000a, 0, sizeof(p78_rtpc_client_000a));
    memset(p78_rtpc_client_001a, 0, sizeof(p78_rtpc_client_001a));
    p78_rtpc_client_000a_len = 44u;
    p78_rtpc_client_001a_len = 60u;
    pseudo_tcp = (gpointer)0x1;
    pseudotcp_open = TRUE;
    p12_tx_pending = FALSE;
    pseudotcp_graceful_stop_started = FALSE;
    p92_device_000a_observed = FALSE;
    p78_rtpc_client_000a_sent = FALSE;
    p78_rtpc_client_001a_sent = FALSE;
    p78_rtpc_stage = P78_RTPC_IDLE;
    p97_client_ack_000a_sent = FALSE;
    p97_client_ack_000a_sequence = 0;
    p97_wait_device_ack_000a = FALSE;
    p97_device_ack_000a_observed = FALSE;
    p97_client_001a_started = FALSE;
    p97_wait_device_ack_001a = FALSE;
    p97_device_ack_001a_observed = FALSE;
    p97_signaling_finished = FALSE;
    p101_harness_queue_calls = 0;
    p101_harness_flush_calls = 0;
    p101_harness_fail_calls = 0;
    p101_harness_timer_calls = 0;
    p101_harness_media_begin_calls = 0;
}

static void ack_valid(guint8 *body)
{
    memset(body, 0, 32u);
    write_le16(body + 0u, 0x1800u);
    memset(body + 8u, 0xff, 4u);
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


RTP_TEST_LIB = r'''
static void rtp_reset(void)
{
    failed = FALSE;
    loop = (gpointer)0x1;
    p101_harness_loop_quit_calls = 0;
    p101_harness_socket_calls = 0;
    p101_harness_sendto_calls = 0;
    p101_harness_sendto_result = -1;
    p91_media_rx_total = 0;
    p91_media_wrapper_len_match = 0;
    p91_media_inner_rtp_v2 = 0;
    p91_media_pt99 = 0;
    p91_media_pt8 = 0;
    p80_media_forwarding_enabled = FALSE;
    p99_preactive_media_demux_armed = FALSE;
    p99_preactive_media_packets = 0;
    p80_video_rtp_fd = -1;
    p80_audio_rtp_fd = -1;
    memset(&p80_video_rtp_target, 0, sizeof(p80_video_rtp_target));
    memset(&p80_audio_rtp_target, 0, sizeof(p80_audio_rtp_target));
    p80_video_target_ready = FALSE;
    p80_audio_target_ready = FALSE;
    p80_video_profile_seen = FALSE;
    p80_audio_profile_seen = FALSE;
    memset(p80_video_profile, 0, sizeof(p80_video_profile));
    memset(p80_audio_profile, 0, sizeof(p80_audio_profile));
    p80_video_rtp_packets = 0;
    p80_audio_rtp_packets = 0;
}

static void make_packet(guint8 *packet, guint8 payload_type, guint8 profile_seed)
{
    memset(packet, 0, 21u);
    packet[0] = profile_seed;
    packet[1] = (guint8)(profile_seed + 1u);
    packet[2] = 13u;
    packet[4] = (guint8)(profile_seed + 2u);
    packet[5] = (guint8)(profile_seed + 3u);
    packet[6] = (guint8)(profile_seed + 4u);
    packet[7] = (guint8)(profile_seed + 5u);
    packet[8] = 0x80u;
    packet[9] = payload_type;
    packet[20] = 0x55u;
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


class P101PreactiveProfileGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.candidate = transform(SOURCE.read_text(encoding="utf-8"))

    def _run_ack(self, main_body: str) -> subprocess.CompletedProcess[str]:
        return _compile_and_run(ack_harness_source(self.candidate, ACK_TEST_LIB + main_body))

    def _run_rtp(self, main_body: str) -> subprocess.CompletedProcess[str]:
        return _compile_and_run(rtp_harness_source(self.candidate, RTP_TEST_LIB + main_body))

    @unittest.skipUnless(CC, "cc compiler not available")
    def test_ack_valid_matching_gate_consumed(self) -> None:
        result = self._run_ack(r'''
int main(void) {
    guint8 body[32];
    ack_reset();
    ack_valid(body);
    p97_wait_device_ack_000a = TRUE;
    return expect(p97_handle_device_ack(v4_ctpp_channel_id, body, 32u) == TRUE, "consume") ||
        expect(p97_device_ack_000a_observed == TRUE, "observed") ||
        expect(p97_wait_device_ack_000a == FALSE, "gate");
}
''')
        self.assertIn("P80_DEVICE_ACK_000A_OBSERVED=PASS", result.stdout)

    @unittest.skipUnless(CC, "cc compiler not available")
    def test_ack_wrong_request_identity_not_consumed(self) -> None:
        self._run_ack(r'''
int main(void) {
    guint8 body[32];
    ack_reset();
    ack_valid(body);
    p97_wait_device_ack_000a = TRUE;
    return expect(p97_handle_device_ack((guint16)(v4_ctpp_channel_id + 1u), body, 32u) == FALSE, "not consumed") ||
        expect(p97_device_ack_000a_observed == FALSE, "not observed");
}
''')

    @unittest.skipUnless(CC, "cc compiler not available")
    def test_ack_wrong_body_lengths_not_consumed(self) -> None:
        self._run_ack(r'''
int main(void) {
    guint8 body[33];
    ack_reset();
    ack_valid(body);
    p97_wait_device_ack_000a = TRUE;
    if (expect(p97_handle_device_ack(v4_ctpp_channel_id, body, 31u) == FALSE, "len31"))
        return 1;
    if (expect(p97_device_ack_000a_observed == FALSE, "len31 observed"))
        return 1;
    p97_wait_device_ack_000a = TRUE;
    return expect(p97_handle_device_ack(v4_ctpp_channel_id, body, 33u) == FALSE, "len33") ||
        expect(p97_device_ack_000a_observed == FALSE, "len33 observed");
}
''')

    @unittest.skipUnless(CC, "cc compiler not available")
    def test_ack_wrong_opcode_not_consumed(self) -> None:
        self._run_ack(r'''
int main(void) {
    guint8 body[32];
    ack_reset();
    ack_valid(body);
    write_le16(body + 0u, 0x1801u);
    p97_wait_device_ack_000a = TRUE;
    return expect(p97_handle_device_ack(v4_ctpp_channel_id, body, 32u) == FALSE, "opcode");
}
''')

    @unittest.skipUnless(CC, "cc compiler not available")
    def test_ack_wrong_zero_structural_fields_not_consumed(self) -> None:
        self._run_ack(r'''
int main(void) {
    guint8 body[32];
    ack_reset();
    ack_valid(body);
    body[6] = 1u;
    p97_wait_device_ack_000a = TRUE;
    if (expect(p97_handle_device_ack(v4_ctpp_channel_id, body, 32u) == FALSE, "byte6"))
        return 1;
    ack_valid(body);
    body[7] = 1u;
    return expect(p97_handle_device_ack(v4_ctpp_channel_id, body, 32u) == FALSE, "byte7");
}
''')

    @unittest.skipUnless(CC, "cc compiler not available")
    def test_ack_wrong_ff_structural_fields_not_consumed(self) -> None:
        self._run_ack(r'''
int main(void) {
    guint8 body[32];
    guint i;
    for (i = 8u; i < 12u; i++) {
        ack_reset();
        ack_valid(body);
        body[i] = 0xfeu;
        p97_wait_device_ack_000a = TRUE;
        if (expect(p97_handle_device_ack(v4_ctpp_channel_id, body, 32u) == FALSE, "ff"))
            return 1;
    }
    return 0;
}
''')

    @unittest.skipUnless(CC, "cc compiler not available")
    def test_ack_valid_without_gate_not_consumed(self) -> None:
        self._run_ack(r'''
int main(void) {
    guint8 body[32];
    ack_reset();
    ack_valid(body);
    return expect(p97_handle_device_ack(v4_ctpp_channel_id, body, 32u) == FALSE, "no gate");
}
''')

    @unittest.skipUnless(CC, "cc compiler not available")
    def test_ack_duplicate_out_of_state_not_consumed(self) -> None:
        self._run_ack(r'''
int main(void) {
    guint8 body[32];
    ack_reset();
    ack_valid(body);
    p97_wait_device_ack_000a = TRUE;
    if (expect(p97_handle_device_ack(v4_ctpp_channel_id, body, 32u) == TRUE, "first"))
        return 1;
    return expect(p97_handle_device_ack(v4_ctpp_channel_id, body, 32u) == FALSE, "second") ||
        expect(p97_device_ack_000a_observed == TRUE, "stable");
}
''')

    @unittest.skipUnless(CC, "cc compiler not available")
    def test_ack_state_scope_ignores_capture_tail_relation(self) -> None:
        result = self._run_ack(r'''
int main(void) {
    guint8 body[32];
    ack_reset();
    ack_valid(body);
    memset(body + 12u, 0x11, 20u);
    memset(p78_rtpc_client_000a + 24u, 0x22, 20u);
    p97_wait_device_ack_000a = TRUE;
    return expect(p97_ack_matches_source(body, 32u, p78_rtpc_client_000a, p78_rtpc_client_000a_len) == FALSE, "tail false") ||
        expect(p97_handle_device_ack(v4_ctpp_channel_id, body, 32u) == TRUE, "accepted") ||
        expect(p97_device_ack_000a_observed == TRUE, "observed");
}
''')
        self.assertIn("P80_DEVICE_ACK_000A_TAIL_RELATION=NOT_MATCHED", result.stdout)

    @unittest.skipUnless(CC, "cc compiler not available")
    def test_media_before_arm_and_inactive_falls_through(self) -> None:
        self._run_rtp(r'''
int main(void) {
    guint8 packet[21];
    rtp_reset();
    make_packet(packet, 99u, 1u);
    return expect(p80_try_forward_wrapped_rtp(packet, 21u) == FALSE, "fallthrough");
}
''')

    @unittest.skipUnless(CC, "cc compiler not available")
    def test_media_malformed_wrapper_length_falls_through(self) -> None:
        self._run_rtp(r'''
int main(void) {
    guint8 packet[21];
    rtp_reset();
    make_packet(packet, 99u, 1u);
    packet[2] = 12u;
    p99_preactive_media_demux_armed = TRUE;
    return expect(p80_try_forward_wrapped_rtp(packet, 21u) == FALSE, "len");
}
''')

    @unittest.skipUnless(CC, "cc compiler not available")
    def test_media_truncated_inner_rtp_falls_through(self) -> None:
        self._run_rtp(r'''
int main(void) {
    guint8 packet[19];
    rtp_reset();
    memset(packet, 0, sizeof(packet));
    packet[2] = 11u;
    p99_preactive_media_demux_armed = TRUE;
    return expect(p80_try_forward_wrapped_rtp(packet, 19u) == FALSE, "truncated");
}
''')

    @unittest.skipUnless(CC, "cc compiler not available")
    def test_media_wrong_rtp_version_falls_through(self) -> None:
        self._run_rtp(r'''
int main(void) {
    guint8 packet[21];
    rtp_reset();
    make_packet(packet, 99u, 1u);
    packet[8] = 0x40u;
    p99_preactive_media_demux_armed = TRUE;
    return expect(p80_try_forward_wrapped_rtp(packet, 21u) == FALSE, "version");
}
''')

    @unittest.skipUnless(CC, "cc compiler not available")
    def test_media_unsupported_payload_type_falls_through(self) -> None:
        self._run_rtp(r'''
int main(void) {
    guint8 packet[21];
    rtp_reset();
    make_packet(packet, 96u, 1u);
    p99_preactive_media_demux_armed = TRUE;
    return expect(p80_try_forward_wrapped_rtp(packet, 21u) == FALSE, "pt");
}
''')

    @unittest.skipUnless(CC, "cc compiler not available")
    def test_media_valid_pt8_preactive_consumes_without_forward_or_counters(self) -> None:
        result = self._run_rtp(r'''
int main(void) {
    guint8 packet[21];
    rtp_reset();
    make_packet(packet, 8u, 3u);
    p99_preactive_media_demux_armed = TRUE;
    return expect(p80_try_forward_wrapped_rtp(packet, 21u) == TRUE, "consume") ||
        expect(p101_harness_sendto_calls == 0u, "sendto") ||
        expect(p101_harness_socket_calls == 0u, "socket") ||
        expect(p91_media_rx_total == 0u && p91_media_wrapper_len_match == 0u &&
               p91_media_inner_rtp_v2 == 0u && p91_media_pt99 == 0u && p91_media_pt8 == 0u &&
               p80_video_rtp_packets == 0u && p80_audio_rtp_packets == 0u, "counters");
}
''')
        self.assertEqual(result.stdout.count("P80_PREACTIVE_MEDIA_DEMUX=PASS"), 1)
        self.assertEqual(result.stdout.count("P80_PREACTIVE_MEDIA_PROFILE_ACCEPT=PASS"), 1)
        self.assertIn("P80_PREACTIVE_MEDIA_PAYLOAD_TYPE=8", result.stdout)

    @unittest.skipUnless(CC, "cc compiler not available")
    def test_media_valid_pt99_preactive_consumes_without_forward_or_counters(self) -> None:
        result = self._run_rtp(r'''
int main(void) {
    guint8 packet[21];
    rtp_reset();
    make_packet(packet, 99u, 5u);
    p99_preactive_media_demux_armed = TRUE;
    return expect(p80_try_forward_wrapped_rtp(packet, 21u) == TRUE, "consume") ||
        expect(p101_harness_sendto_calls == 0u, "sendto") ||
        expect(p101_harness_socket_calls == 0u, "socket") ||
        expect(p91_media_rx_total == 0u && p91_media_wrapper_len_match == 0u &&
               p91_media_inner_rtp_v2 == 0u && p91_media_pt99 == 0u && p91_media_pt8 == 0u &&
               p80_video_rtp_packets == 0u && p80_audio_rtp_packets == 0u, "counters");
}
''')
        self.assertEqual(result.stdout.count("P80_PREACTIVE_MEDIA_DEMUX=PASS"), 1)
        self.assertEqual(result.stdout.count("P80_PREACTIVE_MEDIA_PROFILE_ACCEPT=PASS"), 1)
        self.assertIn("P80_PREACTIVE_MEDIA_PAYLOAD_TYPE=99", result.stdout)

    @unittest.skipUnless(CC, "cc compiler not available")
    def test_media_preactive_pt99_profile_change_fails_closed(self) -> None:
        result = self._run_rtp(r'''
int main(void) {
    guint8 first[21], second[21];
    rtp_reset();
    make_packet(first, 99u, 7u);
    make_packet(second, 99u, 8u);
    p99_preactive_media_demux_armed = TRUE;
    if (expect(p80_try_forward_wrapped_rtp(first, 21u) == TRUE, "first"))
        return 1;
    return expect(p80_try_forward_wrapped_rtp(second, 21u) == TRUE, "second consumed") ||
        expect(failed == TRUE, "failed") ||
        expect(p101_harness_loop_quit_calls == 1u, "quit") ||
        expect(p101_harness_sendto_calls == 0u, "sendto");
}
''')
        self.assertIn("P80_WRAPPER_PROFILE_MISMATCH_STATE=PREACTIVE", result.stderr)

    @unittest.skipUnless(CC, "cc compiler not available")
    def test_media_audio_video_profiles_are_independent_and_fail_closed(self) -> None:
        result = self._run_rtp(r'''
int main(void) {
    guint8 v1[21], a1[21], v2[21], a2[21];
    rtp_reset();
    make_packet(v1, 99u, 9u);
    make_packet(a1, 8u, 21u);
    make_packet(v2, 99u, 10u);
    make_packet(a2, 8u, 22u);
    p99_preactive_media_demux_armed = TRUE;
    if (expect(p80_try_forward_wrapped_rtp(v1, 21u) == TRUE, "v1"))
        return 1;
    if (expect(p80_try_forward_wrapped_rtp(a1, 21u) == TRUE, "a1"))
        return 1;
    if (expect(p80_try_forward_wrapped_rtp(v2, 21u) == TRUE && failed == TRUE, "v2 fail"))
        return 1;
    failed = FALSE;
    return expect(p80_try_forward_wrapped_rtp(a2, 21u) == TRUE && failed == TRUE, "a2 fail") ||
        expect(p101_harness_sendto_calls == 0u, "sendto");
}
''')
        self.assertEqual(result.stderr.count("P80_WRAPPER_PROFILE_MISMATCH_STATE=PREACTIVE"), 2)

    @unittest.skipUnless(CC, "cc compiler not available")
    def test_media_active_path_still_forwards_pt99(self) -> None:
        self._run_rtp(r'''
int main(void) {
    guint8 packet[21];
    rtp_reset();
    make_packet(packet, 99u, 11u);
    p80_media_forwarding_enabled = TRUE;
    return expect(p80_try_forward_wrapped_rtp(packet, 21u) == TRUE, "forward") ||
        expect(p101_harness_socket_calls == 1u, "socket") ||
        expect(p101_harness_sendto_calls == 1u, "sendto") ||
        expect(p80_video_rtp_packets == 1u, "video count");
}
''')

    @unittest.skipUnless(CC, "cc compiler not available")
    def test_media_preactive_profile_carries_into_active_then_mismatch_fails(self) -> None:
        result = self._run_rtp(r'''
int main(void) {
    guint8 pre[21], active_ok[21], active_bad[21];
    rtp_reset();
    make_packet(pre, 99u, 13u);
    make_packet(active_ok, 99u, 13u);
    make_packet(active_bad, 99u, 14u);
    p99_preactive_media_demux_armed = TRUE;
    if (expect(p80_try_forward_wrapped_rtp(pre, 21u) == TRUE, "pre"))
        return 1;
    p80_media_forwarding_enabled = TRUE;
    if (expect(p80_try_forward_wrapped_rtp(active_ok, 21u) == TRUE, "active ok"))
        return 1;
    return expect(p101_harness_sendto_calls == 1u, "sendto once") ||
        expect(p80_try_forward_wrapped_rtp(active_bad, 21u) == TRUE, "bad consumed") ||
        expect(failed == TRUE, "failed") ||
        expect(p101_harness_sendto_calls == 1u, "no bad forward");
}
''')
        self.assertIn("P80_WRAPPER_PROFILE_MISMATCH_STATE=ACTIVE", result.stderr)

    def test_safety_no_door_entrypoint_or_tokens(self) -> None:
        for token in (
            "signal(SIGUSR1, v4_door_signal_handler);",
            "OPEN_DOOR",
            "open_door",
            "create_door_message",
        ):
            self.assertNotIn(token, self.candidate)

    def test_safety_exactly_one_ctpp_open_call(self) -> None:
        self.assertEqual(self.candidate.count("v4_queue_open_ctpp("), 2)

    def test_safety_no_retry_construct_added_by_p101(self) -> None:
        p100 = __import__("entrance_p100_p99_compile_order_transform").transform(
            SOURCE.read_text(encoding="utf-8")
        )
        added = "\n".join(
            line[1:]
            for line in __import__("difflib").unified_diff(
                p100.splitlines(), self.candidate.splitlines(), lineterm=""
            )
            if line.startswith("+") and not line.startswith("+++")
        )
        self.assertNotRegex(added, r"\b(while|for)\s*\(")
        self.assertNotIn("retry", added.lower())
        self.assertNotIn("p99_preactive_media_demux_armed = TRUE", added)

    def test_safety_p101_adds_no_literal_captured_constant(self) -> None:
        source = (MEDIA / "entrance_p101_preactive_profile_gate_transform.py").read_text(
            encoding="utf-8"
        )
        self.assertNotRegex(source, r"(?:static\s+)?(?:const\s+)?guint8\s+\w+\s*\[[^\]]*\]\s*=")
        self.assertNotRegex(source, r"b[\"']")
        self.assertNotIn("base64", source)
        self.assertIn("P80_PREACTIVE_MEDIA_PROFILE_ACCEPT=PASS", source)
        self.assertIn("P80_WRAPPER_PROFILE_MISMATCH_STATE=%s", source)

    def test_safety_profile_gate_order_inside_classifier(self) -> None:
        start = self.candidate.index("p80_try_forward_wrapped_rtp(const guint8 *packet, guint len)")
        end = self.candidate.index("/* === P80_HA_MEDIA_RTP_FORWARDING_END === */", start)
        body = self.candidate[start:end]
        self.assertLess(
            body.index("p80_profile_accept(packet, payload_type)"),
            body.index("if (!p99_active_forward) {"),
        )
        self.assertIn("P80_WRAPPER_PROFILE_MISMATCH_STATE=%s", body)

    def test_report_markers(self) -> None:
        text = report()
        for marker in (
            "P101_TRANSFORM=PASS",
            "P101_COMPOSES=P100",
            "P101_PREACTIVE_PROFILE_GATE=P80_PROFILE_ACCEPT_SHARED_BOTH_STATES",
            "P101_PREACTIVE_PROFILE_MISMATCH_FAIL_CLOSED=true",
            "P101_PREACTIVE_MEDIA_FORWARD=false",
            "P101_PREACTIVE_ACTIVE_COUNTERS_UNTOUCHED=true",
            "P101_AUTOMATIC_RETRY=false",
            "P101_SECOND_CTPP_OPEN=false",
            "DOOR_ACTION_SENT=false",
            "NETWORK_IO_PERFORMED=false",
            "CANDIDATE_EXECUTED=false",
        ):
            self.assertIn(marker, text)
        self.assertNotIn("P101_PROACTIVE_MEDIA_FORWARD=false", text)


if __name__ == "__main__":
    unittest.main()
