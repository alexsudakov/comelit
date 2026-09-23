# P116 R51 Native Capability Dataflow Closure

Status: offline static research only. No production file, native artifact, HA
state, Comelit network path, physical call, Door, Gate, ptrace/watchpoint, ADB,
or proprietary binary execution was touched.

```text
BASE_SHA=836cdee1ed6c2514c6da4d01946cc0f454deeab5
BRANCH=feat/p116-r42-attached-inbound-media-runtime
NETWORK_TX=0
PHYSICAL_CALL_ATTEMPTS=0
SELF_ACTIVATION_ATTEMPTS=0
DOOR_ACTIONS=0
GATE_ACTIONS=0
PRODUCTION_FILES_CHANGED=0
```

## 1. Source Inventory

Required prior repository reports read for context:

- `P116_R43B_NATIVE_CALL_ADOPTION_SERIALIZER_EXTRACTION.md`
- `P116_R43C_CALL_ADOPTION_C_HARNESS_AND_RUNTIME_SOURCE_CLOSURE.md`
- `P116_R48_CALL_ADOPTION_PRODUCTION_CORRECTIVE.md`
- `P116_R49_CAPABILITY_PROVENANCE_AND_CALL_ADOPTION_CORRECTIVE.md`
- related R29A/R30/R30B/R30C/R35/R36/R42/R45-R46 material under
  `safety-poc/research/media/v1/`

Prepared evidence used:

- `.r48-evidence/native/libvipcomelit.so`
- `.r48-evidence/native/libsafecomelit.so`
- `.r48-evidence/native/libcomelitvipkit.so`
- matching `.nm.txt`, `.sections.txt`, and bounded disassembly listings
- `.r48-evidence/r47/*.txt`
- `.r48-evidence/dex/*.strings.txt`
- `.r49-evidence/dex-java/*.java`

Sanitization boundary: this report records symbol names, relative offsets,
field formulas, and high-level pseudocode only. It does not include raw binary,
raw payload, raw decompiler database, absolute runtime address, token, session
material, or proprietary byte dumps.

## 2. Tool Inventory

Available and used:

- `python3`
- `/home/hermes/.r49-tools/bin/python` with `capstone 5.0.7`
- `readelf`
- `rg`, `sed`
- bounded local Python helpers under `/tmp`

Verified unavailable / not used:

- Ghidra: not installed / not used
- radare2/rizin: not installed / not used
- RetDec: not installed / not used
- Binary Ninja: not installed / not used
- angr: not installed / not used
- Java runtime: not available / not used
- host `objdump` for AArch64 disassembly: not usable for this target

`DECOMPILER_USED=none`. Existing jadx Java extractions were read; no new jadx
run was requested.

## 3. Forward Dataflow

This round did not repeat the R48/R49 literal `CallFsm+840` store search as the
primary method. The forward chain was followed from the official Java-native
capability argument into native object storage and then into `CallFsm`
construction.

Already-proven Java input, carried forward from R49:

```text
VipUnitManager.createFromSettings:
  vipUnitCapab = AUDIO_SRC | AUDIO_DST | VIDEO_DST
               | (MSTREAM if resolution_setup__enable else 0)
               = 0x07 | (0x20 if resolution_setup__enable else 0)

VipEngine.createVipUnit(sysId, vipAddress, subAddress, capabilities, flags)
  passes capabilities to native createVipUnit.
```

Native handoff:

```text
Java VipEngine.createVipUnit
  -> ComelitEngine::sysCreateVipUnit(..., native_role=0, capabilities, flags)
  -> System::createVipUnit(..., call_type=f(native_role), capabilities, flags)
  -> VipUnitImpl::VipUnitImpl(..., call_type, capabilities, cfg, flags)
```

Native role-to-call-type, unchanged from R48/R49:

```text
native role 0 -> 0x49
native role 2 -> 0x47
otherwise     -> 0x3f
```

`System::createVipUnit` passes the capability argument as the constructor stack
byte corresponding to `VipUnitImpl::VipUnitImpl` parameter after `call_type`.
`VipUnitImpl::VipUnitImpl` stores:

