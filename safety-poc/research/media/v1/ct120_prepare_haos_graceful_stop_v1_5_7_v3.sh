#!/usr/bin/env bash
# CT120 release builder for Comelit v1.5.7 without Docker/Podman.
#
# It rebuilds the already-reviewed graceful-stop source inside an exact Alpine
# 3.24.1 minirootfs chroot, verifies HAOS/musl compatibility, freezes release
# metadata/tests, commits only the expected release artifact set, and pushes
# with the configured GitHub token credential store.
#
# The candidate native binary is NEVER executed by this script. The chroot is
# used only for package installation, compilation, and ELF metadata inspection.
# No Comelit session, HA action, Door action, self-activation, or media signaling
# is performed.
#
# Required environment:
#   RELEASE_SEED_SHA=<exact commit containing this reviewed script>

set -u -o pipefail
umask 077

REPO=/root/comelit-door-diag-repo
CREDS=/root/.config/git/comelit.credentials
BRANCH=fix/graceful-pseudotcp-stop-haos-v1-5-7
BASE_MAIN=c9dc9ad0b1fb2ae4701340437edc9d2ff93b81ea
EXPECTED_ARCH=x86_64

ALPINE_VERSION_EXPECTED=3.24.1
ALPINE_ROOTFS_NAME=alpine-minirootfs-3.24.1-x86_64.tar.gz
ALPINE_ROOTFS_URL=https://dl-cdn.alpinelinux.org/alpine/v3.24/releases/x86_64/alpine-minirootfs-3.24.1-x86_64.tar.gz
ALPINE_ROOTFS_SHA256_URL=https://dl-cdn.alpinelinux.org/alpine/v3.24/releases/x86_64/alpine-minirootfs-3.24.1-x86_64.tar.gz.sha256
EXPECTED_LIBNICE=0.1.22
EXPECTED_GLIB=2.88.1
EXPECTED_INTERPRETER=/lib/ld-musl-x86_64.so.1
EXPECTED_DIRECT_NEEDED_SORTED='libc.musl-x86_64.so.1,libglib-2.0.so.0,libgobject-2.0.so.0,libnice.so.10'

GRACEFUL_SOURCE_REL=safety-poc/research/door/v1_5_5/comelit-v4-persistent-ctpp-door.c
GRACEFUL_SOURCE_SHA=5827d9fd043b85fc0c59a31661a1a125c6b239771e2a70c3e5afdd95f1a03c73
FROZEN_V153_SOURCE_REL=safety-poc/research/door/v1_5_3/comelit-v4-persistent-ctpp-door.c
FROZEN_V153_SOURCE_SHA=088e0e23c07404792254f5c18e3f12dbbd499a676bda2d3883988d1d9bb3be6f
CURRENT_V156_BINARY_SHA=c171e7d1d342d059858f0cfca4f81dc8a07679f1d18992718bec2d6ead84db86
TRANSFORM_REL=safety-poc/research/media/v1/pseudotcp_graceful_stop_transform.py
TRANSFORM_SHA=b98e3f774054934421d7fda71e8c28aa89e9383adefe170221b00aa6184cbb6f

BINARY_REL=custom_components/comelit/native/comelit-v4
VENDORED_LIBNICE_REL=custom_components/comelit/native/lib/libnice.so.10
MANIFEST_REL=custom_components/comelit/manifest.json
RELEASE_DIR_REL=safety-poc/research/door/v1_5_7
RELEASE_SOURCE_REL=$RELEASE_DIR_REL/comelit-v4-persistent-ctpp-door.c
BUILD_INFO_REL=$RELEASE_DIR_REL/BUILD_INFO.txt
RELEASE_TEST_REL=safety-poc/tests/test_p29_haos_graceful_stop_release_contract.py

FAIL=0
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
RUN_ROOT="/root/comelit-v1-5-7-chroot-release-$STAMP"
WT="$RUN_ROOT/repo"
BUILD="$RUN_ROOT/build"
ROOTFS="$RUN_ROOT/alpine-rootfs"
ARCHIVE="$RUN_ROOT/$ALPINE_ROOTFS_NAME"
SHA_FILE="$ARCHIVE.sha256"
CANDIDATE="$BUILD/comelit-v4"
META="$BUILD/alpine-build-meta.txt"

