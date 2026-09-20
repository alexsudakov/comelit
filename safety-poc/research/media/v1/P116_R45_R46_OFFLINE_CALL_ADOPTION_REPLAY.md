# P116 / R45-R46 — offline call-adoption C harness and parser replay

Status: **offline research/test infrastructure complete**

Base evidence:
- R43/R43B: native call-adoption serializers and transport ACK semantics.
- R44: STRICT_NATIVE fake inbound peer and physical-call minimization strategy.

Current research branch at the start of this result:
`1b602c26a80cd06a832a3cad64ec71f5bf337203`.

No production file is modified by R45/R46.

~~~text
PRODUCTION_FILES_CHANGED=0
HA_DEPLOY_PERFORMED=false
HA_RESTART_PERFORMED=false
PHYSICAL_CALL_ATTEMPTS=0
NETWORK_COMELIT_ACTIONS=0
DOOR_ACTIONS=0
GATE_ACTIONS=0
~~~

## 1. R45: exact C call-adoption host harness

R45 adds a dependency-free C core and a host-compiled fake-writer harness:

- `entrance_p116_r45_call_adoption_core.py`
- `tests/native/p116_r45_call_adoption_host_harness.c`
- `tests/test_p116_r45_call_adoption_host_harness.py`

The harness composes the **actual extracted R35 and R36 C core regions** with
the new R45 adoption core.  It never opens a socket.  Every attempted TX is
captured by a fake writer.

The exact primary-native contracts exercised are:

~~~text
INVITE empty ACK:
  flags=0x80
  body_len=0
  tx_sequence=peer INVITE acknowledgement
  acknowledgement=peer INVITE sequence + 1
  empty ACK does not advance tx_sequence

local CAPABILITIES:
  opcode=0x0003
  len=8
  body=00 03 <runtime call type> 00 <runtime capability word LE32>
  body-bearing TX advances tx_sequence by 1

local ALERTING:
  opcode=0x000A
  len=3
  body=00 0A <runtime alerting byte>
  adoption path alerting byte=0
  body-bearing TX advances tx_sequence by 1
~~~

The harness verifies:

1. CALL_INIT transaction capture;
2. native-equivalent initial empty ACK;
3. duplicate initial ACK rejected;
4. exact CAPABILITIES serializer;
5. duplicate CAPABILITIES rejected;
6. exact ALERTING serializer;
7. duplicate ALERTING rejected;
8. peer CAPABILITIES matches the current call;
9. peer body-bearing DATA is acknowledged before the media trigger;
10. acknowledgement becomes `peer_sequence + 1`;
11. that empty ACK does not advance local TX sequence;
12. existing R36 media OPEN uses the updated transaction state;
13. duplicate peer CAPABILITIES cannot produce a second media OPEN;
14. a new call generation resets adoption state;
15. a foreign call connection fails closed;
16. network/Door/Gate side effects remain zero.

Exact CI on the warning-clean R45 state
`39ff679070fbb91728f700efe1bd821177ff864c`:

~~~text
Validate HACS=success
offline-safety=success
~~~

## 2. New defect proven offline: peer DATA ACK was missing before OPEN

This harness exposes an additional protocol-state defect in the current
production R36/R42 path.

Current R36 receives a peer CAPABILITIES DATA frame and can immediately call
the media OPEN trigger, but it does not first apply the native CTP receive
semantics for a body-bearing frame.

Primary-native R30C/R43B evidence requires:

~~~text
receive peer body-bearing DATA
-> local acknowledgement = peer sequence + 1
-> emit empty ACK flags 0x80
-> empty ACK does not advance local TX sequence
-> continue higher-level processing
~~~

Without that step, the current MEDIAREQ26 OPEN is serialized with stale
`call_ack`.

R45 therefore proves the future production ordering must be:

~~~text
peer CAPABILITIES
-> transport accept / call_ack = peer_sequence + 1
-> empty ACK 0x80
-> evaluate CAPABILITIES trigger
-> media OPEN
~~~

Classification:

~~~text
PEER_DATA_ACK_BEFORE_MEDIA_TRIGGER_REQUIRED=true
CURRENT_R36_PEER_DATA_ACK_MISSING=true
CURRENT_R36_MEDIA_OPEN_USES_STALE_ACK_POSSIBLE=true
R45_OFFLINE_CORRECT_ORDER_PROVEN=true
~~~

This was found without another physical call.

## 3. R46: outer VIP/post-UAut parser replay

R46 adds a second offline test layer:

- `tests/native/p116_r46_post_uaut_parser_replay_harness.c`
- `tests/test_p116_r46_post_uaut_parser_replay.py`

The host executable models the exact bounded outer frame consumed by
`p12_process_post_uaut()`:

~~~text
00 06
LE16 body_len
LE32 request_id
body
~~~

The body is then processed by the real extracted R35/R36/R45 C cores and the
same fake writer used for the call-adoption tests.

The replay covers the receive-loop failures that pure serializer tests cannot
catch.

