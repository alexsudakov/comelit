# P116 / R30E — native helper rebuild provenance result

```text
=== COMELIT P116 R30E NATIVE HELPER REBUILD PROVENANCE ===
TASK_ID=COMELIT-P116-R30E-NATIVE-HELPER-REBUILD-PROVENANCE
BASE_SHA=53ce0632008709687d9eae69dbaa31b019f021ea
BUILD_INPUT_SHA=53ce0632008709687d9eae69dbaa31b019f021ea
FINAL_SHA=53ce0632008709687d9eae69dbaa31b019f021ea observed before orchestrator commit; a commit cannot embed its own sha, and the authoritative pushed head comes from the orchestrator report.
ACTUAL_EXECUTOR=codex-cli
CODEX_VERSION=codex-cli 0.137.0
CHANGED_FILES=15
  custom_components/comelit/media_transport.py
  custom_components/comelit/native/comelit-media
  safety-poc/docs/P116_HA_STREAM_RTP_BRIDGE.md
  safety-poc/research/media/v1/P116_R30E_NATIVE_HELPER_REBUILD_PROVENANCE_RESULT.md
  safety-poc/research/media/v1/ct120_run_p116_r27_repeat_001a_live.sh
  safety-poc/research/media/v1/p116_media_telemetry_build_meta.txt
  safety-poc/tests/test_p107_musl_package_provenance.py
  safety-poc/tests/test_p116_ha_stream_rtp_bridge.py
  safety-poc/tests/test_p116_native_rtp_telemetry.py
  safety-poc/tests/test_p116_provenance_binary_analysis.py
  safety-poc/tests/test_p116_r18_hls_runtime_diagnostics.py
  safety-poc/tests/test_p116_r20_hls_http_boundary_diagnostics.py
  safety-poc/tests/test_p116_r24_recovery_shim_lifecycle.py
  safety-poc/tests/test_p116_r27_repeat_001a_contract.py
  safety-poc/tests/test_p80_media_transport_static_contract.py
CANONICAL_SOURCE_SHA256=1c89d61de4372d96b25f6894862741244753c107a3a9b9e04817250b3bea55b2
CANONICAL_SOURCE_SHA_GATE=PASS
OFFLINE_ROOTFS=/root/comelit-p80-haos-build-20260909T193410Z/rootfs
OFFLINE_CACHED_TOOLCHAIN_GATE=PASS
ALPINE_VERSION=3.24.1
CC_VERSION=gcc (Alpine 15.2.0) 15.2.0
PKG_CONFIG_VERSION=2.5.1
LIBNICE_VERSION=0.1.22
GLIB_VERSION=2.88.1
GOBJECT_VERSION=2.88.1
BUILD_A_SHA256=a336477aa3564f4c99983a71621fc630885c55bf7ff07909bc70838d851a49b8
BUILD_A=PASS
BUILD_B_SHA256=a336477aa3564f4c99983a71621fc630885c55bf7ff07909bc70838d851a49b8
BUILD_B=PASS
REPRODUCIBLE_BINARY_SHA_GATE=PASS
REPRODUCIBLE_BINARY_CMP_GATE=PASS
PACKAGED_BINARY_SHA256=a336477aa3564f4c99983a71621fc630885c55bf7ff07909bc70838d851a49b8
PACKAGED_BINARY_SHA_GATE=PASS
TRANSPORT_PIN_SHA256=a336477aa3564f4c99983a71621fc630885c55bf7ff07909bc70838d851a49b8
TRANSPORT_BINARY_PIN_GATE=PASS
BUILD_META_SOURCE_GATE=PASS
BUILD_META_BINARY_GATE=PASS
PACKAGED_NATIVE_BINARY_REBUILT=true
HEAD_CANONICAL_SOURCE_CHANGED=true
NATIVE_REBUILD_REQUIRED=false
CURRENT_PACKAGED_BINARY_MATCHES_HEAD_SOURCE=true
ARTIFACT_PROVENANCE_READY=true
R27_GENERATED_SOURCE_SHA256=1c9f13cff0d1d3599e00109146310c7372b1b0ae12117bb46ad68f091a841d42
R27_STATIC_PIN_UPDATED=true
P107_PROVENANCE_TESTS=PASS
P116_BINARY_ANALYSIS_TESTS=PASS
R27_STATIC_PIN_TESTS=PASS
R30D_FOCUSED_REGRESSION=PASS
P116_BUILD_PROVENANCE_TESTS=PASS
P116_CANONICAL_GENERATOR_TESTS=PASS
AMENDMENT1_FOCUSED_TESTS=PASS
FULL_OFFLINE_TESTS=PASS
SANDBOX_FULL_OFFLINE_TESTS=FAIL_ENVIRONMENT_ARTIFACT errors=2 skipped=5 tests=1522
STATIC_SAFETY=PASS
COMPILE_SHELL_GATES=PASS
CLI_SAFETY_SCENARIOS=PASS
MUSL_INTERPRETER_GATE=PASS
NO_GLIBC_DEPENDENCY=PASS
NO_NEW_RUNTIME_DEPENDENCY=PASS
LIB_IDENTICAL=PASS
ADDITIONAL_SCOPE_REPIN_GATE=PASS
TEST_LOGIC_CHANGED=false
ASSERTION_REMOVED=false
ASSERTION_WEAKENED=false
SKIP_ADDED=false
TEST_RENAMED=false
ONLY_IDENTITY_CONSTANTS_REPINNED=true
R18_TRANSPORT_FILE_SHA_REPIN=PASS fad1dacadf0655237bb8a72d0e7c29492c88362ea57128c81dfad48119a16c51
R20_TRANSPORT_FILE_SHA_REPIN=PASS fad1dacadf0655237bb8a72d0e7c29492c88362ea57128c81dfad48119a16c51
DOC_HISTORICAL_EVIDENCE_CHANGED=false
WRITE_SCOPE_GATE=PASS
COMELIT_NETWORK_TX=0
EXTERNAL_TOOLCHAIN_DOWNLOADS=0
CANDIDATE_EXECUTIONS=0
LIVE_INVOCATIONS=0
DOOR_ACTIONS=0
GATE_ACTIONS=0
SELF_ACTIVATION_ACTIONS=0
REFRESH_OR_REPEAT_ACTIONS=0
PRODUCTION_LISTENER_TOUCHED=false
HA_DEPLOYED=false
LIVE_AUTHORIZED=false
LIVE_READY=false
OFFLINE_SAFETY=PENDING_ORCHESTRATOR_CI
VALIDATE_HACS=PENDING_ORCHESTRATOR_CI
PR=none
RESULT=PASS
=== END COMELIT P116 R30E NATIVE HELPER REBUILD PROVENANCE ===
```

