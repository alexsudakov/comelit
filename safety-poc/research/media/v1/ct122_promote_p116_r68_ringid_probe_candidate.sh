#!/usr/bin/env bash
# Promote one reproducibly-built P116/R68 musl listener candidate into the
# integration tree and write public-safe provenance metadata.
#
# This script performs NO network IO, NO HA deploy, NO listener action and NO
# Git commit/push.  The orchestrator must fill PINNED_R68_BINARY_SHA after it
# has measured the reproducible Docker build output.
#
# The R68 round records the observability overlay (ring opaque body probe plus
# the additive monotonic/trace markers).  When the same R68 phase is promoted
# again because that overlay genuinely changed the generated source, the pins
# below MUST be updated to the newly measured reproducible artifact and the
# replaced same-round artifact is recorded in the build info.
set -Eeuo pipefail
umask 077

REPO=${REPO:-/home/hermes/repos/comelit}
CANDIDATE=${CANDIDATE:-}
REPRODUCIBLE_PEER=${REPRODUCIBLE_PEER:-}
R68_SOURCE=${R68_SOURCE:-}
EXPECTED_SHA256=${EXPECTED_SHA256:-}
EXPECTED_SOURCE_SHA256=${EXPECTED_SOURCE_SHA256:-}
PINNED_R68_SOURCE_SHA=566ff0e554f3f2b1c7b2c89bfc1b7b3cdbb0d40a0c1eeba79500ad6f20cba420
PINNED_R68_BINARY_SHA=0f1798bff9527b50fe6f72c2be7c10000cd1d1d08472da8ccb35aa08da3edbab
PINNED_R68_TRANSFORM_SHA=07e89b14a8aae4f5630b24f4bff29043e9d71b1659bfe786836258e64579fd84
PINNED_R68_CORE_SHA=11cc22cd6ade347b734207c940f1951a41d002dceeafb3a1b8035dfd47b98cce
PINNED_R68_RUN_ROOT=/home/hermes/comelit-r68-build-20261014T124229Z
REPLACED_R68_BINARY_SHA=fb3b68c140901bbd6ee5cc4c1c2fc602004012dfe40bf725a931efa970fde851

TARGET="$REPO/custom_components/comelit/native/comelit-v4"
BUILD_INFO="$REPO/safety-poc/research/media/v1/P116_R68_BUILD_INFO.txt"
EXPECTED_INTERPRETER=/lib/ld-musl-x86_64.so.1
EXPECTED_NEEDED=libc.musl-x86_64.so.1,libglib-2.0.so.0,libgobject-2.0.so.0,libnice.so.10

fail() {
    echo "R68_PROMOTION=FAIL"
    echo "REASON=$1"
    exit 1
}

[[ "$PINNED_R68_BINARY_SHA" != "ORCHESTRATOR_FILL" ]] || fail "ORCHESTRATOR_FILL_BINARY_SHA"
[[ "$(id -u)" -ne 0 ]] || fail "ROOT_NOT_ALLOWED"
[[ -n "$CANDIDATE" ]] || fail "CANDIDATE_NOT_SET"
[[ -n "$REPRODUCIBLE_PEER" ]] || fail "REPRODUCIBLE_PEER_NOT_SET"
[[ -n "$R68_SOURCE" ]] || fail "R68_SOURCE_NOT_SET"
[[ -n "$EXPECTED_SHA256" ]] || fail "EXPECTED_SHA256_NOT_SET"
[[ -n "$EXPECTED_SOURCE_SHA256" ]] || fail "EXPECTED_SOURCE_SHA256_NOT_SET"
[[ "$EXPECTED_SHA256" =~ ^[0-9a-f]{64}$ ]] || fail "EXPECTED_SHA256_SHAPE"
[[ "$EXPECTED_SOURCE_SHA256" =~ ^[0-9a-f]{64}$ ]] || fail "EXPECTED_SOURCE_SHA256_SHAPE"
[[ -f "$CANDIDATE" ]] || fail "CANDIDATE_MISSING"
[[ -f "$REPRODUCIBLE_PEER" ]] || fail "REPRODUCIBLE_PEER_MISSING"
[[ -f "$R68_SOURCE" ]] || fail "R68_SOURCE_MISSING"
[[ -d "$REPO/.git" || -f "$REPO/.git" ]] || fail "REPO_MISSING"

for c in git sha256sum readelf strings install stat cmp grep awk sort paste; do
    command -v "$c" >/dev/null || fail "COMMAND_MISSING_$c"
done

REPO_HEAD="$(git -C "$REPO" rev-parse HEAD)"
ACTUAL_SOURCE_SHA256="$(sha256sum "$R68_SOURCE" | awk '{print $1}')"
ACTUAL_SHA256="$(sha256sum "$CANDIDATE" | awk '{print $1}')"
PEER_SHA256="$(sha256sum "$REPRODUCIBLE_PEER" | awk '{print $1}')"

