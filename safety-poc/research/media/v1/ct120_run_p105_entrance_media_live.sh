#!/usr/bin/env bash
# CT120 research-only P105 bounded entrance media live runner.
#
# Purpose: build the P101/P105 candidate on CT120, pause only the HA Comelit
# listener, execute one bounded entrance-media invocation, capture local RTP
# evidence, and restore the listener only after teardown is confirmed.
#
# Single-invocation contract: LIVE_INVOCATIONS is hard-coded to 1 immediately
# before the wrapper entry point and the P105_EXACTLY_ONCE gate rejects any
# other value. There is no automatic retry path.
#
# Bounds: the media observation window is bounded to 45 s or less
# (LIVE_WINDOW_SECONDS=40), and the wrapper/capture outer bound is 75 s
# (OUTER_TIMEOUT_SECONDS=75).
#
# Safety rules: no Door action is allowed, no gate action is allowed, Home
# Assistant Core is never stopped or restarted, and fail-closed teardown is
# enforced. If upstream/media teardown is uncertain, the listener is not
# restarted and the runner exits 90 for operator intervention.

set -u -o pipefail
umask 077

REPO=/root/comelit-door-diag-repo
BRANCH=fix/p105-complete-post-000a-ack-cycle
EXPECTED_MIN_PARENT=949f290158702b1a85d8e900449d0807d54414a9
CT120_IP=192.168.1.85
HA_WEBHOOK_URL="${HA_WEBHOOK_URL:-http://192.168.1.108:8123/api/webhook/comelit-ha-ring-test-control-v1}"
BASE_WRAPPER=/usr/local/sbin/comelit-p2p-cloud-probe
BASE_WRAPPER_SHA256=a564535dff0cf10b1fe4766171f2960c52fb581f1c816cf81d2992c5c84e79c9
SECRETS_FILE=/root/.config/comelit/secrets.env
SOURCE_REL=safety-poc/research/door/v1_5_7/comelit-v4-persistent-ctpp-door.c
TRANSFORM_REL=safety-poc/research/media/v1/entrance_p105_len24_fallback_diagnostic_transform.py
RUN_DIR=/run/comelit-media
STOP_FILE="$RUN_DIR/stop"
VIDEO_RTP_PORT=17899
AUDIO_RTP_PORT=17808
LIVE_WINDOW_SECONDS=40
OUTER_TIMEOUT_SECONDS=75
CANDIDATE_HOLDER_NAME=comelit-p105-live
WRAPPER_NAME=comelit-p2p-cloud-probe-p105
ARTIFACT_ROOT=/root/comelit-artifacts

LIVE_RUN="${LIVE_RUN:-1}"
HYPOTHESIS_ID="${HYPOTHESIS_ID:-p105-p101-profile-gate-plus-len24-classification}"
LEN24_FALLBACK_SUMMARY_MAX=32

FAIL=0
SUMMARY_PRINTED=0
LISTENER_STOPPED=0
LISTENER_RESTART_SUPPRESSED=false
RESTORE_OK=0
RESTORE_ATTEMPTS=0
TEARDOWN_CONFIDENCE=UNCERTAIN
LIVE_INVOCATIONS=0
WRAPPER_PID=""
VIDEO_SINK_PID=""
AUDIO_SINK_PID=""
RUN_ROOT=""
BUILD=""
MEDIA_DIR=""
LOG=""
STATUS_AFTER=""
CURRENT_HEAD=UNKNOWN
REPO_HEAD=UNKNOWN
WRAPPER_RC=NOT_REACHED
OBSERVATION_SECONDS=0
LISTENER_READY_BEFORE=FAIL
LISTENER_STOP_GATE=FAIL
LISTENER_RESTORE_READY=FAIL
LISTENER_READY_AFTER=FAIL
LISTENER_RECONNECT_COUNT_BEFORE=UNKNOWN
LISTENER_RECONNECT_COUNT_AFTER=UNKNOWN
CAMPAIGN_PROCESSES_REMAINING=FOUND
CTPP_OPEN_COUNT=0
SECOND_CTPP_OPEN=false
DOOR_RESULT_COUNT=0
UPSTREAM_MEDIA_ACTIVE_AT_EXIT=false
FFMPEG_PRESENT=false
FFPROBE_PRESENT=false
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
PSEUDOTCP_NOTIFY_PACKET_FAIL_LEN=NOT_OBSERVED

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

