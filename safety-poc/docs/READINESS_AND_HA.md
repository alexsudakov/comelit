# Transport readiness and Home Assistant contract

## Three readiness levels

`readiness.py` separates three independent levels:

1. `REPOSITORY_READY` — offline structural/session/transaction proofs and core one-shot safety invariants.
2. `READONLY_TRANSPORT_READY` — a real session has been proven only for connect/auth/configuration/target-discovery/close semantics.
3. `LIVE_TEST_READY` — a later actuation transport, audit proof, and explicit operator approval are all present in addition to the first two levels.

Missing markers remain `MISSING`; mismatched markers are `FAIL`. A higher readiness level cannot become true unless every lower level is already true.

## Repository gates

Repository gates cover canonical/legacy source pins, body/control-plane/full-transaction reconciliation, the transport-boundary contract, fixed single attempt, no automatic retry, and no physical-effect assertion.

## Read-only real-session gates

P12 read-only readiness requires:

- `REAL_TRANSPORT_IMPLEMENTED=true` for a transport that is exposed only through the read-only session surface;
- `REAL_TRANSPORT_READONLY_SESSION_PROOF=PASS`;
- `READONLY_SCOPE_ENFORCED=PASS`;
- `TARGET_BINDING_VERIFIED=PASS`;
- `AUTH_SESSION_LIFETIME_VERIFIED=PASS`;
- `TIMEOUT_MAPPING_VERIFIED=PASS`;
- `CREDENTIAL_MATERIAL_EMITTED=false`;
- `ACTUATOR_COMMAND_ATTEMPTED=false`.

The fixed P12 application plan is:

`CONNECT -> AUTHENTICATE -> LOAD_CONFIGURATION -> DISCOVER_TARGETS -> CLOSE`.

A successful read-only session therefore proves connectivity/session behavior, not permission or capability to actuate a relay.

## Live-only gates

`LIVE_TEST_READY=true` additionally requires all of:

- `ACTUATION_TRANSPORT_IMPLEMENTED=true`;
- `AUDIT_SINK_VERIFIED=PASS`;
- `EXPLICIT_LIVE_TEST_APPROVAL=true`.

No repository-only commit or read-only probe may set the explicit approval marker on behalf of the operator.

## Home Assistant service contract

The future integration surface remains `comelit.open_door` with a mandatory caller-supplied `operation_id` and explicit target.

The contract requires:

- no automatic retry;
- duplicate operation ids remain idempotent through the backend journal;
- `FAILED_SAFE`, `ACKED`, and especially `UNKNOWN_OUTCOME` are surfaced to the caller;
- `ACKED` remains protocol evidence only;
- no result object may assert physical Door state;
- HA must not convert a timeout or `UNKNOWN_OUTCOME` into an implicit retry.

Actual Home Assistant registration/config-entry code remains blocked until P12 read-only readiness and P13 live-actuation gates are independently completed. This avoids creating an operational access-control surface merely because read-only connectivity works.
