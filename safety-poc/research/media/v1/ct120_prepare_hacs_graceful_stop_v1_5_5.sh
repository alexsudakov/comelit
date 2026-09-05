#!/usr/bin/env bash
# Build and push the HACS v1.5.5 native artifact from CT120.
#
# This script performs no Comelit/HA network session. It only:
# - materializes a detached worktree from an explicitly pinned release seed;
# - applies the already-reviewed graceful-stop transform to the frozen v1.5.3
#   native source;
# - compiles the new native artifact with CT120 libnice;
# - freezes hashes and release tests;
# - commits and token-authenticated pushes the release artifact to the existing
#   release branch.
#
# Required environment:
#   RELEASE_SEED_SHA=<exact commit containing this script>

set -u -o pipefail
umask 077

REPO=/root/comelit-door-diag-repo
CREDS=/root/.config/git/comelit.credentials
BRANCH=fix/graceful-pseudotcp-stop-v1-5-5
BASE_MAIN=7c3ce946aca267bdc2a41423a6a4130cf09c1754
FROZEN_V153_SOURCE_SHA=088e0e23c07404792254f5c18e3f12dbbd499a676bda2d3883988d1d9bb3be6f
FROZEN_V153_BINARY_SHA=c171e7d1d342d059858f0cfca4f81dc8a07679f1d18992718bec2d6ead84db86

SOURCE_REL=safety-poc/research/door/v1_5_3/comelit-v4-persistent-ctpp-door.c
TRANSFORM_REL=safety-poc/research/media/v1/pseudotcp_graceful_stop_transform.py
RELEASE_DIR_REL=safety-poc/research/door/v1_5_5
RELEASE_SOURCE_REL=$RELEASE_DIR_REL/comelit-v4-persistent-ctpp-door.c
BUILD_INFO_REL=$RELEASE_DIR_REL/BUILD_INFO.txt
BINARY_REL=custom_components/comelit/native/comelit-v4
MANIFEST_REL=custom_components/comelit/manifest.json
RELEASE_TEST_REL=safety-poc/tests/test_p27_hacs_graceful_stop_release_contract.py

FAIL=0
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
RUN_ROOT="/root/comelit-v1-5-5-release-$STAMP"
WT="$RUN_ROOT/repo"
BUILD="$RUN_ROOT/build"
CANDIDATE_BINARY="$BUILD/comelit-v4"

fail() {
    echo "$1"
    FAIL=1
}

cleanup() {
    if [ -e "$WT/.git" ]; then
        if git -C "$REPO" worktree remove --force "$WT" >/dev/null 2>&1; then
            echo "V155_RELEASE_WORKTREE_CLEANUP=PASS"
        else
            echo "V155_RELEASE_WORKTREE_CLEANUP=WARNING"
        fi
    fi
}
trap cleanup EXIT

if [ "${EUID}" -ne 0 ]; then
    echo "V155_RELEASE_REQUIRES_ROOT=true"
    exit 1
fi

if [ -z "${RELEASE_SEED_SHA:-}" ]; then
    echo "V155_RELEASE_SEED_PRESENT=false"
    exit 1
fi

echo "V155_RELEASE_SEED_SHA=$RELEASE_SEED_SHA"

for command in git python3 cc pkg-config sha256sum strings file cmp; do
    if ! command -v "$command" >/dev/null 2>&1; then
        fail "V155_RELEASE_MISSING_COMMAND=$command"
    fi
done

if [ ! -d "$REPO/.git" ]; then
    fail "V155_RELEASE_REPO_PRESENT=false"
fi

if [ ! -f "$CREDS" ]; then
    fail "V155_RELEASE_TOKEN_CREDENTIAL_PRESENT=false"
else
    MODE="$(stat -c '%a' "$CREDS")"
    echo "V155_RELEASE_TOKEN_CREDENTIAL_MODE=$MODE"
    if [ "$MODE" != 600 ]; then
        fail "V155_RELEASE_TOKEN_CREDENTIAL_GATE=FAIL"
    else
        echo "V155_RELEASE_TOKEN_CREDENTIAL_GATE=PASS"
    fi
fi

if ! pkg-config --exists nice glib-2.0 gio-2.0 gobject-2.0; then
    fail "V155_RELEASE_BUILD_DEPS=FAIL"
else
    echo "V155_RELEASE_BUILD_DEPS=PASS"
    echo "V155_RELEASE_LIBNICE_VERSION=$(pkg-config --modversion nice)"
fi