stop_candidate_if_needed() {
    if [ -z "$WRAPPER_PID" ] || ! kill -0 "$WRAPPER_PID" 2>/dev/null; then
        return 0
    fi

    echo "P105_STOP_REQUESTED=true"
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

    echo "P105_STOP_ESCALATION=TERM"
    kill -TERM "$WRAPPER_PID" 2>/dev/null || true
    sleep 2
    if kill -0 "$WRAPPER_PID" 2>/dev/null; then
        echo "P105_STOP_ESCALATION=KILL"
        kill -KILL "$WRAPPER_PID" 2>/dev/null || true
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
    CTPP_OPEN_COUNT="$(count_log_literal 'P78_RTPC_OPEN_1_SENT=PASS')"
    local open2_count
    open2_count="$(count_log_literal 'P78_RTPC_OPEN_2_SENT=PASS')"
    if [ "$open2_count" -eq 0 ]; then
        SECOND_CTPP_OPEN=false
    else
        SECOND_CTPP_OPEN=true
    fi
    DOOR_RESULT_COUNT="$(count_log_literal 'V4_DOOR_RESULT=')"
    LEN24_FALLBACK_LINES_EMITTED="$(emit_len24_lines | awk -F= '/^LEN24_FALLBACK_LINES_EMITTED=/{print $2}')"
}

campaign_processes_remaining() {
    if pgrep -af "$WRAPPER_NAME|$CANDIDATE_HOLDER_NAME" >/dev/null 2>&1; then
        CAMPAIGN_PROCESSES_REMAINING=FOUND
    else
        CAMPAIGN_PROCESSES_REMAINING=NONE
    fi
    echo "P105_CAMPAIGN_PROCESSES_REMAINING=$CAMPAIGN_PROCESSES_REMAINING"
}

