# P116 / R30H-C musl launcher offline corrective result

TASK_ID: `COMELIT-P116-R30H-C-MUSL-LAUNCHER-OFFLINE-CORRECTIVE`

MODE: `OFFLINE_ONLY`

Result class: `PASS_EXECUTION_PATH_READY`

## Source and main identity

The CT120 preparation used a full clone at:

```text
/root/comelit-r30h-c-musl-launcher-offline-repo
```

Prep completed with:

```text
FETCH_RC=0
CHECKOUT_RC=0
PREP_PORCELAIN=[]
CT120_CLONE_HEAD=5cfd36b5ac9a74894f9a271c66313e207511fd45
```

The harness confirmed the same repo head:

```text
R30H_C_REPO_HEAD=5cfd36b5ac9a74894f9a271c66313e207511fd45
P80_BUILD_REPO_HEAD=5cfd36b5ac9a74894f9a271c66313e207511fd45
P80_BUILD_EXPECTED_SHA_GATE=PASS 5cfd36b5ac9a74894f9a271c66313e207511fd45
P80_BUILD_WORKTREE_CLEAN=PASS
```

The R30H-C branch was based on the accepted latest `origin/main` identified by the task as
`2335dc270d04f7d362fad8ce72f468895d5914a2`. The generated-source pin remained the accepted R30H-A
value:

```text
GENERATED_SOURCE_SHA256=1c9f13cff0d1d3599e00109146310c7372b1b0ae12117bb46ad68f091a841d42
P80_BUILD_EXPECTED_SOURCE_SHA_GATE=PASS 1c9f13cff0d1d3599e00109146310c7372b1b0ae12117bb46ad68f091a841d42
EXPECTED_SOURCE_SHA_GATE=PASS
```

The orchestrator reported the transform byte-identical to `origin/main`; no `custom_components/**`
diff was present:

```text
CLONE_PORCELAIN=[]
CLONE_CUSTOM_COMPONENTS_DIFF=[]
```

## R30H-B blocker

R30H-B was inconclusive because the materialized wrapper attempted to execute the raw musl-linked
candidate ELF directly on the glibc CT120 host. The candidate requested interpreter
`/lib/ld-musl-x86_64.so.1`, but CT120 does not have that path at host root:

```text
HOST_LD_MUSL_PRESENT=false
```

The failure was therefore an execution-boundary defect before helper startup, not evidence for or
against the R27 same-session repeat hypothesis.

## Corrective design

R30H-C changes the research execution boundary to:

```text
materialized wrapper
  -> per-run candidate launcher
    -> explicit run-root musl loader
      -> exact candidate ELF
      -> explicit packaged native library directory
```

The launcher is disposable with the run-root, mode `700`, and contains no base-helper fallback. It
preserves normal stdout/stderr and exit-code behavior by ending in:

```text
exec "$LOADER" --library-path "$LIBDIR" "$CANDIDATE" "$@"
```

No retry loop, refresh loop, protocol payload, SDP, credential, or production helper fallback was
added.

## Loader provenance

The builder-selected rootfs was read from the build log produced by this harness run, not guessed:

```text
P80_OFFLINE_ROOTFS=/root/comelit-p80-haos-build-20260909T193410Z/rootfs
BUILDER_ROOTFS=/root/comelit-p80-haos-build-20260909T193410Z/rootfs
BUILDER_ROOTFS_MODE=CACHED_CHROOT
```

The source loader was:

```text
SOURCE_MUSL_LOADER=/root/comelit-p80-haos-build-20260909T193410Z/rootfs/lib/ld-musl-x86_64.so.1
SOURCE_MUSL_LOADER_SHA256=38d022ce7425ff105ccfb53598f606e6e5f5f0a34bfbc793d65e6f34c9d72806
```

It was copied only into the R30H-C run-root:

```text
RUN_MUSL_LOADER=/root/comelit-r30h-c-musl-launcher-offline-20260917T144615Z/ld-musl-x86_64.so.1
RUN_MUSL_LOADER_SHA256=38d022ce7425ff105ccfb53598f606e6e5f5f0a34bfbc793d65e6f34c9d72806
RUN_MUSL_LOADER_MODE=700
LOADER_COPY_SHA_GATE=PASS
```

No loader was copied to `/lib`, `/usr/lib`, `/usr/local/lib`, or another persistent host path, and no
host loader configuration was changed.

## Candidate provenance

The raw candidate ELF still exists as an artifact and was not replaced by the launcher:

```text
CANDIDATE_BINARY_SHA256=baeb9406b503a43542bc89b2a89a8d18b5564b429646113ccfd81367432f69a4
CANDIDATE_BINARY_SIZE=279888
CANDIDATE_INTERPRETER=/lib/ld-musl-x86_64.so.1
CANDIDATE_NEEDED_LIBS=libc.musl-x86_64.so.1,libglib-2.0.so.0,libgobject-2.0.so.0,libnice.so.10
CANDIDATE_SHA_GATE=PASS
CANDIDATE_INTERPRETER_MATCH=PASS
CANDIDATE_NEEDED_LIBS_GATE=PASS
```

