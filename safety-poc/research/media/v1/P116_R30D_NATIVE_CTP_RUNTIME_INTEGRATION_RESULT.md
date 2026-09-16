# P116 / R30D — native CTP runtime integration result

```text
TASK_ID=COMELIT-P116-R30D-NATIVE-CTP-RUNTIME-INTEGRATION
BASE_SHA=9dc2a9bec0d0dee60cfc7c66aa1588642b7d5f0f
FINAL_SHA=43b7096309dcb8c187dbbd6c11814f4df36134e3
FINAL_SHA_SEMANTICS=EXECUTOR_OBSERVED_BRANCH_HEAD (a commit cannot embed the sha of the commit that contains it; the authoritative pushed head is returned by the Hermes orchestrator report)
ACTUAL_EXECUTOR=codex-cli
CODEX_VERSION=codex-cli 0.137.0
CHANGED_FILES=8
  safety-poc/research/media/v1/entrance_p116_r30b_call_transaction_model.py
  safety-poc/research/media/v1/entrance_rtpc_control_media_runtime_transform.py
  safety-poc/tests/test_p116_r30b_offline_call_transaction.py
  safety-poc/tests/test_p76_entrance_rtpc_control_media_runtime_parity.py
  safety-poc/tests/test_p107_musl_package_provenance.py
  safety-poc/tests/test_p116_canonical_generator_contract.py
  safety-poc/tests/test_p116_r27_repeat_001a_contract.py
  safety-poc/research/media/v1/P116_R30D_NATIVE_CTP_RUNTIME_INTEGRATION_RESULT.md
LOCAL_CONNECTION_DIRECTION_RULE=NATIVE_PROVEN
OFFICIAL_NATIVE_LOCAL_ID_EQUIVALENCE=PROVEN
FIRST_LOCAL_TX_SEQUENCE_SOURCE=INBOUND_ACK_BYTE_OFFSET_5
INITIAL_LOCAL_ACK_SOURCE=INBOUND_SEQUENCE_BYTE_OFFSET_4
SEQUENCE_STATE_OWNER=CTP_TRANSPORT_CONNECTION_OBJECT
SEQUENCE_ACK_INDEPENDENT_BYTES=true
SEQUENCE_WRAP_0XFF_TO_0X00_WITHOUT_ACK_CARRY=PASS
ACK_WRAP_0XFF_TO_0X00_INDEPENDENT=PASS
EMPTY_ACK_ADVANCES_TX_SEQUENCE=false
PACKAGED_NATIVE_BINARY_REBUILT=false
HEAD_CANONICAL_SOURCE_CHANGED=true
NATIVE_REBUILD_REQUIRED=true
CURRENT_PACKAGED_BINARY_MATCHES_HEAD_SOURCE=false
LIVE_READY=false
R30B_FOCUSED_TESTS=PASS
P76_FOCUSED_TESTS=PASS
P107_PROVENANCE_TESTS=PASS
P116_CANONICAL_GENERATOR_TESTS=PASS
R27_REPEAT_CONTRACT_TESTS=PASS
FULL_OFFLINE_TESTS=PASS
STATIC_SAFETY=PASS
NETWORK_TX=0
DOOR_ACTIONS=0
GATE_ACTIONS=0
SELF_ACTIVATION_ACTIONS=0
REFRESH_OR_REPEAT_ACTIONS=0
PRODUCTION_LISTENER_TOUCHED=false
PRODUCTION_FILES_CHANGED=0
LIVE_AUTHORIZED=false
OFFLINE_SAFETY=UNAVAILABLE
VALIDATE_HACS=UNAVAILABLE
PR=none
RESULT=PASS
```

## Summary

R30D model/source integration is complete inside the approved write scope. The current HEAD source identities were split from historical/package provenance:

```text
HEAD default generator digest=2a96044de2455bf5f083090c691fbc693f518e8dbe0cf4d0b265327b90e21586
HEAD include_p116=True digest=1c89d61de4372d96b25f6894862741244753c107a3a9b9e04817250b3bea55b2
ARCHIVED a54fe39 P106 digest=0c15927dbc40bdb1f7c522f063a8a2f38c557f9eb735cdd981cdd49449595c79
PACKAGED native artifact source identity=93756730fd088b9227f37c4e0e3edbd18ac30c110db03b75bcc63f1c93952e66
R27 current generated source digest=1c9f13cff0d1d3599e00109146310c7372b1b0ae12117bb46ad68f091a841d42
```

The packaged native binary and `custom_components/comelit` pin were not modified. R30D green means the offline model/source side is correct; it is not live readiness. The next separate stage must be a native helper rebuild with reproducible provenance before any live test.

