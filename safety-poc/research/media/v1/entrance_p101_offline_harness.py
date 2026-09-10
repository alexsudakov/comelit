#!/usr/bin/env python3
"""Build offline C harnesses from real P101 generated C regions.

The helpers in this module extract byte-for-byte regions from a transformed
candidate and add only the minimal C shims needed for deterministic unit tests.
They do not reimplement RTP classification or ACK binding logic.
"""
from __future__ import annotations

import argparse
from pathlib import Path


RTP_BEGIN = "/* === P80_HA_MEDIA_RTP_FORWARDING_BEGIN === */"
RTP_END = "/* === P80_HA_MEDIA_RTP_FORWARDING_END === */"
ACK_BEGIN = "static gboolean\np99_state_scoped_structural_ack("
ACK_END = "static gboolean\np92_device_000a_is_valid("
RECV_BEGIN = "static void\nrecv_cb("
RECV_END = "static gboolean\nabsolute_timeout_cb("


def _between(text: str, start: str, end: str, label: str, *, include_end: bool) -> str:
    start_i = text.find(start)
    if start_i < 0:
        raise RuntimeError(f"{label}: start delimiter not found")
    if text.find(start, start_i + 1) >= 0:
        raise RuntimeError(f"{label}: start delimiter is not unique")
    end_i = text.find(end, start_i)
    if end_i < 0:
        raise RuntimeError(f"{label}: end delimiter not found")
    if include_end:
        end_i += len(end)
    return text[start_i:end_i]


def extract_rtp_region(candidate: str) -> str:
    return _between(candidate, RTP_BEGIN, RTP_END, "RTP region", include_end=True)


def extract_ack_region(candidate: str) -> str:
    return _between(candidate, ACK_BEGIN, ACK_END, "ACK region", include_end=False)


def extract_recv_region(candidate: str) -> str:
    return _between(candidate, RECV_BEGIN, RECV_END, "recv region", include_end=False)


RTP_PROLOGUE = r'''
#include <arpa/inet.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/types.h>

typedef int gboolean;
typedef unsigned int guint;
typedef uint8_t guint8;
typedef uint16_t guint16;
typedef uint32_t guint32;
typedef uint64_t guint64;
typedef void *gpointer;
typedef unsigned long GMaxULong;

#define TRUE 1
#define FALSE 0
#define G_MAXUINT ((guint)~0u)
static gboolean failed = FALSE;
static gpointer loop = (gpointer)0x1;
static guint p101_harness_loop_quit_calls = 0;
static guint p101_harness_socket_calls = 0;
static guint p101_harness_sendto_calls = 0;
static ssize_t p101_harness_sendto_result = -1;

static void g_main_loop_quit(gpointer value)
{
    (void)value;
    p101_harness_loop_quit_calls++;
}

static int p101_harness_socket(int domain, int type, int protocol)
{
    (void)domain;
    (void)type;
    (void)protocol;
    p101_harness_socket_calls++;
    return 7;
}

static ssize_t p101_harness_sendto(
    int fd,
    const void *buf,
    size_t len,
    int flags,
    const struct sockaddr *dest_addr,
    socklen_t addrlen)
{
    (void)fd;
    (void)buf;
    (void)flags;
    (void)dest_addr;
    (void)addrlen;
    p101_harness_sendto_calls++;
    return p101_harness_sendto_result >= 0
        ? p101_harness_sendto_result
        : (ssize_t)len;
}

#define socket(...) p101_harness_socket(__VA_ARGS__)
#define sendto(...) p101_harness_sendto(__VA_ARGS__)
'''


