#!/usr/bin/env bash
# CT120 research-only P111 corrected final RUN5 runner.
#
# Offline preparation only in this worktree. A future authorized live run must
# execute exactly one pinned P105/RUN3 base-wrapper invocation. The wrapper owns
# offer -> transform_offer -> OAuth -> cloud P2P -> remote.sdp; a research-only
# holder shim only verifies and execs the frozen PR #106 packaged musl helper.
# All prelive gates run before listener control.

set -u -o pipefail
umask 077

RUNNER_EXECUTED_PATH="${BASH_SOURCE[0]}"
RUNNER_EXECUTED_DIR="$(cd "$(dirname "$RUNNER_EXECUTED_PATH")" && pwd)"
RESEARCH_ARTIFACT_ROOT="${P111_RESEARCH_ARTIFACT_ROOT:-$(cd "$RUNNER_EXECUTED_DIR/../../../.." && pwd)}"
REPO="${REPO:-/root/comelit-door-diag-pr106}"
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
BASE_WRAPPER=/usr/local/sbin/comelit-p2p-cloud-probe
BASE_WRAPPER_SHA256=a564535dff0cf10b1fe4766171f2960c52fb581f1c816cf81d2992c5c84e79c9
CT120_IP=192.168.1.85
HA_WEBHOOK_URL="${HA_WEBHOOK_URL:-http://192.168.1.108:8123/api/webhook/comelit-ha-ring-test-control-v1}"
SECRETS_FILE="${SECRETS_FILE:-/root/.config/comelit/secrets.env}"
HOLDER_SHIM_REL=safety-poc/research/media/v1/p111_packaged_musl_holder_shim.sh
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
PACKAGED_BINARY=""
PACKAGED_LIB_DIR=""
PACKAGED_BINARY_SHA_BEFORE_RUN=NOT_REACHED
PACKAGED_BINARY_SHA_AFTER_RUN=NOT_REACHED
RUNTIME_ABI_GATE=FAIL
RUNTIME_LOADER=NONE
RUNTIME_LIBRARY_PATH=NONE
RUNTIME_ROOT=NONE
BASE_WRAPPER_GATE=FAIL
HOLDER_SHIM_GATE=FAIL
HOLDER_ANCHOR_REPLACED_EXACTLY_ONCE=FAIL
RTP_CAPTURE_SELFTEST=FAIL
MEDIA_POSTPROCESS_SELFTEST=FAIL
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
RESEARCH_DELIVERY_GATE=FAIL
PACKAGED_MUSL_EXEC_GATE=FAIL
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
H264_FU_A_COUNT=0
H264_STAP_A_COUNT=0
P110_DOOR_RESULT_COUNT=0
P110_GATE_TOKEN_COUNT=0
FFMPEG_PRESENT=false
FFPROBE_PRESENT=false
CANDIDATE_WRAPPER=""
HOLDER_SHIM=""
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
        echo "P111_CAPTURE_VIDEO_PID_REDACTED=true"
    else
        AUDIO_SINK_PID="$pid"
        echo "P111_CAPTURE_AUDIO_PID_REDACTED=true"
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
fu_header = None

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
            fu_header = bytes([(fu_indicator & 0xE0) | original_type])
            fu_parts = [fu_header, media[2:]]
        elif fu_parts:
            fu_parts.append(media[2:])
        if end and fu_parts:
            emit(b"".join(fu_parts))
            fu_parts = []
            fu_header = None

