#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

# P13 operator-gated physical one-shot runner.
#
# This runner is intentionally NOT executable by this task: it requires the
# exact operator approval token at execution time, verifies all preconditions
# (identity, payload hashes, audit durability, target binding, no conflicting
# process), persists PREPARED and SEND_ARMED in a durable SQLite journal, then
# invokes the real transport exactly once.  There is no retry anywhere.
#
# Usage:
#     P13_APPROVAL=I_APPROVE_P13_ONE_SHOT_PHYSICAL_DOOR_TEST \
#     p13_one_shot_physical_runner.sh --db <path> --operation-id <id> \
#       --target-fingerprint <fp> [--min-interval-seconds 10]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
POC_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(git -C "$POC_ROOT" rev-parse --show-toplevel)"
PAYLOAD_FILE=/root/comelit-p13-actuator-prep/real-door-payloads.json
WRAPPER=/usr/local/sbin/comelit-p13-door-wrapper
AUDIT_DIR=/root/comelit-p13-audit
AUDIT_FILE="$AUDIT_DIR/audit.jsonl"
RUN_DIR=/root/comelit-p13-run
EXPECTED_BRANCH=feat/p13-one-shot-actuation
APPROVAL_TOKEN=I_APPROVE_P13_ONE_SHOT_PHYSICAL_DOOR_TEST
# Runtime identity (PoC): the expected wrapper identity is read from the
# root-only runtime identity file captured by p13_capture_runtime_identity.sh.
IDENTITY_FILE=/root/comelit-p13-runtime-identity.json
EXPECTED_WRAPPER_MODE="${P13_EXPECTED_WRAPPER_MODE:-700}"

# -- arguments ------------------------------------------------------------
DB=""
OPERATION_ID=""
TARGET_FP=""
MIN_INTERVAL=10

usage() {
    echo "usage: $0 --db <path> --operation-id <id> --target-fingerprint <fp> [--min-interval-seconds N]" >&2
    exit 64
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --db) DB="$2"; shift 2 ;;
        --operation-id) OPERATION_ID="$2"; shift 2 ;;
        --target-fingerprint) TARGET_FP="$2"; shift 2 ;;
        --min-interval-seconds) MIN_INTERVAL="$2"; shift 2 ;;
        *) usage ;;
    esac
done

[[ -n "$DB" && -n "$OPERATION_ID" && -n "$TARGET_FP" ]] || usage
[[ "$TARGET_FP" =~ ^[0-9a-f]{64}$ ]] || { echo "P13_TARGET_FINGERPRINT_FORMAT=FAIL"; exit 65; }
[[ "$MIN_INTERVAL" =~ ^[0-9]+$ ]] || usage

STEP=START
runner_exit() {
    rc=$?
    echo "P13_ONE_SHOT_EXIT_RC=$rc"
    echo "P13_ONE_SHOT_LAST_STEP=$STEP"
    trap - EXIT
    exit "$rc"
}
trap runner_exit EXIT
echo "P13_ONE_SHOT_DIAGNOSTIC_TRAP=ARMED"

# -- operator gate --------------------------------------------------------
STEP=APPROVAL
[[ "${EUID}" -eq 0 ]] || { echo "P13_ONE_SHOT_REQUIRES_ROOT=true"; exit 1; }
if [[ "${P13_APPROVAL:-}" != "$APPROVAL_TOKEN" ]]; then
    echo "P13_ONE_SHOT_APPROVAL=FAIL"
    echo "P13_ONE_SHOT_APPROVAL_EXPECTED=$APPROVAL_TOKEN"
    exit 1
fi
echo "P13_ONE_SHOT_APPROVAL=GRANTED"

# -- preflight gate (identity, audit, no conflict) ------------------------
STEP=PREFLIGHT
# The live approval belongs only to this outer physical runner.  The preflight
# is non-actuating and includes negative approval tests, so it must run in a
# child environment where live execution identity is absent.  env -u affects
# only the preflight child; P13_APPROVAL remains available below for EXECUTE.
if ! env -u P13_APPROVAL -u P13_OPERATION_ID \
    bash "$SCRIPT_DIR/p13_actuation_preflight.sh" >/dev/null 2>&1; then
    echo "P13_ONE_SHOT_PREFLIGHT=FAIL"
    exit 1
fi
echo "P13_ONE_SHOT_PREFLIGHT=PASS"

# -- exact pre-arm binding -------------------------------------------------
STEP=PAYLOAD_HASH
PAYLOAD_SHA="$(sha256sum "$PAYLOAD_FILE" | awk '{print $1}')"
echo "P13_ONE_SHOT_PAYLOAD_SHA256=$PAYLOAD_SHA"

# -- durable execution via the typed boundary ------------------------------
STEP=EXECUTE
export PYTHONPATH="$POC_ROOT/src"
export PYTHONDONTWRITEBYTECODE=1

# Runtime identity from the captured root-only identity file.
if [[ ! -f "$IDENTITY_FILE" ]]; then
    echo "P13_RUNTIME_IDENTITY_ABSENT=true"
    exit 1
fi
EXPECTED_WRAPPER_SHA256="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["wrapper"]["sha256"])' "$IDENTITY_FILE")"

python3 -m comelit_safety_poc.p13_one_shot_physical \
    --db "$DB" \
    --operation-id "$OPERATION_ID" \
    --target-fingerprint "$TARGET_FP" \
    --min-interval-seconds "$MIN_INTERVAL" \
    --wrapper "$WRAPPER" \
    --wrapper-sha256 "$EXPECTED_WRAPPER_SHA256" \
    --wrapper-mode "$EXPECTED_WRAPPER_MODE" \
    --payload "$PAYLOAD_FILE" \
    --payload-sha256 "$PAYLOAD_SHA" \
    --audit "$AUDIT_FILE" \
    --head "$(git -C "$REPO_ROOT" rev-parse HEAD)" \
    --tree "$(git -C "$REPO_ROOT" rev-parse HEAD^{tree})"

STEP=COMPLETE
echo "P13_ONE_SHOT_LAST_STEP=COMPLETE"
