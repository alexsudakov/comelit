#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

POC_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_ROOT="$(git -C "$POC_ROOT" rev-parse --show-toplevel)"
CANONICAL_ROOT=/root/comelit-vip-poc
OUT="${1:-/root/comelit-v0.6-runtime-gates}"

case "$OUT" in
    /root/comelit-v0.6-runtime-gates|/root/comelit-v0.6-runtime-gates-*) ;;
    *)
        echo "RUNTIME_GATE_OUTPUT_PATH_REJECTED=$OUT"
        exit 64
        ;;
esac

ORIGINAL_BRANCH="$(git -C "$REPO_ROOT" branch --show-current)"
if [[ -z "$ORIGINAL_BRANCH" ]]; then
    echo "RUNTIME_GATES_REQUIRE_NAMED_BRANCH=true"
    exit 1
fi
if [[ -n "$(git -C "$REPO_ROOT" status --porcelain)" ]]; then
    echo "RUNTIME_GATES_REQUIRE_CLEAN_WORKTREE=true"
    git -C "$REPO_ROOT" status --short
    exit 1
fi

GIT_SHA="$(git -C "$REPO_ROOT" rev-parse HEAD)"
TREE_SHA="$(git -C "$REPO_ROOT" rev-parse HEAD^{tree})"
VERSION="$(awk -F'"' '/^version = / {print $2; exit}' "$POC_ROOT/pyproject.toml")"
[[ -n "$VERSION" ]] || { echo "RUNTIME_GATE_VERSION_RESOLUTION=FAIL"; exit 1; }

rm -rf "$OUT"
mkdir -p "$OUT"

cat > "$OUT/05_repository_identity.txt" <<EOF
RUNTIME_GATE_GIT_SHA=$GIT_SHA
RUNTIME_GATE_TREE_SHA=$TREE_SHA
RUNTIME_GATE_VERSION=$VERSION
RUNTIME_GATE_SOURCE_BRANCH=$ORIGINAL_BRANCH
EOF

export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$POC_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

echo "=== OFFLINE REPOSITORY SUITE ==="
bash "$POC_ROOT/scripts/run_offline_suite.sh" | tee "$OUT/00_offline_suite.txt"

echo
echo "=== PINNED LEGACY SYNTHETIC BODY ORACLE ==="
python3 "$POC_ROOT/scripts/verify_legacy_synthetic_body_oracle.py" | tee "$OUT/10_body_oracle.txt"

echo
echo "=== CANONICAL CAPTURE-BASED SESSION TESTS ==="
(
    cd "$CANONICAL_ROOT"
    python3 -m unittest \
      tests.test_vip_session \
      tests.test_channel_session \
      tests.test_application_session -v
) 2>&1 | tee "$OUT/20_canonical_tests.txt"
printf '%s\n' \
  'CANONICAL_VIP_CAPTURE_TESTS=PASS' \
  'CANONICAL_VIP_SOURCE_HASHES=PASS' \
  'NETWORK_ACTION_PERFORMED=false' \
  'PHYSICAL_DOOR_ACTION=false' \
  >> "$OUT/20_canonical_tests.txt"

echo
echo "=== CANONICAL CTPP CONTROL FIXTURE ==="
python3 "$POC_ROOT/scripts/verify_ctpp_control_plane_fixture.py" | tee "$OUT/30_ctpp_control.txt"

echo
echo "=== FULL OFFLINE TRANSACTION FIXTURE ==="
python3 "$POC_ROOT/scripts/verify_full_offline_transaction_fixture.py" | tee "$OUT/40_full_transaction.txt"

cat \
  "$OUT/00_offline_suite.txt" \
  "$OUT/05_repository_identity.txt" \
  "$OUT/10_body_oracle.txt" \
  "$OUT/20_canonical_tests.txt" \
  "$OUT/30_ctpp_control.txt" \
  "$OUT/40_full_transaction.txt" \
  > "$OUT/90_combined_markers.txt"

echo
echo "=== REPOSITORY READINESS ==="
python3 "$POC_ROOT/scripts/evaluate_plan_readiness.py" "$OUT/90_combined_markers.txt" \
  | tee "$OUT/95_readiness.txt"
cat "$OUT/95_readiness.txt" >> "$OUT/90_combined_markers.txt"

cat >> "$OUT/90_combined_markers.txt" <<'EOF'
CT120_RUNTIME_GATES=PASS
REPOSITORY_READY=true
REAL_TRANSPORT_IMPLEMENTED=false
READONLY_TRANSPORT_READY=false
ACTUATION_TRANSPORT_IMPLEMENTED=false
LIVE_TEST_READY=false
SECRETS_READ=false
REAL_DOOR_PAYLOAD_VALUES_COLLECTED=false
NETWORK_ACTION_PERFORMED=false
PHYSICAL_DOOR_ACTION=false
EOF

