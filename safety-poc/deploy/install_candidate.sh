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

HEAD="$(git -C "$REPO_ROOT" rev-parse HEAD)"
VERSION="$(awk -F'"' '/^version = / {print $2; exit}' "$POC_ROOT/pyproject.toml")"
if [[ -z "$VERSION" ]]; then
    echo "VERSION_RESOLUTION=FAIL"
    exit 1
fi
if [[ "$VERSION" == *dev* ]]; then
    echo "DEPLOY_BLOCKED_DEVELOPMENT_VERSION=$VERSION"
    exit 1
fi

export PYTHONPATH="$POC_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONDONTWRITEBYTECODE=1

echo "=== REPOSITORY READINESS ==="
python3 "$POC_ROOT/scripts/evaluate_plan_readiness.py" "$@"

echo "=== PREDEPLOY OFFLINE SUITE ==="
bash "$POC_ROOT/scripts/run_offline_suite.sh"

STAMP="$(date -u +%Y-%m-%d)"
RELEASE_ID="${STAMP}-v${VERSION}-${HEAD:0:12}"
RELEASE="$RELEASES/$RELEASE_ID"
STAGE="$(mktemp -d "$RUNTIME_ROOT/.stage-${RELEASE_ID}.XXXXXX")"
OLD_CURRENT="$(readlink -f "$CURRENT" 2>/dev/null || true)"
PROMOTED=false

cleanup() {
    rc=$?
    if [[ $rc -ne 0 ]]; then
        if [[ "$PROMOTED" == true && -n "$OLD_CURRENT" && -d "$OLD_CURRENT" ]]; then
            ln -sfn "$OLD_CURRENT" "$CURRENT"
        fi
        rm -rf "$STAGE"
        echo "DEPLOY_RESULT=FAIL"
    fi
    return "$rc"
}
trap cleanup EXIT

mkdir -p "$RELEASES"
cp -a "$POC_ROOT/." "$STAGE/"

cat > "$STAGE/RELEASE_GIT.txt" <<EOF
VERSION=$VERSION
GIT_SHA=$HEAD
RELEASE_ID=$RELEASE_ID
REAL_TRANSPORT_IMPLEMENTED=false
PHYSICAL_DOOR_ACTION=false
EOF

(
    cd "$STAGE"
    find . -type f ! -name RELEASE_CONTENT.sha256 -print0 \
        | sort -z \
        | xargs -0 sha256sum > RELEASE_CONTENT.sha256
)

if [[ -e "$RELEASE" ]]; then
    echo "IMMUTABLE_RELEASE_ALREADY_EXISTS=$RELEASE"
    exit 1
fi
mv "$STAGE" "$RELEASE"
ln -sfn "$RELEASE" "$CURRENT"
PROMOTED=true

echo "=== FINAL OFFLINE SUITE FROM PROMOTED RELEASE ==="
bash "$CURRENT/scripts/run_offline_suite.sh"

echo "=== RELEASE CONTENT VERIFY ==="
(
    cd "$CURRENT"
    sha256sum -c RELEASE_CONTENT.sha256
)

trap - EXIT
echo "DEPLOY_RESULT=PASS"
echo "VERSION=$VERSION"
echo "GIT_SHA=$HEAD"
echo "OLD_RELEASE=${OLD_CURRENT:-none}"
echo "NEW_RELEASE=$RELEASE"
echo "REAL_TRANSPORT_IMPLEMENTED=false"
echo "PHYSICAL_DOOR_ACTION=false"
