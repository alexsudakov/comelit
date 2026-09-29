#!/usr/bin/env python3
"""P122: Entrance Door on the active on-demand media session.

Composes the shipped P121 media helper and adds one Entrance-only Door
entrypoint owned by that same helper. It reuses the already active CTPP/P2P
session, never resumes the persistent listener, never promotes Gate semantics,
and never retries a Door operation.
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import entrance_p121_gather_initial_timeout_transform as p121
from entrance_p106_teardown_state_classification_transform import DEFAULT_SOURCE

BEGIN = "/* P122_ON_DEMAND_DOOR_BEGIN */"
END = "/* P122_ON_DEMAND_DOOR_END */"


def _replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {count}")
    return source.replace(old, new, 1)


_ENUM_OLD = """    R27_TX_RTPC_CLIENT_001A_REPEAT,

    P95_TX_DEVICE_0002_ACK,
"""
_ENUM_NEW = """    R27_TX_RTPC_CLIENT_001A_REPEAT,
    P122_TX_ON_DEMAND_DOOR,

    P95_TX_DEVICE_0002_ACK,
"""

_STATE_ANCHOR = """static gboolean p97_signaling_finished = FALSE;

/* R27 bounded same-session periodic refresh 0x001A research state. */
"""
_STATE_REPLACEMENT = r'''static gboolean p97_signaling_finished = FALSE;

/* P122 on-demand media-owned Entrance Door state. */
#define P122_DOOR_PACKET_LEN 48u
#define P122_DOOR_SETTLE_MS 1000u
static volatile sig_atomic_t p122_door_signal_pending = 0;
static gboolean p122_door_queued = FALSE;
static gboolean p122_door_waiting_ack = FALSE;
static gboolean p122_door_ack_observed = FALSE;
static guint32 p122_door_counter = 0u;

static void p122_door_signal_handler(int signum);
static gboolean p122_on_demand_door_busy(void);
static gboolean p122_on_demand_door_tick_cb(gpointer data);
static gboolean p122_on_demand_door_settle_cb(gpointer data);
static gboolean p122_note_door_ack(
    guint16 request_id,
    const guint8 *body,
    guint body_len);
static void p122_emit_door_result(const char *result);
static gboolean p122_commit_counter_baseline(void);

/* R27 bounded same-session periodic refresh 0x001A research state. */
'''

_HELPER_ANCHOR = """/* === R27_REPEAT_001A_BEGIN === */
static void
r27_cancel_repeat_timers(void)
"""
_HELPERS = r'''/* P122_ON_DEMAND_DOOR_BEGIN */
static void
p122_door_signal_handler(int signum)
{
    (void)signum;
    p122_door_signal_pending = 1;
}

static gboolean
p122_on_demand_door_busy(void)
{
    return p122_door_queued || p122_door_waiting_ack;
}

static guint32
p122_current_media_counter(void)
{
    if (p122_door_counter != 0u)
        return p122_door_counter;
    if (r27_repeat_001a_sent_count > 0u && r27_repeat_001a_sequence != 0u)
        return r27_repeat_001a_sequence;
    return r27_initial_001a_sequence;
}

static guint32
p122_next_media_counter(guint32 current)
{
    guint32 next_byte4 =
        ((((current >> 16u) & 0xffu) + 1u) & 0xffu) << 16u;
    return (current & 0xff00ffffu) | next_byte4;
}

static void
p122_write_padded_ascii(guint8 *out, const char *value, guint width)
{
    guint i;
    memset(out, 0, width);
    if (!value)
        return;
    for (i = 0; i < width && value[i] != '\0'; i++)
        out[i] = (guint8)value[i];
}

static gboolean
p122_serialize_door(guint8 out[P122_DOOR_PACKET_LEN], guint32 counter)
{
    memset(out, 0, P122_DOOR_PACKET_LEN);
    write_le16(out + 0u, 0x1840u);
    write_le32(out + 2u, counter);
    out[6] = 0x00u;
    out[7] = 0x0du;
    out[8] = 0x00u;
    out[9] = 0x2du;
    p122_write_padded_ascii(out + 10u, V4_ENTRANCE, 10u);
    write_le32(out + 20u, 1u);
    memset(out + 24u, 0xff, 4u);
    p122_write_padded_ascii(out + 28u, V4_FULL_ADDRESS, 10u);
    p122_write_padded_ascii(out + 38u, V4_APT_ADDRESS, 10u);

    return out[0] == 0x40u &&
        out[1] == 0x18u &&
        out[6] == 0x00u &&
        out[7] == 0x0du &&
        out[8] == 0x00u &&
        out[9] == 0x2du &&
        out[20] == 0x01u &&
        out[21] == 0x00u &&
        out[22] == 0x00u &&
        out[23] == 0x00u &&
        out[24] == 0xffu &&
        out[25] == 0xffu &&
        out[26] == 0xffu &&
        out[27] == 0xffu;
}

static gboolean
p122_door_ready(void)
{
    return entrance_signal_stage == ENTRANCE_SIGNAL_OBSERVE_MEDIA &&
        p78_rtpc_stage == P78_RTPC_COMPLETE &&
        p80_media_forwarding_enabled &&
        pseudo_tcp &&
        pseudotcp_open &&
        !pseudotcp_graceful_stop_started &&
        v4_registered &&
        v4_ctpp_channel_id != 0u &&
        !p12_tx_pending &&
        !r27_repeat_outstanding &&
        !r27_refresh_fail_closed &&
        !p122_on_demand_door_busy() &&
        r27_initial_001a_sent_count == 1u &&
        r27_initial_001a_sequence != 0u;
}

static void
p122_emit_door_result(const char *result)
{
    printf("P122_ON_DEMAND_DOOR_ACK_OBSERVED=%s\n",
        p122_door_ack_observed ? "true" : "false");
    printf("P122_ON_DEMAND_DOOR_DOOR_SPECIFIC_ACK_PROVEN=false\n");
    printf("P122_ON_DEMAND_DOOR_AUTOMATIC_RETRY_ALLOWED=false\n");
    printf("P122_ON_DEMAND_DOOR_PHYSICAL_EFFECT_ASSERTED=false\n");
    printf("P122_ON_DEMAND_DOOR_RESULT=%s\n", result);
    fflush(stdout);
    p122_door_queued = FALSE;
    p122_door_waiting_ack = FALSE;
    p122_door_ack_observed = FALSE;
}

static gboolean
p122_on_demand_door_settle_cb(gpointer data)
{
    (void)data;
    if (!p122_door_waiting_ack)
        return G_SOURCE_REMOVE;
    p122_emit_door_result("UNKNOWN_OUTCOME");
    return G_SOURCE_REMOVE;
}

static gboolean
p122_queue_door(void)
{
    guint8 packet[P122_DOOR_PACKET_LEN];
    guint32 current_counter;
    guint32 next_counter;

    if (!p122_door_ready())
        return FALSE;

    current_counter = p122_current_media_counter();
    next_counter = p122_next_media_counter(current_counter);
    if (!p122_serialize_door(packet, next_counter))
        return FALSE;

    if (!p12_queue_vip_frame(
            v4_ctpp_channel_id,
            packet,
            sizeof(packet),
            P122_TX_ON_DEMAND_DOOR)) {
        memset(packet, 0, sizeof(packet));
        return FALSE;
    }
    memset(packet, 0, sizeof(packet));

    p122_door_counter = next_counter;
    p122_door_queued = TRUE;
    p122_door_ack_observed = FALSE;
    printf("P122_ON_DEMAND_DOOR_COMMAND_ACCEPTED=true\n");
    printf("P122_ON_DEMAND_DOOR_PATH=MEDIA_SESSION_SINGLE\n");
    printf("P122_ON_DEMAND_DOOR_EXISTING_CTPP_REUSED=true\n");
    printf("P122_ON_DEMAND_DOOR_QUEUED=true\n");
    fflush(stdout);

    if (!p12_flush_tx()) {
        p122_door_queued = FALSE;
        return FALSE;
    }
    return TRUE;
}

static gboolean
p122_on_demand_door_tick_cb(gpointer data)
{
    (void)data;
    if (!p122_door_signal_pending)
        return G_SOURCE_CONTINUE;

    p122_door_signal_pending = 0;
    if (!p122_door_ready()) {
        printf("P122_ON_DEMAND_DOOR_COMMAND_ACCEPTED=false\n");
        p122_emit_door_result("REJECTED_NOT_READY");
        return G_SOURCE_CONTINUE;
    }

    if (!p122_queue_door()) {
        p122_emit_door_result("FAILED_SAFE");
        return G_SOURCE_CONTINUE;
    }
    return G_SOURCE_CONTINUE;
}

static gboolean
p122_commit_counter_baseline(void)
{
    if (p78_rtpc_client_001a_len != 60u)
        return FALSE;
    write_le32(p78_rtpc_client_001a + 2u, p122_door_counter);
    r27_initial_001a_sequence = p122_door_counter;
    return TRUE;
}

static gboolean
p122_note_door_ack(guint16 request_id, const guint8 *body, guint body_len)
{
    if (!p122_door_waiting_ack ||
        request_id != v4_ctpp_channel_id ||
        !body ||
        body_len < 8u)
        return FALSE;

    if (read_le16(body + 0u) == 0x1800u &&
        body[6] == 0x00u &&
        body[7] == 0x00u) {
        p122_door_ack_observed = TRUE;
        return TRUE;
    }
    return FALSE;
}
/* P122_ON_DEMAND_DOOR_END */

/* === R27_REPEAT_001A_BEGIN === */
static void
r27_cancel_repeat_timers(void)
'''

_TX_CASE_ANCHOR = r'''        case R27_TX_RTPC_CLIENT_001A_REPEAT:
            r27_repeat_001a_sent_count++;
'''
_TX_CASE_REPLACEMENT = r'''        case P122_TX_ON_DEMAND_DOOR:
            p122_door_queued = FALSE;
            p122_door_waiting_ack = TRUE;
            if (p122_commit_counter_baseline()) {
                printf("P122_ON_DEMAND_DOOR_COUNTER_BASELINE_ADVANCED=true\n");
            } else {
                r27_refresh_fail_closed = TRUE;
                printf("P122_ON_DEMAND_DOOR_COUNTER_BASELINE_ADVANCED=false\n");
                printf("P122_REFRESH_FAIL_CLOSED=true\n");
            }
            printf("P122_ON_DEMAND_DOOR_SENT=true\n");
            printf("P122_ON_DEMAND_DOOR_WRITE_COUNT=1\n");
            fflush(stdout);
            if (g_timeout_add(
                    P122_DOOR_SETTLE_MS,
                    p122_on_demand_door_settle_cb,
                    NULL) == 0u) {
                p122_emit_door_result("UNKNOWN_OUTCOME");
            }
            break;

        case R27_TX_RTPC_CLIENT_001A_REPEAT:
            r27_repeat_001a_sent_count++;
'''

_ACK_ANCHOR = """        } else if (r27_repeat_outstanding) {
            if (r27_handle_repeat_ack(request_id, body, body_len)) {
                p12_consume_post_ack(frame_len);
                continue;
            }
        } else if (p97_wait_device_ack_000a || p97_wait_device_ack_001a) {
"""
_ACK_REPLACEMENT = """        } else if (p122_door_waiting_ack) {
            if (p122_note_door_ack(request_id, body, body_len)) {
                p12_consume_post_ack(frame_len);
                continue;
            }
        } else if (r27_repeat_outstanding) {
            if (r27_handle_repeat_ack(request_id, body, body_len)) {
                p12_consume_post_ack(frame_len);
                continue;
            }
        } else if (p97_wait_device_ack_000a || p97_wait_device_ack_001a) {
"""

_REFRESH_ANCHOR = """    r27_repeat_timer_armed = FALSE;
    (void)r27_try_queue_repeat_001a("delay");
    return G_SOURCE_REMOVE;
}
"""
_REFRESH_REPLACEMENT = r"""    r27_repeat_timer_armed = FALSE;
    if (p122_on_demand_door_busy()) {
        if (g_timeout_add_seconds(2u, r27_repeat_delay_cb, NULL) == 0u) {
            p78_fail_rtpc("P122_REFRESH_DEFER_TIMER_START=FAIL");
            return G_SOURCE_REMOVE;
        }
        r27_repeat_timer_armed = TRUE;
        printf("P122_REFRESH_DEFERRED_FOR_DOOR=true\n");
        fflush(stdout);
        return G_SOURCE_REMOVE;
    }
    (void)r27_try_queue_repeat_001a("delay");
    return G_SOURCE_REMOVE;
}
"""

_SIGNAL_ANCHOR = r'''    printf("ENTRANCE_SIGNALING_DOOR_SIGNAL_INSTALLED=false\n");
    printf("ENTRANCE_SIGNALING_DOOR_TIMER_INSTALLED=false\n");
    printf("ENTRANCE_SIGNALING_DOOR_ACTION_SENT=false\n");
    fflush(stdout);

    g_timeout_add(
        100,
        stop_check_cb,
        NULL
    );
'''
_SIGNAL_REPLACEMENT = r'''    signal(SIGUSR1, p122_door_signal_handler);
    printf("ENTRANCE_SIGNALING_DOOR_SIGNAL_INSTALLED=false\n");
    printf("ENTRANCE_SIGNALING_DOOR_TIMER_INSTALLED=false\n");
    printf("ENTRANCE_SIGNALING_DOOR_ACTION_SENT=false\n");
    printf("P122_ON_DEMAND_DOOR_SIGNAL_INSTALLED=true\n");
    printf("P122_ON_DEMAND_DOOR_TIMER_INSTALLED=true\n");
    fflush(stdout);

    g_timeout_add(
        100,
        stop_check_cb,
        NULL
    );

    g_timeout_add(
        100,
        p122_on_demand_door_tick_cb,
        NULL
    );
'''


def transform(source: str, *, include_p116: bool = True) -> str:
    if not include_p116:
        raise ValueError("P122 requires --include-p116; --no-include-p116 is fail-closed")
    candidate = p121.transform(source, include_p116=True)
    candidate = _replace_once(candidate, _ENUM_OLD, _ENUM_NEW, "P122 tx enum")
    candidate = _replace_once(candidate, _STATE_ANCHOR, _STATE_REPLACEMENT, "P122 state")
    candidate = _replace_once(candidate, _HELPER_ANCHOR, _HELPERS, "P122 helpers")
    candidate = _replace_once(candidate, _TX_CASE_ANCHOR, _TX_CASE_REPLACEMENT, "P122 tx completion")
    candidate = _replace_once(candidate, _ACK_ANCHOR, _ACK_REPLACEMENT, "P122 ack hook")
    candidate = _replace_once(candidate, _REFRESH_ANCHOR, _REFRESH_REPLACEMENT, "P122 refresh defer")
    candidate = _replace_once(candidate, _SIGNAL_ANCHOR, _SIGNAL_REPLACEMENT, "P122 signal install")

    for marker in (
        BEGIN,
        END,
        "P122_TX_ON_DEMAND_DOOR",
        "P122_ON_DEMAND_DOOR_PATH=MEDIA_SESSION_SINGLE",
        "P122_ON_DEMAND_DOOR_WRITE_COUNT=1",
        "P122_ON_DEMAND_DOOR_RESULT=%s",
        "P122_REFRESH_DEFERRED_FOR_DOOR=true",
    ):
        if marker not in candidate:
            raise RuntimeError(f"P122 final gate missing {marker}")
    return candidate


def report() -> str:
    return "\n".join(
        (
            "=== COMELIT P122 ON-DEMAND MEDIA DOOR TRANSFORM ===",
            "P122_COMPOSES=P121_GATHER_INITIAL_TIMEOUT",
            "ON_DEMAND_ENTRANCE_DOOR=true",
            "DOOR_PROFILE=SINGLE_0x1840_0x000D",
            "DOOR_TX_COUNT=1",
            "RELAY_INDEX=1",
            "USES_EXISTING_CTPP=true",
            "SECOND_CTPP_OPEN=false",
            "SECOND_P2P_SESSION=false",
            "AUTOMATIC_RETRY=false",
            "GATE_PROFILE_PROMOTED=false",
            "PHYSICAL_EFFECT_ASSERTED=false",
            "NETWORK_IO_PERFORMED=false",
            "CANDIDATE_EXECUTED=false",
            "=== END COMELIT P122 ON-DEMAND MEDIA DOOR TRANSFORM ===",
        )
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--report", action="store_true")
    parser.add_argument("--sha256", action="store_true")
    args = parser.parse_args(argv)
    if args.report:
        print(report())
        return 0
    source_path = args.source
    if not source_path.exists() and str(source_path).startswith("safety-poc/"):
        source_path = Path(str(source_path)[len("safety-poc/"):])
    generated = transform(source_path.read_text(encoding="utf-8"), include_p116=True)
    if args.sha256:
        print(hashlib.sha256(generated.encode("utf-8")).hexdigest())
        return 0
    if args.output is None:
        parser.error("--output is required unless --report or --sha256 is used")
    args.output.write_text(generated, encoding="utf-8")
    print("P122_ON_DEMAND_MEDIA_DOOR_TRANSFORM=PASS")
    print("NETWORK_IO_PERFORMED=false")
    print("CANDIDATE_EXECUTED=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
