#!/usr/bin/env bash
# CT120 research-only P116/R29 listener-attached inbound media live runner.
# Default mode is dry-run preflight/build/selfcheck only.  Live mode requires
# R29_LIVE_RUN=YES and an exact R29_EXPECTED_COMMIT_SHA.

set -u -o pipefail
umask 077

REPO=${REPO:-}
R29_LIVE_RUN=${R29_LIVE_RUN:-NO}
R29_EXPECTED_COMMIT_SHA=${R29_EXPECTED_COMMIT_SHA:-}
R29_EXPECTED_GENERATED_SOURCE_SHA=${R29_EXPECTED_GENERATED_SOURCE_SHA:-}
HA_WEBHOOK_URL=${HA_WEBHOOK_URL:-}
BASE_WRAPPER=${BASE_WRAPPER:-/usr/local/sbin/comelit-p2p-cloud-probe}
BASE_WRAPPER_SHA256=a564535dff0cf10b1fe4766171f2960c52fb581f1c816cf81d2992c5c84e79c9
BUILDER_REL=safety-poc/research/media/v1/ct120_build_p80_haos_media_helper.sh
TRANSFORM_REL=safety-poc/research/media/v1/entrance_p116_r29_listener_attached_media_live_transform.py
RUNNER_REL=safety-poc/research/media/v1/ct120_run_p116_r29_listener_attached_media_live.sh
RUN_DIR=/run/comelit-media
STOP_FILE="$RUN_DIR/stop"
CANDIDATE_NAME=comelit-r29-listener-attached-media
WRAPPER_NAME=comelit-p2p-cloud-probe-r29
R29_OUTER_TIMEOUT_SECONDS=${R29_OUTER_TIMEOUT_SECONDS:-180}
WAIT_FOR_RING_MAX_SECONDS=${WAIT_FOR_RING_MAX_SECONDS:-90}
MEDIA_START_MAX_SECONDS=${MEDIA_START_MAX_SECONDS:-10}
RTP_OBSERVATION_MAX_SECONDS=${RTP_OBSERVATION_MAX_SECONDS:-20}
POST_TEARDOWN_OBSERVATION_SECONDS=${POST_TEARDOWN_OBSERVATION_SECONDS:-10}

FAIL=0
RESULT=INCONCLUSIVE_RUNTIME_FAILURE
RUN_ROOT=""
SESSION_LOG=""
BUILD_PROVENANCE_LOG=""
CANDIDATE_OUTPUT=""
CANDIDATE_WRAPPER=""
WRAPPER_PID=""
VIDEO_SINK_PID=""
AUDIO_SINK_PID=""
LISTENER_STOPPED=0
RESTORE_ATTEMPTS=0
LIVE_INVOCATIONS=0
PRODUCTION_LISTENER_RUNNING_BEFORE=false
PRODUCTION_LISTENER_READY_BEFORE=false
PRODUCTION_LISTENER_RUNNING_AFTER=false
PRODUCTION_LISTENER_READY_AFTER=false
PRODUCTION_MEDIA_ACTIVE_BEFORE=unknown
PRODUCTION_MEDIA_ACTIVE_AFTER=unknown
PRODUCTION_LISTENER_OWNERSHIP_RELEASED=false
RESEARCH_LISTENER_READY_BEFORE_CALL=false
LISTENER_STILL_RUNNING_AFTER_10S=false
LISTENER_READY_AFTER_10S=false
SUCCESS_GATE=false
READY_ICE_BOOTSTRAP_COUNT=UNKNOWN
READY_CLOUD_NEGOTIATION_COUNT=UNKNOWN
READY_PSEUDOTCP_OPEN_COUNT=UNKNOWN
READY_CTPP_REGISTRATION_COUNT=UNKNOWN
AFTER_ICE_BOOTSTRAP_COUNT=UNKNOWN
AFTER_CLOUD_NEGOTIATION_COUNT=UNKNOWN
AFTER_PSEUDOTCP_OPEN_COUNT=UNKNOWN
AFTER_CTPP_REGISTRATION_COUNT=UNKNOWN

fail() {
    echo "$1"
    FAIL=1
}

json_scalar() {
    python3 - "$1" "$2" <<'PY'
import json
from pathlib import Path
import sys
try:
    data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
except Exception:
    print("__INVALID_JSON__")
    raise SystemExit(0)
value = data.get(sys.argv[2], "__MISSING__")
if value is True:
    print("true")
elif value is False:
    print("false")
elif value is None:
    print("null")
else:
    print(str(value))
PY
}

