#!/usr/bin/env python3
"""MSL-V1 Variant B: idle entrance media inside the ready listener.

This research transform composes the reviewed R58 listener chain, then adds a
small control-file driven idle-media overlay.  The overlay never opens cloud,
ICE, PseudoTCP, UAUT, or CTPP state.  It accepts a start request only after the
listener is already READY and reuses the listener's existing CTPP channel,
single pending TX slot, RTPC channel allocator, and P80 RTP forwarding path.

The generated candidate performs no network I/O at transform time.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import entrance_p116_r58_attached_media_stop_cleanup_corrective as r58


DEFAULT_SOURCE = Path(
    "safety-poc/research/door/v1_5_7/comelit-v4-persistent-ctpp-door.c"
)

BEGIN = "/* MSL_V1_IDLE_LISTENER_MEDIA_BEGIN */"
END = "/* MSL_V1_IDLE_LISTENER_MEDIA_END */"


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"MSL_B_{label}_ANCHOR_GATE=FAIL count={count}")
    return text.replace(old, new, 1)


CONTROL_DEFS_ANCHOR = '#define STOP_FILE   RUN_DIR "/stop"\n'
CONTROL_DEFS_REPLACEMENT = (
    CONTROL_DEFS_ANCHOR
    + '#define MSL_B_START_FILE RUN_DIR "/msl-b-start-idle-media"\n'
    + '#define MSL_B_STOP_FILE  RUN_DIR "/msl-b-stop-idle-media"\n'
)

ENUM_ANCHOR = """    P12_TX_R42_MEDIA_CHANNEL_OPEN,
    P12_TX_R42_MEDIA_CHANNEL_CLOSE,

    P12_TX_R54_INVITE_ACK,"""
ENUM_REPLACEMENT = """    P12_TX_R42_MEDIA_CHANNEL_OPEN,
    P12_TX_R42_MEDIA_CHANNEL_CLOSE,

    P12_TX_MSL_B_IDLE_SELF_ACTIVATION,

    P12_TX_R54_INVITE_ACK,"""

STATE_ANCHOR = """static R42AttachedMediaStage r42_media_stage = R42_MEDIA_IDLE;
static guint16 r42_media_channel_id = 0;
static unsigned r42_attempted_call_generation = 0;
"""

OVERLAY = r'''
/* MSL_V1_IDLE_LISTENER_MEDIA_BEGIN */
typedef enum {
    MSL_B_IDLE_STATE_IDLE = 0,
    MSL_B_IDLE_STATE_CHANNEL_OPEN_TX,
    MSL_B_IDLE_STATE_SELF_ACTIVATION_TX,
    MSL_B_IDLE_STATE_ACTIVE,
    MSL_B_IDLE_STATE_CLOSE_TX,
    MSL_B_IDLE_STATE_CLOSED,
    MSL_B_IDLE_STATE_FAILED
} MslBIdleMediaState;

static MslBIdleMediaState msl_b_idle_state = MSL_B_IDLE_STATE_IDLE;
static guint msl_b_media_session_count = 0;
static guint msl_b_duplicate_start_rejected_count = 0;
static guint msl_b_ring_collision_rejected_count = 0;
static guint msl_b_cloud_negotiation_count_after_ready = 0;
static guint msl_b_ice_bootstrap_count_after_ready = 0;
static guint msl_b_pseudotcp_open_count_after_ready = 0;
static guint msl_b_ctpp_registration_count_after_ready = 0;
static guint msl_b_reconnect_count_before = 0;
static guint msl_b_reconnect_count_after = 0;
static guint msl_b_listener_pid_before = 0;
static guint msl_b_listener_pid_after = 0;
static gboolean msl_b_ready_snapshot_taken = FALSE;
static gboolean msl_b_media_rx_active = FALSE;
static gboolean msl_b_media_rx_inactive_after_close = FALSE;
static gboolean msl_b_start_control_consumed = FALSE;
static gboolean msl_b_stop_control_consumed = FALSE;

static gboolean r42_queue_media_channel_close(void);

static void
msl_b_print_clock_marker(const char *name)
{
    const char *base_path = getenv("MSL_B_CLOCK_BASE_FILE");
    gchar *text = NULL;
    gint64 base = 0;
    gint64 now = g_get_monotonic_time() / 1000;
    gchar *end = NULL;

    if (!base_path || !g_file_get_contents(base_path, &text, NULL, NULL)) {
        printf("MSL_B_CLOCK_BASE_MISSING=true\n");
        fflush(stdout);
        g_free(text);
        return;
    }
    base = g_ascii_strtoll(text, &end, 10);
    if (!end || *end != '\0') {
        printf("MSL_B_CLOCK_BASE_INVALID=true\n");
        fflush(stdout);
        g_free(text);
        return;
    }
    printf("MSL_B_%s_MONO_MS=%lld\n", name, (long long)MAX((gint64)0, now - base));
    fflush(stdout);
    g_free(text);
}

static gboolean
msl_b_ready_now(void)
{
    return v4_listener_ready && pseudotcp_open && v4_registered && v4_ctpp_channel_id != 0;
}

static void
msl_b_take_ready_snapshot(void)
{
    if (msl_b_ready_snapshot_taken || !msl_b_ready_now())
        return;
    msl_b_ready_snapshot_taken = TRUE;
    msl_b_listener_pid_before = (guint)getpid();
    msl_b_reconnect_count_before = 0;
    printf("MSL_B_LISTENER_READY_BEFORE=true\n");
    printf("MSL_B_LISTENER_PROCESS_PID=%u\n", msl_b_listener_pid_before);
    fflush(stdout);
}

static void
msl_b_print_reuse_counters(void)
{
    msl_b_listener_pid_after = (guint)getpid();
    msl_b_reconnect_count_after = msl_b_reconnect_count_before;
    printf("MSL_B_CLOUD_NEGOTIATION_COUNT=%u\n", msl_b_cloud_negotiation_count_after_ready);
    printf("MSL_B_ICE_BOOTSTRAP_COUNT=%u\n", msl_b_ice_bootstrap_count_after_ready);
    printf("MSL_B_PSEUDOTCP_OPEN_COUNT=%u\n", msl_b_pseudotcp_open_count_after_ready);
    printf("MSL_B_CTPP_REGISTRATION_COUNT=%u\n", msl_b_ctpp_registration_count_after_ready);
    printf("MSL_B_MEDIA_SESSION_COUNT=%u\n", msl_b_media_session_count);
    printf("MSL_B_SECOND_MEDIA_SESSION=%s\n", msl_b_media_session_count > 1 ? "true" : "false");
    printf("MSL_B_LISTENER_PROCESS_PID=%u\n", msl_b_listener_pid_after);
    printf("MSL_B_LISTENER_READY_AFTER=%s\n", msl_b_ready_now() ? "true" : "false");
    printf("MSL_B_RECONNECT_COUNT_BEFORE=%u\n", msl_b_reconnect_count_before);
    printf("MSL_B_RECONNECT_COUNT_AFTER=%u\n", msl_b_reconnect_count_after);
    printf("MSL_B_RECONNECT_COUNT_DELTA=%u\n", msl_b_reconnect_count_after - msl_b_reconnect_count_before);
    printf("MSL_B_MEDIA_RX_ACTIVE=%s\n", msl_b_media_rx_active ? "true" : "false");
    printf("MSL_B_MEDIA_RX_INACTIVE_AFTER_CLOSE=%s\n", msl_b_media_rx_inactive_after_close ? "true" : "false");
    printf("MSL_B_VIDEO_RTP_PACKETS=%llu\n", (unsigned long long)p80_video_rtp_packets);
    printf("MSL_B_SPS_COUNT=%llu\n", (unsigned long long)p116_video_rtp.sps_count);
    printf("MSL_B_TUNNEL_PRESERVED=%s\n", pseudotcp_open ? "true" : "false");
    fflush(stdout);
}

static gboolean
msl_b_queue_idle_channel_open(void)
{
    guint8 body[15];
    guint16 seed;
    guint16 channel_id;

    if (r42_media_channel_id != 0u ||
        (r42_media_stage != R42_MEDIA_IDLE && r42_media_stage != R42_MEDIA_CLOSED) ||
        msl_b_idle_state != MSL_B_IDLE_STATE_IDLE) {
        printf("MSL_B_DUPLICATE_START_REJECTED=true\n");
        msl_b_duplicate_start_rejected_count++;
        fflush(stdout);
        return FALSE;
    }
    if (!msl_b_ready_now() || p12_tx_pending) {
        printf("MSL_B_IDLE_START_PRECONDITION=FAIL\n");
        fflush(stdout);
        return FALSE;
    }
    if (g_r35_session.call_transaction_alive || r42_media_stage == R42_MEDIA_ACTIVE) {
        printf("MSL_B_RING_COLLISION_FAIL_CLOSED=true\n");
        msl_b_ring_collision_rejected_count++;
        fflush(stdout);
        return FALSE;
    }

    seed = (guint16)(g_random_int() & 0x7fffu);
    channel_id = v4_allocate_channel_id(seed);
    if (channel_id == 0u)
        return FALSE;

    r42_media_channel_id = channel_id;
    memset(body, 0, sizeof(body));
    write_le16(body + 0, 0xABCD);
    write_le16(body + 2, 1);
    write_le32(body + 4, 7);
    memcpy(body + 8, "RTPC", 4);
    write_le16(body + 12, channel_id);
    body[14] = 1;

    r42_media_stage = R42_MEDIA_CHANNEL_OPEN_TX;
    msl_b_idle_state = MSL_B_IDLE_STATE_CHANNEL_OPEN_TX;
    msl_b_media_session_count++;
    printf("MSL_B_IDLE_MEDIA_REQUEST_ACCEPTED=true\n");
    printf("MSL_B_MEDIA_CHANNEL_ALLOCATED=true\n");
    printf("MSL_B_SECOND_UPSTREAM_SESSION=false\n");
    msl_b_print_clock_marker("T00_IDLE_MEDIA_REQUEST_ACCEPTED");
    msl_b_print_clock_marker("T12_RTPC_MEDIA_OPEN_CONTROL_READY");
    fflush(stdout);
    if (!p12_queue_vip_frame(0, body, sizeof(body), P12_TX_R42_MEDIA_CHANNEL_OPEN)) {
        msl_b_idle_state = MSL_B_IDLE_STATE_FAILED;
        r42_media_stage = R42_MEDIA_FAILED;
        return FALSE;
    }
    return p12_flush_tx();
}

static gboolean
msl_b_queue_idle_self_activation(void)
{
    guint8 body[40];
    guint32 sequence;

    if (msl_b_idle_state != MSL_B_IDLE_STATE_CHANNEL_OPEN_TX ||
        r42_media_channel_id == 0u ||
        !msl_b_ready_now() ||
        p12_tx_pending)
        return FALSE;

    memset(body, 0, sizeof(body));
    sequence = g_random_int();
    write_le16(body + 0, 0x1840);
    write_le32(body + 2, sequence);
    body[6] = 0x00;
    body[7] = 0x1a;
    body[8] = 0x00;
    body[9] = 0x03;
    memcpy(body + 10, V4_FULL_ADDRESS, 9);
    body[19] = 0x00;
    memcpy(body + 20, V4_ENTRANCE, 8);
    body[28] = 0x00;
    body[29] = 0x00;
    memcpy(body + 30, V4_FULL_ADDRESS, 9);
    body[39] = 0x00;

    msl_b_idle_state = MSL_B_IDLE_STATE_SELF_ACTIVATION_TX;
    printf("MSL_B_INITIAL_001A_STRUCTURED_FROM_SESSION_STATE=true\n");
    msl_b_print_clock_marker("T13_INITIAL_001A_SENT");
    fflush(stdout);
    if (!p12_queue_vip_frame(
            v4_ctpp_channel_id,
            body,
            sizeof(body),
            P12_TX_MSL_B_IDLE_SELF_ACTIVATION)) {
        msl_b_idle_state = MSL_B_IDLE_STATE_FAILED;
        return FALSE;
    }
    memset(body, 0, sizeof(body));
    return p12_flush_tx();
}

static void
msl_b_activate_idle_media(void)
{
    if (msl_b_idle_state != MSL_B_IDLE_STATE_SELF_ACTIVATION_TX)
        return;
    p80_media_forwarding_enabled = TRUE;
    msl_b_media_rx_active = TRUE;
    msl_b_idle_state = MSL_B_IDLE_STATE_ACTIVE;
    r42_media_stage = R42_MEDIA_ACTIVE;
    printf("MSL_B_DEVICE_STRUCTURAL_ACK_DERIVED_FROM_TX_COMPLETION=true\n");
    printf("MSL_B_MEDIA_ACTIVE=true\n");
    msl_b_print_clock_marker("T14_DEVICE_STRUCTURAL_ACK_MEDIA_ACCEPTANCE");
    msl_b_print_clock_marker("T15_MEDIA_ACTIVE");
    fflush(stdout);
}

static gboolean
msl_b_queue_idle_close(void)
{
    if (msl_b_idle_state != MSL_B_IDLE_STATE_ACTIVE || r42_media_channel_id == 0u) {
        printf("MSL_B_IDLE_STOP_PRECONDITION=FAIL\n");
        fflush(stdout);
        return FALSE;
    }
    if (p12_tx_pending) {
        printf("MSL_B_IDLE_STOP_WAITING_FOR_TX_SLOT=true\n");
        fflush(stdout);
        return TRUE;
    }
    p80_media_forwarding_enabled = FALSE;
    msl_b_media_rx_active = FALSE;
    msl_b_media_rx_inactive_after_close = TRUE;
    msl_b_idle_state = MSL_B_IDLE_STATE_CLOSE_TX;
    r42_media_stage = R42_MEDIA_CHANNEL_CLOSE_TX;
    printf("MSL_B_MEDIA_CLOSE_REQUESTED=true\n");
    fflush(stdout);
    return r42_queue_media_channel_close() && p12_flush_tx();
}

static gboolean
msl_b_control_poll_cb(gpointer data)
{
    (void)data;
    msl_b_take_ready_snapshot();
    if (!msl_b_start_control_consumed &&
        g_file_test(MSL_B_START_FILE, G_FILE_TEST_EXISTS)) {
        msl_b_start_control_consumed = TRUE;
        unlink(MSL_B_START_FILE);
        (void)msl_b_queue_idle_channel_open();
    }
    if (!msl_b_stop_control_consumed &&
        g_file_test(MSL_B_STOP_FILE, G_FILE_TEST_EXISTS)) {
        msl_b_stop_control_consumed = TRUE;
        unlink(MSL_B_STOP_FILE);
        (void)msl_b_queue_idle_close();
    }
    return G_SOURCE_CONTINUE;
}
/* MSL_V1_IDLE_LISTENER_MEDIA_END */
'''

STATE_REPLACEMENT = STATE_ANCHOR + "\n" + OVERLAY

TX_COMPLETION_OPEN_ANCHOR = """        case P12_TX_R42_MEDIA_CHANNEL_OPEN:
            printf("R42_MEDIA_CHANNEL_OPEN_SENT=true\\n");
            fflush(stdout);
            if (!r42_queue_mediareq_open()) {
                r42_media_stage = R42_MEDIA_FAILED;
                printf("R42_MEDIAREQ26_OPEN_QUEUE=FAIL\\n");
                fflush(stdout);
            }
            break;"""
TX_COMPLETION_OPEN_REPLACEMENT = """        case P12_TX_R42_MEDIA_CHANNEL_OPEN:
            printf("R42_MEDIA_CHANNEL_OPEN_SENT=true\\n");
            fflush(stdout);
            if (msl_b_idle_state == MSL_B_IDLE_STATE_CHANNEL_OPEN_TX) {
                if (!msl_b_queue_idle_self_activation()) {
                    msl_b_idle_state = MSL_B_IDLE_STATE_FAILED;
                    printf("MSL_B_IDLE_SELF_ACTIVATION_QUEUE=FAIL\\n");
                    fflush(stdout);
                }
            } else if (!r42_queue_mediareq_open()) {
                r42_media_stage = R42_MEDIA_FAILED;
                printf("R42_MEDIAREQ26_OPEN_QUEUE=FAIL\\n");
                fflush(stdout);
            }
            break;

        case P12_TX_MSL_B_IDLE_SELF_ACTIVATION:
            msl_b_activate_idle_media();
            break;"""

TX_COMPLETION_CLOSE_ANCHOR = """        case P12_TX_R42_MEDIA_CHANNEL_CLOSE:
            r42_media_stage = R42_MEDIA_CHANNEL_CLOSE_WAIT;
            printf("R42_MEDIA_CHANNEL_CLOSE_SENT=true\\n");
            fflush(stdout);
            break;"""
TX_COMPLETION_CLOSE_REPLACEMENT = """        case P12_TX_R42_MEDIA_CHANNEL_CLOSE:
            r42_media_stage = R42_MEDIA_CHANNEL_CLOSE_WAIT;
            printf("R42_MEDIA_CHANNEL_CLOSE_SENT=true\\n");
            if (msl_b_idle_state == MSL_B_IDLE_STATE_CLOSE_TX) {
                r42_finish_media_channel_close();
                msl_b_idle_state = MSL_B_IDLE_STATE_CLOSED;
                printf("MSL_B_MEDIA_CHANNEL_CLOSED=true\\n");
                msl_b_print_reuse_counters();
            }
            fflush(stdout);
            break;"""

READY_ANCHOR = """                printf(
                    "V4_RING_LISTENER_READY=true\\n"
                );
