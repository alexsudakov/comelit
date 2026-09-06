#!/usr/bin/env bash
# CT120 research-only one-shot entrance self-activation signaling probe.
#
# Controlled sequence:
#   verify HA listener READY
#   -> stop only Comelit listener
#   -> build reviewed research candidate
#   -> exactly one P2P invocation
#   -> require 0x0028 ACK, client 0x0008 ACK, device 0x0008
#   -> candidate gracefully closes PseudoTCP
#   -> restore HA listener and verify READY
#
# No Door action is reachable.  This stage deliberately does not ACK the final
# device video event and does not capture/decode RTP/H264 media payload.

set -u -o pipefail
umask 077

REPO=/root/comelit-door-diag-repo
REMOTE_REF=refs/remotes/origin/main
REQUIRED_ANCESTOR=e535198b42461ef088b6c06d8b1a7a11df64fc28
CT120_IP=192.168.1.85
HA_WEBHOOK_URL=http://192.168.1.108:8123/api/webhook/comelit-ha-ring-test-control-v1
BASE_WRAPPER=/usr/local/sbin/comelit-p2p-cloud-probe
BASE_WRAPPER_SHA256=a564535dff0cf10b1fe4766171f2960c52fb581f1c816cf81d2992c5c84e79c9
SECRETS_FILE=/root/.config/comelit/secrets.env
SOURCE_REL=safety-poc/research/door/v1_5_7/comelit-v4-persistent-ctpp-door.c
TRANSFORM_REL=safety-poc/research/media/v1/entrance_self_activation_signaling_transform.py

FAIL=0
LISTENER_STOPPED=0
RESTORE_OK=0
RESTORE_ATTEMPTS=0
LIVE_INVOCATIONS=0
RUN_ROOT=""
WT=""
BUILD=""
LOG=""
CANDIDATE_SOURCE=""
CANDIDATE_BINARY=""
CANDIDATE_WRAPPER=""
STATUS_BEFORE=""
STATUS_AFTER=""

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

