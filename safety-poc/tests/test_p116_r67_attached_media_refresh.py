#!/usr/bin/env python3
"""P116/R67 attached-media refresh lifecycle contract tests."""

from __future__ import annotations

import hashlib
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
MEDIA = ROOT / "research" / "media" / "v1"
SOURCE = ROOT / "research" / "door" / "v1_5_7" / "comelit-v4-persistent-ctpp-door.c"

sys.path.insert(0, str(MEDIA))

import entrance_p116_r66_call_time_door_transform as r66  # noqa: E402
import entrance_p116_r67_attached_media_refresh_transform as r67  # noqa: E402


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _extract(text: str, begin: str, end: str) -> str:
    return begin + text.split(begin, 1)[1].split(end, 1)[0] + end


def _markers(stdout: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in stdout.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            out[key] = value
    return out


HARNESS = r'''
static guint g_timer_adds = 0u;
static guint g_last_timer_seconds = 0u;
static gboolean (*g_timer_cb)(gpointer data) = NULL;
static unsigned char g_last_packet[128];
static guint g_last_packet_len = 0u;
static P12TxKind g_last_kind = P12_TX_NONE;
static guint g_queued_count = 0u;

static guint g_p2p_start_count = 0u;
static guint g_ice_start_count = 0u;
static guint g_pseudotcp_start_count = 0u;
static guint g_ctpp_start_count = 0u;
static guint g_rtpc_start_count = 0u;

static guint
g_timeout_add_seconds(guint seconds, gboolean (*cb)(gpointer data), gpointer data)
{
    (void)data;
    g_timer_adds++;
    g_last_timer_seconds = seconds;
    g_timer_cb = cb;
    return g_timer_adds;
}

static void reset_world(void)
{
    memset(&g_r35_session, 0, sizeof(g_r35_session));
    g_r35_session.call_ctp_valid = TRUE;
    g_r35_session.call_transaction_alive = TRUE;
    g_r35_session.listener_alive = TRUE;
    g_r35_session.registration_alive = TRUE;
    g_r35_session.pseudotcp_alive = TRUE;
    g_r35_session.call_generation = 7u;
    g_r35_session.call_ctp_connection = 0x1234u;
    g_r35_session.call_sequence = 0x20u;
    g_r35_session.call_ack = 0x99u;
    memcpy(g_r35_session.source_logical, "SRCLOGIC12", R35_CTP_LOGADDR_LEN);
    memcpy(g_r35_session.dest_logical, "DSTLOGIC34", R35_CTP_LOGADDR_LEN);
    g_r35_session.channel_allocated = TRUE;
    g_r35_session.channel_generation = 7u;
    g_r35_session.channel_id = 0x4567u;
    g_r35_session.open_sent = TRUE;
    g_r35_session.open_count = 1u;
    g_r35_session.rtp_armed = TRUE;

    v4_listener_ready = TRUE;
    v4_registered = TRUE;
    v4_ctpp_channel_id = 0x2222u;
    p12_stage = P12_STAGE_V4_LISTEN_RING;
    r42_media_stage = R42_MEDIA_ACTIVE;
    r42_media_channel_id = 0x4567u;
    pseudotcp_graceful_stop_started = FALSE;
    p12_tx_pending = FALSE;

    g_r67_attached_refresh_timer_armed = 0u;
    g_r67_attached_refresh_outstanding = 0u;
    g_r67_attached_refresh_fail_closed = 0u;
    g_r67_attached_refresh_cancelled = 0u;
    g_r67_attached_refresh_sent_count = 0u;
    g_r67_attached_refresh_first_elapsed_seconds = 0u;
    g_r67_attached_refresh_last_elapsed_seconds = 0u;
    g_r67_attached_refresh_tick_count = 0u;
    g_r67_attached_refresh_generation = 0u;
    g_r67_attached_refresh_sequence_before = 0u;
    g_r67_attached_refresh_sequence_after = 0u;
    g_r67_attached_refresh_last_result = R67_REFRESH_RESULT_NONE;
    g_r67_attached_refresh_last_error = "NONE";

    g_timer_adds = 0u;
    g_last_timer_seconds = 0u;
    g_timer_cb = NULL;
    memset(g_last_packet, 0, sizeof(g_last_packet));
    g_last_packet_len = 0u;
    g_last_kind = P12_TX_NONE;
    g_queued_count = 0u;
}

static void print_passfail(const char *name, int ok)
{
    printf("%s=%s\n", name, ok ? "PASS" : "FAIL");
}

static int r35_call_ready(const R35AttachedMediaSession *s)
{
    return s && s->call_ctp_valid && s->call_transaction_alive;
}

static void r35_write_be16(unsigned char *out, unsigned value)
{
    out[0] = (unsigned char)((value >> 8) & 0xffu);
    out[1] = (unsigned char)(value & 0xffu);
}

static void r35_write_le16(unsigned char *out, unsigned value)
{
    out[0] = (unsigned char)(value & 0xffu);
    out[1] = (unsigned char)((value >> 8) & 0xffu);
}

static void r35_write_le32(unsigned char *out, unsigned long value)
{
    out[0] = (unsigned char)(value & 0xffu);
    out[1] = (unsigned char)((value >> 8) & 0xffu);
    out[2] = (unsigned char)((value >> 16) & 0xffu);
    out[3] = (unsigned char)((value >> 24) & 0xffu);
}

static int r35_serialize_mediareq26_open(unsigned char out[26], const R35MediaRequestSources *src)
{
    memset(out, 0, R35_MEDIAREQ26_BODY_LEN);
    r35_write_be16(out + 0, R35_MEDIAREQ26_OPCODE);
    out[2] = R35_MEDIAREQ26_OPEN_ACTION;
    out[3] = 0x3au;
    r35_write_le16(out + 8, src->media_channel_id);
    r35_write_le16(out + 10, src->max_rtp_payload);
    r35_write_le32(out + 12, src->channel_profile_word);
    r35_write_le16(out + 16, src->profile_halfwords[0]);
    r35_write_le16(out + 18, src->profile_halfwords[1]);
    r35_write_le16(out + 20, src->profile_halfwords[2]);
    r35_write_le16(out + 22, src->profile_halfword_3);
    out[24] = (unsigned char)(src->profile_byte_4 & 0xffu);
    return TRUE;
}

static int r35_build_call_bound_packet(
    unsigned char out[R35_CALL_BOUND_PACKET_LEN],
    unsigned connection,
    unsigned sequence,
    unsigned acknowledgement,
    const unsigned char mediareq26[R35_MEDIAREQ26_BODY_LEN],
    const unsigned char source_raw[R35_CTP_LOGADDR_LEN],
    const unsigned char dest_raw[R35_CTP_LOGADDR_LEN])
{
    memset(out, 0, R35_CALL_BOUND_PACKET_LEN);
    out[0] = R35_CTP_FLAG_DATA;
    out[1] = R35_CTP_VERSION;
    r35_write_be16(out + 2, connection);
    out[4] = (unsigned char)(sequence & 0xffu);
    out[5] = (unsigned char)(acknowledgement & 0xffu);
    r35_write_be16(out + 6, R35_MEDIAREQ26_BODY_LEN);
    memcpy(out + 8, mediareq26, R35_MEDIAREQ26_BODY_LEN);
    out[36] = 0xffu; out[37] = 0xffu; out[38] = 0xffu; out[39] = 0xffu;
    memcpy(out + 40, source_raw, R35_CTP_LOGADDR_LEN);
    memcpy(out + 50, dest_raw, R35_CTP_LOGADDR_LEN);
    return TRUE;
}

static gboolean p12_queue_vip_frame(
    guint32 request_id,
    const guint8 *body,
    guint body_len,
    P12TxKind kind)
{
    (void)request_id;
    if (p12_tx_pending)
        return FALSE;
    memcpy(g_last_packet, body, body_len);
    g_last_packet_len = body_len;
    g_last_kind = kind;
    g_queued_count++;
    p12_tx_pending = TRUE;
    return TRUE;
}

static gboolean p12_flush_tx(void)
{
    return TRUE;
}

static void complete_refresh_tx(void)
{
    p12_tx_pending = FALSE;
    (void)r67_attached_refresh_tx_completed();
}

static void run_refresh_tick(void)
{
    if (g_timer_cb)
        (void)g_timer_cb(NULL);
}

static void case_lifecycle_15_30_45(void)
{
    reset_world();
    r42_media_stage = R42_MEDIA_IDLE;
    print_passfail("R67_NO_REFRESH_BEFORE_ACTIVE", !r67_start_attached_refresh_loop("inactive"));
    r42_media_stage = R42_MEDIA_ACTIVE;
    print_passfail("R67_STARTS_AFTER_ACTIVE", r67_start_attached_refresh_loop("active"));
    print_passfail("R67_CADENCE_15_SECONDS", g_last_timer_seconds == 15u);
    print_passfail("R67_NO_DUPLICATE_TIMER", r67_start_attached_refresh_loop("again") && g_timer_adds == 1u);

    run_refresh_tick();
    print_passfail("R67_TICK1_ONE_REFRESH", g_queued_count == 1u && g_r67_attached_refresh_outstanding);
    print_passfail("R67_TICK1_OPCODE_0011", g_last_packet[8] == 0x00u && g_last_packet[9] == 0x11u);
    print_passfail("R67_TICK1_OPEN_ACTION", g_last_packet[10] == 0x14u);
    complete_refresh_tx();
    print_passfail("R67_TICK1_AGE_15", g_r67_attached_refresh_last_elapsed_seconds == 15u);

    run_refresh_tick();
    print_passfail("R67_TICK2_ONE_MORE_REFRESH", g_queued_count == 2u);
    complete_refresh_tx();
    print_passfail("R67_TICK2_AGE_30", g_r67_attached_refresh_last_elapsed_seconds == 30u);

    run_refresh_tick();
    print_passfail("R67_TICK3_ONE_MORE_REFRESH", g_queued_count == 3u);
    complete_refresh_tx();
    print_passfail("R67_TICK3_AGE_45", g_r67_attached_refresh_last_elapsed_seconds == 45u);
    print_passfail("R67_SEQUENCE_ADVANCED", (g_r35_session.call_sequence & 0xffu) == 0x23u);
    printf("R67_REFRESH_SENT_COUNT=%u\n", g_r67_attached_refresh_sent_count);
}

static void case_stop_teardown_failure_and_door_interop(void)
{
    reset_world();
    (void)r67_start_attached_refresh_loop("active");
    p12_tx_pending = TRUE;
    run_refresh_tick();
    print_passfail("R67_DOOR_PENDING_DOES_NOT_QUEUE_REFRESH", g_queued_count == 0u);
    print_passfail("R67_DOOR_PENDING_DEFERRED_NOT_FAIL_CLOSED", !g_r67_attached_refresh_fail_closed);
    p12_tx_pending = FALSE;
    run_refresh_tick();
    print_passfail("R67_REFRESH_AFTER_DOOR_PENDING", g_queued_count == 1u);
    complete_refresh_tx();

    r67_cancel_attached_refresh("attached-media-stop");
    run_refresh_tick();
    print_passfail("R67_STOP_CANCELS_NEW_REFRESH", g_queued_count == 1u);

    reset_world();
    (void)r67_start_attached_refresh_loop("active");
    g_r35_session.call_generation++;
    run_refresh_tick();
    print_passfail("R67_STALE_GENERATION_DOES_NOT_REVIVE", g_queued_count == 0u);

    reset_world();
    (void)r67_start_attached_refresh_loop("active");
    g_r67_attached_refresh_outstanding = 1u;
    run_refresh_tick();
    print_passfail("R67_OVERLAP_FAILS_CLOSED", g_r67_attached_refresh_fail_closed);

    print_passfail(
        "R67_NO_SECOND_TRANSPORT",
        g_p2p_start_count == 0u &&
        g_ice_start_count == 0u &&
        g_pseudotcp_start_count == 0u &&
        g_ctpp_start_count == 0u &&
        g_rtpc_start_count == 0u);
}

int main(void)
{
    case_lifecycle_15_30_45();
    case_stop_teardown_failure_and_door_interop();
    return 0;
}
'''


class P116R67AttachedMediaRefreshTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = SOURCE.read_text(encoding="utf-8")
        cls.r66_generated = r66.transform(cls.source)
        cls.generated_a = r67.transform(cls.source)
        cls.generated_b = r67.transform(cls.source)
        cls.generated_sha = _sha256(cls.generated_a)
        cls.region = _extract(cls.generated_a, r67.BEGIN, r67.END)
        cls.cc = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")
        cls.compile_stderr = ""
        cls.harness_stdout = ""
        cls.harness_markers: dict[str, str] = {}
        cls.harness_returncode: int | None = None
        if cls.cc:
            cls.tmp_obj = tempfile.TemporaryDirectory(prefix="p116-r67-harness-")
            tmp = Path(cls.tmp_obj.name)
            combined = tmp / "r67_harness.c"
            combined.write_text(cls._prelude() + "\n" + cls.region + "\n" + HARNESS, encoding="utf-8")
            binary = tmp / "r67_harness"
            result = subprocess.run(
                [cls.cc, "-std=c99", "-Wall", "-Wextra", "-pedantic", str(combined), "-o", str(binary)],
                text=True,
                capture_output=True,
            )
            cls.compile_stderr = result.stderr
            if result.returncode == 0:
                run = subprocess.run([str(binary)], text=True, capture_output=True)
                cls.harness_stdout = run.stdout
                cls.harness_returncode = run.returncode
                cls.harness_markers = _markers(run.stdout)

    @classmethod
    def tearDownClass(cls) -> None:
        if hasattr(cls, "tmp_obj"):
            cls.tmp_obj.cleanup()

    @staticmethod
    def _prelude() -> str:
        return r'''
#include <stdio.h>
#include <string.h>

typedef int gboolean;
typedef unsigned int guint;
typedef unsigned char guint8;
typedef unsigned short guint16;
typedef unsigned int guint32;
typedef void *gpointer;

#define TRUE 1
#define FALSE 0
#define NULL ((void *)0)
#define G_SOURCE_REMOVE FALSE
#define G_SOURCE_CONTINUE TRUE

#define R35_MEDIAREQ26_BODY_LEN 26u
#define R35_MEDIAREQ26_OPCODE 0x0011u
#define R35_MEDIAREQ26_OPEN_ACTION 0x14u
#define R35_CTP_VERSION 0x18u
#define R35_CTP_FLAG_DATA 0x40u
#define R35_CALL_BOUND_PACKET_LEN 60u
#define R35_CTP_LOGADDR_LEN 10u

typedef enum {
    P12_STAGE_IDLE = 0,
    P12_STAGE_V4_LISTEN_RING
} P12ReadonlyStage;

typedef enum {
    P12_TX_NONE = 0,
    P12_TX_CALL_TIME_DOOR,
    P12_TX_R67_ATTACHED_REFRESH
} P12TxKind;

typedef enum {
    R42_MEDIA_IDLE = 0,
    R42_MEDIA_ACTIVE
} R42AttachedMediaStage;

typedef struct {
    int call_ctp_valid;
    int call_transaction_alive;
    unsigned call_generation;
    unsigned call_ctp_connection;
    unsigned call_sequence;
    unsigned call_ack;
    unsigned outer_ctpp_handle;
    unsigned char source_logical[R35_CTP_LOGADDR_LEN];
    unsigned char dest_logical[R35_CTP_LOGADDR_LEN];
    int channel_allocated;
    int channel_disposed;
    unsigned channel_generation;
    unsigned channel_id;
    unsigned channel_token;
    int open_pending;
    int open_sent;
    int open_confirmed;
    int stop_sent;
    int rtp_armed;
    unsigned open_count;
    unsigned stop_count;
    int listener_alive;
    int registration_alive;
    int pseudotcp_alive;
} R35AttachedMediaSession;

typedef struct {
    int form;
    int video_request;
    int profile_selector;
    unsigned media_channel_id;
    unsigned max_rtp_payload;
    unsigned channel_profile_word;
    unsigned profile_halfwords[3];
    unsigned profile_halfword_3;
    unsigned profile_byte_4;
    unsigned char address_ipv4[4];
} R35MediaRequestSources;

#define R35_FORM_TUNNEL 0

static R35AttachedMediaSession g_r35_session;
static gboolean v4_listener_ready = FALSE;
static gboolean v4_registered = FALSE;
static guint16 v4_ctpp_channel_id = 0u;
static P12ReadonlyStage p12_stage = P12_STAGE_IDLE;
static R42AttachedMediaStage r42_media_stage = R42_MEDIA_IDLE;
static guint16 r42_media_channel_id = 0u;
static gboolean pseudotcp_graceful_stop_started = FALSE;
static gboolean p12_tx_pending = FALSE;

static int r35_call_ready(const R35AttachedMediaSession *s);
static int r35_serialize_mediareq26_open(unsigned char out[26], const R35MediaRequestSources *src);
static int r35_build_call_bound_packet(
    unsigned char out[R35_CALL_BOUND_PACKET_LEN],
    unsigned connection,
    unsigned sequence,
    unsigned acknowledgement,
    const unsigned char mediareq26[R35_MEDIAREQ26_BODY_LEN],
    const unsigned char source_raw[R35_CTP_LOGADDR_LEN],
    const unsigned char dest_raw[R35_CTP_LOGADDR_LEN]);
static gboolean p12_queue_vip_frame(guint32 request_id, const guint8 *body, guint body_len, P12TxKind kind);
static gboolean p12_flush_tx(void);
static guint g_timeout_add_seconds(guint seconds, gboolean (*cb)(gpointer data), gpointer data);
'''

    def test_transform_is_deterministic_and_composes_r66(self) -> None:
        self.assertEqual(self.generated_a, self.generated_b)
        self.assertIn(r66.BEGIN, self.generated_a)
        self.assertIn(r67.BEGIN, self.generated_a)
        self.assertNotEqual(_sha256(self.r66_generated), self.generated_sha)

    def test_refresh_region_contract_and_no_second_transport(self) -> None:
        region = self.region
        self.assertIn("R67_ATTACHED_REFRESH_CADENCE_SECONDS 15u", region)
        self.assertIn("R67_ATTACHED_REFRESH_OPCODE=0x0011", region)
        self.assertIn("R67_ATTACHED_REFRESH_FRAME=MEDIAREQ26_OPEN", region)
        self.assertIn("r35_serialize_mediareq26_open(body, &src)", region)
        self.assertIn("r35_build_call_bound_packet(", region)
        self.assertIn("p12_queue_vip_frame(", region)
        self.assertIn("g_timeout_add_seconds(", region)
        self.assertNotIn("0x001A", region)
        self.assertNotIn("0x1a", region)
        for forbidden in (
            "/p2p/start",
            "nice_agent_new",
            "pseudo_tcp_socket_new",
            "P12_TX_V4_OPEN_CTPP",
            "P12_TX_V4_OPEN_CSPB",
            "P12_TX_ENTRANCE_SELF_ACTIVATION",
        ):
            self.assertNotIn(forbidden, region)

    def test_lifecycle_and_door_interop_host_harness(self) -> None:
        if not self.cc:
            self.skipTest("no C compiler available")
        if self.harness_returncode is None:
            self.fail("R67 native harness failed to compile:\n" + self.compile_stderr[:4000])
        self.assertEqual(self.harness_returncode, 0, self.harness_stdout)
        for marker in (
            "R67_NO_REFRESH_BEFORE_ACTIVE",
            "R67_STARTS_AFTER_ACTIVE",
            "R67_CADENCE_15_SECONDS",
            "R67_NO_DUPLICATE_TIMER",
            "R67_TICK1_ONE_REFRESH",
            "R67_TICK1_OPCODE_0011",
            "R67_TICK1_OPEN_ACTION",
            "R67_TICK1_AGE_15",
            "R67_TICK2_ONE_MORE_REFRESH",
            "R67_TICK2_AGE_30",
            "R67_TICK3_ONE_MORE_REFRESH",
            "R67_TICK3_AGE_45",
            "R67_SEQUENCE_ADVANCED",
            "R67_DOOR_PENDING_DOES_NOT_QUEUE_REFRESH",
            "R67_DOOR_PENDING_DEFERRED_NOT_FAIL_CLOSED",
            "R67_REFRESH_AFTER_DOOR_PENDING",
            "R67_STOP_CANCELS_NEW_REFRESH",
            "R67_STALE_GENERATION_DOES_NOT_REVIVE",
            "R67_OVERLAP_FAILS_CLOSED",
            "R67_NO_SECOND_TRANSPORT",
        ):
            self.assertEqual(self.harness_markers.get(marker), "PASS", self.harness_stdout)
        self.assertEqual(self.harness_markers.get("R67_REFRESH_SENT_COUNT"), "3")

    def test_door_contract_remains_supervisor_lock_owned(self) -> None:
        supervisor = (ROOT.parent / "custom_components" / "comelit" / "supervisor.py").read_text(encoding="utf-8")
        self.assertIn("self._lifecycle_lock = asyncio.Lock()", supervisor)
        self.assertRegex(
            supervisor,
            re.compile(
                r"async def async_open_entrance_door\(.*?async with self\._lifecycle_lock:.*?"
                r"return await self\._runtime\.async_open_door\(",
                re.S,
            ),
        )
        self.assertRegex(
            supervisor,
            re.compile(
                r"async def async_recover_attached_media_stop_failure\(self\) -> None:.*?"
                r"async with self\._lifecycle_lock:",
                re.S,
            ),
        )
        self.assertIn("return await media_transport.async_open_door(event_id=event_id)", supervisor)


if __name__ == "__main__":
    unittest.main()
