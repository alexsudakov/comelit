#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
POC_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(git -C "$POC_ROOT" rev-parse --show-toplevel)"

BASE_SOURCE=/root/comelit-vip-poc/bin/comelit_ice_offer_holder.c
BASE_BINARY=/root/comelit-vip-poc/bin/comelit_ice_offer_holder
BASE_WRAPPER=/usr/local/sbin/comelit-p2p-cloud-probe
CANONICAL_ROOT=/root/comelit-vip-poc
BUILD_DIR=/root/comelit-p12-readonly-candidate
CANDIDATE_SOURCE="$BUILD_DIR/comelit_ice_offer_holder.p12-readonly.c"
CANDIDATE_BINARY="$BUILD_DIR/comelit_ice_offer_holder.p12-readonly"
CANDIDATE_WRAPPER="$BUILD_DIR/comelit-p2p-cloud-probe-p12-readonly"
TEMPLATES="$BUILD_DIR/protocol_templates.json"
MANIFEST="$BUILD_DIR/MANIFEST.txt"

EXPECTED_SOURCE_SHA=d8c3bd50c33d702699b96c24f08363bb06f3b5312b3033aceead9ed67a6ce9d9
EXPECTED_BINARY_SHA=628b9c020bd3948d5edae2b7a6d68061c8af2b3a72e26463f2f5486f1e61d9de
EXPECTED_WRAPPER_SHA=a564535dff0cf10b1fe4766171f2960c52fb581f1c816cf81d2992c5c84e79c9

[[ -f "$BASE_SOURCE" && -f "$BASE_BINARY" && -f "$BASE_WRAPPER" ]] || {
    echo "P12_BASELINE_FILES_PRESENT=false"
    exit 1
}

source_sha="$(sha256sum "$BASE_SOURCE" | awk '{print $1}')"
binary_sha="$(sha256sum "$BASE_BINARY" | awk '{print $1}')"
wrapper_sha="$(sha256sum "$BASE_WRAPPER" | awk '{print $1}')"

[[ "$source_sha" == "$EXPECTED_SOURCE_SHA" ]] || { echo "P12_BASELINE_SOURCE_PIN=FAIL"; exit 1; }
[[ "$binary_sha" == "$EXPECTED_BINARY_SHA" ]] || { echo "P12_BASELINE_BINARY_PIN=FAIL"; exit 1; }
[[ "$wrapper_sha" == "$EXPECTED_WRAPPER_SHA" ]] || { echo "P12_BASELINE_WRAPPER_PIN=FAIL"; exit 1; }

[[ -z "$(git -C "$REPO_ROOT" status --porcelain)" ]] || {
    echo "P12_CANDIDATE_REQUIRES_CLEAN_WORKTREE=true"
    git -C "$REPO_ROOT" status --short
    exit 1
}

rm -rf -- "$BUILD_DIR"
mkdir -p "$BUILD_DIR"
chmod 700 "$BUILD_DIR"

python3 "$SCRIPT_DIR/p12_application_templates.py" \
    --canonical-root "$CANONICAL_ROOT" \
    --output "$TEMPLATES" \
    | tee "$BUILD_DIR/10_templates.txt"

python3 "$SCRIPT_DIR/p12_holder_transform_safe.py" \
    --source "$BASE_SOURCE" \
    --templates "$TEMPLATES" \
    --output "$CANDIDATE_SOURCE" \
    | tee "$BUILD_DIR/20_transform.txt"

chmod 600 "$CANDIDATE_SOURCE"

if grep -Eq 'CTPP|OPEN_DOOR|open_door|create_door_message' "$CANDIDATE_SOURCE"; then
    echo "P12_CANDIDATE_SOURCE_ACTUATOR_SCAN=FAIL"
    exit 1
fi

grep -q 'P2_VIP_UAUT_AUTH=PASS' "$CANDIDATE_SOURCE"
grep -q 'UCFG_RECEIVED=true' "$CANDIDATE_SOURCE"
grep -q 'P12_READONLY_TRANSACTION=PASS' "$CANDIDATE_SOURCE"
grep -q 'LIVE_TEST_READY=false' "$CANDIDATE_SOURCE"

