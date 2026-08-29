#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
POC_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(git -C "$POC_ROOT" rev-parse --show-toplevel)"
LEGACY_SOURCE=/root/comelit-poc/comelit_client.py
CANONICAL_ROOT=/root/comelit-vip-poc
RUNTIME_ROOT=/opt/comelit-door-safety-poc
CURRENT_LINK="$RUNTIME_ROOT/current"
CORRECTS_EVIDENCE_COMMIT=153e1864d947e9ff0a5386f2d60b4b87d117c239

ORIGINAL_BRANCH="$(git -C "$REPO_ROOT" branch --show-current)"
ORIGINAL_HEAD="$(git -C "$REPO_ROOT" rev-parse HEAD)"
[[ -n "$ORIGINAL_BRANCH" ]] || { echo "COLLECTOR_REQUIRES_NAMED_BRANCH=true"; exit 1; }
[[ -z "$(git -C "$REPO_ROOT" status --porcelain)" ]] || {
    echo "COLLECTOR_REQUIRES_CLEAN_WORKTREE=true"
    git -C "$REPO_ROOT" status --short
    exit 1
}

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
EVIDENCE_BRANCH="evidence/ct120-v2-${STAMP}"
EVIDENCE_REL="evidence/ct120-v2/${STAMP}"
EVIDENCE_DIR="$REPO_ROOT/$EVIDENCE_REL"

git -C "$REPO_ROOT" switch -c "$EVIDENCE_BRANCH"
mkdir -p "$EVIDENCE_DIR"

cleanup() {
    rc=$?
    if [[ $rc -ne 0 ]]; then
        echo "COLLECTOR_V2_FAILED_RC=$rc"
        git -C "$REPO_ROOT" switch "$ORIGINAL_BRANCH" >/dev/null 2>&1 || true
    fi
    return "$rc"
}
trap cleanup EXIT

cat > "$EVIDENCE_DIR/MANIFEST.txt" <<EOF
EVIDENCE_SCHEMA=2
COLLECTED_AT_UTC=$STAMP
SOURCE_BRANCH=$ORIGINAL_BRANCH
SOURCE_HEAD=$ORIGINAL_HEAD
CORRECTS_EVIDENCE_COMMIT=$CORRECTS_EVIDENCE_COMMIT
BODY_INVENTORY_METHOD_SELECTION=QUALIFIED_CLASS_METHOD
PUBLIC_SAFE=true
SOURCE_EXECUTED=false
SECRETS_CONTENT_READ=false
CREDENTIAL_VALUES_COLLECTED=false
REAL_DOOR_PAYLOAD_VALUES_COLLECTED=false
ACTIVE_COMELIT_NETWORK_PROBES=false
PHYSICAL_DOOR_ACTION=false
EOF

python3 "$SCRIPT_DIR/legacy_body_shape_inventory.py" \
  > "$EVIDENCE_DIR/legacy_body_shape_inventory_v2.txt"

python3 "$SCRIPT_DIR/canonical_control_shape_inventory.py" \
  > "$EVIDENCE_DIR/canonical_control_shape_inventory.txt"

TEST_PATHS=()
for name in test_channel_session.py test_vip_session.py test_application_session.py; do
    path="$CANONICAL_ROOT/tests/$name"
    [[ -f "$path" ]] && TEST_PATHS+=("$path")
