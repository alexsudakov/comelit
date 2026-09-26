#!/usr/bin/env bash
# CT120 research-only MSL-V1 baseline startup-latency runner.

set -u -o pipefail
umask 077

REPO=${REPO:-/root/comelit-door-diag-repo}
MSL_EXPECTED_COMMIT_SHA=${MSL_EXPECTED_COMMIT_SHA:-}
MSL_LIVE_RUN=${MSL_LIVE_RUN:-NO}
MSL_ATTEMPT_LEDGER=${MSL_ATTEMPT_LEDGER:-}
HA_WEBHOOK_URL=${HA_WEBHOOK_URL:-http://192.168.1.108:8123/api/webhook/comelit-ha-ring-test-control-v1}
BASE_WRAPPER=/usr/local/sbin/comelit-p2p-cloud-probe
BASE_WRAPPER_SHA256=a564535dff0cf10b1fe4766171f2960c52fb581f1c816cf81d2992c5c84e79c9
SOURCE_REL=safety-poc/research/door/v1_5_7/comelit-v4-persistent-ctpp-door.c
BUILDER_REL=safety-poc/research/media/v1/ct120_build_p80_haos_media_helper.sh
TRANSFORM_REL=safety-poc/research/media/v1/entrance_msl_v1_latency_instrumentation_transform.py
R65_TRANSFORM_REL=safety-poc/research/media/v1/entrance_p116_r65_production_media_refresh_transform.py
RUNNER_REL=safety-poc/research/media/v1/ct120_run_msl_v1_baseline_live.sh
EXPECTED_BASE_SOURCE_SHA=5827d9fd043b85fc0c59a31661a1a125c6b239771e2a70c3e5afdd95f1a03c73
EXPECTED_R65_ENTRY_SHA=5de655f60b3f29d1fe06c6a35ddb2f1a2892ba185c3015edffa26cf017c89b51
EXPECTED_GENERATED_SOURCE_SHA=${MSL_EXPECTED_GENERATED_SOURCE_SHA:-}
VIDEO_RTP_PORT=17899
AUDIO_RTP_PORT=17808
SETUP_MARGIN_SECONDS=${SETUP_MARGIN_SECONDS:-45}
MEDIA_OBSERVATION_SECONDS=${MEDIA_OBSERVATION_SECONDS:-40}
MIN_SETUP_MARGIN_SECONDS=30
MEDIA_STARTUP_OUTER_TIMEOUT=$((SETUP_MARGIN_SECONDS + MEDIA_OBSERVATION_SECONDS))
MAX_BASELINE_OUTER_TIMEOUT_SECONDS=90
CREDENTIAL_MIN_TTL_SECONDS=900
OAUTH_STATUS=/usr/local/sbin/comelit-oauth-status
RUN_DIR=/run/comelit-media
STOP_FILE="$RUN_DIR/stop"
CLOCK_BASE_FILE="$RUN_DIR/msl-clock-base"
CANDIDATE_HOLDER_NAME=comelit-msl-v1-baseline
WRAPPER_NAME=comelit-p2p-cloud-probe-msl-v1

FAIL=0
LISTENER_STOPPED=0
RESTORE_OK=0
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
MSL_RUN_CLASSIFICATION=NOT_RUN
LISTENER_READY_BEFORE=false
LISTENER_READY_AFTER=false
LISTENER_RESTORE_OK=false
MEDIA_TEARDOWN=UNCERTAIN
CAMPAIGN_PROCESSES_REMAINING=UNKNOWN
RTP_SINK_PORTS_REMAINING=UNKNOWN

msl_mono_ms() {
    python3 - <<'PY'
import time
print(time.monotonic_ns() // 1_000_000)
PY
}

msl_since_base() {
    python3 - "$CLOCK_BASE_FILE" <<'PY'
from pathlib import Path
import sys, time
base = int(Path(sys.argv[1]).read_text(encoding="utf-8").strip())
now = time.monotonic_ns() // 1_000_000
print(max(0, now - base))
PY
}

msl_mark() {
    printf 'MSL_%s_MONO_MS=%s\n' "$1" "$(msl_since_base)"
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
    local action="$1" output="$2" max_time="$3" http_file="${output}.http" rc
    curl --silent --show-error --connect-timeout 5 --max-time "$max_time" \
      --header 'Content-Type: application/json' \
      --output "$output" \
      --write-out '%{http_code}\n' \
      --data "{\"action\":\"$action\"}" \
      "$HA_WEBHOOK_URL" > "$http_file"
    rc=$?
    echo "CONTROL_${action^^}_CURL_RC=$rc"
    [ -s "$http_file" ] && echo "CONTROL_${action^^}_HTTP_STATUS=$(cat "$http_file")" || echo "CONTROL_${action^^}_HTTP_STATUS=NONE"
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

msl_start_udp_sink() {
    local port="$1" count_file="$2" timeout_seconds="${3:-2}"
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

if [ "${MSL_SELF_TEST_UDP_SINK:-NO}" = YES ]; then
    tmp="${TMPDIR:-/tmp}/msl-udp-sink-$$.count"
    pid="$(msl_start_udp_sink 17991 "$tmp" 2)"
    sleep 0.2
    set +e
    python3 - <<'PY'
import socket
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
for i in range(3):
    s.sendto(b"x", ("127.0.0.1", 17991))
PY
    send_rc=$?
    set -u -o pipefail
    if [ "$send_rc" -ne 0 ]; then
        echo "MSL_UDP_SINK_SELF_TEST_PERMISSION_DENIED=true"
        kill -TERM "$pid" 2>/dev/null || true
        rm -f "$tmp" "$tmp.log"
        exit 0
    fi
    sleep 2
    kill -TERM "$pid" 2>/dev/null || true
    echo "MSL_UDP_SINK_SELF_TEST_COUNT=$(tr -d '[:space:]' < "$tmp")"
    rm -f "$tmp" "$tmp.log"
    exit 0
fi

if [ "$MSL_LIVE_RUN" != YES ]; then
    echo "MSL_OFFLINE_SAFE_REFUSAL=true"
    echo "LIVE_INVOCATIONS=0"
    echo "MSL_RUN_CLASSIFICATION=NOT_RUN"
    exit 2
fi

print_final_block() {
    echo "=== COMELIT MSL V1 BASELINE FINAL ==="
    echo "LIVE_INVOCATIONS=$LIVE_INVOCATIONS"
    echo "WRAPPER_RC=$WRAPPER_RC"
    echo "MSL_START_REFERENCE=T03_NATIVE_MEDIA_HELPER_PROCESS_START"
    echo "SETUP_MARGIN_SECONDS=$SETUP_MARGIN_SECONDS"
    echo "MEDIA_OBSERVATION_SECONDS=$MEDIA_OBSERVATION_SECONDS"
    echo "MEDIA_STARTUP_OUTER_TIMEOUT=$MEDIA_STARTUP_OUTER_TIMEOUT"
    REQUIRED_MIN_WRAPPER_BOUND_SECONDS=$((MEDIA_OBSERVATION_SECONDS + MIN_SETUP_MARGIN_SECONDS))
    echo "MIN_SETUP_MARGIN_SECONDS=$MIN_SETUP_MARGIN_SECONDS"
    echo "REQUIRED_MIN_WRAPPER_BOUND_SECONDS=$REQUIRED_MIN_WRAPPER_BOUND_SECONDS"
    if [ "$MEDIA_STARTUP_OUTER_TIMEOUT" -le "$MAX_BASELINE_OUTER_TIMEOUT_SECONDS" ] &&
       [ "$MEDIA_STARTUP_OUTER_TIMEOUT" -ge "$REQUIRED_MIN_WRAPPER_BOUND_SECONDS" ]; then
        echo "MSL_BOUND_INVARIANT=PASS"
    else
        echo "MSL_BOUND_INVARIANT=FAIL"
    fi
    echo "LISTENER_READY_BEFORE=$LISTENER_READY_BEFORE"
    echo "LISTENER_READY_AFTER=$LISTENER_READY_AFTER"
    echo "LISTENER_RESTORE_OK=$LISTENER_RESTORE_OK"
    echo "RECONNECT_COUNT_DELTA=NOT_REACHED"
    echo "MEDIA_TEARDOWN=$MEDIA_TEARDOWN"
    echo "CAMPAIGN_PROCESSES_REMAINING=$CAMPAIGN_PROCESSES_REMAINING"
    echo "RTP_SINK_PORTS_REMAINING=$RTP_SINK_PORTS_REMAINING"
    echo "DOOR_ACTIONS_SENT=0"
    echo "GATE_ACTIONS_SENT=0"
    echo "PHYSICAL_RING_ACTIONS=0"
    echo "AUTOMATIC_PROTOCOL_RETRY=false"
    echo "SECOND_MEDIA_SESSION=false"
    echo "MSL_RUN_CLASSIFICATION=$MSL_RUN_CLASSIFICATION"
    echo "MSL_T19_T24_NA_REASON=HA_STREAM_HLS_PIPELINE_NOT_IN_THIS_CHILD"
    echo "=== END COMELIT MSL V1 BASELINE FINAL ==="
}

stop_pid() {
    local pid="$1"
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
        kill -TERM "$pid" 2>/dev/null || true
        sleep 1
        kill -KILL "$pid" 2>/dev/null || true
    fi
}

restore_listener() {
    local poll status_file start_file
    [ "$LISTENER_STOPPED" -eq 1 ] || return 0
    start_file="$RUN_ROOT/listener-start.json"
    post_control start "$start_file" 40 || true
    for poll in 1 2 3 4 5 6 7 8; do
        status_file="$RUN_ROOT/listener-restore-${poll}.json"
        post_control status "$status_file" 10 || true
        if status_ready "$status_file"; then
            LISTENER_STOPPED=0
            RESTORE_OK=1
            LISTENER_READY_AFTER=true
            LISTENER_RESTORE_OK=true
            return 0
        fi
        sleep 5
    done
    return 91
}

on_exit() {
    rc=$?
    if [ -n "$WRAPPER_PID" ] && kill -0 "$WRAPPER_PID" 2>/dev/null; then
        install -d -m 700 "$RUN_DIR"
        : > "$STOP_FILE"
        chmod 600 "$STOP_FILE"
        stop_pid "$WRAPPER_PID"
    fi
    stop_pid "$VIDEO_SINK_PID"
    stop_pid "$AUDIO_SINK_PID"
    RTP_SINK_PORTS_REMAINING=0
    if [ "$LISTENER_STOPPED" -eq 1 ]; then
        restore_listener || {
            echo "MSL_CAMPAIGN_STOPPED_FAIL_CLOSED=true"
            rc=91
        }
    fi
    if pgrep -af "$WRAPPER_NAME|$CANDIDATE_HOLDER_NAME" >/dev/null 2>&1; then
        CAMPAIGN_PROCESSES_REMAINING=FOUND
        MEDIA_TEARDOWN=UNCERTAIN
    else
        CAMPAIGN_PROCESSES_REMAINING=NONE
        MEDIA_TEARDOWN=CONFIRMED
    fi
    print_final_block
    exit "$rc"
}
trap on_exit EXIT
trap 'exit 130' INT TERM HUP

[ -n "$MSL_EXPECTED_COMMIT_SHA" ] || fail "MSL_EXPECTED_COMMIT_SHA_REQUIRED=true"
[ -n "$MSL_ATTEMPT_LEDGER" ] || fail "MSL_ATTEMPT_LEDGER_REQUIRED=true"
if [ -n "$MSL_ATTEMPT_LEDGER" ]; then
    if [ ! -f "$MSL_ATTEMPT_LEDGER" ]; then
        fail "MSL_ATTEMPT_LEDGER=ABSENT"
    else
        ledger_value="$(tr -d '[:space:]' < "$MSL_ATTEMPT_LEDGER")"
        case "$ledger_value" in
            ''|*[!0-9]*) fail "MSL_ATTEMPT_LEDGER=MALFORMED" ;;
            *) [ "$ledger_value" -lt 15 ] || fail "MSL_ATTEMPT_LEDGER_CAP=FAIL" ;;
        esac
    fi
fi
[ "$MEDIA_STARTUP_OUTER_TIMEOUT" -le "$MAX_BASELINE_OUTER_TIMEOUT_SECONDS" ] || fail "MEDIA_STARTUP_OUTER_TIMEOUT_GATE=FAIL"
[ "$FAIL" -eq 0 ] || exit 1

if [ "${EUID}" -ne 0 ]; then
    echo "MSL_REQUIRES_ROOT=true"
    exit 1
fi

for command in git python3 curl sha256sum timeout awk grep bash chmod install readelf stat cmp; do
    command -v "$command" >/dev/null 2>&1 || fail "MSL_MISSING_COMMAND=$command"
done

[ -d "$REPO/.git" ] || fail "MSL_REPO_PRESENT=false"
[ -x "$BASE_WRAPPER" ] || fail "MSL_BASE_WRAPPER_PRESENT=false"
if [ -x "$BASE_WRAPPER" ]; then
    actual_wrapper_sha="$(sha256sum "$BASE_WRAPPER" | awk '{print $1}')"
    echo "BASE_WRAPPER_SHA256=$actual_wrapper_sha"
    [ "$actual_wrapper_sha" = "$BASE_WRAPPER_SHA256" ] || fail "BASE_WRAPPER_SHA256_GATE=FAIL"
fi
repo_head="$(git -C "$REPO" rev-parse HEAD 2>/dev/null || true)"
echo "MSL_REPO_HEAD=$repo_head"
[ "$repo_head" = "$MSL_EXPECTED_COMMIT_SHA" ] || fail "MSL_EXPECTED_COMMIT_SHA_GATE=FAIL"
[ -z "$(git -C "$REPO" status --porcelain)" ] || fail "MSL_WORKTREE_CLEAN=FAIL"
[ "$(git -C "$REPO" show "$MSL_EXPECTED_COMMIT_SHA:$SOURCE_REL" | sha256sum | awk '{print $1}')" = "$EXPECTED_BASE_SOURCE_SHA" ] || fail "MSL_BASE_SOURCE_SHA_GATE=FAIL"
[ "$(git -C "$REPO" show "$MSL_EXPECTED_COMMIT_SHA:$R65_TRANSFORM_REL" | sha256sum | awk '{print $1}')" = "$EXPECTED_R65_ENTRY_SHA" ] || fail "MSL_R65_ENTRY_SHA_GATE=FAIL"
[ "$FAIL" -eq 0 ] || exit 1

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
RUN_ROOT="/root/comelit-msl-v1-baseline-$STAMP"
mkdir -p "$RUN_ROOT"
chmod 700 "$RUN_ROOT"
SESSION_LOG="$RUN_ROOT/session.log"
BUILD_PROVENANCE_LOG="$RUN_ROOT/build-provenance.log"
CANDIDATE_WRAPPER="$RUN_ROOT/$WRAPPER_NAME"
: > "$SESSION_LOG"
: > "$BUILD_PROVENANCE_LOG"
chmod 600 "$SESSION_LOG" "$BUILD_PROVENANCE_LOG"

git -C "$REPO" show "$MSL_EXPECTED_COMMIT_SHA:$TRANSFORM_REL" > "$RUN_ROOT/transform.py" || fail "MSL_TRANSFORM_BLOB=FAIL"
git -C "$REPO" show "$MSL_EXPECTED_COMMIT_SHA:$RUNNER_REL" > "$RUN_ROOT/runner.sh" || fail "MSL_RUNNER_BLOB=FAIL"
git -C "$REPO" show "$MSL_EXPECTED_COMMIT_SHA:$BUILDER_REL" > "$RUN_ROOT/builder.sh" || fail "MSL_BUILDER_BLOB=FAIL"
bash -n "$RUN_ROOT/runner.sh" || fail "MSL_RUNNER_BASH_N=FAIL"
bash -n "$RUN_ROOT/builder.sh" || fail "MSL_BUILDER_BASH_N=FAIL"
cmp "$RUN_ROOT/transform.py" "$REPO/$TRANSFORM_REL" >/dev/null 2>&1 || fail "MSL_TRANSFORM_WORKTREE_BLOB_GATE=FAIL"
cmp "$RUN_ROOT/runner.sh" "$REPO/$RUNNER_REL" >/dev/null 2>&1 || fail "MSL_RUNNER_WORKTREE_BLOB_GATE=FAIL"
[ "$FAIL" -eq 0 ] || exit 1

install -d -m 700 "$RUN_DIR"
msl_mono_ms > "$CLOCK_BASE_FILE"
chmod 600 "$CLOCK_BASE_FILE"
msl_mark "T00_RESEARCH_START"

echo "=== BUILD EPHEMERAL MSL HELPER ==="
MSL_OUTPUT="$RUN_ROOT/comelit-media-msl-v1"
(
    REPO="$REPO" \
    P80_BUILD_ALLOW_DETACHED=1 \
    P80_BUILD_EXPECTED_SHA="$MSL_EXPECTED_COMMIT_SHA" \
    P80_BUILD_INCLUDE_P116=1 \
    P80_BUILD_TRANSFORM="$TRANSFORM_REL" \
    P80_BUILD_EXPECTED_SOURCE_SHA="$EXPECTED_GENERATED_SOURCE_SHA" \
    OUTPUT="$MSL_OUTPUT" \
    bash "$RUN_ROOT/builder.sh"
) | tee "$BUILD_PROVENANCE_LOG"
build_rc=${PIPESTATUS[0]}
echo "MSL_BUILD_RC=$build_rc"
[ "$build_rc" -eq 0 ] || exit 1

BUILDER_ROOTFS="$(awk -F= '$1=="P80_OFFLINE_ROOTFS"{v=$2} END{print v ? v : "NOT_REACHED"}' "$BUILD_PROVENANCE_LOG")"
PACKAGED_LIB_DIR="$REPO/custom_components/comelit/native/lib"
RUN_MUSL_LOADER="$RUN_ROOT/ld-musl-x86_64.so.1"
CANDIDATE_LAUNCHER="$RUN_ROOT/$CANDIDATE_HOLDER_NAME"
install -m 700 "$BUILDER_ROOTFS/lib/ld-musl-x86_64.so.1" "$RUN_MUSL_LOADER" || fail "MSL_LOADER_COPY=FAIL"
[ -x "$MSL_OUTPUT" ] || fail "MSL_OUTPUT_PRESENT=false"
[ "$FAIL" -eq 0 ] || exit 1

cat > "$CANDIDATE_LAUNCHER" <<EOF
#!/usr/bin/env bash
set -u
export MSL_CLOCK_BASE_FILE="$CLOCK_BASE_FILE"
exec "$RUN_MUSL_LOADER" --library-path "$PACKAGED_LIB_DIR" "$MSL_OUTPUT" "\$@"
EOF
chmod 700 "$CANDIDATE_LAUNCHER"

python3 - "$BASE_WRAPPER" "$CANDIDATE_WRAPPER" "$CANDIDATE_LAUNCHER" "$CLOCK_BASE_FILE" <<'PY'
from pathlib import Path
import os, sys
src, out, holder, base_file = map(Path, sys.argv[1:])
text = src.read_text(encoding="utf-8")
needle = '"$BASE/bin/comelit_ice_offer_holder"'
if text.count(needle) != 1:
    raise SystemExit("MSL_WRAPPER_HOLDER_ANCHOR=FAIL")
text = text.replace(needle, f'"{holder}"', 1)
text = text.replace("/run/comelit-p2p", "/run/comelit-media")
prefix = f'''msl_mono_ms() {{ python3 - <<'PY2'\nimport time\nprint(time.monotonic_ns() // 1000000)\nPY2\n}}\nmsl_since_base() {{ python3 - {str(base_file)!r} <<'PY2'\nfrom pathlib import Path\nimport sys, time\nbase=int(Path(sys.argv[1]).read_text().strip())\nprint(max(0, time.monotonic_ns() // 1000000 - base))\nPY2\n}}\nmsl_wrap_mark() {{ printf 'MSL_%s_MONO_MS=%s\\n' "$1" "$(msl_since_base)"; }}\n'''
text = text.replace("\n", "\n", 1)
text = prefix + text
text = text.replace("COMELIT_OAUTH_ACCESS_TOKEN_PRESENT=true", "COMELIT_OAUTH_ACCESS_TOKEN_PRESENT=true\nmsl_wrap_mark T05_OAUTH_ACCESS_TOKEN_AVAILABLE", 1)
text = text.replace("curl ", "msl_wrap_mark T06_CLOUD_P2P_REQUEST_START\ncurl ", 1)
text = text.replace("REMOTE_SDP_WRITTEN=PASS", "REMOTE_SDP_WRITTEN=PASS\nmsl_wrap_mark T07_CLOUD_P2P_RESPONSE_REMOTE_SDP_WRITTEN", 1)
out.write_text(text, encoding="utf-8")
os.chmod(out, 0o700)
print("MSL_WRAPPER_INSTRUMENTATION=PASS")
PY
[ "$?" -eq 0 ] || fail "MSL_WRAPPER_REWRITE=FAIL"
bash -n "$CANDIDATE_WRAPPER" || fail "MSL_CANDIDATE_WRAPPER_PARSE=FAIL"
[ "$FAIL" -eq 0 ] || exit 1

echo "=== VERIFY CREDENTIAL STATUS ==="
if [ ! -x "$OAUTH_STATUS" ]; then
    fail "MSL_OAUTH_STATUS_PRESENT=false"
fi
if [ "$FAIL" -eq 0 ]; then
    OAUTH_OUTPUT="$RUN_ROOT/oauth-status.txt"
    set +e
    "$OAUTH_STATUS" > "$OAUTH_OUTPUT" 2>&1
    oauth_rc=$?
    set -u -o pipefail
    echo "MSL_OAUTH_STATUS_RC=$oauth_rc"
    [ "$oauth_rc" -eq 0 ] || fail "MSL_OAUTH_STATUS=FAIL"
    access_present="$(awk -F= '$1=="COMELIT_OAUTH_ACCESS_TOKEN_PRESENT"{print $2}' "$OAUTH_OUTPUT" | tail -1)"
    ttl="$(awk -F= '$1=="OAUTH_ACCESS_TOKEN_TTL_SECONDS"{print $2}' "$OAUTH_OUTPUT" | tail -1)"
    [ "$access_present" = true ] || fail "MSL_OAUTH_ACCESS_TOKEN_PRESENT=false"
    [ -n "$ttl" ] && [ "$ttl" -ge "$CREDENTIAL_MIN_TTL_SECONDS" ] 2>/dev/null || fail "MSL_OAUTH_ACCESS_TOKEN_TTL_GATE=FAIL"
    [ "$FAIL" -eq 0 ] && msl_mark "T05_OAUTH_ACCESS_TOKEN_AVAILABLE"
fi
[ "$FAIL" -eq 0 ] || exit 1

echo "=== VERIFY LISTENER READY ==="
STATUS_BEFORE="$RUN_ROOT/listener-status-before.json"
post_control status "$STATUS_BEFORE" 10
if status_ready "$STATUS_BEFORE"; then
    LISTENER_READY_BEFORE=true
else
    fail "LISTENER_READY_BEFORE=false"
fi
[ "$FAIL" -eq 0 ] || exit 1

echo "=== STOP ONLY COMELIT LISTENER ==="
STOP_RESPONSE="$RUN_ROOT/listener-stop.json"
msl_mark "T01_LISTENER_STOP_REQUESTED"
LISTENER_STOPPED=1
post_control stop "$STOP_RESPONSE" 20
if status_stopped "$STOP_RESPONSE"; then
    msl_mark "T02_LISTENER_RUNTIME_CONFIRMED_STOPPED"
else
    fail "LISTENER_STOP_GATE=FAIL"
fi
[ "$FAIL" -eq 0 ] || exit 1

VIDEO_SINK_PID="$(msl_start_udp_sink "$VIDEO_RTP_PORT" "$RUN_ROOT/video.count" "$MEDIA_STARTUP_OUTER_TIMEOUT")"
AUDIO_SINK_PID="$(msl_start_udp_sink "$AUDIO_RTP_PORT" "$RUN_ROOT/audio.count" "$MEDIA_STARTUP_OUTER_TIMEOUT")"
echo "MSL_VIDEO_RTP_SINK=true"
echo "MSL_AUDIO_RTP_SINK=true"
echo "MSL_CONTINUATION_EVIDENCE_SOURCE=INDEPENDENT_UDP_SINK_OR_EXPLICIT_ZERO"

echo "=== RUN EXACTLY ONE WRAPPER INVOCATION ==="
LIVE_INVOCATIONS=1
timeout --signal=TERM --kill-after=5s "$MEDIA_STARTUP_OUTER_TIMEOUT" "$CANDIDATE_WRAPPER" > "$SESSION_LOG" 2>&1 &
WRAPPER_PID=$!
wait "$WRAPPER_PID"
WRAPPER_RC=$?
WRAPPER_PID=""
cat "$SESSION_LOG"
MSL_RUN_CLASSIFICATION=BASELINE_ATTEMPT_COMPLETE

stop_pid "$VIDEO_SINK_PID"
stop_pid "$AUDIO_SINK_PID"
VIDEO_SINK_PID=""
AUDIO_SINK_PID=""
echo "MSL_VIDEO_SINK_DATAGRAMS=$(tr -d '[:space:]' < "$RUN_ROOT/video.count" 2>/dev/null || printf 0)"
echo "MSL_AUDIO_SINK_DATAGRAMS=$(tr -d '[:space:]' < "$RUN_ROOT/audio.count" 2>/dev/null || printf 0)"

echo "=== RESTORE LISTENER ==="
restore_listener || exit 91
exit 0
