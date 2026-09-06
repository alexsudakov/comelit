#!/usr/bin/env bash
# Quiet CT120 launcher for one bounded post-ACK structural observation run.
#
# This wrapper pins and reuses the exact merged P47 launcher, changing only the
# transform selected by its embedded reviewed runner patch:
#
#   P30 signaling -> exact device 0x0008
#   -> exactly one session-derived 0x1800 ACK
#   -> 3000 ms bounded structural-only observation
#   -> graceful PseudoTCP close (force=false)
#   -> mandatory listener restore.
#
# P47 still owns all network/listener behavior. This wrapper adds provenance for
# the merged P48 classifier and a second fail-closed result gate over structural
# metadata. It invokes the patched P47 launcher exactly once and never retries.

set -u -o pipefail
umask 077

REPO=/root/comelit-door-diag-repo
REMOTE_REF=refs/remotes/origin/main

BASE_LAUNCHER_REL=safety-poc/research/media/v1/ct120_launch_entrance_device_video_ack_observation_probe_v1.sh
BASE_LAUNCHER_EXPECTED_BLOB=093007b8930b19c069d253df19391d72e739122c

CLASSIFIER_TRANSFORM_REL=safety-poc/research/media/v1/entrance_post_ack_structural_classifier_transform.py
CLASSIFIER_TRANSFORM_EXPECTED_BLOB=269ad1b22d318551966b4f1a927c755f9ed00156

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
RUN_ROOT="/root/comelit-entrance-post-ack-structural-launch-$STAMP"
BASE_LAUNCHER="$RUN_ROOT/base-launcher.sh"
PATCHED_LAUNCHER="$RUN_ROOT/patched-launcher.sh"
PATCH_LOG="$RUN_ROOT/patch.log"
BASE_OUTPUT="$RUN_ROOT/base-output.log"
SUMMARY_FILE="$RUN_ROOT/summary.txt"

mkdir -p "$RUN_ROOT"
chmod 700 "$RUN_ROOT"

PROVENANCE_GATE=FAIL
PATCH_GATE=FAIL
REMOTE_MAIN=UNAVAILABLE
BASE_LAUNCHER_BLOB=UNAVAILABLE
CLASSIFIER_TRANSFORM_BLOB=UNAVAILABLE
BASE_RC=NOT_RUN

repo_blob() {
    local rel="$1"
    git -C "$REPO" rev-parse "$REMOTE_MAIN:$rel" 2>/dev/null || true
}

last_from_file() {
    local file="$1"
    local prefix="$2"
    local default_value="$3"
    local line

    line="$(grep -F "$prefix" "$file" 2>/dev/null | tail -n 1 || true)"
    if [ -n "$line" ]; then
        printf '%s' "${line#*"$prefix"}"
    else
        printf '%s' "$default_value"
    fi
}

count_contains_file() {
    local file="$1"
    local marker="$2"
    grep -Fc "$marker" "$file" 2>/dev/null || true
}

is_uint() {
    [[ "$1" =~ ^[0-9]+$ ]]
}

