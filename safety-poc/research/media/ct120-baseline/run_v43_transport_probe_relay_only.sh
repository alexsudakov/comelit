#!/usr/bin/env bash
set -euo pipefail

HERE="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
REPO="$(CDPATH= cd -- "$HERE/../../../.." && pwd)"
BASE="$REPO/safety-poc/research/ring/v4_3/comelit_ice_offer_holder.v4-persistent.c"
TRANSFORM="$HERE/transform_media_offer.py"
CLOUD="$REPO/safety-poc/research/ring/v4_2/comelit_cloud_probe.py"
HA_URL="http://192.168.1.108:8123/api/webhook/comelit-ha-ring-test-control-v1"
BUILD=/root/comelit-v43-relay-only-build
RUN=/run/comelit-v43-relay-only
OUT=/root/comelit-v43-relay-only
SRC="$BUILD/comelit-v4-transport-probe.c"
BIN="$BUILD/comelit-v4-transport-probe"
HELPER_LOG="$OUT/helper.log"
CLOUD_LOG="$OUT/cloud.log"
OFFER="$RUN/offer.sdp"
COMELIT_OFFER="$OUT/offer.comelit.sdp"
REMOTE_FULL="$OUT/remote.full.sdp"
REMOTE="$RUN/remote.sdp"
STOP="$RUN/stop"
PID=""
RESTORE_NEEDED=false

ha_status_json() {
    curl -fsS -X POST -H 'Content-Type: application/json' \
      -d '{"action":"status"}' "$HA_URL"
}

ha_call() {
    local action="$1"
    local tmp code
    tmp="$(mktemp)"
    code="$(curl -sS -o "$tmp" -w '%{http_code}' \
      -X POST -H 'Content-Type: application/json' \
      -d "{\"action\":\"$action\"}" "$HA_URL" || true)"
    cat "$tmp"
    rm -f "$tmp"
    printf '\nHTTP_STATUS=%s\n' "$code" >&2
}

restore_listener() {
    local rc=$?
    trap - EXIT INT TERM

    if [ -n "${PID:-}" ] && kill -0 "$PID" 2>/dev/null; then
        mkdir -p "$RUN"
        : > "$STOP" 2>/dev/null || true
        for _ in $(seq 1 30); do
            kill -0 "$PID" 2>/dev/null || break
            sleep 0.1
        done
        kill -KILL "$PID" 2>/dev/null || true
        wait "$PID" 2>/dev/null || true
        PID=""
    fi

    if [ "$RESTORE_NEEDED" = true ]; then
        echo
        echo '=== RESTORE HA COMELIT LISTENER ==='
        START_BODY="$(ha_call start 2>"$OUT/start-http.log" || true)"
        printf '%s\n' "$START_BODY" | jq '{ok,action,supervisor_running,running,listener_ready,reconnect_count,last_error}' 2>/dev/null || true
        cat "$OUT/start-http.log" || true

        RESTORED=false
        for _ in $(seq 1 60); do
            STATUS_JSON="$(ha_status_json 2>/dev/null || true)"
            if printf '%s\n' "$STATUS_JSON" | jq -e \
                '.supervisor_running == true and .running == true and .listener_ready == true' \
                >/dev/null 2>&1; then
                printf '%s\n' "$STATUS_JSON" | jq '{supervisor_running,running,listener_ready,reconnect_count,last_error}'
                RESTORED=true
                break
            fi
            sleep 1
        done

        if [ "$RESTORED" = true ]; then
            echo 'COMELIT_LISTENER_RESTORE_GATE=PASS'
        else
            echo 'COMELIT_LISTENER_RESTORE_GATE=FAIL'
            rc=90
        fi
    fi

    exit "$rc"
}
trap restore_listener EXIT INT TERM

for cmd in curl jq python3 gcc pkg-config timeout strings grep; do
    command -v "$cmd" >/dev/null 2>&1 || {
        echo "MISSING_COMMAND=$cmd"
        exit 10
    }
done

rm -rf "$BUILD" "$RUN" "$OUT"
mkdir -m 700 "$BUILD" "$RUN" "$OUT"

[[ -f "$BASE" ]] || { echo 'BASE_SOURCE=FAIL'; exit 11; }
[[ -f "$TRANSFORM" ]] || { echo 'TRANSFORM=FAIL'; exit 12; }
[[ -f "$CLOUD" ]] || { echo 'CLOUD_PROBE=FAIL'; exit 13; }

