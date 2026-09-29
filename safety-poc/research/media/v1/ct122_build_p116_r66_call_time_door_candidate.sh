#!/usr/bin/env bash
# Offline CT122 builder for the P116/R66 call-time Door single-message candidate.
#
# Source lineage:
#   frozen v1.5.7 persistent listener/Door
#   -> R42-b attached inbound media transform
#   -> R54 call-adoption listener transform
#   -> R63/R64 listener observability lineage
#   -> R66 call-time Door single-message transform
#
# The generated C source is produced twice and must be byte-identical.
# Each generated source is then compiled independently inside Alpine/musl
# containers with --network none; the two ELF binaries must also be identical.
#
# This script does NOT execute the candidate, install it, deploy HA, open
# Comelit sessions, restart HA, or perform Door/Gate actions.
set -Eeuo pipefail
umask 077

REPO=${REPO:-/home/hermes/repos/comelit}
SAFETY_POC="$REPO/safety-poc"
MEDIA="$SAFETY_POC/research/media/v1"
SOURCE="$SAFETY_POC/research/door/v1_5_7/comelit-v4-persistent-ctpp-door.c"
TRANSFORM="$MEDIA/entrance_p116_r66_call_time_door_transform.py"

EXPECTED_BASE_SOURCE_SHA=5827d9fd043b85fc0c59a31661a1a125c6b239771e2a70c3e5afdd95f1a03c73
EXPECTED_GENERATED_SOURCE_SHA=bd9a9580ddba62f3fc093e3ae42b11e3e85090bb8c8f35af2c8e810b1938de42

APK_CLOSURE=${APK_CLOSURE:-/home/hermes/musl-apk-closure-p80}
ALPINE_IMAGE=${ALPINE_IMAGE:-alpine:3.24.1}
EXPECTED_INTERPRETER=/lib/ld-musl-x86_64.so.1
EXPECTED_NEEDED=libc.musl-x86_64.so.1,libglib-2.0.so.0,libgobject-2.0.so.0,libnice.so.10

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
RUN_ROOT=${RUN_ROOT:-/home/hermes/comelit-r66-build-$STAMP}
mkdir -p "$RUN_ROOT"
chmod 700 "$RUN_ROOT"

SOURCE_A="$RUN_ROOT/r66-a.c"
SOURCE_B="$RUN_ROOT/r66-b.c"
BUILD_A="$RUN_ROOT/comelit-v4-r66-candidate-a"
BUILD_B="$RUN_ROOT/comelit-v4-r66-candidate-b"
META_A="$RUN_ROOT/build-a-meta.txt"
META_B="$RUN_ROOT/build-b-meta.txt"
STRINGS_A="$RUN_ROOT/build-a.strings"
COMPILE_INPUT_NAME="r66-build-input.c"
COMPILE_INPUT="$RUN_ROOT/$COMPILE_INPUT_NAME"

sha() { sha256sum "$1" | awk '{print $1}'; }

for c in git python3 docker sha256sum readelf strings grep awk sort paste stat cmp timeout; do
    command -v "$c" >/dev/null
done

[[ "$(id -u)" -ne 0 ]]
[[ -d "$REPO/.git" || -f "$REPO/.git" ]]
[[ -f "$SOURCE" ]]
[[ -f "$TRANSFORM" ]]
[[ -d "$APK_CLOSURE" ]]

BASE_SOURCE_SHA="$(sha "$SOURCE")"
TRANSFORM_SHA="$(sha "$TRANSFORM")"
echo "BASE_SOURCE_SHA256=$BASE_SOURCE_SHA"
echo "R66_TRANSFORM_BLOB_SHA256=$TRANSFORM_SHA"
[[ "$BASE_SOURCE_SHA" == "$EXPECTED_BASE_SOURCE_SHA" ]]
echo 'BASE_SOURCE_SHA_GATE=PASS'

rm -f \
    "$SOURCE_A" "$SOURCE_B" \
    "$BUILD_A" "$BUILD_B" \
    "$META_A" "$META_B" "$STRINGS_A" \
    "$COMPILE_INPUT"

