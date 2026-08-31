#!/usr/bin/env bash
# Non-actuating readiness wrapper for the single-use Hermes observed P13 gate.
# It never calls the live entrypoint or physical runner. It only validates exact
# source identities, proves the acceptance gate is still unused, and executes
# the existing P13 non-actuating preflight with live approval identity removed.
set -Eeuo pipefail
umask 077

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
POC_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(git -C "$POC_ROOT" rev-parse --show-toplevel)"
GATE="$SCRIPT_DIR/p13_hermes_observed_acceptance.sh"
INNER="$SCRIPT_DIR/p13_hermes_one_shot.sh"
RUNNER="$SCRIPT_DIR/p13_one_shot_physical_runner.sh"
PREFLIGHT="$SCRIPT_DIR/p13_actuation_preflight.sh"
RUN_DIR=/root/comelit-p13-run
STATE_FILE="$RUN_DIR/hermes-observed-acceptance-v1.state"
EXPECTED_BRANCH=feat/p13-one-shot-actuation
EXPECTED_GATE_BLOB=f1e40090b6dc458e90a7e662eee2d20d880f2d4d
EXPECTED_INNER_BLOB=d0a640bd2cb06bf108e7edfb26b8e35a7cbfc3fe
EXPECTED_RUNNER_BLOB=d9c13d28aba66b44b27402c026ddebb89419cba4

echo 'P13_HERMES_OBSERVED_PREFLIGHT_START=true'
echo 'P13_HERMES_OBSERVED_PREFLIGHT_NETWORK_ACTION=false'
echo 'P13_HERMES_OBSERVED_PREFLIGHT_PHYSICAL_ACTION=false'

[[ "${EUID}" -eq 0 ]] || { echo 'P13_HERMES_OBSERVED_PREFLIGHT_REQUIRES_ROOT=true'; exit 1; }
[[ "$(git -C "$REPO_ROOT" branch --show-current)" == "$EXPECTED_BRANCH" ]] || {
    echo 'P13_HERMES_OBSERVED_PREFLIGHT_BRANCH=FAIL'
    exit 1
}
[[ -z "$(git -C "$REPO_ROOT" status --porcelain)" ]] || {
    echo 'P13_HERMES_OBSERVED_PREFLIGHT_WORKTREE_CLEAN=false'
    exit 1
}

echo "P13_HERMES_OBSERVED_PREFLIGHT_HEAD=$(git -C "$REPO_ROOT" rev-parse HEAD)"
echo "P13_HERMES_OBSERVED_PREFLIGHT_TREE=$(git -C "$REPO_ROOT" rev-parse 'HEAD^{tree}')"

for path in "$GATE" "$INNER" "$RUNNER" "$PREFLIGHT"; do
    [[ -f "$path" ]] || { echo 'P13_HERMES_OBSERVED_PREFLIGHT_SOURCE_PRESENT=false'; exit 1; }
done

[[ "$(git -C "$REPO_ROOT" hash-object "$GATE")" == "$EXPECTED_GATE_BLOB" ]] || {
    echo 'P13_HERMES_OBSERVED_GATE_IDENTITY=FAIL'
    exit 1
}
[[ "$(git -C "$REPO_ROOT" hash-object "$INNER")" == "$EXPECTED_INNER_BLOB" ]] || {
    echo 'P13_HERMES_OBSERVED_INNER_IDENTITY=FAIL'
    exit 1
}
[[ "$(git -C "$REPO_ROOT" hash-object "$RUNNER")" == "$EXPECTED_RUNNER_BLOB" ]] || {
    echo 'P13_HERMES_OBSERVED_RUNNER_IDENTITY=FAIL'
    exit 1
}

echo 'P13_HERMES_OBSERVED_GATE_IDENTITY=PASS'
echo 'P13_HERMES_OBSERVED_INNER_IDENTITY=PASS'
echo 'P13_HERMES_OBSERVED_RUNNER_IDENTITY=PASS'

install -d -m 700 -o root -g root "$RUN_DIR"
if [[ -e "$STATE_FILE" ]]; then
    echo 'P13_HERMES_OBSERVED_GATE_UNUSED=false'
    echo 'P13_HERMES_OBSERVED_ACCEPTANCE_READY=false'
    exit 76
fi
echo 'P13_HERMES_OBSERVED_GATE_UNUSED=true'

