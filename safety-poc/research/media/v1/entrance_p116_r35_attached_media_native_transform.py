#!/usr/bin/env python3
"""P116/R35 attached inbound media: native (C) port of the R34 offline model.

This is a NEW, SEPARATE overlay transform.  It is applied to the OUTPUT of the
canonical P106/P116 generator
(``entrance_p106_teardown_state_classification_transform.py --include-p116``),
never to the raw door source, and it never re-invokes that generator itself.
The canonical generator and its pinned digest are unchanged by this module.

The injected code ports the proven R33/R34 call-bound MEDIAREQ26 OPEN/STOP
contract (`P116_R33_ATTACHED_INBOUND_MEDIA_PRIMITIVE_CLOSURE.md`,
`entrance_p116_r34_attached_media_helper_model.py`) to dependency-free C,
reusing the existing helper's call-init ring detection, the single-outstanding
VIP transport queue (`p12_queue_vip_frame`), and the existing P80 RTP
forwarding gate (`p80_media_forwarding_enabled`) rather than duplicating them.

Two regions are injected:

- A dependency-free "core" region (types, serializers, the per-call media
  state machine) bounded by ``R35_ATTACHED_MEDIA_BEGIN``/``_END`` markers.
  This region never calls glib/libnice and never performs I/O; every side
  effect goes through an injectable ``R35FrameWriter``/``R35RtpArmHook``
  function pointer, so ``safety-poc/tests/native/p116_r35_attached_media_host_harness.c``
  can extract, compile, and execute it standalone with a fake writer.
- A small "wiring" region bounded by ``R35_WIRING_BEGIN``/``_END`` markers
  that connects the core to the real transport (``p12_queue_vip_frame``) and
  the real RTP forwarding gate (``p80_media_forwarding_enabled``), plus one
  call-site insertion at the existing CALL_INIT ring-detection branch that
  captures the call-bound CTP transaction.  This region is glib-typed and is
  intentionally excluded from the host-harness extraction.

No file under ``custom_components/**`` is read or modified.  No live
Comelit network TX, no Door/Gate action, no synthetic/physical ring, and no
candidate execution are performed by this transform or its callers.
"""
from __future__ import annotations

import argparse
from pathlib import Path

CORE_BEGIN_MARKER = "/* R35_ATTACHED_MEDIA_BEGIN */"
CORE_END_MARKER = "/* R35_ATTACHED_MEDIA_END */"
WIRING_BEGIN_MARKER = "/* R35_WIRING_BEGIN */"
WIRING_END_MARKER = "/* R35_WIRING_END */"

_ENUM_TAIL_ANCHOR = "P12_TX_V4_DOOR_WRITE\n} P12TxKind;"
_ENUM_TAIL_REPLACEMENT = (
    "P12_TX_V4_DOOR_WRITE,\n\n"
    "    P12_TX_R35_MEDIA_OPEN,\n"
    "    P12_TX_R35_MEDIA_STOP\n"
    "} P12TxKind;"
)

_WIRING_ANCHOR = """/*
 * Forward declaration.
 *
 * V4 send helpers are inserted before the existing implementation
 * of p12_flush_tx().
 */
static gboolean
p12_flush_tx(void);"""

_CALL_INIT_CAPTURE_ANCHOR = """                printf(
                    "PHYSICAL_DOOR_ACTION=false\\n"
                );


                fflush(stdout);


                p12_consume_post_ack(
                    frame_len
                );"""

_CALL_INIT_CAPTURE_INSERTED = """                printf(
                    "PHYSICAL_DOOR_ACTION=false\\n"
                );


                fflush(stdout);


                if (!g_r35_session.writer) {
                    r35_wire_session_transport();
                }

                if (r35_capture_call_ctp_id(
                        &g_r35_session,
                        body,
                        body_len,
                        (unsigned)v4_ctpp_channel_id)) {
                    printf("R35_CALL_CTP_CAPTURED=true\\n");
                } else {
                    printf("R35_CALL_CTP_CAPTURED=false\\n");
                }
                fflush(stdout);


                p12_consume_post_ack(
                    frame_len
                );"""

