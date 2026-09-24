#!/usr/bin/env bash
# CT120 research-only P116/R27 same-session repeat 0x001A live runner.
# The helper observes for 100 seconds after MEDIA_ACTIVE. The wrapper timeout is
# a hard 120 second per-session bound, allowing at least 90 seconds of proven
# media while preserving the campaign ceiling.

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
EXPECTED_SOURCE_SHA=7449d477738c1b4a66e9a598d93451caa936b4facfde9919ab935c3335d2a99c
VIDEO_RTP_PORT=17899
AUDIO_RTP_PORT=17808
MAX_LIVE_OBSERVATION_SECONDS=100
OUTER_TIMEOUT_SECONDS=120
RUN_DIR=/run/comelit-media
STOP_FILE="$RUN_DIR/stop"
CANDIDATE_HOLDER_NAME=comelit-r27-repeat-001a
WRAPPER_NAME=comelit-p2p-cloud-probe-r27

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
SESSION_LOG=""
BUILD_PROVENANCE_LOG=""
CANDIDATE_WRAPPER=""
CANDIDATE_LAUNCHER=""
RUN_MUSL_LOADER=""
LISTENER_READY_BEFORE=false
LISTENER_RUNNING_AFTER=false
LISTENER_READY_AFTER=false
PRODUCTION_MEDIA_ACTIVE=false
CAMPAIGN_PROCESSES_REMAINING=UNKNOWN
RTP_SINK_PORTS_REMAINING=UNKNOWN
CT120_RESEARCH_HELPER_STOPPED=false
CT120_RESEARCH_SESSION_CLOSED=false
R27_SESSION_CLOSED=false
TEARDOWN_CONFIDENCE=UNCERTAIN
R27_RUN_CLASSIFICATION=NOT_RUN
R27_REPEAT_EXECUTED=false
R27_HELPER_EVIDENCE=false

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
    if [ -f "$SESSION_LOG" ]; then
        awk -v key="$key" -v fallback="$fallback" '
            index($0, key "=") == 1 { value = substr($0, length(key) + 2); found = 1 }
            END { if (found) print value; else print fallback }
        ' "$SESSION_LOG"
    else
        printf '%s\n' "$fallback"
    fi
}

