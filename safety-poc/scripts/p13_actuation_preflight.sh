#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
POC_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(git -C "$POC_ROOT" rev-parse --show-toplevel)"
PAYLOAD_FILE=/root/comelit-p13-actuator-prep/real-door-payloads.json
WRAPPER=/usr/local/sbin/comelit-p13-door-wrapper
AUDIT_DIR=/root/comelit-p13-audit
AUDIT_FILE="$AUDIT_DIR/audit.jsonl"
IDENTITY_FILE=/root/comelit-p13-runtime-identity.json
EXPECTED_BRANCH=feat/p13-one-shot-actuation

# Runtime-derived wrapper identity.  The wrapper is the single native
# entrypoint for the proven P2P -> ViP -> UAUT -> CTPP -> six-write path.
# Preflight may emit ACTUATION_TRANSPORT_IMPLEMENTED=true only when the live
# holder/wrapper/payload match the runtime identity captured once by
# scripts/p13_capture_runtime_identity.sh (per P13_POC_DIRECT_PATH.md, this is
# runtime identity validation, not reproducible provenance).
EXPECTED_WRAPPER_MODE="${P13_EXPECTED_WRAPPER_MODE:-700}"

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

STEP=RUNTIME_IDENTITY
# The captured runtime identity is authoritative for this PoC: live artifacts
# must match it exactly.  If it is absent, the operator must run
# p13_capture_runtime_identity.sh once (one root command) before preflight.
if [[ ! -f "$IDENTITY_FILE" ]]; then
    echo "P13_RUNTIME_IDENTITY_ABSENT=true"
    echo "P13_RUNTIME_IDENTITY_ACTION=run p13_capture_runtime_identity.sh"
    echo "ACTUATION_TRANSPORT_IMPLEMENTED=false"
    exit 1
fi
EXPECTED_HOLDER_SHA256="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["holder"]["sha256"])' "$IDENTITY_FILE")"
EXPECTED_HOLDER_PATH="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["holder"]["path"])' "$IDENTITY_FILE")"
EXPECTED_WRAPPER_SHA256="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["wrapper"]["sha256"])' "$IDENTITY_FILE")"
EXPECTED_PAYLOAD_SHA256="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["payload"]["sha256"])' "$IDENTITY_FILE")"
EXPECTED_PAYLOAD_WRITE_COUNT="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["payload"]["write_count"])' "$IDENTITY_FILE")"
EXPECTED_TARGET_FP="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["payload"]["target_fingerprint"])' "$IDENTITY_FILE")"

STEP=HOLDER_IDENTITY
[[ -f "$EXPECTED_HOLDER_PATH" ]] || { echo "P13_HOLDER_PRESENT=false"; exit 1; }
HOLDER_SHA="$(sha256sum "$EXPECTED_HOLDER_PATH" | awk '{print $1}')"
[[ "$HOLDER_SHA" == "$EXPECTED_HOLDER_SHA256" ]] || { echo "P13_HOLDER_SHA256=FAIL"; exit 1; }
HOLDER_UID="$(stat -c '%u' "$EXPECTED_HOLDER_PATH")"
[[ "$HOLDER_UID" == "0" ]] || { echo "P13_HOLDER_OWNER=FAIL(uid=$HOLDER_UID)"; exit 1; }
HOLDER_MODE="$(stat -c '%a' "$EXPECTED_HOLDER_PATH")"
[[ "$HOLDER_MODE" == "700" ]] || { echo "P13_HOLDER_MODE=FAIL($HOLDER_MODE)"; exit 1; }
echo "P13_HOLDER_PRESENT=true"
echo "P13_HOLDER_SHA256=$HOLDER_SHA"
echo "P13_HOLDER_OWNER=root"

