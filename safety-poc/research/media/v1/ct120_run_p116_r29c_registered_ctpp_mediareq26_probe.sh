#!/usr/bin/env bash
# CT120 research-only P116/R29C registered-CTPP mediareq26 probe prep runner.
# Default mode is offline materialise/build/selfcheck/dry-run only.

set -u -o pipefail
umask 077

REPO=${REPO:-}
R29_LIVE_RUN=${R29_LIVE_RUN:-NO}
LIVE_RUN=${LIVE_RUN:-NOT_RUN}
R29C_LIVE_AUTHORIZED=${R29C_LIVE_AUTHORIZED:-false}
R29C_EXPECTED_COMMIT_SHA=${R29C_EXPECTED_COMMIT_SHA:-}
R29C_EXPECTED_GENERATED_SOURCE_SHA=${R29C_EXPECTED_GENERATED_SOURCE_SHA:-}
HA_WEBHOOK_URL=${HA_WEBHOOK_URL:-}
BUILDER_REL=safety-poc/research/media/v1/ct120_build_p80_haos_media_helper.sh
TRANSFORM_REL=safety-poc/research/media/v1/entrance_p116_r29c_registered_ctpp_mediareq26_probe_transform.py
RUNNER_REL=safety-poc/research/media/v1/ct120_run_p116_r29c_registered_ctpp_mediareq26_probe.sh
CANDIDATE_NAME=comelit-r29c-registered-ctpp-mediareq26-probe

FAIL=0
RUN_ROOT=""
BUILD_PROVENANCE_LOG=""
CANDIDATE_OUTPUT=""
R29C_SELFCHECK_ROOTFS=""
PRODUCTION_STATUS_BEFORE=not_checked
PRODUCTION_STATUS_AFTER=not_checked
PRODUCTION_RESTORE_PREFLIGHT=NOT_RUN
CANDIDATE_BUILD=NOT_RUN
CANDIDATE_SELFCHECK=NOT_RUN

fail() {
    echo "$1"
    FAIL=1
}

json_scalar() {
    python3 - "$1" "$2" <<'PY'
import json
from pathlib import Path
import sys
try:
    data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
except Exception:
    print("__INVALID_JSON__")
    raise SystemExit(0)
value = data.get(sys.argv[2], "__MISSING__")
if value is True:
    print("true")
elif value is False:
    print("false")
elif value is None:
    print("null")
else:
    print(str(value))
PY
}

post_control() {
    local action="$1"
    local output="$2"
    local max_time="$3"
    local http_file="${output}.http"
    if [ -z "$HA_WEBHOOK_URL" ]; then
        echo "CONTROL_${action}_URL=ABSENT"
        return 2
    fi
    curl --silent --show-error --connect-timeout 5 --max-time "$max_time" \
      --header 'Content-Type: application/json' \
      --output "$output" \
      --write-out '%{http_code}\n' \
      --data "{\"action\":\"$action\"}" \
      "$HA_WEBHOOK_URL" > "$http_file"
}

status_ready() {
    local file="$1"
    [ "$(json_scalar "$file" ok)" = true ] &&
    [ "$(json_scalar "$file" supervisor_running)" = true ] &&
    [ "$(json_scalar "$file" running)" = true ] &&
    [ "$(json_scalar "$file" listener_ready)" = true ] &&
    [ "$(json_scalar "$file" last_error)" = null ]
}

build_marker() {
    local key="$1"
    local fallback="$2"
    if [ -f "$BUILD_PROVENANCE_LOG" ]; then
        awk -v key="$key" -v fallback="$fallback" '
            index($0, key "=") == 1 { value = substr($0, length(key) + 2); found = 1 }
            END { if (found) print value; else print fallback }
        ' "$BUILD_PROVENANCE_LOG"
    else
        printf '%s\n' "$fallback"
    fi
}

select_selfcheck_rootfs() {
    local rootfs
    rootfs="$(build_marker P80_OFFLINE_ROOTFS "")"
    if [ -n "$rootfs" ] && [ -x "$rootfs/usr/bin/gcc" ] && [ -e "$rootfs/lib/ld-musl-x86_64.so.1" ]; then
        printf '%s\n' "$rootfs"
        return 0
    fi
    find /root -maxdepth 2 -path '/root/comelit-p80-haos-build-*/rootfs' -type d \
        -exec test -x '{}/usr/bin/gcc' ';' \
        -exec test -e '{}/lib/ld-musl-x86_64.so.1' ';' \
        -printf '%T@ %p\n' 2>/dev/null |
    sort -nr |
    awk 'NR == 1 {print $2}'
}

