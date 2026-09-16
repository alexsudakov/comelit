# P116 / R30E — scope amendment 1

Status: **APPROVED / OFFLINE ONLY**

TASK_ID=`COMELIT-P116-R30E-NATIVE-HELPER-REBUILD-PROVENANCE`

AMENDMENT_ID=`P116-R30E-SCOPE-AMENDMENT-1`

BASE_MAIN=`5f5a34e690b1ae651fa10a1fc583e705574e09c9`

This amendment resolves a pre-validation contradiction between R30E acceptance (`FULL_OFFLINE_TESTS=PASS`) and the original write scope in §7 of `P116_R30E_NATIVE_HELPER_REBUILD_PROVENANCE_CONTRACT.md`.

The original contract remains authoritative except where this amendment explicitly extends the write scope.

## Approved additional write scope

The following existing files are additionally writable in R30E:

```text
safety-poc/tests/test_p80_media_transport_static_contract.py
safety-poc/tests/test_p116_native_rtp_telemetry.py
safety-poc/tests/test_p116_ha_stream_rtp_bridge.py
safety-poc/tests/test_p116_r18_hls_runtime_diagnostics.py
safety-poc/tests/test_p116_r20_hls_http_boundary_diagnostics.py
safety-poc/tests/test_p116_r24_recovery_shim_lifecycle.py
safety-poc/docs/P116_HA_STREAM_RTP_BRIDGE.md
```

## Exact allowed edits

These seven files may change **only** to update deterministic identity pins made stale by the accepted R30E rebuild/package operation.

Allowed changes are limited to:

1. Replace the pre-R30E packaged native SHA
   `35a9a1604c4bef3667713e3487b68aadc79501c4630748d7143ee9ee7cd85622`
   with the actual `PACKAGED_BINARY_SHA256` produced by the two-build reproducibility gate.
2. In tests that fingerprint the complete `custom_components/comelit/media_transport.py` file (currently R18/R20), update only the expected transport-file SHA to the actual SHA after the contract-authorized single-line `MEDIA_NATIVE_BINARY_SHA256` change.
3. In `P116_HA_STREAM_RTP_BRIDGE.md`, update only current packaged-binary / transport identity pin statements that are made stale by R30E. Historical evidence, historical run identities, experiment results, conclusions and narrative MUST NOT be rewritten.

No global replacement of historical SHA values is authorized.

## Test integrity gate

For all six test files:

```text
TEST_LOGIC_CHANGED=false
ASSERTION_REMOVED=false
ASSERTION_WEAKENED=false
SKIP_ADDED=false
TEST_RENAMED=false
ONLY_IDENTITY_CONSTANTS_REPINNED=true
```

Method bodies and test semantics must remain unchanged except where a literal identity comparison itself is represented directly in the method body; in that case only the literal SHA value may change.

The new expected SHA values must be derived from actual repository bytes after packaging, not copied from an unverified log or guessed.

## Transport identity rule

`custom_components/comelit/media_transport.py` remains governed by the original R30E contract: its only allowed change is the value of `MEDIA_NATIVE_BINARY_SHA256`.

Therefore any new full-file transport SHA used by R18/R20 must be computed **after** that one allowed edit and must correspond byte-for-byte to the committed transport file.

## Safety boundary

This amendment does not authorize:

```text
protocol/source changes
builder/generator changes
runtime logic changes
new network activity
Comelit live traffic
HA deploy/restart/reload
listener changes
Door/Gate/self-activation
R27 execution
external toolchain/package download
```

`LIVE_AUTHORIZED=false` and `LIVE_READY=false` remain unchanged.

## Acceptance additions

Before R30E can report PASS:

```text
ADDITIONAL_SCOPE_REPIN_GATE=PASS
TEST_LOGIC_CHANGED=false
DOC_HISTORICAL_EVIDENCE_CHANGED=false
R18_TRANSPORT_FILE_SHA_REPIN=PASS
R20_TRANSPORT_FILE_SHA_REPIN=PASS
FULL_OFFLINE_TESTS=PASS
```

The final write-scope gate must treat the seven paths above as approved only under these restrictions.

If any of these files requires a change beyond deterministic re-pin of current artifact identity, STOP with `RESULT=BLOCKED_SCOPE_AMENDMENT_INSUFFICIENT`.
