#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONDONTWRITEBYTECODE=1
python3 scripts/static_safety_check.py
python3 -m unittest discover -s tests -v

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
DB="$TMP/poc.sqlite3"

python3 -m comelit_safety_poc.cli --db "$DB" run --operation-id demo-ack --target demo-door --scenario ack --min-interval-seconds 0 >/dev/null
python3 -m comelit_safety_poc.cli --db "$DB" run --operation-id demo-amb --target demo-door-2 --scenario timeout_after_accept --min-interval-seconds 0 >/dev/null
set +e
python3 -m comelit_safety_poc.cli --db "$DB" run --operation-id demo-crash --target demo-door-3 --scenario ack --fault crash_after_arm --min-interval-seconds 0 >/dev/null
RC=$?
set -e
[[ "$RC" -eq 75 ]]
python3 -m comelit_safety_poc.cli --db "$DB" recover >/dev/null
STATE="$(python3 -m comelit_safety_poc.cli --db "$DB" show --operation-id demo-crash | python3 -c 'import json,sys; print(json.load(sys.stdin)["state"])')"
[[ "$STATE" == "UNKNOWN_OUTCOME" ]]

echo "OFFLINE_SUITE=PASS"
echo "VIP_FIXTURE_ADAPTER_TESTS=PASS"
echo "DOOR_SEMANTIC_ADAPTER_TESTS=PASS"
echo "WIRE_RECONCILIATION_TESTS=PASS"
echo "LEGACY_BODY_SHAPE_INVENTORY_TESTS=PASS"
echo "TRANSPORT_BOUNDARY_CONTRACT=PASS"
echo "BOUNDARY_ATTEMPT_NUMBER_FIXED=1"
echo "PHYSICAL_EFFECT_ASSERTION_ALLOWED=false"
echo "REAL_TRANSPORT_IMPLEMENTED=false"
echo "AUTO_RETRY_IMPLEMENTED=false"
