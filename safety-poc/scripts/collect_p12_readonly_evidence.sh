#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
POC_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(git -C "$POC_ROOT" rev-parse --show-toplevel)"
RUNTIME_ROOT=/opt/comelit-door-safety-poc
CURRENT_LINK="$RUNTIME_ROOT/current"

ORIGINAL_BRANCH="$(git -C "$REPO_ROOT" branch --show-current)"
ORIGINAL_HEAD="$(git -C "$REPO_ROOT" rev-parse HEAD)"
[[ -n "$ORIGINAL_BRANCH" ]] || { echo "P12_COLLECTOR_REQUIRES_NAMED_BRANCH=true"; exit 1; }
[[ -z "$(git -C "$REPO_ROOT" status --porcelain)" ]] || {
    echo "P12_COLLECTOR_REQUIRES_CLEAN_WORKTREE=true"
    git -C "$REPO_ROOT" status --short
    exit 1
}

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
EVIDENCE_BRANCH="evidence/p12-readonly-${STAMP}"
EVIDENCE_REL="evidence/p12-readonly/${STAMP}"
EVIDENCE_DIR="$REPO_ROOT/$EVIDENCE_REL"

git -C "$REPO_ROOT" switch -c "$EVIDENCE_BRANCH"
mkdir -p "$EVIDENCE_DIR"

cleanup() {
    rc=$?
    if [[ $rc -ne 0 ]]; then
        echo "P12_COLLECTOR_FAILED_RC=$rc"
        git -C "$REPO_ROOT" switch "$ORIGINAL_BRANCH" >/dev/null 2>&1 || true
    fi
    return "$rc"
}
trap cleanup EXIT

cat > "$EVIDENCE_DIR/MANIFEST.txt" <<EOF
EVIDENCE_SCHEMA=P12_READONLY_V1
COLLECTED_AT_UTC=$STAMP
SOURCE_BRANCH=$ORIGINAL_BRANCH
SOURCE_HEAD=$ORIGINAL_HEAD
PUBLIC_SAFE=true
SOURCE_EXECUTED=false
SECRETS_CONTENT_READ=false
CREDENTIAL_VALUES_COLLECTED=false
REAL_DOOR_PAYLOAD_VALUES_COLLECTED=false
ACTIVE_COMELIT_NETWORK_PROBES=false
ACTUATOR_COMMAND_ATTEMPTED=false
PHYSICAL_DOOR_ACTION=false
EOF

python3 "$SCRIPT_DIR/p12_readonly_source_inventory.py" \
  > "$EVIDENCE_DIR/source_inventory.txt"

{
    echo "=== REPOSITORY IDENTITY ==="
    echo "SOURCE_BRANCH=$ORIGINAL_BRANCH"
    echo "SOURCE_HEAD=$ORIGINAL_HEAD"
    echo "SOURCE_TREE=$(git -C "$REPO_ROOT" rev-parse HEAD^{tree})"
    awk -F'"' '/^version = / {print "PYPROJECT_VERSION="$2; exit}' "$POC_ROOT/pyproject.toml"
} > "$EVIDENCE_DIR/repository_identity.txt"

{
    echo "=== CURRENT IMMUTABLE RELEASE ==="
    if [[ -L "$CURRENT_LINK" || -e "$CURRENT_LINK" ]]; then
        current="$(readlink -f "$CURRENT_LINK" 2>/dev/null || true)"
        echo "CURRENT_PRESENT=true"
        echo "CURRENT_TARGET=$current"
        if [[ -n "$current" && -f "$current/RELEASE_GIT.txt" ]]; then
            grep -E '^(VERSION|GIT_SHA|GIT_TREE_SHA|TESTED_TREE_SHA|RELEASE_ID|REAL_TRANSPORT_IMPLEMENTED|LIVE_TEST_READY|PHYSICAL_DOOR_ACTION)=' \
              "$current/RELEASE_GIT.txt" || true
        fi
    else
        echo "CURRENT_PRESENT=false"
    fi
    echo "SECRETS_CONTENT_READ=false"
} > "$EVIDENCE_DIR/runtime_identity.txt"