```text
VipUnitImpl+18 = call_type byte
VipUnitImpl+20 = zero-extended low byte of capabilities
VipUnitImpl+456 = flags
```

The constructor first writes a default `VipUnitImpl+20 = 0x0f`, then overwrites
it with the passed capability byte. For the official formula this means:

```text
VipUnitImpl+20 = low8(0x07 | optional 0x20)
```

Real `CallFsm` construction sites in both inbound and outgoing paths use the
same shape:

```text
CallFsm::CallFsm(id, unitdata=VipUnitImpl*, cfg=VipUnitImpl+464, arg4=VipUnitImpl+20)
```

`CallFsm::CallFsm` stores that fourth argument at:

```text
CallFsm+720 = arg4 = VipUnitImpl+20
```

The same constructor stores:

```text
CallFsm+824 = VipUnitImpl*
CallFsm+832 = cfg_t*
```

It does not store `CallFsm+840`.

Forward conclusion:

```text
VIPUNIT_CAPABILITY_CTOR_PARAMETER=System::createVipUnit arg4 / VipUnitImpl ctor stack capability byte
VIPUNIT_CAPABILITY_STORAGE_FOUND=true
VIPUNIT_CAPABILITY_STORAGE=VipUnitImpl+20 -> CallFsm+720
VIPUNIT_CAPABILITY_STORAGE_WIDTH=32-bit field holding zero-extended 8-bit capability
VIPUNIT_CAPABILITY_STORAGE_TRANSFORM=CONVERSION
VIPUNIT_CAPABILITY_REACHES_CALLFSM=false for CallFsm+840; true only for CallFsm+720
```

So the official `vipUnitCapab` dataflow reaches the `CallFsm` object, but at
`CallFsm+720`, not at `CallFsm+840`.

## 4. Backward Slice From `CallFsm+840`

Backward slice anchor:

```text
CallFsm::initNewConnectionStart:
  w3 = *(uint32_t *)(CallFsm+840)
  csp_send_capab_report(call_conn, call_type, 0, w3)

CallFsm::initBeginOutgoingCall:
  w3 = *(uint32_t *)(CallFsm+840)
  csp_send_capab_report(call_conn, call_type, 0, w3)
```

In `initNewConnectionStart`, the function writes call metadata parsed from the
inbound START message, then reads `CallFsm+840` for the local CAPABILITIES
report. The function has no dominating write to bytes `840..843`.

In `initBeginOutgoingCall`, the function writes outgoing call metadata and sends
START, then reads `CallFsm+840` for the local CAPABILITIES report. The function
has no dominating write to bytes `840..843`.

The constructor writes adjacent fields and nearby subobjects but leaves
`840..843` uncovered. Capstone alias analysis of `CallFsm` methods in both
libraries found stores around the 800..872 plane, but none covering
`840..843`. Helper calls receiving in-object pointers in this plane receive
`this+856`, `this+860`, or `this+864`, not `this+840`.

Backward conclusion:

```text
CALLFSM_840_ALIAS_SET_RESOLVED=true
CALLFSM_840_SUBOBJECT_BASE=NONE
CALLFSM_840_DEFINITELY_INITIALIZED=false
CALLFSM_840_POSSIBLY_UNINITIALIZED=true
```

The exact native source of `CallFsm+840` remains unproven. It is not derived
from the proven `VipUnitImpl+20` capability storage in the visible constructor
and call-init paths.

## 5. Object Layout Map: `CallFsm` 800..872

Capstone alias scan model:

- function entry `x0` is `this`;
- tracked moves and constant `add/sub` aliases such as `this+N`;
- store widths include byte/halfword/word/xword, pair stores, and SIMD/Q/D
  stores;
- helper calls are flagged when argument registers carry pointers into
  `this+800..872`;
- both `libvipcomelit.so` and `libsafecomelit.so` were checked.

