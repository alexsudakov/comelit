#!/usr/bin/env bash
# =============================================================================
# P13 door wrapper template (reviewed, versioned in Git).
#
# This template is the deterministic source for the installed
# /usr/local/sbin/comelit-p13-door-wrapper on CT120.  It is built by
# scripts/build_p13_wrapper.sh, which:
#   - verifies the pinned native P2P/ICE/PseudoTCP/ViP holder identity,
#   - substitutes this template's HOLDER_PATH marker,
#   - writes the installed wrapper to the root-only destination,
#   - computes the independently derived expected SHA-256 and records it in
#     deploy/p13_wrapper_manifest.json (Git-reviewed) BEFORE the installed
#     wrapper is compared by preflight.
#
# The installed wrapper performs the single proven transaction:
#   Cloud P2P -> ICE -> PseudoTCP -> ViP -> UAUT open/auth -> CTPP open ->
#   six prepared Door writes -> CTPP close -> teardown.
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

# One invocation only: no retry loop exists anywhere in this wrapper.
exec "$HOLDER_PATH" --payload "$PAYLOAD_FILE" --operation-id "$OPERATION_ID" \
    --emit-ctpp-markers