## Evidence

The CT120 relay evidence is accepted. `/tmp/r30e/relay_run1.log`,
`/tmp/r30e/r30e-build-A.log`, and `/tmp/r30e/r30e-build-B.log` show detached
build input `53ce0632008709687d9eae69dbaa31b019f021ea`, a clean worktree,
cached Alpine 3.24.1 rootfs, GCC 15.2.0, pkg-config 2.5.1, libnice 0.1.22,
glib/gobject 2.88.1, `P80_BUILD_EXPECTED_SOURCE_SHA_GATE=PASS`, and no
candidate execution, live invocation, HA change, listener change, or Comelit
network request.

Both independent CT120 builds produced
`a336477aa3564f4c99983a71621fc630885c55bf7ff07909bc70838d851a49b8`,
size `270272`, mode `755`, and `cmp` reported identical bytes. The accepted
artifact was materialized from `/tmp/r30e/ct120-build-A.comelit-media` to
`custom_components/comelit/native/comelit-media`; local recomputation of the
packaged path produced the same SHA and mode.

The current canonical generated source was recomputed offline from
`entrance_p106_teardown_state_classification_transform.py` with
`include_p116=True` and matched
`1c89d61de4372d96b25f6894862741244753c107a3a9b9e04817250b3bea55b2`.
The R27 generated source was recomputed offline and matched
`1c9f13cff0d1d3599e00109146310c7372b1b0ae12117bb46ad68f091a841d42`; the R27
runner was not executed.

`custom_components/comelit/media_transport.py` differs only in the
`MEDIA_NATIVE_BINARY_SHA256` literal. Its post-edit full-file SHA is
`fad1dacadf0655237bb8a72d0e7c29492c88362ea57128c81dfad48119a16c51`, and R18/R20
were re-pinned to that exact byte identity.

## Verification

Authoritative host battery, executed by the Hermes orchestrator with
`working-directory: safety-poc`, is the acceptance source for the full offline
suite.

```text
COMMAND=PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=$PWD/src python3 -m unittest tests.test_p107_musl_package_provenance -v
WORKDIR=safety-poc
EXECUTOR=Hermes orchestrator host
EXIT_CODE=0
Ran 9 tests
OK
```

```text
COMMAND=PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=$PWD/src python3 -m unittest tests.test_p116_provenance_binary_analysis -v
WORKDIR=safety-poc
EXECUTOR=Hermes orchestrator host
EXIT_CODE=0
Ran 3 tests
OK (skipped=1)
```

```text
COMMAND=PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=$PWD/src python3 -m unittest tests.test_p116_r27_repeat_001a_contract -v
WORKDIR=safety-poc
EXECUTOR=Hermes orchestrator host
EXIT_CODE=0
Ran 30 tests
OK
```

