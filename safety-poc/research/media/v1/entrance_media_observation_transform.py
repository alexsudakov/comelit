#!/usr/bin/env python3
"""Generate a bounded metadata-only entrance media observation candidate.

This transform composes the reviewed P30 entrance signaling transform and moves
one research boundary forward after the first capture-shaped device 0x0008
video event:

    P30 signaling success boundary
      -> do NOT ACK the device 0x0008
      -> observe PseudoTCP application receive metadata for 3000 ms
      -> store/emit no observed payload bytes
      -> decode/classify no RTP/H264
      -> graceful PseudoTCP close

Only receive-event count, total bytes and maximum receive-chunk length are
retained. Any bytes already buffered behind the device 0x0008 frame are counted
by length and immediately zeroed; later observed receive buffers are counted by
length and zeroed before the normal capture/parser path.

The transform itself performs no network I/O.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from entrance_self_activation_signaling_transform import transform as add_signaling


DEFAULT_SOURCE = Path(
    "safety-poc/research/door/v1_5_7/comelit-v4-persistent-ctpp-door.c"
)


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)


def transform(source: str) -> str:
    source = add_signaling(source)

    state_anchor = """    ENTRANCE_SIGNAL_WAIT_VIDEO_ACK,
    ENTRANCE_SIGNAL_WAIT_DEVICE_VIDEO,
    ENTRANCE_SIGNAL_DONE
} EntranceSignalStage;

#define ENTRANCE_SIGNAL_SETTLE_MS 4000
#define ENTRANCE_SIGNAL_TIMEOUT_MS 20000

