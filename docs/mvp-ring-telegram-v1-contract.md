# Comelit Ring / Telegram MVP v1 — current contract

Status: **approved current MVP milestone**  
Date: 2026-09-17  
Baseline at creation: `a54d39ea6dc625ea8facefa7cff556648f58515b`

This document is a normative supplement to `docs/ha-integration-target-architecture.md` and `docs/intercom-media-session-architecture.md`.

For the current product milestone it supersedes only the old narrow MVP boundary in section 13 of `ha-integration-target-architecture.md`. All later proven media ownership / listener pause-resume / Door fail-closed rules remain authoritative.

R30H-E and the approximately 30–35 second upstream media-lifetime investigation are deferred. They are not blockers for this MVP.

## 1. Product goal

Deliver one complete user-facing incoming-ring path instead of continuing long-media research:

```text
Comelit ring
-> normalized HA event
-> bounded on-demand preview media
-> first JPEG
-> one Telegram photo message
-> refresh the photo in that same message at about 1 Hz
-> user chooses Open or Ignore, or interaction times out
-> safe media teardown
-> listener READY again
-> if Open: exactly one Door command after media ownership has been released
```

No full-duplex conversation is part of this MVP.

## 2. Existing architectural invariants

The MVP must preserve all of these:

- production path remains `Home Assistant -> custom_components/comelit -> Comelit`;
- no separate permanent Comelit application server;
- persistent Ring/Door listener owns the normal upstream session while media is inactive;
- on-demand media temporarily owns the exclusive upstream session;
- the listener is paused before media and restored only after confirmed teardown;
- at most one active intercom media session;
- Door actions are unavailable while media owns the connection;
- no automatic Door retry;
- no automatic media retry;
- protocol ACK is not physical Door-state proof;
- current 600 second absolute manager limit remains, but the Telegram interaction window is much shorter;
- `gate` media remains capability-gated until independently validated;
- R30H-E repeat-`0x001A` work is deferred and must not be pulled into this MVP child.

## 3. Ring event contract

The existing normalized HA event remains:

```text
comelit_ring
```

Required payload:

```text
event_id      UUID generated inside the integration
timestamp     UTC ISO timestamp
door          entrance | gate
source        normalized safe source identity
kind          CALL_INIT
direction     DEVICE_TO_CLIENT
```

`event_id` is the correlation key for the complete user interaction. A retransmitted copy of one physical CALL_INIT must not create another logical interaction.

No caller supplies `event_id`.

## 4. MVP event model

The MVP has several semantic events, but screenshot refresh ticks are deliberately **not** events.

### 4.1 `comelit_ring`

Producer: Comelit integration.  
Meaning: one normalized incoming ring interaction started.

This event already exists and remains the root event.

### 4.2 `comelit_ring_interaction`

Producer: HA MVP orchestration.  
This document fixes the exact event name for the previously agreed interaction outcomes.

Required payload:

```text
event_id
door
outcome
message_id        optional
chat_id           optional
timestamp
```

Allowed `outcome` values for MVP v1:

```text
open_requested
ignored
timeout
notification_failed
media_failed
```

This event represents the user/notification interaction, not proof that a physical Door opened.

### 4.3 `comelit_door_operation`

Producer: Comelit integration.  
Meaning: result of exactly one Door attempt.

Required safe payload:

```text
event_id          optional correlation when the caller has one
operation_id
door
state
protocol_acked
write_count
door_specific_ack_proven
automatic_retry_allowed=false
physical_effect_asserted=false
```

The integration must emit this result event for every Door attempt that reaches the public integration path. It must not expose secrets or raw protocol payload.

The operation event is distinct from `comelit_ring_interaction(outcome=open_requested)`: one records user intent, the other records protocol outcome.

### 4.4 Deferred recording event

`recording_complete` was discussed in the older product flow, but no stable public event name was previously fixed. It is not fixed or required by this MVP v1 contract because the 60-second recording flow is deferred in section 11 below.

