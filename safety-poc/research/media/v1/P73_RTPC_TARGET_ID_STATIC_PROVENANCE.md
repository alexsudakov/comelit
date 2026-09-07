# P73: static provenance of the RTPC target/channel id

## Scope and artifact gate

This phase answers the P72 allocator gap for the 16-bit identifier serialized at
RTPC ABCD OPEN bytes `12:14`.  The work was offline only: no network I/O, no
Comelit session, no packet replay, no camera/media action, and no Door action.

The native artifact re-gated before analysis:

| Artifact | SHA256 |
|---|---|
| `/home/hermes/comelit-p70-codex/input/native/libvipcomelit.so` | `465c841a8a8400c8e301a18b728594b295a49b5bd5a127fa6b9643f94bf884f0` |

The file is an ARM64 ELF64 shared object, stripped except for dynamic symbols.
All addresses below are virtual addresses in that ELF.

## Proven native path

P70 already proved that `ViperTunnel::openChannel(...)` selects a channel-map
entry and that `viper_tunnel_channel_open` serializes channel struct field
`+0x24` into OPEN bytes `12:14`.  P73 extends the proof backward to the allocator.

The bounded native path is:

1. `ViperTunnel::open` stores the result of `viper_tunnel_new` into
   `ViperTunnel+8` at `0x98960: str x0, [x19,#8]`.
2. `viper_tunnel_new` @ `0xa59c8` allocates zeroed tunnel state with
   `calloc(1,0x32158)` (`0xa59e0..0xa59f4`), calls `rand@LIBC` through PLT
   `0xec140` at `0xa5adc`, masks the result at `0xa5ae0: and w8,w0,#0x7fff`,
   and stores the low counter at `0xa5ae8: strh w8,[x19,#0x128]`.
3. `ViperTunnel::openChannel(...)` @ `0x99fe8` looks up the native channel map
   by requested channel key.  The map node has key at `+0x1c`, tag at `+0x20`,
   and transport at `+0x24`.  It loads transport at `0x9a1f4: ldr w2,[x27,#0x24]`,
   loads tunnel state at `0x9a1f8: ldr x0,[x19,#8]`, places tag in `w1`, and
   calls `viper_tunnel_channel_create` at `0x9a200`.
4. `viper_tunnel_channel_create` @ `0xa5648` generates the id, links the channel,
   and stores the selected id at `0xa572c: strh w20,[x0,#0x24]`.
5. `ViperTunnel::openChannel(...)` calls the generic opener at `0x9a2d0`; on the
   proven RTPC path this reaches `viper_tunnel_channel_open`.
6. `viper_tunnel_channel_open` @ `0xa578c` loads the channel id at
   `0xa57e8: ldrh w10,[x23,#0x24]` and writes it at
   `0xa5804: strh w10,[x0,#0xc]`, which is OPEN bytes `12:14`.

## Allocator instructions

`viper_tunnel_channel_create` receives `x0=tunnel_state`, `w1=tag`,
`w2=transport`.

Important instructions:

| Address | Instruction | Role |
|---|---|---|
| `0xa565c` | `cmp w2,#2`; `b.ne 0xa5674` | rejects transport `2`, error `0x26` |
| `0xa5674` | `ldrsh w19,[x0,#0x120]` | reads signed active-channel count |
| `0xa5678` | `tbnz w19,#0x1f,0xa56fc` | refuses negative count, error `0x18` |
| `0xa567c` | `ldrh w8,[x0]` | reads high halfword near tunnel-state start |
| `0xa5680` | `ldrh w11,[x0,#0x128]` | reads current low 15-bit counter |
| `0xa5688` | `mov w12,#0x7fff` | collision search budget |
| `0xa568c` | `lsl w10,w8,#0xf` | moves high component into bit 15 position |
| `0xa5694` | `add w13,w11,#1` | computes next low candidate |
| `0xa5698` | `orr w20,w11,w10` | candidate = high component OR current low |
| `0xa569c` | `and w11,w13,#0x7fff` | wraps next low to 15 bits |
| `0xa56a0..0xa56b4` | list walk via `[x0,#0x110]`; `ldrh w14,[node,#0x24]`; `cmp w14,w20,uxth` | collision check against existing channel ids |
| `0xa56b8..0xa56c0` | increment collision count; compare with `0x7fff` | on collision, try next low until budget exhausted |
| `0xa56c8` | `strh w11,[x0,#0x128]`; return NULL | failure stores advanced low and returns no channel |
| `0xa56d4` | `strh w11,[x0,#0x128]` | success stores next low before allocation |
| `0xa56d8..0xa56e8` | defensive re-walk comparing `[node,#0x24]` | duplicate after first pass raises error `0x11` |
| `0xa572c` | `strh w20,[channel,#0x24]` | selected id stored in the channel field serialized later |
| `0xa5730` | `str w23,[channel,#0x20]` | tag stored |
| `0xa5738` | `str w21,[channel,#0x38]` | transport stored |
| `0xa577c..0xa5784` | increment and store `[tunnel,#0x120]` | active-channel count is count, not id entropy |

