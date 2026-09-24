#!/usr/bin/env bash
# CT120 offline-only P116/R30H-C musl launcher corrective harness.
# This script never executes candidate main(), never controls HA, and never
# touches the production listener. It proves the wrapper -> launcher -> musl
# loader -> candidate + packaged library path execution boundary offline.

set -u -o pipefail
umask 077

TASK_ID=COMELIT-P116-R30H-C-MUSL-LAUNCHER-OFFLINE-CORRECTIVE
REPO=${REPO:-}
R30H_C_EXPECTED_SHA=${R30H_C_EXPECTED_SHA:-}
R30H_C_EXPECTED_SOURCE_SHA=${R30H_C_EXPECTED_SOURCE_SHA:-}
R30H_C_EXPECTED_CANDIDATE_SHA=${R30H_C_EXPECTED_CANDIDATE_SHA:-baeb9406b503a43542bc89b2a89a8d18b5564b429646113ccfd81367432f69a4}
R30H_C_OFFLINE_RUN=${R30H_C_OFFLINE_RUN:-NO}
R27_LIVE_RUN=${R27_LIVE_RUN:-NO}
TRANSFORM_REL=${TRANSFORM_REL:-safety-poc/research/media/v1/entrance_p116_r27_repeat_001a_transform.py}
RUNNER_REL=${RUNNER_REL:-safety-poc/research/media/v1/ct120_run_p116_r27_repeat_001a_live.sh}
BUILDER_REL=${BUILDER_REL:-safety-poc/research/media/v1/ct120_build_p80_haos_media_helper.sh}
SOURCE_REL=safety-poc/research/door/v1_5_7/comelit-v4-persistent-ctpp-door.c
BASE_WRAPPER=/usr/local/sbin/comelit-p2p-cloud-probe
EXPECTED_INTERPRETER=/lib/ld-musl-x86_64.so.1
EXPECTED_CANDIDATE_SHA="$R30H_C_EXPECTED_CANDIDATE_SHA"
EXPECTED_NEEDED=libc.musl-x86_64.so.1,libglib-2.0.so.0,libgobject-2.0.so.0,libnice.so.10

FAIL=0
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
RUN_ROOT="/root/comelit-r30h-c-musl-launcher-offline-$STAMP"
BUILD_PROVENANCE_LOG="$RUN_ROOT/build-provenance.log"
LOADER_PROBE_OUTPUT="$RUN_ROOT/loader-probe.txt"
CANDIDATE_OUTPUT="$RUN_ROOT/comelit-media-r30h-c-repeat-001a"
CANDIDATE_LAUNCHER="$RUN_ROOT/comelit-r27-repeat-001a-launcher"
CANDIDATE_WRAPPER="$RUN_ROOT/comelit-p2p-cloud-probe-r30h-c-offline"
RUN_MUSL_LOADER="$RUN_ROOT/ld-musl-x86_64.so.1"
PACKAGED_LIB_DIR=NOT_REACHED
BUILDER_ROOTFS=NOT_REACHED
BUILDER_ROOTFS_MODE=NOT_REACHED
SOURCE_MUSL_LOADER=NOT_REACHED
SOURCE_MUSL_LOADER_SHA256=NOT_REACHED
RUN_MUSL_LOADER_SHA256=NOT_REACHED
RUN_MUSL_LOADER_MODE=NOT_REACHED
CANDIDATE_BINARY_SHA256=NOT_REACHED
CANDIDATE_BINARY_SIZE=NOT_REACHED
CANDIDATE_ELF_INTERPRETER=NOT_REACHED
CANDIDATE_NEEDED_LIBS=NOT_REACHED
P80_CHROOT_BUILD_RC=NOT_REACHED
LOADER_PROBE_RC=NOT_REACHED
LOADER_PROBE_RESOLUTION=FAIL
WRAPPER_BINDING_GATE=FAIL

fail() {
    echo "$1"
    FAIL=1
}

refuse() {
    echo "$1"
    echo "R30H_C_HARNESS_RESULT=FAIL"
    exit 2
}

marker_or() {
    local key="$1"
    local fallback="$2"
    if [ -f "$BUILD_PROVENANCE_LOG" ]; then
        awk -v key="$key" -v fallback="$fallback" '
            index($0, key "=") == 1 { value = substr($0, length(key) + 2); found = 1 }
            END { if (found) print value; else print fallback }
        ' "$BUILD_PROVENANCE_LOG"
    else
        printf '%s\n' "$fallback"
    fi
}

