# Hermes completion handoff — Comelit Door Safety PoC

Prepared: 2026-08-30

This document is the handoff for finishing the Comelit integration on the owner's own CT120 infrastructure. Treat Git/runtime evidence as authoritative; do not reconstruct state from chat history unless needed for context.

## 1. Objective

Finish the project from the current P12 read-only milestone through a production-usable, one-shot Door actuation path, with the existing safety model preserved exactly.

The desired end state is:

1. P12 read-only transport proof finalized and frozen as evidence.
2. Real actuation transport implemented behind the existing boundary/state-machine contract.
3. Full offline/unit/runtime validation completed on CT120.
4. P13 live-actuation preflight completed without physical actuation.
5. `LIVE_TEST_READY=true` only after all live-only gates except the operator approval are proven.
6. Stop and ask the operator for an explicit one-shot P13 physical approval.
7. After that explicit approval only: execute exactly one physical Door operation with a fresh `operation_id`, never retry automatically, classify any post-`SEND_ARMED` ambiguity as `UNKNOWN_OUTCOME`.
8. Finish integration/evidence/docs/PR so the project can be used through the restricted operator/Home Assistant surface.

## 2. Repository and CT120 state

Repository: `alexsudakov/comelit`

Current development branch before this handoff:

- branch: `feat/p12-readonly-transport-readiness`
- validated code head: `4fdcf4a1e48c7f5a047ad17d27250017c286a751`
- validated tree: `819e533f93ddb7979a3db41ea60cb3457090ba6b`
- GitHub Actions `offline-safety` run for that head: PASS

CT120 repository:

- `/root/comelit-git`

Deployed immutable v0.6 runtime:

- current release: `/opt/comelit-door-safety-poc/releases/2026-08-29-v0.6.0-f01d8c610daf`
- rollback: `/opt/comelit-door-safety-poc/releases/2026-08-29-v0.5-eba2900dc82e`

Do not overwrite the immutable release in place. Produce a new release only after the new tree is fully validated.

Credential-bearing location:

- `/root/.config/comelit/`

Credential values may be read by the runtime only when necessary for authenticated Comelit operation. They must never be committed, copied into public evidence, printed in reports, or sent to Codex/other external model contexts.

## 3. Canonical P12 live result already obtained

Do **not** repeat the P12 live network run merely to reproduce evidence. The existing one-shot run already proved the real read-only session.

Preserved run identity:

- timestamp: `20260830T113020Z`
- service log: `/root/comelit-p12-readonly-live-service/20260830T113020Z.log`
- preserved UCFG: `/run/comelit-p2p/p12-ucfg-response.json`
- UCFG SHA256: `d31dca0fa13a57d3cbc600510149b3ad2a29c43e20949190ec62b44321d310b7`
- target-v2 report: `/root/comelit-p12-readonly-live/20260830T113020Z.target-v2.txt`

Observed real read-only markers:

- `P12_ONE_SHOT_PROCESS_INVOCATIONS=1`
- `P12_ONE_SHOT_AUTO_RETRY=false`
- `P12_ONE_SHOT_PROCESS_GROUP_ISOLATED=true`
- `TIMEOUT_MAPPING_VERIFIED=PASS`
- `P12_READONLY_LIVE_RUN_PERFORMED=true`
- `P12_READONLY_LIVE_WRAPPER_INVOCATIONS=1`
- `P12_READONLY_LIVE_WRAPPER_OUTCOME=COMPLETED`
- `P12_READONLY_LIVE_WRAPPER_RC=0`
- `P2_VIP_UAUT_AUTH=PASS`
- `UAUT_RESPONSE_CODE=200`
- `VIP_UAUT_CLOSE_RESPONSE=PASS`
- `VIP_UAUT_CLOSE_RESPONSE_WORD=0`
- `VIP_UCFG_OPEN_RESPONSE=PASS`
- `VIP_UCFG_OPEN_RESPONSE_WORD=0`
- `UCFG_RECEIVED=true`
- `VIP_UCFG_CLOSE_RESPONSE=PASS`
- `VIP_UCFG_CLOSE_RESPONSE_WORD=0`
- `P12_READONLY_TRANSACTION=PASS`
- `READONLY_SCOPE_ENFORCED=PASS`
- `AUTH_SESSION_LIFETIME_VERIFIED=PASS`
- `CREDENTIAL_MATERIAL_EMITTED=false`
- `ACTUATOR_COMMAND_ATTEMPTED=false`
- `AUTO_RETRY_OBSERVED=false`
- `PHYSICAL_DOOR_ACTION=false`
- `PHYSICAL_EFFECT_ASSERTED=false`

