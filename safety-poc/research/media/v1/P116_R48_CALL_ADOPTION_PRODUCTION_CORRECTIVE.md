# P116 / R48 - call-adoption production corrective result

Status: **blocked before production functional changes**

This round used only local static native evidence, DEX string-table evidence, and repository files. No network,
HA deploy/restart/reload, physical call, answer/accept, Door, Gate, SIGUSR1, SIGUSR2, proprietary binary
execution, or candidate execution was performed.

```text
BASE_SHA=6968f06d78db08e4278f3a8f9f08afda1b780929
BRANCH=feat/p116-r42-attached-inbound-media-runtime
PHYSICAL_CALL_ATTEMPTS=0
NETWORK_COMELIT_ACTIONS=0
DOOR_ACTIONS=0
GATE_ACTIONS=0
```

## R47 field correction carried forward

R47/R48 correct an older field-map error:

```text
CallFsm+824 = unitdata_t_TAG* / VipUnitImpl*
CallFsm+832 = cfg_t*
local CAPABILITIES call type = [[CallFsm+824] + 18]
```

The native role-to-call-type formula remains:

```text
VipUnitRole == 0 -> 0x49
VipUnitRole == 2 -> 0x47
otherwise        -> 0x3f
```

This means `0x49` is not a standalone production constant. It is valid only when the helper's persistent
listener role is proven to be native `VipUnitRole == 0`.

## CallFsm+840 provenance

R48 extended the R47 direct-offset scan into constructor, allocation, call-site, reset, close, inbound,
and outgoing paths.

Findings:

- The constructor writes adjacent fields but not `CallFsm+840`.
- It writes `CallFsm+832..839`, `CallFsm+848`, and later `CallFsm+856`, leaving `CallFsm+840..843`
  untouched.
- `CallFsm::init()` is a null/self guard and does not initialize `+840`.
- Inbound `VipUnitImpl::handleCtpStart` allocates `0x390` bytes with `operator new`, then calls the
  `CallFsm` constructor. No memset/calloc or full-object zeroing occurs between allocation and construction.
- Outgoing `beginOutgoingCall` uses the same constructor shape after `operator new`.
- Stack-only temporary CallFsm constructions in open-door/set-output handling are also constructor calls
  over stack storage, not a proven zeroed object.
- No direct store, pair store, SIMD store, memset, memcpy, memmove, helper call, reset/go_idle/go_closed/init
  routine, or constructor-called routine in the bounded `CallFsm` analysis establishes a value for
  `CallFsm+840`.
- The field is nevertheless read as the local CAPABILITIES word by `initNewConnectionStart`,
  `initBeginOutgoingCall`, and outgoing alerting, and read bytewise by media gates including video RX/TX
  and audio RX decisions.

The unresolved boundary is therefore not the serializer. The serializer source field is known. The unresolved
boundary is the value provenance for the field read at `CallFsm+840`.

```text
HELPER_CAPABILITY_WORD_FORMULA=UNKNOWN
CAPABILITY_WORD_PRIMARY_NATIVE_PROVEN=false
```

## Helper role / call type

The native formula is proven. TURN2 also checked the staged JNI wrapper and found the official-app
`Java_com_comelitgroup_comelitvipkit_VipEngine_createVipUnit` call into `ComelitEngine::sysCreateVipUnit`
with `w4 = wzr`, which is native `VipUnitRole == 0` for that official JNI path
(`.r48-evidence/native/libcomelitvipkit.dis.txt:11278-11294`).

That does **not** close `HELPER_UNIT_ROLE`: the production helper is the repository-local
`custom_components/comelit/native/comelit-media` binary launched directly by Home Assistant, with source lineage in
the `safety-poc/research/door/v1_5_7/comelit-v4-persistent-ctpp-door.c` transform chain. It has no dynamic import of
`ComelitEngine`, `VipEngine`, `VipUnitImpl`, or `sysCreateVipUnit`, and repository-local helper sources/configs do
not carry a `VipUnitRole` field or a binding saying "this persistent listener is role 0".

