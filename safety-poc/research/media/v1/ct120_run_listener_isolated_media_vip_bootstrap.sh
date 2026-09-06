#!/usr/bin/env bash
# CT120 controlled media-session bootstrap comparison.
# Stops only the HA Comelit listener, runs exactly one bootstrap-only media
# session, then restores the listener.  Home Assistant Core is never stopped.

set -u -o pipefail
umask 077

REPO=/root/comelit-door-diag-repo
REMOTE_REF=refs/remotes/origin/main
REQUIRED_ANCESTOR=e535198b42461ef088b6c06d8b1a7a11df64fc28
CT120_IP=192.168.1.85
HA_WEBHOOK_URL=http://192.168.1.108:8123/api/webhook/comelit-ha-ring-test-control-v1
PROBE_REL=safety-poc/research/media/v1/ct120_run_media_vip_bootstrap_probe.sh

FAIL=0
LISTENER_MAY_BE_STOPPED=0
RESTORE_OK=0
RESTORE_ATTEMPTS=0
PROBE_LIVE_INVOCATIONS=0
RUN_ROOT=""
PROBE_LOG=""
PROBE_RUNNER=""

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

    curl --silent --show-error \
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
    local start_file status_file poll
    if [ "$LISTENER_MAY_BE_STOPPED" -ne 1 ]; then
        return 0
    fi

    RESTORE_ATTEMPTS=$((RESTORE_ATTEMPTS + 1))
    echo "MEDIA_BOOTSTRAP_LISTENER_RESTORE_ATTEMPT=$RESTORE_ATTEMPTS"
    start_file="$RUN_ROOT/listener-start-${RESTORE_ATTEMPTS}.json"
    post_control start "$start_file" 40 || true

    for poll in 1 2 3 4 5 6 7 8; do
        status_file="$RUN_ROOT/listener-restore-status-${RESTORE_ATTEMPTS}-${poll}.json"
        post_control status "$status_file" 10 || true
        if status_ready "$status_file"; then
            LISTENER_MAY_BE_STOPPED=0
            RESTORE_OK=1
            echo "MEDIA_BOOTSTRAP_LISTENER_RESTORE_READY=PASS"
            echo "MEDIA_BOOTSTRAP_LISTENER_RESTORE_POLL=$poll"
            echo "MEDIA_BOOTSTRAP_LISTENER_RECONNECT_COUNT_AFTER=$(json_scalar "$status_file" reconnect_count)"
            return 0
        fi
        echo "MEDIA_BOOTSTRAP_LISTENER_RESTORE_POLL_${poll}=WAIT"
        sleep 5
    done

    echo "MEDIA_BOOTSTRAP_LISTENER_RESTORE_READY=FAIL"
    return 1
}

on_exit() {
    local rc=$?
    if [ "$LISTENER_MAY_BE_STOPPED" -eq 1 ]; then
        echo
        echo "=== MEDIA BOOTSTRAP EXIT RESTORE GUARD ==="
        restore_listener || true
        if [ "$LISTENER_MAY_BE_STOPPED" -eq 1 ] && [ "$RESTORE_ATTEMPTS" -lt 3 ]; then
            sleep 5
            restore_listener || true
        fi
    fi

    echo "MEDIA_BOOTSTRAP_LISTENER_RESTORE_ATTEMPTS=$RESTORE_ATTEMPTS"
    echo "MEDIA_BOOTSTRAP_LISTENER_RESTORE_FINAL=$RESTORE_OK"
    echo "HOME_ASSISTANT_CORE_STOPPED=false"
    echo "HOME_ASSISTANT_CORE_RESTARTED=false"
    echo "DOOR_ACTION_SENT=false"
    echo "SELF_ACTIVATION_SENT=false"
    echo "MEDIA_SIGNALING_SENT=false"

    if [ "$LISTENER_MAY_BE_STOPPED" -eq 1 ]; then
        echo "MEDIA_BOOTSTRAP_LISTENER_RESTORE_FINAL_GATE=FAIL"
        exit 90
    fi
    exit "$rc"
}

trap on_exit EXIT
trap 'exit 130' INT TERM HUP

if [ "${EUID}" -ne 0 ]; then
    echo "LISTENER_ISOLATED_MEDIA_BOOTSTRAP_REQUIRES_ROOT=true"
    exit 1
fi

for command in git python3 curl sha256sum grep tee ip; do
    command -v "$command" >/dev/null 2>&1 || fail "MEDIA_BOOTSTRAP_MISSING_COMMAND=$command"
done

[ -d "$REPO/.git" ] || fail "MEDIA_BOOTSTRAP_REPO_PRESENT=false"

