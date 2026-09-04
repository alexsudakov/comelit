#!/usr/bin/env bash
set -euo pipefail

HERE="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
BUILD=/root/comelit-media-poc-build
SRC="$HERE/comelit-v4-media-poc.c"
BIN="$BUILD/comelit-v4-media-poc"

mkdir -p "$BUILD"
chmod 700 "$BUILD"

python3 "$HERE/test_media_protocol_vectors.py"
python3 "$HERE/generate_media_poc_v1.py"

printf '%s\n' '=== SOURCE SAFETY ==='

for token in \
  'v4_door_queue_open' \
  'v4_door_queue_write' \
  'v4_door_signal_handler' \
  'V4_DOOR_COMMAND_ACCEPTED' \
  'SIGUSR1'
do
  if grep -Fq "$token" "$SRC"; then
    echo "SOURCE_FORBIDDEN=$token"
    exit 20
  fi
done

grep -Fq 'V4_DOOR_ACTION_SURFACE_PRESENT=false' "$SRC"
grep -Fq 'V4_MEDIA_ACTION_SURFACE_PRESENT=true' "$SRC"
grep -Fq '#define V4_MEDIA_TARGET     V4_ENTRANCE' "$SRC"

echo 'SOURCE_DOOR_ACTION=ABSENT'
echo 'SOURCE_MEDIA_TARGET=ENTRANCE'

printf '%s\n' '=== COMPILE ==='

CFLAGS="$(pkg-config --cflags nice glib-2.0 gobject-2.0)"
LIBS="$(pkg-config --libs nice glib-2.0 gobject-2.0)"

# shellcheck disable=SC2086
gcc -std=c11 -O2 -g -Wall -Wextra \
  $CFLAGS \
  "$SRC" \
  -o "$BIN" \
  $LIBS

chmod 700 "$BIN"

printf '%s\n' '=== BINARY SAFETY ==='

for token in \
  'V4_DOOR_COMMAND_ACCEPTED' \
  'V4_DOOR_RESULT=' \
  'V4_DOOR_WRITE_' \
  'V4_DOOR_CTPP_OPEN_SENT'
do
  if strings -a "$BIN" | grep -Fq "$token"; then
    echo "BINARY_FORBIDDEN=$token"
    exit 21
  fi
done

strings -a "$BIN" | grep -Fq 'V4_DOOR_ACTION_SURFACE_PRESENT=false'
strings -a "$BIN" | grep -Fq 'V4_MEDIA_ACTION_SURFACE_PRESENT=true'
strings -a "$BIN" | grep -Fq 'V4_MEDIA_TARGET=entrance'

echo 'BINARY_DOOR_ACTION=ABSENT'
echo 'BINARY_MEDIA_ACTION=PRESENT'

printf '%s\n' '=== RESULT ==='
file "$BIN"
sha256sum "$BIN"
echo "BINARY=$BIN"
echo 'MEDIA_POC_BUILD=PASS'
