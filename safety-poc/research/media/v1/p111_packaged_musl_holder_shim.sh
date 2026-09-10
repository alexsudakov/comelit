#!/usr/bin/env bash
# Research-only holder shim for P111 RUN5.
#
# No Comelit protocol logic lives here. The accepted base wrapper owns offer,
# SDP transform, cloud bootstrap, and terminal classification. This shim only
# re-checks the frozen packaged helper identity/runtime and execs it under the
# verified musl loader.

set -u -o pipefail
umask 077

PACKAGED_BINARY_SHA256=ebc731381022be89576a680c39f7402225048e48adab88376434f660ad1a5ade
PACKAGED_BINARY_REL=custom_components/comelit/native/comelit-media
PACKAGED_LIB_REL=custom_components/comelit/native/lib

PR106_CHECKOUT="${P111_PR106_CHECKOUT:?}"
RUNTIME_ROOT="${P111_RUNTIME_ROOT:?}"
PACKAGED_BINARY="$PR106_CHECKOUT/$PACKAGED_BINARY_REL"
PACKAGED_LIB_DIR="$PR106_CHECKOUT/$PACKAGED_LIB_REL"
RUNTIME_LOADER="$RUNTIME_ROOT/lib/ld-musl-x86_64.so.1"
RUNTIME_LIBRARY_PATH="$PACKAGED_LIB_DIR:$RUNTIME_ROOT/lib:$RUNTIME_ROOT/usr/lib"

die() {
    echo "$1"
    exit 126
}

[ -f "$PACKAGED_BINARY" ] || die "P111_SHIM_PACKAGED_BINARY_PRESENT=false"
[ -d "$PACKAGED_LIB_DIR" ] || die "P111_SHIM_PACKAGED_LIB_DIR_PRESENT=false"
[ -x "$RUNTIME_LOADER" ] || die "P111_SHIM_MUSL_LOADER_PRESENT=false"
[ -r "$RUNTIME_ROOT/etc/alpine-release" ] || die "P111_SHIM_ALPINE_RUNTIME_PRESENT=false"
[ -r "$PACKAGED_LIB_DIR/libnice.so.10" ] || die "P111_SHIM_LIBNICE_PRESENT=false"
[ -r "$PACKAGED_LIB_DIR/libglib-2.0.so.0" ] || die "P111_SHIM_LIBGLIB_PRESENT=false"
[ -r "$PACKAGED_LIB_DIR/libgobject-2.0.so.0" ] || die "P111_SHIM_LIBGOBJECT_PRESENT=false"

actual_sha="$(sha256sum "$PACKAGED_BINARY" | awk '{print $1}')"
echo "P111_SHIM_PACKAGED_BINARY_SHA_BEFORE_EXEC=$actual_sha"
[ "$actual_sha" = "$PACKAGED_BINARY_SHA256" ] || die "P111_SHIM_PACKAGED_BINARY_SHA_GATE=FAIL"
echo "P111_SHIM_MUSL_EXEC_GATE=PASS"
echo "P111_SHIM_EXEC_COMMAND=$RUNTIME_LOADER --library-path $RUNTIME_LIBRARY_PATH $PACKAGED_BINARY"

exec "$RUNTIME_LOADER" --library-path "$RUNTIME_LIBRARY_PATH" "$PACKAGED_BINARY"