if [ "$R30H_C_OFFLINE_RUN" != YES ]; then
    refuse "R30H_C_OFFLINE_SAFE_REFUSAL=true"
fi
if [ "$R27_LIVE_RUN" = YES ]; then
    refuse "R30H_C_REFUSAL_R27_LIVE_RUN_PRESENT=true"
fi
if [ "${EUID}" -ne 0 ]; then
    refuse "R30H_C_REFUSAL_REQUIRES_ROOT=true"
fi

live_env_names="$(
    env | awk -F= '
        $1 ~ /^(HA_WEBHOOK_URL|HA_TOKEN|HA_ACCESS_TOKEN|COMELIT_TOKEN|COMELIT_PASSWORD|COMELIT_SECRET|COMELIT_AUTH|R27_LIVE_TOKEN)$/ {
            print $1
        }
    ' | paste -sd, -
)"
if [ -n "$live_env_names" ]; then
    echo "R30H_C_REFUSAL_LIVE_TOKEN_ENV_PRESENT=true"
    echo "R30H_C_REFUSAL_LIVE_TOKEN_ENV_NAMES=$live_env_names"
    echo "R30H_C_HARNESS_RESULT=FAIL"
    exit 2
fi

for command in git python3 sha256sum awk grep bash chmod install cmp wc tee readelf stat sed date env paste sort cp file; do
    command -v "$command" >/dev/null 2>&1 || fail "R30H_C_MISSING_COMMAND=$command"
done
[ -n "$REPO" ] || fail "R30H_C_REPO_REQUIRED=true"
[ -n "$R30H_C_EXPECTED_SHA" ] || fail "R30H_C_EXPECTED_SHA_REQUIRED=true"
[ -n "$R30H_C_EXPECTED_SOURCE_SHA" ] || fail "R30H_C_EXPECTED_SOURCE_SHA_REQUIRED=true"
[ -n "$R30H_C_EXPECTED_CANDIDATE_SHA" ] || fail "R30H_C_EXPECTED_CANDIDATE_SHA_REQUIRED=true"

mkdir -p "$RUN_ROOT"
chmod 700 "$RUN_ROOT"
: > "$BUILD_PROVENANCE_LOG"
: > "$LOADER_PROBE_OUTPUT"
chmod 600 "$BUILD_PROVENANCE_LOG" "$LOADER_PROBE_OUTPUT"

if [ "$FAIL" -eq 0 ]; then
    [ -d "$REPO/.git" ] || fail "R30H_C_REPO_PRESENT=false"
    repo_head="$(git -C "$REPO" rev-parse HEAD 2>/dev/null || true)"
    echo "R30H_C_REPO_HEAD=$repo_head"
    [ "$repo_head" = "$R30H_C_EXPECTED_SHA" ] || fail "R30H_C_EXPECTED_SHA_GATE=FAIL"
    [ -z "$(git -C "$REPO" status --porcelain)" ] || fail "R30H_C_WORKTREE_CLEAN=FAIL"
    PACKAGED_LIB_DIR="$REPO/custom_components/comelit/native/lib"
    [ -d "$PACKAGED_LIB_DIR" ] || fail "PACKAGED_NATIVE_LIB_DIR_PRESENT=false"
fi

if [ "$FAIL" -eq 0 ]; then
    git -C "$REPO" show "$R30H_C_EXPECTED_SHA:$TRANSFORM_REL" > "$RUN_ROOT/transform.py" || fail "TRANSFORM_BLOB=FAIL"
    git -C "$REPO" show "$R30H_C_EXPECTED_SHA:$RUNNER_REL" > "$RUN_ROOT/runner.sh" || fail "RUNNER_BLOB=FAIL"
    git -C "$REPO" show "$R30H_C_EXPECTED_SHA:$BUILDER_REL" > "$RUN_ROOT/builder.sh" || fail "BUILDER_BLOB=FAIL"
    cmp "$RUN_ROOT/transform.py" "$REPO/$TRANSFORM_REL" >/dev/null 2>&1 || fail "TRANSFORM_BLOB_WORKTREE_CMP=FAIL"
    cmp "$RUN_ROOT/runner.sh" "$REPO/$RUNNER_REL" >/dev/null 2>&1 || fail "RUNNER_BLOB_WORKTREE_CMP=FAIL"
    bash -n "$RUN_ROOT/builder.sh" || fail "BUILDER_BASH_N=FAIL"
    bash -n "$RUN_ROOT/runner.sh" || fail "RUNNER_BASH_N=FAIL"