if [ "$FAIL" -ne 0 ]; then
    echo "V155_RELEASE_PREFLIGHT=FAIL"
    exit 1
fi

REMOTE_MAIN="$(git -C "$REPO" rev-parse refs/remotes/origin/main)"
REMOTE_BRANCH="$(git -C "$REPO" rev-parse "refs/remotes/origin/$BRANCH")"

echo "V155_RELEASE_REMOTE_MAIN=$REMOTE_MAIN"
echo "V155_RELEASE_REMOTE_BRANCH=$REMOTE_BRANCH"

if [ "$REMOTE_MAIN" != "$BASE_MAIN" ]; then
    fail "V155_RELEASE_MAIN_IDENTITY=FAIL"
else
    echo "V155_RELEASE_MAIN_IDENTITY=PASS"
fi

if [ "$REMOTE_BRANCH" != "$RELEASE_SEED_SHA" ]; then
    fail "V155_RELEASE_BRANCH_SEED_IDENTITY=FAIL"
else
    echo "V155_RELEASE_BRANCH_SEED_IDENTITY=PASS"
fi

if ! git -C "$REPO" merge-base --is-ancestor "$BASE_MAIN" "$RELEASE_SEED_SHA"; then
    fail "V155_RELEASE_BASE_ANCESTOR=FAIL"
else
    echo "V155_RELEASE_BASE_ANCESTOR=PASS"
fi

if [ "$FAIL" -ne 0 ]; then
    echo "V155_RELEASE_PREFLIGHT=FAIL"
    exit 1
fi

mkdir -p "$BUILD"
chmod 700 "$RUN_ROOT" "$BUILD"

if ! git -C "$REPO" worktree add --detach "$WT" "$RELEASE_SEED_SHA" >/dev/null; then
    fail "V155_RELEASE_WORKTREE_CREATE=FAIL"
else
    echo "V155_RELEASE_WORKTREE_CREATE=PASS"
fi

if [ "$FAIL" -ne 0 ]; then
    exit 1
fi

SOURCE="$WT/$SOURCE_REL"
TRANSFORM="$WT/$TRANSFORM_REL"
RELEASE_DIR="$WT/$RELEASE_DIR_REL"
RELEASE_SOURCE="$WT/$RELEASE_SOURCE_REL"
BUILD_INFO="$WT/$BUILD_INFO_REL"
BINARY="$WT/$BINARY_REL"
MANIFEST="$WT/$MANIFEST_REL"
RELEASE_TEST="$WT/$RELEASE_TEST_REL"

BASE_SOURCE_SHA="$(sha256sum "$SOURCE" | awk '{print $1}')"
OLD_BINARY_SHA="$(sha256sum "$BINARY" | awk '{print $1}')"
TRANSFORM_SHA="$(sha256sum "$TRANSFORM" | awk '{print $1}')"

echo "V155_RELEASE_BASE_SOURCE_SHA256=$BASE_SOURCE_SHA"
echo "V155_RELEASE_CURRENT_BINARY_SHA256=$OLD_BINARY_SHA"
echo "V155_RELEASE_TRANSFORM_SHA256=$TRANSFORM_SHA"

if [ "$BASE_SOURCE_SHA" != "$FROZEN_V153_SOURCE_SHA" ]; then
    fail "V155_RELEASE_FROZEN_SOURCE_GATE=FAIL"
else
    echo "V155_RELEASE_FROZEN_SOURCE_GATE=PASS"
fi

if [ "$OLD_BINARY_SHA" != "$FROZEN_V153_BINARY_SHA" ]; then
    fail "V155_RELEASE_FROZEN_BINARY_GATE=FAIL"
else
    echo "V155_RELEASE_FROZEN_BINARY_GATE=PASS"
fi

if [ "$FAIL" -ne 0 ]; then
    exit 1
fi

mkdir -p "$RELEASE_DIR"

python3 "$TRANSFORM" \
  --source "$SOURCE" \
  --output "$RELEASE_SOURCE" \
  | tee "$RUN_ROOT/transform.log"
TRANSFORM_RC=${PIPESTATUS[0]}
echo "V155_RELEASE_TRANSFORM_RC=$TRANSFORM_RC"
if [ "$TRANSFORM_RC" -ne 0 ]; then
    fail "V155_RELEASE_TRANSFORM=FAIL"
fi

