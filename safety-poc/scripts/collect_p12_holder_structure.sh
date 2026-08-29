#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
POC_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(git -C "$POC_ROOT" rev-parse --show-toplevel)"
SOURCE=/root/comelit-vip-poc/bin/comelit_ice_offer_holder.c
BINARY=/root/comelit-vip-poc/bin/comelit_ice_offer_holder
EXPECTED_SOURCE_SHA256=d8c3bd50c33d702699b96c24f08363bb06f3b5312b3033aceead9ed67a6ce9d9
EXPECTED_BINARY_SHA256=628b9c020bd3948d5edae2b7a6d68061c8af2b3a72e26463f2f5486f1e61d9de

ORIGINAL_BRANCH="$(git -C "$REPO_ROOT" branch --show-current)"
ORIGINAL_HEAD="$(git -C "$REPO_ROOT" rev-parse HEAD)"
[[ -n "$ORIGINAL_BRANCH" ]] || { echo "P12_HOLDER_STRUCTURE_REQUIRES_NAMED_BRANCH=true"; exit 1; }
[[ -z "$(git -C "$REPO_ROOT" status --porcelain)" ]] || {
    echo "P12_HOLDER_STRUCTURE_REQUIRES_CLEAN_WORKTREE=true"
    git -C "$REPO_ROOT" status --short
    exit 1
}
[[ -f "$SOURCE" && -f "$BINARY" ]] || { echo "P12_HOLDER_BASELINE_PRESENT=false"; exit 1; }

SOURCE_SHA="$(sha256sum "$SOURCE" | awk '{print $1}')"
BINARY_SHA="$(sha256sum "$BINARY" | awk '{print $1}')"
[[ "$SOURCE_SHA" == "$EXPECTED_SOURCE_SHA256" ]] || { echo "P12_HOLDER_SOURCE_PIN=FAIL"; exit 1; }
[[ "$BINARY_SHA" == "$EXPECTED_BINARY_SHA256" ]] || { echo "P12_HOLDER_BINARY_PIN=FAIL"; exit 1; }

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
EVIDENCE_BRANCH="evidence/p12-holder-structure-${STAMP}"
EVIDENCE_REL="evidence/p12-holder-structure/${STAMP}"
EVIDENCE_DIR="$REPO_ROOT/$EVIDENCE_REL"

git -C "$REPO_ROOT" switch -c "$EVIDENCE_BRANCH"
mkdir -p "$EVIDENCE_DIR"

cleanup() {
    rc=$?
    if [[ $rc -ne 0 ]]; then
        echo "P12_HOLDER_STRUCTURE_FAILED_RC=$rc"
        git -C "$REPO_ROOT" switch "$ORIGINAL_BRANCH" >/dev/null 2>&1 || true
    fi
    return "$rc"
}
trap cleanup EXIT

cat > "$EVIDENCE_DIR/MANIFEST.txt" <<EOF
EVIDENCE_SCHEMA=6
COLLECTED_AT_UTC=$STAMP
SOURCE_BRANCH=$ORIGINAL_BRANCH
SOURCE_HEAD=$ORIGINAL_HEAD
PINNED_SOURCE_SHA256=$EXPECTED_SOURCE_SHA256
PINNED_BINARY_SHA256=$EXPECTED_BINARY_SHA256
PUBLIC_SAFE=true
SOURCE_EXECUTED=false
BINARY_EXECUTED=false
SECRETS_CONTENT_READ=false
CREDENTIAL_VALUES_COLLECTED=false
ACTIVE_COMELIT_NETWORK_PROBES=false
ACTUATOR_COMMAND_ATTEMPTED=false
PHYSICAL_DOOR_ACTION=false
EOF

python3 "$SCRIPT_DIR/sanitize_c_source.py" "$SOURCE" \
  --structure-out "$EVIDENCE_DIR/holder_structure.c.txt" \
  --metadata-out "$EVIDENCE_DIR/holder_structure_metadata.txt"

cat > "$EVIDENCE_DIR/baseline_identity.txt" <<EOF
HOLDER_SOURCE_SHA256=$SOURCE_SHA
HOLDER_BINARY_SHA256=$BINARY_SHA
HOLDER_SOURCE_PIN=PASS
HOLDER_BINARY_PIN=PASS
SOURCE_BINARY_PAIR=UAUT_OPEN_BASELINE_134202Z
SOURCE_EXECUTED=false
BINARY_EXECUTED=false
EOF

