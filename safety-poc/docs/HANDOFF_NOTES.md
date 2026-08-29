# Relation to the Comelit handoff

The source handoff dated 2026-08-28 says:

- current live work is Phase 1 read-only transport proof;
- Door is Phase 3 and must not be exercised during Phase 1;
- one physical action must map to at most one command;
- no automatic retry is permitted;
- timeout/transport loss after send must become `UNKNOWN_OUTCOME`;
- active-call and standalone peer/TAP are separate proof paths.

This package intentionally extracts only those safety semantics into an offline executable PoC. It does not copy the credential-bearing CT120 implementation and does not advance the live Door gate.


v0.3 adds a pinned, fixture-only compatibility bridge to `/root/comelit-vip-poc`. No real transport or Door payload is added.

v0.4 adds only a symbolic Door semantic plan derived from the pinned research call graph. It contains no real payload bytes and does not execute the canonical channel-open primitive.

## v0.5 handoff

Wire framing is now reconciled offline. The pinned legacy `_create_binary_packet_from_buffers()` and canonical `VipSession.send_frame()` produce byte-identical ViP frames for synthetic bodies. Outer ViP framing belongs to canonical `VipSession`; passing a legacy-framed packet as `body` would double-frame it. The next unresolved problem is the Door-specific CTPP **body layout**, not the ViP envelope. v0.5 still contains no real Door payload and no real transport.