fi

[ "$FAIL" -eq 0 ] || { echo "R30H_C_PREFLIGHT=FAIL"; exit 1; }
echo "R30H_C_PREFLIGHT=PASS"
echo "R30H_C_RUN_ROOT=$RUN_ROOT"

set +e
R27_LIVE_RUN=NO REPO="$REPO" R27_EXPECTED_COMMIT_SHA="$R30H_C_EXPECTED_SHA" bash "$RUN_ROOT/runner.sh" > "$RUN_ROOT/r27-offline-refusal.log" 2>&1
r27_offline_rc=$?
set -u -o pipefail
if grep -Fq "R27_OFFLINE_SAFE_REFUSAL=true" "$RUN_ROOT/r27-offline-refusal.log" && [ "$r27_offline_rc" -eq 2 ]; then
    echo "R27_OFFLINE_SAFE_REFUSAL_RC=2"
    echo "R27_OFFLINE_SAFE_REFUSAL=true"
else
    fail "R27_OFFLINE_SAFE_REFUSAL=FAIL"
fi
[ "$FAIL" -eq 0 ] || exit 1

(
    REPO="$REPO" \
    P80_BUILD_ALLOW_DETACHED=1 \
    P80_BUILD_EXPECTED_SHA="$R30H_C_EXPECTED_SHA" \
    P80_BUILD_INCLUDE_P116=1 \
    P80_BUILD_TRANSFORM="$TRANSFORM_REL" \
    P80_BUILD_EXPECTED_SOURCE_SHA="$R30H_C_EXPECTED_SOURCE_SHA" \
    OUTPUT="$CANDIDATE_OUTPUT" \
    bash "$RUN_ROOT/builder.sh"
) | tee "$BUILD_PROVENANCE_LOG"
build_rc=${PIPESTATUS[0]}
echo "P80_CHROOT_BUILD_RC=$build_rc"
P80_CHROOT_BUILD_RC="$build_rc"
[ "$build_rc" -eq 0 ] || fail "CANDIDATE_BUILD=FAIL"

if [ -s "$CANDIDATE_OUTPUT" ]; then
    CANDIDATE_BINARY_SHA256="$(sha256sum "$CANDIDATE_OUTPUT" | awk '{print $1}')"
    CANDIDATE_BINARY_SIZE="$(stat -c '%s' "$CANDIDATE_OUTPUT")"
    CANDIDATE_ELF_INTERPRETER="$(readelf -l "$CANDIDATE_OUTPUT" | sed -n 's@.*Requesting program interpreter: \(.*\)]@\1@p')"
    CANDIDATE_NEEDED_LIBS="$(readelf -d "$CANDIDATE_OUTPUT" | sed -n 's/.*Shared library: \[\(.*\)\]/\1/p' | sort | paste -sd, -)"
else
    fail "CANDIDATE_OUTPUT_PRESENT=false"