if [ "$FAIL" -eq 0 ]; then
    cc \
      -O2 \
      -g \
      -Wall \
      -Wextra \
      -o "$CANDIDATE_BINARY" \
      "$RELEASE_SOURCE" \
      $(pkg-config --cflags --libs nice glib-2.0 gio-2.0 gobject-2.0) \
      2>"$RUN_ROOT/compile.stderr"
    BUILD_RC=$?
    cat "$RUN_ROOT/compile.stderr"
    echo "V155_RELEASE_BUILD_RC=$BUILD_RC"
    if [ "$BUILD_RC" -ne 0 ]; then
        fail "V155_RELEASE_BUILD=FAIL"
    fi
fi

if [ "$FAIL" -eq 0 ]; then
    chmod 755 "$CANDIDATE_BINARY"
    file "$CANDIDATE_BINARY" | sed 's#^.*: #V155_RELEASE_BINARY_FILE=#'

    strings -a "$CANDIDATE_BINARY" > "$RUN_ROOT/candidate.strings"
    STRINGS_RC=$?
    echo "V155_RELEASE_STRINGS_RC=$STRINGS_RC"
    if [ "$STRINGS_RC" -ne 0 ]; then
        fail "V155_RELEASE_STRINGS=FAIL"
    fi
fi

if [ "$FAIL" -eq 0 ]; then
    for marker in \
      'PSEUDOTCP_GRACEFUL_CLOSE_REQUESTED=true' \
      'PSEUDOTCP_GRACEFUL_CLOSE_FORCE=false' \
      'PSEUDOTCP_GRACEFUL_CLOSE_FORCE_RST_SENT=false' \
      'PSEUDOTCP_GRACEFUL_CLOSE_COMPLETE=true' \
      'PSEUDOTCP_GRACEFUL_CLOSE_TIMEOUT=true' \
      'V4_DOOR_EXISTING_CTPP_REUSED=true' \
      'V4_DOOR_OPERATION_WRITES_SENT=5' \
      'V4_DOOR_AUTOMATIC_RETRY_ALLOWED=false' \
      'V4_DOOR_PHYSICAL_EFFECT_ASSERTED=false'
    do
        if grep -Fq "$marker" "$RUN_ROOT/candidate.strings"; then
            echo "V155_RELEASE_BINARY_MARKER=PASS $marker"
        else
            fail "V155_RELEASE_BINARY_MARKER=FAIL $marker"
        fi
    done

    if grep -Fq 'PSEUDOTCP_GRACEFUL_CLOSE_FORCE=true' "$RUN_ROOT/candidate.strings"; then
        fail "V155_RELEASE_FORCE_CLOSE_GATE=FAIL"
    else
        echo "V155_RELEASE_FORCE_CLOSE_GATE=PASS"
    fi
fi

if [ "$FAIL" -ne 0 ]; then
    exit 1
fi

cp "$CANDIDATE_BINARY" "$BINARY"
chmod 755 "$BINARY"

SOURCE_SHA="$(sha256sum "$RELEASE_SOURCE" | awk '{print $1}')"
BINARY_SHA="$(sha256sum "$BINARY" | awk '{print $1}')"

echo "V155_RELEASE_SOURCE_SHA256=$SOURCE_SHA"
echo "V155_RELEASE_BINARY_SHA256=$BINARY_SHA"

if [ "$BINARY_SHA" = "$OLD_BINARY_SHA" ]; then
    fail "V155_RELEASE_BINARY_CHANGED_GATE=FAIL"
else
    echo "V155_RELEASE_BINARY_CHANGED_GATE=PASS"
fi

python3 - "$MANIFEST" <<'PY'
import json
from pathlib import Path
import sys

path = Path(sys.argv[1])
data = json.loads(path.read_text(encoding="utf-8"))
if data.get("version") != "1.5.4":
    raise SystemExit(f"unexpected current manifest version: {data.get('version')!r}")
data["version"] = "1.5.5"
path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
PY
MANIFEST_RC=$?
echo "V155_RELEASE_MANIFEST_UPDATE_RC=$MANIFEST_RC"
if [ "$MANIFEST_RC" -ne 0 ]; then
    fail "V155_RELEASE_MANIFEST_UPDATE=FAIL"
fi

cat > "$BUILD_INFO" <<EOF
release=1.5.5
base_main=$BASE_MAIN
release_seed=$RELEASE_SEED_SHA
base_source_sha256=$BASE_SOURCE_SHA
transform_sha256=$TRANSFORM_SHA
source_sha256=$SOURCE_SHA
binary_sha256=$BINARY_SHA
libnice_version=$(pkg-config --modversion nice)
pseudotcp_graceful_close=true
pseudotcp_graceful_close_force=false
pseudotcp_graceful_close_force_rst_sent=false
graceful_close_timeout_ms=5000
door_contract_source=frozen_v1_5_3_transform_only
automatic_retry_allowed=false
physical_effect_asserted=false
terminal_state_without_proven_ack=UNKNOWN_OUTCOME
EOF
chmod 644 "$BUILD_INFO"