out.write_bytes(bytes(annex))
os.chmod(out, 0o600)
stats.write_text(
    "\n".join([
        f"P111_H264_SPS_COUNT={sps}",
        f"P111_H264_PPS_COUNT={pps}",
        f"P111_H264_IDR_COUNT={idr}",
        f"P111_H264_FU_A_COUNT={fua}",
        f"P111_H264_STAP_A_COUNT={stapa}",
        f"P111_VIDEO_RTP_DATAGRAMS={len(payloads)}",
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
        H264_SPS_COUNT="$(awk -F= '/^P111_H264_SPS_COUNT=/{print $2}' "$stats")"
        H264_PPS_COUNT="$(awk -F= '/^P111_H264_PPS_COUNT=/{print $2}' "$stats")"
        H264_IDR_COUNT="$(awk -F= '/^P111_H264_IDR_COUNT=/{print $2}' "$stats")"
        H264_FU_A_COUNT="$(awk -F= '/^P111_H264_FU_A_COUNT=/{print $2}' "$stats")"
        H264_STAP_A_COUNT="$(awk -F= '/^P111_H264_STAP_A_COUNT=/{print $2}' "$stats")"
    fi
    echo "P111_H264_SPS_COUNT=$H264_SPS_COUNT"
    echo "P111_H264_PPS_COUNT=$H264_PPS_COUNT"
    echo "P111_H264_IDR_COUNT=$H264_IDR_COUNT"
    echo "P111_H264_FU_A_COUNT=$H264_FU_A_COUNT"
    echo "P111_H264_STAP_A_COUNT=$H264_STAP_A_COUNT"
    echo "P111_VIDEO_RTP_DATAGRAMS=$VIDEO_RTP_DATAGRAMS"
    echo "P111_AUDIO_RTP_DATAGRAMS=$AUDIO_RTP_DATAGRAMS"

    if [ "${P111_POSTPROCESS_MOCK:-0}" = 1 ]; then
        if [ -s "$annex" ]; then
            FFPROBE_H264=PASS
            printf 'P111 mocked jpeg\n' > "$still"
            printf 'P111 mocked mp4\n' > "$clip"
            chmod 600 "$still" "$clip"
            JPEG_RESULT=PASS
            SHORT_VIDEO_RESULT=PASS
        else
            FFPROBE_H264=FAIL
            JPEG_RESULT=FAIL
            SHORT_VIDEO_RESULT=FAIL
        fi
        echo "P111_FFPROBE_H264=$FFPROBE_H264"
        echo "P111_JPEG_RESULT=$JPEG_RESULT"
        echo "P111_SHORT_VIDEO_RESULT=$SHORT_VIDEO_RESULT"
        return 0
    fi

    if [ "$FFMPEG_PRESENT" != true ] || [ "$FFPROBE_PRESENT" != true ]; then
        FFPROBE_H264=FAIL
        JPEG_RESULT=FAIL
        SHORT_VIDEO_RESULT=FAIL
        echo "P111_FFPROBE_H264=$FFPROBE_H264"
        echo "P111_JPEG_RESULT=$JPEG_RESULT"
        echo "P111_SHORT_VIDEO_RESULT=$SHORT_VIDEO_RESULT"
        return 0
    fi

    if ffprobe -v error -f h264 "$annex" > "$MEDIA_DIR/ffprobe.out" 2> "$MEDIA_DIR/ffprobe.err"; then
        FFPROBE_H264=PASS
    else
        FFPROBE_H264=FAIL
    fi
    echo "P111_FFPROBE_H264=$FFPROBE_H264"
    chmod 600 "$MEDIA_DIR/ffprobe.out" "$MEDIA_DIR/ffprobe.err" 2>/dev/null || true

    if ffmpeg -hide_banner -loglevel error -y -f h264 -i "$annex" -frames:v 1 "$still" > "$MEDIA_DIR/ffmpeg-still.out" 2> "$MEDIA_DIR/ffmpeg-still.err" &&
       [ -s "$still" ]; then
        chmod 600 "$still"
        JPEG_RESULT=PASS
        echo "P111_JPEG_RESULT=PASS"
        echo "P111_JPEG_PATH=$still"
        echo "P111_JPEG_BYTES=$(wc -c < "$still" | awk '{print $1}')"
        echo "P111_JPEG_SHA256=$(sha256sum "$still" | awk '{print $1}')"
    else
        JPEG_RESULT=FAIL
        echo "P111_JPEG_RESULT=FAIL"
    fi
    chmod 600 "$MEDIA_DIR/ffmpeg-still.out" "$MEDIA_DIR/ffmpeg-still.err" 2>/dev/null || true

    if ffmpeg -hide_banner -loglevel error -y -f h264 -i "$annex" -an -t 5 -c:v copy "$clip" > "$MEDIA_DIR/ffmpeg-clip.out" 2> "$MEDIA_DIR/ffmpeg-clip.err" &&
       [ -s "$clip" ]; then
        chmod 600 "$clip"
        SHORT_VIDEO_RESULT=PASS
        echo "P111_SHORT_VIDEO_RESULT=PASS"
        echo "P111_SHORT_VIDEO_PATH=$clip"
        echo "P111_SHORT_VIDEO_BYTES=$(wc -c < "$clip" | awk '{print $1}')"
        echo "P111_SHORT_VIDEO_DURATION=$(ffprobe -v error -show_entries format=duration -of default=nk=1:nw=1 "$clip" 2>/dev/null || echo UNKNOWN)"
        echo "P111_SHORT_VIDEO_SHA256=$(sha256sum "$clip" | awk '{print $1}')"
    else
        SHORT_VIDEO_RESULT=FAIL
        echo "P111_SHORT_VIDEO_RESULT=FAIL"
    fi
    chmod 600 "$MEDIA_DIR/ffmpeg-clip.out" "$MEDIA_DIR/ffmpeg-clip.err" 2>/dev/null || true
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
    CLOUD_NEGOTIATION_COUNT="$(count_log_literal 'P2P_CLOUD_PROBE_RC=0')"
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
    elif pgrep -af "$PACKAGED_BINARY|$RUNTIME_LOADER.*$PACKAGED_BINARY" >/dev/null 2>&1; then
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

assert_base_wrapper_identity() {
    local actual
    [ -f "$BASE_WRAPPER" ] || fail "BASE_WRAPPER_PRESENT=false"
    if [ -f "$BASE_WRAPPER" ]; then
        actual="$(sha256sum "$BASE_WRAPPER" | awk '{print $1}')"
        echo "BASE_WRAPPER_SHA256=$actual"
        if [ "$actual" = "$BASE_WRAPPER_SHA256" ]; then
            BASE_WRAPPER_GATE=PASS
            echo "BASE_WRAPPER_GATE=PASS"
        else
            fail "BASE_WRAPPER_GATE=FAIL"
        fi
    fi
}

prepare_holder_shim() {
    local source="$RESEARCH_ARTIFACT_ROOT/$HOLDER_SHIM_REL"
    HOLDER_SHIM="$RUN_ROOT/p111_packaged_musl_holder_shim.sh"
    [ -x "$source" ] || fail "HOLDER_SHIM_PRESENT=false"
    install -m 700 "$source" "$HOLDER_SHIM"
    HOLDER_SHIM_SHA256="$(sha256sum "$HOLDER_SHIM" | awk '{print $1}')"
    HOLDER_SHIM_SOURCE_SHA256="$(sha256sum "$source" | awk '{print $1}')"
    [ "$HOLDER_SHIM_SHA256" = "$HOLDER_SHIM_SOURCE_SHA256" ] || fail "HOLDER_SHIM_SHA_GATE=FAIL"
    HOLDER_SHIM_GATE=PASS
    echo "HOLDER_SHIM_SHA256=$HOLDER_SHIM_SHA256"
    echo "HOLDER_SHIM_GATE=PASS"
}

prepare_candidate_wrapper() {
    CANDIDATE_WRAPPER="$RUN_ROOT/comelit-p2p-cloud-probe-p111"
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
    raise SystemExit("P111_WRAPPER_HOLDER_ANCHOR=FAIL")
text = text.replace(needle, f'"{holder}"', 1)
result_block = '''if [ "$HOLDER_RC" -eq 0 ] \\
   && [ "$UAUT_OPEN_PASS" = true ]; then

    echo "P2_VIP_UAUT_OPEN=PASS"
    exit 0
fi

echo "P2_VIP_UAUT_OPEN=FAIL"
exit 27
'''
replacement_block = '''if [ "$UAUT_OPEN_PASS" = true ]; then
    echo "P2_VIP_UAUT_OPEN=PASS"
else
    echo "P2_VIP_UAUT_OPEN=FAIL"
fi

echo "P2_HOLDER_TERMINAL_RC=$HOLDER_RC"

HOLDER_TERMINAL_RESULT=FAIL
HOLDER_TERMINAL_PROOF_GRACEFUL_COMPLETE=false
HOLDER_TERMINAL_PROOF_NOTIFY_FATAL=false
HOLDER_TERMINAL_PROOF_TIMEOUT=false
if [ "$HOLDER_RC" -eq 0 ]; then
    HOLDER_TERMINAL_RESULT=PASS
elif [ ! -r "$RUN/ice-holder.log" ]; then
    HOLDER_TERMINAL_RESULT=UNKNOWN
else
    grep -q '^PSEUDOTCP_GRACEFUL_CLOSE_COMPLETE=true$' "$RUN/ice-holder.log" && HOLDER_TERMINAL_PROOF_GRACEFUL_COMPLETE=true
    grep -q '^PSEUDOTCP_NOTIFY_PACKET_CLASS=FATAL$' "$RUN/ice-holder.log" && HOLDER_TERMINAL_PROOF_NOTIFY_FATAL=true
    grep -q '^PSEUDOTCP_GRACEFUL_CLOSE_TIMEOUT=true$' "$RUN/ice-holder.log" && HOLDER_TERMINAL_PROOF_TIMEOUT=true
    if grep -q '^PSEUDOTCP_GRACEFUL_CLOSE_REQUESTED=true$' "$RUN/ice-holder.log" \\
       && grep -q '^ICE_HOLDER_STOP=true$' "$RUN/ice-holder.log" \\
       && grep -q '^PSEUDOTCP_GRACEFUL_CLOSE_FORCE_RST_SENT=false$' "$RUN/ice-holder.log" \\
       && [ "$HOLDER_TERMINAL_PROOF_GRACEFUL_COMPLETE" = true ] \\
       && [ "$HOLDER_TERMINAL_PROOF_NOTIFY_FATAL" = false ] \\
       && [ "$HOLDER_TERMINAL_PROOF_TIMEOUT" = false ]; then
        HOLDER_TERMINAL_RESULT=EXPECTED_SHUTDOWN
    fi
fi
echo "P2_HOLDER_TERMINAL_PROOF_GRACEFUL_COMPLETE=$HOLDER_TERMINAL_PROOF_GRACEFUL_COMPLETE"
echo "P2_HOLDER_TERMINAL_PROOF_NOTIFY_FATAL=$HOLDER_TERMINAL_PROOF_NOTIFY_FATAL"
echo "P2_HOLDER_TERMINAL_PROOF_TIMEOUT=$HOLDER_TERMINAL_PROOF_TIMEOUT"
echo "P2_HOLDER_TERMINAL_RESULT=$HOLDER_TERMINAL_RESULT"

if [ "$UAUT_OPEN_PASS" = true ] \\
   && { [ "$HOLDER_TERMINAL_RESULT" = PASS ] || [ "$HOLDER_TERMINAL_RESULT" = EXPECTED_SHUTDOWN ]; }; then
    exit 0
fi

exit 27
'''
if text.count(result_block) != 1:
    raise SystemExit("P111_WRAPPER_UAUT_DECOUPLE_ANCHOR=FAIL")
text = text.replace(result_block, replacement_block, 1)
legacy_run_dir = "/run/comelit-p2p"
media_run_dir = "/run/comelit-media"
run_dir_count = text.count(legacy_run_dir)
if run_dir_count < 1:
    raise SystemExit("P111_WRAPPER_RUN_DIR_ANCHOR=FAIL")
text = text.replace(legacy_run_dir, media_run_dir)
if text.count(holder) != 1:
    raise SystemExit("P111_WRAPPER_HOLDER_REPLACEMENT_COUNT=FAIL")
out.write_text(text, encoding="utf-8")
os.chmod(out, 0o700)
print("HOLDER_ANCHOR_REPLACED_EXACTLY_ONCE=PASS")
print(f"P111_WRAPPER_RUN_DIR_REPLACEMENTS={run_dir_count}")
PY
    local rc=$?
    [ "$rc" -eq 0 ] || fail "P111_WRAPPER_REWRITE_GATE=FAIL"
    bash -n "$CANDIDATE_WRAPPER" || fail "P111_WRAPPER_PARSE_GATE=FAIL"
    HOLDER_ANCHOR_REPLACED_EXACTLY_ONCE=PASS
}

run_rtp_capture_selftest() {
    local old_media_dir old_video_pid old_audio_pid
    old_media_dir="$MEDIA_DIR"
    old_video_pid="$VIDEO_SINK_PID"
    old_audio_pid="$AUDIO_SINK_PID"
    MEDIA_DIR="$RUN_ROOT/rtp-selftest"
    mkdir -p "$MEDIA_DIR"
    chmod 700 "$MEDIA_DIR"
    VIDEO_SINK_PID=""
    AUDIO_SINK_PID=""
    if [ "${P111_RTP_CAPTURE_FIXTURE_NO_SOCKET:-0}" = 1 ]; then
        python3 - "$MEDIA_DIR/video.rtpdatagrams" "$MEDIA_DIR/audio.rtpdatagrams" <<'PY'
from pathlib import Path
import sys

video = Path(sys.argv[1])
audio = Path(sys.argv[2])

def rtp(seq, payload, pt=99):
    return bytes([0x80, pt]) + seq.to_bytes(2, "big") + b"\x00\x00\x00\x01" + b"\x01\x02\x03\x04" + payload

with video.open("wb") as out:
    for seq, payload in enumerate((b"\x67\x42\x00\x1f", b"\x68\xce\x06\xe2", b"\x65\x88\x84\x21"), start=1):
        packet = rtp(seq, payload)
        out.write(len(packet).to_bytes(2, "big"))
        out.write(packet)
with audio.open("wb") as out:
    packet = rtp(1, b"audio", 111)
    out.write(len(packet).to_bytes(2, "big"))
    out.write(packet)
(video.parent / "video.count").write_text("3\n", encoding="utf-8")
(video.parent / "audio.count").write_text("1\n", encoding="utf-8")
(video.parent / "video.lengths").write_text("16 3\n", encoding="utf-8")
(video.parent / "audio.lengths").write_text("17 1\n", encoding="utf-8")
PY
    else
        start_udp_sink video "$VIDEO_RTP_PORT" "$MEDIA_DIR/video.rtpdatagrams" "$MEDIA_DIR/video.lengths" "$MEDIA_DIR/video.count" 5
        start_udp_sink audio "$AUDIO_RTP_PORT" "$MEDIA_DIR/audio.rtpdatagrams" "$MEDIA_DIR/audio.lengths" "$MEDIA_DIR/audio.count" 5
        sleep 0.5
        python3 - "$VIDEO_RTP_PORT" "$AUDIO_RTP_PORT" <<'PY'
import socket
import sys

video_port = int(sys.argv[1])
audio_port = int(sys.argv[2])
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

def rtp(seq, payload):
    return bytes([0x80, 99]) + seq.to_bytes(2, "big") + b"\x00\x00\x00\x01" + b"\x01\x02\x03\x04" + payload

for seq, payload in enumerate((b"\x67\x42\x00\x1f", b"\x68\xce\x06\xe2", b"\x65\x88\x84\x21"), start=1):
    sock.sendto(rtp(seq, payload), ("127.0.0.1", video_port))
sock.sendto(bytes([0x80, 111]) + b"\x00\x01\x00\x00\x00\x01\x01\x02\x03\x04audio", ("127.0.0.1", audio_port))
PY
        sleep 0.5
        stop_sink_if_needed "$VIDEO_SINK_PID"
        stop_sink_if_needed "$AUDIO_SINK_PID"
        wait "$VIDEO_SINK_PID" 2>/dev/null || true
        wait "$AUDIO_SINK_PID" 2>/dev/null || true
    fi
    VIDEO_SINK_PID="$old_video_pid"
    AUDIO_SINK_PID="$old_audio_pid"
    P111_POSTPROCESS_MOCK=1 postprocess_media
    if [ "$VIDEO_RTP_DATAGRAMS" -gt 0 ] &&
       [ "$AUDIO_RTP_DATAGRAMS" -gt 0 ] &&
       [ "$H264_SPS_COUNT" -gt 0 ] &&
       [ "$H264_PPS_COUNT" -gt 0 ] &&
       [ "$H264_IDR_COUNT" -gt 0 ]; then
        RTP_CAPTURE_SELFTEST=PASS
        MEDIA_POSTPROCESS_SELFTEST=PASS
        echo "RTP_CAPTURE_SELFTEST=PASS"
        echo "MEDIA_POSTPROCESS_SELFTEST=PASS"
    else
        fail "RTP_CAPTURE_SELFTEST=FAIL"
        fail "MEDIA_POSTPROCESS_SELFTEST=FAIL"
    fi
    MEDIA_DIR="$old_media_dir"
    VIDEO_RTP_DATAGRAMS=0
    AUDIO_RTP_DATAGRAMS=0
    H264_SPS_COUNT=0
    H264_PPS_COUNT=0
    H264_IDR_COUNT=0
    H264_FU_A_COUNT=0
    H264_STAP_A_COUNT=0
    FFPROBE_H264=NOT_REACHED
    JPEG_RESULT=NOT_REACHED
    SHORT_VIDEO_RESULT=NOT_REACHED
}

assert_no_credential_bearing_origin() {
    if git -C "$REPO" remote -v 2>/dev/null | grep -E '(://[^/@]+:[^/@]+@|Authorization|access_token|oauth|COMELIT|VIP)' >/dev/null; then
        fail "P110_CREDENTIAL_ORIGIN_GATE=FAIL"
    else
        echo "P110_CREDENTIAL_ORIGIN_GATE=PASS"
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
    [ "$VIDEO_RTP_DATAGRAMS" -gt 0 ] || return 1
    [ "$AUDIO_RTP_DATAGRAMS" -gt 0 ] || return 1
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
    [ "$NO_RETRY_GATE" = PASS ] || return 1
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
    echo "SELECTED_LIVE_BOOTSTRAP=PROVEN_P105_RUN3_BASE_WRAPPER"
    echo "BASE_WRAPPER_PATH=$BASE_WRAPPER"
    echo "BASE_WRAPPER_GATE=$BASE_WRAPPER_GATE"
    echo "HOLDER_ANCHOR_REPLACED_EXACTLY_ONCE=$HOLDER_ANCHOR_REPLACED_EXACTLY_ONCE"
    echo "HOLDER_SHIM_PATH=$HOLDER_SHIM"
    echo "HOLDER_SHIM_GATE=$HOLDER_SHIM_GATE"
    echo "RTP_CAPTURE_SELFTEST=$RTP_CAPTURE_SELFTEST"
    echo "MEDIA_POSTPROCESS_SELFTEST=$MEDIA_POSTPROCESS_SELFTEST"
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

for command in git python3 sha256sum timeout strings grep curl ip awk head wc readelf sed stat install pgrep; do
    command -v "$command" >/dev/null 2>&1 || fail "P110_MISSING_COMMAND=$command"
done
if command -v ffmpeg >/dev/null 2>&1; then
    FFMPEG_PRESENT=true
fi
if command -v ffprobe >/dev/null 2>&1; then
    FFPROBE_PRESENT=true
fi

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
mkdir -p "$MEDIA_DIR"
chmod 700 "$RUN_ROOT" "$MEDIA_DIR"
: > "$LOG"
chmod 600 "$LOG"

assert_no_credential_bearing_origin
assert_packaged_binary_identity "$REPO"
detect_runtime_boundary "$REPO" || true
[ "$RUNTIME_ABI_GATE" = PASS ] || fail "MUSL_ABI_GATE=FAIL"
assert_packaged_elf_identity
assert_base_wrapper_identity
prepare_holder_shim
prepare_candidate_wrapper
run_rtp_capture_selftest
assert_no_door_gate_paths "$RUN_ROOT/packaged.strings"
RUNNER_SELF_SHA256="$(sha256sum "$RUNNER_EXECUTED_PATH" | awk '{print $1}')"
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
    RESEARCH_DELIVERY_GATE=PASS
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

start_udp_sink video "$VIDEO_RTP_PORT" "$MEDIA_DIR/video.rtpdatagrams" "$MEDIA_DIR/video.lengths" "$MEDIA_DIR/video.count" "$OUTER_MAX_SECONDS"
start_udp_sink audio "$AUDIO_RTP_PORT" "$MEDIA_DIR/audio.rtpdatagrams" "$MEDIA_DIR/audio.lengths" "$MEDIA_DIR/audio.count" "$OUTER_MAX_SECONDS"

echo "=== EXACTLY ONE P111 P105/RUN3 BASE WRAPPER LIVE INVOCATION ==="
LIVE_INVOCATIONS=1
BINARY_EXECUTED=true
PACKAGED_MUSL_EXEC_GATE=PASS
export P111_PR106_CHECKOUT="$REPO"
export P111_RUNTIME_ROOT="$RUNTIME_ROOT"
timeout --signal=TERM --kill-after=5s "${MEDIA_SESSION_MAX_SECONDS}s" \
    "$CANDIDATE_WRAPPER" > "$LOG" 2>&1 &
WRAPPER_PID=$!
MEDIA_PID="$WRAPPER_PID"
echo "P111_WRAPPER_STARTED=true"
echo "P111_WRAPPER_PID_REDACTED=true"
NETWORK_IO_PERFORMED=true

while [ "$OBSERVATION_SECONDS" -lt "$OBSERVATION_SECONDS_LIMIT" ]; do
    if ! kill -0 "$WRAPPER_PID" 2>/dev/null; then
        break
    fi
    sleep 1
    OBSERVATION_SECONDS=$((OBSERVATION_SECONDS + 1))
done
echo "OBSERVATION_SECONDS=$OBSERVATION_SECONDS"
stop_media_if_needed
wait "$WRAPPER_PID" || MEDIA_RC=$?
[ "$MEDIA_RC" = NOT_REACHED ] && MEDIA_RC=0
MEDIA_PID=""
WRAPPER_PID=""
packaged_processes_remaining
stop_sink_if_needed "$VIDEO_SINK_PID"
stop_sink_if_needed "$AUDIO_SINK_PID"
wait "$VIDEO_SINK_PID" 2>/dev/null || true
wait "$AUDIO_SINK_PID" 2>/dev/null || true
VIDEO_SINK_PID=""
AUDIO_SINK_PID=""
collect_log_markers
[ "$CLOUD_NEGOTIATION_COUNT" -eq 1 ] && ONE_CLOUD_NEGOTIATION_GATE=PASS || fail "P111_ONE_CLOUD_NEGOTIATION_GATE=FAIL"
derive_teardown_confidence
postprocess_media

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
