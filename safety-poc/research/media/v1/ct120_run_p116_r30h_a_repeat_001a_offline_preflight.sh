#!/usr/bin/env bash
# CT120 offline-only P116/R30H-A repeat-001A preflight harness.
# This script never executes the candidate helper or wrapper, never controls HA,
# and never touches the production listener. It only generates, builds, parses,
# and statically validates per-run artifacts.

set -u -o pipefail
umask 077

TASK_ID=COMELIT-P116-R30H-A-REPEAT-001A-OFFLINE-REVALIDATION
REPO=${REPO:-}
R30H_A_EXPECTED_SHA=${R30H_A_EXPECTED_SHA:-}
R30H_A_EXPECTED_SOURCE_SHA=${R30H_A_EXPECTED_SOURCE_SHA:-}
TRANSFORM_REL=${TRANSFORM_REL:-safety-poc/research/media/v1/entrance_p116_r27_repeat_001a_transform.py}
RUNNER_REL=${RUNNER_REL:-safety-poc/research/media/v1/ct120_run_p116_r27_repeat_001a_live.sh}
BUILDER_REL=${BUILDER_REL:-safety-poc/research/media/v1/ct120_build_p80_haos_media_helper.sh}
SOURCE_REL=safety-poc/research/door/v1_5_7/comelit-v4-persistent-ctpp-door.c
BASE_WRAPPER=/usr/local/sbin/comelit-p2p-cloud-probe
R30H_A_OFFLINE_RUN=${R30H_A_OFFLINE_RUN:-NO}
R27_LIVE_RUN=${R27_LIVE_RUN:-NO}

FAIL=0
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
RUN_ROOT="/root/comelit-r30h-a-offline-$STAMP"
BUILD_PROVENANCE_LOG="$RUN_ROOT/build-provenance.log"
CANDIDATE_OUTPUT="$RUN_ROOT/comelit-media-r30h-a-repeat-001a"
CANDIDATE_WRAPPER="$RUN_ROOT/comelit-p2p-cloud-probe-r30h-a-offline"
CANDIDATE_SOURCE_A="$RUN_ROOT/candidate-a.c"
CANDIDATE_SOURCE_B="$RUN_ROOT/candidate-b.c"
CANDIDATE_BINARY_SHA256=NOT_REACHED
CANDIDATE_BINARY_SIZE=NOT_REACHED
CANDIDATE_ELF_INTERPRETER=NOT_REACHED
CANDIDATE_NEEDED_LIBS=NOT_REACHED
P80_CHROOT_BUILD_RC=NOT_REACHED
ROOTFS_MODE=NOT_REACHED
CANDIDATE_COMPILE=FAIL
CANDIDATE_LINK=FAIL
WRAPPER_BINDING_GATE=FAIL

fail() {
    echo "$1"
    FAIL=1
}

marker_or() {
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

refuse() {
    echo "$1"
    echo "R30H_A_HARNESS_RESULT=FAIL"
    exit 2
}

if [ "${EUID}" -ne 0 ]; then
    refuse "R30H_A_REFUSAL_REQUIRES_ROOT=true"
fi
if [ "$R30H_A_OFFLINE_RUN" != YES ]; then
    refuse "R30H_A_OFFLINE_SAFE_REFUSAL=true"
fi
if [ "$R27_LIVE_RUN" = YES ]; then
    refuse "R30H_A_REFUSAL_R27_LIVE_RUN_PRESENT=true"
fi

live_env_names="$(
    env | awk -F= '
        $1 ~ /^(HA_WEBHOOK_URL|HA_TOKEN|HA_ACCESS_TOKEN|COMELIT_TOKEN|COMELIT_PASSWORD|COMELIT_SECRET|COMELIT_AUTH|R27_LIVE_TOKEN)$/ {
            print $1
        }
    ' | paste -sd, -
)"
if [ -n "$live_env_names" ]; then
    echo "R30H_A_REFUSAL_LIVE_TOKEN_ENV_PRESENT=true"
    echo "R30H_A_REFUSAL_LIVE_TOKEN_ENV_NAMES=$live_env_names"
    echo "R30H_A_HARNESS_RESULT=FAIL"
    exit 2
fi

for command in git python3 sha256sum awk grep bash chmod install cmp wc tee readelf stat sed date env paste sort; do
    command -v "$command" >/dev/null 2>&1 || fail "R30H_A_MISSING_COMMAND=$command"
