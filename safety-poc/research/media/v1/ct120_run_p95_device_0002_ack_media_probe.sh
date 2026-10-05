#!/usr/bin/env bash
# CT120-only bounded P95 research runner.
#
# This removes the HACS/restart round-trip from protocol research. It builds the
# reviewed P95 transform in a detached origin/main worktree, pauses only the
# Comelit listener through its HA control webhook, performs exactly one Comelit
# P2P invocation, then restores and verifies the listener.
#
# The P80 generated helper normally uses /run/comelit-media under Home
# Assistant. For this CT120 harness only, the generated candidate is locally
# adapted back to /run/comelit-p2p so the already-pinned CT120 cloud wrapper can
# own offer/remote SDP exchange. This changes no on-wire protocol fields.
#
# If media becomes active and keeps running, the harness observes it for 12 s
# and requests the candidate's normal stop-file teardown. No automatic retry.

set -u -o pipefail
umask 077

REPO=/root/comelit-door-diag-repo
REMOTE_REF=refs/remotes/origin/main
CT120_IP=192.168.1.85
HA_WEBHOOK_URL=http://192.168.1.108:8123/api/webhook/comelit-ha-ring-test-control-v1
BASE_WRAPPER=/usr/local/sbin/comelit-p2p-cloud-probe
BASE_WRAPPER_SHA256=a564535dff0cf10b1fe4766171f2960c52fb581f1c816cf81d2992c5c84e79c9
SECRETS_FILE=/root/.config/comelit/secrets.env
SOURCE_REL=safety-poc/research/door/v1_5_7/comelit-v4-persistent-ctpp-door.c
TRANSFORM_REL=safety-poc/research/media/v1/entrance_p95_wait_device_0002_ack_before_rtpc_transform.py
TEST_REL=tests.test_p95_wait_device_0002_ack_before_rtpc

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
RUN_ROOT="/root/comelit-p95-device-0002-media-$STAMP"
WT="$RUN_ROOT/repo"
BUILD="$RUN_ROOT/build"
GENERATED="$BUILD/comelit-p95.c"
CANDIDATE="$BUILD/comelit-p95"
CANDIDATE_WRAPPER="$BUILD/comelit-p2p-cloud-probe-p95"
LIVE_LOG="$RUN_ROOT/live.log"
OFFLINE_LOG="$RUN_ROOT/offline.log"
SUMMARY_FILE="$RUN_ROOT/summary.txt"
STATUS_BEFORE="$RUN_ROOT/listener-before.json"
STATUS_STOP="$RUN_ROOT/listener-stop.json"
STATUS_AFTER="$RUN_ROOT/listener-after.json"

FAIL=0
LISTENER_STOPPED=0
LISTENER_RESTORED=0
LIVE_INVOCATIONS=0
REMOTE_MAIN=UNAVAILABLE
TRANSFORM_BLOB=UNAVAILABLE
WRAPPER_RC=NOT_RUN
FORCED_TEARDOWN=false
STOP_FILE_REQUESTED=false
MEDIA_ACTIVE=false
VIDEO_FORWARDING=false
AUDIO_FORWARDING=false

mkdir -p "$RUN_ROOT" "$BUILD"
chmod 700 "$RUN_ROOT" "$BUILD"

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
v = data.get(sys.argv[2], "__MISSING__")
if v is True:
    print("true")
elif v is False:
    print("false")
elif v is None:
    print("null")
else:
    print(v)
PY
}