write_summary() {
    local base_result detail_log base_summary
    local live_invocations ack_sent final_ack obs_result listener_after auto_retry
    local payload_stored payload_emitted rtp_inspection door_action media_capture
    local struct_frames struct_ctpp struct_other struct_malformed struct_tail struct_lines
    local struct_raw struct_hex struct_base64 final_gate

    base_result="$(last_from_file "$BASE_OUTPUT" 'CT120_ENTRANCE_DEVICE_VIDEO_ACK_OBSERVATION_LAUNCH=' 'NOT_REACHED')"
    detail_log="$(last_from_file "$BASE_OUTPUT" 'DETAIL_LOG=' 'NOT_REACHED')"
    base_summary="$(last_from_file "$BASE_OUTPUT" 'SUMMARY_FILE=' 'NOT_REACHED')"

    live_invocations="$(last_from_file "$BASE_OUTPUT" 'LIVE_INVOCATIONS=' '0')"
    ack_sent="$(last_from_file "$BASE_OUTPUT" 'DEVICE_VIDEO_ACK_SENT_COUNT=' '0')"
    final_ack="$(last_from_file "$BASE_OUTPUT" 'FINAL_DEVICE_VIDEO_ACK_SENT=' 'NOT_REACHED')"
    obs_result="$(last_from_file "$BASE_OUTPUT" 'MEDIA_OBSERVATION_RESULT_COUNT=' '0')"
    listener_after="$(last_from_file "$BASE_OUTPUT" 'LISTENER_READY_AFTER=' 'NOT_REACHED')"
    auto_retry="$(last_from_file "$BASE_OUTPUT" 'AUTOMATIC_RETRY=' 'NOT_REACHED')"
    payload_stored="$(last_from_file "$BASE_OUTPUT" 'MEDIA_OBSERVATION_PAYLOAD_STORED=' 'NOT_REACHED')"
    payload_emitted="$(last_from_file "$BASE_OUTPUT" 'MEDIA_OBSERVATION_PAYLOAD_EMITTED=' 'NOT_REACHED')"
    rtp_inspection="$(last_from_file "$BASE_OUTPUT" 'RTP_H264_INSPECTION_PERFORMED=' 'NOT_REACHED')"
    door_action="$(last_from_file "$BASE_OUTPUT" 'DOOR_ACTION_SENT=' 'NOT_REACHED')"
    media_capture="$(last_from_file "$BASE_OUTPUT" 'MEDIA_PAYLOAD_CAPTURED=' 'NOT_REACHED')"

    struct_frames=NOT_REACHED
    struct_ctpp=NOT_REACHED
    struct_other=NOT_REACHED
    struct_malformed=NOT_REACHED
    struct_tail=NOT_REACHED
    struct_lines=0
    struct_raw=NOT_REACHED
    struct_hex=NOT_REACHED
    struct_base64=NOT_REACHED

    if [ "$detail_log" != NOT_REACHED ] && [ -f "$detail_log" ]; then
        struct_frames="$(last_from_file "$detail_log" 'ENTRANCE_POST_ACK_STRUCT_FRAMES=' 'NOT_REACHED')"
        struct_ctpp="$(last_from_file "$detail_log" 'ENTRANCE_POST_ACK_STRUCT_CTPP_FRAMES=' 'NOT_REACHED')"
        struct_other="$(last_from_file "$detail_log" 'ENTRANCE_POST_ACK_STRUCT_OTHER_FRAMES=' 'NOT_REACHED')"
        struct_malformed="$(last_from_file "$detail_log" 'ENTRANCE_POST_ACK_STRUCT_MALFORMED=' 'NOT_REACHED')"
        struct_tail="$(last_from_file "$detail_log" 'ENTRANCE_POST_ACK_STRUCT_TAIL_BYTES=' 'NOT_REACHED')"
        struct_lines="$(count_contains_file "$detail_log" 'ENTRANCE_POST_ACK_STRUCT_FRAME=')"
        struct_raw="$(last_from_file "$detail_log" 'ENTRANCE_POST_ACK_STRUCT_RAW_PAYLOAD_EMITTED=' 'NOT_REACHED')"
        struct_hex="$(last_from_file "$detail_log" 'ENTRANCE_POST_ACK_STRUCT_HEX_EMITTED=' 'NOT_REACHED')"
        struct_base64="$(last_from_file "$detail_log" 'ENTRANCE_POST_ACK_STRUCT_BASE64_EMITTED=' 'NOT_REACHED')"
    fi

    final_gate=FAIL
    if [ "$PROVENANCE_GATE" = PASS ] &&
       [ "$PATCH_GATE" = PASS ] &&
       [ "$BASE_RC" = 0 ] &&
       [ "$base_result" = PASS ] &&
       [ "$live_invocations" = 1 ] &&
       [ "$ack_sent" = 1 ] &&
       [ "$final_ack" = true ] &&
       [ "$obs_result" = 1 ] &&
       [ "$listener_after" = PASS ] &&
       [ "$auto_retry" = false ] &&
       [ "$payload_stored" = false ] &&
       [ "$payload_emitted" = false ] &&
       [ "$rtp_inspection" = false ] &&
       [ "$door_action" = false ] &&
       [ "$media_capture" = false ] &&
       is_uint "$struct_frames" &&
       is_uint "$struct_ctpp" &&
       is_uint "$struct_other" &&
       is_uint "$struct_malformed" &&
       is_uint "$struct_tail" &&
       [ "$struct_malformed" -eq 0 ] &&
       [ "$struct_lines" -eq "$struct_frames" ] &&
       [ $((struct_ctpp + struct_other)) -eq "$struct_frames" ] &&
       [ "$struct_tail" -le 511 ] &&
       [ "$struct_raw" = false ] &&
       [ "$struct_hex" = false ] &&
       [ "$struct_base64" = false ]; then
        final_gate=PASS
    fi

    {
        echo '=== COMELIT ENTRANCE POST-ACK STRUCTURAL SUMMARY ==='
        echo "REMOTE_MAIN=$REMOTE_MAIN"
        echo "BASE_LAUNCHER_BLOB=$BASE_LAUNCHER_BLOB"
        echo "CLASSIFIER_TRANSFORM_BLOB=$CLASSIFIER_TRANSFORM_BLOB"
        echo "PROVENANCE_GATE=$PROVENANCE_GATE"
        echo "LAUNCHER_PATCH_GATE=$PATCH_GATE"
        echo "BASE_LAUNCHER_RC=$BASE_RC"
        echo "BASE_LAUNCH_RESULT=$base_result"
        echo "LIVE_INVOCATIONS=$live_invocations"
        echo "DEVICE_VIDEO_ACK_SENT_COUNT=$ack_sent"
        echo "FINAL_DEVICE_VIDEO_ACK_SENT=$final_ack"
        echo "MEDIA_OBSERVATION_RESULT_COUNT=$obs_result"
        echo "STRUCT_FRAME_LINES=$struct_lines"
        echo "STRUCT_FRAMES=$struct_frames"
        echo "STRUCT_CTPP_FRAMES=$struct_ctpp"
        echo "STRUCT_OTHER_FRAMES=$struct_other"
        echo "STRUCT_MALFORMED=$struct_malformed"
        echo "STRUCT_TAIL_BYTES=$struct_tail"
        echo "STRUCT_RAW_PAYLOAD_EMITTED=$struct_raw"
        echo "STRUCT_HEX_EMITTED=$struct_hex"
        echo "STRUCT_BASE64_EMITTED=$struct_base64"
        echo "MEDIA_OBSERVATION_PAYLOAD_STORED=$payload_stored"
        echo "MEDIA_OBSERVATION_PAYLOAD_EMITTED=$payload_emitted"
        echo "RTP_H264_INSPECTION_PERFORMED=$rtp_inspection"
        echo "DOOR_ACTION_SENT=$door_action"
        echo "MEDIA_PAYLOAD_CAPTURED=$media_capture"
        echo "LISTENER_READY_AFTER=$listener_after"
        echo "AUTOMATIC_RETRY=$auto_retry"
        echo
        echo '=== POST-ACK STRUCTURAL FRAME METADATA ==='
        if [ "$detail_log" != NOT_REACHED ] && [ -f "$detail_log" ]; then
            grep -F 'ENTRANCE_POST_ACK_STRUCT_FRAME=' "$detail_log" 2>/dev/null || true
        fi
        echo '=== END POST-ACK STRUCTURAL FRAME METADATA ==='
        echo
        echo "BASE_DETAIL_LOG=$detail_log"
        echo "BASE_SUMMARY_FILE=$base_summary"
        echo "WRAPPER_OUTPUT=$BASE_OUTPUT"
        echo "SUMMARY_FILE=$SUMMARY_FILE"
        echo "CT120_ENTRANCE_POST_ACK_STRUCTURAL_LAUNCH=$final_gate"
    } > "$SUMMARY_FILE"

    cat "$SUMMARY_FILE"
}

