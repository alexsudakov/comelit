#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

# P14 reusable root-only production runner. Network/public input is exactly one
# canonical operation_id. Target, artifacts and P13 identity remain local.
P13_PROD=/opt/comelit-door-safety-poc/p13
P13_RELEASE_ID=p13-415edb4525e4-50c0a916f73e-b6a10c68773a
P13_RELEASE="$P13_PROD/releases/$P13_RELEASE_ID"
P13_CURRENT="$P13_PROD/current"
P13_MANIFEST="$P13_RELEASE/RELEASE.env"
P13_SOURCE_HEAD=0dace902d2cef1478cddea0f9d4cd36fcddb3837
P13_SOURCE_TREE=415edb4525e46601cd0ef1249fc0965927b1ac29
HOLDER=/root/comelit-p13-native/comelit_p13_holder
WRAPPER=/usr/local/sbin/comelit-p13-door-wrapper
PAYLOAD=/root/comelit-p13-actuator-prep/real-door-payloads.json
JOURNAL=/root/comelit-p13-run/p13-one-shot.sqlite3
AUDIT=/root/comelit-p13-audit/audit.jsonl
RUN_DIR=/root/comelit-p13-run
TARGET_FP=832e5c09cf5f8ef79b9af83ba34b38a0a29847570ea37158310369850e2500ce
HOLDER_SHA=50c0a916f73ec810f131be1f48f47761a2cc69b9d06107d121519f97c538b450
WRAPPER_SHA=bf36b381f4921871f0b4df0820548b8943b935f1dfcd1521ceb79001dab71aa9
PAYLOAD_SHA=0d0159f9cc562c1c67bc362b192a30d3fabd634b2b92c3a96d8f318ecd842832
MIN_INTERVAL=10
P13_APPROVAL_TOKEN=I_APPROVE_P13_ONE_SHOT_PHYSICAL_DOOR_TEST
G1B_STATE=/root/comelit-p13-run/g1b-production-validation-v1.state
HISTORICAL_GATE_STATE=/root/comelit-p13-run/hermes-observed-acceptance-v1.state
G1B_GATE_BINARY=/usr/local/sbin/comelit-p13-g1b-validation

