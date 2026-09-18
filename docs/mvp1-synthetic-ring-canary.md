# Comelit MVP1 synthetic entrance-ring canary

Status: current bounded synthetic canary.

Purpose: validate the integration media lifecycle without waiting for a physical Comelit call.

The synthetic trigger is deliberately **not** a public Home Assistant service. It is available only through the existing local-only Comelit test-control webhook, already restricted to CT120.

## Trigger

Test-control action:

```text
simulate_entrance_ring
```

The integration generates a fresh internal `event_id` and emits one:

```text
comelit_ring
```

with:

```text
door=entrance
kind=CALL_INIT
direction=DEVICE_TO_CLIENT
source=synthetic_test
synthetic=true
```

The trigger then starts the existing `RingMediaCoordinator`. It does not invoke Door/Gate code.

## Expected lifecycle

```text
synthetic comelit_ring
-> one entrance media session
-> repeated latest.jpg capture
-> comelit_snapshot_updated sequence
-> one 20 s recording
-> comelit_recording_complete
-> media release
-> persistent listener READY
```

The snapshot target remains approximately 1 second, latest-only, with no frame queue.

The normal retained paths remain:

```text
/media/comelit/rings/<event_id>/latest.jpg
/media/comelit/rings/<event_id>/recording.mp4
```

## Safe live boundary

One synthetic trigger only.

```text
SYNTHETIC_RING_COUNT_MAX=1
MEDIA_SESSION_MAX=1
RECORDING_MAX=1
RECORDING_TARGET_SECONDS=20
DOOR_ACTIONS=0
GATE_ACTIONS=0
AUTOMATIC_RETRY=false
HA_RESTARTS=0
R30H_E_EXECUTED=false
```

A Comelit integration reload may be used at most once if required to activate the exact deployed code. Full Home Assistant restart is not authorized.

## Acceptance

For PASS:

```text
SYNTHETIC_RING_EVENT=PASS
RING_SYNTHETIC_FLAG=true
MEDIA_SESSION_COUNT=1
SNAPSHOT_EVENT_COUNT>=2
SNAPSHOT_SEQUENCE_MONOTONIC=PASS
SNAPSHOT_AVERAGE_INTERVAL_SECONDS observed and approximately 1 s
FINAL_SNAPSHOT_RETAINED=PASS
RECORDING_COUNT=1
RECORDING_TARGET_SECONDS=20
RECORDING_STATE=completed
MEDIA_TEARDOWN=PASS
LISTENER_READY_AFTER_MEDIA=PASS
DOOR_ACTIONS=0
GATE_ACTIONS=0
```

The canary does not prove reception of a physical CALL_INIT and does not prove Door/Gate actuation. Those remain separate already-known/live capabilities.

No Telegram behavior is part of this test.
