#!/usr/bin/env bash
# P112 final RUN5 timing/provenance corrective wrapper.
#
# This research-only wrapper does not implement Comelit protocol logic and does
# not touch the listener itself. It verifies the exact P111 runner + holder shim,
# derives one deterministic corrected runner, verifies that correction, and only
# then delegates to the already-audited P111 fail-closed pre-live path.
#
# RUN5 requires explicit P112_RUN5_AUTHORIZED=true. P112_PATCH_ONLY=1 performs
# only the deterministic offline derivation and exits without any live action.

set -u -o pipefail
umask 077

SELF_PATH="${BASH_SOURCE[0]}"
SELF_DIR="$(cd "$(dirname "$SELF_PATH")" && pwd)"
SOURCE_ROOT="${P112_SOURCE_ROOT:-$(cd "$SELF_DIR/../../../.." && pwd)}"

P111_RUNNER="${P112_P111_RUNNER:-$SOURCE_ROOT/safety-poc/research/media/v1/ct120_run_p110_final_run5_runner.sh}"
HOLDER_SHIM_SOURCE="${P112_HOLDER_SHIM_SOURCE:-$SOURCE_ROOT/safety-poc/research/media/v1/p111_packaged_musl_holder_shim.sh}"

EXPECTED_P111_RUNNER_SHA256=0826473fa925dd09429238e6c792831897a9077fb0b6899383d75dddda7c4798
EXPECTED_HOLDER_SHIM_SHA256=316858e7f8658a644151cd4a1ccfe13f253a279e118d7d54a499eb31c75a2c9a
EXPECTED_PR106_HEAD=977f7197f103050a9f52b43dad26af5df0c7bbf0
EXPECTED_PACKAGED_BINARY_SHA256=ebc731381022be89576a680c39f7402225048e48adab88376434f660ad1a5ade

OBSERVATION_SECONDS_LIMIT=40
OUTER_MAX_SECONDS=75

PATCH_ROOT="${P112_PATCH_ROOT:-/root/comelit-artifacts/p112-final-run5}"
PATCHED_RUNNER="${P112_OUTPUT:-$PATCH_ROOT/ct120_run_p112_derived_run5_runner.sh}"

FAIL=0
P112_SOURCE_RUNNER_SHA_GATE=FAIL
P112_SOURCE_SHIM_SHA_GATE=FAIL
P112_TIMEOUT_PATCH_GATE=FAIL
P112_SHIM_PIN_PATCH_GATE=FAIL
P112_PATCHED_SYNTAX_GATE=FAIL
OBSERVATION_BOUND_GATE=FAIL
OUTER_TIMEOUT_GATE=FAIL
GRACEFUL_TEARDOWN_HEADROOM_GATE=FAIL

fail() {
    echo "$1"
    FAIL=1
}

sha256_of() {
    sha256sum "$1" | awk '{print $1}'
}

for command in python3 sha256sum bash grep awk mkdir chmod; do
    command -v "$command" >/dev/null 2>&1 || fail "P112_MISSING_COMMAND=$command"
done

[ -f "$P111_RUNNER" ] || fail "P112_P111_RUNNER_PRESENT=false"
[ -f "$HOLDER_SHIM_SOURCE" ] || fail "P112_HOLDER_SHIM_PRESENT=false"

if [ "$FAIL" -eq 0 ]; then
    P111_SHA="$(sha256_of "$P111_RUNNER")"
    SHIM_SHA="$(sha256_of "$HOLDER_SHIM_SOURCE")"
    echo "P112_SOURCE_P111_RUNNER_SHA256=$P111_SHA"
    echo "P112_SOURCE_HOLDER_SHIM_SHA256=$SHIM_SHA"

    if [ "$P111_SHA" = "$EXPECTED_P111_RUNNER_SHA256" ]; then
        P112_SOURCE_RUNNER_SHA_GATE=PASS
    else
        fail "P112_SOURCE_RUNNER_SHA_GATE=FAIL"
    fi

    if [ "$SHIM_SHA" = "$EXPECTED_HOLDER_SHIM_SHA256" ]; then
        P112_SOURCE_SHIM_SHA_GATE=PASS
    else
        fail "P112_SOURCE_SHIM_SHA_GATE=FAIL"
    fi
