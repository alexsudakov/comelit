#!/usr/bin/env bash
set -euo pipefail

HERE="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
BASE="$HERE/comelit-v4-persistent-ring-door.c"
BUILD=/root/comelit-door-reject-diag-build
SRC="$BUILD/comelit-v4-persistent-ring-door-diag.c"
BIN="$BUILD/comelit-v4-door-diag"
DIFF="$BUILD/door-reject-diagnostics.diff"

for cmd in python3 gcc pkg-config sha256sum strings grep diff; do
    command -v "$cmd" >/dev/null 2>&1 || {
        echo "MISSING_COMMAND=$cmd"
        exit 10
    }
done

[[ -f "$BASE" ]] || {
    echo 'BASE_SOURCE=FAIL'
    exit 11
}

rm -rf "$BUILD"
mkdir -m 700 "$BUILD"

python3 - "$BASE" "$SRC" <<'PY'
from pathlib import Path
import hashlib
import sys

base_path = Path(sys.argv[1])
out_path = Path(sys.argv[2])
src = base_path.read_text(encoding="utf-8")

needle = '''        if (response_word != 0) {\n            v4_door_emit_result("REJECTED");\n            v4_door_reset();\n            return V4_DOOR_FRAME_CONSUMED;\n        }\n'''

replacement = r'''        if (response_word != 0) {
            /*
             * Diagnostic-only observability for a protocol REJECTED result.
             *
             * This block MUST NOT alter the Door one-shot sequence:
             * - no retry
             * - no additional protocol frame
             * - no write body queued
             * - no physical-effect assertion
             *
             * Values below are non-secret protocol metadata only.
             */
            printf("V4_DOOR_REJECT_STAGE=CTPP_OPEN\n");
            printf(
                "V4_DOOR_REJECT_RESPONSE_WORD=%u\n",
                (unsigned)response_word
            );
            printf(
                "V4_DOOR_REQUESTED_CHANNEL_ID=%u\n",
                (unsigned)v4_door_requested_channel_id
            );
            printf(
                "V4_DOOR_RESPONSE_CHANNEL_ID=%u\n",
                (unsigned)response_channel
            );
            fflush(stdout);

            gchar diagnostic[256];
            gint diagnostic_len = g_snprintf(
                diagnostic,
                sizeof(diagnostic),
                "stage=CTPP_OPEN\\n"
                "response_word=%u\\n"
                "requested_channel_id=%u\\n"
                "response_channel_id=%u\\n"
                "automatic_retry_allowed=false\\n"
                "physical_effect_asserted=false\\n",
                (unsigned)response_word,
                (unsigned)v4_door_requested_channel_id,
                (unsigned)response_channel
            );

            if (
                diagnostic_len > 0 &&
                (gsize)diagnostic_len < sizeof(diagnostic)
            ) {
                GError *diagnostic_error = NULL;
                if (!g_file_set_contents(
                        RUN_DIR "/door-reject-diagnostic.txt",
                        diagnostic,
                        diagnostic_len,
                        &diagnostic_error)) {
                    fprintf(
                        stderr,
                        "V4_DOOR_REJECT_DIAGNOSTIC_FILE=FAIL\n"
                    );
                    if (diagnostic_error)
                        g_error_free(diagnostic_error);
                } else {
                    (void)g_chmod(
                        RUN_DIR "/door-reject-diagnostic.txt",
                        0600
                    );
                    printf(
                        "V4_DOOR_REJECT_DIAGNOSTIC_FILE=PASS\n"
                    );
                    fflush(stdout);
                }
            } else {
                fprintf(
                    stderr,
                    "V4_DOOR_REJECT_DIAGNOSTIC_FORMAT=FAIL\n"
                );
            }

            memset(diagnostic, 0, sizeof(diagnostic));
            v4_door_emit_result("REJECTED");
            v4_door_reset();
            return V4_DOOR_FRAME_CONSUMED;
        }
'''

if src.count(needle) != 1:
    raise SystemExit(f"DIAGNOSTIC_PATCH=FAIL anchor_count={src.count(needle)}")

# Safety gate 1: the six capture-derived Door write payloads must remain byte-for-byte
# identical after patching.
payload_start = src.index("static const guint8 v4_door_body_1[]")
payload_end = src.index("static void v4_door_set_deadline", payload_start)
payload_before = src[payload_start:payload_end]

