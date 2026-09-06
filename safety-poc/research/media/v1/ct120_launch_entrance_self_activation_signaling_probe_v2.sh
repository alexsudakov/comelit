#!/usr/bin/env bash
# Quiet CT120 launcher for the reviewed entrance self-activation signaling probe.
#
# This launcher exists for two reasons:
# 1. correct the P30 multiline grep false-positive in the Door timer preflight;
# 2. keep the verbose runner output in a file and print only a compact summary
#    at the end of the terminal output.
#
# The reviewed P30 runner remains the network-capable implementation.  This
# launcher materializes that exact pinned blob, applies one source-text-only
# correction to the runner's preflight check, executes it exactly once, stores
# all verbose output in DETAIL_LOG, and never retries.

set -u -o pipefail
umask 077

REPO=/root/comelit-door-diag-repo
REMOTE_REF=refs/remotes/origin/main
BASE_RUNNER_REL=safety-poc/research/media/v1/ct120_run_entrance_self_activation_signaling_probe.sh
BASE_RUNNER_BLOB=399db88970197d63f424262cfbde38d9253d816a

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
RUN_ROOT="/root/comelit-entrance-signaling-launch-$STAMP"
BASE_RUNNER="$RUN_ROOT/base-runner.sh"
PATCHED_RUNNER="$RUN_ROOT/patched-runner.sh"
DETAIL_LOG="$RUN_ROOT/detail.log"
SUMMARY_FILE="$RUN_ROOT/summary.txt"
PATCH_LOG="$RUN_ROOT/patch.log"

mkdir -p "$RUN_ROOT"
chmod 700 "$RUN_ROOT"

LAUNCH_RC=1
PATCH_GATE=FAIL
REMOTE_MAIN=UNAVAILABLE
RUNNER_BLOB=UNAVAILABLE
RUNNER_RC=NOT_RUN

last_value() {
    local prefix="$1"
    local default_value="$2"
    local value

    value="$(grep -F "$prefix" "$DETAIL_LOG" 2>/dev/null | tail -n 1 | sed "s/^.*$prefix//" || true)"
    if [ -n "$value" ]; then
        printf '%s' "$value"
    else
        printf '%s' "$default_value"
    fi
}

count_exact() {
    local marker="$1"
    grep -Fxc "$marker" "$DETAIL_LOG" 2>/dev/null || true
}

count_contains() {
    local marker="$1"
    grep -Fc "$marker" "$DETAIL_LOG" 2>/dev/null || true
}

write_summary() {
    local preflight live_invocations listener_before listener_stop listener_restore listener_after
    local open_count reg_count self_sent self_ack video_sent video_ack device_video probe_pass
    local door_result_count door_action final_ack media_capture graceful_false

    preflight="$(last_value 'ENTRANCE_SIGNALING_PREFLIGHT=' 'NOT_REACHED')"
    live_invocations="$(last_value 'LIVE_INVOCATIONS=' '0')"
    listener_before="$(last_value 'LISTENER_READY_BEFORE=' 'NOT_REACHED')"
    listener_stop="$(last_value 'LISTENER_STOP_GATE=' 'NOT_REACHED')"
    listener_restore="$(last_value 'LISTENER_RESTORE_READY=' 'NOT_REACHED')"
    listener_after="$(last_value 'LISTENER_READY_AFTER=' 'NOT_REACHED')"

    open_count="$(count_exact 'PSEUDOTCP_OPEN=PASS')"
    reg_count="$(count_exact 'V4_CTPP_REGISTRATION=PASS')"
    self_sent="$(count_exact 'ENTRANCE_SELF_ACTIVATION_SENT=PASS')"
    self_ack="$(count_exact 'ENTRANCE_SELF_ACTIVATION_ACK=PASS')"
    video_sent="$(count_exact 'ENTRANCE_VIDEO_EVENT_SENT=PASS')"
    video_ack="$(count_exact 'ENTRANCE_VIDEO_EVENT_ACK=PASS')"
    device_video="$(count_exact 'ENTRANCE_DEVICE_VIDEO_EVENT=PASS')"
    probe_pass="$(count_exact 'ENTRANCE_SIGNALING_PROBE_RESULT=PASS')"
    graceful_false="$(count_exact 'PSEUDOTCP_GRACEFUL_CLOSE_FORCE=false')"

    door_result_count="$(count_contains 'V4_DOOR_RESULT=')"
    door_action="$(last_value 'DOOR_ACTION_SENT=' 'false')"
    final_ack="$(last_value 'FINAL_DEVICE_VIDEO_ACK_SENT=' 'false')"
    media_capture="$(last_value 'MEDIA_PAYLOAD_CAPTURED=' 'false')"

    {
        echo '=== COMELIT ENTRANCE SIGNALING SUMMARY ==='
        echo "REMOTE_MAIN=$REMOTE_MAIN"
        echo "BASE_RUNNER_BLOB=$RUNNER_BLOB"
        echo "RUNNER_PATCH_GATE=$PATCH_GATE"
        echo "RUNNER_RC=$RUNNER_RC"
        echo "PREFLIGHT=$preflight"
        echo "LIVE_INVOCATIONS=$live_invocations"
        echo "LISTENER_READY_BEFORE=$listener_before"
        echo "LISTENER_STOP_GATE=$listener_stop"
        echo "PSEUDOTCP_OPEN_COUNT=$open_count"
        echo "CTPP_REGISTRATION_COUNT=$reg_count"
        echo "SELF_ACTIVATION_SENT_COUNT=$self_sent"
        echo "SELF_ACTIVATION_ACK_COUNT=$self_ack"
        echo "CLIENT_VIDEO_EVENT_SENT_COUNT=$video_sent"
        echo "CLIENT_VIDEO_EVENT_ACK_COUNT=$video_ack"
        echo "DEVICE_VIDEO_EVENT_COUNT=$device_video"
        echo "SIGNALING_PROBE_PASS_COUNT=$probe_pass"
        echo "GRACEFUL_CLOSE_FORCE_FALSE_COUNT=$graceful_false"
        echo "DOOR_RESULT_MARKER_COUNT=$door_result_count"
        echo "DOOR_ACTION_SENT=$door_action"
        echo "FINAL_DEVICE_VIDEO_ACK_SENT=$final_ack"
        echo "MEDIA_PAYLOAD_CAPTURED=$media_capture"
        echo "LISTENER_RESTORE_READY=$listener_restore"
        echo "LISTENER_READY_AFTER=$listener_after"
        echo "AUTOMATIC_RETRY=false"
        echo "DETAIL_LOG=$DETAIL_LOG"
        echo "SUMMARY_FILE=$SUMMARY_FILE"

        if [ "$RUNNER_RC" = 0 ] &&
           [ "$live_invocations" = 1 ] &&
           [ "$open_count" -eq 1 ] &&
           [ "$reg_count" -eq 1 ] &&
           [ "$self_sent" -eq 1 ] &&
           [ "$self_ack" -eq 1 ] &&
           [ "$video_sent" -eq 1 ] &&
           [ "$video_ack" -eq 1 ] &&
           [ "$device_video" -eq 1 ] &&
           [ "$probe_pass" -eq 1 ] &&
           [ "$door_result_count" -eq 0 ] &&
           [ "$listener_after" = PASS ]; then
            echo 'CT120_ENTRANCE_SIGNALING_LAUNCH=PASS'
        else
            echo 'CT120_ENTRANCE_SIGNALING_LAUNCH=FAIL'
        fi
    } > "$SUMMARY_FILE"

    cat "$SUMMARY_FILE"
}

