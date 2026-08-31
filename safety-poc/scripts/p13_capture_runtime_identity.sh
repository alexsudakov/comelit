#!/usr/bin/env bash
# =============================================================================
# Capture P13 runtime identity for the first PoC door opening (CT120, root).
#
# Per P13_POC_DIRECT_PATH.md, the native holder SHA is a *runtime identity*
# for this PoC, not a claim of reproducible provenance. This script captures
# the current artifact identities once, verifies permissions and the required
# P13 no-argument holder capability markers without executing the holder, and
# writes a root-only runtime identity file that the preflight validates against
# the live artifacts.
#
# It performs NO Comelit network session and NO Door write.
# =============================================================================
set -Eeuo pipefail
umask 077

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"
HOLDER_PATH="${P13_HOLDER_PATH:-/root/comelit-p13-native/comelit_p13_holder}"
WRAPPER=/usr/local/sbin/comelit-p13-door-wrapper
PAYLOAD=/root/comelit-p13-actuator-prep/real-door-payloads.json
IDENTITY_FILE=/root/comelit-p13-runtime-identity.json
EXPECTED_TARGET_FINGERPRINT="${P13_TARGET_FINGERPRINT:-}"
EXPECTED_UCFG_SHA256="${P13_EXPECTED_UCFG_SHA256:-d31dca0fa13a57d3cbc600510149b3ad2a29c43e20949190ec62b44321d310b7}"

[[ "${EUID}" -eq 0 ]] || { echo "P13_RUNTIME_IDENTITY_REQUIRES_ROOT=true"; exit 1; }

echo "P13_RUNTIME_IDENTITY_CAPTURE_START=true"

# -- holder --------------------------------------------------------------------
[[ -f "$HOLDER_PATH" ]] || { echo "P13_HOLDER_PRESENT=false"; exit 1; }
HOLDER_SHA="$(sha256sum "$HOLDER_PATH" | awk '{print $1}')"
HOLDER_UID="$(stat -c '%u' "$HOLDER_PATH")"
HOLDER_MODE="$(stat -c '%a' "$HOLDER_PATH")"
[[ "$HOLDER_UID" == "0" ]] || { echo "P13_HOLDER_OWNER=FAIL(uid=$HOLDER_UID)"; exit 1; }
[[ "$HOLDER_MODE" == "700" ]] || { echo "P13_HOLDER_MODE=FAIL($HOLDER_MODE)"; exit 1; }

# Strictly non-executing capability check. The current PoC wrapper intentionally
# invokes the transformed holder with NO CLI arguments. The holder's payload is
# pinned at build time and operation_id is enforced by the wrapper/executor
# environment boundary. Therefore capability is proven by the exact embedded
# P13 transaction/result markers that the real-session adapter consumes, not by
# obsolete CLI flag strings.
for required in \
    'P13_CTPP_OPEN_OUTCOME' \
    'P13_DOOR_WRITE_COUNT' \
    'P13_TEARDOWN=PASS' \
    'P13_ONE_SHOT_MAX_INVOCATIONS=1' \
    'P13_AUTO_RETRY_ALLOWED=false' \
    'PHYSICAL_DOOR_ACTION=false'; do
    grep -aFq -- "$required" "$HOLDER_PATH" || {
        echo "P13_HOLDER_CAPABILITY=FAIL"
        echo "P13_HOLDER_REQUIRED_MARKER_MISSING=true"
        exit 1
    }
done
HOLDER_CAPABILITY="PASS"
echo "P13_HOLDER_CAPABILITY=PASS"
echo "P13_HOLDER_CAPABILITY_METHOD=STATIC_P13_MARKERS_NOARG"
echo "P13_HOLDER_ENTRYPOINT=NO_ARGUMENTS"
echo "P13_HOLDER_EXECUTED=false"

# -- wrapper -------------------------------------------------------------------
[[ -f "$WRAPPER" ]] || { echo "P13_WRAPPER_PRESENT=false"; exit 1; }
WRAPPER_SHA="$(sha256sum "$WRAPPER" | awk '{print $1}')"
WRAPPER_UID="$(stat -c '%u' "$WRAPPER")"
WRAPPER_MODE="$(stat -c '%a' "$WRAPPER")"
[[ "$WRAPPER_UID" == "0" ]] || { echo "P13_WRAPPER_OWNER=FAIL(uid=$WRAPPER_UID)"; exit 1; }
[[ "$WRAPPER_MODE" == "700" ]] || { echo "P13_WRAPPER_MODE=FAIL($WRAPPER_MODE)"; exit 1; }

if grep -q "HOLDER_PATH=\"$HOLDER_PATH\"" "$WRAPPER" 2>/dev/null; then
    WRAPPER_HOLDER_BIND="PASS"
else
    WRAPPER_HOLDER_BIND="FAIL"
fi
[[ "$WRAPPER_HOLDER_BIND" == "PASS" ]] || { echo "P13_WRAPPER_HOLDER_BIND=FAIL"; exit 1; }
echo "P13_WRAPPER_HOLDER_BIND=PASS"

