#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git -C "$SCRIPT_DIR/.." rev-parse --show-toplevel)"
RUNNER="$SCRIPT_DIR/run_p12_readonly_live_once.sh"
RUN_ROOT=/root/comelit-p12-readonly-live-service
EXPECTED_BRANCH=feat/p12-readonly-transport-readiness
APPROVAL=I_APPROVE_P12_READONLY_LIVE_ONCE

[[ "${EUID}" -eq 0 ]] || { echo "P12_LIVE_SERVICE_REQUIRES_ROOT=true"; exit 1; }
[[ -x /usr/bin/systemd-run || -x /bin/systemd-run ]] || { echo "P12_LIVE_SYSTEMD_RUN_PRESENT=false"; exit 1; }
[[ -f "$RUNNER" ]] || { echo "P12_LIVE_RUNNER_PRESENT=false"; exit 1; }
[[ "$(git -C "$REPO_ROOT" branch --show-current)" == "$EXPECTED_BRANCH" ]] || {
    echo "P12_LIVE_SERVICE_BRANCH=FAIL"
    exit 1
}
[[ -z "$(git -C "$REPO_ROOT" status --porcelain)" ]] || {
    echo "P12_LIVE_SERVICE_WORKTREE_CLEAN=false"
    git -C "$REPO_ROOT" status --short
    exit 1
}

mkdir -p "$RUN_ROOT"
chmod 700 "$RUN_ROOT"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
UNIT="p12-readonly-live-${STAMP,,}.service"
LOG="$RUN_ROOT/${STAMP}.log"
RCFILE="$RUN_ROOT/${STAMP}.rc"
META="$RUN_ROOT/${STAMP}.meta"

: > "$LOG"
: > "$RCFILE"
chmod 600 "$LOG" "$RCFILE"

cat > "$META" <<EOF
P12_LIVE_SERVICE_UNIT=$UNIT
P12_LIVE_SERVICE_LOG=$LOG
P12_LIVE_SERVICE_RC_FILE=$RCFILE
P12_LIVE_SERVICE_REPOSITORY_HEAD=$(git -C "$REPO_ROOT" rev-parse HEAD)
P12_LIVE_SERVICE_REPOSITORY_TREE=$(git -C "$REPO_ROOT" rev-parse HEAD^{tree})
P12_LIVE_SERVICE_STARTED_AT_UTC=$STAMP
P12_LIVE_SERVICE_SCOPE=P2P_ICE_PSEUDOTCP_VIP_UAUT_UCFG_READONLY
P12_LIVE_SERVICE_AUTO_RETRY=false
P12_LIVE_SERVICE_DOOR_CTPP_ALLOWED=false
EOF
chmod 600 "$META"

/usr/bin/systemd-run \
    --unit="$UNIT" \
    --collect \
    --property=Type=oneshot \
    --property=TimeoutStartSec=120 \
    --property=KillMode=control-group \
    --property=StandardInput=null \
    --property=StandardOutput=null \
    --property=StandardError=null \
    /bin/bash -c '
        set +e
        runner="$1"
        log="$2"
        rcfile="$3"
        approval="$4"
        printf "P12_LIVE_SERVICE_PAYLOAD_START=true\n" >>"$log"
        P12_READONLY_LIVE_APPROVAL="$approval" /bin/bash "$runner" >>"$log" 2>&1
        rc=$?
        printf "P12_LIVE_SERVICE_RC=%s\n" "$rc" >"$rcfile"
        chmod 600 "$rcfile"
        printf "P12_LIVE_SERVICE_PAYLOAD_END=true\n" >>"$log"
        exit "$rc"
    ' _ "$RUNNER" "$LOG" "$RCFILE" "$APPROVAL" >/dev/null

echo "P12_LIVE_SERVICE_START=PASS"
echo "P12_LIVE_SERVICE_UNIT=$UNIT"
echo "P12_LIVE_SERVICE_LOG=$LOG"
echo "P12_LIVE_SERVICE_RC_FILE=$RCFILE"
echo "P12_LIVE_SERVICE_META=$META"
echo "P12_READONLY_LIVE_APPROVED=true"
echo "P12_LIVE_SERVICE_AUTO_RETRY=false"
echo "P12_LIVE_SERVICE_DOOR_CTPP_ALLOWED=false"
