# P116 / R30H-A — Hermes/Codex execution task: repeat 0x001A offline revalidation

TASK_ID=`COMELIT-P116-R30H-A-REPEAT-001A-OFFLINE-REVALIDATION`

Status: **AUTHORIZED DEV/OFFLINE / NO LIVE / NO DEPLOY / NO HA RESTART**

Primary contract:

`safety-poc/research/media/v1/P116_R30H_A_REPEAT_001A_OFFLINE_REVALIDATION_CONTRACT.md`

## Roles

- Hermes: orchestrator only.
- Codex CLI: semantic executor and owner of diagnosis/corrections.
- Use one bounded Codex context for inspect -> offline lineage proof -> candidate generation/build -> wrapper-binding proof -> tests -> result.
- Hermes may mechanically execute exact build/test commands on CT120 when Codex cannot access that host, returning complete scalar/stdout evidence to the same Codex context.
- Hermes must not author executable code itself.

## Bootstrap

1. `git fetch origin main` and use actual latest `origin/main`; do not roll back a newer accepted main.
2. Read, in order:

```text
safety-poc/research/media/v1/P116_R30H_A_REPEAT_001A_OFFLINE_REVALIDATION_CONTRACT.md
safety-poc/research/media/v1/P116_R30G_RESTART_ACTIVATED_BOUNDED_LIVE_RESULT.md
safety-poc/research/media/v1/P116_R26_D1_MEDIA_LEASE_REFRESH_ANALYSIS.md
safety-poc/research/media/v1/P116_R27_D1_REPEAT_001A_LIVE_PROOF.md
safety-poc/research/media/v1/entrance_p116_r27_repeat_001a_transform.py
safety-poc/research/media/v1/ct120_run_p116_r27_repeat_001a_live.sh
safety-poc/tests/test_p116_r27_repeat_001a_contract.py
safety-poc/research/media/v1/entrance_p106_teardown_state_classification_transform.py
```

3. Create a separate R30H-A branch/worktree from fresh main.
4. Keep GitHub remote credential-free and configure repo-local credentials exactly as required by the Comelit project:

```text
git config credential.helper 'store --file=/root/.config/git/comelit.credentials'
git config credential.useHttpPath true
```

Do not print the credential file or token.

5. Verify `codex-cli` availability. If unavailable, stop `RESULT=BLOCKED_EXECUTOR_UNAVAILABLE`.

## Background that must guide the work

R30G proved that the accepted exact-main helper is actually loaded and that RTP still stops at approximately 35 seconds while the media/control session remains alive. HA Stream itself was proven functional before RTP silence.

R26 already localized the initial video request to client CTPP `0x001A` and classified same-session repeat/lease refresh as plausible.

R27 attempted a one-shot same-session repeat proof but failed to execute the candidate helper. Its result must not be treated as evidence against the hypothesis.

Current main contains a corrected runner design that rewrites a per-run wrapper to the candidate helper. R30H-A must revalidate that corrected path offline before any new live test.

The external implementation's 15-second refresh is corroborating evidence only. Current R27 research candidate uses one repeat after 20 seconds and marks the value as non-production/non-protocol. Do not change it merely to copy the external implementation.

## Authorization boundary

This task is strictly offline with respect to Comelit and Home Assistant.

Allowed:

- Git/GitHub fetch/branch/test/result operations;
- research-only edits inside the contract write scope;
- generation/compilation/linking under `/tmp` or an isolated worktree;
- static inspection, SHA/ELF/build provenance;
- unit/contract/harness tests;
- CT120 offline build/test use;
- materializing the future candidate wrapper and validating its contents **without executing it**.

Forbidden:

- any Comelit cloud/device connection;
- any live media/camera attempt;
- executing `ct120_run_p116_r27_repeat_001a_live.sh` in its live mode;
- executing the materialized candidate wrapper;
- stopping/restarting/replacing the persistent listener;
- HA deploy, integration reload or HA restart;
- HAOS/VM/host reboot;
- Door/Gate;
- any `custom_components/comelit/**` edit;
- packaged native binary replacement;
- go2rtc/Frigate changes;
- packet/media capture.

If an operation is ambiguous about whether it can initiate a Comelit connection, do not run it.

## Default write scope

Only these research/test paths may change if Codex proves a correction is necessary:

```text
safety-poc/research/media/v1/entrance_p116_r27_repeat_001a_transform.py
safety-poc/research/media/v1/ct120_run_p116_r27_repeat_001a_live.sh
safety-poc/tests/test_p116_r27_repeat_001a_contract.py
safety-poc/research/media/v1/ct120_run_p116_r30h_a_repeat_001a_offline_preflight.sh
safety-poc/research/media/v1/P116_R30H_A_REPEAT_001A_OFFLINE_REVALIDATION_RESULT.md
```