# -- payload -------------------------------------------------------------------
[[ -f "$PAYLOAD" ]] || { echo "P13_PAYLOAD_PRESENT=false"; exit 1; }
PAYLOAD_UID="$(stat -c '%u' "$PAYLOAD")"
PAYLOAD_MODE="$(stat -c '%a' "$PAYLOAD")"
[[ "$PAYLOAD_UID" == "0" ]] || { echo "P13_PAYLOAD_OWNER=FAIL(uid=$PAYLOAD_UID)"; exit 1; }
[[ "$PAYLOAD_MODE" == "600" ]] || { echo "P13_PAYLOAD_MODE=FAIL($PAYLOAD_MODE)"; exit 1; }
PAYLOAD_SHA="$(sha256sum "$PAYLOAD" | awk '{print $1}')"

BUNDLE_REPORT="$(python3 - "$PAYLOAD" <<'PY'
import json, sys
raw = json.load(open(sys.argv[1], encoding="utf-8"))
bodies = raw.get("bodies") or []
print("count=%d" % len(bodies))
print("target_fingerprint=%s" % raw.get("target_fingerprint", ""))
print("ucfg_sha256=%s" % raw.get("ucfg_sha256", ""))
PY
)"
PAYLOAD_WRITE_COUNT="$(echo "$BUNDLE_REPORT" | sed -n 's/^count=//p')"
PAYLOAD_TARGET_FINGERPRINT="$(echo "$BUNDLE_REPORT" | sed -n 's/^target_fingerprint=//p')"
PAYLOAD_UCFG_SHA="$(echo "$BUNDLE_REPORT" | sed -n 's/^ucfg_sha256=//p')"
[[ "$PAYLOAD_WRITE_COUNT" == "6" ]] || { echo "P13_PAYLOAD_WRITE_COUNT=FAIL($PAYLOAD_WRITE_COUNT)"; exit 1; }
[[ "$PAYLOAD_TARGET_FINGERPRINT" =~ ^[0-9a-f]{64}$ ]] || { echo "P13_PAYLOAD_TARGET_FINGERPRINT=FAIL"; exit 1; }
[[ "$PAYLOAD_UCFG_SHA" == "$EXPECTED_UCFG_SHA256" ]] || { echo "P13_PAYLOAD_UCFG_BINDING=FAIL"; exit 1; }
echo "P13_PAYLOAD_UCFG_BINDING=PASS"
if [[ -n "$EXPECTED_TARGET_FINGERPRINT" ]]; then
    [[ "$PAYLOAD_TARGET_FINGERPRINT" == "$EXPECTED_TARGET_FINGERPRINT" ]] || {
        echo "P13_PAYLOAD_TARGET_BINDING=FAIL"
        exit 1
    }
    echo "P13_PAYLOAD_TARGET_BINDING=PASS"
fi
echo "P13_PAYLOAD_SIX_WRITES=PASS"

# -- persist runtime identity (root-only) ---------------------------------------
cat > "$IDENTITY_FILE" <<EOF
{
  "schema": 1,
  "identity_type": "RUNTIME_IDENTITY_POC",
  "holder": {
    "path": "$HOLDER_PATH",
    "sha256": "$HOLDER_SHA",
    "uid": "$HOLDER_UID",
    "mode": "$HOLDER_MODE",
    "capability": "$HOLDER_CAPABILITY",
    "capability_method": "STATIC_P13_MARKERS_NOARG",
    "entrypoint": "NO_ARGUMENTS"
  },
  "wrapper": {
    "path": "$WRAPPER",
    "sha256": "$WRAPPER_SHA",
    "uid": "$WRAPPER_UID",
    "mode": "$WRAPPER_MODE",
    "holder_binding": "$WRAPPER_HOLDER_BIND"
  },
  "payload": {
    "path": "$PAYLOAD",
    "sha256": "$PAYLOAD_SHA",
    "uid": "$PAYLOAD_UID",
    "mode": "$PAYLOAD_MODE",
    "write_count": "$PAYLOAD_WRITE_COUNT",
    "target_fingerprint": "$PAYLOAD_TARGET_FINGERPRINT",
    "ucfg_sha256": "$PAYLOAD_UCFG_SHA"
  }
}
EOF
chmod 600 "$IDENTITY_FILE"

echo "P13_RUNTIME_IDENTITY_FILE=$IDENTITY_FILE"
echo "P13_HOLDER_SHA256=$HOLDER_SHA"
echo "P13_WRAPPER_SHA256=$WRAPPER_SHA"
echo "P13_PAYLOAD_SHA256=$PAYLOAD_SHA"
echo "P13_PAYLOAD_SIX_WRITES=true"
echo "P13_TARGET_FINGERPRINT_CAPTURED=true"
echo "P13_RUNTIME_IDENTITY_CAPTURE_COMPLETE=true"