cc -O2 -Wall -Wextra \
    -o "$CANDIDATE_BINARY" \
    "$CANDIDATE_SOURCE" \
    $(pkg-config --cflags --libs nice glib-2.0 gio-2.0 gobject-2.0) \
    2> "$BUILD_DIR/30_compile.stderr"

chmod 700 "$CANDIDATE_BINARY"

if strings -a "$CANDIDATE_BINARY" | grep -Eq 'CTPP|OPEN_DOOR|open_door|create_door_message'; then
    echo "P12_CANDIDATE_BINARY_ACTUATOR_SCAN=FAIL"
    exit 1
fi

strings -a "$CANDIDATE_BINARY" | grep -q 'P2_VIP_UAUT_AUTH=PASS'
strings -a "$CANDIDATE_BINARY" | grep -q 'UCFG_RECEIVED=true'
strings -a "$CANDIDATE_BINARY" | grep -q 'P12_READONLY_TRANSACTION=PASS'
strings -a "$CANDIDATE_BINARY" | grep -q 'LIVE_TEST_READY=false'

python3 - "$BASE_WRAPPER" "$CANDIDATE_WRAPPER" "$CANDIDATE_BINARY" <<'PY'
from pathlib import Path
import sys

src = Path(sys.argv[1])
out = Path(sys.argv[2])
candidate = sys.argv[3]
text = src.read_text(encoding="utf-8")
needle = '"$BASE/bin/comelit_ice_offer_holder"'
count = text.count(needle)
if count != 1:
    raise SystemExit(f"P12_WRAPPER_HOLDER_PATH_COUNT={count}")
text = text.replace(needle, f'"{candidate}"', 1)
out.write_text(text, encoding="utf-8")
PY

chmod 700 "$CANDIDATE_WRAPPER"
bash -n "$CANDIDATE_WRAPPER"

if grep -Eq 'CTPP|OPEN_DOOR|open_door|create_door_message' "$CANDIDATE_WRAPPER"; then
    echo "P12_CANDIDATE_WRAPPER_ACTUATOR_SCAN=FAIL"
    exit 1
fi

grep -Fq "$CANDIDATE_BINARY" "$CANDIDATE_WRAPPER"
if grep -Fq '"$BASE/bin/comelit_ice_offer_holder"' "$CANDIDATE_WRAPPER"; then
    echo "P12_CANDIDATE_WRAPPER_BASELINE_HOLDER_REMAINS=true"
    exit 1
fi

echo "P12_CANDIDATE_WRAPPER_BINDING=PASS"

# Build stage must never touch credential contents or execute a Comelit network probe.
if grep -RIEq 'SECRETS_READ=true|NETWORK_ACTION_PERFORMED=true|ACTUATOR_COMMAND_ATTEMPTED=true|PHYSICAL_DOOR_ACTION=true' "$BUILD_DIR"; then
    echo "P12_CANDIDATE_BUILD_SAFETY_SCAN=FAIL"
    exit 1
fi

source_sha_after="$(sha256sum "$BASE_SOURCE" | awk '{print $1}')"
binary_sha_after="$(sha256sum "$BASE_BINARY" | awk '{print $1}')"
wrapper_sha_after="$(sha256sum "$BASE_WRAPPER" | awk '{print $1}')"
[[ "$source_sha_after" == "$EXPECTED_SOURCE_SHA" ]] || { echo "P12_BASELINE_SOURCE_MUTATED=true"; exit 1; }
[[ "$binary_sha_after" == "$EXPECTED_BINARY_SHA" ]] || { echo "P12_BASELINE_BINARY_MUTATED=true"; exit 1; }
[[ "$wrapper_sha_after" == "$EXPECTED_WRAPPER_SHA" ]] || { echo "P12_BASELINE_WRAPPER_MUTATED=true"; exit 1; }