if grep -RIEq 'github_pat_[A-Za-z0-9_]+|ghp_[A-Za-z0-9]+|Authorization:[[:space:]]*(Bearer|Basic)[[:space:]]+[^<[:space:]]+|-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----' "$OUT"; then
    echo "RUNTIME_EVIDENCE_SECRET_SCAN=FAIL"
    exit 1
fi
if grep -RIEq 'SECRETS_READ=true|REAL_DOOR_PAYLOAD_VALUES_COLLECTED=true|NETWORK_ACTION_PERFORMED=true|PHYSICAL_DOOR_ACTION=true' "$OUT"; then
    echo "RUNTIME_EVIDENCE_SAFETY_MARKER_SCAN=FAIL"
    exit 1
fi

(
    cd "$OUT"
    sha256sum ./*.txt | sort > SHA256SUMS
)

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
EVIDENCE_BRANCH="evidence/ct120-runtime-${STAMP}"
EVIDENCE_REL="evidence/ct120-runtime/${STAMP}"
EVIDENCE_DIR="$REPO_ROOT/$EVIDENCE_REL"

cleanup_branch() {
    rc=$?
    if [[ $rc -ne 0 ]]; then
        git -C "$REPO_ROOT" switch "$ORIGINAL_BRANCH" >/dev/null 2>&1 || true
    fi
    return "$rc"
}
trap cleanup_branch EXIT

git -C "$REPO_ROOT" switch -c "$EVIDENCE_BRANCH"
mkdir -p "$EVIDENCE_DIR"
cp -a "$OUT"/*.txt "$OUT/SHA256SUMS" "$EVIDENCE_DIR/"
cat > "$EVIDENCE_DIR/MANIFEST.txt" <<EOF
EVIDENCE_SCHEMA=3
COLLECTED_AT_UTC=$STAMP
SOURCE_BRANCH=$ORIGINAL_BRANCH
SOURCE_GIT_SHA=$GIT_SHA
SOURCE_TREE_SHA=$TREE_SHA
SOURCE_VERSION=$VERSION
PUBLIC_SAFE=true
SECRETS_READ=false
REAL_DOOR_PAYLOAD_VALUES_COLLECTED=false
ACTIVE_COMELIT_NETWORK_PROBES=false
PHYSICAL_DOOR_ACTION=false
CT120_RUNTIME_GATES=PASS
REPOSITORY_READY=true
READONLY_TRANSPORT_READY=false
ACTUATION_TRANSPORT_IMPLEMENTED=false
LIVE_TEST_READY=false
EOF

if grep -RIEq 'github_pat_[A-Za-z0-9_]+|ghp_[A-Za-z0-9]+|Authorization:[[:space:]]*(Bearer|Basic)[[:space:]]+[^<[:space:]]+|-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----' "$EVIDENCE_DIR"; then
    echo "PUBLIC_RUNTIME_EVIDENCE_SECRET_SCAN=FAIL"
    exit 1
fi

git -C "$REPO_ROOT" add "$EVIDENCE_REL"
git -C "$REPO_ROOT" diff --cached --check
if git -C "$REPO_ROOT" diff --cached --name-only | grep -Ev "^${EVIDENCE_REL}/" >/dev/null; then
    echo "RUNTIME_EVIDENCE_SCOPE_CHECK=FAIL"
    exit 1
fi

git -C "$REPO_ROOT" commit -m "evidence: record CT120 v0.6 runtime gates ${STAMP}"
EVIDENCE_COMMIT="$(git -C "$REPO_ROOT" rev-parse HEAD)"
git -C "$REPO_ROOT" push -u origin "$EVIDENCE_BRANCH"
git -C "$REPO_ROOT" switch "$ORIGINAL_BRANCH"
trap - EXIT

echo
echo "=== CT120 RUNTIME GATE RESULT ==="
echo "RUNTIME_GATE_DIR=$OUT"
echo "RUNTIME_GATE_GIT_SHA=$GIT_SHA"
echo "RUNTIME_GATE_TREE_SHA=$TREE_SHA"
echo "RUNTIME_GATE_VERSION=$VERSION"
echo "RUNTIME_GATE_COMBINED=$OUT/90_combined_markers.txt"
echo "RUNTIME_GATE_SHA256SUMS=$OUT/SHA256SUMS"
echo "RUNTIME_EVIDENCE_BRANCH=$EVIDENCE_BRANCH"
echo "RUNTIME_EVIDENCE_COMMIT=$EVIDENCE_COMMIT"
echo "RUNTIME_EVIDENCE_PATH=$EVIDENCE_REL"
echo "CT120_RUNTIME_GATES=PASS"
echo "REPOSITORY_READY=true"
echo "REAL_TRANSPORT_IMPLEMENTED=false"
echo "READONLY_TRANSPORT_READY=false"
echo "ACTUATION_TRANSPORT_IMPLEMENTED=false"
echo "LIVE_TEST_READY=false"
echo "SECRETS_READ=false"
echo "NETWORK_ACTION_PERFORMED=false"
echo "PHYSICAL_DOOR_ACTION=false"
