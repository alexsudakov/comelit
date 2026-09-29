#!/usr/bin/env bash
# Promote one reproducibly-built P116/R66 musl candidate into the integration
# tree and write public-safe provenance metadata.
#
# This script performs NO network IO, NO HA deploy, NO listener action and NO
# Git commit/push. It only verifies local build artifacts, copies the candidate,
# and writes P116_R66_BUILD_INFO.txt.
set -Eeuo pipefail
umask 077

REPO=${REPO:-/home/hermes/repos/comelit}
CANDIDATE=${CANDIDATE:-}
REPRODUCIBLE_PEER=${REPRODUCIBLE_PEER:-}
R66_SOURCE=${R66_SOURCE:-}
EXPECTED_SHA256=${EXPECTED_SHA256:-}
EXPECTED_SOURCE_SHA256=${EXPECTED_SOURCE_SHA256:-}
PINNED_R66_SOURCE_SHA=de3fbb7d324b04b0f06dad2fb2c6e50de0a8866050b67cce4df00dbe878c9611
PINNED_R66_BINARY_SHA=f35c2f67d50f1b825888e88de80d678b86fd208e20bd719734bec905867b5499

TARGET="$REPO/custom_components/comelit/native/comelit-v4"
BUILD_INFO="$REPO/safety-poc/research/media/v1/P116_R66_BUILD_INFO.txt"
EXPECTED_INTERPRETER=/lib/ld-musl-x86_64.so.1
EXPECTED_NEEDED=libc.musl-x86_64.so.1,libglib-2.0.so.0,libgobject-2.0.so.0,libnice.so.10

fail() {
    echo "R66_PROMOTION=FAIL"
    echo "REASON=$1"
    exit 1
}

[[ "$(id -u)" -ne 0 ]] || fail "ROOT_NOT_ALLOWED"
[[ -n "$CANDIDATE" ]] || fail "CANDIDATE_NOT_SET"
[[ -n "$REPRODUCIBLE_PEER" ]] || fail "REPRODUCIBLE_PEER_NOT_SET"
[[ -n "$R66_SOURCE" ]] || fail "R66_SOURCE_NOT_SET"
[[ -n "$EXPECTED_SHA256" ]] || fail "EXPECTED_SHA256_NOT_SET"
[[ -n "$EXPECTED_SOURCE_SHA256" ]] || fail "EXPECTED_SOURCE_SHA256_NOT_SET"
[[ "$EXPECTED_SHA256" =~ ^[0-9a-f]{64}$ ]] || fail "EXPECTED_SHA256_SHAPE"
[[ "$EXPECTED_SOURCE_SHA256" =~ ^[0-9a-f]{64}$ ]] || fail "EXPECTED_SOURCE_SHA256_SHAPE"
[[ -f "$CANDIDATE" ]] || fail "CANDIDATE_MISSING"
[[ -f "$REPRODUCIBLE_PEER" ]] || fail "REPRODUCIBLE_PEER_MISSING"
[[ -f "$R66_SOURCE" ]] || fail "R66_SOURCE_MISSING"
[[ -d "$REPO/.git" || -f "$REPO/.git" ]] || fail "REPO_MISSING"

for c in git sha256sum readelf strings install stat cmp grep awk sort paste mktemp cp mv rm; do
    command -v "$c" >/dev/null || fail "COMMAND_MISSING_$c"
done

REPO_HEAD="$(git -C "$REPO" rev-parse HEAD)"
ACTUAL_SOURCE_SHA256="$(sha256sum "$R66_SOURCE" | awk '{print $1}')"
ACTUAL_SHA256="$(sha256sum "$CANDIDATE" | awk '{print $1}')"
PEER_SHA256="$(sha256sum "$REPRODUCIBLE_PEER" | awk '{print $1}')"

[[ "$EXPECTED_SOURCE_SHA256" == "$PINNED_R66_SOURCE_SHA" ]] \
    || fail "EXPECTED_SOURCE_SHA_NOT_PINNED"
[[ "$EXPECTED_SHA256" == "$PINNED_R66_BINARY_SHA" ]] \
    || fail "EXPECTED_BINARY_SHA_NOT_PINNED"
[[ "$ACTUAL_SOURCE_SHA256" == "$PINNED_R66_SOURCE_SHA" ]] \
    || fail "SOURCE_SHA_MISMATCH"
[[ "$ACTUAL_SHA256" == "$PINNED_R66_BINARY_SHA" ]] \
    || fail "CANDIDATE_SHA_MISMATCH"