finish() {
    local original_rc=$?
    local final_rc="$original_rc"

    write_summary

    if ! grep -Fxq 'CT120_ENTRANCE_POST_ACK_STRUCTURAL_LAUNCH=PASS' "$SUMMARY_FILE"; then
        if [ "$final_rc" -eq 0 ]; then
            final_rc=1
        fi
    fi

    trap - EXIT
    exit "$final_rc"
}
trap finish EXIT

if [ "${EUID}" -ne 0 ]; then
    echo 'WRAPPER_REQUIRES_ROOT=true' > "$BASE_OUTPUT"
    exit 1
fi

for command in git python3 grep tail; do
    if ! command -v "$command" >/dev/null 2>&1; then
        echo "WRAPPER_MISSING_COMMAND=$command" >> "$BASE_OUTPUT"
        exit 1
    fi
done

if [ ! -d "$REPO/.git" ]; then
    echo 'WRAPPER_REPO_PRESENT=false' >> "$BASE_OUTPUT"
    exit 1
fi

if ! git -C "$REPO" rev-parse --verify -q "$REMOTE_REF" >/dev/null 2>&1; then
    echo 'WRAPPER_REMOTE_MAIN_PRESENT=false' >> "$BASE_OUTPUT"
    exit 1
fi

REMOTE_MAIN="$(git -C "$REPO" rev-parse "$REMOTE_REF")"
BASE_LAUNCHER_BLOB="$(repo_blob "$BASE_LAUNCHER_REL")"
CLASSIFIER_TRANSFORM_BLOB="$(repo_blob "$CLASSIFIER_TRANSFORM_REL")"

