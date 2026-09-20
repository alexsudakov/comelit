# P116 R49 Capability Provenance And Call Adoption Corrective

## Status

R49 does not pass the production corrective gate.

The official app DEX/bytecode path proves the local VIP unit capability formula and the Java to native handoff into `createVipUnit`. Native static analysis also proves native role `0` maps to CAPABILITIES call type `0x49`. However, the required primary provenance from that handed-off capability value to the runtime word read at `CallFsm+840` is still not proven. The staged native libraries read `CallFsm+840` before any proven CallFsm-field write to bytes `840..843`.

No production call-adoption code was changed.

## DEX Capability Formula

Primary bytecode evidence was recovered from `classes7.dex` for `com/comelit/bigapp/engine/managers/VipUnitManager.createFromSettings`.

`VipUnitManager.<init>` initializes:

```text
vipUnitRole = UnitRole.INTUNIT.ordinal()
vipUnitCapab = AUDIO_SRC | AUDIO_DST | VIDEO_DST
```

`UnitRole.<clinit>` in `classes8.dex` proves enum order:

```text
INTUNIT = 0
PORTER = 1
ACTUATOR = 2
```

`UnitCapability` values are:

```text
AUDIO_DST=1
AUDIO_SRC=2
VIDEO_DST=4
VIDEO_SRC=8
OPENDOOR=16
MSTREAM=32
NONE=0
```

`VipUnitManager.createFromSettings` conditionally executes:

```text
if SettingsManager.getSettingsValue(resolution_setup__enable, DB):
    vipUnitCapab |= MSTREAM
```

It then passes `vipUnitCapab` and `vipUnitRole` directly to `VipEngine.createVipUnit`.

Formula:

```text
capability_word = AUDIO_SRC | AUDIO_DST | VIDEO_DST | (MSTREAM if resolution_setup__enable else 0)
                = 0x07 | (0x20 if resolution_setup__enable else 0)
```

For a multistream-enabled official client, the word is `0x27`.

## Role Decision

The official VIP client unit creation path does not use `com.comelitgroup.comelitcorekit.type.Role.PORTER` directly. It uses `com.comelitgroup.comelitvipkit.type.vip.UnitRole.INTUNIT.ordinal()`, and that ordinal is `0`.

The JNI bridge for `VipEngine.createVipUnit` preserves the Java capability argument but calls `ComelitEngine::sysCreateVipUnit` with native role forced to `0`. Native role mapping then gives:

```text
native role 0 -> call_type 0x49
native role 2 -> call_type 0x47
other         -> call_type 0x3f
```

The helper-equivalent local role is therefore native `0`, with CAPABILITIES call type `0x49`.

## Native Handoff

The native bridge stores Java arguments as:

```text
sysId        -> sysCreateVipUnit arg1
vipAddress   -> sysCreateVipUnit arg2
subAddress   -> sysCreateVipUnit arg3
native role  -> 0
capabilities -> sysCreateVipUnit arg5
flags        -> sysCreateVipUnit arg6
```

`System::createVipUnit` carries the derived `call_type` and the capability argument into `VipUnitImpl::VipUnitImpl`. The constructor signature narrows the capability argument to its unsigned-byte parameter; this is sufficient for the proven bits `0x07` and `0x27`.

What is not proven: that this constructor argument, or any copied derivative of it, is the 32-bit word later read from `CallFsm+840`.

## CallFsm+840 Static Result

Capstone analysis over `.text` in the staged native libraries found:

```text
libvipcomelit.so:
  CallFsm+840 exact reads: 23
  proven CallFsm+840 writes: 0
  false-positive exact writes: stack-frame stores only
  covering store: IceSession constructor, not CallFsm

libsafecomelit.so:
  #840 exact displacement reads: 23
  CallFsm-owned +840 reads after symbol ownership: 21
  non-CallFsm #840 reads excluded from the CallFsm bit map: 2
  proven CallFsm+840 writes: 0
  false-positive exact writes: ConfigReader/IceClient stack or non-CallFsm object stores
  covering store: IceSession constructor, not CallFsm

libcomelitvipkit.so:
  no CallFsm symbols and no relevant CallFsm+840 writer source
```

