#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
POC_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(git -C "$POC_ROOT" rev-parse --show-toplevel)"

EXPECTED_BRANCH=feat/p13-one-shot-actuation

PROD_ROOT=/opt/comelit-door-safety-poc/p13
RELEASES="$PROD_ROOT/releases"
CURRENT="$PROD_ROOT/current"
PREVIOUS="$PROD_ROOT/previous"
RETIRED="$PROD_ROOT/retired"

HOLDER=/root/comelit-p13-native/comelit_p13_holder
WRAPPER=/usr/local/sbin/comelit-p13-door-wrapper
PAYLOAD=/root/comelit-p13-actuator-prep/real-door-payloads.json
IDENTITY=/root/comelit-p13-runtime-identity.json
GATE_STATE=/root/comelit-p13-run/hermes-observed-acceptance-v1.state

DISPATCH_SOURCE="$POC_ROOT/deploy/p13_production_runtime_dispatch.sh"
DISPATCH_DEST=/usr/local/sbin/comelit-p13-hermes-dispatch

EXPECTED_HOLDER_SHA=50c0a916f73ec810f131be1f48f47761a2cc69b9d06107d121519f97c538b450
EXPECTED_WRAPPER_SHA=bf36b381f4921871f0b4df0820548b8943b935f1dfcd1521ceb79001dab71aa9
EXPECTED_PAYLOAD_SHA=0d0159f9cc562c1c67bc362b192a30d3fabd634b2b92c3a96d8f318ecd842832

OBSERVED_EVIDENCE_COMMIT=c572010fa05da36058cc634ac1dd250f11e98857
OBSERVED_EVIDENCE_PATH=safety-poc/evidence/p13-observed-open-20260831T185826Z.txt

STEP=START
STAGE=""
RELEASE=""
RELEASE_CREATED=false
PROMOTED=false
DISPATCH_CHANGED=false
OLD_CURRENT=""
OLD_DISPATCH_BACKUP=""

cleanup() {
    rc=$?

    if [[ $rc -ne 0 ]]; then
        if [[ "$DISPATCH_CHANGED" == true && -n "$OLD_DISPATCH_BACKUP" && -f "$OLD_DISPATCH_BACKUP" ]]; then
            install -m 755 -o root -g root "$OLD_DISPATCH_BACKUP" "$DISPATCH_DEST"
        fi

        if [[ "$PROMOTED" == true ]]; then
            if [[ -n "$OLD_CURRENT" && -d "$OLD_CURRENT" ]]; then
                ln -sfn "$OLD_CURRENT" "$CURRENT"
            else
                rm -f "$CURRENT"
            fi
        fi

        if [[ "$RELEASE_CREATED" == true && -n "$RELEASE" && -d "$RELEASE" ]]; then
            rm -rf "$RELEASE"
        fi

        [[ -z "$STAGE" ]] || rm -rf "$STAGE"

        echo 'P13_PRODUCTION_INSTALL=FAIL'
        echo "P13_PRODUCTION_INSTALL_LAST_STEP=$STEP"
    fi

    return "$rc"
}
trap cleanup EXIT

echo 'P13_PRODUCTION_INSTALL_START=true'
echo 'P13_PRODUCTION_INSTALL_NON_ACTUATING=true'

STEP=IDENTITY

[[ "${EUID}" -eq 0 ]] || {
    echo 'P13_PRODUCTION_INSTALL_REQUIRES_ROOT=true'
    exit 1
}

git -C "$REPO_ROOT" fetch origin "$EXPECTED_BRANCH"

[[ "$(git -C "$REPO_ROOT" branch --show-current)" == "$EXPECTED_BRANCH" ]] || {
    echo 'P13_PRODUCTION_INSTALL_BRANCH=FAIL'
    exit 1
}

LOCAL_HEAD="$(git -C "$REPO_ROOT" rev-parse HEAD)"
REMOTE_HEAD="$(git -C "$REPO_ROOT" rev-parse "origin/$EXPECTED_BRANCH")"
TREE="$(git -C "$REPO_ROOT" rev-parse 'HEAD^{tree}')"

[[ "$LOCAL_HEAD" == "$REMOTE_HEAD" ]] || {
    echo 'P13_PRODUCTION_INSTALL_REMOTE_IDENTITY=FAIL'
    exit 1
}

[[ -z "$(git -C "$REPO_ROOT" status --porcelain)" ]] || {
    echo 'P13_PRODUCTION_INSTALL_WORKTREE_DIRTY=true'
    exit 1
}

echo "P13_PRODUCTION_SOURCE_HEAD=$LOCAL_HEAD"
echo "P13_PRODUCTION_SOURCE_TREE=$TREE"

STEP=RUNTIME_IDENTITY

[[ -f "$HOLDER" && -f "$WRAPPER" && -f "$PAYLOAD" && -f "$IDENTITY" ]]
[[ -f "$DISPATCH_SOURCE" ]]
[[ -f "$GATE_STATE" ]]

