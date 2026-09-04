# V4.2 incoming-ring protocol oracle

This directory preserves the exact C source used by the successful V4.2 incoming-ring experiment.

Source SHA-256:

`d6fe792ad252851a415ae23c2449c199e4a6fac540ed1e162f9047967753a836`

The binary and runtime wrapper are intentionally not version-controlled.

This source is research evidence and a protocol oracle. It is not the target Home Assistant runtime implementation.

Live-proven entrance-ring markers:

```text
V4_RING_OBSERVED=true
V4_RING_DIRECTION=DEVICE_TO_CLIENT
V4_RING_KIND=CALL_INIT
V4_RING_DOOR=entrance
V4_RING_SOURCE=00000643
NETWORK_DOOR_ACTION_PERFORMED=false
PHYSICAL_DOOR_ACTION=false
```

No answer-call, media, Door, P13 or P14 action is part of this evidence.
