# Current Ring -> Telegram Home Assistant automation

Status: **current production-consumer contract**  
Date: 2026-09-25  
Applies to: Comelit integration 1.5.17+; reviewed against 1.5.19

This document supersedes the old MVP-v1 Telegram timing/ownership rules for current
Home Assistant deployments. Historical MVP documents remain in the repository as
evidence of the earlier milestone.

## 1. Ownership boundary

The Comelit integration owns the protocol/media lifecycle:

```text
CALL_INIT
-> comelit_ring
-> attached inbound media
-> shared HA Stream
-> comelit_snapshot_updated
-> 20-second recording
-> comelit_recording_complete
-> keep attached Ring media alive
-> backend-observed remote close
-> sensor.comelit_call_state -> idle
```

The Home Assistant automation is only a consumer/orchestrator. It must not:

- turn `switch.comelit_entrance_camera` on or off;
- call `camera.snapshot` to create a second media lifecycle;
- infer call end from a 30/60 second local timer;
- stop attached media on Ignore;
- start a second Comelit media session;
- retry Door automatically.

## 2. Authoritative call lifetime

Current source of truth:

```text
sensor.comelit_call_state
```

Relevant current states:

```text
idle
ringing
error
```

Relevant attributes:

```text
panel
event_id
started_at
media_attached
conversation_active
last_error
```

For a real call, `ringing -> idle` is driven by backend-observed remote-release
evidence. The automation must correlate the active `event_id`; a wall-clock timeout
is only a defense-in-depth guard, not normal call termination.

Recommended automation safety guard: 600 seconds, matching the integration's Ring-media
hard ceiling.

## 3. Recording and snapshots

Recording target remains:

```text
20 seconds
```

Recording completion is independent from call completion.

After `comelit_recording_complete`:

- send/annotate the retained recording;
- do **not** end the Telegram interaction merely because recording finished;
- continue consuming `comelit_snapshot_updated` while the same call remains active.

The final successful JPEG and recording are integration-owned artifacts.

## 4. Telegram interaction

The first `comelit_snapshot_updated` for the exact Ring `event_id` creates one
Telegram photo message.

Subsequent snapshot events edit that same message. The automation stores and validates:

```text
event_id
Telegram chat_id
Telegram message_id
```

Callbacks are accepted only when all three still match the active interaction.

## 5. Ignore

Ignore is notification semantics only.

```text
Ignore
-> answer Telegram callback
-> emit comelit_ring_interaction(outcome=ignored)
-> remove Telegram controls
-> finish Telegram interaction
```

It must **not**:

- stop Ring media;
- send a Comelit reject/hangup packet;
- alter the authoritative backend call state.

The remote Comelit side remains responsible for normal call termination.

## 6. Open

Current 1.5.19 implementation has two Door surfaces with a deliberate practical
difference during attached inbound media:

- the Custom Card uses the standard Door button entity;
- the `comelit.open_door` service currently fails closed while
  `attached_media_busy=true`.

Therefore the current Telegram automation uses exactly one explicit Home Assistant
button press, matching the Custom Card path:

```yaml
action: button.press
target:
  entity_id: button.comelit_main_entrance_open_door
```

Rules:

- only while the exact `sensor.comelit_call_state.event_id` is still `ringing`;
- exactly one press per accepted callback;
- no automatic retry;
- do not stop attached media first;
- do not wait for listener READY first;
- do not claim physical opening from service completion.

Because `button.press` does not pass the Ring `event_id` into
`comelit_door_operation`, the automation separately emits
`comelit_ring_interaction(outcome=open_requested)` with the Ring correlation.

This is the current production-consumer behavior. A future integration change may
unify the service and button semantics without requiring Telegram to know protocol
details.

## 7. Terminal outcomes

Normal terminal reasons for the Telegram interaction:

```text
open_requested
ignored
call_ended
call_error
safety_timeout
```

`call_ended` comes from the authoritative call-state transition for the same Ring.
The 600-second `safety_timeout` is abnormal defense-in-depth only.

After a terminal outcome, remove inline controls so stale callbacks cannot cause a
later Door action.

## 8. Deprecated switch

```text
switch.comelit_entrance_camera
```

is a deprecated, disabled-by-default diagnostic fallback. Camera-owned automatic
startup and release have already been live-validated in HAOS. Current Telegram
automation must not depend on the switch.

## 9. Reference automation

The maintained package example is:

```text
examples/home-assistant/packages/comelit_ring_telegram_live.yaml
```

For UI-managed automations, use the automation body from that example without the
top-level `automation:` package wrapper.
