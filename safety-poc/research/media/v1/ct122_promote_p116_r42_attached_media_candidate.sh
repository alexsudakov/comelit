#!/usr/bin/env bash
# Promote one already-built P116/R42 musl candidate into the integration tree.
# This script performs NO network IO, NO HA deploy, NO listener action and NO
# Git commit/push. It only verifies and copies a caller-specified local file.
set -Eeuo pipefail
umask 077

REPO=${REPO:-/home/hermes/repos/comelit}
CANDIDATE=${CANDIDATE:-}
EXPECTED_SHA256=${EXPECTED_SHA256:-}
TARGET="$REPO/custom_components/comelit/native/comelit-v4"
EXPECTED_INTERPRETER=/lib/ld-musl-x86_64.so.1
EXPECTED_NEEDED=libc.musl-x86_64.so.1,libglib-2.0.so.0,libgobject-2.0.so.0,libnice.so.10

fail() {
    echo "R42_PROMOTION=FAIL"
    echo "REASON=$1"
    exit 1
}

[[ "$(id -u)" -ne 0 ]] || fail "ROOT_NOT_ALLOWED"
[[ -n "$CANDIDATE" ]] || fail "CANDIDATE_NOT_SET"
[[ -n "$EXPECTED_SHA256" ]] || fail "EXPECTED_SHA256_NOT_SET"
[[ "$EXPECTED_SHA256" =~ ^[0-9a-f]{64}$ ]] || fail "EXPECTED_SHA256_SHAPE"
[[ -f "$CANDIDATE" ]] || fail "CANDIDATE_MISSING"
[[ -d "$REPO/.git" || -f "$REPO/.git" ]] || fail "REPO_MISSING"

for c in git sha256sum readelf strings install stat; do
    command -v "$c" >/dev/null || fail "COMMAND_MISSING_$c"
done

ACTUAL_SHA256="$(sha256sum "$CANDIDATE" | awk '{print $1}')"
[[ "$ACTUAL_SHA256" == "$EXPECTED_SHA256" ]] || fail "CANDIDATE_SHA_MISMATCH"

INTERPRETER="$(
    readelf -l "$CANDIDATE" |
      sed -n 's@.*Requesting program interpreter: \(.*\)]@\1@p'
)"
NEEDED="$(
    readelf -d "$CANDIDATE" |
      sed -n 's/.*Shared library: \[\(.*\)\]/\1/p' |
      sort |
      paste -sd, -
)"
[[ "$INTERPRETER" == "$EXPECTED_INTERPRETER" ]] || fail "INTERPRETER_MISMATCH"
[[ "$NEEDED" == "$EXPECTED_NEEDED" ]] || fail "NEEDED_MISMATCH"
[[ ",$NEEDED," != *",libc.so.6,"* ]] || fail "GLIBC_DEPENDENCY"

STRINGS_TMP="$(mktemp)"
trap 'rm -f "$STRINGS_TMP"' EXIT
strings -a "$CANDIDATE" > "$STRINGS_TMP"
for marker in   'R42_MEDIA_CHANNEL_ALLOCATED=true'   'R42_MEDIAREQ26_OPEN_PROFILE=CAPTURE_VALIDATED'   'R42_ATTACHED_MEDIA_ACTIVE=true'   'R42_ATTACHED_MEDIA_STOP_SENT=true'   'R42_MEDIA_CHANNEL_CLOSE_SENT=true'   'R42_MEDIA_CHANNEL_CLOSED=true'   'R42_AUTOMATIC_RETRY=false'   'P80_VIDEO_RTP_FORWARDING=PASS'   'ENTRANCE_SIGNALING_DOOR_ACTION_SENT=false'
do
    grep -Fq "$marker" "$STRINGS_TMP" || fail "MARKER_MISSING"
done

if strings -a "$CANDIDATE" | grep -Eq '0x0[Cc]4[Aa]|0x4[Aa]5[Aa]|0x[Cc][Aa]5[Aa]'; then
    fail "CAPTURE_LITERAL_PRESENT"
fi

OLD_SHA256=NONE
if [[ -f "$TARGET" ]]; then
    OLD_SHA256="$(sha256sum "$TARGET" | awk '{print $1}')"
fi

install -m 0755 "$CANDIDATE" "$TARGET"
PROMOTED_SHA256="$(sha256sum "$TARGET" | awk '{print $1}')"
[[ "$PROMOTED_SHA256" == "$EXPECTED_SHA256" ]] || fail "PROMOTED_SHA_MISMATCH"

echo '=== COMELIT P116 R42 LOCAL BINARY PROMOTION ==='
echo "REPO_HEAD=$(git -C "$REPO" rev-parse HEAD)"
echo "TARGET=custom_components/comelit/native/comelit-v4"
echo "OLD_SHA256=$OLD_SHA256"
echo "PROMOTED_SHA256=$PROMOTED_SHA256"
echo "PROMOTED_BYTES=$(stat -c '%s' "$TARGET")"
echo "INTERPRETER=$INTERPRETER"
echo "NEEDED=$NEEDED"
echo 'CANDIDATE_EXECUTED=false'
echo 'NETWORK_IO_PERFORMED=false'
echo 'HA_DEPLOY_PERFORMED=false'
echo 'LISTENER_CHANGED=NO'
echo 'DOOR_ACTION_SENT=false'
echo 'GATE_ACTION_SENT=false'
echo 'GIT_COMMIT_PERFORMED=false'
echo 'GIT_PUSH_PERFORMED=false'
echo 'R42_PROMOTION=PASS'
