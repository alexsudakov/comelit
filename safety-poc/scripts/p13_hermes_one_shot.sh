#!/usr/bin/env bash
# Hermes/Telegram entrypoint for one deliberate P13 physical Door attempt.
#
# The Telegram/OPS request is the operator action. This script does not ask for
# a second approval token; it translates the exact action trigger into the
# internal P13 approval environment required by the physical runner.
#
# Safety invariants:
# - exact action phrase required;
# - one process-wide nonblocking lock;
# - fresh operation_id generated for every accepted invocation;
# - exactly one physical-runner exec;
# - no retry loop;
# - the physical runner still performs the full non-actuating preflight before
#   SEND_ARMED and retains terminal UNKNOWN_OUTCOME semantics on ambiguity.
set -Eeuo pipefail
umask 077

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
POC_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(git -C "$POC_ROOT" rev-parse --show-toplevel)"
RUNNER="$SCRIPT_DIR/p13_one_shot_physical_runner.sh"
RUN_DIR=/root/comelit-p13-run
DB="$RUN_DIR/p13-one-shot.sqlite3"
LOCK_FILE="$RUN_DIR/hermes-one-shot.lock"
EXPECTED_BRANCH=feat/p13-one-shot-actuation
ACTION_PHRASE=OPEN_72K4_3_ONCE
TARGET_FINGERPRINT=832e5c09cf5f8ef79b9af83ba34b38a0a29847570ea37158310369850e2500ce
INTERNAL_APPROVAL=I_APPROVE_P13_ONE_SHOT_PHYSICAL_DOOR_TEST

[[ "${EUID}" -eq 0 ]] || { echo 'P13_HERMES_REQUIRES_ROOT=true'; exit 1; }
[[ "${1:-}" == "$ACTION_PHRASE" && $# -eq 1 ]] || {
    echo "P13_HERMES_ACTION=REJECTED"
    echo "P13_HERMES_EXPECTED_ACTION=$ACTION_PHRASE"
    exit 64
}
[[ "$(git -C "$REPO_ROOT" branch --show-current)" == "$EXPECTED_BRANCH" ]] || {
    echo 'P13_HERMES_BRANCH=FAIL'
    exit 1
}
[[ -z "$(git -C "$REPO_ROOT" status --porcelain)" ]] || {
    echo 'P13_HERMES_WORKTREE_CLEAN=false'
    exit 1
}
[[ -x "$RUNNER" || -f "$RUNNER" ]] || { echo 'P13_HERMES_RUNNER_PRESENT=false'; exit 1; }

install -d -m 700 -o root -g root "$RUN_DIR"
touch "$LOCK_FILE"
chmod 600 "$LOCK_FILE"
chown root:root "$LOCK_FILE"

# The descriptor remains held across exec, preventing a concurrent Telegram or
# console invocation from entering the same one-shot path.
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
    echo 'P13_HERMES_CONCURRENT_INVOCATION=true'
    exit 75
fi

OPERATION_ID="$(python3 - <<'PY'
import uuid
print('p13-hermes-' + str(uuid.uuid4()))
PY
)"

echo 'P13_HERMES_TRIGGER=ACCEPTED'
echo 'P13_HERMES_WARNING=PHYSICAL_DOOR_MAY_OPEN'
echo "P13_HERMES_OPERATION_ID=$OPERATION_ID"
echo 'P13_HERMES_ONE_SHOT_MAX_INVOCATIONS=1'
echo 'P13_HERMES_AUTO_RETRY_ALLOWED=false'

# Exactly one handoff. exec prevents a second shell-level invocation surface.
exec env P13_APPROVAL="$INTERNAL_APPROVAL" \
    bash "$RUNNER" \
    --db "$DB" \
    --operation-id "$OPERATION_ID" \
    --target-fingerprint "$TARGET_FINGERPRINT" \
    --min-interval-seconds 10