The important read sites remain:

```text
initNewConnectionStart: ldr w3, [CallFsm+840] -> csp_send_capab_report
initBeginOutgoingCall:  ldr w3, [CallFsm+840] -> csp_send_capab_report
media gates:            ldrb from [CallFsm+840], including bit2 video gate
```

The inbound path constructs `CallFsm` and then calls `initNewConnectionStart`; no static writer to `CallFsm[840..843]` was proven between those points.

## CallFsm+840 Bit Map

This table enumerates every CallFsm-owned read of byte or word `CallFsm+840` in the staged libraries. Two additional `#840` reads in `libsafecomelit.so` resolve to `ConfigReaderSafeVedo` symbols, not `CallFsm`, and are excluded from the CallFsm bit map.

`FORWARDED_FULL_WORD` means the word is passed to `csp_send_capab_report`; the peer receives the whole value, but local code does not inspect individual bits at that site.

| Library | Symbol + relative offset | Width | Consumed bits | Classification |
| --- | --- | --- | --- | --- |
| libvipcomelit | `initBeginOutgoingCall+0x1d0` | word32 | `FORWARDED_FULL_WORD` | native CAPABILITIES serializer |
| libvipcomelit | `initNewConnectionStart+0x188` | word32 | `FORWARDED_FULL_WORD` | native CAPABILITIES serializer |
| libvipcomelit | `go_connected+0xcc` | word32 | `{0,2}` | structural local gates |
| libvipcomelit | `st_in_alerting+0x4ec` | byte | `{0}` | structural local gate |
| libvipcomelit | `st_in_alerting+0x680` | byte | `{0}` | structural local gate |
| libvipcomelit | `st_in_alerting+0x7b8` | byte | `{3}` | structural local gate |
| libvipcomelit | `start_videorx+0x28` | byte | `{2}` | structural video-RX gate |
| libvipcomelit | `checkCapabAndStartAudioRx+0x34` | byte | `{0}` | structural audio-RX gate |
| libvipcomelit | `handle_mediareq+0x168` | byte | `{3}` | structural media-request/video-TX gate |
| libvipcomelit | `handle_mediareq+0x1e8` | byte | `{3}` | structural media-request/video-TX gate |
| libvipcomelit | `handle_mediareq+0x290` | byte | `{3}` | structural media-request/video-TX gate |
| libvipcomelit | `stop_videotx+0xc` | byte | `{3}` | structural video-TX gate |
| libvipcomelit | `stop_videorx+0x20` | byte | `{2}` | structural video-RX gate |
| libvipcomelit | `st_connected+0x658` | byte | `{3}` | structural local gate |
| libvipcomelit | `st_out_initiated+0x228` | byte | `{3}` | structural local gate |
| libvipcomelit | `st_out_initiated+0x3dc` | byte | `{0}` | structural local gate |
| libvipcomelit | `st_out_initiated+0x4d0` | byte | `{3}` | structural local gate |
| libvipcomelit | `st_out_alerting+0x3f4` | byte | `{0}` | structural local gate |
| libvipcomelit | `st_out_alerting+0x484` | byte | `{3}` | structural local gate |
| libvipcomelit | `st_out_alerting+0x5a0` | word32 | `FORWARDED_FULL_WORD` | native CAPABILITIES serializer |
| libvipcomelit | `st_out_alerting+0x620` | byte | `{3}` | structural local gate |
| libvipcomelit | `start_videotx(tunnel)+0x0` | byte | `{3}` | structural video-TX gate |
| libvipcomelit | `start_videotx(address)+0x0` | byte | `{3}` | structural video-TX gate |
| libsafecomelit | `initBeginOutgoingCall+0x1d0` | word32 | `FORWARDED_FULL_WORD` | native CAPABILITIES serializer |
| libsafecomelit | `initNewConnectionStart+0x188` | word32 | `FORWARDED_FULL_WORD` | native CAPABILITIES serializer |
| libsafecomelit | `go_connected+0xcc` | word32 | `{0,2}` | structural local gates |
| libsafecomelit | `st_in_alerting+0x4ec` | byte | `{0}` | structural local gate |
| libsafecomelit | `st_in_alerting+0x728` | byte | `{0}` | structural local gate |
| libsafecomelit | `st_in_alerting+0x860` | byte | `{3}` | structural local gate |
| libsafecomelit | `start_videorx+0x28` | byte | `{2}` | structural video-RX gate |
| libsafecomelit | `checkCapabAndStartAudioRx+0x34` | byte | `{0}` | structural audio-RX gate |
| libsafecomelit | `handle_mediareq+0x178` | byte | `{3}` | structural media-request/video-TX gate |
| libsafecomelit | `handle_mediareq+0x1f4` | byte | `{3}` | structural media-request/video-TX gate |
| libsafecomelit | `stop_videotx+0xc` | byte | `{3}` | structural video-TX gate |
| libsafecomelit | `stop_videorx+0x20` | byte | `{2}` | structural video-RX gate |
| libsafecomelit | `st_connected+0x670` | byte | `{3}` | structural local gate |
| libsafecomelit | `st_out_initiated+0x228` | byte | `{3}` | structural local gate |
| libsafecomelit | `st_out_initiated+0x3dc` | byte | `{0}` | structural local gate |
| libsafecomelit | `st_out_initiated+0x4d0` | byte | `{3}` | structural local gate |
| libsafecomelit | `st_out_alerting+0x3f4` | byte | `{0}` | structural local gate |
| libsafecomelit | `st_out_alerting+0x484` | byte | `{3}` | structural local gate |
| libsafecomelit | `st_out_alerting+0x5a0` | word32 | `FORWARDED_FULL_WORD` | native CAPABILITIES serializer |
| libsafecomelit | `st_out_alerting+0x620` | byte | `{3}` | structural local gate |
| libsafecomelit | `start_videotx(address)+0x0` | byte | `{3}` | structural video-TX gate |