[[ "$(cat "$GATE_STATE")" == 'CONSUMED_BEFORE_LIVE_ENTRYPOINT' ]]

[[ "$(stat -c '%u:%a' "$HOLDER")" == '0:700' ]]
[[ "$(stat -c '%u:%a' "$WRAPPER")" == '0:700' ]]
[[ "$(stat -c '%u:%a' "$PAYLOAD")" == '0:600' ]]

[[ "$(sha256sum "$HOLDER" | awk '{print $1}')" == "$EXPECTED_HOLDER_SHA" ]]
[[ "$(sha256sum "$WRAPPER" | awk '{print $1}')" == "$EXPECTED_WRAPPER_SHA" ]]
[[ "$(sha256sum "$PAYLOAD" | awk '{print $1}')" == "$EXPECTED_PAYLOAD_SHA" ]]

python3 - "$IDENTITY" \
    "$EXPECTED_HOLDER_SHA" \
    "$EXPECTED_WRAPPER_SHA" \
    "$EXPECTED_PAYLOAD_SHA" <<'PY'
import json
import sys

path, holder_sha, wrapper_sha, payload_sha = sys.argv[1:]
obj = json.load(open(path, encoding="utf-8"))

assert obj["identity_type"] == "RUNTIME_IDENTITY_POC"
assert obj["holder"]["sha256"] == holder_sha
assert obj["holder"]["entrypoint"] == "NO_ARGUMENTS"
assert obj["wrapper"]["sha256"] == wrapper_sha
assert obj["payload"]["sha256"] == payload_sha
assert str(obj["payload"]["write_count"]) == "6"

print("P13_PRODUCTION_RUNTIME_IDENTITY_INPUT=PASS")
PY

STEP=STAGE

DISPATCH_SHA="$(sha256sum "$DISPATCH_SOURCE" | awk '{print $1}')"
RELEASE_ID="p13-${TREE:0:12}-${EXPECTED_HOLDER_SHA:0:12}-${DISPATCH_SHA:0:12}"

mkdir -p "$RELEASES" "$RETIRED"
chmod 700 "$PROD_ROOT" "$RELEASES" "$RETIRED"

RELEASE="$RELEASES/$RELEASE_ID"

if [[ -d "$RELEASE" ]]; then
    echo "P13_PRODUCTION_RELEASE_ALREADY_EXISTS=$RELEASE_ID"

    (
        cd "$RELEASE"
        sha256sum -c RELEASE_CONTENT.sha256 >/dev/null
    )

else
    STAGE="$(mktemp -d "$PROD_ROOT/.stage-${RELEASE_ID}.XXXXXX")"
    chmod 700 "$STAGE"

    mkdir -p \
        "$STAGE/repo" \
        "$STAGE/runtime-proof"

    git -C "$REPO_ROOT" archive HEAD:safety-poc \
        | tar -xf - -C "$STAGE/repo"

    install -m 700 -o root -g root \
        "$HOLDER" \
        "$STAGE/runtime-proof/comelit_p13_holder"

    install -m 700 -o root -g root \
        "$WRAPPER" \
        "$STAGE/runtime-proof/comelit-p13-door-wrapper"

    install -m 600 -o root -g root \
        "$PAYLOAD" \
        "$STAGE/runtime-proof/real-door-payloads.json"

    install -m 600 -o root -g root \
        "$IDENTITY" \
        "$STAGE/runtime-proof/runtime-identity-poc.json"

    cat >"$STAGE/RELEASE.env" <<EOF
P13_PRODUCTION_RELEASE_SCHEMA=1
P13_RELEASE_ID=$RELEASE_ID
P13_SOURCE_HEAD=$LOCAL_HEAD
P13_SOURCE_TREE=$TREE
P13_TARGET_FINGERPRINT=832e5c09cf5f8ef79b9af83ba34b38a0a29847570ea37158310369850e2500ce
P13_HOLDER_SHA256=$EXPECTED_HOLDER_SHA
P13_WRAPPER_SHA256=$EXPECTED_WRAPPER_SHA
P13_PAYLOAD_SHA256=$EXPECTED_PAYLOAD_SHA
P13_PRODUCTION_DISPATCH_SHA256=$DISPATCH_SHA
P13_OBSERVED_EVIDENCE_COMMIT=$OBSERVED_EVIDENCE_COMMIT
P13_OBSERVED_EVIDENCE_PATH=$OBSERVED_EVIDENCE_PATH
P13_PROTOCOL_STATE=UNKNOWN_OUTCOME
P13_DOOR_SPECIFIC_ACK=UNPROVEN
P13_PHYSICAL_OBSERVATION=OPENED
P13_OBSERVED_PHYSICAL_ACCEPTANCE=PASS
P13_OBSERVED_ACCEPTANCE_GATE_TERMINAL=CONSUMED
P13_PRODUCTION_OBSERVED_OPEN_RETIRED=true
P13_PRODUCTION_LIVE_COMMAND_EXPOSED=false
P13_AUTO_RETRY_ALLOWED=false
P13_PHYSICAL_EFFECT_ASSERTED=false
EOF

    chmod 600 "$STAGE/RELEASE.env"

    (
        cd "$STAGE"
        find . \
            -type f \
            ! -name RELEASE_CONTENT.sha256 \
            -print0 \
            | sort -z \
            | xargs -0 sha256sum \
            >RELEASE_CONTENT.sha256

        chmod 600 RELEASE_CONTENT.sha256
        sha256sum -c RELEASE_CONTENT.sha256 >/dev/null
    )

    mv "$STAGE" "$RELEASE"
    STAGE=""
    RELEASE_CREATED=true

    echo "P13_PRODUCTION_RELEASE_CREATED=$RELEASE_ID"
