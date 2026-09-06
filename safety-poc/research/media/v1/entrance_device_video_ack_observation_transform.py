#!/usr/bin/env python3
"""Generate an offline-reviewed entrance device-video ACK observation candidate.

This transform composes the reviewed metadata-only P36 observation candidate and
advances exactly one protocol boundary:

    P30 signaling
      -> first capture-shaped device 0x0008
      -> consume that frame
      -> send exactly one structural 0x1800 ACK on the existing CTPP channel
      -> begin the same 3000 ms metadata-only observation
      -> store/emit no observed payload bytes
      -> perform no RTP/H264 inspection or decode
      -> graceful PseudoTCP close (force=false)

The ACK contract is derived from the frozen PCAP forensics P42-P45:

* the ACK reverses the two device-frame address roles;
* the first ACK is uniquely bound to packet-200 device 0x0008 by immediate
  predecessor ordering (packet 201, no intervening same-CTPP frame);
* the client ACK sequence is the actual client-video sequence plus 0x01010000.

No literal capture sequence value is copied.  The client-video sequence is
stored as generated session state and the ACK sequence is derived from it.

The transform itself performs no network I/O.  This file does not provide a
live runner or launcher.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from entrance_media_observation_transform import transform as add_observation


DEFAULT_SOURCE = Path(
    "safety-poc/research/door/v1_5_7/comelit-v4-persistent-ctpp-door.c"
)


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)


def transform(source: str) -> str:
    source = add_observation(source)

    tx_kind_anchor = """    P12_TX_ENTRANCE_SELF_ACTIVATION,
    P12_TX_ENTRANCE_VIDEO_EVENT,

    P12_TX_V4_DOOR_WRITE
"""
    tx_kind_replacement = """    P12_TX_ENTRANCE_SELF_ACTIVATION,
    P12_TX_ENTRANCE_VIDEO_EVENT,
    P12_TX_ENTRANCE_DEVICE_VIDEO_ACK,

    P12_TX_V4_DOOR_WRITE
"""
    source = _replace_once(source, tx_kind_anchor, tx_kind_replacement, "device video ACK tx kind")

    state_anchor = """    ENTRANCE_SIGNAL_WAIT_VIDEO_ACK,
    ENTRANCE_SIGNAL_WAIT_DEVICE_VIDEO,
    ENTRANCE_SIGNAL_OBSERVE_MEDIA,
    ENTRANCE_SIGNAL_DONE
} EntranceSignalStage;

#define ENTRANCE_SIGNAL_SETTLE_MS 4000
#define ENTRANCE_SIGNAL_TIMEOUT_MS 20000
#define ENTRANCE_MEDIA_OBSERVE_MS 3000

static EntranceSignalStage entrance_signal_stage = ENTRANCE_SIGNAL_IDLE;
static guint32 entrance_signal_sequence = 0;
static gboolean entrance_self_activation_sent = FALSE;
static gboolean entrance_video_event_sent = FALSE;
static gboolean entrance_signaling_result = FALSE;
static guint entrance_media_observation_events = 0;
static guint64 entrance_media_observation_bytes = 0;
static guint entrance_media_observation_max_chunk = 0;
"""
    state_replacement = """    ENTRANCE_SIGNAL_WAIT_VIDEO_ACK,
    ENTRANCE_SIGNAL_WAIT_DEVICE_VIDEO,
    ENTRANCE_SIGNAL_DEVICE_VIDEO_ACK_TX,
    ENTRANCE_SIGNAL_OBSERVE_MEDIA,
    ENTRANCE_SIGNAL_DONE
} EntranceSignalStage;

#define ENTRANCE_SIGNAL_SETTLE_MS 4000
#define ENTRANCE_SIGNAL_TIMEOUT_MS 20000
#define ENTRANCE_MEDIA_OBSERVE_MS 3000
#define ENTRANCE_DEVICE_VIDEO_ACK_SEQUENCE_DELTA_FROM_CLIENT_VIDEO 0x01010000u

static EntranceSignalStage entrance_signal_stage = ENTRANCE_SIGNAL_IDLE;
static guint32 entrance_signal_sequence = 0;
static guint32 entrance_video_event_sequence = 0;
static guint32 entrance_device_video_ack_sequence = 0;
static gboolean entrance_self_activation_sent = FALSE;
static gboolean entrance_video_event_sent = FALSE;
static gboolean entrance_device_video_ack_sent = FALSE;
static gboolean entrance_signaling_result = FALSE;
static guint entrance_media_observation_events = 0;
static guint64 entrance_media_observation_bytes = 0;
static guint entrance_media_observation_max_chunk = 0;
"""
    source = _replace_once(source, state_anchor, state_replacement, "device video ACK state")

    video_sequence_anchor = """    write_le16(body + 0, 0x1840);
    write_le32(body + 2, entrance_signal_sequence + 0x00010000u);
    body[6] = 0x00;