post_control() {
    local action="$1"
    local output="$2"
    local max_time="$3"
    local http_file="${output}.http"
    if [ -z "$HA_WEBHOOK_URL" ]; then
        echo "CONTROL_${action}_URL=ABSENT"
        return 2
    fi
    curl --silent --show-error --connect-timeout 5 --max-time "$max_time" \
      --header 'Content-Type: application/json' \
      --output "$output" \
      --write-out '%{http_code}\n' \
      --data "{\"action\":\"$action\"}" \
      "$HA_WEBHOOK_URL" > "$http_file"
}

status_ready() {
    local file="$1"
    [ "$(json_scalar "$file" ok)" = true ] &&
    [ "$(json_scalar "$file" supervisor_running)" = true ] &&
    [ "$(json_scalar "$file" running)" = true ] &&
    [ "$(json_scalar "$file" listener_ready)" = true ] &&
    [ "$(json_scalar "$file" last_error)" = null ]
}

status_stopped() {
    local file="$1"
    [ "$(json_scalar "$file" ok)" = true ] &&
    [ "$(json_scalar "$file" running)" = false ] &&
    [ "$(json_scalar "$file" listener_ready)" = false ]
}

derive_production_media_active_from_status() {
    local status_file="$1"
    local suffix="$2"
    local running ready ring door p13 p14
    running="$(json_scalar "$status_file" running)"
    ready="$(json_scalar "$status_file" listener_ready)"
    ring="$(json_scalar "$status_file" ring_observed)"
    door="$(json_scalar "$status_file" network_door_action_performed)"
    p13="$(json_scalar "$status_file" p13_executed)"
    p14="$(json_scalar "$status_file" p14_executed)"
    echo "PRODUCTION_MEDIA_ACTIVE_${suffix}_DERIVED_FROM=running,listener_ready,ring_observed,network_door_action_performed,p13_executed,p14_executed"
    echo "PRODUCTION_MEDIA_ACTIVE_${suffix}_DERIVATION_RUNNING=$running"
    echo "PRODUCTION_MEDIA_ACTIVE_${suffix}_DERIVATION_READY=$ready"
    if [ "$running" = true ] && [ "$ready" = true ] &&
       [ "$ring" = false ] && [ "$door" = false ] &&
       [ "$p13" = false ] && [ "$p14" = false ]; then
        printf 'false\n'
    else
        printf 'unknown\n'
    fi
}

last_marker() {
    local key="$1"
    local fallback="$2"
    if [ -f "$SESSION_LOG" ]; then
        awk -v key="$key" -v fallback="$fallback" '
            index($0, key "=") == 1 { value = substr($0, length(key) + 2); found = 1 }
            END { if (found) print value; else print fallback }
        ' "$SESSION_LOG"
    else
        printf '%s\n' "$fallback"
    fi
}

build_marker() {
    local key="$1"
    local fallback="$2"
    if [ -f "$BUILD_PROVENANCE_LOG" ]; then
        awk -v key="$key" -v fallback="$fallback" '
            index($0, key "=") == 1 { value = substr($0, length(key) + 2); found = 1 }
            END { if (found) print value; else print fallback }
        ' "$BUILD_PROVENANCE_LOG"
    else
        printf '%s\n' "$fallback"
    fi
}

compute_delta() {
    local before="$1"
    local after="$2"
    case "$before" in *[!0-9]*|"") printf 'UNKNOWN\n'; return 0 ;; esac
    case "$after" in *[!0-9]*|"") printf 'UNKNOWN\n'; return 0 ;; esac
    printf '%s\n' "$((after - before))"
}

snapshot_ready_counters() {
    READY_ICE_BOOTSTRAP_COUNT="$(last_marker ICE_BOOTSTRAP_COUNT UNKNOWN)"
    READY_CLOUD_NEGOTIATION_COUNT="$(last_marker CLOUD_NEGOTIATION_COUNT UNKNOWN)"
    READY_PSEUDOTCP_OPEN_COUNT="$(last_marker PSEUDOTCP_OPEN_COUNT UNKNOWN)"
    READY_CTPP_REGISTRATION_COUNT="$(last_marker CTPP_REGISTRATION_COUNT UNKNOWN)"
    echo "R29_READY_COUNTER_SNAPSHOT=PASS"
}

snapshot_after_teardown_counters() {
    AFTER_ICE_BOOTSTRAP_COUNT="$(last_marker ICE_BOOTSTRAP_COUNT UNKNOWN)"
    AFTER_CLOUD_NEGOTIATION_COUNT="$(last_marker CLOUD_NEGOTIATION_COUNT UNKNOWN)"
    AFTER_PSEUDOTCP_OPEN_COUNT="$(last_marker PSEUDOTCP_OPEN_COUNT UNKNOWN)"
    AFTER_CTPP_REGISTRATION_COUNT="$(last_marker CTPP_REGISTRATION_COUNT UNKNOWN)"
    echo "R29_AFTER_TEARDOWN_COUNTER_SNAPSHOT=PASS"
}

