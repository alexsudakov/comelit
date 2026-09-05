#!/usr/bin/env python3
"""Generate a research candidate that preserves early PseudoTCP datagrams.

The production listener currently creates its PseudoTcpSocket only after ICE
reaches READY.  Nice application payload can arrive before that point.  The
current recv callback logs PSEUDOTCP_RX_BEFORE_START and discards the datagram.

This transform is intentionally research-only.  It does not perform network
I/O and does not modify the production native binary.  It preserves datagram
boundaries in a small bounded queue, creates the PseudoTcpSocket at ICE READY,
replays the queued packets while the socket is still in its initial LISTEN
state, and calls pseudo_tcp_socket_connect() only if replay did not already
advance the peer-initiated handshake.
"""

from __future__ import annotations

import argparse
from pathlib import Path


DEFAULT_SOURCE = Path(
    "safety-poc/research/door/v1_5_3/comelit-v4-persistent-ctpp-door.c"
)


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)


def transform(source: str) -> str:
    state_anchor = """static guint64 pseudotcp_app_bytes_in = 0;

#define APP_CAPTURE_MAX 64
"""
    state_replacement = """static guint64 pseudotcp_app_bytes_in = 0;

/*
 * Nice may deliver peer PseudoTCP datagrams before the component reaches
 * READY and before start_pseudotcp() has created the socket.  Dropping such a
 * datagram creates a timing race in the handshake.  Preserve packet boundaries
 * in a deliberately small bounded queue and replay only after ICE is READY.
 */
#define PSEUDOTCP_PRESTART_MAX_PACKETS 8
#define PSEUDOTCP_PRESTART_MAX_LEN     2048

static guint8 pseudotcp_prestart_packets[
    PSEUDOTCP_PRESTART_MAX_PACKETS
][PSEUDOTCP_PRESTART_MAX_LEN];
static guint16 pseudotcp_prestart_lengths[PSEUDOTCP_PRESTART_MAX_PACKETS];
static guint pseudotcp_prestart_count = 0;

#define APP_CAPTURE_MAX 64
"""
    source = _replace_once(
        source,
        state_anchor,
        state_replacement,
        "prestart state",
    )

    recv_anchor = """    if (!pseudo_tcp) {
        printf(
            \"PSEUDOTCP_RX_BEFORE_START=%u\\n\",
            len
        );

        fflush(stdout);
        return;
    }
"""
    recv_replacement = """    if (!pseudo_tcp) {
        if (len > PSEUDOTCP_PRESTART_MAX_LEN ||
            pseudotcp_prestart_count >= PSEUDOTCP_PRESTART_MAX_PACKETS) {

            fprintf(
                stderr,
                \"PSEUDOTCP_PRESTART_BUFFER=FAIL LEN=%u COUNT=%u\\n\",
                len,
                pseudotcp_prestart_count
            );

            failed = TRUE;

            if (loop)
                g_main_loop_quit(loop);

            return;
        }

        memcpy(
            pseudotcp_prestart_packets[pseudotcp_prestart_count],
            buf,
            len
        );
        pseudotcp_prestart_lengths[pseudotcp_prestart_count] =
            (guint16)len;
        pseudotcp_prestart_count++;

        printf(
            \"PSEUDOTCP_RX_BUFFERED=%u LEN=%u\\n\",
            pseudotcp_prestart_count,
            len
        );

        fflush(stdout);
        return;
    }
"""
    source = _replace_once(
        source,
        recv_anchor,
        recv_replacement,
        "recv prestart queue",
    )

    helper_anchor = """static gboolean
start_pseudotcp(void)
{
"""
    helper = """static gboolean
replay_pseudotcp_prestart_packets(void)
{
    if (!pseudo_tcp)
        return FALSE;

    for (guint i = 0; i < pseudotcp_prestart_count; i++) {
        guint len = pseudotcp_prestart_lengths[i];

        if (!pseudo_tcp_socket_notify_packet(
                pseudo_tcp,
                (const gchar *)pseudotcp_prestart_packets[i],
                len)) {

            fprintf(
                stderr,
                \"PSEUDOTCP_PRESTART_REPLAY=FAIL INDEX=%u LEN=%u\\n\",
                i + 1,
                len
            );

            return FALSE;
        }

        printf(
            \"PSEUDOTCP_PRESTART_REPLAY=PASS INDEX=%u LEN=%u\\n\",
            i + 1,
            len
        );
    }

    if (pseudotcp_prestart_count > 0) {
        printf(
            \"PSEUDOTCP_PRESTART_REPLAY_COUNT=%u\\n\",
            pseudotcp_prestart_count
        );
    }

    pseudotcp_prestart_count = 0;
    memset(
        pseudotcp_prestart_lengths,
        0,
        sizeof(pseudotcp_prestart_lengths)
    );

    fflush(stdout);
    return TRUE;
}


static gboolean
start_pseudotcp(void)
{
"""
    source = _replace_once(
        source,
        helper_anchor,
        helper,
        "prestart replay helper",
    )

    connect_anchor = """    /*
     * Comelit client is the PseudoTCP initiator,
     * even though its ICE role is CONTROLLED.
     */
    if (!pseudo_tcp_socket_connect(
            pseudo_tcp)) {

        fprintf(
            stderr,
            \"PSEUDOTCP_CONNECT_START=FAIL \"
            \"ERROR=%d\\n\",
            pseudo_tcp_socket_get_error(
                pseudo_tcp
            )
        );

        return FALSE;
    }

    printf(
        \"PSEUDOTCP_CONNECT_START=PASS\\n\"
    );

    fflush(stdout);

    return TRUE;
"""
    connect_replacement = """    /*
     * Replay peer data only after ICE is READY so WritePacket can use the
     * selected pair.  PseudoTcpSocket starts in LISTEN.  A replayed peer SYN
     * may therefore advance it to SYN_RECEIVED/ESTABLISHED before we initiate
     * locally; in that case calling connect() would be invalid and is skipped.
     */
    if (!replay_pseudotcp_prestart_packets())
        return FALSE;

    guint pseudotcp_state = PSEUDO_TCP_CLOSED;
    g_object_get(
        pseudo_tcp,
        \"state\",
        &pseudotcp_state,
        NULL
    );

    printf(
        \"PSEUDOTCP_STATE_AFTER_PRESTART_REPLAY=%u\\n\",
        pseudotcp_state
    );

    if (pseudotcp_state == PSEUDO_TCP_LISTEN) {
        if (!pseudo_tcp_socket_connect(
                pseudo_tcp)) {

            fprintf(
                stderr,
                \"PSEUDOTCP_CONNECT_START=FAIL \"
                \"ERROR=%d\\n\",
                pseudo_tcp_socket_get_error(
                    pseudo_tcp
                )
            );

            return FALSE;
        }

        printf(\"PSEUDOTCP_CONNECT_START=PASS\\n\");
    } else if (
        pseudotcp_state == PSEUDO_TCP_SYN_RECEIVED ||
        pseudotcp_state == PSEUDO_TCP_ESTABLISHED
    ) {
        printf(
            \"PSEUDOTCP_CONNECT_START=SKIPPED_PEER_INITIATED\\n\"
        );
    } else {
        fprintf(
            stderr,
            \"PSEUDOTCP_STATE_AFTER_PRESTART_REPLAY=FAIL STATE=%u\\n\",
            pseudotcp_state
        );
        return FALSE;
    }

    fflush(stdout);

    return TRUE;
"""
    source = _replace_once(
        source,
        connect_anchor,
        connect_replacement,
        "conditional PseudoTCP connect",
    )

    return source


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    source = args.source.read_text(encoding="utf-8")
    candidate = transform(source)
    args.output.write_text(candidate, encoding="utf-8")

    print("PSEUDOTCP_PRESTART_TRANSFORM=PASS")
    print("NETWORK_IO_PERFORMED=false")
    print("DOOR_ACTION_SENT=false")
    print("MEDIA_ACTION_SENT=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