derive_teardown_confidence() {
    local wrapper_gone=true
    if [ -n "$WRAPPER_PID" ] && kill -0 "$WRAPPER_PID" 2>/dev/null; then
        wrapper_gone=false
    fi

    # The media session is owned by the candidate helper process. Once the
    # helper is provably gone and no campaign-owned process remains, upstream
    # ownership is released. P80_MEDIA_ACTIVE=true is a historical in-run
    # observation and MUST NOT by itself force UNCERTAIN. WRAPPER_RC=124 (outer
    # timeout expiry) or 137 (SIGKILL) means graceful close is NOT proven, so
    # fail closed: no listener start. A PSEUDOTCP_NOTIFY_PACKET=FAIL observation
    # must not by itself force UNCERTAIN either.
    if [ "$wrapper_gone" = true ] &&
       [ "$CAMPAIGN_PROCESSES_REMAINING" = NONE ]; then
        UPSTREAM_MEDIA_ACTIVE_AT_EXIT=false
    else
        UPSTREAM_MEDIA_ACTIVE_AT_EXIT=true
    fi

    if [ "$UPSTREAM_MEDIA_ACTIVE_AT_EXIT" = false ] &&
       [ "$WRAPPER_RC" != 124 ] &&
       [ "$WRAPPER_RC" != 137 ]; then
        TEARDOWN_CONFIDENCE=CONFIRMED
    else
        TEARDOWN_CONFIDENCE=UNCERTAIN
    fi
    echo "P105_UPSTREAM_MEDIA_ACTIVE_AT_EXIT=$UPSTREAM_MEDIA_ACTIVE_AT_EXIT"
    echo "TEARDOWN_CONFIDENCE=$TEARDOWN_CONFIDENCE"
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
        echo "P105_CAPTURE_VIDEO_PID_REDACTED=true"
    else
        AUDIO_SINK_PID="$pid"
        echo "P105_CAPTURE_AUDIO_PID_REDACTED=true"
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
        f"P105_H264_SPS_COUNT={sps}",
        f"P105_H264_PPS_COUNT={pps}",
        f"P105_H264_IDR_COUNT={idr}",
        f"P105_H264_FU_A_COUNT={fua}",
        f"P105_H264_STAP_A_COUNT={stapa}",
        f"P105_VIDEO_RTP_DATAGRAMS={len(payloads)}",
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
        H264_SPS_COUNT="$(awk -F= '/^P105_H264_SPS_COUNT=/{print $2}' "$stats")"
        H264_PPS_COUNT="$(awk -F= '/^P105_H264_PPS_COUNT=/{print $2}' "$stats")"
        H264_IDR_COUNT="$(awk -F= '/^P105_H264_IDR_COUNT=/{print $2}' "$stats")"
        H264_FU_A_COUNT="$(awk -F= '/^P105_H264_FU_A_COUNT=/{print $2}' "$stats")"
        H264_STAP_A_COUNT="$(awk -F= '/^P105_H264_STAP_A_COUNT=/{print $2}' "$stats")"
    fi
    echo "P105_H264_SPS_COUNT=$H264_SPS_COUNT"
    echo "P105_H264_PPS_COUNT=$H264_PPS_COUNT"
    echo "P105_H264_IDR_COUNT=$H264_IDR_COUNT"
    echo "P105_H264_FU_A_COUNT=$H264_FU_A_COUNT"
    echo "P105_H264_STAP_A_COUNT=$H264_STAP_A_COUNT"
    echo "P105_VIDEO_RTP_DATAGRAMS=$VIDEO_RTP_DATAGRAMS"
    echo "P105_AUDIO_RTP_DATAGRAMS=$AUDIO_RTP_DATAGRAMS"

    if [ "$FFMPEG_PRESENT" != true ] || [ "$FFPROBE_PRESENT" != true ]; then
        JPEG_RESULT=NOT_PROVABLE_FFMPEG_ABSENT
        SHORT_VIDEO_RESULT=NOT_PROVABLE_FFMPEG_ABSENT
        echo "P105_JPEG_RESULT=$JPEG_RESULT"
        echo "P105_SHORT_VIDEO_RESULT=$SHORT_VIDEO_RESULT"
        return 0
    fi

    if ffprobe -v error -f h264 "$annex" > "$MEDIA_DIR/ffprobe.out" 2> "$MEDIA_DIR/ffprobe.err"; then
        echo "P105_FFPROBE_H264=PASS"
    else
        echo "P105_FFPROBE_H264=FAIL"
    fi
    chmod 600 "$MEDIA_DIR/ffprobe.out" "$MEDIA_DIR/ffprobe.err" 2>/dev/null || true

    if ffmpeg -hide_banner -loglevel error -y -f h264 -i "$annex" -frames:v 1 "$still" > "$MEDIA_DIR/ffmpeg-still.out" 2> "$MEDIA_DIR/ffmpeg-still.err" &&
       [ -s "$still" ]; then
        chmod 600 "$still"
        JPEG_RESULT=PASS
        JPEG_PATH="$still"
        JPEG_SHA256="$(sha256sum "$still" | awk '{print $1}')"
        echo "P105_JPEG_RESULT=PASS"
        echo "P105_JPEG_PATH=$JPEG_PATH"
        echo "P105_JPEG_BYTES=$(wc -c < "$still" | awk '{print $1}')"
        echo "P105_JPEG_SHA256=$JPEG_SHA256"
    else
        JPEG_RESULT=FAIL
        echo "P105_JPEG_RESULT=FAIL"
    fi
    chmod 600 "$MEDIA_DIR/ffmpeg-still.out" "$MEDIA_DIR/ffmpeg-still.err" 2>/dev/null || true

    if ffmpeg -hide_banner -loglevel error -y -f h264 -i "$annex" -an -t 5 -c:v copy "$clip" > "$MEDIA_DIR/ffmpeg-clip.out" 2> "$MEDIA_DIR/ffmpeg-clip.err" &&
       [ -s "$clip" ]; then
        chmod 600 "$clip"
        SHORT_VIDEO_RESULT=PASS
        SHORT_VIDEO_PATH="$clip"
        SHORT_VIDEO_SHA256="$(sha256sum "$clip" | awk '{print $1}')"
        SHORT_VIDEO_DURATION_SEC="$(ffprobe -v error -show_entries format=duration -of default=nk=1:nw=1 "$clip" 2>/dev/null || echo UNKNOWN)"
        echo "P105_SHORT_VIDEO_RESULT=PASS"
        echo "P105_SHORT_VIDEO_PATH=$SHORT_VIDEO_PATH"
        echo "P105_SHORT_VIDEO_BYTES=$(wc -c < "$clip" | awk '{print $1}')"
        echo "P105_SHORT_VIDEO_DURATION=$SHORT_VIDEO_DURATION_SEC"
        echo "P105_SHORT_VIDEO_SHA256=$SHORT_VIDEO_SHA256"
    else
        SHORT_VIDEO_RESULT=FAIL
        echo "P105_SHORT_VIDEO_RESULT=FAIL"
    fi
    chmod 600 "$MEDIA_DIR/ffmpeg-clip.out" "$MEDIA_DIR/ffmpeg-clip.err" 2>/dev/null || true
}