[[ "$EXPECTED_SOURCE_SHA256" == "$PINNED_R68_SOURCE_SHA" ]] \
    || fail "EXPECTED_SOURCE_SHA_NOT_PINNED"
[[ "$EXPECTED_SHA256" == "$PINNED_R68_BINARY_SHA" ]] \
    || fail "EXPECTED_BINARY_SHA_NOT_PINNED"
[[ "$ACTUAL_SOURCE_SHA256" == "$PINNED_R68_SOURCE_SHA" ]] \
    || fail "SOURCE_SHA_MISMATCH"
[[ "$ACTUAL_SHA256" == "$PINNED_R68_BINARY_SHA" ]] \
    || fail "CANDIDATE_SHA_MISMATCH"
[[ "$PEER_SHA256" == "$PINNED_R68_BINARY_SHA" ]] \
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
NO_GLIBC_DEPENDENCY=PASS
REPRODUCIBLE_BINARY_CMP_GATE=PASS
BASE_SOURCE_SHA_GATE=PASS
GENERATED_SOURCE_SHA_GATE=PASS
MUSL_INTERPRETER_GATE=PASS
NO_NEW_RUNTIME_DEPENDENCY=PASS

STRINGS_TMP="$(mktemp)"
INFO_TMP="$(mktemp)"
trap 'rm -f "$STRINGS_TMP" "$INFO_TMP"' EXIT

strings -a "$CANDIDATE" > "$STRINGS_TMP"
for marker in \
    'R67_ATTACHED_REFRESH_CADENCE_SECONDS=%u' \
    'R67_ATTACHED_REFRESH_QUEUED_COUNT=%u' \
    'R67_ATTACHED_REFRESH_SENT_COUNT=%u' \
    'R67_ATTACHED_REFRESH_LAST_RESULT=%s' \
    'R67_ATTACHED_REFRESH_LAST_ERROR=%s' \
    'R67_ATTACHED_REFRESH_SESSION_RESET=true' \
    'R67_ATTACHED_REFRESH_OPCODE=0x0011' \
    'R67_ATTACHED_REFRESH_FRAME=MEDIAREQ26_OPEN' \
    'V4_DOOR_PATH=CALL_TIME_SINGLE' \
    'V4_RING_BODY_32_35' \
    'V4_RING_PEER_CONNECTION' \
    'V4_RING_PHASE' \
    'V4_RING_PARSE_STATUS' \
    'V4_RING_MONOTONIC_MS=%llu' \
    'VIDEO_PACKET_COUNT_AT_REPEAT=%llu' \
    'AUDIO_PACKET_COUNT_AT_REPEAT=%llu' \
    'LAST_VIDEO_RTP_MONOTONIC_MS=%llu' \
    'LAST_AUDIO_RTP_MONOTONIC_MS=%llu' \
    'RX_STALLED=true' \
    'RTP_STALL_SECONDS=%llu' \
    'CTPP_TRACE_DIRECTION=IN' \
    'CTPP_TRACE_DIRECTION=OUT' \
    'CTPP_TRACE_OPCODE=%u' \
    'CTPP_TRACE_TYPE=%u' \
    'CTPP_TRACE_CHANNEL=%u' \
    'CTPP_TRACE_LENGTH=%u' \
    'CTPP_TRACE_MONOTONIC_MS=%llu' \
    'P116_NATIVE_EXIT_INTENTIONAL_STOP=%s' \
    'PSEUDOTCP_CLOSED_CALLBACK_ERROR=%u'
do
    grep -Fq "$marker" "$STRINGS_TMP" || fail "MARKER_MISSING"
done
R68_BINARY_MARKER_GATE=PASS

for forbidden in \
    '/run/comelit-media' \
    'signal(SIGUSR1, SIG_IGN);' \
    'entrance_self_activation' \
    'P12_TX_ENTRANCE_SELF_ACTIVATION' \
    'CTPP_TRACE_PAYLOAD' \
    'CTPP_TRACE_HEX'
do
    if grep -Fq "$forbidden" "$STRINGS_TMP"; then
        fail "FORBIDDEN_MARKER_PRESENT"
    fi
done
grep -Fq 'V4_RING_BODY_32_35' "$R68_SOURCE" \
    || fail "R68_RINGID_PROBE_SOURCE_MARKER_MISSING"
grep -Fq 'R67_ATTACHED_REFRESH_CADENCE_SECONDS=%u' "$R68_SOURCE" \
    || fail "R67_SOURCE_MARKER_MISSING"
grep -Fq 'P116_NATIVE_EXIT_INTENTIONAL_STOP=%s' "$R68_SOURCE" \
    || fail "CAPTURE_LITERAL_MISSING"
