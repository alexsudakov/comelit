#!/usr/bin/env bash
# CT120 research-only P108 RUN4 exact packaged musl validation runner.
#
# This runner validates exactly one entrance-media live invocation of the
# production-packaged musl helper:
#   custom_components/comelit/native/comelit-media
#
# It deliberately performs no rebuild, C transform, compile, binary
# substitution, HA deployment, or HA Core restart. The live section is gated by
# packaged SHA identity and by a proven musl runtime boundary. If that boundary
# is absent, P108_RUNTIME_ABI_GATE=FAIL is emitted and the runner stops before
# any listener action.

set -u -o pipefail
umask 077

REPO="${REPO:-/root/comelit-door-diag-repo}"
BRANCH=fix/p107-package-p106-entrance-media
EXPECTED_PR_HEAD=977f7197f103050a9f52b43dad26af5df0c7bbf0
CT120_IP=192.168.1.85
HA_WEBHOOK_URL="${HA_WEBHOOK_URL:-http://192.168.1.108:8123/api/webhook/comelit-ha-ring-test-control-v1}"
SECRETS_FILE=/root/.config/comelit/secrets.env
PACKAGED_BINARY_REL=custom_components/comelit/native/comelit-media
PACKAGED_LIB_REL=custom_components/comelit/native/lib
PACKAGED_BINARY_SHA256=ebc731381022be89576a680c39f7402225048e48adab88376434f660ad1a5ade
PACKAGED_BINARY_BYTES=256992
PACKAGED_BINARY_REBUILT=false
EXPECTED_INTERPRETER=/lib/ld-musl-x86_64.so.1
EXPECTED_NEEDED_CSV=libc.musl-x86_64.so.1,libglib-2.0.so.0,libgobject-2.0.so.0,libnice.so.10
RUN_DIR=/run/comelit-media
STOP_FILE="$RUN_DIR/stop"
VIDEO_RTP_PORT=17899
AUDIO_RTP_PORT=17808
LIVE_WINDOW_SECONDS=40
OUTER_TIMEOUT_SECONDS=75
MEDIA_SESSION_TIMEOUT_SECONDS=45
P108_LIVE_INVOCATION_LIMIT=1
ARTIFACT_ROOT=/root/comelit-artifacts

LIVE_RUN="${LIVE_RUN:-1}"
HYPOTHESIS_ID="${HYPOTHESIS_ID:-p108-exact-packaged-musl-run4}"
LEN24_FALLBACK_SUMMARY_MAX=32

FAIL=0
SUMMARY_PRINTED=0
LISTENER_STOPPED=0
LISTENER_RESTART_SUPPRESSED=false
RESTORE_OK=0
RESTORE_ATTEMPTS=0
TEARDOWN_CONFIDENCE=UNCERTAIN
LIVE_INVOCATIONS=0
MEDIA_PID=""
VIDEO_SINK_PID=""
AUDIO_SINK_PID=""
RUN_ROOT=""
MEDIA_DIR=""
LOG=""
STATUS_AFTER=""
CURRENT_HEAD=UNKNOWN
REPO_HEAD=UNKNOWN
MEDIA_RC=NOT_REACHED
OBSERVATION_SECONDS=0
LISTENER_READY_BEFORE=FAIL
LISTENER_STOP_GATE=FAIL
LISTENER_RESTORE_READY=FAIL
LISTENER_READY_AFTER=FAIL
LISTENER_RECONNECT_COUNT_BEFORE=UNKNOWN
LISTENER_RECONNECT_COUNT_AFTER=UNKNOWN
PACKAGED_MUSL_PROCESS_REMAINING=UNKNOWN
CTPP_OPEN_COUNT=0
SECOND_CTPP_OPEN=false
RTPC_OPEN_1_COUNT=0
RTPC_OPEN_2_COUNT=0
RTPC_OPEN_TOTAL_COUNT=0
P108_DOOR_RESULT_COUNT=0
P108_GATE_TOKEN_COUNT=0
UPSTREAM_MEDIA_ACTIVE_AT_EXIT=true
FFMPEG_PRESENT=false
FFPROBE_PRESENT=false
FFPROBE_H264=NOT_PROVABLE_FFMPEG_ABSENT
JPEG_RESULT=NOT_PROVABLE_FFMPEG_ABSENT
JPEG_PATH=NONE
JPEG_SHA256=NONE
SHORT_VIDEO_RESULT=NOT_PROVABLE_FFMPEG_ABSENT
SHORT_VIDEO_PATH=NONE
SHORT_VIDEO_DURATION_SEC=UNKNOWN
SHORT_VIDEO_SHA256=NONE
H264_SPS_COUNT=UNKNOWN
H264_PPS_COUNT=UNKNOWN
H264_IDR_COUNT=UNKNOWN
H264_FU_A_COUNT=UNKNOWN
H264_STAP_A_COUNT=UNKNOWN
VIDEO_RTP_DATAGRAMS=0
AUDIO_RTP_DATAGRAMS=0
LEN24_FALLBACK_LINES_EMITTED=0
PACKAGED_BINARY=""
PACKAGED_LIB_DIR=""
PACKAGED_BINARY_SHA_BEFORE_RUN=NOT_REACHED
PACKAGED_BINARY_SHA_AFTER_RUN=NOT_REACHED
RUNTIME_ABI_GATE=FAIL
RUNTIME_LOADER=NONE
RUNTIME_LIBRARY_PATH=NONE
RUNTIME_ROOT=NONE
STAGED_COPY_BYTE_IDENTICAL=false
EXECUTABLE_MEDIA_PATH=NONE