The original target verifier failed only because the real UCFG did not contain `model`/`version`. The corrected verifier uses the unique required pair `apt-address + apt-subaddress`; optional `model/version` must match only when present.

The saved target-v2 result is:

- `P12_TARGET_APT_ADDRESS_MATCH=true`
- `P12_TARGET_APT_ADDRESS_OBSERVED_SCALARS=1`
- `P12_TARGET_APT_SUBADDRESS_MATCH=true`
- `P12_TARGET_APT_SUBADDRESS_OBSERVED_SCALARS=1`
- `P12_TARGET_APT_ADDRESS_UNIQUE=true`
- `P12_TARGET_APT_SUBADDRESS_UNIQUE=true`
- `P12_TARGET_MODEL_CONTEXT_COMPATIBLE=true`
- `P12_TARGET_VERSION_CONTEXT_COMPATIBLE=true`
- `TARGET_BINDING_VERIFIED=PASS`

The current branch contains a local-only preserved-run reclassifier and finalizer. Use those saved artifacts to close P12; no second network session is required.

## 4. Mandatory reading order

Before changing code, read:

1. `safety-poc/docs/ACCEPTANCE.md`
2. `safety-poc/docs/ARCHITECTURE.md`
3. `safety-poc/docs/CONTROL_PLANE_AND_TRANSACTION.md`
4. `safety-poc/docs/CTPP_BODY_LAYOUT_RECONCILIATION.md`
5. `safety-poc/docs/DOOR_SEMANTIC_INTEGRATION.md`
6. `safety-poc/docs/P12_READONLY_TRANSPORT_READINESS.md`
7. `safety-poc/docs/CT120_RUNTIME_GATES.md`
8. `safety-poc/docs/EVIDENCE_COLLECTION.md`
9. this file
10. `safety-poc/HERMES_TASK.md`

Also inspect current source/tests rather than assuming these docs are complete.

## 5. Non-negotiable safety semantics

These are architectural invariants, not suggestions.

### Irreversible boundary

`SEND_ARMED` is the irreversible ambiguity boundary.

- Before `SEND_ARMED`, a failure may be `FAILED_SAFE` only when the implementation can prove the request was not sent.
- After `SEND_ARMED`, any uncertainty about whether the physical command was transmitted or acted upon must become `UNKNOWN_OUTCOME`.
- `UNKNOWN_OUTCOME` is terminal for that `operation_id` and is never automatically retried.

### Exactly one invocation

For one `operation_id`:

- `attempt_number=1` only;
- at most one boundary/transport invocation;
- no retry loop at any layer;
- no watchdog or recovery logic may silently reissue the Door command;
- duplicate `operation_id` returns persisted state and never sends again.

### ACK semantics

A protocol acknowledgement is not proof that the relay moved or the door physically opened.

- `physical_effect_asserted=true` is forbidden.
- external human observation may be recorded separately as observation, but must not be synthesized from protocol ACK.

### Fault injection

Fault injection and repeated attempts are allowed only against fixture/mock transports. Never use repeated physical sends to test timeout/crash behavior.

### P12/P13 separation

P12 remains read-only.

P13 is a separate actuation stage and requires all of:

- `READONLY_TRANSPORT_READY=true`
- `ACTUATION_TRANSPORT_IMPLEMENTED=true`
- `AUDIT_SINK_VERIFIED=PASS`
- exact target binding
- deterministic one-shot executor
- no automatic retry
- explicit abort/timeout classification
- `EXPLICIT_LIVE_TEST_APPROVAL=true` supplied by the operator at the final physical execution step

No repository commit, test, or agent may set the operator approval marker on the user's behalf.

## 6. Proven transport/protocol direction

The working real transport foundation is:

`cloud signaling -> ICE -> PseudoTCP -> ViP -> session channels`

Do not replace this with direct LAN/public TCP as the primary path unless new evidence proves a justified architectural change.

