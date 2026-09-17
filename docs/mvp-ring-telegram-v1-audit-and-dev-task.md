# Comelit Ring / Telegram MVP v1 — current-main audit and offline DEV task

TASK_ID=`COMELIT-MVP1-RING-TELEGRAM-OFFLINE-BUILD`

MODE=`OFFLINE_ONLY`

Baseline audited: `a54d39ea6dc625ea8facefa7cff556648f58515b`

Companion contract: `docs/mvp-ring-telegram-v1-contract.md`

## 1. Purpose

Build the minimum offline implementation artifacts required for the first end-to-end Ring -> dynamic Telegram snapshot -> Open/Ignore/Timeout MVP, while explicitly deferring long-media refresh work (R30H-E), physical Gate validation, HA deployment and live actions.

This task includes a static audit because large parts of the required foundation already exist and must be reused rather than reimplemented.

## 2. Current-main audit

### READY — reuse as-is unless a test exposes a defect

#### Incoming ring producer

Current runtime already:

- parses safe CALL_INIT markers;
- distinguishes `entrance` and `gate`;
- maps sources through the closed set;
- generates an internal UUID `event_id`;
- adds UTC `timestamp`;
- emits `comelit_ring` on the HA bus.

Status: `READY`.

#### Ring source mapping

Current canonical mapping:

```text
00000643 -> entrance
00000610 -> gate
```

Unknown/mismatched source fails closed.

Status: `READY`.

#### Ring retransmit deduplication

README/current runtime contract records exact-frame retransmit deduplication for incoming CALL_INIT.

Status: `READY`.

#### Entrance media owner

`ComelitMediaSessionManager` already provides:

- one active media session;
- listener pause/resume;
- leases by reason;
- absolute 600 s hard limit;
- transport watchdog;
- fail-closed teardown behavior.

Status: `READY`.

#### Manual entrance media switch

`switch.comelit_entrance_camera` already starts/stops the same manager.

Status: `READY`.

#### Entrance camera entity

`camera.comelit_entrance` already:

- exposes HA Stream;
- reports active/forwarding packet diagnostics;
- implements `async_camera_image()` from the active stream;
- supports snapshots only while media is already active.

Status: `READY_FOR_REUSE`.

#### Listener diagnostic

`sensor.comelit_listener_status` already exposes listener state including media pause.

Status: `READY`.

#### HA native building blocks

Current Home Assistant provides native actions needed for the orchestration layer:

```text
camera.snapshot
telegram_bot.send_photo
telegram_bot.edit_message_media
telegram_bot.edit_replymarkup
telegram_bot.answer_callback_query
```

`telegram_bot.send_photo` returns `chat_id` and `message_id`, so no external Telegram client is required.

Status: `READY_PLATFORM_CAPABILITY`.

### PARTIAL

#### Door UI/API

Entrance Door action/button implementation exists and is intentionally blocked while media owns the exclusive connection.

Gate Button entity also exists, but current canonical capability model marks Gate actuation profile unvalidated and public service support is still entrance-only.

Status:

```text
ENTRANCE_DOOR=READY
GATE_ENTITY=EXISTS_BUT_ACTUATION_GATED
```

Do not rewrite buttons as part of this task.

#### Event history

`comelit_ring` already provides a Recorder-visible event source, but there is no complete interaction/outcome event chain and no retained final-snapshot convention.

Status: `PARTIAL`.

### MISSING — this task's implementation scope

#### Door-operation HA event

The approved architecture requires a Door operation result event, but current runtime/service/button path does not emit `comelit_door_operation`.

Status: `MISSING`.

#### Ring-interaction outcome event

No `comelit_ring_interaction` producer currently exists.

Status: `MISSING`.

#### Automatic Ring -> media -> first JPEG orchestration

Current camera/media path is manual. No production orchestration consumes `comelit_ring` and starts the bounded preview flow.

Status: `MISSING`.

#### Telegram single-message preview

No current code sends the first JPEG, captures Telegram `message_id`, or updates the same message.

Status: `MISSING`.

#### ~1 Hz latest-only refresh

No current implementation exists for:

```text
wait/capture/edit
-> no queued frames
-> skip/delay naturally while previous edit is in flight
-> stop at terminal state
```

Status: `MISSING`.

#### Open / Ignore / Timeout orchestration

No current one-shot callback context exists for a ring `event_id`.

Status: `MISSING`.

#### Final snapshot retention

No per-`event_id` retained final JPEG convention exists.

Status: `MISSING`.

### DEFERRED — explicitly not blockers

#### R30H-E / repeat 0x001A / >30–35 s source lifetime

Status: `DEFERRED_POST_MVP`.

The 30-second Telegram interaction window does not require media >35/40/60 seconds.

#### 60-second retained recording

Status: `DEFERRED_POST_MVP`.

Reason: later proven production ownership makes Door unavailable while media is active. The historical requirement "record 60 seconds even if Open is pressed" needs a separate explicit resolution (truncated clip vs sequential second media session vs different protocol ownership). Do not silently choose one in this task.

#### Gate media and physical Gate validation

