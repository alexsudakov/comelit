#!/usr/bin/env bash
# =============================================================================
# P13 runtime artifact install (CT120, root, non-actuating).
#
# Installs the two artifacts strictly required for the first real Door-open:
#   /root/comelit-p13-native/comelit_p13_holder      (mode 0700, root:root)
#   /usr/local/sbin/comelit-p13-door-wrapper          (mode 0700, root:root)
#
# The holder is built by transforming the already-proven P12 native holder
# (P2P -> ICE -> PseudoTCP -> ViP -> UAUT baseline) with the reviewed
# p13_holder_transform.py, adding the CTPP open / six Door writes / close /
# teardown stage machine and the typed result markers.
#
# This script performs NO Comelit network session, NO UAUT/CTPP/Door action,
# and never reaches SEND_ARMED.
#
# Usage (root, on CT120, in an exact-synced feature branch checkout):
#   bash safety-poc/scripts/install_p13_runtime_artifacts.sh
#
# Optional overrides:
#   P13_BASE_SOURCE=/root/comelit-vip-poc/bin/comelit_ice_offer_holder.c
#   P13_PAYLOAD=/root/comelit-p13-actuator-prep/real-door-payloads.json
# =============================================================================
set -Eeuo pipefail
umask 077

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
POC_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(git -C "$POC_ROOT" rev-parse --show-toplevel)"
EXPECTED_BRANCH=feat/p13-one-shot-actuation
BASE_SOURCE="${P13_BASE_SOURCE:-/root/comelit-vip-poc/bin/comelit_ice_offer_holder.c}"
BASE_BINARY="/root/comelit-vip-poc/bin/comelit_ice_offer_holder"
PAYLOAD="${P13_PAYLOAD:-/root/comelit-p13-actuator-prep/real-door-payloads.json}"
NATIVE_DIR=/root/comelit-p13-native
HOLDER="$NATIVE_DIR/comelit_p13_holder"
WRAPPER=/usr/local/sbin/comelit-p13-door-wrapper
WRAPPER_TEMPLATE="$POC_ROOT/deploy/p13_wrapper_template.sh"
HOLDER_SOURCE="$NATIVE_DIR/comelit_p13_holder.c"
BUILD_LOG="$NATIVE_DIR/install.log"

EXPECTED_BASE_SOURCE_SHA=d8c3bd50c33d702699b96c24f08363bb06f3b5312b3033aceead9ed67a6ce9d9
EXPECTED_BASE_BINARY_SHA=628b9c020bd3948d5edae2b7a6d68061c8af2b3a72e26463f2f5486f1e61d9de

STEP=START
install_exit() {
    rc=$?
    echo "P13_INSTALL_EXIT_RC=$rc"
    echo "P13_INSTALL_LAST_STEP=$STEP"
    trap - EXIT
    exit "$rc"
}
trap install_exit EXIT

echo "P13_INSTALL_START=true"
echo "P13_INSTALL_NON_ACTUATING=true"

# ---- 0. identity ------------------------------------------------------------
STEP=IDENTITY
[[ "${EUID}" -eq 0 ]] || { echo "P13_INSTALL_REQUIRES_ROOT=true"; exit 1; }
[[ "$(git -C "$REPO_ROOT" branch --show-current)" == "$EXPECTED_BRANCH" ]] || {
    echo "P13_INSTALL_BRANCH=FAIL"
    exit 1
}
REMOTE_HEAD="$(git -C "$REPO_ROOT" rev-parse "origin/$EXPECTED_BRANCH")"
LOCAL_HEAD="$(git -C "$REPO_ROOT" rev-parse HEAD)"
[[ "$LOCAL_HEAD" == "$REMOTE_HEAD" ]] || { echo "P13_INSTALL_REMOTE_IDENTITY=FAIL"; exit 1; }
[[ -z "$(git -C "$REPO_ROOT" status --porcelain)" ]] || {
    echo "P13_INSTALL_WORKTREE_DIRTY=true"
    exit 1
}
HEAD="$LOCAL_HEAD"
TREE="$(git -C "$REPO_ROOT" rev-parse HEAD^{tree})"
echo "P13_INSTALL_HEAD=$HEAD"
echo "P13_INSTALL_TREE=$TREE"

# ---- 1. baseline artifacts ---------------------------------------------------
STEP=BASELINE
[[ -f "$BASE_SOURCE" ]] || { echo "P13_BASE_SOURCE_PRESENT=false"; exit 1; }
[[ -f "$BASE_BINARY" ]] || { echo "P13_BASE_BINARY_PRESENT=false"; exit 1; }
BASE_SOURCE_SHA="$(sha256sum "$BASE_SOURCE" | awk '{print $1}')"
BASE_BINARY_SHA="$(sha256sum "$BASE_BINARY" | awk '{print $1}')"
[[ "$BASE_SOURCE_SHA" == "$EXPECTED_BASE_SOURCE_SHA" ]] || { echo "P13_BASE_SOURCE_PIN=FAIL"; exit 1; }
[[ "$BASE_BINARY_SHA" == "$EXPECTED_BASE_BINARY_SHA" ]] || { echo "P13_BASE_BINARY_PIN=FAIL"; exit 1; }
[[ -f "$PAYLOAD" ]] || { echo "P13_PAYLOAD_PRESENT=false"; exit 1; }
PAYLOAD_MODE="$(stat -c '%a' "$PAYLOAD")"
[[ "$PAYLOAD_MODE" == "600" ]] || { echo "P13_PAYLOAD_MODE=FAIL($PAYLOAD_MODE)"; exit 1; }
echo "P13_BASE_SOURCE_PIN=PASS"
echo "P13_BASE_BINARY_PIN=PASS"