fi
echo "CANDIDATE_BINARY_SHA256=$CANDIDATE_BINARY_SHA256"
echo "CANDIDATE_BINARY_SIZE=$CANDIDATE_BINARY_SIZE"
echo "CANDIDATE_INTERPRETER=$CANDIDATE_ELF_INTERPRETER"
echo "CANDIDATE_NEEDED_LIBS=$CANDIDATE_NEEDED_LIBS"
[ "$CANDIDATE_BINARY_SHA256" = "$EXPECTED_CANDIDATE_SHA" ] && echo "CANDIDATE_SHA_GATE=PASS" || fail "CANDIDATE_SHA_GATE=FAIL"
[ "$CANDIDATE_ELF_INTERPRETER" = "$EXPECTED_INTERPRETER" ] && echo "CANDIDATE_INTERPRETER_MATCH=PASS" || fail "CANDIDATE_INTERPRETER_MATCH=FAIL"
[ "$CANDIDATE_NEEDED_LIBS" = "$EXPECTED_NEEDED" ] && echo "CANDIDATE_NEEDED_LIBS_GATE=PASS" || fail "CANDIDATE_NEEDED_LIBS_GATE=FAIL"
[ "$(marker_or GENERATED_SOURCE_SHA256 NOT_REACHED)" = "$R30H_C_EXPECTED_SOURCE_SHA" ] && echo "EXPECTED_SOURCE_SHA_GATE=PASS" || fail "EXPECTED_SOURCE_SHA_GATE=FAIL"
[ "$(marker_or NO_GLIBC_DEPENDENCY FAIL)" = PASS ] && echo "NO_GLIBC_DEPENDENCY=PASS" || fail "NO_GLIBC_DEPENDENCY=FAIL"
[ "$(marker_or NO_NEW_RUNTIME_DEPENDENCY FAIL)" = PASS ] && echo "NO_NEW_RUNTIME_DEPENDENCY=PASS" || fail "NO_NEW_RUNTIME_DEPENDENCY=FAIL"
[ "$(marker_or LIB_IDENTICAL FAIL)" = PASS ] && echo "LIB_IDENTICAL=PASS" || fail "LIB_IDENTICAL=FAIL"
[ "$FAIL" -eq 0 ] || exit 1

BUILDER_ROOTFS="$(marker_or P80_OFFLINE_ROOTFS NOT_REACHED)"
BUILDER_ROOTFS_MODE="$(marker_or P80_BUILD_ROOTFS_MODE NOT_REACHED)"
SOURCE_MUSL_LOADER="$BUILDER_ROOTFS/lib/ld-musl-x86_64.so.1"
echo "BUILDER_ROOTFS=$BUILDER_ROOTFS"
echo "BUILDER_ROOTFS_MODE=$BUILDER_ROOTFS_MODE"
echo "SOURCE_MUSL_LOADER=$SOURCE_MUSL_LOADER"
[ -d "$BUILDER_ROOTFS" ] || fail "BUILDER_ROOTFS_PRESENT=false"
[ -f "$SOURCE_MUSL_LOADER" ] || fail "SOURCE_MUSL_LOADER_PRESENT=false"
if [ "$FAIL" -eq 0 ]; then
    SOURCE_MUSL_LOADER_SHA256="$(sha256sum "$SOURCE_MUSL_LOADER" | awk '{print $1}')"
    echo "SOURCE_MUSL_LOADER_SHA256=$SOURCE_MUSL_LOADER_SHA256"
    install -m 700 "$SOURCE_MUSL_LOADER" "$RUN_MUSL_LOADER" || fail "RUN_MUSL_LOADER_COPY=FAIL"
    RUN_MUSL_LOADER_SHA256="$(sha256sum "$RUN_MUSL_LOADER" | awk '{print $1}')"
    RUN_MUSL_LOADER_MODE="$(stat -c '%a' "$RUN_MUSL_LOADER")"
    echo "RUN_MUSL_LOADER=$RUN_MUSL_LOADER"
    echo "RUN_MUSL_LOADER_SHA256=$RUN_MUSL_LOADER_SHA256"
    echo "RUN_MUSL_LOADER_MODE=$RUN_MUSL_LOADER_MODE"
    [ "$RUN_MUSL_LOADER_SHA256" = "$SOURCE_MUSL_LOADER_SHA256" ] && echo "LOADER_COPY_SHA_GATE=PASS" || fail "LOADER_COPY_SHA_GATE=FAIL"
fi
[ "$FAIL" -eq 0 ] || exit 1

python3 - "$CANDIDATE_LAUNCHER" "$RUN_MUSL_LOADER" "$CANDIDATE_OUTPUT" "$PACKAGED_LIB_DIR" "$SOURCE_MUSL_LOADER_SHA256" <<'PY'
from pathlib import Path
import hashlib
import os
import sys

out = Path(sys.argv[1])
loader = Path(sys.argv[2])
candidate = Path(sys.argv[3])
libdir = Path(sys.argv[4])
expected_loader_sha = sys.argv[5]
if hashlib.sha256(loader.read_bytes()).hexdigest() != expected_loader_sha:
    raise SystemExit("CANDIDATE_LAUNCHER_GATE=FAIL reason=loader_sha")