print_summary() {
    if [ "$SUMMARY_PRINTED" -eq 1 ]; then
        return 0
    fi
    SUMMARY_PRINTED=1
    echo "=== COMELIT P105 CT120 LIVE RUN SUMMARY ==="
    echo "P105_LIVE_RUN=$LIVE_RUN"
    echo "P105_HYPOTHESIS_ID=$HYPOTHESIS_ID"
    echo "P105_BRANCH_HEAD=$CURRENT_HEAD"
    echo "P105_LIVE_INVOCATIONS=$LIVE_INVOCATIONS"
    echo "P105_WRAPPER_RC=$WRAPPER_RC"
    echo "P105_OBSERVATION_SECONDS=$OBSERVATION_SECONDS"
    echo "P105_REPO_HEAD=$REPO_HEAD"
    echo "LISTENER_READY_BEFORE=$LISTENER_READY_BEFORE"
    echo "LISTENER_STOP_GATE=$LISTENER_STOP_GATE"
    echo "LISTENER_RESTORE_READY=$LISTENER_RESTORE_READY"
    echo "LISTENER_READY_AFTER=$LISTENER_READY_AFTER"
    echo "LISTENER_RESTART_SUPPRESSED=$LISTENER_RESTART_SUPPRESSED"
    echo "TEARDOWN_CONFIDENCE=$TEARDOWN_CONFIDENCE"
    echo "P105_CAMPAIGN_PROCESSES_REMAINING=$CAMPAIGN_PROCESSES_REMAINING"
    echo "P105_CTPP_OPEN_COUNT=$CTPP_OPEN_COUNT"
    echo "P105_SECOND_CTPP_OPEN=$SECOND_CTPP_OPEN"
    echo "P105_DOOR_RESULT_COUNT=$DOOR_RESULT_COUNT"
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
    echo "PSEUDOTCP_NOTIFY_PACKET_FAIL_LEN=$PSEUDOTCP_NOTIFY_PACKET_FAIL_LEN"
    echo "LEN24_FALLBACK_LINES_EMITTED=$LEN24_FALLBACK_LINES_EMITTED"
    echo "P105_H264_SPS_COUNT=$H264_SPS_COUNT"
    echo "P105_H264_PPS_COUNT=$H264_PPS_COUNT"
    echo "P105_H264_IDR_COUNT=$H264_IDR_COUNT"
    echo "P105_FFMPEG_PRESENT=$FFMPEG_PRESENT"
    echo "P105_JPEG_RESULT=$JPEG_RESULT"
    echo "P105_JPEG_PATH=$JPEG_PATH"
    echo "P105_JPEG_SHA256=$JPEG_SHA256"
    echo "P105_SHORT_VIDEO_RESULT=$SHORT_VIDEO_RESULT"
    echo "P105_SHORT_VIDEO_PATH=$SHORT_VIDEO_PATH"
    echo "P105_SHORT_VIDEO_DURATION_SEC=$SHORT_VIDEO_DURATION_SEC"
    echo "P105_SHORT_VIDEO_SHA256=$SHORT_VIDEO_SHA256"
    echo "P105_RUN_ROOT=${RUN_ROOT:-NONE}"
    echo "DOOR_ACTION_SENT=false"
    echo "GATE_ACTION_SENT=false"
    echo "AUTOMATIC_RETRY=false"
    echo "HOME_ASSISTANT_CORE_STOPPED=false"
    echo "HOME_ASSISTANT_CORE_RESTARTED=false"
    echo "SECRETS_CONTENT_EMITTED=false"
    echo "=== END COMELIT P105 CT120 LIVE RUN SUMMARY ==="
}

