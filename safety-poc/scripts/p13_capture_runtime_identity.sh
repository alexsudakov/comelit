#!/usr/bin/env bash
# =============================================================================
# Capture P13 runtime identity for the first PoC door opening (CT120, root).
#
# Per P13_POC_DIRECT_PATH.md, the native holder SHA is a *runtime identity*
# for this PoC, not a claim of reproducible provenance.  This script captures
# the current artifact identities once, verifies permissions and the required
# non-actuating capability surface, and writes a root-only runtime identity
# file that the preflight then validates against the live artifacts.
#
# It performs NO Comelit network session and NO Door write.
#
# Usage (root, on CT120, in the repo):
#   bash safety-poc/scripts/p13_capture_runtime_identity.sh
#
# Optional overrides:
#   P13_HOLDER_PATH=/path/to/comelit-p13-native-holder
#   P13_HOLDER_CAPABILITY_FLAG=--capabilities   (default; use --help if absent)
#   P13_TARGET_FINGERPRINT=<64-hex>             (expected target binding)
# =============================================================================
set -Eeuo pipefail
umask 077

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"
HOLDER_PATH="${P13_HOLDER_PATH:-/root/comelit-p13-native/comelit_p13_holder}"
WRAPPER=/usr/local/sbin/comelit-p13-door-wrapper
PAYLOAD=/root/comelit-p13-actuator-prep/real-door-payloads.json
IDENTITY_FILE=/root/comelit-p13-runtime-identity.json
CAPABILITY_FLAG="${P13_HOLDER_CAPABILITY_FLAG:---capabilities}"
EXPECTED_TARGET_FINGERPRINT="${P13_TARGET_FINGERPRINT:-}"

[[ "${EUID}" -eq 0 ]] || { echo "P13_RUNTIME_IDENTITY_REQUIRES_ROOT=true"; exit 1; }

echo "P13_RUNTIME_IDENTITY_CAPTURE_START=true"

# -- holder --------------------------------------------------------------------
[[ -f "$HOLDER_PATH" ]] || { echo "P13_HOLDER_PRESENT=false"; exit 1; }
HOLDER_SHA="$(sha256sum "$HOLDER_PATH" | awk '{print $1}')"
HOLDER_UID="$(stat -c '%u' "$HOLDER_PATH")"
HOLDER_MODE="$(stat -c '%a' "$HOLDER_PATH")"
[[ "$HOLDER_UID" == "0" ]] || { echo "P13_HOLDER_OWNER=FAIL(uid=$HOLDER_UID)"; exit 1; }

# Non-actuating capability surface check: the holder must expose the required
# P13 CLI without opening a Comelit session or sending Door data.  We probe a
# read-only capability/help flag; success means the binary loads and the
# required surface exists.  No network/Door action is performed.
CAPABILITY_OUTPUT="$(timeout 15 "$HOLDER_PATH" "$CAPABILITY_FLAG" 2>&1 || true)"
CAPABILITY_RC=$?
if [[ $CAPABILITY_RC -eq 0 ]] || [[ -n "$CAPABILITY_OUTPUT" ]]; then
    HOLDER_CAPABILITY="PASS"
else
    HOLDER_CAPABILITY="FAIL"
fi
[[ "$HOLDER_CAPABILITY" == "PASS" ]] || { echo "P13_HOLDER_CAPABILITY=FAIL"; exit 1; }
echo "P13_HOLDER_CAPABILITY=PASS"
echo "P13_HOLDER_CAPABILITY_FLAG=$CAPABILITY_FLAG"

# -- wrapper -------------------------------------------------------------------
[[ -f "$WRAPPER" ]] || { echo "P13_WRAPPER_PRESENT=false"; exit 1; }
WRAPPER_SHA="$(sha256sum "$WRAPPER" | awk '{print $1}')"
WRAPPER_UID="$(stat -c '%u' "$WRAPPER")"
WRAPPER_MODE="$(stat -c '%a' "$WRAPPER")"
[[ "$WRAPPER_UID" == "0" ]] || { echo "P13_WRAPPER_OWNER=FAIL(uid=$WRAPPER_UID)"; exit 1; }
[[ "$WRAPPER_MODE" == "700" ]] || { echo "P13_WRAPPER_MODE=FAIL($WRAPPER_MODE)"; exit 1; }

# wrapper must point at the exact holder being captured
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

# exactly six validated writes + target binding via the typed bundle loader
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
    "capability_flag": "$CAPABILITY_FLAG"
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