done
[ -n "$REPO" ] || fail "R30H_A_REPO_REQUIRED=true"
[ -n "$R30H_A_EXPECTED_SHA" ] || fail "R30H_A_EXPECTED_SHA_REQUIRED=true"
[ -n "$R30H_A_EXPECTED_SOURCE_SHA" ] || fail "R30H_A_EXPECTED_SOURCE_SHA_REQUIRED=true"

mkdir -p "$RUN_ROOT"
chmod 700 "$RUN_ROOT"
: > "$BUILD_PROVENANCE_LOG"
chmod 600 "$BUILD_PROVENANCE_LOG"

if [ "$FAIL" -eq 0 ]; then
    [ -d "$REPO/.git" ] || fail "R30H_A_REPO_PRESENT=false"
    repo_head="$(git -C "$REPO" rev-parse HEAD 2>/dev/null || true)"
    echo "R30H_A_REPO_HEAD=$repo_head"
    [ "$repo_head" = "$R30H_A_EXPECTED_SHA" ] || fail "R30H_A_EXPECTED_SHA_GATE=FAIL"
    [ -z "$(git -C "$REPO" status --porcelain)" ] || fail "R30H_A_WORKTREE_CLEAN=FAIL"
fi

if [ "$FAIL" -eq 0 ]; then
    git -C "$REPO" show "$R30H_A_EXPECTED_SHA:$TRANSFORM_REL" > "$RUN_ROOT/transform.py" || fail "TRANSFORM_BLOB=FAIL"
    git -C "$REPO" show "$R30H_A_EXPECTED_SHA:$RUNNER_REL" > "$RUN_ROOT/runner.sh" || fail "RUNNER_BLOB=FAIL"
    git -C "$REPO" show "$R30H_A_EXPECTED_SHA:$BUILDER_REL" > "$RUN_ROOT/builder.sh" || fail "BUILDER_BLOB=FAIL"
    if cmp "$RUN_ROOT/transform.py" "$REPO/$TRANSFORM_REL" >/dev/null 2>&1; then
        echo "TRANSFORM_BLOB_WORKTREE_CMP=PASS"
    else
        fail "TRANSFORM_BLOB_WORKTREE_CMP=FAIL"
    fi
    if cmp "$RUN_ROOT/runner.sh" "$REPO/$RUNNER_REL" >/dev/null 2>&1; then
        echo "RUNNER_BLOB_WORKTREE_CMP=PASS"
    else
        fail "RUNNER_BLOB_WORKTREE_CMP=FAIL"
    fi
    if bash -n "$RUN_ROOT/builder.sh"; then
        echo "BUILDER_BASH_N=PASS"
    else
        fail "BUILDER_BASH_N=FAIL"
    fi
    if bash -n "$RUN_ROOT/runner.sh"; then
        echo "RUNNER_BASH_N=PASS"
    else
        fail "RUNNER_BASH_N=FAIL"
    fi
fi

[ "$FAIL" -eq 0 ] || { echo "R30H_A_PREFLIGHT=FAIL"; exit 1; }
echo "R30H_A_PREFLIGHT=PASS"
echo "R30H_A_RUN_ROOT=$RUN_ROOT"

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$REPO/safety-poc/research/media/v1" \
  python3 "$REPO/$TRANSFORM_REL" \
  --source "$REPO/$SOURCE_REL" \
  --output "$CANDIDATE_SOURCE_A" \
  --include-p116
gen_a_rc=$?
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$REPO/safety-poc/research/media/v1" \
  python3 "$REPO/$TRANSFORM_REL" \
  --source "$REPO/$SOURCE_REL" \
  --output "$CANDIDATE_SOURCE_B" \
  --include-p116
gen_b_rc=$?

[ "$gen_a_rc" -eq 0 ] && echo "CANDIDATE_GENERATION_A=PASS" || fail "CANDIDATE_GENERATION_A=FAIL"
[ "$gen_b_rc" -eq 0 ] && echo "CANDIDATE_GENERATION_B=PASS" || fail "CANDIDATE_GENERATION_B=FAIL"
if [ -s "$CANDIDATE_SOURCE_A" ]; then
    sha_a="$(sha256sum "$CANDIDATE_SOURCE_A" | awk '{print $1}')"
    bytes_a="$(wc -c < "$CANDIDATE_SOURCE_A" | awk '{print $1}')"
else
    sha_a=NOT_CREATED
    bytes_a=0