if ip -4 addr show | grep -Fq "$CT120_IP/"; then
    echo "MEDIA_BOOTSTRAP_CT120_IDENTITY=PASS"
else
    fail "MEDIA_BOOTSTRAP_CT120_IDENTITY=FAIL"
fi

REMOTE_MAIN="$(git -C "$REPO" rev-parse "$REMOTE_REF" 2>/dev/null || true)"
echo "MEDIA_BOOTSTRAP_REMOTE_MAIN=$REMOTE_MAIN"
if [ -z "$REMOTE_MAIN" ] || ! git -C "$REPO" merge-base --is-ancestor "$REQUIRED_ANCESTOR" "$REMOTE_MAIN"; then
    fail "MEDIA_BOOTSTRAP_MAIN_GATE=FAIL"
else
    echo "MEDIA_BOOTSTRAP_MAIN_GATE=PASS"
fi

if [ "$FAIL" -ne 0 ]; then
    echo "LISTENER_ISOLATED_MEDIA_BOOTSTRAP_PREFLIGHT=FAIL"
    echo "LISTENER_STOP_REQUESTED=false"
    echo "PROBE_LIVE_INVOCATIONS=0"
    exit 1
fi

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
RUN_ROOT="/root/comelit-listener-isolated-media-bootstrap-$STAMP"
mkdir -p "$RUN_ROOT"
chmod 700 "$RUN_ROOT"
PROBE_RUNNER="$RUN_ROOT/ct120_run_media_vip_bootstrap_probe.sh"
PROBE_LOG="$RUN_ROOT/probe.log"
STATUS_BEFORE="$RUN_ROOT/listener-status-before.json"
STOP_RESPONSE="$RUN_ROOT/listener-stop.json"

echo
echo "=== 1. MATERIALIZE REVIEWED BOOTSTRAP RUNNER ==="
git -C "$REPO" show "$REMOTE_MAIN:$PROBE_REL" > "$PROBE_RUNNER"
EXTRACT_RC=$?
echo "MEDIA_BOOTSTRAP_PROBE_EXTRACT_RC=$EXTRACT_RC"
if [ "$EXTRACT_RC" -ne 0 ]; then
    fail "MEDIA_BOOTSTRAP_PROBE_EXTRACT=FAIL"
else
    chmod 700 "$PROBE_RUNNER"
    bash -n "$PROBE_RUNNER"
    PARSE_RC=$?
    echo "MEDIA_BOOTSTRAP_PROBE_PARSE_RC=$PARSE_RC"
    [ "$PARSE_RC" -eq 0 ] || fail "MEDIA_BOOTSTRAP_PROBE_PARSE=FAIL"
fi

if [ "$FAIL" -ne 0 ]; then
    echo "LISTENER_STOP_REQUESTED=false"
    exit 1
fi

echo
echo "=== 2. VERIFY PRODUCTION LISTENER READY ==="
post_control status "$STATUS_BEFORE" 10
STATUS_RC=$?
if [ "$STATUS_RC" -eq 0 ] && status_ready "$STATUS_BEFORE"; then
    echo "MEDIA_BOOTSTRAP_LISTENER_READY_BEFORE=PASS"
    echo "MEDIA_BOOTSTRAP_RECONNECT_COUNT_BEFORE=$(json_scalar "$STATUS_BEFORE" reconnect_count)"
else
    fail "MEDIA_BOOTSTRAP_LISTENER_READY_BEFORE=FAIL"
fi

if [ "$FAIL" -ne 0 ]; then
    echo "LISTENER_STOP_REQUESTED=false"
    exit 1
fi

echo
echo "=== 3. STOP ONLY COMELIT LISTENER ==="
# Once the request is sent, restoration becomes mandatory even if HTTP fails.
LISTENER_MAY_BE_STOPPED=1
post_control stop "$STOP_RESPONSE" 20
STOP_RC=$?
echo "LISTENER_STOP_REQUESTED=true"
if [ "$STOP_RC" -eq 0 ] && status_stopped "$STOP_RESPONSE"; then
    echo "MEDIA_BOOTSTRAP_LISTENER_STOP_GATE=PASS"
else
    fail "MEDIA_BOOTSTRAP_LISTENER_STOP_GATE=FAIL"
fi

if [ "$FAIL" -ne 0 ]; then
    echo "PROBE_LIVE_INVOCATIONS=0"
    exit 1
fi

echo "MEDIA_BOOTSTRAP_LISTENER_ISOLATION_SETTLE_SECONDS=5"
sleep 5

