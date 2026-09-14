#!/usr/bin/env bash
# CT120 research-only P116/R29C registered-CTPP mediareq26 LIVE runner.
#
# This artefact is the live-execution half of the R29C lane.  R29C/R29E prepare the
# 26-byte registered-CTPP mediareq26 OPEN/STOP builder and prove it OFFLINE (chroot
# self-check).  Nothing in the merged tree runs it; this runner is the bounded
# orchestrator that does, exactly once.
#
# Phases (both fail-closed):
#   R29C_PHASE=ARM  (default)
#       build the exact candidate, provenance gates, chroot self-check, holder-shim and
#       candidate-wrapper materialisation, RTP sink bind check, read-only production
#       listener preflight.  Never stops/starts the production listener, never performs
#       Comelit network TX.
#   R29C_PHASE=LIVE
#       the single authorised handoff:
#         production listener stop -> verify inactive -> research candidate bootstrap ->
#         exactly one inbound CALL_INIT -> exactly one registered-CTPP mediareq26 OPEN ->
#         <=10 s video RTP observation -> exactly one mediareq26 STOP -> listener survival
#         check -> research session close -> production listener restore.
#
# Authorisation: LIVE requires R29C_PHASE=LIVE *and* LIVE_RUN=YES *and*
# R29C_LIVE_AUTHORIZED=authorized.  The legacy R29_LIVE_RUN flag is read only so that it
# can be reported as ignored; on its own it never authorises anything.
set -u -o pipefail
umask 077

REPO=${REPO:-}
R29C_EXPECTED_COMMIT_SHA=${R29C_EXPECTED_COMMIT_SHA:-}
R29C_EXPECTED_GENERATED_SOURCE_SHA=${R29C_EXPECTED_GENERATED_SOURCE_SHA:-}
R29C_MAIN_SHA=${R29C_MAIN_SHA:-}
HA_WEBHOOK_URL=${HA_WEBHOOK_URL:-http://192.168.1.108:8123/api/webhook/comelit-ha-ring-test-control-v1}
BASE_WRAPPER=${BASE_WRAPPER:-/usr/local/sbin/comelit-p2p-cloud-probe}
BASE_WRAPPER_SHA256=a564535dff0cf10b1fe4766171f2960c52fb581f1c816cf81d2992c5c84e79c9
R29C_PHASE=${R29C_PHASE:-ARM}
LIVE_RUN=${LIVE_RUN:-NOT_RUN}
R29_LIVE_RUN=${R29_LIVE_RUN:-NO}
R29C_LIVE_AUTHORIZED=${R29C_LIVE_AUTHORIZED:-false}
ARTIFACT_ROOT=${ARTIFACT_ROOT:-/root/comelit-artifacts}

BUILDER_REL=safety-poc/research/media/v1/ct120_build_p80_haos_media_helper.sh
TRANSFORM_REL=safety-poc/research/media/v1/entrance_p116_r29c_registered_ctpp_mediareq26_probe_transform.py
RUNNER_REL=safety-poc/research/media/v1/ct120_run_p116_r29c_registered_ctpp_mediareq26_live.sh
CANDIDATE_NAME=comelit-r29c-registered-ctpp-mediareq26-probe
SHIM_NAME=p116_r29c_packaged_musl_holder_shim.sh
WRAPPER_NAME=comelit-p2p-cloud-probe-r29c

RUN_DIR=/run/comelit-media
STOP_FILE="$RUN_DIR/stop"
CANDIDATE_LOG="$RUN_DIR/ice-holder.log"
MEDIA_VIDEO_RTP_PORT=17899
MEDIA_AUDIO_RTP_PORT=17808

R29C_READY_MAX_SECONDS=${R29C_READY_MAX_SECONDS:-120}
R29C_RING_MAX_SECONDS=${R29C_RING_MAX_SECONDS:-90}
R29C_OPEN_MAX_SECONDS=${R29C_OPEN_MAX_SECONDS:-10}
R29C_RTP_OBSERVATION_SECONDS=${R29C_RTP_OBSERVATION_SECONDS:-10}
R29C_STOP_MAX_SECONDS=${R29C_STOP_MAX_SECONDS:-10}
R29C_POST_STOP_OBSERVATION_SECONDS=${R29C_POST_STOP_OBSERVATION_SECONDS:-10}
R29C_OUTER_TIMEOUT_SECONDS=${R29C_OUTER_TIMEOUT_SECONDS:-420}
R29C_RESTORE_POLLS=${R29C_RESTORE_POLLS:-12}

FAIL=0
RESULT=NOT_RUN
RESULT_CASE=NONE
RUN_ROOT=""
BUILD_PROVENANCE_LOG=""
SELFCHECK_LOG=""
WRAPPER_LOG=""
CANDIDATE_OUTPUT=""
CANDIDATE_SHA256=NOT_REACHED
CANDIDATE_WRAPPER=""
HOLDER_SHIM=""
HOLDER_SHIM_SHA256=NOT_REACHED
RUNTIME_ROOT=NONE
RUNTIME_LOADER=NONE
VIDEO_SINK_PID=""
AUDIO_SINK_PID=""
WRAPPER_PID=""
CANDIDATE_PID=""
WATCHDOG_PID=""

PRODUCTION_LISTENER_RUNNING_BEFORE=unknown
PRODUCTION_LISTENER_READY_BEFORE=unknown
PRODUCTION_LISTENER_RUNNING_AFTER=unknown
PRODUCTION_LISTENER_READY_AFTER=unknown
PRODUCTION_LISTENER_TOUCHED=false
PRODUCTION_LISTENER_INACTIVE=false
UPSTREAM_OWNERSHIP_RELEASED=false
PRODUCTION_RESTORE_RESULT=NOT_ATTEMPTED
HANDOFF_PATH_READY=false
RESTORE_PATH_READY=false
WATCHDOG_READY=false
LIVE_RUNNER_PREFLIGHT=NOT_RUN

LIVE_ATTEMPT_BUDGET_USED=0
RING_BUDGET_USED=0
OPEN_BUDGET_USED=0
STOP_BUDGET_USED=0

RESEARCH_LISTENER_READY=false
RESEARCH_LISTENER_PID_STABLE=UNKNOWN
REGISTRATION_GENERATION_STABLE=UNKNOWN
PSEUDOTCP_GENERATION_STABLE=UNKNOWN
CALL_INIT_OBSERVED=false
CALL_SOURCE=none
OPEN_SENT=false
STOP_SENT=false
LISTENER_SURVIVED_STOP=UNKNOWN
REGISTRATION_SURVIVED_STOP=UNKNOWN
PSEUDOTCP_SURVIVED_STOP=UNKNOWN
FINAL_RESEARCH_SESSION_CLEANUP=NOT_RUN

VIDEO_RTP_STARTED=false
VIDEO_RTP_PACKETS=NOT_REACHED
VIDEO_RTP_DATAGRAMS_SINK=NOT_REACHED
AUDIO_RTP_DATAGRAMS_SINK=NOT_REACHED
RTP_OBSERVATION_SECONDS=0
FIRST_RTP_RELATIVE_TO_CHANNEL_OPEN_RESPONSE=UNKNOWN
FIRST_RTP_EPOCH=NOT_OBSERVED
OPEN_OBSERVED_EPOCH=NOT_OBSERVED
OPEN_RESPONSE_OBSERVED_EPOCH=NOT_OBSERVED

READY_ICE_BOOTSTRAP_COUNT=UNKNOWN
READY_CLOUD_NEGOTIATION_COUNT=UNKNOWN
READY_PSEUDOTCP_OPEN_COUNT=UNKNOWN
READY_CTPP_REGISTRATION_COUNT=UNKNOWN
PREOPEN_ICE_BOOTSTRAP_COUNT=UNKNOWN
PREOPEN_CLOUD_NEGOTIATION_COUNT=UNKNOWN
PREOPEN_PSEUDOTCP_OPEN_COUNT=UNKNOWN
PREOPEN_CTPP_REGISTRATION_COUNT=UNKNOWN
AFTER_ICE_BOOTSTRAP_COUNT=UNKNOWN
AFTER_CLOUD_NEGOTIATION_COUNT=UNKNOWN
AFTER_PSEUDOTCP_OPEN_COUNT=UNKNOWN
AFTER_CTPP_REGISTRATION_COUNT=UNKNOWN

SELF_ACTIVATION_001A_SENT_COUNT=NOT_REACHED
R27_REPEAT_001A_SENT_COUNT=NOT_REACHED
DOOR_ACTIONS_SENT=NOT_REACHED
GATE_ACTIONS_SENT=NOT_REACHED
REFRESH_LOOP_STARTED_COUNT=NOT_REACHED
MEDIA_ONLY_STOP_RESULT=NOT_REACHED
CANDIDATE_MEDIA_ONLY_STOP_RESULT=NOT_REACHED
CANDIDATE_FINAL_RESEARCH_SESSION_CLEANUP=NOT_REACHED
CANDIDATE_LISTENER_READY_AFTER_MEDIA=NOT_REACHED

PREP_READY=false
USER_READY_RECEIVED=false
RESTORE_ATTEMPTED=false
CLEANUP_DONE=false
EARLY_RESULT=""

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
    [ -f "$file" ] || return 1
    [ "$(json_scalar "$file" ok)" = true ] &&
    [ "$(json_scalar "$file" supervisor_running)" = true ] &&
    [ "$(json_scalar "$file" running)" = true ] &&
    [ "$(json_scalar "$file" listener_ready)" = true ] &&
    [ "$(json_scalar "$file" last_error)" = null ]
}