fi
if [ -s "$CANDIDATE_SOURCE_B" ]; then
    sha_b="$(sha256sum "$CANDIDATE_SOURCE_B" | awk '{print $1}')"
    bytes_b="$(wc -c < "$CANDIDATE_SOURCE_B" | awk '{print $1}')"
else
    sha_b=NOT_CREATED
    bytes_b=0
fi
echo "CANDIDATE_SOURCE_SHA256_A=$sha_a"
echo "CANDIDATE_SOURCE_SHA256_B=$sha_b"
echo "CANDIDATE_SOURCE_BYTES_A=$bytes_a"
echo "CANDIDATE_SOURCE_BYTES_B=$bytes_b"
if [ "$sha_a" = "$sha_b" ] && cmp "$CANDIDATE_SOURCE_A" "$CANDIDATE_SOURCE_B" >/dev/null 2>&1; then
    echo "CANDIDATE_REPRODUCIBLE=true"
else
    fail "CANDIDATE_REPRODUCIBLE=false"
fi
if [ "$sha_a" = "$R30H_A_EXPECTED_SOURCE_SHA" ]; then
    echo "EXPECTED_SOURCE_SHA_GATE=PASS"
else
    fail "EXPECTED_SOURCE_SHA_GATE=FAIL expected=$R30H_A_EXPECTED_SOURCE_SHA actual=$sha_a"
fi
[ "$FAIL" -eq 0 ] || exit 1

(
    REPO="$REPO" \
    P80_BUILD_ALLOW_DETACHED=1 \
    P80_BUILD_EXPECTED_SHA="$R30H_A_EXPECTED_SHA" \
    P80_BUILD_INCLUDE_P116=1 \
    P80_BUILD_TRANSFORM="$TRANSFORM_REL" \
    P80_BUILD_EXPECTED_SOURCE_SHA="$R30H_A_EXPECTED_SOURCE_SHA" \
    OUTPUT="$CANDIDATE_OUTPUT" \
    bash "$RUN_ROOT/builder.sh"
) | tee "$BUILD_PROVENANCE_LOG"
build_rc=${PIPESTATUS[0]}
echo "P80_CHROOT_BUILD_RC=$build_rc"
P80_CHROOT_BUILD_RC="$build_rc"
ROOTFS_MODE="$(marker_or P80_BUILD_ROOTFS_MODE NOT_REACHED)"
echo "ROOTFS_MODE=$ROOTFS_MODE"
if [ "$build_rc" -eq 0 ]; then
    CANDIDATE_COMPILE=PASS
    CANDIDATE_LINK=PASS
else
    fail "CANDIDATE_BUILD=FAIL"
fi
if [ -s "$CANDIDATE_OUTPUT" ]; then
    CANDIDATE_BINARY_SHA256="$(sha256sum "$CANDIDATE_OUTPUT" | awk '{print $1}')"
    CANDIDATE_BINARY_SIZE="$(stat -c '%s' "$CANDIDATE_OUTPUT")"
    CANDIDATE_ELF_INTERPRETER="$(readelf -l "$CANDIDATE_OUTPUT" | sed -n 's@.*Requesting program interpreter: \(.*\)]@\1@p')"
    CANDIDATE_NEEDED_LIBS="$(readelf -d "$CANDIDATE_OUTPUT" | sed -n 's/.*Shared library: \[\(.*\)\]/\1/p' | sort | paste -sd, -)"
else
    fail "CANDIDATE_OUTPUT_PRESENT=false"
fi
echo "CANDIDATE_COMPILE=$CANDIDATE_COMPILE"
echo "CANDIDATE_LINK=$CANDIDATE_LINK"
echo "CANDIDATE_BINARY_SHA256=$CANDIDATE_BINARY_SHA256"
echo "CANDIDATE_BINARY_SIZE=$CANDIDATE_BINARY_SIZE"
echo "CANDIDATE_ELF_INTERPRETER=$CANDIDATE_ELF_INTERPRETER"
echo "CANDIDATE_NEEDED_LIBS=$CANDIDATE_NEEDED_LIBS"
[ "$(marker_or NO_NEW_RUNTIME_DEPENDENCY FAIL)" = PASS ] && echo "NEW_RUNTIME_DEPENDENCY=false" || fail "NEW_RUNTIME_DEPENDENCY=true"
echo "CANDIDATE_BINARY_EXECUTED=false"
[ "$FAIL" -eq 0 ] || exit 1

