#!/usr/bin/env bash
# CT120 research-only launcher for one bounded metadata-only entrance observation.
#
# This launcher reuses the exact reviewed P30 network runner and applies only
# validation/configuration text patches needed to select the reviewed P36
# observation transform and to preserve the corrected P34 Door invariant gate.
# It executes the patched runner exactly once and never retries.
#
# Live boundary:
#   P30 signaling -> device 0x0008 -> NO ACK -> 3000 ms metadata-only receive
#   observation -> graceful PseudoTCP close (force=false) -> listener restore.
#
# No observed payload content is stored/emitted and no RTP/H264 inspection is
# allowed by the pinned transform.

set -u -o pipefail
umask 077

REPO=/root/comelit-door-diag-repo
REMOTE_REF=refs/remotes/origin/main
BASE_RUNNER_REL=safety-poc/research/media/v1/ct120_run_entrance_self_activation_signaling_probe.sh
BASE_RUNNER_BLOB=399db88970197d63f424262cfbde38d9253d816a
OBS_TRANSFORM_REL=safety-poc/research/media/v1/entrance_media_observation_transform.py
OBS_TRANSFORM_BLOB=85a66b95d4f2ed633f978901fc9041d4a5999531

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
RUN_ROOT="/root/comelit-entrance-media-observation-launch-$STAMP"
BASE_RUNNER="$RUN_ROOT/base-runner.sh"
PATCHED_RUNNER="$RUN_ROOT/patched-runner.sh"
DETAIL_LOG="$RUN_ROOT/detail.log"
PATCH_LOG="$RUN_ROOT/patch.log"
SUMMARY_FILE="$RUN_ROOT/summary.txt"

mkdir -p "$RUN_ROOT"
chmod 700 "$RUN_ROOT"

REMOTE_MAIN=UNAVAILABLE
RUNNER_BLOB=UNAVAILABLE
TRANSFORM_BLOB=UNAVAILABLE
PATCH_GATE=FAIL
RUNNER_RC=NOT_RUN

count_exact() {
    local marker="$1"
    grep -Fxc "$marker" "$DETAIL_LOG" 2>/dev/null || true
}

count_contains() {
    local marker="$1"
    grep -Fc "$marker" "$DETAIL_LOG" 2>/dev/null || true
}

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