script = f"""#!/usr/bin/env bash
set -u
LOADER={str(loader)!r}
CANDIDATE={str(candidate)!r}
LIBDIR={str(libdir)!r}
EXPECTED_LOADER_SHA={expected_loader_sha!r}
if [ ! -x "$LOADER" ] || [ ! -x "$CANDIDATE" ] || [ ! -d "$LIBDIR" ]; then
    echo "CANDIDATE_LAUNCHER_PREFLIGHT=FAIL" >&2
    exit 127
fi
actual_loader_sha="$(sha256sum "$LOADER" | awk '{{print $1}}')"
if [ "$actual_loader_sha" != "$EXPECTED_LOADER_SHA" ]; then
    echo "CANDIDATE_LAUNCHER_LOADER_SHA_GATE=FAIL" >&2
    exit 127
fi
exec "$LOADER" --library-path "$LIBDIR" "$CANDIDATE" "$@"
"""
if "comelit_ice_offer_holder" in script or "/root/comelit-vip-poc/bin" in script:
    raise SystemExit("LAUNCHER_BASE_HELPER_FALLBACK=true")
out.write_text(script, encoding="utf-8")
os.chmod(out, 0o700)
print("CANDIDATE_LAUNCHER_GATE=PASS")
print("LAUNCHER_BASE_HELPER_FALLBACK=false")
PY
launcher_rc=$?
echo "CANDIDATE_LAUNCHER_RC=$launcher_rc"
[ "$launcher_rc" -eq 0 ] || fail "CANDIDATE_LAUNCHER_GATE=FAIL"
if grep -Fq "$RUN_MUSL_LOADER" "$CANDIDATE_LAUNCHER"; then echo "LAUNCHER_LOADER_PATH_MATCH=true"; else fail "LAUNCHER_LOADER_PATH_MATCH=false"; fi
if grep -Fq "$CANDIDATE_OUTPUT" "$CANDIDATE_LAUNCHER"; then echo "LAUNCHER_CANDIDATE_PATH_MATCH=true"; else fail "LAUNCHER_CANDIDATE_PATH_MATCH=false"; fi
if grep -Fq "$PACKAGED_LIB_DIR" "$CANDIDATE_LAUNCHER"; then echo "LAUNCHER_LIBRARY_PATH_MATCH=true"; else fail "LAUNCHER_LIBRARY_PATH_MATCH=false"; fi
if grep -Fq "/root/comelit-vip-poc/bin/comelit_ice_offer_holder" "$CANDIDATE_LAUNCHER"; then fail "LAUNCHER_BASE_HELPER_FALLBACK=true"; fi
[ "$FAIL" -eq 0 ] || exit 1

set +e
"$RUN_MUSL_LOADER" --library-path "$PACKAGED_LIB_DIR" --list "$CANDIDATE_OUTPUT" > "$LOADER_PROBE_OUTPUT" 2>&1
LOADER_PROBE_RC=$?
set -u -o pipefail
echo "LOADER_PROBE_EXECUTED=true"
echo "LOADER_PROBE_RC=$LOADER_PROBE_RC"
echo "CANDIDATE_MAIN_EXECUTED=false"
if [ "$LOADER_PROBE_RC" -eq 0 ]; then
    LOADER_PROBE_RESOLUTION=PASS
    echo "LOADER_PROBE_RESOLUTION=PASS"
else
    fail "LOADER_PROBE_RESOLUTION=FAIL"
fi
for lib in libglib-2.0.so.0 libgobject-2.0.so.0 libnice.so.10; do
    if grep -F "$PACKAGED_LIB_DIR/$lib" "$LOADER_PROBE_OUTPUT" >/dev/null; then
        echo "LOADER_PROBE_PACKAGED_RESOLUTION_$lib=PASS"
    else
        fail "LOADER_PROBE_PACKAGED_RESOLUTION_$lib=FAIL"
    fi
done
if grep -Fq "libc.so.6" "$LOADER_PROBE_OUTPUT" || grep -Fq "ld-linux-x86-64" "$LOADER_PROBE_OUTPUT"; then
    fail "GLIBC_RESOLUTION_USED=true"
else
    echo "GLIBC_RESOLUTION_USED=false"
fi
sed -n '1,12p' "$LOADER_PROBE_OUTPUT" | sed 's/^/LOADER_PROBE_SUMMARY=/' || true
[ "$FAIL" -eq 0 ] || exit 1

