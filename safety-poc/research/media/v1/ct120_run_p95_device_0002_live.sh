#!/usr/bin/env bash
# CT120 research-only P95 bounded live runner.
#
# Sequence:
#   verify HA Comelit listener READY
#   -> stop only that listener through the existing local control webhook
#   -> build the P95 candidate from the current branch
#   -> derive one cloud wrapper invocation for the candidate
#   -> execute exactly once for a bounded observation window
#   -> request helper stop if it remains active
#   -> restore HA listener and verify READY
#
# This runner never invokes Door, never retries the Comelit live operation, and
# never stops/restarts Home Assistant Core. Raw protocol/media payloads are kept
# in a private local log and are not printed by the summary.

set -u -o pipefail
umask 077

REPO=/root/comelit-door-diag-repo
BRANCH=fix/p102-wait-device-0002-before-rtpc
EXPECTED_PARENT=f4221fab88500f81e8258407bcbb35f9cad692f0
CT120_IP=192.168.1.85
HA_WEBHOOK_URL=http://192.168.1.108:8123/api/webhook/comelit-ha-ring-test-control-v1
BASE_WRAPPER=/usr/local/sbin/comelit-p2p-cloud-probe
BASE_WRAPPER_SHA256=a564535dff0cf10b1fe4766171f2960c52fb581f1c816cf81d2992c5c84e79c9
SECRETS_FILE=/root/.config/comelit/secrets.env
SOURCE_REL=safety-poc/research/door/v1_5_7/comelit-v4-persistent-ctpp-door.c
TRANSFORM_REL=safety-poc/research/media/v1/entrance_p95_compile_declarations_transform.py
RUN_DIR=/run/comelit-media
STOP_FILE="$RUN_DIR/stop"
LIVE_WINDOW_SECONDS=18

FAIL=0
LISTENER_STOPPED=0
RESTORE_OK=0
RESTORE_ATTEMPTS=0
LIVE_INVOCATIONS=0
RUN_ROOT=""
STATUS_AFTER=""
WRAPPER_PID=""

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

    curl \
      --silent \
      --show-error \
      --connect-timeout 5 \
      --max-time "$max_time" \
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
    [ "$(json_scalar "$file" action)" = stop ] &&
    [ "$(json_scalar "$file" supervisor_running)" = false ] &&
    [ "$(json_scalar "$file" running)" = false ] &&
    [ "$(json_scalar "$file" listener_ready)" = false ]
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
            STATUS_AFTER="$status_file"
            LISTENER_STOPPED=0
            RESTORE_OK=1
            echo "LISTENER_RESTORE_READY=PASS"
            echo "LISTENER_RESTORE_READY_POLL=$poll"
            return 0
        fi
        echo "LISTENER_RESTORE_READY_POLL_${poll}=WAIT"
        sleep 5
    done

    echo "LISTENER_RESTORE_READY=FAIL"
    return 1
}

stop_candidate_if_needed() {
    if [ -z "$WRAPPER_PID" ] || ! kill -0 "$WRAPPER_PID" 2>/dev/null; then
        return 0
    fi

    echo "P95_STOP_REQUESTED=true"
    install -d -m 700 "$RUN_DIR"
    : > "$STOP_FILE"
    chmod 600 "$STOP_FILE"

    local i
    for i in 1 2 3 4 5 6 7 8; do
        if ! kill -0 "$WRAPPER_PID" 2>/dev/null; then
            return 0
        fi
        sleep 1
    done

    echo "P95_STOP_ESCALATION=TERM"
    kill -TERM "$WRAPPER_PID" 2>/dev/null || true
    sleep 2
    if kill -0 "$WRAPPER_PID" 2>/dev/null; then
        echo "P95_STOP_ESCALATION=KILL"
        kill -KILL "$WRAPPER_PID" 2>/dev/null || true
    fi
}