fail() {
    echo "$1"
    FAIL=1
}

cleanup() {
    if [ -e "$WT/.git" ]; then
        if git -C "$REPO" worktree remove --force "$WT" >/dev/null 2>&1; then
            echo "V157_CHROOT_WORKTREE_CLEANUP=PASS"
        else
            echo "V157_CHROOT_WORKTREE_CLEANUP=WARNING"
        fi
    fi
}
trap cleanup EXIT

if [ "${EUID}" -ne 0 ]; then
    echo "V157_CHROOT_REQUIRES_ROOT=true"
    exit 1
fi

if [ -z "${RELEASE_SEED_SHA:-}" ]; then
    echo "V157_CHROOT_RELEASE_SEED_PRESENT=false"
    exit 1
fi

echo "V157_CHROOT_RELEASE_SEED_SHA=$RELEASE_SEED_SHA"

for command in git python3 sha256sum strings file awk grep sed uname chroot tar sort paste stat; do
    if ! command -v "$command" >/dev/null 2>&1; then
        fail "V157_CHROOT_MISSING_COMMAND=$command"
    fi
done

if [ "$(uname -m)" != "$EXPECTED_ARCH" ]; then
    fail "V157_CHROOT_HOST_ARCH=FAIL"
else
    echo "V157_CHROOT_HOST_ARCH=PASS $EXPECTED_ARCH"
fi

if [ ! -d "$REPO/.git" ]; then
    fail "V157_CHROOT_REPO_PRESENT=false"
fi

if [ ! -f "$CREDS" ]; then
    fail "V157_CHROOT_TOKEN_CREDENTIAL_PRESENT=false"
else
    MODE="$(stat -c '%a' "$CREDS")"
    echo "V157_CHROOT_TOKEN_CREDENTIAL_MODE=$MODE"
    if [ "$MODE" != 600 ]; then
        fail "V157_CHROOT_TOKEN_CREDENTIAL_GATE=FAIL"
    else
        echo "V157_CHROOT_TOKEN_CREDENTIAL_GATE=PASS"
    fi
fi

if [ "$FAIL" -ne 0 ]; then
    echo "V157_CHROOT_PREFLIGHT=FAIL"
    exit 1
fi

echo
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
echo "V157_CHROOT_TOKEN_ONLY_FETCH_RC=$FETCH_RC"
if [ "$FETCH_RC" -ne 0 ]; then
    fail "V157_CHROOT_TOKEN_ONLY_FETCH=FAIL"
fi

REMOTE_MAIN="$(git -C "$REPO" rev-parse refs/remotes/origin/main 2>/dev/null || true)"
REMOTE_BRANCH="$(git -C "$REPO" rev-parse "refs/remotes/origin/$BRANCH" 2>/dev/null || true)"

echo "V157_CHROOT_REMOTE_MAIN=$REMOTE_MAIN"
echo "V157_CHROOT_REMOTE_BRANCH=$REMOTE_BRANCH"

if [ "$REMOTE_MAIN" != "$BASE_MAIN" ]; then
    fail "V157_CHROOT_MAIN_IDENTITY=FAIL"
else
    echo "V157_CHROOT_MAIN_IDENTITY=PASS"
fi

if [ "$REMOTE_BRANCH" != "$RELEASE_SEED_SHA" ]; then
    fail "V157_CHROOT_BRANCH_SEED_IDENTITY=FAIL"
else
    echo "V157_CHROOT_BRANCH_SEED_IDENTITY=PASS"
fi

if ! git -C "$REPO" merge-base --is-ancestor "$BASE_MAIN" "$RELEASE_SEED_SHA"; then
    fail "V157_CHROOT_BASE_ANCESTOR=FAIL"
else
    echo "V157_CHROOT_BASE_ANCESTOR=PASS"
fi

if [ "$FAIL" -ne 0 ]; then
    echo "V157_CHROOT_PREFLIGHT=FAIL"
    exit 1
fi

mkdir -p "$RUN_ROOT" "$BUILD" "$ROOTFS"
chmod 700 "$RUN_ROOT" "$BUILD" "$ROOTFS"

