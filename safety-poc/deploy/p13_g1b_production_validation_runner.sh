#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

SELF="$(readlink -f "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(cd "$(dirname "$SELF")" && pwd)"
POC_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
RELEASE_ROOT="$(cd "$POC_ROOT/.." && pwd)"

PROD_ROOT=/opt/comelit-door-safety-poc/p13
CURRENT="$PROD_ROOT/current"

MANIFEST="$RELEASE_ROOT/RELEASE.env"
CHECKSUMS="$RELEASE_ROOT/RELEASE_CONTENT.sha256"

HOLDER=/root/comelit-p13-native/comelit_p13_holder
WRAPPER=/usr/local/sbin/comelit-p13-door-wrapper
PAYLOAD=/root/comelit-p13-actuator-prep/real-door-payloads.json

RUN_DIR=/root/comelit-p13-run
AUDIT_DIR=/root/comelit-p13-audit
DB="$RUN_DIR/g1b-production-validation.sqlite3"
AUDIT="$AUDIT_DIR/g1b-production-validation.jsonl"

INTERNAL_APPROVAL=I_APPROVE_P13_ONE_SHOT_PHYSICAL_DOOR_TEST

marker() {
    local key="$1"
    awk -F= -v key="$key" '
        $1 == key {
            print substr($0, length(key) + 2)
            exit
        }
    ' "$MANIFEST"
}

common_preflight() {
    [[ "${EUID}" -eq 0 ]]

    [[ -L "$CURRENT" ]]
    CURRENT_REAL="$(readlink -f "$CURRENT")"
    [[ "$CURRENT_REAL" == "$RELEASE_ROOT" ]]

    [[ -f "$MANIFEST" && -f "$CHECKSUMS" ]]

    (
        cd "$RELEASE_ROOT"
        sha256sum -c RELEASE_CONTENT.sha256 >/dev/null
    )

    HEAD="$(marker P13_SOURCE_HEAD)"
    TREE="$(marker P13_SOURCE_TREE)"
    RELEASE_ID="$(marker P13_RELEASE_ID)"

    HOLDER_SHA="$(marker P13_HOLDER_SHA256)"
    WRAPPER_SHA="$(marker P13_WRAPPER_SHA256)"
    PAYLOAD_SHA="$(marker P13_PAYLOAD_SHA256)"
    TARGET_FP="$(marker P13_TARGET_FINGERPRINT)"

    [[ "$HEAD" =~ ^[0-9a-f]{40}$ ]]
    [[ "$TREE" =~ ^[0-9a-f]{40}$ ]]
    [[ "$HOLDER_SHA" =~ ^[0-9a-f]{64}$ ]]
    [[ "$WRAPPER_SHA" =~ ^[0-9a-f]{64}$ ]]
    [[ "$PAYLOAD_SHA" =~ ^[0-9a-f]{64}$ ]]
    [[ "$TARGET_FP" =~ ^[0-9a-f]{64}$ ]]

    [[ "$(marker P13_G1B_VALIDATION_SCHEMA)" == 1 ]]

    [[ -f "$HOLDER" && -f "$WRAPPER" && -f "$PAYLOAD" ]]

    [[ "$(stat -c '%u:%a' "$HOLDER")" == '0:700' ]]
    [[ "$(stat -c '%u:%a' "$WRAPPER")" == '0:700' ]]
    [[ "$(stat -c '%u:%a' "$PAYLOAD")" == '0:600' ]]

    [[ "$(sha256sum "$HOLDER" | awk '{print $1}')" == "$HOLDER_SHA" ]]
    [[ "$(sha256sum "$WRAPPER" | awk '{print $1}')" == "$WRAPPER_SHA" ]]
    [[ "$(sha256sum "$PAYLOAD" | awk '{print $1}')" == "$PAYLOAD_SHA" ]]

    python3 - \
      "$RELEASE_ROOT/runtime-proof/runtime-identity-poc.json" \
      "$HOLDER_SHA" \
      "$WRAPPER_SHA" \
      "$PAYLOAD_SHA" \
      "$TARGET_FP" <<'PY'
import json
import sys

path, holder_sha, wrapper_sha, payload_sha, target_fp = sys.argv[1:]
obj = json.load(open(path, encoding="utf-8"))

assert obj["identity_type"] == "RUNTIME_IDENTITY_POC"
assert obj["holder"]["sha256"] == holder_sha
assert obj["holder"]["entrypoint"] == "NO_ARGUMENTS"
assert obj["wrapper"]["sha256"] == wrapper_sha
assert obj["payload"]["sha256"] == payload_sha
assert str(obj["payload"]["write_count"]) == "6"
assert obj["payload"]["target_fingerprint"] == target_fp
PY

    python3 - "$PAYLOAD" "$TARGET_FP" <<'PY'
import json
import sys

obj = json.load(open(sys.argv[1], encoding="utf-8"))
assert obj["target_fingerprint"] == sys.argv[2]
assert int(obj["write_count"]) == 6
PY

    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH="$POC_ROOT/src" \
    python3 "$POC_ROOT/scripts/p13_adapter_dry_init.py" \
      --payload "$PAYLOAD" \
      --wrapper "$WRAPPER" \
      --wrapper-sha256 "$WRAPPER_SHA" \
      --wrapper-mode 700 \
      >/dev/null

    if pgrep -f -- '(^|/)comelit_p13_holder([[:space:]]|$)' >/dev/null; then
        echo 'P13_G1B_CONFLICTING_PROCESS=true'
        exit 1
    fi

    if pgrep -f -- '(^|/)comelit-p13-door-wrapper([[:space:]]|$)' >/dev/null; then
        echo 'P13_G1B_CONFLICTING_PROCESS=true'
        exit 1
    fi

    install -d -m 700 -o root -g root "$RUN_DIR" "$AUDIT_DIR"

    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH="$POC_ROOT/src" \
    python3 "$POC_ROOT/scripts/p13_audit_durability_proof.py" \
      --audit "$AUDIT" \
      --head "$HEAD" \
      >/dev/null

    echo 'P13_G1B_RELEASE_BINDING=PASS'
    echo "P13_G1B_RELEASE_ID=$RELEASE_ID"
    echo "P13_G1B_SOURCE_HEAD=$HEAD"
    echo "P13_G1B_SOURCE_TREE=$TREE"
    echo 'P13_G1B_RUNTIME_ARTIFACT_IDENTITIES=PASS'
    echo 'P13_G1B_TARGET_BINDING=PASS'
    echo 'P13_G1B_AUDIT_DURABILITY=PASS'
    echo 'P13_G1B_CONFLICTING_PROCESS=false'
    echo 'P13_G1B_ONE_SHOT_MAX_INVOCATIONS=1'
    echo 'P13_G1B_AUTO_RETRY_ALLOWED=false'
    echo 'P13_G1B_PHYSICAL_EFFECT_ASSERTED=false'
}

