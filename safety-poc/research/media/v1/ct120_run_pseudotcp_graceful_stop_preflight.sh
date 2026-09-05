#!/usr/bin/env bash
# CT120 offline-only preflight for the research graceful PseudoTCP stop candidate.
# It transforms and compiles the current native source and verifies markers.
# It never executes the candidate binary and performs no Comelit/HA network I/O.

set -u -o pipefail
umask 077

REPO=/root/comelit-door-diag-repo
REMOTE_REF=refs/remotes/origin/main
REQUIRED_ANCESTOR=40197c634f6f12745fda48a14f8481e6cc902388
CT120_IP=192.168.1.85
SOURCE_REL=safety-poc/research/door/v1_5_3/comelit-v4-persistent-ctpp-door.c
TRANSFORM_REL=safety-poc/research/media/v1/pseudotcp_graceful_stop_transform.py

FAIL=0

fail() {
    echo "$1"
    FAIL=1
}

if [ "${EUID}" -ne 0 ]; then
    echo "GRACEFUL_STOP_PREFLIGHT_REQUIRES_ROOT=true"
    exit 1
fi

for command in git python3 cc pkg-config sha256sum strings grep ip; do
    if ! command -v "$command" >/dev/null 2>&1; then
        fail "GRACEFUL_STOP_PREFLIGHT_MISSING_COMMAND=$command"
    fi
done

if [ ! -d "$REPO/.git" ]; then
    fail "GRACEFUL_STOP_PREFLIGHT_REPO_PRESENT=false"
fi

if ! ip -4 addr show | grep -Fq "$CT120_IP/"; then
    fail "GRACEFUL_STOP_PREFLIGHT_CT120_IDENTITY=FAIL"
else
    echo "GRACEFUL_STOP_PREFLIGHT_CT120_IDENTITY=PASS"
fi

if ! git -C "$REPO" rev-parse --verify -q "$REMOTE_REF" >/dev/null 2>&1; then
    fail "GRACEFUL_STOP_PREFLIGHT_REMOTE_MAIN_PRESENT=false"
fi

REMOTE_MAIN=""
if [ "$FAIL" -eq 0 ]; then
    REMOTE_MAIN="$(git -C "$REPO" rev-parse "$REMOTE_REF")"
    echo "GRACEFUL_STOP_PREFLIGHT_REMOTE_MAIN=$REMOTE_MAIN"
    if git -C "$REPO" merge-base --is-ancestor "$REQUIRED_ANCESTOR" "$REMOTE_MAIN"; then
        echo "GRACEFUL_STOP_PREFLIGHT_RESEARCH_ANCESTOR=PASS"
    else
        fail "GRACEFUL_STOP_PREFLIGHT_RESEARCH_ANCESTOR=FAIL"
    fi
fi

if ! pkg-config --exists nice glib-2.0 gio-2.0 gobject-2.0; then
    fail "GRACEFUL_STOP_PREFLIGHT_BUILD_DEPS=FAIL"
else
    echo "GRACEFUL_STOP_PREFLIGHT_BUILD_DEPS=PASS"
    echo "GRACEFUL_STOP_PREFLIGHT_LIBNICE_VERSION=$(pkg-config --modversion nice)"
fi

if [ "$FAIL" -ne 0 ]; then
    echo "PSEUDOTCP_GRACEFUL_STOP_PREFLIGHT=FAIL"
    echo "NETWORK_IO_PERFORMED=false"
    echo "HOME_ASSISTANT_TOUCHED=false"
    exit 1
fi

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
RUN_ROOT="/root/comelit-pseudotcp-graceful-stop-preflight-$STAMP"
WT="$RUN_ROOT/repo"
BUILD="$RUN_ROOT/build"
CANDIDATE_SOURCE="$BUILD/comelit-v4-graceful-stop.c"
CANDIDATE_BINARY="$BUILD/comelit-v4-graceful-stop"
STRINGS_DUMP="$RUN_ROOT/candidate.strings"
MANIFEST="$RUN_ROOT/MANIFEST.txt"

cleanup_worktree() {
    if [ -e "$WT/.git" ]; then
        if git -C "$REPO" worktree remove --force "$WT" >/dev/null 2>&1; then
            echo "GRACEFUL_STOP_PREFLIGHT_WORKTREE_CLEANUP=PASS"
        else
            echo "GRACEFUL_STOP_PREFLIGHT_WORKTREE_CLEANUP=WARNING"
        fi
    fi
}

mkdir -p "$BUILD"
chmod 700 "$RUN_ROOT" "$BUILD"

if git -C "$REPO" worktree add --detach "$WT" "$REMOTE_MAIN" >/dev/null; then
    echo "GRACEFUL_STOP_PREFLIGHT_WORKTREE_CREATE=PASS"
else
    fail "GRACEFUL_STOP_PREFLIGHT_WORKTREE_CREATE=FAIL"
fi

if [ "$FAIL" -eq 0 ]; then
    SOURCE="$WT/$SOURCE_REL"
    TRANSFORM="$WT/$TRANSFORM_REL"
    if [ ! -f "$SOURCE" ] || [ ! -f "$TRANSFORM" ]; then
        fail "GRACEFUL_STOP_PREFLIGHT_RESEARCH_FILES_PRESENT=false"
    fi
fi

if [ "$FAIL" -eq 0 ]; then
    python3 "$TRANSFORM" \
      --source "$SOURCE" \
      --output "$CANDIDATE_SOURCE" \
      > "$RUN_ROOT/transform.log"
    TRANSFORM_RC=$?
    cat "$RUN_ROOT/transform.log"
    echo "GRACEFUL_STOP_PREFLIGHT_TRANSFORM_RC=$TRANSFORM_RC"
    if [ "$TRANSFORM_RC" -ne 0 ]; then
        fail "GRACEFUL_STOP_PREFLIGHT_TRANSFORM=FAIL"
    fi