fi

if [ "$FAIL" -ne 0 ]; then
    echo "P112_LIVE_INVOCATIONS_THIS_TASK=0"
    exit 1
fi

mkdir -p "$(dirname "$PATCHED_RUNNER")"
chmod 700 "$(dirname "$PATCHED_RUNNER")"

python3 - "$P111_RUNNER" "$PATCHED_RUNNER" "$EXPECTED_HOLDER_SHIM_SHA256" <<'PY'
from pathlib import Path
import os
import sys

source = Path(sys.argv[1])
target = Path(sys.argv[2])
expected_shim = sys.argv[3]
text = source.read_text(encoding="utf-8")

timeout_old = '"${MEDIA_SESSION_MAX_SECONDS}s"'
timeout_new = '"${OUTER_MAX_SECONDS}s"'
if text.count(timeout_old) != 1:
    raise SystemExit("P112_TIMEOUT_ANCHOR_COUNT=FAIL")
text = text.replace(timeout_old, timeout_new, 1)

rel_anchor = "HOLDER_SHIM_REL=safety-poc/research/media/v1/p111_packaged_musl_holder_shim.sh\n"
if text.count(rel_anchor) != 1:
    raise SystemExit("P112_SHIM_VAR_ANCHOR_COUNT=FAIL")
text = text.replace(
    rel_anchor,
    rel_anchor + f"EXPECTED_HOLDER_SHIM_SHA256={expected_shim}\n",
    1,
)

state_anchor = "HOLDER_SHIM_GATE=FAIL\n"
if text.count(state_anchor) != 1:
    raise SystemExit("P112_SHIM_STATE_ANCHOR_COUNT=FAIL")
text = text.replace(
    state_anchor,
    state_anchor
    + "HOLDER_SHIM_SOURCE_SHA_GATE=FAIL\n"
    + "HOLDER_SHIM_INSTALLED_SHA_GATE=FAIL\n",
    1,
)

old_block = """    HOLDER_SHIM_SHA256="$(sha256sum "$HOLDER_SHIM" | awk '{print $1}')"
    HOLDER_SHIM_SOURCE_SHA256="$(sha256sum "$source" | awk '{print $1}')"
    [ "$HOLDER_SHIM_SHA256" = "$HOLDER_SHIM_SOURCE_SHA256" ] || fail "HOLDER_SHIM_SHA_GATE=FAIL"
    HOLDER_SHIM_GATE=PASS
    echo "HOLDER_SHIM_SHA256=$HOLDER_SHIM_SHA256"
    echo "HOLDER_SHIM_GATE=PASS"
"""
new_block = """    HOLDER_SHIM_SHA256="$(sha256sum "$HOLDER_SHIM" | awk '{print $1}')"
    HOLDER_SHIM_SOURCE_SHA256="$(sha256sum "$source" | awk '{print $1}')"
    if [ "$HOLDER_SHIM_SOURCE_SHA256" = "$EXPECTED_HOLDER_SHIM_SHA256" ]; then
        HOLDER_SHIM_SOURCE_SHA_GATE=PASS
        echo "HOLDER_SHIM_SOURCE_SHA_GATE=PASS"
    else
        fail "HOLDER_SHIM_SOURCE_SHA_GATE=FAIL"
    fi
    if [ "$HOLDER_SHIM_SHA256" = "$EXPECTED_HOLDER_SHIM_SHA256" ]; then
        HOLDER_SHIM_INSTALLED_SHA_GATE=PASS
        echo "HOLDER_SHIM_INSTALLED_SHA_GATE=PASS"
    else
        fail "HOLDER_SHIM_INSTALLED_SHA_GATE=FAIL"
    fi
    if [ "$HOLDER_SHIM_SOURCE_SHA_GATE" = PASS ] && [ "$HOLDER_SHIM_INSTALLED_SHA_GATE" = PASS ]; then
        HOLDER_SHIM_GATE=PASS
        echo "HOLDER_SHIM_SHA256=$HOLDER_SHIM_SHA256"
        echo "HOLDER_SHIM_GATE=PASS"
    fi
"""
if text.count(old_block) != 1:
    raise SystemExit("P112_SHIM_BLOCK_ANCHOR_COUNT=FAIL")