Builder gates remained satisfied:

```text
P80_CHROOT_BUILD_RC=0
P80_BINARY_MARKER_GATE=PASS
P80_INTERPRETER_GATE=PASS /lib/ld-musl-x86_64.so.1
NO_GLIBC_DEPENDENCY=PASS
NO_NEW_RUNTIME_DEPENDENCY=PASS
MUSL_INTERPRETER_GATE=PASS
LIB_IDENTICAL=PASS
P80_HAOS_MEDIA_BUILD=PASS
```

## No-main loader probe

The harness executed the musl loader's dependency-listing mode against the exact candidate and explicit
packaged library path. The candidate program's `main()` was not entered.

```text
LOADER_PROBE_EXECUTED=true
LOADER_PROBE_RC=0
LOADER_PROBE_RESOLUTION=PASS
CANDIDATE_MAIN_EXECUTED=false
GLIBC_RESOLUTION_USED=false
COMELIT_NETWORK_REQUESTS=0
```

The three direct packaged libraries resolved from the repo packaged native library directory:

```text
LOADER_PROBE_PACKAGED_RESOLUTION_libglib-2.0.so.0=PASS
LOADER_PROBE_PACKAGED_RESOLUTION_libgobject-2.0.so.0=PASS
LOADER_PROBE_PACKAGED_RESOLUTION_libnice.so.10=PASS
PACKAGED_NATIVE_LIB_DIR=/root/comelit-r30h-c-musl-launcher-offline-repo/custom_components/comelit/native/lib
```

The orchestrator independently re-ran the loader listing after the harness:

```text
HERMES_LOADER_LIST_RC=0
HERMES_LOADER_LIST_LINES=26
HERMES_LIST_RESOLVED_FROM_PACKAGED_LIB=24
HERMES_LIST_GLIBC_TOKENS=0
CANDIDATE_PROCS=0
```

Nuance: the loader-list output included lines such as:

```text
/lib/ld-musl-x86_64.so.1 (0x...)
libc.musl-x86_64.so.1 => /lib/ld-musl-x86_64.so.1 (0x...)
```

This is musl's own identity/canonical-name display for the loader process. It is not evidence that CT120
resolved a host-root loader, because CT120 still had:

```text
HOST_LD_MUSL_PRESENT=false
```

The actual loader process was started from the explicit run-root path whose SHA matched the copied
builder-rootfs loader.

## Wrapper and launcher binding

The harness materialized and parsed the corrected wrapper:

```text
BASE_WRAPPER=/usr/local/sbin/comelit-p2p-cloud-probe
BASE_WRAPPER_SHA256=a564535dff0cf10b1fe4766171f2960c52fb581f1c816cf81d2992c5c84e79c9
CANDIDATE_WRAPPER=/root/comelit-r30h-c-musl-launcher-offline-20260917T144615Z/comelit-p2p-cloud-probe-r30h-c-offline
CANDIDATE_WRAPPER_PARSE=PASS
WRAPPER_BINDING_GATE=PASS
```

Required wrapper counts were satisfied:

```text
BASE_HOLDER_PATH_PRESENT_IN_CANDIDATE_WRAPPER=false
RAW_CANDIDATE_PATH_PRESENT_AS_HOLDER=false
CANDIDATE_LAUNCHER_PATH_PRESENT_IN_CANDIDATE_WRAPPER=true
CANDIDATE_LAUNCHER_OCCURRENCES=1
BASE_WRAPPER_PATH_OCCURRENCES=0
```

The orchestrator independently re-derived:

```text
WRAPPER_LAUNCHER_OCCURRENCES=1
WRAPPER_RAW_CANDIDATE_OCCURRENCES=0
WRAPPER_BASE_HOLDER_EXPR_OCCURRENCES=0
WRAPPER_BASE_HOLDER_PATH_OCCURRENCES=0
WRAPPER_BASE_WRAPPER_PATH_OCCURRENCES=0
WRAPPER_BASH_N=PASS
```

The launcher artifact was mode `700`, 793 bytes, and contained the exact run-root loader path, exact
candidate path, exact packaged libdir, and no fallback:

```text
LAUNCHER_LOADER_PATH_MATCH=true
LAUNCHER_CANDIDATE_PATH_MATCH=true
LAUNCHER_LIBRARY_PATH_MATCH=true
LAUNCHER_BASE_HELPER_FALLBACK=false
LAUNCHER_HAS_RUN_LOADER=1
LAUNCHER_HAS_CANDIDATE=1
LAUNCHER_HAS_LIBDIR=1
LAUNCHER_HAS_BASE_FALLBACK=0
LAUNCHER_EXEC_LINE=16:exec "$LOADER" --library-path "$LIBDIR" "$CANDIDATE" "$@"
```

