#!/usr/bin/env bash
# Offline CT122 builder for the P116/R67 attached-media refresh candidate.
#
# Source lineage:
#   frozen v1.5.7 persistent listener/Door
#   -> P106 include_p116 canonical generation
#   -> R35/R36/R37/R42/R42b attached inbound media
#   -> R54/R63/R64/R66 listener/Door lineage
#   -> R67 attached MEDIAREQ26 refresh
#
# This script does NOT execute the candidate, install it, deploy HA, open
# Comelit sessions, restart HA, or perform Door/Gate actions.
set -Eeuo pipefail
umask 077

REPO=${REPO:-/home/hermes/repos/comelit}
SAFETY_POC="$REPO/safety-poc"
MEDIA="$SAFETY_POC/research/media/v1"
SOURCE="$SAFETY_POC/research/door/v1_5_7/comelit-v4-persistent-ctpp-door.c"
TRANSFORM="$MEDIA/entrance_p116_r67_attached_media_refresh_transform.py"

EXPECTED_BASE_SOURCE_SHA=5827d9fd043b85fc0c59a31661a1a125c6b239771e2a70c3e5afdd95f1a03c73
EXPECTED_GENERATED_SOURCE_SHA=926329b9510f4250f898091da0a8256370415a70f1a39f93b8783403121c9d71

APK_CLOSURE=${APK_CLOSURE:-/home/hermes/musl-apk-closure-p80}
ALPINE_IMAGE=${ALPINE_IMAGE:-alpine:3.24.1}
EXPECTED_INTERPRETER=/lib/ld-musl-x86_64.so.1
EXPECTED_NEEDED=libc.musl-x86_64.so.1,libglib-2.0.so.0,libgobject-2.0.so.0,libnice.so.10

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
RUN_ROOT=${RUN_ROOT:-/home/hermes/comelit-r67-build-$STAMP}
mkdir -p "$RUN_ROOT"
chmod 700 "$RUN_ROOT"

SOURCE_A="$RUN_ROOT/r67-a.c"
SOURCE_B="$RUN_ROOT/r67-b.c"
BUILD_A="$RUN_ROOT/comelit-v4-r67-candidate-a"
BUILD_B="$RUN_ROOT/comelit-v4-r67-candidate-b"
META_A="$RUN_ROOT/build-a-meta.txt"
META_B="$RUN_ROOT/build-b-meta.txt"
STRINGS_A="$RUN_ROOT/build-a.strings"
COMPILE_INPUT_NAME="r67-build-input.c"
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
echo "R67_TRANSFORM_BLOB_SHA256=$TRANSFORM_SHA"
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
    'R42_MEDIAREQ26_OPEN_PROFILE=CAPTURE_VALIDATED' \
    'R54_CALL_ADOPTION_STARTED=%s' \
    'R64_POST_CALL_SNAPSHOT=true' \
    'V4_DOOR_PATH=CALL_TIME_SINGLE' \
    'P12_TX_CALL_TIME_DOOR' \
    'R67_ATTACHED_REFRESH_CADENCE_SECONDS=%u' \
    'R67_ATTACHED_REFRESH_SENT_COUNT=%u' \
    'R67_ATTACHED_REFRESH_FIRST_AGE_SECONDS=%u' \
    'R67_ATTACHED_REFRESH_LAST_AGE_SECONDS=%u' \
    'R67_ATTACHED_REFRESH_LAST_RESULT=%s' \
    'R67_ATTACHED_REFRESH_LAST_ERROR=%s' \
    'R67_ATTACHED_REFRESH_OPCODE=0x0011' \
    'R67_ATTACHED_REFRESH_FRAME=MEDIAREQ26_OPEN' \
    'P12_TX_R67_ATTACHED_REFRESH'
do
    grep -Fq "$marker" "$SOURCE_A"
done

for forbidden in \
    '/run/comelit-media' \
    'signal(SIGUSR1, SIG_IGN);' \
    'entrance_self_activation' \
    'P12_TX_ENTRANCE_SELF_ACTIVATION'
do
    forbidden_count="$(awk -v needle="$forbidden" '
        {
            line = $0
            while ((pos = index(line, needle)) > 0) {
                count++
                line = substr(line, pos + length(needle))
            }
        }
        END { print count + 0 }
    ' "$SOURCE_A")"
    echo "R67_WHOLE_SOURCE_FORBIDDEN_COUNT needle=$forbidden count=$forbidden_count"
    if [[ "$forbidden_count" != 0 ]]; then
        echo "R67_FORBIDDEN_MARKER_GATE=FAIL needle=$forbidden"
        exit 1
    fi
done

for forbidden in \
    '/p2p/start' \
    'nice_agent_new' \
    'pseudo_tcp_socket_new'