finish() {
    local rc=$?
    if [ "$rc" -eq 0 ]; then
        LAUNCH_RC=0
    else
        LAUNCH_RC="$rc"
    fi
    write_summary
    exit "$LAUNCH_RC"
}
trap finish EXIT

if [ "${EUID}" -ne 0 ]; then
    echo 'LAUNCHER_REQUIRES_ROOT=true' > "$DETAIL_LOG"
    exit 1
fi

for command in git python3 grep sed tail; do
    if ! command -v "$command" >/dev/null 2>&1; then
        echo "LAUNCHER_MISSING_COMMAND=$command" >> "$DETAIL_LOG"
        exit 1
    fi
done

if [ ! -d "$REPO/.git" ]; then
    echo 'LAUNCHER_REPO_PRESENT=false' >> "$DETAIL_LOG"
    exit 1
fi

if ! git -C "$REPO" rev-parse --verify -q "$REMOTE_REF" >/dev/null 2>&1; then
    echo 'LAUNCHER_REMOTE_MAIN_PRESENT=false' >> "$DETAIL_LOG"
    exit 1
fi

REMOTE_MAIN="$(git -C "$REPO" rev-parse "$REMOTE_REF")"
RUNNER_BLOB="$(git -C "$REPO" rev-parse "$REMOTE_MAIN:$BASE_RUNNER_REL" 2>/dev/null || true)"

if [ "$RUNNER_BLOB" != "$BASE_RUNNER_BLOB" ]; then
    echo "LAUNCHER_BASE_RUNNER_BLOB_GATE=FAIL actual=$RUNNER_BLOB expected=$BASE_RUNNER_BLOB" >> "$DETAIL_LOG"
    exit 1
fi

git -C "$REPO" show "$REMOTE_MAIN:$BASE_RUNNER_REL" > "$BASE_RUNNER"
chmod 600 "$BASE_RUNNER"

python3 - "$BASE_RUNNER" "$PATCHED_RUNNER" > "$PATCH_LOG" 2>&1 <<'PY'
from pathlib import Path
import sys

src = Path(sys.argv[1]).read_text(encoding="utf-8")
out = Path(sys.argv[2])

old = "if grep -Fq $'        100,\\n        v4_door_tick_cb,' \"$CANDIDATE_SOURCE\"; then"
new = "if grep -Fq '        v4_door_tick_cb,' \"$CANDIDATE_SOURCE\"; then"

count = src.count(old)
if count != 1:
    raise SystemExit(f"RUNNER_PATCH_ANCHOR_COUNT={count}")

patched = src.replace(old, new, 1)

if old in patched:
    raise SystemExit("RUNNER_PATCH_OLD_PATTERN_REMAINS=true")
if patched.count(new) != 1:
    raise SystemExit("RUNNER_PATCH_NEW_PATTERN_COUNT_INVALID=true")

out.write_text(patched, encoding="utf-8")
print("RUNNER_PATCH_GATE=PASS")
PY
PATCH_RC=$?

if [ "$PATCH_RC" -ne 0 ] || ! grep -Fxq 'RUNNER_PATCH_GATE=PASS' "$PATCH_LOG"; then
    cat "$PATCH_LOG" >> "$DETAIL_LOG"
    exit 1
fi

PATCH_GATE=PASS
chmod 700 "$PATCHED_RUNNER"

if ! bash -n "$PATCHED_RUNNER" > "$RUN_ROOT/bash-n.log" 2>&1; then
    cat "$RUN_ROOT/bash-n.log" >> "$DETAIL_LOG"
    exit 1
fi

# Exactly one invocation.  Verbose stdout/stderr are intentionally hidden from
# the interactive terminal and retained in DETAIL_LOG for forensic review.
"$PATCHED_RUNNER" > "$DETAIL_LOG" 2>&1
RUNNER_RC=$?

exit "$RUNNER_RC"
