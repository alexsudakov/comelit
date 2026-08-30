#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
POC_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(git -C "$POC_ROOT" rev-parse --show-toplevel)"

BUILD_DIR=/root/comelit-p12-readonly-candidate
SRC="$BUILD_DIR/comelit_ice_offer_holder.p12-readonly.c"
BIN="$BUILD_DIR/comelit_ice_offer_holder.p12-readonly"
WRAP="$BUILD_DIR/comelit-p2p-cloud-probe-p12-readonly"
BUILD_MANIFEST="$BUILD_DIR/MANIFEST.txt"
BUILD_SUMS="$BUILD_DIR/SHA256SUMS"

EXPECTED_BUILD_HEAD=150d594072aa1d999c99679d5451772e65c6554f
EXPECTED_BUILD_TREE=16531cebda2d407b157056dfd5a9836c211a89ec
EXPECTED_SRC_SHA=b8215df5008133c38fa57a31aae63f7cbf734710fa322aa641de2da08b8015ab
EXPECTED_BIN_SHA=bae10046aa4a449e0e1bb56315308592aaf06b82049c80291871d6485b55668c
EXPECTED_WRAP_SHA=7eb9c4e8999dc6c6f15ac03344abd155a042482158352fadbca58a3f4fd91ce1
EXPECTED_BASE_SOURCE_SHA=d8c3bd50c33d702699b96c24f08363bb06f3b5312b3033aceead9ed67a6ce9d9
EXPECTED_BASE_BINARY_SHA=628b9c020bd3948d5edae2b7a6d68061c8af2b3a72e26463f2f5486f1e61d9de
EXPECTED_BASE_WRAPPER_SHA=a564535dff0cf10b1fe4766171f2960c52fb581f1c816cf81d2992c5c84e79c9

ORIGINAL_BRANCH="$(git -C "$REPO_ROOT" branch --show-current)"
COLLECTOR_HEAD="$(git -C "$REPO_ROOT" rev-parse HEAD)"
COLLECTOR_TREE="$(git -C "$REPO_ROOT" rev-parse HEAD^{tree})"
[[ -n "$ORIGINAL_BRANCH" ]] || { echo "P12_STATIC_EVIDENCE_REQUIRES_NAMED_BRANCH=true"; exit 1; }
[[ -z "$(git -C "$REPO_ROOT" status --porcelain)" ]] || {
    echo "P12_STATIC_EVIDENCE_REQUIRES_CLEAN_WORKTREE=true"
    git -C "$REPO_ROOT" status --short
    exit 1
}

for p in "$SRC" "$BIN" "$WRAP" "$BUILD_MANIFEST" "$BUILD_SUMS"; do
    [[ -f "$p" ]] || { echo "P12_STATIC_EVIDENCE_FILE_MISSING=$p"; exit 1; }
done

src_sha="$(sha256sum "$SRC" | awk '{print $1}')"
bin_sha="$(sha256sum "$BIN" | awk '{print $1}')"
wrap_sha="$(sha256sum "$WRAP" | awk '{print $1}')"
[[ "$src_sha" == "$EXPECTED_SRC_SHA" ]] || { echo "P12_STATIC_SOURCE_PIN=FAIL"; exit 1; }
[[ "$bin_sha" == "$EXPECTED_BIN_SHA" ]] || { echo "P12_STATIC_BINARY_PIN=FAIL"; exit 1; }
[[ "$wrap_sha" == "$EXPECTED_WRAP_SHA" ]] || { echo "P12_STATIC_WRAPPER_PIN=FAIL"; exit 1; }

grep -Fxq "REPOSITORY_HEAD=$EXPECTED_BUILD_HEAD" "$BUILD_MANIFEST"
grep -Fxq "REPOSITORY_TREE=$EXPECTED_BUILD_TREE" "$BUILD_MANIFEST"
grep -Fxq "CANDIDATE_SOURCE_SHA256=$EXPECTED_SRC_SHA" "$BUILD_MANIFEST"
grep -Fxq "CANDIDATE_BINARY_SHA256=$EXPECTED_BIN_SHA" "$BUILD_MANIFEST"
grep -Fxq "CANDIDATE_WRAPPER_SHA256=$EXPECTED_WRAP_SHA" "$BUILD_MANIFEST"
grep -Fxq "BASELINE_FILES_MUTATED=false" "$BUILD_MANIFEST"
grep -Fxq "SECRETS_READ=false" "$BUILD_MANIFEST"
grep -Fxq "NETWORK_ACTION_PERFORMED=false" "$BUILD_MANIFEST"
grep -Fxq "ACTUATOR_COMMAND_ATTEMPTED=false" "$BUILD_MANIFEST"
grep -Fxq "PHYSICAL_DOOR_ACTION=false" "$BUILD_MANIFEST"
grep -Fxq "LIVE_TEST_READY=false" "$BUILD_MANIFEST"