MODE="${1:-}"

case "$MODE" in
    preflight)
        [[ $# -eq 1 ]]
        common_preflight

        echo 'P13_G1B_RUNNER_MODE=PREFLIGHT'
        echo 'P13_G1B_NON_ACTUATING_PREFLIGHT=PASS'
        echo 'P13_G1B_LIVE_APPROVAL=false'
        echo 'NETWORK_DOOR_ACTION_PERFORMED=false'
        echo 'PHYSICAL_DOOR_ACTION=false'
        echo 'SEND_ARMED_REACHED=false'
        ;;

    execute)
        [[ $# -eq 2 ]]
        OPERATION_ID="$2"

        [[ "$OPERATION_ID" =~ ^p13-g1b-[0-9a-f-]{36}$ ]]
        [[ "${P13_G1B_INTERNAL_ARM:-}" == 'G1B_SINGLE_USE_GATE_CONSUMED' ]]

        common_preflight

        echo 'P13_G1B_RUNNER_MODE=EXECUTE'
        echo "P13_G1B_OPERATION_ID=$OPERATION_ID"
        echo 'P13_G1B_WARNING=PHYSICAL_DOOR_MAY_OPEN'
        echo 'P13_G1B_ONE_SHOT_MAX_INVOCATIONS=1'
        echo 'P13_G1B_AUTO_RETRY_ALLOWED=false'

        exec env \
          P13_APPROVAL="$INTERNAL_APPROVAL" \
          PYTHONDONTWRITEBYTECODE=1 \
          PYTHONPATH="$POC_ROOT/src" \
          python3 -m comelit_safety_poc.p13_one_shot_physical \
            --db "$DB" \
            --operation-id "$OPERATION_ID" \
            --target-fingerprint "$TARGET_FP" \
            --min-interval-seconds 10 \
            --wrapper "$WRAPPER" \
            --wrapper-sha256 "$WRAPPER_SHA" \
            --wrapper-mode 700 \
            --payload "$PAYLOAD" \
            --payload-sha256 "$PAYLOAD_SHA" \
            --audit "$AUDIT" \
            --head "$HEAD" \
            --tree "$TREE"
        ;;

    *)
        echo 'P13_G1B_RUNNER=DENIED'
        exit 126
        ;;
esac
