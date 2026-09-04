#!/usr/bin/env bash
set -euo pipefail

BUILD=/root/comelit-door-reject-diag-build
SRC="$BUILD/comelit-v4-persistent-ring-door-diag.c"
BIN="$BUILD/comelit-v4-door-diag"
STRINGS_FILE="$BUILD/comelit-v4-door-diag.strings"

for cmd in strings grep sha256sum; do
    command -v "$cmd" >/dev/null 2>&1 || {
        echo "MISSING_COMMAND=$cmd"
        exit 10
    }
done

[[ -f "$SRC" ]] || {
    echo 'DIAGNOSTIC_SOURCE=NOT_FOUND'
    exit 11
}

[[ -x "$BIN" ]] || {
    echo 'DIAGNOSTIC_BINARY=NOT_FOUND_OR_NOT_EXECUTABLE'
    exit 12
}

# Do not pipe `strings` into `grep -q` under `set -o pipefail`: grep exits
# as soon as it finds a match, which can SIGPIPE `strings` and make a valid
# marker look like a failed pipeline. Materialize strings once, then inspect.
strings -a "$BIN" > "$STRINGS_FILE"
chmod 600 "$STRINGS_FILE"

for marker in \
  'V4_DOOR_REJECT_STAGE=CTPP_OPEN' \
  'V4_DOOR_REJECT_RESPONSE_WORD=%u' \
  'V4_DOOR_REQUESTED_CHANNEL_ID=%u' \
  'V4_DOOR_RESPONSE_CHANNEL_ID=%u' \
  'door-reject-diagnostic.txt'
do
    grep -Fq "$marker" "$SRC" || {
        echo "SOURCE_DIAGNOSTIC_MARKER=FAIL marker=$marker"
        exit 13
    }
    grep -Fq "$marker" "$STRINGS_FILE" || {
        echo "BINARY_DIAGNOSTIC_MARKER=FAIL marker=$marker"
        exit 14
    }
done

echo 'SOURCE_DIAGNOSTIC_MARKERS=PASS'
echo 'BINARY_DIAGNOSTIC_MARKERS=PASS'

# The diagnostic build must still contain the no-retry and no-physical-proof
# contract strings used by the Door path.
for marker in \
  'V4_DOOR_AUTOMATIC_RETRY_ALLOWED=false' \
  'V4_DOOR_PHYSICAL_EFFECT_ASSERTED=false'
do
    grep -Fq "$marker" "$STRINGS_FILE" || {
        echo "BINARY_SAFETY_MARKER=FAIL marker=$marker"
        exit 15
    }
done

echo 'BINARY_SAFETY_MARKERS=PASS'

sha256sum "$SRC" "$BIN"

echo 'NETWORK_IO_PERFORMED=false'
echo 'DOOR_ACTION_SENT=false'
echo 'MEDIA_ACTION_SENT=false'
echo 'DOOR_REJECT_DIAGNOSTIC_VERIFY=PASS'