STEP=WRAPPER_IDENTITY
[[ -f "$WRAPPER" ]] || { echo "P13_REAL_WRAPPER_PRESENT=false"; exit 1; }
WRAPPER_UID="$(stat -c '%u' "$WRAPPER")"
[[ "$WRAPPER_UID" == "0" ]] || {
    echo "P13_REAL_WRAPPER_OWNER=FAIL(uid=$WRAPPER_UID)"
    echo "ACTUATION_TRANSPORT_IMPLEMENTED=false"
    exit 1
}
WRAPPER_MODE="$(stat -c '%a' "$WRAPPER")"
[[ "$WRAPPER_MODE" == "$EXPECTED_WRAPPER_MODE" ]] || {
    echo "P13_REAL_WRAPPER_MODE=FAIL($WRAPPER_MODE)"
    echo "ACTUATION_TRANSPORT_IMPLEMENTED=false"
    exit 1
}
WRAPPER_SHA="$(sha256sum "$WRAPPER" | awk '{print $1}')"
[[ "$WRAPPER_SHA" == "$EXPECTED_WRAPPER_SHA256" ]] || {
    echo "P13_REAL_WRAPPER_SHA256=FAIL"
    echo "ACTUATION_TRANSPORT_IMPLEMENTED=false"
    exit 1
}
# wrapper must point at the exact captured holder
if grep -q "HOLDER_PATH=\"$EXPECTED_HOLDER_PATH\"" "$WRAPPER" 2>/dev/null; then
    echo "P13_REAL_WRAPPER_HOLDER_BIND=PASS"
else
    echo "P13_REAL_WRAPPER_HOLDER_BIND=FAIL"
    echo "ACTUATION_TRANSPORT_IMPLEMENTED=false"
    exit 1
fi
echo "P13_REAL_WRAPPER_PRESENT=true"
echo "P13_REAL_WRAPPER_SHA256=$WRAPPER_SHA"
echo "P13_REAL_WRAPPER_MODE=$WRAPPER_MODE"
echo "P13_REAL_WRAPPER_OWNER=root"

STEP=PAYLOAD_IDENTITY
[[ -f "$PAYLOAD_FILE" ]] || { echo "P13_PAYLOAD_PRESENT=false"; exit 1; }
PAYLOAD_UID="$(stat -c '%u' "$PAYLOAD_FILE")"
[[ "$PAYLOAD_UID" == "0" ]] || {
    echo "P13_PAYLOAD_OWNER=FAIL(uid=$PAYLOAD_UID)"
    echo "ACTUATION_TRANSPORT_IMPLEMENTED=false"
    exit 1
}
PAYLOAD_MODE="$(stat -c '%a' "$PAYLOAD_FILE")"
[[ "$PAYLOAD_MODE" == "600" ]] || { echo "P13_PAYLOAD_MODE=FAIL($PAYLOAD_MODE)"; exit 1; }
PAYLOAD_SHA="$(sha256sum "$PAYLOAD_FILE" | awk '{print $1}')"
[[ "$PAYLOAD_SHA" == "$EXPECTED_PAYLOAD_SHA256" ]] || {
    echo "P13_PAYLOAD_SHA256=FAIL"
    echo "ACTUATION_TRANSPORT_IMPLEMENTED=false"
    exit 1
}
echo "P13_PAYLOAD_PRESENT=true"
echo "P13_PAYLOAD_SHA256=$PAYLOAD_SHA"
echo "P13_PAYLOAD_MODE=$PAYLOAD_MODE"

STEP=REAL_ADAPTER_DRY_INIT
if ! python3 "$SCRIPT_DIR/p13_adapter_dry_init.py" \
    --payload "$PAYLOAD_FILE" \
    --wrapper "$WRAPPER" \
    --wrapper-sha256 "$EXPECTED_WRAPPER_SHA256" \
    --wrapper-mode "$EXPECTED_WRAPPER_MODE"; then
    echo "P13_REAL_ADAPTER_DRY_INIT=FAIL"
    echo "ACTUATION_TRANSPORT_IMPLEMENTED=false"
    exit 1
fi
echo "P13_REAL_ADAPTER_DRY_INIT=PASS"
echo "ACTUATION_TRANSPORT_IMPLEMENTED=true"

STEP=AUDIT_SINK_PROOF
mkdir -p "$AUDIT_DIR"
chmod 700 "$AUDIT_DIR"
# Prove a real append + flush + fsync + close/reopen cycle through the
# AuditSink API, then verify the exact new entry and journal structure.
if ! python3 "$SCRIPT_DIR/p13_audit_durability_proof.py" --audit "$AUDIT_FILE" --head "$HEAD"; then
    echo "P13_AUDIT_DURABILITY_PROOF=FAIL"
    echo "AUDIT_SINK_VERIFIED=FAIL"
    exit 1
fi
echo "P13_AUDIT_DURABILITY_PROOF=PASS"
echo "AUDIT_SINK_VERIFIED=PASS"

