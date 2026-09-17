# Hermes execution task — P116 / R30H-E repeat `0x001A` body offline corrective

TASK_ID=`COMELIT-P116-R30H-E-REPEAT-BODY-OFFLINE-CORRECTIVE`

MODE=`OFFLINE_ONLY`

User authorization status: `AUTHORIZED_OFFLINE_ONLY`.

## Execution model

- Hermes is orchestrator only.
- Use one bounded Codex CLI context for diagnosis, implementation, tests, evidence interpretation, and result-document authorship.
- If additional semantic turns are required, resume the same Codex session.
- Hermes must not author executable code.
- Ordinary implementation/test defects discovered inside this bounded write scope are for Codex to diagnose and fix without asking the user again.
- If the task would require live Comelit traffic, production code, HA runtime changes, credentials changes, Door/Gate behavior, or a new architecture boundary, STOP and report.

## Mandatory bootstrap

Start with fresh authenticated `git fetch origin main` and use actual latest accepted main.

At task creation expected accepted main is:

```text
3d937b5dc8679c860292b3bd5f06944cd64d556b
```

A newer accepted main must not be rolled back.

On every CT120 clone/worktree needing GitHub access configure repo-local:

```bash
git config credential.helper 'store --file=/root/.config/git/comelit.credentials'
git config credential.useHttpPath true
```

Requirements:

- `/root/.config/git/comelit.credentials` exists;
- mode `600`;
- token is never printed/logged;
- remote URL is credential-free;
- authenticated fetch succeeds.

Read at minimum:

```text
safety-poc/research/media/v1/P116_R30H_E_REPEAT_BODY_OFFLINE_CORRECTIVE_CONTRACT.md
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
safety-poc/research/media/v1/ct120_run_p116_r30h_c_musl_launcher_offline.sh
```

## Goal

Fix the R30H-D defect where the one-shot repeat path calls `p76_generate_client_001a()` on an unpopulated repeat buffer and therefore fails before emission.

The finished research candidate must construct/populate a same-session repeat `0x001A` body first, validate it second, and preserve all one-shot/session safety invariants.

No live validation is part of R30H-E.

## Phase 1 — source-level diagnosis

Codex must first prove from current source, with exact file/line references in its evidence, the roles of:

```text
p76_build_client_001a(...)
p76_generate_client_001a(...)
r27_try_queue_repeat_001a(...)
r27_queue_rtpc_client_001a_repeat(...)
```

Required diagnosis fields:

```text
P76_BUILD_001A_ROLE=<...>
P76_GENERATE_001A_ACTUAL_ROLE=<...>
R27_REPEAT_BUFFER_POPULATED_BEFORE_VALIDATION=<true|false>
R30H_D_GENERATION_FAILURE_STATICALLY_EXPLAINED=<true|false>
```

Do not proceed to implementation if the R30H-D failure cannot be explained by current canonical code.

## Phase 2 — choose minimum corrective

Codex must choose and document the smallest evidence-supported body-construction strategy.

Allowed strategies include:

```text
A. Build from current P76/runtime semantic bindings using the existing body builder.
B. Copy the already runtime-generated initial 0x001A body as an in-session semantic template, mutate only proven mutable CTP state field(s), then validate.
C. Another equivalent strategy if proven from canonical source/tests.
```

Not allowed:

```text
- frozen captured packet literal replay;
- weakening/removing P76 validation;
- skipping target/geometry/role checks;
- creating new RTPC targets or opens;
- new CTPP/ICE/PseudoTCP/self-activation;
- a retry loop or periodic refresh.
```

The result doc must state why the chosen strategy is safer/minimal relative to alternatives.

## Phase 3 — CTP sequence correctness

Reconcile repeat sequence handling against accepted R30C/R30D CTP state semantics.

Required properties:

```text
CTP_BODY_SEQUENCE_ADVANCES_BY_ONE_MOD_256=true
CTP_ACK_BYTE_INDEPENDENT=true
CTP_SEQUENCE_FF_TO_00_NO_ACK_CARRY=true
```

If the current R27 `+ 0x00010000` arithmetic violates those properties at rollover, Codex must correct it within this child and add an executable offline rollover test.

Do not alter unrelated sequence/ACK behavior.

