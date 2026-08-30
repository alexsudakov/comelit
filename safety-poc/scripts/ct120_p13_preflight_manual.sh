#!/usr/bin/env bash
# =============================================================================
# CT120 manual non-actuating P13 preflight + public-safe evidence collection
#
# Run as root on CT120. This script performs no Comelit network session and no
# actuator command. It verifies the installed real-adapter artifact in dry-init
# mode, runs the non-actuating P13 preflight, records public-safe evidence, and
# pushes a dedicated evidence branch when Git credentials are available.
#
# Required runtime input (independent pin, NOT derived from the installed file):
#   none — the expected wrapper SHA-256 is read from the Git-reviewed build
#   manifest deploy/p13_wrapper_manifest.json (status=BUILT).  The manifest is
#   produced by scripts/build_p13_wrapper.sh from the reviewed template and
#   pinned native holder, then committed and reviewed in Git before preflight.
#
# Optional push input:
#   GITHUB_TOKEN_COMELIT=<repo-write token>
# If omitted, configured Git credentials are tried. The token is never printed
# or committed.
# =============================================================================
set -Eeuo pipefail
umask 077

REPO_ROOT="${COMELIT_REPO_ROOT:-/root/comelit-git}"
EXPECTED_BRANCH=feat/p13-one-shot-actuation
WRAPPER=/usr/local/sbin/comelit-p13-door-wrapper
PAYLOAD=/root/comelit-p13-actuator-prep/real-door-payloads.json
RUN_ROOT=/root/comelit-p13-preflight-evidence
ASKPASS=/run/comelit-p13-evidence-askpass.sh
SOURCE_HEAD=""
EVIDENCE_BRANCH=""

cleanup() {
    rc=$?
    rm -f -- "$ASKPASS"
    if [[ -n "$SOURCE_HEAD" ]] && git -C "$REPO_ROOT" rev-parse --git-dir >/dev/null 2>&1; then
        git -C "$REPO_ROOT" checkout -q "$EXPECTED_BRANCH" >/dev/null 2>&1 || true
    fi
    trap - EXIT
    exit "$rc"
}
trap cleanup EXIT

[[ "${EUID}" -eq 0 ]] || { echo "CT120_P13_MANUAL_REQUIRES_ROOT=true"; exit 1; }

cd "$REPO_ROOT"
[[ -z "$(git status --porcelain)" ]] || { echo "CT120_P13_MANUAL_WORKTREE_DIRTY=true"; exit 1; }

echo "CT120_P13_MANUAL_START=true"
echo "CT120_P13_MANUAL_NON_ACTUATING=true"

# ---- 0. exact remote identity -----------------------------------------------
git fetch origin --prune
git checkout -q -B "$EXPECTED_BRANCH" "origin/$EXPECTED_BRANCH"
SOURCE_HEAD="$(git rev-parse HEAD)"
SOURCE_TREE="$(git rev-parse HEAD^{tree})"
REMOTE_HEAD="$(git rev-parse "origin/$EXPECTED_BRANCH")"
[[ "$SOURCE_HEAD" == "$REMOTE_HEAD" ]] || { echo "CT120_P13_MANUAL_REMOTE_IDENTITY=FAIL"; exit 1; }
[[ -z "$(git status --porcelain)" ]] || { echo "CT120_P13_MANUAL_WORKTREE_DIRTY_AFTER_SYNC=true"; exit 1; }
echo "CT120_P13_MANUAL_HEAD=$SOURCE_HEAD"
echo "CT120_P13_MANUAL_TREE=$SOURCE_TREE"
echo "CT120_P13_MANUAL_REMOTE_IDENTITY=PASS"

SCRIPT_DIR="$REPO_ROOT/safety-poc/scripts"
POC_ROOT="$REPO_ROOT/safety-poc"

# ---- 1. local artifact prerequisites -----------------------------------------
[[ -f "$WRAPPER" ]] || { echo "P13_REAL_WRAPPER_PRESENT=false"; exit 1; }
[[ -f "$PAYLOAD" ]] || { echo "P13_PAYLOAD_PRESENT=false"; exit 1; }

