#!/usr/bin/env bash
# Offline CT122 builder for the P116/R42 attached inbound media candidate.
#
# Generates canonical -> R35 -> R36 -> R37 -> R42 and compiles the exact same
# generated source twice inside isolated Alpine/musl containers with
# --network none. The two binaries must be byte-identical.
#
# This script does NOT execute the candidate, install it into the integration,
# deploy Home Assistant, start a Comelit session, or perform Door/Gate actions.
set -Eeuo pipefail
umask 077

REPO=${REPO:-/home/hermes/repos/comelit}
SAFETY_POC="$REPO/safety-poc"
MEDIA="$SAFETY_POC/research/media/v1"
SOURCE="$SAFETY_POC/research/door/v1_5_7/comelit-v4-persistent-ctpp-door.c"

EXPECTED_CANONICAL_SHA=1c89d61de4372d96b25f6894862741244753c107a3a9b9e04817250b3bea55b2
EXPECTED_R35_SHA=5aa1662c2f75d01033c8ba6c773bffc6e8bb289a41f2e16fed417635ce1380a0
EXPECTED_R36_SHA=59262cd3ff1ff87b2ac8612fc38e5d0c3c789e6bbad9204e5a20915c237cc1b5
EXPECTED_R37_SHA=d314efcecc10b2656fa069c069833c9d8815c8753749554e8b83702241a0950a

APK_CLOSURE=${APK_CLOSURE:-/home/hermes/musl-apk-closure-p80}
ALPINE_IMAGE=${ALPINE_IMAGE:-alpine:3.24.1}
EXPECTED_INTERPRETER=/lib/ld-musl-x86_64.so.1
EXPECTED_NEEDED=libc.musl-x86_64.so.1,libglib-2.0.so.0,libgobject-2.0.so.0,libnice.so.10

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
RUN_ROOT=${RUN_ROOT:-/home/hermes/comelit-r42-build-$STAMP}
mkdir -p "$RUN_ROOT"
chmod 700 "$RUN_ROOT"

CANONICAL="$RUN_ROOT/canonical.c"
R35="$RUN_ROOT/r35.c"
R36="$RUN_ROOT/r36.c"
R37="$RUN_ROOT/r37.c"
R42="$RUN_ROOT/r42.c"
BUILD_A="$RUN_ROOT/comelit-v4-r42-candidate-a"
BUILD_B="$RUN_ROOT/comelit-v4-r42-candidate-b"
META_A="$RUN_ROOT/build-a-meta.txt"
META_B="$RUN_ROOT/build-b-meta.txt"
STRINGS_A="$RUN_ROOT/build-a.strings"

sha() { sha256sum "$1" | awk '{print $1}'; }

gate_sha() {
    local name=$1 file=$2 expected=$3 actual
    actual="$(sha "$file")"
    echo "${name}_SHA256=$actual"
    if [[ "$actual" != "$expected" ]]; then
        echo "${name}_SHA_GATE=FAIL"
        return 1
    fi
    echo "${name}_SHA_GATE=PASS"
}

for c in git python3 docker sha256sum readelf strings grep awk sort paste stat cmp; do
    command -v "$c" >/dev/null
done

[[ "$(id -u)" -ne 0 ]]
[[ -d "$REPO/.git" || -f "$REPO/.git" ]]
[[ -d "$APK_CLOSURE" ]]

rm -f     "$CANONICAL" "$R35" "$R36" "$R37" "$R42"     "$BUILD_A" "$BUILD_B" "$META_A" "$META_B" "$STRINGS_A"

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$MEDIA" python3 "$MEDIA/entrance_p106_teardown_state_classification_transform.py"     --source "$SOURCE"     --output "$CANONICAL"     --include-p116
gate_sha CANONICAL "$CANONICAL" "$EXPECTED_CANONICAL_SHA"

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$MEDIA" python3 "$MEDIA/entrance_p116_r35_attached_media_native_transform.py"     --source "$CANONICAL"     --output "$R35"
gate_sha R35 "$R35" "$EXPECTED_R35_SHA"

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$MEDIA" python3 "$MEDIA/entrance_p116_r36_attached_media_trigger_transform.py"     --source "$R35"     --output "$R36"
gate_sha R36 "$R36" "$EXPECTED_R36_SHA"

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$MEDIA" python3 "$MEDIA/entrance_p116_r37_attached_media_live_readiness_transform.py"     --source "$R36"     --output "$R37"
gate_sha R37 "$R37" "$EXPECTED_R37_SHA"

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$MEDIA" python3 "$MEDIA/entrance_p116_r42_attached_media_runtime_transform.py"     --source "$R37"     --output "$R42"

R42_SHA="$(sha "$R42")"

