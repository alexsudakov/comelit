#!/usr/bin/env bash
# CT120 research-only one-shot ViP bootstrap probe for an already isolated
# Comelit session.  The caller must stop the HA Comelit listener first and
# restore it afterward.  This runner never touches HA itself.
#
# Live boundary:
#   cloud P2P -> ICE -> PseudoTCP -> ECHO/UAUT/UCFG -> CTPP/CSPB registration
#   -> V4_RING_LISTENER_READY -> terminate.
#
# It sends no self-activation (0x0028), no video event (0x0008), and no Door
# action.  Exactly one network-capable wrapper invocation is permitted.

set -u -o pipefail
umask 077

REPO=/root/comelit-door-diag-repo
REMOTE_REF=refs/remotes/origin/main
REQUIRED_ANCESTOR=e535198b42461ef088b6c06d8b1a7a11df64fc28
BASE_WRAPPER=/usr/local/sbin/comelit-p2p-cloud-probe
BASE_WRAPPER_SHA256=a564535dff0cf10b1fe4766171f2960c52fb581f1c816cf81d2992c5c84e79c9
SECRETS_FILE=/root/.config/comelit/secrets.env
SOURCE_REL=safety-poc/research/door/v1_5_7/comelit-v4-persistent-ctpp-door.c
TRANSFORM_REL=safety-poc/research/media/v1/media_vip_bootstrap_probe_transform.py
SOURCE_SHA256=5827d9fd043b85fc0c59a31661a1a125c6b239771e2a70c3e5afdd95f1a03c73

FAIL=0

fail() {
    echo "$1"
    FAIL=1
}

if [ "${EUID}" -ne 0 ]; then
    echo "CT120_MEDIA_BOOTSTRAP_REQUIRES_ROOT=true"
    exit 1
fi

for command in git python3 cc pkg-config sha256sum timeout strings grep tee; do
    if ! command -v "$command" >/dev/null 2>&1; then
        fail "CT120_MEDIA_BOOTSTRAP_MISSING_COMMAND=$command"
    fi
done

if [ ! -d "$REPO/.git" ]; then
    fail "CT120_MEDIA_BOOTSTRAP_REPO_PRESENT=false"
fi

if ! git -C "$REPO" rev-parse --verify -q "$REMOTE_REF" >/dev/null 2>&1; then
    fail "CT120_MEDIA_BOOTSTRAP_REMOTE_MAIN_PRESENT=false"
fi

REMOTE_MAIN=""
if [ "$FAIL" -eq 0 ]; then
    REMOTE_MAIN="$(git -C "$REPO" rev-parse "$REMOTE_REF")"
    echo "CT120_MEDIA_BOOTSTRAP_REMOTE_MAIN=$REMOTE_MAIN"
    if git -C "$REPO" merge-base --is-ancestor "$REQUIRED_ANCESTOR" "$REMOTE_MAIN"; then
        echo "CT120_MEDIA_BOOTSTRAP_RESEARCH_ANCESTOR=PASS"
    else
        fail "CT120_MEDIA_BOOTSTRAP_RESEARCH_ANCESTOR=FAIL"
    fi
fi

if [ ! -f "$BASE_WRAPPER" ]; then
    fail "CT120_MEDIA_BOOTSTRAP_BASE_WRAPPER_PRESENT=false"
else
    WRAPPER_SHA="$(sha256sum "$BASE_WRAPPER" | awk '{print $1}')"
    echo "CT120_MEDIA_BOOTSTRAP_BASE_WRAPPER_SHA256=$WRAPPER_SHA"
    if [ "$WRAPPER_SHA" = "$BASE_WRAPPER_SHA256" ]; then
        echo "CT120_MEDIA_BOOTSTRAP_BASE_WRAPPER_PIN=PASS"
    else
        fail "CT120_MEDIA_BOOTSTRAP_BASE_WRAPPER_PIN=FAIL"
    fi
fi

if [ ! -f "$SECRETS_FILE" ]; then
    fail "CT120_MEDIA_BOOTSTRAP_SECRETS_FILE_PRESENT=false"
else
    echo "CT120_MEDIA_BOOTSTRAP_SECRETS_FILE_PRESENT=true"
    echo "CT120_MEDIA_BOOTSTRAP_SECRETS_CONTENT_EMITTED=false"
fi

if ! pkg-config --exists nice glib-2.0 gio-2.0 gobject-2.0; then
    fail "CT120_MEDIA_BOOTSTRAP_BUILD_DEPS=FAIL"
else
    echo "CT120_MEDIA_BOOTSTRAP_BUILD_DEPS=PASS"
fi