candidate_source_sha="$(sha256sum "$CANDIDATE_SOURCE" | awk '{print $1}')"
candidate_binary_sha="$(sha256sum "$CANDIDATE_BINARY" | awk '{print $1}')"
candidate_wrapper_sha="$(sha256sum "$CANDIDATE_WRAPPER" | awk '{print $1}')"
templates_sha="$(sha256sum "$TEMPLATES" | awk '{print $1}')"
repo_head="$(git -C "$REPO_ROOT" rev-parse HEAD)"
repo_tree="$(git -C "$REPO_ROOT" rev-parse HEAD^{tree})"

cat > "$MANIFEST" <<EOF
P12_CANDIDATE_SCHEMA=1
REPOSITORY_HEAD=$repo_head
REPOSITORY_TREE=$repo_tree
BASELINE_SOURCE_SHA256=$EXPECTED_SOURCE_SHA
BASELINE_BINARY_SHA256=$EXPECTED_BINARY_SHA
BASELINE_WRAPPER_SHA256=$EXPECTED_WRAPPER_SHA
PROTOCOL_TEMPLATES_SHA256=$templates_sha
CANDIDATE_SOURCE_SHA256=$candidate_source_sha
CANDIDATE_BINARY_SHA256=$candidate_binary_sha
CANDIDATE_WRAPPER_SHA256=$candidate_wrapper_sha
CANDIDATE_SOURCE=$CANDIDATE_SOURCE
CANDIDATE_BINARY=$CANDIDATE_BINARY
CANDIDATE_WRAPPER=$CANDIDATE_WRAPPER
P12_CANONICAL_TEMPLATE_DERIVATION=PASS
P12_CONTROL_TEMPLATE_EQUIVALENCE=PASS
P12_HOLDER_TRANSFORM_SAFE=PASS
P12_CANDIDATE_SOURCE_ACTUATOR_SCAN=PASS
P12_CANDIDATE_BINARY_ACTUATOR_SCAN=PASS
P12_CANDIDATE_WRAPPER_ACTUATOR_SCAN=PASS
P12_CANDIDATE_WRAPPER_BINDING=PASS
BASELINE_FILES_MUTATED=false
SECRETS_READ=false
NETWORK_ACTION_PERFORMED=false
ACTUATOR_COMMAND_ATTEMPTED=false
PHYSICAL_DOOR_ACTION=false
LIVE_TEST_READY=false
EOF
chmod 600 "$MANIFEST"

(
    cd "$BUILD_DIR"
    sha256sum \
        protocol_templates.json \
        comelit_ice_offer_holder.p12-readonly.c \
        comelit_ice_offer_holder.p12-readonly \
        comelit-p2p-cloud-probe-p12-readonly \
        MANIFEST.txt \
        > SHA256SUMS
)
chmod 600 "$BUILD_DIR/SHA256SUMS"

echo "P12_CANDIDATE_PREPARE=PASS"
echo "P12_REPOSITORY_HEAD=$repo_head"
echo "P12_REPOSITORY_TREE=$repo_tree"
echo "P12_BASELINE_SOURCE_PIN=PASS"
echo "P12_BASELINE_BINARY_PIN=PASS"
echo "P12_BASELINE_WRAPPER_PIN=PASS"
echo "P12_CANONICAL_TEMPLATE_DERIVATION=PASS"
echo "P12_CONTROL_TEMPLATE_EQUIVALENCE=PASS"
echo "P12_HOLDER_TRANSFORM_SAFE=PASS"
echo "P12_CANDIDATE_WRAPPER_BINDING=PASS"
echo "P12_CANDIDATE_SOURCE_SHA256=$candidate_source_sha"
echo "P12_CANDIDATE_BINARY_SHA256=$candidate_binary_sha"
echo "P12_CANDIDATE_WRAPPER_SHA256=$candidate_wrapper_sha"
echo "BASELINE_FILES_MUTATED=false"
echo "SECRETS_READ=false"
echo "NETWORK_ACTION_PERFORMED=false"
echo "ACTUATOR_COMMAND_ATTEMPTED=false"
echo "PHYSICAL_DOOR_ACTION=false"
echo "LIVE_TEST_READY=false"