# ---------------------------------------------------------------------------
# Dependency-free core region.
#
# Wire constants and byte layout mirror the R33-proven contract as ported by
# R34 (entrance_p116_r34_attached_media_helper_model.py: MEDIAREQ26_BODY_LENGTH,
# open_flags/stop_flags, serialize_mediareq26_open/serialize_mediareq26_stop)
# and the R30 CTP envelope model (entrance_p116_r30_call_ctp_envelope_model.py:
# parse_ctp_envelope / build_call_bound_media_packet).  The call CTP capture
# direction transform (XOR 0x8000) mirrors
# entrance_p116_r30b_call_transaction_model.py:derive_native_local_connection_id.
# ---------------------------------------------------------------------------
CORE_REGION = r'''/* R35_ATTACHED_MEDIA_BEGIN */
/*
 * P116/R35 attached inbound media: dependency-free call-bound MEDIAREQ26
 * OPEN/STOP state machine.
 *
 * This region intentionally never includes GLib or libnice headers and never
 * calls a network/socket primitive.  All transport and RTP-forwarding side
 * effects are reached only through the injected R35FrameWriter/R35RtpArmHook
 * function pointers so a host test can substitute a fake writer and drive
 * the full call-bound media lifecycle without the packaged helper runtime.
 *
 * Wire layout/action bytes/flag formulas are the R33-proven MEDIAREQ26
 * contract (P116_R33_ATTACHED_INBOUND_MEDIA_PRIMITIVE_CLOSURE.md CHILD A) as
 * ported offline by R34 (entrance_p116_r34_attached_media_helper_model.py).
 */
#include <stdint.h>
#include <string.h>

#define R35_MEDIAREQ26_BODY_LEN     26u
#define R35_MEDIAREQ26_OPCODE       0x0011u
#define R35_MEDIAREQ26_OPEN_ACTION  0x14u
#define R35_MEDIAREQ26_STOP_ACTION  0x94u
#define R35_CTP_VERSION             0x18u
#define R35_CTP_FLAG_DATA           0x40u
#define R35_CTP_FLAG_SYN_MASK       0x80u
#define R35_CALL_BOUND_PACKET_LEN   60u
#define R35_CTP_LOGADDR_LEN         10u

typedef enum {
    R35_FORM_TUNNEL = 0,
    R35_FORM_ADDRESS = 1
} R35Form;

typedef enum {
    R35_STATE_CALL_CAPTURED = 0,
    R35_STATE_CHANNEL_UNALLOCATED,
    R35_STATE_CHANNEL_ALLOCATED_OPEN_REQUESTED,
    R35_STATE_OPEN_SENT,
    R35_STATE_RTP_ELIGIBLE,
    R35_STATE_STOP_SENT,
    R35_STATE_DISPOSED,
    R35_STATE_TERMINAL,
    R35_STATE_ERROR
} R35MediaState;

typedef enum {
    R35_OK = 0,
    R35_ERR_BAD_ARGUMENT,
    R35_ERR_NO_CALL_TRANSACTION_OR_BARRIER,
    R35_ERR_NO_CHANNEL_ALLOCATED,
    R35_ERR_CHANNEL_ALREADY_ALLOCATED,
    R35_ERR_OPEN_ALREADY_PENDING,
    R35_ERR_OPEN_ALREADY_EMITTED,
    R35_ERR_STOP_ALREADY_SENT,
    R35_ERR_CHANNEL_ALREADY_DISPOSED,
    R35_ERR_REGISTRATION_HANDLE_OR_FOREIGN_CALL,
    R35_ERR_WRONG_CHANNEL,
    R35_ERR_STALE_CHANNEL,
    R35_ERR_STOP_BEFORE_OPEN,
    R35_ERR_SECOND_STOP,
    R35_ERR_DISPOSE_BEFORE_STOP,
    R35_ERR_RTP_BEFORE_OPEN
} R35Result;

/* The seven forbidden second-OPEN conditions, proven native/offline in R33/R34
 * (P116_R33_ATTACHED_INBOUND_MEDIA_PRIMITIVE_CLOSURE.md CHILD D item 6;
 * entrance_p116_r34_attached_media_helper_model.py SECOND_OPEN_FORBIDDEN_STATES). */
typedef struct {
    const char *code;
    const char *description;
} R35SecondOpenForbiddenState;

static const R35SecondOpenForbiddenState R35_SECOND_OPEN_FORBIDDEN_STATES[7] = {
    { "NO_CALL_TRANSACTION_CAPTURE_OR_SIGNALING_BARRIER",
      "no call-transaction capture / no call signaling barrier" },
    { "NO_LOCAL_MEDIA_RX_CHANNEL_ALLOCATED",
      "no local media RX channel / id allocated" },
    { "OPEN_ALREADY_PENDING", "OPEN already pending" },
    { "OPEN_ALREADY_EMITTED_ACTIVE_OR_CONFIRMED",
      "OPEN already emitted/active or confirmed" },
    { "STOP_ALREADY_SENT", "STOP already sent" },
    { "MEDIA_CHANNEL_ALREADY_DISPOSED", "media channel already disposed" },
    { "REGISTRATION_HANDLE_OR_FOREIGN_CALL_TRANSACTION",
      "OPEN aimed at the registration handle or a foreign call transaction" }
};

typedef void (*R35FrameWriter)(
    void *ctx,
    const char *semantic_kind,
    const unsigned char *ctp_packet,
    unsigned packet_len,
    unsigned connection,
    unsigned sequence,
    unsigned acknowledgement);

typedef void (*R35RtpArmHook)(void *ctx, int armed);

typedef struct {
    /* call-bound transaction state (R32 CHILD1 / R30 model). */
    int call_ctp_valid;
    int call_transaction_alive;
    unsigned call_generation;
    unsigned call_ctp_connection;
    unsigned call_sequence;
    unsigned call_ack;
    unsigned outer_ctpp_handle;
    unsigned char source_logical[R35_CTP_LOGADDR_LEN];
    unsigned char dest_logical[R35_CTP_LOGADDR_LEN];

    /* media RX channel state (R33 CHILD B minimal model / R34 session). */
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

    /* preservation booleans (R32 CHILD4 teardown ownership model). */
    int listener_alive;
    int registration_alive;
    int pseudotcp_alive;

    R35MediaState state;

    R35FrameWriter writer;
    void *writer_ctx;
    R35RtpArmHook rtp_arm_hook;
    void *rtp_arm_hook_ctx;
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

typedef struct {
    unsigned flags;
    unsigned version;
    unsigned connection;
    unsigned sequence;
    unsigned acknowledgement;
    unsigned inner_len;
    const unsigned char *inner_body;
    const unsigned char *source_raw;
    const unsigned char *dest_raw;
} R35CtpEnvelopeView;

static unsigned r35_read_be16(const unsigned char *p) {
    return ((unsigned)p[0] << 8) | (unsigned)p[1];
}

static void r35_write_be16(unsigned char *p, unsigned v) {
    p[0] = (unsigned char)((v >> 8) & 0xffu);
    p[1] = (unsigned char)(v & 0xffu);
}

static void r35_write_le16(unsigned char *p, unsigned v) {
    p[0] = (unsigned char)(v & 0xffu);
    p[1] = (unsigned char)((v >> 8) & 0xffu);
}

static void r35_write_le32(unsigned char *p, unsigned long v) {
    p[0] = (unsigned char)(v & 0xffu);
    p[1] = (unsigned char)((v >> 8) & 0xffu);
    p[2] = (unsigned char)((v >> 16) & 0xffu);
    p[3] = (unsigned char)((v >> 24) & 0xffu);
}

/* R33 CHILD A: tunnel base 0x32 with bit3 re-derived from video_request;
 * address base 0x30 composed with the profile-selector (bit2) and
 * video-request (bit3) bits.  Never an unconditional literal for callers:
 * the flags byte is always the return value of this function. */
static unsigned r35_open_flags(int form, int video_request, int profile_selector) {
    if (form == R35_FORM_TUNNEL) {
        return (unsigned)((0x32u & ~0x08u) | (video_request ? 0x08u : 0x00u));
    }
    return (unsigned)(0x30u | (profile_selector ? 0x04u : 0x00u) | (video_request ? 0x08u : 0x00u));
}

static unsigned r35_stop_flags(int form) {
    return form == R35_FORM_TUNNEL ? 0x02u : 0x00u;
}

static int r35_serialize_mediareq26_open(unsigned char out[26], const R35MediaRequestSources *src) {
    if (!out || !src) return 0;
    if (src->media_channel_id == 0u || src->media_channel_id > 0xFFFFu) return 0;
    if (src->form != R35_FORM_TUNNEL && src->form != R35_FORM_ADDRESS) return 0;
    memset(out, 0, R35_MEDIAREQ26_BODY_LEN);
    r35_write_be16(out + 0, R35_MEDIAREQ26_OPCODE);
    out[2] = (unsigned char)R35_MEDIAREQ26_OPEN_ACTION;
    out[3] = (unsigned char)r35_open_flags(src->form, src->video_request, src->profile_selector);
    if (src->form == R35_FORM_ADDRESS) {
        memcpy(out + 4, src->address_ipv4, 4);
    }
    r35_write_le16(out + 8, src->media_channel_id);
    r35_write_le16(out + 10, src->max_rtp_payload);
    r35_write_le32(out + 12, (unsigned long)src->channel_profile_word);
    r35_write_le16(out + 16, src->profile_halfwords[0]);
    r35_write_le16(out + 18, src->profile_halfwords[1]);
    r35_write_le16(out + 20, src->profile_halfwords[2]);
    r35_write_le16(out + 22, src->profile_halfword_3);
    out[24] = (unsigned char)(src->profile_byte_4 & 0xffu);
    out[25] = 0;
    return 1;
}

static int r35_serialize_mediareq26_stop(unsigned char out[26], int form, unsigned media_channel_id) {
    if (!out) return 0;
    if (media_channel_id == 0u || media_channel_id > 0xFFFFu) return 0;
    if (form != R35_FORM_TUNNEL && form != R35_FORM_ADDRESS) return 0;
    memset(out, 0, R35_MEDIAREQ26_BODY_LEN);
    r35_write_be16(out + 0, R35_MEDIAREQ26_OPCODE);
    out[2] = (unsigned char)R35_MEDIAREQ26_STOP_ACTION;
    out[3] = (unsigned char)r35_stop_flags(form);
    r35_write_le16(out + 8, media_channel_id);
    return 1;
}

/* Generic CTP envelope reader mirroring the R30-proven layout
 * (entrance_p116_r30_call_ctp_envelope_model.py:parse_ctp_envelope):
 * flags(1) version(1) connection(2,BE) sequence(1) ack(1) inner_len(2,BE)
 * inner_body(inner_len) pad trailer(4x0xff) source(10) dest(10). */
static int r35_parse_ctp_envelope(const unsigned char *payload, unsigned len, R35CtpEnvelopeView *out) {
    unsigned inner_len, body_end, pad, trailer_start;
    if (!payload || !out || len < 32u) return 0;
    if (payload[1] != R35_CTP_VERSION) return 0;
    inner_len = r35_read_be16(payload + 6);
    body_end = 8u + inner_len;
    pad = (4u - (inner_len % 4u)) % 4u;
    trailer_start = body_end + pad;
    if (len != trailer_start + 24u) return 0;
    if (!(payload[trailer_start] == 0xffu && payload[trailer_start + 1] == 0xffu &&
          payload[trailer_start + 2] == 0xffu && payload[trailer_start + 3] == 0xffu)) {
        return 0;
    }
    out->flags = payload[0];
    out->version = payload[1];
    out->connection = r35_read_be16(payload + 2);
    out->sequence = payload[4];
    out->acknowledgement = payload[5];
    out->inner_len = inner_len;
    out->inner_body = payload + 8;
    out->source_raw = payload + trailer_start + 4;
    out->dest_raw = payload + trailer_start + 14;
    return 1;
}

static int r35_build_call_bound_packet(
    unsigned char out[R35_CALL_BOUND_PACKET_LEN],
    unsigned connection,
    unsigned sequence,
    unsigned acknowledgement,
    const unsigned char mediareq26[R35_MEDIAREQ26_BODY_LEN],
    const unsigned char source_raw[R35_CTP_LOGADDR_LEN],
    const unsigned char dest_raw[R35_CTP_LOGADDR_LEN]) {
    if (!out || !mediareq26 || !source_raw || !dest_raw) return 0;
    memset(out, 0, R35_CALL_BOUND_PACKET_LEN);
    out[0] = (unsigned char)R35_CTP_FLAG_DATA;
    out[1] = (unsigned char)R35_CTP_VERSION;
    r35_write_be16(out + 2, connection & 0xFFFFu);
    out[4] = (unsigned char)(sequence & 0xffu);
    out[5] = (unsigned char)(acknowledgement & 0xffu);
    r35_write_be16(out + 6, R35_MEDIAREQ26_BODY_LEN);
    memcpy(out + 8, mediareq26, R35_MEDIAREQ26_BODY_LEN);
    out[36] = 0xffu; out[37] = 0xffu; out[38] = 0xffu; out[39] = 0xffu;
    memcpy(out + 40, source_raw, R35_CTP_LOGADDR_LEN);
    memcpy(out + 50, dest_raw, R35_CTP_LOGADDR_LEN);
    return 1;
}

/* Capture the call-bound CTP transaction at CALL_INIT: connection bytes 2..3
 * of the inbound CTP header, direction-transformed by XOR 0x8000 (R32 CHILD1;
 * entrance_p116_r30b_call_transaction_model.py:derive_native_local_connection_id).
 * Sequence/ack seed the outbound call-bound counters the same way R30B seeds
 * CallTransaction.next_tx_sequence/next_tx_acknowledgement (peer ack/sequence
 * swapped).  Resets media-channel bookkeeping is NOT performed here: a fresh
 * allocate call always starts a new channel generation (see
 * r35_allocate_media_rx_channel), so residual state from a prior call on the
 * same session object cannot be reused without a matching call_generation. */
static int r35_capture_call_ctp_id(
    R35AttachedMediaSession *s,
    const unsigned char *call_init_envelope,
    unsigned envelope_len,
    unsigned outer_ctpp_handle) {
    R35CtpEnvelopeView view;
    unsigned local_connection;
    if (!s || !r35_parse_ctp_envelope(call_init_envelope, envelope_len, &view)) return 0;
    if (!(view.flags & R35_CTP_FLAG_SYN_MASK)) return 0;
    local_connection = (view.connection ^ 0x8000u) & 0xFFFFu;
    if (local_connection == 0u || (local_connection & 0x7FFFu) == 0x7FFFu) return 0;
    if (local_connection == (outer_ctpp_handle & 0xFFFFu)) return 0;

    s->call_generation += 1u;
    s->call_ctp_connection = local_connection;
    s->call_sequence = view.acknowledgement & 0xffu;
    s->call_ack = view.sequence & 0xffu;
    s->outer_ctpp_handle = outer_ctpp_handle;
    memcpy(s->source_logical, view.dest_raw, R35_CTP_LOGADDR_LEN);
    memcpy(s->dest_logical, view.source_raw, R35_CTP_LOGADDR_LEN);
    s->call_ctp_valid = 1;
    s->call_transaction_alive = 1;
    s->listener_alive = 1;
    s->registration_alive = 1;
    s->pseudotcp_alive = 1;
    s->state = R35_STATE_CALL_CAPTURED;
    return 1;
}

static int r35_call_ready(const R35AttachedMediaSession *s) {
    if (!s->call_ctp_valid || !s->call_transaction_alive) return 0;
    if (s->call_ctp_connection == (s->outer_ctpp_handle & 0xFFFFu)) return 0;
    return 1;
}

/* Order mirrors R34's _require_live_channel: disposed is checked before
 * "not allocated" because dispose_media_rx_channel sets both channel_disposed
 * and clears channel_allocated in the same step, and a disposed/invalidated
 * identity must read as STALE rather than merely "never allocated". */
static R35Result r35_require_live_channel(const R35AttachedMediaSession *s, unsigned channel_id) {
    if (s->channel_disposed) return R35_ERR_STALE_CHANNEL;
    if (!s->channel_allocated) return R35_ERR_NO_CHANNEL_ALLOCATED;
    if (s->channel_generation != s->call_generation) return R35_ERR_REGISTRATION_HANDLE_OR_FOREIGN_CALL;
    if (s->channel_id != channel_id) return R35_ERR_WRONG_CHANNEL;
    return R35_OK;
}

R35Result r35_allocate_media_rx_channel(R35AttachedMediaSession *s, unsigned channel_id, unsigned token) {
    if (!s) return R35_ERR_BAD_ARGUMENT;
    if (!r35_call_ready(s)) return R35_ERR_NO_CALL_TRANSACTION_OR_BARRIER;
    if (channel_id == 0u || channel_id > 0xFFFFu) return R35_ERR_BAD_ARGUMENT;
    if (s->channel_allocated && s->channel_generation == s->call_generation) {
        return R35_ERR_CHANNEL_ALREADY_ALLOCATED;
    }
    s->channel_id = channel_id;
    s->channel_token = token;
    s->channel_generation = s->call_generation;
    s->channel_allocated = 1;
    s->channel_disposed = 0;
    s->open_pending = 0;
    s->open_sent = 0;
    s->open_confirmed = 0;
    s->stop_sent = 0;
    s->rtp_armed = 0;
    s->open_count = 0;
    s->stop_count = 0;
    s->state = R35_STATE_CHANNEL_ALLOCATED_OPEN_REQUESTED;
    return R35_OK;
}

R35Result r35_send_open(
    R35AttachedMediaSession *s,
    const R35MediaRequestSources *src,
    int use_registration_handle) {
    unsigned char body[R35_MEDIAREQ26_BODY_LEN];
    unsigned char packet[R35_CALL_BOUND_PACKET_LEN];
    R35Result live;
    if (!s || !src) return R35_ERR_BAD_ARGUMENT;
    if (use_registration_handle) return R35_ERR_REGISTRATION_HANDLE_OR_FOREIGN_CALL;
    if (!r35_call_ready(s)) return R35_ERR_NO_CALL_TRANSACTION_OR_BARRIER;
    live = r35_require_live_channel(s, src->media_channel_id);
    if (live != R35_OK) return live;
    if (s->open_pending) return R35_ERR_OPEN_ALREADY_PENDING;
    if (s->open_sent || s->open_confirmed) return R35_ERR_OPEN_ALREADY_EMITTED;
    if (s->stop_sent) return R35_ERR_STOP_ALREADY_SENT;
    if (!r35_serialize_mediareq26_open(body, src)) return R35_ERR_BAD_ARGUMENT;
    if (!r35_build_call_bound_packet(packet, s->call_ctp_connection, s->call_sequence,
                                      s->call_ack, body, s->source_logical, s->dest_logical)) {
        return R35_ERR_BAD_ARGUMENT;
    }
    if (s->writer) {
        s->writer(s->writer_ctx, "MEDIA_OPEN", packet, R35_CALL_BOUND_PACKET_LEN,
                   s->call_ctp_connection, s->call_sequence, s->call_ack);
    }
    s->call_sequence = (s->call_sequence + 1u) & 0xffu;
    s->open_pending = 1;
    s->open_sent = 1;
    s->open_count += 1u;
    s->state = R35_STATE_OPEN_SENT;
    return R35_OK;
}

R35Result r35_observe_channel_open_response(R35AttachedMediaSession *s, unsigned channel_id, int ok) {
    R35Result live;
    if (!s) return R35_ERR_BAD_ARGUMENT;
    live = r35_require_live_channel(s, channel_id);
    if (live != R35_OK) return live;
    if (!s->open_pending && !s->open_sent) return R35_ERR_STOP_BEFORE_OPEN;
    s->open_pending = 0;
    s->open_confirmed = ok ? 1 : 0;
    return R35_OK;
}

/* RTP may arm only after exactly one call-bound OPEN (R33 CHILD C:
 * CHANNEL_OPEN_RESPONSE_REQUIRED_BEFORE_RTP=false, so no response wait is
 * required, but a proven prior OPEN on the same channel/generation is). */
R35Result r35_enable_rtp(R35AttachedMediaSession *s, unsigned channel_id) {
    R35Result live;
    if (!s) return R35_ERR_BAD_ARGUMENT;
    live = r35_require_live_channel(s, channel_id);
    if (live != R35_OK) return live;
    if (!s->open_sent || s->open_count != 1u) return R35_ERR_RTP_BEFORE_OPEN;
    s->rtp_armed = 1;
    s->state = R35_STATE_RTP_ELIGIBLE;
    if (s->rtp_arm_hook) s->rtp_arm_hook(s->rtp_arm_hook_ctx, 1);
    return R35_OK;
}

R35Result r35_send_stop(R35AttachedMediaSession *s, int form, unsigned channel_id) {
    unsigned char body[R35_MEDIAREQ26_BODY_LEN];
    unsigned char packet[R35_CALL_BOUND_PACKET_LEN];
    R35Result live;
    if (!s) return R35_ERR_BAD_ARGUMENT;
    if (!r35_call_ready(s)) return R35_ERR_NO_CALL_TRANSACTION_OR_BARRIER;
    live = r35_require_live_channel(s, channel_id);
    if (live != R35_OK) return live;
    if (!s->open_sent || s->open_count == 0u) return R35_ERR_STOP_BEFORE_OPEN;
    if (s->stop_sent || s->stop_count != 0u) return R35_ERR_SECOND_STOP;
    if (!r35_serialize_mediareq26_stop(body, form, channel_id)) return R35_ERR_BAD_ARGUMENT;
    if (!r35_build_call_bound_packet(packet, s->call_ctp_connection, s->call_sequence,
                                      s->call_ack, body, s->source_logical, s->dest_logical)) {
        return R35_ERR_BAD_ARGUMENT;
    }
    if (s->writer) {
        s->writer(s->writer_ctx, "MEDIA_STOP", packet, R35_CALL_BOUND_PACKET_LEN,
                   s->call_ctp_connection, s->call_sequence, s->call_ack);
    }
    s->call_sequence = (s->call_sequence + 1u) & 0xffu;
    s->stop_sent = 1;
    s->stop_count += 1u;
    s->rtp_armed = 0;
    s->state = R35_STATE_STOP_SENT;
    if (s->rtp_arm_hook) s->rtp_arm_hook(s->rtp_arm_hook_ctx, 0);
    return R35_OK;
}

/* STOP strictly precedes disposal; no STOP ACK is awaited (R33 CHILD D items
 * 1-2).  Once disposed, channel_id/token are permanently invalid for this
 * call_generation: r35_require_live_channel rejects any further use. */
R35Result r35_dispose_media_rx_channel(R35AttachedMediaSession *s, unsigned channel_id) {
    R35Result live;
    if (!s) return R35_ERR_BAD_ARGUMENT;
    live = r35_require_live_channel(s, channel_id);
    if (live != R35_OK) return live;
    if (!s->stop_sent || s->stop_count == 0u) return R35_ERR_DISPOSE_BEFORE_STOP;
    s->channel_disposed = 1;
    s->channel_allocated = 0;
    s->rtp_armed = 0;
    s->state = R35_STATE_DISPOSED;
    return R35_OK;
}

int r35_preserve_listener_registration_pseudotcp(const R35AttachedMediaSession *s) {
    if (!s) return 0;
    if (s->channel_allocated || s->rtp_armed) return 0;
    return s->listener_alive && s->registration_alive && s->pseudotcp_alive && s->call_transaction_alive;
}

/* Stale call/media state after call end must fail closed: clearing
 * call_ctp_valid/call_transaction_alive makes r35_call_ready() reject every
 * subsequent allocate/open/stop attempt on this session until a fresh
 * r35_capture_call_ctp_id() call for a new call transaction succeeds. */
void r35_teardown_call(R35AttachedMediaSession *s) {
    if (!s) return;
    s->call_ctp_valid = 0;
    s->call_transaction_alive = 0;
    s->state = R35_STATE_TERMINAL;
}
/* R35_ATTACHED_MEDIA_END */'''

