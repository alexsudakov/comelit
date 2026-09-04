#!/usr/bin/env bash
set -euo pipefail

HERE="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
REPO="$(CDPATH= cd -- "$HERE/../../../.." && pwd)"
BASE="$REPO/safety-poc/research/ring/v4_3/comelit_ice_offer_holder.v4-persistent.c"
TRANSFORM="$HERE/transform_media_offer.py"
CLOUD="$REPO/safety-poc/research/ring/v4_2/comelit_cloud_probe.py"
HA_URL="http://192.168.1.108:8123/api/webhook/comelit-ha-ring-test-control-v1"
BUILD=/root/comelit-v43-early-packet-build
RUN=/run/comelit-v43-early-packet
OUT=/root/comelit-v43-early-packet
SRC="$BUILD/comelit-v4-early-packet-probe.c"
BIN="$BUILD/comelit-v4-early-packet-probe"
HELPER_LOG="$OUT/helper.log"
CLOUD_LOG="$OUT/cloud.log"
OFFER="$RUN/offer.sdp"
COMELIT_OFFER="$OUT/offer.comelit.sdp"
REMOTE="$RUN/remote.sdp"
STOP="$RUN/stop"
PID=""
RESTORE_NEEDED=false

ha_status_json() {
    curl -fsS \
      -X POST \
      -H 'Content-Type: application/json' \
      -d '{"action":"status"}' \
      "$HA_URL"
}

ha_call() {
    local action="$1"
    local tmp code
    tmp="$(mktemp)"
    code="$(curl -sS -o "$tmp" -w '%{http_code}' \
      -X POST \
      -H 'Content-Type: application/json' \
      -d "{\"action\":\"$action\"}" \
      "$HA_URL" || true)"
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
echo '=== BUILD EARLY-PACKET SHAPE PROBE ==='
python3 - "$BASE" "$SRC" <<'PY'
from pathlib import Path
import sys

src = Path(sys.argv[1]).read_text(encoding='utf-8')

old_run = '#define RUN_DIR     "/run/comelit-p2p"'
new_run = '#define RUN_DIR     "/run/comelit-v43-early-packet"'
if src.count(old_run) != 1:
    raise SystemExit(f'RUN_DIR_PATCH=FAIL count={src.count(old_run)}')
src = src.replace(old_run, new_run, 1)
print('RUN_DIR_PATCH=PASS')

old_recv = '''    if (!pseudo_tcp) {\n        printf(\n            "PSEUDOTCP_RX_BEFORE_START=%u\\n",\n            len\n        );\n\n        fflush(stdout);\n        return;\n    }\n'''
new_recv = '''    if (!pseudo_tcp) {\n        printf(\n            "PSEUDOTCP_RX_BEFORE_START=%u\\n",\n            len\n        );\n\n        if (len >= 24) {\n            const guint8 *u = (const guint8 *)buf;\n            guint32 conv =\n                ((guint32)u[0] << 24) |\n                ((guint32)u[1] << 16) |\n                ((guint32)u[2] << 8) |\n                (guint32)u[3];\n            guint8 flags = u[13];\n\n            printf("EARLY_PACKET_HEADER_LEN=24\\n");\n            printf("EARLY_PACKET_TOTAL_LEN=%u\\n", len);\n            printf("EARLY_PACKET_DATA_LEN=%u\\n", len - 24);\n            printf("EARLY_PACKET_CONVERSATION=%u\\n", (unsigned)conv);\n            printf("EARLY_PACKET_FLAGS=%u\\n", (unsigned)flags);\n            printf(\n                "EARLY_PACKET_CONVERSATION_ZERO=%s\\n",\n                conv == 0 ? "true" : "false"\n            );\n            printf(\n                "EARLY_PACKET_FLAG_RST=%s\\n",\n                (flags & 0x04) != 0 ? "true" : "false"\n            );\n            printf(\n                "EARLY_PACKET_FLAG_CTL=%s\\n",\n                (flags & 0x02) != 0 ? "true" : "false"\n            );\n            printf("EARLY_PACKET_CAPTURED=true\\n");\n        } else {\n            printf("EARLY_PACKET_CAPTURED_SHORT=true\\n");\n        }\n\n        fflush(stdout);\n        return;\n    }\n'''
if src.count(old_recv) != 1:
    raise SystemExit(f'RECV_PATCH=FAIL count={src.count(old_recv)}')
src = src.replace(old_recv, new_recv, 1)
print('RECV_PATCH=PASS')

old_ready = '''        if (!start_pseudotcp()) {\n            fprintf(\n                stderr,\n                "PSEUDOTCP_START=FAIL\\n"\n            );\n\n            failed = TRUE;\n\n            if (loop)\n                g_main_loop_quit(loop);\n\n            return;\n        }\n'''
new_ready = '''        /* Diagnostic-only probe: never create or connect PseudoTCP. */\n        printf("PSEUDOTCP_START_SUPPRESSED=true\\n");\n'''
if src.count(old_ready) != 1:
    raise SystemExit(f'READY_PATCH=FAIL count={src.count(old_ready)}')
src = src.replace(old_ready, new_ready, 1)
print('READY_PATCH=PASS')

Path(sys.argv[2]).write_text(src, encoding='utf-8')
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
echo '=== START ICE-ONLY EARLY-PACKET SESSION ==='
timeout --signal=KILL 20s "$BIN" >"$HELPER_LOG" 2>&1 &
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
echo '=== EXACTLY ONE CLOUD REQUEST ==='
RC=0
python3 "$CLOUD" "$COMELIT_OFFER" "$REMOTE" >"$CLOUD_LOG" 2>&1 || RC=$?
echo "CLOUD_RC=$RC"
grep -E '^(P2P_HTTP_STATUS|REMOTE_SDP_LINES|REMOTE_CANDIDATE_COUNT|REMOTE_CANDIDATE_TYPES|REMOTE_UFRAG_PRESENT|REMOTE_PWD_PRESENT|REMOTE_SDP_USABLE|P2P_CLOUD_NEGOTIATION)=' "$CLOUD_LOG" || true
[ "$RC" -eq 0 ] || { echo 'CLOUD_GATE=FAIL'; exit 19; }
echo 'CLOUD_GATE=PASS'

echo
echo '=== WAIT FOR FIRST PRE-PSEUDOTCP APPLICATION PACKET ==='
CAPTURED=false
for _ in $(seq 1 160); do
    if grep -Fq 'EARLY_PACKET_CAPTURED=true' "$HELPER_LOG"; then
        CAPTURED=true
        break
    fi
    kill -0 "$PID" 2>/dev/null || break
    sleep 0.05
done

grep -E '^(ICE_COMPONENT_STATE|ICE_CONNECTED|ICE_READY|SELECTED_PAIR|PSEUDOTCP_RX_BEFORE_START|PSEUDOTCP_START_SUPPRESSED|EARLY_PACKET_)' "$HELPER_LOG" | tail -n 80 || true

if [ "$CAPTURED" = true ]; then
    echo 'EARLY_PACKET_SHAPE_GATE=PASS'
else
    echo 'EARLY_PACKET_SHAPE_GATE=FAIL'
fi

echo
echo '=== STOP ICE-ONLY SESSION ==='
: > "$STOP"
wait "$PID" 2>/dev/null || true
PID=""

echo 'PSEUDOTCP_CONNECT_SENT=false'
echo 'MEDIA_ACTION_SENT=false'
echo 'DOOR_ACTION_SENT=false'

if [ "$CAPTURED" != true ]; then
    exit 20
fi

echo 'EARLY_PACKET_SHAPE_PROBE=PASS'
exit 0
