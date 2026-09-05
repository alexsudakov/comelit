#!/usr/bin/env bash
# Reviewed CT120 builder for Comelit v1.5.7.
# Build-only: it never executes the candidate or contacts Comelit/HA.

set -u -o pipefail
umask 077

REPO=/root/comelit-door-diag-repo
CREDS=/root/.config/git/comelit.credentials
BRANCH=fix/graceful-pseudotcp-stop-haos-v1-5-7
BASE_MAIN=c9dc9ad0b1fb2ae4701340437edc9d2ff93b81ea
ALPINE_IMAGE=alpine:3.24.1
EXPECTED_ARCH=x86_64
EXPECTED_LIBNICE=0.1.22
EXPECTED_GLIB=2.88.1
EXPECTED_INTERPRETER=/lib/ld-musl-x86_64.so.1
EXPECTED_NEEDED_SORTED='libc.musl-x86_64.so.1,libglib-2.0.so.0,libgobject-2.0.so.0,libnice.so.10'

GRACEFUL_SOURCE_REL=safety-poc/research/door/v1_5_5/comelit-v4-persistent-ctpp-door.c
GRACEFUL_SOURCE_SHA=5827d9fd043b85fc0c59a31661a1a125c6b239771e2a70c3e5afdd95f1a03c73
FROZEN_V153_SOURCE_REL=safety-poc/research/door/v1_5_3/comelit-v4-persistent-ctpp-door.c
FROZEN_V153_SOURCE_SHA=088e0e23c07404792254f5c18e3f12dbbd499a676bda2d3883988d1d9bb3be6f
CURRENT_V156_BINARY_SHA=c171e7d1d342d059858f0cfca4f81dc8a07679f1d18992718bec2d6ead84db86
TRANSFORM_REL=safety-poc/research/media/v1/pseudotcp_graceful_stop_transform.py
TRANSFORM_SHA=b98e3f774054934421d7fda71e8c28aa89e9383adefe170221b00aa6184cbb6f

BINARY_REL=custom_components/comelit/native/comelit-v4
MANIFEST_REL=custom_components/comelit/manifest.json
RELEASE_DIR_REL=safety-poc/research/door/v1_5_7
RELEASE_SOURCE_REL=$RELEASE_DIR_REL/comelit-v4-persistent-ctpp-door.c
BUILD_INFO_REL=$RELEASE_DIR_REL/BUILD_INFO.txt
RELEASE_TEST_REL=safety-poc/tests/test_p29_haos_graceful_stop_release_contract.py
OLD_BUILDER_REL=safety-poc/research/media/v1/ct120_prepare_haos_graceful_stop_v1_5_7.sh

FAIL=0
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
RUN_ROOT="/root/comelit-v1-5-7-release-$STAMP"
WT="$RUN_ROOT/repo"
BUILD="$RUN_ROOT/build"
CANDIDATE="$BUILD/comelit-v4"
META="$BUILD/alpine-build-meta.txt"
CONTAINER_RUNTIME=""

fail() { echo "$1"; FAIL=1; }

cleanup() {
    if [ -e "$WT/.git" ]; then
        git -C "$REPO" worktree remove --force "$WT" >/dev/null 2>&1 \
          && echo "V157_RELEASE_WORKTREE_CLEANUP=PASS" \
          || echo "V157_RELEASE_WORKTREE_CLEANUP=WARNING"
    fi
}
trap cleanup EXIT

[ "${EUID}" -eq 0 ] || { echo "V157_RELEASE_REQUIRES_ROOT=true"; exit 1; }
[ -n "${RELEASE_SEED_SHA:-}" ] || { echo "V157_RELEASE_SEED_PRESENT=false"; exit 1; }
echo "V157_RELEASE_SEED_SHA=$RELEASE_SEED_SHA"

for command in git python3 sha256sum strings file awk grep sed sort paste uname; do
    command -v "$command" >/dev/null 2>&1 || fail "V157_RELEASE_MISSING_COMMAND=$command"
done

if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
    CONTAINER_RUNTIME=docker
elif command -v podman >/dev/null 2>&1 && podman info >/dev/null 2>&1; then
    CONTAINER_RUNTIME=podman
else
    fail "V157_RELEASE_CONTAINER_RUNTIME=FAIL"
fi
[ -z "$CONTAINER_RUNTIME" ] || echo "V157_RELEASE_CONTAINER_RUNTIME=$CONTAINER_RUNTIME"

