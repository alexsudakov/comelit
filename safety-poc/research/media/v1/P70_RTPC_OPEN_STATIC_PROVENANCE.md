# P70: static provenance of the RTPC OPEN trailer (byte 14)

## Starting question

P69 observed trailer value `1` at byte offset 14 of every captured RTPC `0xABCD`
OPEN body (three samples in the frozen `self_activation.pcap`) and deliberately
kept `OPEN_TRAILER_SEMANTICS=NOT_PROVEN`. This phase answers, from offline static
provenance only: what generates byte 14 of the RTPC OPEN body, and under which rule?

No live experiment was run. P69 intentionally left the generation contract
`NOT_PROVEN`; P70 resolves the remaining trailer question statically, so no
additional live experiment is required for this promotion.
This is a pure offline reverse-engineering follow-up on staged proprietary
artifacts (APK-derived DEX files and native ARM64 libraries from the official
Comelit Android client) plus the frozen capture.

## Artifact SHA256 gates (host-verified 2026-09-07, P70 workspace)

Proprietary artifacts are NOT committed to this repository. The authoritative
gates, re-validated by the repository verifier when external paths are supplied:

| Artifact | SHA256 |
|---|---|
| classes7.dex | `851afb335a731c54e46ec39eb214a532c21c695eda6ce62de246b8d750e8f407` |
| classes8.dex | `05864bb668f26a7344217373f1d56fc8d38f71e92bf82f2cc9d82f20472c33ea` |
| classes9.dex | `8015830948e6317e57313026d5f00292fdc097c25418d0ccc47c66a22a34bd36` |
| libcomelitvipkit.so | `2fe212c8ee2ecce8f64c556af01e91d148b3e7a001876d159c84ac50611476c1` |
| libsafecomelit.so | `83a6fa2f8166366c73d3dc1b1a487451579b7e1121ce01d6996d6befc06e239b` |
| libvipcomelit.so | `465c841a8a8400c8e301a18b728594b295a49b5bd5a127fa6b9643f94bf884f0` |
| self_activation.pcap | `f15bb1922f55237bfaeb570bd288f7023e0196c05e878dfdaa76ad165bbc044a` |
| p2p_rtsp.pcap | `62888c21a795d3a2716423a196d9b68e80f73843f5202fcd23837312298f8ec3` |

## DEX provenance

- `classes7.dex`: `RTPC` exists in `ViperEnum$ViperChannelType` enum construction as
  name `RTPC` with legacy ordinal `10`.
- `classes8.dex`: `RTPC` exists in `comelitgroup/comelitvipkit/type/viper/Channel`
  with enum ordinal `11` and custom integer `10` stored in `Channel.id`.
  `Channel.getId()` is called only from `Channel$Companion.fromInt(I)`, used when
  parsing incoming events. `Channel.id=10` is therefore an internal enum lookup
  code, not a wire byte.
- The official Java/Kotlin boundary is
  `ComelitService.openChannel(ViperChannelType, int)` →
  `VipEngine.openChannel(runtime_int, ViperChannelType.ordinal())`; for RTPC this
  is `VipEngine.openChannel(runtime_int, 10)`. `VipEngine.openChannel(II)I` is
  declared native in `classes8.dex` with no DEX code body.

## JNI boundary

`libcomelitvipkit.so` exports the direct JNI symbol
`Java_com_comelitgroup_comelitvipkit_VipEngine_openChannel` (no
`JNI_OnLoad`/`RegisterNatives` dynamic registration found). JNI instance-method
ABI (AAPCS64): `x0=JNIEnv*`, `x1=thiz`, `w2` = first declared Java int
(`runtime_int`), `w3` = second declared Java int (channel ordinal `10` for RTPC).
The export tail-calls the PLT slot for
`ComelitEngine::sysViperOpenChannel(int, ViperChannelType)` passing runtime int in
`w1` and channel type in `w2`.

## Exact native library

All further functions are defined in `libvipcomelit.so` (ARM64, ELF64, stripped;
dynamic symbols). `libcomelitvipkit.so` imports
`ComelitEngine::sysViperOpenChannel` from it; `libsafecomelit.so` also references
the same symbol.

