# P116 / R42-b — call-adoption signaling forensic

Status: **offline forensic / no live actions**

BASE_SHA=`643231f1ab789af8ea905953b9cf3cf335cd8f90`

PRODUCTION_MUTATED=false

PHYSICAL_CALL_ATTEMPTS=0

## 1. Door clarification

The owner withdrew the earlier physical-door-open observation. The sound was the
intercom itself, not the lock/door actuator.

```text
INITIAL_DOOR_OPEN_REPORT_WITHDRAWN=true
PHYSICAL_DOOR_EFFECT_OBSERVED=false
DOOR_SAFETY_INCIDENT=false
DOOR_FORENSIC_REQUIRED=false
```

The media workstream is therefore not blocked by a Door incident.

## 2. Current R42-b behavior after CALL_INIT

The current R35/R42-b path does the following at a detected inbound CALL_INIT:

1. lazily wires the existing transport writer;
2. parses the inbound CTP envelope;
3. captures the direction-transformed call CTP connection;
4. seeds local sequence from the inbound acknowledgement byte;
5. seeds local acknowledgement from the inbound sequence byte;
6. stores reversed logical source/destination roles;
7. increments `call_generation`;
8. consumes CALL_INIT and keeps the persistent listener alive.

The current production path does **not** contain a call-adoption signaling
emission after that capture:

```text
CURRENT_R42_SENDS_INVITE_ACK=false
CURRENT_R42_SENDS_LOCAL_CAPABILITIES=false
CURRENT_R42_SENDS_LOCAL_ALERTING=false
CURRENT_R42_WAITS_FOR_PEER_CAPABILITIES=true
```

R36 then waits for a call-bound CTP DATA frame whose inner opcode is
`OP_CAPABILITIES=0x0003`, matches it to the current call connection, checks
the video-request bit, and only then enters the R42 media-channel OPEN path.

This explains why CALL_INIT capture alone is not equivalent to native inbound
call adoption.

## 3. Official native order

Existing primary native evidence already recorded in
`P116_R29A_INBOUND_MEDIA_WIRE_CONTRACT.md` and
`P116_R36_ATTACHED_INBOUND_MEDIA_TRIGGER_CLOSURE.md` establishes the default
inbound-ring sequence:

```text
inbound CTP INVITE / START
-> native CTP connection adoption
-> CallFsm::initNewConnectionStart(call_ctp_id, msg)
-> csp_send_capab_report(call_ctp_id, local state)
-> csp_send_alerting(call_ctp_id, ...)
-> local FSM event 0x901
-> go_in_alerting
-> later peer CAPABILITY_REPORT event 0xa03
-> update CallFsm+100 capability word
-> guarded start_videorx(1)
-> local media RX setup
-> call-bound MEDIAREQ26 OPEN
```

The capability/alerting sends happen inside `initNewConnectionStart` before
the local transition into alerting. The later peer CAPABILITY_REPORT is a
second wire event; it is not the CALL_INIT frame.

Therefore the current R42-b implementation is waiting for a later call-signaling
event without reproducing the native call-adoption signaling that precedes it.

```text
R42_CALL_ADOPTION_SIGNALING_INCOMPLETE=true
```

## 4. Answer / accept is not the missing prerequisite

Native evidence in R36 separates the capability-driven video RX branch from
`go_connected()`. The CAPABILITY_REPORT branch can invoke
`start_videorx(1)` while the FSM is still `st_in_alerting`; it does not call
`go_connected()`.

The Android/SDK evidence recorded in R28 independently separates preview
startup (`startCall`) from explicit answer (`answer-call`).

```text
USER_ANSWER_REQUIRED_BEFORE_INITIAL_VIDEO_RX=false
PREVIEW_CAN_RUN_WHILE_RINGING=true
```

A physical answer/accept canary is therefore not the next justified experiment.

## 5. Transport ACK: state semantics are proven, byte-exact first ACK is not

R30C proves the native adopted-connection state:

- local/internal connection id is the received wire connection with direction
  bit transformed;
- first local TX sequence is sourced from inbound wire acknowledgement byte 5;
- initial local acknowledgement is sourced from inbound wire sequence byte 4;
- accepted body-bearing peer packets advance acknowledgement to
  `peer_sequence + 1 mod 256`;
- body-bearing local sends advance local sequence once;
- an empty ACK does not advance the local TX sequence.

R30B contains an offline `intercept_transport_ack()` serializer using the
captured call transaction state.

However the committed evidence is not sufficient to call the R30B ACK
**byte-identical to native**. R30B/R30A models `FLAG_ACK=0x00`, while the
R30C native serializer summary records that its TX flags byte is the caller
argument with bit `0x80` applied for an empty body. The exact caller-side
flags argument for the first adopted-call ACK is not recorded in the committed
bounded disassembly summary.

