#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD_DIR=/root/comelit-p12-readonly-candidate
SOURCE="$BUILD_DIR/comelit_ice_offer_holder.p12-readonly.c"
BINARY="$BUILD_DIR/comelit_ice_offer_holder.p12-readonly"
WRAPPER="$BUILD_DIR/comelit-p2p-cloud-probe-p12-readonly"
MANIFEST="$BUILD_DIR/MANIFEST.txt"
ONE_SHOT_EXEC="$SCRIPT_DIR/p12_one_shot_exec.py"
TARGET_VERIFY="$SCRIPT_DIR/p12_verify_target_binding.py"
LIVE_RUNNER="$SCRIPT_DIR/run_p12_readonly_live_once.sh"
FINALIZER="$SCRIPT_DIR/p12_finalize_readonly_readiness.py"
SECRETS_DIR=/root/.config/comelit
SECRETS_FILE=/root/.config/comelit/secrets.env

EXPECTED_BUILD_HEAD=150d594072aa1d999c99679d5451772e65c6554f
EXPECTED_BUILD_TREE=16531cebda2d407b157056dfd5a9836c211a89ec
EXPECTED_SOURCE_SHA=b8215df5008133c38fa57a31aae63f7cbf734710fa322aa641de2da08b8015ab
EXPECTED_BINARY_SHA=bae10046aa4a449e0e1bb56315308592aaf06b82049c80291871d6485b55668c
EXPECTED_WRAPPER_SHA=7eb9c4e8999dc6c6f15ac03344abd155a042482158352fadbca58a3f4fd91ce1

[[ "${EUID}" -eq 0 ]] || { echo "P12_PREFLIGHT_REQUIRES_ROOT=true"; exit 1; }
[[ -f "$SOURCE" && -f "$BINARY" && -f "$WRAPPER" && -f "$MANIFEST" ]] || {
    echo "P12_CANDIDATE_ARTIFACTS_PRESENT=false"
    exit 1
}
[[ -f "$ONE_SHOT_EXEC" && -f "$TARGET_VERIFY" && -f "$LIVE_RUNNER" && -f "$FINALIZER" ]] || {
    echo "P12_PREFLIGHT_CONTROL_PLANE_FILES_PRESENT=false"
    exit 1
}

source_sha="$(sha256sum "$SOURCE" | awk '{print $1}')"
binary_sha="$(sha256sum "$BINARY" | awk '{print $1}')"
wrapper_sha="$(sha256sum "$WRAPPER" | awk '{print $1}')"

[[ "$source_sha" == "$EXPECTED_SOURCE_SHA" ]] || { echo "P12_PREFLIGHT_SOURCE_PIN=FAIL"; exit 1; }
[[ "$binary_sha" == "$EXPECTED_BINARY_SHA" ]] || { echo "P12_PREFLIGHT_BINARY_PIN=FAIL"; exit 1; }
[[ "$wrapper_sha" == "$EXPECTED_WRAPPER_SHA" ]] || { echo "P12_PREFLIGHT_WRAPPER_PIN=FAIL"; exit 1; }

grep -Fxq "REPOSITORY_HEAD=$EXPECTED_BUILD_HEAD" "$MANIFEST"
grep -Fxq "REPOSITORY_TREE=$EXPECTED_BUILD_TREE" "$MANIFEST"
grep -Fxq "CANDIDATE_SOURCE_SHA256=$EXPECTED_SOURCE_SHA" "$MANIFEST"
grep -Fxq "CANDIDATE_BINARY_SHA256=$EXPECTED_BINARY_SHA" "$MANIFEST"
grep -Fxq "CANDIDATE_WRAPPER_SHA256=$EXPECTED_WRAPPER_SHA" "$MANIFEST"
grep -Fxq "P12_HOLDER_TRANSFORM_SAFE=PASS" "$MANIFEST"
grep -Fxq "P12_CANDIDATE_WRAPPER_BINDING=PASS" "$MANIFEST"
grep -Fxq "ACTUATOR_COMMAND_ATTEMPTED=false" "$MANIFEST"
grep -Fxq "PHYSICAL_DOOR_ACTION=false" "$MANIFEST"
grep -Fxq "LIVE_TEST_READY=false" "$MANIFEST"
echo "P12_PREFLIGHT_BUILD_IDENTITY=PASS"

[[ "$(stat -c '%a' "$SOURCE")" == "600" ]]
[[ "$(stat -c '%a' "$BINARY")" == "700" ]]
[[ "$(stat -c '%a' "$WRAPPER")" == "700" ]]
[[ "$(stat -c '%a' "$MANIFEST")" == "600" ]]
readelf -h "$BINARY" >/dev/null
bash -n "$WRAPPER"
echo "P12_PREFLIGHT_ARTIFACT_SHAPE=PASS"