## Semantic Changes

- Adopted inbound CTP state no longer depends on caller-injected `next_tx_sequence_seed`.
- Initial local TX sequence is copied from inbound wire offset 5.
- Initial local acknowledgement is copied from inbound wire offset 4.
- Sequence and acknowledgement are independently updated uint8 fields.
- Empty ACK serialization does not advance local TX sequence.
- Accepted inbound body packets update acknowledgement to `(peer_sequence + 1) % 256` without advancing local TX sequence.
- Direction transform is promoted to native-proven, with fail-closed rejection for derived zero/reserved local connection ids.
- P76 no longer advances sequence via composite `previous_client_ctpp_sequence + 0x00010000u`; it writes connection bytes, advanced sequence byte, and acknowledgement byte independently.

## Boundary Test Mapping

```text
1. inbound sequence=S, inbound ack=A -> initial local sequence=A, local ack=S
   tests.test_p116_r30b_offline_call_transaction.P116R30BOfflineCallTransaction.test_native_adopted_state_comes_from_inbound_sequence_and_ack_bytes

2. local sequence=0xff, ack=X -> next body-bearing sequence=0x00, ack stays X
   tests.test_p116_r30b_offline_call_transaction.P116R30BOfflineCallTransaction.test_sequence_wrap_does_not_carry_into_acknowledgement
   tests.test_p76_entrance_rtpc_control_media_runtime_parity.P76RtpcControlMediaRuntimeParityTests.test_001a_sequence_wrap_advances_sequence_byte_without_ack_carry

3. peer sequence=0xff on accepted body -> local ack=0x00 and local TX sequence unchanged
   tests.test_p116_r30b_offline_call_transaction.P116R30BOfflineCallTransaction.test_peer_sequence_wrap_updates_ack_without_advancing_local_sequence

4. empty ACK -> local TX sequence does not advance
   tests.test_p116_r30b_offline_call_transaction.P116R30BOfflineCallTransaction.test_empty_ack_does_not_advance_local_tx_sequence
   tests.test_p116_r30b_offline_call_transaction.P116R30BOfflineCallTransaction.test_ack_does_not_advance_sequence_and_body_packets_advance_once_each

5. connection direction transform changes only connection-id semantics; sequence/ack untouched
   tests.test_p116_r30b_offline_call_transaction.P116R30BOfflineCallTransaction.test_native_connection_transform_does_not_mutate_sequence_or_acknowledgement

6. malformed/truncated/wrong-version/non-SYN initial packet -> fail closed
   tests.test_p116_r30b_offline_call_transaction.P116R30BOfflineCallTransaction.test_negative_01_malformed_truncated_ctp_envelope_rejected
   tests.test_p116_r30b_offline_call_transaction.P116R30BOfflineCallTransaction.test_negative_02_wrong_ctp_version_rejected
   tests.test_p116_r30b_offline_call_transaction.P116R30BOfflineCallTransaction.test_negative_03_non_syn_initial_packet_rejected

7. invalid/reserved/zero derived local connection id -> fail closed
   tests.test_p116_r30b_offline_call_transaction.P116R30BOfflineCallTransaction.test_native_derived_local_connection_id_invalid_zero_and_reserved_fail_closed
```

Digest flip regressions:

```text
tests.test_p116_canonical_generator_contract.P116CanonicalGeneratorContractTests.test_head_digest_pins_are_separate_from_archive_and_fail_on_byte_flip
tests.test_p107_musl_package_provenance.P107MuslPackageProvenanceTests.test_packaged_and_head_digest_pins_fail_on_byte_flip
tests.test_p76_entrance_rtpc_control_media_runtime_parity.P76RtpcControlMediaRuntimeParityTests.test_001a_sequence_wrap_advances_sequence_byte_without_ack_carry
```

## P76 Corrective Change

Before:

```c
p76_write_le32(out + 2, previous_client_ctpp_sequence + 0x00010000u);
```

After:

```c
static void p76_write_ctp_state_advance_sequence(p76_u8 *dst, p76_u32 previous)
{
    dst[0] = (p76_u8)(previous & 0xffu);
    dst[1] = (p76_u8)((previous >> 8) & 0xffu);
    dst[2] = (p76_u8)(((previous >> 16) + 1u) & 0xffu);
    dst[3] = (p76_u8)((previous >> 24) & 0xffu);
}
```

The corrected helper preserves bytes 2..3, advances only wire byte 4 modulo 256, and preserves wire byte 5.

## Verification