## Preserved R27 semantics

The generated source SHA remained unchanged:

```text
GENERATED_SOURCE_SHA256=1c9f13cff0d1d3599e00109146310c7372b1b0ae12117bb46ad68f091a841d42
```

The focused contract module passed with the R30H-C tests added:

```text
Ran 33 tests
OK
```

This preserves the existing R27 one-shot semantics asserted by the test module, including the single
initial `0x001A`, single repeat `0x001A`, third-send fail-closed behavior, repeat only after initial
ACK/media/video progress, no retry-on-timeout, and no new session setup paths.

## Tests

Round-1 local verification:

```text
bash -n safety-poc/research/media/v1/ct120_run_p116_r27_repeat_001a_live.sh: pass
bash -n safety-poc/research/media/v1/ct120_run_p116_r30h_c_musl_launcher_offline.sh: pass
python3 -m py_compile safety-poc/tests/test_p116_r27_repeat_001a_contract.py: pass
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=$PWD/src python3 -m unittest tests.test_p116_r27_repeat_001a_contract: Ran 33 tests, OK
```

CT120 harness verification:

```text
R30H_C_HARNESS_RESULT=PASS
HARNESS_EXIT_CODE=0
```

### Full offline-safety suite

The repository full offline-safety suite was run on the R30H-C branch head:

```text
branch=research/p116-r30h-c-musl-launcher-offline-corrective
HEAD=5cfd36b5ac9a74894f9a271c66313e207511fd45
command=PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=$PWD/src python3 -m unittest discover -s tests
Ran 1525 tests in 28.149s
FAILED (failures=1, skipped=1)
```

The same command was run on a fresh detached baseline at accepted main
`2335dc270d04f7d362fad8ce72f468895d5914a2`:

```text
Ran 1522 tests in 28.080s
FAILED (failures=1, skipped=1)
```

Both heads failed only:

```text
test_committed_build_metadata_records_historical_non_runtime_mismatch
test_p116_provenance_binary_analysis.P116ProvenanceBinaryAnalysisTests
AssertionError: '755' != '775'
```

The mechanism is a pre-existing checkout/filesystem mode artifact: the committed metadata records mode
`755`, while the working-tree artifact is mode `775` on both heads:

```text
775 /tmp/r30hc-base/custom_components/comelit/native/comelit-media
775 /home/hermes/repos/comelit-worktrees/p116-r30h-c/custom_components/comelit/native/comelit-media
```

This is labeled `NOT_A_R30H_C_REGRESSION`. The R30H-C delta is the three added R30H-C tests:
`1522 -> 1525`, with identical failure and skip counts on branch and baseline.

Independent orchestrator verification confirmed artifact modes, SHA values, loader-list success,
wrapper counts, launcher content, build provenance, refusal behavior, and absence of live side effects.

## Forbidden-action evidence

R30H-C remained offline:

```text
R27_OFFLINE_SAFE_REFUSAL=true
R27_OFFLINE_SAFE_REFUSAL_RC=2
LIVE_INVOCATIONS=0
COMELIT_LIVE_EXECUTED=false
HA_TOUCHED=false
PRODUCTION_LISTENER_TOUCHED=false
CANDIDATE_BINARY_EXECUTED=false
CANDIDATE_WRAPPER_EXECUTED=false
```

The R27 live runner refusal path was invoked before any build/listener/network side effect:

```text
R27_RUN_CLASSIFICATION=NOT_RUN
WRAPPER_RC=NOT_REACHED
RUN_ROOT_LISTENER_ARTIFACTS=0
NEWER_THAN_RUNROOT_MEDIA_DIRS=0
```

No HA/listener control occurred:

```text
HARNESS_CURL_OCCURRENCES=0
RUN_ROOT_LISTENER_ARTIFACTS=0
```

The orchestrator found `HARNESS_HA_WEBHOOK_OCCURRENCES=1`; this is only the literal environment
variable name in the harness refusal allowlist, not a webhook URL value or a call site.

Door/gate/media capture prohibitions remained satisfied:

```text
DOOR_ACTIONS_SENT=0
GATE_ACTIONS_SENT=0
OFFICIAL_APP_CAPTURE=false
RAW_PCAP_CAPTURE=false
```

No candidate process remained:

```text
CANDIDATE_PROCS=0
```

## Result class

`PASS_EXECUTION_PATH_READY`

This satisfies the contract's pass conditions:

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

`PASS_EXECUTION_PATH_READY` means only that the R30H-B execution blocker is closed offline. It does
not authorize another live attempt.

## Still not proven

This result does not prove that repeat `0x001A` extends RTP, video, audio, or any live media behavior.

This result does not prove a successful Comelit live session, because no live session was attempted.

This result does not prove listener or Home Assistant integration behavior after a live run, because
the production listener and HA were not touched.

This result does not authorize R30H-D or any other live attempt. A future live child requires fresh
explicit user authorization.