[ "$(uname -m)" = "$EXPECTED_ARCH" ] \
  && echo "V157_RELEASE_HOST_ARCH=PASS $EXPECTED_ARCH" \
  || fail "V157_RELEASE_HOST_ARCH=FAIL"

[ -d "$REPO/.git" ] || fail "V157_RELEASE_REPO_PRESENT=false"
if [ -f "$CREDS" ]; then
    MODE="$(stat -c '%a' "$CREDS")"
    echo "V157_RELEASE_TOKEN_CREDENTIAL_MODE=$MODE"
    [ "$MODE" = 600 ] \
      && echo "V157_RELEASE_TOKEN_CREDENTIAL_GATE=PASS" \
      || fail "V157_RELEASE_TOKEN_CREDENTIAL_GATE=FAIL"
else
    fail "V157_RELEASE_TOKEN_CREDENTIAL_PRESENT=false"
fi

[ "$FAIL" -eq 0 ] || { echo "V157_RELEASE_PREFLIGHT=FAIL"; exit 1; }

REMOTE_MAIN="$(git -C "$REPO" rev-parse refs/remotes/origin/main)"
REMOTE_BRANCH="$(git -C "$REPO" rev-parse "refs/remotes/origin/$BRANCH")"
echo "V157_RELEASE_REMOTE_MAIN=$REMOTE_MAIN"
echo "V157_RELEASE_REMOTE_BRANCH=$REMOTE_BRANCH"

[ "$REMOTE_MAIN" = "$BASE_MAIN" ] \
  && echo "V157_RELEASE_MAIN_IDENTITY=PASS" \
  || fail "V157_RELEASE_MAIN_IDENTITY=FAIL"
[ "$REMOTE_BRANCH" = "$RELEASE_SEED_SHA" ] \
  && echo "V157_RELEASE_BRANCH_SEED_IDENTITY=PASS" \
  || fail "V157_RELEASE_BRANCH_SEED_IDENTITY=FAIL"
git -C "$REPO" merge-base --is-ancestor "$BASE_MAIN" "$RELEASE_SEED_SHA" \
  && echo "V157_RELEASE_BASE_ANCESTOR=PASS" \
  || fail "V157_RELEASE_BASE_ANCESTOR=FAIL"

[ "$FAIL" -eq 0 ] || { echo "V157_RELEASE_PREFLIGHT=FAIL"; exit 1; }

mkdir -p "$BUILD"
chmod 700 "$RUN_ROOT" "$BUILD"
git -C "$REPO" worktree add --detach "$WT" "$RELEASE_SEED_SHA" >/dev/null \
  && echo "V157_RELEASE_WORKTREE_CREATE=PASS" \
  || fail "V157_RELEASE_WORKTREE_CREATE=FAIL"
[ "$FAIL" -eq 0 ] || exit 1

GRACEFUL_SOURCE="$WT/$GRACEFUL_SOURCE_REL"
FROZEN_SOURCE="$WT/$FROZEN_V153_SOURCE_REL"
TRANSFORM="$WT/$TRANSFORM_REL"
BINARY="$WT/$BINARY_REL"
MANIFEST="$WT/$MANIFEST_REL"
RELEASE_DIR="$WT/$RELEASE_DIR_REL"
RELEASE_SOURCE="$WT/$RELEASE_SOURCE_REL"
BUILD_INFO="$WT/$BUILD_INFO_REL"
RELEASE_TEST="$WT/$RELEASE_TEST_REL"

ACTUAL_GRACEFUL_SHA="$(sha256sum "$GRACEFUL_SOURCE" | awk '{print $1}')"
ACTUAL_FROZEN_SHA="$(sha256sum "$FROZEN_SOURCE" | awk '{print $1}')"
ACTUAL_TRANSFORM_SHA="$(sha256sum "$TRANSFORM" | awk '{print $1}')"
CURRENT_BINARY_SHA="$(sha256sum "$BINARY" | awk '{print $1}')"
echo "V157_RELEASE_GRACEFUL_SOURCE_SHA256=$ACTUAL_GRACEFUL_SHA"
echo "V157_RELEASE_FROZEN_SOURCE_SHA256=$ACTUAL_FROZEN_SHA"
echo "V157_RELEASE_TRANSFORM_SHA256=$ACTUAL_TRANSFORM_SHA"
echo "V157_RELEASE_CURRENT_BINARY_SHA256=$CURRENT_BINARY_SHA"