restore_predicate() {
    local status_file="$1"
    if status_ready "$status_file"; then
        echo "RESTORE_PREDICATE=true"
        return 0
    fi
    echo "RESTORE_PREDICATE=false"
    return 1
}

evaluate_success_gate() {
    local video_packets="$1"
    local teardown_complete="$2"
    local same_after_call="$3"
    local same_after_media="$4"
    local ready_after="$5"
    local ice_delta="$6"
    local cloud_delta="$7"
    local tcp_delta="$8"
    local ctpp_delta="$9"
    if [ "$video_packets" != NOT_REACHED ] && [ "$video_packets" -gt 0 ] 2>/dev/null &&
       [ "$teardown_complete" = true ] &&
       [ "$same_after_call" = true ] &&
       [ "$same_after_media" = true ] &&
       [ "$ready_after" = true ] &&
       [ "$ice_delta" = 0 ] &&
       [ "$cloud_delta" = 0 ] &&
       [ "$tcp_delta" = 0 ] &&
       [ "$ctpp_delta" = 0 ]; then
        SUCCESS_GATE=true
    else
        SUCCESS_GATE=false
    fi
    echo "SUCCESS_GATE=$SUCCESS_GATE"
}

start_udp_sink() {
    local port="$1"
    local count_file="$2"
    python3 - "$port" "$count_file" "$R29_OUTER_TIMEOUT_SECONDS" <<'PY' &
from pathlib import Path
import signal
import socket
import sys
import time
port = int(sys.argv[1])
count_file = Path(sys.argv[2])
deadline = time.monotonic() + int(sys.argv[3])
stop = False
def handle(_signum, _frame):
    global stop
    stop = True
signal.signal(signal.SIGTERM, handle)
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
loopback = socket.inet_ntoa(bytes((0x7f, 0, 0, 1)))
sock.bind((loopback, port))
sock.settimeout(0.5)
count = 0
while not stop and time.monotonic() < deadline:
    try:
        sock.recvfrom(65535)
    except socket.timeout:
        continue
    count += 1
count_file.write_text(f"{count}\n", encoding="utf-8")
PY
    printf '%s\n' "$!"
}

stop_pid() {
    local pid="$1"
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
        kill -TERM "$pid" 2>/dev/null || true
        sleep 1
        kill -KILL "$pid" 2>/dev/null || true
    fi
}

stop_candidate_if_needed() {
    if [ -n "$WRAPPER_PID" ] && kill -0 "$WRAPPER_PID" 2>/dev/null; then
        kill -USR2 "$WRAPPER_PID" 2>/dev/null || true
        sleep 1
        install -d -m 700 "$RUN_DIR" || true
        : > "$STOP_FILE" || true
        chmod 600 "$STOP_FILE" || true
        sleep 2
        stop_pid "$WRAPPER_PID"
    fi
}

restore_listener() {
    local poll start_file status_file
    if [ "$LISTENER_STOPPED" -ne 1 ]; then
        return 0
    fi
    RESTORE_ATTEMPTS=$((RESTORE_ATTEMPTS + 1))
    echo "LISTENER_RESTORE_ATTEMPT=$RESTORE_ATTEMPTS"
    start_file="$RUN_ROOT/listener-start-${RESTORE_ATTEMPTS}.json"
    post_control start "$start_file" 40 || true
    for poll in 1 2 3 4 5 6 7 8; do
        status_file="$RUN_ROOT/listener-restore-${RESTORE_ATTEMPTS}-${poll}.json"
        post_control status "$status_file" 10 || true
        if status_ready "$status_file"; then
            LISTENER_STOPPED=0
            PRODUCTION_LISTENER_RUNNING_AFTER=true
            PRODUCTION_LISTENER_READY_AFTER=true
            echo "LISTENER_RESTORE=PASS"
            return 0
        fi
        sleep 5
    done
    echo "LISTENER_RESTORE=FAIL"
    return 91
}