do
    forbidden_count="$(awk -v needle="$forbidden" '
        index($0, "/* R67_ATTACHED_MEDIA_REFRESH_BEGIN */") { in_region = 1 }
        in_region {
            line = $0
            while ((pos = index(line, needle)) > 0) {
                count++
                line = substr(line, pos + length(needle))
            }
        }
        index($0, "/* R67_ATTACHED_MEDIA_REFRESH_END */") { in_region = 0 }
        END { print count + 0 }
    ' "$SOURCE_A")"
    echo "R67_REGION_FORBIDDEN_COUNT needle=$forbidden count=$forbidden_count"
    if [[ "$forbidden_count" != 0 ]]; then
        echo "R67_FORBIDDEN_MARKER_GATE=FAIL needle=$forbidden"
        exit 1
    fi
done
echo 'R67_SOURCE_MARKER_GATE=PASS'

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

stage_compile_input() {
    local from=$1 expected_sha=$2
    cp "$from" "$COMPILE_INPUT"
    local staged_sha
    staged_sha="$(sha "$COMPILE_INPUT")"
    [[ "$staged_sha" == "$expected_sha" ]]
    echo "$staged_sha"
}

BUILD_A_COMPILE_INPUT_SHA256="$(stage_compile_input "$SOURCE_A" "$SOURCE_A_SHA")"
echo "COMPILE_INPUT_NAME=$COMPILE_INPUT_NAME"
echo "BUILD_A_COMPILE_INPUT_SHA256=$BUILD_A_COMPILE_INPUT_SHA256"
build_once "$COMPILE_INPUT_NAME" "$(basename "$BUILD_A")" "$(basename "$META_A")"

BUILD_B_COMPILE_INPUT_SHA256="$(stage_compile_input "$SOURCE_B" "$SOURCE_B_SHA")"
echo "BUILD_B_COMPILE_INPUT_SHA256=$BUILD_B_COMPILE_INPUT_SHA256"
build_once "$COMPILE_INPUT_NAME" "$(basename "$BUILD_B")" "$(basename "$META_B")"
echo 'COMPILE_INPUT_STAGE_GATE=PASS'

BUILD_A_SHA="$(sha "$BUILD_A")"
BUILD_B_SHA="$(sha "$BUILD_B")"
[[ "$BUILD_A_SHA" == "$BUILD_B_SHA" ]]
cmp -s "$BUILD_A" "$BUILD_B"
echo 'REPRODUCIBLE_BINARY_CMP_GATE=PASS'

grep -Fq "interpreter=$EXPECTED_INTERPRETER" "$META_A"
grep -Fq "interpreter=$EXPECTED_INTERPRETER" "$META_B"
grep -Fq "needed_sorted=$EXPECTED_NEEDED" "$META_A"
grep -Fq "needed_sorted=$EXPECTED_NEEDED" "$META_B"
echo 'MUSL_INTERPRETER_GATE=PASS'
echo 'NO_NEW_RUNTIME_DEPENDENCY=PASS'

strings -a "$BUILD_A" > "$STRINGS_A"
for marker in \
    'R67_ATTACHED_REFRESH_CADENCE_SECONDS=%u' \
    'R67_ATTACHED_REFRESH_SENT_COUNT=%u' \
    'R67_ATTACHED_REFRESH_LAST_RESULT=%s' \
    'R67_ATTACHED_REFRESH_LAST_ERROR=%s' \
    'R67_ATTACHED_REFRESH_OPCODE=0x0011' \
    'R67_ATTACHED_REFRESH_FRAME=MEDIAREQ26_OPEN' \
    'V4_DOOR_PATH=CALL_TIME_SINGLE'
do
    grep -Fq "$marker" "$STRINGS_A"
done
echo 'R67_BINARY_MARKER_GATE=PASS'

BYTES_A="$(stat -c '%s' "$BUILD_A")"
echo '=== COMELIT P116 R67 LISTENER CANDIDATE BUILD ==='
echo "RUN_ROOT=$RUN_ROOT"
echo "SOURCE_A=$SOURCE_A"
echo "SOURCE_SHA256=$SOURCE_A_SHA"
echo "CANDIDATE_A=$BUILD_A"
echo "CANDIDATE_B=$BUILD_B"
echo "BINARY_SHA256=$BUILD_A_SHA"
echo "BINARY_BYTES=$BYTES_A"
echo 'CANDIDATE_EXECUTED=false'
echo 'NETWORK_IO_PERFORMED=false'
echo 'HA_DEPLOY_PERFORMED=false'
echo 'DOOR_ACTION_SENT=false'
echo 'GATE_ACTION_SENT=false'
echo 'R67_BUILD=PASS'
