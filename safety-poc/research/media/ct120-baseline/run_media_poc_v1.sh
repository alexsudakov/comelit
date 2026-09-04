#!/usr/bin/env bash
set -euo pipefail

HERE="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
BIN=/root/comelit-media-poc-build/comelit-v4-media-poc
CLOUD="$HERE/../../ring/v4_2/comelit_cloud_probe.py"
RUN_DIR=/run/comelit-media-poc
OUT_DIR=/root/comelit-media-poc-output
REPORT_DIR=/root/comelit-media-poc-run
HELPER_LOG="$REPORT_DIR/helper.log"
CLOUD_LOG="$REPORT_DIR/cloud.log"
OFFER="$RUN_DIR/offer.sdp"
REMOTE="$RUN_DIR/remote.sdp"
STOP_FILE="$RUN_DIR/stop"
H264="$OUT_DIR/live.h264"
MP4="$OUT_DIR/live.mp4"
JPG="$OUT_DIR/first-frame.jpg"

WATCH_PID=""

finish_running_helper() {
    if [[ -n "${WATCH_PID:-}" ]] && kill -0 "$WATCH_PID" 2>/dev/null; then
        mkdir -p "$RUN_DIR"
        chmod 700 "$RUN_DIR" || true
        : > "$STOP_FILE"
        chmod 600 "$STOP_FILE" || true

        # Give the helper a bounded chance to perform protocol teardown.
        for _ in $(seq 1 40); do
            if ! kill -0 "$WATCH_PID" 2>/dev/null; then
                break
            fi
            sleep 0.1
        done

        if kill -0 "$WATCH_PID" 2>/dev/null; then
            kill -KILL "$WATCH_PID" 2>/dev/null || true
        fi
    fi
}

trap finish_running_helper EXIT INT TERM

printf '%s\n' '=== LIVE POC PREFLIGHT ==='

[[ -x "$BIN" ]] || { echo 'PREFLIGHT_BINARY=FAIL'; exit 20; }
[[ -f "$CLOUD" ]] || { echo 'PREFLIGHT_CLOUD_PROBE=FAIL'; exit 21; }
command -v timeout >/dev/null || { echo 'PREFLIGHT_TIMEOUT=FAIL'; exit 22; }
command -v ffmpeg >/dev/null || { echo 'PREFLIGHT_FFMPEG=FAIL'; exit 23; }
command -v ffprobe >/dev/null || { echo 'PREFLIGHT_FFPROBE=FAIL'; exit 24; }

if pgrep -f '^/root/comelit-media-poc-build/comelit-v4-media-poc$' >/dev/null 2>&1; then
    echo 'PREFLIGHT_EXISTING_MEDIA_HELPER=FAIL'
    exit 25
fi

for token in \
  'V4_DOOR_COMMAND_ACCEPTED' \
  'V4_DOOR_RESULT=' \
  'V4_DOOR_WRITE_' \
  'V4_DOOR_CTPP_OPEN_SENT'
do
    if strings -a "$BIN" | grep -Fq "$token"; then
        echo "PREFLIGHT_BINARY_FORBIDDEN=$token"
        exit 26
    fi
done

strings -a "$BIN" | grep -Fq 'V4_DOOR_ACTION_SURFACE_PRESENT=false'
strings -a "$BIN" | grep -Fq 'V4_MEDIA_ACTION_SURFACE_PRESENT=true'
strings -a "$BIN" | grep -Fq 'V4_MEDIA_TARGET=entrance'

mkdir -p "$REPORT_DIR" "$OUT_DIR"
chmod 700 "$REPORT_DIR" "$OUT_DIR"
rm -f "$HELPER_LOG" "$CLOUD_LOG" "$H264" "$MP4" "$JPG"
rm -rf "$RUN_DIR"
mkdir -p "$RUN_DIR"
chmod 700 "$RUN_DIR"

printf 'BINARY_SHA256='
sha256sum "$BIN" | awk '{print $1}'
echo 'PREFLIGHT_DOOR_ACTION=ABSENT'
echo 'PREFLIGHT_MEDIA_TARGET=ENTRANCE'
echo 'PREFLIGHT_AUTO_RETRY=false'

echo
echo '=== START ONE-SHOT HELPER ==='

# Independent process-level boundary. The helper has its own graceful
# watchdog at 28 s; this 30 s watchdog is the final fail-closed boundary.
timeout --signal=KILL 30s "$BIN" >"$HELPER_LOG" 2>&1 &
WATCH_PID=$!
echo "WATCH_PID=$WATCH_PID"

# Wait only for the local ICE offer. No cloud/media retry is performed.
OFFER_READY=false
for _ in $(seq 1 120); do
    if [[ -s "$OFFER" ]]; then
        OFFER_READY=true
        break
    fi

    if ! kill -0 "$WATCH_PID" 2>/dev/null; then
        break
    fi

    sleep 0.1
