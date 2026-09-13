#!/usr/bin/env bash
# CT120 research-only P116/R28 listener-attached inbound media runner.
# Live execution is disabled by default.  This runner materializes a candidate
# helper and substitutes it into a per-lane wrapper before any possible live
# step, preserving the R27 lesson that helper paths must never silently fall
# back to the base wrapper.

set -u -o pipefail
umask 077

REPO=${REPO:-/root/comelit-door-diag-repo}
R28_LIVE_RUN=${R28_LIVE_RUN:-false}
R28_EXPECTED_COMMIT_SHA=${R28_EXPECTED_COMMIT_SHA:-}
BASE_WRAPPER=${BASE_WRAPPER:-/usr/local/sbin/comelit-p2p-cloud-probe}
RUN_ROOT=${RUN_ROOT:-/run/comelit-r28-listener-attached-media}
TRANSFORM_REL=safety-poc/research/media/v1/entrance_p116_r28_listener_attached_media_transform.py
HELPER_NAME=comelit-r28-listener-attached-media-helper
WRAPPER_NAME=comelit-p2p-cloud-probe-r28-listener-attached-media

FAIL=0
LIVE_STEP_REACHED=false
CANDIDATE_HELPER_EXECUTED=false
CANDIDATE_HELPER_PROVENANCE=false
CANDIDATE_HELPER=""
CANDIDATE_WRAPPER=""

fail() {
    echo "$1"
    FAIL=1
}

require_file() {
    if [ ! -f "$1" ]; then
        fail "MISSING_FILE=$1"
        return 1
    fi
    return 0
}

materialize_candidate_helper() {
    local helper_dir
    helper_dir="$RUN_ROOT/helper"
    install -d -m 700 "$helper_dir" || return 1
    CANDIDATE_HELPER="$helper_dir/$HELPER_NAME"
    cat > "$CANDIDATE_HELPER" <<'SH'
#!/usr/bin/env bash
set -u -o pipefail
echo "CANDIDATE_HELPER_EXECUTED=true"
echo "R28_HELPER_NO_NETWORK=true"
echo "R28_HELPER_NO_DOOR_ACTION=true"
echo "R28_HELPER_NO_GATE_ACTION=true"
echo "R28_HELPER_NO_REFRESH_LOOP=true"
echo "R28_HELPER_NEW_ICE_BOOTSTRAP=false"
echo "R28_HELPER_NEW_CLOUD_NEGOTIATION=false"
echo "R28_HELPER_NEW_PSEUDOTCP_SESSION=false"
echo "R28_HELPER_NEW_CTPP_REGISTRATION=false"
SH
    chmod 700 "$CANDIDATE_HELPER" || return 1
    CANDIDATE_HELPER_PROVENANCE=true
}

materialize_candidate_wrapper() {
    local wrapper_dir
    wrapper_dir="$RUN_ROOT/wrapper"
    install -d -m 700 "$wrapper_dir" || return 1
    CANDIDATE_WRAPPER="$wrapper_dir/$WRAPPER_NAME"
    sed "s|__R28_CANDIDATE_HELPER__|$CANDIDATE_HELPER|g" > "$CANDIDATE_WRAPPER" <<'SH'
#!/usr/bin/env bash
set -u -o pipefail
exec "__R28_CANDIDATE_HELPER__" "$@"
SH
    chmod 700 "$CANDIDATE_WRAPPER" || return 1
}

verify_candidate_contract() {
    local output
    output="$RUN_ROOT/candidate-helper-contract.log"
    "$CANDIDATE_WRAPPER" --self-check > "$output"
    if grep -qx 'CANDIDATE_HELPER_EXECUTED=true' "$output" &&
       grep -qx 'R28_HELPER_NO_NETWORK=true' "$output" &&
       grep -qx 'R28_HELPER_NO_DOOR_ACTION=true' "$output" &&
       grep -qx 'R28_HELPER_NO_GATE_ACTION=true' "$output"; then
        CANDIDATE_HELPER_EXECUTED=true
        echo "CANDIDATE_HELPER_EXECUTED=true"
        echo "CANDIDATE_HELPER_PROVENANCE=$CANDIDATE_HELPER_PROVENANCE"
    else
        fail "CANDIDATE_HELPER_EVIDENCE_CONTRACT=FAIL"
    fi
}

main() {
    cd "$REPO" || exit 2
    require_file "$TRANSFORM_REL" || true
    require_file "$BASE_WRAPPER" || true
    install -d -m 700 "$RUN_ROOT" || exit 2
    materialize_candidate_helper || fail "CANDIDATE_HELPER_MATERIALIZE=FAIL"
    materialize_candidate_wrapper || fail "CANDIDATE_WRAPPER_MATERIALIZE=FAIL"
    if [ "$FAIL" -eq 0 ]; then
        verify_candidate_contract
    fi

    echo "R28_LIVE_RUN_DEFAULT=false"
    echo "R28_LIVE_RUN=$R28_LIVE_RUN"
    if [ "$R28_LIVE_RUN" != "true" ]; then
        echo "LIVE_RUN=NOT_RUN"
        exit "$FAIL"
    fi

    if [ -z "$R28_EXPECTED_COMMIT_SHA" ]; then
        fail "R28_EXPECTED_COMMIT_SHA_REQUIRED=true"
    fi
    if [ "$CANDIDATE_HELPER_EXECUTED" != "true" ] ||
       [ "$CANDIDATE_HELPER_PROVENANCE" != "true" ]; then
        fail "LIVE_BLOCKED_CANDIDATE_HELPER_EVIDENCE_REQUIRED=true"
    fi
    if [ "$FAIL" -ne 0 ]; then
        echo "LIVE_RUN=NOT_RUN"
        exit "$FAIL"
    fi

    LIVE_STEP_REACHED=true
    echo "LIVE_STEP_REACHED=$LIVE_STEP_REACHED"
    echo "LIVE_RUN=BLOCKED_BY_ROUND4_OFFLINE_CONTRACT"
    exit 1
}

main "$@"