[ "$ACTUAL_GRACEFUL_SHA" = "$GRACEFUL_SOURCE_SHA" ] || fail "V157_RELEASE_GRACEFUL_SOURCE_GATE=FAIL"
[ "$ACTUAL_FROZEN_SHA" = "$FROZEN_V153_SOURCE_SHA" ] || fail "V157_RELEASE_FROZEN_SOURCE_GATE=FAIL"
[ "$ACTUAL_TRANSFORM_SHA" = "$TRANSFORM_SHA" ] || fail "V157_RELEASE_TRANSFORM_GATE=FAIL"
[ "$CURRENT_BINARY_SHA" = "$CURRENT_V156_BINARY_SHA" ] || fail "V157_RELEASE_CURRENT_BINARY_GATE=FAIL"
[ "$FAIL" -eq 0 ] || exit 1
echo "V157_RELEASE_SOURCE_IDENTITY=PASS"

echo
echo "=== ALPINE/MUSL BUILD ==="
"$CONTAINER_RUNTIME" run --rm \
  --network bridge \
  -v "$WT:/src:ro" \
  -v "$BUILD:/out" \
  "$ALPINE_IMAGE" \
  /bin/sh -eu -c '
    apk add --no-cache build-base pkgconf glib-dev libnice-dev file binutils >/dev/null
    ALPINE_VERSION="$(cat /etc/alpine-release)"
    CC_VERSION="$(cc --version | head -n1)"
    NICE_VERSION="$(pkg-config --modversion nice)"
    GLIB_VERSION="$(pkg-config --modversion glib-2.0)"

    cc -O2 -g -Wall -Wextra -Wl,--as-needed \
      -o /out/comelit-v4 \
      /src/safety-poc/research/door/v1_5_5/comelit-v4-persistent-ctpp-door.c \
      $(pkg-config --cflags --libs nice glib-2.0 gio-2.0 gobject-2.0)
    chmod 755 /out/comelit-v4

    INTERPRETER="$(readelf -l /out/comelit-v4 | sed -n "s@.*Requesting program interpreter: \(.*\)]@\1@p")"
    NEEDED_SORTED="$(readelf -d /out/comelit-v4 | sed -n "s/.*Shared library: \[\(.*\)\]/\1/p" | sort | paste -sd, -)"
    {
      echo "alpine_version=$ALPINE_VERSION"
      echo "cc_version=$CC_VERSION"
      echo "libnice_version=$NICE_VERSION"
      echo "glib_version=$GLIB_VERSION"
      echo "interpreter=$INTERPRETER"
      echo "needed_sorted=$NEEDED_SORTED"
      echo "candidate_executed=false"
    } > /out/alpine-build-meta.txt
  '
BUILD_RC=$?
echo "V157_RELEASE_ALPINE_BUILD_RC=$BUILD_RC"
[ "$BUILD_RC" -eq 0 ] || fail "V157_RELEASE_ALPINE_BUILD=FAIL"
[ "$FAIL" -eq 0 ] || exit 1

cat "$META"
ALPINE_VERSION="$(sed -n 's/^alpine_version=//p' "$META")"
LIBNICE_VERSION="$(sed -n 's/^libnice_version=//p' "$META")"
GLIB_VERSION="$(sed -n 's/^glib_version=//p' "$META")"
INTERPRETER="$(sed -n 's/^interpreter=//p' "$META")"
NEEDED_SORTED="$(sed -n 's/^needed_sorted=//p' "$META")"

[ "$ALPINE_VERSION" = 3.24.1 ] \
  && echo "V157_RELEASE_ALPINE_VERSION_GATE=PASS" \
  || fail "V157_RELEASE_ALPINE_VERSION_GATE=FAIL actual=$ALPINE_VERSION"
[ "$LIBNICE_VERSION" = "$EXPECTED_LIBNICE" ] \
  && echo "V157_RELEASE_LIBNICE_GATE=PASS $LIBNICE_VERSION" \
  || fail "V157_RELEASE_LIBNICE_GATE=FAIL expected=$EXPECTED_LIBNICE actual=$LIBNICE_VERSION"
[ "$GLIB_VERSION" = "$EXPECTED_GLIB" ] \
  && echo "V157_RELEASE_GLIB_GATE=PASS $GLIB_VERSION" \
  || fail "V157_RELEASE_GLIB_GATE=FAIL expected=$EXPECTED_GLIB actual=$GLIB_VERSION"