if [ "$FAIL" -ne 0 ]; then
    echo "CT120_MEDIA_BOOTSTRAP_PREFLIGHT=FAIL"
    echo "CT120_MEDIA_BOOTSTRAP_LIVE_INVOKED=false"
    echo "CT120_MEDIA_BOOTSTRAP_AUTO_RETRY=false"
    echo "DOOR_ACTION_SENT=false"
    echo "SELF_ACTIVATION_SENT=false"
    echo "MEDIA_SIGNALING_SENT=false"
    exit 1
fi

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
RUN_ROOT="/root/comelit-media-vip-bootstrap-$STAMP"
WT="$RUN_ROOT/repo"
BUILD="$RUN_ROOT/build"
LOG="$RUN_ROOT/live.log"
MANIFEST="$RUN_ROOT/MANIFEST.txt"
CANDIDATE_SOURCE="$BUILD/comelit-media-vip-bootstrap.c"
CANDIDATE_BINARY="$BUILD/comelit-media-vip-bootstrap"
CANDIDATE_WRAPPER="$BUILD/comelit-p2p-cloud-probe-media-bootstrap"
STRINGS_DUMP="$RUN_ROOT/candidate.strings"

cleanup_worktree() {
    if [ -e "$WT/.git" ]; then
        if git -C "$REPO" worktree remove --force "$WT" >/dev/null 2>&1; then
            echo "CT120_MEDIA_BOOTSTRAP_WORKTREE_CLEANUP=PASS"
        else
            echo "CT120_MEDIA_BOOTSTRAP_WORKTREE_CLEANUP=WARNING"
        fi
    fi
}

mkdir -p "$BUILD"
chmod 700 "$RUN_ROOT" "$BUILD"

if ! git -C "$REPO" worktree add --detach "$WT" "$REMOTE_MAIN" >/dev/null; then
    fail "CT120_MEDIA_BOOTSTRAP_WORKTREE_CREATE=FAIL"
else
    echo "CT120_MEDIA_BOOTSTRAP_WORKTREE_CREATE=PASS"
fi

if [ "$FAIL" -eq 0 ]; then
    SOURCE="$WT/$SOURCE_REL"
    TRANSFORM="$WT/$TRANSFORM_REL"
    if [ ! -f "$SOURCE" ] || [ ! -f "$TRANSFORM" ]; then
        fail "CT120_MEDIA_BOOTSTRAP_RESEARCH_FILES_PRESENT=false"
    fi
fi

if [ "$FAIL" -eq 0 ]; then
    ACTUAL_SOURCE_SHA="$(sha256sum "$SOURCE" | awk '{print $1}')"
    echo "CT120_MEDIA_BOOTSTRAP_SOURCE_SHA256=$ACTUAL_SOURCE_SHA"
    if [ "$ACTUAL_SOURCE_SHA" != "$SOURCE_SHA256" ]; then
        fail "CT120_MEDIA_BOOTSTRAP_SOURCE_GATE=FAIL"
    else
        echo "CT120_MEDIA_BOOTSTRAP_SOURCE_GATE=PASS"
    fi
fi

if [ "$FAIL" -eq 0 ]; then
    python3 "$TRANSFORM" \
      --source "$SOURCE" \
      --output "$CANDIDATE_SOURCE" \
      | tee "$RUN_ROOT/transform.log"
    TRANSFORM_RC=${PIPESTATUS[0]}
    echo "CT120_MEDIA_BOOTSTRAP_TRANSFORM_RC=$TRANSFORM_RC"
    if [ "$TRANSFORM_RC" -ne 0 ]; then
        fail "CT120_MEDIA_BOOTSTRAP_TRANSFORM=FAIL"
    fi
fi

