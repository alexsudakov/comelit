#!/usr/bin/env python3
"""P116/R45 native-equivalent call-adoption C core (offline research artifact).

This module does not modify production source by itself.  It exposes a
dependency-free C core used by the R45 host harness.  The core is deliberately
built on R35's existing captured call transaction and writer hook, so the test
exercises the same connection/sequence/address state later used by R36/R42.

Primary-native contracts are pinned by P116/R43B:
- empty transport ACK: flags 0x80, body length 0;
- accepted body-bearing peer frame advances local acknowledgement to
  peer_sequence + 1, while empty ACK does not advance local TX sequence;
- local CAPABILITIES: 00 03 <call-type> 00 <capability-word LE32>, length 8;
- local ALERTING: 00 0A <runtime-byte>, length 3.

No socket/network/HA/Door/Gate primitive appears in this core.
"""
from __future__ import annotations

CORE_BEGIN_MARKER = "/* R45_CALL_ADOPTION_BEGIN */"
CORE_END_MARKER = "/* R45_CALL_ADOPTION_END */"

CORE_REGION = r'''/* R45_CALL_ADOPTION_BEGIN */
#define R45_CTP_FLAG_EMPTY_ACK        0x80u
#define R45_OP_CAPABILITIES           0x0003u
#define R45_OP_ALERTING               0x000Au
#define R45_CAPABILITIES_BODY_LEN     8u
#define R45_ALERTING_BODY_LEN         3u
#define R45_PACKET_MAX_LEN            40u

typedef struct {
    unsigned generation;
    int invite_ack_sent;
    int local_capabilities_sent;
    int local_alerting_sent;
    unsigned inbound_ack_count;
    unsigned local_signaling_write_count;
} R45CallAdoptionState;

typedef struct {
    unsigned call_type;
    unsigned capability_word;
    unsigned alerting_argument;
} R45RuntimeFields;

static void r45_reset_state(R45CallAdoptionState *state, unsigned generation) {
    if (!state) return;
    memset(state, 0, sizeof(*state));
    state->generation = generation;
}

static void r45_sync_generation(
    R45CallAdoptionState *state,
    const R35AttachedMediaSession *session) {
    if (!state || !session) return;
    if (state->generation != session->call_generation) {
        r45_reset_state(state, session->call_generation);
    }
}

static unsigned r45_padded_inner_len(unsigned inner_len) {
    return (inner_len + 3u) & ~3u;
}

static unsigned r45_packet_len(unsigned inner_len) {
    return 8u + r45_padded_inner_len(inner_len) + 4u
        + (2u * R35_CTP_LOGADDR_LEN);
}

static int r45_build_packet(
    unsigned char out[R45_PACKET_MAX_LEN],
    unsigned *out_len,
    unsigned flags,
    unsigned connection,
    unsigned sequence,
    unsigned acknowledgement,
    const unsigned char *inner_body,
    unsigned inner_len,
    const unsigned char source_raw[R35_CTP_LOGADDR_LEN],
    const unsigned char dest_raw[R35_CTP_LOGADDR_LEN]) {
    unsigned padded_len;
    unsigned trailer_start;
    unsigned packet_len;
    if (!out || !out_len || !source_raw || !dest_raw) return 0;
    if (inner_len > R45_CAPABILITIES_BODY_LEN) return 0;
    if (inner_len != 0u && !inner_body) return 0;

    padded_len = r45_padded_inner_len(inner_len);
    trailer_start = 8u + padded_len;
    packet_len = r45_packet_len(inner_len);
    if (packet_len > R45_PACKET_MAX_LEN) return 0;

    memset(out, 0, R45_PACKET_MAX_LEN);
    out[0] = (unsigned char)(flags & 0xffu);
    out[1] = (unsigned char)R35_CTP_VERSION;
    r35_write_be16(out + 2, connection & 0xffffu);
    out[4] = (unsigned char)(sequence & 0xffu);
    out[5] = (unsigned char)(acknowledgement & 0xffu);
    r35_write_be16(out + 6, inner_len);
    if (inner_len != 0u) memcpy(out + 8, inner_body, inner_len);

    out[trailer_start + 0u] = 0xffu;
    out[trailer_start + 1u] = 0xffu;
    out[trailer_start + 2u] = 0xffu;
    out[trailer_start + 3u] = 0xffu;
    memcpy(out + trailer_start + 4u, source_raw, R35_CTP_LOGADDR_LEN);
    memcpy(out + trailer_start + 14u, dest_raw, R35_CTP_LOGADDR_LEN);
    *out_len = packet_len;
    return 1;
}

static int r45_emit(
    R35AttachedMediaSession *session,
    const char *semantic_kind,
    const unsigned char *packet,
    unsigned packet_len,
    unsigned sequence,
    unsigned acknowledgement) {
    if (!session || !semantic_kind || !packet || !session->writer) return 0;
    session->writer(
        session->writer_ctx,
        semantic_kind,
        packet,
        packet_len,
        session->call_ctp_connection,
        sequence,
        acknowledgement);
    return 1;
}

static int r45_view_matches_current_call(
    const R35AttachedMediaSession *session,
    const R35CtpEnvelopeView *view) {
    unsigned local_connection;
    if (!session || !view || !r35_call_ready(session)) return 0;
    local_connection = (view->connection ^ 0x8000u) & 0xffffu;
    return local_connection == session->call_ctp_connection ? 1 : 0;
}

static int r45_emit_empty_ack_for_peer_frame(
    R35AttachedMediaSession *session,
    R45CallAdoptionState *state,
    const R35CtpEnvelopeView *view,
    const char *semantic_kind) {
    unsigned char packet[R45_PACKET_MAX_LEN];
    unsigned packet_len = 0u;
    unsigned outgoing_ack;
    unsigned sequence;
    if (!session || !state || !view || !semantic_kind) return 0;
    r45_sync_generation(state, session);
    if (!r45_view_matches_current_call(session, view)) return 0;
    if ((view->flags & R35_CTP_FLAG_DATA) == 0u &&
        (view->flags & R35_CTP_FLAG_SYN_MASK) == 0u) return 0;
    if (view->inner_len == 0u) return 0;

    outgoing_ack = (view->sequence + 1u) & 0xffu;
    sequence = session->call_sequence & 0xffu;
    session->call_ack = outgoing_ack;

    if (!r45_build_packet(
            packet, &packet_len,
            R45_CTP_FLAG_EMPTY_ACK,
            session->call_ctp_connection,
            sequence,
            outgoing_ack,
            NULL, 0u,
            session->source_logical,
            session->dest_logical)) {
        return 0;
    }
    if (!r45_emit(
            session, semantic_kind, packet, packet_len,
            sequence, outgoing_ack)) {
        return 0;
    }
    /* Primary-native invariant: empty ACK does not advance TX sequence. */
    state->inbound_ack_count += 1u;
    return 1;
}

static int r45_send_invite_ack(
    R35AttachedMediaSession *session,
    R45CallAdoptionState *state,
    const R35CtpEnvelopeView *invite_view) {
    if (!session || !state || !invite_view) return 0;
    r45_sync_generation(state, session);
    if (state->invite_ack_sent) return 0;
    if ((invite_view->flags & R35_CTP_FLAG_SYN_MASK) == 0u) return 0;
    if (!r45_emit_empty_ack_for_peer_frame(
            session, state, invite_view, "CALL_INVITE_ACK")) {
        return 0;
    }
    state->invite_ack_sent = 1;
    state->local_signaling_write_count += 1u;
    return 1;
}

static int r45_serialize_capabilities(
    unsigned char body[R45_CAPABILITIES_BODY_LEN],
    const R45RuntimeFields *runtime) {
    unsigned word;
    if (!body || !runtime) return 0;
    if (runtime->call_type > 0xffu) return 0;
    body[0] = 0x00u;
    body[1] = 0x03u;
    body[2] = (unsigned char)(runtime->call_type & 0xffu);
    body[3] = 0x00u;
    word = runtime->capability_word;
    body[4] = (unsigned char)(word & 0xffu);
    body[5] = (unsigned char)((word >> 8) & 0xffu);
    body[6] = (unsigned char)((word >> 16) & 0xffu);
    body[7] = (unsigned char)((word >> 24) & 0xffu);
    return 1;
}

static int r45_serialize_alerting(
    unsigned char body[R45_ALERTING_BODY_LEN],
    const R45RuntimeFields *runtime) {
    if (!body || !runtime) return 0;
    if (runtime->alerting_argument > 0xffu) return 0;
    body[0] = 0x00u;
    body[1] = 0x0au;
    body[2] = (unsigned char)(runtime->alerting_argument & 0xffu);
    return 1;
}

static int r45_send_local_capabilities(
    R35AttachedMediaSession *session,
    R45CallAdoptionState *state,
    const R45RuntimeFields *runtime) {
    unsigned char body[R45_CAPABILITIES_BODY_LEN];
    unsigned char packet[R45_PACKET_MAX_LEN];
    unsigned packet_len = 0u;
    unsigned sequence;
    if (!session || !state || !runtime) return 0;
    r45_sync_generation(state, session);
    if (!r35_call_ready(session)) return 0;
    if (!state->invite_ack_sent || state->local_capabilities_sent) return 0;
    if (!r45_serialize_capabilities(body, runtime)) return 0;

    sequence = session->call_sequence & 0xffu;
    if (!r45_build_packet(
            packet, &packet_len,
            R35_CTP_FLAG_DATA,
            session->call_ctp_connection,
            sequence,
            session->call_ack,
            body, R45_CAPABILITIES_BODY_LEN,
            session->source_logical,
            session->dest_logical)) {
        return 0;
    }
    if (!r45_emit(
            session, "CALL_CAPABILITIES", packet, packet_len,
            sequence, session->call_ack)) {
        return 0;
    }
    session->call_sequence = (sequence + 1u) & 0xffu;
    state->local_capabilities_sent = 1;
    state->local_signaling_write_count += 1u;
    return 1;
}

static int r45_send_local_alerting(
    R35AttachedMediaSession *session,
    R45CallAdoptionState *state,
    const R45RuntimeFields *runtime) {
    unsigned char body[R45_ALERTING_BODY_LEN];
    unsigned char packet[R45_PACKET_MAX_LEN];
    unsigned packet_len = 0u;
    unsigned sequence;
    if (!session || !state || !runtime) return 0;
    r45_sync_generation(state, session);
    if (!r35_call_ready(session)) return 0;
    if (!state->local_capabilities_sent || state->local_alerting_sent) return 0;
    if (!r45_serialize_alerting(body, runtime)) return 0;

    sequence = session->call_sequence & 0xffu;
    if (!r45_build_packet(
            packet, &packet_len,
            R35_CTP_FLAG_DATA,
            session->call_ctp_connection,
            sequence,
            session->call_ack,
            body, R45_ALERTING_BODY_LEN,
            session->source_logical,
            session->dest_logical)) {
        return 0;
    }
    if (!r45_emit(
            session, "CALL_ALERTING", packet, packet_len,
            sequence, session->call_ack)) {
        return 0;
    }
    session->call_sequence = (sequence + 1u) & 0xffu;
    state->local_alerting_sent = 1;
    state->local_signaling_write_count += 1u;
    return 1;
}

static int r45_call_adoption_complete(
    const R45CallAdoptionState *state,
    const R35AttachedMediaSession *session) {
    if (!state || !session) return 0;
    return state->generation == session->call_generation
        && state->invite_ack_sent
        && state->local_capabilities_sent
        && state->local_alerting_sent;
}

static int r45_accept_peer_data_and_ack(
    R35AttachedMediaSession *session,
    R45CallAdoptionState *state,
    const R35CtpEnvelopeView *view) {
    if (!session || !state || !view) return 0;
    r45_sync_generation(state, session);
    if (!r45_call_adoption_complete(state, session)) return 0;
    if (view->flags != R35_CTP_FLAG_DATA) return 0;
    return r45_emit_empty_ack_for_peer_frame(
        session, state, view, "CALL_PEER_DATA_ACK");
}
/* R45_CALL_ADOPTION_END */'''


def extract_core_region(text: str) -> str:
    if CORE_BEGIN_MARKER not in text or CORE_END_MARKER not in text:
        raise ValueError("R45 core markers missing")
    return text.split(CORE_BEGIN_MARKER, 1)[1].split(CORE_END_MARKER, 1)[0]


def report() -> str:
    return "\n".join(
        (
            "=== P116 R45 CALL ADOPTION C CORE ===",
            "PRIMARY_NATIVE_ACK_FLAGS=0x80",
            "PRIMARY_NATIVE_CAPABILITIES_OPCODE=0x0003",
            "PRIMARY_NATIVE_ALERTING_OPCODE=0x000A",
            "EMPTY_ACK_ADVANCES_TX_SEQUENCE=false",
            "PEER_DATA_ADVANCES_ACK_TO_SEQUENCE_PLUS_ONE=true",
            "NETWORK_IO=false",
            "PHYSICAL_CALLS=0",
            "PRODUCTION_WIRING_ADDED=false",
            "=== END P116 R45 CALL ADOPTION C CORE ===",
        )
    )


if __name__ == "__main__":
    print(report())