post_control() {
    local action="$1" output="$2" max_time="$3" http_file="${output}.http"
    curl --silent --show-error --connect-timeout 5 --max-time "$max_time" \
      --header 'Content-Type: application/json' \
      --output "$output" --write-out '%{http_code}\n' \
      --data "{\"action\":\"$action\"}" "$HA_WEBHOOK_URL" > "$http_file"
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

restore_listener() {
    local start_file poll file
    [ "$LISTENER_STOPPED" -eq 1 ] || return 0

    start_file="$RUN_ROOT/listener-start.json"
    post_control start "$start_file" 40 || true
    for poll in 1 2 3 4 5 6 7 8; do
        file="$RUN_ROOT/listener-restore-$poll.json"
        post_control status "$file" 10 || true
        if status_ready "$file"; then
            cp "$file" "$STATUS_AFTER"
            LISTENER_STOPPED=0
            LISTENER_RESTORED=1
            return 0
        fi
        sleep 5
    done
    return 1
}

cleanup() {
    local rc=$?
    if [ "$LISTENER_STOPPED" -eq 1 ]; then
        restore_listener || true
    fi
    if [ -n "$WT" ] && [ -e "$WT/.git" ]; then
        git -C "$REPO" worktree remove --force "$WT" >/dev/null 2>&1 || true
    fi
    if [ "$LISTENER_STOPPED" -eq 1 ]; then
        exit 90
    fi
    exit "$rc"
}
trap cleanup EXIT
trap 'exit 130' INT TERM HUP

for command in git python3 cc pkg-config sha256sum strings curl ip grep setsid kill sleep cp; do
    command -v "$command" >/dev/null 2>&1 || FAIL=1
done
[ "${EUID}" -eq 0 ] || FAIL=1
[ -d "$REPO/.git" ] || FAIL=1
ip -4 addr show | grep -Fq "$CT120_IP/" || FAIL=1
[ -f "$BASE_WRAPPER" ] || FAIL=1
[ -f "$SECRETS_FILE" ] || FAIL=1
[ "$(sha256sum "$BASE_WRAPPER" | awk '{print $1}')" = "$BASE_WRAPPER_SHA256" ] || FAIL=1
pkg-config --exists nice glib-2.0 gio-2.0 gobject-2.0 || FAIL=1

if [ "$FAIL" -ne 0 ]; then
    echo '=== COMELIT P95 CT120 SUMMARY ==='
    echo 'P95_PREFLIGHT=FAIL'
    echo 'LIVE_INVOCATIONS=0'
    echo 'LISTENER_CHANGED=NO'
    echo 'P95_RESEARCH_RESULT=NOT_RUN'
    exit 1
fi

# GitHub network only; no Comelit side effect yet.
git -C "$REPO" fetch origin main >/dev/null 2>&1 || {
    echo '=== COMELIT P95 CT120 SUMMARY ==='
    echo 'P95_GIT_FETCH=FAIL'
    echo 'LIVE_INVOCATIONS=0'
    echo 'LISTENER_CHANGED=NO'
    echo 'P95_RESEARCH_RESULT=NOT_RUN'
    exit 1
}
REMOTE_MAIN="$(git -C "$REPO" rev-parse "$REMOTE_REF")"
TRANSFORM_BLOB="$(git -C "$REPO" rev-parse "$REMOTE_MAIN:$TRANSFORM_REL" 2>/dev/null || true)"
[ -n "$TRANSFORM_BLOB" ] || {
    echo '=== COMELIT P95 CT120 SUMMARY ==='
    echo "P95_REMOTE_MAIN=$REMOTE_MAIN"
    echo 'P95_TRANSFORM_ON_MAIN=false'
    echo 'LIVE_INVOCATIONS=0'
    echo 'LISTENER_CHANGED=NO'
    echo 'P95_RESEARCH_RESULT=NOT_RUN'
    exit 1
}

git -C "$REPO" worktree add --detach "$WT" "$REMOTE_MAIN" >/dev/null || exit 1

# Fast offline gate before any Comelit/HA side effect.
(
  cd "$WT/safety-poc" || exit 1
  PYTHONPATH="$PWD/src" PYTHONDONTWRITEBYTECODE=1 \
    python3 -m unittest -v "$TEST_REL"
  python3 scripts/static_safety_check.py
) > "$OFFLINE_LOG" 2>&1 || {
    echo '=== COMELIT P95 CT120 SUMMARY ==='
    echo "P95_REMOTE_MAIN=$REMOTE_MAIN"
    echo "P95_TRANSFORM_BLOB=$TRANSFORM_BLOB"
    echo 'P95_OFFLINE_GATE=FAIL'
    echo 'LIVE_INVOCATIONS=0'
    echo 'LISTENER_CHANGED=NO'
    echo "OFFLINE_LOG=$OFFLINE_LOG"
    echo 'P95_RESEARCH_RESULT=NOT_RUN'
    exit 1
}

PYTHONDONTWRITEBYTECODE=1 \
PYTHONPATH="$WT/safety-poc/research/media/v1" \
python3 "$WT/$TRANSFORM_REL" \
  --source "$WT/$SOURCE_REL" --output "$GENERATED" >> "$OFFLINE_LOG" 2>&1 || exit 1

# CT120 local harness adaptation only: reuse the pinned cloud wrapper run dir.
python3 - "$GENERATED" <<'PY'
from pathlib import Path
import sys
p = Path(sys.argv[1])
s = p.read_text(encoding="utf-8")
old = '#define RUN_DIR     "/run/comelit-media"'
new = '#define RUN_DIR     "/run/comelit-p2p"'
if s.count(old) != 1:
    raise SystemExit(f"P95_CT120_RUN_DIR_PATCH=FAIL count={s.count(old)}")
s = s.replace(old, new, 1)
s = s.replace('P80_RUN_DIR=/run/comelit-media', 'P80_RUN_DIR=/run/comelit-p2p')
p.write_text(s, encoding="utf-8")
print("P95_CT120_RUN_DIR_PATCH=PASS")
print("P95_CT120_PROTOCOL_FIELDS_CHANGED=false")
PY

for marker in \
  'P95_WAIT_DEVICE_0002=true' \
  'P95_DEVICE_0002_OBSERVED=PASS' \
  'P95_DEVICE_0002_ACK_SENT=PASS' \
  'P95_DEVICE_0002_GATE=PASS' \
  'P92_DEVICE_000A_GATE=PASS' \
  'P78_RTPC_SIGNALING_RESULT=PASS' \
  'P80_MEDIA_ACTIVE=true' \
  'P80_VIDEO_RTP_FORWARDING=PASS' \
  'P80_AUDIO_RTP_FORWARDING=PASS' \
  'P78_SECOND_CTPP_OPEN=false' \
  'ENTRANCE_SIGNALING_DOOR_ACTION_SENT=false'
do
    grep -Fq "$marker" "$GENERATED" || {
        echo "P95_SOURCE_MARKER_GATE=FAIL marker=$marker"
        exit 1
    }
done
! grep -Fq 'signal(SIGUSR1, v4_door_signal_handler);' "$GENERATED" || exit 1

cc -O2 -g -Wall -Wextra -o "$CANDIDATE" "$GENERATED" \
  $(pkg-config --cflags --libs nice glib-2.0 gio-2.0 gobject-2.0) \
  2>> "$OFFLINE_LOG" || exit 1
chmod 700 "$CANDIDATE"
strings -a "$CANDIDATE" > "$BUILD/candidate.strings"

python3 - "$BASE_WRAPPER" "$CANDIDATE_WRAPPER" "$CANDIDATE" <<'PY'
from pathlib import Path
import sys
src = Path(sys.argv[1]).read_text(encoding="utf-8")
needle = '"$BASE/bin/comelit_ice_offer_holder"'
if src.count(needle) != 1:
    raise SystemExit("P95_WRAPPER_HOLDER_PATCH=FAIL")
Path(sys.argv[2]).write_text(src.replace(needle, f'"{sys.argv[3]}"', 1), encoding="utf-8")
PY
chmod 700 "$CANDIDATE_WRAPPER"
bash -n "$CANDIDATE_WRAPPER" || exit 1

# Verify listener is healthy, then stop only the Comelit listener.
post_control status "$STATUS_BEFORE" 10 || exit 1
status_ready "$STATUS_BEFORE" || exit 1
post_control stop "$STATUS_STOP" 40 || exit 1
status_stopped "$STATUS_STOP" || exit 1
LISTENER_STOPPED=1

# One and only one Comelit invocation.
LIVE_INVOCATIONS=1
setsid "$CANDIDATE_WRAPPER" > "$LIVE_LOG" 2>&1 &
WRAPPER_PID=$!

# Wait at most 45 s for active or process exit.
for _ in $(seq 1 90); do
    if ! kill -0 "$WRAPPER_PID" 2>/dev/null; then
        break
    fi
    if grep -Fxq 'P80_MEDIA_ACTIVE=true' "$LIVE_LOG" 2>/dev/null; then
        MEDIA_ACTIVE=true
        break
    fi
    sleep 0.5
done

if [ "$MEDIA_ACTIVE" = true ]; then
    # P91 exits itself after 10 s if no forwarding. If forwarding starts it
    # remains alive; keep a 12 s bounded observation then request normal stop.
    for _ in $(seq 1 24); do
        grep -Fxq 'P80_VIDEO_RTP_FORWARDING=PASS' "$LIVE_LOG" 2>/dev/null && VIDEO_FORWARDING=true
        grep -Fxq 'P80_AUDIO_RTP_FORWARDING=PASS' "$LIVE_LOG" 2>/dev/null && AUDIO_FORWARDING=true
        kill -0 "$WRAPPER_PID" 2>/dev/null || break
        sleep 0.5
    done
    if kill -0 "$WRAPPER_PID" 2>/dev/null; then
        mkdir -p /run/comelit-p2p
        : > /run/comelit-p2p/stop
        chmod 600 /run/comelit-p2p/stop
        STOP_FILE_REQUESTED=true
    fi
fi

# Bounded teardown wait. Fall back to terminating the whole wrapper process
# group only if the normal stop-file path does not finish.
for _ in $(seq 1 20); do
    kill -0 "$WRAPPER_PID" 2>/dev/null || break
    sleep 0.5
done
if kill -0 "$WRAPPER_PID" 2>/dev/null; then
    FORCED_TEARDOWN=true
    kill -TERM -- "-$WRAPPER_PID" 2>/dev/null || true
    sleep 2
fi
if kill -0 "$WRAPPER_PID" 2>/dev/null; then
    kill -KILL -- "-$WRAPPER_PID" 2>/dev/null || true
fi
wait "$WRAPPER_PID"
WRAPPER_RC=$?

# Refresh marker state after process completion.
grep -Fxq 'P80_MEDIA_ACTIVE=true' "$LIVE_LOG" 2>/dev/null && MEDIA_ACTIVE=true
grep -Fxq 'P80_VIDEO_RTP_FORWARDING=PASS' "$LIVE_LOG" 2>/dev/null && VIDEO_FORWARDING=true
grep -Fxq 'P80_AUDIO_RTP_FORWARDING=PASS' "$LIVE_LOG" 2>/dev/null && AUDIO_FORWARDING=true

restore_listener || true

P95_WAIT_COUNT="$(grep -Fxc 'P95_WAIT_DEVICE_0002=true' "$LIVE_LOG" 2>/dev/null || true)"
P95_OBSERVED_COUNT="$(grep -Fxc 'P95_DEVICE_0002_OBSERVED=PASS' "$LIVE_LOG" 2>/dev/null || true)"
P95_ACK_COUNT="$(grep -Fxc 'P95_DEVICE_0002_ACK_SENT=PASS' "$LIVE_LOG" 2>/dev/null || true)"
P95_GATE_COUNT="$(grep -Fxc 'P95_DEVICE_0002_GATE=PASS' "$LIVE_LOG" 2>/dev/null || true)"
P95_DUPLICATES="$(grep -F 'P95_DEVICE_0002_DUPLICATE_COUNT=' "$LIVE_LOG" 2>/dev/null | tail -n1 | cut -d= -f2 || true)"
P92_000A_GATE_COUNT="$(grep -Fxc 'P92_DEVICE_000A_GATE=PASS' "$LIVE_LOG" 2>/dev/null || true)"
P78_SIGNALING_PASS_COUNT="$(grep -Fxc 'P78_RTPC_SIGNALING_RESULT=PASS' "$LIVE_LOG" 2>/dev/null || true)"
RX_TOTAL="$(grep -F 'P80_MEDIA_RX_TOTAL=' "$LIVE_LOG" 2>/dev/null | tail -n1 | cut -d= -f2 || true)"
WRAPPER_MATCH="$(grep -F 'P80_MEDIA_WRAPPER_LEN_MATCH=' "$LIVE_LOG" 2>/dev/null | tail -n1 | cut -d= -f2 || true)"
PT99="$(grep -F 'P80_MEDIA_PT99=' "$LIVE_LOG" 2>/dev/null | tail -n1 | cut -d= -f2 || true)"
PT8="$(grep -F 'P80_MEDIA_PT8=' "$LIVE_LOG" 2>/dev/null | tail -n1 | cut -d= -f2 || true)"

P95_RESEARCH_RESULT=PRE_RTPC_GATE_FAIL
if [ "$P95_GATE_COUNT" = 1 ] && [ "$P92_000A_GATE_COUNT" != 1 ]; then
    P95_RESEARCH_RESULT=DEVICE_0002_GATE_PASS_NEXT_GATE_NOT_REACHED
fi
if [ "$P95_GATE_COUNT" = 1 ] && [ "$P92_000A_GATE_COUNT" = 1 ] && [ "$P78_SIGNALING_PASS_COUNT" != 1 ]; then
    P95_RESEARCH_RESULT=DEVICE_0002_AND_000A_GATES_PASS_SIGNALING_INCOMPLETE
fi
if [ "$P78_SIGNALING_PASS_COUNT" = 1 ]; then
    P95_RESEARCH_RESULT=SIGNALING_PASS_NO_MEDIA_FORWARDING
fi
if [ "$VIDEO_FORWARDING" = true ] || [ "$AUDIO_FORWARDING" = true ]; then
    P95_RESEARCH_RESULT=MEDIA_FORWARDING_PASS
fi
if [ "$LISTENER_RESTORED" -ne 1 ]; then
    P95_RESEARCH_RESULT=LISTENER_RESTORE_FAIL
fi

{
    echo '=== COMELIT P95 CT120 SUMMARY ==='
    echo "P95_REMOTE_MAIN=$REMOTE_MAIN"
    echo "P95_TRANSFORM_BLOB=$TRANSFORM_BLOB"
    echo 'P95_OFFLINE_GATE=PASS'
    echo 'P95_CT120_RUN_DIR=/run/comelit-p2p'
    echo 'P95_CT120_PROTOCOL_FIELDS_CHANGED=false'
    echo "LIVE_INVOCATIONS=$LIVE_INVOCATIONS"
    echo 'AUTOMATIC_RETRY=false'
    echo 'DOOR_ACTION_SENT=false'
    echo 'SECOND_CTPP_OPEN=false'
    echo "P95_WAIT_DEVICE_0002_COUNT=$P95_WAIT_COUNT"
    echo "P95_DEVICE_0002_OBSERVED_COUNT=$P95_OBSERVED_COUNT"
    echo "P95_DEVICE_0002_ACK_SENT_COUNT=$P95_ACK_COUNT"
    echo "P95_DEVICE_0002_GATE_PASS_COUNT=$P95_GATE_COUNT"
    echo "P95_DEVICE_0002_DUPLICATE_COUNT=${P95_DUPLICATES:-0}"
    echo "P92_DEVICE_000A_GATE_PASS_COUNT=$P92_000A_GATE_COUNT"
    echo "P78_SIGNALING_PASS_COUNT=$P78_SIGNALING_PASS_COUNT"
    echo "P80_MEDIA_ACTIVE=$MEDIA_ACTIVE"
    echo "P80_VIDEO_FORWARDING=$VIDEO_FORWARDING"
    echo "P80_AUDIO_FORWARDING=$AUDIO_FORWARDING"
    echo "P80_MEDIA_RX_TOTAL=${RX_TOTAL:-NOT_EMITTED}"
    echo "P80_MEDIA_WRAPPER_LEN_MATCH=${WRAPPER_MATCH:-NOT_EMITTED}"
    echo "P80_MEDIA_PT99=${PT99:-NOT_EMITTED}"
    echo "P80_MEDIA_PT8=${PT8:-NOT_EMITTED}"
    echo "STOP_FILE_REQUESTED=$STOP_FILE_REQUESTED"
    echo "FORCED_TEARDOWN=$FORCED_TEARDOWN"
    echo "WRAPPER_RC=$WRAPPER_RC"
    echo "LISTENER_RESTORED=$([ "$LISTENER_RESTORED" -eq 1 ] && echo true || echo false)"
    echo "P95_RESEARCH_RESULT=$P95_RESEARCH_RESULT"
    echo "LIVE_LOG=$LIVE_LOG"
    echo "OFFLINE_LOG=$OFFLINE_LOG"
    echo "SUMMARY_FILE=$SUMMARY_FILE"
    echo '=== END COMELIT P95 CT120 SUMMARY ==='
} > "$SUMMARY_FILE"
cat "$SUMMARY_FILE"

# Research protocol failure is data, not a reason to skip safe cleanup. Return
# nonzero only for teardown/listener failure; otherwise let the summary carry
# the protocol outcome.
[ "$LISTENER_RESTORED" -eq 1 ] || exit 1
exit 0