fi

STEP=PROMOTE

OLD_CURRENT=""

# First install has no current selector.  Bare `readlink -f` is not an
# existence test because GNU readlink can canonicalize a missing final path
# component.
if [[ -L "$CURRENT" ]]; then
    OLD_CURRENT="$(readlink -f "$CURRENT" 2>/dev/null || true)"

    [[ -n "$OLD_CURRENT" && -d "$OLD_CURRENT" ]] || {
        echo 'P13_PRODUCTION_OLD_CURRENT_TARGET=FAIL'
        exit 1
    }

elif [[ -e "$CURRENT" ]]; then
    echo 'P13_PRODUCTION_CURRENT_NOT_SYMLINK=true'
    exit 1

else
    echo 'P13_PRODUCTION_FIRST_INSTALL=true'
fi

if [[ -n "$OLD_CURRENT" && "$OLD_CURRENT" != "$RELEASE" ]]; then
    case "$OLD_CURRENT" in
        "$RELEASES"/*)
            ln -sfn "$OLD_CURRENT" "$PREVIOUS"
            ;;
        *)
            echo 'P13_PRODUCTION_OLD_CURRENT_SCOPE=FAIL'
            exit 1
            ;;
    esac
fi

ln -sfn "$RELEASE" "$CURRENT"
PROMOTED=true

STEP=RETIRE_POC_DISPATCH

if [[ -f "$DISPATCH_DEST" ]]; then
    OLD_DISPATCH_SHA="$(sha256sum "$DISPATCH_DEST" | awk '{print $1}')"

    RETIRED_COPY="$RETIRED/poc-dispatch-${OLD_DISPATCH_SHA}"

    if [[ ! -f "$RETIRED_COPY" ]]; then
        install -m 700 -o root -g root \
            "$DISPATCH_DEST" \
            "$RETIRED_COPY"
    fi

    OLD_DISPATCH_BACKUP="$(mktemp /root/p13-old-dispatch.XXXXXX)"
    cp -a "$DISPATCH_DEST" "$OLD_DISPATCH_BACKUP"
fi

install -m 755 -o root -g root \
    "$CURRENT/repo/deploy/p13_production_runtime_dispatch.sh" \
    "$DISPATCH_DEST"

DISPATCH_CHANGED=true

STEP=VERIFY

"$DISPATCH_DEST" readiness

grep -Fq \
    "P13_PRODUCTION_OBSERVED_OPEN_RETIRED=true" \
    "$DISPATCH_DEST"

if grep -Eq \
    'p13_hermes_observed_acceptance|p13_one_shot_physical_runner|p13_hermes_one_shot|exec[[:space:]]+bash.*GATE' \
    "$DISPATCH_DEST"
then
    echo 'P13_PRODUCTION_DISPATCH_LIVE_HANDOFF_PRESENT=true'
    exit 1
fi

[[ "$(readlink -f "$CURRENT")" == "$RELEASE" ]]

(
    cd "$CURRENT"
    sha256sum -c RELEASE_CONTENT.sha256 >/dev/null
)

STEP=COMPLETE
trap - EXIT

rm -f "$OLD_DISPATCH_BACKUP"

echo 'P13_PRODUCTION_INSTALL=PASS'
echo "P13_PRODUCTION_RELEASE_ID=$RELEASE_ID"
echo "P13_PRODUCTION_CURRENT=$(readlink -f "$CURRENT")"
if [[ -L "$PREVIOUS" ]]; then
    PREVIOUS_REAL="$(readlink -f "$PREVIOUS")"
else
    PREVIOUS_REAL=none
fi
echo "P13_PRODUCTION_PREVIOUS=$PREVIOUS_REAL"
echo 'P13_PRODUCTION_OBSERVED_OPEN_RETIRED=true'
echo 'P13_PRODUCTION_LIVE_COMMAND_EXPOSED=false'
echo 'P13_COMELIT_NETWORK_ACTION_PERFORMED=false'
echo 'NETWORK_DOOR_ACTION_PERFORMED=false'
echo 'PHYSICAL_DOOR_ACTION=false'
echo 'SEND_ARMED_REACHED=false'
echo 'P13_ACTUATOR_COMMAND_ATTEMPTED=false'
