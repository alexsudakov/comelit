#!/usr/bin/env python3
"""Research-only transform for graceful persistent-listener PseudoTCP shutdown.

The official Comelit Android captures both start transport teardown with a
client-to-device FIN.  The current native STOP_FILE path only quits the GLib
loop and never asks PseudoTCP to close.  This transform changes only that stop
boundary:

* drain any already-buffered receive bytes before close, because libnice warns
  that unread receive data can turn a graceful close into RST;
* call pseudo_tcp_socket_close(..., FALSE) exactly once when PseudoTCP is open;
* keep the GLib loop alive for a bounded period while existing PseudoTCP clocks
  and ICE receive callbacks complete the FIN handshake;
* quit early when pseudo_tcp_socket_get_next_clock() reports the socket is
  fully closed, otherwise quit at a bounded timeout without forcing RST.

It does not perform network I/O itself and does not modify production files.
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
    state_anchor = """static gboolean pseudotcp_started = FALSE;
static gboolean pseudotcp_open = FALSE;

static guint pseudotcp_packets_in = 0;
"""
    state_replacement = """static gboolean pseudotcp_started = FALSE;
static gboolean pseudotcp_open = FALSE;

/* Research-only graceful shutdown state. */
#define PSEUDOTCP_GRACEFUL_STOP_TIMEOUT_MS 5000
#define PSEUDOTCP_GRACEFUL_STOP_POLL_MS     100

static gboolean pseudotcp_graceful_stop_started = FALSE;
static gint64 pseudotcp_graceful_stop_deadline_us = 0;

static guint pseudotcp_packets_in = 0;
"""
    source = _replace_once(
        source,
        state_anchor,
        state_replacement,
        "graceful stop state",
    )

    stop_anchor = """static gboolean