write_summary() {
    local live_invocations listener_after obs_started obs_result obs_window
    local obs_ack_false stored_false emitted_false rtp_false
    local forbidden_true door_result events bytes max_chunk
    local final_gate=FAIL

    live_invocations="$(last_value 'LIVE_INVOCATIONS=' '0')"
    listener_after="$(last_value 'LISTENER_READY_AFTER=' 'NOT_REACHED')"
    obs_started="$(count_exact 'ENTRANCE_MEDIA_OBSERVATION_STARTED=true')"
    obs_result="$(count_exact 'ENTRANCE_MEDIA_OBSERVATION_RESULT=PASS')"
    obs_window="$(count_exact 'ENTRANCE_MEDIA_OBSERVATION_WINDOW_MS=3000')"
    obs_ack_false="$(count_exact 'ENTRANCE_MEDIA_OBSERVATION_DEVICE_VIDEO_ACK_SENT=false')"
    stored_false="$(count_exact 'ENTRANCE_MEDIA_OBSERVATION_PAYLOAD_STORED=false')"
    emitted_false="$(count_exact 'ENTRANCE_MEDIA_OBSERVATION_PAYLOAD_EMITTED=false')"
    rtp_false="$(count_exact 'ENTRANCE_RTP_H264_INSPECTION_PERFORMED=false')"
    forbidden_true="$(count_contains 'ENTRANCE_MEDIA_OBSERVATION_PAYLOAD_STORED=true')"
    forbidden_true=$((forbidden_true + $(count_contains 'ENTRANCE_MEDIA_OBSERVATION_PAYLOAD_EMITTED=true')))
    forbidden_true=$((forbidden_true + $(count_contains 'ENTRANCE_MEDIA_PAYLOAD_CAPTURED=true')))
    forbidden_true=$((forbidden_true + $(count_contains 'ENTRANCE_RTP_H264_INSPECTION_PERFORMED=true')))
    forbidden_true=$((forbidden_true + $(count_contains 'FINAL_DEVICE_VIDEO_ACK_SENT=true')))
    door_result="$(count_contains 'V4_DOOR_RESULT=')"
    events="$(last_value 'ENTRANCE_MEDIA_OBSERVATION_EVENTS=' 'MISSING')"
    bytes="$(last_value 'ENTRANCE_MEDIA_OBSERVATION_BYTES=' 'MISSING')"
    max_chunk="$(last_value 'ENTRANCE_MEDIA_OBSERVATION_MAX_CHUNK=' 'MISSING')"

    if [ "$RUNNER_RC" = 0 ] &&
       [ "$live_invocations" = 1 ] &&
       [ "$listener_after" = PASS ] &&
       [ "$obs_started" -eq 1 ] &&
       [ "$obs_result" -eq 1 ] &&
       [ "$obs_window" -eq 1 ] &&
       [ "$obs_ack_false" -eq 1 ] &&
       [ "$stored_false" -eq 1 ] &&
       [ "$emitted_false" -eq 1 ] &&
       [ "$rtp_false" -eq 1 ] &&
       [ "$forbidden_true" -eq 0 ] &&
       [ "$door_result" -eq 0 ] &&
       [[ "$events" =~ ^[0-9]+$ ]] &&
       [[ "$bytes" =~ ^[0-9]+$ ]] &&
       [[ "$max_chunk" =~ ^[0-9]+$ ]]; then
        final_gate=PASS
    fi

    {
        echo '=== COMELIT ENTRANCE MEDIA OBSERVATION SUMMARY ==='
        echo "REMOTE_MAIN=$REMOTE_MAIN"
        echo "BASE_RUNNER_BLOB=$RUNNER_BLOB"
        echo "OBS_TRANSFORM_BLOB=$TRANSFORM_BLOB"
        echo "RUNNER_PATCH_GATE=$PATCH_GATE"
        echo "RUNNER_RC=$RUNNER_RC"
        echo "LIVE_INVOCATIONS=$live_invocations"
        echo "LISTENER_READY_AFTER=$listener_after"
        echo "OBSERVATION_STARTED_COUNT=$obs_started"
        echo "OBSERVATION_RESULT_PASS_COUNT=$obs_result"
        echo "OBSERVATION_WINDOW_3000_COUNT=$obs_window"
        echo "DEVICE_VIDEO_ACK_FALSE_COUNT=$obs_ack_false"
        echo "PAYLOAD_STORED_FALSE_COUNT=$stored_false"
        echo "PAYLOAD_EMITTED_FALSE_COUNT=$emitted_false"
        echo "RTP_H264_INSPECTION_FALSE_COUNT=$rtp_false"
        echo "FORBIDDEN_TRUE_MARKER_COUNT=$forbidden_true"
        echo "DOOR_RESULT_MARKER_COUNT=$door_result"
        echo "OBSERVATION_EVENTS=$events"
        echo "OBSERVATION_BYTES=$bytes"
        echo "OBSERVATION_MAX_CHUNK=$max_chunk"
        echo 'AUTOMATIC_RETRY=false'
        echo 'FINAL_DEVICE_VIDEO_ACK_SENT=false'
        echo 'MEDIA_PAYLOAD_CAPTURED=false'
        echo 'DOOR_ACTION_SENT=false'
        echo "DETAIL_LOG=$DETAIL_LOG"
        echo "SUMMARY_FILE=$SUMMARY_FILE"
        echo "CT120_ENTRANCE_MEDIA_OBSERVATION_LAUNCH=$final_gate"
    } > "$SUMMARY_FILE"

    cat "$SUMMARY_FILE"
    [ "$final_gate" = PASS ]
}

