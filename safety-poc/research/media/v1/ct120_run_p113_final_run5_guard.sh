#!/usr/bin/env bash
# P113 final research-only guard for RUN5.
# Derives the exact P112-corrected runner, adds the final fail-closed MEDIA_RC=0
# success requirement, verifies the resulting executable contract, and only
# delegates when explicitly authorized. No Comelit protocol logic lives here.

set -u -o pipefail
umask 077

SELF_PATH="${BASH_SOURCE[0]}"
SELF_DIR="$(cd "$(dirname "$SELF_PATH")" && pwd)"
SOURCE_ROOT="${P113_SOURCE_ROOT:-$(cd "$SELF_DIR/../../../.." && pwd)}"
P112="$SOURCE_ROOT/safety-poc/research/media/v1/ct120_run_p112_final_run5_runner.sh"

EXPECTED_P112_HEAD=3e7396f552567a34ed609b3c0f1d88f44a24470c
EXPECTED_PR106_HEAD=977f7197f103050a9f52b43dad26af5df0c7bbf0
EXPECTED_PACKAGED_BINARY_SHA256=ebc731381022be89576a680c39f7402225048e48adab88376434f660ad1a5ade
EXPECTED_HOLDER_SHIM_SHA256=316858e7f8658a644151cd4a1ccfe13f253a279e118d7d54a499eb31c75a2c9a

WORK_ROOT="${P113_WORK_ROOT:-/root/comelit-artifacts/p113-final-run5}"
P112_DERIVED="$WORK_ROOT/p112-derived-runner.sh"
FINAL_RUNNER="$WORK_ROOT/p113-final-run5-runner.sh"

fail() {
    echo "$1"
    echo "P113_LIVE_INVOCATIONS_THIS_TASK=0"
    exit 1
}

for cmd in git bash python3 sha256sum grep mkdir chmod; do
    command -v "$cmd" >/dev/null 2>&1 || fail "P113_MISSING_COMMAND=$cmd"
done

[ -f "$P112" ] || fail "P113_P112_PRESENT=false"
mkdir -p "$WORK_ROOT"
chmod 700 "$WORK_ROOT"

CURRENT_HEAD="$(git -C "$SOURCE_ROOT" rev-parse HEAD 2>/dev/null || echo UNKNOWN)"
[ "$CURRENT_HEAD" = "$EXPECTED_P112_HEAD" ] || fail "P113_RESEARCH_HEAD_GATE=FAIL"
echo "P113_RESEARCH_HEAD_GATE=PASS"

P112_PATCH_ONLY=1 \
P112_SOURCE_ROOT="$SOURCE_ROOT" \
P112_OUTPUT="$P112_DERIVED" \
bash "$P112" >"$WORK_ROOT/p112-derivation.log" 2>&1 || {
    cat "$WORK_ROOT/p112-derivation.log"
    fail "P113_P112_DERIVATION_GATE=FAIL"
}

[ -f "$P112_DERIVED" ] || fail "P113_P112_DERIVED_PRESENT=false"

python3 - "$P112_DERIVED" "$FINAL_RUNNER" <<'PY'
from pathlib import Path
import os
import sys

src = Path(sys.argv[1])
out = Path(sys.argv[2])
text = src.read_text(encoding="utf-8")

anchor = '    [ "$LIVE_INVOCATIONS" -eq 1 ] || return 1\n'
insert = anchor + '    [ "$MEDIA_RC" -eq 0 ] || return 1\n'
if text.count(anchor) != 1:
    raise SystemExit("P113_MEDIA_RC_GATE_ANCHOR_COUNT=FAIL")
if '[ "$MEDIA_RC" -eq 0 ] || return 1' in text:
    raise SystemExit("P113_MEDIA_RC_GATE_ALREADY_PRESENT=FAIL")
text = text.replace(anchor, insert, 1)

summary_anchor = '    echo "LIVE_INVOCATIONS=$LIVE_INVOCATIONS"\n'
summary_insert = summary_anchor + '    echo "MEDIA_RC=$MEDIA_RC"\n'
if text.count(summary_anchor) != 1:
    raise SystemExit("P113_MEDIA_RC_SUMMARY_ANCHOR_COUNT=FAIL")
text = text.replace(summary_anchor, summary_insert, 1)

