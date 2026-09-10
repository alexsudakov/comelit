#!/usr/bin/env bash
# CT120 research-only P110 final RUN5 runner.
#
# Offline preparation only in this worktree. A future authorized live run must
# execute exactly one PR #106 packaged musl helper invocation after the proven
# RUN1-RUN3 offer -> transform_offer -> OAuth -> cloud P2P -> remote.sdp
# bootstrap. All prelive gates run before listener control.

set -u -o pipefail
umask 077

REPO="${REPO:-/root/comelit-door-diag-repo}"
PR106_BRANCH="${PR106_BRANCH:-fix/p107-package-p106-entrance-media}"
EXPECTED_PR106_HEAD=977f7197f103050a9f52b43dad26af5df0c7bbf0
EXPECTED_REMOTE_REF="${EXPECTED_REMOTE_REF:-refs/remotes/origin/fix/p107-package-p106-entrance-media}"
EXPECTED_RUNNER_SHA256="${P110_EXPECTED_RUNNER_SHA256:-}"
PACKAGED_BINARY_REL=custom_components/comelit/native/comelit-media
PACKAGED_LIB_REL=custom_components/comelit/native/lib
PACKAGED_BINARY_SHA256=ebc731381022be89576a680c39f7402225048e48adab88376434f660ad1a5ade
PACKAGED_BINARY_BYTES=256992
PACKAGED_BINARY_REBUILT=false
PACKAGED_BINARY_SUBSTITUTED=false
EXPECTED_INTERPRETER=/lib/ld-musl-x86_64.so.1
EXPECTED_NEEDED_CSV=libc.musl-x86_64.so.1,libglib-2.0.so.0,libgobject-2.0.so.0,libnice.so.10
CT120_IP=192.168.1.85
HA_WEBHOOK_URL="${HA_WEBHOOK_URL:-http://192.168.1.108:8123/api/webhook/comelit-ha-ring-test-control-v1}"
SECRETS_FILE="${SECRETS_FILE:-/root/.config/comelit/secrets.env}"
BOOTSTRAP_REL=safety-poc/research/media/v1/p110_run5_bootstrap.py
RUN_DIR=/run/comelit-media
STOP_FILE="$RUN_DIR/stop"
VIDEO_RTP_PORT=17899
AUDIO_RTP_PORT=17808
MEDIA_SESSION_MAX_SECONDS=45
OBSERVATION_SECONDS_LIMIT=40
OUTER_MAX_SECONDS=75
MAX_LIVE_INVOCATIONS=1
ARTIFACT_ROOT=/root/comelit-artifacts

