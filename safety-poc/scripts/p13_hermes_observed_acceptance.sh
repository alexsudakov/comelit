#!/usr/bin/env bash
# Single-use Hermes acceptance gate for one physically observed P13 Door test.
#
# This is intentionally narrower than the reusable P13 one-shot entrypoint.
# It exists only to make a second, observed acceptance attempt safe when the
# first physical attempt reached UNKNOWN_OUTCOME without a human observation.
#
# Safety properties:
# - exact action phrase only;
# - root only;
# - current P13 feature branch + clean worktree required;
# - global single-use gate is durably CONSUMED *before* the inner live entrypoint;
# - one invocation of p13_hermes_one_shot.sh maximum for this gate generation;
# - no retry loop;
# - if anything fails after gate consumption, the gate remains consumed;
# - a new physical attempt then requires forensic review + a new gate generation.
#
# This script does NOT itself constitute operator approval. The external
# operator approval boundary remains P13_POC_DIRECT_PATH.md §4.
set -Eeuo pipefail
umask 077

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
POC_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(git -C "$POC_ROOT" rev-parse --show-toplevel)"
INNER="$SCRIPT_DIR/p13_hermes_one_shot.sh"
RUN_DIR=/root/comelit-p13-run
LOCK_FILE="$RUN_DIR/hermes-observed-acceptance-v1.lock"
STATE_FILE="$RUN_DIR/hermes-observed-acceptance-v1.state"
LOG_FILE="$RUN_DIR/hermes-observed-acceptance-v1.log"
EXPECTED_BRANCH=feat/p13-one-shot-actuation
EXPECTED_INNER_BLOB=d0a640bd2cb06bf108e7edfb26b8e35a7cbfc3fe
ACTION_PHRASE=OPEN_72K4_3_ONCE

[[ "${EUID}" -eq 0 ]] || { echo 'P13_HERMES_OBSERVED_REQUIRES_ROOT=true'; exit 1; }
[[ "${1:-}" == "$ACTION_PHRASE" && $# -eq 1 ]] || {
    echo 'P13_HERMES_OBSERVED_ACTION=REJECTED'
    echo "P13_HERMES_OBSERVED_EXPECTED_ACTION=$ACTION_PHRASE"
    exit 64
}
[[ "$(git -C "$REPO_ROOT" branch --show-current)" == "$EXPECTED_BRANCH" ]] || {
    echo 'P13_HERMES_OBSERVED_BRANCH=FAIL'
    exit 1
}
[[ -z "$(git -C "$REPO_ROOT" status --porcelain)" ]] || {
    echo 'P13_HERMES_OBSERVED_WORKTREE_CLEAN=false'
    exit 1
}
[[ -f "$INNER" ]] || { echo 'P13_HERMES_OBSERVED_INNER_PRESENT=false'; exit 1; }
[[ "$(git -C "$REPO_ROOT" hash-object "$INNER")" == "$EXPECTED_INNER_BLOB" ]] || {
    echo 'P13_HERMES_OBSERVED_INNER_IDENTITY=FAIL'
    exit 1
}

install -d -m 700 -o root -g root "$RUN_DIR"
touch "$LOCK_FILE"
chmod 600 "$LOCK_FILE"
chown root:root "$LOCK_FILE"

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
    echo 'P13_HERMES_OBSERVED_CONCURRENT_INVOCATION=true'
    exit 75
fi

if [[ -e "$STATE_FILE" ]]; then
    echo 'P13_HERMES_OBSERVED_GATE_CONSUMED=true'
    echo 'P13_HERMES_OBSERVED_RESEND_ALLOWED=false'
    exit 76
fi

# Irreversibly consume this acceptance gate before entering any live-capable
# child. O_EXCL-equivalent noclobber prevents two processes from creating the
# gate state even if the outer flock contract is accidentally changed later.
set -o noclobber
printf '%s\n' 'CONSUMED_BEFORE_LIVE_ENTRYPOINT' >"$STATE_FILE"
set +o noclobber
chmod 600 "$STATE_FILE"
chown root:root "$STATE_FILE"
python3 - "$STATE_FILE" <<'PY'
import os
import sys

path = sys.argv[1]
fd = os.open(path, os.O_RDONLY)
try:
    os.fsync(fd)
finally:
    os.close(fd)
parent = os.open(os.path.dirname(path), os.O_RDONLY | os.O_DIRECTORY)
try:
    os.fsync(parent)
finally:
    os.close(parent)
PY

echo 'P13_HERMES_OBSERVED_GATE=CONSUMED'
echo 'P13_HERMES_OBSERVED_WARNING=PHYSICAL_DOOR_MAY_OPEN'
echo 'P13_HERMES_OBSERVED_MAX_LIVE_ENTRYPOINT_INVOCATIONS=1'
echo 'P13_HERMES_OBSERVED_AUTO_RETRY_ALLOWED=false'
echo 'P13_HERMES_OBSERVED_RESEND_ALLOWED=false'

# Exactly one live-capable inner invocation. tee preserves a root-only log for
# forensic review while retaining the child exit status through pipefail.
: >"$LOG_FILE"
chmod 600 "$LOG_FILE"
chown root:root "$LOG_FILE"

set +e
bash "$INNER" "$ACTION_PHRASE" 2>&1 | tee "$LOG_FILE"
rc=${PIPESTATUS[0]}
set -e

OPERATION_ID="$(sed -n 's/^P13_HERMES_OPERATION_ID=//p' "$LOG_FILE" | head -n 1)"
if [[ -n "$OPERATION_ID" ]]; then
    echo "P13_HERMES_OBSERVED_OPERATION_ID=$OPERATION_ID"
fi

echo "P13_HERMES_OBSERVED_INNER_RC=$rc"
echo 'P13_HERMES_OBSERVED_GATE_TERMINAL=CONSUMED'
echo 'P13_HERMES_OBSERVED_RESEND_ALLOWED=false'
exit "$rc"