if [ "$BASE_LAUNCHER_BLOB" != "$BASE_LAUNCHER_EXPECTED_BLOB" ]; then
    echo "WRAPPER_BASE_LAUNCHER_BLOB_GATE=FAIL actual=$BASE_LAUNCHER_BLOB expected=$BASE_LAUNCHER_EXPECTED_BLOB" >> "$BASE_OUTPUT"
    exit 1
fi
if [ "$CLASSIFIER_TRANSFORM_BLOB" != "$CLASSIFIER_TRANSFORM_EXPECTED_BLOB" ]; then
    echo "WRAPPER_CLASSIFIER_TRANSFORM_BLOB_GATE=FAIL actual=$CLASSIFIER_TRANSFORM_BLOB expected=$CLASSIFIER_TRANSFORM_EXPECTED_BLOB" >> "$BASE_OUTPUT"
    exit 1
fi

PROVENANCE_GATE=PASS

git -C "$REPO" show "$REMOTE_MAIN:$BASE_LAUNCHER_REL" > "$BASE_LAUNCHER"
chmod 600 "$BASE_LAUNCHER"

python3 - "$BASE_LAUNCHER" "$PATCHED_LAUNCHER" > "$PATCH_LOG" 2>&1 <<'PY'
from pathlib import Path
import sys

src = Path(sys.argv[1]).read_text(encoding="utf-8")
out = Path(sys.argv[2])

old_transform = '''new_transform = (
    "TRANSFORM_REL=safety-poc/research/media/v1/"
    "entrance_device_video_ack_observation_transform.py"
)
'''
new_transform = '''new_transform = (
    "TRANSFORM_REL=safety-poc/research/media/v1/"
    "entrance_post_ack_structural_classifier_transform.py"
)
'''

old_marker = 'print("RUNNER_TRANSFORM=entrance_device_video_ack_observation_transform.py")'
new_marker = 'print("RUNNER_TRANSFORM=entrance_post_ack_structural_classifier_transform.py")'

for label, old in (("TRANSFORM", old_transform), ("MARKER", old_marker)):
    count = src.count(old)
    if count != 1:
        raise SystemExit(f"P47_{label}_PATCH_ANCHOR_COUNT={count}")

patched = src.replace(old_transform, new_transform, 1)
patched = patched.replace(old_marker, new_marker, 1)

for label, old, new in (
    ("TRANSFORM", old_transform, new_transform),
    ("MARKER", old_marker, new_marker),
):
    if old in patched:
        raise SystemExit(f"P47_{label}_PATCH_OLD_PATTERN_REMAINS=true")
    if patched.count(new) != 1:
        raise SystemExit(f"P47_{label}_PATCH_NEW_PATTERN_COUNT_INVALID=true")

out.write_text(patched, encoding="utf-8")
print("P47_LAUNCHER_PATCH_GATE=PASS")
print("P47_RUNNER_TRANSFORM=entrance_post_ack_structural_classifier_transform.py")
print("P47_NETWORK_SEQUENCE_CHANGED=false")
print("P47_AUTOMATIC_RETRY=false")
PY
PATCH_RC=$?

if [ "$PATCH_RC" -ne 0 ] || ! grep -Fxq 'P47_LAUNCHER_PATCH_GATE=PASS' "$PATCH_LOG"; then
    cat "$PATCH_LOG" >> "$BASE_OUTPUT"
    exit 1
fi

PATCH_GATE=PASS
chmod 700 "$PATCHED_LAUNCHER"

if ! bash -n "$PATCHED_LAUNCHER" > "$RUN_ROOT/bash-n.log" 2>&1; then
    cat "$RUN_ROOT/bash-n.log" >> "$BASE_OUTPUT"
    exit 1
fi

# Exactly one P47 launcher invocation. The pinned P47 launcher invokes its
# patched reviewed runner exactly once; that runner permits at most one live
# wrapper invocation and has mandatory listener EXIT restoration.
"$PATCHED_LAUNCHER" > "$BASE_OUTPUT" 2>&1
BASE_RC=$?

exit "$BASE_RC"
