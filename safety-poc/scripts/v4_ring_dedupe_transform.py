#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

SOURCE_SHA256 = "7b33945be9bd87fbfff96c2947259e924a113552f2396ee84c77fdb2692082f8"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)


def transform(source: str) -> str:
    text = source

    text = replace_once(
        text,
        "static gboolean v4_ring_observed = FALSE;\n",
        "static gboolean v4_ring_observed = FALSE;\n\n"
        "/* Exact CALL_INIT retransmit suppression.  The device retries the same\n"
        " * CALL_INIT frame with a short backoff.  Hashing the protocol body lets\n"
        " * us suppress only an identical frame inside a bounded window while a\n"
        " * later or different CALL_INIT remains eligible for a new HA event. */\n"
        "#define V4_RING_DEDUP_WINDOW_USEC ((gint64)15 * G_USEC_PER_SEC)\n"
        "static gchar v4_last_ring_sha256[65] = {0};\n"
        "static gint64 v4_last_ring_seen_us = 0;\n",
        "ring dedupe globals",
    )

    helper = r'''
static gboolean
v4_ring_is_retransmit(
    const guint8 *body,
    guint body_len)
{
    gchar *digest =
        g_compute_checksum_for_data(
            G_CHECKSUM_SHA256,
            body,
            body_len
        );

    if (!digest) {
        /* Fail open: never drop a real ring merely because local hashing failed. */
        return FALSE;
    }

    gint64 now = g_get_monotonic_time();
    gboolean duplicate =
        v4_last_ring_seen_us > 0 &&
        now >= v4_last_ring_seen_us &&
        (now - v4_last_ring_seen_us) <= V4_RING_DEDUP_WINDOW_USEC &&
        g_strcmp0(digest, v4_last_ring_sha256) == 0;

    if (duplicate) {
        /* Refresh the window while the same protocol retransmit train continues. */
        v4_last_ring_seen_us = now;
        printf("V4_RING_RETRANSMIT_SUPPRESSED=true\n");
        printf("V4_RING_RETRANSMIT_SHA256=%s\n", digest);
    } else {
        g_strlcpy(
            v4_last_ring_sha256,
            digest,
            sizeof(v4_last_ring_sha256)
        );
        v4_last_ring_seen_us = now;
        printf("V4_RING_FRAME_SHA256=%s\n", digest);
    }

    g_free(digest);
    fflush(stdout);
    return duplicate;
}


'''

    text = replace_once(
        text,
        "static gboolean\np12_process_post_uaut(void)\n{",
        helper + "static gboolean\np12_process_post_uaut(void)\n{",
        "ring dedupe helper",
    )

    text = replace_once(
        text,
        "                v4_ring_observed =\n                    TRUE;",
        "                if (\n"
        "                    v4_ring_is_retransmit(\n"
        "                        body,\n"
        "                        body_len\n"
        "                    )\n"
        "                ) {\n"
        "                    p12_consume_post_ack(\n"
        "                        frame_len\n"
        "                    );\n"
        "                    continue;\n"
        "                }\n\n\n"
        "                v4_ring_observed =\n"
        "                    TRUE;",
        "CALL_INIT retransmit guard",
    )

    required = (
        "V4_RING_DEDUP_WINDOW_USEC",
        "v4_ring_is_retransmit",
        "V4_RING_RETRANSMIT_SUPPRESSED=true",
        "V4_RING_FRAME_SHA256=%s",
        "CALL_INIT observation must not terminate",
    )
    for marker in required:
        if marker not in text:
            raise RuntimeError(f"generated source missing {marker}")

    return text


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate persistent Comelit Ring helper with exact CALL_INIT retransmit suppression"
    )
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    source_bytes = args.source.read_bytes()
    actual = hashlib.sha256(source_bytes).hexdigest()
    if actual != SOURCE_SHA256:
        raise RuntimeError(
            f"persistent source SHA-256 mismatch: expected={SOURCE_SHA256} actual={actual}"
        )

    generated = transform(source_bytes.decode("utf-8"))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(generated, encoding="utf-8")

    print("V131_RING_DEDUPE_TRANSFORM=PASS")
    print(f"V131_DEDUPE_SOURCE_SHA256={hashlib.sha256(generated.encode()).hexdigest()}")
    print("V131_DEDUPE_MODE=exact_body_sha256_plus_15s_window")
    print("V131_DEDUPE_FAIL_OPEN=true")
    print("RAW_RING_PAYLOAD_EMITTED=false")
    print("NETWORK_ACTION_PERFORMED=false")
    print("PHYSICAL_DOOR_ACTION=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