on_exit() {
    local original_rc=$?
    stop_candidate_if_needed || true
    stop_sink_if_needed "$VIDEO_SINK_PID" || true
    stop_sink_if_needed "$AUDIO_SINK_PID" || true
    if [ "$LISTENER_STOPPED" -eq 1 ]; then
        restore_listener || true
    fi
    echo "AUTOMATIC_RETRY=false"
    echo "HOME_ASSISTANT_CORE_STOPPED=false"
    echo "HOME_ASSISTANT_CORE_RESTARTED=false"
    echo "DOOR_ACTION_SENT=false"
    if [ "$LISTENER_STOPPED" -eq 1 ] && [ "$TEARDOWN_CONFIDENCE" != CONFIRMED ]; then
        print_summary
        exit 90
    fi
    print_summary
    exit "$original_rc"
}

trap on_exit EXIT
trap 'exit 130' INT TERM HUP

if [ "${EUID}" -ne 0 ]; then
    echo "P105_LIVE_REQUIRES_ROOT=true"
    exit 1
fi

for command in git python3 cc pkg-config sha256sum timeout strings grep curl ip ps od awk; do
    command -v "$command" >/dev/null 2>&1 || fail "P105_MISSING_COMMAND=$command"
done
if command -v ffmpeg >/dev/null 2>&1; then
    FFMPEG_PRESENT=true
fi
if command -v ffprobe >/dev/null 2>&1; then
    FFPROBE_PRESENT=true
fi
echo "P105_FFMPEG_PRESENT=$FFMPEG_PRESENT"
echo "P105_FFPROBE_PRESENT=$FFPROBE_PRESENT"

if ip -4 addr show | grep -Fq "$CT120_IP/"; then
    echo "P105_CT120_IDENTITY=PASS"
else
    fail "P105_CT120_IDENTITY=FAIL"
fi

[ -d "$REPO/.git" ] || fail "P105_REPO_PRESENT=false"
if [ "$FAIL" -eq 0 ]; then
    git -C "$REPO" fetch origin "$BRANCH" || fail "P105_REPO_FETCH=FAIL"
fi
if [ "$FAIL" -eq 0 ]; then
    git -C "$REPO" checkout -B "$BRANCH" "origin/$BRANCH" || fail "P105_REPO_CHECKOUT=FAIL"
fi
if [ "$FAIL" -eq 0 ]; then
    CURRENT_HEAD="$(git -C "$REPO" rev-parse HEAD 2>/dev/null || echo UNKNOWN)"
    REPO_HEAD="$CURRENT_HEAD"
    echo "P105_REPO_HEAD=$REPO_HEAD"
    CURRENT_BRANCH="$(git -C "$REPO" branch --show-current 2>/dev/null || true)"
    [ "$CURRENT_BRANCH" = "$BRANCH" ] || fail "P105_BRANCH_GATE=FAIL"
    git -C "$REPO" merge-base --is-ancestor "$EXPECTED_MIN_PARENT" HEAD || fail "P105_PARENT_GATE=FAIL"
    if [ -n "$(git -C "$REPO" status --porcelain)" ]; then
        fail "P105_WORKTREE_CLEAN=FAIL"
    else
        echo "P105_WORKTREE_CLEAN=PASS"
    fi
fi

[ -f "$REPO/$SOURCE_REL" ] || fail "P105_SOURCE_PRESENT=false"
[ -f "$REPO/$TRANSFORM_REL" ] || fail "P105_TRANSFORM_PRESENT=false"
if [ -f "$BASE_WRAPPER" ]; then
    BASE_SHA="$(sha256sum "$BASE_WRAPPER" | awk '{print $1}')"
    echo "P105_BASE_WRAPPER_SHA256=$BASE_SHA"
    [ "$BASE_SHA" = "$BASE_WRAPPER_SHA256" ] || fail "P105_BASE_WRAPPER_PIN=FAIL"
