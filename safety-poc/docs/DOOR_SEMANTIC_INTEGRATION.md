# Door Semantic Integration — v0.4

v0.4 maps the observed research call graph into an **offline symbolic plan** over the pinned canonical ViP fixture stack.

The plan contains nine ordered semantic steps: one CTPP-channel precondition, six synthetic write steps, and two optional wait points. The implementation does not contain credential-bearing frame bytes and does not invoke the canonical channel-open primitive.

A complete six-write fixture emission has no protocol acknowledgement and therefore maps to `ACCEPTED_NO_ACK -> UNKNOWN_OUTCOME`. A failure after any partial write is `AMBIGUOUS`. A failure before the first write is `PROVEN_NOT_SENT`.

This release is still incapable of physical access-control action: no socket/network transport is implemented, no real Door payload is present, and no physical effect is asserted.
