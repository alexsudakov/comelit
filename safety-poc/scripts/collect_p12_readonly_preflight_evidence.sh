#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
POC_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(git -C "$POC_ROOT" rev-parse --show-toplevel)"
RUN_ROOT=/root/comelit-p12-readonly-preflight
SOURCE_BRANCH=feat/p12-readonly-transport-readiness
META="${1:-}"

[[ "${EUID}" -eq 0 ]] || { echo "P12_PREFLIGHT_EVIDENCE_REQUIRES_ROOT=true"; exit 1; }
[[ "$(git -C "$REPO_ROOT" branch --show-current)" == "$SOURCE_BRANCH" ]] || {
    echo "P12_PREFLIGHT_EVIDENCE_SOURCE_BRANCH=FAIL"
    exit 1
}
[[ -z "$(git -C "$REPO_ROOT" status --porcelain)" ]] || {
    echo "P12_PREFLIGHT_EVIDENCE_REQUIRES_CLEAN_WORKTREE=true"
    git -C "$REPO_ROOT" status --short
    exit 1
}
[[ -d "$RUN_ROOT" ]] || { echo "P12_PREFLIGHT_RUN_ROOT_PRESENT=false"; exit 1; }

if [[ -z "$META" ]]; then
    META="$(find "$RUN_ROOT" -maxdepth 1 -type f -name '*.meta' -printf '%T@ %p\n' | sort -nr | awk 'NR==1 {sub(/^[^ ]+ /, ""); print; exit}')"