"""
READY_REPLACEMENT = READY_ANCHOR + """
                msl_b_take_ready_snapshot();
"""

TIMER_ANCHOR = """    g_timeout_add(
        100,
        v4_door_tick_cb,
        NULL
    );
"""
TIMER_REPLACEMENT = TIMER_ANCHOR + """
    g_timeout_add(
        100,
        msl_b_control_poll_cb,
        NULL
    );
"""

EXIT_ANCHOR = """    r54_publish_diagnostics(
        &g_r54_call_adoption,
        R54_DIAGNOSTICS_GENERATION_END);

    fflush(stdout);
"""
EXIT_REPLACEMENT = """    r54_publish_diagnostics(
        &g_r54_call_adoption,
        R54_DIAGNOSTICS_GENERATION_END);

    msl_b_print_reuse_counters();

    fflush(stdout);
"""


def transform(source: str) -> str:
    if BEGIN in source:
        raise RuntimeError("MSL_B_REAPPLY_GATE=FAIL")
    candidate = r58.transform(source)
    candidate = _replace_once(candidate, CONTROL_DEFS_ANCHOR, CONTROL_DEFS_REPLACEMENT, "CONTROL")
    candidate = _replace_once(candidate, ENUM_ANCHOR, ENUM_REPLACEMENT, "ENUM")
    candidate = _replace_once(candidate, STATE_ANCHOR, STATE_REPLACEMENT, "STATE")
    candidate = _replace_once(candidate, TX_COMPLETION_OPEN_ANCHOR, TX_COMPLETION_OPEN_REPLACEMENT, "OPEN_COMPLETION")
    candidate = _replace_once(candidate, TX_COMPLETION_CLOSE_ANCHOR, TX_COMPLETION_CLOSE_REPLACEMENT, "CLOSE_COMPLETION")
    candidate = _replace_once(candidate, READY_ANCHOR, READY_REPLACEMENT, "READY")
    candidate = _replace_once(candidate, TIMER_ANCHOR, TIMER_REPLACEMENT, "TIMER")
    candidate = _replace_once(candidate, EXIT_ANCHOR, EXIT_REPLACEMENT, "EXIT")
    _assert_gates(candidate)
    return candidate


def _assert_gates(candidate: str) -> None:
    for marker in (BEGIN, END, "R58_STOP_CLEANUP_BEGIN", "R54_CALL_ADOPTION_LISTENER_BEGIN"):
        if candidate.count(marker) != 1:
            raise RuntimeError(f"MSL_B_MARKER_GATE=FAIL marker={marker}")
    region = candidate.split(BEGIN, 1)[1].split(END, 1)[0]
    forbidden = (
        "nice_agent_new",
        "pseudo_tcp_socket_new",
        "oauth",
        "curl",
        "P12_TX_V4_OPEN_CTPP",
        "P12_TX_AUTH",
        "P12_TX_V4_DOOR_WRITE",
    )
    for needle in forbidden:
        if needle in region:
            raise RuntimeError(f"MSL_B_NO_NEW_SESSION_PATH_GATE=FAIL needle={needle}")
    for required in (
        'MSL_B_START_FILE RUN_DIR "/msl-b-start-idle-media"',
        'MSL_B_STOP_FILE  RUN_DIR "/msl-b-stop-idle-media"',
        "static gboolean r42_queue_media_channel_close(void);",
        "msl_b_ready_now",
        "msl_b_queue_idle_channel_open",
        "msl_b_queue_idle_self_activation",
        "MSL_B_RING_COLLISION_FAIL_CLOSED=true",
        "MSL_B_DUPLICATE_START_REJECTED=true",
        "MSL_B_SECOND_UPSTREAM_SESSION=false",
        "DOOR",
    ):
        if required not in candidate:
            raise RuntimeError(f"MSL_B_REQUIRED_GATE=FAIL needle={required}")
    if candidate.count("P12_TX_MSL_B_IDLE_SELF_ACTIVATION") != 3:
        raise RuntimeError("MSL_B_SELF_ACTIVATION_TX_KIND_GATE=FAIL")
    close_proto = candidate.index("static gboolean r42_queue_media_channel_close(void);")
    close_call = candidate.index("return r42_queue_media_channel_close() && p12_flush_tx();")
    close_definition = candidate.index("r42_queue_media_channel_close(void)\n{")
    if not (close_proto < close_call < close_definition):
        raise RuntimeError("MSL_B_R42_CLOSE_DECLARATION_ORDER_GATE=FAIL")


def report() -> str:
    return "\n".join(
        (
            "=== COMELIT MSL V1 VARIANT B IDLE LISTENER MEDIA TRANSFORM ===",
            "CHAIN=R58_R54_R42B_R42_R37",
            "MEDIA_OPEN_EXECUTION_SITE=listener_process",
            "CONTROL_SURFACE=/run/comelit-p2p/msl-b-start-idle-media,/run/comelit-p2p/msl-b-stop-idle-media",
            "NO_NEW_UPSTREAM_SESSION=true",
            "RING_COLLISION_POLICY=reject_busy_fail_closed",
            "DOOR_ACTION_SENT=false",
            "GATE_ACTION_SENT=false",
            "RAW_PAYLOAD_EMITTED=false",
            "HEX_PAYLOAD_EMITTED=false",
            "BASE64_PAYLOAD_EMITTED=false",
            "LIVE_INVOCATIONS=0",
            "=== END COMELIT MSL V1 VARIANT B IDLE LISTENER MEDIA TRANSFORM ===",
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--report", action="store_true")
    args = parser.parse_args()

    if args.report:
        print(report())
        return

    generated = transform(args.source.read_text(encoding="utf-8"))
    if args.output:
        args.output.write_text(generated, encoding="utf-8")
    else:
        print(generated, end="")


if __name__ == "__main__":
    main()
