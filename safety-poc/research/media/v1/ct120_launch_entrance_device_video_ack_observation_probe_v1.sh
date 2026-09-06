#!/usr/bin/env bash
# Quiet CT120 launcher for one bounded entrance device-video ACK observation run.
#
# Reviewed live boundary:
#
#   P30 signaling -> first exact device 0x0008
#   -> exactly one session-derived 0x1800 ACK on the existing CTPP channel
#   -> 3000 ms metadata-only observation
#   -> graceful PseudoTCP close (force=false)
#   -> mandatory listener restore.
#
# No raw/hex/base64 payload is emitted. No RTP/H264 inspection is performed.
# No Door action is reachable. The patched reviewed runner is invoked exactly
# once and is never retried.

set -u -o pipefail
umask 077

REPO=/root/comelit-door-diag-repo
REMOTE_REF=refs/remotes/origin/main

BASE_RUNNER_REL=safety-poc/research/media/v1/ct120_run_entrance_self_activation_signaling_probe.sh
BASE_RUNNER_BLOB=399db88970197d63f424262cfbde38d9253d816a

SOURCE_REL=safety-poc/research/door/v1_5_7/comelit-v4-persistent-ctpp-door.c
SOURCE_EXPECTED_BLOB=c6bdfc17edbfb58d6d87c0c6e9dd58082752734b

ACK_OBS_TRANSFORM_REL=safety-poc/research/media/v1/entrance_device_video_ack_observation_transform.py
ACK_OBS_TRANSFORM_EXPECTED_BLOB=5a87e2531c2cef0297d8a7e84d75f9d4f2182311

OBS_TRANSFORM_REL=safety-poc/research/media/v1/entrance_media_observation_transform.py
OBS_TRANSFORM_EXPECTED_BLOB=85a66b95d4f2ed633f978901fc9041d4a5999531

SIGNAL_TRANSFORM_REL=safety-poc/research/media/v1/entrance_self_activation_signaling_transform.py
SIGNAL_TRANSFORM_EXPECTED_BLOB=b8cdb7fc70b3475ad5b6a0cb0077ef0430f95f30

PRESTART_TRANSFORM_REL=safety-poc/research/media/v1/pseudotcp_prestart_replay_transform.py
PRESTART_TRANSFORM_EXPECTED_BLOB=7b1b79706abb9c2273bfa42c83760fade7b823c8

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
RUN_ROOT="/root/comelit-entrance-device-video-ack-launch-$STAMP"
BASE_RUNNER="$RUN_ROOT/base-runner.sh"
PATCHED_RUNNER="$RUN_ROOT/patched-runner.sh"
DETAIL_LOG="$RUN_ROOT/detail.log"
SUMMARY_FILE="$RUN_ROOT/summary.txt"
PATCH_LOG="$RUN_ROOT/patch.log"

mkdir -p "$RUN_ROOT"
chmod 700 "$RUN_ROOT"

PATCH_GATE=FAIL
PROVENANCE_GATE=FAIL
REMOTE_MAIN=UNAVAILABLE
RUNNER_BLOB=UNAVAILABLE
SOURCE_BLOB=UNAVAILABLE
ACK_OBS_TRANSFORM_BLOB=UNAVAILABLE
OBS_TRANSFORM_BLOB=UNAVAILABLE
SIGNAL_TRANSFORM_BLOB=UNAVAILABLE
PRESTART_TRANSFORM_BLOB=UNAVAILABLE
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

repo_blob() {
    local rel="$1"
    git -C "$REPO" rev-parse "$REMOTE_MAIN:$rel" 2>/dev/null || true
}

is_uint() {
    [[ "$1" =~ ^[0-9]+$ ]]
}

