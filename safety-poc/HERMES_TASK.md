# Hermes task — COMELIT-P13-COMPLETION-001

## Mission

Take ownership of the current `alexsudakov/comelit` development state, work locally with authorized access to CT120, and finish the Comelit Door Safety PoC from the current P12 read-only milestone through a production-ready one-shot P13 actuation implementation.

Use Codex selectively where it reduces total iteration cost. You are expected to run tests and runtime checks yourself rather than asking the operator to relay routine CT120 commands.

## Mandatory source of truth

Read first, in order:

1. `safety-poc/docs/ACCEPTANCE.md`
2. `safety-poc/docs/ARCHITECTURE.md`
3. `safety-poc/docs/CONTROL_PLANE_AND_TRANSACTION.md`
4. `safety-poc/docs/CTPP_BODY_LAYOUT_RECONCILIATION.md`
5. `safety-poc/docs/DOOR_SEMANTIC_INTEGRATION.md`
6. `safety-poc/docs/P12_READONLY_TRANSPORT_READINESS.md`
7. `safety-poc/docs/CT120_RUNTIME_GATES.md`
8. `safety-poc/docs/EVIDENCE_COLLECTION.md`
9. `safety-poc/docs/HERMES_COMPLETION_HANDOFF.md`
10. this file

Then inspect the actual current source/tests/runtime before making changes.

## Starting state

Repository: `alexsudakov/comelit`

Start from the current tip of:

`feat/p12-readonly-transport-readiness`

The last code head validated before the handoff documents were added was:

- commit `4fdcf4a1e48c7f5a047ad17d27250017c286a751`
- tree `819e533f93ddb7979a3db41ea60cb3457090ba6b`
- `offline-safety=PASS`

CT120 repository is `/root/comelit-git`.

Existing P12 live run is `20260830T113020Z`; do not repeat it simply to regenerate evidence. Close P12 locally from the preserved artifacts described in `HERMES_COMPLETION_HANDOFF.md`.

## Required work

### A. Finalize/freeze P12

- sync current branch;
- validate preserved UCFG SHA and `TARGET_BINDING_VERIFIED=PASS`;
- run preserved-live reclassification;
- run final readiness aggregation;
- require `READONLY_TRANSPORT_READY=true` and `LIVE_TEST_READY=false`;
- create/push public-safe P12 final evidence with hashes/markers only.

### B. Implement P13

Create a dedicated branch/worktree, preferably `feat/p13-one-shot-actuation`.

Implement the real Door transport behind the existing typed boundary and state machine. Reuse the proven Cloud P2P/ICE/PseudoTCP/ViP session path and the already reconciled CTPP/Door transaction semantics.

Do not bypass `OneShotExecutor`, persistence, idempotency, audit, rate limiting, or target binding.

### C. Test aggressively without physical sends

Run/fix until green:

- repository unit suite;
- static safety checks;
- shell parse checks;
- all v0.6 and P12 regressions;
- real-adapter fixture/mocked tests;
- duplicate-operation tests;
- crash/timeout/ambiguity mapping tests;
- audit durability tests;
- target-binding tests;
- credential/log redaction tests;
- CI.

Use CT120 directly for runtime tests and diagnostics. Batch related fixes and rerun the smallest relevant tests first, then the complete suite.

### D. Prepare P13 non-actuating preflight

Prove on CT120, without issuing the Door command:

- exact head/tree/runtime hashes;
- exact target binding;
- real actuation transport installed/available;
- audit sink verified/durable;
- one-shot process/executor behavior;
- no retry path;
- no conflicting live process;
- no credential emission;
- `ACTUATION_TRANSPORT_IMPLEMENTED=true`;
- `AUDIT_SINK_VERIFIED=PASS`;
- `EXPLICIT_LIVE_TEST_APPROVAL=false`;
- `LIVE_TEST_READY=false` until operator approval is supplied.

### E. STOP for explicit physical approval

Before any physical Door command, stop and ask the operator for an explicit approval equivalent to:

`I_APPROVE_P13_ONE_SHOT_PHYSICAL_DOOR_TEST`

The current task assignment is **not** that final physical approval.

### F. After approval only: one physical test

Use exactly one fresh `operation_id` and exactly one physical transport invocation.

- persist `SEND_ARMED` durably before the one transport call;
- no automatic retry anywhere;
- pre-`SEND_ARMED` proven-unsent failure => `FAILED_SAFE`;
- post-`SEND_ARMED` ambiguity/timeout/crash/disconnect => `UNKNOWN_OUTCOME`;
- `UNKNOWN_OUTCOME` is never retried automatically;
- protocol ACK does not prove the relay moved;
- `PHYSICAL_EFFECT_ASSERTED=false` always;
- record operator observation separately if available.

Do not use repeated physical sends for fault testing.

### G. Production completion

After the one-shot result is classified and reviewed:

- finish restricted operator/Home Assistant integration;
- prevent bypass of the state-machine boundary;
- preserve operation-id idempotency/rate limiting;
- create immutable deployment + rollback;
- run full CT120 regression after deploy;
- update documentation/readiness/evidence;
- open/update PR with exact commit/tree/CI/runtime evidence;
- do not merge unresolved safety gates.

## Hard invariants

Never weaken these:

1. `SEND_ARMED` is the irreversible ambiguity boundary.
2. One `operation_id` => at most one transport invocation.
3. `attempt_number=1` only.
4. No automatic retry.
5. Post-`SEND_ARMED` uncertainty => `UNKNOWN_OUTCOME`.
6. Duplicate operation IDs never send again.
7. ACK != physical effect.
8. `physical_effect_asserted=true` is forbidden.
9. Credentials/tokens/raw secret material are never committed or sent to Codex.
10. P12 and P13 remain separate gates.

## Codex usage policy

Use Codex when economically justified for substantive multi-file implementation, deterministic test creation/fixes, focused diagnosis of a failing test cluster, or review of a non-trivial diff.

Prefer Hermes/local shell directly for git, CT120 runtime diagnostics, builds/tests, hashes/modes/processes, tiny fixes, and all work involving credentials or unsanitized live output.

Do not repeatedly call Codex on the same unresolved issue. Inspect first, then delegate one focused corrective task.

## If agent/tool-call limits are hit

Do not restart the project. Preserve state at a coherent commit boundary and report:

- `CONTINUATION_REQUIRED=true`
- branch/head/tree
- completed phase
- changed files
- failing command/output summary
- whether any network action occurred
- whether any physical action occurred
- current `operation_id`, if any
- whether `SEND_ARMED` was ever reached
- exact next action

Wait for operator permission to continue. If `SEND_ARMED` was reached, never reissue that operation.

## Final report

Return a concise but exact report containing:

- final branch/commit/tree;
- PR number/status;
- CI runs/results;
- P12 final evidence branch/commit;
- P13 implementation summary;
- CT120 test matrix and results;
- deployed release/rollback paths;
- audit/readiness markers;
- physical one-shot `operation_id` and classification if operator approved it;
- explicit statement of whether a physical Door action occurred;
- explicit statement that no automatic retry occurred;
- unresolved items, if any.

Only report `TASK_RESULT=DONE` when the definition of done in `safety-poc/docs/HERMES_COMPLETION_HANDOFF.md` is satisfied.