materialize_wrapper() {
    python3 - "$BASE_WRAPPER" "$CANDIDATE_WRAPPER" "$CANDIDATE_OUTPUT" <<'PY'
from pathlib import Path
import os
import sys
src = Path(sys.argv[1])
out = Path(sys.argv[2])
candidate = sys.argv[3]
text = src.read_text(encoding="utf-8")
anchor = '"$BASE/bin/comelit_ice_offer_holder"'
if text.count(anchor) != 1:
    raise SystemExit("R29_WRAPPER_HOLDER_ANCHOR=FAIL")
text = text.replace(anchor, f'"{candidate}"', 1)
base_run_dir = "/run/comelit-p2p"
media_run_dir = "/run/comelit-media"
run_dir_count = text.count(base_run_dir)
if run_dir_count < 1:
    raise SystemExit("R29_WRAPPER_RUN_DIR_ANCHOR=FAIL")
text = text.replace(base_run_dir, media_run_dir)
if anchor in text:
    raise SystemExit("R29_WRAPPER_SUBSTITUTION_BASE_ABSENT=FAIL")
if f'"{candidate}"' not in text:
    raise SystemExit("R29_WRAPPER_SUBSTITUTION_CANDIDATE_PRESENT=FAIL")
out.write_text(text, encoding="utf-8")
os.chmod(out, 0o700)
print("R29_WRAPPER_SUBSTITUTION_BASE_ABSENT=PASS")
print("R29_WRAPPER_SUBSTITUTION_CANDIDATE_PRESENT=PASS")
print(f"R29_WRAPPER_RUN_DIR_REPLACEMENTS={run_dir_count}")
PY
}