# The generated holder pins the SHA-256 of the canonical JSON byte stream.
# Normalize only JSON formatting before transform/build so the runtime file
# bytes are exactly the bytes whose SHA is embedded in the holder. Door bodies
# and all semantic metadata remain unchanged.
STEP=PAYLOAD_CANONICALIZE
python3 "$SCRIPT_DIR/p13_canonicalize_payload.py" --payload "$PAYLOAD"
[[ "$(stat -c '%a' "$PAYLOAD")" == "600" ]] || { echo "P13_PAYLOAD_MODE_AFTER_CANONICALIZE=FAIL"; exit 1; }
echo "P13_PAYLOAD_CANONICAL_RUNTIME_BYTES=PASS"

# ---- 2. transform + build holder ---------------------------------------------
STEP=TRANSFORM
mkdir -p "$NATIVE_DIR"
chmod 700 "$NATIVE_DIR"
python3 "$SCRIPT_DIR/p13_holder_transform.py" \
    --source "$BASE_SOURCE" \
    --payload "$PAYLOAD" \
    --output "$HOLDER_SOURCE" \
    | tee "$BUILD_LOG"
chmod 600 "$HOLDER_SOURCE"

STEP=COMPILE
cc -O2 -Wall -Wextra \
    -o "$HOLDER" \
    "$HOLDER_SOURCE" \
    $(pkg-config --cflags --libs nice glib-2.0 gio-2.0 gobject-2.0) \
    2>> "$BUILD_LOG"

chmod 700 "$HOLDER"
chown root:root "$HOLDER"

# runtime identity sanity (non-actuating static scan only)
strings -a "$HOLDER" | grep -q 'P13_CTPP_OPEN_OUTCOME'
strings -a "$HOLDER" | grep -q 'P13_DOOR_WRITE_COUNT'
strings -a "$HOLDER" | grep -q 'P13_TEARDOWN=PASS'
strings -a "$HOLDER" | grep -q 'P13_ONE_SHOT_MAX_INVOCATIONS=1'
strings -a "$HOLDER" | grep -q 'P13_AUTO_RETRY_ALLOWED=false'
strings -a "$HOLDER" | grep -q 'PHYSICAL_DOOR_ACTION=false'
strings -a "$HOLDER" | grep -q -- '--emit-ctpp-markers'
echo "P13_HOLDER_BUILD=PASS"
echo "P13_HOLDER_SHA256=$(sha256sum "$HOLDER" | awk '{print $1}')"
echo "P13_HOLDER_MODE=$(stat -c '%a' "$HOLDER")"
echo "P13_HOLDER_OWNER=$(stat -c '%u' "$HOLDER")"

# ---- 3. wrapper ---------------------------------------------------------------
STEP=WRAPPER
python3 - "$WRAPPER_TEMPLATE" "$WRAPPER" "$HOLDER" <<'PY'
from pathlib import Path
import sys

src = Path(sys.argv[1])
out = Path(sys.argv[2])
holder = sys.argv[3]
text = src.read_text(encoding="utf-8")
needle = 'HOLDER_PATH="__P13_HOLDER_PATH__"'
count = text.count(needle)
if count != 1:
    raise SystemExit(f"P13_WRAPPER_TEMPLATE_MARKER_COUNT={count}")
text = text.replace(needle, f'HOLDER_PATH="{holder}"', 1)
out.write_text(text, encoding="utf-8")
PY
chmod 700 "$WRAPPER"
chown root:root "$WRAPPER"
bash -n "$WRAPPER"

grep -Fq "$HOLDER" "$WRAPPER" || { echo "P13_WRAPPER_HOLDER_BIND=FAIL"; exit 1; }
if grep -Fq '__P13_HOLDER_PATH__' "$WRAPPER"; then
    echo "P13_WRAPPER_TEMPLATE_MARKER_REMAINS=true"
    exit 1
fi
echo "P13_WRAPPER_INSTALL=PASS"
echo "P13_WRAPPER_SHA256=$(sha256sum "$WRAPPER" | awk '{print $1}')"
echo "P13_WRAPPER_MODE=$(stat -c '%a' "$WRAPPER")"
echo "P13_WRAPPER_OWNER=$(stat -c '%u' "$WRAPPER")"

# ---- 4. safety scan (non-actuating) -------------------------------------------
STEP=SAFETY_SCAN
if grep -RIEq 'NETWORK_ACTION_PERFORMED=true|PHYSICAL_DOOR_ACTION=true|SEND_ARMED_REACHED=true' "$NATIVE_DIR" "$WRAPPER"; then
    echo "P13_INSTALL_SAFETY_SCAN=FAIL"
    exit 1
fi
echo "P13_INSTALL_SAFETY_SCAN=PASS"

STEP=COMPLETE
echo "P13_INSTALL_LAST_STEP=COMPLETE"
echo "P13_RUNTIME_ARTIFACTS_INSTALLED=true"
echo "P13_HOLDER_PATH=$HOLDER"
echo "P13_WRAPPER_PATH=$WRAPPER"
echo "P13_NETWORK_ACTION_PERFORMED=false"
echo "P13_UAUT_CTPP_ACTION_PERFORMED=false"
echo "P13_DOOR_ACTION_PERFORMED=false"
echo "SEND_ARMED_REACHED=false"