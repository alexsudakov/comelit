# P72: composed RTPC client-media generation contract

## Goal

Compose the already-proven RTPC OPEN and client media-signaling rules into one
deterministic **offline** builder boundary, without performing a live Comelit
operation and without inventing the remaining RTPC target-id allocator.

This phase follows P70/P71, which statically proved the RTPC ABCD OPEN trailer:

```text
OPEN[14] = channel_map[RTPC].transport & 0xff = 1
```

P72 does not revisit that result.  It combines it with the P63/P65 capture
cross-validation of client `0x000A` / `0x001A` signaling.

## Evidence composed

### RTPC OPEN

From P70:

- 15-byte `0xABCD` OPEN envelope;
- channel tag `RTPC`;
- target/channel id at bytes `12:14`, little-endian;
- channel transport at byte `14`;
- RTPC transport value `1`;
- target id and transport are separate fields.

### RTPC target-id behavior

From P66:

- exactly two client RTPC OPEN ids in the frozen reference flow;
- ids are distinct and non-zero;
- neither id appears in earlier bounded CONTROL traffic;
- each id is later echoed by device CONTROL traffic;
- the two observed ids are sequential.

P72 preserves those relations as input validation but **does not infer an
allocator start value or allocator algorithm**.  The ids are supplied by the
caller.  Exact allocator provenance remains the next unresolved generation
boundary.

### Client `0x000A`

From P63/P65:

- body length `44`;
- prefix `0x1840`;
- action `0x000A`;
- flags `0x0011`;
- fixed RTPC-link tag at bytes `10:16`;
- first RTPC target id at bytes `16:18`, little-endian;
- validated reserved fields;
- address role B at `24:33` and role A at `34:43`;
- sequence delta from the nearest preceding same-request client CTPP frame is
  `0`.

### Client `0x001A`

From P63/P65:

- body length `60`;
- prefix `0x1840`;
- action `0x001A`;
- flags `0x0011`;
- fixed video-config tag at bytes `10:16`;
- second RTPC target id at bytes `16:18`, little-endian;
- validated reserved fields;
- reference geometry `(800, 480, 320, 240, 16)` encoded as LE16 fields;
- address role B at `40:49` and role A at `50:59`;
- sequence delta from the nearest preceding same-request client CTPP frame is
  `0x00010000`.

## Repository artifact

`entrance_rtpc_client_media_generation_contract.py` provides pure deterministic
builders for:

- one RTPC OPEN from a caller-supplied runtime target id;
- client `0x000A`;
- client `0x001A`;
- the composed pair of RTPC OPENs plus their bound client signaling bodies.

The module emits no raw body values in its report and performs no network I/O.
It refuses zero/equal ids, refuses non-sequential ids by default, validates the
9-byte address-role contract, and fails closed for geometry other than the
cross-validated reference geometry.

## Explicit non-promotion

P72 intentionally leaves the following unresolved:

```text
RTPC_TARGET_ID_ALLOCATION_CONTRACT=CALLER_SUPPLIED_NOT_PROVEN
RTPC_TARGET_ID_START_VALUE=NOT_PROVEN
LIVE_TRANSMISSION_AUTHORIZED=false
```

Therefore this phase does **not** add the P72 builder to the existing live
self-activation launcher and does not authorize a new one-shot camera session.

## Next gate

Resolve the official-client provenance of the generated 16-bit RTPC
`target/channel id` used by `viper_tunnel_channel_create` / its caller.  The
preferred path is bounded offline static analysis of the already-staged official
Android native artifacts.  The goal is to determine the allocator source,
initialization rule, increment/wrap behavior, and collision/zero handling without
running a media session.

Only after that allocator boundary is proven should the composed P72 builder be
wired into a new one-shot live candidate.

## Safety

OFFLINE_ONLY. No network I/O, no PseudoTCP session, no CTPP/RTPC transmission, no
camera/media session, no Door action, no listener stop/restart, no payload/media
capture, no Home Assistant change, and no direct change to `main`.