# ---------------------------------------------------------------------------
# Wiring region: connects the dependency-free core to the real transport
# (p12_queue_vip_frame) and the real P80 RTP-forwarding gate
# (p80_media_forwarding_enabled).  Intentionally excluded from the host
# harness extraction because it uses glib types.
# ---------------------------------------------------------------------------
WIRING_REGION = r'''/* R35_WIRING_BEGIN */
static R35AttachedMediaSession g_r35_session;

static void
r35_glib_transport_writer(
    void *ctx,
    const char *semantic_kind,
    const unsigned char *ctp_packet,
    unsigned packet_len,
    unsigned connection,
    unsigned sequence,
    unsigned acknowledgement)
{
    gboolean queued;

    (void)ctx;
    (void)connection;
    (void)sequence;
    (void)acknowledgement;

    queued = p12_queue_vip_frame(
        (guint32)v4_ctpp_channel_id,
        ctp_packet,
        packet_len,
        strcmp(semantic_kind, "MEDIA_OPEN") == 0
            ? P12_TX_R35_MEDIA_OPEN
            : P12_TX_R35_MEDIA_STOP);

    printf("R35_%s_QUEUED=%s\n", semantic_kind, queued ? "true" : "false");
    fflush(stdout);
}

/* Reuses the existing P80 receive/forwarding gate: R35 arms/disarms the same
 * boolean the self-activation path sets at P80_MEDIA_ACTIVE (see
 * p80_try_forward_wrapped_rtp), rather than duplicating a second forwarding
 * decision surface. */
static void
r35_p80_rtp_arm_hook(void *ctx, int armed)
{
    (void)ctx;
    p80_media_forwarding_enabled = armed ? TRUE : FALSE;
    printf("R35_RTP_ARMED=%s\n", armed ? "true" : "false");
    fflush(stdout);
}

static void
r35_wire_session_transport(void)
{
    g_r35_session.writer = r35_glib_transport_writer;
    g_r35_session.writer_ctx = NULL;
    g_r35_session.rtp_arm_hook = r35_p80_rtp_arm_hook;
    g_r35_session.rtp_arm_hook_ctx = NULL;
}
/* R35_WIRING_END */

'''


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one anchor, found {count}")
    return text.replace(old, new, 1)