Therefore:

```text
INBOUND_INVITE_TRANSPORT_ACK_REQUIRED=true
ACK_CONNECTION_STATE=PROVEN_NATIVE
ACK_SEQUENCE_STATE=PROVEN_NATIVE
ACK_ACKNOWLEDGEMENT_STATE=PROVEN_NATIVE
ACK_EMPTY_SEND_DOES_NOT_ADVANCE_SEQUENCE=true
R30B_ACK_BYTE_MODEL_MATCHES_NATIVE=UNKNOWN
ACK_EXACT_FLAGS=UNKNOWN
```

No production ACK serializer should be promoted until that one wire-byte
ambiguity is closed from primary native evidence.

## 6. Local CAPABILITIES contract

The native order proves that `csp_send_capab_report` is sent on the adopted
call CTP transaction before alerting.

R36 plus the pinned independent public implementation confirm the peer-visible
CAPABILITIES wire discriminator:

```text
opcode = 0x0003
body length = 8
call-type byte is present at body offset 2
capability word is at body offsets 4..7
```

The pinned public implementation uses:

```text
00 03 49 00 27 00 00 00
```

but R36 explicitly classifies the public capability word `0x27` as
corroborating behavior, not as a production/native constant. Native
`initNewConnectionStart` passes this device's own `CallFsm+840` state to
`csp_send_capab_report`.

The committed evidence does not yet contain the byte-exact native serializer
mapping from that runtime state into the complete 8-byte body.

```text
LOCAL_CAPABILITIES_SENT=true
LOCAL_CAPABILITIES_OPCODE=0x0003
LOCAL_CAPABILITIES_BODY_LENGTH=8
LOCAL_CAPABILITIES_EXACT_SERIALIZER_PROVEN=false
LOCAL_CAPABILITIES_WORD_SOURCE=CallFsm+840_RUNTIME_STATE
PUBLIC_0X27_AS_RUNTIME_CONSTANT_FORBIDDEN=true
```

## 7. Local ALERTING / setup contract

Primary native evidence proves that `csp_send_alerting` is emitted immediately
after the local capability report and before the local `0x901` alerting state
event.

The pinned public outgoing-call implementation waits for two peer messages after
sending local CAPABILITIES:

1. peer `OP_CAPABILITIES=0x0003`;
2. peer `OP_SETUP_ACK=0x000C`.

Its fake-panel model responds to a capabilities request with an 8-byte
CAPABILITIES body followed by an 8-byte `OP_SETUP_ACK` body.

That is strong independent corroboration that the native
`csp_send_alerting` wire message corresponds to the setup/alerting response,
but the committed primary native evidence does not record the exact body bytes
or length produced by `csp_send_alerting`.

```text
LOCAL_ALERTING_SENT=true
LOCAL_ALERTING_FUNCTION=csp_send_alerting
LOCAL_ALERTING_OPCODE=0x000C_STRONGLY_CORROBORATED
LOCAL_ALERTING_BODY_LENGTH=8_STRONGLY_CORROBORATED
LOCAL_ALERTING_EXACT_SERIALIZER_PROVEN=false
```

The public fake-panel zero-filled body must not be promoted as a native runtime
constant without primary evidence.

## 8. Interpretation of the three passive physical rings

Three consecutive passive rings reached CALL_INIT/call-generation capture and
then produced no post-call trigger marker:

```text
capabilities_seen=false
trigger_reject_stage=null
media_channel=null
mediareq26_open_sent=false
```

The CALL_INIT buffered-frame drain did not change that result.

This is fully consistent with the implementation gap above: the helper captures
the incoming transaction but does not perform the native call-adoption signaling
sequence before waiting for the peer CAPABILITY_REPORT.

What is proven is the implementation defect, not the single causal packet:

```text
PASSIVE_NO_POST_CALL_TRAFFIC_CONSISTENT_WITH_MISSING_ACK=true
PASSIVE_NO_POST_CALL_TRAFFIC_CONSISTENT_WITH_MISSING_LOCAL_SIGNALING=true
ROOT_CAUSE_CLASS=CALL_ADOPTION_SIGNALING_INCOMPLETE
ROOT_CAUSE_PROVEN_AT_COMPONENT_LEVEL=true
SINGLE_CAUSAL_MISSING_PACKET_PROVEN=false
```

It is not yet proven whether the peer is blocked specifically by the missing
transport ACK, the missing local CAPABILITIES/ALERTING exchange, or the complete
missing native sequence.

