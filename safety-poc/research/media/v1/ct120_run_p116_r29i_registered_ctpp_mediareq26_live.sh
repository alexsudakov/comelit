#!/usr/bin/env bash
# Research-only launcher for the P116/R29I registered-CTPP live runner.
# It never authorizes LIVE by itself. The generated runner keeps the existing
# LIVE_RUN/R29C_LIVE_AUTHORIZED gates.
set -euo pipefail
umask 077

REPO=${REPO:-}
R29I_EXPECTED_COMMIT_SHA=${R29I_EXPECTED_COMMIT_SHA:-}

BASE_RUNNER_REL=safety-poc/research/media/v1/ct120_run_p116_r29c_registered_ctpp_mediareq26_live.sh
RUNNER_TRANSFORM_REL=safety-poc/research/media/v1/entrance_p116_r29i_live_runner_transform.py
LAUNCHER_REL=safety-poc/research/media/v1/ct120_run_p116_r29i_registered_ctpp_mediareq26_live.sh

fail() {
    echo "$1" >&2
    exit 1
}

[ "${EUID}" -eq 0 ] || fail "R29I_ROOT_GATE=FAIL"
[ -n "$REPO" ] || fail "R29I_REPO_REQUIRED=true"
[ -n "$R29I_EXPECTED_COMMIT_SHA" ] || fail "R29I_EXPECTED_COMMIT_SHA_REQUIRED=true"
[ -d "$REPO/.git" ] || fail "R29I_REPO_PRESENT=false"

repo_head="$(git -C "$REPO" rev-parse HEAD)"
[ "$repo_head" = "$R29I_EXPECTED_COMMIT_SHA" ] || fail "R29I_EXPECTED_COMMIT_SHA_GATE=FAIL"
[ -z "$(git -C "$REPO" status --porcelain)" ] || fail "R29I_WORKTREE_CLEAN=FAIL"

run_root="$(mktemp -d /tmp/comelit-r29i-runner.XXXXXX)"
trap 'rm -rf "$run_root"' EXIT
chmod 700 "$run_root"

pin_file() {
    local rel="$1"
    local out="$2"
    git -C "$REPO" show "$R29I_EXPECTED_COMMIT_SHA:$rel" > "$out" || fail "R29I_PIN_BLOB=FAIL:$rel"
    cmp -s "$out" "$REPO/$rel" || fail "R29I_WORKTREE_BLOB_GATE=FAIL:$rel"
}

pin_file "$BASE_RUNNER_REL" "$run_root/base-runner.sh"
pin_file "$RUNNER_TRANSFORM_REL" "$run_root/runner-transform.py"
pin_file "$LAUNCHER_REL" "$run_root/launcher.sh"

python3 -m py_compile "$run_root/runner-transform.py" || fail "R29I_RUNNER_TRANSFORM_COMPILE=FAIL"
python3 "$run_root/runner-transform.py" \
  --source "$run_root/base-runner.sh" \
  --output "$run_root/r29i-runner.sh"
bash -n "$run_root/r29i-runner.sh" || fail "R29I_GENERATED_RUNNER_BASH_N=FAIL"

runner_sha256="$(sha256sum "$run_root/r29i-runner.sh" | awk '{print $1}')"
echo "R29I_EXPECTED_COMMIT_SHA=$R29I_EXPECTED_COMMIT_SHA"
echo "R29I_GENERATED_RUNNER_SHA256=$runner_sha256"
echo "R29I_LAUNCHER_PREFLIGHT=PASS"

exec bash "$run_root/r29i-runner.sh" "$@"
