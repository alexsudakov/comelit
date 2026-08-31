# P13 corrective task — COMELIT-P13-CORRECTIVE-003

## Status: SUPERSEDED FOR FIRST POC OPENING

This task is intentionally deferred until after the first successful real Door-open PoC.

Reason: native-holder reproducible-build / supply-chain provenance is useful production hardening, but it is not technically required to perform one controlled real opening on CT120 when the runtime holder identity, permissions, capability surface, target binding, one-shot execution boundary, and no-retry semantics are validated directly.

The active execution contract is now:

`safety-poc/P13_POC_DIRECT_PATH.md`

Do not perform the provenance/build-manifest work from the earlier version of this task before the first physical PoC unless a concrete runtime defect shows that it is required for the real opening.

## Still mandatory before the physical attempt

The deferral of provenance work does NOT relax the live safety boundary. The following remain required:

- target binding must be valid;
- prepared transaction must contain exactly six validated Door writes;
- the actual CT120 holder/wrapper/payload must pass runtime identity/permission/capability checks;
- exact operator approval must be required at execution time;
- one `operation_id` => at most one native transport invocation;
- `attempt_number=1`;
- durable `SEND_ARMED` before the invocation;
- no automatic retry;
- post-`SEND_ARMED` ambiguity => `UNKNOWN_OUTCOME`;
- duplicate `operation_id` never resends;
- protocol ACK != physical effect;
- `PHYSICAL_EFFECT_ASSERTED=false` from protocol evidence.

## Deferred until after PoC

- reproducible native-holder source/build provenance;
- independently reviewed holder build manifest;
- supply-chain assurance beyond runtime artifact identity;
- production release/deployment hardening not necessary for the first opening.

`I_APPROVE_P13_ONE_SHOT_PHYSICAL_DOOR_TEST` has not been granted by this document.