fi

if [ "$FAIL" -eq 0 ]; then
    for marker in \
      'pseudo_tcp_socket_close(pseudo_tcp, FALSE);' \
      'PSEUDOTCP_GRACEFUL_CLOSE_REQUESTED=true' \
      'PSEUDOTCP_GRACEFUL_CLOSE_FORCE=false' \
      'PSEUDOTCP_GRACEFUL_CLOSE_FORCE_RST_SENT=false' \
      'PSEUDOTCP_GRACEFUL_CLOSE_COMPLETE=true' \
      'PSEUDOTCP_GRACEFUL_CLOSE_TIMEOUT=true' \
      'PSEUDOTCP_GRACEFUL_CLOSE_DRAINED_BYTES=%u'
    do
        if grep -Fq "$marker" "$CANDIDATE_SOURCE"; then
            echo "GRACEFUL_STOP_SOURCE_MARKER=PASS $marker"
        else
            fail "GRACEFUL_STOP_SOURCE_MARKER=FAIL $marker"
        fi
    done

    if grep -Fq 'pseudo_tcp_socket_close(pseudo_tcp, TRUE);' "$CANDIDATE_SOURCE"; then
        fail "GRACEFUL_STOP_FORCE_CLOSE_GATE=FAIL"
    else
        echo "GRACEFUL_STOP_FORCE_CLOSE_GATE=PASS"
    fi
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
      2> "$RUN_ROOT/compile.stderr"
    BUILD_RC=$?
    cat "$RUN_ROOT/compile.stderr"
    echo "GRACEFUL_STOP_PREFLIGHT_BUILD_RC=$BUILD_RC"
    if [ "$BUILD_RC" -ne 0 ]; then
        fail "GRACEFUL_STOP_PREFLIGHT_BUILD=FAIL"
    fi
fi

if [ "$FAIL" -eq 0 ]; then
    strings -a "$CANDIDATE_BINARY" > "$STRINGS_DUMP"
    STRINGS_RC=$?
    echo "GRACEFUL_STOP_PREFLIGHT_STRINGS_RC=$STRINGS_RC"
    if [ "$STRINGS_RC" -ne 0 ]; then
        fail "GRACEFUL_STOP_PREFLIGHT_STRINGS=FAIL"
    fi
fi

if [ "$FAIL" -eq 0 ]; then
    for marker in \
      'PSEUDOTCP_GRACEFUL_CLOSE_REQUESTED=true' \
      'PSEUDOTCP_GRACEFUL_CLOSE_FORCE=false' \
      'PSEUDOTCP_GRACEFUL_CLOSE_FORCE_RST_SENT=false' \
      'PSEUDOTCP_GRACEFUL_CLOSE_COMPLETE=true' \
      'PSEUDOTCP_GRACEFUL_CLOSE_TIMEOUT=true'
    do
        if grep -Fq "$marker" "$STRINGS_DUMP"; then
            echo "GRACEFUL_STOP_BINARY_MARKER=PASS $marker"
        else
            fail "GRACEFUL_STOP_BINARY_MARKER=FAIL $marker"
        fi
    done
fi

if [ "$FAIL" -eq 0 ]; then
    SOURCE_SHA="$(sha256sum "$SOURCE" | awk '{print $1}')"
    TRANSFORM_SHA="$(sha256sum "$TRANSFORM" | awk '{print $1}')"
    CANDIDATE_SOURCE_SHA="$(sha256sum "$CANDIDATE_SOURCE" | awk '{print $1}')"
    CANDIDATE_BINARY_SHA="$(sha256sum "$CANDIDATE_BINARY" | awk '{print $1}')"

    cat > "$MANIFEST" <<EOF
PSEUDOTCP_GRACEFUL_STOP_PREFLIGHT_SCHEMA=1
REPOSITORY_MAIN=$REMOTE_MAIN
SOURCE_SHA256=$SOURCE_SHA
TRANSFORM_SHA256=$TRANSFORM_SHA
CANDIDATE_SOURCE_SHA256=$CANDIDATE_SOURCE_SHA
CANDIDATE_BINARY_SHA256=$CANDIDATE_BINARY_SHA
LIBNICE_VERSION=$(pkg-config --modversion nice)
CANDIDATE_EXECUTED=false
NETWORK_IO_PERFORMED=false
HOME_ASSISTANT_TOUCHED=false
DOOR_ACTION_SENT=false
SELF_ACTIVATION_SENT=false
MEDIA_SIGNALING_SENT=false
EOF
    chmod 600 "$MANIFEST"
fi

cleanup_worktree

echo
echo "=== FINAL ==="
echo "GRACEFUL_STOP_PREFLIGHT_RUN_ROOT=$RUN_ROOT"
echo "CANDIDATE_EXECUTED=false"
echo "NETWORK_IO_PERFORMED=false"
echo "HOME_ASSISTANT_TOUCHED=false"
echo "DOOR_ACTION_SENT=false"
echo "SELF_ACTIVATION_SENT=false"
echo "MEDIA_SIGNALING_SENT=false"

if [ "$FAIL" -eq 0 ]; then
    echo "PSEUDOTCP_GRACEFUL_STOP_PREFLIGHT=PASS"
    exit 0
fi

echo "PSEUDOTCP_GRACEFUL_STOP_PREFLIGHT=FAIL"
exit 1