static EntranceSignalStage entrance_signal_stage = ENTRANCE_SIGNAL_IDLE;
static guint32 entrance_signal_sequence = 0;
static gboolean entrance_self_activation_sent = FALSE;
static gboolean entrance_video_event_sent = FALSE;
static gboolean entrance_signaling_result = FALSE;
"""
    state_replacement = """    ENTRANCE_SIGNAL_WAIT_VIDEO_ACK,
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
    source = _replace_once(source, state_anchor, state_replacement, "media observation state")

    finish_anchor = r'''static gboolean
entrance_signal_finish_success(void)
{
    if (entrance_signal_stage != ENTRANCE_SIGNAL_WAIT_DEVICE_VIDEO ||
        !pseudo_tcp ||
        !pseudotcp_open ||
        pseudotcp_graceful_stop_started) {

        fprintf(stderr, "ENTRANCE_SIGNALING_FINISH_PRECONDITION=FAIL\n");
        return FALSE;
    }

    entrance_signal_stage = ENTRANCE_SIGNAL_DONE;
    entrance_signaling_result = TRUE;
    failed = FALSE;

    printf("ENTRANCE_DEVICE_VIDEO_EVENT=PASS\n");
    printf("ENTRANCE_SIGNALING_PROBE_RESULT=PASS\n");
    printf("ENTRANCE_FINAL_DEVICE_VIDEO_ACK_SENT=false\n");
    printf("ENTRANCE_MEDIA_PAYLOAD_CAPTURED=false\n");
    printf("ENTRANCE_RTP_H264_INSPECTION_PERFORMED=false\n");
    printf("ENTRANCE_DOOR_ACTION_SENT=false\n");
    fflush(stdout);

    pseudotcp_graceful_stop_started = TRUE;
    guint drained = pseudotcp_drain_before_graceful_close();
    printf("PSEUDOTCP_GRACEFUL_CLOSE_DRAINED_BYTES=%u\n", drained);

    pseudo_tcp_socket_close(pseudo_tcp, FALSE);
    printf("PSEUDOTCP_GRACEFUL_CLOSE_REQUESTED=true\n");
    printf("PSEUDOTCP_GRACEFUL_CLOSE_FORCE=false\n");
    printf("PSEUDOTCP_GRACEFUL_CLOSE_FORCE_RST_SENT=false\n");

    pseudotcp_graceful_stop_deadline_us =
        g_get_monotonic_time() +
        ((gint64)PSEUDOTCP_GRACEFUL_STOP_TIMEOUT_MS * 1000);

    if (g_timeout_add(
            PSEUDOTCP_GRACEFUL_STOP_POLL_MS,
            pseudotcp_graceful_stop_poll_cb,
            NULL) == 0) {

        fprintf(stderr, "PSEUDOTCP_GRACEFUL_CLOSE_POLL_START=FAIL\n");
        return FALSE;
    }

    printf("PSEUDOTCP_GRACEFUL_CLOSE_POLL_START=PASS\n");
    fflush(stdout);
    return TRUE;
}
'''
    finish_replacement = r'''static gboolean
entrance_media_observation_finish_cb(gpointer data)
{
    (void)data;

    if (entrance_signal_stage != ENTRANCE_SIGNAL_OBSERVE_MEDIA ||
        !pseudo_tcp ||
        !pseudotcp_open ||
        pseudotcp_graceful_stop_started) {

        fprintf(stderr, "ENTRANCE_MEDIA_OBSERVATION_FINISH_PRECONDITION=FAIL\n");
        failed = TRUE;
        if (loop)
            g_main_loop_quit(loop);
        return G_SOURCE_REMOVE;
    }

    entrance_signal_stage = ENTRANCE_SIGNAL_DONE;
    entrance_signaling_result = TRUE;
    failed = FALSE;

    printf("ENTRANCE_MEDIA_OBSERVATION_RESULT=PASS\n");
    printf("ENTRANCE_MEDIA_OBSERVATION_EVENTS=%u\n", entrance_media_observation_events);
    printf(
        "ENTRANCE_MEDIA_OBSERVATION_BYTES=%" G_GUINT64_FORMAT "\n",
        entrance_media_observation_bytes
    );
    printf("ENTRANCE_MEDIA_OBSERVATION_MAX_CHUNK=%u\n", entrance_media_observation_max_chunk);
    printf("ENTRANCE_MEDIA_OBSERVATION_PAYLOAD_STORED=false\n");
    printf("ENTRANCE_MEDIA_OBSERVATION_PAYLOAD_EMITTED=false\n");
    printf("ENTRANCE_SIGNALING_PROBE_RESULT=PASS\n");
    printf("ENTRANCE_FINAL_DEVICE_VIDEO_ACK_SENT=false\n");
    printf("ENTRANCE_MEDIA_PAYLOAD_CAPTURED=false\n");
    printf("ENTRANCE_RTP_H264_INSPECTION_PERFORMED=false\n");
    printf("ENTRANCE_DOOR_ACTION_SENT=false\n");
    fflush(stdout);

    pseudotcp_graceful_stop_started = TRUE;
    guint drained = pseudotcp_drain_before_graceful_close();
    printf("PSEUDOTCP_GRACEFUL_CLOSE_DRAINED_BYTES=%u\n", drained);

    pseudo_tcp_socket_close(pseudo_tcp, FALSE);
    printf("PSEUDOTCP_GRACEFUL_CLOSE_REQUESTED=true\n");
    printf("PSEUDOTCP_GRACEFUL_CLOSE_FORCE=false\n");
    printf("PSEUDOTCP_GRACEFUL_CLOSE_FORCE_RST_SENT=false\n");

    pseudotcp_graceful_stop_deadline_us =
        g_get_monotonic_time() +
        ((gint64)PSEUDOTCP_GRACEFUL_STOP_TIMEOUT_MS * 1000);

    if (g_timeout_add(
            PSEUDOTCP_GRACEFUL_STOP_POLL_MS,
            pseudotcp_graceful_stop_poll_cb,
            NULL) == 0) {

        fprintf(stderr, "PSEUDOTCP_GRACEFUL_CLOSE_POLL_START=FAIL\n");
        failed = TRUE;
        if (loop)
            g_main_loop_quit(loop);
        return G_SOURCE_REMOVE;
    }

    printf("PSEUDOTCP_GRACEFUL_CLOSE_POLL_START=PASS\n");
    fflush(stdout);
    return G_SOURCE_REMOVE;
}


static gboolean
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

    /* p12_consume_post_ack() may leave bytes already coalesced behind the
     * device 0x0008 frame. Count length only, then erase those bytes. */
    if (post_ack_capture_len > 0) {
        entrance_media_observation_events++;
        entrance_media_observation_bytes += (guint64)post_ack_capture_len;
        if (post_ack_capture_len > entrance_media_observation_max_chunk)
            entrance_media_observation_max_chunk = post_ack_capture_len;
        memset(post_ack_capture, 0, post_ack_capture_len);
        post_ack_capture_len = 0;
    }

    printf("ENTRANCE_DEVICE_VIDEO_EVENT=PASS\n");
    printf("ENTRANCE_MEDIA_OBSERVATION_STARTED=true\n");
    printf("ENTRANCE_MEDIA_OBSERVATION_WINDOW_MS=%u\n", ENTRANCE_MEDIA_OBSERVE_MS);
    printf("ENTRANCE_MEDIA_OBSERVATION_DEVICE_VIDEO_ACK_SENT=false\n");
    printf("ENTRANCE_MEDIA_OBSERVATION_PAYLOAD_STORAGE_ALLOWED=false\n");
    printf("ENTRANCE_MEDIA_OBSERVATION_RTP_H264_DECODE_ALLOWED=false\n");
    fflush(stdout);

    if (g_timeout_add(
            ENTRANCE_MEDIA_OBSERVE_MS,
            entrance_media_observation_finish_cb,
            NULL) == 0) {

        fprintf(stderr, "ENTRANCE_MEDIA_OBSERVATION_TIMER_START=FAIL\n");
        return FALSE;
    }

    return TRUE;
}
'''
    source = _replace_once(source, finish_anchor, finish_replacement, "media observation finish")

    parse_anchor = r'''                p12_consume_post_ack(frame_len);
                return entrance_signal_finish_success();
'''
    parse_replacement = r'''                p12_consume_post_ack(frame_len);
                return entrance_signal_begin_media_observation();
'''
    source = _replace_once(source, parse_anchor, parse_replacement, "device video observation transition")

    readable_anchor = r'''        if (n > 0) {
            pseudotcp_app_bytes_in +=
                (guint64)n;
'''
    readable_replacement = r'''        if (n > 0) {
            if (entrance_signal_stage == ENTRANCE_SIGNAL_OBSERVE_MEDIA) {
                entrance_media_observation_events++;
                entrance_media_observation_bytes += (guint64)n;
                if ((guint)n > entrance_media_observation_max_chunk)
                    entrance_media_observation_max_chunk = (guint)n;

                printf("ENTRANCE_MEDIA_OBSERVATION_RX_EVENT=%d\n", n);
                memset(buf, 0, (gsize)n);
                fflush(stdout);
                continue;
            }

            pseudotcp_app_bytes_in +=
                (guint64)n;
'''
    source = _replace_once(source, readable_anchor, readable_replacement, "metadata-only readable path")

    return source


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    candidate = transform(args.source.read_text(encoding="utf-8"))
    args.output.write_text(candidate, encoding="utf-8")

    print("ENTRANCE_MEDIA_OBSERVATION_TRANSFORM=PASS")
    print("ENTRANCE_MEDIA_OBSERVATION_WINDOW_MS=3000")
    print("ENTRANCE_FINAL_DEVICE_VIDEO_ACK_SENT=false")
    print("ENTRANCE_MEDIA_PAYLOAD_CAPTURED=false")
    print("ENTRANCE_RTP_H264_INSPECTION_PERFORMED=false")
    print("ENTRANCE_MEDIA_OBSERVATION_PAYLOAD_STORED=false")
    print("ENTRANCE_MEDIA_OBSERVATION_PAYLOAD_EMITTED=false")
    print("DOOR_ACTION_SENT=false")
    print("NETWORK_IO_PERFORMED=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