fi
[[ -n "$META" && -f "$META" ]] || { echo "P12_PREFLIGHT_META_PRESENT=false"; exit 1; }
case "$META" in "$RUN_ROOT"/*.meta) ;; *) echo "P12_PREFLIGHT_META_PATH=FAIL"; exit 1 ;; esac

LOG="$(awk -F= '$1 == "P12_PREFLIGHT_SERVICE_LOG" {print substr($0, index($0,"=")+1)}' "$META")"
RCFILE="$(awk -F= '$1 == "P12_PREFLIGHT_SERVICE_RC_FILE" {print substr($0, index($0,"=")+1)}' "$META")"
UNIT="$(awk -F= '$1 == "P12_PREFLIGHT_SERVICE_UNIT" {print substr($0, index($0,"=")+1)}' "$META")"
RUN_HEAD="$(awk -F= '$1 == "P12_PREFLIGHT_SERVICE_REPOSITORY_HEAD" {print $2}' "$META")"
RUN_TREE="$(awk -F= '$1 == "P12_PREFLIGHT_SERVICE_REPOSITORY_TREE" {print $2}' "$META")"
RUN_STAMP="$(awk -F= '$1 == "P12_PREFLIGHT_SERVICE_STARTED_AT_UTC" {print $2}' "$META")"

case "$LOG" in "$RUN_ROOT"/*.log) ;; *) echo "P12_PREFLIGHT_LOG_PATH=FAIL"; exit 1 ;; esac
case "$RCFILE" in "$RUN_ROOT"/*.rc) ;; *) echo "P12_PREFLIGHT_RC_PATH=FAIL"; exit 1 ;; esac
[[ -f "$LOG" && -s "$LOG" ]] || { echo "P12_PREFLIGHT_LOG_NONEMPTY=false"; exit 1; }
[[ -f "$RCFILE" && -s "$RCFILE" ]] || { echo "P12_PREFLIGHT_RC_NONEMPTY=false"; exit 1; }
[[ "$RUN_HEAD" =~ ^[0-9a-f]{40}$ ]] || { echo "P12_PREFLIGHT_RUN_HEAD_FORMAT=FAIL"; exit 1; }
[[ "$RUN_TREE" =~ ^[0-9a-f]{40}$ ]] || { echo "P12_PREFLIGHT_RUN_TREE_FORMAT=FAIL"; exit 1; }
[[ "$RUN_STAMP" =~ ^[0-9]{8}T[0-9]{6}Z$ ]] || { echo "P12_PREFLIGHT_RUN_STAMP_FORMAT=FAIL"; exit 1; }
[[ -n "$UNIT" ]] || { echo "P12_PREFLIGHT_UNIT_METADATA=FAIL"; exit 1; }

RC="$(awk -F= '$1 == "P12_PREFLIGHT_RC" && $2 ~ /^[0-9]+$/ {print $2}' "$RCFILE")"
[[ "$RC" == "0" ]] || { echo "P12_PREFLIGHT_EVIDENCE_RC=FAIL"; exit 1; }

required=(
  'P12_PREFLIGHT_SERVICE_PAYLOAD_START=true'
  'P12_PREFLIGHT_DIAGNOSTIC_TRAP=ARMED'
  'P12_PREFLIGHT_BUILD_IDENTITY=PASS'
  'P12_PREFLIGHT_ARTIFACT_SHAPE=PASS'
  'P12_PREFLIGHT_SOURCE_ACTUATOR_SCAN=PASS'
  'P12_PREFLIGHT_BINARY_ACTUATOR_SCAN=PASS'
  'P12_PREFLIGHT_WRAPPER_ACTUATOR_SCAN=PASS'
  'P12_PREFLIGHT_READONLY_SURFACE=PASS'
  'P12_PREFLIGHT_WRAPPER_BINDING=PASS'
  'P12_PREFLIGHT_ONE_SHOT_CONTROL=PASS'
  'P12_PREFLIGHT_TARGET_HASH_PROFILE=PASS'
  'P12_PREFLIGHT_LIVE_RUNNER_CONTRACT=PASS'
  'P12_PREFLIGHT_FINALIZER_CONTRACT=PASS'
  'P12_PREFLIGHT_CONTROL_PLANE=PASS'
  'P12_PREFLIGHT_CREDENTIAL_METADATA=PASS'
  'P12_PREFLIGHT_NO_ACTIVE_CANDIDATE=PASS'
  'P12_READONLY_LIVE_APPROVAL_REQUIRED=true'
  'P12_READONLY_LIVE_APPROVED=false'
  'P12_READONLY_LIVE_RUN_PERFORMED=false'
  'CANDIDATE_EXECUTED=false'
  'WRAPPER_EXECUTED=false'
  'SECRETS_CONTENT_READ=false'
  'CREDENTIAL_MATERIAL_EMITTED=false'
  'TARGET_IDENTITY_VALUES_EMITTED=false'
  'ACTIVE_COMELIT_NETWORK_PROBES=false'
  'ACTUATOR_COMMAND_ATTEMPTED=false'
  'PHYSICAL_DOOR_ACTION=false'
  'PHYSICAL_EFFECT_ASSERTED=false'
  'READONLY_TRANSPORT_READY=false'
  'LIVE_TEST_READY=false'
  'P12_READONLY_LIVE_PREFLIGHT=PASS'
  'P12_PREFLIGHT_EXIT_RC=0'
  'P12_PREFLIGHT_LAST_STEP=COMPLETE'
  'P12_PREFLIGHT_SERVICE_PAYLOAD_END=true'
)
for marker in "${required[@]}"; do
    [[ "$(grep -Fxc "$marker" "$LOG")" -eq 1 ]] || {
        echo "P12_PREFLIGHT_EVIDENCE_REQUIRED_MARKER=FAIL"
        exit 1
    }
done

# The preflight run is immutable evidence from RUN_HEAD/RUN_TREE. The collector
# may be a later descendant only when the entire intervening diff is limited to
# this collector and its repository-only test. This prevents later P12 runtime
# changes from being retroactively attached to an older preflight PASS.
COLLECTOR_HEAD="$(git -C "$REPO_ROOT" rev-parse HEAD)"
COLLECTOR_TREE="$(git -C "$REPO_ROOT" rev-parse HEAD^{tree})"
git -C "$REPO_ROOT" cat-file -e "$RUN_HEAD^{commit}" 2>/dev/null || { echo "P12_PREFLIGHT_RUN_HEAD_PRESENT=false"; exit 1; }
[[ "$(git -C "$REPO_ROOT" rev-parse "$RUN_HEAD^{tree}")" == "$RUN_TREE" ]] || {
    echo "P12_PREFLIGHT_RUN_TREE_BINDING=FAIL"
    exit 1
}
git -C "$REPO_ROOT" merge-base --is-ancestor "$RUN_HEAD" "$COLLECTOR_HEAD" || {
    echo "P12_PREFLIGHT_RUN_NOT_ANCESTOR_OF_COLLECTOR=true"
    exit 1
}
DRIFT_PATHS="$(git -C "$REPO_ROOT" diff --name-only "$RUN_HEAD..$COLLECTOR_HEAD")"
if printf '%s\n' "$DRIFT_PATHS" | sed '/^$/d' | grep -Ev '^(safety-poc/scripts/collect_p12_readonly_preflight_evidence\.sh|safety-poc/tests/test_collect_p12_readonly_preflight_evidence\.py)$' >/dev/null; then
    echo "P12_PREFLIGHT_TO_COLLECTOR_DRIFT_SCOPE=FAIL"
    exit 1
fi
echo "P12_PREFLIGHT_TO_COLLECTOR_DRIFT_SCOPE=PASS"

# Public evidence contains only fixed safety/readiness markers and hashes.
# Never copy raw service logs, credential files, or target identity values.
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
EVIDENCE_BRANCH="evidence/p12-preflight-${STAMP}"
EVIDENCE_REL="evidence/p12-preflight/${STAMP}"
EVIDENCE_DIR="$REPO_ROOT/$EVIDENCE_REL"

git -C "$REPO_ROOT" switch -c "$EVIDENCE_BRANCH"
cleanup() {
    rc=$?
    if [[ $rc -ne 0 ]]; then
        git -C "$REPO_ROOT" switch "$SOURCE_BRANCH" >/dev/null 2>&1 || true
    fi
    return "$rc"
}
trap cleanup EXIT
mkdir -p "$EVIDENCE_DIR"

LOG_SHA="$(sha256sum "$LOG" | awk '{print $1}')"
RC_SHA="$(sha256sum "$RCFILE" | awk '{print $1}')"
META_SHA="$(sha256sum "$META" | awk '{print $1}')"

cat > "$EVIDENCE_DIR/MANIFEST.txt" <<EOF
EVIDENCE_SCHEMA=P12_PREFLIGHT_V2
COLLECTED_AT_UTC=$STAMP
SOURCE_BRANCH=$SOURCE_BRANCH
COLLECTOR_SOURCE_HEAD=$COLLECTOR_HEAD
COLLECTOR_SOURCE_TREE=$COLLECTOR_TREE
PREFLIGHT_RUN_HEAD=$RUN_HEAD
PREFLIGHT_RUN_TREE=$RUN_TREE
PREFLIGHT_TO_COLLECTOR_DRIFT_SCOPE=PASS
PREFLIGHT_RUN_STARTED_AT_UTC=$RUN_STAMP
PREFLIGHT_SERVICE_UNIT=$UNIT
PREFLIGHT_LOG_SHA256=$LOG_SHA
PREFLIGHT_RC_SHA256=$RC_SHA
PREFLIGHT_META_SHA256=$META_SHA
P12_PREFLIGHT_SERVICE_RESULT=PASS
P12_PREFLIGHT_RC=0
P12_READONLY_LIVE_PREFLIGHT=PASS
P12_PREFLIGHT_LAST_STEP=COMPLETE
P12_READONLY_LIVE_APPROVED=false
P12_READONLY_LIVE_RUN_PERFORMED=false
CANDIDATE_EXECUTED=false
WRAPPER_EXECUTED=false
SECRETS_CONTENT_READ=false
CREDENTIAL_MATERIAL_EMITTED=false
TARGET_IDENTITY_VALUES_EMITTED=false
ACTIVE_COMELIT_NETWORK_PROBES=false
ACTUATOR_COMMAND_ATTEMPTED=false
PHYSICAL_DOOR_ACTION=false
PHYSICAL_EFFECT_ASSERTED=false
READONLY_TRANSPORT_READY=false
LIVE_TEST_READY=false
PUBLIC_SAFE=true
RAW_PREFLIGHT_LOG_COPIED=false
CREDENTIAL_VALUES_COLLECTED=false
EOF
chmod 600 "$EVIDENCE_DIR/MANIFEST.txt"

if grep -RIEq 'github_pat_[A-Za-z0-9_]+|ghp_[A-Za-z0-9]+|Authorization:[[:space:]]*(Bearer|Basic)[[:space:]]+[^<[:space:]]+|-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----' "$EVIDENCE_DIR"; then
    echo "P12_PREFLIGHT_PUBLIC_EVIDENCE_SECRET_SCAN=FAIL"
    exit 1
fi
if grep -RIEq 'SECRETS_CONTENT_READ=true|CREDENTIAL_VALUES_COLLECTED=true|ACTIVE_COMELIT_NETWORK_PROBES=true|ACTUATOR_COMMAND_ATTEMPTED=true|PHYSICAL_DOOR_ACTION=true|PHYSICAL_EFFECT_ASSERTED=true|READONLY_TRANSPORT_READY=true|LIVE_TEST_READY=true' "$EVIDENCE_DIR"; then
    echo "P12_PREFLIGHT_PUBLIC_EVIDENCE_SAFETY_SCAN=FAIL"
    exit 1
fi
cat >> "$EVIDENCE_DIR/MANIFEST.txt" <<'EOF'
P12_PREFLIGHT_PUBLIC_EVIDENCE_SECRET_SCAN=PASS
P12_PREFLIGHT_PUBLIC_EVIDENCE_SAFETY_SCAN=PASS
EOF

(
    cd "$EVIDENCE_DIR"
    sha256sum MANIFEST.txt > SHA256SUMS
)
chmod 600 "$EVIDENCE_DIR/SHA256SUMS"

git -C "$REPO_ROOT" add "$EVIDENCE_REL"
git -C "$REPO_ROOT" diff --cached --check
if git -C "$REPO_ROOT" diff --cached --name-only | grep -Ev "^${EVIDENCE_REL}/" >/dev/null; then
    echo "P12_PREFLIGHT_EVIDENCE_SCOPE_CHECK=FAIL"
    exit 1
fi

git -C "$REPO_ROOT" commit -m "evidence: record P12 read-only preflight ${STAMP}"
EVIDENCE_COMMIT="$(git -C "$REPO_ROOT" rev-parse HEAD)"
git -C "$REPO_ROOT" push -u origin "$EVIDENCE_BRANCH"
git -C "$REPO_ROOT" switch "$SOURCE_BRANCH"
trap - EXIT

echo "P12_PREFLIGHT_EVIDENCE_BRANCH=$EVIDENCE_BRANCH"
echo "P12_PREFLIGHT_EVIDENCE_COMMIT=$EVIDENCE_COMMIT"
echo "P12_PREFLIGHT_EVIDENCE_PATH=$EVIDENCE_REL"
echo "P12_PREFLIGHT_EVIDENCE_COLLECTION=PASS"
echo "P12_READONLY_LIVE_APPROVED=false"
echo "P12_READONLY_LIVE_RUN_PERFORMED=false"
echo "SECRETS_CONTENT_READ=false"
echo "ACTIVE_COMELIT_NETWORK_PROBES=false"
echo "ACTUATOR_COMMAND_ATTEMPTED=false"
echo "PHYSICAL_DOOR_ACTION=false"
echo "READONLY_TRANSPORT_READY=false"
echo "LIVE_TEST_READY=false"
