# P116 / R30H-E — repeat `0x001A` body offline corrective contract

TASK_ID=`COMELIT-P116-R30H-E-REPEAT-BODY-OFFLINE-CORRECTIVE`

MODE=`OFFLINE_ONLY`

Live authorization: `false`.

## 1. Purpose

R30H-E closes the concrete implementation defect exposed by R30H-D before any further live attempt.

R30H-D proved that the corrected research execution path can reach ICE, PseudoTCP, registered CTPP reuse, two RTPC OPENs, the initial client `0x001A`, its device ACK, `P80_MEDIA_ACTIVE=true`, and video/audio RTP forwarding. The only attempted repeat failed before transmission with:

```text
R27_REPEAT_001A_GENERATION=FAIL
P78_RTPC_SIGNALING_RESULT=FAIL
INITIAL_001A_SENT_COUNT=1
REPEAT_001A_SENT_COUNT=0
TOTAL_001A_SENT_COUNT=1
```

The narrow question for R30H-E is:

> How must the one-shot repeat `0x001A` body be constructed from the already established live runtime state so that it is a valid same-session second media request, without replaying captured literals or creating a second session?

R30H-E is implementation + offline proof only. It does not authorize Comelit live traffic, listener mutation, Home Assistant actions, or a new media session.

## 2. Source of truth

Execution must start with a fresh authenticated fetch and use the actual latest accepted `origin/main`.

At task creation accepted main is:

```text
3d937b5dc8679c860292b3bd5f06944cd64d556b
```

A newer accepted main must not be rolled back merely to match this SHA.

Read at minimum:

```text
safety-poc/research/media/v1/P116_R30H_D_REPEAT_001A_LIVE_PROOF_RESULT.md
safety-poc/research/media/v1/P116_R30H_C_MUSL_LAUNCHER_OFFLINE_CORRECTIVE_RESULT.md
safety-poc/research/media/v1/P116_R26_D1_MEDIA_LEASE_REFRESH_ANALYSIS.md
safety-poc/research/media/v1/entrance_p116_r27_repeat_001a_transform.py
safety-poc/research/media/v1/entrance_rtpc_control_media_runtime_transform.py
safety-poc/research/media/v1/entrance_p97_complete_post_000a_ack_cycle_transform.py
safety-poc/research/media/v1/P116_R30C_NATIVE_CTP_ADOPTION_EVIDENCE_RESULT.md
safety-poc/research/media/v1/P116_R30D_NATIVE_CTP_RUNTIME_INTEGRATION_RESULT.md
safety-poc/tests/test_p116_r27_repeat_001a_contract.py
safety-poc/research/media/v1/ct120_run_p116_r27_repeat_001a_live.sh
```

## 3. Established defect

Static code must be treated according to what it actually does.

`p76_build_client_001a(...)` is the body constructor. It writes a 60-byte client media body including request/action shape, target binding, geometry, and role fields.

`p76_generate_client_001a(...)` is not a constructor. It validates an already-populated body against current runtime state and marks `runtime->facts.client_001a_generated` only after validation succeeds.

The current R27 repeat path allocates a separate repeat buffer, sets only its length, then calls `p76_generate_client_001a()` on that not-yet-built repeat body. R30H-D observed the corresponding non-OK return and fail-closed termination before repeat emission.

R30H-E must correct this build/validate contract rather than weaken the validator.

## 4. Required semantic outcome

After the corrective, the one-shot repeat path must have an explicit sequence:

```text
live initial 0x001A and current P76/CTP runtime state
        -> construct/populate repeat body
        -> rebind only fields proven mutable for the second same-session request
        -> validate repeat body with the existing P76 binding validator
        -> queue repeat only if validation succeeds
```

The implementation may use either of these evidence-supported approaches, or another approach Codex proves equivalent:

1. construct the repeat through the existing P76 body builder using current runtime semantic bindings; or
2. derive from the runtime-generated initial `0x001A` body, preserving all immutable semantic fields and rebinding only the proven mutable CTP sequence/state field(s).