if ! git -C "$REPO" worktree add --detach "$WT" "$RELEASE_SEED_SHA" >/dev/null; then
    fail "V157_CHROOT_WORKTREE_CREATE=FAIL"
else
    echo "V157_CHROOT_WORKTREE_CREATE=PASS"
fi

if [ "$FAIL" -ne 0 ]; then
    exit 1
fi

GRACEFUL_SOURCE="$WT/$GRACEFUL_SOURCE_REL"
FROZEN_SOURCE="$WT/$FROZEN_V153_SOURCE_REL"
TRANSFORM="$WT/$TRANSFORM_REL"
BINARY="$WT/$BINARY_REL"
VENDORED_LIBNICE="$WT/$VENDORED_LIBNICE_REL"
MANIFEST="$WT/$MANIFEST_REL"
RELEASE_DIR="$WT/$RELEASE_DIR_REL"
RELEASE_SOURCE="$WT/$RELEASE_SOURCE_REL"
BUILD_INFO="$WT/$BUILD_INFO_REL"
RELEASE_TEST="$WT/$RELEASE_TEST_REL"

ACTUAL_GRACEFUL_SHA="$(sha256sum "$GRACEFUL_SOURCE" | awk '{print $1}')"
ACTUAL_FROZEN_SHA="$(sha256sum "$FROZEN_SOURCE" | awk '{print $1}')"
ACTUAL_TRANSFORM_SHA="$(sha256sum "$TRANSFORM" | awk '{print $1}')"
CURRENT_BINARY_SHA="$(sha256sum "$BINARY" | awk '{print $1}')"

echo "V157_CHROOT_GRACEFUL_SOURCE_SHA256=$ACTUAL_GRACEFUL_SHA"
echo "V157_CHROOT_FROZEN_SOURCE_SHA256=$ACTUAL_FROZEN_SHA"
echo "V157_CHROOT_TRANSFORM_SHA256=$ACTUAL_TRANSFORM_SHA"
echo "V157_CHROOT_CURRENT_BINARY_SHA256=$CURRENT_BINARY_SHA"

[ "$ACTUAL_GRACEFUL_SHA" = "$GRACEFUL_SOURCE_SHA" ] || fail "V157_CHROOT_GRACEFUL_SOURCE_GATE=FAIL"
[ "$ACTUAL_FROZEN_SHA" = "$FROZEN_V153_SOURCE_SHA" ] || fail "V157_CHROOT_FROZEN_SOURCE_GATE=FAIL"
[ "$ACTUAL_TRANSFORM_SHA" = "$TRANSFORM_SHA" ] || fail "V157_CHROOT_TRANSFORM_GATE=FAIL"
[ "$CURRENT_BINARY_SHA" = "$CURRENT_V156_BINARY_SHA" ] || fail "V157_CHROOT_CURRENT_BINARY_GATE=FAIL"

if strings -a "$VENDORED_LIBNICE" | grep -Fxq 'pseudo_tcp_socket_close'; then
    echo "V157_CHROOT_VENDORED_LIBNICE_CLOSE_SYMBOL=PASS"
else
    fail "V157_CHROOT_VENDORED_LIBNICE_CLOSE_SYMBOL=FAIL"
fi

if [ "$FAIL" -ne 0 ]; then
    exit 1
fi

echo "V157_CHROOT_SOURCE_IDENTITY=PASS"

echo
echo "=== OFFICIAL ALPINE MINIROOTFS DOWNLOAD ==="

python3 - "$ALPINE_ROOTFS_URL" "$ARCHIVE" "$ALPINE_ROOTFS_SHA256_URL" "$SHA_FILE" <<'PY'
from pathlib import Path
import sys
import urllib.parse
import urllib.request

pairs = ((sys.argv[1], Path(sys.argv[2])), (sys.argv[3], Path(sys.argv[4])))
for url, target in pairs:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != "dl-cdn.alpinelinux.org":
        raise SystemExit(f"refusing non-official Alpine URL: {url}")
    with urllib.request.urlopen(url, timeout=60) as response:
        if response.status != 200:
            raise SystemExit(f"download failed: {url} status={response.status}")
        target.write_bytes(response.read())