[[ "$PEER_SHA256" == "$PINNED_R66_BINARY_SHA" ]] \
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
TARGET_STAGE="$(mktemp "${TARGET}.r66-stage.XXXXXX")"
INFO_STAGE="$(mktemp "${BUILD_INFO}.r66-stage.XXXXXX")"
TARGET_BACKUP="$(mktemp)"
INFO_BACKUP="$(mktemp)"
HAD_TARGET=false
HAD_BUILD_INFO=false
trap 'rm -f "$STRINGS_TMP" "$INFO_TMP" "$TARGET_STAGE" "$INFO_STAGE" "$TARGET_BACKUP" "$INFO_BACKUP"' EXIT

strings -a "$CANDIDATE" > "$STRINGS_TMP"
for marker in \
    'R42_LISTENER_DOOR_SIGNAL_PRESERVED=true' \
    'R42_MEDIAREQ26_OPEN_PROFILE=CAPTURE_VALIDATED' \
    'R54_CALL_ADOPTION_STARTED=%s' \
    'R64_POST_CALL_SNAPSHOT=true' \
    'R64_TERMINAL_SNAPSHOT=true' \
    'V4_DOOR_PATH=CALL_TIME_SINGLE' \
    'V4_CALL_TIME_DOOR_COMMAND_ACCEPTED=true' \
    'V4_CALL_TIME_DOOR_QUEUED=true' \
    'V4_CALL_TIME_DOOR_SENT=true' \
    'V4_CALL_TIME_DOOR_WRITE_COUNT=1' \
    'CALL_SEQUENCE_BEFORE=%u' \
    'CALL_SEQUENCE_AFTER=%u' \
    'CALL_TIME_DOOR_ACK_OBSERVED=%s' \
    'CALL_TIME_DOOR_STALE_GENERATION=true' \
    'CALL_TIME_DOOR_SEQUENCE_COMMITTED=%s' \
    'P12_TX_CALL_TIME_DOOR'
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
    cp -p "$TARGET" "$TARGET_BACKUP"
    HAD_TARGET=true
fi
if [[ -f "$BUILD_INFO" ]]; then
    cp -p "$BUILD_INFO" "$INFO_BACKUP"
    HAD_BUILD_INFO=true
fi

install -m 0755 "$CANDIDATE" "$TARGET_STAGE"
STAGED_SHA256="$(sha256sum "$TARGET_STAGE" | awk '{print $1}')"
[[ "$STAGED_SHA256" == "$EXPECTED_SHA256" ]] \
    || fail "STAGED_SHA_MISMATCH"

PROMOTED_BYTES="$(stat -c '%s' "$TARGET_STAGE")"

cat > "$INFO_TMP" <<EOF
phase=P116_R66_CALL_TIME_DOOR_SINGLE_MESSAGE
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
standalone_door_bytes_unchanged=true
gate_semantics_changed=false
second_ctpp_open=false
automatic_retry_added=false
physical_effect_asserted=false
candidate_executed=false
production_deploy_performed=false
EOF

install -m 0644 "$INFO_TMP" "$INFO_STAGE"

rollback_pair() {
    if [[ "$HAD_TARGET" == true ]]; then
        cp -p "$TARGET_BACKUP" "$TARGET" || true
    else
        rm -f "$TARGET"
    fi
    if [[ "$HAD_BUILD_INFO" == true ]]; then
        cp -p "$INFO_BACKUP" "$BUILD_INFO" || true
    else
        rm -f "$BUILD_INFO"
    fi
}

if ! mv -f "$TARGET_STAGE" "$TARGET"; then
    fail "TARGET_INSTALL_FAILED"
fi
if ! mv -f "$INFO_STAGE" "$BUILD_INFO"; then
    rollback_pair
    fail "BUILD_INFO_INSTALL_FAILED_ROLLED_BACK"
fi

PROMOTED_SHA256="$(sha256sum "$TARGET" | awk '{print $1}')"
[[ "$PROMOTED_SHA256" == "$EXPECTED_SHA256" ]] \
    || { rollback_pair; fail "PROMOTED_SHA_MISMATCH_ROLLED_BACK"; }

echo '=== COMELIT P116 R66 LISTENER BINARY PROMOTION ==='
echo "REPO_HEAD=$REPO_HEAD"
echo "TARGET=custom_components/comelit/native/comelit-v4"
echo "BUILD_INFO=safety-poc/research/media/v1/P116_R66_BUILD_INFO.txt"
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
echo 'R66_PROMOTION=PASS'