```text
COMMAND=PYTHONPATH=$PWD/src PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_p116_r30b_offline_call_transaction -v
WORKDIR=safety-poc
EXIT_CODE=0
Ran 33 tests in 0.011s
OK
skipped=0
```

```text
COMMAND=PYTHONPATH=$PWD/src PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_p76_entrance_rtpc_control_media_runtime_parity -v
WORKDIR=safety-poc
EXIT_CODE=0
Ran 27 tests in 0.074s
OK
skipped=0
```

```text
COMMAND=PYTHONPATH=$PWD/src PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_p107_musl_package_provenance -v
WORKDIR=safety-poc
EXIT_CODE=0
Ran 9 tests in 0.050s
OK
skipped=0
```

```text
COMMAND=PYTHONPATH=$PWD/src PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_p116_canonical_generator_contract -v
WORKDIR=safety-poc
EXIT_CODE=0
Ran 6 tests in 0.289s
OK
skipped=0
```

Initial R27 corrective run before splitting the runner-embedded pre-R30D hash:

```text
COMMAND=PYTHONPATH=$PWD/src PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_p116_r27_repeat_001a_contract -v
WORKDIR=safety-poc
EXIT_CODE=1
Ran 30 tests in 0.234s
FAILED (failures=1)
skipped=0
```

Final R27 run:

```text
COMMAND=PYTHONPATH=$PWD/src PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_p116_r27_repeat_001a_contract -v
WORKDIR=safety-poc
EXIT_CODE=0
Ran 30 tests in 0.230s
OK
skipped=0
```

Authoritative full offline discovery, executed by the Hermes orchestrator on the host with the exact workflow command:

```text
COMMAND=PYTHONPATH=$PWD/src PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
WORKDIR=safety-poc
EXECUTOR=Hermes orchestrator host
EXIT_CODE=0
Ran 1522 tests in 27.735s
OK (skipped=1)
```

Codex sandbox full offline discovery, preserved as an environment artifact:

```text
COMMAND=PYTHONPATH=$PWD/src PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
WORKDIR=safety-poc
EXIT_CODE=1
Ran 1522 tests in 31.973s
FAILED (errors=2, skipped=5)
```

Codex sandbox full discovery errors are the known environment artifact:

```text
NOT_A_R30D_REGRESSION: two pre-existing R29I datagram sink tests errored in the Codex exec sandbox.
Root cause: the sandbox blocks the UDP datagram sink path used by start_udp_sink / socket.AF_INET, SOCK_DGRAM.
Affected tests:
  test_p116_r29i_preopen_idle_and_sink_ownership.P116R29IPreOpenIdleAndSinkOwnership.test_nonzero_datagram_sink_materializes_final_counter_after_exit
  test_p116_r29i_preopen_idle_and_sink_ownership.P116R29IPreOpenIdleAndSinkOwnership.test_zero_datagram_sink_materializes_final_counter_after_exit
```

Static and compile checks:

```text
COMMAND=python3 scripts/static_safety_check.py
WORKDIR=safety-poc
EXIT_CODE=0
STATIC_SAFETY_CHECK=PASS
NETWORK_IMPORTS_PRESENT=false
COMELIT_ENDPOINTS_PRESENT=false
SOURCE_FILES_SCANNED=29
```

```text
COMMAND=python3 -m compileall -q ../custom_components/comelit
WORKDIR=safety-poc
EXIT_CODE=0
OUTPUT=<none>
```

```text
COMMAND=python3 -m compileall -q research/media/v1/entrance_p116_r30b_call_transaction_model.py research/media/v1/entrance_rtpc_control_media_runtime_transform.py tests/test_p116_r30b_offline_call_transaction.py tests/test_p76_entrance_rtpc_control_media_runtime_parity.py tests/test_p107_musl_package_provenance.py tests/test_p116_canonical_generator_contract.py tests/test_p116_r27_repeat_001a_contract.py
WORKDIR=safety-poc
EXIT_CODE=0
OUTPUT=<none>
```

Local reproduction of the remaining `.github/workflows/offline-safety.yml` steps, executed by the
Hermes orchestrator on the host in this worktree (same `working-directory: safety-poc`):