The dedicated R30H-A offline-preflight script is optional; create it only if it materially improves proof/reproducibility.

No production path is in scope.

## Execution sequence

### Phase 1 — inspect current main

Codex must establish:

- fresh main SHA;
- current R30E/R30G packaged helper SHA/pin for reference only;
- current R27 transform and runner hashes;
- current expected generated-candidate SHA pins in tests/runner;
- whether the corrected wrapper-substitution code and its tests are present;
- current research repeat delay.

Expected at task creation, unless fresh main supersedes it:

```text
CURRENT_MAIN=95c27619aca6aadadea298e523fd1f08ad261043
PACKAGED_NATIVE_SHA256=a336477aa3564f4c99983a71621fc630885c55bf7ff07909bc70838d851a49b8
R27_EXPECTED_GENERATED_SOURCE_SHA256=1c9f13cff0d1d3599e00109146310c7372b1b0ae12117bb46ad68f091a841d42
R27_REPEAT_DELAY_SECONDS=20
```

Treat these as expected observations, not permission to force old values onto a newer source tree.

### Phase 2 — current-lineage candidate generation

Generate the R27 candidate twice from fresh-main canonical sources without network/live actions.

Record:

```text
CANDIDATE_GENERATION_A=<PASS|FAIL>
CANDIDATE_GENERATION_B=<PASS|FAIL>
CANDIDATE_SOURCE_SHA256_A=<sha>
CANDIDATE_SOURCE_SHA256_B=<sha>
CANDIDATE_REPRODUCIBLE=<true|false>
EXPECTED_SOURCE_SHA_GATE=<PASS|FAIL|STALE_PIN>
```

If the generated source differs from the pinned value, Codex must determine whether:

- current canonical upstream source semantics changed legitimately; or
- the transform changed; or
- the pin is stale; or
- generation is nondeterministic.

Never update a SHA pin merely to make a test green.

### Phase 3 — one-shot repeat semantic gates

Run the existing contract/harness and inspect the generated candidate.

Require proof of:

```text
INITIAL_001A_MAX_COUNT=1
REPEAT_001A_MAX_COUNT=1
TOTAL_001A_MAX_COUNT=2
THIRD_001A_FAIL_CLOSED=true
REPEAT_AFTER_INITIAL_ACK=true
REPEAT_AFTER_MEDIA_ACTIVE=true
REPEAT_REQUIRES_VIDEO_PROGRESS=true
REPEAT_BODY_REGENERATED_FROM_RUNTIME=true
REPEAT_SEQUENCE_FRESH=true
TARGET_GEOMETRY_ADDRESS_ROLES_REUSED=true
NEW_ICE_AFTER_REPEAT=false
NEW_PSEUDOTCP_AFTER_REPEAT=false
NEW_CTPP_AFTER_REPEAT=false
NEW_RTPC_OPEN_AFTER_REPEAT=false
NEW_SELF_ACTIVATION_AFTER_REPEAT=false
ACK_OBSERVATION_BOUNDED=true
ACK_TIMEOUT_RETRY=false
TEARDOWN_CANCELS_REPEAT_TIMERS=true
```

Record:

```text
R30H_A_REPEAT_DELAY_SECONDS=<value>
R30H_A_REPEAT_DELAY_IS_PROTOCOL_CONSTANT=false
R30H_A_REPEAT_DELAY_PROMOTED_TO_PRODUCTION=false
```

### Phase 4 — candidate compile/build proof

Compile/link the generated research candidate on CT120 with the existing trusted toolchain and without downloading new dependencies.

Do not execute the candidate binary.

Record at least:

```text
CANDIDATE_COMPILE=<PASS|FAIL>
CANDIDATE_LINK=<PASS|FAIL>
CANDIDATE_BINARY_SHA256=<sha-or-na>
CANDIDATE_BINARY_SIZE=<bytes-or-na>
CANDIDATE_ELF_INTERPRETER=<value-or-na>
NEW_RUNTIME_DEPENDENCY=false
```

If reproducible A/B binary generation is practical with the current build path, perform it and report the result. Do not broaden the task solely to achieve bit-identical build machinery that does not already exist.

### Phase 5 — corrected wrapper binding proof

Materialize the exact candidate wrapper form that R30H-B would later use, but do not execute it.

Verify fail-closed substitution and record:

