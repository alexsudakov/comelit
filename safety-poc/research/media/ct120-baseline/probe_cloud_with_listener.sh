#!/usr/bin/env bash
set -euo pipefail

HERE="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
HA_URL="http://192.168.1.108:8123/api/webhook/comelit-ha-ring-test-control-v1"
BIN="/root/comelit-media-poc-build/comelit-v4-media-poc"
PROBE="$HERE/../../ring/v4_2/comelit_cloud_probe.py"
TRANSFORM="$HERE/transform_media_offer.py"
RUN="/run/comelit-media-poc"
OUT="/root/comelit-media-poc-cloud-corrected"
PID=""

cleanup() {
    local rc=$?
    trap - EXIT INT TERM
    if [ -n "${PID:-}" ]; then
        touch "$RUN/stop" 2>/dev/null || true
        wait "$PID" 2>/dev/null || true
        PID=""
    fi
    exit "$rc"
}
trap cleanup EXIT INT TERM

call_status() {
    curl -fsS \
      -X POST \
      -H 'Content-Type: application/json' \
      -d '{"action":"status"}' \
      "$HA_URL"
}

echo "=== LISTENER PRECONDITION ==="
STATUS_JSON="$(call_status)"
echo "$STATUS_JSON" | jq '{supervisor_running,running,listener_ready,reconnect_count,last_error}'
echo "$STATUS_JSON" | jq -e \
    '.supervisor_running == true and .running == true and .listener_ready == true' \
    >/dev/null || {
        echo "LISTENER_PRECONDITION=FAIL"
        exit 20
    }
echo "LISTENER_PRECONDITION=PASS"

echo
echo "=== PREPARE CLOUD-ONLY PROBE ==="
rm -rf "$OUT"
mkdir -m 700 "$OUT"
rm -rf "$RUN"
mkdir -m 700 "$RUN"

"$BIN" >"$OUT/helper.log" 2>&1 &
PID=$!

for _ in $(seq 1 120); do
    [ -s "$RUN/offer.sdp" ] && break
    if ! kill -0 "$PID" 2>/dev/null; then
        break
    fi
    sleep 0.1
done

if [ ! -s "$RUN/offer.sdp" ]; then
    echo "RAW_OFFER_READY=FAIL"
    exit 21
fi
echo "RAW_OFFER_READY=PASS"

echo
echo "=== TRANSFORM OFFER LIKE PRODUCTION HA ==="
python3 "$TRANSFORM" \
    "$RUN/offer.sdp" \
    "$OUT/offer.comelit.sdp"

echo
echo "=== EXACTLY ONE CLOUD REQUEST ==="
RC=0
python3 "$PROBE" \
    "$OUT/offer.comelit.sdp" \
    "$OUT/remote-probe.sdp" \
    >"$OUT/cloud.log" 2>&1 || RC=$?

echo "CLOUD_RC=$RC"
grep -E \
'^(P2P_HTTP_STATUS|REMOTE_SDP_LINES|REMOTE_CANDIDATE_COUNT|REMOTE_CANDIDATE_TYPES|REMOTE_UFRAG_PRESENT|REMOTE_PWD_PRESENT|REMOTE_SDP_USABLE|P2P_CLOUD_NEGOTIATION)=' \
"$OUT/cloud.log" || true

echo
echo "=== STOP PROBE HELPER ==="
touch "$RUN/stop"
wait "$PID" 2>/dev/null || true
PID=""

if [ -e "$RUN/remote.sdp" ]; then
    echo "MEDIA_REMOTE_INJECTION=FAIL"
    exit 22
fi

echo "MEDIA_REMOTE_INJECTION=false"
echo "MEDIA_ACTION_SENT=false"

if [ "$RC" -ne 0 ]; then
    echo "CORRECTED_CLOUD_GATE=FAIL"
    exit 23
fi

grep -q '^REMOTE_SDP_USABLE=true$' "$OUT/cloud.log" || {
    echo "CORRECTED_CLOUD_GATE=FAIL"
    exit 24
}

echo "CORRECTED_CLOUD_GATE=PASS"
echo "CLOUD_ONLY_WITH_LISTENER=PASS"