Repository-local sources checked for helper role provenance:

| Source | Result | Why it does not prove `HELPER_UNIT_ROLE` |
| --- | --- | --- |
| `custom_components/comelit/runtime.py` | `UNKNOWN` | launches `custom_components/comelit/native/comelit-media` with token/env only; no role argument or native VIP unit construction |
| `custom_components/comelit/const.py` | `UNKNOWN` | door/media capability topology only; no native `VipUnitRole`, call type, or CAPABILITIES word binding |
| `custom_components/comelit/native/comelit-media` dynamic symbols | `REFUTED` | imports GLib/libnice/pseudotcp/libc helpers only; no official Comelit native symbols |
| `safety-poc/research/door/v1_5_7/comelit-v4-persistent-ctpp-door.c` | `UNKNOWN` | defines local addresses and CTPP listener states, not native `VipUnitRole` or `CallFsm+840` |
| `safety-poc/research/media/v1/entrance_p116_r45_call_adoption_core.py` | `UNKNOWN` | models `R45RuntimeFields.call_type` and `capability_word` as runtime inputs; does not derive them |
| `safety-poc/research/media/v1/entrance_p116_r44_inbound_peer_simulator.py` | `UNKNOWN` | contains lab/default bytes `00 03 49 00 27 00 00 00`; explicitly fixture-level, not helper provenance |
| `safety-poc/tests/native/p116_r45_call_adoption_host_harness.c` | `UNKNOWN` | test chooses `runtime.call_type = 0x49` and arbitrary `capability_word = 0x12345678` to test serialization |
| `safety-poc/tests/test_p116_r43b_call_adoption_serializers.py` | `UNKNOWN` | validates byte layout and non-equality of alternate runtime values; does not prove helper role |
| `safety-poc/research/media/v1/P116_R43B_NATIVE_CALL_ADOPTION_SERIALIZER_EXTRACTION.md` | `UNKNOWN` | proves native serializer field sources but warns that `0x27` is not a production constant |
| `safety-poc/research/media/v1/P116_R45_R46_OFFLINE_CALL_ADOPTION_REPLAY.md` | `UNKNOWN` | records the same runtime-field blocker and forbids inserting public/demo values |
| `docs/` and `examples/` | `UNKNOWN` | HA/user-facing capability contracts only; no native unit role mapping |

```text
HELPER_UNIT_ROLE=UNKNOWN
HELPER_CALL_TYPE=UNKNOWN
```

Because both the capability word formula and helper role are unresolved, R48's decision gate forbids
production functional changes and guessed constants.

## Third module exclusion

The staged `libcomelitvipkit.so` module is excluded as a `CallFsm+840` writer/source.

Findings:

- `libcomelitvipkit.nm.txt`: `CallFsm=0`, `VipUnitImpl=0`, `cfg_t=0`, `#840=0`.
- `libcomelitvipkit.dis.txt`: `CallFsm=0`, `VipUnitImpl=0`, `cfg_t=0`.
- No store to `[xN,#840]` was found in `libcomelitvipkit.dis.txt`.
- One literal `#840` reference exists, but it is `ldrb w8, [sp, #840]` in
  `Java_com_comelitgroup_comelitvipkit_VipEngine_createViperTunnel__ILcom_comelitgroup_comelitcorekit_model_P2PParameters_2`,
  immediately after a `memmove` and before stack cleanup. It is a stack-slot read, not a `CallFsm` object access.

```text
THIRD_MODULE_EXCLUDED=true
THIRD_MODULE_LITERAL_840_REFS=1
THIRD_MODULE_CALLFSM_840_REFS=0
THIRD_MODULE_CALLFSM_840_STORES=0
```

## Java / DEX layer semantics

The DEX string tables prove name-level presence of call-adoption vocabulary, not native-equivalent field provenance.