# Independent pin: expected identity comes from the Git-reviewed build manifest
# (status=BUILT), never computed by the operator from the installed file.
MANIFEST="$REPO_ROOT/safety-poc/deploy/p13_wrapper_manifest.json"
[[ -f "$MANIFEST" ]] || { echo "P13_WRAPPER_MANIFEST_ABSENT=true"; exit 1; }
MANIFEST_STATUS="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["status"])' "$MANIFEST")"
EXPECTED_WRAPPER_SHA256="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["wrapper_sha256"])' "$MANIFEST")"
if [[ "$MANIFEST_STATUS" != "BUILT" || -z "$EXPECTED_WRAPPER_SHA256" ]]; then
    echo "P13_WRAPPER_MANIFEST_NOT_BUILT=true"
    exit 1
fi
echo "P13_WRAPPER_MANIFEST_STATUS=$MANIFEST_STATUS"
WRAPPER_SHA="$(sha256sum "$WRAPPER" | awk '{print $1}')"
[[ "$WRAPPER_SHA" == "$EXPECTED_WRAPPER_SHA256" ]] || { echo "P13_REAL_WRAPPER_SHA256=FAIL"; exit 1; }
echo "P13_REAL_WRAPPER_PRESENT=true"
echo "P13_REAL_WRAPPER_SHA256=$WRAPPER_SHA"

# ---- 2. non-actuating preflight ---------------------------------------------
mkdir -p "$RUN_ROOT"
chmod 700 "$RUN_ROOT"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
PREFLIGHT_LOG="$RUN_ROOT/${STAMP}.preflight.log"

if ! bash "$POC_ROOT/scripts/p13_actuation_preflight.sh" | tee "$PREFLIGHT_LOG"; then
    echo "CT120_P13_MANUAL_PREFLIGHT=FAIL"
    exit 1
fi
chmod 600 "$PREFLIGHT_LOG"

grep -Fxq 'P13_NON_ACTUATING_PREFLIGHT=PASS' "$PREFLIGHT_LOG"
grep -Fxq 'READONLY_TRANSPORT_READY=true' "$PREFLIGHT_LOG"
grep -Fxq 'ACTUATION_TRANSPORT_IMPLEMENTED=true' "$PREFLIGHT_LOG"
grep -Fxq 'AUDIT_SINK_VERIFIED=PASS' "$PREFLIGHT_LOG"
grep -Fxq 'P13_ONE_SHOT_MAX_INVOCATIONS=1' "$PREFLIGHT_LOG"
grep -Fxq 'P13_AUTO_RETRY_ALLOWED=false' "$PREFLIGHT_LOG"
grep -Fxq 'EXPLICIT_LIVE_TEST_APPROVAL=false' "$PREFLIGHT_LOG"
grep -Fxq 'LIVE_TEST_READY=false' "$PREFLIGHT_LOG"
grep -Fxq 'P13_ACTUATOR_COMMAND_ATTEMPTED=false' "$PREFLIGHT_LOG"
grep -Fxq 'PHYSICAL_DOOR_ACTION=false' "$PREFLIGHT_LOG"
grep -Fxq 'PHYSICAL_EFFECT_ASSERTED=false' "$PREFLIGHT_LOG"
echo "CT120_P13_MANUAL_PREFLIGHT=PASS"

# ---- 3. public-safe evidence -------------------------------------------------
EVIDENCE_BRANCH="evidence/p13-preflight-$STAMP"
EVIDENCE_REL="evidence/p13-preflight/$STAMP"
EVIDENCE_DIR="$REPO_ROOT/$EVIDENCE_REL"
mkdir -p "$EVIDENCE_DIR"
chmod 700 "$EVIDENCE_DIR"

# The preflight output is allowlisted operational metadata only. It never emits
# credential values, raw payload bodies, target identity values, or approval.
cp "$PREFLIGHT_LOG" "$EVIDENCE_DIR/preflight.log"
chmod 600 "$EVIDENCE_DIR/preflight.log"

