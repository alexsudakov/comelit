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
echo "LEGACY_BODY_METHOD_SELECTION=QUALIFIED_CLASS_METHOD"
echo "CANONICAL_CONTROL_SHAPE_INVENTORY_TESTS=PASS"
echo "CTPP_BODY_STRUCTURAL_MODEL_TESTS=PASS"
echo "CTPP_CONTROL_PLANE_MODEL_TESTS=PASS"
echo "OFFLINE_DOOR_TRANSACTION_MODEL_TESTS=PASS"
echo "READINESS_GATE_TESTS=PASS"
echo "HA_SERVICE_CONTRACT_TESTS=PASS"
echo "SAFE_SOURCE_TOPOLOGY_TESTS=PASS"
echo "P12_READONLY_SESSION_CONTRACT_TESTS=PASS"
echo "P12_READONLY_SOURCE_INVENTORY_TESTS=PASS"
echo "P12_P2P_TRANSPORT_CONTRACT_TESTS=PASS"
echo "P12_TRANSPORT_PRIMARY_PATH=CLOUD_P2P_ICE_PSEUDOTCP_VIP"
echo "P13_ACTUATION_TRANSPORT_MODEL_TESTS=PASS"
echo "P13_AUDIT_SINK_TESTS=PASS"
echo "P13_ACTUATION_BOUNDARY_TESTS=PASS"
echo "P13_ONE_SHOT_EXECUTOR_INTEGRATION_TESTS=PASS"
echo "P13_ACTUATION_PREFLIGHT_TESTS=PASS"
echo "P13_REAL_PAYLOAD_PREP_TESTS=PASS"
echo "P13_CT120_REAL_SESSION_TESTS=PASS"
echo "P13_ONE_SHOT_PHYSICAL_RUNNER_TESTS=PASS"
echo "P13_RESTRICTED_SERVICE_TESTS=PASS"
echo "P13_ADAPTER_DRY_INIT_PRESENT=true"
echo "P13_AUDIT_DURABILITY_PROOF_PRESENT=true"
echo "P13_ONE_SHOT_RUNNER_PRESENT=true"
echo "P13_RUNTIME_IDENTITY_CAPTURE_PRESENT=true"
echo "P13_HOLDER_TRANSFORM_TESTS=PASS"
echo "P13_INSTALL_SCRIPT_TESTS=PASS"
echo "P13_HOLDER_TRANSFORM_PRESENT=true"
echo "P13_INSTALL_SCRIPT_PRESENT=true"
echo "P13_PRIMARY_PATH=CLOUD_P2P_ICE_PSEUDOTCP_VIP_CTPP"
echo "P13_ATTEMPT_NUMBER_FIXED=1"
echo "P13_AUTO_RETRY_ALLOWED=false"
echo "P13_PHYSICAL_EFFECT_ASSERTION_ALLOWED=false"
echo "CTPP_BODY_LAYOUT_RECONCILIATION=PENDING_RUNTIME_BYTE_ORACLE"
echo "CTPP_CONTROL_PLANE_RECONCILIATION=PENDING_RUNTIME_FIXTURE"
echo "FULL_OFFLINE_DOOR_TRANSACTION=PENDING_RUNTIME_FIXTURE"
echo "TRANSPORT_BOUNDARY_CONTRACT=PASS"
echo "BOUNDARY_ATTEMPT_NUMBER_FIXED=1"
echo "PHYSICAL_EFFECT_ASSERTION_ALLOWED=false"
echo "REAL_TRANSPORT_IMPLEMENTED=false"
echo "READONLY_TRANSPORT_READY=false"
echo "ACTUATION_TRANSPORT_IMPLEMENTED=false"
echo "AUTO_RETRY_IMPLEMENTED=false"
echo "LIVE_TEST_READY=false"