| Offset | Width | Initialization / later stores | Readers / use | R51 classification |
|---:|---:|---|---|---|
| 800 | 1 | ctor zero; later state/media byte stores | state/media gates | local mutable byte |
| 804 | 4 | `handle_mediaoffer` stores helper return | media-offer state | local mutable word |
| 808 | 2 | `handle_mediaoffer` stores halfword | media-offer/send paths | local mutable halfword |
| 812 | 12 | outgoing callarg small-struct copy/zero | outgoing setup | inline copied small struct |
| 824 | 8 | ctor stores `VipUnitImpl*` | many `CallFsm` methods | unitdata pointer |
| 832 | 8 | ctor stores `cfg_t*` | config users | config pointer |
| 840 | 4 | no constructor, helper, pair, SIMD, indexed, shifted-base, aggregate-copy, or subobject store found | CAPABILITIES word and bit gates | unresolved / possibly uninitialized |
| 844 | 4 | ref/unRef/go_closed/st_closed stores | refcount-style readers | lifecycle counter |
| 848 | 4 | ctor zero; go_closed stores | status/timing readers | local mutable word |
| 852 | 1 | `setAudioRxEnable` stores | audio RX enable path | local mutable byte |
| 856 | 8 | ctor zeroes with D store; passed to queue helpers | event queue helper argument | queue/subobject field, not 840 |
| 860 | 4 | helper receives pointer into queue area | dequeue/event helpers | queue/subobject field, not 840 |
| 864 | 8 | destructor/request/media helpers receive pointer | mutex/string/list style helpers | subobject pointer area, not 840 |
| 872 | - | outside requested closed range | - | boundary |

Alias probes explicitly covered:

```text
shifted base pointer: covered; constructor uses this+120 alias, no coverage of 840
register holding this+K: covered; no writer to this+840
indexed addressing: checked in CallFsm methods; no resolved index writes to 840
partially covering STP: checked; adjacent 832..839 and 844..847 do not cover 840..843
SIMD/Q/D store: checked; stores at 856..863 and other subobjects do not cover 840
helper receiving pointer into object: found only 856/860/864 in this plane
inline copy / small struct assignment: found at 812..823, not 840
vtable/indirect helper: no argument alias to this+840 found
store through returned subobject pointer: no returned subobject alias to 840 found
constructor delegation: C1/C2 share the same constructor body
placement construction: real inbound/outgoing use operator new plus constructor; stack temporaries do not initialize 840
compiler aggregate copy: no aggregate copy covering 840 found
```

```text
R48_R49_STATIC_SEARCH_LIMITATION_FOUND=true
R48_R49_LIMITATION=R48/R49 proved no direct/literal CallFsm+840 writer, but did not close the independent forward chain proving VipUnit capability lands at CallFsm+720 and the alias/subobject set for 840.
```

## 6. Subobject Hypothesis

Hypothesis tested:

```text
subobject = CallFsm + N
store at subobject + M
N + M = 840
```

Resolved aliases in both builds show helper pointers in the nearby plane at
`this+856`, `this+860`, and `this+864`; inline stores cover 800, 804, 808,
812..823, 824..839, 844..848, 848..852, and 856..864. No base `N` with a store
offset `M` was found that covers `840..843`.

```text
CALLFSM_840_ALIAS_SET_RESOLVED=true
CALLFSM_840_SUBOBJECT_BASE=NONE
```

## 7. Incoming Versus Outgoing

Inbound path:

```text
VipUnitImpl::handleCtpStart
  operator new(0x390)
  CallFsm::CallFsm(id, VipUnitImpl*, cfg, VipUnitImpl+20)
  CallFsm::initNewConnectionStart(...)
  read CallFsm+840 -> csp_send_capab_report
```

Outgoing path:

```text
VipUnitImpl::beginOutgoingCall
  operator new(0x390)
  CallFsm::CallFsm(id, VipUnitImpl*, cfg, VipUnitImpl+20)
  CallFsm::initBeginOutgoingCall(...)
  read CallFsm+840 -> csp_send_capab_report
```

Both construction paths share the same `CallFsm` constructor and the same
`VipUnitImpl+20 -> CallFsm+720` copy. Both capability-report functions read the
same unresolved `CallFsm+840` word.

```text
INBOUND_OUTGOING_CALLFSM_CONSTRUCTOR_SHARED=true
CALLFSM_840_SOURCE_SAME_IN_BOTH_PATHS=true
```