ACK_PROLOGUE = r'''
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
typedef void *gpointer;

#define TRUE 1
#define FALSE 0
#define G_SOURCE_REMOVE FALSE
#define P97_ACK_TIMEOUT_SECONDS 3
#define P97_CLIENT_ACK_000A_SEQUENCE_DELTA 0x00010000u
#define P97_CLIENT_001A_SEQUENCE_DELTA_FROM_ACK 0x00010000u

typedef enum {
    P78_RTPC_IDLE = 0,
    P78_RTPC_CLIENT_001A_TX,
    P78_RTPC_COMPLETE,
    P78_RTPC_FAILED
} P78RtpcLiveStage;

typedef enum {
    P78_TX_RTPC_CLIENT_001A = 1,
    P97_TX_DEVICE_000A_ACK = 2
} P12TxKind;

static gboolean failed = FALSE;
static gpointer loop = NULL;
static guint16 v4_ctpp_channel_id = 0x1234u;
static guint8 p78_rtpc_client_000a[64];
static guint p78_rtpc_client_000a_len = 44u;
static guint8 p78_rtpc_client_001a[64];
static guint p78_rtpc_client_001a_len = 60u;
static gpointer pseudo_tcp = (gpointer)0x1;
static gboolean pseudotcp_open = TRUE;
static gboolean p12_tx_pending = FALSE;
static gboolean pseudotcp_graceful_stop_started = FALSE;
static gboolean p92_device_000a_observed = FALSE;
static gboolean p78_rtpc_client_000a_sent = FALSE;
static gboolean p78_rtpc_client_001a_sent = FALSE;
static P78RtpcLiveStage p78_rtpc_stage = P78_RTPC_IDLE;

static gboolean p97_device_000a_roles_stored = FALSE;
static guint8 p97_device_000a_first_role[9];
static guint8 p97_device_000a_second_role[9];
static gboolean p97_client_ack_000a_queued = FALSE;
static gboolean p97_client_ack_000a_sent = FALSE;
static guint32 p97_client_ack_000a_sequence = 0;
static gboolean p97_wait_device_ack_000a = FALSE;
static gboolean p97_device_ack_000a_observed = FALSE;
static gboolean p97_client_001a_started = FALSE;
static gboolean p97_wait_device_ack_001a = FALSE;
static gboolean p97_device_ack_001a_observed = FALSE;
static gboolean p97_signaling_finished = FALSE;

static guint p101_harness_queue_calls = 0;
static guint p101_harness_flush_calls = 0;
static guint p101_harness_fail_calls = 0;
static guint p101_harness_timer_calls = 0;
static guint p101_harness_media_begin_calls = 0;

static guint16 read_le16(const guint8 *p)
{
    return (guint16)(((guint16)p[0]) | ((guint16)p[1] << 8));
}

static guint32 read_le32(const guint8 *p)
{
    return ((guint32)p[0]) |
        ((guint32)p[1] << 8) |
        ((guint32)p[2] << 16) |
        ((guint32)p[3] << 24);
}

static void write_le16(guint8 *p, guint16 value)
{
    p[0] = (guint8)(value & 0xffu);
    p[1] = (guint8)(value >> 8);
}

static void write_le32(guint8 *p, guint32 value)
{
    p[0] = (guint8)(value & 0xffu);
    p[1] = (guint8)((value >> 8) & 0xffu);
    p[2] = (guint8)((value >> 16) & 0xffu);
    p[3] = (guint8)((value >> 24) & 0xffu);
}

static gboolean p12_queue_vip_frame(
    guint16 request_id,
    const guint8 *body,
    guint body_len,
    P12TxKind kind)
{
    (void)request_id;
    (void)body;
    (void)body_len;
    (void)kind;
    p101_harness_queue_calls++;
    return TRUE;
}

static gboolean p12_flush_tx(void)
{
    p101_harness_flush_calls++;
    return TRUE;
}

static void p78_fail_rtpc(const char *marker)
{
    (void)marker;
    p101_harness_fail_calls++;
    failed = TRUE;
    p78_rtpc_stage = P78_RTPC_FAILED;
}

static gboolean p78_queue_rtpc_client_001a(void)
{
    p78_rtpc_stage = P78_RTPC_CLIENT_001A_TX;
    p101_harness_queue_calls++;
    p78_rtpc_client_001a_sent = TRUE;
    return TRUE;
}

static gboolean entrance_signal_begin_media_observation(void)
{
    p101_harness_media_begin_calls++;
    return TRUE;
}

static guint g_timeout_add_seconds(
    guint interval,
    gboolean (*function)(gpointer),
    gpointer data)
{
    (void)interval;
    (void)function;
    (void)data;
    p101_harness_timer_calls++;
    return 1u;
}

static gboolean p97_ack_matches_source(
    const guint8 *body,
    guint body_len,
    const guint8 *source,
    guint source_len)
{
    (void)body;
    (void)body_len;
    (void)source;
    (void)source_len;
    return FALSE;
}

static gboolean p97_queue_client_001a_after_ack(void)
{
    p97_client_001a_started = TRUE;
    p97_wait_device_ack_001a = TRUE;
    p97_device_ack_001a_observed = FALSE;
    return TRUE;
}

static gboolean p97_finish_after_device_ack_001a(void)
{
    p97_signaling_finished = TRUE;
    p78_rtpc_stage = P78_RTPC_COMPLETE;
    return entrance_signal_begin_media_observation();
}
'''


