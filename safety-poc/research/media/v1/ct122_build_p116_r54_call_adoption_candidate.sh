#!/usr/bin/env bash
# Offline CT122 builder for the P116/R54 call-adoption production candidate.
#
# Source lineage:
#   frozen v1.5.7 persistent listener/Door
#   -> R42-b attached inbound media transform
#   -> R54 call-adoption listener transform
#
# This script does NOT execute the candidate, install it, deploy HA, open
# Comelit sessions, restart HA, or perform Door/Gate actions.
set -Eeuo pipefail
umask 077

REPO=${REPO:-/home/hermes/repos/comelit}
SAFETY_POC="$REPO/safety-poc"
MEDIA="$SAFETY_POC/research/media/v1"
SOURCE="$SAFETY_POC/research/door/v1_5_7/comelit-v4-persistent-ctpp-door.c"
R42B_TRANSFORM="$MEDIA/entrance_p116_r42b_listener_attached_media_transform.py"
R54_TRANSFORM="$MEDIA/entrance_p116_r54_call_adoption_listener_transform.py"
R53_CORE="$MEDIA/entrance_p116_r53_call_adoption_profile_core.py"

EXPECTED_BASE_SOURCE_SHA=5827d9fd043b85fc0c59a31661a1a125c6b239771e2a70c3e5afdd95f1a03c73

APK_CLOSURE=${APK_CLOSURE:-/home/hermes/musl-apk-closure-p80}
ALPINE_IMAGE=${ALPINE_IMAGE:-alpine:3.24.1}
EXPECTED_INTERPRETER=/lib/ld-musl-x86_64.so.1
EXPECTED_NEEDED=libc.musl-x86_64.so.1,libglib-2.0.so.0,libgobject-2.0.so.0,libnice.so.10

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
RUN_ROOT=${RUN_ROOT:-/home/hermes/comelit-r54-build-$STAMP}
mkdir -p "$RUN_ROOT"
chmod 700 "$RUN_ROOT"

SOURCE_A="$RUN_ROOT/r54-a.c"
SOURCE_B="$RUN_ROOT/r54-b.c"
BUILD_A="$RUN_ROOT/comelit-v4-r54-candidate-a"
BUILD_B="$RUN_ROOT/comelit-v4-r54-candidate-b"
META_A="$RUN_ROOT/build-a-meta.txt"
META_B="$RUN_ROOT/build-b-meta.txt"
STRINGS_A="$RUN_ROOT/build-a.strings"
COMPILE_INPUT_NAME="r54-build-input.c"
COMPILE_INPUT="$RUN_ROOT/$COMPILE_INPUT_NAME"

sha() { sha256sum "$1" | awk '{print $1}'; }

for c in git python3 sha256sum grep awk sort paste stat cmp; do
    command -v "$c" >/dev/null
done

[[ "$(id -u)" -ne 0 ]]
[[ -d "$REPO/.git" || -f "$REPO/.git" ]]
[[ -f "$SOURCE" ]]
[[ -f "$R42B_TRANSFORM" ]]
[[ -f "$R54_TRANSFORM" ]]
[[ -f "$R53_CORE" ]]

BASE_SOURCE_SHA="$(sha "$SOURCE")"
R42B_TRANSFORM_SHA="$(sha "$R42B_TRANSFORM")"
R54_TRANSFORM_SHA="$(sha "$R54_TRANSFORM")"
R53_CORE_SHA="$(sha "$R53_CORE")"
echo "BASE_SOURCE_SHA256=$BASE_SOURCE_SHA"
echo "R42B_TRANSFORM_BLOB_SHA256=$R42B_TRANSFORM_SHA"
echo "R54_TRANSFORM_BLOB_SHA256=$R54_TRANSFORM_SHA"
echo "R53_CORE_BLOB_SHA256=$R53_CORE_SHA"
[[ "$BASE_SOURCE_SHA" == "$EXPECTED_BASE_SOURCE_SHA" ]]
echo 'FROZEN_BASE_SHA256_GATE=PASS'

rm -f \
    "$SOURCE_A" "$SOURCE_B" \
    "$BUILD_A" "$BUILD_B" \
    "$META_A" "$META_B" "$STRINGS_A" \
    "$COMPILE_INPUT"

generate_once() {
    local output=$1
    PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$MEDIA" \
    python3 "$R54_TRANSFORM" \
        --source "$SOURCE" \
        --output "$output"
}

