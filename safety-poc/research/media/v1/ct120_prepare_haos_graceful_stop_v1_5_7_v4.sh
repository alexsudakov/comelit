#!/usr/bin/env bash
# CT120 reviewed wrapper for the v1.5.7 Docker-free HAOS/musl builder.
#
# The v3 builder has one unsafe `strings | grep -q` probe while `pipefail` is
# enabled. If grep finds the symbol early, strings can receive SIGPIPE and the
# pipeline is reported as failed. This wrapper deterministically patches only
# that probe into a two-step strings-file + grep check, then executes the
# otherwise unchanged reviewed v3 builder.
#
# Candidate binary is never executed here or by v3. No Comelit/HA/Door/media
# action is performed.

set -u -o pipefail
umask 077

REPO=/root/comelit-door-diag-repo
CREDS=/root/.config/git/comelit.credentials
BRANCH=fix/graceful-pseudotcp-stop-haos-v1-5-7
BASE_MAIN=c9dc9ad0b1fb2ae4701340437edc9d2ff93b81ea
V3_REL=safety-poc/research/media/v1/ct120_prepare_haos_graceful_stop_v1_5_7_v3.sh
V3_BLOB_SHA=e69315c00b41914295a28e635a6af97b6c764635

if [ "${EUID}" -ne 0 ]; then
    echo "V157_V4_REQUIRES_ROOT=true"
    exit 1
fi

if [ -z "${RELEASE_SEED_SHA:-}" ]; then
    echo "V157_V4_RELEASE_SEED_PRESENT=false"
    exit 1
fi

if [ ! -f "$CREDS" ] || [ "$(stat -c '%a' "$CREDS" 2>/dev/null || true)" != 600 ]; then
    echo "V157_V4_TOKEN_CREDENTIAL_GATE=FAIL"
    exit 1
fi

echo "V157_V4_TOKEN_CREDENTIAL_GATE=PASS"

echo "=== TOKEN-ONLY REFRESH ==="
GIT_TERMINAL_PROMPT=0 \
git -C "$REPO" \
  -c credential.helper= \
  -c "credential.helper=store --file=$CREDS" \
  -c credential.useHttpPath=true \
  fetch origin \
  '+refs/heads/main:refs/remotes/origin/main' \
  "+refs/heads/$BRANCH:refs/remotes/origin/$BRANCH"
FETCH_RC=$?
echo "V157_V4_TOKEN_ONLY_FETCH_RC=$FETCH_RC"
[ "$FETCH_RC" -eq 0 ] || exit 1

REMOTE_MAIN="$(git -C "$REPO" rev-parse refs/remotes/origin/main)"
REMOTE_BRANCH="$(git -C "$REPO" rev-parse "refs/remotes/origin/$BRANCH")"
echo "V157_V4_REMOTE_MAIN=$REMOTE_MAIN"
echo "V157_V4_REMOTE_BRANCH=$REMOTE_BRANCH"

if [ "$REMOTE_MAIN" != "$BASE_MAIN" ]; then
    echo "V157_V4_MAIN_IDENTITY=FAIL"
    exit 1
fi
if [ "$REMOTE_BRANCH" != "$RELEASE_SEED_SHA" ]; then
    echo "V157_V4_BRANCH_SEED_IDENTITY=FAIL"
    exit 1
fi

echo "V157_V4_MAIN_IDENTITY=PASS"
echo "V157_V4_BRANCH_SEED_IDENTITY=PASS"

ACTUAL_V3_BLOB="$(git -C "$REPO" rev-parse "$RELEASE_SEED_SHA:$V3_REL")"
echo "V157_V4_V3_BLOB_SHA=$ACTUAL_V3_BLOB"
if [ "$ACTUAL_V3_BLOB" != "$V3_BLOB_SHA" ]; then
    echo "V157_V4_V3_BLOB_GATE=FAIL"
    exit 1