```text
python3 -m py_compile scripts/*.py
EXIT_CODE=0  PYCOMPILE_OK

for script in scripts/*.sh deploy/*.sh; do bash -n "$script"; done
EXIT_CODE=0  BASH_N_OK

TMPD=$(mktemp -d); DB="$TMPD/poc.sqlite3"
python3 -m comelit_safety_poc.cli --db "$DB" run --operation-id ci-ack  --target demo-door   --scenario ack                  --min-interval-seconds 0
python3 -m comelit_safety_poc.cli --db "$DB" run --operation-id ci-amb  --target demo-door-2 --scenario timeout_after_accept --min-interval-seconds 0
EXIT_CODE=0  SCENARIO_1_2_OK
python3 -m comelit_safety_poc.cli --db "$DB" run --operation-id ci-crash --target demo-door-3 --scenario ack --fault crash_after_arm --min-interval-seconds 0
EXIT_CODE=75  CRASH_RC=75   (workflow expects 75)
python3 -m comelit_safety_poc.cli --db "$DB" recover
EXIT_CODE=0  RECOVER_OK
python3 -m comelit_safety_poc.cli --db "$DB" show --operation-id ci-crash
STATE=UNKNOWN_OUTCOME   (workflow expects UNKNOWN_OUTCOME)
```

Every step of `offline-safety.yml` therefore reproduces green locally on the reviewed bytes. This is
local reproduction only: the GitHub `offline-safety` check itself has no run, because the branch was
pushed as `research/**` (the workflow triggers on `main` and `feat/**`) and no PR could be created.

## Scope Gate

```text
git status --porcelain
 M safety-poc/research/media/v1/P116_R30D_NATIVE_CTP_RUNTIME_INTEGRATION_RESULT.md
 M safety-poc/tests/test_p107_musl_package_provenance.py
 M safety-poc/tests/test_p116_canonical_generator_contract.py
 M safety-poc/tests/test_p116_r27_repeat_001a_contract.py

git diff --stat origin/main
 ...6_R30D_NATIVE_CTP_RUNTIME_INTEGRATION_RESULT.md | 301 +++++++++++++++++++++
 .../entrance_p116_r30b_call_transaction_model.py   |  47 +++-
 ...ntrance_rtpc_control_media_runtime_transform.py |  23 +-
 .../tests/test_p107_musl_package_provenance.py     |  40 ++-
 .../test_p116_canonical_generator_contract.py      |  31 ++-
 .../tests/test_p116_r27_repeat_001a_contract.py    |   6 +-
 .../test_p116_r30b_offline_call_transaction.py     | 128 +++++++++-
 ...6_entrance_rtpc_control_media_runtime_parity.py |  24 ++
 8 files changed, 573 insertions(+), 27 deletions(-)

git diff --name-only origin/main -- custom_components docs README.md .github hacs.json
<no output>
```

All changed files are inside the expanded R30D write scope. Production files changed: 0.

## Residual Uncertainty

No live behavior was tested or authorized. `OFFLINE_SAFETY` and `VALIDATE_HACS` are unavailable because no PR was created. There is no repository-local evidence in this corrective pass proving the existing packaged native binary was rebuilt from the R30D HEAD source; this is deliberately recorded as:

```text
PACKAGED_NATIVE_BINARY_REBUILT=false
HEAD_CANONICAL_SOURCE_CHANGED=true
NATIVE_REBUILD_REQUIRED=true
CURRENT_PACKAGED_BINARY_MATCHES_HEAD_SOURCE=false
LIVE_READY=false
```

The R27 live runner still pins the pre-R30D source identity and remains outside the R30D write scope:

```text
RUNNER_PATH=safety-poc/research/media/v1/ct120_run_p116_r27_repeat_001a_live.sh
RUNNER_EMBEDDED_EXPECTED_SOURCE_SHA=62e0023521cef0e4178248beb78408f89752d108d9d009c388ff153d94195368
R30D_HEAD_R27_GENERATED_SOURCE_SHA=1c9f13cff0d1d3599e00109146310c7372b1b0ae12117bb46ad68f091a841d42
R27_GENERATED_SOURCE_SHA_GATE_WOULD_FAIL_CLOSED_FOR_FRESH_R30D_BUILD=true
```

The test module preserves that runner value as `RUNNER_EMBEDDED_PRE_R30D_SOURCE_SHA` because the runner was not approved for R30D editing and because it documents the live-runner/native-helper rebuild boundary. Updating that runner pin belongs to the later native-rebuild / reproducible-provenance stage together with the rebuild itself. A green R30D is a PASS of the R30D model and sources only, not native-helper live readiness, and no live test may run before that rebuild stage.

`FINAL_SHA` is the branch head the Codex executor observed during its pass, not the sha of the commit that carries this document: a commit cannot embed its own sha, and the orchestrator's commit for a review pass necessarily lands after the executor has stopped. The authoritative pushed branch head is returned in the Hermes orchestrator report. Only the orchestrator writes git in this task; the executor never commits.
