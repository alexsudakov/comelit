# Architecture

## Boundary

The state `SEND_ARMED` is persisted and fsync-protected by SQLite (`synchronous=FULL`) **before** the single transport call. If the process disappears after that commit, recovery cannot prove that no side effect occurred and therefore moves the operation to `UNKNOWN_OUTCOME`.

A crash in `PREPARED` is recovered as `FAILED_SAFE`. The current PoC deliberately still does **not** retry automatically; the caller must create a new operation explicitly if policy allows it.

## Idempotency

`operation_id` is the primary key. Re-running an existing operation ID returns the persisted operation and does not call the transport again.

## Rate limit

A per-target minimum interval is enforced before `SEND_ARMED`. A rate-limited request terminates as `FAILED_SAFE`, with no transport call.

## Acknowledgement semantics

`ACKED` means only that the backend returned a protocol acknowledgement in the same process execution. It is not evidence that a physical relay moved or that a door is open.

## Real transport

P13 implements the real Door actuation transport behind the typed boundary:
`RealDoorActuationBoundary` (see `P13_ONE_SHOT_ACTUATION.md`) converts exactly
one `TransportRequest` into one of the five typed outcomes using the proven
P2P/session path plus the reconciled CTPP six-write transaction.  The
repository ships the fixture session and the prepared-payload contract;
`DisabledRealTransport` remains the fail-closed placeholder for the default
CLI path until the CT120 live adapter is deployed.  Protocol ACK is never
evidence that a relay moved or that a door opened.

## Typed transport boundary (v0.2)

The executor still owns all irreversible-action semantics. A future backend is
connected only through `BoundaryTransportAdapter`, which converts exactly one
`TransportRequest(attempt_number=1)` into one of five explicit outcomes:

- `PROVEN_NOT_SENT`
- `REJECTED`
- `ACCEPTED_NO_ACK`
- `ACKED`
- `AMBIGUOUS`

Only `PROVEN_NOT_SENT` and `REJECTED` can become `FAILED_SAFE`. Both
`ACCEPTED_NO_ACK` and `AMBIGUOUS` become `UNKNOWN_OUTCOME`; `ACKED` remains a
protocol acknowledgement only.

`BoundaryEvidence` rejects any attempt to assert physical actuator state. A
future real backend therefore cannot silently upgrade protocol evidence into a
claim that a relay moved or a door opened.


## Canonical fixture bridge

`OneShotExecutor -> BoundaryTransportAdapter -> CanonicalVipFixtureBoundary -> FixtureTransport/VipSession/VipChannelSession/VipApplicationSession`. The bridge is an offline compatibility proof, not a real transport.

## Offline Door semantic plan (v0.4)

The research branch contributes only an ordered semantic call graph, pinned by source hash. v0.4 does not import or invoke the research client. Instead it models the observed sequence as symbolic steps over the already pinned canonical fixture stack. Six write steps are encoded as synthetic markers and passed through `VipSession.send_frame()` into `FixtureTransport`.

The CTPP channel requirement is a symbolic precondition only. `VipChannelSession.open_channel()` is deliberately not executed in this release because the control-plane response contract is a separate gate. This keeps v0.4 non-operational while proving sequence ordering and conservative ambiguity handling.

## v0.5 wire-shape reconciliation

v0.5 adds `CanonicalDoorWireFixtureBoundary`. It keeps the v0.4 symbolic nine-step plan, but the six write steps are reconciled against the pinned legacy framing oracle and canonical `VipSession.send_frame()` using synthetic bodies only. All six writes use the same synthetic CTPP channel id (`7449`). Byte-exact equality proves the legacy helper already adds the outer ViP header; therefore an already-framed legacy packet must never be passed as canonical `body`. A negative control proves doing so adds a second 8-byte header.