The source is "same unresolved / possibly uninitialized field", not the proven
VIP unit capability field.

## 8. Cross-Build Result

The same semantics are present in `libsafecomelit.so`:

- `VipUnitImpl` constructor stores call type at `+18`;
- `VipUnitImpl` constructor stores the low byte of capabilities at `+20`;
- inbound and outgoing `CallFsm` construction pass `VipUnitImpl+20` as arg4;
- `CallFsm` constructor stores arg4 at `+720`;
- `CallFsm+840` is not initialized by the constructor;
- `initNewConnectionStart` and `initBeginOutgoingCall` read `+840` and pass it
  to `csp_send_capab_report`;
- alias/helper/subobject scan finds no store covering `840..843`.

```text
VIP_DATAFLOW_RESULT=vipUnitCapab -> VipUnitImpl+20 -> CallFsm+720; no path to CallFsm+840
SAFE_DATAFLOW_RESULT=vipUnitCapab -> VipUnitImpl+20 -> CallFsm+720; no path to CallFsm+840
VIP_SAFE_CAPABILITY_DATAFLOW_EQUIVALENT=true
```

## 9. Uninitialized Alternative

The real inbound/outgoing sites allocate `0x390` bytes with `operator new` and
then call the `CallFsm` constructor. C++ `operator new` does not guarantee
zeroed storage. The constructor writes many fields but not bytes `840..843`.
No site-local `memset`, `calloc`, full-object zeroing, placement aggregate
initialization, or constructor-called helper initializes `840..843`.

Therefore:

```text
CALLFSM_840_DEFINITELY_INITIALIZED=false
CALLFSM_840_POSSIBLY_UNINITIALIZED=true
```

This is compatible with repeated native usage in the narrow sense that native
code can repeatedly read and forward an object field even if static evidence
does not prove its initialization. It is not compatible with deriving a
production constant. If the field is allocator residue, repeated observations
could be stable by allocator reuse or prior object layout and still not be a
valid source contract.

No constant may be derived from this state.

## 10. Bit Semantics And The Bit-3 Puzzle

`UnitCapability` bits from the DEX side:

```text
bit0 AUDIO_DST  = 0x01
bit1 AUDIO_SRC  = 0x02
bit2 VIDEO_DST  = 0x04
bit3 VIDEO_SRC  = 0x08
bit4 OPENDOOR   = 0x10
bit5 MSTREAM    = 0x20
```

Official Java formula:

```text
0x07 | (0x20 if resolution_setup__enable else 0)
```

This formula sets bits 0, 1, 2, and optionally 5. It does not set bit 3.

Local native `CallFsm+840` users consume bits 0, 2, and 3. Bit 3 gates local
video-TX/source paths such as video-TX/media-request paths, while the official
Java unit-capability formula never sets `VIDEO_SRC`.

Because `CallFsm+840` is not proven equal to `vipUnitCapab`, R51 does not
substitute `0x27` for the local CAPABILITIES word. The bit-3 source remains
unknown.

```text
CALLFSM_840_SEMANTIC_CLASS=UNKNOWN
BIT3_SOURCE=UNKNOWN
```

The most defensible interpretation from static evidence is that `CallFsm+840`
is a distinct mutable call-state/capability word, but R51 cannot prove its
writer/source. It is not the official Java formula by the visible constructor
dataflow.

## 11. DEX Side

Read from existing local jadx extractions and string tables:

- `UnitCapability.kt`: enum values above are present in extracted Java.
- `VipEngine.kt`: `createVipUnit(int sysId, String vipAddress, String subAddress, int capabilities, int flags)` is native.
- `VipEngineWrapper`: forwards `createVipUnit` capabilities to `VipEngine`.
- `Role.kt`, `CallType.kt`, `CallDirection.kt`: role/call type names and mappings are present.
- R49 bytecode evidence for `VipUnitManager.createFromSettings` is carried
  forward: `vipUnitCapab = 0x07 | optional 0x20`.
- R48/R49 string evidence includes `resolution_setup__enable`, `vipUnitCapab`,
  `createFromSettings`, `createVipUnit`, `setOpendoorCapability`, and
  `setVideoCapability`.

