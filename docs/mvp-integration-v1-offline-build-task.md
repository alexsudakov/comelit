# Comelit Home Assistant Integration MVP v1 — offline build task

TASK_ID=`COMELIT-MVP1-INTEGRATION-OFFLINE-BUILD`

MODE=`OFFLINE_ONLY`

Companion contract: `docs/mvp-integration-v1-contract.md`

## 1. Objective

Implement the integration-only MVP delta after the Telegram scope correction:

```text
comelit_ring
-> one entrance media session
-> latest JPEG refresh about every 1 s
-> comelit_snapshot_updated events
-> retained 20 s video recording
-> comelit_recording_complete event
-> safe media teardown
-> listener READY
```

Preserve existing buttons/Door behavior and `comelit_door_operation`.

Telegram is outside this task and outside MVP acceptance.

## 2. Required source audit before writing code

Codex must first inspect fresh accepted `main` and report which parts are already implemented versus missing for:

```text
comelit_ring
camera.comelit_entrance
switch.comelit_entrance_camera
ComelitMediaSessionManager
camera snapshot path
HA Stream recording capability
comelit_door_operation
existing entrance/gate buttons
```

It must also inspect the merged PR #155 artifacts and explicitly distinguish reusable generic integration changes from optional Telegram-only artifacts.

Do not remove or refactor working Telegram example material merely because it is no longer MVP scope unless it directly conflicts with the integration implementation.

## 3. Required implementation

### 3.1 Snapshot lifecycle

Add an integration-owned bounded latest-snapshot lifecycle correlated to `comelit_ring.event_id`.

Required behavior:

- one stable per-event path: `/media/comelit/rings/<event_id>/latest.jpg` or an HA-valid equivalent derived only from safe `event_id`;
- reuse exactly one active entrance media session;
- capture first decodable JPEG as soon as practical;
- refresh target ~1 s while recording/preview lease remains active;
- sequential latest-only loop, no queue/backlog;
- atomically replace final JPEG where practical;
- preserve last successful JPEG after teardown;
- emit `comelit_snapshot_updated` after each successful replacement;
- sequence starts at 1 and increases monotonically per event;
- no secrets/raw session identifiers in event/path;
- no Telegram dependency.

### 3.2 Recording lifecycle

Implement one retained video recording per entrance ring media lifecycle.

Target duration:

```text
20 seconds
```

Requirements:

- recording uses the same existing media session/HA Stream path;
- no second upstream Comelit session;
- no automatic retry;
- no audio-recording requirement;
- store under `/media/comelit/rings/<event_id>/recording.mp4` or equivalent HA-valid safe path;
- if the recording reaches target, emit `comelit_recording_complete(state=completed)`;
- if media ends explicitly/early, emit `state=truncated` and safe actual duration;
- if no usable recording can be produced, emit `state=failed` without crashing listener restoration;
- retain file; no automatic deletion in MVP.

### 3.3 Event contracts

Implement constants/schema/tests for:

```text
comelit_snapshot_updated
comelit_recording_complete
```

`comelit_snapshot_updated` minimum payload:

```text
event_id
door
camera_entity
snapshot_path
timestamp
sequence
```

`comelit_recording_complete` minimum payload:

```text
event_id
door
recording_path
duration_target_seconds=20
duration_actual_seconds
state=completed|truncated|failed
timestamp
```

Preserve existing `comelit_ring` and `comelit_door_operation` semantics unchanged unless a minimal compatibility fix is required and separately justified.

### 3.4 Trigger/orchestration placement

Prefer the lifecycle to be owned by the Comelit integration rather than by Telegram/example automation.

The exact internal placement is for Codex to choose after source audit, but it must satisfy:

- ring listener itself must not be blocked for 20 seconds by synchronous recording work;
- all long work runs as bounded background tasks associated with the config entry/runtime lifecycle;
- unload cancels/tears down cleanly;
- one active ring-media lifecycle at a time;
- duplicate CALL_INIT does not create duplicate recording/snapshot lifecycle;
- failure to start media emits/records a safe terminal result and returns listener ownership appropriately.

### 3.5 Existing controls

Do not reimplement buttons.

Add regression tests proving current entrance/gate button/entity contracts remain unchanged and current capability guards are preserved.

`comelit_door_operation` remains exactly once per completed Door attempt.

## 4. Telegram exclusion

For this task:

```text
TELEGRAM_REQUIRED=false
TELEGRAM_CODE_CHANGED=false
TELEGRAM_LIVE_SENT=false
```

Do not:

- add Telegram dependencies to `custom_components/comelit`;
- use `telegram_bot.*` in the new MVP integration lifecycle;
- make `comelit_ring_interaction` part of acceptance;
- test Telegram callbacks/messages as an MVP gate.

The existing optional example under `examples/home-assistant/packages/` may remain untouched.

## 5. 20-second recording and known source limit

R30H-E is not required.

The implementation must be designed around the presently usable short session and target only 20 s recording.

No attempt to solve or mask the ~30–35 s media lifetime problem is authorized.

```text
R30H_E_EXECUTED=false
REPEAT_001A_CHANGED=false
```

## 6. Offline test gates

At minimum prove:

