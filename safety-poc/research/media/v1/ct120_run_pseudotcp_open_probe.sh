#!/usr/bin/env bash
# CT120 research-only single-run PseudoTCP OPEN probe.
#
# Preconditions:
# - the caller has already refreshed refs/remotes/origin/main using the
#   repository's token-only credential workflow;
# - this script is executed as root on CT120;
# - the historical cloud-probe wrapper is still byte-identical to the pinned
#   baseline. The wrapper is copied and rebound to a research candidate;
#   the original is never modified.
#
# This script performs exactly one network-capable wrapper invocation and never
# retries it. It must not touch Home Assistant, Door, or self-activation.

set -u -o pipefail
umask 077

REPO=/root/comelit-door-diag-repo
REMOTE_REF=refs/remotes/origin/main
REQUIRED_ANCESTOR=33649c16b6a6bf646d7735b4d3796f5fc1bd222d
BASE_WRAPPER=/usr/local/sbin/comelit-p2p-cloud-probe
BASE_WRAPPER_SHA256=a564535dff0cf10b1fe4766171f2960c52fb581f1c816cf81d2992c5c84e79c9
SECRETS_FILE=/root/.config/comelit/secrets.env
SOURCE_REL=safety-poc/research/door/v1_5_3/comelit-v4-persistent-ctpp-door.c
TRANSFORM_REL=safety-poc/research/media/v1/pseudotcp_open_probe_transform.py

FAIL=0

fail() {
    echo "$1"
    FAIL=1
}

if [ "${EUID}" -ne 0 ]; then
    echo "CT120_OPEN_PROBE_REQUIRES_ROOT=true"
    exit 1
fi

for command in git python3 cc pkg-config sha256sum timeout strings grep tee; do
    if ! command -v "$command" >/dev/null 2>&1; then
        fail "CT120_OPEN_PROBE_MISSING_COMMAND=$command"
    fi
done

if [ ! -d "$REPO/.git" ]; then
    fail "CT120_OPEN_PROBE_REPO_PRESENT=false"
fi

if ! git -C "$REPO" rev-parse --verify -q "$REMOTE_REF" >/dev/null 2>&1; then
    fail "CT120_OPEN_PROBE_REMOTE_MAIN_PRESENT=false"
fi

REMOTE_MAIN=""
if [ "$FAIL" -eq 0 ]; then
    REMOTE_MAIN="$(git -C "$REPO" rev-parse "$REMOTE_REF")"
    echo "CT120_OPEN_PROBE_REMOTE_MAIN=$REMOTE_MAIN"

    if git -C "$REPO" merge-base --is-ancestor "$REQUIRED_ANCESTOR" "$REMOTE_MAIN"; then
        echo "CT120_OPEN_PROBE_RESEARCH_ANCESTOR=PASS"
    else
        fail "CT120_OPEN_PROBE_RESEARCH_ANCESTOR=FAIL"
    fi
fi

if [ ! -f "$BASE_WRAPPER" ]; then
    fail "CT120_OPEN_PROBE_BASE_WRAPPER_PRESENT=false"
else
    WRAPPER_SHA="$(sha256sum "$BASE_WRAPPER" | awk '{print $1}')"
    echo "CT120_OPEN_PROBE_BASE_WRAPPER_SHA256=$WRAPPER_SHA"
    if [ "$WRAPPER_SHA" = "$BASE_WRAPPER_SHA256" ]; then
        echo "CT120_OPEN_PROBE_BASE_WRAPPER_PIN=PASS"
    else
        fail "CT120_OPEN_PROBE_BASE_WRAPPER_PIN=FAIL"
    fi
fi

if [ ! -f "$SECRETS_FILE" ]; then
    fail "CT120_OPEN_PROBE_SECRETS_FILE_PRESENT=false"
else
    echo "CT120_OPEN_PROBE_SECRETS_FILE_PRESENT=true"
    echo "CT120_OPEN_PROBE_SECRETS_CONTENT_EMITTED=false"
fi

if ! pkg-config --exists nice glib-2.0 gio-2.0 gobject-2.0; then
    fail "CT120_OPEN_PROBE_BUILD_DEPS=FAIL"
else
    echo "CT120_OPEN_PROBE_BUILD_DEPS=PASS"
fi

if [ "$FAIL" -ne 0 ]; then
    echo "CT120_PSEUDOTCP_OPEN_PREFLIGHT=FAIL"
    echo "CT120_PSEUDOTCP_OPEN_LIVE_INVOKED=false"
    echo "CT120_PSEUDOTCP_OPEN_AUTO_RETRY=false"
    echo "DOOR_ACTION_SENT=false"
    echo "SELF_ACTIVATION_SENT=false"
    echo "MEDIA_SIGNALING_SENT=false"
    exit 1
