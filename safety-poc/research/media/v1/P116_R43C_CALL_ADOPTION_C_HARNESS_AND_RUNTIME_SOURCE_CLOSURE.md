# P116 R43C — call-adoption C harness and runtime source closure

Status: offline research round. No production file, no native artifact, no HA
state, no Comelit connection was touched.

```text
BASE_SHA=5394ce7c11cb8726f7ef8780bf614c11ae094b13
NETWORK_TX=0
PHYSICAL_CALL_ATTEMPTS=0
DOOR_ACTIONS=0
GATE_ACTIONS=0
DEPLOY_ACTIONS=0
RESTART_ACTIONS=0
PRODUCTION_FILES_CHANGED=0
```

## 1. C harness result

`safety-poc/tests/native/p116_r43c_call_adoption_host_harness.c` is assembled by
`safety-poc/tests/test_p116_r43c_call_adoption_host_harness.py` from the exact R35, R36 and R45
dependency-free C regions plus the R43C scenario body, compiled with
`cc -std=c99 -Wall -Wextra -pedantic` (zero warnings) and run offline.

Everything the harness sends goes through `fake_writer()`; the media OPEN is intercepted through the
existing R45/R36 wiring, so no socket is opened anywhere.

| Pillar | Exact expectation | Result |
|---|---|---|
| First empty ACK | `flags=0x80`, `body_len=0`, `sequence=inbound_ack`, `acknowledgement=inbound_seq+1 mod 256`, TX sequence unchanged | PASS |
| Local CAPABILITIES | CTP DATA, inner opcode `0x0003`, length 8, body `00 03 <call_type> 00 <word LE32>` | PASS |
| Local ALERTING | CTP DATA, inner opcode `0x000A`, length 3, body `00 0A <runtime byte>` | PASS |
| Sequence model | CAPABILITIES = first body sequence, ALERTING = next, one advance per body send | PASS |
| Wrap | `0xFF -> 0x00` on the ALERTING body while the ACK byte stays `inbound_seq+1` | PASS |
| Parameterization | SET A (`0x49`/`0x00000027`) and SET B (`0x50`/`0x0000033B`) both build exact bodies | PASS |
| Peer replay | peer CAPABILITIES through the existing R36 classifier, empty peer DATA ACK before the trigger, exactly one intercepted OPEN | PASS |
| Negative cases | 18 fail-closed scenarios (see §4) | PASS |

The mutation detectors exist so the checks can flip: a mutated ACK with `flags=0x00`, `flags=0x40`, a
declared body, a shifted sequence byte, a wrong acknowledgement byte or a foreign connection each makes
the detector report `FAIL` (`R43C_07` … `R43C_12`).

```text
C_HOST_HARNESS=PASS
FIRST_ACK_NATIVE_EQUIVALENCE=PASS
CAPABILITIES_SERIALIZER_NATIVE_EQUIVALENCE=PASS
ALERTING_SERIALIZER_NATIVE_EQUIVALENCE=PASS
SEQUENCE_ACK_MODEL=PASS
R36_PARSER_REPLAY=PASS
CAPABILITIES_SEEN=true
CAPABILITIES_PARSE_OK=true
CAPABILITIES_CALL_MATCH=true
CAPABILITIES_VIDEO_REQUESTED=true
```

## 2. Runtime source provenance — call type

Native chain (already proven statically, re-stated here as the canonical source):

```text
CallFsm+824            = unitdata_t_TAG* (VipUnitImpl*)
[CallFsm+824] + 18     = VipUnitImpl+18  (CAPABILITIES call-type byte)
VipUnitImpl+18 writer  = VipUnitImpl::VipUnitImpl, default mov w8,#0x49, overwritten by ctor arg10
arg10 source           = System::createVipUnit argument, supplied by ComelitEngine::sysCreateVipUnit
sysCreateVipUnit value = VipUnitRole == 0 -> 0x49 ; == 2 -> 0x47 ; otherwise -> 0x3f
official JNI path      = VipEngine.createVipUnit -> native role forced to 0 (INTUNIT, per R49 DEX/JNI proof)
```

The value is therefore fixed by the role, not by a captured sample, and the role used by the official
VIP client path that our helper emulates is `0`.

```text
CALL_TYPE_NATIVE_SOURCE=[[CallFsm+824]+18] = VipUnitImpl+18 = f(VipUnitRole) via ComelitEngine::sysCreateVipUnit
CALL_TYPE_VALUE_FIXED_FOR_ENTRANCE=true
CALL_TYPE_FIXED_VALUE=0x49
CALL_TYPE_HELPER_SOURCE=EMULATED_OFFICIAL_VIP_CLIENT_ROLE_INTUNIT_0 (native role 0 -> 0x49)
CALL_TYPE_HELPER_SOURCE_PROVEN=true
```

This stays an emulated-role equivalence, not a claim that the helper reads a native `VipUnitRole` field:
the helper has no such field, and it must not invent one. It is recorded as a protocol-role
configuration whose value is derived from the proven native role mapping.

## 3. Runtime source provenance — capability word

```text
CallFsm+840 = the word read by initNewConnectionStart / initBeginOutgoingCall and passed to csp_send_capab_report
```