echo '=== HA LISTENER PRECONDITION ==='
STATUS_JSON="$(ha_status_json)"
echo "$STATUS_JSON" | jq '{supervisor_running,running,listener_ready,reconnect_count,last_error}'
echo "$STATUS_JSON" | jq -e '.supervisor_running == true and .running == true and .listener_ready == true' >/dev/null || {
    echo 'LISTENER_PRECONDITION=FAIL'
    exit 14
}
echo 'LISTENER_PRECONDITION=PASS'

echo
echo '=== STOP ONLY HA COMELIT LISTENER ==='
STOP_BODY="$(ha_call stop 2>"$OUT/stop-http.log")"
RESTORE_NEEDED=true
printf '%s\n' "$STOP_BODY" | jq '{ok,action,supervisor_running,running,listener_ready,reconnect_count,last_error}'
cat "$OUT/stop-http.log" || true
printf '%s\n' "$STOP_BODY" | jq -e \
    '.supervisor_running == false and .running == false and .listener_ready == false' \
    >/dev/null || {
        echo 'LISTENER_STOP_GATE=FAIL'
        exit 15
    }
echo 'LISTENER_STOP_GATE=PASS'
sleep 2

echo
echo '=== BUILD EXACT V4_3 WITH ISOLATED RUN DIR ==='
python3 - "$BASE" "$SRC" <<'PY'
from pathlib import Path
import sys
src = Path(sys.argv[1]).read_text(encoding='utf-8')
old = '#define RUN_DIR     "/run/comelit-p2p"'
new = '#define RUN_DIR     "/run/comelit-v43-relay-only"'
if src.count(old) != 1:
    raise SystemExit(f'RUN_DIR_PATCH=FAIL count={src.count(old)}')
src = src.replace(old, new, 1)
Path(sys.argv[2]).write_text(src, encoding='utf-8')
print('RUN_DIR_PATCH=PASS')
PY

for token in \
  'v4_door_queue_open' \
  'v4_door_queue_write' \
  'v4_door_signal_handler' \
  'V4_DOOR_COMMAND_ACCEPTED' \
  'SIGUSR1'
do
    if grep -Fq "$token" "$SRC"; then
        echo "SOURCE_DOOR_ACTION=FAIL token=$token"
        exit 16
    fi
done
echo 'SOURCE_DOOR_ACTION=ABSENT'

CFLAGS="$(pkg-config --cflags nice glib-2.0 gobject-2.0)"
LIBS="$(pkg-config --libs nice glib-2.0 gobject-2.0)"
gcc -std=c11 -O2 -g -Wall -Wextra $CFLAGS "$SRC" -o "$BIN" $LIBS

for token in 'V4_DOOR_COMMAND_ACCEPTED' 'V4_DOOR_RESULT=' 'V4_DOOR_WRITE_' 'V4_DOOR_CTPP_OPEN_SENT'; do
    if strings -a "$BIN" | grep -Fq "$token"; then
        echo "BINARY_DOOR_ACTION=FAIL token=$token"
        exit 17
    fi
done
echo 'BINARY_DOOR_ACTION=ABSENT'

echo
echo '=== START ISOLATED PASSIVE TRANSPORT SESSION ==='
timeout --signal=KILL 25s "$BIN" >"$HELPER_LOG" 2>&1 &
PID=$!

for _ in $(seq 1 120); do
    [ -s "$OFFER" ] && break
    kill -0 "$PID" 2>/dev/null || break
    sleep 0.1
done
[ -s "$OFFER" ] || {
    echo 'OFFER_READY=FAIL'
    tail -n 100 "$HELPER_LOG" || true
    exit 18
}
echo 'OFFER_READY=PASS'

echo
echo '=== TRANSFORM OFFER LIKE PRODUCTION HA ==='
python3 "$TRANSFORM" "$OFFER" "$COMELIT_OFFER"

