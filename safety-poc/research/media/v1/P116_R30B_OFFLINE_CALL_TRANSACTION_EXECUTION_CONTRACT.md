# P116 / R30B — offline call-transaction execution contract

Status: **research contract / offline-only**

TASK_ID=`COMELIT-P116-R30B-OFFLINE-CALL-TRANSACTION-EXECUTION`

BASE_MAIN=`c76a8406c1f767b34e05113abb7e81d9a56fbd0e`

PARENT=`P116_R30_CALL_BOUND_CTP_ENVELOPE_RECOVERY.md`

LIVE_RUN=`NOT_AUTHORIZED`

NETWORK_TX_ALLOWED=`false`

PRODUCTION_FILES_ALLOWED=`false`

EXECUTION_AGENT=`CODEX`

REQUIRED_EXECUTOR=`codex-cli`

HERMES_ROLE=`ORCHESTRATOR_ONLY`

CODEX_REQUIRED=`true`

## 1. Purpose

R30A recovered the missing protocol layer between the persistent outer Viper `CTPP` channel and the inbound call-scoped CTP transaction.

The next bounded task is to turn that recovered structure into an **offline-only, intercepted call-transaction state machine** that can serialize the real wire shape without sending it.

R30B must answer one narrow question:

> Can the helper capture an inbound call transaction, preserve its transaction state, allocate one media-channel identity, and serialize one OPEN followed by one STOP as complete call-bound CTP packets, while all writes remain intercepted and network TX remains exactly zero?

This task is implementation/research work on executable artifacts and therefore follows the project iterative DEV/RESEARCH rule: Hermes orchestrates, Codex performs code/script changes and iterative corrections.

## 2. Facts inherited from R30A

The following are accepted inputs for this child:

- `v4_ctpp_channel_id` is the **outer carrier handle**, not the per-call CTP connection id.
- The CTP packet carried inside that handle has:
  - flags at byte `0`;
  - version at byte `1`;
  - connection id at bytes `2..3`;
  - sequence at byte `4`;
  - acknowledgement at byte `5`;
  - inner-body length at bytes `6..7`, big endian;
  - inner CTP body beginning at byte `8`.
- The inbound call INVITE has inner opcode `0x0001` and body length `40`.
- The logical application call id inside the INVITE body is distinct from the CTP connection id.
- Existing P76 `p76_build_client_001a` is structurally a **complete 60-byte CTP DATA packet** containing a 26-byte `OP_MEDIA_REQUEST` body.
- A 26-byte media body wrapped as CTP has total length `60 = 8 + 26 + 2 padding + 24 trailer`.
- R29C tested only a bare 26-byte request on the outer CTPP handle; that negative live result does not test the call-bound CTP wire form.

R30B must not reopen or reinterpret those conclusions unless contradictory repository evidence is found.

## 3. Evidence classifications that must remain explicit

R30B must distinguish these evidence levels in code comments, test names and the final research note:

### Proven / strongly supported offline

- field offsets and complete CTP envelope shape;
- separation of outer CTPP handle from inner CTP connection;
- inbound call transaction data are present in the received CTP payload;
- P76 full-packet structural shape;
- native media request is call-bound and uses the stored call transaction.

### Corroborating external behavior only

Pinned public `jfmlima/comelit-vip` uses a direction-bit transform (`connection ^ 0x8000`) to derive the peer-facing/local connection id for an adopted inbound call.

R30B may model that rule in a synthetic/offline candidate, but it must label it:

`LOCAL_CONNECTION_DIRECTION_RULE=CORROBORATING_EXTERNAL_ONLY`

It must **not** promote this rule to `PROVEN_PROTOCOL_CONSTANT` or `LIVE_READY` merely because the synthetic model passes.

### Still not proven

- exact official-native internal id representation expected by `ctp_write(call_ctp_id, ...)`;
- exact native initial local TX sequence seed for an adopted inbound call;
- exact helper-equivalent capability/alerting payload bytes and all native call-signaling bodies;
- a production-safe media-channel allocator equivalent to native `ViperTunnel::openMediaRXChannel`;
- live behavior of the complete call-bound packet.

## 4. Required implementation scope

Allowed new executable artifacts are limited to research/offline code under:

```text
safety-poc/research/media/v1/
safety-poc/tests/
```

Expected implementation shape:

