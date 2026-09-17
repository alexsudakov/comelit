# P116 / R30H-C — musl launcher offline corrective contract

TASK_ID=`COMELIT-P116-R30H-C-MUSL-LAUNCHER-OFFLINE-CORRECTIVE`

MODE=`OFFLINE_ONLY`

User authorization: after R30H-B was classified `INCONCLUSIVE` because the musl candidate could not be executed directly on glibc CT120, the user instructed to continue with the proposed offline execution-path corrective.

## 1. Purpose

R30H-C fixes and proves only the execution boundary exposed by R30H-B.

R30H-B established that the corrected wrapper binding was semantically correct but still unusable on CT120 because it substituted a raw musl ELF into a glibc-host wrapper. The candidate interpreter is `/lib/ld-musl-x86_64.so.1`, while that interpreter is absent at the host root. The candidate therefore failed before helper startup with `cannot execute: required file not found`.

R30H-C must make the research runner materialize a per-run **candidate launcher** that explicitly invokes a proven musl loader and the candidate's proven runtime libraries. The materialized Comelit wrapper must bind to that launcher, never directly to the raw candidate ELF.

This child is strictly offline. It does not retry R30H-B, does not contact Comelit, does not stop the production listener, and does not touch Home Assistant.

## 2. Source of truth

At contract creation the accepted repository main is:

```text
ef4d9cd832d262564e80b1efaaf1b84e1c5b4ee9
```

Execution must begin with a fresh authenticated `git fetch origin main` using the project credential rules and must use the actual latest accepted `origin/main`. A newer accepted main must not be rolled back merely to match the SHA above.

Read at minimum:

```text
safety-poc/research/media/v1/P116_R30H_B_REPEAT_001A_LIVE_PROOF_RESULT.md
safety-poc/research/media/v1/P116_R30H_A_REPEAT_001A_OFFLINE_REVALIDATION_RESULT.md
safety-poc/research/media/v1/P116_R30H_B_REPEAT_001A_LIVE_PROOF_CONTRACT.md
safety-poc/research/media/v1/ct120_run_p116_r27_repeat_001a_live.sh
safety-poc/research/media/v1/ct120_run_p116_r30h_a_repeat_001a_offline_preflight.sh
safety-poc/research/media/v1/ct120_build_p80_haos_media_helper.sh
safety-poc/research/media/v1/entrance_p116_r27_repeat_001a_transform.py
safety-poc/tests/test_p116_r27_repeat_001a_contract.py
```

## 3. Inherited facts

R30H-A proved:

```text
RESULT=PASS_LIVE_READY
CANDIDATE_SOURCE_SHA256=1c9f13cff0d1d3599e00109146310c7372b1b0ae12117bb46ad68f091a841d42
CANDIDATE_BINARY_SHA256_REFERENCE=baeb9406b503a43542bc89b2a89a8d18b5564b429646113ccfd81367432f69a4
WRAPPER_BINDING_GATE=PASS
ONE_SHOT_REPEAT_CONTRACT=PASS
```

R30H-B proved:

```text
LIVE_INVOCATIONS=1
RESULT=INCONCLUSIVE
CANDIDATE_INTERPRETER=/lib/ld-musl-x86_64.so.1
HOST_LD_MUSL_PRESENT=false
ROOTFS_LD_MUSL_PRESENT=true
SESSION_LOG_ERROR=candidate_path_cannot_execute_required_file_not_found
R27_HELPER_EVIDENCE_GATE=FAIL
```

The R30H-B failure occurred before helper startup. It is therefore an execution-path defect, not evidence for or against the same-session repeat `0x001A` hypothesis.

## 4. Required corrective design

The accepted research runner currently materializes a wrapper whose holder command points directly at the candidate ELF. R30H-C must change that research-only path so the wrapper points to a per-run launcher instead.

Required logical chain:

```text
materialized Comelit wrapper
    -> per-run candidate launcher
        -> explicit musl loader
            -> candidate helper ELF
                + explicit runtime library search path
```

The launcher must be generated inside the runner run-root and must be disposable with that run-root.

The launcher must not install musl into the CT120 host root and must not modify the system dynamic loader configuration.

### 4.1 Loader provenance

The musl loader must come from the same accepted Alpine rootfs provenance used by the P80 builder for the candidate.

The runner/corrective must obtain the exact rootfs path from the builder evidence rather than guessing a global path. If the builder does not currently expose enough machine-readable provenance, R30H-C may minimally extend the research builder output to expose the selected rootfs path as a scalar marker.

Record at minimum:

```text
CANDIDATE_INTERPRETER=/lib/ld-musl-x86_64.so.1
BUILDER_ROOTFS=<path>
BUILDER_ROOTFS_MODE=<mode>
SOURCE_MUSL_LOADER=<path-under-builder-rootfs>
SOURCE_MUSL_LOADER_SHA256=<sha>
```

The loader may be copied into the per-run directory before use. If copied, require:

```text
RUN_MUSL_LOADER=<path-under-run-root>
RUN_MUSL_LOADER_SHA256=<same-sha>
RUN_MUSL_LOADER_MODE=700-or-755
LOADER_COPY_SHA_GATE=PASS
```

No loader may be copied to `/lib`, `/usr/lib`, `/usr/local/lib`, or another persistent host-system path.

### 4.2 Runtime library provenance

The launcher must use an explicit library search path. Prefer the already packaged native library directory:

```text
custom_components/comelit/native/lib
```

The corrective must prove offline that the selected loader resolves the candidate's complete runtime dependency closure from the intended paths without falling back to glibc.

The existing builder facts `NO_GLIBC_DEPENDENCY=PASS`, `NO_NEW_RUNTIME_DEPENDENCY=PASS`, and `LIB_IDENTICAL=PASS` remain necessary but are not sufficient by themselves; R30H-C must add an actual loader resolution probe.

### 4.3 Candidate launcher

The per-run launcher must:

- have a fixed absolute loader path inside the run-root;
- have a fixed absolute candidate path inside the run-root;
- set or pass an explicit library search path;
- preserve stdout/stderr and exit code from the candidate when used normally;
- not contain credentials, tokens, private media, SDP, or protocol payloads;
- not contain a fallback to the base holder or production helper;
- be mode `0700` or otherwise owner-only executable where practical;
- fail closed if loader, candidate, or library directory identity gates fail.

Do not add a production cadence, retry loop, second media session, or protocol behavior to the launcher.

## 5. Mandatory offline execution-path proof

Before R30H-C can pass, the exact loader + explicit library path + exact candidate combination that the launcher will use must be exercised in a way that **does not execute the candidate program's `main()`**.

Use the musl loader's dependency/listing mode or an equivalent loader-native no-main probe. The probe must:

```text
LOADER_PROBE_EXECUTED=true
CANDIDATE_MAIN_EXECUTED=false
COMELIT_NETWORK_REQUESTS=0
HA_TOUCHED=false
PRODUCTION_LISTENER_TOUCHED=false
```

The proof is valid only if the loader process itself executes successfully and resolves the candidate rather than returning the R30H-B `required file not found` class.

Record the exact probe exit code and a bounded, sanitized dependency summary. Do not commit host-private absolute paths if they contain secrets; ordinary CT120 run-root paths are allowed.

Required gates:

```text
LOADER_PROBE_RC=0
LOADER_PROBE_RESOLUTION=PASS
GLIBC_RESOLUTION_USED=false
CANDIDATE_INTERPRETER_MATCH=PASS
CANDIDATE_SHA_GATE=PASS
```

A static `readelf` check alone is insufficient for `PASS`.

## 6. Wrapper binding proof after corrective

The materialized wrapper must bind to the launcher, not the raw candidate and not the base holder.

Require all of:

```text
BASE_HOLDER_PATH_PRESENT_IN_CANDIDATE_WRAPPER=false
RAW_CANDIDATE_PATH_PRESENT_AS_HOLDER=false
CANDIDATE_LAUNCHER_PATH_PRESENT_IN_CANDIDATE_WRAPPER=true
CANDIDATE_LAUNCHER_OCCURRENCES=1
BASE_WRAPPER_PATH_OCCURRENCES=0
CANDIDATE_WRAPPER_PARSE=PASS
WRAPPER_BINDING_GATE=PASS
```

The launcher itself must prove:

```text
LAUNCHER_LOADER_PATH_MATCH=true
LAUNCHER_CANDIDATE_PATH_MATCH=true
LAUNCHER_LIBRARY_PATH_MATCH=true
LAUNCHER_BASE_HELPER_FALLBACK=false
```

`WRAPPER_BINDING_GATE=PASS` must now mean that the wrapper is bound to an execution-capable launcher path proven by the loader probe; textual substitution alone is no longer sufficient.

## 7. Repository write scope

R30H-C may modify only the minimum research/offline surface required to fix and prove this execution boundary.

Expected write scope:

```text
safety-poc/research/media/v1/ct120_run_p116_r27_repeat_001a_live.sh
safety-poc/tests/test_p116_r27_repeat_001a_contract.py
safety-poc/research/media/v1/ct120_run_p116_r30h_c_musl_launcher_offline.sh
safety-poc/research/media/v1/P116_R30H_C_MUSL_LAUNCHER_OFFLINE_CORRECTIVE_RESULT.md
```

`ct120_build_p80_haos_media_helper.sh` may be changed only if a minimal scalar provenance marker is necessary to expose the exact selected rootfs path. Any such change must remain offline-only and must not alter compiler flags, candidate source, candidate ABI, output binary, or production packaging.

No changes are authorized under:

```text
custom_components/comelit/**
```

including packaged native binaries and libraries.

Do not modify the R27 one-shot repeat transform unless Codex proves the execution-boundary correction cannot be made without doing so. If transform modification becomes necessary, STOP and return the exact reason rather than broadening scope silently.

