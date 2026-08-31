# P13 PoC direct path — real door opening only

## Goal

Reach exactly one real, operator-approved Door-open attempt on CT120 as quickly as possible while preserving only the safety properties that are necessary to avoid duplicate or uncontrolled physical actuation.

This document intentionally excludes production hardening that does not materially improve the probability or safety of the first real PoC opening.

## Scope rule

A task is in scope only if at least one of the following is true:

1. without it the real Door command cannot be formed or transported;
2. without it we cannot bind the command to the intended target;
3. without it a single operator-approved attempt could accidentally be sent more than once;
4. without it an ambiguous transport result could cause an unsafe retry;
5. without it we cannot tell whether the live path reached the actuation boundary.

Everything else is deferred until after the first successful physical opening.

## Explicitly deferred

The following are NOT blockers for the first PoC opening:

- reproducible-build / supply-chain provenance for the native holder;
- independently reviewed holder build manifests beyond runtime identity capture;
- long-term immutable deployment packaging;
- production Home Assistant integration;
- production operator service hardening beyond what is required for one-shot execution;
- generalized release engineering;
- extra evidence/reporting work that does not change the live actuation decision;
- refactors, cleanup, documentation completeness, or architectural polish unrelated to the first real opening.

These may be done after the physical PoC succeeds.

## Already proven and reusable

P12 live read-only path is proven on the real installation:

- P2P/ICE/PseudoTCP/ViP connection: PASS;
- UAUT authentication: response-code 200;
- UCFG read: PASS;
- target binding by apt-address + apt-subaddress: PASS;
- clean UAUT/UCFG close: PASS;
- no actuation occurred during P12.

Door/CTPP transaction shape is already fixture/capture tested and requires exactly six Door writes.

## Remaining functional path to first real opening

### 1. Runtime holder validation

Use the existing P13-capable native holder on CT120 as a PoC runtime artifact.

For the first PoC, it is sufficient to:

- record its current SHA-256 as runtime identity;
- verify root ownership and expected executable mode;
- verify it exposes the required P13 CLI/capability surface without opening a Comelit session or sending Door data;
- verify the wrapper points to this exact holder;
- verify payload file ownership/mode and expected six-write metadata.

The holder SHA is a runtime identity for this PoC, not a claim of independently reproducible provenance.

### 2. Non-actuating CT120 preflight

Run exactly one non-actuating preflight that proves:

- current feature HEAD/TREE are known;
- P12 read-only transport evidence is available;
- holder/wrapper/payload are present and permissions are correct;
- holder dry capability check passes;
- target binding is valid;
- six-write payload bundle validates;
- audit/journal path is writable/durable enough for the one-shot attempt;
- no conflicting Comelit process is active;
- no automatic retry path exists;
- `EXPLICIT_LIVE_TEST_APPROVAL=false` and `LIVE_TEST_READY=false` before operator approval;
- `PHYSICAL_DOOR_ACTION=false`.

Do not block this preflight on reproducible-build provenance.

### 3. One-shot live runner readiness

Before asking for approval, verify the actual runner that will be used for the physical attempt satisfies:

- exact approval token required at execution time;
- one `operation_id` maps to at most one transport invocation;
- `attempt_number=1`;
- durable `SEND_ARMED` is written before the single native transport invocation;
- duplicate `operation_id` returns persisted state and never invokes transport again;
- no automatic retry;
- timeout/disconnect/missing or contradictory markers after `SEND_ARMED` => `UNKNOWN_OUTCOME`;
- protocol ACK is never treated as proof of physical relay effect;
- wrapper/native process is invoked exactly once.

### 4. Operator approval

Only after steps 1-3 pass, stop and request the exact explicit approval:

`I_APPROVE_P13_ONE_SHOT_PHYSICAL_DOOR_TEST`

No older task text, previous approval, or generic instruction implies this approval.

### 5. Exactly one physical attempt

After approval:

- generate a fresh unique `operation_id`;
- execute the physical runner exactly once;
- do not retry automatically or manually under the same operation;
- preserve raw runtime log root-only;
- report protocol outcome separately from observed physical result;
- if the result is ambiguous, classify `UNKNOWN_OUTCOME` and do not resend.

## Required outcome reporting

Report functionality, not process ceremony:

- P2P connection;
- authentication;
- target identification;
- CTPP open;
- number of Door writes reported;
- CTPP close/teardown;
- one-shot/duplicate protection;
- protocol outcome;
- whether the operator physically observed the door opening.

Never set `PHYSICAL_EFFECT_ASSERTED=true` from protocol evidence alone.

## Stop conditions before physical attempt

Stop and fix only if a defect can prevent or make unsafe the first real opening, including:

- holder cannot provide the required live actuation capability;
- target binding is absent or ambiguous;
- payload is not exactly six validated writes;
- runner can invoke transport more than once;
- approval is not enforced;
- `SEND_ARMED` is not durable before invocation;
- post-arm uncertainty can be mapped to safe/retryable state;
- automatic retry exists;
- installed runtime artifacts or permissions are inconsistent enough that execution is not trustworthy.

Do not stop for provenance/release/HA/documentation hardening that can be safely deferred until after the PoC.