generate_once() {
    local output=$1
    PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$MEDIA" \
    python3 "$TRANSFORM" \
        --source "$SOURCE" \
        --output "$output"
}

generate_once "$SOURCE_A"
generate_once "$SOURCE_B"

SOURCE_A_SHA="$(sha "$SOURCE_A")"
SOURCE_B_SHA="$(sha "$SOURCE_B")"

[[ "$SOURCE_A_SHA" == "$SOURCE_B_SHA" ]]
cmp -s "$SOURCE_A" "$SOURCE_B"
[[ "$SOURCE_A_SHA" == "$EXPECTED_GENERATED_SOURCE_SHA" ]]
echo 'GENERATED_SOURCE_SHA_GATE=PASS'

for marker in \
    '#define RUN_DIR     "/run/comelit-p2p"' \
    'signal(SIGUSR1, v4_door_signal_handler);' \
    'V4_RING_LISTENER_READY=true' \
    'R42_LISTENER_DOOR_SIGNAL_PRESERVED=true' \
    'R42_MEDIAREQ26_OPEN_PROFILE=CAPTURE_VALIDATED' \
    'R54_CALL_ADOPTION_STARTED=%s' \
    'R54_INVITE_ACK_SENT=%s' \
    'R54_LOCAL_CAPABILITIES_SENT=%s' \
    'R54_WAITING_PEER_CAPABILITIES=%s' \
    'R54_PEER_CAPABILITIES_SEEN=%s' \
    'R54_CALL_ADOPTION_FAILURE_STAGE=%s' \
    'R64_POST_CALL_SNAPSHOT=true' \
    'R64_TERMINAL_SNAPSHOT=true' \
    'R64_POST_CALL_TX_STATE=%s' \
    'R64_TERMINAL_TX_STATE=%s' \
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
    grep -Fq "$marker" "$SOURCE_A"
done

for forbidden in \
    '/run/comelit-media' \
    'signal(SIGUSR1, SIG_IGN);' \
    'ENTRANCE_SIGNALING_DOOR_SIGNAL_INSTALLED=false' \
    'entrance_self_activation' \
    'P12_TX_ENTRANCE_SELF_ACTIVATION'
do
    if grep -Fq "$forbidden" "$SOURCE_A"; then
        echo "LISTENER_LINEAGE_FORBIDDEN_GATE=FAIL needle=$forbidden"
        exit 1
    fi
done
echo 'LISTENER_LINEAGE_GATE=PASS'
echo 'R66_SOURCE_MARKER_GATE=PASS'

if grep -Eq '0x0[Cc]4[Aa]|0x4[Aa]5[Aa]|0x[Cc][Aa]5[Aa]' "$SOURCE_A"; then
    echo 'CAPTURE_LITERAL_GATE=FAIL'
    exit 1
fi
echo 'CAPTURE_LITERAL_GATE=PASS'

cat > "$RUN_ROOT/build.sh" <<'EOS'
set -eu
: "${SRC:?SRC is required}"
: "${OUT:?OUT is required}"
: "${META:?META is required}"