fi

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
RUN_ROOT="/root/comelit-media-open-probe-$STAMP"
WT="$RUN_ROOT/repo"
BUILD="$RUN_ROOT/build"
LOG="$RUN_ROOT/live.log"
MANIFEST="$RUN_ROOT/MANIFEST.txt"
CANDIDATE_SOURCE="$BUILD/comelit-pseudotcp-open-probe.c"
CANDIDATE_BINARY="$BUILD/comelit-pseudotcp-open-probe"
CANDIDATE_WRAPPER="$BUILD/comelit-p2p-cloud-probe-open-probe"

mkdir -p "$BUILD"
chmod 700 "$RUN_ROOT" "$BUILD"

if ! git -C "$REPO" worktree add --detach "$WT" "$REMOTE_MAIN" >/dev/null; then
    fail "CT120_OPEN_PROBE_WORKTREE_CREATE=FAIL"
else
    echo "CT120_OPEN_PROBE_WORKTREE_CREATE=PASS"
fi

if [ "$FAIL" -eq 0 ]; then
    SOURCE="$WT/$SOURCE_REL"
    TRANSFORM="$WT/$TRANSFORM_REL"

    if [ ! -f "$SOURCE" ] || [ ! -f "$TRANSFORM" ]; then
        fail "CT120_OPEN_PROBE_RESEARCH_FILES_PRESENT=false"
    fi
fi

if [ "$FAIL" -eq 0 ]; then
    python3 "$TRANSFORM" \
        --source "$SOURCE" \
        --output "$CANDIDATE_SOURCE" \
        | tee "$RUN_ROOT/transform.log"
    TRANSFORM_RC=${PIPESTATUS[0]}

    if [ "$TRANSFORM_RC" -eq 0 ]; then
        echo "CT120_OPEN_PROBE_TRANSFORM_RC=0"
    else
        fail "CT120_OPEN_PROBE_TRANSFORM_RC=$TRANSFORM_RC"
    fi
fi

if [ "$FAIL" -eq 0 ]; then
    if grep -Fq 'signal(SIGUSR1, v4_door_signal_handler);' "$CANDIDATE_SOURCE"; then
        fail "CT120_OPEN_PROBE_DOOR_SIGNAL_GATE=FAIL"
    else
        echo "CT120_OPEN_PROBE_DOOR_SIGNAL_GATE=PASS"
    fi

    if grep -Fq '        3300,' "$CANDIDATE_SOURCE"; then
        fail "CT120_OPEN_PROBE_LONG_TIMEOUT_GATE=FAIL"
    else
        echo "CT120_OPEN_PROBE_LONG_TIMEOUT_GATE=PASS"
    fi

    for marker in \
      'PSEUDOTCP_OPEN_PROBE_RESULT=PASS' \
      'PSEUDOTCP_OPEN_PROBE_APP_SIGNALING_SENT=false' \
      'PSEUDOTCP_OPEN_PROBE_SELF_ACTIVATION_SENT=false' \
      'PSEUDOTCP_OPEN_PROBE_MEDIA_SIGNALING_SENT=false' \
      'PSEUDOTCP_OPEN_PROBE_DOOR_ACTION_SENT=false' \
      'PSEUDOTCP_RX_BUFFERED=%u LEN=%u' \
      'PSEUDOTCP_PRESTART_REPLAY_COUNT=%u'
    do
        if grep -Fq "$marker" "$CANDIDATE_SOURCE"; then
            echo "CT120_OPEN_PROBE_SOURCE_MARKER=PASS $marker"
        else
            fail "CT120_OPEN_PROBE_SOURCE_MARKER=FAIL $marker"
        fi
    done
fi

if [ "$FAIL" -eq 0 ]; then
    cc \
      -O2 \
      -g \
      -Wall \
      -Wextra \
      -o "$CANDIDATE_BINARY" \
      "$CANDIDATE_SOURCE" \
      $(pkg-config --cflags --libs nice glib-2.0 gio-2.0 gobject-2.0) \
      2>"$RUN_ROOT/compile.stderr"
    BUILD_RC=$?
    cat "$RUN_ROOT/compile.stderr"
    echo "CT120_OPEN_PROBE_BUILD_RC=$BUILD_RC"

    if [ "$BUILD_RC" -ne 0 ]; then
        fail "CT120_OPEN_PROBE_BUILD=FAIL"
    fi
fi

