# Comelit Intercom Media Session Architecture

Status: approved normative supplement, updated after live protocol evidence  
Date: 2026-09-09  
Applies to: `custom_components/comelit`

## 1. Purpose

Intercom media is **on-demand only** and must never be kept permanently open. An active camera/media session can prevent another Comelit client from connecting.

The previous pre-live assumption that media `must not stop or recreate the persistent Ring/Door listener` is retained here only as historical wording and is **superseded by observed protocol behavior**. The production rule is now explicit: the persistent Ring/Door listener runs normally while media is inactive, but it must be intentionally paused before a separately bootstrapped media session starts and restored after media teardown is confirmed.

## 2. Non-negotiable rules

1. Intercom media is on-demand only.
2. Home Assistant startup must not open a camera session just to keep `camera.*` live.
3. One media session has a hard limit of **600 seconds** from successful upstream start.
4. The **deadline is absolute**. New viewers, snapshots, recordings or leases never extend it.
5. The integration permits **at most one active intercom media session across the whole Comelit integration** until a different concurrency model is independently proven.
6. Persistent listener and on-demand media must never own concurrent upstream Comelit sessions.
7. Before media bootstrap: stop the listener runtime, inhibit supervisor reconnect, and confirm listener not running/not ready.
8. After media teardown: confirm media inactive, release the pause, restart the persistent listener, and let it return to READY.
9. If media teardown is uncertain, fail closed and keep the listener paused rather than risk two upstream sessions.
10. Media lifecycle must never invoke a Door action.
11. While media owns the connection, Door actions are temporarily unavailable and must not restart the listener behind the manager's back.
12. Home Assistant core must never be stopped or restarted for this lifecycle.
13. Cleanup is idempotent.
14. `gate` media remains unvalidated and unavailable.

## 3. Session owner

All consumers use one internal owner:

```python
ComelitMediaSessionManager
```

Conceptual API:

```python
await media.async_acquire(panel="entrance", reason="manual")
await media.async_acquire(panel="entrance", reason="snapshot")
await media.async_acquire(panel="entrance", reason="recording")
await media.async_release(reason="snapshot")
await media.async_force_stop(reason="manual_off")
```

The manager tracks:

```text
panel
phase
started_at
expires_at
remaining_seconds
active leases
last_error
listener_paused
```

Phases:

```text
inactive
starting
active
stopping
error
```

## 4. Required start/stop sequencing

Start:

```text
acquire manager lock
-> pause persistent listener
-> stop listener runtime
-> inhibit automatic reconnect
-> confirm listener stopped/not-ready
-> bootstrap entrance media
-> confirm media active
-> set T0 and T0+600 deadline
-> publish active state
```

Stop:

```text
last lease / manual off / hard timeout / unload
-> stop upstream media
-> confirm upstream media inactive
-> release listener pause
-> restart persistent Ring/Door listener
-> listener returns READY
```

If bootstrap fails before media becomes active, restore the listener. If teardown cannot prove release, enter `error` and do not automatically restart the listener.

## 5. Home Assistant entities

Manual activation:

```text
switch.comelit_entrance_camera
```

Observed active state:

```text
binary_sensor.comelit_entrance_camera_active
```

Remaining time diagnostic:

```text
sensor.comelit_entrance_camera_session_remaining
```

Camera:

```text
camera.comelit_entrance
```

Listener diagnostic remains:

```text
sensor.comelit_listener_status
```

and gains intentional state:

```text
paused_media
```

with diagnostics equivalent to:

```text
media_paused=true
runtime_running=false
listener_ready=false
```

The camera entity never owns a permanent upstream session. Live view, snapshot and recording all acquire leases through the same manager.

## 6. Absolute timeout

The 600-second timer starts when the upstream media session is actually established:

```text
T0       media active
T0+60    recording lease may finish
T0+170   a new viewer may reuse the session
T0+600   forced teardown regardless of remaining leases
```

A request at `T0+590` gets only the remaining 10 seconds. It cannot move expiry to `T0+1190`.

## 7. Snapshot

```text
snapshot request
-> pause listener
-> acquire media
-> wait for decodable frame / IDR
-> produce JPEG
-> release snapshot lease
-> stop media if no other lease remains
-> restore listener
```

A snapshot must not leave the session open for the remainder of the 600-second window unless another lease requires it.

## 8. Recording after ring

```text
ring received by persistent listener
-> acquire recording lease
-> pause listener
-> start media
-> snapshot
-> record 60 seconds
-> release recording lease
-> stop media if no other lease remains
-> restore listener
```

The 60-second recording remains subject to the same absolute 600-second limit.

## 9. Door behavior during media

Both public Door surfaces fail closed while `media_paused=true`:

```text
button.comelit_main_entrance_open_door
comelit.open_door
```

They must not call `runtime.async_start()` while media owns the exclusive connection. Door availability returns after media is torn down and the listener is restored.

## 10. Full-duplex future

Conversation uses the same session owner:

```text
answer
-> acquire conversation lease
-> pause listener
-> receive video/audio
-> transmit microphone audio
-> hang up
-> teardown media
-> restore listener
```

No second conversation-specific upstream session manager is allowed. The 600-second limit remains until explicitly changed.

## 11. Acceptance gates

Before exposing media entities in production HA, implementation must prove:

1. entrance self-activation starts valid media after the listener is paused;
2. H.264 produces a still image and playable short recording;
3. teardown releases the upstream Comelit session;
4. the listener is restored and returns READY;
5. repeated start/stop does not leak processes, sockets or media sessions;
6. the **official Comelit application can connect again** after our media session stops;
7. hard timeout releases media even with a local viewer still attached;
8. media lifecycle emits no Door action;
9. Door surfaces stay blocked during media and recover afterward;
10. only one upstream media session exists at a time;
11. gate profile is independently validated before exposure.

## 12. Implementation order

1. Listener diagnostic entity — implemented.
2. Entrance signaling/media receive chain — P46-P78 evidence available.
3. Production `ComelitMediaSessionManager` with absolute 600-second deadline.
4. Exclusive listener pause/resume + Door fail-closed boundary.
5. Package the entrance media native/runtime path for Home Assistant and prove one listener-isolated media cycle.
6. `switch.comelit_entrance_camera` + active/remaining diagnostics.
7. `camera.comelit_entrance` live view.
8. Snapshot.
9. 60-second ring recording.
10. Gate validation.
11. Full-duplex conversation.
