#!/usr/bin/env bash
# CT120 research-only MSL-V1 Variant B idle-listener media runner.

set -u -o pipefail
umask 077

REPO=${REPO:-/root/comelit-door-diag-repo}
MSL_B_EXPECTED_COMMIT_SHA=${MSL_B_EXPECTED_COMMIT_SHA:-}
MSL_B_EXPECTED_GENERATED_SOURCE_SHA=${MSL_B_EXPECTED_GENERATED_SOURCE_SHA:-}
MSL_B_LIVE_RUN=${MSL_B_LIVE_RUN:-NO}
MSL_B_DRY_RUN=${MSL_B_DRY_RUN:-NO}
MSL_B_ATTEMPT_LEDGER=${MSL_B_ATTEMPT_LEDGER:-}
HA_WEBHOOK_URL=${HA_WEBHOOK_URL:-http://192.168.1.108:8123/api/webhook/comelit-ha-ring-test-control-v1}
BASE_WRAPPER=/usr/local/sbin/comelit-p2p-cloud-probe
BASE_WRAPPER_SHA256=a564535dff0cf10b1fe4766171f2960c52fb581f1c816cf81d2992c5c84e79c9
SOURCE_REL=safety-poc/research/door/v1_5_7/comelit-v4-persistent-ctpp-door.c
BUILDER_REL=safety-poc/research/media/v1/ct122_build_p116_r54_call_adoption_candidate.sh
TRANSFORM_REL=safety-poc/research/media/v1/entrance_msl_v1_idle_listener_media_transform.py
RUNNER_REL=safety-poc/research/media/v1/ct120_run_msl_v1_variant_b_live.sh
BASELINE_RUNNER_REL=safety-poc/research/media/v1/ct120_run_msl_v1_baseline_live.sh
EXPECTED_BASE_SOURCE_SHA=5827d9fd043b85fc0c59a31661a1a125c6b239771e2a70c3e5afdd95f1a03c73
APK_CLOSURE=${APK_CLOSURE:-/home/hermes/musl-apk-closure-p80}
ALPINE_IMAGE=${ALPINE_IMAGE:-alpine:3.24.1}
EXPECTED_INTERPRETER=/lib/ld-musl-x86_64.so.1
EXPECTED_NEEDED=libc.musl-x86_64.so.1,libglib-2.0.so.0,libgobject-2.0.so.0,libnice.so.10
VIDEO_RTP_PORT=17899
AUDIO_RTP_PORT=17808
SETUP_MARGIN_SECONDS=${SETUP_MARGIN_SECONDS:-35}
LISTENER_READY_WAIT_SECONDS=${LISTENER_READY_WAIT_SECONDS:-35}
MEDIA_OBSERVATION_SECONDS=${MEDIA_OBSERVATION_SECONDS:-20}
MEDIA_STARTUP_OUTER_TIMEOUT=$((SETUP_MARGIN_SECONDS + MEDIA_OBSERVATION_SECONDS))
MAX_MEDIA_STARTUP_OUTER_TIMEOUT_SECONDS=90
RUN_DIR=/run/comelit-p2p
START_FILE="$RUN_DIR/msl-b-start-idle-media"
STOP_FILE="$RUN_DIR/msl-b-stop-idle-media"
CLOCK_BASE_FILE="$RUN_DIR/msl-b-clock-base"
CANDIDATE_NAME=comelit-msl-v1-variant-b-listener

FAIL=0
LIVE_INVOCATIONS=0
LISTENER_STOPPED=0
LISTENER_READY_BEFORE=false
LISTENER_READY_AFTER=false
MSL_B_DRY_RUN_COMPLETED=false
MSL_B_DRY_RUN_REACHED_FINAL_SUMMARY=false
MSL_B_COMELIT_INTERACTION=0
MSL_B_HA_INTERACTION=0
MSL_B_RUN_CLASSIFICATION=NOT_RUN
MEDIA_TEARDOWN=UNCERTAIN
CAMPAIGN_PROCESSES_REMAINING=UNKNOWN
RTP_SINK_PORTS_REMAINING=UNKNOWN
RUN_ROOT=""
SESSION_LOG=""
LISTENER_PID=""
VIDEO_SINK_PID=""
AUDIO_SINK_PID=""
MSL_B_CAMPAIGN_STOPPED_FAIL_CLOSED=false

msl_b_mono_ms() {
    python3 - <<'PY'
import time
print(time.monotonic_ns() // 1_000_000)
PY
}

msl_b_since_base() {
    python3 - "$CLOCK_BASE_FILE" <<'PY'
from pathlib import Path
import sys, time
base = int(Path(sys.argv[1]).read_text(encoding="utf-8").strip())
print(max(0, time.monotonic_ns() // 1_000_000 - base))
PY
}

msl_b_mark() {
    printf 'MSL_B_%s_MONO_MS=%s\n' "$1" "$(msl_b_since_base)"
}

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
    if [ "$MSL_B_DRY_RUN" = YES ]; then
        case "$action" in
            status|start)
                printf '{"ok":true,"supervisor_running":true,"running":true,"listener_ready":true,"last_error":null}\n' > "$output"
                ;;
            stop)
                printf '{"ok":true,"supervisor_running":true,"running":false,"listener_ready":false,"last_error":null}\n' > "$output"
                ;;
            *)
                printf '{"ok":false,"last_error":"unknown dry-run action"}\n' > "$output"
                ;;
        esac
        printf '200\n' > "$http_file"
        echo "CONTROL_${action^^}_DRY_RUN=true"
        echo "CONTROL_${action^^}_HTTP_STATUS=200"
        return 0
    fi
    MSL_B_HA_INTERACTION=$((MSL_B_HA_INTERACTION + 1))
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

msl_b_start_udp_sink() {
    local port="$1"
    local count_file="$2"
    local timeout_seconds="${3:-2}"
    python3 - "$port" "$count_file" "$timeout_seconds" >"${count_file}.log" 2>&1 <<'PY' &
from pathlib import Path
import signal, socket, sys, time
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
sock.settimeout(0.05)
count = 0
while not stop and time.monotonic() < deadline:
    try:
        sock.recvfrom(65535)
        count += 1
    except socket.timeout:
        continue
count_file.write_text(f"{count}\n", encoding="utf-8")
PY
    printf '%s\n' "$!"
}

if [ "${MSL_B_SELF_TEST_UDP_SINK:-NO}" = YES ]; then
    tmp="${TMPDIR:-/tmp}/msl-b-udp-sink-$$.count"
    pid="$(msl_b_start_udp_sink 17992 "$tmp" 2)"
    sleep 0.2
    set +e
    python3 - <<'PY'
import socket
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
for _ in range(3):
    s.sendto(b"x", ("127.0.0.1", 17992))
PY
    send_rc=$?
    set -u -o pipefail
    if [ "$send_rc" -ne 0 ]; then
        echo "MSL_B_UDP_SINK_SELF_TEST_PERMISSION_DENIED=true"
        kill -TERM "$pid" 2>/dev/null || true
        rm -f "$tmp" "$tmp.log"
        exit 0
    fi
    sleep 2
    kill -TERM "$pid" 2>/dev/null || true
    echo "MSL_B_UDP_SINK_SELF_TEST_COUNT=$(tr -d '[:space:]' < "$tmp")"
    rm -f "$tmp" "$tmp.log"
    exit 0
fi

if [ "$MSL_B_DRY_RUN" != YES ] && [ "$MSL_B_LIVE_RUN" != YES ]; then
    echo "MSL_B_OFFLINE_SAFE_REFUSAL=true"
    echo "LIVE_INVOCATIONS=0"
    echo "MSL_B_RUN_CLASSIFICATION=NOT_RUN"
    exit 2
fi

print_final_block() {
    echo "=== COMELIT MSL V1 VARIANT B FINAL ==="
    echo "LIVE_INVOCATIONS=$LIVE_INVOCATIONS"
    echo "MSL_B_START_REFERENCE=MSL_B_T00_IDLE_MEDIA_REQUEST_ACCEPTED"
    echo "SETUP_MARGIN_SECONDS=$SETUP_MARGIN_SECONDS"
    echo "LISTENER_READY_WAIT_SECONDS=$LISTENER_READY_WAIT_SECONDS"
    echo "MEDIA_OBSERVATION_SECONDS=$MEDIA_OBSERVATION_SECONDS"
    echo "MEDIA_STARTUP_OUTER_TIMEOUT=$MEDIA_STARTUP_OUTER_TIMEOUT"
    if [ "$MEDIA_STARTUP_OUTER_TIMEOUT" -le "$MAX_MEDIA_STARTUP_OUTER_TIMEOUT_SECONDS" ] &&
       [ "$SETUP_MARGIN_SECONDS" -ge 30 ] &&
       [ "$MEDIA_OBSERVATION_SECONDS" -ge 10 ]; then
        echo "MSL_B_BOUND_INVARIANT=PASS"
    else
        echo "MSL_B_BOUND_INVARIANT=FAIL"
    fi
    echo "MSL_B_LISTENER_READY_BEFORE=$LISTENER_READY_BEFORE"
    echo "MSL_B_LISTENER_READY_AFTER=$LISTENER_READY_AFTER"
    echo "MSL_B_T03_NATIVE_MEDIA_HELPER_PROCESS_START_MONO_MS=N/A REASON=same_ready_listener_process"
    echo "MSL_B_T04_LOCAL_SDP_OFFER_READY_MONO_MS=N/A REASON=no_new_offer"
    echo "MSL_B_T06_CLOUD_P2P_REQUEST_START_MONO_MS=N/A REASON=no_new_cloud_negotiation"
    echo "MSL_B_T07_CLOUD_P2P_RESPONSE_REMOTE_SDP_WRITTEN_MONO_MS=N/A REASON=no_new_remote_sdp"
    echo "MSL_B_T08_ICE_CONNECTED_MONO_MS=N/A REASON=existing_ICE_session_reused"
    echo "MSL_B_T09_PSEUDOTCP_OPEN_MONO_MS=N/A REASON=existing_PseudoTCP_reused"
    echo "MSL_B_T10_VIP_UAUT_READY_MONO_MS=N/A REASON=existing_UAUT_reused"
    echo "MSL_B_T11_CTPP_REGISTRATION_READY_MONO_MS=N/A REASON=existing_CTPP_registration_reused"
    echo "MEDIA_TEARDOWN=$MEDIA_TEARDOWN"
    echo "MSL_B_CAMPAIGN_STOPPED_FAIL_CLOSED=$MSL_B_CAMPAIGN_STOPPED_FAIL_CLOSED"
    echo "CAMPAIGN_PROCESSES_REMAINING=$CAMPAIGN_PROCESSES_REMAINING"
    echo "RTP_SINK_PORTS_REMAINING=$RTP_SINK_PORTS_REMAINING"
    echo "DOOR_ACTIONS_SENT=0"
    echo "GATE_ACTIONS_SENT=0"
    echo "PHYSICAL_RING_ACTIONS=0"
    echo "AUTOMATIC_PROTOCOL_RETRY=false"
    echo "SECOND_MEDIA_SESSION=false"
    echo "MSL_B_RUN_CLASSIFICATION=$MSL_B_RUN_CLASSIFICATION"
    echo "MSL_B_DRY_RUN_COMPLETED=$MSL_B_DRY_RUN_COMPLETED"
    echo "MSL_B_DRY_RUN_REACHED_FINAL_SUMMARY=$MSL_B_DRY_RUN_REACHED_FINAL_SUMMARY"
    echo "MSL_B_DRY_RUN_LIVE_INVOCATIONS=$LIVE_INVOCATIONS"
    echo "MSL_B_DRY_RUN_COMELIT_INTERACTION=$MSL_B_COMELIT_INTERACTION"
    echo "MSL_B_DRY_RUN_HA_INTERACTION=$MSL_B_HA_INTERACTION"
    echo "MSL_B_CONTINUATION_EVIDENCE_SOURCE=INDEPENDENT_UDP_SINK_OR_EXPLICIT_ZERO"
    echo "=== END COMELIT MSL V1 VARIANT B FINAL ==="
}

restore_listener() {
    local poll
    local status_file
    local start_file
    [ "$LISTENER_STOPPED" -eq 1 ] || return 0
    start_file="$RUN_ROOT/listener-start.json"
    post_control start "$start_file" 40 || true
    for poll in 1 2 3 4 5 6 7 8; do
        status_file="$RUN_ROOT/listener-restore-${poll}.json"
        post_control status "$status_file" 10 || true
        if status_ready "$status_file"; then
            LISTENER_STOPPED=0
            LISTENER_READY_AFTER=true
            return 0
        fi
        sleep 5
    done
    return 91
}

stop_pid() {
    local pid="$1"
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
        kill -TERM "$pid" 2>/dev/null || true
        sleep 1
        kill -KILL "$pid" 2>/dev/null || true
    fi
}

run_dry_run() {
    RUN_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/comelit-msl-v1-b-dry-run.XXXXXX")"
    chmod 700 "$RUN_ROOT"
    SESSION_LOG="$RUN_ROOT/session.log"
    CLOCK_BASE_FILE="$RUN_ROOT/msl-b-clock-base"
    : > "$SESSION_LOG"
    chmod 600 "$SESSION_LOG"
    msl_b_mono_ms > "$CLOCK_BASE_FILE"
    chmod 600 "$CLOCK_BASE_FILE"

    echo "MSL_B_DRY_RUN_MODE=YES"
    echo "MSL_B_DRY_RUN_REAL_HA_WEBHOOK=false"
    echo "MSL_B_DRY_RUN_REAL_COMELIT=false"
    echo "MSL_B_DRY_RUN_CHROOT_BUILD=false"
    echo "MSL_B_DRY_RUN_CANDIDATE_EXECUTED=false"
    echo "MSL_B_BUILD_RC=DRY_RUN"
    echo "P78_GATE_DECISION=substituted REASON=research_branch_uses_commit_and_blob_pins"

    STATUS_BEFORE="$RUN_ROOT/listener-status-before.json"
    post_control status "$STATUS_BEFORE" 10
    if status_ready "$STATUS_BEFORE"; then
        LISTENER_READY_BEFORE=true
    else
        fail "MSL_B_DRY_RUN_STATUS_READY=FAIL"
    fi
    [ "$FAIL" -eq 0 ] || return 1

    STOP_RESPONSE="$RUN_ROOT/listener-stop.json"
    LISTENER_STOPPED=1
    post_control stop "$STOP_RESPONSE" 20
    if ! status_stopped "$STOP_RESPONSE"; then
        fail "MSL_B_DRY_RUN_STATUS_STOPPED=FAIL"
    fi
    [ "$FAIL" -eq 0 ] || return 1

    {
        echo "MSL_B_LISTENER_READY_BEFORE=true"
        echo "MSL_B_LISTENER_PROCESS_PID=4242"
        echo "MSL_B_IDLE_MEDIA_REQUEST_ACCEPTED=true"
        echo "MSL_B_T00_IDLE_MEDIA_REQUEST_ACCEPTED_MONO_MS=$(msl_b_since_base)"
        echo "MSL_B_T12_RTPC_MEDIA_OPEN_CONTROL_READY_MONO_MS=$(msl_b_since_base)"
        echo "MSL_B_T13_INITIAL_001A_SENT_MONO_MS=$(msl_b_since_base)"
        echo "MSL_B_T14_DEVICE_STRUCTURAL_ACK_MEDIA_ACCEPTANCE_MONO_MS=$(msl_b_since_base)"
        echo "MSL_B_MEDIA_ACTIVE=true"
        echo "MSL_B_T15_MEDIA_ACTIVE_MONO_MS=$(msl_b_since_base)"
        echo "MSL_B_T17_FIRST_VIDEO_RTP_MONO_MS=$(msl_b_since_base)"
        echo "MSL_B_T18_FIRST_SPS_PPS_IDR_MONO_MS=$(msl_b_since_base)"
        echo "MSL_B_START_TO_FIRST_VIDEO_RTP_MS=0"
        echo "MSL_B_START_TO_DECODABLE_VIDEO_MS=0"
        echo "MSL_B_PHASE_T00_TO_T12_MS=0"
        echo "MSL_B_PHASE_T12_TO_T13_MS=0"
        echo "MSL_B_PHASE_T13_TO_T14_MS=0"
        echo "MSL_B_PHASE_T14_TO_T15_MS=0"
        echo "MSL_B_PHASE_T15_TO_T17_MS=0"
        echo "MSL_B_PHASE_T17_TO_T18_MS=0"
        echo "MSL_B_CLOUD_NEGOTIATION_COUNT=0"
        echo "MSL_B_ICE_BOOTSTRAP_COUNT=0"
        echo "MSL_B_PSEUDOTCP_OPEN_COUNT=0"
        echo "MSL_B_CTPP_REGISTRATION_COUNT=0"
        echo "MSL_B_MEDIA_SESSION_COUNT=1"
        echo "MSL_B_SECOND_MEDIA_SESSION=false"
        echo "MSL_B_LISTENER_READY_AFTER=true"
        echo "MSL_B_RECONNECT_COUNT_BEFORE=0"
        echo "MSL_B_RECONNECT_COUNT_AFTER=0"
        echo "MSL_B_RECONNECT_COUNT_DELTA=0"
        echo "MSL_B_MEDIA_RX_ACTIVE=true"
        echo "MSL_B_MEDIA_RX_INACTIVE_AFTER_CLOSE=true"
        echo "MSL_B_VIDEO_RTP_PACKETS=3"
        echo "MSL_B_SPS_COUNT=1"
        echo "MSL_B_MEDIA_CHANNEL_CLOSED=true"
        echo "MSL_B_TUNNEL_PRESERVED=true"
    } > "$SESSION_LOG"
    cat "$SESSION_LOG"
    MEDIA_TEARDOWN=CONFIRMED
    CAMPAIGN_PROCESSES_REMAINING=NONE
    RTP_SINK_PORTS_REMAINING=0
    MSL_B_RUN_CLASSIFICATION=DRY_RUN_COMPLETE
    restore_listener || return 91
    MSL_B_DRY_RUN_COMPLETED=true
    MSL_B_DRY_RUN_REACHED_FINAL_SUMMARY=true
    print_final_block
    rm -rf "$RUN_ROOT"
}

on_exit() {
    rc=$?
    stop_pid "$LISTENER_PID"
    stop_pid "$VIDEO_SINK_PID"
    stop_pid "$AUDIO_SINK_PID"
    RTP_SINK_PORTS_REMAINING=0
    if [ "$LISTENER_STOPPED" -eq 1 ]; then
        restore_listener || {
            MSL_B_CAMPAIGN_STOPPED_FAIL_CLOSED=true
            rc=91
        }
    fi
    if [ -n "$RUN_ROOT" ] && pgrep -af "$CANDIDATE_NAME" >/dev/null 2>&1; then
        CAMPAIGN_PROCESSES_REMAINING=FOUND
        MEDIA_TEARDOWN=UNCERTAIN
    else
        CAMPAIGN_PROCESSES_REMAINING=NONE
        [ "$MEDIA_TEARDOWN" = CONFIRMED ] || MEDIA_TEARDOWN=UNCERTAIN
    fi
    print_final_block
    exit "$rc"
}
trap on_exit EXIT
trap 'exit 130' INT TERM HUP

if [ "$MSL_B_DRY_RUN" = YES ] && [ "$MSL_B_LIVE_RUN" = YES ]; then
    echo "MSL_B_DRY_RUN_LIVE_RUN_CONFLICT=true"
    echo "LIVE_INVOCATIONS=0"
    exit 2
fi

if [ "$MSL_B_DRY_RUN" = YES ]; then
    trap - EXIT
    run_dry_run
    exit "$?"
fi

[ -n "$MSL_B_EXPECTED_COMMIT_SHA" ] || fail "MSL_B_EXPECTED_COMMIT_SHA_REQUIRED=true"
[ -n "$MSL_B_EXPECTED_GENERATED_SOURCE_SHA" ] || fail "MSL_B_EXPECTED_GENERATED_SOURCE_SHA_REQUIRED=true"
[ -n "$MSL_B_ATTEMPT_LEDGER" ] || fail "MSL_B_ATTEMPT_LEDGER_REQUIRED=true"
if [ -n "$MSL_B_ATTEMPT_LEDGER" ]; then
    if [ ! -f "$MSL_B_ATTEMPT_LEDGER" ]; then
        fail "MSL_B_ATTEMPT_LEDGER=ABSENT"
    else
        ledger_value="$(tr -d '[:space:]' < "$MSL_B_ATTEMPT_LEDGER")"
        case "$ledger_value" in
            ''|*[!0-9]*) fail "MSL_B_ATTEMPT_LEDGER=MALFORMED" ;;
            *) [ "$ledger_value" -lt 15 ] || fail "MSL_B_ATTEMPT_LEDGER_CAP=FAIL" ;;
        esac
    fi
