#!/usr/bin/env bash
# Promote one reproducibly-built P116/R42 musl candidate into the integration
# tree and write public-safe provenance metadata.
#
# This script performs NO network IO, NO HA deploy, NO listener action and NO
# Git commit/push. It only verifies local build artifacts, copies the candidate,
# and writes P116_R42_BUILD_INFO.txt.
set -Eeuo pipefail
umask 077

REPO=${REPO:-/home/hermes/repos/comelit}
CANDIDATE=${CANDIDATE:-}
REPRODUCIBLE_PEER=${REPRODUCIBLE_PEER:-}
R42_SOURCE=${R42_SOURCE:-}
EXPECTED_SHA256=${EXPECTED_SHA256:-}
EXPECTED_SOURCE_SHA256=${EXPECTED_SOURCE_SHA256:-}

TARGET="$REPO/custom_components/comelit/native/comelit-v4"
BUILD_INFO="$REPO/safety-poc/research/media/v1/P116_R42_BUILD_INFO.txt"
EXPECTED_INTERPRETER=/lib/ld-musl-x86_64.so.1
EXPECTED_NEEDED=libc.musl-x86_64.so.1,libglib-2.0.so.0,libgobject-2.0.so.0,libnice.so.10

fail() {
    echo "R42_PROMOTION=FAIL"
    echo "REASON=$1"
    exit 1
}

[[ "$(id -u)" -ne 0 ]] || fail "ROOT_NOT_ALLOWED"
[[ -n "$CANDIDATE" ]] || fail "CANDIDATE_NOT_SET"
[[ -n "$REPRODUCIBLE_PEER" ]] || fail "REPRODUCIBLE_PEER_NOT_SET"
[[ -n "$R42_SOURCE" ]] || fail "R42_SOURCE_NOT_SET"
[[ -n "$EXPECTED_SHA256" ]] || fail "EXPECTED_SHA256_NOT_SET"
[[ -n "$EXPECTED_SOURCE_SHA256" ]] || fail "EXPECTED_SOURCE_SHA256_NOT_SET"
[[ "$EXPECTED_SHA256" =~ ^[0-9a-f]{64}$ ]] || fail "EXPECTED_SHA256_SHAPE"
[[ "$EXPECTED_SOURCE_SHA256" =~ ^[0-9a-f]{64}$ ]] || fail "EXPECTED_SOURCE_SHA256_SHAPE"
[[ -f "$CANDIDATE" ]] || fail "CANDIDATE_MISSING"
[[ -f "$REPRODUCIBLE_PEER" ]] || fail "REPRODUCIBLE_PEER_MISSING"
[[ -f "$R42_SOURCE" ]] || fail "R42_SOURCE_MISSING"
[[ -d "$REPO/.git" || -f "$REPO/.git" ]] || fail "REPO_MISSING"

for c in git sha256sum readelf strings install stat cmp grep awk sort paste; do
    command -v "$c" >/dev/null || fail "COMMAND_MISSING_$c"
done

REPO_HEAD="$(git -C "$REPO" rev-parse HEAD)"
ACTUAL_SOURCE_SHA256="$(sha256sum "$R42_SOURCE" | awk '{print $1}')"
ACTUAL_SHA256="$(sha256sum "$CANDIDATE" | awk '{print $1}')"
PEER_SHA256="$(sha256sum "$REPRODUCIBLE_PEER" | awk '{print $1}')"

[[ "$ACTUAL_SOURCE_SHA256" == "$EXPECTED_SOURCE_SHA256" ]]     || fail "SOURCE_SHA_MISMATCH"
[[ "$ACTUAL_SHA256" == "$EXPECTED_SHA256" ]]     || fail "CANDIDATE_SHA_MISMATCH"
[[ "$PEER_SHA256" == "$EXPECTED_SHA256" ]]     || fail "REPRODUCIBLE_PEER_SHA_MISMATCH"
cmp -s "$CANDIDATE" "$REPRODUCIBLE_PEER"     || fail "REPRODUCIBLE_PEER_CMP_MISMATCH"

INTERPRETER="$(
    readelf -l "$CANDIDATE"       | sed -n 's@.*Requesting program interpreter: \(.*\)]@\1@p'
)"
NEEDED="$(
    readelf -d "$CANDIDATE"       | sed -n 's/.*Shared library: \[\(.*\)\]/\1/p'       | sort       | paste -sd, -
)"

[[ "$INTERPRETER" == "$EXPECTED_INTERPRETER" ]]     || fail "INTERPRETER_MISMATCH"
[[ "$NEEDED" == "$EXPECTED_NEEDED" ]]     || fail "NEEDED_MISMATCH"
[[ ",$NEEDED," != *",libc.so.6,"* ]]     || fail "GLIBC_DEPENDENCY"

