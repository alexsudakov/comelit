# Real-transport readiness and Home Assistant contract

## Readiness evaluator

`readiness.py` intentionally separates repository readiness from live-test readiness.

Repository gates require all offline structural/session/transaction proofs and core safety invariants. Live gates additionally require a real transport implementation, read-only session proof, exact target binding, authentication/session-lifetime proof, timeout mapping, an audit sink, and an explicit live-test approval marker.

`evaluate_readiness()` cannot infer missing evidence: missing markers remain `MISSING`, mismatched markers are `FAIL`, and `live_test_ready` can become true only if every repository and live marker has the expected value.

No repository-only commit may set `EXPLICIT_LIVE_TEST_APPROVAL=true` on behalf of the operator.

## Home Assistant service contract

The future integration surface is fixed as `comelit.open_door` with a mandatory caller-supplied `operation_id` and explicit target.

The contract requires:

- no automatic retry;
- duplicate operation ids remain idempotent through the backend journal;
- `FAILED_SAFE`, `ACKED`, and especially `UNKNOWN_OUTCOME` are surfaced to the caller;
- `ACKED` remains protocol evidence only;
- no result object may assert physical Door state;
- HA must not convert a timeout or `UNKNOWN_OUTCOME` into an implicit retry.

Actual Home Assistant registration/config-entry code is intentionally deferred until the real transport and explicit live-test gates are complete. This avoids creating an operational access-control surface before the backend has been proven.