print_final_block() {
    local video_packets teardown same_call same_media ready_after ice_delta cloud_delta tcp_delta ctpp_delta
    local self_count client_001a_count r27_count door_count gate_count refresh_count new_ice new_cloud new_pseudotcp new_registration
    video_packets="$(last_marker VIDEO_RTP_PACKETS NOT_REACHED)"
    teardown="$(last_marker MEDIA_ONLY_TEARDOWN_COMPLETE false)"
    same_call="$(last_marker LISTENER_PROCESS_SAME_AFTER_CALL false)"
    same_media="$(last_marker LISTENER_PROCESS_SAME_AFTER_MEDIA false)"
    ready_after="$(last_marker LISTENER_READY_AFTER_MEDIA false)"
    ice_delta="$(compute_delta "$READY_ICE_BOOTSTRAP_COUNT" "$AFTER_ICE_BOOTSTRAP_COUNT")"
    cloud_delta="$(compute_delta "$READY_CLOUD_NEGOTIATION_COUNT" "$AFTER_CLOUD_NEGOTIATION_COUNT")"
    tcp_delta="$(compute_delta "$READY_PSEUDOTCP_OPEN_COUNT" "$AFTER_PSEUDOTCP_OPEN_COUNT")"
    ctpp_delta="$(compute_delta "$READY_CTPP_REGISTRATION_COUNT" "$AFTER_CTPP_REGISTRATION_COUNT")"
    self_count="$(last_marker SELF_ACTIVATION_SENT_COUNT NOT_REACHED)"
    client_001a_count="$(last_marker CLIENT_001A_SENT_COUNT NOT_REACHED)"
    r27_count="$(last_marker R27_REPEAT_SENT_COUNT NOT_REACHED)"
    door_count="$(last_marker DOOR_ACTIONS_SENT NOT_REACHED)"
    gate_count="$(last_marker GATE_ACTIONS_SENT NOT_REACHED)"
    refresh_count="$(last_marker REFRESH_LOOP_STARTED_COUNT NOT_REACHED)"
    new_ice="$(last_marker NEW_ICE_BOOTSTRAP_AFTER_READY NOT_REACHED)"
    new_cloud="$(last_marker NEW_CLOUD_NEGOTIATION_AFTER_READY NOT_REACHED)"
    new_pseudotcp="$(last_marker NEW_PSEUDOTCP_AFTER_READY NOT_REACHED)"
    new_registration="$(last_marker NEW_REGISTRATION_AFTER_READY NOT_REACHED)"
    evaluate_success_gate "$video_packets" "$teardown" "$same_call" "$same_media" "$ready_after" "$ice_delta" "$cloud_delta" "$tcp_delta" "$ctpp_delta" >/dev/null
    if [ "$SUCCESS_GATE" = true ] && [ "$RESULT" = INCONCLUSIVE_RUNTIME_FAILURE ]; then
        RESULT=SUCCESS_LIVE_PROOF
    fi
    echo "=== COMELIT P116 R29 LISTENER ATTACHED MEDIA LIVE FINAL ==="
    echo "RESULT=$RESULT"
    echo "DRY_RUN=$([ "$R29_LIVE_RUN" = YES ] && echo false || echo PASS)"
    echo "LIVE_INVOCATIONS=$LIVE_INVOCATIONS"
    echo "GENERATED_SOURCE_SHA256=$(build_marker GENERATED_SOURCE_SHA256 NOT_REACHED)"
    echo "CANDIDATE_HELPER_EXECUTED=$(last_marker CANDIDATE_HELPER_EXECUTED NOT_REACHED)"
    echo "PRODUCTION_LISTENER_RUNNING_BEFORE=$PRODUCTION_LISTENER_RUNNING_BEFORE"
    echo "PRODUCTION_LISTENER_READY_BEFORE=$PRODUCTION_LISTENER_READY_BEFORE"
    echo "PRODUCTION_MEDIA_ACTIVE_BEFORE=$PRODUCTION_MEDIA_ACTIVE_BEFORE"
    echo "PRODUCTION_LISTENER_OWNERSHIP_RELEASED=$PRODUCTION_LISTENER_OWNERSHIP_RELEASED"
    echo "RESEARCH_LISTENER_READY_BEFORE_CALL=$RESEARCH_LISTENER_READY_BEFORE_CALL"
    echo "ATTACHED_MEDIA_STARTED=$(last_marker ATTACHED_MEDIA_STARTED NOT_REACHED)"
    echo "VIDEO_RTP_STARTED=$(last_marker VIDEO_RTP_STARTED NOT_REACHED)"
    echo "VIDEO_RTP_PACKETS=$video_packets"
    echo "MEDIA_ONLY_TEARDOWN_COMPLETE=$teardown"
    echo "LISTENER_STILL_RUNNING_AFTER_10S=$LISTENER_STILL_RUNNING_AFTER_10S"
    echo "LISTENER_READY_AFTER_10S=$LISTENER_READY_AFTER_10S"
    echo "ICE_BOOTSTRAP_DELTA_AFTER_READY=$ice_delta"
    echo "CLOUD_NEGOTIATION_DELTA_AFTER_READY=$cloud_delta"
    echo "PSEUDOTCP_OPEN_DELTA_AFTER_READY=$tcp_delta"
    echo "CTPP_REGISTRATION_DELTA_AFTER_READY=$ctpp_delta"
    echo "MEDIA_TEARDOWN_PRESERVES_TRANSPORT=$(last_marker MEDIA_TEARDOWN_PRESERVES_TRANSPORT NOT_REACHED)"
    echo "MEDIA_TEARDOWN_PRESERVES_REGISTRATION=$(last_marker MEDIA_TEARDOWN_PRESERVES_REGISTRATION NOT_REACHED)"
    echo "MEDIA_TEARDOWN_PRESERVES_RING_LISTENER=$(last_marker MEDIA_TEARDOWN_PRESERVES_RING_LISTENER NOT_REACHED)"
    echo "SELF_ACTIVATION_SENT_COUNT=$self_count"
    echo "CLIENT_001A_SENT_COUNT=$client_001a_count"
    echo "R27_REPEAT_SENT_COUNT=$r27_count"
    echo "DOOR_ACTIONS_SENT=$door_count"
    echo "GATE_ACTIONS_SENT=$gate_count"
    echo "REFRESH_LOOP_STARTED_COUNT=$refresh_count"
    echo "NEW_ICE_BOOTSTRAP_AFTER_READY=$new_ice"
    echo "NEW_CLOUD_NEGOTIATION_AFTER_READY=$new_cloud"
    echo "NEW_PSEUDOTCP_AFTER_READY=$new_pseudotcp"
    echo "NEW_REGISTRATION_AFTER_READY=$new_registration"
    echo "R29_MEDIA_OPEN_MODEL=$(last_marker R29_MEDIA_OPEN_MODEL NOT_REACHED)"
    echo "R29_MEDIA_ONLY_TEARDOWN_MODEL=$(last_marker R29_MEDIA_ONLY_TEARDOWN_MODEL NOT_REACHED)"
    echo "PRODUCTION_LISTENER_RUNNING_AFTER=$PRODUCTION_LISTENER_RUNNING_AFTER"
    echo "PRODUCTION_LISTENER_READY_AFTER=$PRODUCTION_LISTENER_READY_AFTER"
    echo "PRODUCTION_MEDIA_ACTIVE_AFTER=$PRODUCTION_MEDIA_ACTIVE_AFTER"
    echo "SUCCESS_GATE=$SUCCESS_GATE"
    echo "=== END COMELIT P116 R29 LISTENER ATTACHED MEDIA LIVE FINAL ==="
}

