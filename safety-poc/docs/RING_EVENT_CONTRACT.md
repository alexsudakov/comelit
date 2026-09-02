# Incoming Ring Event Contract

Status: implementation baseline after successful live entrance-ring proof.

## Proven incoming event

The live-proven incoming event is:

```text
direction = DEVICE_TO_CLIENT
kind      = CALL_INIT
source    = 00000643
door      = entrance
```

The same observation reported:

```text
NETWORK_DOOR_ACTION_PERFORMED=false
PHYSICAL_DOOR_ACTION=false
```

Ring observation is therefore separate from Door actuation.

## Closed source mapping

The implementation uses the fixed mapping:

```text
00000643 -> entrance
00000610 -> gate
```

The entrance mapping has been proven by a real incoming call.

The gate mapping is part of the established Comelit source mapping, but an incoming gate call has not yet been live-proven.

## Normalization rules

`ring_event.py` consumes safe V4 marker lines only.

An event is emitted only when:

1. `V4_RING_OBSERVED=true`
2. direction is `DEVICE_TO_CLIENT`
3. kind is `CALL_INIT`
4. source belongs to the closed source mapping
5. reported door matches that source

Unknown, incomplete or conflicting observed-ring data fails closed.

No ring marker, or `V4_RING_OBSERVED=false`, produces no event.

## Call identity

No protocol-level call/session identifier has yet been proven.

The implementation therefore does not invent a Comelit `call_id`.

A future Home Assistant event may use a locally generated event identifier if needed, but it must not be represented as a Comelit protocol call identifier.

## Not implemented in this slice

- persistent listener supervision
- automatic reconnect
- P14 ring API
- Home Assistant event emission
- snapshots or recording
- answer-call
- audio/video media
- Door actuation
- Telegram

## Safety boundary

The normalized ring model is read-only:

- no network imports
- no subprocess execution
- no Door calls
- no P13/P14 invocation
- no retry or actuation semantics

The frozen V4.2 C source is retained separately only as the protocol oracle.