## 5. Telegram message contract

Telegram orchestration belongs in Home Assistant automation/script (or the existing LLM project if later moved there), not in a third permanent Comelit server.

For one ring interaction there must be exactly **one Telegram media message**.

Initial message:

```text
[ first JPEG ]

Comelit: Подъезд | Калитка

[Открыть] [Игнорировать]
```

The first JPEG should be sent as soon as media is active and a decodable still is available.

The send action must capture the returned Telegram `chat_id` and `message_id`; all later updates target that exact message.

Callback data must contain both action and `event_id`, for example conceptually:

```text
comelit:open:<event_id>
comelit:ignore:<event_id>
```

The implementation may choose an equivalent bounded encoding, but must not lose `event_id` correlation.

## 6. Screenshot refresh contract

The user-facing effect is a "live screenshot" inside one Telegram message.

Rules:

1. Use the already-active **same** media session; do not open one media session per frame.
2. Target refresh cadence: approximately **1 second**.
3. Capture a new JPEG from `camera.comelit_entrance` while media is active.
4. Replace media in the same Telegram message using the native HA Telegram edit-media action.
5. Keep a stable per-event local snapshot path, e.g. under `/media/comelit/rings/<event_id>.jpg`, and replace it atomically.
6. No frame queue.
7. At most one snapshot/edit operation may be in flight for one interaction.
8. If the previous edit is still running at the next tick, **skip that tick**. Never accumulate delayed frames.
9. The newest successfully delivered frame becomes the visible frame.
10. Stop refresh immediately when the interaction becomes terminal (`open_requested`, `ignored`, `timeout`) or when media is no longer usable.
11. On timeout/ignore, leave the last successfully displayed frame in Telegram.
12. Screenshot ticks must not emit one HA event per frame.

The current ~30–35 second upstream lifetime is a known limitation. Because the interaction timeout is 30 seconds, this investigation is not a blocker. The update loop must nevertheless tolerate early media termination and preserve the last frame.

## 7. Interaction timeout

MVP interaction timeout:

```text
30 seconds
```

The timeout starts from creation of the Telegram interaction context.

At timeout:

- mark the context terminal exactly once;
- stop screenshot refresh;
- remove inline buttons;
- retain the last displayed frame;
- emit `comelit_ring_interaction(outcome=timeout)`;
- stop/release media if this interaction owns the last lease;
- restore the listener through the existing media manager lifecycle.

No Door action occurs on timeout.

## 8. Ignore

On the first valid Ignore callback for the active `event_id`:

- atomically mark interaction terminal;
- acknowledge the callback;
- stop screenshot refresh;
- remove inline buttons;
- leave the last frame visible;
- emit `comelit_ring_interaction(outcome=ignored)`;
- release/stop media;
- restore listener READY.

Ignore does not send an active Comelit call-reject command.

Repeated/stale callbacks for the same or older `event_id` must not start media, send Door commands, or reopen the interaction.

## 9. Open

On the first valid Open callback for the active `event_id`:

1. atomically mark interaction terminal;
2. acknowledge callback;
3. stop screenshot refresh;
4. remove inline buttons;
5. emit `comelit_ring_interaction(outcome=open_requested)`;
6. release/stop media;
7. wait boundedly for media inactive and persistent listener READY;
8. perform exactly one semantic Door action for the `door` correlated with this `event_id`;
9. rely on `comelit_door_operation` for protocol result;
10. never retry automatically.

This order is mandatory because the proven production architecture deliberately blocks Door operations while media owns the exclusive Comelit connection.

The Telegram caption may be updated with a safe terminal status after the Door result, but it must not claim the physical Door opened solely from protocol ACK.

## 10. Interaction state / concurrency

MVP v1 permits one active Telegram ring interaction at a time, matching the single active intercom media-session invariant.

Minimum logical states:

```text
IDLE
RING_RECEIVED
MEDIA_STARTING
PREVIEW_ACTIVE
TERMINALIZING
DONE
```

