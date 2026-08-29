#!/usr/bin/env bash
set -Eeuo pipefail
umask 022

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
POC_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(git -C "$POC_ROOT" rev-parse --show-toplevel)"
RUNTIME_ROOT=/opt/comelit-door-safety-poc
RELEASES="$RUNTIME_ROOT/releases"
CURRENT="$RUNTIME_ROOT/current"

if [[ $# -lt 1 ]]; then
    echo "usage: $0 <gate-report> [<gate-report> ...]" >&2
    exit 64
fi

if [[ -n "$(git -C "$REPO_ROOT" status --porcelain)" ]]; then
    echo "DEPLOY_REQUIRES_CLEAN_WORKTREE=true"
    exit 1
fi

BRANCH="$(git -C "$REPO_ROOT" branch --show-current)"
if [[ "$BRANCH" != main ]]; then
    echo "DEPLOY_REQUIRES_MAIN_BRANCH=true"
    echo "ACTUAL_BRANCH=$BRANCH"
    exit 1
fi

git -C "$REPO_ROOT" fetch origin main
HEAD="$(git -C "$REPO_ROOT" rev-parse HEAD)"
ORIGIN_MAIN="$(git -C "$REPO_ROOT" rev-parse origin/main)"
TREE_SHA="$(git -C "$REPO_ROOT" rev-parse HEAD^{tree})"
if [[ "$HEAD" != "$ORIGIN_MAIN" ]]; then
    echo "DEPLOY_REQUIRES_ORIGIN_MAIN_CONVERGENCE=true"
    echo "LOCAL_HEAD=$HEAD"
    echo "ORIGIN_MAIN=$ORIGIN_MAIN"
    exit 1
fi

VERSION="$(awk -F'"' '/^version = / {print $2; exit}' "$POC_ROOT/pyproject.toml")"
if [[ -z "$VERSION" ]]; then
    echo "VERSION_RESOLUTION=FAIL"
    exit 1
fi
if [[ "$VERSION" == *dev* ]]; then
    echo "DEPLOY_BLOCKED_DEVELOPMENT_VERSION=$VERSION"
    exit 1
fi

marker() {
    local key="$1"
    shift
    awk -F= -v key="$key" '
        $1 == key { value=substr($0, length(key)+2) }
        END { if (value != "") print value }
    ' "$@"
}

TESTED_TREE="$(marker RUNTIME_GATE_TREE_SHA "$@")"
TESTED_VERSION="$(marker RUNTIME_GATE_VERSION "$@")"
RUNTIME_PASS="$(marker CT120_RUNTIME_GATES "$@")"
REPOSITORY_READY="$(marker REPOSITORY_READY "$@")"
REAL_TRANSPORT="$(marker REAL_TRANSPORT_IMPLEMENTED "$@")"
LIVE_READY="$(marker LIVE_TEST_READY "$@")"

[[ "$RUNTIME_PASS" == PASS ]] || { echo "DEPLOY_RUNTIME_GATE=FAIL"; exit 1; }
[[ "$REPOSITORY_READY" == true ]] || { echo "DEPLOY_REPOSITORY_READINESS=FAIL"; exit 1; }
[[ "$TESTED_TREE" == "$TREE_SHA" ]] || {
    echo "DEPLOY_TESTED_TREE_MISMATCH=true"
    echo "TESTED_TREE=$TESTED_TREE"
    echo "CURRENT_TREE=$TREE_SHA"
    exit 1
}
[[ "$TESTED_VERSION" == "$VERSION" ]] || {
    echo "DEPLOY_TESTED_VERSION_MISMATCH=true"
    echo "TESTED_VERSION=$TESTED_VERSION"
    echo "CURRENT_VERSION=$VERSION"
    exit 1
}
[[ "$REAL_TRANSPORT" == false ]] || { echo "DEPLOY_EXPECTED_REAL_TRANSPORT_FALSE=FAIL"; exit 1; }
[[ "$LIVE_READY" == false ]] || { echo "DEPLOY_EXPECTED_LIVE_READY_FALSE=FAIL"; exit 1; }

export PYTHONPATH="$POC_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONDONTWRITEBYTECODE=1

echo "=== REPOSITORY READINESS ==="
python3 "$POC_ROOT/scripts/evaluate_plan_readiness.py" "$@"

echo "=== PREDEPLOY OFFLINE SUITE ==="
bash "$POC_ROOT/scripts/run_offline_suite.sh"

STAMP="$(date -u +%Y-%m-%d)"
RELEASE_ID="${STAMP}-v${VERSION}-${HEAD:0:12}"
RELEASE="$RELEASES/$RELEASE_ID"
mkdir -p "$RUNTIME_ROOT" "$RELEASES"
STAGE="$(mktemp -d "$RUNTIME_ROOT/.stage-${RELEASE_ID}.XXXXXX")"
OLD_CURRENT="$(readlink -f "$CURRENT" 2>/dev/null || true)"
PROMOTED=false
RELEASE_CREATED=false

cleanup() {
    rc=$?
    if [[ $rc -ne 0 ]]; then
        if [[ "$PROMOTED" == true ]]; then
            if [[ -n "$OLD_CURRENT" && -d "$OLD_CURRENT" ]]; then
                ln -sfn "$OLD_CURRENT" "$CURRENT"
            else
                rm -f "$CURRENT"
            fi
        fi
        if [[ "$RELEASE_CREATED" == true && -d "$RELEASE" ]]; then
            rm -rf "$RELEASE"
        fi
        rm -rf "$STAGE"
        echo "DEPLOY_RESULT=FAIL"
    fi
    return "$rc"
}
trap cleanup EXIT

# Build only from the committed safety-poc Git tree; ignored/untracked files cannot enter the release.
git -C "$REPO_ROOT" archive HEAD:safety-poc | tar -xf - -C "$STAGE"

cat > "$STAGE/RELEASE_GIT.txt" <<EOF
VERSION=$VERSION
GIT_SHA=$HEAD
GIT_TREE_SHA=$TREE_SHA
TESTED_TREE_SHA=$TESTED_TREE
RELEASE_ID=$RELEASE_ID
REAL_TRANSPORT_IMPLEMENTED=false
LIVE_TEST_READY=false
PHYSICAL_DOOR_ACTION=false
EOF

echo "=== STAGED RELEASE OFFLINE SUITE ==="
(
    export PYTHONPATH="$STAGE/src${PYTHONPATH:+:$PYTHONPATH}"
    bash "$STAGE/scripts/run_offline_suite.sh"
)

(
    cd "$STAGE"
    find . -type f ! -name RELEASE_CONTENT.sha256 -print0 \
        | sort -z \
        | xargs -0 sha256sum > RELEASE_CONTENT.sha256
    sha256sum -c RELEASE_CONTENT.sha256
)

if [[ -e "$RELEASE" ]]; then
    echo "IMMUTABLE_RELEASE_ALREADY_EXISTS=$RELEASE"
    exit 1
fi
mv "$STAGE" "$RELEASE"
RELEASE_CREATED=true
ln -sfn "$RELEASE" "$CURRENT"
PROMOTED=true

echo "=== FINAL OFFLINE SUITE FROM PROMOTED RELEASE ==="
(
    export PYTHONPATH="$CURRENT/src${PYTHONPATH:+:$PYTHONPATH}"
    bash "$CURRENT/scripts/run_offline_suite.sh"
)

echo "=== RELEASE CONTENT VERIFY ==="
(
    cd "$CURRENT"
    sha256sum -c RELEASE_CONTENT.sha256
)

trap - EXIT
echo "DEPLOY_RESULT=PASS"
echo "VERSION=$VERSION"
echo "GIT_SHA=$HEAD"
echo "GIT_TREE_SHA=$TREE_SHA"
echo "TESTED_TREE_SHA=$TESTED_TREE"
echo "OLD_RELEASE=${OLD_CURRENT:-none}"
echo "NEW_RELEASE=$RELEASE"
echo "REAL_TRANSPORT_IMPLEMENTED=false"
echo "LIVE_TEST_READY=false"
echo "PHYSICAL_DOOR_ACTION=false"
