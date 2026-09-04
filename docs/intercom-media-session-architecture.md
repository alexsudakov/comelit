# Comelit Intercom Media Session Architecture

Status: approved normative supplement
Date: 2026-09-04
Applies to: `custom_components/comelit`
Normative parent: `docs/ha-integration-target-architecture.md`

## 1. Purpose

This document fixes the lifecycle and Home Assistant entity contract for the two Comelit intercom-associated cameras before the media PoC is implemented.

The key constraint is that a Comelit intercom camera/media session must never be kept open permanently. An active media session can prevent other users/clients from connecting to the intercom camera, so media is strictly on-demand and time-bounded.

The persistent Ring/Door listener is a separate 24x7 session and is not governed by this media timeout.

## 2. Non-negotiable media-session rules

1. Intercom media is on-demand only.
2. No intercom video session may be started automatically at Home Assistant startup merely to keep a camera entity live.
3. The initial hard limit for one media session is **180 seconds** from successful session start.
4. The 180-second deadline is absolute. New viewers, snapshots, recording requests or lease acquisitions must not extend the original deadline.
5. At expiry the integration must force a clean media teardown and release all upstream Comelit media resources.
6. Home Assistant unload/reload/shutdown and any media error must also release the upstream session.
7. Until concurrency is explicitly proven safe, the integration must allow **at most one active intercom media session across the whole Comelit integration**, not one per panel.
8. The existing persistent Ring/Door listener must remain independent and must not be stopped merely because video is inactive.
9. Media-session lifecycle code must not invoke Door actions.
10. Media-session cleanup must be idempotent and safe to call repeatedly.

## 3. Session manager

All media consumers must converge on one internal owner, conceptually:

```python
ComelitMediaSessionManager
```

The manager is the only component allowed to create or destroy an upstream Comelit intercom media session.

Conceptual API:

```python
await media.async_acquire(panel="entrance", reason="manual")
await media.async_acquire(panel="entrance", reason="snapshot")
await media.async_acquire(panel="entrance", reason="recording")
await media.async_release(reason="snapshot")
await media.async_force_stop(reason="manual_off")
```

Implementation details may differ, but the ownership and lifecycle semantics are mandatory.

The manager must track at least:

```text
panel
phase
started_at
expires_at
remaining_seconds
active reasons / leases
last_error
```

Suggested phases:

```text
inactive
starting
active
stopping
error
```

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

`turn_off` is an explicit user force-stop command. It must release the upstream media session immediately and cancel all current media leases for that panel/session.

The switch must never silently extend the 180-second hard deadline.

### 4.2 Actual media-state sensor

Target entity:

```text
binary_sensor.comelit_entrance_camera_active
```

This represents observed media-session reality, not merely the requested switch state.

Examples:

```text
switch on + media setup succeeds  -> active sensor on
switch on + media setup fails     -> active sensor off
hard timeout                      -> active sensor off
force stop                        -> active sensor off
```

This entity should be diagnostic unless a later UI requirement justifies normal visibility.

### 4.3 Remaining-time diagnostic sensor

Target entity:

```text
sensor.comelit_entrance_camera_session_remaining
```

It reports remaining seconds until the current absolute 180-second deadline. When no media session exists it may report `0` or be unavailable; the exact HA representation can be chosen during implementation.

It is a diagnostic entity.

### 4.4 Camera entity

Target entity:

```text
camera.comelit_entrance
```

The camera entity must not imply a permanent upstream session.

Manual live viewing is gated by the media session lifecycle above. Snapshot and recording operations may acquire short internal media leases through the same session manager, but they must never bypass the manager or create a second upstream media session.

## 5. Hard timeout semantics

The timer starts when the upstream media session is actually established, not when a user first presses the switch.

Example:

```text
T0       media session becomes active
T0+60    recording lease ends
T0+120   viewer is still watching
T0+180   forced teardown regardless of remaining leases/viewers
```

A new request arriving at `T0+170` may reuse the current session, but it receives only the remaining 10 seconds. It must not move the deadline to `T0+350`.

After forced teardown, a user may explicitly start a new media session if continued viewing is required.

## 6. Snapshot behavior

A snapshot request while media is inactive should use a short-lived internal lease:

```text
snapshot request
  -> acquire session
  -> wait for a decodable frame / required IDR
  -> produce JPEG
  -> release snapshot lease
  -> stop media if no other leases remain
```

A snapshot request must not leave the media session running for the remainder of the 180-second window unless another active lease requires it.

## 7. Recording behavior

The approved ring workflow remains:

```text
ring
  -> start media
  -> snapshot
  -> record 60 seconds
  -> release recording lease
  -> stop media if no other leases remain
```

The 60-second recording duration is independent of whether the Door is opened, the ring is ignored, or the later conversation feature is used.

A recording is still subject to the absolute 180-second media-session hard limit.

An explicit user `switch.turn_off` is allowed to force-stop the media session even if a recording is in progress; this is a deliberate manual override.

## 8. Relationship to the persistent listener

The integration contains two distinct lifecycle domains:

```text
Persistent domain (24x7)
  Comelit Ring/Door listener
  -> registered P2P/ViP listener session
  -> ring events
  -> Door command transport

On-demand domain (0..180 s)
  Comelit intercom media
  -> self-activation / call-media setup
  -> video
  -> later: bidirectional audio
```

Stopping the on-demand media session must not stop or recreate the persistent Ring/Door listener unless protocol evidence later proves that Comelit itself requires a coupled transition.

The media PoC must explicitly test that starting and stopping media does not break ring reception or Door availability.

## 9. Future full-duplex conversation

The same media session manager must become the owner of later conversation media.

Future flow:

```text
answer
  -> acquire conversation lease
  -> receive remote audio/video
  -> transmit microphone audio
  -> hang up
  -> release conversation lease
```

No second, parallel conversation-specific upstream Comelit session manager may be introduced.

The initial implementation should retain the 180-second absolute media limit for conversation until a separate user-facing conversation timeout is explicitly approved.

Conversation audio recording remains out of scope.

## 10. Media PoC acceptance gates

Before exposing `camera.*`, `switch.*` or recording to production HA, the media PoC must prove at least:

1. `entrance` self-activation starts a valid media session on demand.
2. H.264 video can be decoded into both a still image and a playable short recording.
3. media teardown demonstrably releases the Comelit session;
4. repeated start/stop cycles do not leak helper processes, sockets or media sessions;
5. the persistent Ring/Door listener continues working before, during and after media use;
6. the official Comelit application can connect again after our media session stops;
7. the 180-second forced timeout releases the session even if a local viewer remains connected;
8. no Door action is emitted anywhere in the media lifecycle;
9. only one upstream intercom media session can exist at a time until concurrency is separately validated;
10. the `gate` media profile is not assumed identical to `entrance`; it requires its own validation before exposure.

## 11. Implementation order

1. Listener diagnostic entity (`sensor.comelit_listener_status`).
2. Entrance media PoC in the native helper/runtime without production camera entities.
3. Session manager with the 180-second absolute deadline and cleanup gates.
4. Entrance switch + active/remaining diagnostics.
5. `camera.comelit_entrance` live view.
6. Snapshot.
7. 60-second ring recording.
8. Gate media validation and equivalent entities.
9. Full-duplex conversation.