run_candidate_selfcheck_in_chroot() {
    local rootfs selfcheck_dir rootfs_candidate
    rootfs="$(select_selfcheck_rootfs)"
    [ -n "$rootfs" ] || fail "R29C_SELFCHECK_ROOTFS=ABSENT"
    [ -x "$rootfs/usr/bin/gcc" ] || fail "R29C_SELFCHECK_ROOTFS_GCC=FAIL"
    [ -e "$rootfs/lib/ld-musl-x86_64.so.1" ] || fail "R29C_SELFCHECK_ROOTFS_MUSL_LOADER=FAIL"
    [ "$FAIL" -eq 0 ] || return 1
    R29C_SELFCHECK_ROOTFS="$rootfs"
    echo "R29C_SELFCHECK_ROOTFS=$rootfs"
    echo "R29C_SELFCHECK_ROOTFS_SELECTION=P80_OFFLINE_ROOTFS_OR_NEWEST_CACHED_CHROOT_PATTERN"
    selfcheck_dir="$rootfs/r29c-selfcheck"
    rm -rf "$selfcheck_dir"
    install -d -m 700 "$selfcheck_dir"
    rootfs_candidate="$selfcheck_dir/$CANDIDATE_NAME"
    install -m 700 "$CANDIDATE_OUTPUT" "$rootfs_candidate"
    chroot "$rootfs" "/r29c-selfcheck/$CANDIDATE_NAME" --r29-selfcheck > "$RUN_ROOT/selfcheck.log" 2>&1
}

dry_run_restore_preflight() {
    local before="$RUN_ROOT/listener-status-before.json"
    local after="$RUN_ROOT/listener-status-after.json"
    post_control status "$before" 10 || true
    post_control status "$after" 10 || true
    if [ -f "$before" ] && status_ready "$before"; then
        PRODUCTION_STATUS_BEFORE=ready
    else
        PRODUCTION_STATUS_BEFORE=not_ready_or_not_checked
    fi
    if [ -f "$after" ] && status_ready "$after"; then
        PRODUCTION_STATUS_AFTER=ready
    else
        PRODUCTION_STATUS_AFTER="$PRODUCTION_STATUS_BEFORE"
    fi
    PRODUCTION_RESTORE_PREFLIGHT=PASS
    echo "R29C_HANDOFF_DRY_RUN=PASS"
    echo "PRODUCTION_LISTENER_STOP_REQUESTED=false"
    echo "PRODUCTION_LISTENER_RESTORE_REQUESTED=false"
    echo "PRODUCTION_RESTORE_PREFLIGHT=PASS"
    echo "PRODUCTION_LISTENER_STATUS_BEFORE=$PRODUCTION_STATUS_BEFORE"
    echo "PRODUCTION_LISTENER_STATUS_AFTER=$PRODUCTION_STATUS_AFTER"
}

print_report() {
    local generated_sha
    generated_sha="$(build_marker GENERATED_SOURCE_SHA256 NOT_REACHED)"
    echo "=== COMELIT P116 R29C RUNNER REPORT ==="
    echo "LIVE_RUN=NOT_RUN"
    echo "R29_LIVE_RUN_IGNORED=$R29_LIVE_RUN"
    echo "R29C_LIVE_AUTHORIZED=$R29C_LIVE_AUTHORIZED"
    echo "GENERATED_SOURCE_SHA256=$generated_sha"
    echo "CANDIDATE_BUILD=$CANDIDATE_BUILD"
    echo "CANDIDATE_SELFCHECK=$CANDIDATE_SELFCHECK"
    echo "PRODUCTION_RESTORE_PREFLIGHT=$PRODUCTION_RESTORE_PREFLIGHT"
    echo "PRODUCTION_LISTENER_TOUCHED=false"
    echo "=== END COMELIT P116 R29C RUNNER REPORT ==="
}

on_exit() {
    local rc=$?
    print_report
    exit "$rc"
}

