#!/usr/bin/env bash
# Offline CT120 builder for the P80 HAOS/musl entrance media helper.
#
# This script does NOT execute the candidate, does NOT contact Comelit, does NOT
# control the Home Assistant listener, and does NOT install anything into HA.
# It only transforms source, compiles it in an Alpine 3.24.1 chroot, validates
# the ELF/marker contract, and copies the candidate to /root/comelit-media-p80.

set -u -o pipefail
umask 077

REPO=${REPO:-/root/comelit-door-diag-repo}
BRANCH=${BRANCH:-fix/p116-ha-stream-rtp-bridge}
SOURCE_REL=safety-poc/research/door/v1_5_7/comelit-v4-persistent-ctpp-door.c
TRANSFORM_REL=safety-poc/research/media/v1/entrance_p80_ha_media_runtime_transform.py
OUTPUT=${OUTPUT:-/root/comelit-media-p80}
EXPECTED_ARCH=x86_64
EXPECTED_INTERPRETER=/lib/ld-musl-x86_64.so.1
EXPECTED_NEEDED=libc.musl-x86_64.so.1,libglib-2.0.so.0,libgobject-2.0.so.0,libnice.so.10
ALPINE_VERSION=3.24.1
ALPINE_NAME=alpine-minirootfs-3.24.1-x86_64.tar.gz
ALPINE_URL=https://dl-cdn.alpinelinux.org/alpine/v3.24/releases/x86_64/$ALPINE_NAME
ALPINE_SHA_URL=$ALPINE_URL.sha256
OFFLINE_ROOTFS=${OFFLINE_ROOTFS:-}
OFFLINE_BUILD=${OFFLINE_BUILD:-1}

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
RUN_ROOT="/root/comelit-p80-haos-build-$STAMP"
ROOTFS="$RUN_ROOT/rootfs"
BUILD="$RUN_ROOT/build"
ARCHIVE="$RUN_ROOT/$ALPINE_NAME"
SHA_FILE="$ARCHIVE.sha256"
GENERATED="$BUILD/comelit-media.c"
CANDIDATE="$BUILD/comelit-media"
META="$BUILD/build-meta.txt"
FAIL=0
ROOTFS_MODE=UNSELECTED

fail() {
    echo "$1" >&2
    FAIL=1
}

summary() {
    echo
    echo '=== COMELIT P80 HAOS MEDIA BUILD SUMMARY ==='
    echo "P80_BUILD_RUN_ROOT=$RUN_ROOT"
    echo "P80_BUILD_REPO_HEAD=${REPO_HEAD:-UNKNOWN}"
    echo "P80_BUILD_BRANCH=${CURRENT_BRANCH:-UNKNOWN}"
    echo "P80_TRANSFORM_RC=${TRANSFORM_RC:-NOT_REACHED}"
    echo "P80_CHROOT_BUILD_RC=${BUILD_RC:-NOT_REACHED}"
    echo "P80_BINARY_SHA256=${CANDIDATE_SHA:-NOT_REACHED}"
    echo "P80_BINARY_OUTPUT=${FINAL_OUTPUT:-NOT_CREATED}"
    echo "candidate_executed=false"
    echo "P80_BINARY_EXECUTED=false"
    echo "P80_BUILD_ROOTFS_MODE=$ROOTFS_MODE"
    echo "LIB_IDENTICAL=${LIB_IDENTICAL:-NOT_REACHED}"
    echo "NO_GLIBC_DEPENDENCY=${NO_GLIBC_DEPENDENCY:-NOT_REACHED}"
    echo "NO_NEW_RUNTIME_DEPENDENCY=${NO_NEW_RUNTIME_DEPENDENCY:-NOT_REACHED}"
    echo "MUSL_INTERPRETER_GATE=${MUSL_INTERPRETER_GATE:-NOT_REACHED}"
    echo "COMELIT_NETWORK_REQUESTS=0"
    echo "LISTENER_CHANGED=NO"
    echo "HA_CORE_CHANGED=NO"
    echo "DOOR_ACTION_SENT=false"
    if [ "$FAIL" -eq 0 ] && [ -n "${FINAL_OUTPUT:-}" ]; then
        echo 'P80_HAOS_MEDIA_BUILD=PASS'
    else
        echo 'P80_HAOS_MEDIA_BUILD=FAIL'
    fi
    echo '=== END COMELIT P80 HAOS MEDIA BUILD SUMMARY ==='
}
trap summary EXIT

if [ "${EUID}" -ne 0 ]; then
    fail 'P80_BUILD_ROOT_REQUIRED=true'
    exit 1
fi

for command in git python3 sha256sum awk grep strings file tar chroot uname stat cp readelf sort paste find cmp sed install; do
    command -v "$command" >/dev/null 2>&1 || fail "P80_BUILD_MISSING_COMMAND=$command"
