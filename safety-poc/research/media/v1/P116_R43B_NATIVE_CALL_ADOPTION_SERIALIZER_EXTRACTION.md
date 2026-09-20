# P116 / R43B — native call-adoption serializer extraction

Status: **static native forensic only**.  No live Comelit action, no HA deploy,
no candidate execution, no network TX.

BASE_SHA=`1156948246f194fc4b11912892e6865636c2da51`

~~~text
PHYSICAL_CALL_ATTEMPTS=0
DOOR_ACTIONS=0
GATE_ACTIONS=0
DEPLOY_ACTIONS=0
RESTART_ACTIONS=0
NETWORK_TX=0
CANDIDATE_EXECUTED=false
~~~

## 1. Provenance (primary staged native evidence, CT120, read-only)

| Artifact | Description | SHA256 |
|---|---|---|
| `NATIVE_LIB_VIPCOMELIT` | primary build, ELF aarch64, stripped | `465c841a8a8400c8e301a18b728594b295a49b5bd5a127fa6b9643f94bf884f0` |
| `NATIVE_LIB_SAFECOMELIT` | second build, ELF aarch64, stripped | `83a6fa2f8166366c73d3dc1b1a487451579b7e1121ce01d6996d6befc06e239b` |

Tools used: `aarch64-linux-gnu-nm`, `aarch64-linux-gnu-objdump`, `readelf`,
`strings`, `sha256sum` and bounded Python analysis of the saved disassembly.

Only symbolic/relative anchors are recorded below.  No full disassembly,
absolute addresses, session material or payload bytes are published.

Method validation: the same extraction pipeline was first applied to the
already-closed `csp_send_mediareq26` contract and reproduced the R33 result
(`malloc(0x1a)`, length `0x1a`, wire opcode halfword `0x1100` → `00 11`,
body offsets `0..25`).

## 2. CTP TX serializer — empty-body flags rule

Serializer entry is an internal (non-exported) function; anchors are relative to
its prologue.

~~~text
CTP_TX_SERIALIZE(conn, body, len, flags_arg):
  +0x20  mov  w24, w3          ; flags argument
  +0x54  ldrb w22, [conn+140]  ; queued body length
  +0x70  cmp  w22, #0x0
  +0x7c  cset w10, eq          ; w10 = 1 when body is empty
  +0x88  orr  w8, w24, w10, lsl #7
  +0xac  strb w8, [buf]        ; wire byte 0 = flags
  +0x84  strb (0x18)    -> wire byte 1 (version)
  +0x8c  strh (rev16 id) -> wire bytes 2..3
  +0xa4  strb (conn+137) -> wire byte 4 (sequence)
  +0xa8  strb (conn+138) -> wire byte 5 (acknowledgement)
~~~

Consequence: an outgoing frame with an empty body always carries bit 7 set on
wire byte 0.

## 3. FIRST EMPTY ACK — proven path and bytes

Inbound RX handling of the call connection:

~~~text
ldrb w23, [recv]              ; wire byte 0 of the received frame
tbnz w23, #5  -> conn[+142]=1 ; peer bit 5
tbz  w23, #6  -> no ACK       ; peer bit 6 requests acknowledgement
otherwise:
  x0 = conn, x1 = NULL, w2 = 0, w3 = wzr
  bl CTP_TX_SERIALIZE
~~~

The caller passes a flags argument of `0x00` with an empty body, so the
serializer emits wire byte 0 = `0x00 | 0x80`.

Also proven in the same RX path:

~~~text
add  w8, w24, #0x1            ; w24 = accepted peer sequence
strb w8,  [conn+138]          ; outgoing acknowledgement = peer_seq + 1 (mod 256)
ldrb w8,  [recv, #5]          ; peer acknowledgement byte
cmp  w8,  conn[+136]
strb w8,  [conn+137]          ; local TX sequence follows the peer ack when equal
~~~

~~~text
FIRST_ACK_FLAGS=<0x80>
FIRST_ACK_BODY_LENGTH=0
FIRST_ACK_CONNECTION_SOURCE=rev16(conn[+36]) — native proven (R30C)
FIRST_ACK_SEQUENCE_SOURCE=conn[+137] — native proven (R30C)
FIRST_ACK_ACKNOWLEDGEMENT_SOURCE=conn[+138] = accepted_peer_sequence + 1
FIRST_ACK_SEQUENCE_ADVANCES=false
R30B_ACK_BYTE_MODEL_MATCHES_NATIVE=false
~~~

The frozen R30A/R30B offline model (hash-pinned by the historical phase test)
still emits `flags 0x00` and `acknowledgement == peer_sequence`.  It is left
untouched as historical evidence; the mismatch is recorded, not silently
rewritten.

Observed caller flags argument vocabulary in the same build:

| flags arg | meaning at call site |
|---|---|
| `0x00` | bare empty-body ACK (this contract) |
| `0x20` | connection teardown (`ctp_remove`, `ctp_remove_forced`, `ctp_close`) |
| `0x40` | data send (TX queue, payload path) |
| `0x60` | data send with connection state set |

## 4. csp_send_capab_report — exact body

~~~text
csp_send_capab_report(conn_id, arg1, arg2, arg3):
  malloc(0x8)
  strh 0x0300 -> body[0:2]      ; wire inner opcode 0x0003
  strb arg1   -> body[2]        ; call-type byte (runtime)
  strb arg2   -> body[3]        ; reserved byte
  str    arg3 -> body[4:8]      ; 32-bit capability/state word (runtime)
  ctp_write(conn_id, body, 0x8)
~~~

Caller (`CallFsm::initNewConnectionStart`, the only adjacent capabilities
call site):

~~~text
ldr  x8, [CallFsm+824]
ldr  w3, [CallFsm+840]        ; capability/state word
mov  w2, wzr                  ; reserved = 0
ldrh w0, [CallFsm+48]         ; call connection id
ldrb w1, [x8, #18]            ; call-type byte
bl   csp_send_capab_report
ldrh w0, [CallFsm+48]
mov  w1, wzr
bl   csp_send_alerting
~~~

~~~text
LOCAL_CAPABILITIES_OPCODE=0x0003
LOCAL_CAPABILITIES_BODY_LENGTH=8
LOCAL_CAPABILITIES_CALL_TYPE_SOURCE=byte at [CallFsm+824]+18 (runtime)
LOCAL_CAPABILITIES_WORD_SOURCE=CallFsm+840 (runtime)
LOCAL_CAPABILITIES_WORD_ENDIANNESS=little-endian 32-bit store at body[4:8]
LOCAL_CAPABILITIES_FIXED_BYTES=body[0:2]=00 03, body[3]=00 (reserved)
LOCAL_CAPABILITIES_EXACT_SERIALIZER_PROVEN=true
~~~

The public fixture `00 03 49 00 27 00 00 00` is byte-equal to this layout for
its own runtime values, which proves nothing about provenance.  `0x27` is not a
native constant.

## 5. csp_send_alerting — exact body (public shape refuted)

~~~text
csp_send_alerting(conn_id, arg1):
  malloc(0x3)
  strh 0x0a00 -> body[0:2]      ; wire inner opcode 0x000A
  strb arg1   -> body[2]        ; single runtime byte
  ctp_write(conn_id, body, 0x3)
~~~

At the call-adoption call site the argument is a compile-time zero
(`mov w1, wzr`), so the adopted-call alerting body is exactly `00 0a 00`.

~~~text
LOCAL_ALERTING_OPCODE=0x000A
LOCAL_ALERTING_BODY_LENGTH=3
LOCAL_ALERTING_FIELD_LAYOUT=body[0:2]=opcode (big-endian on wire), body[2]=runtime byte
LOCAL_ALERTING_FIXED_BYTES=body[0:2]=00 0a
LOCAL_ALERTING_RUNTIME_FIELDS=body[2] (0 on the call-adoption path)
LOCAL_ALERTING_EXACT_SERIALIZER_PROVEN=true
OP_SETUP_ACK_0X000C_REFUTED_FOR_ALERTING=true
PUBLIC_8_BYTE_FAKE_PANEL_SHAPE_REFUTED=true
~~~

`0x000C` exists in the same build as a different message: `csp_send_connect`
(`malloc(0x2)`, `ctp_write` length `0x2`, wire opcode `00 0c`).

Recovered opcode table (same pipeline, bounded):

| function | body length | wire opcode |
|---|---|---|
| `csp_send_connect` | 2 | `00 0c` |
| `csp_send_alerting` | 3 | `00 0a` |
| `csp_send_capab_report` | 8 | `00 03` |
| `csp_send_mediareq26` | 26 | `00 11` |

## 6. Cross-build check

Both contracts and the empty-body flags rule reproduce identically in
`NATIVE_LIB_SAFECOMELIT`:

- `csp_send_capab_report`: `malloc(0x8)`, wire opcode `00 03`, offsets `2/3/4..7`;
- `csp_send_alerting`: `malloc(0x3)`, wire opcode `00 0a`, runtime byte at offset 2;
- serializer: `orr w8, w24, w10, lsl #7` with the same empty-body predicate.

~~~text
VIP_NATIVE_MATCH=true
SAFE_NATIVE_MATCH=true
FIRMWARE_SPECIFIC_CONSTANTS_MIXED_INTO_PROTOCOL_CONTRACT=false
~~~

## 7. Offline consequence

All three strict gaps from R43 are now closed from primary native evidence, so
the R44 simulator's `STRICT_NATIVE` profile is complete and `LAB_CORROBORATION`
remains a separate, non-promotable mode.

~~~text
STRICT_NATIVE_PROFILE_READY=true
LAB_CORROBORATION_STILL_ISOLATED=true
LAB_CONSTANTS_PROMOTABLE_TO_PRODUCTION=false
~~~

## Result

~~~text
=== P116 R43B NATIVE CALL ADOPTION SERIALIZER EXTRACTION ===

BASE_SHA=1156948246f194fc4b11912892e6865636c2da51

FIRST_ACK_FLAGS=0x80
FIRST_ACK_BODY_LENGTH=0
FIRST_ACK_SEQUENCE_ADVANCES=false
R30B_ACK_BYTE_MODEL_MATCHES_NATIVE=false

LOCAL_CAPABILITIES_OPCODE=0x0003
LOCAL_CAPABILITIES_BODY_LENGTH=8
LOCAL_CAPABILITIES_CALL_TYPE_SOURCE=CALL_FSM_PLUS_824_PLUS_18_RUNTIME
LOCAL_CAPABILITIES_WORD_SOURCE=CALL_FSM_PLUS_840_RUNTIME
LOCAL_CAPABILITIES_WORD_ENDIANNESS=LITTLE_ENDIAN_32BIT
LOCAL_CAPABILITIES_EXACT_SERIALIZER_PROVEN=true

LOCAL_ALERTING_OPCODE=0x000A
LOCAL_ALERTING_BODY_LENGTH=3
LOCAL_ALERTING_EXACT_SERIALIZER_PROVEN=true

VIP_NATIVE_MATCH=true
SAFE_NATIVE_MATCH=true

STRICT_NATIVE_PROFILE_READY=true
LAB_CORROBORATION_STILL_ISOLATED=true

PRODUCTION_FILES_CHANGED=0
HA_DEPLOY_PERFORMED=false
HA_RESTART_PERFORMED=false
PHYSICAL_CALL_ATTEMPTS=0
DOOR_ACTIONS=0
GATE_ACTIONS=0
NETWORK_COMELIT_ACTIONS=0

READY_FOR_CALL_ADOPTION_C_HOST_HARNESS=true
READY_FOR_PRODUCTION_CORRECTIVE=false

=== END P116 R43B NATIVE CALL ADOPTION SERIALIZER EXTRACTION ===
~~~