cat > "$RELEASE_TEST" <<EOF
import hashlib
import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
EXPECTED_SOURCE_SHA = "$SOURCE_SHA"
EXPECTED_BINARY_SHA = "$BINARY_SHA"
EXPECTED_BASE_SOURCE_SHA = "$BASE_SOURCE_SHA"
EXPECTED_TRANSFORM_SHA = "$TRANSFORM_SHA"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class P27HacsGracefulStopReleaseContract(unittest.TestCase):
    def test_manifest_is_1_5_5(self):
        manifest = json.loads(
            (ROOT / "custom_components/comelit/manifest.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(manifest["version"], "1.5.5")

    def test_release_source_and_binary_hashes_are_frozen(self):
        source = (
            ROOT / "safety-poc/research/door/v1_5_5"
            / "comelit-v4-persistent-ctpp-door.c"
        )
        binary = ROOT / "custom_components/comelit/native/comelit-v4"
        self.assertEqual(sha256(source), EXPECTED_SOURCE_SHA)
        self.assertEqual(sha256(binary), EXPECTED_BINARY_SHA)

    def test_release_source_is_exact_reviewed_transform_of_frozen_v153(self):
        base = (
            ROOT / "safety-poc/research/door/v1_5_3"
            / "comelit-v4-persistent-ctpp-door.c"
        )
        transform_path = (
            ROOT / "safety-poc/research/media/v1"
            / "pseudotcp_graceful_stop_transform.py"
        )
        release = (
            ROOT / "safety-poc/research/door/v1_5_5"
            / "comelit-v4-persistent-ctpp-door.c"
        )

        self.assertEqual(sha256(base), EXPECTED_BASE_SOURCE_SHA)
        self.assertEqual(sha256(transform_path), EXPECTED_TRANSFORM_SHA)

        spec = importlib.util.spec_from_file_location(
            "pseudotcp_graceful_stop_transform_release_test",
            transform_path,
        )
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)

        expected = module.transform(base.read_text(encoding="utf-8"))
        self.assertEqual(release.read_text(encoding="utf-8"), expected)

    def test_graceful_close_contract_is_present_and_never_force_closes(self):
        source = (
            ROOT / "safety-poc/research/door/v1_5_5"
            / "comelit-v4-persistent-ctpp-door.c"
        ).read_text(encoding="utf-8")

        self.assertEqual(
            source.count("pseudo_tcp_socket_close(pseudo_tcp, FALSE);"),
            1,
        )
        self.assertNotIn(
            "pseudo_tcp_socket_close(pseudo_tcp, TRUE);",
            source,
        )
        self.assertIn("PSEUDOTCP_GRACEFUL_STOP_TIMEOUT_MS 5000", source)
        self.assertIn("PSEUDOTCP_GRACEFUL_CLOSE_DRAINED_BYTES=%u", source)

    def test_current_binary_contains_graceful_and_door_safety_markers(self):
        binary = (
            ROOT / "custom_components/comelit/native/comelit-v4"
        ).read_bytes()

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

        self.assertNotIn(
            b"PSEUDOTCP_GRACEFUL_CLOSE_FORCE=true",
            binary,
        )

    def test_build_info_matches_release_artifacts(self):
        text = (
            ROOT / "safety-poc/research/door/v1_5_5/BUILD_INFO.txt"
        ).read_text(encoding="utf-8")

        for marker in (
            "release=1.5.5",
            "source_sha256=" + EXPECTED_SOURCE_SHA,
            "binary_sha256=" + EXPECTED_BINARY_SHA,
            "base_source_sha256=" + EXPECTED_BASE_SOURCE_SHA,
            "transform_sha256=" + EXPECTED_TRANSFORM_SHA,
            "pseudotcp_graceful_close=true",
            "pseudotcp_graceful_close_force=false",
            "pseudotcp_graceful_close_force_rst_sent=false",
            "door_contract_source=frozen_v1_5_3_transform_only",
            "automatic_retry_allowed=false",
            "physical_effect_asserted=false",
        ):
            self.assertIn(marker, text)


if __name__ == "__main__":
    unittest.main()
EOF
chmod 644 "$RELEASE_TEST"

if [ "$FAIL" -ne 0 ]; then
    exit 1
fi

python3 -m py_compile "$RELEASE_TEST"
TEST_COMPILE_RC=$?
echo "V155_RELEASE_TEST_COMPILE_RC=$TEST_COMPILE_RC"
if [ "$TEST_COMPILE_RC" -ne 0 ]; then
    fail "V155_RELEASE_TEST_COMPILE=FAIL"
fi

(
    cd "$WT/safety-poc" &&
    python3 -m unittest tests.test_p15_hacs_persistent_ctpp_release_contract \
                       tests.test_p26_pseudotcp_graceful_stop_contract \
                       tests.test_p27_hacs_graceful_stop_release_contract
)
TEST_RC=$?
echo "V155_RELEASE_TARGETED_TEST_RC=$TEST_RC"
if [ "$TEST_RC" -ne 0 ]; then
    fail "V155_RELEASE_TARGETED_TESTS=FAIL"
fi

if [ "$FAIL" -ne 0 ]; then
    exit 1
fi

EXPECTED_PATHS="$RUN_ROOT/expected-paths.txt"
ACTUAL_PATHS="$RUN_ROOT/actual-paths.txt"
cat > "$EXPECTED_PATHS" <<EOF
$BINARY_REL
$MANIFEST_REL
$BUILD_INFO_REL
$RELEASE_SOURCE_REL
$RELEASE_TEST_REL
EOF
sort -o "$EXPECTED_PATHS" "$EXPECTED_PATHS"

git -C "$WT" add \
  "$BINARY_REL" \
  "$MANIFEST_REL" \
  "$BUILD_INFO_REL" \
  "$RELEASE_SOURCE_REL" \
  "$RELEASE_TEST_REL"

git -C "$WT" diff --cached --name-only | sort > "$ACTUAL_PATHS"

if cmp -s "$EXPECTED_PATHS" "$ACTUAL_PATHS"; then
    echo "V155_RELEASE_STAGED_PATH_GATE=PASS"
else
    echo "V155_RELEASE_STAGED_PATH_GATE=FAIL"
    echo "V155_RELEASE_EXPECTED_PATHS:"
    cat "$EXPECTED_PATHS"
    echo "V155_RELEASE_ACTUAL_PATHS:"
    cat "$ACTUAL_PATHS"
    exit 1
fi

if [ -n "$(git -C "$WT" status --porcelain | grep '^??' || true)" ]; then
    fail "V155_RELEASE_UNTRACKED_PATH_GATE=FAIL"
else
    echo "V155_RELEASE_UNTRACKED_PATH_GATE=PASS"
fi

if [ "$FAIL" -ne 0 ]; then
    exit 1
fi

git -C "$WT" config user.name "Comelit CT120 Release Builder"
git -C "$WT" config user.email "ct120-builder@local.invalid"

git -C "$WT" commit -m "fix(comelit): gracefully close persistent PseudoTCP"
COMMIT_RC=$?
echo "V155_RELEASE_COMMIT_RC=$COMMIT_RC"
if [ "$COMMIT_RC" -ne 0 ]; then
    exit 1
fi

RELEASE_COMMIT="$(git -C "$WT" rev-parse HEAD)"
echo "V155_RELEASE_COMMIT=$RELEASE_COMMIT"

GIT_TERMINAL_PROMPT=0 \
git -C "$WT" \
  -c credential.helper= \
  -c "credential.helper=store --file=$CREDS" \
  -c credential.useHttpPath=true \
  push origin "HEAD:refs/heads/$BRANCH"
PUSH_RC=$?
echo "V155_RELEASE_TOKEN_ONLY_PUSH_RC=$PUSH_RC"
if [ "$PUSH_RC" -ne 0 ]; then
    exit 1
fi

echo
echo "=== V1.5.5 RELEASE ARTIFACT FINAL ==="
echo "V155_RELEASE_PREPARE=PASS"
echo "V155_RELEASE_BRANCH=$BRANCH"
echo "V155_RELEASE_COMMIT=$RELEASE_COMMIT"
echo "V155_RELEASE_SOURCE_SHA256=$SOURCE_SHA"
echo "V155_RELEASE_BINARY_SHA256=$BINARY_SHA"
echo "V155_RELEASE_MANIFEST_VERSION=1.5.5"
echo "CANDIDATE_EXECUTED=false"
echo "COMELIT_NETWORK_SESSION_STARTED=false"
echo "HOME_ASSISTANT_TOUCHED=false"
echo "DOOR_ACTION_SENT=false"
echo "SELF_ACTIVATION_SENT=false"
echo "MEDIA_SIGNALING_SENT=false"