def _assert_gates(candidate: str) -> None:
    for marker in (CORE_BEGIN_MARKER, CORE_END_MARKER, WIRING_BEGIN_MARKER, WIRING_END_MARKER):
        if candidate.count(marker) != 1:
            raise RuntimeError(f"R35_MARKER_GATE=FAIL marker={marker} count={candidate.count(marker)}")

    begin_idx = candidate.index(CORE_BEGIN_MARKER)
    end_idx = candidate.index(CORE_END_MARKER)
    if not begin_idx < end_idx:
        raise RuntimeError("R35_MARKER_ORDER_GATE=FAIL core begin/end out of order")

    core = extract_core_region(candidate)
    for forbidden in ("glib.h", "nice/agent.h", "GMainLoop", "gboolean", "guint", "NiceAgent",
                       "PseudoTcpSocket", "socket(", "sendto(", "printf(", "fprintf("):
        if forbidden in core:
            raise RuntimeError(f"R35_CORE_DEPENDENCY_FREE_GATE=FAIL forbidden={forbidden}")

    for forbidden in (
        "P12_TX_ENTRANCE_SELF_ACTIVATION",
        "entrance_self_activation",
        "v4_door_signal_handler",
        "V4_DOOR_WRITE",
        "repeat_001a",
        "REPEAT_001A",
        "-lpthread",
        "pthread_create",
    ):
        if forbidden in core:
            raise RuntimeError(f"R35_CORE_FORBIDDEN_SYMBOL_GATE=FAIL forbidden={forbidden}")

    if "R35_ERR_REGISTRATION_HANDLE_OR_FOREIGN_CALL" not in core:
        raise RuntimeError("R35_REGISTRATION_GUARD_GATE=FAIL")
    if candidate.count("r35_capture_call_ctp_id(") < 2:
        raise RuntimeError("R35_CAPTURE_CALL_SITE_GATE=FAIL")
    if "p80_media_forwarding_enabled = armed" not in candidate:
        raise RuntimeError("R35_RTP_REUSE_GATE=FAIL")
    if "p12_queue_vip_frame(" not in candidate.split(WIRING_BEGIN_MARKER, 1)[1].split(WIRING_END_MARKER, 1)[0]:
        raise RuntimeError("R35_TRANSPORT_REUSE_GATE=FAIL")

    # No automatic retry: neither region schedules a g_timeout_add/backoff
    # around a MEDIA_OPEN/MEDIA_STOP write.
    wiring = candidate.split(WIRING_BEGIN_MARKER, 1)[1].split(WIRING_END_MARKER, 1)[0]
    if "g_timeout_add" in wiring or "retry" in wiring.lower():
        raise RuntimeError("R35_NO_RETRY_GATE=FAIL")