on_exit() {
    local rc=$?
    stop_candidate_if_needed || true
    stop_pid "$VIDEO_SINK_PID"
    stop_pid "$AUDIO_SINK_PID"
    restore_listener || rc=91
    print_final_block
    exit "$rc"
}

run_main() {
    trap on_exit EXIT
    trap 'exit 130' INT TERM HUP

    [ "${EUID}" -eq 0 ] || fail "R29_ROOT_GATE=FAIL"
    for command in git python3 curl sha256sum timeout awk grep bash chmod install cmp sed; do
        command -v "$command" >/dev/null 2>&1 || fail "R29_MISSING_COMMAND=$command"
    done
    [ -n "$REPO" ] || fail "R29_REPO_REQUIRED=true"
    [ -n "$R29_EXPECTED_COMMIT_SHA" ] || fail "R29_EXPECTED_COMMIT_SHA_REQUIRED=true"
    [ -n "$R29_EXPECTED_GENERATED_SOURCE_SHA" ] || fail "R29_EXPECTED_GENERATED_SOURCE_SHA_REQUIRED=true"
    [ -d "$REPO/.git" ] || fail "R29_REPO_PRESENT=false"
    [ -x "$BASE_WRAPPER" ] || fail "R29_BASE_WRAPPER_PRESENT=false"
    if [ -x "$BASE_WRAPPER" ]; then
        actual_wrapper_sha="$(sha256sum "$BASE_WRAPPER" | awk '{print $1}')"
        echo "BASE_WRAPPER_SHA256=$actual_wrapper_sha"
        [ "$actual_wrapper_sha" = "$BASE_WRAPPER_SHA256" ] || fail "BASE_WRAPPER_SHA256_GATE=FAIL"
    fi
    if [ "$FAIL" -eq 0 ]; then
        repo_head="$(git -C "$REPO" rev-parse HEAD 2>/dev/null || true)"
        echo "R29_REPO_HEAD=$repo_head"
        [ "$repo_head" = "$R29_EXPECTED_COMMIT_SHA" ] || fail "R29_EXPECTED_COMMIT_SHA_GATE=FAIL"
        [ -z "$(git -C "$REPO" status --porcelain)" ] || fail "R29_WORKTREE_CLEAN=FAIL"
    fi

    STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
    RUN_ROOT="/root/comelit-r29-listener-attached-media-$STAMP"
    mkdir -p "$RUN_ROOT"
    chmod 700 "$RUN_ROOT"
    SESSION_LOG="$RUN_ROOT/session.log"
    BUILD_PROVENANCE_LOG="$RUN_ROOT/build-provenance.log"
    CANDIDATE_OUTPUT="$RUN_ROOT/$CANDIDATE_NAME"
    CANDIDATE_WRAPPER="$RUN_ROOT/$WRAPPER_NAME"
    : > "$SESSION_LOG"
    : > "$BUILD_PROVENANCE_LOG"
    chmod 600 "$SESSION_LOG" "$BUILD_PROVENANCE_LOG"
    case "$CANDIDATE_OUTPUT" in "$RUN_ROOT"/*) echo "R29_CANDIDATE_OUTPUT_SCOPE=RUN_ROOT" ;; *) fail "R29_CANDIDATE_OUTPUT_SCOPE=FAIL" ;; esac

    if [ "$FAIL" -eq 0 ]; then
        git -C "$REPO" show "$R29_EXPECTED_COMMIT_SHA:$TRANSFORM_REL" > "$RUN_ROOT/transform.py" || fail "R29_TRANSFORM_BLOB=FAIL"
        git -C "$REPO" show "$R29_EXPECTED_COMMIT_SHA:$RUNNER_REL" > "$RUN_ROOT/runner.sh" || fail "R29_RUNNER_BLOB=FAIL"
        git -C "$REPO" show "$R29_EXPECTED_COMMIT_SHA:$BUILDER_REL" > "$RUN_ROOT/builder.sh" || fail "R29_BUILDER_BLOB=FAIL"
        bash -n "$RUN_ROOT/runner.sh" || fail "R29_RUNNER_BASH_N=FAIL"
        bash -n "$RUN_ROOT/builder.sh" || fail "R29_BUILDER_BASH_N=FAIL"
        cmp "$RUN_ROOT/transform.py" "$REPO/$TRANSFORM_REL" >/dev/null 2>&1 || fail "R29_TRANSFORM_WORKTREE_BLOB_GATE=FAIL"
        cmp "$RUN_ROOT/runner.sh" "$REPO/$RUNNER_REL" >/dev/null 2>&1 || fail "R29_RUNNER_WORKTREE_BLOB_GATE=FAIL"
        cmp "$RUN_ROOT/builder.sh" "$REPO/$BUILDER_REL" >/dev/null 2>&1 || fail "R29_BUILDER_WORKTREE_BLOB_GATE=FAIL"
    fi
    [ "$FAIL" -eq 0 ] || exit 1
    echo "R29_PREFLIGHT=PASS"

    (
        REPO="$REPO" \
        P80_BUILD_ALLOW_DETACHED=1 \
        P80_BUILD_EXPECTED_SHA="$R29_EXPECTED_COMMIT_SHA" \
        P80_BUILD_INCLUDE_P116=1 \
        P80_BUILD_TRANSFORM="$TRANSFORM_REL" \
        P80_BUILD_EXPECTED_SOURCE_SHA="$R29_EXPECTED_GENERATED_SOURCE_SHA" \
        OUTPUT="$CANDIDATE_OUTPUT" \
        bash "$RUN_ROOT/builder.sh"
    ) | tee "$BUILD_PROVENANCE_LOG"
    build_rc=${PIPESTATUS[0]}
    echo "R29_BUILD_RC=$build_rc"
    [ "$build_rc" -eq 0 ] || exit 1
    grep -F "GENERATED_SOURCE_SHA256=$R29_EXPECTED_GENERATED_SOURCE_SHA" "$BUILD_PROVENANCE_LOG" >/dev/null || fail "R29_GENERATED_SOURCE_SHA_GATE=FAIL"
    [ -x "$CANDIDATE_OUTPUT" ] || fail "R29_CANDIDATE_OUTPUT_PRESENT=false"
    [ "$FAIL" -eq 0 ] || exit 1

    materialize_wrapper || fail "R29_WRAPPER_REWRITE=FAIL"
    bash -n "$CANDIDATE_WRAPPER" || fail "R29_WRAPPER_PARSE=FAIL"
    "$CANDIDATE_OUTPUT" --r29-selfcheck > "$RUN_ROOT/selfcheck.log" 2>&1 || fail "R29_CANDIDATE_SELFCHECK=FAIL"
    grep -qx 'CANDIDATE_HELPER_EXECUTED=true' "$RUN_ROOT/selfcheck.log" || fail "R29_CANDIDATE_HELPER_EXECUTED=FAIL"
    cat "$RUN_ROOT/selfcheck.log" >> "$SESSION_LOG"
    [ "$FAIL" -eq 0 ] || exit 1
    if grep -qx 'R29_MEDIA_OPEN_MODEL=BLOCKED' "$RUN_ROOT/selfcheck.log" ||
       grep -qx 'R29_MEDIA_ONLY_TEARDOWN_MODEL=BLOCKED' "$RUN_ROOT/selfcheck.log"; then
        RESULT=BLOCKED_MEDIA_MODEL
        echo "R29_LIVE_PREFLIGHT_REFUSED=BLOCKED_MEDIA_MODEL"
        echo "LIVE_RUN=NOT_RUN"
        exit 1
    fi

    STATUS_BEFORE="$RUN_ROOT/listener-status-before.json"
    post_control status "$STATUS_BEFORE" 10 || true
    if status_ready "$STATUS_BEFORE"; then
        PRODUCTION_LISTENER_RUNNING_BEFORE=true
        PRODUCTION_LISTENER_READY_BEFORE=true
    fi
    echo "PRODUCTION_LISTENER_RUNNING_BEFORE=$PRODUCTION_LISTENER_RUNNING_BEFORE"
    echo "PRODUCTION_LISTENER_READY_BEFORE=$PRODUCTION_LISTENER_READY_BEFORE"
    PRODUCTION_MEDIA_ACTIVE_BEFORE="$(derive_production_media_active_from_status "$STATUS_BEFORE" BEFORE | tail -1)"
    echo "PRODUCTION_MEDIA_ACTIVE_BEFORE=$PRODUCTION_MEDIA_ACTIVE_BEFORE"

    if [ "$R29_LIVE_RUN" != YES ]; then
        RESULT=DRY_RUN_PASS
        echo "RESTORER_DRY_RUN=PASS"
        echo "DRY_RUN=PASS"
        exit 0
    fi

    [ "$PRODUCTION_LISTENER_RUNNING_BEFORE" = true ] || fail "PRODUCTION_LISTENER_RUNNING_BEFORE=false"
    [ "$PRODUCTION_LISTENER_READY_BEFORE" = true ] || fail "PRODUCTION_LISTENER_READY_BEFORE=false"
    [ "$FAIL" -eq 0 ] || exit 1

    STOP_RESPONSE="$RUN_ROOT/listener-stop.json"
    LISTENER_STOPPED=1
    post_control stop "$STOP_RESPONSE" 20 || true
    echo "LISTENER_STOP_REQUESTED=true"
    if status_stopped "$STOP_RESPONSE"; then
        PRODUCTION_LISTENER_OWNERSHIP_RELEASED=true
        echo "PRODUCTION_LISTENER_OWNERSHIP_RELEASED=true"
    else
        fail "PRODUCTION_LISTENER_OWNERSHIP_RELEASED=false"
    fi
    [ "$FAIL" -eq 0 ] || exit 1

    VIDEO_SINK_PID="$(start_udp_sink "$((17000 + 899))" "$RUN_ROOT/video.count")"
    AUDIO_SINK_PID="$(start_udp_sink "$((17000 + 808))" "$RUN_ROOT/audio.count")"

    LIVE_INVOCATIONS=1
    echo "LIVE_INVOCATIONS=$LIVE_INVOCATIONS"
    (
        timeout --signal=TERM --kill-after=5s "$R29_OUTER_TIMEOUT_SECONDS" "$CANDIDATE_WRAPPER"
    ) > "$SESSION_LOG" 2>&1 &
    WRAPPER_PID=$!

    for _poll in $(seq 1 60); do
        if grep -qx 'RESEARCH_LISTENER_READY=true' "$SESSION_LOG" 2>/dev/null; then
            RESEARCH_LISTENER_READY_BEFORE_CALL=true
            echo "RESEARCH_LISTENER_READY_BEFORE_CALL=true"
            echo "R29_RING_NOW_SIGNAL=READY"
            snapshot_ready_counters
            break
        fi
        sleep 1
    done
    if [ "$RESEARCH_LISTENER_READY_BEFORE_CALL" != true ]; then
        RESULT=LISTENER_SURVIVAL_NOT_PROVEN
        exit 1
    fi

    for _poll in $(seq 1 "$WAIT_FOR_RING_MAX_SECONDS"); do
        if grep -qx 'CALL_TRANSACTION_CREATED=true' "$SESSION_LOG" 2>/dev/null; then
            break
        fi
        sleep 1
    done
    if ! grep -qx 'CALL_TRANSACTION_CREATED=true' "$SESSION_LOG" 2>/dev/null; then
        RESULT=NO_CALL_OBSERVED
        exit 1
    fi

    for _poll in $(seq 1 "$MEDIA_START_MAX_SECONDS"); do
        if grep -qx 'ATTACHED_MEDIA_STARTED=true' "$SESSION_LOG" 2>/dev/null; then
            break
        fi
        sleep 1
    done
    if ! grep -qx 'ATTACHED_MEDIA_STARTED=true' "$SESSION_LOG" 2>/dev/null; then
        RESULT=INBOUND_MEDIA_START_FAILED
        exit 1
    fi

    sleep "$RTP_OBSERVATION_MAX_SECONDS"
    if [ "$(last_marker VIDEO_RTP_PACKETS 0)" -le 0 ] 2>/dev/null; then
        RESULT=MEDIA_ACTIVE_NO_RTP
    fi
    kill -USR2 "$WRAPPER_PID" 2>/dev/null || true
    sleep "$POST_TEARDOWN_OBSERVATION_SECONDS"
    snapshot_after_teardown_counters
    if kill -0 "$WRAPPER_PID" 2>/dev/null; then
        LISTENER_STILL_RUNNING_AFTER_10S=true
        LISTENER_READY_AFTER_10S="$(last_marker LISTENER_READY_AFTER_MEDIA false)"
    else
        RESULT=ATTACHED_MEDIA_TEARDOWN_BREAKS_LISTENER
    fi
    install -d -m 700 "$RUN_DIR" || true
    : > "$STOP_FILE" || true
    wait "$WRAPPER_PID" || true
    WRAPPER_PID=""

    restore_listener || exit 91
    STATUS_AFTER="$RUN_ROOT/listener-status-after.json"
    post_control status "$STATUS_AFTER" 10 || true
    if status_ready "$STATUS_AFTER"; then
        PRODUCTION_LISTENER_RUNNING_AFTER=true
        PRODUCTION_LISTENER_READY_AFTER=true
    fi
    PRODUCTION_MEDIA_ACTIVE_AFTER="$(derive_production_media_active_from_status "$STATUS_AFTER" AFTER | tail -1)"
    [ "$RESULT" = MEDIA_ACTIVE_NO_RTP ] || RESULT=SUCCESS_LIVE_PROOF
    exit 0
}

if [ "${R29_UNIT_TEST:-0}" != 1 ]; then
    run_main "$@"
fi