cleanup_worktree() {
    if [ -n "$WT" ] && [ -e "$WT/.git" ]; then
        if git -C "$REPO" worktree remove --force "$WT" >/dev/null 2>&1; then
            echo "ENTRANCE_SIGNALING_WORKTREE_CLEANUP=PASS"
        else
            echo "ENTRANCE_SIGNALING_WORKTREE_CLEANUP=WARNING"
        fi
    fi
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

on_exit() {
    local original_rc=$?

    cleanup_worktree

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
    echo "ENTRANCE_SIGNALING_REQUIRES_ROOT=true"
    exit 1
fi

for command in git python3 cc pkg-config sha256sum timeout strings grep tee curl ip; do
    if ! command -v "$command" >/dev/null 2>&1; then
        fail "ENTRANCE_SIGNALING_MISSING_COMMAND=$command"
    fi
done

if [ ! -d "$REPO/.git" ]; then
    fail "ENTRANCE_SIGNALING_REPO_PRESENT=false"
fi

if ! ip -4 addr show | grep -Fq "$CT120_IP/"; then
    fail "ENTRANCE_SIGNALING_CT120_IDENTITY=FAIL"
else
    echo "ENTRANCE_SIGNALING_CT120_IDENTITY=PASS"
fi

if ! git -C "$REPO" rev-parse --verify -q "$REMOTE_REF" >/dev/null 2>&1; then
    fail "ENTRANCE_SIGNALING_REMOTE_MAIN_PRESENT=false"
fi

REMOTE_MAIN=""
if [ "$FAIL" -eq 0 ]; then
    REMOTE_MAIN="$(git -C "$REPO" rev-parse "$REMOTE_REF")"
    echo "ENTRANCE_SIGNALING_REMOTE_MAIN=$REMOTE_MAIN"
    if git -C "$REPO" merge-base --is-ancestor "$REQUIRED_ANCESTOR" "$REMOTE_MAIN"; then
        echo "ENTRANCE_SIGNALING_RESEARCH_ANCESTOR=PASS"
    else
        fail "ENTRANCE_SIGNALING_RESEARCH_ANCESTOR=FAIL"
    fi
fi

if [ ! -f "$BASE_WRAPPER" ]; then
    fail "ENTRANCE_SIGNALING_BASE_WRAPPER_PRESENT=false"
else
    WRAPPER_SHA="$(sha256sum "$BASE_WRAPPER" | awk '{print $1}')"
    echo "ENTRANCE_SIGNALING_BASE_WRAPPER_SHA256=$WRAPPER_SHA"
    if [ "$WRAPPER_SHA" = "$BASE_WRAPPER_SHA256" ]; then
        echo "ENTRANCE_SIGNALING_BASE_WRAPPER_PIN=PASS"
    else
        fail "ENTRANCE_SIGNALING_BASE_WRAPPER_PIN=FAIL"
    fi
fi

if [ ! -f "$SECRETS_FILE" ]; then
    fail "ENTRANCE_SIGNALING_SECRETS_PRESENT=false"
else
    echo "ENTRANCE_SIGNALING_SECRETS_PRESENT=true"
    echo "ENTRANCE_SIGNALING_SECRETS_CONTENT_EMITTED=false"
fi

if pkg-config --exists nice glib-2.0 gio-2.0 gobject-2.0; then
    echo "ENTRANCE_SIGNALING_BUILD_DEPS=PASS"
else
    fail "ENTRANCE_SIGNALING_BUILD_DEPS=FAIL"
fi

if [ "$FAIL" -ne 0 ]; then
    echo "ENTRANCE_SIGNALING_PREFLIGHT=FAIL"
    exit 1
fi

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
RUN_ROOT="/root/comelit-entrance-signaling-probe-$STAMP"
WT="$RUN_ROOT/repo"
BUILD="$RUN_ROOT/build"
LOG="$RUN_ROOT/live.log"
CANDIDATE_SOURCE="$BUILD/comelit-entrance-signaling.c"
CANDIDATE_BINARY="$BUILD/comelit-entrance-signaling"
CANDIDATE_WRAPPER="$BUILD/comelit-p2p-cloud-probe-entrance-signaling"
STATUS_BEFORE="$RUN_ROOT/listener-status-before.json"
mkdir -p "$BUILD"
chmod 700 "$RUN_ROOT" "$BUILD"

if git -C "$REPO" worktree add --detach "$WT" "$REMOTE_MAIN" >/dev/null; then
    echo "ENTRANCE_SIGNALING_WORKTREE_CREATE=PASS"
else
    fail "ENTRANCE_SIGNALING_WORKTREE_CREATE=FAIL"
fi

SOURCE="$WT/$SOURCE_REL"
TRANSFORM="$WT/$TRANSFORM_REL"
if [ ! -f "$SOURCE" ] || [ ! -f "$TRANSFORM" ]; then
    fail "ENTRANCE_SIGNALING_RESEARCH_FILES_PRESENT=false"
fi

if [ "$FAIL" -eq 0 ]; then
    python3 "$TRANSFORM" \
      --source "$SOURCE" \
      --output "$CANDIDATE_SOURCE" \
      | tee "$RUN_ROOT/transform.log"
    TRANSFORM_RC=${PIPESTATUS[0]}
    echo "ENTRANCE_SIGNALING_TRANSFORM_RC=$TRANSFORM_RC"
    [ "$TRANSFORM_RC" -eq 0 ] || FAIL=1
fi

if [ "$FAIL" -eq 0 ]; then
    if grep -Fq 'signal(SIGUSR1, v4_door_signal_handler);' "$CANDIDATE_SOURCE"; then
        fail "ENTRANCE_SIGNALING_DOOR_SIGNAL_GATE=FAIL"
    else
        echo "ENTRANCE_SIGNALING_DOOR_SIGNAL_GATE=PASS"
    fi

    if grep -Fq $'        100,\n        v4_door_tick_cb,' "$CANDIDATE_SOURCE"; then
        fail "ENTRANCE_SIGNALING_DOOR_TIMER_GATE=FAIL"
    else
        echo "ENTRANCE_SIGNALING_DOOR_TIMER_GATE=PASS"
    fi

    if grep -Fq '        3300,' "$CANDIDATE_SOURCE"; then
        fail "ENTRANCE_SIGNALING_LONG_TIMEOUT_GATE=FAIL"
    else
        echo "ENTRANCE_SIGNALING_LONG_TIMEOUT_GATE=PASS"
    fi

    for marker in \
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
    do
        if grep -Fq "$marker" "$CANDIDATE_SOURCE"; then
            echo "ENTRANCE_SIGNALING_SOURCE_MARKER=PASS $marker"
        else
            fail "ENTRANCE_SIGNALING_SOURCE_MARKER=FAIL $marker"
        fi
    done
fi

if [ "$FAIL" -eq 0 ]; then
    cc -O2 -g -Wall -Wextra \
      -o "$CANDIDATE_BINARY" \
      "$CANDIDATE_SOURCE" \
      $(pkg-config --cflags --libs nice glib-2.0 gio-2.0 gobject-2.0) \
      2>"$RUN_ROOT/compile.stderr"
    BUILD_RC=$?
    cat "$RUN_ROOT/compile.stderr"
    echo "ENTRANCE_SIGNALING_BUILD_RC=$BUILD_RC"
    [ "$BUILD_RC" -eq 0 ] || FAIL=1
fi

if [ "$FAIL" -eq 0 ]; then
    chmod 700 "$CANDIDATE_BINARY"
    strings -a "$CANDIDATE_BINARY" > "$RUN_ROOT/candidate.strings"
    STRINGS_RC=$?
    echo "ENTRANCE_SIGNALING_STRINGS_RC=$STRINGS_RC"
    [ "$STRINGS_RC" -eq 0 ] || FAIL=1
fi

if [ "$FAIL" -eq 0 ]; then
    for marker in \
      'ENTRANCE_SIGNALING_PROBE_RESULT=PASS' \
      'ENTRANCE_FINAL_DEVICE_VIDEO_ACK_SENT=false' \
      'ENTRANCE_MEDIA_PAYLOAD_CAPTURED=false' \
      'ENTRANCE_SIGNALING_DOOR_ACTION_SENT=false' \
      'PSEUDOTCP_GRACEFUL_CLOSE_FORCE=false'
    do
        if grep -Fq "$marker" "$RUN_ROOT/candidate.strings"; then
            echo "ENTRANCE_SIGNALING_BINARY_MARKER=PASS $marker"
        else
            fail "ENTRANCE_SIGNALING_BINARY_MARKER=FAIL $marker"
        fi
    done
fi

if [ "$FAIL" -eq 0 ]; then
    python3 - "$BASE_WRAPPER" "$CANDIDATE_WRAPPER" "$CANDIDATE_BINARY" <<'PY'
from pathlib import Path
import sys

source = Path(sys.argv[1]).read_text(encoding="utf-8")
needle = '"$BASE/bin/comelit_ice_offer_holder"'
if source.count(needle) != 1:
    raise SystemExit("ENTRANCE_SIGNALING_WRAPPER_HOLDER_ANCHOR=FAIL")
Path(sys.argv[2]).write_text(source.replace(needle, f'"{sys.argv[3]}"', 1), encoding="utf-8")
PY
    REWRITE_RC=$?
    echo "ENTRANCE_SIGNALING_WRAPPER_REWRITE_RC=$REWRITE_RC"
    if [ "$REWRITE_RC" -eq 0 ]; then
        chmod 700 "$CANDIDATE_WRAPPER"
        bash -n "$CANDIDATE_WRAPPER" || FAIL=1
    else
        FAIL=1
    fi
fi

if [ "$FAIL" -ne 0 ]; then
    echo "ENTRANCE_SIGNALING_PREFLIGHT=FAIL"
    exit 1
fi

echo "ENTRANCE_SIGNALING_PREFLIGHT=PASS"
echo "ENTRANCE_SIGNALING_RUN_ROOT=$RUN_ROOT"

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
STOP_RESPONSE="$RUN_ROOT/listener-stop.json"
# Treat the stop request as potentially accepted even if the HTTP response is
# lost: from here the EXIT guard must restore the listener.
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

echo
echo "=== ONE-SHOT ENTRANCE SIGNALING LIVE RUN ==="
echo "ENTRANCE_SIGNALING_LIVE_INVOCATION_LIMIT=1"
echo "ENTRANCE_SIGNALING_AUTO_RETRY=false"
echo "ENTRANCE_SIGNALING_DOOR_ACTION_ALLOWED=false"
echo "ENTRANCE_SIGNALING_FINAL_DEVICE_VIDEO_ACK_ALLOWED=false"
echo "ENTRANCE_SIGNALING_MEDIA_PAYLOAD_CAPTURE_ALLOWED=false"

LIVE_INVOCATIONS=1
timeout --signal=TERM --kill-after=5s 75s "$CANDIDATE_WRAPPER" 2>&1 | tee "$LOG"
LIVE_RC=${PIPESTATUS[0]}
echo "ENTRANCE_SIGNALING_WRAPPER_RC=$LIVE_RC"

required_markers=(
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

LIVE_GATE=PASS
for marker in "${required_markers[@]}"; do
    COUNT="$(grep -Fxc "$marker" "$LOG" 2>/dev/null || true)"
    echo "ENTRANCE_SIGNALING_LIVE_MARKER_COUNT=$COUNT $marker"
    if [ "$COUNT" -ne 1 ]; then
        LIVE_GATE=FAIL
    fi
done

SELF_SENT_COUNT="$(grep -Fxc 'ENTRANCE_SELF_ACTIVATION_SENT=PASS' "$LOG" 2>/dev/null || true)"
VIDEO_SENT_COUNT="$(grep -Fxc 'ENTRANCE_VIDEO_EVENT_SENT=PASS' "$LOG" 2>/dev/null || true)"
DOOR_RESULT_COUNT="$(grep -Fc 'V4_DOOR_RESULT=' "$LOG" 2>/dev/null || true)"

printf 'ENTRANCE_SELF_ACTIVATION_SENT_COUNT=%s\n' "$SELF_SENT_COUNT"
printf 'ENTRANCE_VIDEO_EVENT_SENT_COUNT=%s\n' "$VIDEO_SENT_COUNT"
printf 'ENTRANCE_DOOR_RESULT_MARKER_COUNT=%s\n' "$DOOR_RESULT_COUNT"

if [ "$SELF_SENT_COUNT" -ne 1 ] ||
   [ "$VIDEO_SENT_COUNT" -ne 1 ] ||
   [ "$DOOR_RESULT_COUNT" -ne 0 ]; then
    LIVE_GATE=FAIL
fi

echo "ENTRANCE_SIGNALING_LIVE_GATE=$LIVE_GATE"

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

if [ "$LIVE_INVOCATIONS" -ne 1 ]; then
    fail "ENTRANCE_SIGNALING_EXACTLY_ONCE_GATE=FAIL"
else
    echo "ENTRANCE_SIGNALING_EXACTLY_ONCE_GATE=PASS"
fi

if [ "$LIVE_GATE" != PASS ]; then
    FAIL=1
fi

if [ "$RESTORE_OK" -ne 1 ]; then
    FAIL=1
fi

echo
echo "=== FINAL ==="
echo "ENTRANCE_SIGNALING_RUN_ROOT=$RUN_ROOT"
echo "SELF_ACTIVATION_SENT=$([ "$SELF_SENT_COUNT" -eq 1 ] && echo true || echo false)"
echo "CLIENT_VIDEO_SIGNALING_SENT=$([ "$VIDEO_SENT_COUNT" -eq 1 ] && echo true || echo false)"
echo "FINAL_DEVICE_VIDEO_ACK_SENT=false"
echo "MEDIA_PAYLOAD_CAPTURED=false"
echo "DOOR_ACTION_SENT=false"
echo "HOME_ASSISTANT_CORE_STOPPED=false"
echo "HOME_ASSISTANT_CORE_RESTARTED=false"

if [ "$FAIL" -eq 0 ]; then
    echo "ENTRANCE_SELF_ACTIVATION_SIGNALING_PROBE=PASS"
    exit 0
fi

echo "ENTRANCE_SELF_ACTIVATION_SIGNALING_PROBE=FAIL"
exit 1