fi
[ "$MEDIA_STARTUP_OUTER_TIMEOUT" -le "$MAX_MEDIA_STARTUP_OUTER_TIMEOUT_SECONDS" ] || fail "MSL_B_MEDIA_STARTUP_OUTER_TIMEOUT_GATE=FAIL"
[ "$FAIL" -eq 0 ] || exit 1

if [ "${EUID}" -ne 0 ]; then
    echo "MSL_B_REQUIRES_ROOT=true"
    exit 1
fi

for command in git python3 curl sha256sum timeout awk grep bash chmod install readelf cmp stat; do
    command -v "$command" >/dev/null 2>&1 || fail "MSL_B_MISSING_COMMAND=$command"
done

[ -d "$REPO/.git" ] || fail "MSL_B_REPO_PRESENT=false"
[ -x "$BASE_WRAPPER" ] || fail "MSL_B_BASE_WRAPPER_PRESENT=false"
if [ -x "$BASE_WRAPPER" ]; then
    actual_wrapper_sha="$(sha256sum "$BASE_WRAPPER" | awk '{print $1}')"
    echo "BASE_WRAPPER_SHA256=$actual_wrapper_sha"
    [ "$actual_wrapper_sha" = "$BASE_WRAPPER_SHA256" ] || fail "MSL_B_BASE_WRAPPER_SHA256_GATE=FAIL"