done
if [[ ${#TEST_PATHS[@]} -gt 0 ]]; then
    python3 "$SCRIPT_DIR/safe_source_topology.py" "${TEST_PATHS[@]}" \
      > "$EVIDENCE_DIR/canonical_test_topology.txt"
else
    echo "CANONICAL_TESTS_PRESENT=false" > "$EVIDENCE_DIR/canonical_test_topology.txt"
fi

{
    echo "=== CANONICAL PYTHON TREE ==="
    if [[ -d "$CANONICAL_ROOT" ]]; then
        while IFS= read -r -d '' path; do
            rel="${path#$CANONICAL_ROOT/}"
            size="$(stat -c '%s' "$path" 2>/dev/null || echo unknown)"
            sha="$(sha256sum "$path" | awk '{print $1}')"
            echo "PY path=$rel bytes=$size sha256=$sha"
        done < <(find "$CANONICAL_ROOT" -type f -name '*.py' ! -path '*/__pycache__/*' -print0 | sort -z)
    else
        echo "CANONICAL_ROOT_PRESENT=false"
    fi
    echo "SOURCE_CONTENT_EMITTED=false"
} > "$EVIDENCE_DIR/canonical_python_tree.txt"

{
    echo "=== LEGACY SOURCE IDENTITY ==="
    if [[ -f "$LEGACY_SOURCE" ]]; then
        echo "SHA256=$(sha256sum "$LEGACY_SOURCE" | awk '{print $1}')"
        echo "BYTES=$(stat -c '%s' "$LEGACY_SOURCE")"
    else
        echo "LEGACY_SOURCE_PRESENT=false"
    fi
    echo "SOURCE_CONTENT_EMITTED=false"
} > "$EVIDENCE_DIR/legacy_source_identity.txt"

{
    echo "=== RUNTIME RELEASE V2 ==="
    if [[ -L "$CURRENT_LINK" || -e "$CURRENT_LINK" ]]; then
        current="$(readlink -f "$CURRENT_LINK" 2>/dev/null || true)"
        echo "CURRENT_PRESENT=true"
        echo "CURRENT_TARGET=$current"
        if [[ -n "$current" && -f "$current/pyproject.toml" ]]; then
            awk -F'"' '/^version = / {print "PYPROJECT_VERSION="$2; exit}' "$current/pyproject.toml" || true
        fi
    else
        echo "CURRENT_PRESENT=false"
    fi
    echo "RUNTIME_TREE_CONTENT_READ=false_except_version_metadata"
} > "$EVIDENCE_DIR/runtime_release_v2.txt"

{
    echo "=== OPERATOR BOUNDARY V2 ==="
    for path in /usr/local/sbin/comelit-smoke /usr/local/sbin/comelit-p2p-readiness /usr/local/sbin/hermes-comelit-dispatch /usr/local/sbin/hermes-comelit-dispatch.pre-door-poc-v1; do
        if [[ -f "$path" ]]; then
            echo "FILE=$path mode=$(stat -c '%a' "$path") sha256=$(sha256sum "$path" | awk '{print $1}')"
        fi
    done
    echo "SECRETS_CONTENT_READ=false"
    echo "GIT_CREDENTIAL_FILE_READ=false"
} > "$EVIDENCE_DIR/operator_boundary_v2.txt"

if grep -RIEq 'github_pat_[A-Za-z0-9_]+|ghp_[A-Za-z0-9]+|Authorization:[[:space:]]*(Bearer|Basic)[[:space:]]+[^<[:space:]]+|-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----' "$EVIDENCE_DIR"; then
    echo "PUBLIC_EVIDENCE_SECRET_SCAN=FAIL"
    exit 1
fi
if grep -RIEq 'SECRETS_CONTENT_READ=true|CREDENTIAL_VALUES_COLLECTED=true|REAL_DOOR_PAYLOAD_VALUES_COLLECTED=true|ACTIVE_COMELIT_NETWORK_PROBES=true|PHYSICAL_DOOR_ACTION=true' "$EVIDENCE_DIR"; then
    echo "PUBLIC_EVIDENCE_SAFETY_MARKER_SCAN=FAIL"
    exit 1
fi
cat >> "$EVIDENCE_DIR/MANIFEST.txt" <<'EOF'
PUBLIC_EVIDENCE_SECRET_SCAN=PASS
PUBLIC_EVIDENCE_SAFETY_MARKER_SCAN=PASS
EOF

(
    cd "$EVIDENCE_DIR"
    sha256sum ./*.txt | sort > SHA256SUMS
)

git -C "$REPO_ROOT" add "$EVIDENCE_REL"
git -C "$REPO_ROOT" diff --cached --check
if git -C "$REPO_ROOT" diff --cached --name-only | grep -Ev "^${EVIDENCE_REL}/" >/dev/null; then
    echo "EVIDENCE_SCOPE_CHECK=FAIL"
    exit 1
fi

git -C "$REPO_ROOT" commit -m "evidence: collect corrected CT120 control/body inventory ${STAMP}"
EVIDENCE_COMMIT="$(git -C "$REPO_ROOT" rev-parse HEAD)"
git -C "$REPO_ROOT" push -u origin "$EVIDENCE_BRANCH"

echo "EVIDENCE_V2_BRANCH=$EVIDENCE_BRANCH"
echo "EVIDENCE_V2_COMMIT=$EVIDENCE_COMMIT"
echo "EVIDENCE_V2_PATH=$EVIDENCE_REL"
echo "CORRECTS_EVIDENCE_COMMIT=$CORRECTS_EVIDENCE_COMMIT"
echo "QUALIFIED_BODY_METHOD_SELECTION=PASS"
echo "PUBLIC_SAFE_EVIDENCE=PASS"
echo "SECRETS_CONTENT_READ=false"
echo "REAL_DOOR_PAYLOAD_VALUES_COLLECTED=false"
echo "ACTIVE_COMELIT_NETWORK_PROBES=false"
echo "PHYSICAL_DOOR_ACTION=false"

git -C "$REPO_ROOT" switch "$ORIGINAL_BRANCH"
trap - EXIT
echo "RETURNED_TO_BRANCH=$ORIGINAL_BRANCH"
echo "PLAN_EVIDENCE_V2_COLLECTION=PASS"