on_exit() {
    local original_rc=$?

    stop_candidate_if_needed || true

    if [ "$LISTENER_STOPPED" -eq 1 ]; then
        echo
        echo "=== EXIT LISTENER RESTORE GUARD ==="
        restore_listener || true
        if [ "$LISTENER_STOPPED" -eq 1 ] && [ "$RESTORE_ATTEMPTS" -lt 3 ]; then
            sleep 5
            restore_listener || true
        fi
    fi

    echo "LISTENER_RESTORE_ATTEMPTS=$RESTORE_ATTEMPTS"
    echo "LISTENER_RESTORE_FINAL=$RESTORE_OK"
    echo "LIVE_INVOCATIONS=$LIVE_INVOCATIONS"
    echo "AUTOMATIC_RETRY=false"
    echo "HOME_ASSISTANT_CORE_STOPPED=false"
    echo "HOME_ASSISTANT_CORE_RESTARTED=false"
    echo "DOOR_ACTION_SENT=false"

    if [ "$LISTENER_STOPPED" -eq 1 ]; then
        echo "LISTENER_RESTORE_FINAL_GATE=FAIL"
        exit 90
    fi

    exit "$original_rc"
}

trap on_exit EXIT
trap 'exit 130' INT TERM HUP

if [ "${EUID}" -ne 0 ]; then
    echo "P95_LIVE_REQUIRES_ROOT=true"
    exit 1
fi

for command in git python3 cc pkg-config sha256sum timeout strings grep curl ip; do
    command -v "$command" >/dev/null 2>&1 || fail "P95_MISSING_COMMAND=$command"
done

[ -d "$REPO/.git" ] || fail "P95_REPO_PRESENT=false"

if ! ip -4 addr show | grep -Fq "$CT120_IP/"; then
    fail "P95_CT120_IDENTITY=FAIL"
else
    echo "P95_CT120_IDENTITY=PASS"
fi

CURRENT_BRANCH="$(git -C "$REPO" branch --show-current 2>/dev/null || true)"
CURRENT_HEAD="$(git -C "$REPO" rev-parse HEAD 2>/dev/null || true)"
echo "P95_CURRENT_BRANCH=$CURRENT_BRANCH"
echo "P95_CURRENT_HEAD=$CURRENT_HEAD"

[ "$CURRENT_BRANCH" = "$BRANCH" ] || fail "P95_BRANCH_GATE=FAIL"
if ! git -C "$REPO" merge-base --is-ancestor "$EXPECTED_PARENT" "$CURRENT_HEAD"; then
    fail "P95_PARENT_GATE=FAIL"
else
    echo "P95_PARENT_GATE=PASS"
fi

if [ -n "$(git -C "$REPO" status --porcelain)" ]; then
    fail "P95_WORKTREE_CLEAN=FAIL"
else
    echo "P95_WORKTREE_CLEAN=PASS"
fi

[ -f "$REPO/$SOURCE_REL" ] || fail "P95_SOURCE_PRESENT=false"
[ -f "$REPO/$TRANSFORM_REL" ] || fail "P95_TRANSFORM_PRESENT=false"

if [ ! -f "$BASE_WRAPPER" ]; then
    fail "P95_BASE_WRAPPER_PRESENT=false"
else
    BASE_SHA="$(sha256sum "$BASE_WRAPPER" | awk '{print $1}')"
    echo "P95_BASE_WRAPPER_SHA256=$BASE_SHA"
    [ "$BASE_SHA" = "$BASE_WRAPPER_SHA256" ] || fail "P95_BASE_WRAPPER_PIN=FAIL"
fi

if [ ! -f "$SECRETS_FILE" ]; then
    fail "P95_SECRETS_PRESENT=false"
else
    echo "P95_SECRETS_PRESENT=true"
    echo "P95_SECRETS_CONTENT_EMITTED=false"
fi

if pkg-config --exists nice glib-2.0 gio-2.0 gobject-2.0; then
    echo "P95_BUILD_DEPS=PASS"
else
    fail "P95_BUILD_DEPS=FAIL"
fi

if pgrep -af 'comelit-p2p-cloud-probe-p95|comelit-p95-live' >/dev/null 2>&1; then
    fail "P95_EXISTING_CANDIDATE_PROCESS=FAIL"
fi

if [ "$FAIL" -ne 0 ]; then
    echo "P95_PREFLIGHT=FAIL"
    exit 1
fi

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
RUN_ROOT="/root/comelit-p95-live-$STAMP"
BUILD="$RUN_ROOT/build"
LOG="$RUN_ROOT/live.log"
CANDIDATE_SOURCE="$BUILD/comelit-p95-live.c"
CANDIDATE_BINARY="$BUILD/comelit-p95-live"
CANDIDATE_WRAPPER="$BUILD/comelit-p2p-cloud-probe-p95"
STATUS_BEFORE="$RUN_ROOT/listener-status-before.json"
STOP_RESPONSE="$RUN_ROOT/listener-stop.json"
mkdir -p "$BUILD"
chmod 700 "$RUN_ROOT" "$BUILD"
: > "$LOG"
chmod 600 "$LOG"