echo
echo '=== EXACTLY ONE CLOUD REQUEST TO RAW REMOTE SDP ==='
RC=0
python3 "$CLOUD" "$COMELIT_OFFER" "$REMOTE_FULL" >"$CLOUD_LOG" 2>&1 || RC=$?
echo "CLOUD_RC=$RC"
grep -E '^(P2P_HTTP_STATUS|REMOTE_SDP_LINES|REMOTE_CANDIDATE_COUNT|REMOTE_CANDIDATE_TYPES|REMOTE_UFRAG_PRESENT|REMOTE_PWD_PRESENT|REMOTE_SDP_USABLE|P2P_CLOUD_NEGOTIATION)=' "$CLOUD_LOG" || true
[ "$RC" -eq 0 ] || { echo 'CLOUD_GATE=FAIL'; exit 19; }
echo 'CLOUD_GATE=PASS'

echo
echo '=== FILTER REMOTE SDP TO RELAY CANDIDATE ONLY ==='
python3 - "$REMOTE_FULL" "$REMOTE" <<'PY'
from pathlib import Path
import os, sys
src = Path(sys.argv[1])
dst = Path(sys.argv[2])
text = src.read_text(encoding='utf-8')
lines = [line.strip() for line in text.replace('\r\n','\n').replace('\r','\n').split('\n') if line.strip()]
cands = [line for line in lines if line.startswith('a=candidate:')]
relay = []
for line in cands:
    parts = line.split()
    try:
        i = parts.index('typ')
    except ValueError:
        continue
    if i + 1 < len(parts) and parts[i + 1].lower() == 'relay':
        relay.append(line)
if len(relay) != 1:
    raise SystemExit(f'RELAY_FILTER=FAIL relay_count={len(relay)} total_candidates={len(cands)}')
out = [line for line in lines if not line.startswith('a=candidate:')]
# Keep SDP ordering stable by inserting the single relay candidate immediately
# before the final ICE role/credential attributes.
insert_at = next((i for i, line in enumerate(out) if line.startswith('a=ice-role:')), len(out))
out.insert(insert_at, relay[0])
data = ('\r\n'.join(out) + '\r\n').encode('ascii')
tmp = dst.with_suffix('.tmp')
old = os.umask(0o077)
try:
    tmp.write_bytes(data)
    os.chmod(tmp, 0o600)
    os.replace(tmp, dst)
finally:
    os.umask(old)
    try:
        tmp.unlink()
    except FileNotFoundError:
        pass
parts = relay[0].split()
typ_i = parts.index('typ')
print('RELAY_FILTER=PASS')
print(f'REMOTE_CANDIDATES_ORIGINAL={len(cands)}')
print('REMOTE_CANDIDATES_FILTERED=1')
print(f'REMOTE_RELAY_ADDRESS={parts[4]}')
print(f'REMOTE_RELAY_PORT={parts[5]}')
print(f'REMOTE_RELAY_TYPE={parts[typ_i+1]}')
PY

echo
echo '=== WAIT FOR PASSIVE LISTENER READY ==='
TRANSPORT_READY=false
for _ in $(seq 1 180); do
    if grep -Fq 'V4_RING_LISTENER_READY=true' "$HELPER_LOG"; then
        TRANSPORT_READY=true
        break
    fi
    kill -0 "$PID" 2>/dev/null || break
    sleep 0.1
done

grep -E '^(REMOTE_CANDIDATES_|ICE_COMPONENT_STATE|ICE_CONNECTED|ICE_READY|SELECTED_PAIR|SELECTED_LOCAL_TYPE|SELECTED_REMOTE_TYPE|PSEUDOTCP_RX_BEFORE_START|PSEUDOTCP_CONVERSATION|PSEUDOTCP_MTU|PSEUDOTCP_CONNECT_START|PSEUDOTCP_OPEN|PSEUDOTCP_CLOSED|UAUT_|UCFG_|V4_CTPP_|V4_CSPB_|V4_REGISTER|V4_RING_LISTENER_READY)' "$HELPER_LOG" | tail -n 180 || true

if [ "$TRANSPORT_READY" = true ]; then
    echo 'RELAY_ONLY_TRANSPORT_READY=PASS'
else
    echo 'RELAY_ONLY_TRANSPORT_READY=FAIL'
fi

echo
echo '=== STOP ISOLATED PASSIVE SESSION ==='
: > "$STOP"
wait "$PID" 2>/dev/null || true
PID=""

echo 'MEDIA_ACTION_SENT=false'
echo 'DOOR_ACTION_SENT=false'

if [ "$TRANSPORT_READY" != true ]; then
    exit 20
fi

echo 'RELAY_ONLY_TRANSPORT_PROBE=PASS'
exit 0