Thus the promoted allocator rule is:

```
candidate_id = ((high_halfword << 15) | low15_counter) & 0xffff
stored_low15 = (low15_counter + 1) & 0x7fff
if candidate_id collides with any channel_struct[+0x24] in tunnel_state[+0x110]:
    repeat with stored_low15 as the next candidate
after 0x7fff collisions:
    store the advanced low15 counter and fail
```

The selected value is the current candidate.  The stored counter is the next
candidate to try, not the selected value.

## Constructor and MGMT channel

`viper_tunnel_new` initializes the allocator state:

- `0xa59f4` calls `calloc`, so fields not written by the constructor, including
  the high halfword at `+0`, start zero on this proven construction path.
- `0xa5adc` calls PLT `0xec140`; relocation `0xf6050` resolves that PLT slot to
  `rand@LIBC`.
- `0xa5ae0` masks the return value with `0x7fff`.
- `0xa5ae8` stores the seed into `tunnel_state+0x128`.

The constructor then builds an internal `MGMT` channel:

- `0xa5b18..0xa5b30` allocates a channel, stores tag `"MGMT"` at channel `+0x20`,
  and stores the tunnel backref at `+0x30`.
- It does not write channel `+0x24`; because the channel allocation is zeroed,
  the internal MGMT channel id remains `0`.
- `0xa5b78..0xa5b98` increments the active-channel count and marks channel state,
  but does not change the low counter at `+0x128`.

Implication: the first user-visible RTPC id is seeded by `rand() & 0x7fff`; the
internal MGMT channel does not consume a low-counter candidate.  However, because
MGMT id `0` is in the same channel list, a user channel candidate `0` collides
and is skipped on the normal constructor path.  In a bare synthetic state with no
id-0 channel, the generic allocator can allocate id `0`; on the proven
`viper_tunnel_new` path, user-visible zero is skipped by collision avoidance.

## RTPC map and branch scope

The native channel-map constructor @ `0x9ef38` creates the RTPC entry at
`0x9f1e0..0x9f210`:

- key `10`,
- tag `"RTPC"`,
- transport `1`.

`ViperTunnel::openChannel(...)` uses the same map lookup and same
`viper_tunnel_channel_create` call for RTPC as for other channel keys.  No
RTPC-specific allocator branch was found in this path.  The allocator is generic;
RTPC is distinguished by map entry tag/transport, not by a dedicated id routine.

## Serializer linkage

`viper_tunnel_channel_open` serializes a 15-byte ABCD OPEN body:

| OPEN offset | Source |
|---|---|
| `0:4` | `0xa57e0/0xa57ec/0xa57f8`: `0x0001abcd` |
| `4:6` | `0xa57f0`: length `7` |
| `8:12` | `0xa57fc/0xa5808`: channel tag from `channel+0x20` |
| `12:14` | `0xa57e8/0xa5804`: channel id from `channel+0x24` |
| `14` | `0xa57f4/0xa580c`: channel transport from `channel+0x38` |

The generated id in `viper_tunnel_channel_create` is therefore the id serialized
into RTPC OPEN bytes `12:14`.