apk add --no-network --allow-untrusted /pkgs/*.apk >/dev/null

cc -O2 -g -Wall -Wextra -Wl,--as-needed \
    -o "/w/$OUT" \
    "/w/$SRC" \
    $(pkg-config --cflags --libs nice glib-2.0 gio-2.0 gobject-2.0)

chmod 755 "/w/$OUT"

readelf -l "/w/$OUT" \
    | sed -n 's@.*Requesting program interpreter: \(.*\)]@interpreter=\1@p' \
    > "/w/$META"

readelf -d "/w/$OUT" \
    | sed -n 's/.*Shared library: \[\(.*\)\]/\1/p' \
    | sort \
    | paste -sd, - \
    | sed 's/^/needed_sorted=/' \
    >> "/w/$META"
EOS
chmod 700 "$RUN_ROOT/build.sh"

build_once() {
    local src_name=$1 out_name=$2 meta_name=$3
    timeout 900 docker run --rm --network none \
        --security-opt apparmor=unconfined \
        -e SRC="$src_name" \
        -e OUT="$out_name" \
        -e META="$meta_name" \
        -v "$RUN_ROOT":/w \
        -v "$APK_CLOSURE":/pkgs:ro \
        "$ALPINE_IMAGE" \
        /bin/sh /w/build.sh
}

# Both builds must compile the same source path inside the container
# (/w/$COMPILE_INPUT_NAME) so the compiled filename baked into DWARF/BuildID
# does not itself become a source of binary drift.
stage_compile_input() {
    local from=$1 expected_sha=$2
    cp "$from" "$COMPILE_INPUT"
    local staged_sha
    staged_sha="$(sha "$COMPILE_INPUT")"
    if [[ "$staged_sha" != "$expected_sha" ]]; then
        echo "COMPILE_INPUT_STAGE_GATE=FAIL from=$from"
        exit 1
    fi
    echo "$staged_sha"
}

BUILD_A_COMPILE_INPUT_SHA256="$(stage_compile_input "$SOURCE_A" "$SOURCE_A_SHA")"
echo "COMPILE_INPUT_NAME=$COMPILE_INPUT_NAME"
echo "BUILD_A_COMPILE_INPUT_SHA256=$BUILD_A_COMPILE_INPUT_SHA256"
build_once \
    "$COMPILE_INPUT_NAME" \
    "$(basename "$BUILD_A")" \
    "$(basename "$META_A")"

BUILD_B_COMPILE_INPUT_SHA256="$(stage_compile_input "$SOURCE_B" "$SOURCE_B_SHA")"
echo "BUILD_B_COMPILE_INPUT_SHA256=$BUILD_B_COMPILE_INPUT_SHA256"
build_once \
    "$COMPILE_INPUT_NAME" \
    "$(basename "$BUILD_B")" \
    "$(basename "$META_B")"

echo 'COMPILE_INPUT_STAGE_GATE=PASS'

BUILD_A_SHA="$(sha "$BUILD_A")"
BUILD_B_SHA="$(sha "$BUILD_B")"

[[ "$BUILD_A_SHA" == "$BUILD_B_SHA" ]]
cmp -s "$BUILD_A" "$BUILD_B"

INTERPRETER_A="$(sed -n 's/^interpreter=//p' "$META_A")"
INTERPRETER_B="$(sed -n 's/^interpreter=//p' "$META_B")"
NEEDED_A="$(sed -n 's/^needed_sorted=//p' "$META_A")"
NEEDED_B="$(sed -n 's/^needed_sorted=//p' "$META_B")"

[[ "$INTERPRETER_A" == "$EXPECTED_INTERPRETER" ]]
[[ "$INTERPRETER_B" == "$EXPECTED_INTERPRETER" ]]
[[ "$NEEDED_A" == "$EXPECTED_NEEDED" ]]
[[ "$NEEDED_B" == "$EXPECTED_NEEDED" ]]
[[ ",$NEEDED_A," != *",libc.so.6,"* ]]

strings -a "$BUILD_A" > "$STRINGS_A"

for marker in \
    'V4_RING_LISTENER_READY=true' \
    'R42_LISTENER_DOOR_SIGNAL_PRESERVED=true' \
    'R42_MEDIAREQ26_OPEN_PROFILE=CAPTURE_VALIDATED' \
    'R54_CALL_ADOPTION_STARTED=%s' \
    'R54_INVITE_ACK_SENT=%s' \
    'R54_LOCAL_CAPABILITIES_SENT=%s' \
    'R54_WAITING_PEER_CAPABILITIES=%s' \
    'R54_PEER_CAPABILITIES_SEEN=%s' \
    'R54_CALL_ADOPTION_FAILURE_STAGE=%s' \
    'R64_POST_CALL_SNAPSHOT=true' \
    'R64_TERMINAL_SNAPSHOT=true' \
    'R64_POST_CALL_TX_STATE=%s' \
    'R64_TERMINAL_TX_STATE=%s' \
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
    grep -Fq "$marker" "$STRINGS_A"
done

for forbidden in \
    '/run/comelit-media' \
    'signal(SIGUSR1, SIG_IGN);' \
    'entrance_self_activation' \
    'P12_TX_ENTRANCE_SELF_ACTIVATION'
do
    if grep -Fq "$forbidden" "$STRINGS_A"; then
        echo "BINARY_FORBIDDEN_GATE=FAIL needle=$forbidden"
        exit 1
    fi
done

if strings -a "$BUILD_A" \
    | grep -Eq '0x0[Cc]4[Aa]|0x4[Aa]5[Aa]|0x[Cc][Aa]5[Aa]'
then
    echo 'BINARY_CAPTURE_LITERAL_GATE=FAIL'
    exit 1
fi

BUILD_BYTES="$(stat -c '%s' "$BUILD_A")"

echo '=== COMELIT P116 R66 OFFLINE BUILD SUMMARY ==='
echo "REPO_HEAD=$(git -C "$REPO" rev-parse HEAD)"
echo "BASE_SOURCE_SHA256=$BASE_SOURCE_SHA"
echo "R66_TRANSFORM_BLOB_SHA256=$TRANSFORM_SHA"
echo "EXPECTED_GENERATED_SOURCE_SHA=$EXPECTED_GENERATED_SOURCE_SHA"
echo "R66_GENERATED_SOURCE=$SOURCE_A"
echo "R66_GENERATED_SOURCE_REPRODUCIBLE_PEER=$SOURCE_B"
echo "R66_GENERATED_SOURCE_SHA256=$SOURCE_A_SHA"
echo "SOURCE_SHA256=$SOURCE_A_SHA"
echo "SOURCE_A_SHA256=$SOURCE_A_SHA"
echo "SOURCE_B_SHA256=$SOURCE_B_SHA"
echo "CANDIDATE_PATH=$BUILD_A"
echo "CANDIDATE_REPRODUCIBLE_PEER=$BUILD_B"
echo "CANDIDATE_SHA256=$BUILD_A_SHA"
echo "BUILD_A_SHA256=$BUILD_A_SHA"
echo "BUILD_B_SHA256=$BUILD_B_SHA"
echo "COMPILE_INPUT_NAME=$COMPILE_INPUT_NAME"
echo "BUILD_A_COMPILE_INPUT_SHA256=$BUILD_A_COMPILE_INPUT_SHA256"
echo "BUILD_B_COMPILE_INPUT_SHA256=$BUILD_B_COMPILE_INPUT_SHA256"
echo "CANDIDATE_BYTES=$BUILD_BYTES"
echo "INTERPRETER=$INTERPRETER_A"
echo "NEEDED=$NEEDED_A"
echo 'BASE_SOURCE_SHA_GATE=PASS'
echo 'GENERATED_SOURCE_SHA_GATE=PASS'
echo 'COMPILE_INPUT_STAGE_GATE=PASS'
echo 'REPRODUCIBLE_SOURCE_SHA_GATE=PASS'
echo 'REPRODUCIBLE_SOURCE_CMP_GATE=PASS'
echo 'REPRODUCIBLE_BINARY_SHA_GATE=PASS'
echo 'REPRODUCIBLE_BINARY_CMP_GATE=PASS'
echo 'MUSL_INTERPRETER_GATE=PASS'
echo 'NO_GLIBC_DEPENDENCY=PASS'
echo 'NO_NEW_RUNTIME_DEPENDENCY=PASS'
echo 'LISTENER_LINEAGE_GATE=PASS'
echo 'R66_SOURCE_MARKER_GATE=PASS'
echo 'R66_BINARY_MARKER_GATE=PASS'
echo 'CAPTURE_LITERAL_GATE=PASS'
echo 'BINARY_CAPTURE_LITERAL_GATE=PASS'
echo 'CANDIDATE_EXECUTED=false'
echo 'COMELIT_NETWORK_REQUESTS=0'
echo 'HA_DEPLOY_PERFORMED=false'
echo 'DOOR_ACTION_SENT=false'
echo 'GATE_ACTION_SENT=false'
echo 'R66_CANDIDATE_BUILD=PASS'
