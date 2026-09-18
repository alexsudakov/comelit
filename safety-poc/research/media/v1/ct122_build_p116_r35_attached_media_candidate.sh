#!/usr/bin/env bash
# Offline CT122 (this host) builder for the P116/R35 attached-media research
# candidate.  Runs as the non-root `hermes` user via `docker run --network none`,
# modeled on the ct120_build_p80_haos_media_helper.sh recipe and the proven
# local precedent /tmp/p107/musl-build3.sh.
#
# This script does NOT execute the candidate, does NOT contact Comelit, does
# NOT touch the Home Assistant listener, does NOT install anything, and does
# NOT write inside the repository tree.  It only: (1) regenerates the
# canonical --include-p116 source and checks its pinned digest, (2) applies
# the R35 overlay transform and records its digest, (3) compiles the result
# inside an Alpine 3.24.1 container with --network none using a local APK
# closure (no package index contact), and (4) runs read-only ELF/marker gates
# against the resulting candidate binary.
set -u -o pipefail
umask 077

REPO=${REPO:-/home/hermes/repos/comelit-worktrees/p116-r35-attached-media-native}
SAFETY_POC="$REPO/safety-poc"
SOURCE_REL=research/door/v1_5_7/comelit-v4-persistent-ctpp-door.c
CANONICAL_TRANSFORM_REL=research/media/v1/entrance_p106_teardown_state_classification_transform.py
R35_TRANSFORM_REL=research/media/v1/entrance_p116_r35_attached_media_native_transform.py
EXPECTED_CANONICAL_SOURCE_SHA=${EXPECTED_CANONICAL_SOURCE_SHA:-1c89d61de4372d96b25f6894862741244753c107a3a9b9e04817250b3bea55b2}

APK_CLOSURE=${APK_CLOSURE:-/home/hermes/comelit-r35-apk-closure}
ALPINE_IMAGE=${ALPINE_IMAGE:-alpine:3.24.1}
EXPECTED_INTERPRETER=/lib/ld-musl-x86_64.so.1
EXPECTED_NEEDED=libc.musl-x86_64.so.1,libglib-2.0.so.0,libgobject-2.0.so.0,libnice.so.10

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
RUN_ROOT="/home/hermes/comelit-r35-build-$STAMP"
GENERATED="$RUN_ROOT/comelit-media-canonical.c"
CANDIDATE_SOURCE="$RUN_ROOT/comelit-media.c"
CANDIDATE="$RUN_ROOT/comelit-media-r35-candidate"
CONTAINER_META="$RUN_ROOT/build-meta.txt"
META="$RUN_ROOT/r35-meta-summary.txt"
FAIL=0

fail() {
    echo "$1" >&2
    FAIL=1
}

summary() {
    echo
    echo '=== COMELIT P116 R35 ATTACHED MEDIA CANDIDATE BUILD SUMMARY ==='
    echo "BUILD_ROOT=$RUN_ROOT"
    echo "REPO_HEAD=${REPO_HEAD:-UNKNOWN}"
    echo "CANONICAL_TRANSFORM=$CANONICAL_TRANSFORM_REL"
    echo "R35_TRANSFORM=$R35_TRANSFORM_REL"
    echo "CANONICAL_INCLUDE_P116_SOURCE_SHA256=${CANONICAL_SHA:-NOT_REACHED}"
    echo "CANONICAL_SOURCE_GATE=${CANONICAL_SOURCE_GATE:-NOT_REACHED}"
    echo "R35_GENERATED_SOURCE_SHA256=${CANDIDATE_SOURCE_SHA:-NOT_REACHED}"
    echo "CHROOT_BUILD_RC=${BUILD_RC:-NOT_REACHED}"
    echo "CANDIDATE_SHA256=${CANDIDATE_SHA:-NOT_REACHED}"
    echo "CANDIDATE_BYTES=${CANDIDATE_BYTES:-NOT_REACHED}"
    echo "candidate_executed=false"
    echo "MUSL_INTERPRETER_GATE=${MUSL_INTERPRETER_GATE:-NOT_REACHED}"
    echo "NO_GLIBC_DEPENDENCY=${NO_GLIBC_DEPENDENCY:-NOT_REACHED}"
    echo "NEEDED=${NEEDED:-NOT_REACHED}"
    echo "NO_NEW_RUNTIME_DEPENDENCY=${NO_NEW_RUNTIME_DEPENDENCY:-NOT_REACHED}"
    echo "LIB_IDENTICAL=${LIB_IDENTICAL:-NOT_REACHED}"
    echo "R35_MARKER_GATE=${R35_MARKER_GATE:-NOT_REACHED}"
    echo "PRODUCTION_MARKER_INTEGRITY_GATE=${PRODUCTION_MARKER_GATE:-NOT_REACHED}"
    echo "COMELIT_NETWORK_REQUESTS=0"
    echo "LISTENER_CHANGED=NO"
    echo "HA_CORE_CHANGED=NO"
    echo "DOOR_ACTION_SENT=false"
    echo "GATE_ACTION_SENT=false"
    if [ "$FAIL" -eq 0 ] && [ -n "${CANDIDATE_SHA:-}" ]; then
        echo 'R35_CANDIDATE_BUILD=PASS'
    else
        echo 'R35_CANDIDATE_BUILD=FAIL'
    fi
    echo '=== END COMELIT P116 R35 ATTACHED MEDIA CANDIDATE BUILD SUMMARY ==='
}
trap summary EXIT

