# P68: resolve the P67 CONTROL mismatch

P67 on the frozen primary capture returned NOT_PROVEN. It found two client
RTPC OPENs, but its zero-filled bytes 2–7 template failed. The client response
at packet 208 differed from device packet 207 only at offsets 8–9 and contained
neither client-created RTPC ID. These are observations, not a live failure:
no signaling or media invocation occurred.

P67's tests used invented zero-filled OPEN fields and literal response copies.
They tested those hypotheses, not their validity against the real capture.
The old analyzer is retained as evidence of the rejected model.

P68 uses the typed CONTROL schemas already in
`research/door/v1_5_7/comelit-v4-persistent-ctpp-door.c`:

- `v4_queue_open_cspb`: OPEN opcode 1, declared payload length 7, channel name,
  target ID and zero trailer.
- `p12_parse_control_response` and its CTPP/CSPB OPEN callers: response opcode 2,
  declared payload length 4, target ID and zero status word.

It tests a new hypothesis: packet 208 responds to a separate device RTPC OPEN
at packet 205, while packets 207 and 209 respond to the two client OPENs at
206. Pairing requires the same target, opposite sender, strict packet ordering,
exact schemas and a unique matching OPEN. No nearest-response echo assumption
is used. Ambiguous, duplicate, unknown, extra or malformed CONTROL traffic
keeps the result NOT_PROVEN. A different device channel is reported by name
from a fixed allowlist but does not pass this RTPC-specific hypothesis.

The report includes semantic classes, positions and pairing counts only.
It emits no identifiers, CONTROL bytes, endpoints or media. The script does
not generate a candidate, connect to the network or manipulate the listener.

Run once on the existing frozen PCAP after the PR is merged and the source
commit and blob are verified. Exit 0 means the capture-specific pairing
contract passed; exit 4 means it remains NOT_PROVEN. Digest or parsing failures
are nonzero and sanitized. A passed synthetic test or merged PR does not prove
the frozen capture or a live media session.

Before live work, review the real P68 output and incorporate the confirmed
direction-specific channel behavior in an independently reviewed candidate.
All existing one-invocation, no-retry, no-Door, timeout, metadata-only and
listener-restoration requirements remain applicable.