def rtp_harness_source(candidate: str, test_program: str = "") -> str:
    """Return a C translation unit for the real extracted RTP classifier."""
    return RTP_PROLOGUE + "\n" + extract_rtp_region(candidate) + "\n" + test_program


def ack_harness_source(candidate: str, test_program: str = "") -> str:
    """Return a C translation unit for the real extracted ACK binding region."""
    return ACK_PROLOGUE + "\n" + extract_ack_region(candidate) + "\n" + test_program


RECV_PROLOGUE = r'''
typedef struct _NiceAgent NiceAgent;
static guint stream_id = 1u;
static gpointer pseudo_tcp = (gpointer)0x1;
static gboolean pseudotcp_graceful_stop_started = FALSE;
static guint64 pseudotcp_packets_in = 0;
static guint pseudotcp_prestart_count = 0;
#define PSEUDOTCP_PRESTART_MAX_LEN 1600u
#define PSEUDOTCP_PRESTART_MAX_PACKETS 8u
static guint8 pseudotcp_prestart_packets[PSEUDOTCP_PRESTART_MAX_PACKETS][PSEUDOTCP_PRESTART_MAX_LEN];
static guint16 pseudotcp_prestart_lengths[PSEUDOTCP_PRESTART_MAX_PACKETS];
static guint p101_harness_notify_calls = 0;
static gboolean p101_harness_notify_result = TRUE;
static gboolean p101_harness_socket_closed = FALSE;

static gboolean pseudo_tcp_socket_notify_packet(gpointer tcp, const gchar *buf, guint len)
{
    (void)tcp;
    (void)buf;
    (void)len;
    p101_harness_notify_calls++;
    return p101_harness_notify_result;
}

static gboolean pseudo_tcp_socket_is_closed(gpointer tcp)
{
    (void)tcp;
    return p101_harness_socket_closed;
}
'''


def recv_harness_source(candidate: str, test_program: str = "") -> str:
    """Return a C translation unit for the real RTP classifier plus recv_cb."""
    return (
        RTP_PROLOGUE
        + "\n"
        + "typedef char gchar;\n"
        + extract_rtp_region(candidate)
        + "\n"
        + RECV_PROLOGUE
        + "\n"
        + extract_recv_region(candidate)
        + "\n"
        + test_program
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--region", choices=("rtp", "ack", "recv"), required=True)
    args = parser.parse_args(argv)

    text = args.candidate.read_text(encoding="utf-8")
    if args.region == "rtp":
        source = rtp_harness_source(text)
    elif args.region == "ack":
        source = ack_harness_source(text)
    else:
        source = recv_harness_source(text)
    args.output.write_text(source, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
