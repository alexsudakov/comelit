# P74: allocator-backed RTPC media generation

## Goal

P74 closes the P72 caller-supplied RTPC target-id gap by composing two existing
offline contracts:

- P72 body generation for RTPC ABCD OPEN, client `0x000A`, client `0x001A`,
  sequence placement, address-role placement, and reference geometry.
- P73 native allocator provenance for the 16-bit channel id serialized into
  RTPC OPEN bytes `12:14`.

The resulting layer builds the first allocated RTPC id, first OPEN, second
allocated RTPC id, second OPEN, client `0x000A` bound to allocation 1, and
client `0x001A` bound to allocation 2.  It does not transmit anything.

## Composition

`entrance_rtpc_allocator_backed_media_generation_contract.py` imports P72 and
P73 directly.  It does not duplicate the RTPC tag, transport, geometry, or
allocator constants.

The composed flow is:

1. `allocation_1 = allocate_target_id(state)`.
2. `allocation_2 = allocate_target_id(state)`.
3. `rtpc_open_1 = build_rtpc_open(allocation_1.target_id)`.
4. `rtpc_open_2 = build_rtpc_open(allocation_2.target_id)`.
5. `client_000a = build_client_000a(..., rtpc_target_id=allocation_1.target_id)`.
6. `client_001a = build_client_001a(..., rtpc_target_id=allocation_2.target_id)`.

The runtime-rand helper applies P73's constructor rule:

```text
seed_low15 = rand_value & 0x7fff
state = new_tunnel_state(seed_low15, include_mgmt_channel=True)
```

Including the MGMT channel is important because the official constructor path
links an internal id-0 channel before user RTPC allocation.  Therefore user id
0 is skipped on that path by the same collision rule used for every channel.

## Caller-supplied ids removed

P72 remains byte-identical and still documents
`RTPC_TARGET_ID_ALLOCATION_CONTRACT=CALLER_SUPPLIED_NOT_PROVEN`.  P74 does not
rewrite that history.  Instead, P74's public composition functions accept only
allocator state or a runtime PRNG value plus the P72 media context.  They do not
accept `rtpc_target_1`, `rtpc_target_2`, or equivalent caller-supplied target-id
parameters.  The allocator result is the only source for OPEN and client-body
target-id bindings.

## Sequential relation

The frozen capture showed sequential RTPC target ids.  P73 explains why two
collision-free allocations naturally produce that observation: the native loop
stores `(low15 + 1) & 0x7fff` after each successful candidate.

That observation is not promoted into a universal P74 requirement.  If the next
candidate is already in the channel list, P73 skips it and returns the next free
candidate within the bounded search budget.  P74 treats the allocator result as
authoritative even when allocation 2 is not allocation 1 plus one.

Markers:

```text
CAPTURE_SEQUENTIAL_RELATION=OBSERVED_AND_EXPLAINED
RTPC_ALLOCATOR_REQUIRES_STRICT_SEQUENTIAL_IDS=false
```

## Collision, wrap, and exhaustion

Collision behavior is inherited from P73: candidate ids are compared against the
existing channel id list, including the constructor-created MGMT id 0 when that
state is used.  Colliding candidates advance to the next low15 value.

Wrap behavior is also inherited from P73.  After low15 `0x7fff`, the next low15
candidate is `0`.  On the official constructor path, id 0 collides with MGMT and
the next user-visible id is selected if available.

Exhaustion fails closed.  If either of the two required allocations returns
`None`, P74 raises an explicit `RuntimeError` and returns no composed result.
It never returns an object with only part of the OPEN/client binding sequence.

## Exact bindings

The authoritative bindings are:

- `allocation_1.target_id == rtpc_open_1[12:14]` as little-endian `u16`.
- `allocation_2.target_id == rtpc_open_2[12:14]` as little-endian `u16`.
- `allocation_1.target_id == client_000a[16:18]` as little-endian `u16`.
- `allocation_2.target_id == client_001a[16:18]` as little-endian `u16`.

P74 uses P72 for the body layouts and P73 for the allocator.  It adds only the
offline composition boundary.

## Remaining scope limitations

P74 does not prove global predictability of `rand@LIBC`, process seeding,
persistence across tunnel recreation, high-halfword mutation outside the proven
constructor path, or any live media viability.  The target-id start value remains
runtime-state dependent, not a numeric constant.

## Safety

OFFLINE_ONLY.  No network I/O, DNS, P2P/ICE/STUN/TURN, PseudoTCP, CTPP sending,
RTPC sending, camera/media session, listener or Home Assistant change, Door
action, replay, injection, credential access, raw payload dump, or proprietary
artifact commit is authorized by this phase.

Required markers include:

```text
RTPC_TARGET_ID_ALLOCATION_CONTRACT=PROVEN_STATIC
RTPC_TARGET_ID_SOURCE=P73_NATIVE_ALLOCATOR
RTPC_TARGET_IDS_CALLER_SUPPLIED=false
OUTBOUND_RTPC_MEDIA_BODY_GENERATION_CONTRACT=PROVEN_OFFLINE_COMPOSED
LIVE_TRANSMISSION_AUTHORIZED=false
NETWORK_IO_PERFORMED=false
RAW_PAYLOAD_EMITTED=false
```