STEP=NO_CONFLICT
# Match full command lines because Linux process comm names are limited to 15
# characters; pgrep -x on the old long names emitted warnings and could never
# match the actual P13 processes.
pgrep -f -- '(^|/)comelit_ice_offer_holder([[:space:]]|$)' >/dev/null && { echo "P13_CONFLICTING_PROCESS=true"; exit 1; } || true
pgrep -f -- '(^|/)comelit_p13_holder([[:space:]]|$)' >/dev/null && { echo "P13_CONFLICTING_PROCESS=true"; exit 1; } || true
pgrep -f -- '(^|/)comelit-p13-door-wrapper([[:space:]]|$)' >/dev/null && { echo "P13_CONFLICTING_PROCESS=true"; exit 1; } || true
echo "P13_CONFLICTING_PROCESS=false"

STEP=NO_RETRY_SURFACE
# Verify executable one-shot semantics, not the presence of the word "retry"
# in comments or conservative recovery messages.  This remains non-actuating:
# Python source is parsed as AST and the wrapper is inspected as text only.
if ! python3 - "$POC_ROOT/src/comelit_safety_poc/executor.py" "$POC_ROOT/src/comelit_safety_poc/ct120_real_session.py" <<'PY'
import ast
import sys
from pathlib import Path

executor_path = Path(sys.argv[1])
session_path = Path(sys.argv[2])
executor_tree = ast.parse(executor_path.read_text(encoding="utf-8"))
session_tree = ast.parse(session_path.read_text(encoding="utf-8"))


def method(tree: ast.AST, class_name: str, method_name: str) -> ast.FunctionDef:
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == method_name:
                    return item
    raise AssertionError(f"missing {class_name}.{method_name}")


def attr_calls(node: ast.AST, attr: str) -> int:
    return sum(
        1
        for item in ast.walk(node)
        if isinstance(item, ast.Call)
        and isinstance(item.func, ast.Attribute)
        and item.func.attr == attr
    )

execute = method(executor_tree, "OneShotExecutor", "execute")
open_ctpp = method(session_tree, "Ct120RealP13Session", "open_ctpp")

# The side-effect transport has one syntactic send point in execute().
assert attr_calls(execute, "send_once") == 1, "execute() must contain exactly one send_once call"
# No loop may surround/repeat the send path.
assert not any(isinstance(item, (ast.For, ast.AsyncFor, ast.While)) for item in ast.walk(execute)), \
    "execute() must not contain retry loops"
# The native wrapper has one syntactic invocation point in open_ctpp().
assert attr_calls(open_ctpp, "_run_wrapper_once") == 1, \
    "open_ctpp() must contain exactly one wrapper invocation"
assert not any(isinstance(item, (ast.For, ast.AsyncFor, ast.While)) for item in ast.walk(open_ctpp)), \
    "open_ctpp() must not contain retry loops"
# There must be no retry-named callable API on either class.
for tree, class_name in ((executor_tree, "OneShotExecutor"), (session_tree, "Ct120RealP13Session")):
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            retry_methods = [
                item.name for item in node.body
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and "retry" in item.name.lower()
            ]
            assert not retry_methods, f"retry methods present on {class_name}: {retry_methods}"

print("P13_PYTHON_ONE_SHOT_SOURCE=PASS")
PY
then
    echo "P13_ONE_SHOT_SOURCE_CONTRACT=FAIL"
    echo "P13_RETRY_SURFACE_DETECTED=true"
    exit 1
fi
WRAPPER_EXEC_COUNT="$(grep -Fc 'exec "$HOLDER_PATH"' "$WRAPPER" || true)"
[[ "$WRAPPER_EXEC_COUNT" == "1" ]] || {
    echo "P13_WRAPPER_SINGLE_EXEC=FAIL(count=$WRAPPER_EXEC_COUNT)"
    echo "P13_RETRY_SURFACE_DETECTED=true"
    exit 1
}
echo "P13_WRAPPER_SINGLE_EXEC=PASS"
echo "P13_ONE_SHOT_SOURCE_CONTRACT=PASS"
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
echo "READONLY_TRANSPORT_READY=true"
echo "P13_ONE_SHOT_MAX_INVOCATIONS=1"
echo "P13_AUTO_RETRY_ALLOWED=false"
echo "P13_TARGET_BINDING_REQUIRED=true"
echo "P13_PHYSICAL_EFFECT_ASSERTED=false"
echo "EXPLICIT_LIVE_TEST_APPROVAL=false"
echo "LIVE_TEST_READY=false"
echo "P13_ACTUATOR_COMMAND_ATTEMPTED=false"
echo "PHYSICAL_DOOR_ACTION=false"
echo "PHYSICAL_EFFECT_ASSERTED=false"