text = text.replace(old_block, new_block, 1)

if 'OBSERVATION_SECONDS_LIMIT=40' not in text:
    raise SystemExit("P112_OBSERVATION_BOUND_ANCHOR=FAIL")
if 'OUTER_MAX_SECONDS=75' not in text:
    raise SystemExit("P112_OUTER_BOUND_ANCHOR=FAIL")
if '"${MEDIA_SESSION_MAX_SECONDS}s"' in text:
    raise SystemExit("P112_OLD_WRAPPER_TIMEOUT_REMAINS=FAIL")
if text.count('"${OUTER_MAX_SECONDS}s"') != 1:
    raise SystemExit("P112_OUTER_WRAPPER_TIMEOUT_COUNT=FAIL")

target.write_text(text, encoding="utf-8")
os.chmod(target, 0o700)
PY
PATCH_RC=$?
if [ "$PATCH_RC" -ne 0 ]; then
    fail "P112_DERIVATION_GATE=FAIL"
fi

if [ "$FAIL" -eq 0 ]; then
    if grep -Fq 'timeout --signal=TERM --kill-after=5s "${OUTER_MAX_SECONDS}s"' "$PATCHED_RUNNER" &&
       ! grep -Fq 'timeout --signal=TERM --kill-after=5s "${MEDIA_SESSION_MAX_SECONDS}s"' "$PATCHED_RUNNER"; then
        P112_TIMEOUT_PATCH_GATE=PASS
        OUTER_TIMEOUT_GATE=PASS
    else
        fail "P112_TIMEOUT_PATCH_GATE=FAIL"
    fi

    if grep -Fq "EXPECTED_HOLDER_SHIM_SHA256=$EXPECTED_HOLDER_SHIM_SHA256" "$PATCHED_RUNNER" &&
       grep -Fq 'HOLDER_SHIM_SOURCE_SHA_GATE=PASS' "$PATCHED_RUNNER" &&
       grep -Fq 'HOLDER_SHIM_INSTALLED_SHA_GATE=PASS' "$PATCHED_RUNNER"; then
        P112_SHIM_PIN_PATCH_GATE=PASS
    else
        fail "P112_SHIM_PIN_PATCH_GATE=FAIL"
    fi

    if grep -Fq 'OBSERVATION_SECONDS_LIMIT=40' "$PATCHED_RUNNER"; then
        OBSERVATION_BOUND_GATE=PASS
    else
        fail "P112_OBSERVATION_BOUND_GATE=FAIL"
    fi

    if [ "$OUTER_MAX_SECONDS" -gt "$OBSERVATION_SECONDS_LIMIT" ]; then
        GRACEFUL_TEARDOWN_HEADROOM_GATE=PASS
    else
        fail "P112_GRACEFUL_TEARDOWN_HEADROOM_GATE=FAIL"
    fi

    if bash -n "$PATCHED_RUNNER"; then
        P112_PATCHED_SYNTAX_GATE=PASS
    else
        fail "P112_PATCHED_SYNTAX_GATE=FAIL"
    fi
fi

PATCHED_SHA=NONE
if [ -f "$PATCHED_RUNNER" ]; then
    PATCHED_SHA="$(sha256_of "$PATCHED_RUNNER")"
fi