Terminal outcomes:

```text
open_requested
ignored
timeout
notification_failed
media_failed
```

The active context must retain at least:

```text
event_id
door
started_at
terminal flag
Telegram chat_id
Telegram message_id
latest snapshot path
```

A terminal context cannot become active again.

A second distinct ring while another interaction is active must fail closed with respect to media ownership: no second media session and no automatic Door action. The implementation must surface the second ring safely rather than silently corrupt the active context. Exact secondary-notification UX may remain minimal in v1.

## 11. Recording and history

The older product goal remains:

```text
ring -> start recording -> retain approximately 60 seconds -> manual retention/deletion
```

and historically opening the Door was intended not to stop that recording.

However, later proven production behavior introduced a hard architectural conflict: Door actions are intentionally unavailable while media owns the exclusive session. Therefore a single uninterrupted 60-second media recording cannot currently coexist with an early Open action without changing the proven ownership model or introducing a second sequential media session.

For **MVP v1 ship**, 60-second recording is therefore **DEFERRED, not deleted from the roadmap**.

The MVP history baseline is event-driven:

- `comelit_ring` records the beginning of the interaction;
- `comelit_ring_interaction` records the notification/user outcome;
- `comelit_door_operation` records the Door protocol result when applicable;
- the final snapshot for the `event_id` is retained at a stable local path for later browsing/diagnostics.

A later child may add the 60-second retained clip and a `recording_complete` event only after its coexistence semantics with Open are explicitly resolved.

## 12. Entrance vs gate capability

Ring detection already distinguishes:

```text
entrance
gate
```

The complete dynamic-snapshot path is currently an **entrance** capability because entrance media is the only validated media profile.

`gate` ring events remain valid and must preserve `event_id`/door correlation, but gate media must not be enabled by assumption.

Likewise, existence of a Gate Button entity is not sufficient proof of a validated Gate actuation profile. Gate actuation remains capability-gated by the current production safety contract.

The entrance MVP flow may ship while these gate-specific media/actuation capabilities remain separately gated; they must be reported as explicit capability gaps, not silently emulated with entrance behavior.

## 13. Current MVP acceptance

Entrance MVP is complete when all of the following are proven:

```text
RING_EVENT=PASS
EVENT_ID_CORRELATION=PASS
RING_DEDUP=PASS
MEDIA_SINGLE_SESSION=PASS
FIRST_JPEG=PASS
TELEGRAM_SINGLE_MESSAGE=PASS
TELEGRAM_MESSAGE_ID_CAPTURE=PASS
SCREENSHOT_REFRESH_APPROX_1HZ=PASS
SCREENSHOT_NO_QUEUE=PASS
OPEN_CALLBACK_ONE_SHOT=PASS
IGNORE_CALLBACK_ONE_SHOT=PASS
TIMEOUT_30S=PASS
INTERACTION_EVENT=PASS
DOOR_OPERATION_EVENT=PASS
OPEN_STOPS_MEDIA_BEFORE_DOOR=PASS
LISTENER_READY_AFTER_IGNORE=PASS
LISTENER_READY_AFTER_TIMEOUT=PASS
LISTENER_READY_BEFORE_OPEN_DOOR=PASS
AUTOMATIC_RETRY=false
SECOND_MEDIA_SESSION=false
R30H_E_REQUIRED_FOR_MVP=false
```

No acceptance criterion requires media past 35/40/60 seconds.

## 14. Explicit non-goals for this MVP child

- R30H-E repeat-`0x001A` corrective;
- periodic media lease refresh;
- media lifetime >30–35 seconds;
- full-duplex audio;
- answering/hanging up Comelit call protocol;
- audio recording;
- Frigate/go2rtc redesign;
- permanent camera session;
- gate media activation without separate proof;
- automatic Door retry;
- claiming physical Door state from protocol ACK;
- a third standalone Comelit application server.