if [ "$FAIL" -eq 0 ]; then
    chmod 700 "$CANDIDATE_BINARY"

    for marker in \
      'PSEUDOTCP_OPEN_PROBE_RESULT=PASS' \
      'PSEUDOTCP_OPEN_PROBE_SELF_ACTIVATION_SENT=false' \
      'PSEUDOTCP_OPEN_PROBE_MEDIA_SIGNALING_SENT=false' \
      'PSEUDOTCP_OPEN_PROBE_DOOR_ACTION_SENT=false'
    do
        if strings -a "$CANDIDATE_BINARY" | grep -Fq "$marker"; then
            echo "CT120_OPEN_PROBE_BINARY_MARKER=PASS $marker"
        else
            fail "CT120_OPEN_PROBE_BINARY_MARKER=FAIL $marker"
        fi
    done
fi

if [ "$FAIL" -eq 0 ]; then
    python3 - "$BASE_WRAPPER" "$CANDIDATE_WRAPPER" "$CANDIDATE_BINARY" <<'PY'
from pathlib import Path
import sys

source = Path(sys.argv[1])
out = Path(sys.argv[2])
candidate = sys.argv[3]
text = source.read_text(encoding="utf-8")
needle = '"$BASE/bin/comelit_ice_offer_holder"'
count = text.count(needle)
if count != 1:
    raise SystemExit(f"CT120_OPEN_PROBE_WRAPPER_HOLDER_ANCHOR_COUNT={count}")
out.write_text(text.replace(needle, f'"{candidate}"', 1), encoding="utf-8")
PY
    REWRITE_RC=$?
    echo "CT120_OPEN_PROBE_WRAPPER_REWRITE_RC=$REWRITE_RC"
    if [ "$REWRITE_RC" -ne 0 ]; then
        fail "CT120_OPEN_PROBE_WRAPPER_REWRITE=FAIL"
    else
        chmod 700 "$CANDIDATE_WRAPPER"
        if bash -n "$CANDIDATE_WRAPPER"; then
            echo "CT120_OPEN_PROBE_WRAPPER_PARSE=PASS"
        else
            fail "CT120_OPEN_PROBE_WRAPPER_PARSE=FAIL"
        fi
    fi
fi

if [ "$FAIL" -eq 0 ]; then
    SOURCE_SHA="$(sha256sum "$SOURCE" | awk '{print $1}')"
    TRANSFORM_SHA="$(sha256sum "$TRANSFORM" | awk '{print $1}')"
    CANDIDATE_SOURCE_SHA="$(sha256sum "$CANDIDATE_SOURCE" | awk '{print $1}')"
    CANDIDATE_BINARY_SHA="$(sha256sum "$CANDIDATE_BINARY" | awk '{print $1}')"
    CANDIDATE_WRAPPER_SHA="$(sha256sum "$CANDIDATE_WRAPPER" | awk '{print $1}')"

    cat > "$MANIFEST" <<EOF
CT120_PSEUDOTCP_OPEN_PROBE_SCHEMA=1
REPOSITORY_MAIN=$REMOTE_MAIN
REQUIRED_RESEARCH_ANCESTOR=$REQUIRED_ANCESTOR
SOURCE_SHA256=$SOURCE_SHA
TRANSFORM_SHA256=$TRANSFORM_SHA
CANDIDATE_SOURCE_SHA256=$CANDIDATE_SOURCE_SHA
CANDIDATE_BINARY_SHA256=$CANDIDATE_BINARY_SHA
BASE_WRAPPER_SHA256=$WRAPPER_SHA
CANDIDATE_WRAPPER_SHA256=$CANDIDATE_WRAPPER_SHA
LIVE_INVOCATION_LIMIT=1
AUTO_RETRY=false
DOOR_ACTION_ALLOWED=false
SELF_ACTIVATION_ALLOWED=false
MEDIA_SIGNALING_ALLOWED=false
EOF
    chmod 600 "$MANIFEST"

    echo "CT120_PSEUDOTCP_OPEN_PREFLIGHT=PASS"
    echo "CT120_PSEUDOTCP_OPEN_RUN_ROOT=$RUN_ROOT"
fi

if [ "$FAIL" -ne 0 ]; then
    echo "CT120_PSEUDOTCP_OPEN_PREFLIGHT=FAIL"
    echo "CT120_PSEUDOTCP_OPEN_LIVE_INVOKED=false"
    echo "CT120_PSEUDOTCP_OPEN_AUTO_RETRY=false"
    echo "DOOR_ACTION_SENT=false"
    echo "SELF_ACTIVATION_SENT=false"
    echo "MEDIA_SIGNALING_SENT=false"
    exit 1
fi