PY
DOWNLOAD_RC=$?
echo "V157_CHROOT_ALPINE_DOWNLOAD_RC=$DOWNLOAD_RC"
if [ "$DOWNLOAD_RC" -ne 0 ]; then
    fail "V157_CHROOT_ALPINE_DOWNLOAD=FAIL"
fi

if [ "$FAIL" -ne 0 ]; then
    exit 1
fi

CHECKSUM_HASH="$(awk 'NF >= 2 {print $1; exit}' "$SHA_FILE")"
CHECKSUM_NAME="$(awk 'NF >= 2 {print $2; exit}' "$SHA_FILE")"
CHECKSUM_NAME="${CHECKSUM_NAME#\*}"
ACTUAL_ARCHIVE_SHA="$(sha256sum "$ARCHIVE" | awk '{print $1}')"

echo "V157_CHROOT_ALPINE_CHECKSUM_NAME=$CHECKSUM_NAME"
echo "V157_CHROOT_ALPINE_CHECKSUM_SHA256=$CHECKSUM_HASH"
echo "V157_CHROOT_ALPINE_ARCHIVE_SHA256=$ACTUAL_ARCHIVE_SHA"

if [ "$CHECKSUM_NAME" != "$ALPINE_ROOTFS_NAME" ]; then
    fail "V157_CHROOT_ALPINE_CHECKSUM_NAME_GATE=FAIL"
else
    echo "V157_CHROOT_ALPINE_CHECKSUM_NAME_GATE=PASS"
fi