No site is logging-only. Every CallFsm-owned bit-test site is structural control flow.

## Consumed Bit Semantics

The local native code consumes only bits `{0,2,3}`:

| Bit | UnitCapability value | Static semantic support |
| --- | --- | --- |
| `0` | `AUDIO_DST` (`0x01`) | Used by `checkCapabAndStartAudioRx` and alerting/connected gates before local audio receive startup. |
| `2` | `VIDEO_DST` (`0x04`) | Used by `start_videorx`, `stop_videorx`, and `go_connected`; this is the video-RX gate proven by earlier media work. |
| `3` | `VIDEO_SRC` (`0x08`) | Used by `start_videotx`, `stop_videotx`, and media-request/outgoing state gates; this is a video-TX/source gate. |

No local CallFsm bit-test consumes bit `1` (`AUDIO_SRC`), bit `4` (`OPENDOOR`), bit `5` (`MSTREAM`), or higher bits in the staged static evidence.

## Official Mask Versus Consumed Bits

The official Java formula is:

```text
AUDIO_DST | AUDIO_SRC | VIDEO_DST | (MSTREAM if resolution_setup__enable else 0)
= {bit0, bit1, bit2} | optional {bit5}
```

Comparison:

```text
demonstrably consumed and covered by official mask: bit0 AUDIO_DST, bit2 VIDEO_DST
sent by official mask but not locally consumed: bit1 AUDIO_SRC, optional bit5 MSTREAM
locally consumed but not covered by official mask: bit3 VIDEO_SRC
```

For the inbound media path currently under correction, the known local receive gates are covered by bit0 and bit2. The native code still has structural bit3 consumers in video-TX/media-request paths, and the static evidence does not prove that those paths are irrelevant for every adopted call state.

## Peer Bit Requirements

The native serializer sends the full 32-bit `CallFsm+840` word in every local CAPABILITIES report:

```text
body = 00 03 <call_type> 00 <CallFsm+840 little-endian word>
```