if grep -Eq 'CTPP|OPEN_DOOR|open_door|create_door_message' "$SOURCE"; then
    echo "P12_PREFLIGHT_SOURCE_ACTUATOR_SCAN=FAIL"
    exit 1
fi
if strings -a "$BINARY" | grep -Eq 'CTPP|OPEN_DOOR|open_door|create_door_message'; then
    echo "P12_PREFLIGHT_BINARY_ACTUATOR_SCAN=FAIL"
    exit 1
fi
if grep -Eq 'CTPP|OPEN_DOOR|open_door|create_door_message' "$WRAPPER"; then
    echo "P12_PREFLIGHT_WRAPPER_ACTUATOR_SCAN=FAIL"
    exit 1
fi

grep -q 'P12_READONLY_TRANSACTION=PASS' "$SOURCE"
grep -q 'P12_VIP_TOKEN_VALUE_EMITTED=false' "$SOURCE"
grep -q 'CREDENTIAL_MATERIAL_EMITTED=false' "$SOURCE"
grep -q 'AUTO_RETRY_OBSERVED=false' "$SOURCE"
grep -q 'LIVE_TEST_READY=false' "$SOURCE"
strings -a "$BINARY" | grep -q 'P12_READONLY_TRANSACTION=PASS'
strings -a "$BINARY" | grep -q 'P12_VIP_TOKEN_VALUE_EMITTED=false'
strings -a "$BINARY" | grep -q 'CREDENTIAL_MATERIAL_EMITTED=false'
strings -a "$BINARY" | grep -q 'AUTO_RETRY_OBSERVED=false'
strings -a "$BINARY" | grep -q 'LIVE_TEST_READY=false'
echo "P12_PREFLIGHT_READONLY_SURFACE=PASS"

[[ "$(grep -Fc "$BINARY" "$WRAPPER")" -eq 1 ]] || { echo "P12_PREFLIGHT_WRAPPER_BINDING=FAIL"; exit 1; }
if grep -Fq '"$BASE/bin/comelit_ice_offer_holder"' "$WRAPPER"; then
    echo "P12_PREFLIGHT_BASELINE_HOLDER_BINDING_PRESENT=true"
    exit 1
fi
if grep -Eq '(^|[[:space:]])set[[:space:]]+-[^#\n]*x|bash[[:space:]]+-x|printenv|env[[:space:]]*$' "$WRAPPER"; then
    echo "P12_PREFLIGHT_XTRACE_OR_ENV_DUMP_SURFACE=true"
    exit 1
fi
echo "P12_PREFLIGHT_WRAPPER_BINDING=PASS"

# Parse repository control-plane sources only. This does not execute the
# supervisor, candidate, wrapper, finalizer, or any network-capable code.
python3 - "$ONE_SHOT_EXEC" "$TARGET_VERIFY" "$LIVE_RUNNER" "$FINALIZER" <<'PY'
from __future__ import annotations

import ast
from pathlib import Path
import re
import sys

one_shot, target, runner, finalizer = [Path(value) for value in sys.argv[1:]]
texts = {path: path.read_text(encoding="utf-8") for path in (one_shot, target, runner, finalizer)}
for path, text in texts.items():
    ast.parse(text, filename=str(path)) if path.suffix == ".py" else None
    if re.search(r"CTPP|OPEN_DOOR|open_door|create_door_message", text):
        raise SystemExit(f"P12_PREFLIGHT_CONTROL_ACTUATOR_SURFACE={path.name}")

one = texts[one_shot]
if one.count("subprocess.Popen(") != 1:
    raise SystemExit("P12_PREFLIGHT_ONE_SHOT_SPAWN_COUNT_FAIL")
for required in ("start_new_session=True", "os.killpg(proc.pid, sig)", "P12_ONE_SHOT_AUTO_RETRY=false"):
    if required not in one:
        raise SystemExit("P12_PREFLIGHT_ONE_SHOT_PROCESS_GROUP_FAIL")
if "shell=True" in one or "for attempt" in one or "while True" in one:
    raise SystemExit("P12_PREFLIGHT_ONE_SHOT_RETRY_SURFACE=true")

tree = ast.parse(texts[target], filename=str(target))
expected = None
for node in tree.body:
    if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "EXPECTED_VALUE_SHA256" for t in node.targets):
        expected = ast.literal_eval(node.value)
        break