R68_RINGID_PROBE_SOURCE_MARKER_GATE=PASS
R67_SOURCE_MARKER_GATE=PASS
CAPTURE_LITERAL_GATE=PASS
COMPILE_INPUT_STAGE_GATE=PASS

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
phase=P116_R68_RINGID_PROBE_OBSERVABILITY_ONLY
observability_only=true
BODY_32_35_SEMANTICS_PROVEN=false
builder=safety-poc/research/media/v1/ct122_build_p116_r68_ringid_probe_candidate.sh
RUN_ROOT=$PINNED_R68_RUN_ROOT
repo_head_at_promotion=$REPO_HEAD
base_source_sha256=5827d9fd043b85fc0c59a31661a1a125c6b239771e2a70c3e5afdd95f1a03c73
source_sha256=$ACTUAL_SOURCE_SHA256
generated_source_sha256=$ACTUAL_SOURCE_SHA256
ringid_probe_transform=safety-poc/research/media/v1/entrance_p116_r68_ringid_probe_transform.py
ringid_probe_transform_sha256_at_build=$PINNED_R68_TRANSFORM_SHA
ringid_probe_transform_sha256_current=$PINNED_R68_TRANSFORM_SHA
ringid_probe_transform_post_build_change=observability overlay (ring-id core + R57/R67 markers) applied before this build; generated_source_sha256 remained $ACTUAL_SOURCE_SHA256
ringid_probe_core=safety-poc/research/media/v1/entrance_p116_r68_ringid_probe_core.py
ringid_probe_core_sha256=$PINNED_R68_CORE_SHA
native_binary_sha256=$PROMOTED_SHA256
native_binary_size=$PROMOTED_BYTES
native_binary_mode=755
interpreter=$INTERPRETER
needed=$NEEDED
build_a_sha256=$PROMOTED_SHA256
build_b_sha256=$PROMOTED_SHA256
REPRODUCIBLE_BINARY_CMP_GATE=$REPRODUCIBLE_BINARY_CMP_GATE
BASE_SOURCE_SHA_GATE=$BASE_SOURCE_SHA_GATE
GENERATED_SOURCE_SHA_GATE=$GENERATED_SOURCE_SHA_GATE
R68_RINGID_PROBE_SOURCE_MARKER_GATE=$R68_RINGID_PROBE_SOURCE_MARKER_GATE
R67_SOURCE_MARKER_GATE=$R67_SOURCE_MARKER_GATE
CAPTURE_LITERAL_GATE=$CAPTURE_LITERAL_GATE
COMPILE_INPUT_STAGE_GATE=$COMPILE_INPUT_STAGE_GATE
MUSL_INTERPRETER_GATE=$MUSL_INTERPRETER_GATE
NO_NEW_RUNTIME_DEPENDENCY=$NO_NEW_RUNTIME_DEPENDENCY
R68_BINARY_MARKER_GATE=$R68_BINARY_MARKER_GATE
RAW_RING_PAYLOAD_EMITTED=false
NETWORK_ACTION_PERFORMED=false
PHYSICAL_DOOR_ACTION=false
superseded_native_binary_sha256=eabda869783f9b1efb578e3801b0b0e50c70fd52932960ba22c95003e28fbacb
superseded_provenance_file=P116_R67_BUILD_INFO.txt
replaced_native_binary_sha256=$REPLACED_R68_BINARY_SHA
replaced_reason=CORR-2 R57 native intentional-stop predicate correction (g_p116_native_exit_intentional_stop && failure_count==0 && !failed_flag) rebuilt the R68 listener source (566ff0e5); same R68 phase re-promoted in place
candidate_executed=false
production_deploy_performed=false
EOF

install -m 0644 "$INFO_TMP" "$BUILD_INFO"

echo '=== COMELIT P116 R68 LISTENER BINARY PROMOTION ==='
echo "REPO_HEAD=$REPO_HEAD"
echo "TARGET=custom_components/comelit/native/comelit-v4"
echo "BUILD_INFO=safety-poc/research/media/v1/P116_R68_BUILD_INFO.txt"
echo "SOURCE_SHA256=$ACTUAL_SOURCE_SHA256"
echo "OLD_SHA256=$OLD_SHA256"
echo "PROMOTED_SHA256=$PROMOTED_SHA256"
echo "PROMOTED_BYTES=$PROMOTED_BYTES"
echo "INTERPRETER=$INTERPRETER"
echo "NEEDED=$NEEDED"
echo "REPRODUCIBLE_BINARY_CMP_GATE=$REPRODUCIBLE_BINARY_CMP_GATE"
echo "MUSL_INTERPRETER_GATE=$MUSL_INTERPRETER_GATE"
echo "NO_GLIBC_DEPENDENCY=$NO_GLIBC_DEPENDENCY"
echo "NO_NEW_RUNTIME_DEPENDENCY=$NO_NEW_RUNTIME_DEPENDENCY"
echo 'CANDIDATE_EXECUTED=false'
echo 'NETWORK_IO_PERFORMED=false'
echo 'HA_DEPLOY_PERFORMED=false'
echo 'DOOR_ACTION_SENT=false'
echo 'GATE_ACTION_SENT=false'
echo 'GIT_COMMIT_PERFORMED=false'
echo 'GIT_PUSH_PERFORMED=false'
echo 'R68_PROMOTION=PASS'