Static native evidence does not prove which bits the peer requires. In particular, there is no static proof that the peer only requires bit2, or that it ignores bit1, bit3, or bit5.

```text
PEER_BIT_REQUIREMENTS_PROVEN=false
```

## Decision Gate

```text
DEX_CAPABILITY_FORMULA_PROVEN=true
DEX_CAPABILITY_WORD_FORMULA=0x07 | (0x20 if resolution_setup__enable else 0)
DEX_NATIVE_HANDOFF_PROVEN=true
NATIVE_840_FORMULA_PROVEN=false
NATIVE_840_FORMULA=UNKNOWN
CAPABILITY_WORD_PRIMARY_NATIVE_PROVEN=false
LIVE_WATCHPOINT_REQUIRED=true
```

Because `CallFsm+840` is the runtime source for the native CAPABILITIES serializer, the production corrective must remain blocked until a bounded live watchpoint proves either:

1. a writer/source that initializes `CallFsm+840` from the official capability formula, or
2. a deterministic replacement contract that is proven not to depend on undefined/reused allocation contents.

Repeatability of observed values alone is not sufficient.

## Section 12 Verdict

Deterministic replacement is not proven.

The exact blockers are:

```text
bit3 VIDEO_SRC is consumed by structural native video-TX/media-request paths but is not present in the official client mask
peer bit requirements for the full 32-bit CAPABILITIES word are not proven
CallFsm+840 still has no proven native writer/source before the serializer read
```

Therefore the production helper must not replace `CallFsm+840` with a deterministic word yet, even though the official Java mask formula itself is proven.

## Production Implementation Summary

No production implementation was made in R49.

The existing R45/R46 offline model remains the target behavior after the gate passes:

```text
CALL_INIT -> empty INVITE ACK -> local CAPABILITIES -> local ALERTING
peer CAPABILITIES -> empty peer DATA ACK -> existing R42 media OPEN
```

No changes were made to diagnostics, RTP classification, Door/listener behavior, generated C, native binaries, or Home Assistant production files.

## Observability

The requested media diagnostics expansion from 23 to 28 fields was not implemented because the corrective gate did not pass.

Required future fields remain:

```text
call_invite_ack_sent
call_capabilities_sent
call_alerting_sent
call_peer_data_ack_sent
call_adoption_reject_stage
```

## Watchpoint Requirement

A bounded official-app watchpoint is required on the phone/CT120 environment. It must be read-mostly and collect only bounded scalar values:

```text
VipUnitRole observed at sysCreateVipUnit
call_type at VipUnitImpl+18
capability argument passed to VipUnitImpl
all writes to CallFsm+840: count, writer symbol/relative address, old value, new value
csp_send_capab_report args: connection, call_type, mode/zero arg, capability word
```

Limits:

```text
OFFICIAL_APP_SELF_ACTIVATION_ATTEMPTS <= 3
PHYSICAL_CALL_ATTEMPTS = 0
no Door/Gate/opendoor/set-output/answer/manual relay/HA Door/Telegram Door
no memory patching, register writes, branch forcing, packet rewriting, or raw packet/session dumps
```

## Watchpoint Prerequisites

The owner/operator must provide a phone with the official Comelit app installed, authenticated, and able to perform self-activation/preview without a physical ring or Door/Gate action. Hermes can mechanically run the instrumentation once the phone is attached to the CT120 host and the operator starts the approved official-app self-activation flow. Instrumentation must read only registers and the specific `CallFsm+840` field, with at most three self-activation attempts and no packet/body/session dumping.

## Harness And Replay Results

No new harness or replay was executed for R49 because the corrective gate failed before implementation.

Previously existing R45/R46 offline artifacts remain relevant but do not prove the missing native field provenance.

## Build Provenance

No generated source, native build, promotion, or production binary update was performed.

## Remaining Unknowns

The unresolved item is the primary native provenance of `CallFsm+840`. Static evidence currently supports:

```text
read before proven write
no direct CallFsm writer in the staged libraries
no proven alias/indexed/helper/vtable/bulk-copy writer
```

The next action is the bounded official-app watchpoint.