if [ "$(id -u)" -eq 0 ]; then
    fail 'R35_BUILD_MUST_RUN_AS_NON_ROOT=true'
    exit 1
fi

for command in git python3 sha256sum awk grep sort paste stat cmp cp install docker readelf strings file; do
    command -v "$command" >/dev/null 2>&1 || fail "R35_BUILD_MISSING_COMMAND=$command"
done
[ "$FAIL" -eq 0 ] || exit 1

[ -e "$REPO/.git" ] || { fail 'R35_BUILD_REPO=ABSENT'; exit 1; }
REPO_HEAD="$(git -C "$REPO" rev-parse HEAD 2>/dev/null || true)"
echo "REPO_HEAD=$REPO_HEAD"

[ -f "$SAFETY_POC/$SOURCE_REL" ] || { fail 'R35_BUILD_SOURCE=ABSENT'; exit 1; }
[ -f "$SAFETY_POC/$CANONICAL_TRANSFORM_REL" ] || { fail 'R35_BUILD_CANONICAL_TRANSFORM=ABSENT'; exit 1; }
[ -f "$SAFETY_POC/$R35_TRANSFORM_REL" ] || { fail 'R35_BUILD_R35_TRANSFORM=ABSENT'; exit 1; }
[ -d "$APK_CLOSURE" ] || { fail 'R35_BUILD_APK_CLOSURE=ABSENT'; exit 1; }

mkdir -p "$RUN_ROOT"
chmod 700 "$RUN_ROOT"

echo '=== CANONICAL --include-p116 SOURCE GATE (unchanged, pinned) ==='
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$SAFETY_POC/research/media/v1" \
python3 "$SAFETY_POC/$CANONICAL_TRANSFORM_REL" \
    --source "$SAFETY_POC/$SOURCE_REL" \
    --output "$GENERATED" \
    --include-p116
[ -s "$GENERATED" ] || { fail 'R35_BUILD_CANONICAL_SOURCE=EMPTY'; exit 1; }
CANONICAL_SHA="$(sha256sum "$GENERATED" | awk '{print $1}')"
echo "CANONICAL_INCLUDE_P116_SOURCE_SHA256=$CANONICAL_SHA"
if [ "$CANONICAL_SHA" = "$EXPECTED_CANONICAL_SOURCE_SHA" ]; then
    CANONICAL_SOURCE_GATE=PASS
else
    CANONICAL_SOURCE_GATE=FAIL
    fail "R35_CANONICAL_SOURCE_GATE=FAIL expected=$EXPECTED_CANONICAL_SOURCE_SHA actual=$CANONICAL_SHA"
fi
[ "$FAIL" -eq 0 ] || exit 1
echo "CANONICAL_SOURCE_GATE=$CANONICAL_SOURCE_GATE"

echo '=== R35 OVERLAY TRANSFORM (separate step, does not touch the canonical chain) ==='
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$SAFETY_POC/research/media/v1" \
python3 "$SAFETY_POC/$R35_TRANSFORM_REL" \
    --source "$GENERATED" \
    --output "$CANDIDATE_SOURCE"
R35_TRANSFORM_RC=$?
echo "R35_TRANSFORM_RC=$R35_TRANSFORM_RC"
[ "$R35_TRANSFORM_RC" -eq 0 ] || { fail 'R35_TRANSFORM=FAIL'; exit 1; }
[ -s "$CANDIDATE_SOURCE" ] || { fail 'R35_GENERATED_SOURCE=EMPTY'; exit 1; }
CANDIDATE_SOURCE_SHA="$(sha256sum "$CANDIDATE_SOURCE" | awk '{print $1}')"
echo "R35_GENERATED_SOURCE_SHA256=$CANDIDATE_SOURCE_SHA"

for marker in \
    'R35_ATTACHED_MEDIA_BEGIN' \
    'R35_ATTACHED_MEDIA_END' \
    'R35_WIRING_BEGIN' \
    'R35_WIRING_END' \
    'r35_capture_call_ctp_id' \
    'r35_send_open' \
    'r35_send_stop' \
    'p80_media_forwarding_enabled = armed' \
    'P80_MEDIA_ACTIVE=true' \
    'P80_VIDEO_RTP_FORWARDING=PASS' \
    'ENTRANCE_SELF_ACTIVATION_SENT=PASS' \
    'P78_SECOND_CTPP_OPEN=false'