P78_RTPC_SIGNALING_RESULT=NOT_REACHED
P80_DEVICE_ACK_000A_OBSERVED=NOT_REACHED
P80_DEVICE_ACK_001A_OBSERVED=NOT_REACHED
P80_POST_001A_ACK_GATE=NOT_REACHED
P80_PREACTIVE_MEDIA_DEMUX=NOT_REACHED
P80_PREACTIVE_MEDIA_PROFILE_ACCEPT=NOT_REACHED
P80_PREACTIVE_MEDIA_PAYLOAD_TYPE=NOT_REACHED
P80_MEDIA_ACTIVE=NOT_REACHED
P80_VIDEO_RTP_FORWARDING=NOT_REACHED
P80_AUDIO_RTP_FORWARDING=NOT_REACHED
P80_DEVICE_ACK_000A_BINDING=NOT_REACHED
P80_DEVICE_ACK_001A_BINDING=NOT_REACHED
P80_WRAPPER_PROFILE_MISMATCH=NOT_OBSERVED
P80_WRAPPER_PROFILE_MISMATCH_STATE=NOT_OBSERVED
PSEUDOTCP_NOTIFY_PACKET=NOT_OBSERVED
PSEUDOTCP_NOTIFY_PACKET_CLASS=NOT_OBSERVED
PSEUDOTCP_NOTIFY_PACKET_SOCKET_CLOSED=NOT_OBSERVED
PSEUDOTCP_NOTIFY_PACKET_GRACEFUL_STARTED=NOT_OBSERVED
PSEUDOTCP_GRACEFUL_CLOSE_COMPLETE=NOT_OBSERVED
PSEUDOTCP_NOTIFY_PACKET_FAIL_LEN=NOT_OBSERVED
P2_HOLDER_TERMINAL_RC=NOT_OBSERVED
P2_HOLDER_TERMINAL_RESULT=NOT_OBSERVED

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
            LISTENER_RESTORE_READY=PASS
            LISTENER_READY_AFTER=PASS
            LISTENER_RECONNECT_COUNT_AFTER="$(json_scalar "$status_file" reconnect_count)"
            echo "LISTENER_RESTORE_READY=PASS"
            echo "LISTENER_RESTORE_READY_POLL=$poll"
            echo "LISTENER_READY_AFTER=PASS"
            echo "LISTENER_RECONNECT_COUNT_AFTER=$LISTENER_RECONNECT_COUNT_AFTER"
            return 0
        fi
        echo "LISTENER_RESTORE_READY_POLL_${poll}=WAIT"
        sleep 5
    done

    LISTENER_RESTORE_READY=FAIL
    LISTENER_READY_AFTER=FAIL
    echo "LISTENER_RESTORE_READY=FAIL"
    return 1
}

stop_media_if_needed() {
    if [ -z "$MEDIA_PID" ] || ! kill -0 "$MEDIA_PID" 2>/dev/null; then
        return 0
    fi

    echo "P108_STOP_REQUESTED=true"
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

    echo "P108_STOP_ESCALATION=TERM"
    kill -TERM "$MEDIA_PID" 2>/dev/null || true
    sleep 2
    if kill -0 "$MEDIA_PID" 2>/dev/null; then
        echo "P108_STOP_ESCALATION=KILL"
        kill -KILL "$MEDIA_PID" 2>/dev/null || true
    fi
}

