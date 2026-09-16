# P116 / R30B Offline Call-Transaction Result

TASK_ID=`COMELIT-P116-R30B-OFFLINE-CALL-TRANSACTION-EXECUTION`

BRANCH=`research/p116-r30b-offline-call-transaction-model`

REQUESTED_BASE_SHA=`6c8ddf1418ff805c148bbcb49aeefed0f190df2c`

CONTRACT_BASE_MAIN_CONFLICT=`c76a8406c1f767b34e05113abb7e81d9a56fbd0e`

LIVE_AUTHORIZED=`false`

NETWORK_TX_ALLOWED=`false`

## Scope

R30B adds an offline-only Python call-transaction model and focused tests. It does not modify production integration files, architecture docs, the R30A envelope model, R29C transform, or native/helper C lineage.

Allowed files created:

- `safety-poc/research/media/v1/entrance_p116_r30b_call_transaction_model.py`
- `safety-poc/tests/test_p116_r30b_offline_call_transaction.py`
- `safety-poc/research/media/v1/P116_R30B_OFFLINE_CALL_TRANSACTION_RESULT.md`

## Identifier Separation

Layer diagram:

```text
outer ViP / CTPP carrier frame
  request_id = outer_ctpp_handle
  payload =
    CTP header bytes 2..3 = peer_connection_id / candidate_local_connection_id
    CTP header bytes 4..5 = peer_sequence / peer_acknowledgement
    CTP INVITE body bytes 24..27 = logical_call_id
```

The model keeps:

- `outer_ctpp_handle`: `OuterCtppHandle`, a typed integer carrier handle.
- `peer_connection_id`: exactly two `bytes`, captured from inbound CTP bytes `2..3`.
- `logical_call_id`: bytes parsed from inside the 40-byte INVITE body.

Passing `outer_ctpp_handle` where a CTP connection id is expected raises; it cannot silently serialize as a connection id.

## Evidence Classification

Proven / strongly supported offline:

- complete CTP envelope shape and 60-byte wrapped media-request shape;
- outer CTPP handle is distinct from the call CTP connection field;
- inbound INVITE exposes connection, sequence, acknowledgement and logical addresses;
- OPEN and STOP use a 26-byte `OP_MEDIA_REQUEST` body inside a complete CTP DATA packet;
- outbound logical addresses reverse the inbound roles.

Corroborating external only:

- `candidate_local_connection_id = peer_connection_id ^ 0x8000`;
- `next_tx_acknowledgement = received_sequence + 1 modulo 256`.

Not proven:

- official native local-id equivalence for `ctp_write(call_ctp_id, ...)`;
- official native initial local TX sequence seed;
- exact native capability/alerting payload serializers;
- production media-channel allocator equivalence;
- live behavior of the complete call-bound packet.

## Observed Marker Block

```text
CALL_TRANSACTION_CAPTURE=PASS
OUTER_CTPP_HANDLE_SEPARATION=PASS
ACK_MODEL_INTERCEPTED=PASS
CALL_SIGNALING_ORDER_BARRIER=PASS
MEDIA_CHANNEL_SINGLE_ALLOCATION=PASS
FULL_CTP_MEDIA_OPEN_SERIALIZATION=PASS
FULL_CTP_MEDIA_STOP_SERIALIZATION=PASS
OPEN_STOP_MEDIA_CHANNEL_IDENTITY=PASS
PER_CALL_SEQUENCE_STATE=PASS
INTERCEPTED_ACK_WRITES=1
INTERCEPTED_MEDIA_OPEN_WRITES=1
INTERCEPTED_MEDIA_STOP_WRITES=1
NETWORK_WRITES=0
DOOR_ACTIONS=0
GATE_ACTIONS=0
SELF_ACTIVATION_ACTIONS=0
REFRESH_OR_REPEAT_ACTIONS=0
PRODUCTION_FILES_CHANGED=0
LOCAL_CONNECTION_DIRECTION_RULE=CORROBORATING_EXTERNAL_ONLY
OFFICIAL_NATIVE_LOCAL_ID_EQUIVALENCE=NOT_PROVEN
LIVE_CALL_BOUND_MEDIA=NOT_PROVEN
LIVE_AUTHORIZED=false
```

Additional model markers:

```text
MEDIA_CHANNEL_ALLOCATOR_STATUS=OFFLINE_COMPONENT_ONLY
OPEN_INNER_MEDIAREQ26_LENGTH=26
OPEN_FULL_CTP_PACKET_LENGTH=60
OPEN_USES_CALL_TRANSACTION_CONNECTION=true
OPEN_USES_OUTER_CTPP_HANDLE_AS_CONNECTION=false
OPEN_MEDIA_CHANNEL_MATCH=true
STOP_INNER_MEDIAREQ26_LENGTH=26
STOP_FULL_CTP_PACKET_LENGTH=60
STOP_REUSES_OPEN_MEDIA_CHANNEL=true
STOP_USES_CALL_TRANSACTION_CONNECTION=true
STOP_AFTER_OPEN_ONLY=true
OUTBOUND_LOGICAL_ADDRESSES_REVERSED=true
STOP_SEQUENCE_FOLLOWS_OPEN=true
EVENT_ORDER=INVITE_CAPTURED->CALL_TRANSACTION_CREATED->TRANSPORT_ACK_INTERCEPTED->CAPABILITY_STAGE_INTERCEPTED->ALERTING_STAGE_INTERCEPTED->CALL_SIGNALING_ORDER_BARRIER_REACHED->MEDIA_CHANNEL_ALLOCATED->MEDIA_OPEN_INTERCEPTED->MEDIA_STOP_INTERCEPTED
```

All PASS/boolean packet and state markers in the block are derived in `verify_happy_path(...)`. The derivation reparses the inbound INVITE and intercepted `serialized_ctp_packet` bytes, then checks capture fields, outer-handle separation, ACK interception without sequence consumption, call-signaling event order, single media-channel allocation, OPEN/STOP connection bytes, media-channel identity, packet lengths, reversed logical addresses, and STOP sequence advancement.

## Negative-Test Inventory

1. malformed/truncated CTP envelope: `test_negative_01_malformed_truncated_ctp_envelope_rejected` covers truncation, inner length mismatch, and corrupted trailer marker
2. wrong CTP version: `test_negative_02_wrong_ctp_version_rejected`
3. non-SYN initial packet: `test_negative_03_non_syn_initial_packet_rejected`
4. SYN with non-INVITE opcode: `test_negative_04_syn_with_non_invite_opcode_rejected`
5. outer CTPP handle reused as call connection id: `test_negative_05_outer_ctpp_handle_reused_as_call_connection_id_rejected`
6. media OPEN before signaling barrier: `test_negative_06_media_open_before_call_signaling_barrier_rejected`
7. media OPEN before allocation: `test_negative_07_media_open_before_media_channel_allocation_rejected`
8. zero / invalid media-channel id: `test_negative_08_zero_or_invalid_media_channel_id_rejected`
9. second media-channel allocation: `test_negative_09_second_media_channel_allocation_rejected`
10. second OPEN: `test_negative_10_second_open_rejected`
11. STOP before OPEN: `test_negative_11_stop_before_open_rejected`
12. STOP with different media-channel id: `test_negative_12_stop_with_different_media_channel_id_rejected`
13. second STOP causing another intercepted wire action: `test_negative_13_second_stop_creates_no_wire_action`
14. self-activation / repeat path reachable: `test_negative_14_self_activation_or_repeat_path_fail_closed`
15. network-writer path reachable: `test_negative_15_network_writer_path_fail_closed_and_unincrementable`
16. Door / Gate path reachable: `test_negative_16_door_and_gate_actions_fail_closed_and_unincrementable`

All negative cases fail closed and emit no intercepted media wire action.

Corrective iteration 1 added:

- `test_report_evidence_is_derived_from_parsed_intercepted_bytes`: corrupts OPEN channel id, STOP channel id, and OPEN connection bytes, then verifies the computed evidence flips to `False`.
- `test_forbidden_counters_are_read_only_zero_properties`: proves the five forbidden counters are read-only zero properties and cannot be assigned non-zero values.

Corrective iteration 2 extended `test_report_evidence_is_derived_from_parsed_intercepted_bytes` to prove `OUTER_CTPP_HANDLE_SEPARATION` and `CALL_SIGNALING_ORDER_BARRIER` also flip to `False` under corrupted state.

## Structural Equivalence Findings

R29C mediareq26 layout anchors:

- `entrance_p116_r29c_registered_ctpp_mediareq26_probe_transform.py:393`: `write_le16(out + 0, 0x1100u)`
- `entrance_p116_r29c_registered_ctpp_mediareq26_probe_transform.py:398`: OPEN action byte `0x14`
- `entrance_p116_r29c_registered_ctpp_mediareq26_probe_transform.py:409`: STOP action byte `0x94`
- `entrance_p116_r29c_registered_ctpp_mediareq26_probe_transform.py:415`: media-channel id at inner offsets `8..9`
- `entrance_p116_r29c_registered_ctpp_mediareq26_probe_transform.py:467`: historical negative queue `p12_queue_vip_frame(v4_ctpp_channel_id, body, 26u, kind)`

Full packet lineage anchors:

- `entrance_rtpc_control_media_runtime_transform.py:286`: `p76_build_client_001a`
- `entrance_rtpc_control_media_runtime_transform.py:299`: inner opcode `0x0011`
- `entrance_rtpc_control_media_runtime_transform.py:300`: OPEN action/flags `0x14/0x32`
- `entrance_rtpc_control_media_runtime_transform.py:301`: target/media id field
- `entrance_rtpc_control_media_runtime_transform.py:303`: profile width `800`

The R30B model preserves the R29C body field mapping but changes the tested binding: OPEN/STOP are wrapped as complete 60-byte CTP DATA packets and use the call transaction connection bytes, not the outer CTPP handle.

## Verification

Focused R30B suite:

```text
Ran 27 tests in 0.014s

OK
```

Existing R30 envelope recovery suite:

```text
Ran 7 tests in 0.001s

OK
```

Static safety:

```text
STATIC_SAFETY_CHECK=PASS
NETWORK_IMPORTS_PRESENT=false
COMELIT_ENDPOINTS_PRESENT=false
SOURCE_FILES_SCANNED=29
```

Repository offline discovery, authoritative host / CI-equivalent verification supplied by Hermes, was run after corrective iteration 1 and again against the final branch head after corrective iteration 2 with identical result:

```text
Ran 1513 tests

OK (skipped=1)
```

Hermes also verified the previously failing isolated module on the host:

```text
python3 -m unittest tests.test_p116_r29i_preopen_idle_and_sink_ownership
Ran 10 tests in 6.535s

OK
```

This host result is authoritative for the repository offline regression because CI runs `unittest discover` from `safety-poc` with `PYTHONPATH=safety-poc/src` on a runner without the Codex exec sandbox.

Codex sandbox-restricted full discovery observation:

```text
Ran 1511 tests in 31.753s

FAILED (errors=2, skipped=5)
```

The two sandbox-observed errors were both in the pre-existing module `tests.test_p116_r29i_preopen_idle_and_sink_ownership`:

- `test_zero_datagram_sink_materializes_final_counter_after_exit`
- `test_nonzero_datagram_sink_materializes_final_counter_after_exit`

Sandbox-targeted rerun of that module reproduced:

```text
Ran 10 tests in 10.505s

FAILED (errors=2)
```

Root cause classification: the Codex exec sandbox blocks the UDP datagram sink used by that pre-existing R29I module (`socket.socket(AF_INET, SOCK_DGRAM)` plus `start_udp_sink`). `SANDBOX_R29I_SINK_FAILURE=NOT_A_R30B_REGRESSION`.

No R30B focused test failed. Baseline on pristine `origin/main` at `6c8ddf1418ff805c148bbcb49aeefed0f190df2c` was `Ran 1486 tests ... OK (skipped=1)`; R30B now contributes 27 focused tests for Hermes' `Ran 1513` full-suite count.

Hermes inspected the final tree: exactly three new files under `safety-poc/research/media/v1/` and `safety-poc/tests/`, zero modified existing files, and no production HA, docs, `safety-poc/src`, `safety-poc/scripts`, R30A model, or R29C transform change.

## Residual Unknowns

`OFFICIAL_NATIVE_LOCAL_ID_EQUIVALENCE=NOT_PROVEN`

`LIVE_CALL_BOUND_MEDIA=NOT_PROVEN`

`LIVE_AUTHORIZED=false`

R30B PASS is an offline structural result only. It does not authorize a live test, a Comelit transmission, Door/Gate action, self-activation, media refresh/repeat, HA deploy, HA restart, or any physical/device probe.