## Phase 4 — implementation scope

Codex may edit only the minimum research files needed, expected subset:

```text
safety-poc/research/media/v1/entrance_p116_r27_repeat_001a_transform.py
safety-poc/tests/test_p116_r27_repeat_001a_contract.py
safety-poc/research/media/v1/ct120_run_p116_r27_repeat_001a_live.sh
safety-poc/research/media/v1/ct120_run_p116_r30h_e_repeat_body_offline.sh
```

The runner may change only for corrected generated-source provenance/pin or narrowly required research evidence. Preserve `R27_LIVE_RUN=NO` refusal semantics.

Do not edit:

```text
custom_components/comelit/**
custom_components/comelit/native/comelit-media
production HA integration behavior
Door/Gate production code
```

## Phase 5 — behavioral offline proof

Add/extend executable tests that compile/run the actual generated R27 corrective logic or a mechanically extracted exact R27 region.

Mandatory cases:

```text
VALID_REPEAT_BODY_BUILD=PASS
VALID_REPEAT_BODY_VALIDATION=P76_OK
REPEAT_TARGET_EQUALS_INITIAL_ALLOCATION_2=true
REPEAT_GEOMETRY_PRESERVED=true
REPEAT_ROLE_BINDINGS_PRESERVED=true
REPEAT_BODY_DIFF_GATE=PASS
CTP_SEQUENCE_ROLLOVER_GATE=PASS
MALFORMED_TARGET_FAIL_CLOSED=true
MALFORMED_GEOMETRY_FAIL_CLOSED=true
MALFORMED_REQUEST_SHAPE_FAIL_CLOSED=true
REPEAT_BEFORE_INITIAL_ACK_BLOCKED=true
REPEAT_WITHOUT_VIDEO_PROGRESS_BLOCKED=true
THIRD_001A_FAIL_CLOSED=true
ACK_TIMEOUT_RETRY=false
NO_NEW_SESSION_SETUP_PATHS=true
DOOR_GATE_PATHS_UNREACHABLE=true
```

For `REPEAT_BODY_DIFF_GATE`, report exact changed byte offsets between the established initial body and corrected repeat body. Every changed offset must map to a proven mutable CTP state field. Any unexplained offset is failure.

## Phase 6 — deterministic generation and source pin

Generate corrected candidate source twice independently:

```text
CANDIDATE_SOURCE_SHA256_A=<sha>
CANDIDATE_SOURCE_SHA256_B=<sha>
CANDIDATE_REPRODUCIBLE=<true|false>
```

If the source changed relative to the current runner pin, treat the old pin as expected stale provenance, not as a test failure to paper over.

Only after semantic acceptance and deterministic A/B equality may Codex update the research runner expected source SHA to the new exact hash.

Then require:

```text
EXPECTED_SOURCE_SHA_GATE=PASS
```

## Phase 7 — CT120 offline build

Build the corrected ephemeral candidate using the existing musl/chroot builder.

Required evidence:

```text
CANDIDATE_COMPILE=PASS
CANDIDATE_LINK=PASS
CANDIDATE_BINARY_SHA256=<sha>
MUSL_INTERPRETER_GATE=PASS
NO_GLIBC_DEPENDENCY=PASS
NO_NEW_RUNTIME_DEPENDENCY=PASS
LIB_IDENTICAL=PASS
```

Do not execute candidate `main()`.

## Phase 8 — R30H-C execution-boundary regression

Run the accepted R30H-C offline no-main harness or an exact updated equivalent if source-pin changes require it.

Required:

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

The launcher must still use the provenance-bound run-root musl loader and explicit packaged library path.

## Phase 9 — negative live/refusal proof

Do not execute live.

You may invoke the R27 runner only in its refusal mode:

```text
R27_LIVE_RUN=NO
```

and require that it exits before build/listener/network side effects with:

```text
R27_OFFLINE_SAFE_REFUSAL=true
LIVE_INVOCATIONS=0
R27_RUN_CLASSIFICATION=NOT_RUN
```

Verify no listener control artifacts, no candidate process, and no Comelit/HA runtime traffic were created.

## Phase 10 — tests

Run at minimum:

```text
python3 -m py_compile <changed Python files>
bash -n <changed shell files>
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=$PWD/src python3 -m unittest tests.test_p116_r27_repeat_001a_contract
```

Run the repository offline-safety suite. If it contains a pre-existing failure, reproduce the same failure on a fresh accepted-main baseline before classifying it as non-regression.

Do not hide or delete failing tests.

## Phase 11 — independent Hermes verification

Hermes must independently re-derive, without relying only on Codex self-report:

- branch/base/head cleanliness;
- exact changed-file scope;
- focused test count/result;
- source A/B hashes;
- runner source pin;
- CT120 build exit/result and binary hash;
- repeat-body changed offsets and semantic classification;
- rollover proof;
- loader no-main probe;
- refusal path;
- no candidate/helper processes left;
- no `custom_components/**` diff;
- no live/listener/HA/Door/Gate action.

If Hermes cannot independently verify a claimed PASS gate, downgrade the result.

## Phase 12 — result document

Write:

```text
safety-poc/research/media/v1/P116_R30H_E_REPEAT_BODY_OFFLINE_CORRECTIVE_RESULT.md
```

Required final scalar block:

```text
=== COMELIT P116 R30H-E REPEAT BODY OFFLINE CORRECTIVE ===
TASK_ID=COMELIT-P116-R30H-E-REPEAT-BODY-OFFLINE-CORRECTIVE
BASE_SHA=<accepted-main>
R30H_D_RESULT=INCONCLUSIVE
R30H_D_REPEAT_EXECUTED=false
P76_BUILD_001A_ROLE=<...>
P76_GENERATE_001A_ACTUAL_ROLE=<...>
R30H_D_GENERATION_FAILURE_STATICALLY_EXPLAINED=<true|false>
REPEAT_BODY_STRATEGY=<...>
REPEAT_BODY_BUILD=<PASS|FAIL>
REPEAT_BODY_VALIDATION=<PASS|FAIL>
REPEAT_BODY_CHANGED_OFFSETS=<...>
REPEAT_BODY_DIFF_GATE=<PASS|FAIL>
CTP_SEQUENCE_ROLLOVER_GATE=<PASS|FAIL>
ONE_SHOT_REPEAT_CONTRACT=<PASS|FAIL>
CANDIDATE_SOURCE_SHA256_A=<sha>
CANDIDATE_SOURCE_SHA256_B=<sha>
CANDIDATE_REPRODUCIBLE=<true|false>
EXPECTED_SOURCE_SHA_GATE=<PASS|FAIL>
CANDIDATE_BINARY_SHA256=<sha|NOT_REACHED>
CANDIDATE_BUILD=<PASS|FAIL|NOT_REACHED>
LOADER_PROBE_RESOLUTION=<PASS|FAIL|NOT_REACHED>
CANDIDATE_MAIN_EXECUTED=false
COMELIT_LIVE_EXECUTED=false
LIVE_INVOCATIONS=0
PRODUCTION_LISTENER_TOUCHED=false
HA_TOUCHED=false
DOOR_ACTIONS=0
GATE_ACTIONS=0
CUSTOM_COMPONENTS_TOUCHED=false
PACKAGED_NATIVE_TOUCHED=false
RESULT_DOC=safety-poc/research/media/v1/P116_R30H_E_REPEAT_BODY_OFFLINE_CORRECTIVE_RESULT.md
BRANCH=<branch>
REMOTE_HEAD=<sha|NOT_PUSHED>
PR=<number|none>
RESULT=<PASS_REPEAT_BODY_READY|BLOCKED_REPEAT_BODY_SEMANTICS|FAIL_OFFLINE_CORRECTIVE|INCONCLUSIVE>
=== END COMELIT P116 R30H-E REPEAT BODY OFFLINE CORRECTIVE ===
```

No credentials, raw SDP, raw protocol bytes, raw RTP/media payload, peer/session identifiers, or private media may be committed.

## Phase 13 — GitHub completion

Commit the bounded corrective/tests/harness/result only.

Push with project credential rules. Attempt PR creation. If `createPullRequest` is unavailable to the CT120 PAT, return exact branch + remote head for ChatGPT.

After R30H-E: STOP.

Even `PASS_REPEAT_BODY_READY` does not authorize a new live run, production refresh loop, or cadence selection.