(
    cd "$BUILD_DIR"
    sha256sum -c SHA256SUMS >/dev/null
)

[[ "$(stat -c '%a' "$SRC")" == "600" ]]
[[ "$(stat -c '%a' "$BIN")" == "700" ]]
[[ "$(stat -c '%a' "$WRAP")" == "700" ]]
[[ "$(stat -c '%a' "$BUILD_MANIFEST")" == "600" ]]

readelf -h "$BIN" >/dev/null
bash -n "$WRAP"

if grep -Eq 'CTPP|OPEN_DOOR|open_door|create_door_message' "$SRC"; then
    echo "P12_STATIC_SOURCE_ACTUATOR_SCAN=FAIL"
    exit 1
fi
if strings -a "$BIN" | grep -Eq 'CTPP|OPEN_DOOR|open_door|create_door_message'; then
    echo "P12_STATIC_BINARY_ACTUATOR_SCAN=FAIL"
    exit 1
fi
if grep -Eq 'CTPP|OPEN_DOOR|open_door|create_door_message' "$WRAP"; then
    echo "P12_STATIC_WRAPPER_ACTUATOR_SCAN=FAIL"
    exit 1
fi
[[ "$(grep -Fc "$BIN" "$WRAP")" -eq 1 ]]
if grep -Fq '"$BASE/bin/comelit_ice_offer_holder"' "$WRAP"; then
    echo "P12_STATIC_WRAPPER_BASELINE_HOLDER_REMAINS=true"
    exit 1
fi

base_source_sha="$(sha256sum /root/comelit-vip-poc/bin/comelit_ice_offer_holder.c | awk '{print $1}')"
base_binary_sha="$(sha256sum /root/comelit-vip-poc/bin/comelit_ice_offer_holder | awk '{print $1}')"
base_wrapper_sha="$(sha256sum /usr/local/sbin/comelit-p2p-cloud-probe | awk '{print $1}')"
[[ "$base_source_sha" == "$EXPECTED_BASE_SOURCE_SHA" ]]
[[ "$base_binary_sha" == "$EXPECTED_BASE_BINARY_SHA" ]]
[[ "$base_wrapper_sha" == "$EXPECTED_BASE_WRAPPER_SHA" ]]

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
EVIDENCE_BRANCH="evidence/p12-candidate-static-${STAMP}"
EVIDENCE_REL="evidence/p12-candidate-static/${STAMP}"
EVIDENCE_DIR="$REPO_ROOT/$EVIDENCE_REL"

git -C "$REPO_ROOT" switch -c "$EVIDENCE_BRANCH"
mkdir -p "$EVIDENCE_DIR"

cleanup() {
    rc=$?
    if [[ $rc -ne 0 ]]; then
        echo "P12_CANDIDATE_STATIC_EVIDENCE_FAILED_RC=$rc"
        git -C "$REPO_ROOT" switch "$ORIGINAL_BRANCH" >/dev/null 2>&1 || true
    fi
    return "$rc"
}
trap cleanup EXIT

cat > "$EVIDENCE_DIR/MANIFEST.txt" <<EOF
EVIDENCE_SCHEMA=1
COLLECTED_AT_UTC=$STAMP
COLLECTOR_SOURCE_BRANCH=$ORIGINAL_BRANCH
COLLECTOR_SOURCE_HEAD=$COLLECTOR_HEAD
COLLECTOR_SOURCE_TREE=$COLLECTOR_TREE
CANDIDATE_BUILD_HEAD=$EXPECTED_BUILD_HEAD
CANDIDATE_BUILD_TREE=$EXPECTED_BUILD_TREE
CANDIDATE_SOURCE_SHA256=$src_sha
CANDIDATE_BINARY_SHA256=$bin_sha
CANDIDATE_WRAPPER_SHA256=$wrap_sha
BASELINE_SOURCE_SHA256=$base_source_sha
BASELINE_BINARY_SHA256=$base_binary_sha
BASELINE_WRAPPER_SHA256=$base_wrapper_sha
P12_BUILD_MANIFEST_IDENTITY=PASS
P12_BUILD_SHA256SUMS=PASS
P12_CANDIDATE_MODES=PASS
P12_CANDIDATE_ELF=PASS
P12_CANDIDATE_WRAPPER_PARSE=PASS
P12_ACTUATOR_SURFACE_SCAN=PASS
P12_WRAPPER_EXACT_BINDING=PASS
P12_BASELINE_STILL_PINNED=PASS
PUBLIC_SAFE=true
CANDIDATE_EXECUTED=false
WRAPPER_EXECUTED=false
SECRETS_CONTENT_READ=false
CREDENTIAL_VALUES_COLLECTED=false
ACTIVE_COMELIT_NETWORK_PROBES=false
ACTUATOR_COMMAND_ATTEMPTED=false
PHYSICAL_DOOR_ACTION=false
READONLY_TRANSPORT_READY=false
LIVE_TEST_READY=false
P12_STATIC_CANDIDATE_VALIDATION=PASS
EOF