"""
    video_sequence_replacement = """    write_le16(body + 0, 0x1840);
    entrance_video_event_sequence = entrance_signal_sequence + 0x00010000u;
    write_le32(body + 2, entrance_video_event_sequence);
    body[6] = 0x00;
"""
    source = _replace_once(source, video_sequence_anchor, video_sequence_replacement, "client video sequence state")

    finish_ack_anchor = '    printf("ENTRANCE_FINAL_DEVICE_VIDEO_ACK_SENT=false\\n");\n'
    finish_ack_replacement = '    printf("ENTRANCE_FINAL_DEVICE_VIDEO_ACK_SENT=true\\n");\n'
    source = _replace_once(source, finish_ack_anchor, finish_ack_replacement, "final ACK result marker")

    begin_anchor = r'''static gboolean
entrance_signal_begin_media_observation(void)
{
    if (entrance_signal_stage != ENTRANCE_SIGNAL_WAIT_DEVICE_VIDEO ||
        !pseudo_tcp ||
        !pseudotcp_open ||
        pseudotcp_graceful_stop_started) {

        fprintf(stderr, "ENTRANCE_MEDIA_OBSERVATION_START_PRECONDITION=FAIL\n");
        return FALSE;
    }

    entrance_signal_stage = ENTRANCE_SIGNAL_OBSERVE_MEDIA;
'''
    begin_replacement = r'''static gboolean
entrance_signal_begin_media_observation(void)
{
    if (entrance_signal_stage != ENTRANCE_SIGNAL_DEVICE_VIDEO_ACK_TX ||
        !entrance_device_video_ack_sent ||
        !pseudo_tcp ||
        !pseudotcp_open ||
        pseudotcp_graceful_stop_started) {

        fprintf(stderr, "ENTRANCE_MEDIA_OBSERVATION_START_PRECONDITION=FAIL\n");
        return FALSE;
    }

    entrance_signal_stage = ENTRANCE_SIGNAL_OBSERVE_MEDIA;
'''
    source = _replace_once(source, begin_anchor, begin_replacement, "post-ACK observation gate")

    begin_marker_anchor = '    printf("ENTRANCE_MEDIA_OBSERVATION_DEVICE_VIDEO_ACK_SENT=false\\n");\n'
    begin_marker_replacement = '    printf("ENTRANCE_MEDIA_OBSERVATION_DEVICE_VIDEO_ACK_SENT=true\\n");\n'
    source = _replace_once(source, begin_marker_anchor, begin_marker_replacement, "observation ACK marker")

    parse_anchor = r'''                p12_consume_post_ack(frame_len);
                return entrance_signal_begin_media_observation();
'''
    parse_replacement = r'''                p12_consume_post_ack(frame_len);
                return entrance_signal_queue_device_video_ack();
'''
    source = _replace_once(source, parse_anchor, parse_replacement, "device video ACK transition")

    tx_case_anchor = r'''        case P12_TX_ENTRANCE_VIDEO_EVENT:
            entrance_video_event_sent = TRUE;
            entrance_signal_stage = ENTRANCE_SIGNAL_WAIT_VIDEO_ACK;
            printf("ENTRANCE_VIDEO_EVENT_SENT=PASS\n");
            fflush(stdout);
            break;

        case P12_TX_V4_DOOR_WRITE:
'''
    tx_case_replacement = r'''        case P12_TX_ENTRANCE_VIDEO_EVENT:
            entrance_video_event_sent = TRUE;
            entrance_signal_stage = ENTRANCE_SIGNAL_WAIT_VIDEO_ACK;
            printf("ENTRANCE_VIDEO_EVENT_SENT=PASS\n");
            fflush(stdout);
            break;

        case P12_TX_ENTRANCE_DEVICE_VIDEO_ACK:
            entrance_device_video_ack_sent = TRUE;
            printf("ENTRANCE_DEVICE_VIDEO_ACK_SENT=PASS\n");
            printf("ENTRANCE_DEVICE_VIDEO_ACK_SEQUENCE_EMITTED=false\n");
            printf("ENTRANCE_DEVICE_VIDEO_ACK_ADDRESS_ROLE_REVERSAL=true\n");
            fflush(stdout);

            if (!entrance_signal_begin_media_observation()) {
                failed = TRUE;
                if (loop)
                    g_main_loop_quit(loop);
            }
            break;

        case P12_TX_V4_DOOR_WRITE:
'''
    source = _replace_once(source, tx_case_anchor, tx_case_replacement, "device video ACK tx completion")

    helper_anchor = r'''static gboolean
entrance_media_observation_finish_cb(gpointer data)
{
'''
    helper_replacement = r'''static gboolean
entrance_signal_queue_device_video_ack(void)
{
    if (entrance_signal_stage != ENTRANCE_SIGNAL_WAIT_DEVICE_VIDEO ||
        !entrance_video_event_sent ||
        entrance_device_video_ack_sent ||
        !pseudo_tcp ||
        !pseudotcp_open ||
        v4_ctpp_channel_id == 0 ||
        p12_tx_pending ||
        pseudotcp_graceful_stop_started) {

        fprintf(stderr, "ENTRANCE_DEVICE_VIDEO_ACK_PRECONDITION=FAIL\n");
        return FALSE;
    }

    guint8 body[32];
    memset(body, 0, sizeof(body));

    write_le16(body + 0, 0x1800);

    entrance_device_video_ack_sequence =
        entrance_video_event_sequence +
        ENTRANCE_DEVICE_VIDEO_ACK_SEQUENCE_DELTA_FROM_CLIENT_VIDEO;
    write_le32(body + 2, entrance_device_video_ack_sequence);

    body[6] = 0x00;
    body[7] = 0x00;
    memset(body + 8, 0xff, 4);

    /* P43-P45 capture-derived role reversal for client -> device ACK:
     * first ACK address = device frame second address (our full address),
     * second ACK address = device frame first address (entrance panel). */
    memcpy(body + 12, V4_FULL_ADDRESS, 9);
    body[21] = 0x00;
    memcpy(body + 22, V4_ENTRANCE, 8);
    body[30] = 0x00;
    body[31] = 0x00;

    entrance_signal_stage = ENTRANCE_SIGNAL_DEVICE_VIDEO_ACK_TX;

    gboolean ok = p12_queue_vip_frame(
        v4_ctpp_channel_id,
        body,
        sizeof(body),
        P12_TX_ENTRANCE_DEVICE_VIDEO_ACK
    );

    memset(body, 0, sizeof(body));

    if (!ok)
        return FALSE;

    printf("ENTRANCE_DEVICE_VIDEO_ACK_BODY_LEN=32\n");
    printf("ENTRANCE_DEVICE_VIDEO_ACK_PREFIX=0x1800\n");
    printf("ENTRANCE_DEVICE_VIDEO_ACK_ACTION=0x0000\n");
    printf("ENTRANCE_DEVICE_VIDEO_ACK_FLAGS=0xffff\n");
    printf("ENTRANCE_DEVICE_VIDEO_ACK_SEQUENCE_DELTA_FROM_CLIENT_VIDEO=0x01010000\n");
    printf("ENTRANCE_DEVICE_VIDEO_ACK_SEQUENCE_EMITTED=false\n");
    printf("ENTRANCE_DEVICE_VIDEO_ACK_CTPP_REUSED=true\n");
    fflush(stdout);

    return p12_flush_tx();
}


static gboolean
entrance_media_observation_finish_cb(gpointer data)
{
'''
    source = _replace_once(source, helper_anchor, helper_replacement, "device video ACK helper")

    return source


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    candidate = transform(args.source.read_text(encoding="utf-8"))
    args.output.write_text(candidate, encoding="utf-8")

    print("ENTRANCE_DEVICE_VIDEO_ACK_OBSERVATION_TRANSFORM=PASS")
    print("ENTRANCE_DEVICE_VIDEO_ACK_SEQUENCE_DELTA_FROM_CLIENT_VIDEO=0x01010000")
    print("ENTRANCE_DEVICE_VIDEO_ACK_SEQUENCE_EMITTED=false")
    print("ENTRANCE_DEVICE_VIDEO_ACK_ADDRESS_ROLE_REVERSAL=true")
    print("ENTRANCE_DEVICE_VIDEO_ACK_MAX_SENDS=1")
    print("ENTRANCE_MEDIA_OBSERVATION_WINDOW_MS=3000")
    print("ENTRANCE_FINAL_DEVICE_VIDEO_ACK_SENT=true")
    print("ENTRANCE_MEDIA_PAYLOAD_CAPTURED=false")
    print("ENTRANCE_RTP_H264_INSPECTION_PERFORMED=false")
    print("ENTRANCE_MEDIA_OBSERVATION_PAYLOAD_STORED=false")
    print("ENTRANCE_MEDIA_OBSERVATION_PAYLOAD_EMITTED=false")
    print("DOOR_ACTION_SENT=false")
    print("NETWORK_IO_PERFORMED=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
