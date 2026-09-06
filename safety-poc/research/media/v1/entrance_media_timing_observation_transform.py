#!/usr/bin/env python3
"""Add per-fragment timing metadata to the bounded entrance observation stage.

This transform composes the reviewed metadata-only P36 observation candidate and
adds no payload inspection.  For each application receive fragment it records
only:

- ordinal index;
- origin (already coalesced at the device-0x0008 boundary vs later readable);
- fragment length;
- monotonic microseconds since observation start;
- monotonic microseconds since the previous observed fragment.

Payload bytes are still never emitted or retained: the inherited observation
path zeroes them immediately.  The device 0x0008 remains unacknowledged, the
Door surface remains unreachable, and the observation window remains 3000 ms.

The transform itself performs no network I/O.
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

    state_anchor = """static guint entrance_media_observation_events = 0;
static guint64 entrance_media_observation_bytes = 0;
static guint entrance_media_observation_max_chunk = 0;
"""
    state_replacement = """static guint entrance_media_observation_events = 0;
static guint64 entrance_media_observation_bytes = 0;
static guint entrance_media_observation_max_chunk = 0;
static guint entrance_media_observation_event_index = 0;
static gint64 entrance_media_observation_start_us = 0;
static gint64 entrance_media_observation_last_event_us = 0;
"""
    source = _replace_once(source, state_anchor, state_replacement, "timing state")

    finish_anchor = r'''static gboolean
entrance_media_observation_finish_cb(gpointer data)
{
'''
    timing_helper = r'''static void
entrance_media_timing_record_event(guint len, const gchar *origin)
{
    const gint64 now_us = g_get_monotonic_time();
    guint64 since_start_us = 0;
    guint64 delta_us = 0;

    if (entrance_media_observation_start_us > 0 &&
        now_us >= entrance_media_observation_start_us) {
        since_start_us =
            (guint64)(now_us - entrance_media_observation_start_us);
    }

    if (entrance_media_observation_last_event_us > 0 &&
        now_us >= entrance_media_observation_last_event_us) {
        delta_us =
            (guint64)(now_us - entrance_media_observation_last_event_us);
    }

    entrance_media_observation_event_index++;
    entrance_media_observation_events++;
    entrance_media_observation_bytes += (guint64)len;
    if (len > entrance_media_observation_max_chunk)
        entrance_media_observation_max_chunk = len;

    printf(
        "ENTRANCE_MEDIA_TIMING_EVENT_INDEX=%u ORIGIN=%s LEN=%u "
        "SINCE_START_US=%" G_GUINT64_FORMAT " DELTA_US=%" G_GUINT64_FORMAT "\n",
        entrance_media_observation_event_index,
        origin,
        len,
        since_start_us,
        delta_us
    );
    fflush(stdout);

    entrance_media_observation_last_event_us = now_us;
}


static gboolean
entrance_media_observation_finish_cb(gpointer data)
{
'''
    source = _replace_once(source, finish_anchor, timing_helper, "timing helper")

    start_anchor = r'''    entrance_signal_stage = ENTRANCE_SIGNAL_OBSERVE_MEDIA;

    /* p12_consume_post_ack() may leave bytes already coalesced behind the
'''
    start_replacement = r'''    entrance_signal_stage = ENTRANCE_SIGNAL_OBSERVE_MEDIA;
    entrance_media_observation_event_index = 0;
    entrance_media_observation_start_us = g_get_monotonic_time();
    entrance_media_observation_last_event_us = 0;

    printf("ENTRANCE_MEDIA_TIMING_OBSERVATION_STARTED=true\n");
    printf("ENTRANCE_MEDIA_TIMING_CLOCK=MONOTONIC_US\n");
    fflush(stdout);

    /* p12_consume_post_ack() may leave bytes already coalesced behind the
'''
    source = _replace_once(source, start_anchor, start_replacement, "timing start")

    coalesced_anchor = r'''    if (post_ack_capture_len > 0) {
        entrance_media_observation_events++;
        entrance_media_observation_bytes += (guint64)post_ack_capture_len;
        if (post_ack_capture_len > entrance_media_observation_max_chunk)
            entrance_media_observation_max_chunk = post_ack_capture_len;
        memset(post_ack_capture, 0, post_ack_capture_len);
        post_ack_capture_len = 0;
    }
'''
    coalesced_replacement = r'''    if (post_ack_capture_len > 0) {
        entrance_media_timing_record_event(
            post_ack_capture_len,
            "COALESCED"
        );
        memset(post_ack_capture, 0, post_ack_capture_len);
        post_ack_capture_len = 0;
    }
'''
    source = _replace_once(
        source,
        coalesced_anchor,
        coalesced_replacement,
        "coalesced timing event",
    )

    readable_anchor = r'''            if (entrance_signal_stage == ENTRANCE_SIGNAL_OBSERVE_MEDIA) {
                entrance_media_observation_events++;
                entrance_media_observation_bytes += (guint64)n;
                if ((guint)n > entrance_media_observation_max_chunk)
                    entrance_media_observation_max_chunk = (guint)n;

                printf("ENTRANCE_MEDIA_OBSERVATION_RX_EVENT=%d\n", n);
                memset(buf, 0, (gsize)n);
                fflush(stdout);
                continue;
            }
'''
    readable_replacement = r'''            if (entrance_signal_stage == ENTRANCE_SIGNAL_OBSERVE_MEDIA) {
                entrance_media_timing_record_event(
                    (guint)n,
                    "READABLE"
                );
                printf("ENTRANCE_MEDIA_OBSERVATION_RX_EVENT=%d\n", n);
                memset(buf, 0, (gsize)n);
                fflush(stdout);
                continue;
            }
'''
    source = _replace_once(
        source,
        readable_anchor,
        readable_replacement,
        "readable timing event",
    )

    finish_marker_anchor = r'''    printf("ENTRANCE_MEDIA_OBSERVATION_RESULT=PASS\n");
'''
    finish_marker_replacement = r'''    printf("ENTRANCE_MEDIA_TIMING_OBSERVATION_RESULT=PASS\n");
    printf(
        "ENTRANCE_MEDIA_TIMING_EVENT_COUNT=%u\n",
        entrance_media_observation_event_index
    );
    printf("ENTRANCE_MEDIA_OBSERVATION_RESULT=PASS\n");
'''
    source = _replace_once(
        source,
        finish_marker_anchor,
        finish_marker_replacement,
        "timing finish markers",
    )

    return source


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    candidate = transform(args.source.read_text(encoding="utf-8"))
    args.output.write_text(candidate, encoding="utf-8")

    print("ENTRANCE_MEDIA_TIMING_OBSERVATION_TRANSFORM=PASS")
    print("ENTRANCE_MEDIA_TIMING_CLOCK=MONOTONIC_US")
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