Native-side post-create capability replacement API:

- No general post-create API that replaces `VipUnitImpl+20` or `CallFsm+840`
  was found in the extracted Java surface.
- Native `sysVipSetOpenDoorCapabProperities` / `VipUnitImpl::setOpenDoorCapabProperities`
  exists, but it only checks that `VipUnitImpl+20` already has bit 4 before
  setting open-door related properties. It does not rewrite `VipUnitImpl+20`.

```text
POST_CREATE_CAPABILITY_UPDATE_API_FOUND=false
```

## 12. Sanitized Pseudocode

Relevant native pseudocode only:

```text
ComelitEngine::sysCreateVipUnit(sysId, vipAddress, subAddress, role, capabilities, flags):
  unit = lookup system unit
  call_type = role == 0 ? 0x49 : role == 2 ? 0x47 : 0x3f
  return System::createVipUnit(vipAddress, subAddress, call_type, capabilities, flags)
```

```text
System::createVipUnit(vipAddress, subAddress, call_type, capabilities, flags):
  unit = operator new(sizeof(VipUnitImpl))
  VipUnitImpl::VipUnitImpl(
      unit_type,
      event_sender,
      system_id,
      generated_unit_id,
      vipAddress,
      subAddress,
      constant_arg,
      cfg,
      call_type_byte,
      capability_byte,
      flags)
  return unit_id
```

```text
VipUnitImpl::VipUnitImpl(..., call_type_byte, capability_byte, flags):
  this+18 = 0x49 default
  this+20 = 0x0f default
  ...
  this+18 = call_type_byte
  this+20 = zero_extend(capability_byte)
  this+456 = flags
```

```text
CallFsm::CallFsm(id, unitdata, cfg, cap_from_unit):
  initialize adjacent fields and subobjects
  this+720 = cap_from_unit
  this+824 = unitdata
  this+832 = cfg
  initialize this+848 and this+856
  // no write to this+840
```

```text
CallFsm::initNewConnectionStart(conn, msg):
  parse inbound START metadata
  call_type = *(uint8_t *)(*(this+824) + 18)
  word = *(uint32_t *)(this+840)
  csp_send_capab_report(conn, call_type, 0, word)
  csp_send_alerting(conn, 0)
```

```text
CallFsm::initBeginOutgoingCall(...):
  prepare outgoing START metadata
  send START
  call_type = *(uint8_t *)(*(this+824) + 18)
  word = *(uint32_t *)(this+840)
  csp_send_capab_report(conn, call_type, 0, word)
```

## 13. Decision

R51 closes the specific derivation question:

```text
IS_CALLFSM_840_DERIVED_FROM_VIPUNIT_CAPABILITY=false
```

Reason:

```text
vipUnitCapab -> native capability arg -> VipUnitImpl+20 -> CallFsm constructor arg4 -> CallFsm+720
```

There is no proven edge from `VipUnitImpl+20` or `CallFsm+720` to
`CallFsm+840`. `CallFsm+840` has no proven writer/source before the native
CAPABILITIES read in either inbound or outgoing construction path.

Decision gate:

```text
CASE=CASE C
CAPABILITY_WORD_PRIMARY_NATIVE_PROVEN=false
CAPABILITY_WORD_NATIVE_SOURCE=UNKNOWN
CAPABILITY_WORD_NATIVE_FORMULA=UNKNOWN
CAPABILITY_WORD_EQUALS_OFFICIAL_VIPUNIT_CAPABILITY=false
READY_FOR_PRODUCTION_CORRECTIVE=false
```

Only in this CASE C state may a future bounded watchpoint be recommended, and
only to identify the real writer/source of `CallFsm+840`, not to promote a
repeated observed value or allocator residue into a constant.

## 14. Required Markers