done

if [[ "$OFFER_READY" != true ]]; then
    echo 'OFFER_READY=FAIL'
    : > "$STOP_FILE"
    wait "$WATCH_PID" 2>/dev/null || true
    WATCH_PID=""
    grep -E '^(ICE_|PSEUDOTCP_|V4_MEDIA_|V4_CTPP_|P12_)' "$HELPER_LOG" | tail -n 30 || true
    exit 30
fi

echo 'OFFER_READY=PASS'

echo
echo '=== SINGLE CLOUD NEGOTIATION ==='

CLOUD_RC=0
python3 "$CLOUD" "$OFFER" "$REMOTE" >"$CLOUD_LOG" 2>&1 || CLOUD_RC=$?

grep -E '^(CREDENTIAL_GATE|P2P_HTTP_STATUS|REMOTE_SDP_PRESENT|REMOTE_SDP_USABLE|P2P_CLOUD_NEGOTIATION)=' "$CLOUD_LOG" || true

echo "CLOUD_RC=$CLOUD_RC"

if [[ "$CLOUD_RC" -ne 0 || ! -s "$REMOTE" ]]; then
    echo 'CLOUD_NEGOTIATION_GATE=FAIL'
    : > "$STOP_FILE"
    wait "$WATCH_PID" 2>/dev/null || true
    WATCH_PID=""
    grep -E '^(V4_MEDIA_|ICE_|PSEUDOTCP_|P12_)' "$HELPER_LOG" | tail -n 30 || true
    exit 31
fi

echo 'CLOUD_NEGOTIATION_GATE=PASS'

echo
echo '=== WAIT FOR MEDIA + TEARDOWN ==='

HELPER_RC=0
wait "$WATCH_PID" || HELPER_RC=$?
WATCH_PID=""
echo "HELPER_RC=$HELPER_RC"

# Compact protocol result only; full diagnostics remain in helper.log.
grep -E '^(V4_DOOR_ACTION_SURFACE_PRESENT|V4_MEDIA_(TARGET|SETUP_STARTED|CALL_INIT_SENT|ACTION_0008_SENT|ACTION_000A_START_SENT|ACTION_001A_START_SENT|ACTIVE|RTP_PT|TEARDOWN_STARTED|TEARDOWN_RESULT|H264_BYTES|RTP_PACKETS|RTP_SEQUENCE_GAPS|ICE_CLOSED|EXIT))=' "$HELPER_LOG" | tail -n 40 || true

if [[ "$HELPER_RC" -ne 0 ]]; then
    echo 'HELPER_GATE=FAIL'
    exit 32
fi

for required in \
  'V4_DOOR_ACTION_SURFACE_PRESENT=false' \
  'V4_MEDIA_ACTIVE=true' \
  'V4_MEDIA_TEARDOWN_STARTED=true' \
  'V4_MEDIA_TEARDOWN_RESULT=ACKED' \
  'V4_MEDIA_ICE_CLOSED=true' \
  'V4_MEDIA_EXIT=PASS'
do
    grep -Fq "$required" "$HELPER_LOG" || {
        echo "HELPER_REQUIRED_MISSING=$required"
        exit 33
    }
done

[[ -s "$H264" ]] || { echo 'H264_GATE=FAIL'; exit 34; }
echo 'HELPER_GATE=PASS'

echo
echo '=== MEDIA ARTIFACT VALIDATION ==='

# Raw H.264 has no container timestamps; use the capture-proven 25 fps
# solely for the validation MP4 created after the upstream session is gone.
ffmpeg -hide_banner -loglevel error -y \
    -f h264 -r 25 -i "$H264" \
    -c:v copy "$MP4"

ffmpeg -hide_banner -loglevel error -y \
    -f h264 -i "$H264" \
    -frames:v 1 "$JPG"

ffprobe -v error \
    -select_streams v:0 \
    -show_entries stream=codec_name,profile,width,height,pix_fmt,avg_frame_rate \
    -show_entries format=duration,size \
    -of default=noprint_wrappers=1 \
    "$MP4"

[[ -s "$MP4" ]] || { echo 'MP4_GATE=FAIL'; exit 35; }
[[ -s "$JPG" ]] || { echo 'JPG_GATE=FAIL'; exit 36; }

printf 'H264_BYTES='; stat -c %s "$H264"
printf 'MP4_BYTES='; stat -c %s "$MP4"
printf 'JPG_BYTES='; stat -c %s "$JPG"
echo 'MEDIA_ARTIFACT_GATE=PASS'

echo
echo '=== RESULT ==='
echo "HELPER_LOG=$HELPER_LOG"
echo "CLOUD_LOG=$CLOUD_LOG"
echo "H264=$H264"
echo "MP4=$MP4"
echo "JPG=$JPG"
echo 'MEDIA_POC_LIVE_V1=PASS'
