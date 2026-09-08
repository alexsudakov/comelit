# Comelit Intercom Media Session Architecture

Status: approved normative supplement, updated after live protocol evidence  
Date: 2026-09-09  
Applies to: `custom_components/comelit`  
Normative parent: `docs/ha-integration-target-architecture.md`

## 1. Purpose

This document fixes the lifecycle and Home Assistant entity contract for the two Comelit intercom-associated cameras.

A Comelit intercom camera/media session must never be kept open permanently. An active media session can prevent other users/clients from connecting to the intercom camera, so media is strictly on-demand and time-bounded.

Protocol work also established an additional runtime constraint: the persistent Ring/Door listener and a separately bootstrapped media session must not be active at the same time. Normal operation therefore keeps the Ring/Door listener running 24x7, but the media-session manager temporarily pauses it while an on-demand media session owns the Comelit connection.

## 2. Non-negotiable media-session rules

1. Intercom media is on-demand only.
2. No intercom video session may be started automatically at Home Assistant startup merely to keep a camera entity live.
3. The initial hard limit for one media session is **180 seconds** from successful session start.
4. The 180-second deadline is absolute. New viewers, snapshots, recording requests or lease acquisitions must not extend the original deadline.
5. At expiry the integration must force a clean media teardown and release all upstream Comelit media resources.
6. Home Assistant unload/reload/shutdown and any media error must also release the upstream session when release can be confirmed safely.
7. Until concurrency is explicitly proven safe, the integration must allow **at most one active intercom media session across the whole Comelit integration**, not one per panel.
8. The persistent Ring/Door listener runs whenever media is inactive, but it **must be fully paused before media bootstrap starts**.
9. Media bootstrap may begin only after the listener runtime is confirmed stopped/not-ready and automatic listener reconnect is inhibited.
10. The listener may be restarted only after media teardown is confirmed. If media teardown is uncertain, fail closed and keep the listener paused rather than creating two potentially concurrent Comelit sessions.
11. While media owns the exclusive Comelit connection, Door actions are unavailable and must not start the listener behind the media manager's back.
12. Media-session lifecycle code must never invoke a Door action.
13. Media-session cleanup must be idempotent and safe to call repeatedly.
14. Home Assistant core itself must never be stopped or restarted as part of media lifecycle management.

## 3. Session manager

All media consumers converge on one internal owner:

```python
ComelitMediaSessionManager
```

The manager is the only component allowed to create or destroy an upstream Comelit intercom media session and the only media component allowed to acquire the listener pause.

Conceptual API:

```python
await media.async_acquire(panel="entrance", reason="manual")
await media.async_acquire(panel="entrance", reason="snapshot")
await media.async_acquire(panel="entrance", reason="recording")
await media.async_release(reason="snapshot")
await media.async_force_stop(reason="manual_off")
```

The manager tracks at least:

```text
panel
phase
started_at
expires_at
remaining_seconds
active reasons / leases
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

### 3.1 Start sequence

The required start sequence is:

```text
media acquire
  -> serialize on media-session lock
  -> request exclusive listener pause
  -> stop persistent listener runtime
  -> inhibit supervisor auto-reconnect
  -> confirm listener stopped/not-ready
  -> bootstrap Comelit media session
  -> confirm media active
  -> set T0 and absolute T0+180 deadline
  -> publish active state
```

If media bootstrap fails before an upstream media session becomes active, the manager restores the listener.

If bootstrap partly succeeds and cleanup cannot prove that the media session was released, the manager enters `error` and leaves the listener paused. This is fail-closed behavior against accidental concurrent upstream sessions.

### 3.2 Stop sequence

The required stop sequence is:

```text
force stop / last lease / hard timeout / unload
  -> stop upstream media
  -> confirm upstream media inactive
  -> release exclusive listener pause
  -> restart persistent Ring/Door listener
  -> supervisor resumes normal reconnect policy
  -> listener returns to READY