finish() {
    local original_rc=$?
    local summary_rc=0
    write_summary || summary_rc=$?
    if [ "$original_rc" -ne 0 ]; then
        exit "$original_rc"
    fi
    exit "$summary_rc"
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
TRANSFORM_BLOB="$(git -C "$REPO" rev-parse "$REMOTE_MAIN:$OBS_TRANSFORM_REL" 2>/dev/null || true)"

if [ "$RUNNER_BLOB" != "$BASE_RUNNER_BLOB" ]; then
    echo "LAUNCHER_BASE_RUNNER_BLOB_GATE=FAIL actual=$RUNNER_BLOB expected=$BASE_RUNNER_BLOB" >> "$DETAIL_LOG"
    exit 1
fi

if [ "$TRANSFORM_BLOB" != "$OBS_TRANSFORM_BLOB" ]; then
    echo "LAUNCHER_OBS_TRANSFORM_BLOB_GATE=FAIL actual=$TRANSFORM_BLOB expected=$OBS_TRANSFORM_BLOB" >> "$DETAIL_LOG"
    exit 1
fi

git -C "$REPO" show "$REMOTE_MAIN:$BASE_RUNNER_REL" > "$BASE_RUNNER"
chmod 600 "$BASE_RUNNER"

python3 - "$BASE_RUNNER" "$PATCHED_RUNNER" > "$PATCH_LOG" 2>&1 <<'PY'
from pathlib import Path
import sys

src = Path(sys.argv[1]).read_text(encoding="utf-8")
out = Path(sys.argv[2])

replacements = [
    (
        "TRANSFORM_REL=safety-poc/research/media/v1/entrance_self_activation_signaling_transform.py",
        "TRANSFORM_REL=safety-poc/research/media/v1/entrance_media_observation_transform.py",
        "observation transform selection",
    ),
    (
        "if grep -Fq $'        100,\\n        v4_door_tick_cb,' \"$CANDIDATE_SOURCE\"; then",
        "if grep -Fq '        v4_door_tick_cb,' \"$CANDIDATE_SOURCE\"; then",
        "Door timer preflight",
    ),
    (
        '''    if [ "$COUNT" -ne 1 ]; then\n        LIVE_GATE=FAIL\n    fi\ndone\n''',
        '''    if [ "$marker" = 'ENTRANCE_SIGNALING_DOOR_ACTION_SENT=false' ]; then\n        if [ "$COUNT" -lt 1 ]; then\n            LIVE_GATE=FAIL\n        fi\n    elif [ "$COUNT" -ne 1 ]; then\n        LIVE_GATE=FAIL\n    fi\ndone\n''',
        "repeated false Door invariant",
    ),
]

patched = src
for old, new, label in replacements:
    count = patched.count(old)
    if count != 1:
        raise SystemExit(f"RUNNER_PATCH_ANCHOR_COUNT={count} LABEL={label}")
    patched = patched.replace(old, new, 1)

for forbidden in (
    "TRANSFORM_REL=safety-poc/research/media/v1/entrance_self_activation_signaling_transform.py",
    "if grep -Fq $'        100,\\n        v4_door_tick_cb,' \"$CANDIDATE_SOURCE\"; then",
):
    if forbidden in patched:
        raise SystemExit("RUNNER_PATCH_OLD_PATTERN_REMAINS=true")

if patched.count("TRANSFORM_REL=safety-poc/research/media/v1/entrance_media_observation_transform.py") != 1:
    raise SystemExit("RUNNER_OBSERVATION_TRANSFORM_SELECTION_INVALID=true")
if patched.count("if [ \"$marker\" = 'ENTRANCE_SIGNALING_DOOR_ACTION_SENT=false' ]; then") != 1:
    raise SystemExit("RUNNER_DOOR_INVARIANT_POLICY_INVALID=true")

out.write_text(patched, encoding="utf-8")
print("RUNNER_PATCH_GATE=PASS")
print("RUNNER_NETWORK_SEQUENCE_CHANGED=false")
print("RUNNER_OBSERVATION_TRANSFORM_SELECTED=true")
print("RUNNER_DOOR_INVARIANT_COUNT_POLICY=AT_LEAST_ONE")
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

# Exactly one invocation. The patched P30 runner itself retains all preflight,
# listener isolation, 75 s outer timeout, EXIT restore guard and no-retry gates.
"$PATCHED_RUNNER" > "$DETAIL_LOG" 2>&1
RUNNER_RC=$?

exit "$RUNNER_RC"