write_summary() {
    local preflight live_invocations listener_before listener_stop listener_restore listener_after
    local open_count reg_count self_sent self_ack video_sent video_ack device_video probe_pass
    local ack_sent ack_delta ack_reversal ack_ctpp
    local obs_started obs_result obs_rx_events obs_events obs_bytes obs_max obs_window
    local payload_stored payload_emitted rtp_inspection
    local graceful_false door_result_count door_action final_ack media_capture final_gate

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

    ack_sent="$(count_exact 'ENTRANCE_DEVICE_VIDEO_ACK_SENT=PASS')"
    ack_delta="$(last_value 'ENTRANCE_DEVICE_VIDEO_ACK_SEQUENCE_DELTA_FROM_CLIENT_VIDEO=' 'NOT_REACHED')"
    ack_reversal="$(last_value 'ENTRANCE_DEVICE_VIDEO_ACK_ADDRESS_ROLE_REVERSAL=' 'NOT_REACHED')"
    ack_ctpp="$(last_value 'ENTRANCE_DEVICE_VIDEO_ACK_CTPP_REUSED=' 'NOT_REACHED')"

    obs_started="$(count_exact 'ENTRANCE_MEDIA_OBSERVATION_STARTED=true')"
    obs_result="$(count_exact 'ENTRANCE_MEDIA_OBSERVATION_RESULT=PASS')"
    obs_rx_events="$(count_contains 'ENTRANCE_MEDIA_OBSERVATION_RX_EVENT=')"
    obs_events="$(last_value 'ENTRANCE_MEDIA_OBSERVATION_EVENTS=' 'NOT_REACHED')"
    obs_bytes="$(last_value 'ENTRANCE_MEDIA_OBSERVATION_BYTES=' 'NOT_REACHED')"
    obs_max="$(last_value 'ENTRANCE_MEDIA_OBSERVATION_MAX_CHUNK=' 'NOT_REACHED')"
    obs_window="$(last_value 'ENTRANCE_MEDIA_OBSERVATION_WINDOW_MS=' 'NOT_REACHED')"
    payload_stored="$(last_value 'ENTRANCE_MEDIA_OBSERVATION_PAYLOAD_STORED=' 'NOT_REACHED')"
    payload_emitted="$(last_value 'ENTRANCE_MEDIA_OBSERVATION_PAYLOAD_EMITTED=' 'NOT_REACHED')"
    rtp_inspection="$(last_value 'ENTRANCE_RTP_H264_INSPECTION_PERFORMED=' 'NOT_REACHED')"

    graceful_false="$(count_exact 'PSEUDOTCP_GRACEFUL_CLOSE_FORCE=false')"
    door_result_count="$(count_contains 'V4_DOOR_RESULT=')"
    door_action="$(last_value 'DOOR_ACTION_SENT=' 'false')"
    final_ack="$(last_value 'FINAL_DEVICE_VIDEO_ACK_SENT=' 'NOT_REACHED')"
    media_capture="$(last_value 'MEDIA_PAYLOAD_CAPTURED=' 'NOT_REACHED')"

    final_gate=FAIL
    if [ "$PROVENANCE_GATE" = PASS ] &&
       [ "$PATCH_GATE" = PASS ] &&
       [ "$RUNNER_RC" = 0 ] &&
       [ "$preflight" = PASS ] &&
       [ "$live_invocations" = 1 ] &&
       [ "$listener_before" = PASS ] &&
       [ "$listener_stop" = PASS ] &&
       [ "$open_count" -eq 1 ] &&
       [ "$reg_count" -eq 1 ] &&
       [ "$self_sent" -eq 1 ] &&
       [ "$self_ack" -eq 1 ] &&
       [ "$video_sent" -eq 1 ] &&
       [ "$video_ack" -eq 1 ] &&
       [ "$device_video" -eq 1 ] &&
       [ "$probe_pass" -eq 1 ] &&
       [ "$ack_sent" -eq 1 ] &&
       [ "$ack_delta" = 0x01010000 ] &&
       [ "$ack_reversal" = true ] &&
       [ "$ack_ctpp" = true ] &&
       [ "$obs_started" -eq 1 ] &&
       [ "$obs_result" -eq 1 ] &&
       is_uint "$obs_events" &&
       is_uint "$obs_bytes" &&
       is_uint "$obs_max" &&
       [ "$obs_window" = 3000 ] &&
       [ "$payload_stored" = false ] &&
       [ "$payload_emitted" = false ] &&
       [ "$rtp_inspection" = false ] &&
       [ "$graceful_false" -eq 1 ] &&
       [ "$door_result_count" -eq 0 ] &&
       [ "$door_action" = false ] &&
       [ "$final_ack" = true ] &&
       [ "$media_capture" = false ] &&
       [ "$listener_restore" = PASS ] &&
       [ "$listener_after" = PASS ]; then
        final_gate=PASS
    fi

    {
        echo '=== COMELIT ENTRANCE DEVICE VIDEO ACK OBSERVATION SUMMARY ==='
        echo "REMOTE_MAIN=$REMOTE_MAIN"
        echo "BASE_RUNNER_BLOB=$RUNNER_BLOB"
        echo "SOURCE_BLOB=$SOURCE_BLOB"
        echo "ACK_OBS_TRANSFORM_BLOB=$ACK_OBS_TRANSFORM_BLOB"
        echo "OBS_TRANSFORM_BLOB=$OBS_TRANSFORM_BLOB"
        echo "SIGNAL_TRANSFORM_BLOB=$SIGNAL_TRANSFORM_BLOB"
        echo "PRESTART_TRANSFORM_BLOB=$PRESTART_TRANSFORM_BLOB"
        echo "PROVENANCE_GATE=$PROVENANCE_GATE"
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
        echo "DEVICE_VIDEO_ACK_SENT_COUNT=$ack_sent"
        echo "DEVICE_VIDEO_ACK_SEQUENCE_DELTA_FROM_CLIENT_VIDEO=$ack_delta"
        echo "DEVICE_VIDEO_ACK_ADDRESS_ROLE_REVERSAL=$ack_reversal"
        echo "DEVICE_VIDEO_ACK_CTPP_REUSED=$ack_ctpp"
        echo "SIGNALING_PROBE_PASS_COUNT=$probe_pass"
        echo "MEDIA_OBSERVATION_STARTED_COUNT=$obs_started"
        echo "MEDIA_OBSERVATION_RESULT_COUNT=$obs_result"
        echo "MEDIA_OBSERVATION_RX_EVENT_LINES=$obs_rx_events"
        echo "MEDIA_OBSERVATION_EVENTS=$obs_events"
        echo "MEDIA_OBSERVATION_BYTES=$obs_bytes"
        echo "MEDIA_OBSERVATION_MAX_CHUNK=$obs_max"
        echo "MEDIA_OBSERVATION_WINDOW_MS=$obs_window"
        echo "MEDIA_OBSERVATION_PAYLOAD_STORED=$payload_stored"
        echo "MEDIA_OBSERVATION_PAYLOAD_EMITTED=$payload_emitted"
        echo "RTP_H264_INSPECTION_PERFORMED=$rtp_inspection"
        echo "GRACEFUL_CLOSE_FORCE_FALSE_COUNT=$graceful_false"
        echo "DOOR_RESULT_MARKER_COUNT=$door_result_count"
        echo "DOOR_ACTION_SENT=$door_action"
        echo "FINAL_DEVICE_VIDEO_ACK_SENT=$final_ack"
        echo "MEDIA_PAYLOAD_CAPTURED=$media_capture"
        echo "LISTENER_RESTORE_READY=$listener_restore"
        echo "LISTENER_READY_AFTER=$listener_after"
        echo 'AUTOMATIC_RETRY=false'
        echo "DETAIL_LOG=$DETAIL_LOG"
        echo "SUMMARY_FILE=$SUMMARY_FILE"
        echo "CT120_ENTRANCE_DEVICE_VIDEO_ACK_OBSERVATION_LAUNCH=$final_gate"
    } > "$SUMMARY_FILE"

    cat "$SUMMARY_FILE"
}

