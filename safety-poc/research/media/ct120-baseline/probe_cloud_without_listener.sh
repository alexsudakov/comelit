#!/usr/bin/env bash
set -euo pipefail

HA_URL="http://192.168.1.108:8123/api/webhook/comelit-ha-ring-test-control-v1"
BIN="/root/comelit-media-poc-build/comelit-v4-media-poc"
PROBE="/tmp/comelit-media-poc-v1/safety-poc/research/ring/v4_2/comelit_cloud_probe.py"
RUN="/run/comelit-media-poc"
OUT="/root/comelit-media-poc-concurrency-probe"
PID=""
RESTORE_NEEDED=false

for cmd in curl jq python3; do
    command -v "$cmd" >/dev/null 2>&1 || {
        echo "MISSING_COMMAND=$cmd"
        exit 10
    }
done

call_ha() {
    local action="$1"
    curl -fsS \
      -X POST \
      -H 'Content-Type: application/json' \
      -d "{\"action\":\"$action\"}" \
      "$HA_URL"
}

show_status() {
    jq '{
      ok,
      action,
      supervisor_running,
      running,
      listener_ready,
      reconnect_count,
      last_error
    }'
}

restore_listener() {
    local rc=$?
    trap - EXIT INT TERM

    if [ -n "${PID:-}" ]; then
        touch "$RUN/stop" 2>/dev/null || true
        wait "$PID" 2>/dev/null || true
        PID=""
    fi

    if [ "$RESTORE_NEEDED" = true ]; then
        echo
        echo "=== RESTORE COMELIT LISTENER ==="
        if START_JSON="$(call_ha start 2>/dev/null)"; then
            echo "$START_JSON" | show_status || true
            if echo "$START_JSON" | jq -e \
                '.supervisor_running == true and .running == true and .listener_ready == true' \
                >/dev/null 2>&1; then
                echo "COMELIT_LISTENER_RESTORE_GATE=PASS"
            else
                echo "COMELIT_LISTENER_RESTORE_GATE=FAIL"
            fi
        else
            echo "COMELIT_LISTENER_RESTORE_GATE=FAIL"
        fi
    fi

    exit "$rc"
}
trap restore_listener EXIT INT TERM

echo "=== STATUS BEFORE ==="
STATUS_JSON="$(call_ha status)"
echo "$STATUS_JSON" | show_status

echo "$STATUS_JSON" | jq -e \
    '.supervisor_running == true and .running == true and .listener_ready == true' \
    >/dev/null || {
        echo "COMELIT_LISTENER_PRECONDITION=FAIL"
        exit 20
    }
echo "COMELIT_LISTENER_PRECONDITION=PASS"

echo
echo "=== STOP ONLY COMELIT LISTENER ==="
STOP_JSON="$(call_ha stop)"
RESTORE_NEEDED=true
echo "$STOP_JSON" | show_status

echo "$STOP_JSON" | jq -e \
    '.supervisor_running == false and .running == false and .listener_ready == false' \
    >/dev/null || {
        echo "COMELIT_LISTENER_STOP_GATE=FAIL"
        exit 21
    }
echo "COMELIT_LISTENER_STOP_GATE=PASS"

sleep 2

echo
echo "=== PREPARE CLOUD-ONLY PROBE ==="
rm -rf "$OUT"
mkdir -m 700 "$OUT"
rm -f "$RUN/offer.sdp" "$RUN/remote.sdp" "$RUN/stop"

"$BIN" >"$OUT/helper.log" 2>&1 &
PID=$!

for _ in $(seq 1 100); do
    [ -s "$RUN/offer.sdp" ] && break
    sleep 0.1
done

if [ ! -s "$RUN/offer.sdp" ]; then
    echo "OFFER_READY=FAIL"
    exit 22
fi
echo "OFFER_READY=PASS"

echo
echo "=== EXACTLY ONE CLOUD REQUEST ==="
RC=0
python3 "$PROBE" \
    "$RUN/offer.sdp" \
    "$OUT/remote-probe.sdp" \
    >"$OUT/cloud.log" 2>&1 || RC=$?

echo "CLOUD_RC=$RC"
grep -E \
'^(P2P_HTTP_STATUS|REMOTE_SDP_LINES|REMOTE_CANDIDATE_COUNT|REMOTE_CANDIDATE_TYPES|REMOTE_UFRAG_PRESENT|REMOTE_PWD_PRESENT|REMOTE_SDP_USABLE|P2P_CLOUD_NEGOTIATION)=' \
"$OUT/cloud.log" || true

echo
echo "=== SANITIZED SDP SHAPE ==="
python3 - <<'PY'
from pathlib import Path
p = Path('/root/comelit-media-poc-concurrency-probe/remote-probe.sdp')
if not p.exists():
    print('REMOTE_FILE=ABSENT')
    raise SystemExit
lines = [
    x.strip()
    for x in p.read_text(errors='replace').replace('\r\n', '\n').split('\n')
    if x.strip()
]
print('REMOTE_FILE=PRESENT')
print('LINES=%d' % len(lines))
print('LINE_KINDS=%s' % ','.join(x[:2] for x in lines))
print('MEDIA_LINES=%d' % sum(x.startswith('m=') for x in lines))
print('ATTRIBUTE_LINES=%d' % sum(x.startswith('a=') for x in lines))
print('CANDIDATES=%d' % sum(x.startswith('a=candidate:') for x in lines))
PY

echo
echo "=== STOP PROBE HELPER ==="
touch "$RUN/stop"
wait "$PID" 2>/dev/null || true
PID=""

echo "MEDIA_ACTION_SENT=false"
echo "CLOUD_ONLY_TEST_DONE=true"

echo
echo "=== START COMELIT LISTENER ==="
START_JSON="$(call_ha start)"
echo "$START_JSON" | show_status

echo "$START_JSON" | jq -e \
    '.supervisor_running == true and .running == true and .listener_ready == true' \
    >/dev/null || {
        echo "COMELIT_LISTENER_RESTORE_GATE=FAIL"
        exit 23
    }

echo "COMELIT_LISTENER_RESTORE_GATE=PASS"
RESTORE_NEEDED=false
trap - EXIT INT TERM