```

A failed or uncertain media teardown must not be hidden by immediately starting the listener.

## 4. Home Assistant entities

### 4.1 Manual camera switch

Target entity:

```text
switch.comelit_entrance_camera
```

Later, after the gate media profile is independently validated:

```text
switch.comelit_gate_camera
```

`turn_on` requests a manual media lease and starts the on-demand media session if none exists.

`turn_off` is an explicit user force-stop command. It releases the upstream media session immediately and cancels all current media leases for that panel/session.

The switch never extends the 180-second hard deadline.

### 4.2 Actual media-state sensor

Target entity:

```text
binary_sensor.comelit_entrance_camera_active
```

This represents observed media-session reality, not merely requested switch state.

Examples:

```text
switch on + media setup succeeds  -> active sensor on
switch on + media setup fails     -> active sensor off
hard timeout                      -> active sensor off
force stop                        -> active sensor off
```

### 4.3 Remaining-time diagnostic sensor

Target entity:

```text
sensor.comelit_entrance_camera_session_remaining
```

It reports remaining seconds until the current absolute 180-second deadline. When no media session exists it reports `0` or unavailable according to the final HA entity implementation.

### 4.4 Listener status

Existing diagnostic entity:

```text
sensor.comelit_listener_status
```

must distinguish an intentional media pause from failure/reconnect noise. The normative state for this transition is:

```text
paused_media
```

and diagnostics expose:

```text
media_paused=true
runtime_running=false
listener_ready=false
```

### 4.5 Camera entity

Target entity:

```text
camera.comelit_entrance
```

The camera entity must not imply a permanent upstream session. Manual live viewing, snapshot and recording all acquire leases through the same media-session manager and can never create a second upstream media session.

## 5. Hard timeout semantics

The timer starts when the upstream media session is actually established, not when a user first presses the switch.

Example:

```text
T0       media session becomes active
T0+60    recording lease ends
T0+120   viewer is still watching
T0+180   forced teardown regardless of remaining leases/viewers
```

A new request arriving at `T0+170` may reuse the current session, but receives only the remaining 10 seconds. It must not move the deadline.

After forced teardown and listener restoration, a user may explicitly start a new media session if continued viewing is required.

## 6. Snapshot behavior

A snapshot request while media is inactive uses a short-lived internal lease:

```text
snapshot request
  -> pause listener
  -> acquire media session
  -> wait for a decodable frame / required IDR
  -> produce JPEG
  -> release snapshot lease
  -> stop media if no other leases remain
  -> restore listener
```

A snapshot request must not leave the media session running for the remainder of the 180-second window unless another active lease requires it.

## 7. Recording behavior

The approved ring workflow is:

```text
ring received by persistent listener
  -> acquire recording media lease
  -> pause listener
  -> start media
  -> snapshot
  -> record 60 seconds
  -> release recording lease
  -> stop media if no other leases remain
  -> restore listener
```

The 60-second recording duration is independent of whether the Door is opened, the ring is ignored, or the later conversation feature is used. Recording remains subject to the absolute 180-second media-session hard limit.

An explicit user `switch.turn_off` may force-stop the media session even if recording is in progress.

## 8. Relationship to the persistent listener

The integration has two lifecycle domains but one exclusive upstream Comelit connection slot:

```text
Normal state
  Persistent Ring/Door listener = active
  On-demand media              = inactive

Media state
  Persistent Ring/Door listener = intentionally paused
  On-demand media              = active (0..180 s)

Return to normal
  media teardown confirmed
  -> persistent listener restarted
  -> READY restored
```

Therefore ring reception and Door transport are intentionally unavailable during the bounded media ownership window. This is preferable to attempting two simultaneous upstream sessions that the protocol/runtime does not reliably support.

The listener must not be stopped merely because video is *inactive*. It is paused only as part of an actual media acquisition and restored immediately after the media session ends.

## 9. Door behavior during media

Door actions remain one-shot and non-retryable, but they are additionally fail-closed while `media_paused=true`.

Both public surfaces must enforce this:

```text
button.comelit_main_entrance_open_door
comelit.open_door service
```

Neither may directly call `runtime.async_start()` while media owns the exclusive connection.

After media teardown is confirmed and the listener is restored, Door availability returns automatically.

## 10. Future full-duplex conversation

The same media session manager owns later conversation media:

```text
answer
  -> acquire conversation lease
  -> pause persistent listener
  -> receive remote audio/video
  -> transmit microphone audio
  -> hang up
  -> release conversation lease
  -> teardown media
  -> restore persistent listener
```

No second conversation-specific upstream Comelit session manager may be introduced.

The initial implementation retains the 180-second absolute media limit for conversation until a separate user-facing timeout is approved.

Conversation audio recording remains out of scope.

## 11. Media implementation acceptance gates

Before exposing `camera.*`, camera switches or recording to production HA, implementation must prove at least:

1. `entrance` self-activation starts a valid media session on demand with the listener intentionally paused first;
2. H.264 video can be decoded into both a still image and a playable short recording;
3. media teardown demonstrably releases the Comelit session;
4. the listener is restored and returns to READY after media teardown;
5. repeated start/stop cycles do not leak helper processes, sockets or media sessions;
6. the official Comelit application can connect again after our media session stops;
7. the 180-second forced timeout releases the media session even if a local viewer remains connected;
8. no Door action is emitted anywhere in the media lifecycle;
9. Door surfaces remain blocked while media owns the connection and recover after listener restoration;
10. only one upstream intercom media session can exist at a time;
11. the `gate` media profile is not assumed identical to `entrance` and requires independent validation before exposure.

## 12. Implementation order

1. Listener diagnostic entity (`sensor.comelit_listener_status`). — implemented.
2. Entrance signaling/media receive research chain. — P46-P78 evidence available.
3. Production media-session manager with 180-second absolute deadline. — implementation in progress.
4. Exclusive listener pause/resume integrated into supervisor and Door fail-closed boundary. — implementation in progress.
5. Package the entrance media native/runtime path for Home Assistant and prove one listener-isolated live media cycle.
6. Entrance switch + active/remaining diagnostics.
7. `camera.comelit_entrance` live view.
8. Snapshot.
9. 60-second ring recording.
10. Gate media validation and equivalent entities.
11. Full-duplex conversation.
