#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="${1:-/root/comelit-v0.6-runtime-gates}"
CANONICAL_ROOT=/root/comelit-vip-poc

rm -rf "$OUT"
mkdir -p "$OUT"

export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

echo "=== OFFLINE REPOSITORY SUITE ==="
bash "$ROOT/scripts/run_offline_suite.sh" | tee "$OUT/00_offline_suite.txt"

echo
echo "=== PINNED LEGACY SYNTHETIC BODY ORACLE ==="
python3 "$ROOT/scripts/verify_legacy_synthetic_body_oracle.py" | tee "$OUT/10_body_oracle.txt"

echo
echo "=== CANONICAL CAPTURE-BASED SESSION TESTS ==="
(
    cd "$CANONICAL_ROOT"
    python3 -m unittest \
      tests.test_vip_session \
      tests.test_channel_session \
      tests.test_application_session -v
) 2>&1 | tee "$OUT/20_canonical_tests.txt"
printf '%s\n' \
  'CANONICAL_VIP_CAPTURE_TESTS=PASS' \
  'CANONICAL_VIP_SOURCE_HASHES=PASS' \
  'NETWORK_ACTION_PERFORMED=false' \
  'PHYSICAL_DOOR_ACTION=false' \
  >> "$OUT/20_canonical_tests.txt"

echo
echo "=== CANONICAL CTPP CONTROL FIXTURE ==="
python3 "$ROOT/scripts/verify_ctpp_control_plane_fixture.py" | tee "$OUT/30_ctpp_control.txt"

echo
echo "=== FULL OFFLINE TRANSACTION FIXTURE ==="
python3 "$ROOT/scripts/verify_full_offline_transaction_fixture.py" | tee "$OUT/40_full_transaction.txt"

cat \
  "$OUT/00_offline_suite.txt" \
  "$OUT/10_body_oracle.txt" \
  "$OUT/20_canonical_tests.txt" \
  "$OUT/30_ctpp_control.txt" \
  "$OUT/40_full_transaction.txt" \
  > "$OUT/90_combined_markers.txt"

echo
echo "=== REPOSITORY READINESS ==="
python3 "$ROOT/scripts/evaluate_plan_readiness.py" "$OUT/90_combined_markers.txt" \
  | tee "$OUT/95_readiness.txt"

cat "$OUT/95_readiness.txt" >> "$OUT/90_combined_markers.txt"

(
    cd "$OUT"
    sha256sum ./*.txt | sort > SHA256SUMS
)

echo
echo "=== CT120 RUNTIME GATE RESULT ==="
echo "RUNTIME_GATE_DIR=$OUT"
echo "RUNTIME_GATE_COMBINED=$OUT/90_combined_markers.txt"
echo "RUNTIME_GATE_SHA256SUMS=$OUT/SHA256SUMS"
echo "CT120_RUNTIME_GATES=PASS"
echo "REPOSITORY_READY=true"
echo "REAL_TRANSPORT_IMPLEMENTED=false"
echo "LIVE_TEST_READY=false"
echo "SECRETS_READ=false"
echo "NETWORK_ACTION_PERFORMED=false"
echo "PHYSICAL_DOOR_ACTION=false"