else
    fail "P105_BASE_WRAPPER_PRESENT=false"
fi
if [ -f "$SECRETS_FILE" ]; then
    echo "P105_SECRETS_PRESENT=true"
    echo "P105_SECRETS_CONTENT_EMITTED=false"
else
    fail "P105_SECRETS_PRESENT=false"
fi
pkg-config --exists nice glib-2.0 gio-2.0 gobject-2.0 || fail "P105_BUILD_DEPS=FAIL"

if pgrep -af "$WRAPPER_NAME|$CANDIDATE_HOLDER_NAME" >/dev/null 2>&1; then
    fail "P105_EXISTING_CANDIDATE_PROCESS=FAIL"
fi

if [ "$FAIL" -ne 0 ]; then
    echo "P105_PREFLIGHT=FAIL"
    exit 1
fi

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
RUN_ROOT="$ARTIFACT_ROOT/p105-live-$STAMP"
BUILD="$RUN_ROOT/build"
MEDIA_DIR="$RUN_ROOT/media"
LOG="$RUN_ROOT/live.log"
CANDIDATE_SOURCE="$BUILD/$CANDIDATE_HOLDER_NAME.c"
CANDIDATE_BINARY="$BUILD/$CANDIDATE_HOLDER_NAME"
CANDIDATE_WRAPPER="$BUILD/$WRAPPER_NAME"
STATUS_BEFORE="$RUN_ROOT/listener-status-before.json"
STOP_RESPONSE="$RUN_ROOT/listener-stop.json"
mkdir -p "$BUILD" "$MEDIA_DIR"
chmod 700 "$RUN_ROOT" "$BUILD" "$MEDIA_DIR"
: > "$LOG"
chmod 600 "$LOG"

python3 "$REPO/$TRANSFORM_REL" \
  --source "$REPO/$SOURCE_REL" \
  --output "$CANDIDATE_SOURCE" \
  > "$RUN_ROOT/transform.log" 2>&1
TRANSFORM_RC=$?
echo "P105_TRANSFORM_RC=$TRANSFORM_RC"
if [ "$TRANSFORM_RC" -ne 0 ]; then
    fail "P105_TRANSFORM=FAIL"
fi

if [ "$FAIL" -eq 0 ]; then
    for marker in \
      'P80_DEVICE_ACK_000A_OBSERVED=PASS' \
      'P80_POST_001A_ACK_GATE=PASS' \
      'P80_MEDIA_ACTIVE=true' \
      'P80_PREACTIVE_MEDIA_PROFILE_ACCEPT=PASS' \
      'P80_WRAPPER_PROFILE_MISMATCH_STATE=%s' \
      'LEN24_FALLBACK_DIAGNOSTIC_ONLY=true' \
      'P80_DOOR_SIGNAL_ENTRYPOINT=false'
    do
        grep -Fq "$marker" "$CANDIDATE_SOURCE" || fail "P105_SOURCE_MARKER_GATE=FAIL marker=$marker"
    done
    if grep -Fq 'signal(SIGUSR1, v4_door_signal_handler);' "$CANDIDATE_SOURCE"; then
        fail "P105_DOOR_SIGNAL_GATE=FAIL"
    else
        echo "P105_DOOR_SIGNAL_GATE=PASS"
    fi
fi

if [ "$FAIL" -eq 0 ]; then
    cc -O2 -g -Wall -Wextra \
      -o "$CANDIDATE_BINARY" \
      "$CANDIDATE_SOURCE" \
      $(pkg-config --cflags --libs nice glib-2.0 gio-2.0 gobject-2.0) \
      2> "$RUN_ROOT/compile.stderr"
    BUILD_RC=$?
    cat "$RUN_ROOT/compile.stderr"
    echo "P105_BUILD_RC=$BUILD_RC"
    [ "$BUILD_RC" -eq 0 ] || fail "P105_BUILD=FAIL"
fi