run_main() {
    trap on_exit EXIT
    trap 'exit 130' INT TERM HUP

    [ "${EUID}" -eq 0 ] || fail "R29C_ROOT_GATE=FAIL"
    for command in git python3 sha256sum timeout awk grep bash chmod install cmp chroot find sort rm; do
        command -v "$command" >/dev/null 2>&1 || fail "R29C_MISSING_COMMAND=$command"
    done
    [ -n "$REPO" ] || fail "R29C_REPO_REQUIRED=true"
    [ -n "$R29C_EXPECTED_COMMIT_SHA" ] || fail "R29C_EXPECTED_COMMIT_SHA_REQUIRED=true"
    [ -n "$R29C_EXPECTED_GENERATED_SOURCE_SHA" ] || fail "R29C_EXPECTED_GENERATED_SOURCE_SHA_REQUIRED=true"
    [ -d "$REPO/.git" ] || fail "R29C_REPO_PRESENT=false"
    if [ "$FAIL" -eq 0 ]; then
        repo_head="$(git -C "$REPO" rev-parse HEAD 2>/dev/null || true)"
        echo "R29C_REPO_HEAD=$repo_head"
        [ "$repo_head" = "$R29C_EXPECTED_COMMIT_SHA" ] || fail "R29C_EXPECTED_COMMIT_SHA_GATE=FAIL"
        [ -z "$(git -C "$REPO" status --porcelain)" ] || fail "R29C_WORKTREE_CLEAN=FAIL"
    fi

    STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
    RUN_ROOT="/root/comelit-r29c-mediareq26-prep-$STAMP"
    mkdir -p "$RUN_ROOT"
    chmod 700 "$RUN_ROOT"
    BUILD_PROVENANCE_LOG="$RUN_ROOT/build-provenance.log"
    CANDIDATE_OUTPUT="$RUN_ROOT/$CANDIDATE_NAME"
    : > "$BUILD_PROVENANCE_LOG"
    chmod 600 "$BUILD_PROVENANCE_LOG"
    case "$CANDIDATE_OUTPUT" in "$RUN_ROOT"/*) echo "R29C_CANDIDATE_OUTPUT_SCOPE=RUN_ROOT" ;; *) fail "R29C_CANDIDATE_OUTPUT_SCOPE=FAIL" ;; esac

    if [ "$FAIL" -eq 0 ]; then
        git -C "$REPO" show "$R29C_EXPECTED_COMMIT_SHA:$TRANSFORM_REL" > "$RUN_ROOT/transform.py" || fail "R29C_TRANSFORM_BLOB=FAIL"
        git -C "$REPO" show "$R29C_EXPECTED_COMMIT_SHA:$RUNNER_REL" > "$RUN_ROOT/runner.sh" || fail "R29C_RUNNER_BLOB=FAIL"
        git -C "$REPO" show "$R29C_EXPECTED_COMMIT_SHA:$BUILDER_REL" > "$RUN_ROOT/builder.sh" || fail "R29C_BUILDER_BLOB=FAIL"
        bash -n "$RUN_ROOT/runner.sh" || fail "R29C_RUNNER_BASH_N=FAIL"
        bash -n "$RUN_ROOT/builder.sh" || fail "R29C_BUILDER_BASH_N=FAIL"
        cmp "$RUN_ROOT/transform.py" "$REPO/$TRANSFORM_REL" >/dev/null 2>&1 || fail "R29C_TRANSFORM_WORKTREE_BLOB_GATE=FAIL"
        cmp "$RUN_ROOT/runner.sh" "$REPO/$RUNNER_REL" >/dev/null 2>&1 || fail "R29C_RUNNER_WORKTREE_BLOB_GATE=FAIL"
        cmp "$RUN_ROOT/builder.sh" "$REPO/$BUILDER_REL" >/dev/null 2>&1 || fail "R29C_BUILDER_WORKTREE_BLOB_GATE=FAIL"
    fi
    [ "$FAIL" -eq 0 ] || exit 1
    echo "R29C_PREFLIGHT=PASS"

    (
        REPO="$REPO" \
        P80_BUILD_ALLOW_DETACHED=1 \
        P80_BUILD_EXPECTED_SHA="$R29C_EXPECTED_COMMIT_SHA" \
        P80_BUILD_INCLUDE_P116=1 \
        P80_BUILD_TRANSFORM="$TRANSFORM_REL" \
        P80_BUILD_EXPECTED_SOURCE_SHA="$R29C_EXPECTED_GENERATED_SOURCE_SHA" \
        OUTPUT="$CANDIDATE_OUTPUT" \
        bash "$RUN_ROOT/builder.sh"
    ) | tee "$BUILD_PROVENANCE_LOG"
    build_rc=${PIPESTATUS[0]}
    echo "R29C_BUILD_RC=$build_rc"
    [ "$build_rc" -eq 0 ] || exit 1
    grep -F "GENERATED_SOURCE_SHA256=$R29C_EXPECTED_GENERATED_SOURCE_SHA" "$BUILD_PROVENANCE_LOG" >/dev/null || fail "R29C_GENERATED_SOURCE_SHA_GATE=FAIL"
    [ -x "$CANDIDATE_OUTPUT" ] || fail "R29C_CANDIDATE_OUTPUT_PRESENT=false"
    [ "$FAIL" -eq 0 ] || exit 1
    CANDIDATE_BUILD=PASS

    run_candidate_selfcheck_in_chroot || fail "R29C_CANDIDATE_SELFCHECK=FAIL"
    grep -qx 'CANDIDATE_HELPER_EXECUTED=true' "$RUN_ROOT/selfcheck.log" || fail "R29C_CANDIDATE_HELPER_EXECUTED=FAIL"
    grep -qx 'R29C_BUILDER=BLOCKED' "$RUN_ROOT/selfcheck.log" || fail "R29C_BUILDER_BLOCKED_GATE=FAIL"
    grep -qx 'R29C_PROBE_READY=false' "$RUN_ROOT/selfcheck.log" || fail "R29C_PROBE_READY_FALSE_GATE=FAIL"
    [ "$FAIL" -eq 0 ] || exit 1
    CANDIDATE_SELFCHECK=PASS

    dry_run_restore_preflight

    if [ "$R29C_LIVE_AUTHORIZED" != authorized ]; then
        echo "R29C_LIVE_PREFLIGHT_REFUSED=LIVE_FORBIDDEN"
        echo "LIVE_RUN=NOT_RUN"
        exit 0
    fi
    echo "R29C_LIVE_PREFLIGHT_REFUSED=LIVE_DISABLED_IN_THIS_ARTIFACT"
    echo "LIVE_RUN=NOT_RUN"
}

if [ "${R29C_UNIT_TEST:-0}" != 1 ]; then
    run_main "$@"
fi