PAYLOAD_SHA="$(sha256sum "$PAYLOAD" | awk '{print $1}')"
cat > "$EVIDENCE_DIR/MANIFEST.txt" <<EOF
EVIDENCE_SCHEMA=P13_PREFLIGHT_V1
P13_PREFLIGHT_EVIDENCE_STAMP=$STAMP
P13_PREFLIGHT_SOURCE_BRANCH=$EXPECTED_BRANCH
P13_PREFLIGHT_SOURCE_HEAD=$SOURCE_HEAD
P13_PREFLIGHT_SOURCE_TREE=$SOURCE_TREE
P13_PREFLIGHT_WRAPPER_SHA256=$WRAPPER_SHA
P13_PREFLIGHT_PAYLOAD_SHA256=$PAYLOAD_SHA
READONLY_TRANSPORT_READY=true
ACTUATION_TRANSPORT_IMPLEMENTED=true
AUDIT_SINK_VERIFIED=PASS
P13_ONE_SHOT_MAX_INVOCATIONS=1
P13_AUTO_RETRY_ALLOWED=false
EXPLICIT_LIVE_TEST_APPROVAL=false
LIVE_TEST_READY=false
ACTUATOR_COMMAND_ATTEMPTED=false
PHYSICAL_DOOR_ACTION=false
PHYSICAL_EFFECT_ASSERTED=false
PUBLIC_SAFE=true
CREDENTIAL_VALUES_COLLECTED=false
TARGET_IDENTITY_VALUES_EMITTED=false
RAW_PAYLOAD_BODIES_COLLECTED=false
EOF
chmod 600 "$EVIDENCE_DIR/MANIFEST.txt"

sha256sum "$EVIDENCE_DIR/MANIFEST.txt" "$EVIDENCE_DIR/preflight.log" > "$EVIDENCE_DIR/SHA256SUMS"
chmod 600 "$EVIDENCE_DIR/SHA256SUMS"

# ---- 4. dedicated evidence branch + commit ----------------------------------
git checkout -q -b "$EVIDENCE_BRANCH" "$SOURCE_HEAD"
git add "$EVIDENCE_REL/"
git -c user.name="hermes" -c user.email="hermes@localhost" commit -q \
    -m "evidence: P13 non-actuating preflight $STAMP"
EVIDENCE_COMMIT="$(git rev-parse HEAD)"
EVIDENCE_TREE="$(git rev-parse HEAD^{tree})"
echo "P13_PREFLIGHT_EVIDENCE_BRANCH=$EVIDENCE_BRANCH"
echo "P13_PREFLIGHT_EVIDENCE_COMMIT=$EVIDENCE_COMMIT"
echo "P13_PREFLIGHT_EVIDENCE_TREE=$EVIDENCE_TREE"

# ---- 5. push evidence branch -------------------------------------------------
PUSH_OK=false
if [[ -n "${GITHUB_TOKEN_COMELIT:-}" ]]; then
    cat > "$ASKPASS" <<'EOF'
#!/usr/bin/env bash
case "${1:-}" in
  *Username*) printf '%s\n' 'x-access-token' ;;
  *) printf '%s\n' "${GITHUB_TOKEN_COMELIT:-}" ;;
esac
EOF
    chmod 700 "$ASKPASS"
    if GIT_ASKPASS="$ASKPASS" GIT_TERMINAL_PROMPT=0 git push -u origin "$EVIDENCE_BRANCH"; then
        PUSH_OK=true
    fi
else
    if GIT_TERMINAL_PROMPT=0 git push -u origin "$EVIDENCE_BRANCH"; then
        PUSH_OK=true
    fi
fi

if [[ "$PUSH_OK" == true ]]; then
    echo "P13_PREFLIGHT_EVIDENCE_PUSH=PASS"
else
    echo "P13_PREFLIGHT_EVIDENCE_PUSH=REQUIRED"
    echo "P13_PREFLIGHT_EVIDENCE_LOCAL_COMMIT=$EVIDENCE_COMMIT"
fi

# Return the working tree to the source feature branch.
git checkout -q "$EXPECTED_BRANCH"
[[ "$(git rev-parse HEAD)" == "$SOURCE_HEAD" ]] || { echo "CT120_P13_MANUAL_SOURCE_RETURN=FAIL"; exit 1; }
[[ -z "$(git status --porcelain)" ]] || { echo "CT120_P13_MANUAL_SOURCE_RETURN_DIRTY=true"; exit 1; }

echo "CT120_P13_MANUAL_COMPLETE=true"
echo "P13_NON_ACTUATING_PREFLIGHT=PASS"
echo "ACTUATOR_COMMAND_ATTEMPTED=false"
echo "PHYSICAL_DOOR_ACTION=false"
echo "EXPLICIT_LIVE_TEST_APPROVAL=false"
echo "LIVE_TEST_READY=false"
