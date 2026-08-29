# P12 — real transport read-only readiness

P12 is the first stage allowed to exercise a real Comelit session, but it is **not** an actuation stage.

The safety objective is to prove that a real session can be established, authenticated, used for configuration/target discovery, and closed while the actuator path remains unavailable.

## Three readiness levels

The project uses three independent readiness levels:

1. `REPOSITORY_READY` — offline body/control-plane/full-transaction proofs and one-shot safety invariants are complete.
2. `READONLY_TRANSPORT_READY` — a real session has been proven for read-only application semantics with exact target/auth/lifetime/timeout evidence and no actuator command attempt.
3. `LIVE_TEST_READY` — requires read-only readiness plus a separate actuation implementation, audit proof, and explicit operator approval.

A PASS at level 1 or 2 can never imply level 3.

## Fixed read-only application plan

The only allowed P12 application sequence is:

`CONNECT -> AUTHENTICATE -> LOAD_CONFIGURATION -> DISCOVER_TARGETS -> CLOSE`

Session-control and query protocol writes are allowed because a network session cannot be established otherwise. They are not Door/relay actions.

The P12 contract forbids:

- actuator-command capability;
- credential export or logging;
- automatic retry;
- physical-effect assertions;
- any implicit promotion from protocol/session success to a physical Door claim.

## Repository-only work

This branch adds:

- `readonly_session.py` with the fixed five-step plan and fail-closed capability contract;
- a separate `READONLY_GATES` layer in `readiness.py`;
- `p12_readonly_source_inventory.py`, an AST-only inventory of the pinned legacy read-only call chain and canonical session interfaces;
- `collect_p12_readonly_evidence.sh`, which records public-safe source/runtime metadata and pushes it to a dedicated evidence branch;
- tests proving that read-only readiness cannot imply live-test readiness.

No network implementation is added by this repository-only stage.

## Source-evidence stage

The first CT120 P12 action is still **no-network**. The collector inventories, without executing the research source:

- legacy connection and shutdown method shapes;
- authentication, configuration and target-discovery method shapes;
- the top-level read-only discovery wrapper call graph;
- canonical transport/session/channel/application interface shapes;
- statically visible timeout values used by selected methods;
- current immutable release identity;
- credential-directory metadata only (presence/mode/file count), never names or contents.

The evidence bundle must report:

- `P12_READONLY_SOURCE_INVENTORY=PASS`;
- `PUBLIC_SAFE_EVIDENCE=PASS`;
- `SECRETS_CONTENT_READ=false`;
- `CREDENTIAL_VALUES_COLLECTED=false`;
- `ACTIVE_COMELIT_NETWORK_PROBES=false`;
- `ACTUATOR_COMMAND_ATTEMPTED=false`;
- `PHYSICAL_DOOR_ACTION=false`.

## Later real-session gate

Only after the source inventory is reviewed may a separate real-session probe be implemented. That probe must be limited to the fixed read-only application plan and must emit evidence for:

- `REAL_TRANSPORT_IMPLEMENTED=true`;
- `REAL_TRANSPORT_READONLY_SESSION_PROOF=PASS`;
- `READONLY_SCOPE_ENFORCED=PASS`;
- `TARGET_BINDING_VERIFIED=PASS`;
- `AUTH_SESSION_LIFETIME_VERIFIED=PASS`;
- `TIMEOUT_MAPPING_VERIFIED=PASS`;
- `CREDENTIAL_MATERIAL_EMITTED=false`;
- `ACTUATOR_COMMAND_ATTEMPTED=false`.

Even if all of those pass, `LIVE_TEST_READY` remains false until the later live-only gates pass:

- `ACTUATION_TRANSPORT_IMPLEMENTED=true`;
- `AUDIT_SINK_VERIFIED=PASS`;
- `EXPLICIT_LIVE_TEST_APPROVAL=true`.

P12 therefore cannot authorize a Door action by construction.