Using the already runtime-generated initial body as an in-session semantic template is allowed. Replaying a frozen/captured packet literal is not allowed.

The implementation must not simply make `p76_generate_client_001a()` accept malformed or zero-filled bodies.

## 5. CTP state requirement

R30C/R30D state semantics are authoritative for CTP sequence/ACK behavior.

The corrective must preserve the independent 8-bit sequence/ACK model. In particular, an outbound body sequence increment must wrap modulo 256 without carrying into the independent ACK byte.

Any existing R27 arithmetic that can turn sequence `0xff` into a carry into the adjacent state byte must be corrected inside this child if it participates in repeat construction.

An offline rollover test is mandatory:

```text
sequence 0xff -> 0x00
adjacent ACK/state byte unchanged
```

Do not change unrelated CTP behavior.

## 6. Immutable repeat semantics

The corrected repeat must preserve the initial request's established semantics, including:

- same registered CTPP channel;
- same RTPC allocation #2 target binding;
- same media request/action identity `0x001A` / media tag;
- same video geometry/settings unless current canonical runtime proves a required mutable field;
- same role/address semantic bindings;
- same ICE negotiation;
- same PseudoTCP socket;
- same helper process;
- no new RTPC OPEN;
- no self-activation repeat;
- no second media session.

The offline proof must explicitly report which byte offsets differ between initial and repeat body and classify every difference as proven mutable. Unexpected differences are fail-closed.

## 7. One-shot safety invariants

The accepted R27 limits remain unchanged:

```text
INITIAL_001A_MAX_COUNT=1
REPEAT_001A_MAX_COUNT=1
TOTAL_001A_MAX_COUNT=2
THIRD_001A_FAIL_CLOSED=true
AUTOMATIC_RETRY_001A=false
PERIODIC_REFRESH_LOOP=false
SECOND_MEDIA_SESSION=false
```

Repeat remains gated by:

```text
initial 0x001A sent
initial device ACK observed
signaling finished
media active
video RTP progress > 0
PseudoTCP open
no graceful teardown started
same CTPP valid
no TX already pending
RTPC stage complete
```

R30H-E must not relax those gates.

## 8. Repository write scope

Allowed executable research files are limited to the smallest set required to close the repeat-body defect, expected to be a subset of:

```text
safety-poc/research/media/v1/entrance_p116_r27_repeat_001a_transform.py
safety-poc/tests/test_p116_r27_repeat_001a_contract.py
safety-poc/research/media/v1/ct120_run_p116_r27_repeat_001a_live.sh
safety-poc/research/media/v1/ct120_run_p116_r30h_e_repeat_body_offline.sh
```

The live runner may change only when required to update generated-source provenance/pins or to expose the corrected candidate path. It must retain its live refusal boundary.

A result document may be added:

```text
safety-poc/research/media/v1/P116_R30H_E_REPEAT_BODY_OFFLINE_CORRECTIVE_RESULT.md
```

Forbidden repository changes:

```text
custom_components/comelit/**
custom_components/comelit/native/comelit-media
Door/Gate production code
HA integration behavior
production deployment files unrelated to this research runner
```

If a production-code change is discovered to be necessary, STOP and report instead of widening scope.

## 9. Required offline tests

At minimum prove all of the following with executable offline tests/harnesses using generated candidate logic, not prose-only assertions:

1. A fresh repeat buffer is populated before `p76_generate_client_001a()` validation.
2. Corrected repeat validation returns `P76_OK` for a valid established P76 runtime.
3. Initial target binding and repeat target binding are both allocation #2.
4. Geometry/settings and role/address semantics are preserved.
5. Only proven mutable CTP state byte(s) differ between initial and repeat bodies.
6. Sequence rollover `0xff -> 0x00` does not alter the independent ACK byte.
7. A malformed target, geometry, request shape, or semantic role still fails closed.
8. Repeat cannot be queued before initial ACK/media/video progress.
9. Third `0x001A` remains blocked.
10. ACK timeout does not cause automatic retry.
11. No new ICE/PseudoTCP/CTPP/RTPC OPEN/self-activation paths appear in the R27 repeat region.
12. Door/Gate paths remain unreachable from the corrective.