if [ "$FAIL" -eq 0 ]; then
    if grep -Fq 'signal(SIGUSR1, v4_door_signal_handler);' "$CANDIDATE_SOURCE"; then
        fail "CT120_MEDIA_BOOTSTRAP_DOOR_SIGNAL_GATE=FAIL"
    else
        echo "CT120_MEDIA_BOOTSTRAP_DOOR_SIGNAL_GATE=PASS"
    fi

    if grep -Fq $'g_timeout_add(\n        100,\n        v4_door_tick_cb,' "$CANDIDATE_SOURCE"; then
        fail "CT120_MEDIA_BOOTSTRAP_DOOR_TICK_GATE=FAIL"
    else
        echo "CT120_MEDIA_BOOTSTRAP_DOOR_TICK_GATE=PASS"
    fi

    if grep -Fq '        3300,' "$CANDIDATE_SOURCE"; then
        fail "CT120_MEDIA_BOOTSTRAP_LONG_TIMEOUT_GATE=FAIL"
    else
        echo "CT120_MEDIA_BOOTSTRAP_LONG_TIMEOUT_GATE=PASS"
    fi

    for marker in \
      'MEDIA_VIP_BOOTSTRAP_RESULT=PASS' \
      'MEDIA_VIP_BOOTSTRAP_SELF_ACTIVATION_SENT=false' \
      'MEDIA_VIP_BOOTSTRAP_VIDEO_EVENT_SENT=false' \
      'MEDIA_VIP_BOOTSTRAP_DOOR_ACTION_SENT=false' \
      'V4_DOOR_ACTION_SURFACE_PRESENT=false' \
      'V4_RING_LISTENER_READY=true' \
      'PSEUDOTCP_RX_BUFFERED=%u LEN=%u' \
      'PSEUDOTCP_PRESTART_REPLAY_COUNT=%u'
    do
        if grep -Fq "$marker" "$CANDIDATE_SOURCE"; then
            echo "CT120_MEDIA_BOOTSTRAP_SOURCE_MARKER=PASS $marker"
        else
            fail "CT120_MEDIA_BOOTSTRAP_SOURCE_MARKER=FAIL $marker"
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
    echo "CT120_MEDIA_BOOTSTRAP_BUILD_RC=$BUILD_RC"
    if [ "$BUILD_RC" -ne 0 ]; then
        fail "CT120_MEDIA_BOOTSTRAP_BUILD=FAIL"
    fi
fi

if [ "$FAIL" -eq 0 ]; then
    chmod 700 "$CANDIDATE_BINARY"
    strings -a "$CANDIDATE_BINARY" > "$STRINGS_DUMP"
    STRINGS_RC=$?
    echo "CT120_MEDIA_BOOTSTRAP_STRINGS_RC=$STRINGS_RC"
    if [ "$STRINGS_RC" -ne 0 ]; then
        fail "CT120_MEDIA_BOOTSTRAP_STRINGS=FAIL"
    fi
fi

if [ "$FAIL" -eq 0 ]; then
    for marker in \
      'MEDIA_VIP_BOOTSTRAP_RESULT=PASS' \
      'MEDIA_VIP_BOOTSTRAP_SELF_ACTIVATION_SENT=false' \
      'MEDIA_VIP_BOOTSTRAP_VIDEO_EVENT_SENT=false' \
      'MEDIA_VIP_BOOTSTRAP_DOOR_ACTION_SENT=false' \
      'V4_DOOR_ACTION_SURFACE_PRESENT=false'
    do
        if grep -Fq "$marker" "$STRINGS_DUMP"; then
            echo "CT120_MEDIA_BOOTSTRAP_BINARY_MARKER=PASS $marker"
        else
            fail "CT120_MEDIA_BOOTSTRAP_BINARY_MARKER=FAIL $marker"
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
    raise SystemExit(f"CT120_MEDIA_BOOTSTRAP_WRAPPER_HOLDER_ANCHOR_COUNT={count}")
out.write_text(text.replace(needle, f'"{candidate}"', 1), encoding="utf-8")
PY
    REWRITE_RC=$?
    echo "CT120_MEDIA_BOOTSTRAP_WRAPPER_REWRITE_RC=$REWRITE_RC"
    if [ "$REWRITE_RC" -ne 0 ]; then
        fail "CT120_MEDIA_BOOTSTRAP_WRAPPER_REWRITE=FAIL"
    else
        chmod 700 "$CANDIDATE_WRAPPER"
        bash -n "$CANDIDATE_WRAPPER"
        PARSE_RC=$?
        echo "CT120_MEDIA_BOOTSTRAP_WRAPPER_PARSE_RC=$PARSE_RC"
        if [ "$PARSE_RC" -ne 0 ]; then
            fail "CT120_MEDIA_BOOTSTRAP_WRAPPER_PARSE=FAIL"
        fi
    fi
fi

if [ "$FAIL" -eq 0 ]; then
    cat > "$MANIFEST" <<EOF
CT120_MEDIA_VIP_BOOTSTRAP_SCHEMA=1
REPOSITORY_MAIN=$REMOTE_MAIN
SOURCE_SHA256=$ACTUAL_SOURCE_SHA
LIVE_INVOCATION_LIMIT=1
AUTO_RETRY=false
DOOR_ACTION_ALLOWED=false
SELF_ACTIVATION_ALLOWED=false
VIDEO_EVENT_ALLOWED=false
EOF
    chmod 600 "$MANIFEST"
    echo "CT120_MEDIA_BOOTSTRAP_PREFLIGHT=PASS"
    echo "CT120_MEDIA_BOOTSTRAP_RUN_ROOT=$RUN_ROOT"
fi