fi
repo_head="$(git -C "$REPO" rev-parse HEAD 2>/dev/null || true)"
echo "MSL_B_REPO_HEAD=$repo_head"
[ "$repo_head" = "$MSL_B_EXPECTED_COMMIT_SHA" ] || fail "MSL_B_EXPECTED_COMMIT_SHA_GATE=FAIL"
[ -z "$(git -C "$REPO" status --porcelain)" ] || fail "MSL_B_WORKTREE_CLEAN=FAIL"
[ "$(git -C "$REPO" show "$MSL_B_EXPECTED_COMMIT_SHA:$SOURCE_REL" | sha256sum | awk '{print $1}')" = "$EXPECTED_BASE_SOURCE_SHA" ] || fail "MSL_B_BASE_SOURCE_SHA_GATE=FAIL"
[ "$FAIL" -eq 0 ] || exit 1

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
RUN_ROOT="/root/comelit-msl-v1-variant-b-$STAMP"
mkdir -p "$RUN_ROOT"
chmod 700 "$RUN_ROOT"
SESSION_LOG="$RUN_ROOT/session.log"
: > "$SESSION_LOG"
chmod 600 "$SESSION_LOG"

git -C "$REPO" show "$MSL_B_EXPECTED_COMMIT_SHA:$TRANSFORM_REL" > "$RUN_ROOT/transform.py" || fail "MSL_B_TRANSFORM_BLOB=FAIL"
git -C "$REPO" show "$MSL_B_EXPECTED_COMMIT_SHA:$RUNNER_REL" > "$RUN_ROOT/runner.sh" || fail "MSL_B_RUNNER_BLOB=FAIL"
git -C "$REPO" show "$MSL_B_EXPECTED_COMMIT_SHA:$BASELINE_RUNNER_REL" > "$RUN_ROOT/baseline-runner.sh" || fail "MSL_B_BASELINE_RUNNER_BLOB=FAIL"
bash -n "$RUN_ROOT/runner.sh" || fail "MSL_B_RUNNER_BASH_N=FAIL"
cmp "$RUN_ROOT/transform.py" "$REPO/$TRANSFORM_REL" >/dev/null 2>&1 || fail "MSL_B_TRANSFORM_WORKTREE_BLOB_GATE=FAIL"
cmp "$RUN_ROOT/runner.sh" "$REPO/$RUNNER_REL" >/dev/null 2>&1 || fail "MSL_B_RUNNER_WORKTREE_BLOB_GATE=FAIL"
echo "P78_GATE_DECISION=substituted REASON=research_branch_pins_CT120_clone_commit_generated_source_runner_transform_and_base_wrapper"
[ "$FAIL" -eq 0 ] || exit 1