```text
COMMAND=PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=$PWD/src python3 -m unittest tests.test_p80_media_transport_static_contract tests.test_p116_native_rtp_telemetry tests.test_p116_ha_stream_rtp_bridge tests.test_p116_r18_hls_runtime_diagnostics tests.test_p116_r20_hls_http_boundary_diagnostics tests.test_p116_r24_recovery_shim_lifecycle -v
WORKDIR=safety-poc
EXECUTOR=Hermes orchestrator host
EXIT_CODE=0
Ran 69 tests
OK
```

```text
COMMAND=PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=$PWD/src python3 -m unittest tests.test_p116_build_provenance_gate tests.test_p116_canonical_generator_contract -v
WORKDIR=safety-poc
EXECUTOR=Hermes orchestrator host
EXIT_CODE=0
Ran 14 tests
OK
```

The raw `/tmp/r30e/host_battery.log` contains an intermediate wrapper typo
(`set1`, rc 127) for the provenance-focused command, but the orchestrator
reported the corrected command result above, and the same tests are also covered
by the authoritative full discovery below.

```text
COMMAND=PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=$PWD/src python3 -m unittest tests.test_p116_r30b_offline_call_transaction tests.test_p76_entrance_rtpc_control_media_runtime_parity -v
WORKDIR=safety-poc
EXECUTOR=Hermes orchestrator host
EXIT_CODE=0
Ran 60 tests
OK
```

```text
COMMAND=python3 scripts/static_safety_check.py
WORKDIR=safety-poc
EXECUTOR=Hermes orchestrator host
EXIT_CODE=0
STATIC_SAFETY_CHECK=PASS
NETWORK_IMPORTS_PRESENT=false
COMELIT_ENDPOINTS_PRESENT=false
SOURCE_FILES_SCANNED=29
```

```text
COMMAND=python3 -m py_compile scripts/*.py; python3 -m compileall -q ../custom_components/comelit; python3 -m compileall -q research/media/v1/entrance_p116_r30b_call_transaction_model.py research/media/v1/entrance_rtpc_control_media_runtime_transform.py tests/test_p107_musl_package_provenance.py tests/test_p116_provenance_binary_analysis.py tests/test_p116_r27_repeat_001a_contract.py; bash -n scripts/*.sh deploy/*.sh
WORKDIR=safety-poc
EXECUTOR=Hermes orchestrator host
EXIT_CODE=0
COMPILE_SHELL_GATES=PASS
OUTPUT=<none, except BASH_N_OK marker>
```

```text
COMMAND=bash /tmp/r30e/cli_scenarios.sh
WORKDIR=safety-poc
EXECUTOR=Hermes orchestrator host
EXIT_CODE=0
CRASH_RC=75
STATE=UNKNOWN_OUTCOME
CLI_SCENARIOS=PASS
```

```text
COMMAND=PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=$PWD/src python3 -m unittest discover -s tests -v
WORKDIR=safety-poc
EXECUTOR=Hermes orchestrator host
EXIT_CODE=0
Ran 1522 tests in 28.263s
OK (skipped=1)
```

```text
COMMAND=git diff --check; git diff --cached --check
WORKDIR=/home/hermes/worktrees/comelit-p116-r30e
EXECUTOR=Hermes orchestrator host
EXIT_CODE=0
OUTPUT=<none>
```

```text
COMMAND=independent R27 digest recomputation
WORKDIR=safety-poc
EXECUTOR=Hermes orchestrator host
EXIT_CODE=0
R27_GENERATED_SOURCE_SHA256=1c9f13cff0d1d3599e00109146310c7372b1b0ae12117bb46ad68f091a841d42
```

Sandbox full discovery:

```text
COMMAND=PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=$PWD/src python3 -m unittest discover -s tests -v
WORKDIR=safety-poc
EXIT_CODE=1
Ran 1522 tests in 32.188s
FAILED (errors=2, skipped=5)
```

The two sandbox full-suite errors are preserved as
`NOT_A_R30E_REGRESSION`: the sandbox blocks the UDP datagram sink path used by
`start_udp_sink` / `socket.AF_INET, SOCK_DGRAM`.

Affected tests:

```text
test_p116_r29i_preopen_idle_and_sink_ownership.P116R29IPreOpenIdleAndSinkOwnership.test_nonzero_datagram_sink_materializes_final_counter_after_exit
test_p116_r29i_preopen_idle_and_sink_ownership.P116R29IPreOpenIdleAndSinkOwnership.test_zero_datagram_sink_materializes_final_counter_after_exit
```

## Scope

All edited files are inside the original R30E contract or approved amendment-1
scope. Amendment-1 files changed only deterministic identity literals or current
artifact identity statements. The R30E docs, R30D result, and R27 D1 live proof
retain historical SHA evidence unchanged.

Residual uncertainty: `offline-safety` and `Validate HACS` can only be observed
after the orchestrator commits, pushes, and opens the PR. `PR=none` remains
honest until that step. No live readiness is claimed.