| DEX question | Status | Finding |
| --- | --- | --- |
| Numeric `Role` / `CallType` mapping | `NAME_LEVEL_ONLY` | strings include `Role`, `CallType`, `CallDirection`, `setRole-kuIjeqM`, `ordinal`, and `intValue`, but string tables do not contain instruction operands or enum numeric values |
| Config-derived capability set | `NAME_LEVEL_ONLY` | strings include `Capability.kt`, `_systemCapability`, `getSystemCapability`, `configCapability`, `svcCapability`, `getSvcCapability`, and `ConfigCapability(name=`, but no serialized numeric word formula is recoverable from strings alone |
| Value handed into native layer | `NAME_LEVEL_ONLY` | `libcomelitvipkit` JNI symbols include `createVipUnit`, `answerCall`, `requestVideo`, `startOutgoingCall`, etc.; bounded disassembly proves `createVipUnit` hands role `0` to `sysCreateVipUnit` on the official JNI path, but no DEX string evidence proves a `CallFsm+840` value or helper handoff |
| Native-equivalent source for `CallFsm+840` | `REFUTED` for available DEX string-table evidence | the staged DEX artifacts are string tables, not decompiled code or bytecode data-flow; they cannot prove the numeric capability word read by native `CallFsm+840` |

```text
JAVA_LAYER_CAPABILITY_SOURCE=NONE
JAVA_LAYER_ROLE_NAMES=NAME_LEVEL_ONLY
JAVA_LAYER_CAPABILITY_NAMES=NAME_LEVEL_ONLY
JAVA_LAYER_NATIVE_HANDOFF=NAME_LEVEL_ONLY
```

## Checked `CallFsm+840` path boundary

| # | Path | Observed result | Minimal next evidence |
| --- | --- | --- | --- |
| 1 | Direct store | none to `CallFsm+840`; whole-text offset scan found no CallFsm writer | full `CallFsm+840` data-flow from official `libvipcomelit.so`/`libsafecomelit.so`, or dynamic watchpoint |
| 2 | Pair/SIMD store | no pair/SIMD store covering `CallFsm[840..843]` for CallFsm; only unrelated `IceSession` `stp q0,q0,[x0,#832]` | same full data-flow/watchpoint |
| 3 | memset/calloc/zeroing | inbound/outgoing real sites use `operator new(0x390)` then constructor; no zeroing before construction | dynamic watchpoint from allocation through first `initNewConnectionStart` |
| 4 | memcpy/memmove | no CallFsm bulk copy into `+840` found; third-module `memmove` is JNI tunnel stack/object handling, not CallFsm | data-flow over all pointer aliases into constructed CallFsm |
| 5 | Alias pointer | not proven; no direct alias-derived writer found in bounded scan | alias-aware analysis or watchpoint on `CallFsm+840` |
| 6 | `this` + offset arithmetic | no explicit arithmetic-derived store to offset 840 found | alias-aware disassembly pass over all stores in CallFsm lifetime |
| 7 | Indexed store | still open: register-indexed stores exist in the CallFsm plane, but no proof they target `+840` | full data-flow for indexed stores, or watchpoint |
| 8 | Pointer passed to callee/helper | no constructor-called helper/reset/init path shown to write `+840`; open for opaque callees receiving aliased object pointers | callee argument data-flow for all CallFsm methods |
| 9 | Vtable/indirect call | no proven writer through indirect call | vtable target resolution or watchpoint |
| 10 | Placement construction | stack-only temporary CallFsm constructions are constructor calls over existing storage; no `+840` init | caller stack initialization proof if those temporaries ever matter |
| 11 | `operator new` zeroing at real site | `operator new(0x390)` is called; C++ `operator new` does not imply zeroing and no site-local zero was found | dynamic allocation memory observation at `handleCtpStart` / `beginOutgoingCall` |
| 12 | Bulk copy from another call state | none found | whole-object copy analysis across active-call containers |
| 13 | reset/go_idle/go_closed/init | no `+840` initialization; `init()` is guard-like, close/ref paths target adjacent/refcount fields | targeted disassembly of any not-yet-staged lifecycle helpers, or watchpoint |
| 14 | inbound accept path | `handleCtpStart` allocates and constructs CallFsm, then `initNewConnectionStart` reads `+840`; no writer found before read | dynamic watchpoint on inbound official app call adoption |
| 15 | outgoing init path | `beginOutgoingCall` has same allocation/constructor shape; `initBeginOutgoingCall` reads `+840` | dynamic watchpoint on official outgoing setup |
| 16 | third JNI/native module | excluded for CallFsm: no symbols, no CallFsm stores, one unrelated stack `#840` read | none for third-module exclusion; only DEX/code provenance remains |
| 17 | Java/DEX capability handoff | string tables only give names; no bytecode/data-flow proof of word | decompiled/bytecode listing for `Capability.kt`, `VipEngine.createVipUnit`, and capability setters/getters |