usage(){ echo 'usage: p14_production_runner.sh --operation-id p13-hermes-<uuid4>' >&2; exit 64; }
[[ $# -eq 2 && "$1" == '--operation-id' ]] || usage
OPERATION_ID="$2"
[[ "${EUID}" -eq 0 ]] || { echo 'P14_PRODUCTION_RUNNER_REQUIRES_ROOT=true'; exit 1; }
/usr/bin/python3 - "$OPERATION_ID" <<'PY'
import re,sys,uuid
v=sys.argv[1]
if not re.fullmatch(r"p13-hermes-[0-9a-f-]{36}",v): raise SystemExit("P14_OPERATION_ID=FAIL")
s=v[len("p13-hermes-"):]; u=uuid.UUID(s)
if u.version != 4 or str(u) != s: raise SystemExit("P14_OPERATION_ID=FAIL")
PY

echo 'P14_PRODUCTION_RUNNER_START=true'
echo 'P14_PRODUCTION_RUNNER_RETRY_ALLOWED=false'
echo 'P14_PHYSICAL_EFFECT_ASSERTED=false'
[[ -L "$P13_CURRENT" && "$(readlink -f "$P13_CURRENT")" == "$P13_RELEASE" ]] || { echo 'P14_P13_CURRENT_RELEASE_MISMATCH=true'; exit 1; }
[[ -f "$P13_MANIFEST" && -f "$P13_RELEASE/RELEASE_CONTENT.sha256" ]]
( cd "$P13_RELEASE"; sha256sum -c RELEASE_CONTENT.sha256 >/dev/null )
for marker in \
 "P13_SOURCE_HEAD=$P13_SOURCE_HEAD" "P13_SOURCE_TREE=$P13_SOURCE_TREE" \
 "P13_TARGET_FINGERPRINT=$TARGET_FP" "P13_HOLDER_SHA256=$HOLDER_SHA" \
 "P13_WRAPPER_SHA256=$WRAPPER_SHA" "P13_PAYLOAD_SHA256=$PAYLOAD_SHA" \
 'P13_PRODUCTION_OBSERVED_OPEN_RETIRED=true' 'P13_PRODUCTION_LIVE_COMMAND_EXPOSED=false' \
 'P13_AUTO_RETRY_ALLOWED=false' 'P13_PHYSICAL_EFFECT_ASSERTED=false'; do
 grep -Fxq "$marker" "$P13_MANIFEST" || { echo "P14_P13_MANIFEST_MARKER_MISSING=$marker"; exit 1; }
done
echo 'P14_P13_IMMUTABLE_RELEASE=PASS'
[[ -f "$G1B_STATE" ]] && grep -Fxq 'P13_G1B_GATE_STATE=CONSUMED_BEFORE_LIVE_ENTRYPOINT' "$G1B_STATE"
[[ -f "$HISTORICAL_GATE_STATE" && "$(cat "$HISTORICAL_GATE_STATE")" == 'CONSUMED_BEFORE_LIVE_ENTRYPOINT' ]]
[[ ! -e "$G1B_GATE_BINARY" ]]
grep -Fxq 'P13_G1B_TEMPORARY_HERMES_AUTHORITY_RETIRED=true' "$P13_MANIFEST"
echo 'P14_P13_PHYSICAL_VALIDATION_GATES_RETIRED=PASS'
[[ "$(stat -c '%u:%a' "$HOLDER")" == '0:700' && "$(stat -c '%u:%a' "$WRAPPER")" == '0:700' && "$(stat -c '%u:%a' "$PAYLOAD")" == '0:600' ]]
[[ "$(sha256sum "$HOLDER"|awk '{print $1}')" == "$HOLDER_SHA" && "$(sha256sum "$WRAPPER"|awk '{print $1}')" == "$WRAPPER_SHA" && "$(sha256sum "$PAYLOAD"|awk '{print $1}')" == "$PAYLOAD_SHA" ]]
echo 'P14_P13_RUNTIME_ARTIFACTS=PASS'
if pgrep -f -- '(^|/)comelit_p13_holder([[:space:]]|$)' >/dev/null || pgrep -f -- '(^|/)comelit-p13-door-wrapper([[:space:]]|$)' >/dev/null; then echo 'P14_CONFLICTING_NATIVE_PROCESS=true'; exit 75; fi
mkdir -p "$(dirname "$JOURNAL")" "$(dirname "$AUDIT")" "$RUN_DIR"; chmod 700 "$(dirname "$JOURNAL")" "$(dirname "$AUDIT")" "$RUN_DIR"
P13_PYTHONPATH="$P13_RELEASE/repo/src"; [[ -f "$P13_PYTHONPATH/comelit_safety_poc/p13_one_shot_physical.py" ]]
/usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin LANG=C.UTF-8 LC_ALL=C.UTF-8 PYTHONPATH="$P13_PYTHONPATH" PYTHONDONTWRITEBYTECODE=1 P13_APPROVAL="$P13_APPROVAL_TOKEN" P13_REQUIRE_ROOT_OWNER=1 \
 /usr/bin/python3 -m comelit_safety_poc.p13_one_shot_physical \
 --db "$JOURNAL" --operation-id "$OPERATION_ID" --target-fingerprint "$TARGET_FP" --min-interval-seconds "$MIN_INTERVAL" \
 --wrapper "$WRAPPER" --wrapper-sha256 "$WRAPPER_SHA" --wrapper-mode 700 --payload "$PAYLOAD" --payload-sha256 "$PAYLOAD_SHA" \
 --audit "$AUDIT" --head "$P13_SOURCE_HEAD" --tree "$P13_SOURCE_TREE" --run-dir "$RUN_DIR"
RC=$?
echo "P14_PRODUCTION_RUNNER_CHILD_RC=$RC"
echo 'P14_PRODUCTION_RUNNER_MAX_INVOCATIONS=1'
echo 'P14_PRODUCTION_RUNNER_RETRY_ALLOWED=false'
echo 'P14_PHYSICAL_EFFECT_ASSERTED=false'
exit "$RC"