if not isinstance(expected, dict) or set(expected) != {"model", "version", "apt-address", "apt-subaddress"}:
    raise SystemExit("P12_PREFLIGHT_TARGET_HASH_SET=FAIL")
if any(not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None for value in expected.values()):
    raise SystemExit("P12_PREFLIGHT_TARGET_HASH_FORMAT=FAIL")

run = texts[runner]
for required in (
    "APPROVAL_EXPECTED=I_APPROVE_P12_READONLY_LIVE_ONCE",
    "UCFG_CAPTURE=/run/comelit-p2p/p12-ucfg-response.json",
    'rm -f -- "$UCFG_CAPTURE"',
    'python3 "$SCRIPT_DIR/p12_one_shot_exec.py"',
    'python3 "$SCRIPT_DIR/p12_verify_target_binding.py"',
    "P12_READONLY_LIVE_GATES=PASS",
    'echo "READONLY_TRANSPORT_READY=false"',
):
    if required not in run:
        raise SystemExit("P12_PREFLIGHT_LIVE_RUNNER_CONTRACT=FAIL")
if 'echo "READONLY_TRANSPORT_READY=true"' in run:
    raise SystemExit("P12_PREFLIGHT_LIVE_RUNNER_OVERCLAIMS_READINESS=true")

final = texts[finalizer]
for required in (
    "REPOSITORY_GATES",
    "READONLY_GATES",
    "ACTUATION_TRANSPORT_IMPLEMENTED",
    "P12_READONLY_FINALIZATION=PASS",
):
    if required not in final:
        raise SystemExit("P12_PREFLIGHT_FINALIZER_CONTRACT=FAIL")

print("P12_PREFLIGHT_ONE_SHOT_CONTROL=PASS")
print("P12_PREFLIGHT_TARGET_HASH_PROFILE=PASS")
print("P12_PREFLIGHT_LIVE_RUNNER_CONTRACT=PASS")
print("P12_PREFLIGHT_FINALIZER_CONTRACT=PASS")
PY
echo "P12_PREFLIGHT_CONTROL_PLANE=PASS"

[[ -d "$SECRETS_DIR" && -f "$SECRETS_FILE" ]] || {
    echo "P12_PREFLIGHT_CREDENTIAL_CONTAINER_PRESENT=false"
    exit 1
}
[[ "$(stat -c '%a' "$SECRETS_DIR")" == "700" ]] || { echo "P12_PREFLIGHT_SECRETS_DIR_MODE=FAIL"; exit 1; }
[[ "$(stat -c '%u' "$SECRETS_DIR")" == "0" ]] || { echo "P12_PREFLIGHT_SECRETS_DIR_OWNER=FAIL"; exit 1; }
[[ "$(stat -c '%a' "$SECRETS_FILE")" == "600" ]] || { echo "P12_PREFLIGHT_SECRETS_FILE_MODE=FAIL"; exit 1; }
[[ "$(stat -c '%u' "$SECRETS_FILE")" == "0" ]] || { echo "P12_PREFLIGHT_SECRETS_FILE_OWNER=FAIL"; exit 1; }
echo "P12_PREFLIGHT_CREDENTIAL_METADATA=PASS"

if pgrep -f -- "$BINARY" >/dev/null 2>&1; then
    echo "P12_PREFLIGHT_CANDIDATE_PROCESS_RUNNING=true"
    exit 1
fi
if pgrep -f -- "$WRAPPER" >/dev/null 2>&1; then
    echo "P12_PREFLIGHT_WRAPPER_PROCESS_RUNNING=true"
    exit 1
fi
echo "P12_PREFLIGHT_NO_ACTIVE_CANDIDATE=PASS"

echo "P12_READONLY_LIVE_APPROVAL_REQUIRED=true"
echo "P12_READONLY_LIVE_APPROVED=false"
echo "P12_READONLY_LIVE_RUN_PERFORMED=false"
echo "CANDIDATE_EXECUTED=false"
echo "WRAPPER_EXECUTED=false"
echo "SECRETS_CONTENT_READ=false"
echo "CREDENTIAL_MATERIAL_EMITTED=false"
echo "TARGET_IDENTITY_VALUES_EMITTED=false"
echo "ACTIVE_COMELIT_NETWORK_PROBES=false"
echo "ACTUATOR_COMMAND_ATTEMPTED=false"
echo "PHYSICAL_DOOR_ACTION=false"
echo "PHYSICAL_EFFECT_ASSERTED=false"
echo "READONLY_TRANSPORT_READY=false"
echo "LIVE_TEST_READY=false"
echo "P12_READONLY_LIVE_PREFLIGHT=PASS"