```text
DECOMPILER_USED=none
FORWARD_DATAFLOW_COMPLETED=true
BACKWARD_SLICE_COMPLETED=true
VIPUNIT_CAPABILITY_CTOR_PARAMETER=System::createVipUnit arg4 / VipUnitImpl ctor capability byte
VIPUNIT_CAPABILITY_STORAGE_FOUND=true
VIPUNIT_CAPABILITY_STORAGE=VipUnitImpl+20 -> CallFsm+720; not CallFsm+840
VIPUNIT_CAPABILITY_STORAGE_WIDTH=32-bit storage containing zero-extended byte
VIPUNIT_CAPABILITY_STORAGE_TRANSFORM=CONVERSION
VIPUNIT_CAPABILITY_REACHES_CALLFSM=false
CALLFSM_840_ALIAS_SET_RESOLVED=true
CALLFSM_840_SUBOBJECT_BASE=NONE
INBOUND_OUTGOING_CALLFSM_CONSTRUCTOR_SHARED=true
CALLFSM_840_SOURCE_SAME_IN_BOTH_PATHS=true
CALLFSM_840_DEFINITELY_INITIALIZED=false
CALLFSM_840_POSSIBLY_UNINITIALIZED=true
CALLFSM_840_SEMANTIC_CLASS=UNKNOWN
BIT3_SOURCE=UNKNOWN
POST_CREATE_CAPABILITY_UPDATE_API_FOUND=false
VIP_DATAFLOW_RESULT=vipUnitCapab reaches VipUnitImpl+20 and CallFsm+720, not CallFsm+840
SAFE_DATAFLOW_RESULT=vipUnitCapab reaches VipUnitImpl+20 and CallFsm+720, not CallFsm+840
VIP_SAFE_CAPABILITY_DATAFLOW_EQUIVALENT=true
IS_CALLFSM_840_DERIVED_FROM_VIPUNIT_CAPABILITY=false
CAPABILITY_WORD_NATIVE_SOURCE=UNKNOWN
CAPABILITY_WORD_NATIVE_FORMULA=UNKNOWN
CAPABILITY_WORD_EQUALS_OFFICIAL_VIPUNIT_CAPABILITY=false
CAPABILITY_WORD_PRIMARY_NATIVE_PROVEN=false
CAPABILITY_WORD_HELPER_SOURCE=UNKNOWN
CAPABILITY_WORD_HELPER_SOURCE_PROVEN=false
R48_R49_STATIC_SEARCH_LIMITATION_FOUND=true
R48_R49_LIMITATION=prior literal writer searches did not establish forward VipUnit capability storage or close the alias/subobject set; R51 shows the capability lands at CallFsm+720 while CallFsm+840 remains source-unknown
NETWORK_TX=0
PHYSICAL_CALL_ATTEMPTS=0
SELF_ACTIVATION_ATTEMPTS=0
DOOR_ACTIONS=0
GATE_ACTIONS=0
PRODUCTION_FILES_CHANGED=0
```

## 15. Offline Checks

No production code or harness code was changed. The only repository change is
this research report.

Offline checks performed:

```text
capstone_alias_scan=PASS
vip_safe_cross_build_static_comparison=PASS
focused_tests=NOT_REQUIRED documentation-only research artifact
```

## 16. Turn 2: Alias / Indirect Boundary Closure

Turn 2 keeps the Turn 1 sentinel block intact and adds a bounded static closure
for the remaining bare-object, RMW, `720 -> 840`, external-writer, and object
extent questions. This pass used the same staged native modules and offline
Capstone/textual disassembly artifacts:

```text
libvipcomelit.so
libsafecomelit.so
libcomelitvipkit.dis.txt / libcomelitvipkit.nm.txt
```

No R48/R49 literal search was restarted. The new scan was constrained to the
specific construction-path and alias shapes requested for this turn.

### T2-1. Bare-`this` Helper Writers

On the inbound construction path:

```text
VipUnitImpl::handleCtpStart
  -> CallFsm::CallFsm(...)
  -> CallFsm::setEventLogger(...)
  -> CallFsm::init()
  -> CallFsm::initNewConnectionStart(...)
```

On the outgoing construction path:

```text
VipUnitImpl::beginOutgoingCall
  -> CallFsm::CallFsm(...)
  -> CallFsm::init()
  -> CallFsm::initBeginOutgoingCall(...)
```