```text
RING_EVENT_CONTRACT_UNCHANGED=PASS
RING_EVENT_ID_CORRELATION=PASS
RING_DEDUP_UNCHANGED=PASS
SNAPSHOT_LOOP_SINGLE_SESSION=PASS
SNAPSHOT_FIRST_FRAME=PASS
SNAPSHOT_REFRESH_TARGET_SECONDS=1
SNAPSHOT_REFRESH_SERIAL_NO_QUEUE=PASS
SNAPSHOT_SEQUENCE_MONOTONIC=PASS
SNAPSHOT_EVENT_SAFE_PAYLOAD=PASS
SNAPSHOT_FINAL_FILE_RETAINED=PASS
RECORDING_TARGET_SECONDS=20
RECORDING_SINGLE_SESSION=PASS
RECORDING_COMPLETE_EVENT_COMPLETED=PASS
RECORDING_COMPLETE_EVENT_TRUNCATED=PASS
RECORDING_COMPLETE_EVENT_FAILED=PASS
RECORDING_SAFE_PATH=PASS
MEDIA_TEARDOWN_AFTER_RECORDING=PASS
LISTENER_RESTORE_CONTRACT=PASS
DUPLICATE_RING_NO_SECOND_LIFECYCLE=PASS
UNLOAD_CLEANUP=PASS
DOOR_OPERATION_EVENT_UNCHANGED=PASS
EXISTING_BUTTONS_REGRESSION=PASS
GATE_CAPABILITY_GUARDS_UNCHANGED=PASS
AUTOMATIC_RETRY=false
TELEGRAM_REQUIRED=false
R30H_E_EXECUTED=false
```

Use behavioral unit tests where feasible; do not settle for string grep alone when Python behavior can be exercised offline.

## 7. Allowed write scope

Minimal changes among:

```text
custom_components/comelit/const.py
custom_components/comelit/runtime.py
custom_components/comelit/camera.py
custom_components/comelit/media_session.py
custom_components/comelit/media_diagnostics.py
custom_components/comelit/__init__.py
tests/**
safety-poc/tests/**
docs/mvp-integration-v1-*.md
```

A new focused integration module such as `ring_media.py` / `media_capture.py` is allowed if Codex demonstrates that this keeps responsibilities cleaner than expanding `runtime.py` or `camera.py`.

Do not change:

```text
custom_components/comelit/native/**
custom_components/comelit/media_transport.py
safety-poc/research/media/v1/entrance_p116_r27_repeat_001a_transform.py
safety-poc/research/media/v1/ct120_run_p116_r27_repeat_001a_live.sh
R30H-E executable research artifacts
```

unless an offline compile/test blocker proves a minimal non-protocol correction is necessary; such a deviation must be called out explicitly before commit.

## 8. Forbidden side effects

This child is strictly offline:

```text
COMELIT_LIVE_EXECUTED=false
PHYSICAL_CAMERA_ACTIVATED=false
HA_DEPLOYED=false
HA_RELOADED=false
HA_RESTARTED=false
PRODUCTION_LISTENER_TOUCHED=false
DOOR_ACTIONS=0
GATE_ACTIONS=0
TELEGRAM_LIVE_SENT=false
RAW_MEDIA_CAPTURED=false
R30H_E_EXECUTED=false
```

No physical Door/Gate action is authorized.

## 9. Executor model

- Hermes = orchestrator only.
- One bounded Codex CLI context owns analysis, implementation, tests, corrections and result document.
- Ordinary test/implementation defects inside scope are fixed by resuming the same Codex session.
- Hermes does not write executable code.
- Fresh authenticated fetch from `origin/main`.
- CT120 GitHub access, if genuinely needed for offline-only inspection/build, must use `/root/.config/git/comelit.credentials`, mode 600, repo-local credential helper, credential-free remote.
- Prefer CT122-only execution if no CT120-specific build dependency exists.

## 10. Required result

Create:

```text
docs/mvp-integration-v1-offline-build-result.md
```

Result classes:

```text
PASS_OFFLINE_INTEGRATION_MVP_READY
BLOCKED_RECORDING_API
BLOCKED_SNAPSHOT_API
FAIL_OFFLINE_INTEGRATION_MVP
INCONCLUSIVE
```

Required final block:

```text
=== COMELIT MVP1 INTEGRATION OFFLINE BUILD ===
TASK_ID=COMELIT-MVP1-INTEGRATION-OFFLINE-BUILD
BASE_SHA=<actual accepted main>
RING_EVENT=PASS|FAIL
SNAPSHOT_REFRESH=PASS|FAIL
SNAPSHOT_REFRESH_TARGET_SECONDS=1
SNAPSHOT_EVENT=PASS|FAIL
FINAL_SNAPSHOT_RETENTION=PASS|FAIL
RECORDING_TARGET_SECONDS=20
RECORDING_IMPLEMENTATION=PASS|FAIL
RECORDING_COMPLETE_EVENT=PASS|FAIL
MEDIA_SINGLE_SESSION=PASS|FAIL
MEDIA_TEARDOWN=PASS|FAIL
LISTENER_RESTORE_CONTRACT=PASS|FAIL
DOOR_OPERATION_EVENT=PASS|FAIL
EXISTING_BUTTONS_REGRESSION=PASS|FAIL
GATE_CAPABILITY_GUARDS_UNCHANGED=true|false
TELEGRAM_REQUIRED=false
TELEGRAM_CODE_CHANGED=false
R30H_E_EXECUTED=false
COMELIT_LIVE_EXECUTED=false
HA_DEPLOYED=false
HA_RELOADED=false
HA_RESTARTED=false
DOOR_ACTIONS=0
GATE_ACTIONS=0
BRANCH=<branch>
REMOTE_HEAD=<sha|NOT_PUSHED>
PR=<number|none>
RESULT=<class>
=== END COMELIT MVP1 INTEGRATION OFFLINE BUILD ===
```

After this child: STOP. The next live step, if offline result is ready, is one **unified** bounded integration canary with one entrance ring, snapshot refresh, 20 s recording, media teardown/listener restore, then exactly one entrance Door action. No Telegram is part of that canary.