P12 has already proven:

`P2P -> ICE -> PseudoTCP -> ECHO -> UAUT open -> UAUT auth 200 -> UAUT close -> UCFG open -> UCFG read -> UCFG close -> clean teardown`.

For actuation, use the already reconciled canonical/offline CTPP Door transaction semantics and existing boundary adapter rather than inventing a second transaction model.

The canonical offline project has already proven:

- CTPP control-plane open/close shape;
- six Door data writes in fixed order;
- all six writes share one CTPP channel;
- legacy/canonical framing reconciliation;
- exactly eight fixture writes for full transaction = two control + six Door data;
- post-send ambiguity is conservative.

## 7. Recommended implementation sequence

Hermes may optimize sequencing, but do not skip gates.

### Phase A — close P12 without network

1. Sync the feature branch.
2. Validate the saved UCFG SHA and target-v2 report.
3. Run the preserved-live reclassifier.
4. Combine it with the existing repository runtime-gate report using `p12_finalize_readonly_readiness.py`.
5. Require:
   - `REPOSITORY_READY=true`
   - `READONLY_TRANSPORT_READY=true`
   - `LIVE_TEST_READY=false`
   - `PHYSICAL_DOOR_ACTION=false`
6. Add a public-safe P12 final evidence collector if one does not yet exist; evidence must contain hashes/markers only, never raw credentials or target identity values.
7. Commit/push the evidence branch and record exact commit/tree.

### Phase B — implement P13 actuation transport

1. Create a dedicated feature branch from the P12-complete head, e.g. `feat/p13-one-shot-actuation`.
2. Implement the real transport behind the existing typed boundary. Do not bypass `OneShotExecutor`/state persistence.
3. Reuse the proven P2P/session setup and the reconciled CTPP transaction sequence.
4. Bind the target to the already proven apartment/subaddress identity without emitting those values publicly.
5. Keep credentials root-only and runtime-only.
6. Map all pre-boundary failures that are provably unsent to `PROVEN_NOT_SENT`/`FAILED_SAFE`.
7. Once `SEND_ARMED` is persisted, any uncertain transport result maps to `AMBIGUOUS`/`UNKNOWN_OUTCOME`.
8. An explicit protocol rejection may map to `REJECTED` only when the implementation can prove the Door command was not accepted/sent in a side-effect-capable way.
9. Do not infer physical effect from ACK.

### Phase C — deterministic tests before physical action

Required before P13 live approval:

- complete repository unit suite PASS;
- static safety scan PASS;
- shell syntax checks PASS;
- all existing v0.6/P12 regressions PASS;
- fixture tests for the real adapter mapping using mocks only;
- duplicate `operation_id` cannot send twice;
- crash before `SEND_ARMED` -> `FAILED_SAFE`;
- crash/timeout after `SEND_ARMED` -> `UNKNOWN_OUTCOME`, no retry;
- control-plane rejection/ambiguity mapping tests;
- exact target binding tests;
- audit sink persistence and fsync/durability verification;
- credentials are not emitted to stdout, evidence, git, CI, or Codex context;
- preflight proves one live invocation maximum;
- `PHYSICAL_EFFECT_ASSERTED=false` throughout.

### Phase D — CT120 non-actuating runtime preflight

Run all repository and runtime checks on CT120 using the real environment, but stop before the actuator send boundary.

The final non-actuating preflight should prove at minimum:

- exact source head/tree;
- exact candidate/binary/runtime hashes if native components are used;
- target binding verified;
- credential container permissions correct;
- no conflicting process active;
- audit sink writable and durable;
- one-shot supervisor/process-group behavior;
- no retry surface;
- no stale `operation_id` collision;
- `ACTUATION_TRANSPORT_IMPLEMENTED=true`;
- `AUDIT_SINK_VERIFIED=PASS`;
- `EXPLICIT_LIVE_TEST_APPROVAL=false`;
- `LIVE_TEST_READY=false` until operator approval is actually supplied.

### Phase E — explicit operator gate

At this point STOP and ask the operator for an explicit approval equivalent to:

`I_APPROVE_P13_ONE_SHOT_PHYSICAL_DOOR_TEST`

Do not treat this handoff or the original request to "finish development" as that final physical approval.