if [ "$FAIL" -eq 0 ]; then
    chmod 700 "$CANDIDATE_BINARY"
    strings -a "$CANDIDATE_BINARY" > "$RUN_ROOT/candidate.strings"
    for marker in \
      'P80_DEVICE_ACK_000A_OBSERVED=PASS' \
      'P80_POST_001A_ACK_GATE=PASS' \
      'P80_MEDIA_ACTIVE=true' \
      'P80_PREACTIVE_MEDIA_PROFILE_ACCEPT=PASS' \
      'P80_WRAPPER_PROFILE_MISMATCH_STATE=%s' \
      'LEN24_FALLBACK_DIAGNOSTIC_ONLY=true' \
      'P80_DOOR_SIGNAL_ENTRYPOINT=false'
    do
        grep -Fq "$marker" "$RUN_ROOT/candidate.strings" || fail "P105_BINARY_MARKER_GATE=FAIL marker=$marker"
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
    raise SystemExit("P105_WRAPPER_HOLDER_ANCHOR=FAIL")
text = text.replace(needle, f'"{holder}"', 1)
legacy_run_dir = "/run/comelit-p2p"
media_run_dir = "/run/comelit-media"
run_dir_count = text.count(legacy_run_dir)
if run_dir_count < 1:
    raise SystemExit("P105_WRAPPER_RUN_DIR_ANCHOR=FAIL")
text = text.replace(legacy_run_dir, media_run_dir)
out.write_text(text, encoding="utf-8")
os.chmod(out, 0o700)
print(f"P105_WRAPPER_RUN_DIR_REPLACEMENTS={run_dir_count}")
PY
    REWRITE_RC=$?
    echo "P105_WRAPPER_REWRITE_RC=$REWRITE_RC"
    if [ "$REWRITE_RC" -eq 0 ]; then
        bash -n "$CANDIDATE_WRAPPER" || fail "P105_WRAPPER_PARSE=FAIL"
    else
        fail "P105_WRAPPER_REWRITE=FAIL"
    fi
fi

if [ "$FAIL" -ne 0 ]; then
    echo "P105_PREFLIGHT=FAIL"
    exit 1
fi

echo "P105_PREFLIGHT=PASS"
echo "P105_RUN_ROOT=$RUN_ROOT"
echo "P105_LIVE_INVOCATION_LIMIT=1"
echo "P105_AUTOMATIC_RETRY=false"
echo "P105_DOOR_ACTION_ALLOWED=false"
echo "P105_HOME_ASSISTANT_CORE_RESTART_ALLOWED=false"

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

echo "=== EXACTLY ONE P105 LIVE INVOCATION ==="
LIVE_INVOCATIONS=1
echo "P105_EXACTLY_ONCE_GATE=PASS"
timeout --signal=TERM --kill-after=5s "${OUTER_TIMEOUT_SECONDS}s" "$CANDIDATE_WRAPPER" > "$LOG" 2>&1 &
WRAPPER_PID=$!
echo "P105_WRAPPER_STARTED=true"
echo "P105_WRAPPER_PID_REDACTED=true"

while [ "$OBSERVATION_SECONDS" -lt "$LIVE_WINDOW_SECONDS" ]; do
    if ! kill -0 "$WRAPPER_PID" 2>/dev/null; then
        break
    fi
    sleep 1
    OBSERVATION_SECONDS=$((OBSERVATION_SECONDS + 1))
done
echo "P105_OBSERVATION_SECONDS=$OBSERVATION_SECONDS"
stop_candidate_if_needed

wait "$WRAPPER_PID" || WRAPPER_RC=$?
if [ "$WRAPPER_RC" = NOT_REACHED ]; then
    WRAPPER_RC=0
fi
WRAPPER_PID=""
echo "P105_WRAPPER_RC=$WRAPPER_RC"

stop_sink_if_needed "$VIDEO_SINK_PID"
stop_sink_if_needed "$AUDIO_SINK_PID"
VIDEO_SINK_PID=""
AUDIO_SINK_PID=""
campaign_processes_remaining
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

[ "$LIVE_INVOCATIONS" -eq 1 ] || fail "P105_EXACTLY_ONCE_GATE=FAIL"
[ "$DOOR_RESULT_COUNT" -eq 0 ] || fail "P105_DOOR_RESULT_GATE=FAIL"

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