```text
inbound synthetic or repository-derived CTP INVITE
-> parse complete CTP envelope
-> validate INVITE
-> capture immutable inbound peer facts
-> create bounded per-call transaction state
-> model/intercept transport ACK
-> model semantic capability/alerting ordering barrier
-> allocate exactly one synthetic media-channel id through an explicit test allocator
-> build 26-byte media OPEN body
-> wrap OPEN in complete 60-byte call-bound CTP DATA packet
-> intercept write
-> transition media state to ACTIVE
-> build 26-byte media STOP body using the same media-channel id
-> wrap STOP in complete call-bound CTP DATA packet
-> intercept write
-> transition media state to STOPPED
```

No socket, UDP, TCP, PseudoTCP, ICE, cloud bootstrap, Home Assistant service call or external process execution may be used by the model.

## 5. Required call transaction state

The per-call state object must keep protocol layers separate. At minimum it must expose semantically named fields equivalent to:

```text
outer_ctpp_handle                 # carrier only; never reused as call id
peer_connection_id                # captured from inbound CTP bytes 2..3
candidate_local_connection_id     # derived only under explicitly labelled candidate rule
peer_sequence                     # captured from inbound byte 4
peer_acknowledgement              # captured from inbound byte 5
next_tx_sequence                  # synthetic/offline runtime state, not a captured constant
next_tx_acknowledgement           # derived from observed peer packet under model rule
source_logical_address            # captured inbound destination, because outbound direction reverses roles
destination_logical_address       # captured inbound source
logical_call_id                   # parsed separately from INVITE body
call_phase
media_channel_id
media_phase
write_count
```

The model must make it impossible to substitute `outer_ctpp_handle` for `peer_connection_id` or `candidate_local_connection_id` without a test failure.

## 6. Inbound call adoption and ACK model

The existing production listener currently observes/deduplicates CALL_INIT but does not expose a first-class per-call transaction object.

R30B must add an **offline model only** that adopts a synthetic inbound INVITE and records the following ordering facts:

```text
INVITE_CAPTURED
-> CALL_TRANSACTION_CREATED
-> TRANSPORT_ACK_INTERCEPTED
-> CALL_SIGNALING_ORDER_BARRIER_REACHED
-> MEDIA_CHANNEL_ALLOCATED
-> MEDIA_OPEN_INTERCEPTED
```

The transport ACK model may use the externally corroborated behavior:

```text
acknowledgement = received_sequence + 1 modulo 256
```

and the candidate local connection id derived by direction-bit transform, but both must be explicitly tagged as candidate/corroborating semantics, not live-proven native generation rules.

The ACK must be **intercepted**, never written to a network sink.

## 7. Capability / alerting boundary

R29A static native evidence established that inbound-call adoption stores the call CTP id and that capability/alerting signaling precedes the alerting/media path.

R30B must model this as a semantic ordering barrier but must not invent bytes for protocol messages whose exact helper serialization is not sourced.

Required rule:

```text
MEDIA_OPEN_BEFORE_CALL_SIGNALING_BARRIER = REJECTED
```

The model may expose semantic intercepted events such as:

```text
CAPABILITY_STAGE_INTERCEPTED
ALERTING_STAGE_INTERCEPTED
CALL_SIGNALING_ORDER_BARRIER_REACHED
```

without claiming those events are exact wire serializers.

If implementation finds an already-proven exact builder in repository lineage, it may reuse it only with source anchors and tests. It must not synthesize a payload from guessed constants.

## 8. Sequence and acknowledgement evolution

The historical P76 name `previous_client_ctpp_sequence` must not be carried forward as one opaque 32-bit semantic sequence field.

R30B must represent the CTP header fields separately.

For the synthetic model:

- incoming peer sequence/ack are captured separately;
- ACK generation must not consume a body-bearing TX sequence step if the chosen CTP model treats empty ACK as non-advancing;
- every intercepted outbound CTP packet carrying a non-empty body must advance `next_tx_sequence` exactly once modulo 256;
- OPEN and STOP therefore use distinct consecutive transaction sequence states in the synthetic execution model;
- no sequence literal from a historical capture may be hard-coded as the runtime value.

The exact native initial TX seed remains `NOT_PROVEN`; tests must inject or deterministically generate synthetic seeds rather than promote an observed capture byte.

## 9. Media channel lifetime

