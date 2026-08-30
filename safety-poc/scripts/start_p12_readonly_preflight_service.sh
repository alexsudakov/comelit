#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git -C "$SCRIPT_DIR/.." rev-parse --show-toplevel)"
PREFLIGHT="$SCRIPT_DIR/p12_readonly_live_preflight.sh"
RUN_ROOT=/root/comelit-p12-readonly-preflight
EXPECTED_BRANCH=feat/p12-readonly-transport-readiness

[[ "${EUID}" -eq 0 ]] || { echo "P12_PREFLIGHT_SERVICE_REQUIRES_ROOT=true"; exit 1; }
[[ -x /usr/bin/systemd-run || -x /bin/systemd-run ]] || { echo "P12_PREFLIGHT_SYSTEMD_RUN_PRESENT=false"; exit 1; }
[[ -f "$PREFLIGHT" ]] || { echo "P12_PREFLIGHT_SCRIPT_PRESENT=false"; exit 1; }
[[ "$(git -C "$REPO_ROOT" branch --show-current)" == "$EXPECTED_BRANCH" ]] || {
    echo "P12_PREFLIGHT_SERVICE_BRANCH=FAIL"
    exit 1
}
[[ -z "$(git -C "$REPO_ROOT" status --porcelain)" ]] || {
    echo "P12_PREFLIGHT_SERVICE_WORKTREE_CLEAN=false"
    git -C "$REPO_ROOT" status --short
    exit 1
}

mkdir -p "$RUN_ROOT"
chmod 700 "$RUN_ROOT"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
UNIT="p12-readonly-preflight-${STAMP,,}.service"
LOG="$RUN_ROOT/${STAMP}.log"
RCFILE="$RUN_ROOT/${STAMP}.rc"
META="$RUN_ROOT/${STAMP}.meta"

: > "$LOG"
: > "$RCFILE"
chmod 600 "$LOG" "$RCFILE"

cat > "$META" <<EOF
P12_PREFLIGHT_SERVICE_UNIT=$UNIT
P12_PREFLIGHT_SERVICE_LOG=$LOG
P12_PREFLIGHT_SERVICE_RC_FILE=$RCFILE
P12_PREFLIGHT_SERVICE_REPOSITORY_HEAD=$(git -C "$REPO_ROOT" rev-parse HEAD)
P12_PREFLIGHT_SERVICE_REPOSITORY_TREE=$(git -C "$REPO_ROOT" rev-parse HEAD^{tree})
P12_PREFLIGHT_SERVICE_STARTED_AT_UTC=$STAMP
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
        preflight="$1"
        log="$2"
        rcfile="$3"
        printf "P12_PREFLIGHT_SERVICE_PAYLOAD_START=true\n" >>"$log"
        /bin/bash "$preflight" >>"$log" 2>&1
        rc=$?
        printf "P12_PREFLIGHT_RC=%s\n" "$rc" >"$rcfile"
        chmod 600 "$rcfile"
        printf "P12_PREFLIGHT_SERVICE_PAYLOAD_END=true\n" >>"$log"
        exit "$rc"
    ' _ "$PREFLIGHT" "$LOG" "$RCFILE" >/dev/null

echo "P12_PREFLIGHT_SERVICE_START=PASS"
echo "P12_PREFLIGHT_SERVICE_UNIT=$UNIT"
echo "P12_PREFLIGHT_SERVICE_LOG=$LOG"
echo "P12_PREFLIGHT_SERVICE_RC_FILE=$RCFILE"
echo "P12_PREFLIGHT_SERVICE_META=$META"
echo "P12_PREFLIGHT_LIVE_RUN_PERFORMED=false"
echo "ACTIVE_COMELIT_NETWORK_PROBES=false"
echo "ACTUATOR_COMMAND_ATTEMPTED=false"
echo "PHYSICAL_DOOR_ACTION=false"