if [ "$CHECKSUM_HASH" != "$ACTUAL_ARCHIVE_SHA" ] || [ ${#CHECKSUM_HASH} -ne 64 ]; then
    fail "V157_CHROOT_ALPINE_CHECKSUM_GATE=FAIL"
else
    echo "V157_CHROOT_ALPINE_CHECKSUM_GATE=PASS"
fi

if [ "$FAIL" -ne 0 ]; then
    exit 1
fi

tar -xzf "$ARCHIVE" -C "$ROOTFS"
EXTRACT_RC=$?
echo "V157_CHROOT_ALPINE_EXTRACT_RC=$EXTRACT_RC"
if [ "$EXTRACT_RC" -ne 0 ]; then
    fail "V157_CHROOT_ALPINE_EXTRACT=FAIL"
fi

if [ ! -f "$ROOTFS/etc/alpine-release" ]; then
    fail "V157_CHROOT_ALPINE_RELEASE_FILE=FAIL"
else
    ROOTFS_VERSION="$(cat "$ROOTFS/etc/alpine-release")"
    echo "V157_CHROOT_ALPINE_ROOTFS_VERSION=$ROOTFS_VERSION"
    if [ "$ROOTFS_VERSION" != "$ALPINE_VERSION_EXPECTED" ]; then
        fail "V157_CHROOT_ALPINE_VERSION_GATE=FAIL"
    else
        echo "V157_CHROOT_ALPINE_VERSION_GATE=PASS"
    fi
fi

if [ "$FAIL" -ne 0 ]; then
    exit 1
fi

rm -f "$ROOTFS/etc/resolv.conf"
cp /etc/resolv.conf "$ROOTFS/etc/resolv.conf"
mkdir -p "$ROOTFS/src" "$ROOTFS/out"
cp "$GRACEFUL_SOURCE" "$ROOTFS/src/comelit-v4-persistent-ctpp-door.c"
chmod 600 "$ROOTFS/src/comelit-v4-persistent-ctpp-door.c"

echo
echo "=== ALPINE CHROOT BUILD ==="

chroot "$ROOTFS" /bin/sh -eu -c '
    apk add --no-cache \
      build-base \
      pkgconf \
      glib-dev \
      libnice-dev \
      file \
      binutils

    ALPINE_VERSION="$(cat /etc/alpine-release)"
    CC_VERSION="$(cc --version | head -n1)"
    NICE_VERSION="$(pkg-config --modversion nice)"
    GLIB_VERSION="$(pkg-config --modversion glib-2.0)"

    cc \
      -O2 \
      -g \
      -Wall \
      -Wextra \
      -Wl,--as-needed \
      -o /out/comelit-v4 \
      /src/comelit-v4-persistent-ctpp-door.c \
      $(pkg-config --cflags --libs nice glib-2.0 gio-2.0 gobject-2.0)

    chmod 755 /out/comelit-v4

    INTERPRETER="$(readelf -l /out/comelit-v4 | sed -n "s@.*Requesting program interpreter: \(.*\)]@\1@p")"
    NEEDED="$(readelf -d /out/comelit-v4 | sed -n "s/.*Shared library: \[\(.*\)\]/\1/p" | sort | paste -sd, -)"

    {
      echo "alpine_version=$ALPINE_VERSION"
      echo "cc_version=$CC_VERSION"
      echo "libnice_version=$NICE_VERSION"
      echo "glib_version=$GLIB_VERSION"
      echo "interpreter=$INTERPRETER"
      echo "needed_sorted=$NEEDED"
      echo "candidate_executed=false"
    } > /out/alpine-build-meta.txt
'
BUILD_RC=$?
echo "V157_CHROOT_ALPINE_BUILD_RC=$BUILD_RC"
if [ "$BUILD_RC" -ne 0 ]; then
    fail "V157_CHROOT_ALPINE_BUILD=FAIL"
fi

if [ "$FAIL" -ne 0 ]; then
    exit 1
fi

cp "$ROOTFS/out/comelit-v4" "$CANDIDATE"
cp "$ROOTFS/out/alpine-build-meta.txt" "$META"
chmod 755 "$CANDIDATE"

cat "$META"

ALPINE_VERSION="$(sed -n 's/^alpine_version=//p' "$META")"
LIBNICE_VERSION="$(sed -n 's/^libnice_version=//p' "$META")"
GLIB_VERSION="$(sed -n 's/^glib_version=//p' "$META")"
INTERPRETER="$(sed -n 's/^interpreter=//p' "$META")"
NEEDED_SORTED="$(sed -n 's/^needed_sorted=//p' "$META")"

[ "$ALPINE_VERSION" = "$ALPINE_VERSION_EXPECTED" ] || fail "V157_CHROOT_ALPINE_VERSION_POSTBUILD_GATE=FAIL"
[ "$LIBNICE_VERSION" = "$EXPECTED_LIBNICE" ] || fail "V157_CHROOT_LIBNICE_GATE=FAIL expected=$EXPECTED_LIBNICE actual=$LIBNICE_VERSION"
[ "$GLIB_VERSION" = "$EXPECTED_GLIB" ] || fail "V157_CHROOT_GLIB_GATE=FAIL expected=$EXPECTED_GLIB actual=$GLIB_VERSION"
[ "$INTERPRETER" = "$EXPECTED_INTERPRETER" ] || fail "V157_CHROOT_INTERPRETER_GATE=FAIL actual=$INTERPRETER"
[ "$NEEDED_SORTED" = "$EXPECTED_DIRECT_NEEDED_SORTED" ] || fail "V157_CHROOT_NEEDED_GATE=FAIL actual=$NEEDED_SORTED"

if [ "$FAIL" -eq 0 ]; then
    echo "V157_CHROOT_LIBNICE_GATE=PASS $LIBNICE_VERSION"
    echo "V157_CHROOT_GLIB_GATE=PASS $GLIB_VERSION"
    echo "V157_CHROOT_INTERPRETER_GATE=PASS $INTERPRETER"
    echo "V157_CHROOT_NEEDED_GATE=PASS $NEEDED_SORTED"
fi

file "$CANDIDATE" | sed 's#^.*: #V157_CHROOT_BINARY_FILE=#'
strings -a "$CANDIDATE" > "$BUILD/candidate.strings"
STRINGS_RC=$?
echo "V157_CHROOT_STRINGS_RC=$STRINGS_RC"
if [ "$STRINGS_RC" -ne 0 ]; then
    fail "V157_CHROOT_STRINGS=FAIL"
fi

for marker in \
  "$EXPECTED_INTERPRETER" \
  'PSEUDOTCP_GRACEFUL_CLOSE_REQUESTED=true' \
  'PSEUDOTCP_GRACEFUL_CLOSE_FORCE=false' \
  'PSEUDOTCP_GRACEFUL_CLOSE_FORCE_RST_SENT=false' \
  'PSEUDOTCP_GRACEFUL_CLOSE_COMPLETE=true' \
  'V4_DOOR_EXISTING_CTPP_REUSED=true' \
  'V4_DOOR_OPERATION_WRITES_SENT=5' \
  'V4_DOOR_AUTOMATIC_RETRY_ALLOWED=false' \
  'V4_DOOR_PHYSICAL_EFFECT_ASSERTED=false'
do
    if grep -Fq "$marker" "$BUILD/candidate.strings"; then
        echo "V157_CHROOT_BINARY_MARKER=PASS $marker"
    else
        fail "V157_CHROOT_BINARY_MARKER=FAIL $marker"
    fi
done

if grep -Fq '/lib64/ld-linux-x86-64.so.2' "$BUILD/candidate.strings"; then
    fail "V157_CHROOT_GLIBC_INTERPRETER_GATE=FAIL"
else
    echo "V157_CHROOT_GLIBC_INTERPRETER_GATE=PASS"
fi

if grep -Fq 'PSEUDOTCP_GRACEFUL_CLOSE_FORCE=true' "$BUILD/candidate.strings"; then
    fail "V157_CHROOT_FORCE_CLOSE_GATE=FAIL"
else
    echo "V157_CHROOT_FORCE_CLOSE_GATE=PASS"
fi

if [ "$FAIL" -ne 0 ]; then
    exit 1
fi

CANDIDATE_SHA="$(sha256sum "$CANDIDATE" | awk '{print $1}')"
echo "V157_CHROOT_BINARY_SHA256=$CANDIDATE_SHA"

if [ "$CANDIDATE_SHA" = "$CURRENT_BINARY_SHA" ]; then
    fail "V157_CHROOT_BINARY_CHANGED_GATE=FAIL"
else
    echo "V157_CHROOT_BINARY_CHANGED_GATE=PASS"
fi

if [ "$FAIL" -ne 0 ]; then
    exit 1
fi

mkdir -p "$RELEASE_DIR"
cp "$GRACEFUL_SOURCE" "$RELEASE_SOURCE"
cp "$CANDIDATE" "$BINARY"
chmod 755 "$BINARY"

python3 - "$MANIFEST" <<'PY'
import json
from pathlib import Path
import sys

path = Path(sys.argv[1])
data = json.loads(path.read_text(encoding="utf-8"))
if data.get("version") != "1.5.6":
    raise SystemExit(f"unexpected current manifest version: {data.get('version')!r}")
data["version"] = "1.5.7"
path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
PY
MANIFEST_RC=$?
echo "V157_CHROOT_MANIFEST_UPDATE_RC=$MANIFEST_RC"
if [ "$MANIFEST_RC" -ne 0 ]; then
    fail "V157_CHROOT_MANIFEST_UPDATE=FAIL"
fi

cat > "$BUILD_INFO" <<EOF
release=1.5.7
base_main=$BASE_MAIN
release_seed=$RELEASE_SEED_SHA
source_sha256=$GRACEFUL_SOURCE_SHA
binary_sha256=$CANDIDATE_SHA
build_environment=Alpine $ALPINE_VERSION minirootfs chroot
alpine_rootfs_url=$ALPINE_ROOTFS_URL
alpine_rootfs_sha256=$ACTUAL_ARCHIVE_SHA
libnice_version=$LIBNICE_VERSION
glib_version=$GLIB_VERSION
interpreter=$INTERPRETER
needed_sorted=$NEEDED_SORTED
replaces_v1_5_6_binary_sha256=$CURRENT_BINARY_SHA
pseudotcp_graceful_close=true
pseudotcp_graceful_close_force=false
pseudotcp_graceful_close_force_rst_sent=false
graceful_close_timeout_ms=5000
door_contract_source=frozen_v1_5_3_transform_only
automatic_retry_allowed=false
physical_effect_asserted=false
candidate_executed=false
comelit_network_session_started=false
EOF
chmod 644 "$BUILD_INFO"

cat > "$RELEASE_TEST" <<EOF
import hashlib
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
EXPECTED_SOURCE_SHA = "$GRACEFUL_SOURCE_SHA"
EXPECTED_BINARY_SHA = "$CANDIDATE_SHA"
EXPECTED_PREVIOUS_BINARY_SHA = "$CURRENT_BINARY_SHA"
EXPECTED_ROOTFS_SHA = "$ACTUAL_ARCHIVE_SHA"
EXPECTED_INTERPRETER = b"$EXPECTED_INTERPRETER"
FORBIDDEN_INTERPRETER = b"/lib64/ld-linux-x86-64.so.2"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class P29HaosGracefulStopReleaseContract(unittest.TestCase):
    def test_manifest_is_1_5_7(self):
        manifest = json.loads(
            (ROOT / "custom_components/comelit/manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["version"], "1.5.7")

    def test_release_source_and_binary_hashes_are_frozen(self):
        source = ROOT / "$RELEASE_SOURCE_REL"
        binary = ROOT / "$BINARY_REL"
        self.assertEqual(sha256(source), EXPECTED_SOURCE_SHA)
        self.assertEqual(sha256(binary), EXPECTED_BINARY_SHA)
        self.assertNotEqual(EXPECTED_BINARY_SHA, EXPECTED_PREVIOUS_BINARY_SHA)

    def test_production_binary_is_musl_not_glibc(self):
        binary = (ROOT / "$BINARY_REL").read_bytes()
        self.assertIn(EXPECTED_INTERPRETER, binary)
        self.assertNotIn(FORBIDDEN_INTERPRETER, binary)

    def test_graceful_and_door_safety_markers_remain_in_binary(self):
        binary = (ROOT / "$BINARY_REL").read_bytes()
        for marker in (
            b"PSEUDOTCP_GRACEFUL_CLOSE_REQUESTED=true",
            b"PSEUDOTCP_GRACEFUL_CLOSE_FORCE=false",
            b"PSEUDOTCP_GRACEFUL_CLOSE_FORCE_RST_SENT=false",
            b"PSEUDOTCP_GRACEFUL_CLOSE_COMPLETE=true",
            b"V4_DOOR_EXISTING_CTPP_REUSED=true",
            b"V4_DOOR_OPERATION_WRITES_SENT=5",
            b"V4_DOOR_AUTOMATIC_RETRY_ALLOWED=false",
            b"V4_DOOR_PHYSICAL_EFFECT_ASSERTED=false",
        ):
            self.assertIn(marker, binary)
        self.assertNotIn(b"PSEUDOTCP_GRACEFUL_CLOSE_FORCE=true", binary)

    def test_build_info_binds_haos_compatibility_and_rootfs(self):
        text = (ROOT / "$BUILD_INFO_REL").read_text(encoding="utf-8")
        for marker in (
            "release=1.5.7",
            "source_sha256=" + EXPECTED_SOURCE_SHA,
            "binary_sha256=" + EXPECTED_BINARY_SHA,
            "build_environment=Alpine 3.24.1 minirootfs chroot",
            "alpine_rootfs_sha256=" + EXPECTED_ROOTFS_SHA,
            "libnice_version=0.1.22",
            "glib_version=2.88.1",
            "interpreter=/lib/ld-musl-x86_64.so.1",
            "pseudotcp_graceful_close=true",
            "pseudotcp_graceful_close_force=false",
            "automatic_retry_allowed=false",
            "physical_effect_asserted=false",
            "candidate_executed=false",
            "comelit_network_session_started=false",
        ):
            self.assertIn(marker, text)


if __name__ == "__main__":
    unittest.main()
EOF

python3 -m py_compile "$RELEASE_TEST"
TEST_PARSE_RC=$?
echo "V157_CHROOT_RELEASE_TEST_PARSE_RC=$TEST_PARSE_RC"
if [ "$TEST_PARSE_RC" -ne 0 ]; then
    fail "V157_CHROOT_RELEASE_TEST_PARSE=FAIL"
fi

(
  cd "$WT" &&
  PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=safety-poc/src \
    python3 -m unittest discover -s safety-poc/tests -v
) 2>&1 | tee "$RUN_ROOT/repository-tests.log"
TEST_RC=${PIPESTATUS[0]}
echo "V157_CHROOT_REPOSITORY_TEST_RC=$TEST_RC"
if [ "$TEST_RC" -ne 0 ]; then
    fail "V157_CHROOT_REPOSITORY_TEST=FAIL"
fi

if [ "$FAIL" -ne 0 ]; then
    exit 1
fi

git -C "$WT" add \
  "$BINARY_REL" \
  "$MANIFEST_REL" \
  "$RELEASE_DIR_REL" \
  "$RELEASE_TEST_REL"

if git -C "$WT" diff --cached --quiet; then
    fail "V157_CHROOT_STAGED_DIFF=EMPTY"
fi

STAGED_PATHS="$(git -C "$WT" diff --cached --name-only | sort)"
echo "V157_CHROOT_STAGED_PATHS_BEGIN"
printf '%s\n' "$STAGED_PATHS"
echo "V157_CHROOT_STAGED_PATHS_END"

EXPECTED_PATHS="$(printf '%s\n' \
  "$BINARY_REL" \
  "$MANIFEST_REL" \
  "$BUILD_INFO_REL" \
  "$RELEASE_SOURCE_REL" \
  "$RELEASE_TEST_REL" | sort)"

if [ "$STAGED_PATHS" != "$EXPECTED_PATHS" ]; then
    fail "V157_CHROOT_STAGED_PATH_GATE=FAIL"
else
    echo "V157_CHROOT_STAGED_PATH_GATE=PASS"
fi

if [ "$FAIL" -ne 0 ]; then
    exit 1
fi

if [ -z "$(git -C "$WT" config user.name)" ]; then
    git -C "$WT" config user.name "alexsudakov"
fi
if [ -z "$(git -C "$WT" config user.email)" ]; then
    git -C "$WT" config user.email "91778685+alexsudakov@users.noreply.github.com"
fi

git -C "$WT" commit -m "fix(comelit): ship HAOS-musl graceful PseudoTCP close"
COMMIT_RC=$?
echo "V157_CHROOT_COMMIT_RC=$COMMIT_RC"
if [ "$COMMIT_RC" -ne 0 ]; then
    fail "V157_CHROOT_COMMIT=FAIL"
fi

if [ "$FAIL" -ne 0 ]; then
    exit 1
fi

RELEASE_COMMIT="$(git -C "$WT" rev-parse HEAD)"
echo "V157_CHROOT_RELEASE_COMMIT=$RELEASE_COMMIT"
echo "V157_CHROOT_MANIFEST_VERSION=1.5.7"
echo "V157_CHROOT_SOURCE_SHA256=$GRACEFUL_SOURCE_SHA"
echo "V157_CHROOT_BINARY_SHA256=$CANDIDATE_SHA"
echo "V157_CHROOT_INTERPRETER=$INTERPRETER"
echo "V157_CHROOT_LIBNICE_VERSION=$LIBNICE_VERSION"
echo "V157_CHROOT_GLIB_VERSION=$GLIB_VERSION"

GIT_TERMINAL_PROMPT=0 \
git -C "$WT" \
  -c credential.helper= \
  -c "credential.helper=store --file=$CREDS" \
  -c credential.useHttpPath=true \
  push origin "HEAD:refs/heads/$BRANCH"
PUSH_RC=$?
echo "V157_CHROOT_TOKEN_ONLY_PUSH_RC=$PUSH_RC"
if [ "$PUSH_RC" -ne 0 ]; then
    fail "V157_CHROOT_TOKEN_ONLY_PUSH=FAIL"
fi

if [ "$FAIL" -ne 0 ]; then
    exit 1
fi

echo "V157_CHROOT_RELEASE_PREPARE=PASS"
echo "CANDIDATE_EXECUTED=false"
echo "COMELIT_NETWORK_SESSION_STARTED=false"
echo "HOME_ASSISTANT_TOUCHED=false"
echo "DOOR_ACTION_SENT=false"
echo "SELF_ACTIVATION_SENT=false"
echo "MEDIA_SIGNALING_SENT=false"
exit 0
