# P116 / R30C — native inbound CTP adoption evidence contract

Status: **research contract / offline-only / no live authorization**

TASK_ID=`COMELIT-P116-R30C-NATIVE-CTP-ADOPTION-EVIDENCE`

BASE_MAIN=`15eef49ddd21259f4f964a34d13670ec871034aa`

PARENT_R30B=`safety-poc/research/media/v1/P116_R30B_OFFLINE_CALL_TRANSACTION_RESULT.md`

PARENT_R30A=`safety-poc/research/media/v1/P116_R30_CALL_BOUND_CTP_ENVELOPE_RECOVERY.md`

LIVE_AUTHORIZED=`false`

NETWORK_TX_ALLOWED=`false`

PRODUCTION_FILES_CHANGED=`0`

## 1. Why R30C exists

R30A recovered the missing protocol layer: an inbound call arrives as a complete CTP packet carried inside the already-open outer Viper `CTPP` handle. R30B then built and verified an offline call-scoped transaction model that keeps the outer CTPP handle, the CTP connection field, the logical call id, sequence/acknowledgement state, and media-channel lifetime separate.

R30B is now accepted offline. It intentionally keeps two transport details unpromoted:

```text
LOCAL_CONNECTION_DIRECTION_RULE=CORROBORATING_EXTERNAL_ONLY
OFFICIAL_NATIVE_LOCAL_ID_EQUIVALENCE=NOT_PROVEN
```

and the result note also leaves the official native initial local TX sequence source unproven.

R30C is the bounded static/offline evidence step for those two unknowns. It does **not** build a live candidate and does not authorize any Comelit transmission.

## 2. Exact questions

R30C must answer only these questions:

1. When the official native stack receives an inbound CTP SYN/INVITE, what exactly is the `unsigned short call_ctp_id` passed through:

```text
VipUnitImpl::new_call_ctp_conn
-> VipUnitImpl::handleCtpStart
-> VipUnitImpl::vip_unit_accept_call
-> CallFsm::initNewConnectionStart(call_ctp_id, ...)
```

relative to the two wire bytes in the received CTP connection field?

2. When official native code later calls:

```text
ctp_write(call_ctp_id, payload, length)
```

what connection id is placed on wire: the same value, a direction-bit transformed value, or a value resolved through internal connection state?

3. For an adopted inbound CTP connection, where do the first local TX sequence and acknowledgement values come from, and which layer advances them?

No other protocol question is in scope for R30C.

## 3. Evidence already established before R30C

### 3.1 Official native evidence from R29A

R29A statically proved:

- `CallFsm::initNewConnectionStart(unsigned short, csp_msgbuf*)` stores an inbound call CTP id;
- capability/alerting signaling and later `csp_send_mediareq26` use that stored call CTP id;
- `csp_send_mediareq26` ends in `ctp_write(call_ctp_id, msg, 26)`;
- registration is not the call transaction.

What R29A did **not** prove is how the native CTP layer maps the callback's `call_ctp_id` to the two connection bytes of the wire envelope.

### 3.2 R30A envelope evidence

R30A established that the outer `v4_ctpp_channel_id` is only the Viper carrier handle. Inside its payload, a CTP envelope has:

```text
offset 0    flags
offset 1    CTP version
offset 2..3 CTP connection field
offset 4    sequence
offset 5    acknowledgement
offset 6..7 inner-body length
offset 8..  inner body
```

Therefore local-id equivalence is a property of the **inner CTP transaction**, not of the outer Viper CTPP handle.

### 3.3 R30B model evidence

R30B correctly keeps:

```text
outer_ctpp_handle
peer_connection_id
candidate_local_connection_id
logical_call_id
peer_sequence
peer_acknowledgement
next_tx_sequence
next_tx_acknowledgement
```

as distinct state.

The model deliberately injects `next_tx_sequence_seed` and labels the direction transform as corroborating-only instead of promoting either one to a native contract.

### 3.4 Pinned public `jfmlima/comelit-vip` corroboration

Pinned external ref:

```text
e3714dcccadb5bf934c32ce1400d891c3cfc61bb
```

The public implementation models CTP as follows:

- `peer_connection_id(connection)` toggles bit 15 of the 16-bit CTP connection value;
- on inbound adoption, `peer_id` is the received wire connection and `local_id` is the direction-toggled value;
- outbound packets for that adopted connection serialize `local_id`;
- on receiving a body-bearing packet, `ack()` sets local acknowledgement to `(peer_sequence + 1) mod 256` and sends an empty ACK;
- `CtpConnection.sequence` is client-owned state initialized locally;
- an empty ACK does not advance local sequence;
- body-bearing outbound sends advance local sequence by one.

This is useful corroboration and a working external implementation, but it is not proof of the official native library's internal-id semantics.