echo
echo "=== BUILD CURRENT P95 CANDIDATE ==="
python3 "$REPO/$TRANSFORM_REL" \
  --source "$REPO/$SOURCE_REL" \
  --output "$CANDIDATE_SOURCE" \
  > "$RUN_ROOT/transform.log" 2>&1
TRANSFORM_RC=$?
echo "P95_TRANSFORM_RC=$TRANSFORM_RC"
if [ "$TRANSFORM_RC" -ne 0 ]; then
    cat "$RUN_ROOT/transform.log"
    fail "P95_TRANSFORM=FAIL"
fi

if [ "$FAIL" -eq 0 ]; then
    if grep -Fq 'signal(SIGUSR1, v4_door_signal_handler);' "$CANDIDATE_SOURCE"; then
        fail "P95_DOOR_SIGNAL_GATE=FAIL"
    else
        echo "P95_DOOR_SIGNAL_GATE=PASS"
    fi

    for marker in \
      'P80_DEVICE_0002_GATE_ARMED=true' \
      'P80_DEVICE_0002_OBSERVED=PASS' \
      'P80_DEVICE_0002_ACK_QUEUED=PASS' \
      'P80_DEVICE_0002_ACK_SENT=PASS' \
      'P80_DEVICE_0002_GATE=PASS' \
      'P80_MEDIA_ACTIVE=true' \
      'P80_DOOR_SIGNAL_ENTRYPOINT=false'
    do
        grep -Fq "$marker" "$CANDIDATE_SOURCE" || fail "P95_SOURCE_MARKER_GATE=FAIL marker=$marker"
    done
fi

if [ "$FAIL" -eq 0 ]; then
    cc -O2 -g -Wall -Wextra \
      -o "$CANDIDATE_BINARY" \
      "$CANDIDATE_SOURCE" \
      $(pkg-config --cflags --libs nice glib-2.0 gio-2.0 gobject-2.0) \
      2> "$RUN_ROOT/compile.stderr"
    BUILD_RC=$?
    cat "$RUN_ROOT/compile.stderr"
    echo "P95_BUILD_RC=$BUILD_RC"
    [ "$BUILD_RC" -eq 0 ] || fail "P95_BUILD=FAIL"
fi

if [ "$FAIL" -eq 0 ]; then
    chmod 700 "$CANDIDATE_BINARY"
    strings -a "$CANDIDATE_BINARY" > "$RUN_ROOT/candidate.strings"
    for marker in \
      'P80_DEVICE_0002_GATE_ARMED=true' \
      'P80_DEVICE_0002_OBSERVED=PASS' \
      'P80_DEVICE_0002_ACK_SENT=PASS' \
      'P80_DEVICE_0002_GATE=PASS' \
      'P80_MEDIA_ACTIVE=true' \
      'P80_DOOR_SIGNAL_ENTRYPOINT=false'
    do
        grep -Fq "$marker" "$RUN_ROOT/candidate.strings" || fail "P95_BINARY_MARKER_GATE=FAIL marker=$marker"
    done
fi

if [ "$FAIL" -eq 0 ]; then
    python3 - "$BASE_WRAPPER" "$CANDIDATE_WRAPPER" "$CANDIDATE_BINARY" <<'PY'
from pathlib import Path
import os
import sys

src = Path(sys.argv[1])
out = Path(sys.argv[2])
holder = sys.argv[3]
text = src.read_text(encoding="utf-8")
needle = '"$BASE/bin/comelit_ice_offer_holder"'
if text.count(needle) != 1:
    raise SystemExit("P95_WRAPPER_HOLDER_ANCHOR=FAIL")
text = text.replace(needle, f'"{holder}"', 1)
legacy_run_dir = "/run/comelit-p2p"
media_run_dir = "/run/comelit-media"
run_dir_count = text.count(legacy_run_dir)
if run_dir_count < 1:
    raise SystemExit("P95_WRAPPER_RUN_DIR_ANCHOR=FAIL")