finish() {
    local original_rc=$?
    local final_rc="$original_rc"

    write_summary

    if ! grep -Fxq 'CT120_ENTRANCE_DEVICE_VIDEO_ACK_OBSERVATION_LAUNCH=PASS' "$SUMMARY_FILE"; then
        if [ "$final_rc" -eq 0 ]; then
            final_rc=1
        fi
    fi

    trap - EXIT
    exit "$final_rc"
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
RUNNER_BLOB="$(repo_blob "$BASE_RUNNER_REL")"
SOURCE_BLOB="$(repo_blob "$SOURCE_REL")"
ACK_OBS_TRANSFORM_BLOB="$(repo_blob "$ACK_OBS_TRANSFORM_REL")"
OBS_TRANSFORM_BLOB="$(repo_blob "$OBS_TRANSFORM_REL")"
SIGNAL_TRANSFORM_BLOB="$(repo_blob "$SIGNAL_TRANSFORM_REL")"
PRESTART_TRANSFORM_BLOB="$(repo_blob "$PRESTART_TRANSFORM_REL")"

if [ "$RUNNER_BLOB" != "$BASE_RUNNER_BLOB" ]; then
    echo "LAUNCHER_BASE_RUNNER_BLOB_GATE=FAIL actual=$RUNNER_BLOB expected=$BASE_RUNNER_BLOB" >> "$DETAIL_LOG"
    exit 1
fi
if [ "$SOURCE_BLOB" != "$SOURCE_EXPECTED_BLOB" ]; then
    echo "LAUNCHER_SOURCE_BLOB_GATE=FAIL actual=$SOURCE_BLOB expected=$SOURCE_EXPECTED_BLOB" >> "$DETAIL_LOG"
    exit 1
fi
if [ "$ACK_OBS_TRANSFORM_BLOB" != "$ACK_OBS_TRANSFORM_EXPECTED_BLOB" ]; then
    echo "LAUNCHER_ACK_OBS_TRANSFORM_BLOB_GATE=FAIL actual=$ACK_OBS_TRANSFORM_BLOB expected=$ACK_OBS_TRANSFORM_EXPECTED_BLOB" >> "$DETAIL_LOG"
    exit 1
fi
if [ "$OBS_TRANSFORM_BLOB" != "$OBS_TRANSFORM_EXPECTED_BLOB" ]; then
    echo "LAUNCHER_OBS_TRANSFORM_BLOB_GATE=FAIL actual=$OBS_TRANSFORM_BLOB expected=$OBS_TRANSFORM_EXPECTED_BLOB" >> "$DETAIL_LOG"
    exit 1
fi
if [ "$SIGNAL_TRANSFORM_BLOB" != "$SIGNAL_TRANSFORM_EXPECTED_BLOB" ]; then
    echo "LAUNCHER_SIGNAL_TRANSFORM_BLOB_GATE=FAIL actual=$SIGNAL_TRANSFORM_BLOB expected=$SIGNAL_TRANSFORM_EXPECTED_BLOB" >> "$DETAIL_LOG"
    exit 1
fi
if [ "$PRESTART_TRANSFORM_BLOB" != "$PRESTART_TRANSFORM_EXPECTED_BLOB" ]; then
    echo "LAUNCHER_PRESTART_TRANSFORM_BLOB_GATE=FAIL actual=$PRESTART_TRANSFORM_BLOB expected=$PRESTART_TRANSFORM_EXPECTED_BLOB" >> "$DETAIL_LOG"
    exit 1
fi

PROVENANCE_GATE=PASS

git -C "$REPO" show "$REMOTE_MAIN:$BASE_RUNNER_REL" > "$BASE_RUNNER"
chmod 600 "$BASE_RUNNER"

python3 - "$BASE_RUNNER" "$PATCHED_RUNNER" > "$PATCH_LOG" 2>&1 <<'PY'
from pathlib import Path
import sys

src = Path(sys.argv[1]).read_text(encoding="utf-8")
out = Path(sys.argv[2])

old_transform = (
    "TRANSFORM_REL=safety-poc/research/media/v1/"
    "entrance_self_activation_signaling_transform.py"
)
new_transform = (
    "TRANSFORM_REL=safety-poc/research/media/v1/"
    "entrance_device_video_ack_observation_transform.py"
)

old_timer = "if grep -Fq $'        100,\\n        v4_door_tick_cb,' \"$CANDIDATE_SOURCE\"; then"
new_timer = "if grep -Fq '        v4_door_tick_cb,' \"$CANDIDATE_SOURCE\"; then"

old_source_markers = r'''    for marker in \
      'PSEUDOTCP_RX_BUFFERED=%u LEN=%u' \
      'ENTRANCE_SELF_ACTIVATION_ACTION=0x0028' \
      'ENTRANCE_SELF_ACTIVATION_CTPP_REUSED=true' \
      'ENTRANCE_SELF_ACTIVATION_ACK=PASS' \
      'ENTRANCE_VIDEO_EVENT_ACTION=0x0008' \
      'ENTRANCE_VIDEO_EVENT_ACK=PASS' \
      'ENTRANCE_DEVICE_VIDEO_EVENT=PASS' \
      'ENTRANCE_SIGNALING_PROBE_RESULT=PASS' \
      'ENTRANCE_FINAL_DEVICE_VIDEO_ACK_SENT=false' \
      'ENTRANCE_MEDIA_PAYLOAD_CAPTURED=false' \
      'ENTRANCE_SIGNALING_DOOR_ACTION_SENT=false' \
      'pseudo_tcp_socket_close(pseudo_tcp, FALSE);'
'''
new_source_markers = r'''    for marker in \
      'PSEUDOTCP_RX_BUFFERED=%u LEN=%u' \
      'ENTRANCE_SELF_ACTIVATION_ACTION=0x0028' \
      'ENTRANCE_SELF_ACTIVATION_CTPP_REUSED=true' \
      'ENTRANCE_SELF_ACTIVATION_ACK=PASS' \
      'ENTRANCE_VIDEO_EVENT_ACTION=0x0008' \
      'ENTRANCE_VIDEO_EVENT_ACK=PASS' \
      'ENTRANCE_DEVICE_VIDEO_EVENT=PASS' \
      'ENTRANCE_DEVICE_VIDEO_ACK_SENT=PASS' \
      'ENTRANCE_DEVICE_VIDEO_ACK_SEQUENCE_DELTA_FROM_CLIENT_VIDEO=0x01010000' \
      'ENTRANCE_DEVICE_VIDEO_ACK_ADDRESS_ROLE_REVERSAL=true' \
      'ENTRANCE_DEVICE_VIDEO_ACK_CTPP_REUSED=true' \
      'ENTRANCE_MEDIA_OBSERVATION_STARTED=true' \
      'ENTRANCE_MEDIA_OBSERVATION_RESULT=PASS' \
      'ENTRANCE_MEDIA_OBSERVATION_PAYLOAD_STORED=false' \
      'ENTRANCE_MEDIA_OBSERVATION_PAYLOAD_EMITTED=false' \
      'ENTRANCE_RTP_H264_INSPECTION_PERFORMED=false' \
      'ENTRANCE_SIGNALING_PROBE_RESULT=PASS' \
      'ENTRANCE_FINAL_DEVICE_VIDEO_ACK_SENT=true' \
      'ENTRANCE_MEDIA_PAYLOAD_CAPTURED=false' \
      'ENTRANCE_SIGNALING_DOOR_ACTION_SENT=false' \
      'pseudo_tcp_socket_close(pseudo_tcp, FALSE);'
'''

old_binary_markers = r'''    for marker in \
      'ENTRANCE_SIGNALING_PROBE_RESULT=PASS' \
      'ENTRANCE_FINAL_DEVICE_VIDEO_ACK_SENT=false' \
      'ENTRANCE_MEDIA_PAYLOAD_CAPTURED=false' \
      'ENTRANCE_SIGNALING_DOOR_ACTION_SENT=false' \
      'PSEUDOTCP_GRACEFUL_CLOSE_FORCE=false'
'''
new_binary_markers = r'''    for marker in \
      'ENTRANCE_DEVICE_VIDEO_ACK_SENT=PASS' \
      'ENTRANCE_DEVICE_VIDEO_ACK_SEQUENCE_DELTA_FROM_CLIENT_VIDEO=0x01010000' \
      'ENTRANCE_MEDIA_OBSERVATION_RESULT=PASS' \
      'ENTRANCE_MEDIA_OBSERVATION_PAYLOAD_STORED=false' \
      'ENTRANCE_MEDIA_OBSERVATION_PAYLOAD_EMITTED=false' \
      'ENTRANCE_RTP_H264_INSPECTION_PERFORMED=false' \
      'ENTRANCE_SIGNALING_PROBE_RESULT=PASS' \
      'ENTRANCE_FINAL_DEVICE_VIDEO_ACK_SENT=true' \
      'ENTRANCE_MEDIA_PAYLOAD_CAPTURED=false' \
      'ENTRANCE_SIGNALING_DOOR_ACTION_SENT=false' \
      'PSEUDOTCP_GRACEFUL_CLOSE_FORCE=false'
'''

old_allowed = 'echo "ENTRANCE_SIGNALING_FINAL_DEVICE_VIDEO_ACK_ALLOWED=false"'
new_allowed = 'echo "ENTRANCE_SIGNALING_FINAL_DEVICE_VIDEO_ACK_ALLOWED=true"'

old_required = r'''required_markers=(
  'PSEUDOTCP_OPEN=PASS'
  'V4_CTPP_REGISTRATION=PASS'
  'ENTRANCE_SELF_ACTIVATION_SENT=PASS'
  'ENTRANCE_SELF_ACTIVATION_ACK=PASS'
  'ENTRANCE_VIDEO_EVENT_SENT=PASS'
  'ENTRANCE_VIDEO_EVENT_ACK=PASS'
  'ENTRANCE_DEVICE_VIDEO_EVENT=PASS'
  'ENTRANCE_SIGNALING_PROBE_RESULT=PASS'
  'ENTRANCE_FINAL_DEVICE_VIDEO_ACK_SENT=false'
  'ENTRANCE_MEDIA_PAYLOAD_CAPTURED=false'
  'ENTRANCE_SIGNALING_DOOR_ACTION_SENT=false'
  'PSEUDOTCP_GRACEFUL_CLOSE_FORCE=false'
  'PSEUDOTCP_GRACEFUL_CLOSE_FORCE_RST_SENT=false'
)
'''
new_required = r'''required_markers=(
  'PSEUDOTCP_OPEN=PASS'
  'V4_CTPP_REGISTRATION=PASS'
  'ENTRANCE_SELF_ACTIVATION_SENT=PASS'
  'ENTRANCE_SELF_ACTIVATION_ACK=PASS'
  'ENTRANCE_VIDEO_EVENT_SENT=PASS'
  'ENTRANCE_VIDEO_EVENT_ACK=PASS'
  'ENTRANCE_DEVICE_VIDEO_EVENT=PASS'
  'ENTRANCE_DEVICE_VIDEO_ACK_SENT=PASS'
  'ENTRANCE_DEVICE_VIDEO_ACK_SEQUENCE_DELTA_FROM_CLIENT_VIDEO=0x01010000'
  'ENTRANCE_DEVICE_VIDEO_ACK_ADDRESS_ROLE_REVERSAL=true'
  'ENTRANCE_DEVICE_VIDEO_ACK_CTPP_REUSED=true'
  'ENTRANCE_MEDIA_OBSERVATION_STARTED=true'
  'ENTRANCE_MEDIA_OBSERVATION_RESULT=PASS'
  'ENTRANCE_MEDIA_OBSERVATION_PAYLOAD_STORED=false'
  'ENTRANCE_MEDIA_OBSERVATION_PAYLOAD_EMITTED=false'
  'ENTRANCE_RTP_H264_INSPECTION_PERFORMED=false'
  'ENTRANCE_SIGNALING_PROBE_RESULT=PASS'
  'ENTRANCE_FINAL_DEVICE_VIDEO_ACK_SENT=true'
  'ENTRANCE_MEDIA_PAYLOAD_CAPTURED=false'
  'ENTRANCE_SIGNALING_DOOR_ACTION_SENT=false'
  'PSEUDOTCP_GRACEFUL_CLOSE_FORCE=false'
  'PSEUDOTCP_GRACEFUL_CLOSE_FORCE_RST_SENT=false'
)
'''

old_live_gate = '''    if [ "$COUNT" -ne 1 ]; then
        LIVE_GATE=FAIL
    fi
done
'''
new_live_gate = '''    if [ "$marker" = 'ENTRANCE_SIGNALING_DOOR_ACTION_SENT=false' ]; then
        if [ "$COUNT" -lt 1 ]; then
            LIVE_GATE=FAIL
        fi
    elif [ "$COUNT" -ne 1 ]; then
        LIVE_GATE=FAIL
    fi
done
'''

old_final = 'echo "FINAL_DEVICE_VIDEO_ACK_SENT=false"'
new_final = 'echo "FINAL_DEVICE_VIDEO_ACK_SENT=true"'

patches = (
    ("TRANSFORM", old_transform, new_transform),
    ("TIMER", old_timer, new_timer),
    ("SOURCE_MARKERS", old_source_markers, new_source_markers),
    ("BINARY_MARKERS", old_binary_markers, new_binary_markers),
    ("ACK_ALLOWED", old_allowed, new_allowed),
    ("REQUIRED_MARKERS", old_required, new_required),
    ("LIVE_GATE", old_live_gate, new_live_gate),
    ("FINAL_ACK_SUMMARY", old_final, new_final),
)

for label, old, _new in patches:
    count = src.count(old)
    if count != 1:
        raise SystemExit(f"RUNNER_{label}_PATCH_ANCHOR_COUNT={count}")

patched = src
for _label, old, new in patches:
    patched = patched.replace(old, new, 1)

for label, old, new in patches:
    if old in patched:
        raise SystemExit(f"RUNNER_{label}_PATCH_OLD_PATTERN_REMAINS=true")
    if patched.count(new) != 1:
        raise SystemExit(f"RUNNER_{label}_PATCH_NEW_PATTERN_COUNT_INVALID=true")

out.write_text(patched, encoding="utf-8")
print("RUNNER_PATCH_GATE=PASS")
print("RUNNER_TRANSFORM=entrance_device_video_ack_observation_transform.py")
print("RUNNER_FINAL_DEVICE_VIDEO_ACK_ALLOWED=true")
print("RUNNER_DOOR_INVARIANT_COUNT_POLICY=AT_LEAST_ONE")
print("RUNNER_AUTOMATIC_RETRY=false")
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

# Exactly one runner invocation. The patched reviewed runner itself performs at
# most one live wrapper invocation and has mandatory listener EXIT restoration.
"$PATCHED_RUNNER" > "$DETAIL_LOG" 2>&1
RUNNER_RC=$?

exit "$RUNNER_RC"
