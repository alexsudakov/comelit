#!/usr/bin/env python3
"""Generate a bounded structural classifier after the reviewed device-video ACK.

This transform composes the merged P46 ACK-observation candidate and changes
only the receive-inspection boundary after the single capture-derived device
video ACK:

    P30 signaling
      -> exact device 0x0008
      -> exactly one session-derived 0x1800 ACK
      -> 3000 ms observation
      -> transiently reassemble bounded ViP application frames
      -> emit structural metadata only
      -> graceful PseudoTCP close (force=false)

Emitted frame metadata is limited to channel class, frame/body length and, for
CTPP frames, prefix/action/flags. Raw payload bytes, hex/base64 payload and
RTP/H264 contents are never emitted or decoded. The transient classifier buffer
is capped at 512 bytes and zeroed on consumption/finish.

The transform itself performs no network I/O and adds no live launcher.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from entrance_device_video_ack_observation_transform import transform as add_ack_observation


DEFAULT_SOURCE = Path(
    "safety-poc/research/door/v1_5_7/comelit-v4-persistent-ctpp-door.c"
)


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)


def transform(source: str) -> str:
    source = add_ack_observation(source)

    state_anchor = """static guint entrance_media_observation_events = 0;
static guint64 entrance_media_observation_bytes = 0;
static guint entrance_media_observation_max_chunk = 0;
"""
    state_replacement = r'''static guint entrance_media_observation_events = 0;
static guint64 entrance_media_observation_bytes = 0;
static guint entrance_media_observation_max_chunk = 0;

#define ENTRANCE_POST_ACK_CLASSIFIER_MAX 512
static guint8 entrance_post_ack_classifier_buf[ENTRANCE_POST_ACK_CLASSIFIER_MAX];
static guint entrance_post_ack_classifier_len = 0;
static guint entrance_post_ack_classifier_frames = 0;
static guint entrance_post_ack_classifier_ctpp_frames = 0;
static guint entrance_post_ack_classifier_other_frames = 0;
static guint entrance_post_ack_classifier_malformed = 0;
'''
    source = _replace_once(source, state_anchor, state_replacement, "post-ACK classifier state")

    finish_anchor = r'''static gboolean
entrance_media_observation_finish_cb(gpointer data)
{
'''
    helpers = r'''static gboolean
entrance_post_ack_classifier_feed(const guint8 *data, guint data_len)
{
    if (!data || data_len == 0)
        return TRUE;

    if (data_len > ENTRANCE_POST_ACK_CLASSIFIER_MAX - entrance_post_ack_classifier_len) {
        fprintf(stderr, "ENTRANCE_POST_ACK_CLASSIFIER_OVERFLOW=true\n");
        entrance_post_ack_classifier_malformed++;
        memset(
            entrance_post_ack_classifier_buf,
            0,
            sizeof(entrance_post_ack_classifier_buf)
        );
        entrance_post_ack_classifier_len = 0;
        return FALSE;
    }

    memcpy(
        entrance_post_ack_classifier_buf + entrance_post_ack_classifier_len,
        data,
        data_len
    );
    entrance_post_ack_classifier_len += data_len;

    while (entrance_post_ack_classifier_len >= 8) {
        guint body_len = (guint)read_le16(entrance_post_ack_classifier_buf + 2);
        guint frame_len = 8u + body_len;

        if (body_len == 0 || frame_len > ENTRANCE_POST_ACK_CLASSIFIER_MAX) {
            fprintf(stderr, "ENTRANCE_POST_ACK_CLASSIFIER_LENGTH_INVALID=%u\n", frame_len);
            entrance_post_ack_classifier_malformed++;
            memset(
                entrance_post_ack_classifier_buf,
                0,
                sizeof(entrance_post_ack_classifier_buf)
            );
            entrance_post_ack_classifier_len = 0;
            return FALSE;
        }

        if (entrance_post_ack_classifier_len < frame_len)
            break;

        guint32 request_id = read_le32(entrance_post_ack_classifier_buf + 4);
        const guint8 *body = entrance_post_ack_classifier_buf + 8;
        const gchar *channel = "OTHER";
        guint16 prefix = 0xffff;
        guint16 action = 0xffff;
        guint16 flags = 0xffff;
        gboolean structural_fields = FALSE;

        if (v4_ctpp_channel_id != 0 && request_id == v4_ctpp_channel_id) {
            channel = "CTPP";
            entrance_post_ack_classifier_ctpp_frames++;
            if (body_len >= 8) {
                prefix = read_le16(body + 0);
                action = ((guint16)body[6] << 8) | (guint16)body[7];
                structural_fields = TRUE;
                if (body_len >= 10)
                    flags = ((guint16)body[8] << 8) | (guint16)body[9];
            }
        } else if (v4_cspb_channel_id != 0 && request_id == v4_cspb_channel_id) {
            channel = "CSPB";
            entrance_post_ack_classifier_other_frames++;
        } else if (request_id == 0) {
            channel = "CONTROL";
            entrance_post_ack_classifier_other_frames++;
        } else {
            entrance_post_ack_classifier_other_frames++;
        }

        entrance_post_ack_classifier_frames++;

        if (structural_fields) {
            printf(
                "ENTRANCE_POST_ACK_STRUCT_FRAME=%u CHANNEL=%s FRAME_LEN=%u BODY_LEN=%u PREFIX=0x%04x ACTION=0x%04x FLAGS=0x%04x\n",
                entrance_post_ack_classifier_frames,
                channel,
                frame_len,
                body_len,
                prefix,
                action,
                flags
            );
        } else {
            printf(
                "ENTRANCE_POST_ACK_STRUCT_FRAME=%u CHANNEL=%s FRAME_LEN=%u BODY_LEN=%u STRUCT_FIELDS=false\n",
                entrance_post_ack_classifier_frames,
                channel,
                frame_len,
                body_len
            );
        }

        guint remaining = entrance_post_ack_classifier_len - frame_len;
        if (remaining > 0) {
            memmove(
                entrance_post_ack_classifier_buf,
                entrance_post_ack_classifier_buf + frame_len,
                remaining
            );
        }
        memset(
            entrance_post_ack_classifier_buf + remaining,
            0,
            entrance_post_ack_classifier_len - remaining
        );
        entrance_post_ack_classifier_len = remaining;
    }

    return TRUE;
}


static gboolean
entrance_media_observation_finish_cb(gpointer data)
{
'''
    source = _replace_once(source, finish_anchor, helpers, "post-ACK classifier helper")

    summary_anchor = r'''    printf("ENTRANCE_MEDIA_OBSERVATION_MAX_CHUNK=%u\n", entrance_media_observation_max_chunk);
    printf("ENTRANCE_MEDIA_OBSERVATION_PAYLOAD_STORED=false\n");
'''
    summary_replacement = r'''    printf("ENTRANCE_MEDIA_OBSERVATION_MAX_CHUNK=%u\n", entrance_media_observation_max_chunk);
    printf("ENTRANCE_POST_ACK_STRUCT_FRAMES=%u\n", entrance_post_ack_classifier_frames);
    printf("ENTRANCE_POST_ACK_STRUCT_CTPP_FRAMES=%u\n", entrance_post_ack_classifier_ctpp_frames);
    printf("ENTRANCE_POST_ACK_STRUCT_OTHER_FRAMES=%u\n", entrance_post_ack_classifier_other_frames);
    printf("ENTRANCE_POST_ACK_STRUCT_MALFORMED=%u\n", entrance_post_ack_classifier_malformed);
    printf("ENTRANCE_POST_ACK_STRUCT_TAIL_BYTES=%u\n", entrance_post_ack_classifier_len);
    printf("ENTRANCE_POST_ACK_STRUCT_RAW_PAYLOAD_EMITTED=false\n");
    printf("ENTRANCE_POST_ACK_STRUCT_HEX_EMITTED=false\n");
    printf("ENTRANCE_POST_ACK_STRUCT_BASE64_EMITTED=false\n");
    memset(
        entrance_post_ack_classifier_buf,
        0,
        sizeof(entrance_post_ack_classifier_buf)
    );
    entrance_post_ack_classifier_len = 0;
    printf("ENTRANCE_MEDIA_OBSERVATION_PAYLOAD_STORED=false\n");
'''
    source = _replace_once(source, summary_anchor, summary_replacement, "post-ACK classifier summary")

    readable_anchor = r'''                printf("ENTRANCE_MEDIA_OBSERVATION_RX_EVENT=%d\n", n);
                memset(buf, 0, (gsize)n);
                fflush(stdout);
                continue;
'''
    readable_replacement = r'''                if (!entrance_post_ack_classifier_feed((const guint8 *)buf, (guint)n)) {
                    memset(buf, 0, (gsize)n);
                    failed = TRUE;
                    if (loop)
                        g_main_loop_quit(loop);
                    return;
                }

                printf("ENTRANCE_MEDIA_OBSERVATION_RX_EVENT=%d\n", n);
                memset(buf, 0, (gsize)n);
                fflush(stdout);
                continue;
'''
    source = _replace_once(source, readable_anchor, readable_replacement, "post-ACK readable classifier feed")

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
        entrance_media_observation_events++;
        entrance_media_observation_bytes += (guint64)post_ack_capture_len;
        if (post_ack_capture_len > entrance_media_observation_max_chunk)
            entrance_media_observation_max_chunk = post_ack_capture_len;

        if (!entrance_post_ack_classifier_feed(post_ack_capture, post_ack_capture_len)) {
            memset(post_ack_capture, 0, post_ack_capture_len);
            post_ack_capture_len = 0;
            fprintf(stderr, "ENTRANCE_POST_ACK_CLASSIFIER_COALESCED_FEED=FAIL\n");
            return FALSE;
        }

        memset(post_ack_capture, 0, post_ack_capture_len);
        post_ack_capture_len = 0;
    }
'''
    source = _replace_once(source, coalesced_anchor, coalesced_replacement, "post-ACK coalesced classifier feed")

    return source


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    candidate = transform(args.source.read_text(encoding="utf-8"))
    args.output.write_text(candidate, encoding="utf-8")

    print("ENTRANCE_POST_ACK_STRUCTURAL_CLASSIFIER_TRANSFORM=PASS")
    print("ENTRANCE_POST_ACK_STRUCTURAL_CLASSIFIER_MAX=512")
    print("ENTRANCE_DEVICE_VIDEO_ACK_MAX_SENDS=1")
    print("ENTRANCE_FINAL_DEVICE_VIDEO_ACK_SENT=true")
    print("ENTRANCE_MEDIA_OBSERVATION_WINDOW_MS=3000")
    print("ENTRANCE_POST_ACK_STRUCT_RAW_PAYLOAD_EMITTED=false")
    print("ENTRANCE_POST_ACK_STRUCT_HEX_EMITTED=false")
    print("ENTRANCE_POST_ACK_STRUCT_BASE64_EMITTED=false")
    print("ENTRANCE_MEDIA_PAYLOAD_CAPTURED=false")
    print("ENTRANCE_RTP_H264_INSPECTION_PERFORMED=false")
    print("DOOR_ACTION_SENT=false")
    print("NETWORK_IO_PERFORMED=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
