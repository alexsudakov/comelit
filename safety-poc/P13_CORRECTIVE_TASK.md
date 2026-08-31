# P13 corrective task — COMELIT-P13-CORRECTIVE-001

## Status

Continue development on `feat/p13-one-shot-actuation`.

Do **not** merge PR #3 and do **not** request operator physical approval until every blocker below is closed and CT120 non-actuating preflight passes from the real runtime implementation.

Initial reviewed remote state:

- HEAD `be04d59e9782af35ef9f4280c445c1698936c102`
- actual Git tree `f884980dc2b16e482d69c06d4c445af47ae1e5bd`
- CI `33311964988` reported success
- P12 evidence branch `evidence/p12-final-20260830T122355Z`, HEAD `7c36c75a6c5db91147867f516ef0625335dd348c`, tree `1a8466f8f663620aa646dd01750a0798f391a7b7`
- `READONLY_TRANSPORT_READY=true`
- no physical Door action has occurred

The previous report incorrectly stated P13 tree `f0b9ae0a30f77f61e2e97404191eb85c5b9b04c5`; use exact remote Git identities in all future reports.

## Blocker 1 — real P13 transport/session adapter is missing

Current repository state is not a real actuation implementation:

- `P13DoorSession` is only a `Protocol`;
- the only concrete P13 session is `FixtureP13DoorSession`;
- CLI backends are `mock`, `real-disabled`, and `p13-fixture`;
- no concrete adapter currently establishes the proven real path
  `Cloud P2P -> ICE -> PseudoTCP -> ViP -> UAUT -> CTPP` and then performs the six prepared Door writes.

Therefore `ACTUATION_TRANSPORT_IMPLEMENTED=true` is currently an overclaim.

### Required correction

Implement a concrete CT120 real P13 session/adapter that reuses the P12-proven real transport foundation and exposes the typed `P13DoorSession` contract to `RealDoorActuationBoundary`.

The implementation may be Python/native/root-only as technically justified, but it must be versioned/reproducible enough that preflight can pin its source/binary/runtime hashes.

It must:

1. perform the real Cloud signaling / ICE / PseudoTCP / ViP session setup;
2. authenticate UAUT using runtime-only credentials without emitting them;
3. open exactly one CTPP channel for the one operation;
4. expose `write_door_body()` for exactly the six prepared bodies;
5. close CTPP and teardown the session;
6. contain no automatic retry loop;
7. expose unambiguous typed failure information so `PROVEN_NOT_SENT` is used only when non-send is actually proven;
8. never assert physical effect.

Do not create an alternate transaction model. Reuse the reconciled P13 bundle and existing typed boundary.

## Blocker 2 — unsafe CTPP-open exception classification

Current `RealDoorActuationBoundary.attempt_once()` can classify an exception thrown by `session.open_ctpp()` as `PROVEN_NOT_SENT` because `opened == false` and `writes == 0`.

That is unsafe. A timeout, disconnect, process interruption, or protocol parse failure during/after the CTPP open request may be ambiguous even though no Door body has yet been counted locally.

### Required correction

Use explicit typed semantics for CTPP open, e.g. distinguish:

- explicit proven rejection / proven no-send -> `PROVEN_NOT_SENT` or `REJECTED` as appropriate;
- ambiguous response/timeout/disconnect/exception after open may have been transmitted -> `AMBIGUOUS`;
- successful open -> continue.

A generic exception from the real open operation must default to `AMBIGUOUS`, not `PROVEN_NOT_SENT`, unless the adapter can prove the request was never emitted.

Add deterministic tests for thrown timeout/disconnect/parse errors before/after transmission and prove they map conservatively.

## Blocker 3 — complete transaction predicate must require exactly six writes

`P13ActuationEvidence.actuation_transaction_complete` currently accepts `door_write_count >= 1`.

The fixed transaction is exactly six Door data writes.

### Required correction

Require `door_write_count == 6` and add negative tests for 0, 1, 5, 7 writes.

## Blocker 4 — preflight hardcodes implementation readiness

`p13_actuation_preflight.sh` currently emits `ACTUATION_TRANSPORT_IMPLEMENTED=true` after checking payload/audit/test/model state, but does not prove a concrete real session adapter exists or is installed/pinned on CT120.

### Required correction

Preflight may emit `ACTUATION_TRANSPORT_IMPLEMENTED=true` only after proving, without sending a Door command:

- exact real-adapter source/binary/module identity;
- expected ownership/modes;
- import/load/linkage/runtime dependencies;
- binding to the current P13 source HEAD/TREE;
- real adapter can be constructed in a non-actuating/dry initialization mode;
- no network/actuator command is performed by preflight unless separately designed as a read-only P12-equivalent probe;
- no retry surface;
- exact target/payload binding is valid.

Do not hardcode readiness markers that are not derived from verified runtime state.

## Blocker 5 — audit runtime proof is insufficient

Current preflight checks mode and JSON parseability of the audit file but does not itself prove a real append + flush + fsync + reopen cycle before emitting `AUDIT_SINK_VERIFIED=PASS`.

### Required correction

Perform a non-actuating CT120 audit durability proof:

1. append a dedicated `preflight`/`audit_sink_verify` event through the real `AuditSink` API;
2. flush/fsync;
3. close/reopen;
4. verify the exact new entry and valid journal structure;
5. keep permissions root-only;
6. do not log credentials/target identity values.

Only then emit `AUDIT_SINK_VERIFIED=PASS`.