do
    grep -Fq "$marker" "$CANDIDATE_SOURCE" || fail "R35_SOURCE_MARKER_GATE=FAIL marker=$marker"
done
[ "$FAIL" -eq 0 ] && R35_MARKER_GATE=PASS || R35_MARKER_GATE=FAIL
[ "$FAIL" -eq 0 ] || exit 1
echo "R35_MARKER_GATE=$R35_MARKER_GATE"

echo '=== ALPINE 3.24.1 OFFLINE MUSL BUILD (docker --network none, local APK closure) ==='
cat > "$RUN_ROOT/build-offline.sh" <<'EOS'
set -eu
apk add --no-network --allow-untrusted /pkgs/*.apk >/dev/null 2>&1 || { echo "APK_OFFLINE_INSTALL=FAIL"; exit 1; }
echo "APK_OFFLINE_INSTALL=PASS"
cc -O2 -g -Wall -Wextra -Wl,--as-needed -o /w/comelit-media-r35-candidate /w/comelit-media.c \
   $(pkg-config --cflags --libs nice glib-2.0 gio-2.0 gobject-2.0)
chmod 755 /w/comelit-media-r35-candidate
INTERPRETER="$(readelf -l /w/comelit-media-r35-candidate | sed -n 's@.*Requesting program interpreter: \(.*\)]@\1@p')"
NEEDED="$(readelf -d /w/comelit-media-r35-candidate | sed -n 's/.*Shared library: \[\(.*\)\]/\1/p' | sort | paste -sd, -)"
BUILDID="$(readelf -n /w/comelit-media-r35-candidate 2>/dev/null | sed -n 's/.*Build ID: \(.*\)/\1/p' | head -1)"
{
  echo "alpine_version=$(cat /etc/alpine-release)"
  echo "cc_version=$(cc --version | head -1)"
  echo "ld_version=$(ld --version | head -1)"
  echo "libnice_version=$(pkg-config --modversion nice)"
  echo "glib_version=$(pkg-config --modversion glib-2.0)"
  echo "gobject_version=$(pkg-config --modversion gobject-2.0)"
  echo "compile_flags=-O2 -g -Wall -Wextra -Wl,--as-needed"
  echo "interpreter=$INTERPRETER"
  echo "needed_sorted=$NEEDED"
  echo "elf_build_id=$BUILDID"
  echo "candidate_executed=false"
} > /w/build-meta.txt
cp /usr/lib/libnice.so.10 /w/container-libnice.so.10 2>/dev/null || true
cp /usr/lib/libglib-2.0.so.0 /w/container-libglib-2.0.so.0 2>/dev/null || true
cp /usr/lib/libgobject-2.0.so.0 /w/container-libgobject-2.0.so.0 2>/dev/null || true
EOS
chmod 755 "$RUN_ROOT/build-offline.sh"

timeout 900 docker run --rm --security-opt apparmor=unconfined --network none \
    -v "$RUN_ROOT":/w -v "$APK_CLOSURE":/pkgs:ro "$ALPINE_IMAGE" /bin/sh /w/build-offline.sh
BUILD_RC=$?
echo "CHROOT_BUILD_RC=$BUILD_RC"
if [ "$BUILD_RC" -ne 0 ] || [ ! -s "$CANDIDATE" ]; then
    fail 'R35_CANDIDATE_COMPILE=FAIL'
    exit 1
fi
CANDIDATE_SHA="$(sha256sum "$CANDIDATE" | awk '{print $1}')"
CANDIDATE_BYTES="$(stat -c '%s' "$CANDIDATE")"
{
    echo "R35_TRANSFORM=$R35_TRANSFORM_REL"
    echo "CANONICAL_INCLUDE_P116_SOURCE_SHA256=$CANONICAL_SHA"
    echo "R35_GENERATED_SOURCE_SHA256=$CANDIDATE_SOURCE_SHA"
    echo "CANDIDATE_SHA256=$CANDIDATE_SHA"
    echo "CANDIDATE_BYTES=$CANDIDATE_BYTES"
    cat "$CONTAINER_META" 2>/dev/null || true
} > "$META"
cat "$META"

echo '=== DEPENDENCY / ABI GATES ==='
INTERPRETER="$(sed -n 's/^interpreter=//p' "$CONTAINER_META")"
NEEDED="$(sed -n 's/^needed_sorted=//p' "$CONTAINER_META")"
[ "$INTERPRETER" = "$EXPECTED_INTERPRETER" ] && MUSL_INTERPRETER_GATE=PASS || MUSL_INTERPRETER_GATE=FAIL
[ "$MUSL_INTERPRETER_GATE" = PASS ] || fail "R35_INTERPRETER_GATE=FAIL actual=$INTERPRETER"
[ "$NEEDED" = "$EXPECTED_NEEDED" ] && NO_NEW_RUNTIME_DEPENDENCY=PASS || NO_NEW_RUNTIME_DEPENDENCY=FAIL
[ "$NO_NEW_RUNTIME_DEPENDENCY" = PASS ] || fail "R35_NEEDED_GATE=FAIL actual=$NEEDED"
case ",$NEEDED," in
    *,libc.so.6,*) NO_GLIBC_DEPENDENCY=FAIL ;;
    *) NO_GLIBC_DEPENDENCY=PASS ;;
esac
[ "$NO_GLIBC_DEPENDENCY" = PASS ] || fail 'R35_GLIBC_DEPENDENCY=FAIL'
echo "MUSL_INTERPRETER_GATE=$MUSL_INTERPRETER_GATE ($INTERPRETER)"
echo "NO_GLIBC_DEPENDENCY=$NO_GLIBC_DEPENDENCY"
echo "NO_NEW_RUNTIME_DEPENDENCY=$NO_NEW_RUNTIME_DEPENDENCY ($NEEDED)"

echo '=== NO NEW NON-libc RUNTIME DEPENDENCY vs PACKAGED custom_components/comelit/native/lib ==='
MISSING=0
for so in $(echo "$NEEDED" | tr ',' ' '); do
    case "$so" in
        libc.musl-x86_64.so.1) continue ;;
    esac
    if [ ! -e "$SAFETY_POC/../custom_components/comelit/native/lib/$so" ]; then
        echo "R35_NEW_RUNTIME_DEP=$so"
        MISSING=1
    fi
done
[ "$MISSING" -eq 0 ] || { NO_NEW_RUNTIME_DEPENDENCY=FAIL; fail 'R35_PACKAGED_LIB_PRESENCE_GATE=FAIL'; }

echo '=== LIB_IDENTICAL (container libs vs packaged custom_components/comelit/native/lib) ==='
LIB_IDENTICAL=PASS
for needed in libglib-2.0.so.0 libgobject-2.0.so.0 libnice.so.10; do
    packaged="$SAFETY_POC/../custom_components/comelit/native/lib/$needed"
    container="$RUN_ROOT/container-$needed"
    if [ ! -f "$packaged" ]; then
        LIB_IDENTICAL=FAIL
        fail "R35_LIB_IDENTICAL=FAIL lib=$needed reason=packaged_absent"
    elif [ ! -f "$container" ]; then
        LIB_IDENTICAL=FAIL
        fail "R35_LIB_IDENTICAL=FAIL lib=$needed reason=container_copy_absent"
    elif ! cmp -s "$packaged" "$container"; then
        LIB_IDENTICAL=FAIL
        fail "R35_LIB_IDENTICAL=FAIL lib=$needed reason=content_mismatch"
    fi
done
echo "LIB_IDENTICAL=$LIB_IDENTICAL"
[ "$FAIL" -eq 0 ] || exit 1

echo '=== CANDIDATE STRINGS / MARKER GATES (strings only, no execution) ==='
strings -a "$CANDIDATE" > "$RUN_ROOT/candidate.strings"
for marker in \
    'R35_CALL_CTP_CAPTURED=' \
    'R35_%s_QUEUED=%s' \
    'MEDIA_OPEN' \
    'MEDIA_STOP' \
    'R35_RTP_ARMED=' \
    'P80_MEDIA_ACTIVE=true' \
    'P80_VIDEO_RTP_FORWARDING=PASS' \
    'P80_AUDIO_RTP_FORWARDING=PASS' \
    'ENTRANCE_SELF_ACTIVATION_SENT=PASS' \
    'P78_SECOND_CTPP_OPEN=false' \
    'ENTRANCE_SIGNALING_DOOR_ACTION_SENT=false'
do
    grep -Fq "$marker" "$RUN_ROOT/candidate.strings" || fail "R35_CANDIDATE_MARKER_GATE=FAIL marker=$marker"
done
[ "$FAIL" -eq 0 ] && PRODUCTION_MARKER_GATE=PASS || PRODUCTION_MARKER_GATE=FAIL
echo "R35_CANDIDATE_MARKER_GATE=$PRODUCTION_MARKER_GATE"
if grep -Fq '/lib64/ld-linux-x86-64.so.2' "$RUN_ROOT/candidate.strings"; then
    fail 'R35_CANDIDATE_GLIBC_INTERPRETER_LEAK=FAIL'
fi
[ "$FAIL" -eq 0 ] || exit 1

echo "CANDIDATE_SHA256=$CANDIDATE_SHA"
echo "CANDIDATE_BYTES=$CANDIDATE_BYTES"
echo 'candidate_executed=false'