## Bounded native instruction chain (all calls via PLT, resolved by JUMP_SLOT)

1. `ComelitEngine::sysViperOpenChannel(int, ViperChannelType)` @ `0x88c4c` —
   uses the runtime int for system/owner selection; passes the channel type to
   `System::viperOpenChannel` (PLT `0xee4b0`, GOT `0xf7208`). The runtime int does
   not flow into OPEN body generation on the proven path.
2. `System::viperOpenChannel(ViperChannelType)` @ `0x9590c` — loads the
   `ViperTunnel*` from `[this,#0x50]`, sets `x2..x5 = 0` (null callback/userdata/
   status/`ViperChOpenParam`), `w6 = 1`, tail-calls `ViperTunnel::openChannel`
   (PLT `0xed960`, GOT `0xf6c60`).
3. `ViperTunnel::openChannel(ViperChannelType, cb, userdata, status,
   ViperChOpenParam*, bool)` @ `0x99fe8` (1128 bytes) — saves the requested
   channel type (`w21`) and looks the channel up in the native channel map; stores
   the key at map node `+0x1c`; loads the node tag into `w24` (`+0x20`) and the
   node transport into `w2` (`+0x24`, instruction `0x9a1f4: ldr w2,[x27,#0x24]`);
   calls `viper_tunnel_channel_create` (PLT `0xeea90`, GOT `0xf74f8`).
4. `viper_tunnel_channel_create` @ `0xa5648` (324 bytes) — `calloc(1,0x40)` channel
   struct; stores generated 16-bit target/channel id at `+0x24`, tag at `+0x20`,
   transport at `+0x38` (instructions `0xa572c`/`0xa5730`/`0xa5738`).
5. `viper_tunnel_channel_open` @ `0xa578c` (240 bytes) — serializes the 15-byte
   OPEN body (see below). `viper_tunnel_open_channel` @ `0xa587c` (180 bytes) is a
   shorter wrapper with the same serializer pattern.

## Native map entry for RTPC

`.init_array` relocation `0xf54c8` targets constructor `0x9ef38`. The constructor
builds a 13-record array of 12-byte `{key, tag, transport}` records and calls map
initializer `0x97694`. For RTPC the record is built at `0x9f1e0..0x9f210`:

- key `10` (`mov w8,#0xa`, stored at `sp+0x84`),
- tag `RTPC` built from immediates `0x5452`/`0x4350` (`mov x8,#0x5452`;
  `movk x8,#0x4350,lsl #16`),
- transport `1` placed in the next 32-bit field (`movk x8,#1,lsl #32`).

Map initializer `0x97694` stores per node: key at `+0x1c`, tag at `+0x20`,
transport at `+0x24` (instructions `0x9773c`, `0x97744`). Map object base
`0xfc9c8`; `0xfc9d0` is its `+8` head field used by `ViperTunnel::openChannel`.

## Serializer provenance

`viper_tunnel_channel_open` @ `0xa578c` allocates `calloc(1, 0xf)` (15 bytes on
the no-extra-param path) and writes:

| OPEN offset | bytes | source instruction |
|---|---|---|
| 0:4 | `0x0001ABCD` LE (magic `0xABCD` + opcode 1) | `0xa57e0/0xa57ec` mov+movk; `0xa57f8: str w8,[x0]` |
| 4:6 | `7` (declared length) | `0xa57f0: strh w9,[x0,#4]` |
| 6:8 | `00 00` (calloc zero) | no write on this path |
| 8:12 | channel tag | `0xa5808: str w8,[x0,#8]` |
| 12:14 | generated target/channel id (LE) | `0xa5804: strh w10,[x0,#0xc]` |
| 14 | channel transport | `0xa580c: strb w9,[x0,#0xe]` |

## Exact offset-14 write

Byte 14 is written by a single instruction:

```
0xa580c: strb w9, [x0, #0xe]
```