Status: `DEFERRED_SEPARATE_CAPABILITY_PROOF`.

No physical action is authorized by this task.

## 3. Implementation architecture for this child

Keep responsibilities separated.

### 3.1 Comelit integration

Implement only generic Comelit responsibilities:

- emit `comelit_door_operation` once for every completed public Door attempt, regardless of whether it came from ButtonEntity or `comelit.open_door`;
- keep protocol result semantics unchanged;
- do not add Telegram dependencies to `custom_components/comelit`;
- do not change media protocol/native code;
- do not weaken Gate capability checks.

Preferred implementation: centralize Door result finalization in the shared runtime path so service and button cannot diverge.

No Door retry.

### 3.2 HA orchestration artifact

Add a production-oriented example/blueprint/package artifact for Home Assistant which consumes `comelit_ring` and implements the MVP interaction.

It must use native HA actions rather than a standalone bot process.

The artifact must be configurable for the user's Telegram bot/event entities at deployment time and must not commit chat IDs, bot tokens, URLs containing credentials, or other private configuration.

Preferred control structure:

```text
trigger: comelit_ring
mode: single

capture event_id + door
start entrance media when capability exists
wait boundedly for video forwarding / packet progress
capture first JPEG
send one Telegram photo -> response_variable -> exact chat_id/message_id

loop until first of:
  matching Open callback
  matching Ignore callback
  30 s deadline
  fatal media/notification failure

inside loop:
  wait up to ~1 s for matching callback
  if no callback:
      snapshot same camera to same per-event file
      edit exact same Telegram message media
      no queue / no parallel frame edit

terminalize exactly once
remove inline keyboard
stop media
wait listener ownership restored
if Open:
    call comelit.open_door exactly once
```

A sequential loop is preferred because it inherently prevents a frame backlog: the next tick cannot start until the prior snapshot/edit has completed.

### 3.3 Callback correlation

A callback is valid only if its embedded `event_id` equals the active automation run's `event_id`.

Stale/different callbacks:

- may be acknowledged as expired;
- must not stop the current media;
- must not invoke Door;
- must not reopen any context.

The first valid Open/Ignore callback is terminal. Later callbacks are inert.

### 3.4 Open sequencing

Because Door is fail-closed during media, the automation must not call Door first.

Required sequence:

```text
Open callback
-> mark interaction terminal
-> emit comelit_ring_interaction(open_requested)
-> stop refresh
-> remove buttons
-> turn media off / release session
-> wait boundedly for listener READY
-> exactly one comelit.open_door(door)
-> no retry
```

If listener READY cannot be proven in the bounded wait, do not invoke Door. Surface a safe failure outcome.

## 4. Exact event contract to implement/test

### `comelit_ring`

Already existing. Preserve payload/behavior.

### `comelit_ring_interaction`

Produced by orchestration artifact.

Minimum fields:

```text
event_id
door
outcome
message_id optional
chat_id optional
timestamp
```

Allowed MVP outcomes:

```text
open_requested
ignored
timeout
notification_failed
media_failed
```

No secrets.

### `comelit_door_operation`

Produced by integration shared Door runtime.

Minimum safe fields:

```text
operation_id
door
state
protocol_acked
write_count
door_specific_ack_proven
automatic_retry_allowed=false
physical_effect_asserted=false
```

Do not claim physical state.

## 5. Snapshot path and update rules

Use a deployment-configurable path under an HA-allowed media directory. Reference example:

```text
/media/comelit_ring_<event_id>.jpg
```

Rules:

- one file per logical event;
- update atomically where practical;
- same path may be overwritten with newest frame;
- final successful frame remains after terminal state;
- no raw RTP/H264/audio persistence;
- no endless cleanup job required in this child;
- no screenshot filename may contain a token, source secret, peer/session identifier, or raw authorization material.

## 6. Offline tests required

Codex must add/extend tests sufficient to prove at least:

```text
DOOR_OPERATION_EVENT_EXACTLY_ONCE=PASS
DOOR_OPERATION_EVENT_SAFE_PAYLOAD=PASS
DOOR_OPERATION_EVENT_FROM_SERVICE_AND_BUTTON_SHARED_PATH=PASS
RING_EVENT_CONTRACT_UNCHANGED=PASS
RING_SOURCE_MAPPING_UNCHANGED=PASS
GATE_ACTUATION_STILL_GATED=PASS
MEDIA_PROTOCOL_CODE_UNCHANGED=PASS
R30H_E_CODE_UNCHANGED=PASS
TELEGRAM_ORCHESTRATION_NO_SECRETS=PASS
TELEGRAM_SINGLE_MESSAGE_MODEL=PASS
TELEGRAM_USES_RETURNED_MESSAGE_ID=PASS
SCREENSHOT_REFRESH_SERIAL_NO_QUEUE=PASS
SCREENSHOT_REFRESH_TARGET_APPROX_1HZ=PASS
CALLBACK_EVENT_ID_MATCH_REQUIRED=PASS
CALLBACK_ONE_SHOT=PASS
IGNORE_NO_DOOR=PASS
TIMEOUT_NO_DOOR=PASS
OPEN_MEDIA_STOP_BEFORE_DOOR=PASS
OPEN_LISTENER_READY_GATE_BEFORE_DOOR=PASS
OPEN_DOOR_MAX_INVOCATIONS=1
AUTOMATIC_RETRY=false
INTERACTION_TIMEOUT_SECONDS=30
RECORDING_IMPLEMENTED=false
```