The minimal next evidence that can close the production gap is one of:

1. A sanitized native data-flow artifact for `CallFsm+840` covering all alias/indexed/indirect stores in
   `libvipcomelit.so` and `libsafecomelit.so`.
2. A precisely bounded dynamic watchpoint on the official app process: allocate `CallFsm`, record every write to
   `this+840` until the first `initNewConnectionStart`/`initBeginOutgoingCall` capability report read, and record
   the `VipUnitRole` used at `sysCreateVipUnit`.
3. Decompiled/bytecode evidence for the staged DEX classes around `Capability.kt`, `Role`, `CallType`,
   `VipEngine.createVipUnit`, and any native setters that proves both the numeric capability word formula and the
   native role passed to the same unit.

## Peer DATA ACK ordering

R45/R46 remain the current offline behavioral evidence:

```text
CURRENT_R36_PEER_DATA_ACK_MISSING=true
peer body-bearing DATA -> call_ack = peer_sequence + 1
peer body-bearing DATA -> exactly one empty ACK flags=0x80
empty peer DATA ACK does not advance local TX sequence
peer CAPABILITIES ACK must precede the R36 media OPEN trigger
MEDIA_OPEN must use the updated call_ack
```

This corrective is still required, but cannot be safely promoted until the local CAPABILITIES runtime fields
are derived from primary/native-equivalent provenance.

## Implementation delta

No production functional code was changed. The only repository changes in this blocked round are documentation:

- add this R48 canonical result;
- add a superseding note to the R37 document correcting the `CallFsm+824/+832` field map.

## Offline harness results

No R48 production code or harness changes were made, so no full test cycle was run. Existing R45/R46 evidence
remains historical/offline support only and is not claimed as a fresh R48 result.

## Generated-source replay result

Not run. The generated-source replay is Phase B acceptance work and was not entered because the Phase A
decision gate blocked functional changes.

```text
GENERATED_SOURCE_REPLAY=NOT_RUN
GENERATED_SOURCE_SHA256=NONE
```

## Reproducible build result

Not run. Native build/promotion is Phase B acceptance work and was not entered.

```text
NATIVE_REPRODUCIBLE=NOT_RUN
NATIVE_SHA256=NONE
```

## Remaining unknowns

```text
LOCAL_CAPABILITIES_WORD_SOURCE=UNKNOWN
HELPER_CAPABILITY_WORD_FORMULA=UNKNOWN
HELPER_UNIT_ROLE=UNKNOWN
HELPER_CALL_TYPE=UNKNOWN
PRODUCTION_CORRECTIVE_READY=false
```

The next valid step is more static evidence or an already-existing sanitized provenance source that proves the
helper-equivalent capability word and helper unit role. A production corrective must not use `0x27`, a public
implementation constant, a single capture value, or "set bit2" as a substitute for that proof.