STRINGS_TMP="$(mktemp)"
INFO_TMP="$(mktemp)"
trap 'rm -f "$STRINGS_TMP" "$INFO_TMP"' EXIT

strings -a "$CANDIDATE" > "$STRINGS_TMP"
for marker in     'V4_DOOR_EXISTING_CTPP_REUSED=true'     'V4_DOOR_OPERATION_WRITES_SENT=5'     'V4_DOOR_AUTOMATIC_RETRY_ALLOWED=false'     'V4_DOOR_PHYSICAL_EFFECT_ASSERTED=false'     'V4_RING_LISTENER_READY=true'     'R42_LISTENER_DOOR_SIGNAL_PRESERVED=true'     'R42_LISTENER_RTP_LIFETIME_RESET=true'     'R42_MEDIA_CHANNEL_ALLOCATED=true'     'R42_MEDIAREQ26_OPEN_PROFILE=CAPTURE_VALIDATED'     'R42_ATTACHED_MEDIA_ACTIVE=true'     'R42_ATTACHED_MEDIA_STOP_SENT=true'     'R42_MEDIA_CHANNEL_CLOSE_SENT=true'     'R42_MEDIA_CHANNEL_CLOSED=true'     'R42_AUTOMATIC_RETRY=false'     'P80_VIDEO_RTP_FORWARDING=PASS'
do
    grep -Fq "$marker" "$STRINGS_TMP" || fail "MARKER_MISSING"
done

if strings -a "$CANDIDATE"     | grep -Eq '0x0[Cc]4[Aa]|0x4[Aa]5[Aa]|0x[Cc][Aa]5[Aa]'
then
    fail "CAPTURE_LITERAL_PRESENT"
fi

OLD_SHA256=NONE
if [[ -f "$TARGET" ]]; then
    OLD_SHA256="$(sha256sum "$TARGET" | awk '{print $1}')"
fi

install -m 0755 "$CANDIDATE" "$TARGET"
PROMOTED_SHA256="$(sha256sum "$TARGET" | awk '{print $1}')"
[[ "$PROMOTED_SHA256" == "$EXPECTED_SHA256" ]]     || fail "PROMOTED_SHA_MISMATCH"

PROMOTED_BYTES="$(stat -c '%s' "$TARGET")"

cat > "$INFO_TMP" <<EOF
phase=P116_R42B_LISTENER_ATTACHED_INBOUND_MEDIA
repo_head_at_promotion=$REPO_HEAD
generated_source_sha256=$ACTUAL_SOURCE_SHA256
native_binary_sha256=$PROMOTED_SHA256
build_a_sha256=$ACTUAL_SHA256
build_b_sha256=$PEER_SHA256
reproducible_binary_sha_gate=PASS
reproducible_binary_cmp_gate=PASS
native_binary_size=$PROMOTED_BYTES
native_binary_mode=755
interpreter=$INTERPRETER
needed=$NEEDED
capture_literal_used=false
automatic_retry=false
self_activation_used_for_physical_ring=false
listener_lineage=frozen_v1_5_7_persistent_listener
run_dir=/run/comelit-p2p
door_sigusr1_preserved=true
door_tick_preserved=true
listener_pause_required_for_physical_ring=false
candidate_executed=false
comelit_network_requests=0
ha_deploy_performed=false
door_action_sent=false
gate_action_sent=false
EOF

install -m 0644 "$INFO_TMP" "$BUILD_INFO"

echo '=== COMELIT P116 R42-B LISTENER BINARY PROMOTION ==='
echo "REPO_HEAD=$REPO_HEAD"
echo "TARGET=custom_components/comelit/native/comelit-v4"
echo "BUILD_INFO=safety-poc/research/media/v1/P116_R42_BUILD_INFO.txt"
echo "GENERATED_SOURCE_SHA256=$ACTUAL_SOURCE_SHA256"
echo "OLD_SHA256=$OLD_SHA256"
echo "PROMOTED_SHA256=$PROMOTED_SHA256"
echo "PROMOTED_BYTES=$PROMOTED_BYTES"
echo "INTERPRETER=$INTERPRETER"
echo "NEEDED=$NEEDED"
echo 'REPRODUCIBLE_BINARY_SHA_GATE=PASS'
echo 'REPRODUCIBLE_BINARY_CMP_GATE=PASS'
echo 'CANDIDATE_EXECUTED=false'
echo 'NETWORK_IO_PERFORMED=false'
echo 'HA_DEPLOY_PERFORMED=false'
echo 'LISTENER_CHANGED=NO'
echo 'DOOR_ACTION_SENT=false'
echo 'GATE_ACTION_SENT=false'
echo 'GIT_COMMIT_PERFORMED=false'
echo 'GIT_PUSH_PERFORMED=false'
echo 'R42_PROMOTION=PASS'