where `w9` was loaded at `0xa57f4: ldr w9,[x23,#0x38]` — the `transport` field of
the channel struct created by `viper_tunnel_channel_create`, whose value came from
the map node transport field (`+0x24`) selected by the requested channel type key.
The mirror serializer `viper_tunnel_open_channel` performs the same write at
`0xa58f8: strb w10,[x0,#0xe]`.

## Generation contract

```
OPEN[14] = channel_map[ViperChannelType].transport & 0xff
```

For `ViperChannelType.RTPC` (key `10`) the statically initialized map entry is
`{key=10, tag="RTPC", transport=1}`, therefore `OPEN[14] = 1`.

Scope limit: this promotes ONLY the RTPC entry. No other channel type's transport
value is asserted here, and `OPEN[14] = 1` is NOT promoted to a universal value
for every ABCD OPEN channel.

Status vocabulary introduced by this phase (superseding the P69 `NOT_PROVEN`
state for RTPC only; P69 artifacts remain untouched as the historical state):

- `RTPC_OPEN_TRAILER_SEMANTICS=CHANNEL_TRANSPORT`
- `RTPC_OPEN_TRAILER_GENERATION_RULE=channel_map[RTPC].transport & 0xff`
- `RTPC_OPEN_TRAILER_VALUE=1`
- `RTPC_OPEN_TRAILER_CONTRACT=PROVEN`
- `LIVE_BODY_GENERATION_CONTRACT=PROVEN_STATIC`
- `LIVE_EXPERIMENT_REQUIRED=NO`

The safe semantic name is `channel transport`: native code exposes the concept
through the channel transport field and the `viper_channel_get_transport`
routine returning `[channel,#0x38]`. Human-readable protocol interpretation
beyond this (e.g. UDP/TCP/PseudoTCP/reliable/unreliable labels) remains
NOT_PROVEN and is deliberately not inferred.

## Rejected hypotheses

- `Channel.id=10` is the wire trailer — REJECTED. It is an enum lookup id used in
  event parsing (`Channel$Companion.fromInt`).
- The Java `runtime_int` passed to `VipEngine.openChannel()` becomes the OPEN
  trailer or target — REJECTED for the proven construction path. It selects the
  system/owner and does not flow into OPEN body generation.
- `ViperChOpenParam` supplies byte 14 — REJECTED on the Java path. `x5` is NULL
  there; the optional parameter only carries extra payload copied after OPEN
  offset `0x14` when present.
- RTPC trailer `1` is merely a literal capture replay value — REJECTED. The
  constructor/map/create/serializer instruction chain independently proves the
  generation rule; the capture observations (three RTPC OPENs with trailer `1` in
  `self_activation.pcap`) corroborate but do not constitute the proof.

## Remaining unknown semantics

- Human-readable protocol meaning of the `transport` field for RTPC and of other
  channels' transport values beyond the native field name.
- Transport values of non-RTPC channel map keys (individually observable in
  captures, none statically promoted here).
- Exact byte-level serializer behavior on paths WITH a non-null
  `ViperChOpenParam` (payload extension, not byte 14).

## Repository promotion (P71)

`entrance_rtpc_open_trailer_static_contract.py` is the deterministic offline
verifier of this contract. It embeds only the minimal proven facts above
(channel-map entry for RTPC, serializer model, scope limits). It accepts the
proprietary artifacts as OPTIONAL external paths for re-validation: SHA256 gates,
an AArch64 byte-pattern scan for the decisive serializer instructions
(`ldr w9,[x23,#0x38]` = `e9 3a 40 b9`; `strb w9,[x0,#0xe]` = `09 38 00 39`;
mirror `strb w10,[x0,#0xe]` = `0a 38 00 39`), and a P69-pipeline consistency check
of the frozen capture. No artifact is committed; absent artifacts are reported as
NOT_PROVIDED, never guessed.

## Safety statement

OFFLINE_ONLY. No network I/O, no Comelit signaling, no camera/media session, no
Door action, no packet injection, no capture replay, no listener stop/restart, no
Home Assistant or production change, no git main change outside this feature
branch. Raw authentication material and raw/media payloads are never emitted.
