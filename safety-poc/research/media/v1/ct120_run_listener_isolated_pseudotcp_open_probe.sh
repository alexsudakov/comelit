#!/usr/bin/env bash
# CT120 research-only controlled comparison:
#   verified HA Comelit listener READY
#   -> stop only the Comelit listener through the local test webhook
#   -> exactly one existing transport-only PseudoTCP OPEN probe
#   -> restore the Comelit listener and verify READY
#
# Home Assistant Core is never stopped or restarted. Door, self-activation and
# media application signalling remain forbidden. Listener restoration may be
# retried because it is infrastructure recovery, never a Door operation.

set -u -o pipefail
umask 077

REPO=/root/comelit-door-diag-repo
REMOTE_REF=refs/remotes/origin/main
REQUIRED_ANCESTOR=1231cdb8c468e7ca72a473807f4f16065469c4f3
CT120_IP=192.168.1.85
HA_WEBHOOK_URL=http://192.168.1.108:8123/api/webhook/comelit-ha-ring-test-control-v1
PROBE_REL=safety-poc/research/media/v1/ct120_run_pseudotcp_open_probe.sh

FAIL=0
LISTENER_STOPPED=0
RESTORE_OK=0
RESTORE_ATTEMPTS=0
PROBE_LIVE_INVOCATIONS=0
RUN_ROOT=""
STATUS_BEFORE=""
STOP_RESPONSE=""
START_RESPONSE=""
STATUS_AFTER=""
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

path = Path(sys.argv[1])
key = sys.argv[2]
try:
    data = json.loads(path.read_text(encoding="utf-8"))
except Exception:
    print("__INVALID_JSON__")
    raise SystemExit(0)

value = data.get(key, "__MISSING__")
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
      "$HA_WEBHOOK_URL" \
      > "$http_file"
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
    [ "$(json_scalar "$file" action)" = status ] &&
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
    local poll
    local status_file

    if [ "$LISTENER_STOPPED" -ne 1 ]; then
        return 0
    fi

    RESTORE_ATTEMPTS=$((RESTORE_ATTEMPTS + 1))
    echo "LISTENER_RESTORE_ATTEMPT=$RESTORE_ATTEMPTS"

    START_RESPONSE="$RUN_ROOT/listener-start-attempt-${RESTORE_ATTEMPTS}.json"
    post_control start "$START_RESPONSE" 40 || true

    for poll in 1 2 3 4 5 6 7 8; do
        status_file="$RUN_ROOT/listener-restore-status-${RESTORE_ATTEMPTS}-${poll}.json"
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
    RESTORE_OK=0
    return 1
}

on_exit() {
    local original_rc=$?

    if [ "$LISTENER_STOPPED" -eq 1 ]; then
        echo
        echo "=== EXIT RESTORE GUARD ==="
        restore_listener || true
        if [ "$LISTENER_STOPPED" -eq 1 ] && [ "$RESTORE_ATTEMPTS" -lt 3 ]; then
            sleep 5
            restore_listener || true
        fi
    fi

    echo "LISTENER_RESTORE_ATTEMPTS=$RESTORE_ATTEMPTS"
    echo "LISTENER_RESTORE_FINAL=${RESTORE_OK}"
    echo "HOME_ASSISTANT_CORE_STOPPED=false"
    echo "HOME_ASSISTANT_CORE_RESTARTED=false"
    echo "DOOR_ACTION_SENT=false"
    echo "SELF_ACTIVATION_SENT=false"
    echo "MEDIA_SIGNALING_SENT=false"

    if [ "$LISTENER_STOPPED" -eq 1 ]; then
        echo "LISTENER_RESTORE_FINAL_GATE=FAIL"
        exit 90
    fi

    exit "$original_rc"
}

trap on_exit EXIT
trap 'exit 130' INT TERM HUP

if [ "${EUID}" -ne 0 ]; then
    echo "LISTENER_ISOLATED_PROBE_REQUIRES_ROOT=true"
    exit 1
fi

for command in git python3 curl sha256sum grep tee ip; do
    if ! command -v "$command" >/dev/null 2>&1; then
        fail "LISTENER_ISOLATED_PROBE_MISSING_COMMAND=$command"
    fi
done

if [ ! -d "$REPO/.git" ]; then
    fail "LISTENER_ISOLATED_PROBE_REPO_PRESENT=false"
fi

if ! ip -4 addr show | grep -Fq "$CT120_IP/"; then
    fail "LISTENER_ISOLATED_PROBE_CT120_IDENTITY=FAIL"