def extract_core_region(candidate: str) -> str:
    """Return exactly the text between the core BEGIN/END markers (exclusive)."""
    begin = candidate.index(CORE_BEGIN_MARKER) + len(CORE_BEGIN_MARKER)
    end = candidate.index(CORE_END_MARKER)
    if end <= begin:
        raise RuntimeError("R35_CORE_EXTRACTION_GATE=FAIL empty or inverted region")
    return candidate[begin:end]


def transform(source: str) -> str:
    """Apply the R35 attached-media overlay to an already-generated P106/P116 C source.

    ``source`` must already be the output of
    ``entrance_p106_teardown_state_classification_transform.py --include-p116``;
    this function never re-invokes that generator and never touches its digest.
    """
    candidate = source

    candidate = _replace_once(
        candidate,
        _ENUM_TAIL_ANCHOR,
        _ENUM_TAIL_REPLACEMENT,
        "R35_P12_TX_KIND_EXTENSION",
    )

    candidate = _replace_once(
        candidate,
        _WIRING_ANCHOR,
        CORE_REGION + "\n\n\n" + WIRING_REGION + _WIRING_ANCHOR,
        "R35_CORE_AND_WIRING_INSERTION",
    )

    candidate = _replace_once(
        candidate,
        _CALL_INIT_CAPTURE_ANCHOR,
        _CALL_INIT_CAPTURE_INSERTED,
        "R35_CALL_INIT_CAPTURE_INSERTION",
    )

    _assert_gates(candidate)
    return candidate