Tests for the HA artifact may be static/structural where no HA runtime harness exists, but should parse/validate YAML rather than rely only on grep when practical.

## 7. Allowed repository write scope

Codex may modify only what is needed among:

```text
custom_components/comelit/const.py
custom_components/comelit/runtime.py
custom_components/comelit/__init__.py
custom_components/comelit/button.py
custom_components/comelit/services.yaml
custom_components/comelit/translations/**
tests/**
safety-poc/tests/**
examples/**
docs/mvp-ring-telegram-v1-*.md
```

The exact subset should be minimal.

Do not modify unless independently required by the event implementation:

```text
custom_components/comelit/camera.py
custom_components/comelit/media_session.py
custom_components/comelit/media_transport.py
custom_components/comelit/native/**
safety-poc/research/media/v1/entrance_p116_r27_repeat_001a_transform.py
safety-poc/research/media/v1/ct120_run_p116_r27_repeat_001a_live.sh
R30H-E executable research artifacts
```

## 8. Forbidden in this child

```text
COMELIT_LIVE_EXECUTED=false
HA_DEPLOYED=false
HA_RELOADED=false
HA_RESTARTED=false
PRODUCTION_LISTENER_TOUCHED=false
DOOR_ACTIONS=0
GATE_ACTIONS=0
R30H_E_EXECUTED=false
REPEAT_001A_CHANGED=false
PACKAGED_NATIVE_TOUCHED=false
RAW_MEDIA_CAPTURED=false
TELEGRAM_MESSAGE_SENT=false
```

No live Telegram message is authorized either; only offline/static implementation and tests.

## 9. Executor model

- Hermes = orchestrator only.
- One bounded Codex CLI context for semantic implementation and test correction.
- Resume the same Codex session for ordinary implementation/test defects.
- Hermes must not author executable code.
- Fresh authenticated fetch; use actual latest accepted `origin/main`.
- CT120 GitHub access must use `/root/.config/git/comelit.credentials`, mode 600, credential-free remote and repo-local helper settings.

## 10. Required output/result

Create:

```text
docs/mvp-ring-telegram-v1-offline-build-result.md
```

Result classes:

```text
PASS_OFFLINE_MVP_READY
BLOCKED_HA_ORCHESTRATION_SEMANTICS
FAIL_OFFLINE_MVP_BUILD
INCONCLUSIVE
```

`PASS_OFFLINE_MVP_READY` means only that code/artifacts/tests are ready for a separately authorized HA deploy/canary. It does not authorize media activation, Telegram sends, Door/Gate action, reload or restart.

Required final scalar block:

```text
=== COMELIT MVP1 RING TELEGRAM OFFLINE BUILD ===
TASK_ID=COMELIT-MVP1-RING-TELEGRAM-OFFLINE-BUILD
BASE_SHA=<actual accepted main>
RING_EVENT=PASS|FAIL
RING_EVENT_ID=PASS|FAIL
RING_DEDUP=PASS|FAIL
DOOR_OPERATION_EVENT=PASS|FAIL
INTERACTION_EVENT_ARTIFACT=PASS|FAIL
TELEGRAM_SINGLE_MESSAGE_MODEL=PASS|FAIL
TELEGRAM_MESSAGE_ID_CAPTURE=PASS|FAIL
SCREENSHOT_REFRESH_SERIAL_NO_QUEUE=PASS|FAIL
SCREENSHOT_REFRESH_TARGET_SECONDS=1
INTERACTION_TIMEOUT_SECONDS=30
OPEN_MEDIA_STOP_BEFORE_DOOR=PASS|FAIL
OPEN_LISTENER_READY_GATE_BEFORE_DOOR=PASS|FAIL
OPEN_DOOR_MAX_INVOCATIONS=1
IGNORE_NO_DOOR=PASS|FAIL
TIMEOUT_NO_DOOR=PASS|FAIL
FINAL_SNAPSHOT_RETENTION=PASS|FAIL
GATE_ACTUATION_GATED=true
GATE_MEDIA_GATED=true
RECORDING_IMPLEMENTED=false
R30H_E_EXECUTED=false
COMELIT_LIVE_EXECUTED=false
TELEGRAM_MESSAGE_SENT=false
HA_DEPLOYED=false
HA_RELOADED=false
HA_RESTARTED=false
DOOR_ACTIONS=0
GATE_ACTIONS=0
BRANCH=<branch>
REMOTE_HEAD=<sha|NOT_PUSHED>
PR=<number|none>
RESULT=<class>
=== END COMELIT MVP1 RING TELEGRAM OFFLINE BUILD ===
```

After this child: STOP. A deploy/canary requires a separate explicit authorization with bounded live/media/Telegram/physical-action scope.