# Fail closed if the sanitized structural output still contains common sensitive literal shapes.
if grep -Eiq 'https?://|Authorization:[[:space:]]|Bearer[[:space:]]|ccstoken[[:space:]]|github_pat_|ghp_|-----BEGIN .*PRIVATE KEY-----' "$EVIDENCE_DIR"; then
    echo "P12_HOLDER_STRUCTURE_SECRET_SCAN=FAIL"
    exit 1
fi
if grep -Eq '(^|[^0-9])([0-9]{1,3}\.){3}[0-9]{1,3}([^0-9]|$)' "$EVIDENCE_DIR/holder_structure.c.txt"; then
    echo "P12_HOLDER_STRUCTURE_IPV4_SCAN=FAIL"
    exit 1
fi
if grep -Eq '(^|[^A-Fa-f0-9])[A-Fa-f0-9]{32}([^A-Fa-f0-9]|$)' "$EVIDENCE_DIR/holder_structure.c.txt"; then
    echo "P12_HOLDER_STRUCTURE_32HEX_SCAN=FAIL"
    exit 1
fi
if grep -RIEq 'SECRETS_READ=true|CREDENTIAL_VALUES_COLLECTED=true|ACTIVE_COMELIT_NETWORK_PROBES=true|ACTUATOR_COMMAND_ATTEMPTED=true|PHYSICAL_DOOR_ACTION=true' "$EVIDENCE_DIR"; then
    echo "P12_HOLDER_STRUCTURE_SAFETY_SCAN=FAIL"
    exit 1
fi

cat >> "$EVIDENCE_DIR/MANIFEST.txt" <<'EOF'
P12_HOLDER_STRUCTURE_SECRET_SCAN=PASS
P12_HOLDER_STRUCTURE_IPV4_SCAN=PASS
P12_HOLDER_STRUCTURE_32HEX_SCAN=PASS
P12_HOLDER_STRUCTURE_SAFETY_SCAN=PASS
P12_HOLDER_STRUCTURE_COLLECTION=PASS
EOF

(
    cd "$EVIDENCE_DIR"
    sha256sum ./*.txt | sort > SHA256SUMS
)

git -C "$REPO_ROOT" add "$EVIDENCE_REL"
git -C "$REPO_ROOT" diff --cached --check
if git -C "$REPO_ROOT" diff --cached --name-only | grep -Ev "^${EVIDENCE_REL}/" >/dev/null; then
    echo "P12_HOLDER_STRUCTURE_SCOPE_CHECK=FAIL"
    exit 1
fi

git -C "$REPO_ROOT" commit -m "evidence: collect sanitized P12 holder structure ${STAMP}"
EVIDENCE_COMMIT="$(git -C "$REPO_ROOT" rev-parse HEAD)"
git -C "$REPO_ROOT" push -u origin "$EVIDENCE_BRANCH"

echo "P12_HOLDER_STRUCTURE_BRANCH=$EVIDENCE_BRANCH"
echo "P12_HOLDER_STRUCTURE_COMMIT=$EVIDENCE_COMMIT"
echo "P12_HOLDER_STRUCTURE_PATH=$EVIDENCE_REL"
echo "HOLDER_SOURCE_PIN=PASS"
echo "HOLDER_BINARY_PIN=PASS"
echo "PUBLIC_SAFE_EVIDENCE=PASS"
echo "SOURCE_EXECUTED=false"
echo "BINARY_EXECUTED=false"
echo "SECRETS_CONTENT_READ=false"
echo "ACTIVE_COMELIT_NETWORK_PROBES=false"
echo "ACTUATOR_COMMAND_ATTEMPTED=false"
echo "PHYSICAL_DOOR_ACTION=false"

git -C "$REPO_ROOT" switch "$ORIGINAL_BRANCH"
trap - EXIT
echo "RETURNED_TO_BRANCH=$ORIGINAL_BRANCH"
echo "P12_HOLDER_STRUCTURE_COLLECTION=PASS"