done
[ "$FAIL" -eq 0 ] || exit 1

[ "$(uname -m)" = "$EXPECTED_ARCH" ] || fail 'P80_BUILD_ARCH=FAIL'
[ -d "$REPO/.git" ] || fail 'P80_BUILD_REPO=ABSENT'
[ "$FAIL" -eq 0 ] || exit 1

REPO_HEAD="$(git -C "$REPO" rev-parse HEAD 2>/dev/null || true)"
CURRENT_BRANCH="$(git -C "$REPO" branch --show-current 2>/dev/null || true)"
[ "$CURRENT_BRANCH" = "$BRANCH" ] || fail "P80_BUILD_BRANCH_GATE=FAIL expected=$BRANCH actual=$CURRENT_BRANCH"
[ -z "$(git -C "$REPO" status --porcelain)" ] || fail 'P80_BUILD_WORKTREE_CLEAN=FAIL'
[ -f "$REPO/$SOURCE_REL" ] || fail 'P80_BUILD_SOURCE=ABSENT'
[ -f "$REPO/$TRANSFORM_REL" ] || fail 'P80_BUILD_TRANSFORM=ABSENT'
[ "$FAIL" -eq 0 ] || exit 1

echo "P80_BUILD_REPO_HEAD=$REPO_HEAD"
echo "P80_BUILD_BRANCH_GATE=PASS"
echo "P80_BUILD_WORKTREE_CLEAN=PASS"

mkdir -p "$RUN_ROOT" "$BUILD"
chmod 700 "$RUN_ROOT" "$BUILD"

PYTHONDONTWRITEBYTECODE=1 \
PYTHONPATH="$REPO/safety-poc/research/media/v1" \
python3 "$REPO/$TRANSFORM_REL" \
  --source "$REPO/$SOURCE_REL" \
  --output "$GENERATED"
TRANSFORM_RC=$?
echo "P80_TRANSFORM_RC=$TRANSFORM_RC"
[ "$TRANSFORM_RC" -eq 0 ] || fail 'P80_TRANSFORM=FAIL'
[ -s "$GENERATED" ] || fail 'P80_GENERATED_SOURCE=EMPTY'

if [ "$FAIL" -eq 0 ]; then
    grep -Fq '#define RUN_DIR     "/run/comelit-media"' "$GENERATED" || fail 'P80_RUN_DIR_GATE=FAIL'
    ! grep -Fq 'signal(SIGUSR1, v4_door_signal_handler);' "$GENERATED" || fail 'P80_DOOR_SIGNAL_GATE=FAIL'
    grep -Fq 'P80_MEDIA_ACTIVE=true' "$GENERATED" || fail 'P80_MEDIA_ACTIVE_MARKER_SOURCE=FAIL'
    grep -Fq 'P80_VIDEO_RTP_FORWARDING=PASS' "$GENERATED" || fail 'P80_VIDEO_FORWARD_MARKER_SOURCE=FAIL'
    grep -Fq 'P80_AUDIO_RTP_FORWARDING=PASS' "$GENERATED" || fail 'P80_AUDIO_FORWARD_MARKER_SOURCE=FAIL'
    grep -Fq 'P78_SECOND_CTPP_OPEN=false' "$GENERATED" || fail 'P80_SECOND_CTPP_OPEN_GATE=FAIL'
fi
[ "$FAIL" -eq 0 ] || exit 1

echo 'P80_GENERATED_SOURCE_GATE=PASS'

if [ -n "$OFFLINE_ROOTFS" ]; then
    ROOTFS="$OFFLINE_ROOTFS"
elif [ "$OFFLINE_BUILD" = "1" ]; then
    ROOTFS="$(
        find /root -maxdepth 2 -path '/root/comelit-p80-haos-build-*/rootfs' -type d \
            -exec test -x '{}/usr/bin/gcc' ';' \
            -exec test -e '{}/lib/ld-musl-x86_64.so.1' ';' \
            -printf '%T@ %p\n' 2>/dev/null |
        sort -nr |
        awk 'NR == 1 {print $2}'
    )"
fi

if [ -n "$ROOTFS" ] && [ -x "$ROOTFS/usr/bin/gcc" ] && [ -e "$ROOTFS/lib/ld-musl-x86_64.so.1" ]; then
    ROOTFS_MODE=CACHED_CHROOT
    echo "P80_OFFLINE_ROOTFS=$ROOTFS"
    echo 'P80_ALPINE_DOWNLOAD=SKIPPED_OFFLINE'