Calls where `x0` or another argument carries the whole `CallFsm*`, rather than
`this+K`, are:

| Caller | Callee | Whole-object argument | `+840` writer result |
|---|---|---:|---|
| `VipUnitImpl::handleCtpStart` | `CallFsm::CallFsm(...)` | `x0` | no, ctor stores `+720`, `+824`, `+832`, adjacent `+848`, but not `+840` |
| `VipUnitImpl::handleCtpStart` | `CallFsm::setEventLogger(...)` | `x0` | no, stores `+904` then passes dispatcher object onward |
| `VipUnitImpl::handleCtpStart` | `CallFsm::init()` | `x0` | no, loads `this+8` and tail-calls `MediaManager::init()` |
| `VipUnitImpl::handleCtpStart` | `CallFsm::initNewConnectionStart(...)` | `x0` | no, reads `+840` for `csp_send_capab_report`; no store to `+840` |
| `VipUnitImpl::handleCtpStart` failure path | `CallFsm::~CallFsm()` / `operator delete` | `x0` | destructor cleanup path, not a pre-serializer writer |
| `VipUnitImpl::beginOutgoingCall` | `CallFsm::CallFsm(...)` | `x0` | no, same ctor |
| `VipUnitImpl::beginOutgoingCall` | `CallFsm::init()` | `x0` | no |
| `VipUnitImpl::beginOutgoingCall` | `CallFsm::initBeginOutgoingCall(...)` | `x0` | no, reads `+840` for `csp_send_capab_report`; no store to `+840` |
| `VipUnitImpl::beginOutgoingCall` failure path | `CallFsm::~CallFsm()` / `operator delete` | `x0` | destructor cleanup path, not a pre-serializer writer |
| `CallFsm::initNewConnectionStart` | `CallFsm::start_audiorx()` | `x0=this` on subtype branch | no, reads/stores audio/media fields and sends media request; no `+840` store |

Helper calls in these functions that receive `this+K` instead of bare `this`
remain subobject-only: `evq_init/evq_add` receive the event queue area
(`this+0x38`/constructor alias from `this+120` back to `this+0`), `logaddr_cpy`
receives address fields such as `this+0x58` and `this+0x91`, and the mutex/queue
helpers receive `this+856`, `this+860`, or `this+864` style subobject pointers.
The indirect call inside `initNewConnectionStart` is on the event sender object
loaded from `[unitdata+296]`; the arguments are event/logaddr scalars and nulls,
not a bare `CallFsm*`.

```text
BARE_THIS_HELPER_WRITER=NONE
```

### T2-2. Read-Modify-Write on `CallFsm+840`

The Turn 2 Capstone scan looked for the RMW shape:

```text
ldr/ldrb/ldrh [base,#840] -> orr/and/bic/add/lsl/... -> str/strb/strh [base,#840]
```

across the staged `libvipcomelit.so` and `libsafecomelit.so`, and the textual
third-module disassembly. Result:

```text
RMW_ON_840_FOUND=false
RMW_ON_840_FUNCTIONS=NONE
```

All `CallFsm`-owned `#840` uses in the media call plane are reads. The only
literal `#840` stores found in the broader three-module text are non-CallFsm
`ConfigReaderSafeVedo` object/list-description stores in `libsafecomelit.so`
and stack stores; none match a `CallFsm` RMW.

### T2-3. Copy / Computation From `+720` to `+840`

The constructor stores the fourth constructor argument at `CallFsm+720`.
Capstone found no `CallFsm` method that reads `[this,#720]` and then stores or
merges into `[this,#840]`. It also found no local arithmetic path that computes
`+840` from `+720`, `+824`, `VipUnitImpl+20`, `VipUnitImpl+18`, `cfg` fields, or
START-message metadata before the CAPABILITIES serializer reads `+840`.

In the checked media `CallFsm` plane, local `CallFsm+720` use is limited to
constructor initialization from the `VipUnitImpl+20` capability argument. No
local post-constructor `CallFsm` read of `+720` was found in the staged media
module; downstream call behavior instead reads `CallFsm+824` for the
`VipUnitImpl*`, `CallFsm+832` for config, and `CallFsm+840` for the independent
CAPABILITIES/media-gate word.