TMP="$(mktemp "$RUN_DIR/hermes-observed-preflight.XXXXXX")"
cleanup() { rm -f "$TMP"; }
trap cleanup EXIT
chmod 600 "$TMP"
chown root:root "$TMP"

set +e
env -u P13_APPROVAL -u P13_OPERATION_ID bash "$PREFLIGHT" >"$TMP" 2>&1
rc=$?
set -e

# Emit only the bounded safe marker allowlist; the raw preflight output stays
# local and is deleted at exit.
grep -E '^(P13_PREFLIGHT_HEAD=|P13_PREFLIGHT_TREE=|P13_HOLDER_PRESENT=|P13_REAL_WRAPPER_PRESENT=|P13_PAYLOAD_PRESENT=|P13_PAYLOAD_BUNDLE_VALID=|P13_CONFLICTING_PROCESS=|P13_STATIC_SAFETY=|P13_RUNTIME_RELEVANT_UNIT_SUITE=|P13_FULL_REPOSITORY_UNIT_SUITE_SOURCE=|P13_CONTRACT_VALIDATION=|P13_NON_ACTUATING_PREFLIGHT=|READONLY_TRANSPORT_READY=|P13_ONE_SHOT_MAX_INVOCATIONS=|P13_AUTO_RETRY_ALLOWED=|P13_TARGET_BINDING_REQUIRED=|P13_PHYSICAL_EFFECT_ASSERTED=|EXPLICIT_LIVE_TEST_APPROVAL=|LIVE_TEST_READY=|P13_ACTUATOR_COMMAND_ATTEMPTED=|PHYSICAL_DOOR_ACTION=|PHYSICAL_EFFECT_ASSERTED=|SEND_ARMED_REACHED=)' "$TMP" || true

echo "P13_HERMES_OBSERVED_INNER_PREFLIGHT_RC=$rc"
if [[ "$rc" -ne 0 ]]; then
    echo 'P13_HERMES_OBSERVED_ACCEPTANCE_READY=false'
    exit "$rc"
fi

grep -qx 'P13_NON_ACTUATING_PREFLIGHT=PASS' "$TMP" || { echo 'P13_HERMES_OBSERVED_ACCEPTANCE_READY=false'; exit 1; }
grep -qx 'READONLY_TRANSPORT_READY=true' "$TMP" || { echo 'P13_HERMES_OBSERVED_ACCEPTANCE_READY=false'; exit 1; }
grep -qx 'P13_ONE_SHOT_MAX_INVOCATIONS=1' "$TMP" || { echo 'P13_HERMES_OBSERVED_ACCEPTANCE_READY=false'; exit 1; }
grep -qx 'P13_AUTO_RETRY_ALLOWED=false' "$TMP" || { echo 'P13_HERMES_OBSERVED_ACCEPTANCE_READY=false'; exit 1; }
grep -qx 'EXPLICIT_LIVE_TEST_APPROVAL=false' "$TMP" || { echo 'P13_HERMES_OBSERVED_ACCEPTANCE_READY=false'; exit 1; }
grep -qx 'LIVE_TEST_READY=false' "$TMP" || { echo 'P13_HERMES_OBSERVED_ACCEPTANCE_READY=false'; exit 1; }
grep -qx 'P13_ACTUATOR_COMMAND_ATTEMPTED=false' "$TMP" || { echo 'P13_HERMES_OBSERVED_ACCEPTANCE_READY=false'; exit 1; }
grep -qx 'PHYSICAL_DOOR_ACTION=false' "$TMP" || { echo 'P13_HERMES_OBSERVED_ACCEPTANCE_READY=false'; exit 1; }
grep -qx 'PHYSICAL_EFFECT_ASSERTED=false' "$TMP" || { echo 'P13_HERMES_OBSERVED_ACCEPTANCE_READY=false'; exit 1; }

echo 'P13_HERMES_OBSERVED_ACCEPTANCE_READY=true'
echo 'EXPLICIT_LIVE_TEST_APPROVAL=false'
echo 'LIVE_TEST_READY=false'
echo 'SEND_ARMED_REACHED=false'
echo 'PHYSICAL_DOOR_ACTION=false'
echo 'PHYSICAL_EFFECT_ASSERTED=false'
echo 'P13_HERMES_OBSERVED_PREFLIGHT_COMPLETE=true'