status_inactive() {
    local file="$1"
    [ -f "$file" ] || return 1
    [ "$(json_scalar "$file" ok)" = true ] &&
    [ "$(json_scalar "$file" running)" = false ] &&
    [ "$(json_scalar "$file" listener_ready)" = false ]
}

# Reads the last occurrence of KEY= from the wrapper log and then the candidate log, so
# the candidate (the live source of truth) always wins over an earlier wrapper dump.
last_marker() {
    local key="$1"
    local fallback="$2"
    local files=()
    [ -n "$WRAPPER_LOG" ] && [ -f "$WRAPPER_LOG" ] && files+=("$WRAPPER_LOG")
    [ -f "$CANDIDATE_LOG" ] && files+=("$CANDIDATE_LOG")
    if [ "${#files[@]}" -eq 0 ]; then
        printf '%s\n' "$fallback"
        return 0
    fi
    awk -v key="$key" -v fallback="$fallback" '
        index($0, key "=") == 1 { value = substr($0, length(key) + 2); found = 1 }
        END { if (found) print value; else print fallback }
    ' "${files[@]}"
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

wait_for_marker() {
    local key="$1"
    local value="$2"
    local timeout_seconds="$3"
    local poll
    local iterations
    iterations="$(python3 - "$timeout_seconds" <<'PY'
import sys
import math
print(max(1, math.ceil(float(sys.argv[1]) * 2)))
PY
)"
    for poll in $(seq 1 "$iterations"); do
        if [ "$(last_marker "$key" "")" = "$value" ]; then
            return 0
        fi
        sleep 0.5
    done
    return 1
}

marker_present() {
    local key="$1"
    local files=()
    [ -n "$WRAPPER_LOG" ] && [ -f "$WRAPPER_LOG" ] && files+=("$WRAPPER_LOG")
    [ -f "$CANDIDATE_LOG" ] && files+=("$CANDIDATE_LOG")
    [ "${#files[@]}" -gt 0 ] || return 1
    grep -h -q -e "$key" "${files[@]}"
}

# Ring watchdog.  Accepts only the first inbound CALL_INIT observed after the research
# listener reported READY, and bails out early when the candidate reports that the call
# came from a non-entrance source.  It never retries the ring.
wait_for_call_init() {
    local timeout_seconds="$1"
    local iterations poll
    iterations="$(python3 - "$timeout_seconds" <<'PY'
import sys
import math
print(max(1, math.ceil(float(sys.argv[1]) * 2)))
PY
)"
    for poll in $(seq 1 "$iterations"); do
        if [ "$(last_marker CALL_TRANSACTION_CREATED "")" = true ]; then
            return 0
        fi
        if marker_present 'R29_UNKNOWN_OR_GATE_SOURCE_REJECTED=true'; then
            return 1
        fi
        sleep 0.5
    done
    return 1
}

# Proves the auto-restore watchdog handler itself works, without leaving it armed during
# preparation: arm it, confirm it logged AUTO_RESTORE_ARMED, then disarm it.
validate_watchdog_arm_disarm() {
    arm_autorestore_watchdog
    if [ "$WATCHDOG_READY" = true ]; then
        kill -TERM "$WATCHDOG_PID" 2>/dev/null || true
        sleep 1
        stop_pid "$WATCHDOG_PID"
        if kill -0 "$WATCHDOG_PID" 2>/dev/null; then
            WATCHDOG_DISARMED=false
            WATCHDOG_READY=false
        else
            WATCHDOG_DISARMED=true
        fi
    else
        WATCHDOG_DISARMED=NOT_ARMED
    fi
    echo "WATCHDOG_DISARMED=$WATCHDOG_DISARMED"
    echo "WATCHDOG_VALIDATION=ARM_OBSERVE_LOG_DISARM"
}

select_runtime_root() {
    local rootfs
    rootfs="$(build_marker P80_OFFLINE_ROOTFS "")"
    if [ -n "$rootfs" ] && [ -x "$rootfs/lib/ld-musl-x86_64.so.1" ] && [ -r "$rootfs/etc/alpine-release" ]; then
        printf '%s\n' "$rootfs"
        return 0
    fi
    find /root -maxdepth 2 -path '/root/comelit-p80-haos-build-*/rootfs' -type d \
        -exec test -x '{}/lib/ld-musl-x86_64.so.1' ';' \
        -exec test -r '{}/etc/alpine-release' ';' \
        -printf '%T@ %p\n' 2>/dev/null |
    sort -nr |
    awk 'NR == 1 {print $2}'
}

run_candidate_selfcheck_in_chroot() {
    local rootfs selfcheck_dir rootfs_candidate
    rootfs="$(select_runtime_root)"
    [ -n "$rootfs" ] || fail "R29C_SELFCHECK_ROOTFS=ABSENT"
    [ -x "$rootfs/usr/bin/gcc" ] || fail "R29C_SELFCHECK_ROOTFS_GCC=FAIL"
    [ -e "$rootfs/lib/ld-musl-x86_64.so.1" ] || fail "R29C_SELFCHECK_ROOTFS_MUSL_LOADER=FAIL"
    [ "$FAIL" -eq 0 ] || return 1
    echo "R29C_SELFCHECK_ROOTFS=$rootfs"
    selfcheck_dir="$rootfs/r29c-selfcheck"
    rm -rf "$selfcheck_dir"
    install -d -m 700 "$selfcheck_dir"
    rootfs_candidate="$selfcheck_dir/$CANDIDATE_NAME"
    install -m 700 "$CANDIDATE_OUTPUT" "$rootfs_candidate"
    chroot "$rootfs" "/r29c-selfcheck/$CANDIDATE_NAME" --r29-selfcheck > "$SELFCHECK_LOG" 2>&1
    echo "R29C_SELFCHECK_RC=$?"
}