```text
COPY_720_TO_840_FOUND=false
CALLFSM_720_USE=constructor stores arg4 from VipUnitImpl+20; no local post-constructor CallFsm read/copy into +840 found in the checked media plane
```

### T2-4. External Writers Through a `CallFsm*`

No function on the checked construction path receives a `CallFsm*` or
`unitdata_t_TAG*`-shaped argument and stores into that argument's `+840`.

The broader all-symbol scan did identify the non-CallFsm class already excluded
in the R47/R49 area:

```text
ConfigReaderSafeVedo::create_nvr_details_cfg_params_list(...)  strb ..., [x0,#840]
ConfigReaderSafeVedo::convert_param_descr(...)                 strb ..., [x8,#840]
```

Those stores are in the safe configuration/NVR description object plane. They
are not reached from the `VipUnitImpl -> CallFsm` media construction path as
stores through a `CallFsm*`, and they do not make `CallFsm+840` initialized.

```text
EXTERNAL_CALLFSM840_WRITER=NONE
```

### T2-5. Object Extent and Array Element

Both real media construction sites allocate the `CallFsm` storage with
`operator new(0x390)`. Offset `840` is `0x348`, so bytes `840..843` are within
the allocated object extent:

```text
0x348 + 4 <= 0x390
```

The checked `CallFsm` references address `+840` as a fixed scalar displacement:
word loads for CAPABILITIES serialization and byte loads for local media gates.
No `CallFsm` writer uses `base + index*stride` to target `840..843`, and no
inline array/buffer ownership for this offset is proven. Nearby fields are
fixed-offset scalars/pointers: `+824` unitdata pointer, `+832` cfg pointer,
`+844` refcount, `+848` initialized word, and `+856` onward queue/subobject
storage.

```text
CALLFSM_840_IN_OBJECT_SCALAR=true
CALLFSM_840_ARRAY_ELEMENT=NONE
```

### Turn 2 Decision

Turn 2 closes the specific alias/indirect holes left by Turn 1. No bare-`this`
helper writer, no RMW, no `720 -> 840` copy, and no external `CallFsm*` writer
was proven. `CallFsm+840` remains an in-object scalar with no static
writer/source before the CAPABILITIES read on the checked inbound/outgoing
construction paths.

Residual unknown boundary: opaque whole-program sources outside the staged
three-module static corpus, allocator residue/reuse history, or a dynamically
resolved writer not present in the checked construction-path call graph could
still initialize the word. Static evidence in this corpus still supports CASE C.

```text
=== P116 R51 TURN2 ===
STATUS=accepted
BARE_THIS_HELPER_WRITER=NONE
RMW_ON_840_FOUND=false
COPY_720_TO_840_FOUND=false
CALLFSM_720_USE=constructor stores arg4 from VipUnitImpl+20; no local post-constructor CallFsm read/copy into +840 found in checked media plane
EXTERNAL_CALLFSM840_WRITER=NONE
CALLFSM_840_IN_OBJECT_SCALAR=true
CALLFSM_840_ARRAY_ELEMENT=NONE
CALLFSM_840_POSSIBLY_UNINITIALIZED=true
IS_CALLFSM_840_DERIVED_FROM_VIPUNIT_CAPABILITY=false
CAPABILITY_WORD_PRIMARY_NATIVE_PROVEN=false
CASE=CASE C
RESIDUAL_UNKNOWN_BOUNDARY=opaque whole-program/dynamic writer outside staged static construction-path corpus or allocator reuse history
CHANGED=safety-poc/research/media/v1/P116_R51_NATIVE_CAPABILITY_DATAFLOW_CLOSURE.md
NETWORK_TX=0
DOOR_ACTIONS=0
GATE_ACTIONS=0
PRODUCTION_FILES_CHANGED=0
HOST_RELAY_COMMANDS=NONE
NEXT_ACTION=Only a future bounded watchpoint/live provenance run could identify any non-static writer/source for CallFsm+840; do not promote helper capability word to production.
=== END P116 R51 TURN2 ===
```