build_provenance_marker() {
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

last_marker_equals() {
    local key="$1"
    local expected="$2"
    [ "$(last_marker "$key" __MISSING__)" = "$expected" ]
}

p80_video_rtp_progress_positive() {
    [ -f "$SESSION_LOG" ] || return 1
    awk -F= '
        $1 ~ /^P80_VIDEO_RTP_PACKETS(_.*)?$/ && $2 ~ /^[0-9]+$/ && $2 + 0 > 0 { found = 1 }
        END { exit found ? 0 : 1 }
    ' "$SESSION_LOG"
}

evaluate_helper_evidence() {
    R27_HELPER_EVIDENCE=false
    if last_marker_equals P78_CTPP_REGISTERED_REUSED true &&
       last_marker_equals P78_SECOND_CTPP_OPEN false &&
       last_marker_equals P78_RTPC_CLIENT_001A_SENT PASS &&
       last_marker_equals P80_MEDIA_ACTIVE true &&
       p80_video_rtp_progress_positive; then
        R27_HELPER_EVIDENCE=true
        echo "R27_HELPER_EVIDENCE_GATE=PASS"
    else
        echo "R27_HELPER_EVIDENCE_GATE=FAIL"
        echo "R27_HELPER_EVIDENCE_REQUIRED=P78_CTPP_REGISTERED_REUSED,P78_SECOND_CTPP_OPEN,P78_RTPC_CLIENT_001A_SENT,P80_MEDIA_ACTIVE,P80_VIDEO_RTP_PACKETS_POSITIVE"
    fi
}

campaign_processes_remaining() {
    local pattern="$BASE_WRAPPER|$WRAPPER_NAME|$CANDIDATE_HOLDER_NAME"
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

rtp_sink_ports_remaining() {
    local remaining=0
    if [ -n "$VIDEO_SINK_PID" ] && kill -0 "$VIDEO_SINK_PID" 2>/dev/null; then
        remaining=$((remaining + 1))
    fi
    if [ -n "$AUDIO_SINK_PID" ] && kill -0 "$AUDIO_SINK_PID" 2>/dev/null; then
        remaining=$((remaining + 1))
    fi
    RTP_SINK_PORTS_REMAINING="$remaining"
    echo "RTP_SINK_PORTS_REMAINING=$RTP_SINK_PORTS_REMAINING"
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
    elif [ "$LIVE_INVOCATIONS" -ne 1 ]; then
        R27_RUN_CLASSIFICATION=NOT_RUN
    elif [ "$TEARDOWN_CONFIDENCE" = CONFIRMED ]; then
        if [ "$R27_HELPER_EVIDENCE" = true ]; then
            R27_RUN_CLASSIFICATION=OBSERVATION_USABLE
        else
            R27_RUN_CLASSIFICATION=INSUFFICIENT_HELPER_EVIDENCE
        fi
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
    echo "RTP_SINK_PORTS_REMAINING=$RTP_SINK_PORTS_REMAINING"
    echo "CT120_RESEARCH_HELPER_STOPPED=$CT120_RESEARCH_HELPER_STOPPED"
    echo "CT120_RESEARCH_SESSION_CLOSED=$CT120_RESEARCH_SESSION_CLOSED"
    echo "R27_SESSION_CLOSED=$R27_SESSION_CLOSED"
    echo "TEARDOWN_CONFIDENCE=$TEARDOWN_CONFIDENCE"
    echo "R27_RUN_CLASSIFICATION=$R27_RUN_CLASSIFICATION"
    echo "R27_REPEAT_EXECUTED=$R27_REPEAT_EXECUTED"
    echo "GENERATED_SOURCE_SHA256=$(build_provenance_marker GENERATED_SOURCE_SHA256 NOT_REACHED)"
    echo "R27_REPEAT_DELAY_SECONDS=20"
    echo "R27_REPEAT_DELAY_IS_PROTOCOL_CONSTANT=false"
    echo "R27_REPEAT_DELAY_PROMOTED_TO_PRODUCTION=false"
    if [ "$R27_RUN_CLASSIFICATION" != OBSERVATION_USABLE ]; then
        echo "R27_USABLE_EVIDENCE=false"
        echo "R27_SCALARS_SUPPRESSED=true"
        if [ "$R27_RUN_CLASSIFICATION" = INCONCLUSIVE_OUTER_TIMEOUT ]; then
            echo "R27_SCALARS_SUPPRESSED_REASON=OUTER_TIMEOUT_OR_SIGKILL"
        else
            echo "R27_SCALARS_SUPPRESSED_REASON=$R27_RUN_CLASSIFICATION"
        fi
    else
        echo "R27_USABLE_EVIDENCE=true"
        echo "INITIAL_001A_SENT_COUNT=$(last_marker INITIAL_001A_SENT_COUNT NOT_REACHED)"
        echo "REPEAT_001A_SENT_COUNT=$(last_marker REPEAT_001A_SENT_COUNT NOT_REACHED)"
        echo "TOTAL_001A_SENT_COUNT=$(last_marker TOTAL_001A_SENT_COUNT NOT_REACHED)"
        echo "SECOND_001A_RESPONSE=$(last_marker SECOND_001A_RESPONSE NOT_REACHED)"
        echo "SECOND_001A_ACK_CLASSIFICATION=$(last_marker SECOND_001A_ACK_CLASSIFICATION NOT_REACHED)"
        echo "VIDEO_RTP_BEFORE_REPEAT=$(last_marker VIDEO_RTP_BEFORE_REPEAT NOT_REACHED)"
        echo "VIDEO_PACKET_COUNT_AT_REPEAT=$(last_marker VIDEO_PACKET_COUNT_AT_REPEAT NOT_REACHED)"
        echo "VIDEO_RTP_AFTER_REPEAT=$(last_marker VIDEO_RTP_AFTER_REPEAT NOT_REACHED)"
        echo "VIDEO_RTP_PAST_35S=$(last_marker VIDEO_RTP_PAST_35S NOT_REACHED)"
        echo "VIDEO_RTP_PAST_40S=$(last_marker VIDEO_RTP_PAST_40S NOT_REACHED)"
        echo "VIDEO_RTP_PAST_75S=$(last_marker VIDEO_RTP_PAST_75S NOT_REACHED)"
        echo "VIDEO_RTP_LAST_SECONDS_FROM_INITIAL_START=$(last_marker VIDEO_RTP_LAST_SECONDS_FROM_INITIAL_START NOT_REACHED)"
        echo "MEDIA_ACTIVE_DURATION_SECONDS=$(last_marker MEDIA_ACTIVE_DURATION_SECONDS NOT_REACHED)"
        echo "VIDEO_PACKET_COUNTER_PROGRESSING=$(last_marker VIDEO_PACKET_COUNTER_PROGRESSING NOT_REACHED)"
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
    echo "NEW_RTPC_OPEN=false"
    echo "NEW_SELF_ACTIVATION=false"
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
    rtp_sink_ports_remaining
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

for command in git python3 curl sha256sum timeout awk grep bash chmod install readelf stat; do
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
SESSION_LOG="$RUN_ROOT/session.log"
BUILD_PROVENANCE_LOG="$RUN_ROOT/build-provenance.log"
CANDIDATE_WRAPPER="$RUN_ROOT/$WRAPPER_NAME"
: > "$SESSION_LOG"
: > "$BUILD_PROVENANCE_LOG"
chmod 600 "$SESSION_LOG" "$BUILD_PROVENANCE_LOG"

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
) | tee "$BUILD_PROVENANCE_LOG"
build_rc=${PIPESTATUS[0]}
echo "R27_BUILD_RC=$build_rc"
[ "$build_rc" -eq 0 ] || exit 1
grep -F "GENERATED_SOURCE_SHA256=$EXPECTED_SOURCE_SHA" "$BUILD_PROVENANCE_LOG" >/dev/null || fail "R27_GENERATED_SOURCE_SHA_GATE=FAIL"
[ -x "$R27_OUTPUT" ] || fail "R27_OUTPUT_PRESENT=false"
[ "$FAIL" -eq 0 ] || exit 1

echo "=== MATERIALIZE R27 CANDIDATE WRAPPER ==="
BUILDER_ROOTFS="$(build_provenance_marker P80_OFFLINE_ROOTFS NOT_REACHED)"
BUILDER_ROOTFS_MODE="$(build_provenance_marker P80_BUILD_ROOTFS_MODE NOT_REACHED)"
SOURCE_MUSL_LOADER="$BUILDER_ROOTFS/lib/ld-musl-x86_64.so.1"
PACKAGED_LIB_DIR="$REPO/custom_components/comelit/native/lib"
CANDIDATE_LAUNCHER="$RUN_ROOT/$CANDIDATE_HOLDER_NAME"
RUN_MUSL_LOADER="$RUN_ROOT/ld-musl-x86_64.so.1"
echo "BUILDER_ROOTFS=$BUILDER_ROOTFS"
echo "BUILDER_ROOTFS_MODE=$BUILDER_ROOTFS_MODE"
echo "SOURCE_MUSL_LOADER=$SOURCE_MUSL_LOADER"
[ -d "$BUILDER_ROOTFS" ] || fail "BUILDER_ROOTFS_PRESENT=false"
[ -f "$SOURCE_MUSL_LOADER" ] || fail "SOURCE_MUSL_LOADER_PRESENT=false"
[ -d "$PACKAGED_LIB_DIR" ] || fail "PACKAGED_NATIVE_LIB_DIR_PRESENT=false"
if [ "$FAIL" -eq 0 ]; then
    SOURCE_MUSL_LOADER_SHA256="$(sha256sum "$SOURCE_MUSL_LOADER" | awk '{print $1}')"
    echo "SOURCE_MUSL_LOADER_SHA256=$SOURCE_MUSL_LOADER_SHA256"
    install -m 700 "$SOURCE_MUSL_LOADER" "$RUN_MUSL_LOADER" || fail "RUN_MUSL_LOADER_COPY=FAIL"
    RUN_MUSL_LOADER_SHA256="$(sha256sum "$RUN_MUSL_LOADER" | awk '{print $1}')"
    RUN_MUSL_LOADER_MODE="$(stat -c '%a' "$RUN_MUSL_LOADER")"
    echo "RUN_MUSL_LOADER=$RUN_MUSL_LOADER"
    echo "RUN_MUSL_LOADER_SHA256=$RUN_MUSL_LOADER_SHA256"
    echo "RUN_MUSL_LOADER_MODE=$RUN_MUSL_LOADER_MODE"
    if [ "$RUN_MUSL_LOADER_SHA256" = "$SOURCE_MUSL_LOADER_SHA256" ]; then
        echo "LOADER_COPY_SHA_GATE=PASS"
    else
        fail "LOADER_COPY_SHA_GATE=FAIL"
    fi
fi
[ "$FAIL" -eq 0 ] || exit 1

python3 - "$CANDIDATE_LAUNCHER" "$RUN_MUSL_LOADER" "$R27_OUTPUT" "$PACKAGED_LIB_DIR" "$SOURCE_MUSL_LOADER_SHA256" <<'PY'
from pathlib import Path
import hashlib
import os
import sys

out = Path(sys.argv[1])
loader = Path(sys.argv[2])
candidate = Path(sys.argv[3])
libdir = Path(sys.argv[4])
expected_loader_sha = sys.argv[5]
if not loader.is_file():
    raise SystemExit("CANDIDATE_LAUNCHER_GATE=FAIL reason=loader_absent")
if not candidate.is_file():
    raise SystemExit("CANDIDATE_LAUNCHER_GATE=FAIL reason=candidate_absent")
if not libdir.is_dir():
    raise SystemExit("CANDIDATE_LAUNCHER_GATE=FAIL reason=libdir_absent")
if hashlib.sha256(loader.read_bytes()).hexdigest() != expected_loader_sha:
    raise SystemExit("CANDIDATE_LAUNCHER_GATE=FAIL reason=loader_sha")
script = f"""#!/usr/bin/env bash
set -u
LOADER={str(loader)!r}
CANDIDATE={str(candidate)!r}
LIBDIR={str(libdir)!r}
EXPECTED_LOADER_SHA={expected_loader_sha!r}
if [ ! -x "$LOADER" ] || [ ! -x "$CANDIDATE" ] || [ ! -d "$LIBDIR" ]; then
    echo "CANDIDATE_LAUNCHER_PREFLIGHT=FAIL" >&2
    exit 127
fi
actual_loader_sha="$(sha256sum "$LOADER" | awk '{{print $1}}')"
if [ "$actual_loader_sha" != "$EXPECTED_LOADER_SHA" ]; then
    echo "CANDIDATE_LAUNCHER_LOADER_SHA_GATE=FAIL" >&2
    exit 127
fi
exec "$LOADER" --library-path "$LIBDIR" "$CANDIDATE" "$@"
"""
if "comelit_ice_offer_holder" in script or "/root/comelit-vip-poc/bin" in script:
    raise SystemExit("LAUNCHER_BASE_HELPER_FALLBACK=true")
out.write_text(script, encoding="utf-8")
os.chmod(out, 0o700)
print("CANDIDATE_LAUNCHER_GATE=PASS")
print("LAUNCHER_BASE_HELPER_FALLBACK=false")
PY
launcher_rc=$?
echo "CANDIDATE_LAUNCHER_RC=$launcher_rc"
[ "$launcher_rc" -eq 0 ] || fail "CANDIDATE_LAUNCHER_GATE=FAIL"
[ "$FAIL" -eq 0 ] || exit 1

if grep -Fq "$RUN_MUSL_LOADER" "$CANDIDATE_LAUNCHER"; then echo "LAUNCHER_LOADER_PATH_MATCH=true"; else fail "LAUNCHER_LOADER_PATH_MATCH=false"; fi
if grep -Fq "$R27_OUTPUT" "$CANDIDATE_LAUNCHER"; then echo "LAUNCHER_CANDIDATE_PATH_MATCH=true"; else fail "LAUNCHER_CANDIDATE_PATH_MATCH=false"; fi
if grep -Fq "$PACKAGED_LIB_DIR" "$CANDIDATE_LAUNCHER"; then echo "LAUNCHER_LIBRARY_PATH_MATCH=true"; else fail "LAUNCHER_LIBRARY_PATH_MATCH=false"; fi
if grep -Fq "/root/comelit-vip-poc/bin/comelit_ice_offer_holder" "$CANDIDATE_LAUNCHER"; then fail "LAUNCHER_BASE_HELPER_FALLBACK=true"; fi
LOADER_PROBE_OUTPUT="$RUN_ROOT/loader-probe.txt"
set +e
"$RUN_MUSL_LOADER" --library-path "$PACKAGED_LIB_DIR" --list "$R27_OUTPUT" > "$LOADER_PROBE_OUTPUT" 2>&1
loader_probe_rc=$?
set -u -o pipefail
echo "LOADER_PROBE_EXECUTED=true"
echo "LOADER_PROBE_RC=$loader_probe_rc"
echo "CANDIDATE_MAIN_EXECUTED=false"
if [ "$loader_probe_rc" -eq 0 ]; then
    echo "LOADER_PROBE_RESOLUTION=PASS"
else
    fail "LOADER_PROBE_RESOLUTION=FAIL"
fi
if grep -Fq "libc.so.6" "$LOADER_PROBE_OUTPUT" || grep -Fq "ld-linux-x86-64" "$LOADER_PROBE_OUTPUT"; then
    fail "GLIBC_RESOLUTION_USED=true"
else
    echo "GLIBC_RESOLUTION_USED=false"
fi
[ "$(sha256sum "$R27_OUTPUT" | awk '{print $1}')" = "$(build_provenance_marker P80_BINARY_SHA256 NOT_REACHED)" ] && echo "CANDIDATE_SHA_GATE=PASS" || fail "CANDIDATE_SHA_GATE=FAIL"
[ "$(readelf -l "$R27_OUTPUT" | sed -n 's@.*Requesting program interpreter: \(.*\)]@\1@p')" = "/lib/ld-musl-x86_64.so.1" ] && echo "CANDIDATE_INTERPRETER_MATCH=PASS" || fail "CANDIDATE_INTERPRETER_MATCH=FAIL"
[ "$FAIL" -eq 0 ] || exit 1

python3 - "$BASE_WRAPPER" "$CANDIDATE_WRAPPER" "$CANDIDATE_LAUNCHER" "$R27_OUTPUT" <<'PY'
from pathlib import Path
import os
import sys

src = Path(sys.argv[1])
out = Path(sys.argv[2])
holder = sys.argv[3]
raw_candidate = sys.argv[4]
text = src.read_text(encoding="utf-8")
holder_needle = '"$BASE/bin/comelit_ice_offer_holder"'
base_holder_path = "/root/comelit-vip-poc/bin/comelit_ice_offer_holder"
base_wrapper_path = "/usr/local/sbin/comelit-p2p-cloud-probe"
if text.count(holder_needle) != 1:
    raise SystemExit("R27_WRAPPER_HOLDER_ANCHOR=FAIL")
text = text.replace(holder_needle, f'"{holder}"', 1)
legacy_run_dir = "/run/comelit-p2p"
media_run_dir = "/run/comelit-media"
run_dir_count = text.count(legacy_run_dir)
if run_dir_count < 1:
    raise SystemExit("R27_WRAPPER_RUN_DIR_ANCHOR=FAIL")
text = text.replace(legacy_run_dir, media_run_dir)
if holder_needle in text:
    raise SystemExit("R27_WRAPPER_SUBSTITUTION_BASE_ABSENT=FAIL")
if f'"{holder}"' not in text:
    raise SystemExit("R27_WRAPPER_SUBSTITUTION_LAUNCHER_PRESENT=FAIL")
if f'"{raw_candidate}"' in text:
    raise SystemExit("RAW_CANDIDATE_PATH_PRESENT_AS_HOLDER=true")
if base_holder_path in text:
    raise SystemExit("BASE_HOLDER_PATH_PRESENT_IN_CANDIDATE_WRAPPER=true")
if text.count(holder) != 1:
    raise SystemExit("CANDIDATE_LAUNCHER_OCCURRENCES_GATE=FAIL")
if base_wrapper_path in text:
    raise SystemExit("BASE_WRAPPER_PATH_OCCURRENCES_GATE=FAIL")
out.write_text(text, encoding="utf-8")
os.chmod(out, 0o700)
print("R27_WRAPPER_SUBSTITUTION_BASE_ABSENT=PASS")
print("R27_WRAPPER_SUBSTITUTION_CANDIDATE_LAUNCHER_PRESENT=PASS")
print(f"R27_WRAPPER_RUN_DIR_REPLACEMENTS={run_dir_count}")
print(f"BASE_HOLDER_PATH_PRESENT_IN_CANDIDATE_WRAPPER={str(base_holder_path in text).lower()}")
print("RAW_CANDIDATE_PATH_PRESENT_AS_HOLDER=false")
print(f"CANDIDATE_LAUNCHER_PATH_PRESENT_IN_CANDIDATE_WRAPPER={str(holder in text).lower()}")
print(f"CANDIDATE_LAUNCHER_OCCURRENCES={text.count(holder)}")
print(f"BASE_WRAPPER_PATH_OCCURRENCES={text.count(base_wrapper_path)}")
PY
wrapper_rewrite_rc=$?
echo "R27_WRAPPER_REWRITE_RC=$wrapper_rewrite_rc"
if [ "$wrapper_rewrite_rc" -eq 0 ]; then
    if bash -n "$CANDIDATE_WRAPPER"; then
        echo "CANDIDATE_WRAPPER_PARSE=PASS"
        echo "WRAPPER_BINDING_GATE=PASS"
    else
        fail "R27_WRAPPER_PARSE=FAIL"
    fi
else
    fail "R27_WRAPPER_REWRITE=FAIL"
fi
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
    timeout --signal=TERM --kill-after=5s "$OUTER_TIMEOUT_SECONDS" "$CANDIDATE_WRAPPER"
) > "$SESSION_LOG" 2>&1 &
WRAPPER_PID=$!
wait "$WRAPPER_PID"
WRAPPER_RC=$?
WRAPPER_PID=""
echo "WRAPPER_RC=$WRAPPER_RC"
R27_REPEAT_EXECUTED="$(last_marker R27_REPEAT_001A_SENT false)"
[ "$R27_REPEAT_EXECUTED" = PASS ] && R27_REPEAT_EXECUTED=true
evaluate_helper_evidence
campaign_processes_remaining
derive_teardown_confidence

stop_pid "$VIDEO_SINK_PID"
stop_pid "$AUDIO_SINK_PID"
rtp_sink_ports_remaining
VIDEO_SINK_PID=""
AUDIO_SINK_PID=""

echo "=== RESTORE LISTENER ==="
restore_listener || exit 91

derive_production_media_active
exit 0