prepare_holder_shim() {
    HOLDER_SHIM="$RUN_ROOT/$SHIM_NAME"
    python3 - "$HOLDER_SHIM" <<'PY'
from pathlib import Path
import os
import sys

out = Path(sys.argv[1])
template = r'''#!/usr/bin/env bash
set -u -o pipefail
umask 077
CANDIDATE="${R29C_CANDIDATE_PATH:?R29C_CANDIDATE_PATH}"
R29C_CANDIDATE_SHA256="${R29C_EXPECTED_CANDIDATE_SHA256:?R29C_EXPECTED_CANDIDATE_SHA256}"
RUNTIME_ROOT="${R29C_RUNTIME_ROOT:?R29C_RUNTIME_ROOT}"
RUNTIME_LOADER="$RUNTIME_ROOT/lib/ld-musl-x86_64.so.1"
RUNTIME_LIBRARY_PATH="$RUNTIME_ROOT/lib:$RUNTIME_ROOT/usr/lib"
die() { echo "$1"; exit 126; }
[ -f "$CANDIDATE" ] || die "R29C_SHIM_CANDIDATE_PRESENT=false"
[ -x "$RUNTIME_LOADER" ] || die "R29C_SHIM_MUSL_LOADER_PRESENT=false"
[ -r "$RUNTIME_ROOT/etc/alpine-release" ] || die "R29C_SHIM_ALPINE_RUNTIME_PRESENT=false"
[ -r "$RUNTIME_ROOT/usr/lib/libnice.so.10" ] || die "R29C_SHIM_LIBNICE_PRESENT=false"
actual_sha="$(sha256sum "$CANDIDATE" | awk '{print $1}')"
echo "R29C_SHIM_CANDIDATE_SHA_BEFORE_EXEC=$actual_sha"
[ "$actual_sha" = "$R29C_CANDIDATE_SHA256" ] || die "R29C_SHIM_CANDIDATE_SHA_GATE=FAIL"
echo "R29C_SHIM_MUSL_EXEC_GATE=PASS"
exec "$RUNTIME_LOADER" --library-path "$RUNTIME_LIBRARY_PATH" "$CANDIDATE"
'''
out.write_text(template, encoding="utf-8")
os.chmod(out, 0o700)
PY
    [ -x "$HOLDER_SHIM" ] || fail "R29C_HOLDER_SHIM_WRITE=FAIL"
    bash -n "$HOLDER_SHIM" || fail "R29C_HOLDER_SHIM_PARSE_GATE=FAIL"
    HOLDER_SHIM_SHA256="$(sha256sum "$HOLDER_SHIM" | awk '{print $1}')"
}

prepare_candidate_wrapper() {
    CANDIDATE_WRAPPER="$RUN_ROOT/$WRAPPER_NAME"
    python3 - "$BASE_WRAPPER" "$CANDIDATE_WRAPPER" "$HOLDER_SHIM" <<'PY'
from pathlib import Path
import os
import sys
src = Path(sys.argv[1])
out = Path(sys.argv[2])
holder = sys.argv[3]
text = src.read_text(encoding="utf-8")
needle = '"$BASE/bin/comelit_ice_offer_holder"'
if text.count(needle) != 1:
    raise SystemExit("R29C_WRAPPER_HOLDER_ANCHOR=FAIL")
text = text.replace(needle, f'"{holder}"', 1)
legacy_run_dir = "/run/comelit-p2p"
if legacy_run_dir not in text:
    raise SystemExit("R29C_WRAPPER_RUN_DIR_ANCHOR=FAIL")
text = text.replace(legacy_run_dir, "/run/comelit-media")
if needle in text:
    raise SystemExit("R29C_WRAPPER_SUBSTITUTION_BASE_ABSENT=FAIL")
out.write_text(text, encoding="utf-8")
os.chmod(out, 0o700)
print("R29C_WRAPPER_SUBSTITUTION_BASE_ABSENT=PASS")
print("R29C_WRAPPER_SUBSTITUTION_SHIM_PRESENT=PASS")
PY
    [ -x "$CANDIDATE_WRAPPER" ] || fail "R29C_WRAPPER_WRITE=FAIL"
    bash -n "$CANDIDATE_WRAPPER" || fail "R29C_WRAPPER_PARSE_GATE=FAIL"
}