stop_check_cb(gpointer data)
{
    (void)data;

    if (g_file_test(STOP_FILE, G_FILE_TEST_EXISTS)) {
        printf(\"ICE_HOLDER_STOP=true\\n\");

        if (loop)
            g_main_loop_quit(loop);

        return G_SOURCE_REMOVE;
    }

    return G_SOURCE_CONTINUE;
}
"""

    stop_replacement = """static guint
pseudotcp_drain_before_graceful_close(void)
{
    guint total = 0;
    gchar discard[4096];

    if (!pseudo_tcp)
        return 0;

    while (TRUE) {
        gint n = pseudo_tcp_socket_recv(
            pseudo_tcp,
            discard,
            sizeof(discard)
        );

        if (n > 0) {
            total += (guint)n;
            memset(discard, 0, (gsize)n);
            continue;
        }

        if (n == 0)
            break;

        gint err = pseudo_tcp_socket_get_error(pseudo_tcp);
        if (err == EWOULDBLOCK || err == ENOTCONN)
            break;

        printf(
            \"PSEUDOTCP_GRACEFUL_CLOSE_DRAIN_ERROR=%d\\n\",
            err
        );
        break;
    }

    memset(discard, 0, sizeof(discard));
    return total;
}


static gboolean
pseudotcp_graceful_stop_poll_cb(gpointer data)
{
    (void)data;

    if (!pseudo_tcp) {
        printf(\"PSEUDOTCP_GRACEFUL_CLOSE_COMPLETE=true\\n\");
        fflush(stdout);
        if (loop)
            g_main_loop_quit(loop);
        return G_SOURCE_REMOVE;
    }

    guint64 next_clock = 0;
    if (!pseudo_tcp_socket_get_next_clock(pseudo_tcp, &next_clock)) {
        printf(\"PSEUDOTCP_GRACEFUL_CLOSE_COMPLETE=true\\n\");
        printf(\"PSEUDOTCP_GRACEFUL_CLOSE_TIMEOUT=false\\n\");
        fflush(stdout);
        if (loop)
            g_main_loop_quit(loop);
        return G_SOURCE_REMOVE;
    }

    if (g_get_monotonic_time() >= pseudotcp_graceful_stop_deadline_us) {
        printf(\"PSEUDOTCP_GRACEFUL_CLOSE_COMPLETE=false\\n\");
        printf(\"PSEUDOTCP_GRACEFUL_CLOSE_TIMEOUT=true\\n\");
        printf(\"PSEUDOTCP_GRACEFUL_CLOSE_FORCE_RST_SENT=false\\n\");
        fflush(stdout);
        if (loop)
            g_main_loop_quit(loop);
        return G_SOURCE_REMOVE;
    }

    return G_SOURCE_CONTINUE;
}


static gboolean
stop_check_cb(gpointer data)
{
    (void)data;

    if (!g_file_test(STOP_FILE, G_FILE_TEST_EXISTS))
        return G_SOURCE_CONTINUE;

    if (pseudotcp_graceful_stop_started)
        return G_SOURCE_CONTINUE;

    pseudotcp_graceful_stop_started = TRUE;
    printf(\"ICE_HOLDER_STOP=true\\n\");

    if (!pseudo_tcp || !pseudotcp_open) {
        printf(\"PSEUDOTCP_GRACEFUL_CLOSE_SKIPPED_NOT_OPEN=true\\n\");
        fflush(stdout);
        if (loop)
            g_main_loop_quit(loop);
        return G_SOURCE_REMOVE;
    }

    guint drained = pseudotcp_drain_before_graceful_close();
    printf(
        \"PSEUDOTCP_GRACEFUL_CLOSE_DRAINED_BYTES=%u\\n\",
        drained
    );

    /*
     * libnice documents force=FALSE as graceful close.  It sends FIN after
     * pending data and does not intentionally send RST.  Keep the main loop
     * alive so the existing PseudoTCP clock and ICE receive paths can finish
     * the close handshake.
     */
    pseudo_tcp_socket_close(pseudo_tcp, FALSE);
    printf(\"PSEUDOTCP_GRACEFUL_CLOSE_REQUESTED=true\\n\");
    printf(\"PSEUDOTCP_GRACEFUL_CLOSE_FORCE=false\\n\");

    pseudotcp_graceful_stop_deadline_us =
        g_get_monotonic_time() +
        ((gint64)PSEUDOTCP_GRACEFUL_STOP_TIMEOUT_MS * 1000);

    guint timer = g_timeout_add(
        PSEUDOTCP_GRACEFUL_STOP_POLL_MS,
        pseudotcp_graceful_stop_poll_cb,
        NULL
    );

    if (timer == 0) {
        fprintf(stderr, \"PSEUDOTCP_GRACEFUL_CLOSE_POLL_START=FAIL\\n\");
        if (loop)
            g_main_loop_quit(loop);
        return G_SOURCE_REMOVE;
    }

    printf(\"PSEUDOTCP_GRACEFUL_CLOSE_POLL_START=PASS\\n\");
    printf(\"PSEUDOTCP_GRACEFUL_CLOSE_FORCE_RST_SENT=false\\n\");
    fflush(stdout);

    return G_SOURCE_CONTINUE;
}
"""

    source = _replace_once(
        source,
        stop_anchor,
        stop_replacement,
        "stop callback",
    )
    return source


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    candidate = transform(args.source.read_text(encoding="utf-8"))
    args.output.write_text(candidate, encoding="utf-8")

    print("PSEUDOTCP_GRACEFUL_STOP_TRANSFORM=PASS")
    print("PSEUDOTCP_GRACEFUL_CLOSE_FORCE=false")
    print("PSEUDOTCP_GRACEFUL_CLOSE_FORCE_RST_SENT=false")
    print("NETWORK_IO_PERFORMED=false")
    print("HOME_ASSISTANT_TOUCHED=false")
    print("DOOR_ACTION_SENT=false")
    print("SELF_ACTIVATION_SENT=false")
    print("MEDIA_SIGNALING_SENT=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