text = text.replace(legacy_run_dir, media_run_dir)
out.write_text(text, encoding="utf-8")
os.chmod(out, 0o700)
print(f"P95_WRAPPER_RUN_DIR_REPLACEMENTS={run_dir_count}")
PY
    REWRITE_RC=$?
    echo "P95_WRAPPER_REWRITE_RC=$REWRITE_RC"
    if [ "$REWRITE_RC" -eq 0 ]; then
        bash -n "$CANDIDATE_WRAPPER" || fail "P95_WRAPPER_PARSE=FAIL"
    else
        fail "P95_WRAPPER_REWRITE=FAIL"
    fi
fi

if [ "$FAIL" -ne 0 ]; then
    echo "P95_PREFLIGHT=FAIL"
    exit 1
fi

echo "P95_PREFLIGHT=PASS"
echo "P95_RUN_ROOT=$RUN_ROOT"
echo "P95_LIVE_INVOCATION_LIMIT=1"
echo "P95_AUTOMATIC_RETRY=false"
echo "P95_DOOR_ACTION_ALLOWED=false"
echo "P95_HOME_ASSISTANT_CORE_RESTART_ALLOWED=false"

echo
echo "=== VERIFY HA LISTENER READY ==="
post_control status "$STATUS_BEFORE" 10
STATUS_RC=$?
if [ "$STATUS_RC" -eq 0 ] && status_ready "$STATUS_BEFORE"; then
    echo "LISTENER_READY_BEFORE=PASS"
    echo "LISTENER_RECONNECT_COUNT_BEFORE=$(json_scalar "$STATUS_BEFORE" reconnect_count)"
else
    fail "LISTENER_READY_BEFORE=FAIL"
fi

if [ "$FAIL" -ne 0 ]; then
    exit 1
fi

echo
echo "=== STOP ONLY COMELIT LISTENER ==="
LISTENER_STOPPED=1
post_control stop "$STOP_RESPONSE" 20
STOP_RC=$?
if [ "$STOP_RC" -eq 0 ] && status_stopped "$STOP_RESPONSE"; then
    echo "LISTENER_STOP_GATE=PASS"
else
    fail "LISTENER_STOP_GATE=FAIL"
fi

if [ "$FAIL" -ne 0 ]; then
    exit 1
fi

echo "LISTENER_ISOLATION_SETTLE_SECONDS=5"
sleep 5

rm -rf "$RUN_DIR"
install -d -m 700 "$RUN_DIR"

echo
echo "=== EXACTLY ONE P95 LIVE INVOCATION ==="
LIVE_INVOCATIONS=1
"$CANDIDATE_WRAPPER" > "$LOG" 2>&1 &
WRAPPER_PID=$!
echo "P95_WRAPPER_STARTED=true"
echo "P95_WRAPPER_PID_REDACTED=true"

elapsed=0
while [ "$elapsed" -lt "$LIVE_WINDOW_SECONDS" ]; do
    if ! kill -0 "$WRAPPER_PID" 2>/dev/null; then
        break
    fi
    sleep 1
    elapsed=$((elapsed + 1))
done

echo "P95_OBSERVATION_SECONDS=$elapsed"

if kill -0 "$WRAPPER_PID" 2>/dev/null; then
    stop_candidate_if_needed
fi

LIVE_RC=0
wait "$WRAPPER_PID" || LIVE_RC=$?
WRAPPER_PID=""
echo "P95_WRAPPER_RC=$LIVE_RC"

# Emit only explicitly safe structural/state markers. Never print the raw log.
echo
echo "=== P95 SAFE LIVE MARKERS ==="
grep -E '^(P80_DEVICE_0002_|P78_RTPC_|P80_MEDIA_ACTIVE=|P80_MEDIA_RX_TOTAL=|P80_MEDIA_WRAPPER_LEN_MATCH=|P80_MEDIA_INNER_RTP_V2=|P80_MEDIA_PT99=|P80_MEDIA_PT8=|P80_MEDIA_DIAGNOSTIC_TIMEOUT=|P80_VIDEO_RTP_FORWARDING=|P80_AUDIO_RTP_FORWARDING=|P80_DOOR_SIGNAL_ENTRYPOINT=|ICE_CONNECTED_FINAL=|ICE_READY_FINAL=|SELECTED_PAIR_FINAL=|PSEUDOTCP_OPEN_FINAL=)' "$LOG" || true