else
    echo "LISTENER_ISOLATED_PROBE_CT120_IDENTITY=PASS"
fi

if ! git -C "$REPO" rev-parse --verify -q "$REMOTE_REF" >/dev/null 2>&1; then
    fail "LISTENER_ISOLATED_PROBE_REMOTE_MAIN_PRESENT=false"
fi

REMOTE_MAIN=""
if [ "$FAIL" -eq 0 ]; then
    REMOTE_MAIN="$(git -C "$REPO" rev-parse "$REMOTE_REF")"
    echo "LISTENER_ISOLATED_PROBE_REMOTE_MAIN=$REMOTE_MAIN"

    if git -C "$REPO" merge-base --is-ancestor "$REQUIRED_ANCESTOR" "$REMOTE_MAIN"; then
        echo "LISTENER_ISOLATED_PROBE_RESEARCH_ANCESTOR=PASS"
    else
        fail "LISTENER_ISOLATED_PROBE_RESEARCH_ANCESTOR=FAIL"
    fi
fi

if [ "$FAIL" -ne 0 ]; then
    echo "LISTENER_ISOLATED_PROBE_PREFLIGHT=FAIL"
    echo "LISTENER_STOP_REQUESTED=false"
    echo "PROBE_LIVE_INVOCATIONS=0"
    exit 1
fi

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
RUN_ROOT="/root/comelit-listener-isolated-open-probe-$STAMP"
STATUS_BEFORE="$RUN_ROOT/listener-status-before.json"
STOP_RESPONSE="$RUN_ROOT/listener-stop.json"
PROBE_LOG="$RUN_ROOT/probe.log"
PROBE_RUNNER="$RUN_ROOT/ct120_run_pseudotcp_open_probe.sh"
mkdir -p "$RUN_ROOT"
chmod 700 "$RUN_ROOT"

echo
echo "=== 1. MATERIALIZE PINNED PROBE RUNNER ==="

git -C "$REPO" show "$REMOTE_MAIN:$PROBE_REL" > "$PROBE_RUNNER"
RUNNER_EXTRACT_RC=$?
echo "PROBE_RUNNER_EXTRACT_RC=$RUNNER_EXTRACT_RC"

if [ "$RUNNER_EXTRACT_RC" -ne 0 ]; then
    fail "PROBE_RUNNER_EXTRACT=FAIL"
else
    chmod 700 "$PROBE_RUNNER"
    if bash -n "$PROBE_RUNNER"; then
        echo "PROBE_RUNNER_PARSE=PASS"
        echo "PROBE_RUNNER_SHA256=$(sha256sum "$PROBE_RUNNER" | awk '{print $1}')"
    else
        fail "PROBE_RUNNER_PARSE=FAIL"
    fi
fi

if [ "$FAIL" -ne 0 ]; then
    echo "LISTENER_ISOLATED_PROBE_PREFLIGHT=FAIL"
    echo "LISTENER_STOP_REQUESTED=false"
    echo "PROBE_LIVE_INVOCATIONS=0"
    exit 1
fi

echo
echo "=== 2. VERIFY CURRENT LISTENER READY ==="

post_control status "$STATUS_BEFORE" 10
STATUS_RC=$?
if [ "$STATUS_RC" -eq 0 ] && status_ready "$STATUS_BEFORE"; then
    echo "LISTENER_READY_BEFORE=PASS"
    echo "LISTENER_RECONNECT_COUNT_BEFORE=$(json_scalar "$STATUS_BEFORE" reconnect_count)"
else
    fail "LISTENER_READY_BEFORE=FAIL"
fi

if [ "$FAIL" -ne 0 ]; then
    echo "LISTENER_ISOLATED_PROBE_PREFLIGHT=FAIL"
    echo "LISTENER_STOP_REQUESTED=false"
    echo "PROBE_LIVE_INVOCATIONS=0"
    exit 1
fi

echo
echo "=== 3. STOP ONLY COMELIT LISTENER ==="

post_control stop "$STOP_RESPONSE" 20
STOP_RC=$?
echo "LISTENER_STOP_REQUESTED=true"

if [ "$STOP_RC" -eq 0 ] && status_stopped "$STOP_RESPONSE"; then
    LISTENER_STOPPED=1
    echo "LISTENER_STOP_GATE=PASS"
else
    fail "LISTENER_STOP_GATE=FAIL"
fi

if [ "$FAIL" -ne 0 ]; then
    echo "PROBE_LIVE_INVOCATIONS=0"
    exit 1
