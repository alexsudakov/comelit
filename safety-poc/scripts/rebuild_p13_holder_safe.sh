#!/usr/bin/env bash
# Rebuild only the P13 native holder with the safe transform.
#
# This is deliberately non-actuating: it reads the pinned baseline source,
# root-only payload, and either the exact bound UCFG snapshot or a root-only
# SHA-pinned runtime CTPP identity binding; generates C; compiles; and
# atomically replaces the holder at the same path already used by the proven
# signaling wrapper. It performs no Comelit network session and never reaches
# SEND_ARMED.
set -Eeuo pipefail
umask 077

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
POC_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(git -C "$POC_ROOT" rev-parse --show-toplevel)"
EXPECTED_BRANCH=feat/p13-one-shot-actuation
BASE_SOURCE=/root/comelit-vip-poc/bin/comelit_ice_offer_holder.c
PAYLOAD=/root/comelit-p13-actuator-prep/real-door-payloads.json
NATIVE_DIR=/root/comelit-p13-native
HOLDER_SOURCE="$NATIVE_DIR/comelit_p13_holder.c"
HOLDER_TMP="$NATIVE_DIR/comelit_p13_holder.safe.tmp"
HOLDER="$NATIVE_DIR/comelit_p13_holder"
WRAPPER=/usr/local/sbin/comelit-p13-door-wrapper
BUILD_LOG="$NATIVE_DIR/rebuild-safe.log"
EXPECTED_BASE_SOURCE_SHA=d8c3bd50c33d702699b96c24f08363bb06f3b5312b3033aceead9ed67a6ce9d9

STEP=START
finish() {
    rc=$?
    rm -f -- "$HOLDER_TMP"
    echo "P13_SAFE_REBUILD_EXIT_RC=$rc"
    echo "P13_SAFE_REBUILD_LAST_STEP=$STEP"
    trap - EXIT
    exit "$rc"
}
trap finish EXIT

printf '%s\n' \
    'P13_SAFE_REBUILD_START=true' \
    'P13_SAFE_REBUILD_NON_ACTUATING=true'

STEP=IDENTITY
[[ "$EUID" -eq 0 ]] || { echo 'P13_SAFE_REBUILD_REQUIRES_ROOT=true'; exit 1; }
[[ "$(git -C "$REPO_ROOT" branch --show-current)" == "$EXPECTED_BRANCH" ]] || {
    echo 'P13_SAFE_REBUILD_BRANCH=FAIL'; exit 1;
}
LOCAL_HEAD="$(git -C "$REPO_ROOT" rev-parse HEAD)"
REMOTE_HEAD="$(git -C "$REPO_ROOT" rev-parse "origin/$EXPECTED_BRANCH")"
[[ "$LOCAL_HEAD" == "$REMOTE_HEAD" ]] || { echo 'P13_SAFE_REBUILD_REMOTE_IDENTITY=FAIL'; exit 1; }
[[ -z "$(git -C "$REPO_ROOT" status --porcelain)" ]] || {
    echo 'P13_SAFE_REBUILD_WORKTREE_CLEAN=false'; exit 1;
}
echo "P13_SAFE_REBUILD_HEAD=$LOCAL_HEAD"
echo "P13_SAFE_REBUILD_TREE=$(git -C "$REPO_ROOT" rev-parse HEAD^{tree})"

STEP=INPUTS
[[ -f "$BASE_SOURCE" ]] || { echo 'P13_SAFE_REBUILD_BASE_SOURCE_PRESENT=false'; exit 1; }
[[ "$(sha256sum "$BASE_SOURCE" | awk '{print $1}')" == "$EXPECTED_BASE_SOURCE_SHA" ]] || {
    echo 'P13_SAFE_REBUILD_BASE_SOURCE_PIN=FAIL'; exit 1;
}
[[ -f "$PAYLOAD" ]] || { echo 'P13_SAFE_REBUILD_PAYLOAD_PRESENT=false'; exit 1; }
[[ "$(stat -c '%u' "$PAYLOAD")" == 0 ]] || { echo 'P13_SAFE_REBUILD_PAYLOAD_OWNER=FAIL'; exit 1; }
[[ "$(stat -c '%a' "$PAYLOAD")" == 600 ]] || { echo 'P13_SAFE_REBUILD_PAYLOAD_MODE=FAIL'; exit 1; }
[[ -x "$WRAPPER" ]] || { echo 'P13_SAFE_REBUILD_WRAPPER_PRESENT=false'; exit 1; }
grep -Fq 'HOLDER_PATH="/root/comelit-p13-native/comelit_p13_holder"' "$WRAPPER" || {
    echo 'P13_SAFE_REBUILD_WRAPPER_HOLDER_BIND=FAIL'; exit 1;
}
echo 'P13_SAFE_REBUILD_INPUTS=PASS'