file "$BIN" | sed "s#^$BIN:#CANDIDATE_BINARY_FILE:#" > "$EVIDENCE_DIR/elf_metadata.txt"
{
    echo "SOURCE_MODE=$(stat -c '%a' "$SRC")"
    echo "BINARY_MODE=$(stat -c '%a' "$BIN")"
    echo "WRAPPER_MODE=$(stat -c '%a' "$WRAP")"
    echo "MANIFEST_MODE=$(stat -c '%a' "$BUILD_MANIFEST")"
} > "$EVIDENCE_DIR/modes.txt"

(
    cd "$EVIDENCE_DIR"
    sha256sum ./*.txt | sort > SHA256SUMS
)

if grep -RIEq 'https?://|Authorization:[[:space:]]|Bearer[[:space:]]|ccstoken[[:space:]]|github_pat_|ghp_|-----BEGIN .*PRIVATE KEY-----' "$EVIDENCE_DIR"; then
    echo "P12_STATIC_EVIDENCE_SECRET_SCAN=FAIL"
    exit 1
fi
if grep -RIEq 'SECRETS_CONTENT_READ=true|CREDENTIAL_VALUES_COLLECTED=true|ACTIVE_COMELIT_NETWORK_PROBES=true|ACTUATOR_COMMAND_ATTEMPTED=true|PHYSICAL_DOOR_ACTION=true' "$EVIDENCE_DIR"; then
    echo "P12_STATIC_EVIDENCE_SAFETY_SCAN=FAIL"
    exit 1
fi

git -C "$REPO_ROOT" add "$EVIDENCE_REL"
git -C "$REPO_ROOT" diff --cached --check
if git -C "$REPO_ROOT" diff --cached --name-only | grep -Ev "^${EVIDENCE_REL}/" >/dev/null; then
    echo "P12_STATIC_EVIDENCE_SCOPE_CHECK=FAIL"
    exit 1
fi

git -C "$REPO_ROOT" commit -m "evidence: collect P12 static candidate ${STAMP}"
EVIDENCE_COMMIT="$(git -C "$REPO_ROOT" rev-parse HEAD)"
git -C "$REPO_ROOT" push -u origin "$EVIDENCE_BRANCH"

echo "P12_CANDIDATE_STATIC_BRANCH=$EVIDENCE_BRANCH"
echo "P12_CANDIDATE_STATIC_COMMIT=$EVIDENCE_COMMIT"
echo "P12_CANDIDATE_STATIC_PATH=$EVIDENCE_REL"
echo "P12_BUILD_MANIFEST_IDENTITY=PASS"
echo "P12_BUILD_SHA256SUMS=PASS"
echo "P12_CANDIDATE_MODES=PASS"
echo "P12_CANDIDATE_ELF=PASS"
echo "P12_CANDIDATE_WRAPPER_PARSE=PASS"
echo "P12_ACTUATOR_SURFACE_SCAN=PASS"
echo "P12_WRAPPER_EXACT_BINDING=PASS"
echo "P12_BASELINE_STILL_PINNED=PASS"
echo "CANDIDATE_EXECUTED=false"
echo "WRAPPER_EXECUTED=false"
echo "SECRETS_CONTENT_READ=false"
echo "ACTIVE_COMELIT_NETWORK_PROBES=false"
echo "ACTUATOR_COMMAND_ATTEMPTED=false"
echo "PHYSICAL_DOOR_ACTION=false"
echo "READONLY_TRANSPORT_READY=false"
echo "LIVE_TEST_READY=false"
echo "P12_CANDIDATE_STATIC_EVIDENCE=PASS"

git -C "$REPO_ROOT" switch "$ORIGINAL_BRANCH"
trap - EXIT
echo "RETURNED_TO_BRANCH=$ORIGINAL_BRANCH"