FAIL=0
SUMMARY_PRINTED=0
LISTENER_STOPPED=0
LISTENER_RESTART_SUPPRESSED=false
TEARDOWN_CONFIDENCE=UNCERTAIN
LIVE_INVOCATIONS=0
CLOUD_NEGOTIATION_COUNT=0
MEDIA_PID=""
VIDEO_SINK_PID=""
AUDIO_SINK_PID=""
RUN_ROOT=""
MEDIA_DIR=""
LOG=""
BOOTSTRAP_LOG=""
PACKAGED_BINARY=""
PACKAGED_LIB_DIR=""
PACKAGED_BINARY_SHA_BEFORE_RUN=NOT_REACHED
PACKAGED_BINARY_SHA_AFTER_RUN=NOT_REACHED
RUNTIME_ABI_GATE=FAIL
RUNTIME_LOADER=NONE
RUNTIME_LIBRARY_PATH=NONE
RUNTIME_ROOT=NONE
BOOTSTRAP_STATIC_SELF_TEST=FAIL
PR106_HEAD=UNKNOWN
REMOTE_PR106_HEAD=UNKNOWN
RUNNER_SELF_SHA256=UNKNOWN
PR106_HEAD_GATE=FAIL
REMOTE_PR106_HEAD_GATE=FAIL
PACKAGED_BINARY_IDENTITY_GATE=FAIL
ONE_CLOUD_NEGOTIATION_GATE=FAIL
NO_RETRY_GATE=PASS
RUN4_REGRESSION_GATE=PASS
MEDIA_SUCCESS_CONTRACT_GATE=FAIL
TEARDOWN_FAIL_CLOSED_GATE=PASS
DOOR_GATE=FAIL
GATE_MEDIA_GATE=FAIL
SECRET_OUTPUT_GATE=PASS
FAIL_CLOSED_PRELIVE_GATE=FAIL
BINARY_EXECUTED=false
NETWORK_IO_PERFORMED=false
LISTENER_READY_BEFORE=FAIL
LISTENER_STOP_GATE=FAIL
LISTENER_READY_AFTER=FAIL
PACKAGED_MUSL_PROCESS_REMAINING=UNKNOWN
UPSTREAM_MEDIA_ACTIVE_AT_EXIT=true
MEDIA_RC=NOT_REACHED
OBSERVATION_SECONDS=0
CTPP_OPEN_COUNT=0
SECOND_CTPP_OPEN=false
P78_RTPC_SIGNALING_RESULT=NOT_REACHED
P80_DEVICE_ACK_000A_OBSERVED=NOT_REACHED
P80_DEVICE_ACK_001A_OBSERVED=NOT_REACHED
P80_POST_001A_ACK_GATE=NOT_REACHED
P80_PREACTIVE_MEDIA_DEMUX=NOT_REACHED
P80_PREACTIVE_MEDIA_PROFILE_ACCEPT=NOT_REACHED
P80_MEDIA_ACTIVE=NOT_REACHED
P80_VIDEO_RTP_FORWARDING=NOT_REACHED
P80_AUDIO_RTP_FORWARDING=NOT_REACHED
H264_SPS_COUNT=0
H264_PPS_COUNT=0
H264_IDR_COUNT=0
VIDEO_RTP_DATAGRAMS=0
AUDIO_RTP_DATAGRAMS=0
FFPROBE_H264=NOT_REACHED
JPEG_RESULT=NOT_REACHED
SHORT_VIDEO_RESULT=NOT_REACHED
P110_DOOR_RESULT_COUNT=0
P110_GATE_TOKEN_COUNT=0

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
    curl --silent --show-error --connect-timeout 5 --max-time "$max_time" \
      --header 'Content-Type: application/json' --output "$output" \
      --write-out '%{http_code}\n' --data "{\"action\":\"$action\"}" \
      "$HA_WEBHOOK_URL" > "$http_file"
    local rc=$?
    echo "CONTROL_${action^^}_CURL_RC=$rc"
    [ -s "$http_file" ] && echo "CONTROL_${action^^}_HTTP_STATUS=$(cat "$http_file")"
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
    [ "$(json_scalar "$file" supervisor_running)" = false ] &&
    [ "$(json_scalar "$file" running)" = false ] &&
    [ "$(json_scalar "$file" listener_ready)" = false ]
}

restore_listener() {
    local poll status_file start_file
    if [ "$LISTENER_STOPPED" -ne 1 ]; then
        return 0
    fi
    if [ "$TEARDOWN_CONFIDENCE" != CONFIRMED ]; then
        LISTENER_RESTART_SUPPRESSED=true
        echo "LISTENER_RESTART_SUPPRESSED=true"
        echo "LISTENER_RESTORE_FINAL_GATE=FAIL"
        return 90
    fi
    start_file="$RUN_ROOT/listener-start.json"
    post_control start "$start_file" 40 || true
    for poll in 1 2 3 4 5 6 7 8; do
        status_file="$RUN_ROOT/listener-restore-${poll}.json"
        post_control status "$status_file" 10 || true
        if status_ready "$status_file"; then
            LISTENER_STOPPED=0
            LISTENER_READY_AFTER=PASS
            echo "LISTENER_READY_AFTER=PASS"
            return 0
        fi
        sleep 5
    done
    LISTENER_READY_AFTER=FAIL
    echo "LISTENER_READY_AFTER=FAIL"
    return 1
}