if [ "$FAIL" -ne 0 ]; then
    cleanup_worktree
    echo "CT120_MEDIA_BOOTSTRAP_PREFLIGHT=FAIL"
    echo "CT120_MEDIA_BOOTSTRAP_LIVE_INVOKED=false"
    echo "CT120_MEDIA_BOOTSTRAP_AUTO_RETRY=false"
    echo "DOOR_ACTION_SENT=false"
    echo "SELF_ACTIVATION_SENT=false"
    echo "MEDIA_SIGNALING_SENT=false"
    exit 1
fi

echo
echo "=== CT120 MEDIA VIP BOOTSTRAP LIVE ONE-SHOT ==="
echo "CT120_MEDIA_BOOTSTRAP_LIVE_INVOCATION_LIMIT=1"
echo "CT120_MEDIA_BOOTSTRAP_AUTO_RETRY=false"
echo "CT120_MEDIA_BOOTSTRAP_DOOR_ACTION_ALLOWED=false"
echo "CT120_MEDIA_BOOTSTRAP_SELF_ACTIVATION_ALLOWED=false"
echo "CT120_MEDIA_BOOTSTRAP_VIDEO_EVENT_ALLOWED=false"

timeout --signal=TERM --kill-after=5s 120s "$CANDIDATE_WRAPPER" 2>&1 | tee "$LOG"
LIVE_RC=${PIPESTATUS[0]}
echo "CT120_MEDIA_BOOTSTRAP_WRAPPER_RC=$LIVE_RC"

READY_COUNT="$(grep -Fxc 'V4_RING_LISTENER_READY=true' "$LOG" 2>/dev/null || true)"
RESULT_COUNT="$(grep -Fxc 'MEDIA_VIP_BOOTSTRAP_RESULT=PASS' "$LOG" 2>/dev/null || true)"

SAFETY_OK=1
for marker in \
  'MEDIA_VIP_BOOTSTRAP_SELF_ACTIVATION_SENT=false' \
  'MEDIA_VIP_BOOTSTRAP_VIDEO_EVENT_SENT=false' \
  'MEDIA_VIP_BOOTSTRAP_DOOR_ACTION_SENT=false'
do
    if grep -Fxq "$marker" "$LOG"; then
        echo "CT120_MEDIA_BOOTSTRAP_LIVE_SAFETY_MARKER=PASS $marker"
    else
        echo "CT120_MEDIA_BOOTSTRAP_LIVE_SAFETY_MARKER=FAIL $marker"
        SAFETY_OK=0
    fi
done

VIOLATION=0
for marker in \
  'V4_DOOR_RESULT=ACKED' \
  'MEDIA_VIP_BOOTSTRAP_SELF_ACTIVATION_SENT=true' \
  'MEDIA_VIP_BOOTSTRAP_VIDEO_EVENT_SENT=true' \
  'MEDIA_VIP_BOOTSTRAP_DOOR_ACTION_SENT=true'
do
    if grep -Fxq "$marker" "$LOG"; then
        echo "CT120_MEDIA_BOOTSTRAP_FORBIDDEN_LIVE_MARKER=FAIL $marker"
        VIOLATION=1
    fi
done

if [ "$READY_COUNT" -eq 1 ] && \
   [ "$RESULT_COUNT" -eq 1 ] && \
   [ "$SAFETY_OK" -eq 1 ] && \
   [ "$VIOLATION" -eq 0 ]; then
    GATE=PASS
else
    GATE=FAIL
fi

{
    echo "LIVE_WRAPPER_RC=$LIVE_RC"
    echo "LISTENER_READY_COUNT=$READY_COUNT"
    echo "BOOTSTRAP_RESULT_COUNT=$RESULT_COUNT"
    echo "LIVE_SAFETY_MARKERS_OK=$SAFETY_OK"
    echo "FORBIDDEN_MARKER_SEEN=$VIOLATION"
    echo "CT120_MEDIA_VIP_BOOTSTRAP_GATE=$GATE"
} >> "$MANIFEST"

cleanup_worktree

echo
echo "=== CT120 MEDIA VIP BOOTSTRAP RESULT ==="
echo "CT120_MEDIA_BOOTSTRAP_LIVE_INVOKED=true"
echo "CT120_MEDIA_BOOTSTRAP_LIVE_INVOCATIONS=1"
echo "CT120_MEDIA_BOOTSTRAP_AUTO_RETRY=false"
echo "CT120_MEDIA_VIP_BOOTSTRAP_GATE=$GATE"
echo "CT120_MEDIA_BOOTSTRAP_RUN_ROOT=$RUN_ROOT"
echo "DOOR_ACTION_SENT=false"
echo "SELF_ACTIVATION_SENT=false"
echo "MEDIA_SIGNALING_SENT=false"

if [ "$GATE" = PASS ]; then
    exit 0
fi
exit 1