# Safety gate 2: open/write/close queue functions must remain byte-for-byte identical.
queue_start = src.index("static gboolean\nv4_door_queue_open(void)")
queue_end = src.index("static V4DoorFrameResult\nv4_door_process_frame", queue_start)
queue_before = src[queue_start:queue_end]

patched = src.replace(needle, replacement, 1)

payload_start_after = patched.index("static const guint8 v4_door_body_1[]")
payload_end_after = patched.index("static void v4_door_set_deadline", payload_start_after)
payload_after = patched[payload_start_after:payload_end_after]

queue_start_after = patched.index("static gboolean\nv4_door_queue_open(void)")
queue_end_after = patched.index("static V4DoorFrameResult\nv4_door_process_frame", queue_start_after)
queue_after = patched[queue_start_after:queue_end_after]

if payload_before != payload_after:
    raise SystemExit("DOOR_PAYLOAD_IMMUTABILITY=FAIL")
if queue_before != queue_after:
    raise SystemExit("DOOR_SEND_SEQUENCE_IMMUTABILITY=FAIL")

print("DIAGNOSTIC_PATCH=PASS")
print("DOOR_PAYLOAD_IMMUTABILITY=PASS")
print("DOOR_SEND_SEQUENCE_IMMUTABILITY=PASS")
print(
    "DOOR_PAYLOAD_BLOCK_SHA256="
    + hashlib.sha256(payload_before.encode()).hexdigest()
)
print(
    "DOOR_QUEUE_BLOCK_SHA256="
    + hashlib.sha256(queue_before.encode()).hexdigest()
)

out_path.write_text(patched, encoding="utf-8")
PY

diff -u "$BASE" "$SRC" > "$DIFF" || true

# Reject any accidental changes outside the single diagnostic hunk.
HUNKS="$(grep -c '^@@ ' "$DIFF" || true)"
if [ "$HUNKS" != "1" ]; then
    echo "DIFF_SCOPE=FAIL hunks=$HUNKS"
    exit 12
fi
echo 'DIFF_SCOPE=PASS hunks=1'

for marker in \
  'V4_DOOR_REJECT_STAGE=CTPP_OPEN' \
  'V4_DOOR_REJECT_RESPONSE_WORD=%u' \
  'V4_DOOR_REQUESTED_CHANNEL_ID=%u' \
  'V4_DOOR_RESPONSE_CHANNEL_ID=%u' \
  'door-reject-diagnostic.txt' \
  'automatic_retry_allowed=false' \
  'physical_effect_asserted=false'
do
    grep -Fq "$marker" "$SRC" || {
        echo "DIAGNOSTIC_MARKER=FAIL marker=$marker"
        exit 13
    }
done
echo 'DIAGNOSTIC_MARKERS=PASS'

# Existing safety contract must still be present.
grep -Fq 'V4_DOOR_AUTOMATIC_RETRY_ALLOWED=false' "$SRC" || {
    echo 'NO_RETRY_CONTRACT=FAIL'
    exit 14
}
echo 'NO_RETRY_CONTRACT=PASS'

CFLAGS="$(pkg-config --cflags nice glib-2.0 gobject-2.0)"
LIBS="$(pkg-config --libs nice glib-2.0 gobject-2.0)"
gcc -std=c11 -O2 -g -Wall -Wextra $CFLAGS "$SRC" -o "$BIN" $LIBS

echo 'COMPILE=PASS'

for marker in \
  'V4_DOOR_REJECT_STAGE=CTPP_OPEN' \
  'V4_DOOR_REJECT_RESPONSE_WORD=%u' \
  'V4_DOOR_REQUESTED_CHANNEL_ID=%u' \
  'V4_DOOR_RESPONSE_CHANNEL_ID=%u' \
  'door-reject-diagnostic.txt'
do
    strings -a "$BIN" | grep -Fq "$marker" || {
        echo "BINARY_DIAGNOSTIC_MARKER=FAIL marker=$marker"
        exit 15
    }
done
echo 'BINARY_DIAGNOSTIC_MARKERS=PASS'

sha256sum "$BASE" "$SRC" "$BIN"

echo "DIFF_FILE=$DIFF"
echo "DIAGNOSTIC_BINARY=$BIN"
echo 'NETWORK_IO_PERFORMED=false'
echo 'DOOR_ACTION_SENT=false'
echo 'MEDIA_ACTION_SENT=false'
echo 'DOOR_REJECT_DIAGNOSTIC_BUILD=PASS'