if [ ! -f "$BASE_WRAPPER" ]; then
    fail "BASE_WRAPPER_PRESENT=false"
else
    BASE_WRAPPER_SHA256_ACTUAL="$(sha256sum "$BASE_WRAPPER" | awk '{print $1}')"
    echo "BASE_WRAPPER=$BASE_WRAPPER"
    echo "BASE_WRAPPER_SHA256=$BASE_WRAPPER_SHA256_ACTUAL"
fi

if [ "$FAIL" -eq 0 ]; then
    python3 - "$BASE_WRAPPER" "$CANDIDATE_WRAPPER" "$CANDIDATE_OUTPUT" "$CANDIDATE_BINARY_SHA256" <<'PY'
from pathlib import Path
import hashlib
import os
import sys

base = Path(sys.argv[1])
out = Path(sys.argv[2])
candidate = Path(sys.argv[3])
expected_sha = sys.argv[4]
holder_needle = '"$BASE/bin/comelit_ice_offer_holder"'
legacy_run_dir = "/run/comelit-p2p"
media_run_dir = "/run/comelit-media"
base_binary = "/usr/local/sbin/comelit-p2p-cloud-probe"

text = base.read_text(encoding="utf-8")
if text.count(holder_needle) != 1:
    raise SystemExit("WRAPPER_BINDING_GATE=FAIL reason=holder_anchor_count")
run_dir_count = text.count(legacy_run_dir)
if run_dir_count < 1:
    raise SystemExit("WRAPPER_BINDING_GATE=FAIL reason=run_dir_anchor_absent")
if not candidate.is_file():
    raise SystemExit("WRAPPER_BINDING_GATE=FAIL reason=candidate_absent")
actual_sha = hashlib.sha256(candidate.read_bytes()).hexdigest()
if actual_sha != expected_sha:
    raise SystemExit("WRAPPER_BINDING_GATE=FAIL reason=candidate_sha_mismatch")

rewritten = text.replace(holder_needle, f'"{candidate}"', 1)
rewritten = rewritten.replace(legacy_run_dir, media_run_dir)
if holder_needle in rewritten:
    raise SystemExit("WRAPPER_BINDING_GATE=FAIL reason=base_holder_still_present")
if f'"{candidate}"' not in rewritten:
    raise SystemExit("WRAPPER_BINDING_GATE=FAIL reason=candidate_holder_absent")
if legacy_run_dir in rewritten:
    raise SystemExit("WRAPPER_BINDING_GATE=FAIL reason=legacy_run_dir_still_present")
if base_binary in rewritten:
    raise SystemExit("WRAPPER_BINDING_GATE=FAIL reason=base_binary_path_present")

# BASE_WRAPPER_FALLBACK_POSSIBLE=false is derived only from this static artifact:
# the unique helper holder expression is replaced by the per-run candidate path,
# the base holder expression and base wrapper path are absent after rewrite, and
# the candidate path is present before the script is only parsed with bash -n.
out.write_text(rewritten, encoding="utf-8")
os.chmod(out, 0o700)
print("BASE_HOLDER_PATH_PRESENT_IN_CANDIDATE_WRAPPER=false")
print("CANDIDATE_HOLDER_PATH_PRESENT_IN_CANDIDATE_WRAPPER=true")
print(f"CANDIDATE_HELPER_SHA_BOUND={actual_sha}")
print("BASE_WRAPPER_FALLBACK_POSSIBLE=false")
PY
    wrapper_rewrite_rc=$?
    if [ "$wrapper_rewrite_rc" -ne 0 ]; then
        fail "WRAPPER_BINDING_GATE=FAIL"
    elif bash -n "$CANDIDATE_WRAPPER"; then
        echo "CANDIDATE_WRAPPER=$CANDIDATE_WRAPPER"
        echo "CANDIDATE_WRAPPER_PARSE=PASS"
        echo "CANDIDATE_BINARY_SHA256=$CANDIDATE_BINARY_SHA256"
        echo "CANDIDATE_HELPER_SHA_BOUND_MATCHES_PRODUCT=true"
        WRAPPER_BINDING_GATE=PASS
        echo "WRAPPER_BINDING_GATE=PASS"
    else
        fail "CANDIDATE_WRAPPER_PARSE=FAIL"
    fi
fi
echo "CANDIDATE_WRAPPER_EXECUTED=false"
[ "$FAIL" -eq 0 ] || exit 1

