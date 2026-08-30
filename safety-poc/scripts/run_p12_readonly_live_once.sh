#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD_DIR=/root/comelit-p12-readonly-candidate
WRAPPER="$BUILD_DIR/comelit-p2p-cloud-probe-p12-readonly"
BINARY="$BUILD_DIR/comelit_ice_offer_holder.p12-readonly"
RUN_DIR=/root/comelit-p12-readonly-live
APPROVAL_EXPECTED=I_APPROVE_P12_READONLY_LIVE_ONCE
EXPECTED_WRAPPER_SHA=7eb9c4e8999dc6c6f15ac03344abd155a042482158352fadbca58a3f4fd91ce1
EXPECTED_BINARY_SHA=bae10046aa4a449e0e1bb56315308592aaf06b82049c80291871d6485b55668c

[[ "${EUID}" -eq 0 ]] || { echo "P12_LIVE_REQUIRES_ROOT=true"; exit 1; }
[[ "${P12_READONLY_LIVE_APPROVAL:-}" == "$APPROVAL_EXPECTED" ]] || {
    echo "P12_READONLY_LIVE_APPROVAL=FAIL"
    exit 1
}

bash "$SCRIPT_DIR/p12_readonly_live_preflight.sh"

[[ "$(sha256sum "$WRAPPER" | awk '{print $1}')" == "$EXPECTED_WRAPPER_SHA" ]] || { echo "P12_LIVE_WRAPPER_PIN=FAIL"; exit 1; }
[[ "$(sha256sum "$BINARY" | awk '{print $1}')" == "$EXPECTED_BINARY_SHA" ]] || { echo "P12_LIVE_BINARY_PIN=FAIL"; exit 1; }

mkdir -p "$RUN_DIR"
chmod 700 "$RUN_DIR"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
RAW="$RUN_DIR/${STAMP}.raw.log"
SAFE="$RUN_DIR/${STAMP}.safe.txt"
: > "$RAW"
chmod 600 "$RAW"

# Exactly one wrapper invocation. No shell retry loop and no second application attempt.
set +e
timeout --signal=TERM --kill-after=5s 75s "$WRAPPER" >"$RAW" 2>&1
rc=$?
set -e

echo "P12_READONLY_LIVE_RUN_PERFORMED=true"
echo "P12_READONLY_LIVE_WRAPPER_INVOCATIONS=1"
echo "P12_READONLY_LIVE_WRAPPER_RC=$rc"
echo "P12_READONLY_LIVE_RAW_LOG=$RAW"

# Raw output may contain environment-specific values. Never print it wholesale.
# Emit only exact public-safe protocol/safety markers needed to classify the run.
python3 - "$RAW" "$SAFE" <<'PY'
from pathlib import Path
import re
import sys

raw = Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace").splitlines()
out = Path(sys.argv[2])

allowed_exact = {
    "P2_VIP_UAUT_AUTH=PASS",
    "UAUT_RESPONSE_CODE=200",
    "UAUT_RESPONSE_VALUE_EMITTED=false",
    "VIP_UAUT_CLOSE_RESPONSE=PASS",
    "VIP_UAUT_CLOSE_RESPONSE_WORD=0",
    "VIP_UCFG_OPEN_RESPONSE=PASS",
    "VIP_UCFG_OPEN_RESPONSE_WORD=0",
    "VIP_UCFG_GET_CONFIGURATION_SENT=PASS",
    "UCFG_RECEIVED=true",
    "UCFG_RESPONSE_VALUE_EMITTED=false",
    "UCFG_LOCAL_CAPTURE_MODE=600",
    "VIP_UCFG_CLOSE_RESPONSE=PASS",
    "VIP_UCFG_CLOSE_RESPONSE_WORD=0",
    "P12_READONLY_TRANSACTION=PASS",
    "READONLY_SCOPE_ENFORCED=PASS",
    "CREDENTIAL_MATERIAL_EMITTED=false",
    "ACTUATOR_COMMAND_ATTEMPTED=false",
    "MEDIA_ACTIVATION_ATTEMPTED=false",
    "AUTO_RETRY_OBSERVED=false",
    "PHYSICAL_DOOR_ACTION=false",
    "PHYSICAL_EFFECT_ASSERTED=false",
    "LIVE_TEST_READY=false",
    "P12_VIP_TOKEN_UNIQUE_MATCH=true",
    "P12_VIP_TOKEN_VALUE_EMITTED=false",
}
allowed_prefix = (
    "VIP_UCFG_OPEN_RESPONSE_CHANNEL_ID=",
    "UCFG_RESPONSE_BYTES=",
    "UCFG_RESPONSE_SHA256=",
    "P12_UAUT_AUTH_OK=",
    "P12_UAUT_CLOSE_OK=",
    "P12_UCFG_OPEN_OK=",
    "P12_UCFG_RECEIVED=",
    "P12_UCFG_CLOSE_OK=",
    "P12_READONLY_STAGE_TIMEOUT stage=",
)

safe = []
for line in raw:
    line = line.strip()
    if line in allowed_exact or line.startswith(allowed_prefix):
        safe.append(line)

out.write_text("\n".join(safe) + ("\n" if safe else ""), encoding="utf-8")
PY
chmod 600 "$SAFE"
cat "$SAFE"

required=(
  'P2_VIP_UAUT_AUTH=PASS'
  'UAUT_RESPONSE_CODE=200'
  'VIP_UAUT_CLOSE_RESPONSE=PASS'
  'VIP_UAUT_CLOSE_RESPONSE_WORD=0'
  'VIP_UCFG_OPEN_RESPONSE=PASS'
  'VIP_UCFG_OPEN_RESPONSE_WORD=0'
  'UCFG_RECEIVED=true'
  'VIP_UCFG_CLOSE_RESPONSE=PASS'
  'VIP_UCFG_CLOSE_RESPONSE_WORD=0'
  'P12_READONLY_TRANSACTION=PASS'
  'READONLY_SCOPE_ENFORCED=PASS'
  'CREDENTIAL_MATERIAL_EMITTED=false'
  'ACTUATOR_COMMAND_ATTEMPTED=false'
  'AUTO_RETRY_OBSERVED=false'
  'PHYSICAL_DOOR_ACTION=false'
  'PHYSICAL_EFFECT_ASSERTED=false'
)
for marker in "${required[@]}"; do
  grep -Fxq "$marker" "$SAFE" || {
    echo "P12_READONLY_LIVE_PROOF=FAIL missing=$marker"
    echo "READONLY_TRANSPORT_READY=false"
    echo "LIVE_TEST_READY=false"
    exit 1
  }
done

[[ "$rc" -eq 0 ]] || {
    echo "P12_READONLY_LIVE_PROOF=FAIL wrapper_rc=$rc"
    echo "READONLY_TRANSPORT_READY=false"
    echo "LIVE_TEST_READY=false"
    exit 1
}

echo "P12_READONLY_LIVE_PROOF=PASS"
echo "REAL_TRANSPORT_IMPLEMENTED=true"
echo "REAL_TRANSPORT_READONLY_SESSION_PROOF=PASS"
echo "READONLY_SCOPE_ENFORCED=PASS"
echo "CREDENTIAL_MATERIAL_EMITTED=false"
echo "ACTUATOR_COMMAND_ATTEMPTED=false"
echo "PHYSICAL_DOOR_ACTION=false"
echo "PHYSICAL_EFFECT_ASSERTED=false"
echo "READONLY_TRANSPORT_READY=true"
echo "LIVE_TEST_READY=false"