required = (
    'OBSERVATION_SECONDS_LIMIT=40',
    'OUTER_MAX_SECONDS=75',
    'timeout --signal=TERM --kill-after=5s "${OUTER_MAX_SECONDS}s"',
    'EXPECTED_HOLDER_SHIM_SHA256=316858e7f8658a644151cd4a1ccfe13f253a279e118d7d54a499eb31c75a2c9a',
    'HOLDER_SHIM_SOURCE_SHA_GATE=PASS',
    'HOLDER_SHIM_INSTALLED_SHA_GATE=PASS',
    '[ "$MEDIA_RC" -eq 0 ] || return 1',
)
for item in required:
    if item not in text:
        raise SystemExit("P113_REQUIRED_CONTRACT_MISSING=FAIL")
if 'timeout --signal=TERM --kill-after=5s "${MEDIA_SESSION_MAX_SECONDS}s"' in text:
    raise SystemExit("P113_OLD_45S_WRAPPER_TIMEOUT_PRESENT=FAIL")

out.write_text(text, encoding="utf-8")
os.chmod(out, 0o700)
PY
PATCH_RC=$?
[ "$PATCH_RC" -eq 0 ] || fail "P113_MEDIA_RC_PATCH_GATE=FAIL"

bash -n "$FINAL_RUNNER" || fail "P113_FINAL_RUNNER_SYNTAX_GATE=FAIL"

grep -Fq '[ "$MEDIA_RC" -eq 0 ] || return 1' "$FINAL_RUNNER" || fail "P113_MEDIA_RC_GATE=FAIL"
grep -Fq 'timeout --signal=TERM --kill-after=5s "${OUTER_MAX_SECONDS}s"' "$FINAL_RUNNER" || fail "P113_OUTER_TIMEOUT_GATE=FAIL"
! grep -Fq 'timeout --signal=TERM --kill-after=5s "${MEDIA_SESSION_MAX_SECONDS}s"' "$FINAL_RUNNER" || fail "P113_OLD_TIMEOUT_REMAINS=FAIL"
grep -Fq "EXPECTED_HOLDER_SHIM_SHA256=$EXPECTED_HOLDER_SHIM_SHA256" "$FINAL_RUNNER" || fail "P113_SHIM_PIN_GATE=FAIL"

FINAL_SHA="$(sha256sum "$FINAL_RUNNER" | awk '{print $1}')"

echo "=== COMELIT P113 FINAL GUARD SUMMARY ==="
echo "P113_RESEARCH_HEAD=$CURRENT_HEAD"
echo "EXPECTED_PR106_HEAD=$EXPECTED_PR106_HEAD"
echo "EXPECTED_PACKAGED_BINARY_SHA256=$EXPECTED_PACKAGED_BINARY_SHA256"
echo "EXPECTED_HOLDER_SHIM_SHA256=$EXPECTED_HOLDER_SHIM_SHA256"
echo "P113_FINAL_RUNNER_SHA256=$FINAL_SHA"
echo "P113_MEDIA_RC_ZERO_GATE=PASS"
echo "P113_OBSERVATION_BOUND=40"
echo "P113_OUTER_BOUND=75"
echo "P113_SHIM_PIN_GATE=PASS"
echo "P113_LIVE_INVOCATIONS_THIS_TASK=0"
echo "=== END COMELIT P113 FINAL GUARD SUMMARY ==="

if [ "${P113_RUN5_AUTHORIZED:-false}" != true ]; then
    echo "P113_RUN5_AUTHORIZATION_GATE=FAIL"
    echo "P113_RUN5_EXECUTED=false"
    exit 2
fi

echo "P113_RUN5_AUTHORIZATION_GATE=PASS"

echo "=== COMELIT P113 DELEGATING EXACTLY ONE FINAL RUN5 ==="
P111_RESEARCH_ARTIFACT_ROOT="$SOURCE_ROOT" \
P110_EXPECTED_RUNNER_SHA256="$FINAL_SHA" \
bash "$FINAL_RUNNER"
RUN_RC=$?

echo
echo "=== COMELIT P113 FINAL EXECUTION SUMMARY ==="
echo "P113_FINAL_RUNNER_SHA256=$FINAL_SHA"
echo "P113_RUN5_DELEGATE_RC=$RUN_RC"
echo "P113_MEDIA_RC_ZERO_GATE=PASS"
echo "AUTOMATIC_RETRY=false"
echo "RUN6_AUTHORIZED=false"
echo "PR106_MERGED=false"
echo "HA_DEPLOYMENT=false"
echo "=== END COMELIT P113 FINAL EXECUTION SUMMARY ==="
exit "$RUN_RC"