## Blocker 6 — physical one-shot runner/service is missing

Repository currently has fixture CLI integration but no separate operator-gated real one-shot execution surface.

### Required correction

Implement a dedicated P13 physical runner/service, but do not execute it yet.

Requirements:

- exact approval token `I_APPROVE_P13_ONE_SHOT_PHYSICAL_DOOR_TEST` required at execution time;
- approval is not persisted or implied by this task;
- one fresh `operation_id` supplied/generated exactly once;
- durable SQLite state with `SEND_ARMED` committed before exactly one transport invocation;
- audit sink enabled and verified before arming;
- exact target fingerprint and payload/UCFG hashes checked immediately before arming;
- no retry in shell, systemd, supervisor, Python, native adapter, recovery, or wrapper layers;
- disconnect/timeout/crash after `SEND_ARMED` -> `UNKNOWN_OUTCOME`;
- duplicate operation id -> return persisted result, never send;
- runner output must never contain payload bodies, credentials, tokens, or raw sensitive UCFG values;
- protocol ACK never sets `PHYSICAL_EFFECT_ASSERTED=true`.

Use a detached one-shot service/supervisor if needed so console loss does not trigger a second operator attempt.

## Blocker 7 — restricted operator / Home Assistant production path is not complete

The completion task requires a production-usable restricted operator/Home Assistant surface. Current CLI exposes only fixture P13 execution.

### Required correction

After the real adapter and one-shot runner are safe and tested, wire the restricted operator/HA service through the existing state-machine boundary only. It must not expose arbitrary shell, credential reads, direct raw transport, or a bypass around `operation_id`/rate-limit/audit semantics.

This production integration may be completed before the physical test, but remains disabled/fail-closed until the explicit operator approval/live gate.

## Required test matrix before CT120 preflight

At minimum add/retain tests proving:

- full repository unit suite PASS;
- all prior v0.6/P12 tests PASS;
- real-adapter mocked protocol sequencing exactly once;
- no retry in any adapter/runner layer;
- explicit pre-send rejection -> safe classification;
- exception/timeout/disconnect during CTPP open -> `AMBIGUOUS` unless non-send is proven;
- partial Door write -> `AMBIGUOUS`;
- six writes exactly -> complete transaction path;
- 0/1/5/7 writes cannot satisfy `actuation_transaction_complete`;
- duplicate `operation_id` invokes real boundary at most once;
- crash before `SEND_ARMED` -> `FAILED_SAFE`;
- crash after `SEND_ARMED` -> `UNKNOWN_OUTCOME` without retry;
- body hash mismatch is fail-closed/conservative;
- target mismatch is fail-closed;
- audit append/fsync/reopen proof;
- credentials/payload bodies absent from stdout/evidence/CI;
- `PHYSICAL_EFFECT_ASSERTED=false` always;
- preflight cannot claim `ACTUATION_TRANSPORT_IMPLEMENTED=true` when real adapter artifact/module is absent or wrong hash.

Run focused tests first, then full suite and GitHub CI.

## CT120 non-actuating preflight

Hermes must run this itself with authorized root access or arrange the authorized local execution path; do not hand routine CT120 commands back to the operator if Hermes has access.

The preflight must perform **no physical Door send** and finish with independently proven markers:

- `READONLY_TRANSPORT_READY=true`
- `ACTUATION_TRANSPORT_IMPLEMENTED=true`
- `AUDIT_SINK_VERIFIED=PASS`
- `TARGET_BINDING_VERIFIED=PASS`
- `P13_ONE_SHOT_MAX_INVOCATIONS=1`
- `P13_AUTO_RETRY_ALLOWED=false`
- `EXPLICIT_LIVE_TEST_APPROVAL=false`
- `LIVE_TEST_READY=false`
- `ACTUATOR_COMMAND_ATTEMPTED=false`
- `PHYSICAL_DOOR_ACTION=false`
- `PHYSICAL_EFFECT_ASSERTED=false`

Collect public-safe evidence with hashes/markers only.

## Stop boundary

After all blockers are fixed and CT120 non-actuating preflight passes, STOP and report readiness.

Do not execute a physical Door command until the operator separately supplies exactly:

`I_APPROVE_P13_ONE_SHOT_PHYSICAL_DOOR_TEST`

The corrective task itself is not approval.

## Codex policy

Use Codex selectively for substantive implementation/test work where it lowers total iteration cost. Keep credentials, tokens, raw payload bodies, raw UCFG identity values, and unsanitized live logs out of Codex context.

Hermes owns runtime diagnosis and should run tests/CT120 checks directly.

## Continuation on limits

If an agent/tool/model limit is hit, commit/push coherent state and return:

- `CONTINUATION_REQUIRED=true`
- branch/head/tree
- PR #3 status
- completed blockers
- remaining blockers
- failing command summary
- whether any network action occurred
- whether any physical action occurred
- whether `SEND_ARMED` was reached outside fixtures
- exact next action

Do not restart from scratch.

## Definition of corrective done

Return `CORRECTIVE_RESULT=DONE` only when:

1. all seven blockers above are closed;
2. actual remote HEAD/TREE are reported exactly;
3. full CI is green;
4. CT120 non-actuating preflight passes from the concrete real adapter;
5. public-safe P13 preflight evidence is pushed;
6. PR #3 body is updated with exact evidence and remains draft until reviewed;
7. `EXPLICIT_LIVE_TEST_APPROVAL=false` and `PHYSICAL_DOOR_ACTION=false` remain true.

Then stop for operator approval.