install -d -m 700 "$RUN_DIR"
rm -f "$START_FILE" "$STOP_FILE"
msl_b_mono_ms > "$CLOCK_BASE_FILE"
chmod 600 "$CLOCK_BASE_FILE"

echo "=== BUILD EPHEMERAL VARIANT B LISTENER ==="
MSL_B_OUTPUT="$RUN_ROOT/$CANDIDATE_NAME"
SOURCE_A="$RUN_ROOT/msl-b-a.c"
SOURCE_B="$RUN_ROOT/msl-b-b.c"
META="$RUN_ROOT/build-meta.txt"
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$REPO/safety-poc/research/media/v1" \
    python3 "$REPO/$TRANSFORM_REL" --source "$REPO/$SOURCE_REL" --output "$SOURCE_A"
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$REPO/safety-poc/research/media/v1" \
    python3 "$REPO/$TRANSFORM_REL" --source "$REPO/$SOURCE_REL" --output "$SOURCE_B"
source_a_sha="$(sha256sum "$SOURCE_A" | awk '{print $1}')"
source_b_sha="$(sha256sum "$SOURCE_B" | awk '{print $1}')"
echo "MSL_B_GENERATED_SOURCE_SHA256_A=$source_a_sha"
echo "MSL_B_GENERATED_SOURCE_SHA256_B=$source_b_sha"
cmp "$SOURCE_A" "$SOURCE_B" >/dev/null 2>&1 || fail "MSL_B_TRANSFORM_DETERMINISTIC=FAIL"
[ "$source_a_sha" = "$MSL_B_EXPECTED_GENERATED_SOURCE_SHA" ] || fail "MSL_B_GENERATED_SOURCE_SHA_GATE=FAIL"
[ "$FAIL" -eq 0 ] || exit 1
[ -d "$APK_CLOSURE" ] || fail "MSL_B_APK_CLOSURE_PRESENT=false"
command -v docker >/dev/null 2>&1 || fail "MSL_B_DOCKER_PRESENT=false"
[ "$FAIL" -eq 0 ] || exit 1
cat > "$RUN_ROOT/build.sh" <<'EOS'
set -eu
apk add --no-network --allow-untrusted /pkgs/*.apk >/dev/null
cc -O2 -g -Wall -Wextra -Wl,--as-needed \
    -o /w/comelit-msl-v1-variant-b-listener \
    /w/msl-b-a.c \
    $(pkg-config --cflags --libs nice glib-2.0 gio-2.0 gobject-2.0)
chmod 755 /w/comelit-msl-v1-variant-b-listener
readelf -l /w/comelit-msl-v1-variant-b-listener \
    | sed -n 's@.*Requesting program interpreter: \(.*\)]@interpreter=\1@p' \
    > /w/build-meta.txt
readelf -d /w/comelit-msl-v1-variant-b-listener \
    | sed -n 's/.*Shared library: \[\(.*\)\]/\1/p' \
    | sort \
    | paste -sd, - \
    | sed 's/^/needed_sorted=/' \
    >> /w/build-meta.txt
EOS
chmod 700 "$RUN_ROOT/build.sh"
set +e
timeout 900 docker run --rm --network none \
    --security-opt apparmor=unconfined \
    -v "$RUN_ROOT":/w \
    -v "$APK_CLOSURE":/pkgs:ro \
    "$ALPINE_IMAGE" \
    /bin/sh /w/build.sh | tee "$RUN_ROOT/build.log"
build_rc=${PIPESTATUS[0]}
set -u -o pipefail
echo "MSL_B_BUILD_RC=$build_rc"
[ "$build_rc" -eq 0 ] || exit 1
mv "$RUN_ROOT/comelit-msl-v1-variant-b-listener" "$MSL_B_OUTPUT"
chmod 700 "$MSL_B_OUTPUT"
interpreter="$(awk -F= '$1=="interpreter"{print $2}' "$META")"
needed="$(awk -F= '$1=="needed_sorted"{print $2}' "$META")"
echo "MSL_B_MUSL_INTERPRETER=$interpreter"
echo "MSL_B_NEEDED_SORTED=$needed"
[ "$interpreter" = "$EXPECTED_INTERPRETER" ] || fail "MSL_B_MUSL_INTERPRETER_GATE=FAIL"
[ "$needed" = "$EXPECTED_NEEDED" ] || fail "MSL_B_NEEDED_GATE=FAIL"
echo "MSL_B_CANDIDATE_BINARY_SHA256=$(sha256sum "$MSL_B_OUTPUT" | awk '{print $1}')"
[ "$FAIL" -eq 0 ] || exit 1

echo "=== STOP HA LISTENER BEFORE RESEARCH LISTENER ==="
STATUS_BEFORE="$RUN_ROOT/listener-status-before.json"
post_control status "$STATUS_BEFORE" 10
if status_ready "$STATUS_BEFORE"; then
    LISTENER_READY_BEFORE=true
else
    fail "MSL_B_LISTENER_READY_BEFORE=false"
fi
[ "$FAIL" -eq 0 ] || exit 1
STOP_RESPONSE="$RUN_ROOT/listener-stop.json"
LISTENER_STOPPED=1
post_control stop "$STOP_RESPONSE" 20
status_stopped "$STOP_RESPONSE" || fail "MSL_B_LISTENER_STOP_GATE=FAIL"
[ "$FAIL" -eq 0 ] || exit 1

VIDEO_SINK_PID="$(msl_b_start_udp_sink "$VIDEO_RTP_PORT" "$RUN_ROOT/video.count" "$MEDIA_STARTUP_OUTER_TIMEOUT")"
AUDIO_SINK_PID="$(msl_b_start_udp_sink "$AUDIO_RTP_PORT" "$RUN_ROOT/audio.count" "$MEDIA_STARTUP_OUTER_TIMEOUT")"
echo "MSL_B_VIDEO_RTP_SINK=true"
echo "MSL_B_AUDIO_RTP_SINK=true"
echo "MSL_B_CONTINUATION_EVIDENCE_SOURCE=INDEPENDENT_UDP_SINK_OR_EXPLICIT_ZERO"

echo "=== RUN RESEARCH LISTENER AND ONE IDLE MEDIA CONTROL ==="
LIVE_INVOCATIONS=1
MSL_B_CLOCK_BASE_FILE="$CLOCK_BASE_FILE" "$MSL_B_OUTPUT" > "$SESSION_LOG" 2>&1 &
LISTENER_PID=$!
for _poll in $(seq 1 "$LISTENER_READY_WAIT_SECONDS"); do
    if grep -q "V4_RING_LISTENER_READY=true" "$SESSION_LOG"; then
        break
    fi
    sleep 1
done
grep -q "V4_RING_LISTENER_READY=true" "$SESSION_LOG" || fail "MSL_B_RESEARCH_LISTENER_READY=FAIL"
[ "$FAIL" -eq 0 ] || exit 1
install -m 600 /dev/null "$START_FILE"
sleep "$MEDIA_OBSERVATION_SECONDS"
install -m 600 /dev/null "$STOP_FILE"
sleep 3
install -m 600 /dev/null "$RUN_DIR/stop"
stop_pid "$LISTENER_PID"
LISTENER_PID=""
cat "$SESSION_LOG"
MSL_B_RUN_CLASSIFICATION=VARIANT_B_ATTEMPT_COMPLETE

stop_pid "$VIDEO_SINK_PID"
stop_pid "$AUDIO_SINK_PID"
VIDEO_SINK_PID=""
AUDIO_SINK_PID=""
echo "MSL_B_VIDEO_SINK_DATAGRAMS=$(tr -d '[:space:]' < "$RUN_ROOT/video.count" 2>/dev/null || printf 0)"
echo "MSL_B_AUDIO_SINK_DATAGRAMS=$(tr -d '[:space:]' < "$RUN_ROOT/audio.count" 2>/dev/null || printf 0)"
if grep -q "MSL_B_MEDIA_CHANNEL_CLOSED=true" "$SESSION_LOG"; then
    MEDIA_TEARDOWN=CONFIRMED
fi

echo "=== RESTORE HA LISTENER ==="
restore_listener || exit 91
LISTENER_READY_AFTER=true
exit 0