R30B must make media-channel ownership explicit.

Rules:

- allocate at most one video media-channel id for the call;
- allocation happens only after the call-signaling barrier;
- the id must be non-zero and fit the builder field width;
- OPEN stores the allocated id into call media state;
- STOP must reuse **the same** id;
- second allocation while media is STARTING/ACTIVE is rejected;
- STOP before OPEN is rejected;
- second OPEN is rejected;
- second STOP is idempotently rejected or classified as already stopped; it must not create another intercepted wire action.

The allocator is a synthetic/offline proof component only unless an independently proven production allocator is reused.

Required marker:

`MEDIA_CHANNEL_ALLOCATOR_STATUS=OFFLINE_COMPONENT_ONLY`

## 10. OPEN serializer requirements

The inner 26-byte OPEN body must use the existing proven R29E/R29C field mapping rather than inventing a new layout.

Required inner-body structure:

```text
00..01  OP_MEDIA_REQUEST / 0x0011 wire bytes
02      OPEN action
03      OPEN flags
04..07  tunnel/channel address form slot
08..09  allocated media-channel id
10..25  media profile fields from the already accepted bounded client profile source
```

The exact field values and provenance must be anchored to existing R29E/R29C source lineage.

Then wrap that 26-byte body in the R30 CTP envelope using the **call transaction state**, not `v4_ctpp_channel_id` as a connection id.

Acceptance markers:

```text
OPEN_INNER_MEDIAREQ26_LENGTH=26
OPEN_FULL_CTP_PACKET_LENGTH=60
OPEN_USES_CALL_TRANSACTION_CONNECTION=true
OPEN_USES_OUTER_CTPP_HANDLE_AS_CONNECTION=false
OPEN_MEDIA_CHANNEL_MATCH=true
```

## 11. STOP serializer requirements

STOP is allowed only after a successful intercepted OPEN transition.

The inner 26-byte STOP body must preserve the existing proven stop layout:

- same media opcode family;
- STOP action/flags from R29E/R29C lineage;
- same persisted media-channel id as OPEN;
- payload/profile tail zeroed as already proven by the prior stop builder.

Wrap it in a complete CTP DATA packet using the same call transaction and current synthetic sequence/ack state.

Acceptance markers:

```text
STOP_INNER_MEDIAREQ26_LENGTH=26
STOP_FULL_CTP_PACKET_LENGTH=60
STOP_REUSES_OPEN_MEDIA_CHANNEL=true
STOP_USES_CALL_TRANSACTION_CONNECTION=true
STOP_AFTER_OPEN_ONLY=true
```

## 12. Intercepted writer

All candidate sends must terminate in an in-memory/intercepted writer.

The writer must record at least:

```text
semantic_kind
outer_ctpp_handle
serialized_ctp_packet
call_connection_id
sequence
acknowledgement
inner_opcode
inner_length
```

It must not open a socket or invoke a subprocess.

Final counters must distinguish:

```text
INTERCEPTED_ACK_WRITES
INTERCEPTED_MEDIA_OPEN_WRITES
INTERCEPTED_MEDIA_STOP_WRITES
NETWORK_WRITES
DOOR_ACTIONS
GATE_ACTIONS
SELF_ACTIVATION_ACTIONS
REFRESH_OR_REPEAT_ACTIONS
```

Required final values for the happy-path offline test:

```text
INTERCEPTED_ACK_WRITES=1
INTERCEPTED_MEDIA_OPEN_WRITES=1
INTERCEPTED_MEDIA_STOP_WRITES=1
NETWORK_WRITES=0
DOOR_ACTIONS=0
GATE_ACTIONS=0
SELF_ACTIVATION_ACTIONS=0
REFRESH_OR_REPEAT_ACTIONS=0
```

## 13. Mandatory negative tests

At minimum the focused suite must reject or fail closed on:

1. malformed/truncated CTP envelope;
2. wrong CTP version;
3. non-SYN packet passed as initial inbound call;
4. SYN with non-INVITE inner opcode;
5. outer CTPP handle reused as call connection id;
6. media OPEN before the call-signaling barrier;
7. media OPEN before media-channel allocation;
8. zero/invalid media-channel id;
9. second media-channel allocation;
10. second OPEN;
11. STOP before OPEN;
12. STOP with a different media-channel id;
13. second STOP causing another intercepted wire action;
14. unexpected self-activation/repeat path becoming reachable;
15. any network-writer code path becoming reachable;
16. any Door/Gate action becoming reachable.