stop_sink_if_needed() {
    local pid="$1"
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
        kill -TERM "$pid" 2>/dev/null || true
        sleep 1
        if kill -0 "$pid" 2>/dev/null; then
            kill -KILL "$pid" 2>/dev/null || true
        fi
    fi
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

count_log_literal() {
    local literal="$1"
    if [ -f "$LOG" ]; then
        grep -cF "$literal" "$LOG" 2>/dev/null || true
    else
        printf '0\n'
    fi
}

derive_open_accounting() {
    CTPP_OPEN_COUNT="$(count_log_literal 'V4_CTPP_OPEN_SENT=PASS')"
    RTPC_OPEN_1_COUNT="$(count_log_literal 'P78_RTPC_OPEN_1_SENT=PASS')"
    RTPC_OPEN_2_COUNT="$(count_log_literal 'P78_RTPC_OPEN_2_SENT=PASS')"
    RTPC_OPEN_TOTAL_COUNT=$((RTPC_OPEN_1_COUNT + RTPC_OPEN_2_COUNT))
    if [ "$CTPP_OPEN_COUNT" -gt 1 ]; then
        SECOND_CTPP_OPEN=true
    else
        SECOND_CTPP_OPEN=false
    fi
}

emit_len24_lines() {
    if [ -f "$LOG" ]; then
        awk -v max="$LEN24_FALLBACK_SUMMARY_MAX" '
            /^LEN24_FALLBACK_/ && count < max { print; count++ }
            END { print "LEN24_FALLBACK_LINES_EMITTED=" count }
        ' "$LOG"
    else
        echo "LEN24_FALLBACK_LINES_EMITTED=0"
    fi
}

collect_log_markers() {
    P78_RTPC_SIGNALING_RESULT="$(last_marker P78_RTPC_SIGNALING_RESULT NOT_REACHED)"
    P80_DEVICE_ACK_000A_OBSERVED="$(last_marker P80_DEVICE_ACK_000A_OBSERVED NOT_REACHED)"
    P80_DEVICE_ACK_001A_OBSERVED="$(last_marker P80_DEVICE_ACK_001A_OBSERVED NOT_REACHED)"
    P80_POST_001A_ACK_GATE="$(last_marker P80_POST_001A_ACK_GATE NOT_REACHED)"
    P80_PREACTIVE_MEDIA_DEMUX="$(last_marker P80_PREACTIVE_MEDIA_DEMUX NOT_REACHED)"
    P80_PREACTIVE_MEDIA_PROFILE_ACCEPT="$(last_marker P80_PREACTIVE_MEDIA_PROFILE_ACCEPT NOT_REACHED)"
    P80_PREACTIVE_MEDIA_PAYLOAD_TYPE="$(last_marker P80_PREACTIVE_MEDIA_PAYLOAD_TYPE NOT_REACHED)"
    P80_MEDIA_ACTIVE="$(last_marker P80_MEDIA_ACTIVE NOT_REACHED)"
    P80_VIDEO_RTP_FORWARDING="$(last_marker P80_VIDEO_RTP_FORWARDING NOT_REACHED)"
    P80_AUDIO_RTP_FORWARDING="$(last_marker P80_AUDIO_RTP_FORWARDING NOT_REACHED)"
    P80_DEVICE_ACK_000A_BINDING="$(last_marker P80_DEVICE_ACK_000A_BINDING NOT_REACHED)"
    P80_DEVICE_ACK_001A_BINDING="$(last_marker P80_DEVICE_ACK_001A_BINDING NOT_REACHED)"
    P80_WRAPPER_PROFILE_MISMATCH="$(last_marker P80_WRAPPER_PROFILE_MISMATCH NOT_OBSERVED)"
    P80_WRAPPER_PROFILE_MISMATCH_STATE="$(last_marker P80_WRAPPER_PROFILE_MISMATCH_STATE NOT_OBSERVED)"
    PSEUDOTCP_NOTIFY_PACKET="$(last_marker PSEUDOTCP_NOTIFY_PACKET NOT_OBSERVED)"
    PSEUDOTCP_NOTIFY_PACKET_FAIL_LEN="$(last_marker PSEUDOTCP_NOTIFY_PACKET_FAIL_LEN NOT_OBSERVED)"
    PSEUDOTCP_NOTIFY_PACKET_CLASS="$(last_marker PSEUDOTCP_NOTIFY_PACKET_CLASS NOT_OBSERVED)"
    PSEUDOTCP_NOTIFY_PACKET_SOCKET_CLOSED="$(last_marker PSEUDOTCP_NOTIFY_PACKET_SOCKET_CLOSED NOT_OBSERVED)"
    PSEUDOTCP_NOTIFY_PACKET_GRACEFUL_STARTED="$(last_marker PSEUDOTCP_NOTIFY_PACKET_GRACEFUL_STARTED NOT_OBSERVED)"
    PSEUDOTCP_GRACEFUL_CLOSE_COMPLETE="$(last_marker PSEUDOTCP_GRACEFUL_CLOSE_COMPLETE NOT_OBSERVED)"
    P2_HOLDER_TERMINAL_RC="$(last_marker P2_HOLDER_TERMINAL_RC NOT_OBSERVED)"
    P2_HOLDER_TERMINAL_RESULT="$(last_marker P2_HOLDER_TERMINAL_RESULT NOT_OBSERVED)"
    derive_open_accounting
    P108_DOOR_RESULT_COUNT="$(count_log_literal 'V4_DOOR_RESULT=')"
    P108_GATE_TOKEN_COUNT="$(count_log_literal 'GATE_ACTION_SENT=')"
    LEN24_FALLBACK_LINES_EMITTED="$(emit_len24_lines | awk -F= '/^LEN24_FALLBACK_LINES_EMITTED=/{print $2}')"
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
    if [ "$PACKAGED_MUSL_PROCESS_REMAINING" = NONE ]; then
        UPSTREAM_MEDIA_ACTIVE_AT_EXIT=false
    else
        UPSTREAM_MEDIA_ACTIVE_AT_EXIT=true
    fi

    if [ "$UPSTREAM_MEDIA_ACTIVE_AT_EXIT" = false ] &&
       [ "$MEDIA_RC" != 124 ] &&
       [ "$MEDIA_RC" != 137 ]; then
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
    local root candidate release
    RUNTIME_ABI_GATE=FAIL
    RUNTIME_LOADER=NONE
    RUNTIME_LIBRARY_PATH=NONE
    RUNTIME_ROOT=NONE
    PACKAGED_LIB_DIR="$repo_root/$PACKAGED_LIB_REL"

    for candidate in \
        "${P108_TEST_RUNTIME_ROOT:-}" \
        /root/comelit-*-haos-build-*/rootfs \
        /root/*alpine*/rootfs \
        /root/*alpine* \
        /
    do
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
            echo "RUNTIME_LOADER=$RUNTIME_LOADER"
            echo "RUNTIME_LIBRARY_PATH=$RUNTIME_LIBRARY_PATH"
            return 0
        done
    done

    echo "P108_RUNTIME_ABI_GATE=FAIL"
    echo "RUNTIME_ABI_GATE=FAIL"
    echo "RUNTIME_LOADER=NONE"
    echo "RUNTIME_LIBRARY_PATH=NONE"
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
        echo "PACKAGED_BINARY_SHA_BEFORE_RUN=$PACKAGED_BINARY_SHA_BEFORE_RUN"
        echo "PACKAGED_BINARY_BYTES=$size"
        [ "$PACKAGED_BINARY_SHA_BEFORE_RUN" = "$PACKAGED_BINARY_SHA256" ] || fail "PACKAGED_BINARY_SHA_GATE=FAIL"
        [ "$size" = "$PACKAGED_BINARY_BYTES" ] || fail "PACKAGED_BINARY_SIZE_GATE=FAIL"
    fi
}

assert_packaged_binary_strings() {
    local strings_file="$1"
    strings -a "$PACKAGED_BINARY" > "$strings_file"
    for marker in \
      'P80_DEVICE_ACK_000A_OBSERVED=PASS' \
      'P80_DEVICE_ACK_001A_OBSERVED=PASS' \
      'P80_POST_001A_ACK_GATE=PASS' \
      'P80_PREACTIVE_MEDIA_DEMUX=PASS' \
      'P80_PREACTIVE_MEDIA_PROFILE_ACCEPT=PASS' \
      'P80_MEDIA_ACTIVE=true' \
      'P80_VIDEO_RTP_FORWARDING=PASS' \
      'P80_AUDIO_RTP_FORWARDING=PASS' \
      'PSEUDOTCP_NOTIFY_PACKET_CLASS=%s' \
      'P80_DOOR_SIGNAL_ENTRYPOINT=false' \
      'P80_RUN_DIR=/run/comelit-media'
    do
        grep -Fq "$marker" "$strings_file" || fail "P108_BINARY_MARKER_GATE=FAIL marker=$marker"
    done
    if grep -Fq -- '--door' "$strings_file" || grep -Fq -- '--gate' "$strings_file"; then
        fail "P108_DOOR_GATE_SWITCH_GATE=FAIL"
    else
        echo "P108_DOOR_GATE_SWITCH_GATE=PASS"
    fi
    if grep -Fq 'signal(SIGUSR1, v4_door_signal_handler);' "$strings_file"; then
        fail "P108_EXTERNAL_DOOR_SIGNAL_GATE=FAIL"
    else
        echo "P108_EXTERNAL_DOOR_SIGNAL_GATE=PASS"
    fi
}

assert_packaged_elf_identity() {
    local interpreter
    local needed
    interpreter="$(readelf -l "$PACKAGED_BINARY" | sed -n 's@.*Requesting program interpreter: \(.*\)]@\1@p')"
    needed="$(readelf -d "$PACKAGED_BINARY" | sed -n 's/.*Shared library: \[\(.*\)\]/\1/p' | sort | paste -sd, -)"
    echo "PACKAGED_BINARY_INTERPRETER=$interpreter"
    echo "PACKAGED_BINARY_NEEDED=$needed"
    [ "$interpreter" = "$EXPECTED_INTERPRETER" ] || fail "P108_ELF_INTERPRETER_GATE=FAIL"
    [ "$needed" = "$EXPECTED_NEEDED_CSV" ] || fail "P108_ELF_NEEDED_GATE=FAIL"
    case "$needed" in
        *libc.so.6*|*ld-linux*) fail "P108_GLIBC_GATE=FAIL" ;;
    esac
}

start_udp_sink() {
    local label="$1"
    local port="$2"
    local datagrams="$3"
    local hist="$4"
    local count_file="$5"
    local deadline="$6"
    python3 - "$port" "$datagrams" "$hist" "$count_file" "$deadline" <<'PY' &
from collections import Counter
from pathlib import Path
import os
import signal
import socket
import sys
import time

port = int(sys.argv[1])
datagrams_path = Path(sys.argv[2])
hist_path = Path(sys.argv[3])
count_path = Path(sys.argv[4])
deadline = min(int(sys.argv[5]), 75)
stop = False

def _stop(_signum, _frame):
    global stop
    stop = True

signal.signal(signal.SIGTERM, _stop)
signal.signal(signal.SIGINT, _stop)
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind(("127.0.0.1", port))
sock.settimeout(0.5)
hist = Counter()
count = 0
end = time.monotonic() + deadline
with datagrams_path.open("ab") as out:
    os.chmod(datagrams_path, 0o600)
    while not stop and time.monotonic() < end:
        try:
            payload, _addr = sock.recvfrom(65535)
        except socket.timeout:
            continue
        count += 1
        hist[len(payload)] += 1
        out.write(len(payload).to_bytes(2, "big"))
        out.write(payload)
hist_path.write_text(
    "\n".join(f"{length} {hist[length]}" for length in sorted(hist)) + ("\n" if hist else ""),
    encoding="utf-8",
)
count_path.write_text(f"{count}\n", encoding="utf-8")
os.chmod(hist_path, 0o600)
os.chmod(count_path, 0o600)
PY
    local pid=$!
    if [ "$label" = video ]; then
        VIDEO_SINK_PID="$pid"
        echo "P108_CAPTURE_VIDEO_PID_REDACTED=true"
    else
        AUDIO_SINK_PID="$pid"
        echo "P108_CAPTURE_AUDIO_PID_REDACTED=true"
    fi
}

depacketize_h264() {
    local datagrams="$1"
    local out="$2"
    local stats="$3"
    python3 - "$datagrams" "$out" "$stats" <<'PY'
from pathlib import Path
import os
import sys

src = Path(sys.argv[1])
out = Path(sys.argv[2])
stats = Path(sys.argv[3])
ANNEX = b"\x00\x00\x00\x01"
PT_H264 = 99
payloads = []
if src.exists():
    data = src.read_bytes()
    pos = 0
    while pos + 2 <= len(data):
        size = int.from_bytes(data[pos:pos + 2], "big")
        pos += 2
        if size < 12 or pos + size > len(data):
            break
        packet = data[pos:pos + size]
        pos += size
        if packet[0] >> 6 != 2:
            continue
        cc = packet[0] & 0x0F
        x = (packet[0] >> 4) & 1
        pt = packet[1] & 0x7F
        header_len = 12 + (cc * 4)
        if len(packet) < header_len:
            continue
        if x:
            if len(packet) < header_len + 4:
                continue
            ext_len = int.from_bytes(packet[header_len + 2:header_len + 4], "big") * 4
            header_len += 4 + ext_len
        if pt == PT_H264 and len(packet) > header_len:
            payloads.append(packet[header_len:])

sps = pps = idr = fua = stapa = 0
annex = bytearray()
fu_parts = []

def emit(nal: bytes) -> None:
    global sps, pps, idr
    if not nal:
        return
    t = nal[0] & 0x1F
    if t == 7:
        sps += 1
    elif t == 8:
        pps += 1
    elif t == 5:
        idr += 1
    annex.extend(ANNEX)
    annex.extend(nal)

for media in payloads:
    nal_type = media[0] & 0x1F
    if 1 <= nal_type <= 23:
        emit(media)
    elif nal_type == 24:
        stapa += 1
        pos = 1
        while pos + 2 <= len(media):
            size = int.from_bytes(media[pos:pos + 2], "big")
            pos += 2
            if size <= 0 or pos + size > len(media):
                break
            emit(media[pos:pos + size])
            pos += size
    elif nal_type == 28 and len(media) >= 3:
        fua += 1
        fu_indicator = media[0]
        fu_header_byte = media[1]
        start = bool(fu_header_byte & 0x80)
        end = bool(fu_header_byte & 0x40)
        original_type = fu_header_byte & 0x1F
        if start:
            fu_parts = [bytes([(fu_indicator & 0xE0) | original_type]), media[2:]]
        elif fu_parts:
            fu_parts.append(media[2:])
        if end and fu_parts:
            emit(b"".join(fu_parts))
            fu_parts = []

out.write_bytes(bytes(annex))
os.chmod(out, 0o600)
stats.write_text(
    "\n".join([
        f"P108_H264_SPS_COUNT={sps}",
        f"P108_H264_PPS_COUNT={pps}",
        f"P108_H264_IDR_COUNT={idr}",
        f"P108_H264_FU_A_COUNT={fua}",
        f"P108_H264_STAP_A_COUNT={stapa}",
        f"P108_VIDEO_RTP_DATAGRAMS={len(payloads)}",
    ]) + "\n",
    encoding="utf-8",
)
os.chmod(stats, 0o600)
PY
}

postprocess_media() {
    local video_count_file="$MEDIA_DIR/video.count"
    local audio_count_file="$MEDIA_DIR/audio.count"
    local annex="$MEDIA_DIR/video.annexb.h264"
    local stats="$MEDIA_DIR/h264.stats"
    local still="$MEDIA_DIR/still.jpg"
    local clip="$MEDIA_DIR/clip.mp4"

    [ -f "$video_count_file" ] && VIDEO_RTP_DATAGRAMS="$(awk 'NR==1{print $1}' "$video_count_file")"
    [ -f "$audio_count_file" ] && AUDIO_RTP_DATAGRAMS="$(awk 'NR==1{print $1}' "$audio_count_file")"
    depacketize_h264 "$MEDIA_DIR/video.rtpdatagrams" "$annex" "$stats" || true
    if [ -f "$stats" ]; then
        H264_SPS_COUNT="$(awk -F= '/^P108_H264_SPS_COUNT=/{print $2}' "$stats")"
        H264_PPS_COUNT="$(awk -F= '/^P108_H264_PPS_COUNT=/{print $2}' "$stats")"
        H264_IDR_COUNT="$(awk -F= '/^P108_H264_IDR_COUNT=/{print $2}' "$stats")"
        H264_FU_A_COUNT="$(awk -F= '/^P108_H264_FU_A_COUNT=/{print $2}' "$stats")"
        H264_STAP_A_COUNT="$(awk -F= '/^P108_H264_STAP_A_COUNT=/{print $2}' "$stats")"
    fi
    echo "P108_H264_SPS_COUNT=$H264_SPS_COUNT"
    echo "P108_H264_PPS_COUNT=$H264_PPS_COUNT"
    echo "P108_H264_IDR_COUNT=$H264_IDR_COUNT"
    echo "P108_H264_FU_A_COUNT=$H264_FU_A_COUNT"
    echo "P108_H264_STAP_A_COUNT=$H264_STAP_A_COUNT"
    echo "P108_VIDEO_RTP_DATAGRAMS=$VIDEO_RTP_DATAGRAMS"
    echo "P108_AUDIO_RTP_DATAGRAMS=$AUDIO_RTP_DATAGRAMS"

    if [ "$FFMPEG_PRESENT" != true ] || [ "$FFPROBE_PRESENT" != true ]; then
        JPEG_RESULT=NOT_PROVABLE_FFMPEG_ABSENT
        SHORT_VIDEO_RESULT=NOT_PROVABLE_FFMPEG_ABSENT
        echo "P108_FFPROBE_H264=$FFPROBE_H264"
        echo "P108_JPEG_RESULT=$JPEG_RESULT"
        echo "P108_SHORT_VIDEO_RESULT=$SHORT_VIDEO_RESULT"
        return 0
    fi

    if ffprobe -v error -f h264 "$annex" > "$MEDIA_DIR/ffprobe.out" 2> "$MEDIA_DIR/ffprobe.err"; then
        FFPROBE_H264=PASS
    else
        FFPROBE_H264=FAIL
    fi
    echo "P108_FFPROBE_H264=$FFPROBE_H264"
    chmod 600 "$MEDIA_DIR/ffprobe.out" "$MEDIA_DIR/ffprobe.err" 2>/dev/null || true

    if ffmpeg -hide_banner -loglevel error -y -f h264 -i "$annex" -frames:v 1 "$still" > "$MEDIA_DIR/ffmpeg-still.out" 2> "$MEDIA_DIR/ffmpeg-still.err" &&
       [ -s "$still" ]; then
        chmod 600 "$still"
        JPEG_RESULT=PASS
        JPEG_PATH="$still"
        JPEG_SHA256="$(sha256sum "$still" | awk '{print $1}')"
        echo "P108_JPEG_RESULT=PASS"
        echo "P108_JPEG_PATH=$JPEG_PATH"
        echo "P108_JPEG_BYTES=$(wc -c < "$still" | awk '{print $1}')"
        echo "P108_JPEG_SHA256=$JPEG_SHA256"
    else
        JPEG_RESULT=FAIL
        echo "P108_JPEG_RESULT=FAIL"
    fi
    chmod 600 "$MEDIA_DIR/ffmpeg-still.out" "$MEDIA_DIR/ffmpeg-still.err" 2>/dev/null || true

    if ffmpeg -hide_banner -loglevel error -y -f h264 -i "$annex" -an -t 5 -c:v copy "$clip" > "$MEDIA_DIR/ffmpeg-clip.out" 2> "$MEDIA_DIR/ffmpeg-clip.err" &&
       [ -s "$clip" ]; then
        chmod 600 "$clip"
        SHORT_VIDEO_RESULT=PASS
        SHORT_VIDEO_PATH="$clip"
        SHORT_VIDEO_SHA256="$(sha256sum "$clip" | awk '{print $1}')"
        SHORT_VIDEO_DURATION_SEC="$(ffprobe -v error -show_entries format=duration -of default=nk=1:nw=1 "$clip" 2>/dev/null || echo UNKNOWN)"
        echo "P108_SHORT_VIDEO_RESULT=PASS"
        echo "P108_SHORT_VIDEO_PATH=$SHORT_VIDEO_PATH"
        echo "P108_SHORT_VIDEO_BYTES=$(wc -c < "$clip" | awk '{print $1}')"
        echo "P108_SHORT_VIDEO_DURATION_SEC=$SHORT_VIDEO_DURATION_SEC"
        echo "P108_SHORT_VIDEO_SHA256=$SHORT_VIDEO_SHA256"
    else
        SHORT_VIDEO_RESULT=FAIL
        echo "P108_SHORT_VIDEO_RESULT=FAIL"
    fi
    chmod 600 "$MEDIA_DIR/ffmpeg-clip.out" "$MEDIA_DIR/ffmpeg-clip.err" 2>/dev/null || true
}

print_summary() {
    if [ "$SUMMARY_PRINTED" -eq 1 ]; then
        return 0
    fi
    SUMMARY_PRINTED=1
    echo "=== COMELIT P108 RUN4 EXACT PACKAGED MUSL SUMMARY ==="
    echo "P108_LIVE_RUN=$LIVE_RUN"
    echo "P108_HYPOTHESIS_ID=$HYPOTHESIS_ID"
    echo "P108_BRANCH_HEAD=$CURRENT_HEAD"
    echo "P108_REPO_HEAD=$REPO_HEAD"
    echo "PACKAGED_BINARY_REBUILT=false"
    echo "PACKAGED_BINARY_PATH=$PACKAGED_BINARY"
    echo "PACKAGED_BINARY_SHA_BEFORE_RUN=$PACKAGED_BINARY_SHA_BEFORE_RUN"
    echo "PACKAGED_BINARY_SHA_AFTER_RUN=$PACKAGED_BINARY_SHA_AFTER_RUN"
    echo "RUNTIME_ABI_GATE=$RUNTIME_ABI_GATE"
    echo "RUNTIME_LOADER=$RUNTIME_LOADER"
    echo "RUNTIME_LIBRARY_PATH=$RUNTIME_LIBRARY_PATH"
    echo "RUNTIME_ROOT=$RUNTIME_ROOT"
    echo "STAGED_COPY_BYTE_IDENTICAL=$STAGED_COPY_BYTE_IDENTICAL"
    echo "EXECUTABLE_MEDIA_PATH=$EXECUTABLE_MEDIA_PATH"
    echo "P108_LIVE_INVOCATION_LIMIT=$P108_LIVE_INVOCATION_LIMIT"
    echo "P108_LIVE_INVOCATIONS=$LIVE_INVOCATIONS"
    echo "P108_MEDIA_RC=$MEDIA_RC"
    echo "P2_HOLDER_TERMINAL_RC=$P2_HOLDER_TERMINAL_RC"
    echo "P2_HOLDER_TERMINAL_RESULT=$P2_HOLDER_TERMINAL_RESULT"
    echo "P108_OBSERVATION_SECONDS=$OBSERVATION_SECONDS"
    echo "LISTENER_READY_BEFORE=$LISTENER_READY_BEFORE"
    echo "LISTENER_STOP_GATE=$LISTENER_STOP_GATE"
    echo "LISTENER_RESTORE_READY=$LISTENER_RESTORE_READY"
    echo "LISTENER_READY_AFTER=$LISTENER_READY_AFTER"
    echo "LISTENER_RESTART_SUPPRESSED=$LISTENER_RESTART_SUPPRESSED"
    echo "TEARDOWN_CONFIDENCE=$TEARDOWN_CONFIDENCE"
    echo "PACKAGED_MUSL_PROCESS_REMAINING=$PACKAGED_MUSL_PROCESS_REMAINING"
    echo "UPSTREAM_MEDIA_ACTIVE_AT_EXIT=$UPSTREAM_MEDIA_ACTIVE_AT_EXIT"
    echo "P108_CTPP_OPEN_COUNT=$CTPP_OPEN_COUNT"
    echo "P108_SECOND_CTPP_OPEN=$SECOND_CTPP_OPEN"
    echo "P108_RTPC_OPEN_1_COUNT=$RTPC_OPEN_1_COUNT"
    echo "P108_RTPC_OPEN_2_COUNT=$RTPC_OPEN_2_COUNT"
    echo "P108_RTPC_OPEN_TOTAL_COUNT=$RTPC_OPEN_TOTAL_COUNT"
    echo "P108_DOOR_RESULT_COUNT=$P108_DOOR_RESULT_COUNT"
    echo "P108_GATE_TOKEN_COUNT=$P108_GATE_TOKEN_COUNT"
    echo "P78_RTPC_SIGNALING_RESULT=$P78_RTPC_SIGNALING_RESULT"
    echo "P80_DEVICE_ACK_000A_OBSERVED=$P80_DEVICE_ACK_000A_OBSERVED"
    echo "P80_DEVICE_ACK_001A_OBSERVED=$P80_DEVICE_ACK_001A_OBSERVED"
    echo "P80_POST_001A_ACK_GATE=$P80_POST_001A_ACK_GATE"
    echo "P80_PREACTIVE_MEDIA_DEMUX=$P80_PREACTIVE_MEDIA_DEMUX"
    echo "P80_PREACTIVE_MEDIA_PROFILE_ACCEPT=$P80_PREACTIVE_MEDIA_PROFILE_ACCEPT"
    echo "P80_MEDIA_ACTIVE=$P80_MEDIA_ACTIVE"
    echo "P80_VIDEO_RTP_FORWARDING=$P80_VIDEO_RTP_FORWARDING"
    echo "P80_AUDIO_RTP_FORWARDING=$P80_AUDIO_RTP_FORWARDING"
    echo "P80_WRAPPER_PROFILE_MISMATCH=$P80_WRAPPER_PROFILE_MISMATCH"
    echo "PSEUDOTCP_NOTIFY_PACKET_CLASS=$PSEUDOTCP_NOTIFY_PACKET_CLASS"
    echo "PSEUDOTCP_NOTIFY_PACKET_SOCKET_CLOSED=$PSEUDOTCP_NOTIFY_PACKET_SOCKET_CLOSED"
    echo "PSEUDOTCP_NOTIFY_PACKET_GRACEFUL_STARTED=$PSEUDOTCP_NOTIFY_PACKET_GRACEFUL_STARTED"
    echo "PSEUDOTCP_GRACEFUL_CLOSE_COMPLETE=$PSEUDOTCP_GRACEFUL_CLOSE_COMPLETE"
    echo "PSEUDOTCP_NOTIFY_PACKET_FAIL_LEN=$PSEUDOTCP_NOTIFY_PACKET_FAIL_LEN"
    echo "LEN24_FALLBACK_LINES_EMITTED=$LEN24_FALLBACK_LINES_EMITTED"
    echo "P108_H264_SPS_COUNT=$H264_SPS_COUNT"
    echo "P108_H264_PPS_COUNT=$H264_PPS_COUNT"
    echo "P108_H264_IDR_COUNT=$H264_IDR_COUNT"
    echo "P108_VIDEO_RTP_DATAGRAMS=$VIDEO_RTP_DATAGRAMS"
    echo "P108_AUDIO_RTP_DATAGRAMS=$AUDIO_RTP_DATAGRAMS"
    echo "P108_FFMPEG_PRESENT=$FFMPEG_PRESENT"
    echo "P108_FFPROBE_PRESENT=$FFPROBE_PRESENT"
    echo "P108_FFPROBE_H264=$FFPROBE_H264"
    echo "P108_JPEG_RESULT=$JPEG_RESULT"
    echo "P108_JPEG_PATH=$JPEG_PATH"
    echo "P108_JPEG_SHA256=$JPEG_SHA256"
    echo "P108_SHORT_VIDEO_RESULT=$SHORT_VIDEO_RESULT"
    echo "P108_SHORT_VIDEO_PATH=$SHORT_VIDEO_PATH"
    echo "P108_SHORT_VIDEO_DURATION_SEC=$SHORT_VIDEO_DURATION_SEC"
    echo "P108_SHORT_VIDEO_SHA256=$SHORT_VIDEO_SHA256"
    echo "P108_RUN_ROOT=${RUN_ROOT:-NONE}"
    echo "DOOR_ACTION_SENT=false"
    echo "GATE_ACTION_SENT=false"
    echo "AUTOMATIC_RETRY=false"
    echo "HOME_ASSISTANT_CORE_STOPPED=false"
    echo "HOME_ASSISTANT_CORE_RESTARTED=false"
    echo "SECRETS_CONTENT_EMITTED=false"
    echo "=== END COMELIT P108 RUN4 EXACT PACKAGED MUSL SUMMARY ==="
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
    echo "HOME_ASSISTANT_CORE_STOPPED=false"
    echo "HOME_ASSISTANT_CORE_RESTARTED=false"
    echo "DOOR_ACTION_SENT=false"
    echo "GATE_ACTION_SENT=false"
    if [ "$LISTENER_STOPPED" -eq 1 ] && [ "$TEARDOWN_CONFIDENCE" != CONFIRMED ]; then
        print_summary
        exit 90
    fi
    print_summary
    exit "$original_rc"
}

if [ "${P108_SOURCE_ONLY:-0}" = 1 ]; then
    return 0 2>/dev/null || exit 0
fi

trap on_exit EXIT
trap 'exit 130' INT TERM HUP

if [ "${EUID}" -ne 0 ]; then
    echo "P108_LIVE_REQUIRES_ROOT=true"
    exit 1
fi

for command in git python3 sha256sum timeout strings grep curl ip awk head wc readelf; do
    command -v "$command" >/dev/null 2>&1 || fail "P108_MISSING_COMMAND=$command"
done
if command -v ffmpeg >/dev/null 2>&1; then
    FFMPEG_PRESENT=true
fi
if command -v ffprobe >/dev/null 2>&1; then
    FFPROBE_PRESENT=true
fi
echo "P108_FFMPEG_PRESENT=$FFMPEG_PRESENT"
echo "P108_FFPROBE_PRESENT=$FFPROBE_PRESENT"

if ip -4 addr show | grep -Fq "$CT120_IP/"; then
    echo "P108_CT120_IDENTITY=PASS"
else
    fail "P108_CT120_IDENTITY=FAIL"
fi

[ -d "$REPO/.git" ] || fail "P108_REPO_PRESENT=false"
if [ "$FAIL" -eq 0 ]; then
    CURRENT_HEAD="$(git -C "$REPO" rev-parse HEAD 2>/dev/null || echo UNKNOWN)"
    REPO_HEAD="$CURRENT_HEAD"
    echo "P108_REPO_HEAD=$REPO_HEAD"
    CURRENT_BRANCH="$(git -C "$REPO" branch --show-current 2>/dev/null || true)"
    [ "$CURRENT_BRANCH" = "$BRANCH" ] || fail "P108_BRANCH_GATE=FAIL"
    [ "$CURRENT_HEAD" = "$EXPECTED_PR_HEAD" ] || fail "P108_PR_HEAD_GATE=FAIL"
fi

assert_packaged_binary_identity "$REPO"
detect_runtime_boundary "$REPO" || true

echo "PACKAGED_BINARY_REBUILT=false"
echo "RUNTIME_ABI_GATE=$RUNTIME_ABI_GATE"
echo "RUNTIME_LOADER=$RUNTIME_LOADER"
echo "RUNTIME_LIBRARY_PATH=$RUNTIME_LIBRARY_PATH"
[ "$RUNTIME_ABI_GATE" = PASS ] || fail "P108_RUNTIME_ABI_GATE=FAIL"

if [ "$FAIL" -eq 0 ]; then
    STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
    RUN_ROOT="$ARTIFACT_ROOT/p108-run4-$STAMP"
    MEDIA_DIR="$RUN_ROOT/media"
    LOG="$RUN_ROOT/live.log"
    STATUS_BEFORE="$RUN_ROOT/listener-status-before.json"
    STOP_RESPONSE="$RUN_ROOT/listener-stop.json"
    mkdir -p "$MEDIA_DIR"
    chmod 700 "$RUN_ROOT" "$MEDIA_DIR"
    : > "$LOG"
    chmod 600 "$LOG"
    assert_packaged_elf_identity
    assert_packaged_binary_strings "$RUN_ROOT/packaged.strings"
fi

if [ -f "$SECRETS_FILE" ]; then
    echo "P108_SECRETS_PRESENT=true"
    echo "SECRETS_CONTENT_EMITTED=false"
else
    fail "P108_SECRETS_PRESENT=false"
fi

if [ "$FAIL" -ne 0 ]; then
    echo "P108_PREFLIGHT=FAIL"
    exit 1
fi

echo "P108_PREFLIGHT=PASS"
echo "P108_RUN_ROOT=$RUN_ROOT"
echo "P108_LIVE_INVOCATION_LIMIT=1"
echo "P108_AUTOMATIC_RETRY=false"
echo "P108_DOOR_ACTION_ALLOWED=false"
echo "P108_GATE_ACTION_ALLOWED=false"
echo "P108_HOME_ASSISTANT_CORE_RESTART_ALLOWED=false"

post_control status "$STATUS_BEFORE" 10
STATUS_RC=$?
if [ "$STATUS_RC" -eq 0 ] && status_ready "$STATUS_BEFORE"; then
    LISTENER_READY_BEFORE=PASS
    LISTENER_RECONNECT_COUNT_BEFORE="$(json_scalar "$STATUS_BEFORE" reconnect_count)"
    echo "LISTENER_READY_BEFORE=PASS"
    echo "LISTENER_RECONNECT_COUNT_BEFORE=$LISTENER_RECONNECT_COUNT_BEFORE"
else
    fail "LISTENER_READY_BEFORE=FAIL"
fi
[ "$FAIL" -eq 0 ] || exit 1

LISTENER_STOPPED=1
post_control stop "$STOP_RESPONSE" 20
STOP_RC=$?
if [ "$STOP_RC" -eq 0 ] && status_stopped "$STOP_RESPONSE"; then
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

start_udp_sink video "$VIDEO_RTP_PORT" "$MEDIA_DIR/video.rtpdatagrams" "$MEDIA_DIR/video.lengths" "$MEDIA_DIR/video.count" "$OUTER_TIMEOUT_SECONDS"
start_udp_sink audio "$AUDIO_RTP_PORT" "$MEDIA_DIR/audio.rtpdatagrams" "$MEDIA_DIR/audio.lengths" "$MEDIA_DIR/audio.count" "$OUTER_TIMEOUT_SECONDS"

echo "PACKAGED_BINARY_SHA_BEFORE_RUN=$PACKAGED_BINARY_SHA_BEFORE_RUN"
echo "RUNTIME_ABI_GATE=$RUNTIME_ABI_GATE"
echo "PACKAGED_BINARY_REBUILT=false"
echo "RUNTIME_LOADER=$RUNTIME_LOADER"
echo "RUNTIME_LIBRARY_PATH=$RUNTIME_LIBRARY_PATH"
echo "=== EXACTLY ONE P108 PACKAGED MUSL LIVE INVOCATION ==="
LIVE_INVOCATIONS=1
echo "P108_EXACTLY_ONCE_GATE=PASS"
EXECUTABLE_MEDIA_PATH="$PACKAGED_BINARY"
timeout --signal=TERM --kill-after=5s "${MEDIA_SESSION_TIMEOUT_SECONDS}s" \
    "$RUNTIME_LOADER" --library-path "$RUNTIME_LIBRARY_PATH" "$EXECUTABLE_MEDIA_PATH" > "$LOG" 2>&1 &
MEDIA_PID=$!
echo "P108_MEDIA_STARTED=true"
echo "P108_MEDIA_PID_REDACTED=true"

while [ "$OBSERVATION_SECONDS" -lt "$LIVE_WINDOW_SECONDS" ]; do
    if ! kill -0 "$MEDIA_PID" 2>/dev/null; then
        break
    fi
    sleep 1
    OBSERVATION_SECONDS=$((OBSERVATION_SECONDS + 1))
done
echo "P108_OBSERVATION_SECONDS=$OBSERVATION_SECONDS"
stop_media_if_needed

wait "$MEDIA_PID" || MEDIA_RC=$?
if [ "$MEDIA_RC" = NOT_REACHED ]; then
    MEDIA_RC=0
fi
MEDIA_PID=""
echo "P108_MEDIA_RC=$MEDIA_RC"

stop_sink_if_needed "$VIDEO_SINK_PID"
stop_sink_if_needed "$AUDIO_SINK_PID"
VIDEO_SINK_PID=""
AUDIO_SINK_PID=""
packaged_processes_remaining
collect_log_markers
emit_len24_lines | sed -n "1,${LEN24_FALLBACK_SUMMARY_MAX}p"
derive_teardown_confidence

if [ "$TEARDOWN_CONFIDENCE" = CONFIRMED ]; then
    restore_listener || true
else
    LISTENER_RESTART_SUPPRESSED=true
    echo "LISTENER_RESTART_SUPPRESSED=true"
    echo "LISTENER_RESTORE_FINAL_GATE=FAIL"
fi

postprocess_media
PACKAGED_BINARY_SHA_AFTER_RUN="$(sha256sum "$PACKAGED_BINARY" | awk '{print $1}')"
echo "PACKAGED_BINARY_SHA_AFTER_RUN=$PACKAGED_BINARY_SHA_AFTER_RUN"

[ "$LIVE_INVOCATIONS" -eq 1 ] || fail "P108_EXACTLY_ONCE_GATE=FAIL"
[ "$P108_DOOR_RESULT_COUNT" -eq 0 ] || fail "P108_DOOR_RESULT_GATE=FAIL"
[ "$P108_GATE_TOKEN_COUNT" -eq 0 ] || fail "P108_GATE_TOKEN_GATE=FAIL"
[ "$PACKAGED_BINARY_SHA_AFTER_RUN" = "$PACKAGED_BINARY_SHA_BEFORE_RUN" ] || fail "P108_PACKAGED_BINARY_SHA_AFTER_GATE=FAIL"

if [ "$TEARDOWN_CONFIDENCE" = UNCERTAIN ]; then
    print_summary
    trap - EXIT
    exit 90
fi
if [ "$FAIL" -ne 0 ]; then
    print_summary
    trap - EXIT
    exit 1
fi
print_summary
trap - EXIT
exit 0