```text
BASE_WRAPPER=<path>
CANDIDATE_WRAPPER=<temporary-path>
BASE_HOLDER_PATH_PRESENT_IN_CANDIDATE_WRAPPER=false
CANDIDATE_HOLDER_PATH_PRESENT_IN_CANDIDATE_WRAPPER=true
CANDIDATE_WRAPPER_PARSE=PASS
CANDIDATE_HELPER_SHA_BOUND=<sha>
CANDIDATE_BINARY_SHA256=<same-sha>
WRAPPER_BINDING_GATE=PASS
CANDIDATE_WRAPPER_EXECUTED=false
```

Also prove the runner still refuses usable repeat conclusions without helper-lineage evidence.

### Phase 6 — gates

Run:

- focused R27 contract tests;
- related P106/P116 generator/provenance tests needed to prove lineage;
- static safety scan;
- Python compile checks for touched Python;
- shell parse checks for touched shell;
- broader offline test discovery if practical and proportionate.

Known host-umask `755 != 775` artifacts must be classified separately with a `umask 022` control if encountered.

### Phase 7 — result and Git

Create:

```text
safety-poc/research/media/v1/P116_R30H_A_REPEAT_001A_OFFLINE_REVALIDATION_RESULT.md
```

If no correction was required, the result doc may be the only changed file.

If research-only corrections were necessary, include exact root cause and tests.

Commit/push using project credential rules. Create a PR if capability permits; otherwise return branch and exact remote head SHA.

## PASS condition

`PASS_LIVE_READY` requires all of:

- fresh-main candidate generation succeeds and is deterministic;
- source lineage/pins are explained and gated;
- one-shot repeat semantics pass;
- candidate compile/link passes;
- corrected wrapper binding is objectively proven and fail-closed;
- candidate wrapper was not executed;
- no Comelit/HA/live action occurred;
- production files were untouched.

## Final block

The useful final block must be the **last output from Hermes**:

```text
=== COMELIT P116 R30H-A REPEAT 001A OFFLINE REVALIDATION ===
TASK_ID=COMELIT-P116-R30H-A-REPEAT-001A-OFFLINE-REVALIDATION
BASE_SHA=<fresh-main>
PACKAGED_NATIVE_SHA256_REFERENCE=<sha>
R27_TRANSFORM_SHA256=<sha>
R27_RUNNER_SHA256=<sha>
R30H_A_REPEAT_DELAY_SECONDS=<value>
R30H_A_REPEAT_DELAY_IS_PROTOCOL_CONSTANT=false
R30H_A_REPEAT_DELAY_PROMOTED_TO_PRODUCTION=false
CANDIDATE_GENERATION_A=<PASS|FAIL>
CANDIDATE_GENERATION_B=<PASS|FAIL>
CANDIDATE_SOURCE_SHA256_A=<sha-or-na>
CANDIDATE_SOURCE_SHA256_B=<sha-or-na>
CANDIDATE_REPRODUCIBLE=<true|false>
EXPECTED_SOURCE_SHA_GATE=<PASS|FAIL|STALE_PIN>
CANDIDATE_COMPILE=<PASS|FAIL>
CANDIDATE_LINK=<PASS|FAIL>
CANDIDATE_BINARY_SHA256=<sha-or-na>
NEW_RUNTIME_DEPENDENCY=<true|false>
ONE_SHOT_REPEAT_CONTRACT=<PASS|FAIL>
THIRD_001A_FAIL_CLOSED=<true|false>
NO_NEW_SESSION_SETUP_PATHS=<true|false>
WRAPPER_BINDING_GATE=<PASS|FAIL>
BASE_HOLDER_PATH_PRESENT_IN_CANDIDATE_WRAPPER=<true|false>
CANDIDATE_HOLDER_PATH_PRESENT_IN_CANDIDATE_WRAPPER=<true|false>
CANDIDATE_HELPER_SHA_BOUND=<sha-or-na>
CANDIDATE_WRAPPER_EXECUTED=false
COMELIT_LIVE_EXECUTED=false
HA_TOUCHED=false
PRODUCTION_LISTENER_TOUCHED=false
PRODUCTION_CODE_CHANGED=false
RESULT_DOC=<path-or-none>
PR=<number-or-none>
RESULT=<PASS_LIVE_READY|BLOCKED_SOURCE_LINEAGE|BLOCKED_RUNNER_BINDING|BLOCKED_SCOPE_EXTENSION_REQUIRED|FAIL>
=== END COMELIT P116 R30H-A REPEAT 001A OFFLINE REVALIDATION ===
```

STOP after R30H-A. Do not begin R30H-B automatically.