The focused R27 test module must pass completely.

## 10. Candidate generation/build proof

Generate candidate source A and B independently from the exact same accepted main and prove deterministic equality.

Record:

```text
CANDIDATE_SOURCE_SHA256_A=<sha>
CANDIDATE_SOURCE_SHA256_B=<sha>
CANDIDATE_REPRODUCIBLE=true
```

Because the R27 transform is expected to change, the previous generated-source SHA pin may legitimately become stale. Do not rewrite a pin merely to make tests green.

Required order:

1. generate corrected source;
2. independently hash A/B;
3. verify semantic tests;
4. if and only if the corrected source is accepted and deterministic, update the research runner's expected generated-source SHA to that observed value;
5. prove the pin equals exact corrected source.

Build the ephemeral candidate on CT120 using the existing musl/chroot builder. Prove compile/link and dependency gates. Do not execute candidate `main()`.

## 11. Execution-path regression gate

R30H-C's musl launcher corrective must remain intact.

Re-run the offline no-main loader gate and require:

```text
LOADER_PROBE_EXECUTED=true
LOADER_PROBE_RC=0
LOADER_PROBE_RESOLUTION=PASS
CANDIDATE_MAIN_EXECUTED=false
GLIBC_RESOLUTION_USED=false
WRAPPER_BINDING_GATE=PASS
RAW_CANDIDATE_PATH_PRESENT_AS_HOLDER=false
CANDIDATE_LAUNCHER_PATH_PRESENT_IN_CANDIDATE_WRAPPER=true
```

If the R30H-E source/hash change requires corresponding harness pin updates, make only the minimum research-only updates and prove them.

## 12. Explicitly forbidden runtime actions

R30H-E does not authorize:

- `R27_LIVE_RUN=YES`;
- any Comelit cloud/device request;
- entrance-camera activation;
- production listener stop/start/reload;
- Home Assistant API/webhook runtime control;
- HA reload/restart/deploy;
- Door action;
- Gate action;
- raw PCAP/RTP/H264/audio capture;
- candidate `main()` execution;
- production helper replacement;
- packaged native replacement.

Negative proof must include:

```text
COMELIT_LIVE_EXECUTED=false
LIVE_INVOCATIONS=0
CANDIDATE_MAIN_EXECUTED=false
PRODUCTION_LISTENER_TOUCHED=false
HA_TOUCHED=false
DOOR_ACTIONS=0
GATE_ACTIONS=0
CUSTOM_COMPONENTS_TOUCHED=false
PACKAGED_NATIVE_TOUCHED=false
```

## 13. Result classes

Use exactly one:

### `PASS_REPEAT_BODY_READY`

Use only when:

```text
REPEAT_BODY_BUILD=PASS
REPEAT_BODY_VALIDATION=PASS
REPEAT_BODY_DIFF_GATE=PASS
CTP_SEQUENCE_ROLLOVER_GATE=PASS
ONE_SHOT_REPEAT_CONTRACT=PASS
CANDIDATE_REPRODUCIBLE=true
CANDIDATE_BUILD=PASS
LOADER_PROBE_RESOLUTION=PASS
CANDIDATE_MAIN_EXECUTED=false
COMELIT_LIVE_EXECUTED=false
```

This means a future bounded live proof may be planned. It does not authorize it.

### `BLOCKED_REPEAT_BODY_SEMANTICS`

Use when there is insufficient canonical evidence to determine safe repeat-body mutable fields or bindings.

### `FAIL_OFFLINE_CORRECTIVE`

Use for a deterministic implementation/test failure attributable to this corrective.

### `INCONCLUSIVE`

Use only where evidence quality/provenance prevents a reliable offline conclusion.

## 14. GitHub completion

Commit only the bounded R30H-E implementation/tests/harness/result files.

Push using project credential rules. Attempt PR creation. If CT120 PAT lacks `createPullRequest`, return branch and exact remote head SHA so ChatGPT can create it.

R30H-E ends with STOP. Do not start a live child automatically.