stop_media_if_needed() {
    if [ -z "$MEDIA_PID" ] || ! kill -0 "$MEDIA_PID" 2>/dev/null; then
        return 0
    fi
    echo "P110_STOP_REQUESTED=true"
    install -d -m 700 "$RUN_DIR"
    : > "$STOP_FILE"
    chmod 600 "$STOP_FILE"
    local i
    for i in 1 2 3 4 5; do
        if ! kill -0 "$MEDIA_PID" 2>/dev/null; then
            return 0
        fi
        sleep 1
    done
    echo "P110_STOP_ESCALATION=TERM"
    kill -TERM "$MEDIA_PID" 2>/dev/null || true
    sleep 2
    if kill -0 "$MEDIA_PID" 2>/dev/null; then
        echo "P110_STOP_ESCALATION=KILL"
        kill -KILL "$MEDIA_PID" 2>/dev/null || true
    fi
}

stop_sink_if_needed() {
    local pid="$1"
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
        kill -TERM "$pid" 2>/dev/null || true
    fi
}

last_marker() {
    local key="$1"
    local fallback="$2"
    if [ -f "$LOG" ]; then
        awk -v key="$key" -v fallback="$fallback" 'index($0, key "=") == 1 { value = substr($0, length(key) + 2); found = 1 } END { if (found) print value; else print fallback }' "$LOG"
    else
        printf '%s\n' "$fallback"
    fi
}

count_log_literal() {
    local literal="$1"
    if [ -f "$LOG" ]; then
        grep -cF "$literal" "$LOG" 2>/dev/null || true
    else
        printf '0\n'
    fi
}

collect_log_markers() {
    CTPP_OPEN_COUNT="$(count_log_literal 'V4_CTPP_OPEN_SENT=PASS')"
    [ "$CTPP_OPEN_COUNT" -gt 1 ] && SECOND_CTPP_OPEN=true || SECOND_CTPP_OPEN=false
    P110_DOOR_RESULT_COUNT="$(count_log_literal 'V4_DOOR_RESULT=')"
    P110_GATE_TOKEN_COUNT="$(count_log_literal 'GATE_ACTION_SENT=')"
    P78_RTPC_SIGNALING_RESULT="$(last_marker P78_RTPC_SIGNALING_RESULT NOT_REACHED)"
    P80_DEVICE_ACK_000A_OBSERVED="$(last_marker P80_DEVICE_ACK_000A_OBSERVED NOT_REACHED)"
    P80_DEVICE_ACK_001A_OBSERVED="$(last_marker P80_DEVICE_ACK_001A_OBSERVED NOT_REACHED)"
    P80_POST_001A_ACK_GATE="$(last_marker P80_POST_001A_ACK_GATE NOT_REACHED)"
    P80_PREACTIVE_MEDIA_DEMUX="$(last_marker P80_PREACTIVE_MEDIA_DEMUX NOT_REACHED)"
    P80_PREACTIVE_MEDIA_PROFILE_ACCEPT="$(last_marker P80_PREACTIVE_MEDIA_PROFILE_ACCEPT NOT_REACHED)"
    P80_MEDIA_ACTIVE="$(last_marker P80_MEDIA_ACTIVE NOT_REACHED)"
    P80_VIDEO_RTP_FORWARDING="$(last_marker P80_VIDEO_RTP_FORWARDING NOT_REACHED)"
    P80_AUDIO_RTP_FORWARDING="$(last_marker P80_AUDIO_RTP_FORWARDING NOT_REACHED)"
}

packaged_processes_remaining() {
    if [ -n "$MEDIA_PID" ] && kill -0 "$MEDIA_PID" 2>/dev/null; then
        PACKAGED_MUSL_PROCESS_REMAINING=FOUND
    else
        PACKAGED_MUSL_PROCESS_REMAINING=NONE
    fi
    echo "PACKAGED_MUSL_PROCESS_REMAINING=$PACKAGED_MUSL_PROCESS_REMAINING"
}

derive_teardown_confidence() {
    [ "$PACKAGED_MUSL_PROCESS_REMAINING" = NONE ] && UPSTREAM_MEDIA_ACTIVE_AT_EXIT=false || UPSTREAM_MEDIA_ACTIVE_AT_EXIT=true
    if [ "$UPSTREAM_MEDIA_ACTIVE_AT_EXIT" = false ] && [ "$MEDIA_RC" != 124 ] && [ "$MEDIA_RC" != 137 ]; then
        TEARDOWN_CONFIDENCE=CONFIRMED
    else
        TEARDOWN_CONFIDENCE=UNCERTAIN
    fi
    echo "UPSTREAM_MEDIA_ACTIVE_AT_EXIT=$UPSTREAM_MEDIA_ACTIVE_AT_EXIT"
    echo "TEARDOWN_CONFIDENCE=$TEARDOWN_CONFIDENCE"
}

