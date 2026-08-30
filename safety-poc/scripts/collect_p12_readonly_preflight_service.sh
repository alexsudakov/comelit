#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

RUN_ROOT=/root/comelit-p12-readonly-preflight
META="${1:-}"

[[ "${EUID}" -eq 0 ]] || { echo "P12_PREFLIGHT_COLLECT_REQUIRES_ROOT=true"; exit 1; }
[[ -d "$RUN_ROOT" ]] || { echo "P12_PREFLIGHT_RUN_ROOT_PRESENT=false"; exit 1; }

if [[ -z "$META" ]]; then
    META="$(find "$RUN_ROOT" -maxdepth 1 -type f -name '*.meta' -printf '%T@ %p\n' | sort -nr | awk 'NR==1 {sub(/^[^ ]+ /, ""); print; exit}')"
fi
[[ -n "$META" && -f "$META" ]] || { echo "P12_PREFLIGHT_META_PRESENT=false"; exit 1; }

LOG="$(awk -F= '$1 == "P12_PREFLIGHT_SERVICE_LOG" {print substr($0, index($0,"=")+1)}' "$META")"
RCFILE="$(awk -F= '$1 == "P12_PREFLIGHT_SERVICE_RC_FILE" {print substr($0, index($0,"=")+1)}' "$META")"
UNIT="$(awk -F= '$1 == "P12_PREFLIGHT_SERVICE_UNIT" {print substr($0, index($0,"=")+1)}' "$META")"

case "$LOG" in "$RUN_ROOT"/*.log) ;; *) echo "P12_PREFLIGHT_LOG_PATH=FAIL"; exit 1 ;; esac
case "$RCFILE" in "$RUN_ROOT"/*.rc) ;; *) echo "P12_PREFLIGHT_RC_PATH=FAIL"; exit 1 ;; esac
[[ -n "$UNIT" ]] || { echo "P12_PREFLIGHT_UNIT_METADATA=FAIL"; exit 1; }
[[ -s "$LOG" ]] || { echo "P12_PREFLIGHT_LOG_NONEMPTY=false"; exit 1; }
[[ -s "$RCFILE" ]] || { echo "P12_PREFLIGHT_RC_NONEMPTY=false"; exit 1; }

[[ "$(grep -Fxc 'P12_PREFLIGHT_SERVICE_PAYLOAD_START=true' "$LOG")" -eq 1 ]] || {
    echo "P12_PREFLIGHT_SERVICE_START_MARKER=FAIL"
    exit 1
}
[[ "$(grep -Fxc 'P12_PREFLIGHT_SERVICE_PAYLOAD_END=true' "$LOG")" -eq 1 ]] || {
    echo "P12_PREFLIGHT_SERVICE_END_MARKER=FAIL"
    exit 1
}

RC="$(awk -F= '$1 == "P12_PREFLIGHT_RC" && $2 ~ /^[0-9]+$/ {print $2}' "$RCFILE")"
[[ -n "$RC" ]] || { echo "P12_PREFLIGHT_RC_PARSE=FAIL"; exit 1; }

echo "P12_PREFLIGHT_SERVICE_UNIT=$UNIT"
echo "P12_PREFLIGHT_SERVICE_LOG=$LOG"
echo "P12_PREFLIGHT_SERVICE_RC_FILE=$RCFILE"
echo "P12_PREFLIGHT_SERVICE_RESULT_RC=$RC"
echo "=== P12 PREFLIGHT LOG ==="
cat "$LOG"
echo "=== P12 PREFLIGHT RC ==="
cat "$RCFILE"

if [[ "$RC" != "0" ]]; then
    echo "P12_PREFLIGHT_SERVICE_RESULT=FAIL"
    echo "READONLY_TRANSPORT_READY=false"
    echo "LIVE_TEST_READY=false"
    exit 1
fi

required=(
  'P12_PREFLIGHT_BUILD_IDENTITY=PASS'
  'P12_PREFLIGHT_ARTIFACT_SHAPE=PASS'
  'P12_PREFLIGHT_SOURCE_ACTUATOR_SCAN=PASS'
  'P12_PREFLIGHT_BINARY_ACTUATOR_SCAN=PASS'
  'P12_PREFLIGHT_WRAPPER_ACTUATOR_SCAN=PASS'
  'P12_PREFLIGHT_READONLY_SURFACE=PASS'
  'P12_PREFLIGHT_WRAPPER_BINDING=PASS'
  'P12_PREFLIGHT_CONTROL_PLANE=PASS'
  'P12_PREFLIGHT_CREDENTIAL_METADATA=PASS'
  'P12_PREFLIGHT_NO_ACTIVE_CANDIDATE=PASS'
  'P12_READONLY_LIVE_RUN_PERFORMED=false'
  'ACTIVE_COMELIT_NETWORK_PROBES=false'
  'ACTUATOR_COMMAND_ATTEMPTED=false'
  'PHYSICAL_DOOR_ACTION=false'
  'READONLY_TRANSPORT_READY=false'
  'LIVE_TEST_READY=false'
  'P12_READONLY_LIVE_PREFLIGHT=PASS'
  'P12_PREFLIGHT_EXIT_RC=0'
  'P12_PREFLIGHT_LAST_STEP=COMPLETE'
)
for marker in "${required[@]}"; do
    grep -Fxq "$marker" "$LOG" || {
        echo "P12_PREFLIGHT_SERVICE_REQUIRED_MARKER_MISSING=$marker"
        echo "P12_PREFLIGHT_SERVICE_RESULT=FAIL"
        exit 1
    }
done

echo "P12_PREFLIGHT_SERVICE_RESULT=PASS"
echo "P12_READONLY_LIVE_RUN_PERFORMED=false"
echo "ACTIVE_COMELIT_NETWORK_PROBES=false"
echo "ACTUATOR_COMMAND_ATTEMPTED=false"
echo "PHYSICAL_DOOR_ACTION=false"
echo "READONLY_TRANSPORT_READY=false"
echo "LIVE_TEST_READY=false"
