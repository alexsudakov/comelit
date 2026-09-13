#!/usr/bin/env bash
# CT120 research-only P116/R27 same-session repeat 0x001A live runner.
# The helper observes for 70 seconds after MEDIA_ACTIVE.  The outer timeout is
# a hard 150 second bound, giving 80 seconds for OAuth/bootstrap/ICE/P2P and
# RTPC/ACK setup before the helper's own 70 second observation can finish.

set -u -o pipefail
umask 077

REPO=${REPO:-/root/comelit-door-diag-repo}
R27_EXPECTED_COMMIT_SHA=${R27_EXPECTED_COMMIT_SHA:-}
R27_LIVE_RUN=${R27_LIVE_RUN:-NO}
HA_WEBHOOK_URL=${HA_WEBHOOK_URL:-http://192.168.1.108:8123/api/webhook/comelit-ha-ring-test-control-v1}
BASE_WRAPPER=/usr/local/sbin/comelit-p2p-cloud-probe
BASE_WRAPPER_SHA256=a564535dff0cf10b1fe4766171f2960c52fb581f1c816cf81d2992c5c84e79c9
BUILDER_REL=safety-poc/research/media/v1/ct120_build_p80_haos_media_helper.sh
TRANSFORM_REL=safety-poc/research/media/v1/entrance_p116_r27_repeat_001a_transform.py
RUNNER_REL=safety-poc/research/media/v1/ct120_run_p116_r27_repeat_001a_live.sh
EXPECTED_SOURCE_SHA=0b9d4d1a75d3852989a1457dce867bb8c0a31f8ac6518779de0e58e801dd5fcb
VIDEO_RTP_PORT=17899
AUDIO_RTP_PORT=17808
MAX_LIVE_OBSERVATION_SECONDS=70
OUTER_TIMEOUT_SECONDS=150
RUN_DIR=/run/comelit-media
STOP_FILE="$RUN_DIR/stop"

FAIL=0
LISTENER_STOPPED=0
RESTORE_OK=0
RESTORE_ATTEMPTS=0
LIVE_INVOCATIONS=0
WRAPPER_RC=NOT_REACHED
WRAPPER_PID=""
VIDEO_SINK_PID=""
AUDIO_SINK_PID=""
RUN_ROOT=""
LOG=""
LISTENER_READY_BEFORE=false
LISTENER_RUNNING_AFTER=false
LISTENER_READY_AFTER=false
PRODUCTION_MEDIA_ACTIVE=false
CAMPAIGN_PROCESSES_REMAINING=UNKNOWN
CT120_RESEARCH_HELPER_STOPPED=false
CT120_RESEARCH_SESSION_CLOSED=false
R27_SESSION_CLOSED=false
TEARDOWN_CONFIDENCE=UNCERTAIN
R27_RUN_CLASSIFICATION=NOT_RUN
R27_REPEAT_EXECUTED=false

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
    local rc
    curl --silent --show-error --connect-timeout 5 --max-time "$max_time" \
      --header 'Content-Type: application/json' \
      --output "$output" \
      --write-out '%{http_code}\n' \
      --data "{\"action\":\"$action\"}" \
      "$HA_WEBHOOK_URL" > "$http_file"
    rc=$?
    echo "CONTROL_${action^^}_CURL_RC=$rc"
    if [ -s "$http_file" ]; then
        echo "CONTROL_${action^^}_HTTP_STATUS=$(cat "$http_file")"
    else
        echo "CONTROL_${action^^}_HTTP_STATUS=NONE"
    fi
    return "$rc"
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

start_udp_sink() {
    local port="$1"
    local count_file="$2"
    python3 - "$port" "$count_file" "$OUTER_TIMEOUT_SECONDS" <<'PY' &
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
sock.bind(("127.0.0.1", port))
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
    if [ -z "$WRAPPER_PID" ] || ! kill -0 "$WRAPPER_PID" 2>/dev/null; then
        return 0
    fi
    echo "R27_STOP_REQUESTED=true"
    install -d -m 700 "$RUN_DIR"
    : > "$STOP_FILE"
    chmod 600 "$STOP_FILE"
    for _poll in 1 2 3 4 5 6 7 8; do
        kill -0 "$WRAPPER_PID" 2>/dev/null || return 0
        sleep 1
    done
    kill -TERM "$WRAPPER_PID" 2>/dev/null || true
    sleep 2
    kill -KILL "$WRAPPER_PID" 2>/dev/null || true
}

restore_listener() {
    local poll status_file start_file
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
            RESTORE_OK=1
            LISTENER_RUNNING_AFTER=true
            LISTENER_READY_AFTER=true
            echo "LISTENER_RESTORE=PASS"
            echo "LISTENER_RUNNING_AFTER=true"
            echo "LISTENER_READY_AFTER=true"
            return 0
        fi
        sleep 5
    done
    echo "LISTENER_RESTORE=FAIL"
    return 91
}

last_marker() {
    local key="$1"
    local fallback="$2"
    if [ -f "$LOG" ]; then
        awk -v key="$key" -v fallback="$fallback" '
            index($0, key "=") == 1 { value = substr($0, length(key) + 2); found = 1 }
            END { if (found) print value; else print fallback }
        ' "$LOG"
    else
        printf '%s\n' "$fallback"
    fi
}

campaign_processes_remaining() {
    local pattern="$BASE_WRAPPER"
    if [ -n "${R27_OUTPUT:-}" ]; then
        pattern="$pattern|$R27_OUTPUT"
    fi
    if pgrep -af "$pattern" >/dev/null 2>&1; then
        CAMPAIGN_PROCESSES_REMAINING=FOUND
    else
        CAMPAIGN_PROCESSES_REMAINING=NONE
    fi
    echo "CAMPAIGN_PROCESSES_REMAINING=$CAMPAIGN_PROCESSES_REMAINING"
}

derive_teardown_confidence() {
    local wrapper_gone=true
    if [ -n "$WRAPPER_PID" ] && kill -0 "$WRAPPER_PID" 2>/dev/null; then
        wrapper_gone=false
    fi

    if [ "$wrapper_gone" = true ] &&
       [ "$CAMPAIGN_PROCESSES_REMAINING" = NONE ] &&
       [ "$WRAPPER_RC" != 124 ] &&
       [ "$WRAPPER_RC" != 137 ]; then
        TEARDOWN_CONFIDENCE=CONFIRMED
        CT120_RESEARCH_HELPER_STOPPED=true
        CT120_RESEARCH_SESSION_CLOSED=true
        R27_SESSION_CLOSED=true
    else
        TEARDOWN_CONFIDENCE=UNCERTAIN
        CT120_RESEARCH_HELPER_STOPPED=false
        CT120_RESEARCH_SESSION_CLOSED=false
        R27_SESSION_CLOSED=false
    fi

    if [ "$WRAPPER_RC" = 124 ] || [ "$WRAPPER_RC" = 137 ]; then
        R27_RUN_CLASSIFICATION=INCONCLUSIVE_OUTER_TIMEOUT
    elif [ "$TEARDOWN_CONFIDENCE" = CONFIRMED ]; then
        R27_RUN_CLASSIFICATION=OBSERVATION_USABLE
    else
        R27_RUN_CLASSIFICATION=INCONCLUSIVE_TEARDOWN_UNPROVEN
    fi
    echo "CT120_RESEARCH_HELPER_STOPPED=$CT120_RESEARCH_HELPER_STOPPED"
    echo "CT120_RESEARCH_SESSION_CLOSED=$CT120_RESEARCH_SESSION_CLOSED"
    echo "R27_SESSION_CLOSED=$R27_SESSION_CLOSED"
    echo "TEARDOWN_CONFIDENCE=$TEARDOWN_CONFIDENCE"
    echo "R27_RUN_CLASSIFICATION=$R27_RUN_CLASSIFICATION"
}

derive_production_media_active() {
    if [ "$LISTENER_READY_AFTER" = true ]; then
        PRODUCTION_MEDIA_ACTIVE=false
    else
        PRODUCTION_MEDIA_ACTIVE=unknown
    fi
    echo "PRODUCTION_MEDIA_ACTIVE_DERIVED_FROM=LISTENER_READY_AFTER"
    echo "PRODUCTION_MEDIA_ACTIVE_DERIVATION_LISTENER_READY_AFTER=$LISTENER_READY_AFTER"
    echo "PRODUCTION_MEDIA_ACTIVE=$PRODUCTION_MEDIA_ACTIVE"
}

print_final_block() {
    echo "=== COMELIT P116 R27 REPEAT 001A LIVE FINAL ==="
    echo "LIVE_INVOCATIONS=$LIVE_INVOCATIONS"
    echo "WRAPPER_RC=$WRAPPER_RC"
    echo "CAMPAIGN_PROCESSES_REMAINING=$CAMPAIGN_PROCESSES_REMAINING"
    echo "CT120_RESEARCH_HELPER_STOPPED=$CT120_RESEARCH_HELPER_STOPPED"
    echo "CT120_RESEARCH_SESSION_CLOSED=$CT120_RESEARCH_SESSION_CLOSED"
    echo "R27_SESSION_CLOSED=$R27_SESSION_CLOSED"
    echo "TEARDOWN_CONFIDENCE=$TEARDOWN_CONFIDENCE"
    echo "R27_RUN_CLASSIFICATION=$R27_RUN_CLASSIFICATION"
    echo "R27_REPEAT_EXECUTED=$R27_REPEAT_EXECUTED"
    echo "GENERATED_SOURCE_SHA256=$(last_marker GENERATED_SOURCE_SHA256 NOT_REACHED)"
    echo "R27_REPEAT_DELAY_SECONDS=20"
    echo "R27_REPEAT_DELAY_IS_PROTOCOL_CONSTANT=false"
    echo "R27_REPEAT_DELAY_PROMOTED_TO_PRODUCTION=false"
    if [ "$R27_RUN_CLASSIFICATION" = INCONCLUSIVE_OUTER_TIMEOUT ]; then
        echo "R27_USABLE_EVIDENCE=false"
        echo "R27_SCALARS_SUPPRESSED=true"
        echo "R27_SCALARS_SUPPRESSED_REASON=OUTER_TIMEOUT_OR_SIGKILL"
    else
        echo "R27_USABLE_EVIDENCE=true"
        echo "INITIAL_001A_SENT_COUNT=$(last_marker INITIAL_001A_SENT_COUNT NOT_REACHED)"
        echo "REPEAT_001A_SENT_COUNT=$(last_marker REPEAT_001A_SENT_COUNT NOT_REACHED)"
        echo "TOTAL_001A_SENT_COUNT=$(last_marker TOTAL_001A_SENT_COUNT NOT_REACHED)"
        echo "SECOND_001A_RESPONSE=$(last_marker SECOND_001A_RESPONSE NOT_REACHED)"
        echo "VIDEO_RTP_BEFORE_REPEAT=$(last_marker VIDEO_RTP_BEFORE_REPEAT NOT_REACHED)"
        echo "VIDEO_PACKET_COUNT_AT_REPEAT=$(last_marker VIDEO_PACKET_COUNT_AT_REPEAT NOT_REACHED)"
        echo "VIDEO_RTP_AFTER_REPEAT=$(last_marker VIDEO_RTP_AFTER_REPEAT NOT_REACHED)"
        echo "VIDEO_RTP_PAST_35S=$(last_marker VIDEO_RTP_PAST_35S NOT_REACHED)"
        echo "VIDEO_RTP_PAST_40S=$(last_marker VIDEO_RTP_PAST_40S NOT_REACHED)"
        echo "VIDEO_RTP_LAST_SECONDS_FROM_INITIAL_START=$(last_marker VIDEO_RTP_LAST_SECONDS_FROM_INITIAL_START NOT_REACHED)"
    fi
    echo "ICE_NEGOTIATION_COUNT=$(last_marker ICE_NEGOTIATION_COUNT NOT_REACHED)"
    echo "PSEUDOTCP_OPEN_COUNT=$(last_marker PSEUDOTCP_OPEN_COUNT NOT_REACHED)"
    echo "CTPP_REGISTRATION_COUNT=$(last_marker CTPP_REGISTRATION_COUNT NOT_REACHED)"
    echo "RTPC_CLIENT_OPEN_COUNT=$(last_marker RTPC_CLIENT_OPEN_COUNT NOT_REACHED)"
    echo "SELF_ACTIVATION_COUNT=$(last_marker SELF_ACTIVATION_COUNT NOT_REACHED)"
    echo "HELPER_PROCESS_UNCHANGED=$(last_marker HELPER_PROCESS_UNCHANGED NOT_REACHED)"
    echo "LISTENER_RUNNING_AFTER=$LISTENER_RUNNING_AFTER"
    echo "LISTENER_READY_AFTER=$LISTENER_READY_AFTER"
    echo "PRODUCTION_MEDIA_ACTIVE_DERIVED_FROM=LISTENER_READY_AFTER"
    echo "PRODUCTION_MEDIA_ACTIVE_DERIVATION_LISTENER_READY_AFTER=$LISTENER_READY_AFTER"
    echo "PRODUCTION_MEDIA_ACTIVE=$PRODUCTION_MEDIA_ACTIVE"
    echo "DOOR_ACTIONS_SENT=0"
    echo "GATE_ACTIONS_SENT=0"
    echo "SECOND_MEDIA_SESSION=false"
    echo "THIRD_001A=false"
    echo "REFRESH_LOOP=false"
    echo "AUTOMATIC_RETRY_001A=false"
    echo "RTCP_PLI=false"
    echo "RTCP_FIR=false"
    echo "NEW_ICE_NEGOTIATION_AFTER_REPEAT=false"
    echo "NEW_PSEUDOTCP_AFTER_REPEAT=false"
    echo "NEW_CTPP_REGISTRATION_AFTER_REPEAT=false"
    echo "NEW_RTPC_OPEN_AFTER_REPEAT=false"
    echo "NEW_SELF_ACTIVATION_AFTER_REPEAT=false"
    echo "OFFICIAL_APP_CAPTURE=false"
    echo "RAW_PCAP_CAPTURE=false"
    echo "=== END COMELIT P116 R27 REPEAT 001A LIVE FINAL ==="
}

on_exit() {
    local rc=$?
    stop_candidate_if_needed || true
    stop_pid "$VIDEO_SINK_PID"
    stop_pid "$AUDIO_SINK_PID"
    if [ "$LISTENER_STOPPED" -eq 1 ]; then
        restore_listener || rc=91
    fi
    campaign_processes_remaining
    derive_teardown_confidence
    derive_production_media_active
    print_final_block
    exit "$rc"
}

trap on_exit EXIT
trap 'exit 130' INT TERM HUP

if [ "$R27_LIVE_RUN" != YES ]; then
    echo "R27_OFFLINE_SAFE_REFUSAL=true"
    echo "LIVE_INVOCATIONS=0"
    exit 2
fi

if [ "${EUID}" -ne 0 ]; then
    echo "R27_REQUIRES_ROOT=true"
    exit 1
fi

for command in git python3 curl sha256sum timeout awk grep bash chmod install; do
    command -v "$command" >/dev/null 2>&1 || fail "R27_MISSING_COMMAND=$command"
done
[ -n "$R27_EXPECTED_COMMIT_SHA" ] || fail "R27_EXPECTED_COMMIT_SHA_REQUIRED=true"
[ -d "$REPO/.git" ] || fail "R27_REPO_PRESENT=false"
[ -x "$BASE_WRAPPER" ] || fail "R27_BASE_WRAPPER_PRESENT=false"
if [ -x "$BASE_WRAPPER" ]; then
    actual_wrapper_sha="$(sha256sum "$BASE_WRAPPER" | awk '{print $1}')"
    echo "BASE_WRAPPER_SHA256=$actual_wrapper_sha"
    [ "$actual_wrapper_sha" = "$BASE_WRAPPER_SHA256" ] || fail "BASE_WRAPPER_SHA256_GATE=FAIL"
fi

if [ "$FAIL" -eq 0 ]; then
    repo_head="$(git -C "$REPO" rev-parse HEAD 2>/dev/null || true)"
    echo "R27_REPO_HEAD=$repo_head"
    [ "$repo_head" = "$R27_EXPECTED_COMMIT_SHA" ] || fail "R27_EXPECTED_COMMIT_SHA_GATE=FAIL"
    [ -z "$(git -C "$REPO" status --porcelain)" ] || fail "R27_WORKTREE_CLEAN=FAIL"
fi

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
RUN_ROOT="/root/comelit-r27-repeat-001a-$STAMP"
mkdir -p "$RUN_ROOT"
chmod 700 "$RUN_ROOT"
LOG="$RUN_ROOT/live.log"
: > "$LOG"
chmod 600 "$LOG"

if [ "$FAIL" -eq 0 ]; then
    git -C "$REPO" show "$R27_EXPECTED_COMMIT_SHA:$TRANSFORM_REL" > "$RUN_ROOT/transform.py" || fail "R27_TRANSFORM_BLOB=FAIL"
    git -C "$REPO" show "$R27_EXPECTED_COMMIT_SHA:$RUNNER_REL" > "$RUN_ROOT/runner.sh" || fail "R27_RUNNER_BLOB=FAIL"
    git -C "$REPO" show "$R27_EXPECTED_COMMIT_SHA:$BUILDER_REL" > "$RUN_ROOT/builder.sh" || fail "R27_BUILDER_BLOB=FAIL"
    bash -n "$RUN_ROOT/runner.sh" || fail "R27_RUNNER_BASH_N=FAIL"
    bash -n "$RUN_ROOT/builder.sh" || fail "R27_BUILDER_BASH_N=FAIL"
    cmp "$RUN_ROOT/transform.py" "$REPO/$TRANSFORM_REL" >/dev/null 2>&1 || fail "R27_TRANSFORM_WORKTREE_BLOB_GATE=FAIL"
    cmp "$RUN_ROOT/runner.sh" "$REPO/$RUNNER_REL" >/dev/null 2>&1 || fail "R27_RUNNER_WORKTREE_BLOB_GATE=FAIL"
fi

if [ "$FAIL" -ne 0 ]; then
    echo "R27_PREFLIGHT=FAIL"
    exit 1
fi

echo "R27_PREFLIGHT=PASS"
echo "R27_RUN_ROOT=$RUN_ROOT"

echo "=== BUILD EPHEMERAL R27 HELPER ==="
R27_OUTPUT="$RUN_ROOT/comelit-media-r27"
(
    REPO="$REPO" \
    P80_BUILD_ALLOW_DETACHED=1 \
    P80_BUILD_EXPECTED_SHA="$R27_EXPECTED_COMMIT_SHA" \
    P80_BUILD_INCLUDE_P116=1 \
    P80_BUILD_TRANSFORM="$TRANSFORM_REL" \
    P80_BUILD_EXPECTED_SOURCE_SHA="$EXPECTED_SOURCE_SHA" \
    OUTPUT="$R27_OUTPUT" \
    bash "$RUN_ROOT/builder.sh"
) | tee "$RUN_ROOT/build.log"
build_rc=${PIPESTATUS[0]}
echo "R27_BUILD_RC=$build_rc"
[ "$build_rc" -eq 0 ] || exit 1
grep -F "GENERATED_SOURCE_SHA256=$EXPECTED_SOURCE_SHA" "$RUN_ROOT/build.log" | tee -a "$LOG" >/dev/null || fail "R27_GENERATED_SOURCE_SHA_GATE=FAIL"
[ -x "$R27_OUTPUT" ] || fail "R27_OUTPUT_PRESENT=false"
[ "$FAIL" -eq 0 ] || exit 1

echo "=== VERIFY LISTENER READY ==="
STATUS_BEFORE="$RUN_ROOT/listener-status-before.json"
post_control status "$STATUS_BEFORE" 10
if status_ready "$STATUS_BEFORE"; then
    LISTENER_READY_BEFORE=true
    echo "LISTENER_READY_BEFORE=true"
else
    fail "LISTENER_READY_BEFORE=false"
fi
[ "$FAIL" -eq 0 ] || exit 1

echo "=== STOP ONLY COMELIT LISTENER ==="
STOP_RESPONSE="$RUN_ROOT/listener-stop.json"
LISTENER_STOPPED=1
post_control stop "$STOP_RESPONSE" 20
echo "LISTENER_STOP_REQUESTED=true"
if status_stopped "$STOP_RESPONSE"; then
    echo "LISTENER_STOP_GATE=PASS"
else
    fail "LISTENER_STOP_GATE=FAIL"
fi
[ "$FAIL" -eq 0 ] || exit 1

VIDEO_SINK_PID="$(start_udp_sink "$VIDEO_RTP_PORT" "$RUN_ROOT/video.count")"
AUDIO_SINK_PID="$(start_udp_sink "$AUDIO_RTP_PORT" "$RUN_ROOT/audio.count")"
echo "R27_VIDEO_RTP_SINK=true"
echo "R27_AUDIO_RTP_SINK=true"

echo "=== RUN EXACTLY ONE WRAPPER INVOCATION ==="
LIVE_INVOCATIONS=1
echo "LIVE_INVOCATIONS=$LIVE_INVOCATIONS"
[ "$LIVE_INVOCATIONS" -eq 1 ] || exit 1
(
    COMELIT_MEDIA_HELPER="$R27_OUTPUT" \
    timeout "$OUTER_TIMEOUT_SECONDS" "$BASE_WRAPPER"
) > "$LOG" 2>&1 &
WRAPPER_PID=$!
wait "$WRAPPER_PID"
WRAPPER_RC=$?
WRAPPER_PID=""
echo "WRAPPER_RC=$WRAPPER_RC"
R27_REPEAT_EXECUTED="$(last_marker R27_REPEAT_001A_SENT false)"
[ "$R27_REPEAT_EXECUTED" = PASS ] && R27_REPEAT_EXECUTED=true
campaign_processes_remaining
derive_teardown_confidence

stop_pid "$VIDEO_SINK_PID"
stop_pid "$AUDIO_SINK_PID"
VIDEO_SINK_PID=""
AUDIO_SINK_PID=""

echo "=== RESTORE LISTENER ==="
restore_listener || exit 91

derive_production_media_active
exit 0