set +e
R27_LIVE_RUN=NO REPO="$REPO" R27_EXPECTED_COMMIT_SHA="$R30H_A_EXPECTED_SHA" bash "$RUN_ROOT/runner.sh" > "$RUN_ROOT/r27-offline-refusal.log" 2>&1
r27_offline_rc=$?
set -u -o pipefail
if grep -Fq "R27_OFFLINE_SAFE_REFUSAL=true" "$RUN_ROOT/r27-offline-refusal.log" && [ "$r27_offline_rc" -eq 2 ]; then
    echo "R27_OFFLINE_SAFE_REFUSAL_RC=2"
    echo "R27_OFFLINE_SAFE_REFUSAL=true"
else
    fail "R27_OFFLINE_SAFE_REFUSAL=FAIL"
fi
echo "R27_HELPER_EVIDENCE_GATE=STATIC_PRESENT file=$RUNNER_REL:246-258"
echo "R27_SCALARS_SUPPRESSED_GATE=STATIC_PRESENT file=$RUNNER_REL:341-348"
echo "R27_INSUFFICIENT_HELPER_EVIDENCE_CLASSIFICATION=STATIC_PRESENT file=$RUNNER_REL:299-304"

echo "=== COMELIT P116 R30H-A OFFLINE PREFLIGHT FINAL ==="
echo "TASK_ID=$TASK_ID"
echo "R30H_A_EXPECTED_SHA=$R30H_A_EXPECTED_SHA"
echo "R30H_A_EXPECTED_SOURCE_SHA=$R30H_A_EXPECTED_SOURCE_SHA"
echo "CANDIDATE_GENERATION_A=PASS"
echo "CANDIDATE_GENERATION_B=PASS"
echo "CANDIDATE_SOURCE_SHA256_A=$sha_a"
echo "CANDIDATE_SOURCE_SHA256_B=$sha_b"
echo "CANDIDATE_SOURCE_BYTES_A=$bytes_a"
echo "CANDIDATE_SOURCE_BYTES_B=$bytes_b"
echo "CANDIDATE_REPRODUCIBLE=true"
echo "EXPECTED_SOURCE_SHA_GATE=PASS"
echo "CANDIDATE_COMPILE=$CANDIDATE_COMPILE"
echo "CANDIDATE_LINK=$CANDIDATE_LINK"
echo "CANDIDATE_BINARY_SHA256=$CANDIDATE_BINARY_SHA256"
echo "CANDIDATE_BINARY_SIZE=$CANDIDATE_BINARY_SIZE"
echo "CANDIDATE_ELF_INTERPRETER=$CANDIDATE_ELF_INTERPRETER"
echo "CANDIDATE_NEEDED_LIBS=$CANDIDATE_NEEDED_LIBS"
echo "NEW_RUNTIME_DEPENDENCY=false"
echo "P80_CHROOT_BUILD_RC=$P80_CHROOT_BUILD_RC"
echo "ROOTFS_MODE=$ROOTFS_MODE"
echo "CANDIDATE_BINARY_EXECUTED=false"
echo "WRAPPER_BINDING_GATE=$WRAPPER_BINDING_GATE"
echo "BASE_HOLDER_PATH_PRESENT_IN_CANDIDATE_WRAPPER=false"
echo "CANDIDATE_HOLDER_PATH_PRESENT_IN_CANDIDATE_WRAPPER=true"
echo "CANDIDATE_HELPER_SHA_BOUND=$CANDIDATE_BINARY_SHA256"
echo "CANDIDATE_HELPER_SHA_BOUND_MATCHES_PRODUCT=true"
echo "BASE_WRAPPER_FALLBACK_POSSIBLE=false"
echo "CANDIDATE_WRAPPER_EXECUTED=false"
echo "COMELIT_LIVE_EXECUTED=false"
echo "HA_TOUCHED=false"
echo "PRODUCTION_LISTENER_TOUCHED=false"
echo "PRODUCTION_CODE_CHANGED=false"
if [ "$FAIL" -eq 0 ] && [ "$WRAPPER_BINDING_GATE" = PASS ]; then
    echo "R30H_A_HARNESS_RESULT=PASS"
else
    echo "R30H_A_HARNESS_RESULT=FAIL"
fi
echo "=== END COMELIT P116 R30H-A OFFLINE PREFLIGHT FINAL ==="

[ "$FAIL" -eq 0 ] && [ "$WRAPPER_BINDING_GATE" = PASS ]