The external fake panel uses fixed synthetic sequence/ack values for tests. Those fixture values are not protocol constants and must not be promoted.

### 3.5 Existing P76 structural support

The historical P76 full CTP media packet stores the CTP header bytes `2..5` as one 32-bit composite value. Its later media packet adds `0x00010000` while preserving the other three bytes.

Given the recovered CTP layout, this operation increments byte 4 — the CTP sequence byte — while preserving the connection bytes and acknowledgement byte.

Therefore:

```text
P76_SEQUENCE_ADVANCEMENT_STRUCTURAL_SUPPORT=true
P76_INITIAL_SEQUENCE_SEED_SOURCE=NOT_PROVEN
```

This is structural/helper evidence only. It does not identify the official native inbound-adoption seed rule.

## 4. Required official-native evidence

R30C should use the already staged native text/disassembly evidence on CT120 and may generate **bounded textual excerpts only**. Proprietary binaries stay outside Git.

Target symbols / call chains, in priority order:

```text
VipUnitImpl::new_call_ctp_conn
VipUnitImpl::handleCtpStart
VipUnitImpl::vip_unit_accept_call
CallFsm::initNewConnectionStart
ctp_write
incoming CTP connection creation / accept / dispatch functions
CTP connection lookup/table functions used by ctp_write
CTP receive path that invokes new_call_ctp_conn
CTP sequence / acknowledgement update functions
```

Search specifically for evidence of:

- a direct pass-through of the received 16-bit connection value;
- XOR/EOR/OR/BIC/AND behavior involving bit 15 / `0x8000` / `0x7fff`;
- creation of a local/peer id pair in a connection object;
- `ctp_write` looking up an object by an opaque/native id before serializing a wire connection value;
- first local sequence initialization from random state, zero, peer state, a connection constructor, or another source;
- receive-side acknowledgement update from peer sequence;
- send-side sequence increment after body-bearing sends versus empty ACK.

Do not infer the rule only from symbol names. The accepted evidence must show dataflow or explicit transformation.

## 5. Saved-capture evidence allowed

If saved, already-authorized captures on CT120 contain an inbound CALL_INIT followed by official-client call-scoped responses, they may be used offline to validate relations between fields.

Allowed capture-derived statements are relations such as:

```text
client_connection == peer_connection XOR 0x8000
client_ack == peer_sequence + 1 mod 256
client_sequence_first == <classification only>
next_body_send_sequence == previous_body_send_sequence + 1 mod 256
```

but only if the relation is demonstrated across enough independent transactions/captures to avoid promoting one capture-specific scalar into a protocol constant.

Never commit raw PCAP, raw addresses, auth/session material, or literal full packets. Store only bounded semantic tables, redacted ids, relative relations, counts, and hashes.

## 6. Required classification for local connection id

R30C must end in exactly one of these classifications:

```text
A_NATIVE_CALLBACK_ID_IS_RECEIVED_WIRE_ID
B_NATIVE_CALLBACK_ID_IS_DIRECTION_TRANSFORMED_WIRE_ID
C_NATIVE_CALLBACK_ID_IS_OPAQUE_INTERNAL_HANDLE
D_NATIVE_LOCAL_ID_MAPPING_NOT_PROVEN
```

For A/B/C, evidence must also explain what `ctp_write(call_ctp_id, ...)` serializes on wire.

Only classification B with direct native/static or independently repeated capture evidence may promote the existing R30B XOR candidate to:

```text
OFFICIAL_NATIVE_LOCAL_ID_EQUIVALENCE=PROVEN
```

Otherwise it remains `NOT_PROVEN`.

## 7. Required classification for sequence / acknowledgement

R30C must report each field separately:

```text
FIRST_LOCAL_TX_SEQUENCE_SOURCE=
LOCAL_SEQUENCE_ADVANCEMENT_RULE=
INITIAL_LOCAL_ACK_SOURCE=
ACKNOWLEDGEMENT_UPDATE_RULE=
SEQUENCE_STATE_OWNER=
```

Allowed evidence states are:

```text
PROVEN_NATIVE
PROVEN_CAPTURE_RELATION
STRONGLY_SUPPORTED_EXTERNAL
NOT_PROVEN
```

The important distinction is ownership. If official native `ctp_write` or an internal CTP connection object owns sequence generation, the future helper should model that transport state rather than let media code inject arbitrary sequence values.

## 8. Promotion rules

R30C may promote a rule only when at least one of these holds:

1. official native dataflow directly proves it; or
2. multiple independent saved captures prove the relation and native code is consistent with it.

External public code alone may yield at most:

```text
STRONGLY_SUPPORTED_EXTERNAL
```

A single capture may yield only `OBSERVED` / `CAPTURE_RELATION_SINGLE_SAMPLE`, never a generation contract.

## 9. Fail-closed rules

If official native evidence cannot distinguish received-id from transformed-id from opaque-handle semantics:

```text
OFFICIAL_NATIVE_LOCAL_ID_EQUIVALENCE=NOT_PROVEN
```

If the initial TX sequence source cannot be proven:

```text
FIRST_LOCAL_TX_SEQUENCE_SOURCE=NOT_PROVEN
```

Do not substitute the public implementation's random seed or XOR rule as production truth merely to unblock a later live test.

## 10. No implementation in R30C

R30C is an evidence/research phase only.

It must not modify:

```text
custom_components/comelit/**
safety-poc/src/**
safety-poc/scripts/**
entrance_p116_r30b_call_transaction_model.py
entrance_p116_r30_call_ctp_envelope_model.py
entrance_p116_r29c_registered_ctpp_mediareq26_probe_transform.py
docs/intercom-media-session-architecture.md
docs/ha-integration-target-architecture.md
```

No new executable candidate, transform, runner, live-probe script, or network writer is allowed in this phase.

## 11. Safety

Mandatory:

```text
LIVE_RUN=NOT_RUN
LIVE_AUTHORIZED=false
NETWORK_TX=0
DOOR_ACTIONS=0
GATE_ACTIONS=0
SELF_ACTIVATION_ACTIONS=0
REFRESH_OR_REPEAT_ACTIONS=0
HA_DEPLOY_COUNT=0
HA_RESTART_COUNT=0
HA_RELOAD_COUNT=0
PRODUCTION_LISTENER_TOUCHED=false
PRODUCTION_FILES_CHANGED=0
```

No production listener handoff is needed. No CT120 process that communicates with Comelit should be started.

## 12. Required result artifact

The execution phase should add one result document only:

```text
safety-poc/research/media/v1/P116_R30C_NATIVE_CTP_ADOPTION_EVIDENCE_RESULT.md
```

It must include:

- evidence inventory with provenance/hash where appropriate;
- bounded symbol/dataflow findings;
- local-id classification A/B/C/D;
- `ctp_write` wire-id mapping result;
- sequence/ack classifications;
- capture relation table if saved captures are used;
- explicit distinction between official native, capture-derived, helper structural, and public external evidence;
- residual unknowns;
- exact next decision.

## 13. Acceptance markers

The result must end with a machine-readable block containing at least:

```text
TASK_ID=COMELIT-P116-R30C-NATIVE-CTP-ADOPTION-EVIDENCE
BASE_SHA=<fresh-main-at-execution>
NATIVE_EVIDENCE_AVAILABLE=true|false
SAVED_CAPTURE_EVIDENCE_USED=true|false
LOCAL_ID_CLASSIFICATION=A_NATIVE_CALLBACK_ID_IS_RECEIVED_WIRE_ID|B_NATIVE_CALLBACK_ID_IS_DIRECTION_TRANSFORMED_WIRE_ID|C_NATIVE_CALLBACK_ID_IS_OPAQUE_INTERNAL_HANDLE|D_NATIVE_LOCAL_ID_MAPPING_NOT_PROVEN
OFFICIAL_NATIVE_LOCAL_ID_EQUIVALENCE=PROVEN|NOT_PROVEN
CTP_WRITE_WIRE_ID_MAPPING=PROVEN|PARTIAL|NOT_PROVEN
FIRST_LOCAL_TX_SEQUENCE_SOURCE=<classification>
LOCAL_SEQUENCE_ADVANCEMENT_RULE=<classification>
INITIAL_LOCAL_ACK_SOURCE=<classification>
ACKNOWLEDGEMENT_UPDATE_RULE=<classification>
SEQUENCE_STATE_OWNER=<classification>
P76_SEQUENCE_ADVANCEMENT_STRUCTURAL_SUPPORT=true
PUBLIC_XOR_RULE_CLASSIFICATION=STRONGLY_SUPPORTED_EXTERNAL
PUBLIC_ACK_RULE_CLASSIFICATION=STRONGLY_SUPPORTED_EXTERNAL
NETWORK_TX=0
DOOR_ACTIONS=0
GATE_ACTIONS=0
SELF_ACTIVATION_ACTIONS=0
REFRESH_OR_REPEAT_ACTIONS=0
PRODUCTION_LISTENER_TOUCHED=false
PRODUCTION_FILES_CHANGED=0
LIVE_AUTHORIZED=false
RESULT=PROVEN_OFFLINE|PARTIAL_OFFLINE|BLOCKED_MISSING_NATIVE_EVIDENCE|FAIL
```

## 14. Next decision after R30C

If local-id mapping and sequence/ack ownership are proven strongly enough, the next phase may be an offline iterative R30D change to replace R30B's injected/corroborating transport fields with the proven rules and add negative tests.

If either remains unproven, do **not** build another live candidate. The next action is additional static/native/capture evidence acquisition only.

R30C success never authorizes a live test by itself.