{
    echo "=== CREDENTIAL STORAGE METADATA ONLY ==="
    secret_dir=/root/.config/comelit
    if [[ -d "$secret_dir" ]]; then
        echo "CREDENTIAL_DIRECTORY_PRESENT=true"
        echo "CREDENTIAL_DIRECTORY_MODE=$(stat -c '%a' "$secret_dir")"
        echo "CREDENTIAL_FILE_COUNT=$(find "$secret_dir" -maxdepth 1 -type f | wc -l)"
    else
        echo "CREDENTIAL_DIRECTORY_PRESENT=false"
    fi
    echo "CREDENTIAL_FILENAMES_EMITTED=false"
    echo "CREDENTIAL_CONTENT_READ=false"
} > "$EVIDENCE_DIR/credential_metadata.txt"

{
    echo "=== PASSIVE RUNTIME METADATA ==="
    echo "PYTHON=$(python3 --version 2>&1)"
    echo "KERNEL=$(uname -sr)"
    echo "ACTIVE_NETWORK_PROBE=false"
    echo "NETWORK_ENDPOINT_VALUES_EMITTED=false"
} > "$EVIDENCE_DIR/runtime_metadata.txt"

if grep -RIEq 'github_pat_[A-Za-z0-9_]+|ghp_[A-Za-z0-9]+|Authorization:[[:space:]]*(Bearer|Basic)[[:space:]]+[^<[:space:]]+|-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----' "$EVIDENCE_DIR"; then
    echo "P12_PUBLIC_EVIDENCE_SECRET_SCAN=FAIL"
    exit 1
fi
if grep -RIEq 'SECRETS_CONTENT_READ=true|CREDENTIAL_VALUES_COLLECTED=true|REAL_DOOR_PAYLOAD_VALUES_COLLECTED=true|ACTIVE_COMELIT_NETWORK_PROBES=true|ACTUATOR_COMMAND_ATTEMPTED=true|PHYSICAL_DOOR_ACTION=true' "$EVIDENCE_DIR"; then
    echo "P12_PUBLIC_EVIDENCE_SAFETY_MARKER_SCAN=FAIL"
    exit 1
fi
cat >> "$EVIDENCE_DIR/MANIFEST.txt" <<'EOF'
P12_PUBLIC_EVIDENCE_SECRET_SCAN=PASS
P12_PUBLIC_EVIDENCE_SAFETY_MARKER_SCAN=PASS
EOF

(
    cd "$EVIDENCE_DIR"
    sha256sum ./*.txt | sort > SHA256SUMS
)

git -C "$REPO_ROOT" add "$EVIDENCE_REL"
git -C "$REPO_ROOT" diff --cached --check
if git -C "$REPO_ROOT" diff --cached --name-only | grep -Ev "^${EVIDENCE_REL}/" >/dev/null; then
    echo "P12_EVIDENCE_SCOPE_CHECK=FAIL"
    exit 1
fi

git -C "$REPO_ROOT" commit -m "evidence: collect P12 read-only source inventory ${STAMP}"
EVIDENCE_COMMIT="$(git -C "$REPO_ROOT" rev-parse HEAD)"
git -C "$REPO_ROOT" push -u origin "$EVIDENCE_BRANCH"

echo "P12_EVIDENCE_BRANCH=$EVIDENCE_BRANCH"
echo "P12_EVIDENCE_COMMIT=$EVIDENCE_COMMIT"
echo "P12_EVIDENCE_PATH=$EVIDENCE_REL"
echo "P12_READONLY_SOURCE_INVENTORY=PASS"
echo "PUBLIC_SAFE_EVIDENCE=PASS"
echo "SECRETS_CONTENT_READ=false"
echo "CREDENTIAL_VALUES_COLLECTED=false"
echo "REAL_DOOR_PAYLOAD_VALUES_COLLECTED=false"
echo "ACTIVE_COMELIT_NETWORK_PROBES=false"
echo "ACTUATOR_COMMAND_ATTEMPTED=false"
echo "PHYSICAL_DOOR_ACTION=false"

git -C "$REPO_ROOT" switch "$ORIGINAL_BRANCH"
trap - EXIT
echo "RETURNED_TO_BRANCH=$ORIGINAL_BRANCH"
echo "P12_EVIDENCE_COLLECTION=PASS"