if [ ! -f "$BASE_WRAPPER" ]; then
    fail "BASE_WRAPPER_PRESENT=false"
else
    BASE_WRAPPER_SHA256_ACTUAL="$(sha256sum "$BASE_WRAPPER" | awk '{print $1}')"
    echo "BASE_WRAPPER=$BASE_WRAPPER"
    echo "BASE_WRAPPER_SHA256=$BASE_WRAPPER_SHA256_ACTUAL"
fi

if [ "$FAIL" -eq 0 ]; then
    python3 - "$BASE_WRAPPER" "$CANDIDATE_WRAPPER" "$CANDIDATE_LAUNCHER" "$CANDIDATE_OUTPUT" <<'PY'
from pathlib import Path
import os
import sys

base = Path(sys.argv[1])
out = Path(sys.argv[2])
launcher = sys.argv[3]
raw_candidate = sys.argv[4]
holder_needle = '"$BASE/bin/comelit_ice_offer_holder"'
base_holder_path = "/root/comelit-vip-poc/bin/comelit_ice_offer_holder"
base_wrapper_path = "/usr/local/sbin/comelit-p2p-cloud-probe"
legacy_run_dir = "/run/comelit-p2p"
media_run_dir = "/run/comelit-media"
text = base.read_text(encoding="utf-8")
if text.count(holder_needle) != 1:
    raise SystemExit("WRAPPER_BINDING_GATE=FAIL reason=holder_anchor_count")
run_dir_count = text.count(legacy_run_dir)
if run_dir_count < 1:
    raise SystemExit("WRAPPER_BINDING_GATE=FAIL reason=run_dir_anchor_absent")
rewritten = text.replace(holder_needle, f'"{launcher}"', 1)
rewritten = rewritten.replace(legacy_run_dir, media_run_dir)
if holder_needle in rewritten:
    raise SystemExit("WRAPPER_BINDING_GATE=FAIL reason=base_holder_still_present")
if f'"{raw_candidate}"' in rewritten:
    raise SystemExit("WRAPPER_BINDING_GATE=FAIL reason=raw_candidate_holder_present")
if base_holder_path in rewritten:
    raise SystemExit("WRAPPER_BINDING_GATE=FAIL reason=base_holder_path_present")
if rewritten.count(launcher) != 1:
    raise SystemExit("WRAPPER_BINDING_GATE=FAIL reason=launcher_occurrences")
if base_wrapper_path in rewritten:
    raise SystemExit("WRAPPER_BINDING_GATE=FAIL reason=base_wrapper_path_present")
out.write_text(rewritten, encoding="utf-8")
os.chmod(out, 0o700)
print(f"BASE_HOLDER_PATH_PRESENT_IN_CANDIDATE_WRAPPER={str(base_holder_path in rewritten).lower()}")
print("RAW_CANDIDATE_PATH_PRESENT_AS_HOLDER=false")
print(f"CANDIDATE_LAUNCHER_PATH_PRESENT_IN_CANDIDATE_WRAPPER={str(launcher in rewritten).lower()}")
print(f"CANDIDATE_LAUNCHER_OCCURRENCES={rewritten.count(launcher)}")
print(f"BASE_WRAPPER_PATH_OCCURRENCES={rewritten.count(base_wrapper_path)}")
print(f"R30H_C_WRAPPER_RUN_DIR_REPLACEMENTS={run_dir_count}")
PY
    wrapper_rewrite_rc=$?
    echo "R30H_C_WRAPPER_REWRITE_RC=$wrapper_rewrite_rc"
    if [ "$wrapper_rewrite_rc" -eq 0 ] && bash -n "$CANDIDATE_WRAPPER"; then
        echo "CANDIDATE_WRAPPER=$CANDIDATE_WRAPPER"
        echo "CANDIDATE_WRAPPER_PARSE=PASS"
        WRAPPER_BINDING_GATE=PASS
        echo "WRAPPER_BINDING_GATE=PASS"
    else
        fail "WRAPPER_BINDING_GATE=FAIL"
    fi
fi
[ "$FAIL" -eq 0 ] || exit 1