### Phase F — one physical one-shot test, after approval only

After explicit approval:

1. create one fresh `operation_id`;
2. verify exact target and all P13 preflight hashes immediately before the run;
3. persist `PREPARED` and then durable `SEND_ARMED` before the one transport invocation;
4. invoke the physical transport exactly once;
5. never retry automatically, including after timeout, console disconnect, process crash, SSH loss, or ambiguous ACK;
6. classify uncertain post-`SEND_ARMED` result `UNKNOWN_OUTCOME`;
7. protocol ACK may become `ACKED` but still `PHYSICAL_EFFECT_ASSERTED=false`;
8. record operator-observed physical result separately if available;
9. collect public-safe evidence and freeze it before any later operation.

### Phase G — production completion

After the one-shot result is reviewed:

- complete the restricted operator/Home Assistant integration using the existing one-shot service contract;
- ensure arbitrary shell/secrets access is not exposed;
- keep rate limiting and `operation_id` idempotency;
- add immutable deployment/rollback metadata;
- run full CT120 regression suite after deployment;
- update docs/acceptance/readiness markers;
- open/update PR with exact test/evidence references;
- do not merge to `main` if any safety gate is unresolved.

## 8. Use of Codex — economic policy

Hermes is the orchestrator and owner of runtime decisions. Use Codex selectively when it reduces total iteration cost.

Good Codex tasks:

- multi-file Python/C implementation changes;
- adding or repairing deterministic tests;
- refactoring the real transport into the existing typed boundary;
- analyzing a failing unit-test cluster;
- preparing a minimal patch after Hermes has isolated the failure;
- code review of a substantive diff.

Prefer Hermes/local shell directly for:

- git operations;
- reading current files;
- CT120 diagnostics;
- running tests/builds;
- checking hashes/modes/processes;
- interpreting runtime markers;
- small one-line/tiny deterministic fixes;
- any operation involving real credentials or unsanitized credential-bearing runtime output.

Never provide Codex with credential values, tokens, raw secret files, or unsanitized live logs that may contain sensitive values. Pass only sanitized structural evidence.

Do not repeatedly ask Codex the same question. Inspect the failure first, then send one focused corrective task with the failing test/output and invariants.

## 9. Iteration/call-limit continuity

If Hermes hits an agent/model/tool-call limit:

1. do not abandon or restart the task;
2. commit or stash only coherent work; prefer a commit boundary;
3. write/update a local continuation report containing:
   - current branch/head/tree;
   - completed phase;
   - failing command and exact failure;
   - changed files;
   - whether any network or physical action occurred;
   - current operation_id if one exists;
   - whether `SEND_ARMED` was ever reached;
   - next exact command/action;
4. report `CONTINUATION_REQUIRED=true` to the operator and wait for permission to continue.

If an actuation operation reached `SEND_ARMED`, continuation must never reissue it. Preserve `UNKNOWN_OUTCOME` semantics.

## 10. Git/worktree rules

- Pull/fetch before starting.
- Work on named feature branches/worktrees; do not develop directly on `main`.
- Never force-push `main`.
- Keep commits small enough to review but do not split one invariant across incoherent commits.
- Run relevant tests before every push.
- GitHub Actions must be green before presenting a phase as complete.
- Public evidence belongs on dedicated `evidence/...` branches where practical.
- Do not commit raw CT120 live logs, credentials, target identity values, tokens, endpoints requiring secrecy, or private keys.

## 11. Definition of done

The development task is complete only when all of the following are true:

- P12 final evidence proves `READONLY_TRANSPORT_READY=true`.
- Real P13 actuation transport exists behind the typed one-shot boundary.
- All offline/CI/runtime tests are green.
- Audit sink is verified.
- P13 preflight is reproducible and fail-closed.
- Exactly one explicitly approved physical test has been classified without automatic retry, or the operator has chosen to stop before the physical test.
- Any ambiguous physical attempt is preserved as `UNKNOWN_OUTCOME` and never retried automatically.
- Protocol ACK is not reported as physical proof.
- restricted/Home Assistant integration cannot bypass the safety boundary.
- immutable deployment and rollback are prepared/verified.
- documentation/evidence/PR accurately reflect the final state.

Do not report `DONE` merely because the Door command path compiles or because a protocol ACK was observed.