### Coalesced-frame scenario

One synthetic receive buffer contains:

~~~text
CALL_INIT outer frame
+
peer CAPABILITIES outer frame
~~~

A single parser invocation must drain both and produce:

~~~text
CALL_INVITE_ACK
CALL_CAPABILITIES
CALL_ALERTING
CALL_PEER_DATA_ACK
MEDIA_OPEN
~~~

exactly once where appropriate.

This is the regression class that would have caught the earlier
`CALL_INIT -> return TRUE` defect without a physical ring.

### Fragmented-frame scenario

The harness feeds:
- less than the 8-byte outer header;
- then the rest of CALL_INIT;
- part of the next CAPABILITIES frame;
- then its remaining bytes.

The parser must wait for completeness, retain the partial buffer, and resume
without duplicate signaling.

### Negative scenarios

R46 also checks:
- unrelated request id -> consumed generically, no call signaling;
- malformed outer header -> fail closed, zero writes;
- duplicate peer CAPABILITIES -> transport ACK may be emitted per received DATA,
  but media OPEN remains exactly one.

Exact CI on
`1b602c26a80cd06a832a3cad64ec71f5bf337203`:

~~~text
Validate HACS=success
offline-safety=success
~~~

## 4. Physical-call replacement achieved

R44 + R45 + R46 now provide a practical offline stack:

~~~text
STRICT_NATIVE wire oracle
-> native-equivalent fake inbound peer
-> extracted C call-adoption core
-> extracted R35/R36 media state machine
-> outer VIP receive-buffer replay
-> intercepted TX transcript
~~~

This is enough to test, without the physical panel:

- CALL_INIT parsing;
- coalescing and fragmentation;
- transaction generation reset;
- connection direction;
- sequence/ack evolution;
- ACK/CAPABILITIES/ALERTING exact packet shape;
- duplicate signaling;
- peer capability matching;
- trigger ordering;
- exactly-one OPEN;
- fail-closed malformed traffic;
- zero Door/Gate/network side effects.

A physical ring is no longer justified for any of those questions.

## 5. Remaining blocker before production wiring

The **serializer shapes** are proven, but two CAPABILITIES inputs are still
runtime state in official native:

~~~text
call_type = byte at [CallFsm+824]+18
capability_word = CallFsm+840
~~~

The helper is a separate process and cannot read those C++ object fields
directly.

R37 already established that `CallFsm+840` contains important local media
eligibility/runtime state and that its writer/value was not present in the
then-staged evidence.  Therefore the production corrective must not simply
insert public/demo values such as `0x49/0x27`.

Before production wiring we need an **equivalent helper-visible source** for
the values, or proof that a stable local configuration value is correct for
this integration.

Preferred zero-new-ring evidence order:

1. statically recover the writer/initialization chain for `CallFsm+840` and
   the source of cfg byte +18 from the already staged native libraries;
2. if static evidence is insufficient, re-analyze an already-existing private
   official-app physical-call capture on CT120 (if retained) and extract only
   the sanitized local outbound CAPABILITIES/ALERTING fields;
3. do not create a new physical call merely to obtain those fields.

## Result

~~~text
=== P116 R45-R46 OFFLINE CALL ADOPTION / REPLAY ===

STRICT_NATIVE_PROFILE_READY=true
CALL_ADOPTION_C_HOST_HARNESS=PASS
OUTER_PARSER_REPLAY=PASS

INVITE_ACK_NATIVE_EQUIVALENT=PASS
LOCAL_CAPABILITIES_SERIALIZER=PASS
LOCAL_ALERTING_SERIALIZER=PASS

PEER_DATA_ACK_BEFORE_MEDIA_TRIGGER_REQUIRED=true
CURRENT_R36_PEER_DATA_ACK_MISSING=true
MEDIA_OPEN_UPDATED_ACK_MODEL=PASS

COALESCED_FRAME_REPLAY=PASS
FRAGMENTED_FRAME_REPLAY=PASS
DUPLICATE_OPEN_GATE=PASS
GENERATION_RESET_GATE=PASS
MALFORMED_FRAME_FAIL_CLOSED=PASS

PHYSICAL_CALL_AS_DEBUG_TOOL_REQUIRED=false
NEXT_PHYSICAL_CALL_REQUIRED_NOW=false

PRODUCTION_CORRECTIVE_READY=false
REMAINING_BLOCKER=LOCAL_CAPABILITIES_RUNTIME_FIELD_SOURCE
NEXT_REQUIRED_STEP=STATIC_RUNTIME_FIELD_PROVENANCE_OR_EXISTING_PRIVATE_CAPTURE_REANALYSIS

PRODUCTION_FILES_CHANGED=0
PHYSICAL_CALL_ATTEMPTS=0
NETWORK_COMELIT_ACTIONS=0
DOOR_ACTIONS=0
GATE_ACTIONS=0

=== END P116 R45-R46 OFFLINE CALL ADOPTION / REPLAY ===
~~~