[ "$INTERPRETER" = "$EXPECTED_INTERPRETER" ] \
  && echo "V157_RELEASE_INTERPRETER_GATE=PASS $INTERPRETER" \
  || fail "V157_RELEASE_INTERPRETER_GATE=FAIL actual=$INTERPRETER"
[ "$NEEDED_SORTED" = "$EXPECTED_NEEDED_SORTED" ] \
  && echo "V157_RELEASE_NEEDED_GATE=PASS $NEEDED_SORTED" \
  || fail "V157_RELEASE_NEEDED_GATE=FAIL actual=$NEEDED_SORTED"

file "$CANDIDATE" | sed 's#^.*: #V157_RELEASE_BINARY_FILE=#'
strings -a "$CANDIDATE" > "$BUILD/candidate.strings"
[ $? -eq 0 ] && echo "V157_RELEASE_STRINGS_RC=0" || fail "V157_RELEASE_STRINGS=FAIL"

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
    grep -Fq "$marker" "$BUILD/candidate.strings" \
      && echo "V157_RELEASE_BINARY_MARKER=PASS $marker" \
      || fail "V157_RELEASE_BINARY_MARKER=FAIL $marker"
done

grep -Fq '/lib64/ld-linux-x86-64.so.2' "$BUILD/candidate.strings" \
  && fail "V157_RELEASE_GLIBC_INTERPRETER_GATE=FAIL" \
  || echo "V157_RELEASE_GLIBC_INTERPRETER_GATE=PASS"
grep -Fq 'PSEUDOTCP_GRACEFUL_CLOSE_FORCE=true' "$BUILD/candidate.strings" \
  && fail "V157_RELEASE_FORCE_CLOSE_GATE=FAIL" \
  || echo "V157_RELEASE_FORCE_CLOSE_GATE=PASS"
[ "$FAIL" -eq 0 ] || exit 1

CANDIDATE_SHA="$(sha256sum "$CANDIDATE" | awk '{print $1}')"
echo "V157_RELEASE_BINARY_SHA256=$CANDIDATE_SHA"
[ "$CANDIDATE_SHA" != "$CURRENT_BINARY_SHA" ] \
  && echo "V157_RELEASE_BINARY_CHANGED_GATE=PASS" \
  || fail "V157_RELEASE_BINARY_CHANGED_GATE=FAIL"
[ "$FAIL" -eq 0 ] || exit 1

mkdir -p "$RELEASE_DIR"
cp "$GRACEFUL_SOURCE" "$RELEASE_SOURCE"
cp "$CANDIDATE" "$BINARY"
chmod 755 "$BINARY"

python3 - "$MANIFEST" <<'PY'
import json
from pathlib import Path
import sys
p = Path(sys.argv[1])
data = json.loads(p.read_text(encoding="utf-8"))
if data.get("version") != "1.5.6":
    raise SystemExit(f"unexpected current manifest version: {data.get('version')!r}")
data["version"] = "1.5.7"
p.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
PY
MANIFEST_RC=$?
echo "V157_RELEASE_MANIFEST_UPDATE_RC=$MANIFEST_RC"
[ "$MANIFEST_RC" -eq 0 ] || fail "V157_RELEASE_MANIFEST_UPDATE=FAIL"