start_udp_sink() {
    local port="$1"
    local count_file="$2"
    local first_file="$3"
    local label="$4"
    python3 - "$port" "$count_file" "$first_file" "$R29C_OUTER_TIMEOUT_SECONDS" <<'PY' &
from pathlib import Path
import signal
import socket
import sys
import time

port = int(sys.argv[1])
count_file = Path(sys.argv[2])
first_file = Path(sys.argv[3])
deadline = time.monotonic() + int(sys.argv[4])

stop = False


def handle(_signum, _frame):
    global stop
    stop = True


signal.signal(signal.SIGTERM, handle)
signal.signal(signal.SIGINT, handle)
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
    if count == 1:
        first_file.write_text(f"{time.time():.3f}\n", encoding="utf-8")
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

sink_bound() {
    local port="$1"
    ss -lun 2>/dev/null | grep -q "127.0.0.1:$port "
}

find_candidate_pid() {
    local pids
    pids="$(pgrep -f "$CANDIDATE_OUTPUT" 2>/dev/null | grep -v -e "^$$\$" -e "^$PPID\$" || true)"
    printf '%s\n' "$(printf '%s\n' "$pids" | awk 'NF {print; exit}')"
}

arm_autorestore_watchdog() {
    local watchdog="$RUN_ROOT/r29c-autorestore-watchdog.sh"
    local log="$RUN_ROOT/r29c-autorestore-watchdog.log"
    python3 - "$watchdog" <<'PY'
from pathlib import Path
import os
import sys

out = Path(sys.argv[1])
text = r'''#!/usr/bin/env bash
set -u -o pipefail
umask 077
URL="${R29C_WATCHDOG_URL:?R29C_WATCHDOG_URL}"
LOG="${R29C_WATCHDOG_LOG:?R29C_WATCHDOG_LOG}"
BUDGET=600
INTERVAL=30
log() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1" >> "$LOG"; }
log "AUTO_RESTORE_ARMED"
deadline=$(( $(date +%s) + BUDGET ))
while [ "$(date +%s)" -lt "$deadline" ]; do
    status="$LOG.status.json"
    curl --silent --show-error --connect-timeout 5 --max-time 10 \
      --header 'Content-Type: application/json' --output "$status" \
      --data '{"action":"status"}' "$URL" >/dev/null 2>&1 || true
    if grep -q '"listener_ready": *true' "$status" 2>/dev/null; then
        log "AUTO_RESTORE_SKIPPED_ALREADY_RUNNING"
        exit 0
    fi
    sleep "$INTERVAL"
done
curl --silent --show-error --connect-timeout 5 --max-time 35 \
  --header 'Content-Type: application/json' --output "$LOG.start.json" \
  --data '{"action":"start"}' "$URL" >/dev/null 2>&1 || true
log "AUTO_RESTORE_START_SENT"
'''
out.write_text(text, encoding="utf-8")
os.chmod(out, 0o700)
PY
    bash -n "$watchdog" || return 1
    : > "$log"
    chmod 600 "$log"
    R29C_WATCHDOG_URL="$HA_WEBHOOK_URL" R29C_WATCHDOG_LOG="$log" setsid "$watchdog" >/dev/null 2>&1 < /dev/null &
    WATCHDOG_PID=$!
    sleep 1
    if kill -0 "$WATCHDOG_PID" 2>/dev/null && grep -q 'AUTO_RESTORE_ARMED' "$log" 2>/dev/null; then
        WATCHDOG_READY=true
        echo "WATCHDOG_ARMED=true"
    else
        WATCHDOG_READY=false
        echo "WATCHDOG_ARMED=false"
    fi
}

read_sink_count() {
    local file="$1"
    local fallback="$2"
    if [ -f "$file" ]; then
        awk 'NR == 1 {print; found = 1} END { if (!found) print "" }' "$file"
    else
        printf '%s\n' "$fallback"
    fi
}

read_sink_first() {
    local file="$1"
    if [ -f "$file" ]; then
        head -n 1 "$file"
    else
        printf '%s\n' NOT_OBSERVED
    fi
}

snapshot_counters() {
    local prefix="$1"
    local ice cloud tcp ctpp
    ice="$(last_marker ICE_BOOTSTRAP_COUNT UNKNOWN)"
    cloud="$(last_marker CLOUD_NEGOTIATION_COUNT UNKNOWN)"
    tcp="$(last_marker PSEUDOTCP_OPEN_COUNT UNKNOWN)"
    ctpp="$(last_marker CTPP_REGISTRATION_COUNT UNKNOWN)"
    eval "${prefix}_ICE_BOOTSTRAP_COUNT=\"\$ice\""
    eval "${prefix}_CLOUD_NEGOTIATION_COUNT=\"\$cloud\""
    eval "${prefix}_PSEUDOTCP_OPEN_COUNT=\"\$tcp\""
    eval "${prefix}_CTPP_REGISTRATION_COUNT=\"\$ctpp\""
    echo "${prefix}_COUNTER_SNAPSHOT=ICE:$ice,CLOUD:$cloud,PSEUDOTCP:$tcp,CTPP:$ctpp"
}

restore_listener() {
    [ "$UPSTREAM_OWNERSHIP_RELEASED" = true ] || return 0
    [ "$RESTORE_ATTEMPTED" = false ] || return 0
    RESTORE_ATTEMPTED=true
    local attempt start_file status_file poll
    for attempt in 1 2; do
        echo "LISTENER_RESTORE_ATTEMPT=$attempt"
        start_file="$RUN_ROOT/listener-start-${attempt}.json"
        post_control start "$start_file" 40 || true
        for poll in $(seq 1 "$R29C_RESTORE_POLLS"); do
            status_file="$RUN_ROOT/listener-restore-${attempt}-${poll}.json"
            post_control status "$status_file" 10 || true
            if status_ready "$status_file"; then
                PRODUCTION_LISTENER_RUNNING_AFTER=true
                PRODUCTION_LISTENER_READY_AFTER=true
                PRODUCTION_RESTORE_RESULT=PASS
                echo "PRODUCTION_RESTORE_RESULT=PASS"
                return 0
            fi
            sleep 5
        done
    done
    PRODUCTION_RESTORE_RESULT=FAIL
    echo "PRODUCTION_RESTORE_RESULT=FAIL"
    return 91
}

close_research_session() {
    local poll
    [ "$CLEANUP_DONE" = false ] || return 0
    CLEANUP_DONE=true
    stop_pid "$VIDEO_SINK_PID"
    stop_pid "$AUDIO_SINK_PID"
    if [ -n "$WRAPPER_PID" ] && kill -0 "$WRAPPER_PID" 2>/dev/null; then
        install -d -m 700 "$RUN_DIR" || true
        : > "$STOP_FILE" || true
        chmod 600 "$STOP_FILE" || true
        for poll in $(seq 1 20); do
            kill -0 "$WRAPPER_PID" 2>/dev/null || break
            sleep 0.5
        done
    fi
    stop_pid "$WRAPPER_PID"
    stop_pid "$CANDIDATE_PID"
    sleep 2
    local residual
    residual="$(find_candidate_pid)"
    if [ -z "$residual" ] && ! pgrep -f "$HOLDER_SHIM" >/dev/null 2>&1; then
        FINAL_RESEARCH_SESSION_CLEANUP=PASS
    else
        FINAL_RESEARCH_SESSION_CLEANUP=FAIL
    fi
    echo "FINAL_RESEARCH_SESSION_CLEANUP=$FINAL_RESEARCH_SESSION_CLEANUP"
    kill -TERM "$WATCHDOG_PID" 2>/dev/null || true
}

classify() {
    if [ -n "$EARLY_RESULT" ]; then
        echo "RESULT_CASE=$RESULT_CASE"
        return 0
    fi
    if [ "$OPEN_SENT" = true ] && [ "$STOP_SENT" != true ]; then
        RESULT_CASE=D
    elif [ "$OPEN_SENT" != true ]; then
        RESULT_CASE=E
    elif [ "$VIDEO_RTP_STARTED" != true ]; then
        RESULT_CASE=A
    elif [ "$LISTENER_SURVIVED_STOP" = true ]; then
        RESULT_CASE=B
    elif [ "$LISTENER_SURVIVED_STOP" = false ]; then
        RESULT_CASE=C
    else
        RESULT_CASE=F
    fi
    case "$RESULT_CASE" in
        A) RESULT=REGISTERED_CTPP_MEDIAREQ26_NOT_PROVEN ;;
        B) RESULT=REGISTERED_CTPP_MEDIAREQ26_OPEN_STOP_LIVE_SUPPORTED ;;
        C) RESULT=REGISTERED_CTPP_MEDIAREQ26_OPEN_SUPPORTED_STOP_BREAKS_LISTENER ;;
        D) RESULT=INCONCLUSIVE_CLEANUP_FAILURE ;;
        E) RESULT=INCONCLUSIVE_OPEN_NOT_SENT ;;
        *) RESULT=INCONCLUSIVE_RUNTIME_FAILURE ;;
    esac
    echo "RESULT_CASE=$RESULT_CASE"
}

# Records an outcome that ends the live attempt before the OPEN/STOP classification can
# be applied (missing call init, wrong source, bootstrap failure).  classify() must not
# overwrite it.
set_result() {
    RESULT_CASE="$1"
    RESULT="$2"
    EARLY_RESULT="$2"
    echo "RESULT_CASE=$RESULT_CASE"
    echo "RESULT=$RESULT"
}

costs_block() {
    echo "R29_LIVE_RUN_IGNORED=$R29_LIVE_RUN"
    echo "R29C_LIVE_AUTHORIZED=$R29C_LIVE_AUTHORIZED"
    echo "LIVE_ATTEMPT_BUDGET_USED=$LIVE_ATTEMPT_BUDGET_USED"
    echo "RING_BUDGET_USED=$RING_BUDGET_USED"
    echo "OPEN_BUDGET_USED=$OPEN_BUDGET_USED"
    echo "STOP_BUDGET_USED=$STOP_BUDGET_USED"
    echo "SELF_ACTIVATION_001A_SENT_COUNT=$SELF_ACTIVATION_001A_SENT_COUNT"
    echo "R27_REPEAT_001A_SENT_COUNT=$R27_REPEAT_001A_SENT_COUNT"
    echo "DOOR_ACTIONS_SENT=$DOOR_ACTIONS_SENT"
    echo "GATE_ACTIONS_SENT=$GATE_ACTIONS_SENT"
    echo "REFRESH_LOOP_STARTED_COUNT=$REFRESH_LOOP_STARTED_COUNT"
    echo "HA_DEPLOY_COUNT=0"
    echo "HA_RESTART_COUNT=0"
    echo "HA_RELOAD_COUNT=0"
}

print_arm_block() {
    echo "=== COMELIT P116 R29C LIVE RUNNER ARM REPORT ==="
    echo "R29C_PHASE=$R29C_PHASE"
    echo "R29C_REPO_HEAD=$(build_marker P80_BUILD_REPO_HEAD NOT_REACHED)"
    echo "GENERATED_SOURCE_SHA256=$(build_marker GENERATED_SOURCE_SHA256 NOT_REACHED)"
    echo "CANDIDATE_BINARY_SHA256=$CANDIDATE_SHA256"
    echo "HOLDER_SHIM_SHA256=$HOLDER_SHIM_SHA256"
    echo "RUNTIME_ROOT=REDACTED"
    echo "PREP_READY=$PREP_READY"
    echo "LIVE_RUNNER_PREFLIGHT=$LIVE_RUNNER_PREFLIGHT"
    echo "HANDOFF_PATH_READY=$HANDOFF_PATH_READY"
    echo "RESTORE_PATH_READY=$RESTORE_PATH_READY"
    echo "WATCHDOG_READY=$WATCHDOG_READY"
    echo "PRODUCTION_LISTENER_RUNNING_BEFORE=$PRODUCTION_LISTENER_RUNNING_BEFORE"
    echo "PRODUCTION_LISTENER_READY_BEFORE=$PRODUCTION_LISTENER_READY_BEFORE"
    echo "PRODUCTION_LISTENER_RUNNING=$PRODUCTION_LISTENER_RUNNING_BEFORE"
    echo "PRODUCTION_LISTENER_READY=$PRODUCTION_LISTENER_READY_BEFORE"
    echo "PRODUCTION_LISTENER_TOUCHED=$PRODUCTION_LISTENER_TOUCHED"
    echo "LIVE_RUN=NOT_RUN"
    costs_block
    echo "=== END COMELIT P116 R29C LIVE RUNNER ARM REPORT ==="
}