generate_once "$SOURCE_A"
generate_once "$SOURCE_B"

SOURCE_A_SHA="$(sha "$SOURCE_A")"
SOURCE_B_SHA="$(sha "$SOURCE_B")"
[[ "$SOURCE_A_SHA" == "$SOURCE_B_SHA" ]]
cmp -s "$SOURCE_A" "$SOURCE_B"
echo 'R42B_TRANSFORM_GATE=PASS'
echo 'R54_TRANSFORM_GATE=PASS'
echo 'GENERATED_SOURCE_DETERMINISTIC=true'

for marker in \
    '#define RUN_DIR     "/run/comelit-p2p"' \
    'signal(SIGUSR1, v4_door_signal_handler);' \
    'V4_RING_LISTENER_READY=true' \
    'R42_LISTENER_DOOR_SIGNAL_PRESERVED=true' \
    'R42_MEDIAREQ26_OPEN_PROFILE=CAPTURE_VALIDATED' \
    'R54_CALL_ADOPTION_STARTED=%s' \
    'R54_INVITE_ACK_SENT=%s' \
    'R54_LOCAL_CAPABILITIES_SENT=%s' \
    'R54_LOCAL_CAPABILITY_WORD=%u' \
    'R54_LOCAL_ALERTING_SENT=%s' \
    'R54_WAITING_PEER_CAPABILITIES=%s' \
    'R54_PEER_CAPABILITIES_SEEN=%s' \
    'R54_PEER_CAPABILITY_WORD=%u' \
    'R54_PEER_VIDEO_REQUESTED=%s' \
    'R54_PEER_DATA_ACK_SENT=%s' \
    'R54_CALL_ADOPTION_FAILURE_STAGE=%s'
do
    grep -Fq "$marker" "$SOURCE_A"
done

for forbidden in \
    '/run/comelit-media' \
    'signal(SIGUSR1, SIG_IGN);' \
    'ENTRANCE_SIGNALING_DOOR_SIGNAL_INSTALLED=false' \
    'entrance_self_activation' \
    'P12_TX_ENTRANCE_SELF_ACTIVATION' \
    'startAudioTX' \
    'PT8_GENERATOR'
do
    if grep -Fq "$forbidden" "$SOURCE_A"; then
        echo "SOURCE_FORBIDDEN_GATE=FAIL needle=$forbidden"
        exit 1
    fi
done

if grep -Eq '0x0[Cc]4[Aa]|0x4[Aa]5[Aa]|0x[Cc][Aa]5[Aa]' "$SOURCE_A"; then
    echo 'CAPTURE_LITERAL_GATE=FAIL'
    exit 1
fi
echo 'SOURCE_MARKER_GATE=PASS'
echo 'AUDIO_TX_ADDED=false'
echo 'CAPTURE_LITERAL_REPLAY_USED=false'
echo 'DOOR_SEMANTICS_CHANGED=false'

if ! command -v docker >/dev/null || [[ ! -d "$APK_CLOSURE" ]]; then
    echo 'BUILD_RC=NOT_RUN_BY_EXECUTOR'
    echo 'BUILD_WARNINGS=NOT_RUN_BY_EXECUTOR'
    echo "GENERATED_SOURCE_SHA256=$SOURCE_A_SHA"
    echo "R54_GENERATED_SOURCE=$SOURCE_A"
    echo "R54_GENERATED_SOURCE_REPRODUCIBLE_PEER=$SOURCE_B"
    echo 'MUSL_INTERPRETER_GATE=NOT_RUN_BY_EXECUTOR'
    echo 'NO_GLIBC_DEPENDENCY=NOT_RUN_BY_EXECUTOR'
    echo 'NO_NEW_RUNTIME_DEPENDENCY=NOT_RUN_BY_EXECUTOR'
    echo 'CANDIDATE_BINARY_SHA256=PENDING_PARENT_BUILD'
    echo 'CANDIDATE_BINARY_SIZE=PENDING_PARENT_BUILD'
    echo 'CANDIDATE_EXECUTED=false'
    echo 'COMELIT_NETWORK_REQUESTS=0'
    echo 'HA_DEPLOY_PERFORMED=false'
    echo 'DOOR_ACTION_SENT=false'
    echo 'GATE_ACTION_SENT=false'
    exit 0
fi

for c in docker readelf strings timeout; do
    command -v "$c" >/dev/null