## 9. Current fail boundary and development gate

```text
CURRENT_FAIL_BOUNDARY=CALL_ADOPTION_SIGNALING
READY_FOR_CALL_ADOPTION_DEV=false
```

The functional target is already clear:

```text
CALL_INIT
-> capture call transaction
-> native-equivalent empty transport ACK
-> native-equivalent local CAPABILITIES
-> native-equivalent local ALERTING/setup response
-> wait for peer CAPABILITIES
-> existing R42 trigger
-> media-channel OPEN
-> call-bound MEDIAREQ26 OPEN
```

But two byte-level contracts are still below the project's live-safety bar:

1. exact native flags byte for the first empty adopted-call ACK;
2. exact native `csp_send_capab_report` and `csp_send_alerting` body
   serializers, especially the runtime capability word sourced from
   `CallFsm+840`.

Those fields must be recovered from the already-staged primary native evidence;
they must not be replaced by public-example constants or guessed bytes.

## 10. Next evidence target

No further physical ring is required to close this gap.

The required next static extraction is bounded to:

- the CTP TX call site used for the first empty ACK on an adopted inbound
  connection, including the flags argument;
- `csp_send_capab_report` body allocation/length/field stores and its
  `ctp_write` call;
- `csp_send_alerting` body allocation/length/field stores and its
  `ctp_write` call.

After those three byte contracts are pinned, the call-adoption corrective can be
implemented offline without an answer/accept experiment.

## Final classification

```text
=== P116 R42-b CALL ADOPTION SIGNALING FORENSIC ===

BASE_SHA=643231f1ab789af8ea905953b9cf3cf335cd8f90

INITIAL_DOOR_OPEN_REPORT_WITHDRAWN=true
PHYSICAL_DOOR_EFFECT_OBSERVED=false
DOOR_SAFETY_INCIDENT=false

OFFICIAL_INBOUND_SEQUENCE=INVITE->ADOPTED_CTP->LOCAL_CAPABILITIES->LOCAL_ALERTING->ALERTING_STATE->PEER_CAPABILITIES->START_VIDEO_RX

INBOUND_INVITE_TRANSPORT_ACK_REQUIRED=true
R30B_ACK_BYTE_MODEL_MATCHES_NATIVE=UNKNOWN
ACK_EXACT_FLAGS=UNKNOWN

LOCAL_CAPABILITIES_SENT=true
LOCAL_CAPABILITIES_OPCODE=0x0003
LOCAL_CAPABILITIES_BODY_LENGTH=8
LOCAL_CAPABILITIES_EXACT_SERIALIZER_PROVEN=false

LOCAL_ALERTING_SENT=true
LOCAL_ALERTING_FUNCTION=csp_send_alerting
LOCAL_ALERTING_OPCODE=0x000C_STRONGLY_CORROBORATED
LOCAL_ALERTING_BODY_LENGTH=8_STRONGLY_CORROBORATED
LOCAL_ALERTING_EXACT_SERIALIZER_PROVEN=false

USER_ANSWER_REQUIRED_BEFORE_INITIAL_VIDEO_RX=false

CURRENT_R42_SENDS_INVITE_ACK=false
CURRENT_R42_SENDS_LOCAL_CAPABILITIES=false
CURRENT_R42_SENDS_LOCAL_ALERTING=false
CURRENT_R42_WAITS_FOR_PEER_CAPABILITIES=true

CURRENT_FAIL_BOUNDARY=CALL_ADOPTION_SIGNALING

PASSIVE_NO_POST_CALL_TRAFFIC_CONSISTENT_WITH_MISSING_ACK=true
PASSIVE_NO_POST_CALL_TRAFFIC_CONSISTENT_WITH_MISSING_LOCAL_SIGNALING=true

R42_CALL_ADOPTION_SIGNALING_INCOMPLETE=true
ROOT_CAUSE_PROVEN=true
SINGLE_CAUSAL_MISSING_PACKET_PROVEN=false

READY_FOR_CALL_ADOPTION_DEV=false
MISSING_REQUIRED_EVIDENCE=FIRST_ACK_FLAGS,CSP_SEND_CAPAB_REPORT_EXACT_BODY,CSP_SEND_ALERTING_EXACT_BODY

PHYSICAL_CALL_ATTEMPTS=0
DOOR_ACTIONS=0
GATE_ACTIONS=0
DEPLOY_ACTIONS=0
RESTART_ACTIONS=0

NEXT_REQUIRED_STEP=STATIC_NATIVE_SERIALIZER_EXTRACTION_NO_LIVE_TEST

=== END P116 R42-b CALL ADOPTION SIGNALING FORENSIC ===
```