print_final_block() {
    classify
    echo "=== COMELIT P116 R29C REGISTERED CTPP MEDIAREQ26 LIVE RESULT ==="
    echo "R29C_PHASE=$R29C_PHASE"
    echo "MAIN_SHA=$R29C_MAIN_SHA"
    echo "CANDIDATE_SOURCE_SHA256=$(build_marker GENERATED_SOURCE_SHA256 NOT_REACHED)"
    echo "CANDIDATE_BINARY_SHA256=$CANDIDATE_SHA256"
    echo "HOLDER_SHIM_SHA256=$HOLDER_SHIM_SHA256"
    echo "PREP_READY=$PREP_READY"
    echo "USER_READY_RECEIVED=$USER_READY_RECEIVED"
    echo "PRODUCTION_HANDOFF=$UPSTREAM_OWNERSHIP_RELEASED"
    echo "PRODUCTION_LISTENER_INACTIVE=$PRODUCTION_LISTENER_INACTIVE"
    echo "UPSTREAM_OWNERSHIP_RELEASED=$UPSTREAM_OWNERSHIP_RELEASED"
    echo "RESEARCH_LISTENER_READY=$RESEARCH_LISTENER_READY"
    echo "RESEARCH_LISTENER_PID_STABLE=$RESEARCH_LISTENER_PID_STABLE"
    echo "REGISTRATION_GENERATION_STABLE=$REGISTRATION_GENERATION_STABLE"
    echo "PSEUDOTCP_GENERATION_STABLE=$PSEUDOTCP_GENERATION_STABLE"
    echo "CALL_INIT_OBSERVED=$CALL_INIT_OBSERVED"
    echo "CALL_SOURCE=$CALL_SOURCE"
    echo "RING_BUDGET_USED=$RING_BUDGET_USED"
    echo "REGISTERED_CTPP_MEDIAREQ26_HYPOTHESIS=true"
    echo "OPEN_SENT=$OPEN_SENT"
    echo "OPEN_BUDGET_USED=$OPEN_BUDGET_USED"
    echo "VIDEO_RTP_STARTED=$VIDEO_RTP_STARTED"
    echo "VIDEO_RTP_PACKETS=$VIDEO_RTP_PACKETS"
    echo "VIDEO_RTP_DATAGRAMS_SINK=$VIDEO_RTP_DATAGRAMS_SINK"
    echo "AUDIO_RTP_DATAGRAMS_SINK=$AUDIO_RTP_DATAGRAMS_SINK"
    echo "RTP_OBSERVATION_SECONDS=$RTP_OBSERVATION_SECONDS"
    echo "FIRST_RTP_RELATIVE_TO_CHANNEL_OPEN_RESPONSE=$FIRST_RTP_RELATIVE_TO_CHANNEL_OPEN_RESPONSE"
    echo "STOP_SENT=$STOP_SENT"
    echo "STOP_BUDGET_USED=$STOP_BUDGET_USED"
    echo "LISTENER_SURVIVED_STOP=$LISTENER_SURVIVED_STOP"
    echo "REGISTRATION_SURVIVED_STOP=$REGISTRATION_SURVIVED_STOP"
    echo "PSEUDOTCP_SURVIVED_STOP=$PSEUDOTCP_SURVIVED_STOP"
    echo "NEW_ICE_AFTER_READY_COUNT=$(compute_delta "$READY_ICE_BOOTSTRAP_COUNT" "$AFTER_ICE_BOOTSTRAP_COUNT")"
    echo "NEW_CLOUD_AFTER_READY_COUNT=$(compute_delta "$READY_CLOUD_NEGOTIATION_COUNT" "$AFTER_CLOUD_NEGOTIATION_COUNT")"
    echo "NEW_PSEUDOTCP_AFTER_READY_COUNT=$(compute_delta "$READY_PSEUDOTCP_OPEN_COUNT" "$AFTER_PSEUDOTCP_OPEN_COUNT")"
    echo "NEW_REGISTRATION_AFTER_READY_COUNT=$(compute_delta "$READY_CTPP_REGISTRATION_COUNT" "$AFTER_CTPP_REGISTRATION_COUNT")"
    echo "MEDIA_ONLY_STOP_RESULT=$MEDIA_ONLY_STOP_RESULT"
    echo "FINAL_RESEARCH_SESSION_CLEANUP=$FINAL_RESEARCH_SESSION_CLEANUP"
    echo "PRODUCTION_RESTORE_RESULT=$PRODUCTION_RESTORE_RESULT"
    echo "PRODUCTION_LISTENER_RUNNING_AFTER=$PRODUCTION_LISTENER_RUNNING_AFTER"
    echo "PRODUCTION_LISTENER_READY_AFTER=$PRODUCTION_LISTENER_READY_AFTER"
    echo "PRODUCTION_LISTENER_RUNNING=$PRODUCTION_LISTENER_RUNNING_AFTER"
    echo "PRODUCTION_LISTENER_READY=$PRODUCTION_LISTENER_READY_AFTER"
    costs_block
    echo "LIVE_ATTEMPT_BUDGET_USED=$LIVE_ATTEMPT_BUDGET_USED"
    echo "RESULT=$RESULT"
    echo "R29_MEDIA_OPEN_MODEL=$(last_marker R29_MEDIA_OPEN_MODEL NOT_REACHED)"
    echo "R29_MEDIA_ONLY_TEARDOWN_MODEL=$(last_marker R29_MEDIA_ONLY_TEARDOWN_MODEL NOT_REACHED)"
    echo "=== END COMELIT P116 R29C REGISTERED CTPP MEDIAREQ26 LIVE RESULT ==="
}

on_exit() {
    local rc=$?
    if [ "$R29C_PHASE" = LIVE ] && [ "$LIVE_ATTEMPT_BUDGET_USED" -eq 1 ]; then
        close_research_session || true
        restore_listener || rc=91
    else
        stop_pid "$VIDEO_SINK_PID"
        stop_pid "$AUDIO_SINK_PID"
        stop_pid "$WATCHDOG_PID"
    fi
    if [ "$R29C_PHASE" = LIVE ]; then
        print_final_block
    else
        print_arm_block
    fi
    exit "$rc"
}