done
[[ -d "$APK_CLOSURE" ]]

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
build_once "$COMPILE_INPUT_NAME" "$(basename "$BUILD_A")" "$(basename "$META_A")"

BUILD_B_COMPILE_INPUT_SHA256="$(stage_compile_input "$SOURCE_B" "$SOURCE_B_SHA")"
build_once "$COMPILE_INPUT_NAME" "$(basename "$BUILD_B")" "$(basename "$META_B")"

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
    'R42_MEDIAREQ26_OPEN_PROFILE=CAPTURE_VALIDATED' \
    'R54_CALL_ADOPTION_STARTED=%s' \
    'R54_INVITE_ACK_SENT=%s' \
    'R54_LOCAL_CAPABILITIES_SENT=%s' \
    'R54_LOCAL_CAPABILITY_WORD=%u' \
    'R54_LOCAL_ALERTING_SENT=%s' \
    'R54_WAITING_PEER_CAPABILITIES=%s' \
    'R54_PEER_CAPABILITIES_SEEN=%s' \
    'R54_PEER_CAPABILITY_WORD=%u' \
    'R54_PEER_VIDEO_REQUESTED=%s' \
    'R54_PEER_DATA_ACK_SENT=%s' \
    'R54_CALL_ADOPTION_FAILURE_STAGE=%s'
do
    grep -Fq "$marker" "$STRINGS_A"
done

if strings -a "$BUILD_A" | grep -Eq '0x0[Cc]4[Aa]|0x4[Aa]5[Aa]|0x[Cc][Aa]5[Aa]'; then
    echo 'BINARY_CAPTURE_LITERAL_GATE=FAIL'
    exit 1
fi

BUILD_BYTES="$(stat -c '%s' "$BUILD_A")"

echo '=== COMELIT P116 R54 OFFLINE BUILD SUMMARY ==='
echo "REPO_HEAD=$(git -C "$REPO" rev-parse HEAD)"
echo "BASE_SOURCE_SHA256=$BASE_SOURCE_SHA"
echo "R42B_TRANSFORM_BLOB_SHA256=$R42B_TRANSFORM_SHA"
echo "R54_TRANSFORM_BLOB_SHA256=$R54_TRANSFORM_SHA"
echo "R53_CORE_BLOB_SHA256=$R53_CORE_SHA"
echo "R54_GENERATED_SOURCE=$SOURCE_A"
echo "R54_GENERATED_SOURCE_REPRODUCIBLE_PEER=$SOURCE_B"
echo "R54_GENERATED_SOURCE_SHA256=$SOURCE_A_SHA"
echo "SOURCE_A_SHA256=$SOURCE_A_SHA"
echo "SOURCE_B_SHA256=$SOURCE_B_SHA"
echo "CANDIDATE_PATH=$BUILD_A"
echo "CANDIDATE_REPRODUCIBLE_PEER=$BUILD_B"
echo "CANDIDATE_SHA256=$BUILD_A_SHA"
echo "BUILD_A_SHA256=$BUILD_A_SHA"
echo "BUILD_B_SHA256=$BUILD_B_SHA"
echo "BUILD_A_COMPILE_INPUT_SHA256=$BUILD_A_COMPILE_INPUT_SHA256"
echo "BUILD_B_COMPILE_INPUT_SHA256=$BUILD_B_COMPILE_INPUT_SHA256"
echo "CANDIDATE_BYTES=$BUILD_BYTES"
echo "INTERPRETER=$INTERPRETER_A"
echo "NEEDED=$NEEDED_A"
echo 'REPRODUCIBLE_SOURCE_SHA_GATE=PASS'
echo 'REPRODUCIBLE_SOURCE_CMP_GATE=PASS'
echo 'REPRODUCIBLE_BINARY_SHA_GATE=PASS'
echo 'REPRODUCIBLE_BINARY_CMP_GATE=PASS'
echo 'MUSL_INTERPRETER_GATE=PASS'
echo 'NO_GLIBC_DEPENDENCY=PASS'
echo 'NO_NEW_RUNTIME_DEPENDENCY=PASS'
echo 'CANDIDATE_EXECUTED=false'
echo 'COMELIT_NETWORK_REQUESTS=0'
echo 'HA_DEPLOY_PERFORMED=false'
echo 'DOOR_ACTION_SENT=false'
echo 'GATE_ACTION_SENT=false'
echo 'R54_CANDIDATE_BUILD=PASS'