## 8. Semantic invariants that must remain unchanged

R30H-C must preserve all existing one-shot R27 protocol semantics:

```text
INITIAL_001A_MAX_COUNT=1
REPEAT_001A_MAX_COUNT=1
TOTAL_001A_MAX_COUNT=2
THIRD_001A_FAIL_CLOSED=true
REPEAT_AFTER_INITIAL_ACK=true
REPEAT_AFTER_MEDIA_ACTIVE=true
REPEAT_REQUIRES_VIDEO_PROGRESS=true
REPEAT_DELAY_SECONDS=20
REPEAT_DELAY_IS_PROTOCOL_CONSTANT=false
REPEAT_DELAY_PROMOTED_TO_PRODUCTION=false
NEW_ICE_AFTER_REPEAT=false
NEW_PSEUDOTCP_AFTER_REPEAT=false
NEW_CTPP_AFTER_REPEAT=false
NEW_RTPC_OPEN_AFTER_REPEAT=false
NEW_SELF_ACTIVATION_AFTER_REPEAT=false
ACK_TIMEOUT_RETRY=false
```

Generated candidate source SHA should remain the accepted R30H-A value. If it changes, classify `BLOCKED_SOURCE_DRIFT` and do not update the expected pin merely to make tests pass.

## 9. Forbidden actions

R30H-C does not authorize:

- any Comelit live session;
- `R27_LIVE_RUN=YES`;
- stopping/restarting the persistent listener;
- Home Assistant access or mutation;
- Home Assistant config-entry reload;
- Home Assistant restart;
- HAOS/VM/host restart;
- Door action;
- Gate action;
- raw PCAP/RTP/H264/audio capture;
- official-app capture;
- package installation into host system paths;
- editing host dynamic-loader configuration;
- installing musl globally;
- changing production custom component code;
- changing packaged native helper or packaged native libs;
- second R30H-B live attempt;
- any network-dependent validation.

If an offline loader proof cannot be completed without one of these actions, STOP with a blocker.

## 10. Required tests

At minimum:

1. Existing focused R27 contract tests still pass.
2. New/updated tests prove wrapper -> launcher -> loader/candidate binding.
3. Tests prove raw candidate substitution is gone from the future live path.
4. Tests prove no fallback to base helper exists.
5. Tests prove loader/rootfs provenance is validated.
6. Tests prove loader resolution probe cannot execute candidate main.
7. Tests prove `R27_LIVE_RUN=NO` refusal remains fail-closed before listener/network actions.
8. `bash -n` passes for all modified/new shell scripts.
9. Python compile/static safety gates pass.
10. The repository full offline-safety suite is run or any unrelated pre-existing failures are explicitly separated from R30H-C changes.

## 11. Result classes

Use exactly one:

### `PASS_EXECUTION_PATH_READY`

Use only when:

```text
CANDIDATE_SOURCE_SHA_GATE=PASS
CANDIDATE_BUILD=PASS
LOADER_PROBE_EXECUTED=true
LOADER_PROBE_RC=0
LOADER_PROBE_RESOLUTION=PASS
CANDIDATE_MAIN_EXECUTED=false
WRAPPER_BINDING_GATE=PASS
RAW_CANDIDATE_PATH_PRESENT_AS_HOLDER=false
CANDIDATE_LAUNCHER_PATH_PRESENT_IN_CANDIDATE_WRAPPER=true
ONE_SHOT_REPEAT_CONTRACT=PASS
COMELIT_LIVE_EXECUTED=false
PRODUCTION_LISTENER_TOUCHED=false
HA_TOUCHED=false
```

This means the R30H-B execution blocker is closed offline. It does **not** authorize another live attempt.

### `BLOCKED_SOURCE_DRIFT`

Use when accepted generated source identity changes unexpectedly.

### `BLOCKED_LOADER_PROBE`

Use when loader execution or dependency resolution cannot be proven offline.

### `FAIL_WRAPPER_LAUNCHER_BINDING`

Use when wrapper/launcher identity or fallback invariants fail.

### `INCONCLUSIVE`

Use only when evidence quality prevents classification above.

## 12. GitHub completion

Write a result document at:

```text
safety-poc/research/media/v1/P116_R30H_C_MUSL_LAUNCHER_OFFLINE_CORRECTIVE_RESULT.md
```

Commit/push the bounded changes to a dedicated branch. Attempt PR creation. If the CT120 token cannot create a PR, return branch name and exact remote head SHA for ChatGPT to create the PR through the connected GitHub tool.

GitHub remote must remain credential-free and the token must never appear in output or committed files.

## 13. Stop boundary

STOP after R30H-C is complete.

Do not start another live session, do not request/perform a listener stop, and do not start a production refresh implementation automatically.

A future live child requires fresh explicit user authorization after `PASS_EXECUTION_PATH_READY` is reviewed.