preflight_gates() {
    [ "${EUID}" -eq 0 ] || fail "R29C_ROOT_GATE=FAIL"
    for command in git python3 curl sha256sum timeout awk grep sed bash chmod install cmp chroot find sort rm ss pgrep wc; do
        command -v "$command" >/dev/null 2>&1 || fail "R29C_MISSING_COMMAND=$command"
    done
    [ -n "$REPO" ] || fail "R29C_REPO_REQUIRED=true"
    [ -n "$R29C_EXPECTED_COMMIT_SHA" ] || fail "R29C_EXPECTED_COMMIT_SHA_REQUIRED=true"
    [ -n "$R29C_EXPECTED_GENERATED_SOURCE_SHA" ] || fail "R29C_EXPECTED_GENERATED_SOURCE_SHA_REQUIRED=true"
    [ -d "$REPO/.git" ] || fail "R29C_REPO_PRESENT=false"
    [ -x "$BASE_WRAPPER" ] || fail "R29C_BASE_WRAPPER_PRESENT=false"
    [ "$FAIL" -eq 0 ] || return 1

    local actual_wrapper_sha
    actual_wrapper_sha="$(sha256sum "$BASE_WRAPPER" | awk '{print $1}')"
    echo "BASE_WRAPPER_SHA256=$actual_wrapper_sha"
    [ "$actual_wrapper_sha" = "$BASE_WRAPPER_SHA256" ] || fail "R29C_BASE_WRAPPER_SHA_GATE=FAIL"

    local repo_head
    repo_head="$(git -C "$REPO" rev-parse HEAD 2>/dev/null || true)"
    echo "R29C_REPO_HEAD=$repo_head"
    [ "$repo_head" = "$R29C_EXPECTED_COMMIT_SHA" ] || fail "R29C_EXPECTED_COMMIT_SHA_GATE=FAIL"
    [ -z "$(git -C "$REPO" status --porcelain)" ] || fail "R29C_WORKTREE_CLEAN=FAIL"

    git -C "$REPO" show "$R29C_EXPECTED_COMMIT_SHA:$TRANSFORM_REL" > "$RUN_ROOT/transform.py" || fail "R29C_TRANSFORM_BLOB=FAIL"
    git -C "$REPO" show "$R29C_EXPECTED_COMMIT_SHA:$RUNNER_REL" > "$RUN_ROOT/runner.sh" || fail "R29C_RUNNER_BLOB=FAIL"
    git -C "$REPO" show "$R29C_EXPECTED_COMMIT_SHA:$BUILDER_REL" > "$RUN_ROOT/builder.sh" || fail "R29C_BUILDER_BLOB=FAIL"
    bash -n "$RUN_ROOT/runner.sh" || fail "R29C_RUNNER_BASH_N=FAIL"
    bash -n "$RUN_ROOT/builder.sh" || fail "R29C_BUILDER_BASH_N=FAIL"
    cmp -s "$RUN_ROOT/transform.py" "$REPO/$TRANSFORM_REL" || fail "R29C_TRANSFORM_WORKTREE_BLOB_GATE=FAIL"
    cmp -s "$RUN_ROOT/runner.sh" "$REPO/$RUNNER_REL" || fail "R29C_RUNNER_WORKTREE_BLOB_GATE=FAIL"
    cmp -s "$RUN_ROOT/builder.sh" "$REPO/$BUILDER_REL" || fail "R29C_BUILDER_WORKTREE_BLOB_GATE=FAIL"

    if [ -n "$R29C_MAIN_SHA" ]; then
        local changed
        changed="$(git -C "$REPO" diff --name-only "$R29C_MAIN_SHA" "$R29C_EXPECTED_COMMIT_SHA" | sort)"
        echo "R29C_MAIN_LINEAGE_DIFF_FILES=$(printf '%s' "$changed" | tr '\n' ',')"
        local unexpected
        unexpected="$(printf '%s\n' "$changed" | grep -v -e "^$RUNNER_REL$" -e '^safety-poc/tests/test_p116_r29c_registered_ctpp_mediareq26_live_contract.py$' | grep -v '^$' || true)"
        if [ -n "$unexpected" ]; then
            fail "R29C_MAIN_LINEAGE_GATE=FAIL"
        else
            echo "R29C_MAIN_LINEAGE_GATE=PASS"
        fi
    fi
    [ "$FAIL" -eq 0 ] || return 1
    echo "R29C_PREFLIGHT=PASS"
}

build_candidate() {
    (
        REPO="$REPO" \
        P80_BUILD_ALLOW_DETACHED=1 \
        P80_BUILD_EXPECTED_SHA="$R29C_EXPECTED_COMMIT_SHA" \
        P80_BUILD_INCLUDE_P116=1 \
        P80_BUILD_TRANSFORM="$TRANSFORM_REL" \
        P80_BUILD_EXPECTED_SOURCE_SHA="$R29C_EXPECTED_GENERATED_SOURCE_SHA" \
        OUTPUT="$CANDIDATE_OUTPUT" \
        bash "$RUN_ROOT/builder.sh"
    ) | tee "$BUILD_PROVENANCE_LOG"
    local build_rc=${PIPESTATUS[0]}
    echo "R29C_BUILD_RC=$build_rc"
    [ "$build_rc" -eq 0 ] || fail "R29C_BUILD_RC_GATE=FAIL"
    grep -Fq "GENERATED_SOURCE_SHA256=$R29C_EXPECTED_GENERATED_SOURCE_SHA" "$BUILD_PROVENANCE_LOG" || fail "R29C_GENERATED_SOURCE_SHA_GATE=FAIL"
    grep -Fq 'P80_CHROOT_BUILD_RC=0' "$BUILD_PROVENANCE_LOG" || fail "R29C_CHROOT_BUILD_RC_GATE=FAIL"
    grep -Fq 'MUSL_INTERPRETER_GATE=PASS' "$BUILD_PROVENANCE_LOG" || fail "R29C_MUSL_INTERPRETER_GATE=FAIL"
    grep -Fq 'NO_GLIBC_DEPENDENCY=PASS' "$BUILD_PROVENANCE_LOG" || fail "R29C_NO_GLIBC_DEPENDENCY=FAIL"
    grep -Fq 'NO_NEW_RUNTIME_DEPENDENCY=PASS' "$BUILD_PROVENANCE_LOG" || fail "R29C_NO_NEW_RUNTIME_DEPENDENCY=FAIL"
    grep -Fq 'LIB_IDENTICAL=PASS' "$BUILD_PROVENANCE_LOG" || fail "R29C_LIB_IDENTICAL=FAIL"
    [ -x "$CANDIDATE_OUTPUT" ] || fail "R29C_CANDIDATE_OUTPUT_PRESENT=false"
    [ "$FAIL" -eq 0 ] || return 1
    CANDIDATE_SHA256="$(sha256sum "$CANDIDATE_OUTPUT" | awk '{print $1}')"
    echo "CANDIDATE_BINARY_SHA256=$CANDIDATE_SHA256"
}

selfcheck_gates() {
    run_candidate_selfcheck_in_chroot || fail "R29C_CANDIDATE_SELFCHECK=FAIL"
    local gate
    for gate in \
        'CANDIDATE_HELPER_EXECUTED=true' \
        'NETWORK_WRITES_INTERCEPTED=true' \
        'MEDIAREQ26_OPEN_STRUCTURAL_LAYOUT=PASS' \
        'MEDIAREQ26_STOP_STRUCTURAL_LAYOUT=PASS' \
        'REGISTERED_CTPP_MEDIAREQ26_OPEN_SENT_COUNT=1' \
        'REGISTERED_CTPP_MEDIAREQ26_STOP_SENT_COUNT=1' \
        'SELF_ACTIVATION_001A_SENT_COUNT=0' \
        'R27_REPEAT_001A_SENT_COUNT=0' \
        'DOOR_ACTIONS_SENT=0' \
        'GATE_ACTIONS_SENT=0' \
        'NEW_ICE_COUNT=0' \
        'NEW_CLOUD_NEGOTIATION_COUNT=0' \
        'NEW_PSEUDOTCP_COUNT=0' \
        'NEW_REGISTRATION_COUNT=0' \
        'REGISTRATION_STATE_UNCHANGED=true' \
        'LISTENER_STOP_COUNT=0' \
        'R29C_BUILDER=PASS' \
        'R29C_PROBE_READY=true'
    do
        grep -qx "$gate" "$SELFCHECK_LOG" || fail "R29C_SELFCHECK_GATE=FAIL missing=$gate"
    done
}