fi
echo "V157_V4_V3_BLOB_GATE=PASS"

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
RUN_ROOT="/root/comelit-v1-5-7-v4-wrapper-$STAMP"
ORIGINAL="$RUN_ROOT/v3-original.sh"
PATCHED="$RUN_ROOT/v3-patched.sh"
mkdir -p "$RUN_ROOT"
chmod 700 "$RUN_ROOT"

git -C "$REPO" show "$RELEASE_SEED_SHA:$V3_REL" > "$ORIGINAL"
EXTRACT_RC=$?
echo "V157_V4_V3_EXTRACT_RC=$EXTRACT_RC"
[ "$EXTRACT_RC" -eq 0 ] || exit 1

python3 - "$ORIGINAL" "$PATCHED" <<'PY'
from pathlib import Path
import sys

src = Path(sys.argv[1]).read_text(encoding="utf-8")
needle = """if strings -a \"$VENDORED_LIBNICE\" | grep -Fxq 'pseudo_tcp_socket_close'; then
    echo \"V157_CHROOT_VENDORED_LIBNICE_CLOSE_SYMBOL=PASS\"
else
    fail \"V157_CHROOT_VENDORED_LIBNICE_CLOSE_SYMBOL=FAIL\"
fi
"""
replacement = """VENDORED_LIBNICE_STRINGS=\"$BUILD/vendored-libnice.strings\"
strings -a \"$VENDORED_LIBNICE\" > \"$VENDORED_LIBNICE_STRINGS\"
VENDORED_LIBNICE_STRINGS_RC=$?
echo \"V157_CHROOT_VENDORED_LIBNICE_STRINGS_RC=$VENDORED_LIBNICE_STRINGS_RC\"
if [ \"$VENDORED_LIBNICE_STRINGS_RC\" -eq 0 ] && grep -Fxq 'pseudo_tcp_socket_close' \"$VENDORED_LIBNICE_STRINGS\"; then
    echo \"V157_CHROOT_VENDORED_LIBNICE_CLOSE_SYMBOL=PASS\"
else
    fail \"V157_CHROOT_VENDORED_LIBNICE_CLOSE_SYMBOL=FAIL\"
fi
"""
count = src.count(needle)
if count != 1:
    raise SystemExit(f"unsafe symbol gate count={count}, expected=1")
patched = src.replace(needle, replacement, 1)
if "strings -a \"$VENDORED_LIBNICE\" | grep -Fxq" in patched:
    raise SystemExit("unsafe pipe remains")
Path(sys.argv[2]).write_text(patched, encoding="utf-8")
PY
PATCH_RC=$?
echo "V157_V4_PATCH_RC=$PATCH_RC"
[ "$PATCH_RC" -eq 0 ] || exit 1
chmod 700 "$PATCHED"

bash -n "$PATCHED"
PARSE_RC=$?
echo "V157_V4_PATCHED_PARSE_RC=$PARSE_RC"
[ "$PARSE_RC" -eq 0 ] || exit 1

echo "V157_V4_PIPEFAIL_FALSE_NEGATIVE_FIX=PASS"
echo "V157_V4_CANDIDATE_EXECUTED=false"
echo "V157_V4_COMELIT_NETWORK_SESSION_STARTED=false"
echo "V157_V4_HOME_ASSISTANT_TOUCHED=false"
echo "V157_V4_DOOR_ACTION_SENT=false"
echo "V157_V4_SELF_ACTIVATION_SENT=false"
echo "V157_V4_MEDIA_SIGNALING_SENT=false"

echo "=== EXECUTE PATCHED REVIEWED V3 BUILDER ==="
RELEASE_SEED_SHA="$RELEASE_SEED_SHA" "$PATCHED"
RC=$?
echo "V157_V4_INNER_BUILDER_RC=$RC"
if [ "$RC" -eq 0 ]; then
    echo "V157_V4_RELEASE_PREPARE=PASS"
else
    echo "V157_V4_RELEASE_PREPARE=FAIL"
fi
exit "$RC"