Static evidence across both staged libraries (R47, R48, R49 and this round) finds **23 exact reads and
zero proven writes** of `CallFsm[840..843]`; the third staged module contains no `CallFsm` symbol and no
`#840` reference at all. The field is read before any provable write on the inbound accept path.

What the official app does prove (DEX):

```text
VipUnitManager.createFromSettings: capability = AUDIO_SRC | AUDIO_DST | VIDEO_DST
                                                | (MSTREAM if resolution_setup__enable else 0)
                                = 0x07 | (0x20 if resolution_setup__enable else 0)
VipEngine.createVipUnit(..., int capabilities, ...) carries that mask into the native unit constructor
UnitCapability bits: AUDIO_DST=1 AUDIO_SRC=2 VIDEO_DST=4 VIDEO_SRC=8 OPENDOOR=16 MSTREAM=32
```

That formula is a proven app-side composition, but nothing yet ties it to the runtime word read at
`CallFsm+840`, and the peer's own bit requirements for the serialized word are unproven. Bit 3
(`VIDEO_SRC`) is consumed by local native code although the official mask never sets it
(`UNCOVERED_BITS={3}`), which is exactly the kind of gap that must not be closed by guessing.

```text
CAPABILITY_WORD_NATIVE_SOURCE=UNKNOWN (read-before-write; no static writer in either staged build)
CAPABILITY_WORD_INITIALIZATION=UNKNOWN
CAPABILITY_WORD_HELPER_SOURCE=NONE
CAPABILITY_WORD_HELPER_SOURCE_PROVEN=false
```

## 4. Negative harness cases

```text
1  CAPABILITIES before ACK                          -> rejected, no write      PASS
2  ALERTING before CAPABILITIES                     -> rejected, no write      PASS
3  duplicate initial ACK                            -> rejected, no second     PASS
4  duplicate local CAPABILITIES                     -> rejected, no second     PASS
5  duplicate local ALERTING                         -> rejected, no second     PASS
6  foreign connection id                            -> rejected, no write      PASS
7  ACK flags 0x00 instead of 0x80                   -> detector FAIL           PASS
8  ACK flags 0x40 (data) instead of 0x80            -> detector FAIL           PASS
9  ACK carrying a body                              -> detector FAIL           PASS
10 ACK with the wrong sequence byte                 -> detector FAIL           PASS
11 ACK with the wrong acknowledgement byte          -> detector FAIL           PASS
12 ACK with another connection                      -> detector FAIL           PASS
13 malformed peer CAPABILITIES length (< minimum)   -> rejected, no write      PASS
14 wrong inner opcode 0x000C                        -> rejected, no write      PASS
15 video-request bit clear                          -> no media OPEN           PASS
16 prior-generation frame                           -> rejected, no write      PASS
17 sequence wrap 0xFF -> 0x00                       -> correct, ACK independent PASS
18 Door / Gate / self-activation / network writer   -> unreachable (tokens absent, counters 0) PASS
```

## 5. Current production gap

The production R42-b listener transform still contains no call-adoption signaling and still waits for
the peer CAPABILITIES frame through the R36 classifier.

```text
CURRENT_R42_SENDS_INVITE_ACK=false
CURRENT_R42_SENDS_LOCAL_CAPABILITIES=false
CURRENT_R42_SENDS_LOCAL_ALERTING=false
CURRENT_R42_WAITS_FOR_PEER_CAPABILITIES=true
R42_CALL_ADOPTION_SIGNALING_INCOMPLETE=true
```

No production patch was made in this round.

## 6. Readiness

```text
C_HOST_HARNESS=PASS
FIRST_ACK_NATIVE_EQUIVALENCE=PASS
CAPABILITIES_SERIALIZER_NATIVE_EQUIVALENCE=PASS
ALERTING_SERIALIZER_NATIVE_EQUIVALENCE=PASS
SEQUENCE_ACK_MODEL=PASS
R36_PARSER_REPLAY=PASS
CALL_TYPE_HELPER_SOURCE_PROVEN=true
CAPABILITY_WORD_HELPER_SOURCE_PROVEN=false

READY_FOR_PRODUCTION_CORRECTIVE=false
MISSING_REQUIRED_EVIDENCE=CAPABILITY_WORD_HELPER_SOURCE
```

`0x49` and `0x27` remain synthetic/LAB fixtures. Neither is promotable to a production constant: the
call-type value is only usable through the proven role mapping, and the capability word has no proven
native-equivalent source at all. The harness keeps both parameterized so a future round cannot smuggle
either value into the serializer.

```text
LAB_0X49_PROMOTABLE=false
LAB_0X27_PROMOTABLE=false
NATIVE_CALL_TYPE_0X49_PROVEN_FOR_ENTRANCE=true
NATIVE_CAPABILITY_WORD_0X27_PROVEN_FOR_ENTRANCE=false
```

## 7. Remaining unknowns

1. The writer/initializer of `CallFsm[840..843]` before the first CAPABILITIES send is not proven
   statically in the staged builds (see R48/R49 for the checked-path boundary; this round added no new
   writer).
2. The capability bit subset the peer actually requires is unproven.
3. `VIDEO_SRC` (bit 3) is consumed locally but is not part of the official app-side mask.