cat > "$BUILD_INFO" <<EOF
release=1.5.7
base_main=$BASE_MAIN
release_seed=$RELEASE_SEED_SHA
source_sha256=$GRACEFUL_SOURCE_SHA
binary_sha256=$CANDIDATE_SHA
build_environment=Alpine $ALPINE_VERSION
container_image=$ALPINE_IMAGE
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
EXPECTED_INTERPRETER = b"$EXPECTED_INTERPRETER"
FORBIDDEN_INTERPRETER = b"/lib64/ld-linux-x86-64.so.2"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class P29HaosGracefulStopReleaseContract(unittest.TestCase):
    def test_manifest_is_1_5_7(self):
        data = json.loads((ROOT / "$MANIFEST_REL").read_text(encoding="utf-8"))
        self.assertEqual(data["version"], "1.5.7")

    def test_artifact_hashes_are_frozen(self):
        self.assertEqual(sha256(ROOT / "$RELEASE_SOURCE_REL"), EXPECTED_SOURCE_SHA)
        self.assertEqual(sha256(ROOT / "$BINARY_REL"), EXPECTED_BINARY_SHA)
        self.assertNotEqual(EXPECTED_BINARY_SHA, EXPECTED_PREVIOUS_BINARY_SHA)

    def test_binary_is_musl_and_keeps_safety_markers(self):
        binary = (ROOT / "$BINARY_REL").read_bytes()
        self.assertIn(EXPECTED_INTERPRETER, binary)
        self.assertNotIn(FORBIDDEN_INTERPRETER, binary)
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

    def test_build_info_binds_haos_compatibility(self):
        text = (ROOT / "$BUILD_INFO_REL").read_text(encoding="utf-8")
        for marker in (
            "release=1.5.7",
            "source_sha256=" + EXPECTED_SOURCE_SHA,
            "binary_sha256=" + EXPECTED_BINARY_SHA,
            "build_environment=Alpine 3.24.1",
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

[ "$FAIL" -eq 0 ] || exit 1
python3 -m py_compile "$RELEASE_TEST" || fail "V157_RELEASE_TEST_PARSE=FAIL"
(
  cd "$WT" || exit 99
  python3 -m unittest \
    safety-poc.tests.test_p29_haos_graceful_stop_release_contract
) 2>&1 | tee "$RUN_ROOT/release-test.log"
TEST_RC=${PIPESTATUS[0]}
echo "V157_RELEASE_CONTRACT_TEST_RC=$TEST_RC"
[ "$TEST_RC" -eq 0 ] || fail "V157_RELEASE_CONTRACT_TEST=FAIL"
[ "$FAIL" -eq 0 ] || exit 1

# Supersede the first builder draft so only the reviewed v2 remains after the
# artifact commit.
rm -f "$WT/$OLD_BUILDER_REL"

git -C "$WT" add \
  "$BINARY_REL" \
  "$MANIFEST_REL" \
  "$RELEASE_DIR_REL" \
  "$RELEASE_TEST_REL" \
  "$OLD_BUILDER_REL"

git -C "$WT" diff --cached --quiet && fail "V157_RELEASE_STAGED_DIFF=EMPTY"
[ "$FAIL" -eq 0 ] || exit 1

[ -n "$(git -C "$WT" config user.name)" ] || git -C "$WT" config user.name alexsudakov
[ -n "$(git -C "$WT" config user.email)" ] || git -C "$WT" config user.email 91778685+alexsudakov@users.noreply.github.com

git -C "$WT" commit -m "fix(comelit): ship HAOS-musl graceful PseudoTCP close"
COMMIT_RC=$?
echo "V157_RELEASE_COMMIT_RC=$COMMIT_RC"
[ "$COMMIT_RC" -eq 0 ] || fail "V157_RELEASE_COMMIT=FAIL"
[ "$FAIL" -eq 0 ] || exit 1

RELEASE_COMMIT="$(git -C "$WT" rev-parse HEAD)"
echo "V157_RELEASE_COMMIT=$RELEASE_COMMIT"
echo "V157_RELEASE_MANIFEST_VERSION=1.5.7"
echo "V157_RELEASE_SOURCE_SHA256=$GRACEFUL_SOURCE_SHA"
echo "V157_RELEASE_BINARY_SHA256=$CANDIDATE_SHA"
echo "V157_RELEASE_INTERPRETER=$INTERPRETER"
echo "V157_RELEASE_LIBNICE_VERSION=$LIBNICE_VERSION"
echo "V157_RELEASE_GLIB_VERSION=$GLIB_VERSION"

GIT_TERMINAL_PROMPT=0 \
git -C "$WT" \
  -c credential.helper= \
  -c "credential.helper=store --file=$CREDS" \
  -c credential.useHttpPath=true \
  push origin "HEAD:refs/heads/$BRANCH"
PUSH_RC=$?
echo "V157_RELEASE_TOKEN_ONLY_PUSH_RC=$PUSH_RC"
[ "$PUSH_RC" -eq 0 ] || fail "V157_RELEASE_TOKEN_ONLY_PUSH=FAIL"
[ "$FAIL" -eq 0 ] || exit 1

echo "V157_RELEASE_PREPARE=PASS"
echo "CANDIDATE_EXECUTED=false"
echo "COMELIT_NETWORK_SESSION_STARTED=false"
echo "HOME_ASSISTANT_TOUCHED=false"
echo "DOOR_ACTION_SENT=false"
echo "SELF_ACTIVATION_SENT=false"
echo "MEDIA_SIGNALING_SENT=false"
exit 0
