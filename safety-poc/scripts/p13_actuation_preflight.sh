#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
POC_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(git -C "$POC_ROOT" rev-parse --show-toplevel)"
PAYLOAD_FILE=/root/comelit-p13-actuator-prep/real-door-payloads.json
AUDIT_DIR=/root/comelit-p13-audit
AUDIT_FILE="$AUDIT_DIR/audit.jsonl"
EXPECTED_BRANCH=feat/p13-one-shot-actuation

STEP=START
preflight_exit() {
    rc=$?
    echo "P13_PREFLIGHT_EXIT_RC=$rc"
    echo "P13_PREFLIGHT_LAST_STEP=$STEP"
    trap - EXIT
    exit "$rc"
}
trap preflight_exit EXIT

echo "P13_PREFLIGHT_DIAGNOSTIC_TRAP=ARMED"

STEP=IDENTITY
[[ "${EUID}" -eq 0 ]] || { echo "P13_PREFLIGHT_REQUIRES_ROOT=true"; exit 1; }
[[ "$(git -C "$REPO_ROOT" branch --show-current)" == "$EXPECTED_BRANCH" ]] || {
    echo "P13_PREFLIGHT_BRANCH=FAIL"
    exit 1
}
[[ -z "$(git -C "$REPO_ROOT" status --porcelain)" ]] || {
    echo "P13_PREFLIGHT_WORKTREE_CLEAN=false"
    exit 1
}
HEAD="$(git -C "$REPO_ROOT" rev-parse HEAD)"
TREE="$(git -C "$REPO_ROOT" rev-parse HEAD^{tree})"
echo "P13_PREFLIGHT_HEAD=$HEAD"
echo "P13_PREFLIGHT_TREE=$TREE"

STEP=PAYLOAD_IDENTITY
[[ -f "$PAYLOAD_FILE" ]] || { echo "P13_PAYLOAD_PRESENT=false"; exit 1; }
PAYLOAD_MODE="$(stat -c '%a' "$PAYLOAD_FILE")"
[[ "$PAYLOAD_MODE" == "600" ]] || { echo "P13_PAYLOAD_MODE=FAIL($PAYLOAD_MODE)"; exit 1; }
PAYLOAD_SHA="$(sha256sum "$PAYLOAD_FILE" | awk '{print $1}')"
echo "P13_PAYLOAD_SHA256=$PAYLOAD_SHA"

STEP=AUDIT_SINK
mkdir -p "$AUDIT_DIR"
chmod 700 "$AUDIT_DIR"
touch "$AUDIT_FILE"
chmod 600 "$AUDIT_FILE"
python3 - "$AUDIT_FILE" <<'PY'
import json
import os
import sys
from pathlib import Path

path = Path(sys.argv[1])
if path.stat().st_mode & 0o777 != 0o600:
    print("P13_AUDIT_MODE=FAIL")
    sys.exit(1)
if path.exists() and path.stat().st_size > 0:
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            json.loads(line)
print("P13_AUDIT_SINK_DURABLE=PASS")
PY

STEP=NO_CONFLICT
pgrep -x "comelit_ice_offer_holder" >/dev/null && { echo "P13_CONFLICTING_PROCESS=true"; exit 1; } || true
echo "P13_CONFLICTING_PROCESS=false"

STEP=NO_RETRY_SURFACE
grep -rn "retry\|RETRY" "$POC_ROOT/src/comelit_safety_poc/executor.py" >/dev/null && { echo "P13_RETRY_SURFACE_DETECTED=true"; exit 1; } || true
echo "P13_RETRY_SURFACE_DETECTED=false"

STEP=SOURCE_SCAN
python3 "$POC_ROOT/scripts/static_safety_check.py" || { echo "P13_STATIC_SAFETY=FAIL"; exit 1; }
echo "P13_STATIC_SAFETY=PASS"

STEP=UNIT_SUITE
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$POC_ROOT/src" python3 -m unittest discover -s "$POC_ROOT/tests" >/dev/null 2>&1 || {
    echo "P13_UNIT_SUITE=FAIL"
    exit 1
}
echo "P13_UNIT_SUITE=PASS"

STEP=CONTRACT
python3 - "$POC_ROOT/src" <<'PY'
import sys
sys.path.insert(0, sys.argv[1])
from comelit_safety_poc.p13_transport_model import default_p13_contract, P13_ACTUATION_P2P_PLAN
c = default_p13_contract()
c.validate()
assert len(P13_ACTUATION_P2P_PLAN) == 10, "P13 plan must have exactly 10 stages"
print("P13_CONTRACT_VALIDATION=PASS")
PY

STEP=COMPLETE
echo "P13_PREFLIGHT_LAST_STEP=COMPLETE"
echo "P13_NON_ACTUATING_PREFLIGHT=PASS"
echo "P13_PAYLOAD_PRESENT=true"
echo "P13_ONE_SHOT_MAX_INVOCATIONS=1"
echo "P13_AUTO_RETRY_ALLOWED=false"
echo "P13_TARGET_BINDING_REQUIRED=true"
echo "P13_PHYSICAL_EFFECT_ASSERTED=false"
echo "ACTUATION_TRANSPORT_IMPLEMENTED=true"
echo "AUDIT_SINK_VERIFIED=PASS"
echo "EXPLICIT_LIVE_TEST_APPROVAL=false"
echo "LIVE_TEST_READY=false"
echo "P13_ACTUATOR_COMMAND_ATTEMPTED=false"
echo "PHYSICAL_DOOR_ACTION=false"