echo "=== COMELIT P116 R30H-C MUSL LAUNCHER OFFLINE FINAL ==="
echo "TASK_ID=$TASK_ID"
echo "R30H_C_EXPECTED_SHA=$R30H_C_EXPECTED_SHA"
echo "R30H_C_EXPECTED_SOURCE_SHA=$R30H_C_EXPECTED_SOURCE_SHA"
echo "R30H_C_EXPECTED_CANDIDATE_SHA=$R30H_C_EXPECTED_CANDIDATE_SHA"
echo "P80_CHROOT_BUILD_RC=$P80_CHROOT_BUILD_RC"
echo "BUILDER_ROOTFS=$BUILDER_ROOTFS"
echo "BUILDER_ROOTFS_MODE=$BUILDER_ROOTFS_MODE"
echo "SOURCE_MUSL_LOADER=$SOURCE_MUSL_LOADER"
echo "SOURCE_MUSL_LOADER_SHA256=$SOURCE_MUSL_LOADER_SHA256"
echo "RUN_MUSL_LOADER=$RUN_MUSL_LOADER"
echo "RUN_MUSL_LOADER_SHA256=$RUN_MUSL_LOADER_SHA256"
echo "RUN_MUSL_LOADER_MODE=$RUN_MUSL_LOADER_MODE"
echo "LOADER_COPY_SHA_GATE=PASS"
echo "PACKAGED_NATIVE_LIB_DIR=$PACKAGED_LIB_DIR"
echo "CANDIDATE_BINARY_SHA256=$CANDIDATE_BINARY_SHA256"
echo "CANDIDATE_BINARY_SIZE=$CANDIDATE_BINARY_SIZE"
echo "CANDIDATE_INTERPRETER=$CANDIDATE_ELF_INTERPRETER"
echo "CANDIDATE_NEEDED_LIBS=$CANDIDATE_NEEDED_LIBS"
echo "CANDIDATE_SHA_GATE=PASS"
echo "CANDIDATE_INTERPRETER_MATCH=PASS"
echo "LOADER_PROBE_EXECUTED=true"
echo "LOADER_PROBE_RC=$LOADER_PROBE_RC"
echo "LOADER_PROBE_RESOLUTION=$LOADER_PROBE_RESOLUTION"
echo "CANDIDATE_MAIN_EXECUTED=false"
echo "GLIBC_RESOLUTION_USED=false"
echo "BASE_HOLDER_PATH_PRESENT_IN_CANDIDATE_WRAPPER=false"
echo "RAW_CANDIDATE_PATH_PRESENT_AS_HOLDER=false"
echo "CANDIDATE_LAUNCHER_PATH_PRESENT_IN_CANDIDATE_WRAPPER=true"
echo "CANDIDATE_LAUNCHER_OCCURRENCES=1"
echo "BASE_WRAPPER_PATH_OCCURRENCES=0"
echo "CANDIDATE_WRAPPER_PARSE=PASS"
echo "WRAPPER_BINDING_GATE=$WRAPPER_BINDING_GATE"
echo "LAUNCHER_LOADER_PATH_MATCH=true"
echo "LAUNCHER_CANDIDATE_PATH_MATCH=true"
echo "LAUNCHER_LIBRARY_PATH_MATCH=true"
echo "LAUNCHER_BASE_HELPER_FALLBACK=false"
echo "COMELIT_NETWORK_REQUESTS=0"
echo "HA_TOUCHED=false"
echo "PRODUCTION_LISTENER_TOUCHED=false"
echo "COMELIT_LIVE_EXECUTED=false"
echo "LIVE_INVOCATIONS=0"
echo "CANDIDATE_BINARY_EXECUTED=false"
echo "CANDIDATE_WRAPPER_EXECUTED=false"
if [ "$FAIL" -eq 0 ] && [ "$WRAPPER_BINDING_GATE" = PASS ] && [ "$LOADER_PROBE_RESOLUTION" = PASS ]; then
    echo "R30H_C_HARNESS_RESULT=PASS"
else
    echo "R30H_C_HARNESS_RESULT=FAIL"
fi
echo "=== END COMELIT P116 R30H-C MUSL LAUNCHER OFFLINE FINAL ==="

[ "$FAIL" -eq 0 ] && [ "$WRAPPER_BINDING_GATE" = PASS ] && [ "$LOADER_PROBE_RESOLUTION" = PASS ]
