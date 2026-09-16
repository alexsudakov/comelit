# P116 / R30D — native CTP runtime integration result

```text
TASK_ID=COMELIT-P116-R30D-NATIVE-CTP-RUNTIME-INTEGRATION
BASE_SHA=9dc2a9bec0d0dee60cfc7c66aa1588642b7d5f0f
FINAL_SHA=ORCHESTRATOR_REPORTED (a commit cannot embed its own sha; authoritative value is in the Hermes final report)
ACTUAL_EXECUTOR=codex-cli
CODEX_VERSION=codex-cli 0.137.0
CHANGED_FILES=5
  safety-poc/research/media/v1/entrance_p116_r30b_call_transaction_model.py
  safety-poc/research/media/v1/entrance_rtpc_control_media_runtime_transform.py
  safety-poc/tests/test_p116_r30b_offline_call_transaction.py
  safety-poc/tests/test_p76_entrance_rtpc_control_media_runtime_parity.py
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
R30B_FOCUSED_TESTS=PASS
P76_FOCUSED_TESTS=PASS
FULL_OFFLINE_TESTS=FAIL
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
RESULT=BLOCKED
```

## Summary

R30D semantic integration was implemented inside the approved write scope:

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

All new PASS invariants reparse produced bytes/state. Negative derivation flips are included by corrupting the source packet or emitted packet and asserting the computed invariant becomes false or fail-closed.

## P76 Corrective Change

Before:

```c
p76_write_le32(out + 2, previous_client_ctpp_sequence + 0x00010000u);
```

This advanced the sequence byte for ordinary values but allowed carry into the acknowledgement byte at sequence `0xff`.

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

Focused R30B:

```text
COMMAND=PYTHONPATH=$PWD/src PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_p116_r30b_offline_call_transaction -v
WORKDIR=safety-poc
EXIT_CODE=0
Ran 33 tests in 0.012s
OK
skipped=0
```

Focused P76:

```text
COMMAND=PYTHONPATH=$PWD/src PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_p76_entrance_rtpc_control_media_runtime_parity -v
WORKDIR=safety-poc
EXIT_CODE=0
Ran 27 tests in 0.070s
OK
skipped=0
```

Full offline discovery:

```text
COMMAND=PYTHONPATH=$PWD/src PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
WORKDIR=safety-poc
EXIT_CODE=1
Ran 1520 tests in 31.987s
FAILED (failures=5, errors=2, skipped=5)
```

Full discovery non-R30D observations:

```text
NOT_A_R30D_REGRESSION: two pre-existing R29I datagram sink tests errored in the Codex exec sandbox.
Root cause: the sandbox blocks the UDP datagram sink path used by start_udp_sink / socket.AF_INET, SOCK_DGRAM.
Affected tests:
  test_p116_r29i_preopen_idle_and_sink_ownership.P116R29IPreOpenIdleAndSinkOwnership.test_nonzero_datagram_sink_materializes_final_counter_after_exit
  test_p116_r29i_preopen_idle_and_sink_ownership.P116R29IPreOpenIdleAndSinkOwnership.test_zero_datagram_sink_materializes_final_counter_after_exit
```

Full discovery scope blocker:

```text
BLOCKER=The required P76 generator text change updates generated source hashes. Five existing exact-hash tests outside the R30D write scope now fail and cannot be updated without widening the write gate.
Affected tests:
  test_p107_musl_package_provenance.P107MuslPackageProvenanceTests.test_generated_source_provenance_matches_p116_p106_transform_digest
  test_p116_canonical_generator_contract.P116CanonicalGeneratorContractTests.test_head_canonical_p106_emits_reachable_p116_and_preserves_p80
  test_p116_canonical_generator_contract.P116CanonicalGeneratorContractTests.test_head_canonical_p106_generation_is_deterministic
  test_p116_canonical_generator_contract.P116CanonicalGeneratorContractTests.test_head_cli_include_p116_switches_canonical_source_hash
  test_p116_r27_repeat_001a_contract.P116R27Repeat001AContractTests.test_required_diagnostics_are_present_and_bounded
```

Static safety:

```text
COMMAND=python3 scripts/static_safety_check.py
WORKDIR=safety-poc
EXIT_CODE=0
STATIC_SAFETY_CHECK=PASS
NETWORK_IMPORTS_PRESENT=false
COMELIT_ENDPOINTS_PRESENT=false
SOURCE_FILES_SCANNED=29
```

Compile custom component:

```text
COMMAND=python3 -m compileall -q ../custom_components/comelit
WORKDIR=safety-poc
EXIT_CODE=0
OUTPUT=<none>
```

Compile changed Python files:

```text
COMMAND=python3 -m compileall -q research/media/v1/entrance_p116_r30b_call_transaction_model.py research/media/v1/entrance_rtpc_control_media_runtime_transform.py tests/test_p116_r30b_offline_call_transaction.py tests/test_p76_entrance_rtpc_control_media_runtime_parity.py
WORKDIR=safety-poc
EXIT_CODE=0
OUTPUT=<none>
```

## Scope Gate

```text
git status --porcelain
 M safety-poc/research/media/v1/entrance_p116_r30b_call_transaction_model.py
 M safety-poc/research/media/v1/entrance_rtpc_control_media_runtime_transform.py
 M safety-poc/tests/test_p116_r30b_offline_call_transaction.py
 M safety-poc/tests/test_p76_entrance_rtpc_control_media_runtime_parity.py
?? safety-poc/research/media/v1/P116_R30D_NATIVE_CTP_RUNTIME_INTEGRATION_RESULT.md

git diff --stat origin/main
 .../entrance_p116_r30b_call_transaction_model.py   |  47 ++++++--
 ...ntrance_rtpc_control_media_runtime_transform.py |  23 +++-
 .../test_p116_r30b_offline_call_transaction.py     | 128 ++++++++++++++++++++-
 ...6_entrance_rtpc_control_media_runtime_parity.py |  24 ++++
 4 files changed, 208 insertions(+), 14 deletions(-)
```

The untracked result document is visible in `git status --porcelain` and is not included in the raw tracked `git diff --stat origin/main` output. The four tracked modifications plus the result document are inside the approved R30D write scope. No production files were changed.

## Residual Uncertainty

No live behavior was tested or authorized. `OFFLINE_SAFETY` and `VALIDATE_HACS` are unavailable because no PR was created. Full offline discovery is blocked by exact-source-hash fixtures outside the approved write scope after the required P76 generator correction; updating those fixtures requires an explicit write-scope expansion.

`FINAL_SHA` was filled in by the Hermes orchestrator, not by Codex: the executor is forbidden to touch git, so only the orchestrator can observe the committed branch head.
