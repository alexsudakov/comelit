/*
 * P116/R42-b CAPABILITIES-trigger diagnostics host harness.
 *
 * This file is NOT part of the packaged helper. It is a research-only,
 * host-compilable driver for the dependency-free diagnostics regions emitted
 * by entrance_p116_r42b_listener_attached_media_transform.py:
 *
 *   - R42_CAPABILITIES_DIAGNOSTICS_STATE_BEGIN/END  (statics + pure helpers)
 *   - R42_CAPABILITIES_DIAGNOSTICS_BEGIN/END        (the inline per-frame block,
 *                                                    wrapped into a function by
 *                                                    the Python test module)
 *
 * The Python test module (test_p116_r42b_capabilities_diag_behavior.py)
 * concatenates: this file, the extracted state region, a driver function
 * containing the extracted inline region, and a scenario driver, then
 * compiles it with `cc -std=c99 -Wall -Wextra -pedantic` and runs it.
 *
 * Why a harness: string-presence gates cannot prove that a stage the block
 * computes is actually published. This harness drives synthetic frames
 * through the real emitted block and lets the assertions look at what was
 * actually printed. It never opens a socket, never forks, never touches the
 * filesystem beyond stdio, and never calls Door/Gate; the R35/R36 predicates
 * the block reads are replaced by in-memory stubs that only count calls.
 */

#include <stdio.h>
#include <string.h>

/* ---- stubs for exactly the predicates/types the diagnostics block reads ---- */

typedef struct {
    unsigned short flags;
    unsigned short connection;
    unsigned inner_len;
    const unsigned char *inner_body;
} R35CtpEnvelopeView;

#define R35_CTP_FLAG_DATA 0x01u
#define R36_OP_CAPABILITIES 0x0003u
#define R36_CAP_BODY_MIN_LEN 5u

typedef struct {
    void *writer;
    unsigned call_generation;
    unsigned call_ctp_connection;
} R35AttachedMediaSession;

static R35AttachedMediaSession g_r35_session;
static const unsigned char *body;
static unsigned body_len;
static unsigned char g_stub_body[8] = {0x00u, 0x03u, 0x49u, 0x00u, 0x08u, 0x00u, 0x00u, 0x00u};

/* scenario knobs (set by the driver, read by the stubs) */
static int g_stub_parse_ok = 1;
static unsigned short g_stub_flags = R35_CTP_FLAG_DATA;
static unsigned short g_stub_connection = 0x4A5Au;
static unsigned g_stub_inner_len = 8u;
static unsigned short g_stub_opcode = R36_OP_CAPABILITIES;
static int g_stub_call_ready = 1;
static int g_stub_video_requested = 1;

/* call counters: the diagnostics block must not reach functional writers */
static unsigned g_parse_calls = 0;
static unsigned g_call_ready_calls = 0;
static unsigned g_video_predicate_calls = 0;

static int
r35_parse_ctp_envelope(
    const unsigned char *buffer,
    unsigned length,
    R35CtpEnvelopeView *view)
{
    (void)buffer;
    (void)length;
    g_parse_calls++;
    if (!g_stub_parse_ok) {
        return 0;
    }
    view->flags = g_stub_flags;
    view->connection = g_stub_connection;
    view->inner_len = g_stub_inner_len;
    view->inner_body = g_stub_body;
    return 1;
}

static unsigned short
r35_read_be16(const unsigned char *field)
{
    (void)field;
    return g_stub_opcode;
}

static int
r35_call_ready(const R35AttachedMediaSession *session)
{
    (void)session;
    g_call_ready_calls++;
    return g_stub_call_ready;
}

static int
r36_capabilities_video_requested(const R35CtpEnvelopeView *view)
{
    (void)view;
    g_video_predicate_calls++;
    return g_stub_video_requested;
}

/* ===================== extracted state region ===================== */
