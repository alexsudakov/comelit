# Comelit Home Assistant Integration MVP v1 — canonical contract

Status: **current MVP boundary**  
Date: 2026-09-17  
Baseline at creation: `ee4f99707afa6bda999e1803ec0a2177880a789a`

This document supersedes `docs/mvp-ring-telegram-v1-contract.md` **only as the definition of the Comelit integration MVP**.

The Telegram package/example already present in the repository is optional integration-consumer material. Telegram is **not** part of MVP acceptance, deployment, canary, or product completeness. Telegram messages remain a Home Assistant automation concern outside the Comelit MVP.

R30H-E and long-media lease refresh are deferred.

## 1. MVP product goal

The MVP is the Home Assistant Comelit integration itself:

```text
persistent Comelit listener
-> normalized HA events
-> on-demand intercom camera/media
-> periodically refreshed latest snapshot
-> bounded short recording
-> safe media teardown
-> listener READY
-> existing Door/Gate controls
-> Door operation result event
```

No Telegram dependency is allowed in MVP acceptance.

## 2. Existing functionality to preserve

The implementation must reuse, not redesign, the already delivered foundation:

- direct Home Assistant custom integration (`custom_components/comelit`);
- persistent Ring/Door listener;
- `comelit_ring` normalized HA bus event;
- ring source mapping `entrance` / `gate`;
- CALL_INIT retransmit deduplication;
- existing Door/Gate button entities and semantic Door path;
- `comelit.open_door` public action where currently capability-enabled;
- `comelit_door_operation` result event from the shared Door runtime;
- `switch.comelit_entrance_camera`;
- `camera.comelit_entrance`;
- media active/remaining/listener diagnostics;
- one active intercom media session maximum;
- listener/media ownership safety;
- no automatic Door retry;
- protocol ACK is not physical Door-state proof.

No MVP work should be spent reimplementing the buttons.

## 3. MVP event model

The MVP exposes several HA lifecycle events. Event payloads must be safe, normalized and contain no credentials/raw protocol payload.

### 3.1 `comelit_ring`

Already implemented. This remains the root call event.

Required payload includes:

```text
event_id
timestamp
door: entrance | gate
source
kind=CALL_INIT
direction=DEVICE_TO_CLIENT
```

`event_id` is generated inside the integration and is the correlation key for snapshot/recording lifecycle artifacts.

### 3.2 `comelit_snapshot_updated`

New MVP lifecycle event.

Meaning: the integration has successfully replaced the latest retained JPEG for one active ring/media interaction.

Required payload:

```text
event_id
door
camera_entity
snapshot_path
timestamp
sequence
```

Rules:

- event emitted only after a complete JPEG is atomically available at `snapshot_path`;
- `sequence` starts at 1 per `event_id` and increases monotonically;
- no raw media/session identifiers;
- consumers may ignore intermediate events and use the current file at `snapshot_path`.

### 3.3 `comelit_recording_complete`

New MVP lifecycle event.

Meaning: bounded recording for the ring interaction has reached a terminal result and its retained artifact is known.

Required payload:

```text
event_id
door
recording_path
duration_target_seconds=20
duration_actual_seconds
state: completed | truncated | failed
timestamp
```

A completed event does not imply any Door action.

### 3.4 `comelit_door_operation`

Already implemented by the current shared Door runtime. Preserve its current safe semantics.

It represents protocol outcome, not physical Door-state proof.

### 3.5 Events not part of MVP

`comelit_ring_interaction` was introduced for the optional Telegram automation flow. It is not required for integration MVP acceptance.

Screenshot refresh must not depend on Telegram callbacks/messages.

## 4. Latest-snapshot mechanism

Snapshot refresh is an integration/HA-media capability, independent of any notification channel.

For an active entrance ring/media interaction:

```text
media active
-> obtain decodable frame
-> write JPEG to a stable per-event path
-> atomically replace prior JPEG
-> emit comelit_snapshot_updated
-> wait approximately 1 second
-> repeat while preview/recording remains active
```

Reference retained path:

```text
/media/comelit/rings/<event_id>/latest.jpg
```

Implementation rules:

1. Use the **same active media session**; never create one upstream media session per screenshot.
2. Target cadence is approximately 1 second.
3. Latest-only semantics: no frame queue.
4. At most one snapshot encode/write operation is in flight per interaction.
5. If one refresh takes longer than the target cadence, do not accumulate delayed work; the next cycle begins only after completion.
6. Replace the final file atomically where practical.
7. The final successful JPEG remains available after media teardown.
8. An early media failure leaves the last successful JPEG intact.
9. Snapshot refresh does not extend the absolute media-session deadline.
10. Snapshot mechanism has no Telegram code/dependency.

## 5. Recording for MVP

The historical target was 60 seconds. That is temporarily reduced for MVP because current upstream media stops around 30–35 seconds and R30H-E is deferred.

MVP recording target:

```text
20 seconds
```

On an entrance ring that enters the media path:

```text
ring
-> start/reuse one media session
-> start periodic latest-snapshot refresh
-> start one 20-second video recording from the same media session
-> retain the clip
-> emit comelit_recording_complete
-> tear media down when no longer needed
-> restore listener READY
```

Reference retained path:

```text
/media/comelit/rings/<event_id>/recording.mp4
```

Rules:

- target duration = 20 s;
- no audio recording requirement for MVP;
- no second upstream media session for recording;
- no automatic retry;
- recording must not require R30H-E;
- current ~30–35 s source lifetime is accepted as a known limitation;
- if media ends early or an explicit media teardown occurs, emit `state=truncated` with actual duration rather than hiding the result;
- retained files are not automatically deleted in MVP.

## 6. Door/Gate controls

Door/Gate buttons are existing functionality and are not a new MVP development item.

MVP must verify that existing controls still expose the intended semantic surfaces and that no media/snapshot/recording work regresses them.

Current capability gates remain authoritative. Do not fake Gate media or remove a fail-closed Gate actuation guard merely to satisfy MVP.

`comelit_door_operation` remains the operation-result event.

## 7. Unified MVP canary

The MVP is not split into Telegram/media and Door canaries.

After offline implementation and separate live authorization, one bounded end-to-end entrance canary should prove the integration in one scenario:

```text
listener READY
-> one real entrance ring
-> exactly one comelit_ring with event_id
-> one media session
-> latest.jpg appears and refreshes multiple times
-> comelit_snapshot_updated sequence advances
-> one retained recording targets 20 s
-> comelit_recording_complete state=completed and actual duration is acceptable
-> media teardown
-> listener READY again
-> exactly one existing entrance Door action
-> exactly one comelit_door_operation
-> no retry
-> final latest.jpg and recording.mp4 retained
```

For this first unified canary the Door action is performed **after the 20-second recording completes and media is torn down**, so it does not test unresolved early-Open concurrency semantics.

No Telegram send/edit/callback is part of this canary.

## 8. MVP acceptance gates

```text
RING_EVENT=PASS
RING_EVENT_ID=PASS
RING_DEDUP=PASS
SNAPSHOT_REFRESH=PASS
SNAPSHOT_REFRESH_TARGET_SECONDS=1
SNAPSHOT_LATEST_ONLY=PASS
SNAPSHOT_EVENT=PASS
FINAL_SNAPSHOT_RETAINED=PASS
RECORDING_TARGET_SECONDS=20
RECORDING_COMPLETE_EVENT=PASS
RECORDING_FILE_RETAINED=PASS
MEDIA_SINGLE_SESSION=PASS
MEDIA_TEARDOWN=PASS
LISTENER_READY_AFTER_MEDIA=PASS
EXISTING_BUTTONS_REGRESSION=PASS
DOOR_OPERATION_EVENT=PASS
DOOR_MAX_INVOCATIONS=1
AUTOMATIC_RETRY=false
TELEGRAM_REQUIRED=false
R30H_E_REQUIRED=false
```

## 9. Explicit non-goals

- Telegram send/edit/callback logic;
- `comelit_ring_interaction` as an MVP requirement;
- 60-second recording;
- R30H-E / periodic `0x001A` refresh;
- media lifetime >30–35 s;
- full-duplex conversation;
- audio recording;
- Frigate/go2rtc redesign;
- permanent camera session;
- automatic Door retry;
- claiming physical Door state from protocol ACK;
- removing Gate safety gates without independent proof.