echo
echo "=== CT120 PSEUDOTCP OPEN LIVE ONE-SHOT ==="
echo "CT120_PSEUDOTCP_OPEN_LIVE_INVOCATION_LIMIT=1"
echo "CT120_PSEUDOTCP_OPEN_AUTO_RETRY=false"
echo "CT120_PSEUDOTCP_OPEN_DOOR_ACTION_ALLOWED=false"
echo "CT120_PSEUDOTCP_OPEN_SELF_ACTIVATION_ALLOWED=false"
echo "CT120_PSEUDOTCP_OPEN_MEDIA_SIGNALING_ALLOWED=false"

timeout --signal=TERM --kill-after=5s 90s "$CANDIDATE_WRAPPER" 2>&1 | tee "$LOG"
LIVE_RC=${PIPESTATUS[0]}
echo "CT120_PSEUDOTCP_OPEN_WRAPPER_RC=$LIVE_RC"

OPEN_COUNT="$(grep -Fxc 'PSEUDOTCP_OPEN=PASS' "$LOG" 2>/dev/null || true)"
RESULT_COUNT="$(grep -Fxc 'PSEUDOTCP_OPEN_PROBE_RESULT=PASS' "$LOG" 2>/dev/null || true)"

SAFETY_OK=1
for marker in \
  'PSEUDOTCP_OPEN_PROBE_APP_SIGNALING_SENT=false' \
  'PSEUDOTCP_OPEN_PROBE_SELF_ACTIVATION_SENT=false' \
  'PSEUDOTCP_OPEN_PROBE_MEDIA_SIGNALING_SENT=false' \
  'PSEUDOTCP_OPEN_PROBE_DOOR_ACTION_SENT=false'
do
    if grep -Fxq "$marker" "$LOG"; then
        echo "CT120_OPEN_PROBE_LIVE_SAFETY_MARKER=PASS $marker"
    else
        echo "CT120_OPEN_PROBE_LIVE_SAFETY_MARKER=FAIL $marker"
        SAFETY_OK=0
    fi
done

APP_VIOLATION=0
for marker in \
  'VIP_ECHO_ACK=PASS' \
  'VIP_UAUT_OPEN_SENT=PASS' \
  'P2_VIP_UAUT_AUTH=PASS' \
  'V4_DOOR_RESULT=ACKED' \
  'PSEUDOTCP_OPEN_PROBE_SELF_ACTIVATION_SENT=true' \
  'PSEUDOTCP_OPEN_PROBE_MEDIA_SIGNALING_SENT=true' \
  'PSEUDOTCP_OPEN_PROBE_DOOR_ACTION_SENT=true'
do
    if grep -Fxq "$marker" "$LOG"; then
        echo "CT120_OPEN_PROBE_FORBIDDEN_LIVE_MARKER=FAIL $marker"
        APP_VIOLATION=1
    fi
done

if [ "$OPEN_COUNT" -eq 1 ] && \
   [ "$RESULT_COUNT" -eq 1 ] && \
   [ "$SAFETY_OK" -eq 1 ] && \
   [ "$APP_VIOLATION" -eq 0 ]; then
    GATE=PASS
else
    GATE=FAIL
fi

{
    echo "LIVE_WRAPPER_RC=$LIVE_RC"
    echo "PSEUDOTCP_OPEN_COUNT=$OPEN_COUNT"
    echo "PSEUDOTCP_OPEN_RESULT_COUNT=$RESULT_COUNT"
    echo "LIVE_SAFETY_MARKERS_OK=$SAFETY_OK"
    echo "FORBIDDEN_APP_MARKER_SEEN=$APP_VIOLATION"
    echo "CT120_PSEUDOTCP_OPEN_GATE=$GATE"
} >> "$MANIFEST"

if git -C "$REPO" worktree remove --force "$WT" >/dev/null 2>&1; then
    echo "CT120_OPEN_PROBE_WORKTREE_CLEANUP=PASS"
else
    echo "CT120_OPEN_PROBE_WORKTREE_CLEANUP=WARNING"
fi

echo
echo "=== CT120 PSEUDOTCP OPEN RESULT ==="
echo "CT120_PSEUDOTCP_OPEN_LIVE_INVOKED=true"
echo "CT120_PSEUDOTCP_OPEN_LIVE_INVOCATIONS=1"
echo "CT120_PSEUDOTCP_OPEN_AUTO_RETRY=false"
echo "CT120_PSEUDOTCP_OPEN_GATE=$GATE"
echo "CT120_PSEUDOTCP_OPEN_RUN_ROOT=$RUN_ROOT"
echo "DOOR_ACTION_SENT=false"
echo "SELF_ACTIVATION_SENT=false"
echo "MEDIA_SIGNALING_SENT=false"

if [ "$GATE" = PASS ]; then
    exit 0
fi

exit 1