for marker in     'R42_ATTACHED_INBOUND_MEDIA_RUNTIME_BEGIN'     'R42_ATTACHED_TRIGGER_BEGIN'     'R42_MEDIA_CHANNEL_ALLOCATED=true'     'R42_MEDIAREQ26_OPEN_PROFILE=CAPTURE_VALIDATED'     'R42_ATTACHED_MEDIA_ACTIVE=true'     'R42_ATTACHED_MEDIA_STOP_SENT=true'     'R42_MEDIA_CHANNEL_CLOSE_SENT=true'     'R42_MEDIA_CHANNEL_CLOSED=true'     'R42_AUTOMATIC_RETRY=false'     'P80_VIDEO_RTP_FORWARDING=PASS'
do
    grep -Fq "$marker" "$R42"
done

if grep -Eq '0x0[Cc]4[Aa]|0x4[Aa]5[Aa]|0x[Cc][Aa]5[Aa]' "$R42"; then
    echo 'CAPTURE_LITERAL_GATE=FAIL'
    exit 1
fi

cat > "$RUN_ROOT/build.sh" <<'EOS'
set -eu
: "${OUT:?OUT is required}"
: "${META:?META is required}"

apk add --no-network --allow-untrusted /pkgs/*.apk >/dev/null

cc -O2 -g -Wall -Wextra -Wl,--as-needed     -o "/w/$OUT"     /w/r42.c     $(pkg-config --cflags --libs nice glib-2.0 gio-2.0 gobject-2.0)

chmod 755 "/w/$OUT"

readelf -l "/w/$OUT"     | sed -n 's@.*Requesting program interpreter: \(.*\)]@interpreter=\1@p'     > "/w/$META"

readelf -d "/w/$OUT"     | sed -n 's/.*Shared library: \[\(.*\)\]/\1/p'     | sort     | paste -sd, -     | sed 's/^/needed_sorted=/'     >> "/w/$META"
EOS
chmod 700 "$RUN_ROOT/build.sh"

build_once() {
    local out_name=$1 meta_name=$2
    timeout 900 docker run --rm --network none         --security-opt apparmor=unconfined         -e OUT="$out_name"         -e META="$meta_name"         -v "$RUN_ROOT":/w         -v "$APK_CLOSURE":/pkgs:ro         "$ALPINE_IMAGE"         /bin/sh /w/build.sh
}

build_once "$(basename "$BUILD_A")" "$(basename "$META_A")"
build_once "$(basename "$BUILD_B")" "$(basename "$META_B")"

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
for marker in     'R42_MEDIA_CHANNEL_ALLOCATED=true'     'R42_MEDIAREQ26_OPEN_PROFILE=CAPTURE_VALIDATED'     'R42_ATTACHED_MEDIA_ACTIVE=true'     'R42_ATTACHED_MEDIA_STOP_SENT=true'     'R42_MEDIA_CHANNEL_CLOSE_SENT=true'     'R42_MEDIA_CHANNEL_CLOSED=true'     'P80_VIDEO_RTP_FORWARDING=PASS'     'ENTRANCE_SIGNALING_DOOR_ACTION_SENT=false'
do
    grep -Fq "$marker" "$STRINGS_A"
done

BUILD_BYTES="$(stat -c '%s' "$BUILD_A")"

echo '=== COMELIT P116 R42 OFFLINE BUILD SUMMARY ==='
echo "REPO_HEAD=$(git -C "$REPO" rev-parse HEAD)"
echo "R42_GENERATED_SOURCE=$R42"
echo "R42_GENERATED_SOURCE_SHA256=$R42_SHA"
echo "CANDIDATE_PATH=$BUILD_A"
echo "CANDIDATE_REPRODUCIBLE_PEER=$BUILD_B"
echo "CANDIDATE_SHA256=$BUILD_A_SHA"
echo "BUILD_A_SHA256=$BUILD_A_SHA"
echo "BUILD_B_SHA256=$BUILD_B_SHA"
echo "CANDIDATE_BYTES=$BUILD_BYTES"
echo "INTERPRETER=$INTERPRETER_A"
echo "NEEDED=$NEEDED_A"
echo 'REPRODUCIBLE_BINARY_SHA_GATE=PASS'
echo 'REPRODUCIBLE_BINARY_CMP_GATE=PASS'
echo 'CAPTURE_LITERAL_GATE=PASS'
echo 'CANDIDATE_EXECUTED=false'
echo 'COMELIT_NETWORK_REQUESTS=0'
echo 'LISTENER_CHANGED=NO'
echo 'HA_CORE_CHANGED=NO'
echo 'DOOR_ACTION_SENT=false'
echo 'GATE_ACTION_SENT=false'
echo 'R42_CANDIDATE_BUILD=PASS'