## 14. Structural equivalence gates

The focused tests must compare the new complete CTP media packet against existing lineage by semantics, not by replaying a captured packet.

Required checks include:

- header flags/version are valid for a CTP DATA packet;
- body length is exactly `26`;
- inner opcode is exactly the existing media-request opcode;
- packet length is exactly `60`;
- trailer marker and logical-address placement match the existing CTP envelope model;
- connection bytes come from the call transaction state;
- media-channel id comes from the current allocation;
- OPEN and STOP share the same transaction identity and media-channel identity;
- STOP follows OPEN and uses advanced synthetic sequence state.

A repository-source test should continue to prove that the old R29C path queued the bare 26-byte body so the historical negative result is not silently rewritten.

## 15. Files and scope

Recommended new files:

```text
safety-poc/research/media/v1/entrance_p116_r30b_call_transaction_model.py
safety-poc/tests/test_p116_r30b_offline_call_transaction.py
safety-poc/research/media/v1/P116_R30B_OFFLINE_CALL_TRANSACTION_RESULT.md
```

A transform or generator may be added only if needed to prove equivalence with current C helper lineage. If added, keep it under the same research tree and keep all output intercepted/offline.

Do not modify:

```text
custom_components/comelit/**
docs/intercom-media-session-architecture.md
docs/ha-integration-target-architecture.md
README.md
production native helper payloads
```

unless a separate task explicitly changes scope.

## 16. Execution workflow

Because this is an iterative executable-artifact task, execution must use:

```text
Hermes orchestrator
-> Codex implementation
-> focused tests
-> full offline-safety regression
-> inspect failures
-> Codex correction if needed
-> repeat until PASS or proven BLOCKED
```

Required task environment semantics:

```text
REPOSITORY_PATH=/home/hermes/repos/comelit
SOURCE_OF_TRUTH=origin/main
EXECUTION_AGENT=CODEX
REQUIRED_EXECUTOR=codex-cli
HERMES_ROLE=ORCHESTRATOR_ONLY
CODEX_REQUIRED=true
LIVE_AUTHORIZED=false
NETWORK_TX_ALLOWED=false
DOOR_ALLOWED=false
GATE_ALLOWED=false
HA_DEPLOY_ALLOWED=false
HA_RESTART_ALLOWED=false
```

Hermes must create a fresh branch/worktree from the then-current `origin/main`, not continue this contract branch.

## 17. Required verification

Before opening the implementation PR:

- focused R30B tests PASS;
- repository full offline test suite PASS;
- `offline-safety` PASS;
- `Validate HACS` PASS where repository CI applies;
- diff contains only allowed research/test files;
- no production HA files changed;
- no sockets/network subprocesses added to the R30B model;
- no raw capture/proprietary artifact committed;
- no token/credential material present;
- exact final head SHA reported.

If any required gate is unavailable, report it as unavailable; do not convert it to PASS.

## 18. R30B completion criteria

R30B can be classified `PROVEN_OFFLINE` only if all of the following are true:

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
NETWORK_WRITES=0
DOOR_ACTIONS=0
GATE_ACTIONS=0
SELF_ACTIVATION_ACTIONS=0
REFRESH_OR_REPEAT_ACTIONS=0
PRODUCTION_FILES_CHANGED=0
```

Even with all of those PASS, the following must remain explicit:

```text
LOCAL_CONNECTION_DIRECTION_RULE=CORROBORATING_EXTERNAL_ONLY
OFFICIAL_NATIVE_LOCAL_ID_EQUIVALENCE=NOT_PROVEN
LIVE_CALL_BOUND_MEDIA=NOT_PROVEN
LIVE_AUTHORIZED=false
```

Therefore R30B PASS does **not** authorize a physical/live test by itself.

## 19. Decision after R30B

After a fully green R30B implementation, perform a review of the remaining unknowns before proposing another live attempt.

The likely next question is whether the direction-bit/local-id and adopted-call sequence semantics can be independently anchored from official native evidence or saved captures. If they can, do that offline first. Only if those semantics remain impossible to resolve offline should a new separately authorized one-shot live proof be designed.

No live permission from R29/R29I carries forward into R30B or any child phase.