def report() -> str:
    return "\n".join(
        (
            "=== COMELIT P116 R35 ATTACHED MEDIA NATIVE TRANSFORM ===",
            "OVERLAY_STEP=SEPARATE_FROM_P106_P116_CHAIN",
            "CORE_REGION_DEPENDENCY_FREE=true",
            "CALL_CTP_CAPTURE_CALL_SITE_ADDED=true",
            "TRANSPORT_REUSED=p12_queue_vip_frame",
            "RTP_GATE_REUSED=p80_media_forwarding_enabled",
            "SELF_ACTIVATION_TOUCHED=false",
            "AUTOMATIC_RETRY_ADDED=false",
            "NEW_RUNTIME_DEPENDENCY_ADDED=false",
            "NETWORK_IO_PERFORMED=false",
            "CANDIDATE_EXECUTED=false",
            "=== END COMELIT P116 R35 ATTACHED MEDIA NATIVE TRANSFORM ===",
        )
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        required=True,
        help="Path to an already-generated P106/P116 candidate C source "
        "(output of entrance_p106_teardown_state_classification_transform.py --include-p116).",
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--report", action="store_true")
    args = parser.parse_args(argv)

    candidate = transform(args.source.read_text(encoding="utf-8"))
    if args.output:
        args.output.write_text(candidate, encoding="utf-8")
    else:
        print(candidate, end="")
    if args.report:
        print(report())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
