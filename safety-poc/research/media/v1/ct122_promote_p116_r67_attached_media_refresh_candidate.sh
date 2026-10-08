#!/usr/bin/env bash
# Promote one reproducibly-built P116/R67 musl candidate into the integration
# tree and write public-safe provenance metadata.
#
# This script performs NO network IO, NO HA deploy, NO listener action and NO
# Git commit/push.  The orchestrator must fill PINNED_R67_BINARY_SHA after it
# has measured the reproducible Docker build output.
set -Eeuo pipefail
umask 077

REPO=${REPO:-/home/hermes/repos/comelit}
CANDIDATE=${CANDIDATE:-}
REPRODUCIBLE_PEER=${REPRODUCIBLE_PEER:-}
R67_SOURCE=${R67_SOURCE:-}
EXPECTED_SHA256=${EXPECTED_SHA256:-}
EXPECTED_SOURCE_SHA256=${EXPECTED_SOURCE_SHA256:-}
PINNED_R67_SOURCE_SHA=f996c073a3ad49619e801d16d1f95aa20c818af388fe8c00dd8c7974f467a4de
PINNED_R67_BINARY_SHA=eabda869783f9b1efb578e3801b0b0e50c70fd52932960ba22c95003e28fbacb

TARGET="$REPO/custom_components/comelit/native/comelit-v4"
BUILD_INFO="$REPO/safety-poc/research/media/v1/P116_R67_BUILD_INFO.txt"
EXPECTED_INTERPRETER=/lib/ld-musl-x86_64.so.1
EXPECTED_NEEDED=libc.musl-x86_64.so.1,libglib-2.0.so.0,libgobject-2.0.so.0,libnice.so.10

fail() {
    echo "R67_PROMOTION=FAIL"
    echo "REASON=$1"
    exit 1
}

[[ "$PINNED_R67_BINARY_SHA" != "ORCHESTRATOR_FILL" ]] || fail "ORCHESTRATOR_FILL_BINARY_SHA"
[[ "$(id -u)" -ne 0 ]] || fail "ROOT_NOT_ALLOWED"
[[ -n "$CANDIDATE" ]] || fail "CANDIDATE_NOT_SET"
[[ -n "$REPRODUCIBLE_PEER" ]] || fail "REPRODUCIBLE_PEER_NOT_SET"
[[ -n "$R67_SOURCE" ]] || fail "R67_SOURCE_NOT_SET"
[[ -n "$EXPECTED_SHA256" ]] || fail "EXPECTED_SHA256_NOT_SET"
[[ -n "$EXPECTED_SOURCE_SHA256" ]] || fail "EXPECTED_SOURCE_SHA256_NOT_SET"
[[ "$EXPECTED_SHA256" =~ ^[0-9a-f]{64}$ ]] || fail "EXPECTED_SHA256_SHAPE"
[[ "$EXPECTED_SOURCE_SHA256" =~ ^[0-9a-f]{64}$ ]] || fail "EXPECTED_SOURCE_SHA256_SHAPE"
[[ -f "$CANDIDATE" ]] || fail "CANDIDATE_MISSING"
[[ -f "$REPRODUCIBLE_PEER" ]] || fail "REPRODUCIBLE_PEER_MISSING"
[[ -f "$R67_SOURCE" ]] || fail "R67_SOURCE_MISSING"
[[ -d "$REPO/.git" || -f "$REPO/.git" ]] || fail "REPO_MISSING"

for c in git sha256sum readelf strings install stat cmp grep awk sort paste; do
    command -v "$c" >/dev/null || fail "COMMAND_MISSING_$c"
done

REPO_HEAD="$(git -C "$REPO" rev-parse HEAD)"
ACTUAL_SOURCE_SHA256="$(sha256sum "$R67_SOURCE" | awk '{print $1}')"
ACTUAL_SHA256="$(sha256sum "$CANDIDATE" | awk '{print $1}')"
PEER_SHA256="$(sha256sum "$REPRODUCIBLE_PEER" | awk '{print $1}')"

[[ "$EXPECTED_SOURCE_SHA256" == "$PINNED_R67_SOURCE_SHA" ]] \
    || fail "EXPECTED_SOURCE_SHA_NOT_PINNED"
[[ "$EXPECTED_SHA256" == "$PINNED_R67_BINARY_SHA" ]] \
    || fail "EXPECTED_BINARY_SHA_NOT_PINNED"
[[ "$ACTUAL_SOURCE_SHA256" == "$PINNED_R67_SOURCE_SHA" ]] \
    || fail "SOURCE_SHA_MISMATCH"
[[ "$ACTUAL_SHA256" == "$PINNED_R67_BINARY_SHA" ]] \
    || fail "CANDIDATE_SHA_MISMATCH"
[[ "$PEER_SHA256" == "$PINNED_R67_BINARY_SHA" ]] \
    || fail "REPRODUCIBLE_PEER_SHA_MISMATCH"
cmp -s "$CANDIDATE" "$REPRODUCIBLE_PEER" \
    || fail "REPRODUCIBLE_PEER_CMP_MISMATCH"

INTERPRETER="$(
    readelf -l "$CANDIDATE" \
      | sed -n 's@.*Requesting program interpreter: \(.*\)]@\1@p'
)"
NEEDED="$(
    readelf -d "$CANDIDATE" \
      | sed -n 's/.*Shared library: \[\(.*\)\]/\1/p' \
      | sort \
      | paste -sd, -
)"

[[ "$INTERPRETER" == "$EXPECTED_INTERPRETER" ]] \
    || fail "INTERPRETER_MISMATCH"