fi

# Give the peer/cloud a short, deterministic gap after the previous persistent
# P2P session has been torn down. This is not a retry and performs no action.
echo "LISTENER_ISOLATION_SETTLE_SECONDS=5"
sleep 5

echo
echo "=== 4. EXACTLY ONE TRANSPORT-ONLY OPEN PROBE ==="
echo "PROBE_LIVE_INVOCATION_LIMIT=1"
echo "PROBE_AUTO_RETRY=false"
echo "PROBE_DOOR_ACTION_ALLOWED=false"
echo "PROBE_SELF_ACTIVATION_ALLOWED=false"
echo "PROBE_MEDIA_SIGNALING_ALLOWED=false"

PROBE_LIVE_INVOCATIONS=1
bash "$PROBE_RUNNER" 2>&1 | tee "$PROBE_LOG"
PROBE_RC=${PIPESTATUS[0]}
echo "LISTENER_ISOLATED_PROBE_INNER_RC=$PROBE_RC"

echo
echo "=== 5. RESTORE COMELIT LISTENER ==="

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

echo
echo "=== 6. CONTROLLED COMPARISON ==="

OPEN_GATE_COUNT="$(grep -Fxc 'CT120_PSEUDOTCP_OPEN_GATE=PASS' "$PROBE_LOG" 2>/dev/null || true)"
CLOSED_104_COUNT="$(grep -Fxc 'PSEUDOTCP_CLOSED_CALLBACK=true ERROR=104' "$PROBE_LOG" 2>/dev/null || true)"
PRESTART_FAIL_COUNT="$(grep -Fc 'PSEUDOTCP_PRESTART_REPLAY=FAIL' "$PROBE_LOG" 2>/dev/null || true)"

printf 'PROBE_LIVE_INVOCATIONS=%s\n' "$PROBE_LIVE_INVOCATIONS"
printf 'PROBE_OPEN_GATE_PASS_COUNT=%s\n' "$OPEN_GATE_COUNT"
printf 'PROBE_CLOSED_ERROR_104_COUNT=%s\n' "$CLOSED_104_COUNT"
printf 'PROBE_PRESTART_REPLAY_FAIL_COUNT=%s\n' "$PRESTART_FAIL_COUNT"

if [ "$PROBE_LIVE_INVOCATIONS" -ne 1 ]; then
    fail "PROBE_EXACTLY_ONCE_GATE=FAIL"
else
    echo "PROBE_EXACTLY_ONCE_GATE=PASS"
fi

if [ "$OPEN_GATE_COUNT" -eq 1 ] && [ "$RESTORE_OK" -eq 1 ]; then
    echo "CONCURRENT_LISTENER_HYPOTHESIS=SUPPORTED"
    echo "CONTROLLED_COMPARISON_RESULT=PSEUDOTCP_OPEN_ONLY_WHEN_HA_LISTENER_STOPPED"
elif [ "$PROBE_RC" -ne 0 ] && [ "$RESTORE_OK" -eq 1 ]; then
    echo "CONCURRENT_LISTENER_HYPOTHESIS=NOT_SUPPORTED_BY_THIS_RUN"
    echo "CONTROLLED_COMPARISON_RESULT=PSEUDOTCP_OPEN_STILL_FAILED_WITH_HA_LISTENER_STOPPED"
else
    echo "CONCURRENT_LISTENER_HYPOTHESIS=INCONCLUSIVE"
    echo "CONTROLLED_COMPARISON_RESULT=INCONCLUSIVE"
fi

if [ "$PROBE_RC" -ne 0 ]; then
    FAIL=1
fi

if [ "$RESTORE_OK" -ne 1 ]; then
    FAIL=1
fi

echo
echo "=== FINAL ==="
echo "LISTENER_ISOLATED_PROBE_RUN_ROOT=$RUN_ROOT"
echo "HOME_ASSISTANT_CORE_STOPPED=false"
echo "HOME_ASSISTANT_CORE_RESTARTED=false"
echo "DOOR_ACTION_SENT=false"
echo "SELF_ACTIVATION_SENT=false"
echo "MEDIA_SIGNALING_SENT=false"

if [ "$FAIL" -eq 0 ]; then
    echo "LISTENER_ISOLATED_PSEUDOTCP_OPEN_PROBE=PASS"
    exit 0
fi

echo "LISTENER_ISOLATED_PSEUDOTCP_OPEN_PROBE=FAIL"
exit 1