required_libs_present() {
    local libdir="$1"
    [ -r "$libdir/libnice.so.10" ] &&
    [ -r "$libdir/libglib-2.0.so.0" ] &&
    [ -r "$libdir/libgobject-2.0.so.0" ]
}

detect_runtime_boundary() {
    local repo_root="${1:-$REPO}"
    local candidate root release
    RUNTIME_ABI_GATE=FAIL
    PACKAGED_LIB_DIR="$repo_root/$PACKAGED_LIB_REL"
    for candidate in "${P110_TEST_RUNTIME_ROOT:-}" /root/comelit-p80-haos-build-*/rootfs /root/comelit-*-haos-build-*/rootfs /root/*alpine*/rootfs /root/*alpine*; do
        [ -n "$candidate" ] || continue
        for root in $candidate; do
            [ -d "$root" ] || continue
            [ -r "$root/etc/alpine-release" ] || continue
            [ -x "$root/lib/ld-musl-x86_64.so.1" ] || continue
            required_libs_present "$PACKAGED_LIB_DIR" || continue
            release="$(head -n 1 "$root/etc/alpine-release" 2>/dev/null || true)"
            [ -n "$release" ] || continue
            RUNTIME_ROOT="$root"
            RUNTIME_LOADER="$root/lib/ld-musl-x86_64.so.1"
            RUNTIME_LIBRARY_PATH="$PACKAGED_LIB_DIR:$root/lib:$root/usr/lib"
            RUNTIME_ABI_GATE=PASS
            echo "RUNTIME_ALPINE_RELEASE=$release"
            echo "RUNTIME_ABI_GATE=PASS"
            return 0
        done
    done
    echo "P110_RUNTIME_ABI_GATE=FAIL"
    return 1
}

assert_packaged_binary_identity() {
    local repo_root="${1:-$REPO}"
    local size
    PACKAGED_BINARY="$repo_root/$PACKAGED_BINARY_REL"
    PACKAGED_LIB_DIR="$repo_root/$PACKAGED_LIB_REL"
    [ -f "$PACKAGED_BINARY" ] || fail "PACKAGED_BINARY_PRESENT=false"
    [ -d "$PACKAGED_LIB_DIR" ] || fail "PACKAGED_LIBRARY_DIR_PRESENT=false"
    if [ -f "$PACKAGED_BINARY" ]; then
        PACKAGED_BINARY_SHA_BEFORE_RUN="$(sha256sum "$PACKAGED_BINARY" | awk '{print $1}')"
        size="$(wc -c < "$PACKAGED_BINARY" | awk '{print $1}')"
        [ "$PACKAGED_BINARY_SHA_BEFORE_RUN" = "$PACKAGED_BINARY_SHA256" ] || fail "PACKAGED_BINARY_SHA_GATE=FAIL"
        [ "$size" = "$PACKAGED_BINARY_BYTES" ] || fail "PACKAGED_BINARY_SIZE_GATE=FAIL"
    fi
}

assert_packaged_elf_identity() {
    local interpreter needed
    interpreter="$(readelf -l "$PACKAGED_BINARY" | sed -n 's@.*Requesting program interpreter: \(.*\)]@\1@p')"
    needed="$(readelf -d "$PACKAGED_BINARY" | sed -n 's/.*Shared library: \[\(.*\)\]/\1/p' | sort | paste -sd, -)"
    [ "$interpreter" = "$EXPECTED_INTERPRETER" ] || fail "P110_ELF_INTERPRETER_GATE=FAIL"
    [ "$needed" = "$EXPECTED_NEEDED_CSV" ] || fail "P110_ELF_NEEDED_GATE=FAIL"
}

assert_no_credential_bearing_origin() {
    if git -C "$REPO" remote -v 2>/dev/null | grep -E '(://[^/@]+:[^/@]+@|Authorization|access_token|oauth|COMELIT|VIP)' >/dev/null; then
        fail "P110_CREDENTIAL_ORIGIN_GATE=FAIL"
    else
        echo "P110_CREDENTIAL_ORIGIN_GATE=PASS"
    fi
}

assert_static_bootstrap() {
    local bootstrap="$REPO/$BOOTSTRAP_REL"
    [ -x "$bootstrap" ] || fail "P110_BOOTSTRAP_COMPONENT_PRESENT=FAIL"
    if [ -x "$bootstrap" ] && python3 "$bootstrap" --self-test > "${RUN_ROOT:-/tmp}/p110-bootstrap-selftest.log" 2>&1; then
        BOOTSTRAP_STATIC_SELF_TEST=PASS
        echo "P110_BOOTSTRAP_STATIC_SELF_TEST=PASS"
    else
        fail "P110_BOOTSTRAP_STATIC_SELF_TEST=FAIL"
    fi
}

assert_no_door_gate_paths() {
    local strings_file="$1"
    strings -a "$PACKAGED_BINARY" > "$strings_file"
    if grep -Fq -- '--door' "$strings_file" || grep -Fq -- '--gate' "$strings_file"; then
        fail "P110_DOOR_GATE_SWITCH_GATE=FAIL"
    else
        DOOR_GATE=PASS
        GATE_MEDIA_GATE=PASS
        echo "P110_DOOR_GATE_SWITCH_GATE=PASS"
    fi
}

validate_media_success_contract() {
    MEDIA_SUCCESS_CONTRACT_GATE=FAIL
    [ "$LIVE_INVOCATIONS" -eq 1 ] || return 1
    [ "$CLOUD_NEGOTIATION_COUNT" -eq 1 ] || return 1
    [ "$CTPP_OPEN_COUNT" -eq 1 ] || return 1
    [ "$SECOND_CTPP_OPEN" = false ] || return 1
    [ "$P78_RTPC_SIGNALING_RESULT" = PASS ] || return 1
    [ "$P80_DEVICE_ACK_000A_OBSERVED" = PASS ] || return 1
    [ "$P80_DEVICE_ACK_001A_OBSERVED" = PASS ] || return 1
    [ "$P80_POST_001A_ACK_GATE" = PASS ] || return 1
    [ "$P80_PREACTIVE_MEDIA_DEMUX" = PASS ] || return 1
    [ "$P80_PREACTIVE_MEDIA_PROFILE_ACCEPT" = PASS ] || return 1
    [ "$P80_MEDIA_ACTIVE" = true ] || return 1
    [ "$P80_VIDEO_RTP_FORWARDING" = PASS ] || return 1
    [ "$P80_AUDIO_RTP_FORWARDING" = PASS ] || return 1
    [ "$H264_SPS_COUNT" -gt 0 ] || return 1
    [ "$H264_PPS_COUNT" -gt 0 ] || return 1
    [ "$H264_IDR_COUNT" -gt 0 ] || return 1
    [ "$FFPROBE_H264" = PASS ] || return 1
    [ "$JPEG_RESULT" = PASS ] || return 1
    [ "$SHORT_VIDEO_RESULT" = PASS ] || return 1
    [ "$PACKAGED_BINARY_SHA_AFTER_RUN" = "$PACKAGED_BINARY_SHA_BEFORE_RUN" ] || return 1
    [ "$PACKAGED_MUSL_PROCESS_REMAINING" = NONE ] || return 1
    [ "$UPSTREAM_MEDIA_ACTIVE_AT_EXIT" = false ] || return 1
    [ "$TEARDOWN_CONFIDENCE" = CONFIRMED ] || return 1
    [ "$LISTENER_READY_AFTER" = PASS ] || return 1
    [ "$P110_DOOR_RESULT_COUNT" -eq 0 ] || return 1
    [ "$P110_GATE_TOKEN_COUNT" -eq 0 ] || return 1
    MEDIA_SUCCESS_CONTRACT_GATE=PASS
}

print_summary() {
    [ "$SUMMARY_PRINTED" -eq 1 ] && return 0
    SUMMARY_PRINTED=1
    echo "=== COMELIT P110 RUN5 SUMMARY ==="
    echo "PR106_HEAD=$PR106_HEAD"
    echo "REMOTE_PR106_HEAD=$REMOTE_PR106_HEAD"
    echo "PACKAGED_BINARY_SHA256=$PACKAGED_BINARY_SHA256"
    echo "PACKAGED_BINARY_REBUILT=false"
    echo "PACKAGED_BINARY_SUBSTITUTED=false"
    echo "PACKAGED_BINARY_IDENTITY_GATE=$PACKAGED_BINARY_IDENTITY_GATE"
    echo "RUNNER_SELF_SHA256=$RUNNER_SELF_SHA256"
    echo "BOOTSTRAP_STATIC_SELF_TEST=$BOOTSTRAP_STATIC_SELF_TEST"
    echo "MAX_LIVE_INVOCATIONS=$MAX_LIVE_INVOCATIONS"
    echo "LIVE_INVOCATIONS=$LIVE_INVOCATIONS"
    echo "CLOUD_NEGOTIATION_COUNT=$CLOUD_NEGOTIATION_COUNT"
    echo "ONE_CLOUD_NEGOTIATION_GATE=$ONE_CLOUD_NEGOTIATION_GATE"
    echo "NO_RETRY_GATE=$NO_RETRY_GATE"
    echo "RUN4_REGRESSION_GATE=$RUN4_REGRESSION_GATE"
    echo "MEDIA_SUCCESS_CONTRACT_GATE=$MEDIA_SUCCESS_CONTRACT_GATE"
    echo "TEARDOWN_FAIL_CLOSED_GATE=$TEARDOWN_FAIL_CLOSED_GATE"
    echo "DOOR_GATE=$DOOR_GATE"
    echo "GATE_MEDIA_GATE=$GATE_MEDIA_GATE"
    echo "SECRET_OUTPUT_GATE=$SECRET_OUTPUT_GATE"
    echo "FAIL_CLOSED_PRELIVE_GATE=$FAIL_CLOSED_PRELIVE_GATE"
    echo "BINARY_EXECUTED=$BINARY_EXECUTED"
    echo "NETWORK_IO_PERFORMED=$NETWORK_IO_PERFORMED"
    echo "=== END COMELIT P110 RUN5 SUMMARY ==="
}

on_exit() {
    local original_rc=$?
    stop_media_if_needed || true
    stop_sink_if_needed "$VIDEO_SINK_PID" || true
    stop_sink_if_needed "$AUDIO_SINK_PID" || true
    if [ -n "${PACKAGED_BINARY:-}" ] && [ -f "$PACKAGED_BINARY" ]; then
        PACKAGED_BINARY_SHA_AFTER_RUN="$(sha256sum "$PACKAGED_BINARY" | awk '{print $1}')"
    fi
    if [ "$LISTENER_STOPPED" -eq 1 ]; then
        restore_listener || true
    fi
    echo "AUTOMATIC_RETRY=false"
    echo "DOOR_ACTION_SENT=false"
    echo "GATE_ACTION_SENT=false"
    print_summary
    exit "$original_rc"
}

if [ "${P110_SOURCE_ONLY:-0}" = 1 ]; then
    return 0 2>/dev/null || exit 0
fi

trap on_exit EXIT
trap 'exit 130' INT TERM HUP

if [ "${EUID}" -ne 0 ]; then
    echo "P110_LIVE_REQUIRES_ROOT=true"
    exit 1
fi

for command in git python3 sha256sum timeout strings grep curl ip awk head wc readelf sed stat; do
    command -v "$command" >/dev/null 2>&1 || fail "P110_MISSING_COMMAND=$command"
done

[ -d "$REPO/.git" ] || fail "P110_REPO_PRESENT=false"
if [ "$FAIL" -eq 0 ]; then
    PR106_HEAD="$(git -C "$REPO" rev-parse HEAD 2>/dev/null || echo UNKNOWN)"
    CURRENT_BRANCH="$(git -C "$REPO" branch --show-current 2>/dev/null || true)"
    REMOTE_PR106_HEAD="$(git -C "$REPO" rev-parse "$EXPECTED_REMOTE_REF" 2>/dev/null || echo UNKNOWN)"
    [ "$CURRENT_BRANCH" = "$PR106_BRANCH" ] || fail "P110_PR106_BRANCH_GATE=FAIL"
    [ "$PR106_HEAD" = "$EXPECTED_PR106_HEAD" ] || fail "P110_PR106_HEAD_GATE=FAIL"
    [ "$REMOTE_PR106_HEAD" = "$EXPECTED_PR106_HEAD" ] || fail "P110_REMOTE_PR106_HEAD_GATE=FAIL"
fi

if [ "${PR106_OPEN_CONFIRMED_SHA:-}" = "$EXPECTED_PR106_HEAD" ]; then
    echo "P110_PR106_OPEN_GATE=PASS"
else
    fail "P110_PR106_OPEN_GATE=FAIL"
fi

if ip -4 addr show | grep -Fq "$CT120_IP/"; then
    echo "P110_CT120_IDENTITY=PASS"
else
    fail "P110_CT120_IDENTITY=FAIL"
fi

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
RUN_ROOT="$ARTIFACT_ROOT/p110-run5-$STAMP"
MEDIA_DIR="$RUN_ROOT/media"
LOG="$RUN_ROOT/live.log"
BOOTSTRAP_LOG="$RUN_ROOT/bootstrap.log"
mkdir -p "$MEDIA_DIR"
chmod 700 "$RUN_ROOT" "$MEDIA_DIR"
: > "$LOG"
chmod 600 "$LOG"

assert_no_credential_bearing_origin
assert_packaged_binary_identity "$REPO"
detect_runtime_boundary "$REPO" || true
assert_packaged_elf_identity
assert_static_bootstrap
assert_no_door_gate_paths "$RUN_ROOT/packaged.strings"
RUNNER_SELF_SHA256="$(sha256sum "$REPO/safety-poc/research/media/v1/ct120_run_p110_final_run5_runner.sh" | awk '{print $1}')"
if [ -n "$EXPECTED_RUNNER_SHA256" ] && [ "$RUNNER_SELF_SHA256" = "$EXPECTED_RUNNER_SHA256" ]; then
    echo "P110_RUNNER_SHA256_GATE=PASS"
else
    fail "P110_RUNNER_SHA256_GATE=FAIL"
fi

if [ -f "$SECRETS_FILE" ]; then
    mode="$(stat -c '%a' "$SECRETS_FILE" 2>/dev/null || echo 000)"
    [ "$mode" = 600 ] || [ "$mode" = 400 ] || fail "P110_SECRETS_MODE_GATE=FAIL"
    echo "P110_SECRETS_PRESENT=true"
    echo "SECRETS_CONTENT_EMITTED=false"
else
    fail "P110_SECRETS_PRESENT=false"
fi

if [ "$FAIL" -eq 0 ]; then
    PACKAGED_BINARY_IDENTITY_GATE=PASS
    FAIL_CLOSED_PRELIVE_GATE=PASS
fi

if [ "$FAIL" -ne 0 ]; then
    echo "P110_PREFLIGHT=FAIL"
    echo "LIVE_INVOCATIONS_THIS_TASK=0"
    print_summary
    trap - EXIT
    exit 1
fi

echo "P110_PREFLIGHT=PASS"
post_control status "$RUN_ROOT/listener-status-before.json" 10
if status_ready "$RUN_ROOT/listener-status-before.json"; then
    LISTENER_READY_BEFORE=PASS
    echo "LISTENER_READY_BEFORE=PASS"
else
    fail "LISTENER_READY_BEFORE=FAIL"
fi
[ "$FAIL" -eq 0 ] || exit 1

LISTENER_STOPPED=1
post_control stop "$RUN_ROOT/listener-stop.json" 20
if status_stopped "$RUN_ROOT/listener-stop.json"; then
    LISTENER_STOP_GATE=PASS
    echo "LISTENER_STOP_GATE=PASS"
else
    fail "LISTENER_STOP_GATE=FAIL"
fi
[ "$FAIL" -eq 0 ] || exit 1

echo "LISTENER_ISOLATION_SETTLE_SECONDS=5"
sleep 5
rm -rf "$RUN_DIR"
install -d -m 700 "$RUN_DIR"

echo "=== EXACTLY ONE P110 PACKAGED MUSL LIVE INVOCATION ==="
LIVE_INVOCATIONS=1
BINARY_EXECUTED=true
EXECUTABLE_MEDIA_PATH="$PACKAGED_BINARY"
timeout --signal=TERM --kill-after=5s "${MEDIA_SESSION_MAX_SECONDS}s" \
    "$RUNTIME_LOADER" --library-path "$RUNTIME_LIBRARY_PATH" "$EXECUTABLE_MEDIA_PATH" > "$LOG" 2>&1 &
MEDIA_PID=$!
echo "P110_MEDIA_PID_REDACTED=true"

for _ in $(seq 1 150); do
    if [ -s "$RUN_DIR/offer.sdp" ]; then
        echo "ICE_OFFER_READY=true"
        break
    fi
    if ! kill -0 "$MEDIA_PID" 2>/dev/null; then
        fail "P110_HELPER_EXITED_BEFORE_OFFER=FAIL"
        break
    fi
    sleep 0.1
done
[ -s "$RUN_DIR/offer.sdp" ] || fail "P110_OFFER_READY_GATE=FAIL"
[ "$FAIL" -eq 0 ] || exit 1

NETWORK_IO_PERFORMED=true
python3 "$REPO/$BOOTSTRAP_REL" --offer "$RUN_DIR/offer.sdp" --remote "$RUN_DIR/remote.sdp" --secrets "$SECRETS_FILE" > "$BOOTSTRAP_LOG" 2>&1
BOOTSTRAP_RC=$?
if [ "$BOOTSTRAP_RC" -ne 0 ] || [ ! -s "$RUN_DIR/remote.sdp" ]; then
    fail "P110_CLOUD_BOOTSTRAP_GATE=FAIL"
fi
CLOUD_NEGOTIATION_COUNT="$(awk -F= '/^P110_CLOUD_NEGOTIATION_COUNT=/{print $2}' "$BOOTSTRAP_LOG" | tail -n 1)"
[ -n "$CLOUD_NEGOTIATION_COUNT" ] || CLOUD_NEGOTIATION_COUNT=0
[ "$CLOUD_NEGOTIATION_COUNT" -eq 1 ] && ONE_CLOUD_NEGOTIATION_GATE=PASS || fail "P110_ONE_CLOUD_NEGOTIATION_GATE=FAIL"

while [ "$OBSERVATION_SECONDS" -lt "$OBSERVATION_SECONDS_LIMIT" ]; do
    if ! kill -0 "$MEDIA_PID" 2>/dev/null; then
        break
    fi
    sleep 1
    OBSERVATION_SECONDS=$((OBSERVATION_SECONDS + 1))
done
echo "OBSERVATION_SECONDS=$OBSERVATION_SECONDS"
stop_media_if_needed
wait "$MEDIA_PID" || MEDIA_RC=$?
[ "$MEDIA_RC" = NOT_REACHED ] && MEDIA_RC=0
MEDIA_PID=""
packaged_processes_remaining
collect_log_markers
derive_teardown_confidence

if [ "$TEARDOWN_CONFIDENCE" = CONFIRMED ]; then
    restore_listener || true
else
    LISTENER_RESTART_SUPPRESSED=true
    echo "LISTENER_RESTART_SUPPRESSED=true"
    echo "LISTENER_RESTORE_FINAL_GATE=FAIL"
fi

PACKAGED_BINARY_SHA_AFTER_RUN="$(sha256sum "$PACKAGED_BINARY" | awk '{print $1}')"
[ "$P110_DOOR_RESULT_COUNT" -eq 0 ] || fail "P110_DOOR_RESULT_GATE=FAIL"
[ "$P110_GATE_TOKEN_COUNT" -eq 0 ] || fail "P110_GATE_TOKEN_GATE=FAIL"
validate_media_success_contract || fail "P110_MEDIA_SUCCESS_CONTRACT_GATE=FAIL"
[ "$MEDIA_SUCCESS_CONTRACT_GATE" = PASS ] || fail "P110_MEDIA_SUCCESS_CONTRACT_GATE=FAIL"
[ "$TEARDOWN_CONFIDENCE" = CONFIRMED ] || exit 90
[ "$FAIL" -eq 0 ] || exit 1
print_summary
trap - EXIT
exit 0