else
    if [ "$OFFLINE_BUILD" = "1" ]; then
        fail 'P80_OFFLINE_ROOTFS=ABSENT'
        exit 1
    fi
    ROOTFS="$RUN_ROOT/rootfs"
    mkdir -p "$ROOTFS"
    chmod 700 "$ROOTFS"
    ROOTFS_MODE=DOWNLOADED_MINIROOTFS

    echo '=== OFFICIAL ALPINE MINIROOTFS ==='
    python3 - "$ALPINE_URL" "$ARCHIVE" "$ALPINE_SHA_URL" "$SHA_FILE" <<'PY'
from pathlib import Path
import sys
import urllib.parse
import urllib.request

for url, target in ((sys.argv[1], Path(sys.argv[2])), (sys.argv[3], Path(sys.argv[4]))):
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != "dl-cdn.alpinelinux.org":
        raise SystemExit(f"refusing URL: {url}")
    with urllib.request.urlopen(url, timeout=60) as response:
        if response.status != 200:
            raise SystemExit(f"download failed status={response.status}")
        target.write_bytes(response.read())
PY
    DOWNLOAD_RC=$?
    echo "P80_ALPINE_DOWNLOAD_RC=$DOWNLOAD_RC"
    [ "$DOWNLOAD_RC" -eq 0 ] || fail 'P80_ALPINE_DOWNLOAD=FAIL'
    [ "$FAIL" -eq 0 ] || exit 1

    EXPECTED_SHA="$(awk 'NF >= 1 {print $1; exit}' "$SHA_FILE")"
    ACTUAL_SHA="$(sha256sum "$ARCHIVE" | awk '{print $1}')"
    [ ${#EXPECTED_SHA} -eq 64 ] || fail 'P80_ALPINE_SHA_FORMAT=FAIL'
    [ "$EXPECTED_SHA" = "$ACTUAL_SHA" ] || fail 'P80_ALPINE_SHA_GATE=FAIL'
    [ "$FAIL" -eq 0 ] || exit 1

    echo "P80_ALPINE_SHA256=$ACTUAL_SHA"
    echo 'P80_ALPINE_SHA_GATE=PASS'

    tar -xzf "$ARCHIVE" -C "$ROOTFS" || { fail 'P80_ALPINE_EXTRACT=FAIL'; exit 1; }
fi

[ "$(cat "$ROOTFS/etc/alpine-release")" = "$ALPINE_VERSION" ] || { fail 'P80_ALPINE_VERSION=FAIL'; exit 1; }

mkdir -p "$ROOTFS/src" "$ROOTFS/out"
cp "$GENERATED" "$ROOTFS/src/comelit-media.c"
chmod 600 "$ROOTFS/src/comelit-media.c"

echo '=== ALPINE CHROOT BUILD ==='
chroot "$ROOTFS" /bin/sh -eu -c '
  if [ ! -x /usr/bin/gcc ]; then
    apk add --no-cache build-base pkgconf glib-dev libnice-dev file binutils
  fi

  cc \
    -O2 \
    -g \
    -Wall \
    -Wextra \
    -Wl,--as-needed \
    -o /out/comelit-media \
    /src/comelit-media.c \
    $(pkg-config --cflags --libs nice glib-2.0 gio-2.0 gobject-2.0)

  chmod 755 /out/comelit-media
  INTERPRETER="$(readelf -l /out/comelit-media | sed -n "s@.*Requesting program interpreter: \(.*\)]@\1@p")"
  NEEDED="$(readelf -d /out/comelit-media | sed -n "s/.*Shared library: \[\(.*\)\]/\1/p" | sort | paste -sd, -)"
  BUILD_ID="$(readelf -n /out/comelit-media | sed -n "s/^.*Build ID: //p" | head -1)"
  {
    echo "rootfs_mode='"$ROOTFS_MODE"'"
    echo "alpine_version=$(cat /etc/alpine-release)"
    echo "cc_version=$(cc --version | head -1)"
    echo "libnice_version=$(pkg-config --modversion nice)"
    echo "glib_version=$(pkg-config --modversion glib-2.0)"
    echo "gobject_version=$(pkg-config --modversion gobject-2.0)"
    echo "cflags=-O2 -g -Wall -Wextra -Wl,--as-needed"
    echo "interpreter=$INTERPRETER"
    echo "needed_sorted=$NEEDED"
    echo "elf_build_id=$BUILD_ID"
    echo "candidate_executed=false"
  } > /out/build-meta.txt
'
BUILD_RC=$?
echo "P80_CHROOT_BUILD_RC=$BUILD_RC"
[ "$BUILD_RC" -eq 0 ] || fail 'P80_CHROOT_BUILD=FAIL'
[ "$FAIL" -eq 0 ] || exit 1

cp "$ROOTFS/out/comelit-media" "$CANDIDATE"
cp "$ROOTFS/out/build-meta.txt" "$META"
chmod 755 "$CANDIDATE"
cat "$META"

INTERPRETER="$(sed -n 's/^interpreter=//p' "$META")"
NEEDED="$(sed -n 's/^needed_sorted=//p' "$META")"
[ "$INTERPRETER" = "$EXPECTED_INTERPRETER" ] && MUSL_INTERPRETER_GATE=PASS || MUSL_INTERPRETER_GATE=FAIL
[ "$MUSL_INTERPRETER_GATE" = PASS ] || fail "P80_INTERPRETER_GATE=FAIL actual=$INTERPRETER"
[ "$NEEDED" = "$EXPECTED_NEEDED" ] && NO_NEW_RUNTIME_DEPENDENCY=PASS || NO_NEW_RUNTIME_DEPENDENCY=FAIL
[ "$NO_NEW_RUNTIME_DEPENDENCY" = PASS ] || fail "P80_NEEDED_GATE=FAIL actual=$NEEDED"
case ",$NEEDED," in
    *,libc.so.6,*) NO_GLIBC_DEPENDENCY=FAIL ;;
    *) NO_GLIBC_DEPENDENCY=PASS ;;