echo
echo "=== 4. EXACTLY ONE VIP BOOTSTRAP SESSION ==="
echo "MEDIA_BOOTSTRAP_LIVE_INVOCATION_LIMIT=1"
echo "MEDIA_BOOTSTRAP_AUTO_RETRY=false"
echo "MEDIA_BOOTSTRAP_DOOR_ACTION_ALLOWED=false"
echo "MEDIA_BOOTSTRAP_SELF_ACTIVATION_ALLOWED=false"
echo "MEDIA_BOOTSTRAP_VIDEO_EVENT_ALLOWED=false"

PROBE_LIVE_INVOCATIONS=1
bash "$PROBE_RUNNER" 2>&1 | tee "$PROBE_LOG"
PROBE_RC=${PIPESTATUS[0]}
echo "MEDIA_BOOTSTRAP_INNER_RC=$PROBE_RC"

echo
echo "=== 5. RESTORE PRODUCTION LISTENER ==="
if ! restore_listener; then
    sleep 5
    restore_listener || true
fi
if [ "$RESTORE_OK" -eq 1 ]; then
    echo "MEDIA_BOOTSTRAP_LISTENER_READY_AFTER=PASS"
else
    fail "MEDIA_BOOTSTRAP_LISTENER_READY_AFTER=FAIL"
fi

echo
echo "=== 6. RESULT ==="
BOOTSTRAP_PASS_COUNT="$(grep -Fxc 'CT120_MEDIA_VIP_BOOTSTRAP_GATE=PASS' "$PROBE_LOG" 2>/dev/null || true)"
READY_COUNT="$(grep -Fxc 'V4_RING_LISTENER_READY=true' "$PROBE_LOG" 2>/dev/null || true)"
SELF_TRUE_COUNT="$(grep -Fc 'SELF_ACTIVATION_SENT=true' "$PROBE_LOG" 2>/dev/null || true)"
VIDEO_TRUE_COUNT="$(grep -Fc 'VIDEO_EVENT_SENT=true' "$PROBE_LOG" 2>/dev/null || true)"
DOOR_TRUE_COUNT="$(grep -Fc 'DOOR_ACTION_SENT=true' "$PROBE_LOG" 2>/dev/null || true)"

printf 'PROBE_LIVE_INVOCATIONS=%s\n' "$PROBE_LIVE_INVOCATIONS"
printf 'MEDIA_BOOTSTRAP_GATE_PASS_COUNT=%s\n' "$BOOTSTRAP_PASS_COUNT"
printf 'MEDIA_BOOTSTRAP_READY_COUNT=%s\n' "$READY_COUNT"
printf 'MEDIA_BOOTSTRAP_SELF_ACTIVATION_TRUE_COUNT=%s\n' "$SELF_TRUE_COUNT"
printf 'MEDIA_BOOTSTRAP_VIDEO_EVENT_TRUE_COUNT=%s\n' "$VIDEO_TRUE_COUNT"
printf 'MEDIA_BOOTSTRAP_DOOR_TRUE_COUNT=%s\n' "$DOOR_TRUE_COUNT"

if [ "$PROBE_LIVE_INVOCATIONS" -eq 1 ]; then
    echo "MEDIA_BOOTSTRAP_EXACTLY_ONCE_GATE=PASS"
else
    fail "MEDIA_BOOTSTRAP_EXACTLY_ONCE_GATE=FAIL"
fi

if [ "$BOOTSTRAP_PASS_COUNT" -eq 1 ] && [ "$READY_COUNT" -eq 1 ] && \
   [ "$SELF_TRUE_COUNT" -eq 0 ] && [ "$VIDEO_TRUE_COUNT" -eq 0 ] && \
   [ "$DOOR_TRUE_COUNT" -eq 0 ] && [ "$RESTORE_OK" -eq 1 ]; then
    echo "LISTENER_ISOLATED_MEDIA_VIP_BOOTSTRAP=PASS"
else
    fail "LISTENER_ISOLATED_MEDIA_VIP_BOOTSTRAP=FAIL"
fi

if [ "$PROBE_RC" -ne 0 ]; then
    FAIL=1
fi

echo "LISTENER_ISOLATED_MEDIA_BOOTSTRAP_RUN_ROOT=$RUN_ROOT"
echo "HOME_ASSISTANT_CORE_STOPPED=false"
echo "HOME_ASSISTANT_CORE_RESTARTED=false"
echo "DOOR_ACTION_SENT=false"
echo "SELF_ACTIVATION_SENT=false"
echo "MEDIA_SIGNALING_SENT=false"

if [ "$FAIL" -eq 0 ]; then
    exit 0
fi
exit 1