[[ "$NEEDED" == "$EXPECTED_NEEDED" ]] \
    || fail "NEEDED_MISMATCH"
[[ ",$NEEDED," != *",libc.so.6,"* ]] \
    || fail "GLIBC_DEPENDENCY"

STRINGS_TMP="$(mktemp)"
INFO_TMP="$(mktemp)"
trap 'rm -f "$STRINGS_TMP" "$INFO_TMP"' EXIT

strings -a "$CANDIDATE" > "$STRINGS_TMP"
for marker in \
    'R67_ATTACHED_REFRESH_CADENCE_SECONDS=%u' \
    'R67_ATTACHED_REFRESH_QUEUED_COUNT=%u' \
    'R67_ATTACHED_REFRESH_SENT_COUNT=%u' \
    'R67_ATTACHED_REFRESH_FIRST_AGE_SECONDS=%u' \
    'R67_ATTACHED_REFRESH_LAST_AGE_SECONDS=%u' \
    'R67_ATTACHED_REFRESH_LAST_RESULT=%s' \
    'R67_ATTACHED_REFRESH_LAST_ERROR=%s' \
    'R67_ATTACHED_REFRESH_SESSION_RESET=true' \
    'R67_ATTACHED_REFRESH_SESSION_RESET_REASON=%s' \
    'R67_ATTACHED_REFRESH_TIMER_SOURCE_ID=%u' \
    'R67_ATTACHED_REFRESH_TIMER_REMOVED=true' \
    'R67_ATTACHED_REFRESH_TIMER_REMOVE_REASON=%s' \
    'R67_ATTACHED_REFRESH_CANCELLED_COMPLETION_IGNORED=true' \
    'R67_ATTACHED_REFRESH_STALE_TIMER_IGNORED=true' \
    'R67_ATTACHED_REFRESH_CHANNEL_GENERATION=%u' \
    'R67_ATTACHED_REFRESH_OPCODE=0x0011' \
    'R67_ATTACHED_REFRESH_FRAME=MEDIAREQ26_OPEN' \
    'V4_DOOR_PATH=CALL_TIME_SINGLE'
do
    grep -Fq "$marker" "$STRINGS_TMP" || fail "MARKER_MISSING"
done

for forbidden in \
    '/run/comelit-media' \
    'signal(SIGUSR1, SIG_IGN);' \
    'entrance_self_activation' \
    'P12_TX_ENTRANCE_SELF_ACTIVATION'
do
    if grep -Fq "$forbidden" "$STRINGS_TMP"; then
        fail "FORBIDDEN_MARKER_PRESENT"
    fi
done

OLD_SHA256=NONE
if [[ -f "$TARGET" ]]; then
    OLD_SHA256="$(sha256sum "$TARGET" | awk '{print $1}')"
fi

install -m 0755 "$CANDIDATE" "$TARGET"
PROMOTED_SHA256="$(sha256sum "$TARGET" | awk '{print $1}')"
[[ "$PROMOTED_SHA256" == "$EXPECTED_SHA256" ]] \
    || fail "PROMOTED_SHA_MISMATCH"
PROMOTED_BYTES="$(stat -c '%s' "$TARGET")"

cat > "$INFO_TMP" <<EOF
phase=P116_R67_ATTACHED_MEDIA_REFRESH
repo_head_at_promotion=$REPO_HEAD
source_sha256=$ACTUAL_SOURCE_SHA256
native_binary_sha256=$PROMOTED_SHA256
native_binary_size=$PROMOTED_BYTES
native_binary_mode=755
interpreter=$INTERPRETER
needed=$NEEDED
reproducible_binary_cmp_gate=PASS
musl_interpreter_gate=PASS
no_glibc_dependency=PASS
no_new_runtime_dependency=PASS
attached_refresh_opcode=0x0011
attached_refresh_frame=MEDIAREQ26_OPEN
attached_refresh_cadence_seconds=15
second_p2p_start=false
second_ice=false
second_pseudotcp=false
second_ctpp=false
second_rtpc=false
candidate_executed=false
production_deploy_performed=false
EOF

install -m 0644 "$INFO_TMP" "$BUILD_INFO"

echo '=== COMELIT P116 R67 LISTENER BINARY PROMOTION ==='
echo "REPO_HEAD=$REPO_HEAD"
echo "TARGET=custom_components/comelit/native/comelit-v4"
echo "BUILD_INFO=safety-poc/research/media/v1/P116_R67_BUILD_INFO.txt"
echo "SOURCE_SHA256=$ACTUAL_SOURCE_SHA256"
echo "OLD_SHA256=$OLD_SHA256"
echo "PROMOTED_SHA256=$PROMOTED_SHA256"
echo "PROMOTED_BYTES=$PROMOTED_BYTES"
echo "INTERPRETER=$INTERPRETER"
echo "NEEDED=$NEEDED"
echo 'REPRODUCIBLE_BINARY_CMP_GATE=PASS'
echo 'MUSL_INTERPRETER_GATE=PASS'
echo 'NO_GLIBC_DEPENDENCY=PASS'
echo 'NO_NEW_RUNTIME_DEPENDENCY=PASS'
echo 'CANDIDATE_EXECUTED=false'
echo 'NETWORK_IO_PERFORMED=false'
echo 'HA_DEPLOY_PERFORMED=false'
echo 'DOOR_ACTION_SENT=false'
echo 'GATE_ACTION_SENT=false'
echo 'GIT_COMMIT_PERFORMED=false'
echo 'GIT_PUSH_PERFORMED=false'
echo 'R67_PROMOTION=PASS'
