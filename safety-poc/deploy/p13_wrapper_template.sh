#!/usr/bin/env bash
# =============================================================================
# P13 door wrapper template (reviewed, versioned in Git).
#
# The installed wrapper performs the single proven transaction:
#   Cloud P2P -> ICE -> PseudoTCP -> ViP -> UAUT open/auth -> CTPP open ->
#   six prepared Door writes -> CTPP close -> teardown.
#
# The generated P13 holder is bound at build time to the root-only payload
# path and emits typed P13 markers unconditionally.  It therefore needs no
# runtime CLI arguments.  Avoiding synthetic --payload/--operation-id flags
# also preserves compatibility with the proven P12 baseline main(argc, argv).
#
# The operation id is still mandatory at the wrapper boundary.  The Python
# one-shot runner sets P13_OPERATION_ID from its exact --operation-id before
# the single wrapper Popen; this wrapper refuses to invoke the holder without
# that value.  No retry loop exists here.
#
# The wrapper protocol is typed markers on stdout:
#   P13_CTPP_OPEN_OUTCOME=OPENED|AMBIGUOUS|PROVEN_NOT_OPENED|REJECTED
#   P13_DOOR_WRITE_COUNT=N
#   P13_CTPP_CLOSE=PASS|FAIL
#   P13_TEARDOWN=PASS
#
# Exit status is significant: a nonzero exit or a timeout is treated by the
# adapter as AMBIGUOUS even when markers look complete.
#
# No credential values, raw payload bodies, or target identity values are ever
# printed by this wrapper.
# =============================================================================
set -Eeuo pipefail
umask 077

HOLDER_PATH="__P13_HOLDER_PATH__"
PAYLOAD_FILE="/root/comelit-p13-actuator-prep/real-door-payloads.json"
OPERATION_ID="${P13_OPERATION_ID:-}"

[[ -n "$OPERATION_ID" ]] || { echo "P13_WRAPPER_OPERATION_ID_MISSING=true" >&2; exit 2; }
[[ -x "$HOLDER_PATH" ]] || { echo "P13_WRAPPER_HOLDER_ABSENT=true" >&2; exit 2; }
[[ -r "$PAYLOAD_FILE" ]] || { echo "P13_WRAPPER_PAYLOAD_ABSENT=true" >&2; exit 2; }

# Exactly one holder invocation. The holder uses its build-bound payload path
# and emits the P13 transaction markers without command-line switches.
exec "$HOLDER_PATH"
