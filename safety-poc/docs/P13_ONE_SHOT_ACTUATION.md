# P13 — real one-shot actuation transport

P13 is the actuation stage that follows the P12 read-only transport proof. It
reuses the proven P2P/session foundation and adds exactly the reconciled CTPP
Door transaction behind the existing typed one-shot boundary.

## Hard invariants (never weakened)

1. `SEND_ARMED` is the irreversible ambiguity boundary, persisted with
   `synchronous=FULL` before the single transport invocation.
2. One `operation_id` => at most one transport invocation.
3. `attempt_number=1` only; `TransportRequest` rejects any other value.
4. No automatic retry at any layer; `UNKNOWN_OUTCOME` is terminal for that
   operation id and is never reissued.
5. Duplicate `operation_id` returns the persisted operation and never sends
   again.
6. Protocol ACK is not proof of a physical relay move.
7. `physical_effect_asserted=true` is forbidden by construction
   (`BoundaryEvidence`, `P13ActuationEvidence`).
8. Credentials/tokens/raw secret material never enter Git, stdout, evidence
   branches, or Codex context.

## Implementation

- `src/comelit_safety_poc/p13_transport_model.py` — fixed ten-stage actuation
  plan and capability contract:
  `CLOUD_SIGNALING -> ICE -> PseudoTCP -> VIP ECHO -> UAUT open -> UAUT auth ->
  CTPP open -> six Door writes -> CTPP close -> clean teardown`.
- `src/comelit_safety_poc/p13_actuation_boundary.py` — `RealDoorActuationBoundary`
  converts exactly one `TransportRequest` into one of the five typed outcomes:
  - failure provably before any Door write => `PROVEN_NOT_SENT`;
  - ambiguous CTPP open => `AMBIGUOUS` (never downgraded);
  - failure after any Door write => `AMBIGUOUS`;
  - complete six-write transaction without Door-specific ACK =>
    `ACCEPTED_NO_ACK`, therefore `UNKNOWN_OUTCOME`;
  - prepared-body SHA-256 mismatch after channel open => `AMBIGUOUS`
    (conservative, mirrors the offline transaction model).
  The real CT120 adapter loads prepared Door bodies from the root-only payload
  file (`/root/comelit-p13-actuator-prep/real-door-payloads.json`, mode 0600)
  and binds the target to the prepared bundle fingerprint.
- `src/comelit_safety_poc/audit.py` — append-only durable audit journal
  (JSONL, fsync before acknowledgement) plus `AuditedExecutorTransport`, which
  records `transport_attempt` and `transport_outcome` for every operation.
- `scripts/p13_actuation_preflight.sh` — non-actuating preflight proving
  head/tree identity, payload presence and mode, audit-sink durability, no
  conflicting process, no retry surface, static safety, unit suite and
  contract validation, while keeping `EXPLICIT_LIVE_TEST_APPROVAL=false` and
  `LIVE_TEST_READY=false`.
- `scripts/prepare_p13_real_payloads.py` — offline, no-network preparation of
  the exact six real Door bodies from the pinned UCFG snapshot (root-only
  output, SHA-256 metadata only in evidence).

## Readiness markers

Repository-only implementation gates (this branch):

- `P13_ACTUATION_TRANSPORT_MODEL_TESTS=PASS`
- `P13_AUDIT_SINK_TESTS=PASS`
- `P13_ACTUATION_BOUNDARY_TESTS=PASS`
- `P13_ONE_SHOT_EXECUTOR_INTEGRATION_TESTS=PASS`
- `P13_ACTUATION_PREFLIGHT_TESTS=PASS`
- `P13_REAL_PAYLOAD_PREP_TESTS=PASS`
- `P13_PRIMARY_PATH=CLOUD_P2P_ICE_PSEUDOTCP_VIP_CTPP`
- `P13_ATTEMPT_NUMBER_FIXED=1`
- `P13_AUTO_RETRY_ALLOWED=false`
- `P13_PHYSICAL_EFFECT_ASSERTION_ALLOWED=false`
- `ACTUATION_TRANSPORT_IMPLEMENTED=true` (implementation exists behind the
  typed boundary; live path requires CT120 runtime verification)
- `AUDIT_SINK_VERIFIED=PASS` (durability proven by tests and by the CT120
  preflight; the live sink is exercised on CT120 only)
- `EXPLICIT_LIVE_TEST_APPROVAL=false`
- `LIVE_TEST_READY=false` until the operator supplies
  `I_APPROVE_P13_ONE_SHOT_PHYSICAL_DOOR_TEST`

## Physical test (operator-gated only)

Before any physical Door command the operator must supply the exact approval
`I_APPROVE_P13_ONE_SHOT_PHYSICAL_DOOR_TEST`. The current development task is
not that approval. After approval: one fresh `operation_id`, one transport
invocation, no automatic retry, post-`SEND_ARMED` ambiguity =>
`UNKNOWN_OUTCOME`, `PHYSICAL_EFFECT_ASSERTED=false` always.