## Answers to allocator questions

1. **Which state constructs the id: PROVEN.**  Tunnel state halfword `+0` and
   halfword `+0x128` construct the candidate in `viper_tunnel_channel_create`.
2. **Roles of `+0x128`, `+0`, mask, shift: PROVEN.**  `+0x128` is the current
   low 15-bit counter; `+0` supplies the high component; `lsl #15` places it into
   bit 15; `& 0x7fff` wraps the next low counter.
3. **Structure `high_component | low_15_bit_counter`: PROVEN.**  The exact
   instruction pair is `0xa568c: lsl w10,w8,#0xf` and
   `0xa5698: orr w20,w11,w10`, with 16-bit storage/comparison afterward.
4. **Low progression: PROVEN for rule, runtime-dependent for seed.**  Initial
   low source is `rand@LIBC() & 0x7fff` in `viper_tunnel_new`; each attempt uses
   the current low, stores `(low+1)&0x7fff` as next; wrap to zero is explicit.
   Generic zero is possible if no id-0 channel is in use; normal constructor
   state has an MGMT id-0 channel that causes zero to be skipped.
5. **Collision avoidance: PROVEN.**  The list at tunnel `+0x110` is walked and
   each channel `+0x24` halfword is compared with the candidate.  On collision it
   tries the next low.  After `0x7fff` collisions it stores the advanced counter
   and returns NULL; caller failure returns `-1`.
6. **Write to serialized field: PROVEN.**  `0xa572c` writes channel `+0x24`;
   `0xa5804` writes that field into OPEN `12:14`.
7. **Complete bounded flow: PROVEN.**  `ViperTunnel::openChannel` -> map lookup
   -> `viper_tunnel_channel_create` -> channel `+0x24` -> generic open serializer
   -> OPEN `12:14`.
8. **RTPC shared vs dedicated allocator: PROVEN shared.**  RTPC uses key `10`,
   tag `"RTPC"`, transport `1`, and the generic allocator.  No dedicated RTPC
   id branch was proven or needed.
9. **Capture sequential ids explained without constants: PROVEN.**  Once seeded,
   two successful non-colliding RTPC allocations naturally produce consecutive
   ids because the stored low counter is incremented by one.  The observed frozen
   sequences are corroboration only; their numeric values are not promoted.
10. **Remaining unknowns: NOT_PROVEN.**  Global predictability of `rand@LIBC`,
    process-start seeding details, persistence across tunnel/session recreation,
    and whether any external path mutates the high halfword after construction
    remain outside the bounded proof.  Therefore `START_VALUE` is
    `RUNTIME_STATE_DEPENDENT`, not a constant.

## Repository verifier

`entrance_rtpc_target_id_static_contract.py` is a deterministic offline model of
the proven allocator.  By default it uses synthetic state and emits status
markers.  When supplied `--libvipcomelit-so`, it SHA-gates the external
proprietary file and scans for the decisive instruction encodings only; it never
commits or emits proprietary bytes.

Key markers:

- `RTPC_TARGET_ID_ALLOCATION_CONTRACT=PROVEN_STATIC`
- `RTPC_TARGET_ID_GENERATION_RULE=((high_halfword<<15)|low15_counter)&0xffff; then low15=(low15+1)&0x7fff; skip in-use ids`
- `RTPC_TARGET_ID_COLLISION_AVOIDANCE=PROVEN_STATIC`
- `RTPC_TARGET_ID_OPEN_OFFSET=12:14`
- `RTPC_TARGET_ID_START_VALUE=RUNTIME_STATE_DEPENDENT`
- `CAPTURE_SEQUENTIAL_IDS_EXPLAINED=true`
- `LIVE_TRANSMISSION_AUTHORIZED=false`

## Safety statement

OFFLINE_ONLY.  No network I/O, no DNS, no P2P/ICE/STUN/TURN, no PseudoTCP or RTPC
sending, no camera session, no Door action, no packet replay or injection, no
credential/token inspection or emission, no Home Assistant or production change,
and no raw payload dump.  The proprietary library is an external analysis input
only and is not committed.