STEP=UNIT_TEST
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover \
    -s "$POC_ROOT/tests" -p 'test_p13_holder_transform_safe.py'
echo 'P13_SAFE_TRANSFORM_UNIT_TEST=PASS'

STEP=TRANSFORM
install -d -m 700 -o root -g root "$NATIVE_DIR"
: > "$BUILD_LOG"
chmod 600 "$BUILD_LOG"
python3 "$SCRIPT_DIR/p13_holder_transform_runtime_binding.py" \
    --source "$BASE_SOURCE" \
    --payload "$PAYLOAD" \
    --output "$HOLDER_SOURCE" \
    | tee -a "$BUILD_LOG"
chmod 600 "$HOLDER_SOURCE"

STEP=SOURCE_CONTRACT
python3 - "$HOLDER_SOURCE" <<'PY'
from pathlib import Path
import sys
text = Path(sys.argv[1]).read_text(encoding='utf-8')
assert text.count('if (!p13_begin_auth())') == 1
assert 'g_timeout_add(\n        250,\n        pseudotcp_success_quit_cb' not in text
assert text.count('g_timeout_add (\n                250,\n                pseudotcp_success_quit_cb') == 1
assert text.count('guint8 body[30];') == 1
assert 'write_le32(body + 4, 7);' in text
assert 'body[15] = 0;' in text
assert 'write_le32(body + 16, (guint32)sizeof(ctpp_extension_payload));' in text
assert 'extension_len != body_len - 16u' in text
print('P13_SAFE_GENERATED_SOURCE_CONTRACT=PASS')
PY

STEP=COMPILE
cc -O2 -Wall -Wextra \
    -o "$HOLDER_TMP" \
    "$HOLDER_SOURCE" \
    $(pkg-config --cflags --libs nice glib-2.0 gio-2.0 gobject-2.0) \
    2>> "$BUILD_LOG"
chmod 700 "$HOLDER_TMP"
chown root:root "$HOLDER_TMP"

for marker in \
    'P13_CTPP_OPEN_OUTCOME' \
    'P13_DOOR_WRITE_COUNT' \
    'P13_TEARDOWN=PASS' \
    'P13_ONE_SHOT_MAX_INVOCATIONS=1' \
    'P13_AUTO_RETRY_ALLOWED=false' \
    'PHYSICAL_DOOR_ACTION=false'; do
    grep -aFq -- "$marker" "$HOLDER_TMP" || {
        echo 'P13_SAFE_REBUILD_BINARY_MARKERS=FAIL'; exit 1;
    }
done

STEP=INSTALL
mv -f -- "$HOLDER_TMP" "$HOLDER"
chmod 700 "$HOLDER"
chown root:root "$HOLDER"
echo 'P13_SAFE_REBUILD_BINARY_MARKERS=PASS'
echo "P13_SAFE_REBUILD_HOLDER_SHA256=$(sha256sum "$HOLDER" | awk '{print $1}')"
echo 'P13_SAFE_REBUILD_HOLDER_OWNER=root'
echo 'P13_SAFE_REBUILD_HOLDER_MODE=700'

STEP=COMPLETE
printf '%s\n' \
    'P13_UAUT_AUTH_HANDOFF=PASS' \
    'P13_CTPP_OPEN_EXTENSION=PASS' \
    'P13_CTPP_ADDRESS_UCFG_BINDING=PASS' \
    'P13_CTPP_ADDRESS_VALUE_EMITTED=false' \
    'P13_NETWORK_ACTION_PERFORMED=false' \
    'P13_DOOR_ACTION_PERFORMED=false' \
    'SEND_ARMED_REACHED=false' \
    'P13_SAFE_REBUILD_COMPLETE=true'