esac
[ "$NO_GLIBC_DEPENDENCY" = PASS ] || fail 'P80_GLIBC_DEPENDENCY=FAIL'
file "$CANDIDATE" | sed 's#^.*: #P80_BINARY_FILE=#'
strings -a "$CANDIDATE" > "$BUILD/candidate.strings"

for marker in \
  '/run/comelit-media' \
  'P80_MEDIA_ACTIVE=true' \
  'P80_MEDIA_LIFETIME_OWNER=HOME_ASSISTANT' \
  'P80_MEDIA_AUTO_CLOSE_3000MS=false' \
  'P80_DOOR_SIGNAL_ENTRYPOINT=false' \
  'P80_VIDEO_RTP_FORWARDING=PASS' \
  'P80_AUDIO_RTP_FORWARDING=PASS' \
  'P80_WRAPPER_PROFILE_MISMATCH=true' \
  'P78_SECOND_CTPP_OPEN=false' \
  'ENTRANCE_SIGNALING_DOOR_ACTION_SENT=false'
do
    grep -Fq "$marker" "$BUILD/candidate.strings" || fail "P80_BINARY_MARKER_GATE=FAIL marker=$marker"
done

if grep -Fq '/run/comelit-p2p' "$BUILD/candidate.strings"; then
    fail 'P80_BINARY_LISTENER_RUN_DIR_LEAK=FAIL'
fi
if grep -Fq '/lib64/ld-linux-x86-64.so.2' "$BUILD/candidate.strings"; then
    fail 'P80_BINARY_GLIBC_INTERPRETER=FAIL'
fi

LIB_IDENTICAL=PASS
for needed in libglib-2.0.so.0 libgobject-2.0.so.0 libnice.so.10; do
    packaged="$REPO/custom_components/comelit/native/lib/$needed"
    rootfs_lib="$(find "$ROOTFS/lib" "$ROOTFS/usr/lib" -name "$needed" -type f -print -quit 2>/dev/null || true)"
    if [ ! -f "$packaged" ] || [ ! -f "$rootfs_lib" ] || ! cmp -s "$packaged" "$rootfs_lib"; then
        LIB_IDENTICAL=FAIL
        fail "P80_LIB_IDENTICAL=FAIL lib=$needed"
    fi
done

[ "$FAIL" -eq 0 ] || exit 1

echo 'P80_BINARY_MARKER_GATE=PASS'
echo "P80_INTERPRETER_GATE=PASS $INTERPRETER"
echo "NO_GLIBC_DEPENDENCY=$NO_GLIBC_DEPENDENCY"
echo "NO_NEW_RUNTIME_DEPENDENCY=$NO_NEW_RUNTIME_DEPENDENCY"
echo "MUSL_INTERPRETER_GATE=$MUSL_INTERPRETER_GATE"
echo "LIB_IDENTICAL=$LIB_IDENTICAL"

CANDIDATE_SHA="$(sha256sum "$CANDIDATE" | awk '{print $1}')"
install -m 755 "$CANDIDATE" "$OUTPUT"
FINAL_OUTPUT="$OUTPUT"

[ -x "$OUTPUT" ] || { fail 'P80_FINAL_OUTPUT=FAIL'; exit 1; }
[ "$(sha256sum "$OUTPUT" | awk '{print $1}')" = "$CANDIDATE_SHA" ] || { fail 'P80_FINAL_SHA_GATE=FAIL'; exit 1; }

echo "P80_FINAL_OUTPUT=$OUTPUT"
echo "P80_FINAL_SHA256=$CANDIDATE_SHA"
