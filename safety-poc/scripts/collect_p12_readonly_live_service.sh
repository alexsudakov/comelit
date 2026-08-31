#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

RUN_ROOT=/root/comelit-p12-readonly-live-service
META="${1:-}"

[[ "${EUID}" -eq 0 ]] || { echo "P12_LIVE_COLLECT_REQUIRES_ROOT=true"; exit 1; }
[[ -d "$RUN_ROOT" ]] || { echo "P12_LIVE_RUN_ROOT_PRESENT=false"; exit 1; }

if [[ -z "$META" ]]; then
    META="$(find "$RUN_ROOT" -maxdepth 1 -type f -name '*.meta' -printf '%T@ %p\n' | sort -nr | awk 'NR==1 {sub(/^[^ ]+ /, ""); print; exit}')"
fi
[[ -n "$META" && -f "$META" ]] || { echo "P12_LIVE_META_PRESENT=false"; exit 1; }
case "$META" in "$RUN_ROOT"/*.meta) ;; *) echo "P12_LIVE_META_PATH=FAIL"; exit 1 ;; esac

LOG="$(awk -F= '$1 == "P12_LIVE_SERVICE_LOG" {print substr($0, index($0,"=")+1)}' "$META")"
RCFILE="$(awk -F= '$1 == "P12_LIVE_SERVICE_RC_FILE" {print substr($0, index($0,"=")+1)}' "$META")"
UNIT="$(awk -F= '$1 == "P12_LIVE_SERVICE_UNIT" {print substr($0, index($0,"=")+1)}' "$META")"

case "$LOG" in "$RUN_ROOT"/*.log) ;; *) echo "P12_LIVE_LOG_PATH=FAIL"; exit 1 ;; esac
case "$RCFILE" in "$RUN_ROOT"/*.rc) ;; *) echo "P12_LIVE_RC_PATH=FAIL"; exit 1 ;; esac
[[ -n "$UNIT" ]] || { echo "P12_LIVE_UNIT_METADATA=FAIL"; exit 1; }

# Wait only for the local result file. This never starts or retries the live
# operation; the systemd unit owns the single network-capable invocation.
echo "P12_LIVE_COLLECT_WAIT_ONLY=true"
for _ in $(seq 1 130); do
    [[ -s "$RCFILE" ]] && break
    sleep 1
done

[[ -s "$LOG" ]] || { echo "P12_LIVE_LOG_NONEMPTY=false"; exit 1; }
[[ -s "$RCFILE" ]] || { echo "P12_LIVE_RC_NONEMPTY=false"; exit 1; }

[[ "$(grep -Fxc 'P12_LIVE_SERVICE_PAYLOAD_START=true' "$LOG")" -eq 1 ]] || {
    echo "P12_LIVE_SERVICE_START_MARKER=FAIL"
    exit 1
}
[[ "$(grep -Fxc 'P12_LIVE_SERVICE_PAYLOAD_END=true' "$LOG")" -eq 1 ]] || {
    echo "P12_LIVE_SERVICE_END_MARKER=FAIL"
    exit 1
}

RC="$(awk -F= '$1 == "P12_LIVE_SERVICE_RC" && $2 ~ /^[0-9]+$/ {print $2}' "$RCFILE")"
[[ -n "$RC" ]] || { echo "P12_LIVE_RC_PARSE=FAIL"; exit 1; }

echo "P12_LIVE_SERVICE_UNIT=$UNIT"
echo "P12_LIVE_SERVICE_LOG=$LOG"
echo "P12_LIVE_SERVICE_RC_FILE=$RCFILE"
echo "P12_LIVE_SERVICE_RESULT_RC=$RC"
echo "=== P12 LIVE READ-ONLY LOG ==="
cat "$LOG"
echo "=== P12 LIVE READ-ONLY RC ==="
cat "$RCFILE"

# Functional PoC status: a successful UAUT response over this runner proves
# that Cloud P2P -> ICE -> PseudoTCP -> ViP connectivity and authentication
# both worked, even if a later read-only UCFG/target-binding step fails.
if grep -Fxq 'P2_VIP_UAUT_AUTH=PASS' "$LOG" && grep -Fxq 'UAUT_RESPONSE_CODE=200' "$LOG"; then
    echo "POC_P2P_CONNECTION=PASS"
    echo "POC_AUTHENTICATION=PASS"
else
    echo "POC_P2P_CONNECTION=NOT_PROVEN"
    echo "POC_AUTHENTICATION=NOT_PROVEN"
fi

if grep -Fxq 'TARGET_BINDING_VERIFIED=PASS' "$LOG"; then
    echo "POC_DEVICE_IDENTIFICATION=PASS"
else
    echo "POC_DEVICE_IDENTIFICATION=NOT_PROVEN"
fi

if [[ "$RC" != "0" ]]; then
    echo "P12_LIVE_SERVICE_RESULT=FAIL"
    echo "P12_LIVE_SERVICE_AUTO_RETRY=false"
    echo "ACTUATOR_COMMAND_ATTEMPTED=false"
    echo "PHYSICAL_DOOR_ACTION=false"
    echo "LIVE_TEST_READY=false"
    exit 1
fi

required=(
  'P12_ONE_SHOT_PROCESS_INVOCATIONS=1'
  'P12_ONE_SHOT_AUTO_RETRY=false'
  'P12_ONE_SHOT_PROCESS_GROUP_ISOLATED=true'
  'TIMEOUT_MAPPING_VERIFIED=PASS'
  'P12_READONLY_LIVE_RUN_PERFORMED=true'
  'P12_READONLY_LIVE_WRAPPER_INVOCATIONS=1'
  'P12_READONLY_LIVE_WRAPPER_OUTCOME=COMPLETED'
  'P12_READONLY_LIVE_WRAPPER_RC=0'
  'P2_VIP_UAUT_AUTH=PASS'
  'UAUT_RESPONSE_CODE=200'
  'VIP_UAUT_CLOSE_RESPONSE=PASS'
  'VIP_UAUT_CLOSE_RESPONSE_WORD=0'
  'P12_READONLY_LIVE_PROOF=PASS'
  'TARGET_BINDING_VERIFIED=PASS'
  'AUTH_SESSION_LIFETIME_VERIFIED=PASS'
  'CREDENTIAL_MATERIAL_EMITTED=false'
  'ACTUATOR_COMMAND_ATTEMPTED=false'
  'PHYSICAL_DOOR_ACTION=false'
  'PHYSICAL_EFFECT_ASSERTED=false'
  'P12_READONLY_LIVE_GATES=PASS'
  'READONLY_TRANSPORT_READY=false'
  'LIVE_TEST_READY=false'
)
for marker in "${required[@]}"; do
    grep -Fxq "$marker" "$LOG" || {
        echo "P12_LIVE_SERVICE_REQUIRED_MARKER_MISSING=$marker"
        echo "P12_LIVE_SERVICE_RESULT=FAIL"
        exit 1
    }
done

echo "P12_LIVE_SERVICE_RESULT=PASS"
echo "POC_P2P_CONNECTION=PASS"
echo "POC_AUTHENTICATION=PASS"
echo "POC_DEVICE_IDENTIFICATION=PASS"
echo "P12_LIVE_SERVICE_AUTO_RETRY=false"
echo "ACTUATOR_COMMAND_ATTEMPTED=false"
echo "PHYSICAL_DOOR_ACTION=false"
echo "READONLY_TRANSPORT_READY=false"
echo "LIVE_TEST_READY=false"
