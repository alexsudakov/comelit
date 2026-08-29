# Transport boundary contract

This document defines the only interface a future real backend may implement.
It is deliberately independent from any Comelit protocol details.

Input: `TransportRequest(operation_id, target, attempt_number=1)`.

Output: exactly one `BoundaryEvidence` with one of:

- `PROVEN_NOT_SENT`: backend can prove no side effect left its local boundary.
- `REJECTED`: request was rejected before a side effect could occur.
- `ACCEPTED_NO_ACK`: backend accepted the attempt but no protocol acknowledgement is proven.
- `ACKED`: protocol acknowledgement is proven in the same attempt.
- `AMBIGUOUS`: outcome cannot be proven.

The boundary has no retry API. `attempt_number` other than `1` is invalid.

`ACKED` does **not** assert physical relay movement. `BoundaryEvidence` rejects
`physical_effect_asserted=True` by construction.

The v0.2 PoC contains only `MockBoundary` and `DisabledBoundary`; no network or
real access-control implementation is present.
