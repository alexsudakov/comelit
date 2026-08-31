#!/usr/bin/env bash
# Narrow CT120 root dispatcher intended for Hermes allowlisting.
#
# This is deliberately NOT a generic shell surface. It exposes exactly two
# fixed operations over the already-reviewed P13 wrappers:
#   readiness      -> non-actuating observed-acceptance preflight
#   observed-open  -> single-use observed acceptance gate, but only when the
#                     exact external operator approval phrase is supplied
#
# No host/path/target/payload/operation-id parameters are accepted.
set -Eeuo pipefail
umask 077

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
POC_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(git -C "$POC_ROOT" rev-parse --show-toplevel)"
PREFLIGHT="$SCRIPT_DIR/p13_hermes_observed_acceptance_preflight.sh"
GATE="$SCRIPT_DIR/p13_hermes_observed_acceptance.sh"
EXPECTED_BRANCH=feat/p13-one-shot-actuation
EXPECTED_PREFLIGHT_BLOB=302ebda51439bdfe8b09782e80b0cd531daad237
EXPECTED_GATE_BLOB=f1e40090b6dc458e90a7e662eee2d20d880f2d4d
APPROVAL_PHRASE=I_APPROVE_P13_ONE_SHOT_PHYSICAL_DOOR_TEST
ACTION_PHRASE=OPEN_72K4_3_ONCE

[[ "${EUID}" -eq 0 ]] || { echo 'P13_HERMES_CT120_DISPATCH_REQUIRES_ROOT=true'; exit 1; }
[[ "$(git -C "$REPO_ROOT" branch --show-current)" == "$EXPECTED_BRANCH" ]] || {
    echo 'P13_HERMES_CT120_DISPATCH_BRANCH=FAIL'
    exit 1
}
[[ -z "$(git -C "$REPO_ROOT" status --porcelain)" ]] || {
    echo 'P13_HERMES_CT120_DISPATCH_WORKTREE_CLEAN=false'
    exit 1
}
[[ -f "$PREFLIGHT" && -f "$GATE" ]] || {
    echo 'P13_HERMES_CT120_DISPATCH_SOURCE_PRESENT=false'
    exit 1
}
[[ "$(git -C "$REPO_ROOT" hash-object "$PREFLIGHT")" == "$EXPECTED_PREFLIGHT_BLOB" ]] || {
    echo 'P13_HERMES_CT120_DISPATCH_PREFLIGHT_IDENTITY=FAIL'
    exit 1
}
[[ "$(git -C "$REPO_ROOT" hash-object "$GATE")" == "$EXPECTED_GATE_BLOB" ]] || {
    echo 'P13_HERMES_CT120_DISPATCH_GATE_IDENTITY=FAIL'
    exit 1
}

echo 'P13_HERMES_CT120_DISPATCH_IDENTITY=PASS'

case "${1:-}" in
    readiness)
        [[ $# -eq 1 ]] || { echo 'P13_HERMES_CT120_DISPATCH_REQUEST=REJECTED'; exit 64; }
        echo 'P13_HERMES_CT120_DISPATCH_MODE=READINESS'
        echo 'P13_HERMES_CT120_DISPATCH_PHYSICAL_ACTION=false'
        exec env -u P13_APPROVAL -u P13_OPERATION_ID bash "$PREFLIGHT"
        ;;

    observed-open)
        [[ $# -eq 2 && "${2:-}" == "$APPROVAL_PHRASE" ]] || {
            echo 'P13_HERMES_CT120_DISPATCH_REQUEST=REJECTED'
            echo 'P13_HERMES_CT120_DISPATCH_APPROVAL=REQUIRED'
            exit 64
        }
        echo 'P13_HERMES_CT120_DISPATCH_MODE=OBSERVED_OPEN'
        echo 'P13_HERMES_CT120_DISPATCH_APPROVAL=GRANTED'
        echo 'P13_HERMES_CT120_DISPATCH_WARNING=PHYSICAL_DOOR_MAY_OPEN'
        # Exactly one handoff to the already single-use outer acceptance gate.
        exec bash "$GATE" "$ACTION_PHRASE"
        ;;

    *)
        echo 'P13_HERMES_CT120_DISPATCH_REQUEST=REJECTED'
        echo 'P13_HERMES_CT120_DISPATCH_ALLOWED=readiness|observed-open'
        exit 64
        ;;
esac
