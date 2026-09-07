# P69: separate OPEN pairing from the byte-14 hypothesis

The real P68 run validated the OPEN operation and declared length, but both
client OPENs differed from its template at byte 14. Every OPEN, including the
device OPEN at packet 205, failed the zero-trailer schema. All three responses
passed their schemas. Therefore the zero matching-OPEN counts were caused by
the candidate filter, not evidence against pairing.

P69 retains P68 unchanged. It independently checks the known 15-byte OPEN
envelope, nonzero target, direction and ordering, then correlates responses to
unique earlier opposite-direction OPENs. It does not require or guess a value
for byte 14 to perform this structural analysis. Duplicate/unknown/extra
controls, malformed envelopes, wrong targets and ambiguous pairings still
fail the structural contract.

The narrowly scoped forensic output change is intentional: for each validated
RTPC OPEN, emit **only byte 14 as a decimal unsigned scalar** (0–255), with its
packet/direction. This is required to replace the now-rejected zero assumption
without another guessed-template iteration. No target IDs, other body bytes,
addresses, endpoints or raw/media payload are emitted. The report explicitly
declares this scalar disclosure and does not claim all body values are hidden.

Trailer equality between the two client OPENs and across all three OPENs is
reported separately from structural pairing. Even when pairing passes, trailer
semantics and live body generation remain NOT_PROVEN. Observing a value in one
capture does not prove its meaning or stability across sessions.

This is an offline-only follow-up on the same frozen PCAP. No candidate,
network access, listener changes, Door action, media activation or capture is
introduced. Tests use fictional targets and trailer values and cover all 256
possible trailer scalars without promoting any to a live-generation contract.
