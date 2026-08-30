#!/usr/bin/env bash
# =============================================================================
# P13 door wrapper template (reviewed, versioned in Git).
#
# The installed wrapper preserves the proven P12 cloud-signaling orchestration
# instead of invoking the native ICE holder directly.  The baseline wrapper is
# pinned by SHA-256 and is transformed at runtime by replacing exactly its one
# proven holder invocation with the P13 holder path.  This is the same wrapper
# substitution model used by the successful P12 read-only live run.
#
# Transaction path:
#   pinned cloud signaling wrapper -> P13 holder -> ICE -> PseudoTCP -> ViP ->
#   UAUT open/auth -> CTPP open -> six prepared Door writes -> close/teardown.
#
# The operation id is mandatory at this outer boundary.  The Python one-shot
# runner sets P13_OPERATION_ID before its single wrapper Popen.  This wrapper
# creates one derived signaling script and execs it exactly once; the pinned
# baseline contains exactly one holder invocation and no P13 retry layer is
# added here.
#
# No credential values, raw payload bodies, or target identity values are ever
# printed by this wrapper.
# =============================================================================
set -Eeuo pipefail
umask 077

# This line is replaced by install_p13_runtime_artifacts.sh and is also the
# static holder binding consumed by runtime identity/preflight.
HOLDER_PATH="__P13_HOLDER_PATH__"
P13_HOLDER_PATH="$HOLDER_PATH"
PAYLOAD_FILE="/root/comelit-p13-actuator-prep/real-door-payloads.json"
OPERATION_ID="${P13_OPERATION_ID:-}"

BASE_SIGNALING_WRAPPER=/usr/local/sbin/comelit-p2p-cloud-probe
EXPECTED_BASE_SIGNALING_SHA256=a564535dff0cf10b1fe4766171f2960c52fb581f1c816cf81d2992c5c84e79c9
DERIVED_DIR=/run/comelit-p13-signaling
SIGNALING_WRAPPER="$DERIVED_DIR/comelit-p2p-cloud-probe-p13"
BASE_HOLDER_LITERAL='"$BASE/bin/comelit_ice_offer_holder"'

[[ -n "$OPERATION_ID" ]] || { echo "P13_WRAPPER_OPERATION_ID_MISSING=true" >&2; exit 2; }
[[ -x "$P13_HOLDER_PATH" ]] || { echo "P13_WRAPPER_HOLDER_ABSENT=true" >&2; exit 2; }
[[ -r "$PAYLOAD_FILE" ]] || { echo "P13_WRAPPER_PAYLOAD_ABSENT=true" >&2; exit 2; }
[[ -f "$BASE_SIGNALING_WRAPPER" ]] || { echo "P13_SIGNALING_BASE_PRESENT=false" >&2; exit 2; }

actual_base_sha="$(sha256sum "$BASE_SIGNALING_WRAPPER" | awk '{print $1}')"
[[ "$actual_base_sha" == "$EXPECTED_BASE_SIGNALING_SHA256" ]] || {
    echo "P13_SIGNALING_BASE_PIN=FAIL" >&2
    exit 2
}
echo "P13_SIGNALING_BASE_PIN=PASS"

install -d -m 700 -o root -g root "$DERIVED_DIR"
python3 - "$BASE_SIGNALING_WRAPPER" "$SIGNALING_WRAPPER" "$P13_HOLDER_PATH" <<'PY'
from pathlib import Path
import os
import sys

src = Path(sys.argv[1])
out = Path(sys.argv[2])
holder = sys.argv[3]
text = src.read_text(encoding="utf-8")
needle = '"$BASE/bin/comelit_ice_offer_holder"'
count = text.count(needle)
if count != 1:
    raise SystemExit(f"P13_SIGNALING_BASE_HOLDER_INVOCATION_COUNT={count}")
if holder in text:
    raise SystemExit("P13_SIGNALING_BASE_ALREADY_CONTAINS_P13_HOLDER=true")
text = text.replace(needle, f'"{holder}"', 1)
out.write_text(text, encoding="utf-8")
os.chmod(out, 0o700)
PY
chown root:root "$SIGNALING_WRAPPER"

[[ "$(grep -Fc -- "$P13_HOLDER_PATH" "$SIGNALING_WRAPPER" || true)" == "1" ]] || {
    echo "P13_SIGNALING_HOLDER_BIND=FAIL" >&2
    exit 2
}
if grep -Fq -- "$BASE_HOLDER_LITERAL" "$SIGNALING_WRAPPER"; then
    echo "P13_SIGNALING_BASE_HOLDER_REMAINS=true" >&2
    exit 2
fi

echo "P13_SIGNALING_HOLDER_BIND=PASS"
echo "P13_SIGNALING_WRAPPER_READY=true"

# Exactly one outer process replacement.  The derived signaling wrapper is the
# proven P12 orchestration with exactly one holder path substituted above.
HOLDER_PATH="$SIGNALING_WRAPPER"
exec "$HOLDER_PATH"