DEVICE_0002_OBSERVED_COUNT="$(grep -Fxc 'P80_DEVICE_0002_OBSERVED=PASS' "$LOG" 2>/dev/null || true)"
DEVICE_0002_ACK_SENT_COUNT="$(grep -Fxc 'P80_DEVICE_0002_ACK_SENT=PASS' "$LOG" 2>/dev/null || true)"
DEVICE_0002_GATE_COUNT="$(grep -Fxc 'P80_DEVICE_0002_GATE=PASS' "$LOG" 2>/dev/null || true)"
RTPC_OPEN1_COUNT="$(grep -Fxc 'P78_RTPC_OPEN_1_SENT=PASS' "$LOG" 2>/dev/null || true)"
RTPC_OPEN2_COUNT="$(grep -Fxc 'P78_RTPC_OPEN_2_SENT=PASS' "$LOG" 2>/dev/null || true)"
DEVICE_000A_COUNT="$(grep -Fxc 'P80_DEVICE_000A_VALIDATION=PASS' "$LOG" 2>/dev/null || true)"
CLIENT_001A_COUNT="$(grep -Fxc 'P78_RTPC_CLIENT_001A_SENT=PASS' "$LOG" 2>/dev/null || true)"
MEDIA_ACTIVE_COUNT="$(grep -Fxc 'P80_MEDIA_ACTIVE=true' "$LOG" 2>/dev/null || true)"
DOOR_RESULT_COUNT="$(grep -Fc 'V4_DOOR_RESULT=' "$LOG" 2>/dev/null || true)"

echo
echo "=== RESTORE HA LISTENER ==="
if ! restore_listener; then
    sleep 5
    restore_listener || true
fi

if [ "$RESTORE_OK" -eq 1 ]; then
    echo "LISTENER_READY_AFTER=PASS"
    echo "LISTENER_RECONNECT_COUNT_AFTER=$(json_scalar "$STATUS_AFTER" reconnect_count)"
else
    fail "LISTENER_READY_AFTER=FAIL"
fi

[ "$LIVE_INVOCATIONS" -eq 1 ] || fail "P95_EXACTLY_ONCE_GATE=FAIL"
[ "$DOOR_RESULT_COUNT" -eq 0 ] || fail "P95_DOOR_RESULT_GATE=FAIL"

if [ "$RESTORE_OK" -ne 1 ]; then
    FAIL=1
fi

echo
echo "=== COMELIT P95 CT120 LIVE SUMMARY ==="
echo "P95_BRANCH_HEAD=$CURRENT_HEAD"
echo "P95_LIVE_INVOCATIONS=$LIVE_INVOCATIONS"
echo "P95_DEVICE_0002_OBSERVED_COUNT=$DEVICE_0002_OBSERVED_COUNT"
echo "P95_DEVICE_0002_ACK_SENT_COUNT=$DEVICE_0002_ACK_SENT_COUNT"
echo "P95_DEVICE_0002_GATE_COUNT=$DEVICE_0002_GATE_COUNT"
echo "P95_RTPC_OPEN_1_SENT_COUNT=$RTPC_OPEN1_COUNT"
echo "P95_RTPC_OPEN_2_SENT_COUNT=$RTPC_OPEN2_COUNT"
echo "P95_DEVICE_000A_VALIDATION_COUNT=$DEVICE_000A_COUNT"
echo "P95_CLIENT_001A_SENT_COUNT=$CLIENT_001A_COUNT"
echo "P95_MEDIA_ACTIVE_COUNT=$MEDIA_ACTIVE_COUNT"
echo "P95_WRAPPER_RC=$LIVE_RC"
echo "P95_LISTENER_RESTORED=$RESTORE_OK"
echo "P95_DOOR_RESULT_MARKER_COUNT=$DOOR_RESULT_COUNT"
echo "P95_AUTOMATIC_RETRY=false"
echo "HOME_ASSISTANT_CORE_STOPPED=false"
echo "HOME_ASSISTANT_CORE_RESTARTED=false"
echo "DOOR_ACTION_SENT=false"
echo "P95_RUN_ROOT=$RUN_ROOT"
if [ "$FAIL" -eq 0 ]; then
    echo "P95_LIVE_RUNNER_RESULT=PASS"
else
    echo "P95_LIVE_RUNNER_RESULT=FAIL"
fi
echo "=== END COMELIT P95 CT120 LIVE SUMMARY ==="

[ "$FAIL" -eq 0 ]