main() {
    trap on_exit EXIT
    trap 'exit 130' INT TERM HUP

    STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
    RUN_ROOT="$ARTIFACT_ROOT/r29c-live-$STAMP"
    mkdir -p "$RUN_ROOT"
    chmod 700 "$RUN_ROOT"
    BUILD_PROVENANCE_LOG="$RUN_ROOT/build-provenance.log"
    SELFCHECK_LOG="$RUN_ROOT/selfcheck.log"
    WRAPPER_LOG="$RUN_ROOT/wrapper.log"
    CANDIDATE_OUTPUT="$RUN_ROOT/$CANDIDATE_NAME"
    : > "$BUILD_PROVENANCE_LOG"
    : > "$SELFCHECK_LOG"
    : > "$WRAPPER_LOG"
    chmod 600 "$BUILD_PROVENANCE_LOG" "$SELFCHECK_LOG" "$WRAPPER_LOG"
    echo "R29C_RUN_ROOT=REDACTED"
    case "$CANDIDATE_OUTPUT" in "$RUN_ROOT"/*) echo "R29C_CANDIDATE_OUTPUT_SCOPE=RUN_ROOT" ;; *) fail "R29C_CANDIDATE_OUTPUT_SCOPE=FAIL" ;; esac

    preflight_gates || exit 1
    build_candidate || exit 1
    selfcheck_gates || exit 1
    [ "$FAIL" -eq 0 ] || exit 1
    echo "R29C_CANDIDATE_SELFCHECK=PASS"

    RUNTIME_ROOT="$(select_runtime_root)"
    [ -n "$RUNTIME_ROOT" ] || fail "R29C_RUNTIME_ROOT=ABSENT"
    RUNTIME_LOADER="$RUNTIME_ROOT/lib/ld-musl-x86_64.so.1"
    [ -x "$RUNTIME_LOADER" ] || fail "R29C_RUNTIME_LOADER=ABSENT"
    echo "R29C_RUNTIME_ROOT=SELECTED"
    echo "R29C_RUNTIME_LOADER=SELECTED"
    [ "$FAIL" -eq 0 ] || exit 1

    prepare_holder_shim
    prepare_candidate_wrapper
    [ "$FAIL" -eq 0 ] || exit 1

    VIDEO_SINK_PID="$(start_udp_sink "$MEDIA_VIDEO_RTP_PORT" "$RUN_ROOT/video.count" "$RUN_ROOT/video.first" VIDEO)"
    AUDIO_SINK_PID="$(start_udp_sink "$MEDIA_AUDIO_RTP_PORT" "$RUN_ROOT/audio.count" "$RUN_ROOT/audio.first" AUDIO)"
    sleep 1
    if sink_bound "$MEDIA_VIDEO_RTP_PORT" && sink_bound "$MEDIA_AUDIO_RTP_PORT"; then
        echo "R29C_RTP_SINK_BIND=PASS"
    else
        fail "R29C_RTP_SINK_BIND=FAIL"
    fi

    post_control status "$RUN_ROOT/listener-status-before.json" 10 || true
    if status_ready "$RUN_ROOT/listener-status-before.json"; then
        PRODUCTION_LISTENER_RUNNING_BEFORE=true
        PRODUCTION_LISTENER_READY_BEFORE=true
        RESTORE_PATH_READY=true
    fi
    echo "PRODUCTION_LISTENER_RUNNING_BEFORE=$PRODUCTION_LISTENER_RUNNING_BEFORE"
    echo "PRODUCTION_LISTENER_READY_BEFORE=$PRODUCTION_LISTENER_READY_BEFORE"
    echo "CONTROL_PATH_STATUS_READ=PASS"

    [ "$FAIL" -eq 0 ] || exit 1
    PREP_READY=true

    if [ "$R29C_PHASE" != LIVE ]; then
        validate_watchdog_arm_disarm
        HANDOFF_PATH_READY="$RESTORE_PATH_READY"
        WATCHDOG_ARMED=false
        LIVE_RUNNER_PREFLIGHT=PASS
        echo "R29C_LIVE_PREFLIGHT_REFUSED=ARM_ONLY_MODE"
        echo "LIVE_RUN=NOT_RUN"
        exit 0
    fi

    if [ "$LIVE_RUN" != YES ] || [ "$R29C_LIVE_AUTHORIZED" != authorized ]; then
        LIVE_RUNNER_PREFLIGHT=REFUSED
        echo "R29C_LIVE_PREFLIGHT_REFUSED=LIVE_FORBIDDEN"
        echo "LIVE_RUN=NOT_RUN"
        exit 0
    fi
    USER_READY_RECEIVED=true

    [ "$PRODUCTION_LISTENER_RUNNING_BEFORE" = true ] || fail "PRODUCTION_LISTENER_RUNNING_BEFORE=false"
    [ "$PRODUCTION_LISTENER_READY_BEFORE" = true ] || fail "PRODUCTION_LISTENER_READY_BEFORE=false"
    [ "$FAIL" -eq 0 ] || exit 1

    arm_autorestore_watchdog
    [ "$WATCHDOG_READY" = true ] || fail "R29C_WATCHDOG_ARMED=false"
    [ "$FAIL" -eq 0 ] || exit 1

    PRODUCTION_LISTENER_TOUCHED=true
    post_control stop "$RUN_ROOT/listener-stop.json" 20 || true
    echo "PRODUCTION_LISTENER_STOP_REQUESTED=true"
    if status_inactive "$RUN_ROOT/listener-stop.json"; then
        PRODUCTION_LISTENER_INACTIVE=true
        UPSTREAM_OWNERSHIP_RELEASED=true
    fi
    if [ "$UPSTREAM_OWNERSHIP_RELEASED" != true ]; then
        sleep 5
        post_control status "$RUN_ROOT/listener-stop-confirm.json" 10 || true
        if status_inactive "$RUN_ROOT/listener-stop-confirm.json"; then
            PRODUCTION_LISTENER_INACTIVE=true
            UPSTREAM_OWNERSHIP_RELEASED=true
        fi
    fi
    echo "PRODUCTION_LISTENER_INACTIVE=$PRODUCTION_LISTENER_INACTIVE"
    echo "UPSTREAM_OWNERSHIP_RELEASED=$UPSTREAM_OWNERSHIP_RELEASED"
    [ "$UPSTREAM_OWNERSHIP_RELEASED" = true ] || exit 1

    LIVE_ATTEMPT_BUDGET_USED=1
    echo "LIVE_ATTEMPT_BUDGET_USED=$LIVE_ATTEMPT_BUDGET_USED"
    (
        R29C_CANDIDATE_PATH="$CANDIDATE_OUTPUT" \
        R29C_EXPECTED_CANDIDATE_SHA256="$CANDIDATE_SHA256" \
        R29C_RUNTIME_ROOT="$RUNTIME_ROOT" \
        timeout --signal=TERM --kill-after=5s "$R29C_OUTER_TIMEOUT_SECONDS" "$CANDIDATE_WRAPPER"
    ) > "$WRAPPER_LOG" 2>&1 &
    WRAPPER_PID=$!
    echo "CANDIDATE_WRAPPER_STARTED=true"

    if ! wait_for_marker RESEARCH_LISTENER_READY true "$R29C_READY_MAX_SECONDS"; then
        set_result BOOTSTRAP_FAILURE INCONCLUSIVE_CANDIDATE_BOOTSTRAP_FAILURE
        echo "R29C_BOOTSTRAP=FAIL"
        exit 1
    fi
    RESEARCH_LISTENER_READY=true
    CANDIDATE_PID="$(find_candidate_pid)"
    echo "RESEARCH_LISTENER_PID_OBSERVED=$([ -n "$CANDIDATE_PID" ] && echo true || echo false)"
    snapshot_counters READY
    echo "RESEARCH_LISTENER_READY=true"
    echo "COMELIT R29C RING NOW"

    if ! wait_for_call_init "$R29C_RING_MAX_SECONDS"; then
        if marker_present 'R29_UNKNOWN_OR_GATE_SOURCE_REJECTED=true'; then
            CALL_INIT_OBSERVED=true
            CALL_SOURCE=other
            set_result WRONG_SOURCE WRONG_CALL_SOURCE
        else
            set_result NO_CALL_INIT_TIMEOUT NO_CALL_INIT_TIMEOUT
        fi
        exit 1
    fi
    CALL_INIT_OBSERVED=true
    CALL_SOURCE=entrance
    RING_BUDGET_USED=1
    echo "CALL_INIT_OBSERVED=true"
    echo "CALL_SOURCE=entrance"
    echo "RING_BUDGET_USED=$RING_BUDGET_USED"
    snapshot_counters PREOPEN

    if ! wait_for_marker REGISTERED_CTPP_MEDIAREQ26_OPEN_SENT_COUNT 1 "$R29C_OPEN_MAX_SECONDS"; then
        set_result OPEN_NOT_SENT INCONCLUSIVE_OPEN_NOT_SENT
        exit 1
    fi
    OPEN_SENT=true
    OPEN_BUDGET_USED=1
    OPEN_OBSERVED_EPOCH="$(date +%s)"
    echo "OPEN_SENT=true"
    echo "OPEN_BUDGET_USED=$OPEN_BUDGET_USED"

    sleep "$R29C_RTP_OBSERVATION_SECONDS"
    RTP_OBSERVATION_SECONDS="$R29C_RTP_OBSERVATION_SECONDS"
    VIDEO_RTP_DATAGRAMS_SINK="$(read_sink_count "$RUN_ROOT/video.count" NOT_REACHED)"
    AUDIO_RTP_DATAGRAMS_SINK="$(read_sink_count "$RUN_ROOT/audio.count" NOT_REACHED)"
    VIDEO_RTP_PACKETS="$(last_marker P80_VIDEO_RTP_PACKETS NOT_REACHED)"
    FIRST_RTP_EPOCH="$(read_sink_first "$RUN_ROOT/video.first")"
    if { [ "$VIDEO_RTP_DATAGRAMS_SINK" != NOT_REACHED ] && [ "$VIDEO_RTP_DATAGRAMS_SINK" -gt 0 ]; } 2>/dev/null ||
       { [ "$VIDEO_RTP_PACKETS" != NOT_REACHED ] && [ "$VIDEO_RTP_PACKETS" -gt 0 ]; } 2>/dev/null; then
        VIDEO_RTP_STARTED=true
    fi
    if marker_present 'MEDIA_CHANNEL_OPEN_RESPONSE_OBSERVED=true'; then
        OPEN_RESPONSE_OBSERVED_EPOCH="$(date +%s)"
        if [ "$FIRST_RTP_EPOCH" = NOT_OBSERVED ]; then
            FIRST_RTP_RELATIVE_TO_CHANNEL_OPEN_RESPONSE=RTP_NOT_OBSERVED
        else
            FIRST_RTP_RELATIVE_TO_CHANNEL_OPEN_RESPONSE="$(
                python3 - "$FIRST_RTP_EPOCH" "$OPEN_RESPONSE_OBSERVED_EPOCH" <<'PY'
import sys
first = float(sys.argv[1])
response = float(sys.argv[2])
if first < response - 1.0:
    print("BEFORE")
elif first > response + 1.0:
    print("AFTER")
else:
    print("SAME_WINDOW")
PY
)"
        fi
    elif [ "$VIDEO_RTP_STARTED" = true ]; then
        FIRST_RTP_RELATIVE_TO_CHANNEL_OPEN_RESPONSE=RESPONSE_NOT_OBSERVED
    else
        FIRST_RTP_RELATIVE_TO_CHANNEL_OPEN_RESPONSE=RTP_NOT_OBSERVED
    fi
    echo "VIDEO_RTP_STARTED=$VIDEO_RTP_STARTED"
    echo "VIDEO_RTP_PACKETS=$VIDEO_RTP_PACKETS"
    echo "VIDEO_RTP_DATAGRAMS_SINK=$VIDEO_RTP_DATAGRAMS_SINK"
    echo "FIRST_RTP_RELATIVE_TO_CHANNEL_OPEN_RESPONSE=$FIRST_RTP_RELATIVE_TO_CHANNEL_OPEN_RESPONSE"

    if [ -n "$CANDIDATE_PID" ] && kill -0 "$CANDIDATE_PID" 2>/dev/null; then
        kill -USR2 "$CANDIDATE_PID" 2>/dev/null || true
        echo "R29C_MEDIAREQ26_STOP_REQUESTED=true"
    else
        echo "R29C_MEDIAREQ26_STOP_REQUESTED=false"
    fi
    if wait_for_marker REGISTERED_CTPP_MEDIAREQ26_STOP_SENT_COUNT 1 "$R29C_STOP_MAX_SECONDS"; then
        STOP_SENT=true
        STOP_BUDGET_USED=1
    fi
    echo "STOP_SENT=$STOP_SENT"
    echo "STOP_BUDGET_USED=$STOP_BUDGET_USED"

    sleep "$R29C_POST_STOP_OBSERVATION_SECONDS"
    snapshot_counters AFTER
    MEDIA_ONLY_STOP_RESULT="$(last_marker MEDIA_ONLY_STOP_RESULT NOT_REACHED)"
    CANDIDATE_MEDIA_ONLY_STOP_RESULT="$MEDIA_ONLY_STOP_RESULT"
    CANDIDATE_LISTENER_READY_AFTER_MEDIA="$(last_marker LISTENER_READY_AFTER_MEDIA NOT_REACHED)"
    CANDIDATE_FINAL_RESEARCH_SESSION_CLEANUP="$(last_marker FINAL_RESEARCH_SESSION_CLEANUP NOT_REACHED)"
    SELF_ACTIVATION_001A_SENT_COUNT="$(last_marker SELF_ACTIVATION_001A_SENT_COUNT NOT_REACHED)"
    R27_REPEAT_001A_SENT_COUNT="$(last_marker R27_REPEAT_001A_SENT_COUNT NOT_REACHED)"
    DOOR_ACTIONS_SENT="$(last_marker DOOR_ACTIONS_SENT NOT_REACHED)"
    GATE_ACTIONS_SENT="$(last_marker GATE_ACTIONS_SENT NOT_REACHED)"
    REFRESH_LOOP_STARTED_COUNT="$(last_marker REFRESH_LOOP_STARTED_COUNT NOT_REACHED)"

    local new_pid
    new_pid="$(find_candidate_pid)"
    if [ -n "$CANDIDATE_PID" ] && [ "$new_pid" = "$CANDIDATE_PID" ] && kill -0 "$CANDIDATE_PID" 2>/dev/null; then
        LISTENER_SURVIVED_STOP=true
    else
        LISTENER_SURVIVED_STOP=false
    fi
    RESEARCH_LISTENER_PID_STABLE="$LISTENER_SURVIVED_STOP"
    if [ "$(compute_delta "$READY_CTPP_REGISTRATION_COUNT" "$AFTER_CTPP_REGISTRATION_COUNT")" = 0 ]; then
        REGISTRATION_GENERATION_STABLE=true
    else
        REGISTRATION_GENERATION_STABLE=false
    fi
    if [ "$(compute_delta "$READY_PSEUDOTCP_OPEN_COUNT" "$AFTER_PSEUDOTCP_OPEN_COUNT")" = 0 ]; then
        PSEUDOTCP_GENERATION_STABLE=true
    else
        PSEUDOTCP_GENERATION_STABLE=false
    fi
    REGISTRATION_SURVIVED_STOP="$REGISTRATION_GENERATION_STABLE"
    PSEUDOTCP_SURVIVED_STOP="$PSEUDOTCP_GENERATION_STABLE"
    echo "LISTENER_SURVIVED_STOP=$LISTENER_SURVIVED_STOP"
    echo "AFTER_READY_CTPP_REGISTRATION_DELTA=$(compute_delta "$READY_CTPP_REGISTRATION_COUNT" "$AFTER_CTPP_REGISTRATION_COUNT")"
    echo "AFTER_READY_PSEUDOTCP_DELTA=$(compute_delta "$READY_PSEUDOTCP_OPEN_COUNT" "$AFTER_PSEUDOTCP_OPEN_COUNT")"
    echo "AFTER_READY_ICE_DELTA=$(compute_delta "$READY_ICE_BOOTSTRAP_COUNT" "$AFTER_ICE_BOOTSTRAP_COUNT")"
    echo "AFTER_READY_CLOUD_DELTA=$(compute_delta "$READY_CLOUD_NEGOTIATION_COUNT" "$AFTER_CLOUD_NEGOTIATION_COUNT")"
    echo "REGISTRATION_SURVIVED_STOP=$REGISTRATION_SURVIVED_STOP"
    echo "PSEUDOTCP_SURVIVED_STOP=$PSEUDOTCP_SURVIVED_STOP"
    echo "MEDIA_ONLY_STOP_RESULT=$MEDIA_ONLY_STOP_RESULT"

    close_research_session
    restore_listener || exit 91
    exit 0
}

if [ "${R29C_UNIT_TEST:-0}" != 1 ]; then
    main "$@"
fi