echo "=== COMELIT P112 DERIVATION SUMMARY ==="
echo "P112_SOURCE_RUNNER_SHA_GATE=$P112_SOURCE_RUNNER_SHA_GATE"
echo "P112_SOURCE_SHIM_SHA_GATE=$P112_SOURCE_SHIM_SHA_GATE"
echo "P112_TIMEOUT_PATCH_GATE=$P112_TIMEOUT_PATCH_GATE"
echo "P112_SHIM_PIN_PATCH_GATE=$P112_SHIM_PIN_PATCH_GATE"
echo "P112_PATCHED_SYNTAX_GATE=$P112_PATCHED_SYNTAX_GATE"
echo "OBSERVATION_SECONDS_LIMIT=$OBSERVATION_SECONDS_LIMIT"
echo "OUTER_MAX_SECONDS=$OUTER_MAX_SECONDS"
echo "OBSERVATION_BOUND_GATE=$OBSERVATION_BOUND_GATE"
echo "OUTER_TIMEOUT_GATE=$OUTER_TIMEOUT_GATE"
echo "GRACEFUL_TEARDOWN_HEADROOM_GATE=$GRACEFUL_TEARDOWN_HEADROOM_GATE"
echo "EXPECTED_HOLDER_SHIM_SHA256=$EXPECTED_HOLDER_SHIM_SHA256"
echo "P112_PATCHED_RUNNER_SHA256=$PATCHED_SHA"
echo "P112_PATCHED_RUNNER_PATH=$PATCHED_RUNNER"
echo "P112_LIVE_INVOCATIONS_THIS_TASK=0"
echo "=== END COMELIT P112 DERIVATION SUMMARY ==="

if [ "$FAIL" -ne 0 ]; then
    exit 1
fi

if [ "${P112_PATCH_ONLY:-0}" = 1 ]; then
    exit 0
fi

if [ "${P112_RUN5_AUTHORIZED:-false}" != true ]; then
    echo "P112_RUN5_AUTHORIZATION_GATE=FAIL"
    echo "P112_RUN5_EXECUTED=false"
    exit 2
fi

echo "P112_RUN5_AUTHORIZATION_GATE=PASS"
echo "P112_DELEGATING_TO_CORRECTED_P111_RUNNER=true"

P111_RESEARCH_ARTIFACT_ROOT="$SOURCE_ROOT" \
P110_EXPECTED_RUNNER_SHA256="$PATCHED_SHA" \
bash "$PATCHED_RUNNER"
RUN_RC=$?

echo
echo "=== COMELIT P112 FINAL EXECUTION SUMMARY ==="
echo "EXPECTED_PR106_HEAD=$EXPECTED_PR106_HEAD"
echo "EXPECTED_PACKAGED_BINARY_SHA256=$EXPECTED_PACKAGED_BINARY_SHA256"
echo "EXPECTED_P111_RUNNER_SHA256=$EXPECTED_P111_RUNNER_SHA256"
echo "EXPECTED_HOLDER_SHIM_SHA256=$EXPECTED_HOLDER_SHIM_SHA256"
echo "P112_PATCHED_RUNNER_SHA256=$PATCHED_SHA"
echo "OBSERVATION_SECONDS_LIMIT=$OBSERVATION_SECONDS_LIMIT"
echo "OUTER_MAX_SECONDS=$OUTER_MAX_SECONDS"
echo "OBSERVATION_BOUND_GATE=$OBSERVATION_BOUND_GATE"
echo "OUTER_TIMEOUT_GATE=$OUTER_TIMEOUT_GATE"
echo "GRACEFUL_TEARDOWN_HEADROOM_GATE=$GRACEFUL_TEARDOWN_HEADROOM_GATE"
echo "P112_RUN5_DELEGATE_RC=$RUN_RC"
echo "AUTOMATIC_RETRY=false"
echo "RUN6_AUTHORIZED=false"
echo "PR106_MERGED=false"
echo "HA_DEPLOYMENT=false"
echo "=== END COMELIT P112 FINAL EXECUTION SUMMARY ==="

exit "$RUN_RC"
