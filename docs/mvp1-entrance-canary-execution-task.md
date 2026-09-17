# Hermes execution task — Comelit MVP1 unified entrance canary

TASK_ID=`COMELIT-MVP1-ENTRANCE-CANARY`

MODE=`BOUNDED_LIVE_PRODUCTION_CANARY`

Companion contract: `docs/mvp1-entrance-canary-contract.md`

## 1. Roles

- Hermes = orchestrator only.
- Use one bounded Codex CLI context for semantic preflight review, live evidence interpretation, result classification and result-document authoring.
- Resume the same Codex context for ordinary analysis/test corrections inside this task.
- Hermes must not author executable repository code.
- The canary itself uses existing production integration/runtime paths; do not create ad-hoc protocol implementations.

## 2. Bootstrap

Fresh authenticated fetch and read:

1. private canonical context from `alexsudakov/llm-home-assistant-stack/services/dialog-service/project-context/comelit/PROJECT_CONTEXT.md`;
2. `docs/ha-integration-target-architecture.md`;
3. `docs/intercom-media-session-architecture.md`;
4. `docs/mvp-integration-v1-contract.md`;
5. `docs/mvp-integration-v1-offline-build-result.md`;
6. `docs/mvp1-entrance-canary-contract.md`;
7. this task.

Expected exact deploy SHA when task was created:

```text
1402a15254340317a4683b6b781024b23073eefd
```

If fresh `origin/main` is different, set `MAIN_MOVED=true`, do not deploy, and STOP for re-baselining. Do not silently substitute another SHA.

## 3. GitHub/auth rules

All Comelit GitHub operations remain token-authenticated without exposing token material.

On CT120 if Git access is required:

```text
credential store: /root/.config/git/comelit.credentials
mode: 600
remote: https://github.com/alexsudakov/comelit.git
repo-local credential.helper=store --file=/root/.config/git/comelit.credentials
credential.useHttpPath=true
```

Never print the credential file contents or token.

## 4. HA deployment mechanism

Use the established HA forced-command gateway only.

Before deploy:

- collect current deployed Comelit identity;
- collect current loaded/runtime identity if available;
- collect listener/media status;
- run HA integration/core check supported by the gateway.

Deploy exact SHA scoped only to `custom_components/comelit/**` through the existing integration-scoped deploy mechanism.

After deploy:

- verify deployed on-disk identity;
- run check again;
- determine whether the loaded modules are already the exact deployed revision.

If not loaded, perform at most one Comelit config-entry/integration reload using the already-approved gateway action.

Do not restart Home Assistant. If a full restart is required for exact code activation:

```text
RESULT=BLOCKED_HA_RESTART_REQUIRED
HA_RESTARTS=0
```

and STOP.

## 5. Pre-live phase

No physical/media actions until every pre-live gate in the companion contract passes.

Required read-only proof immediately before arm:

```text
DEPLOYED_SHA_MATCH=PASS
HA_CORE_CHECK=PASS
COMELIT_ACTIVATION=PASS
LISTENER_RUNNING=true
LISTENER_READY=true
LISTENER_LAST_ERROR=null
MEDIA_ACTIVE=false
RING_MEDIA_LIFECYCLE_ACTIVE=false
DOOR_ACTIONS=0
GATE_ACTIONS=0
RECORDING_TARGET_SECONDS=20
SNAPSHOT_REFRESH_TARGET_SECONDS=1
```

Codex returns one of:

```text
GO_ARM
STOP_<reason>
```

No live ring wait unless Codex returned `GO_ARM`.

## 6. Arm one real entrance ring

Emit a clear operator marker at the end of a concise status block:

```text
=== COMELIT MVP1 CANARY ARMED ===
EXPECTED_DOOR=entrance
MAX_LOGICAL_RINGS=1
MAX_MEDIA_SESSIONS=1
MAX_DOOR_ACTIONS=1
MAX_GATE_ACTIONS=0
RECORDING_TARGET_SECONDS=20
AUTOMATIC_RETRY=false
ACTION_REQUIRED=PRESS_ENTRANCE_CALL_ONCE
=== END COMELIT MVP1 CANARY ARMED ===
```

Then observe the production integration for one **real** new entrance CALL_INIT. No synthetic `hass.bus.fire`, test event or replay may substitute.

Use a bounded arm window. A default maximum of 10 minutes is acceptable if no shorter project-standard window is already canonical. If no real entrance ring arrives, cleanly disarm without media/Door side effects and classify `BLOCKED_NO_REAL_RING`.

## 7. Live observation

For the first accepted new entrance `event_id`, collect scalar/status evidence for:

```text
RING_EVENT_COUNT
RING_EVENT_ID
RING_DOOR
MEDIA_ACQUIRE_COUNT
MEDIA_ACTIVE_TRANSITIONS
SNAPSHOT_EVENT_COUNT
SNAPSHOT_SEQUENCE_FIRST
SNAPSHOT_SEQUENCE_LAST
SNAPSHOT_PATH
SNAPSHOT_FILE_EXISTS
SNAPSHOT_FILE_SIZE
RECORDING_EVENT_COUNT
RECORDING_STATE
RECORDING_TARGET_SECONDS
RECORDING_ACTUAL_SECONDS
RECORDING_PATH
RECORDING_FILE_EXISTS
RECORDING_FILE_SIZE
RECORDING_VIDEO_STREAM_PRESENT
RECORDING_PROBED_DURATION_SECONDS
MEDIA_RELEASE_COUNT
MEDIA_ACTIVE_AFTER
LISTENER_STATUS_AFTER_1
LISTENER_STATUS_AFTER_2
```

Do not commit or print raw media bytes.

Safe probes may inspect file/container metadata only.

Require at least two snapshot events with increasing sequence for PASS.

Require one recording event with `state=completed` and probed video duration `18.0 <= duration <= 24.0` for PASS.

No second media session and no recording retry.

## 8. Teardown gate before Door

After recording terminal event, prove:

```text
MEDIA_ACTIVE=false
RING_MEDIA_LIFECYCLE_ACTIVE=false
LISTENER_RUNNING=true
LISTENER_READY=true
LISTENER_LAST_ERROR=null
```

twice in two bounded consecutive observations.

Only after this gate may Door action occur.

Codex must explicitly return:

```text
GO_DOOR
```

or

```text
STOP_<reason>
```

before physical Door action.

## 9. Door action

If and only if Codex returned `GO_DOOR`:

- execute exactly one existing semantic production entrance Door action;
- use the current HA integration/button/service path, not CT120 raw protocol code;
- Gate action count must remain zero;
- do not retry on timeout, failed ACK or unknown result.

Collect exactly one matching `comelit_door_operation` if emitted and record:

```text
operation_id
door
state
protocol_acked
write_count
door_specific_ack_proven
automatic_retry_allowed
physical_effect_asserted
```

Never convert protocol ACK to a claim that the physical door opened.

## 10. Cleanup

At the end of every terminal path:

- no canary-owned media task remains;
- media inactive;
- persistent listener restored/healthy if runtime reached media phase;
- Door count <=1;
- Gate count =0;
- no full HA restart;
- no retry/second session;
- no R30H-E behavior;
- leave retained MVP files in `/media/comelit/rings/<event_id>/` if they were produced.

Do not delete the final JPEG or MP4 as part of canary cleanup.

## 11. Result and repository finalization

Create `docs/mvp1-entrance-canary-result.md` with:

- exact source/deployed identity;
- activation mechanism (no reload vs one Comelit reload);
- all pre-live gates;
- accepted event id in safely redacted/normal UUID form;
- snapshot scalar evidence;
- recording scalar/container evidence;
- teardown/listener evidence;
- Door operation safe fields;
- explicit forbidden-action counts;
- limitations and any uncertain evidence.

Commit/push result doc on a bounded result branch and attempt PR creation. If PR creation is forbidden by PAT, return branch + exact remote head.

Do not make executable-code corrections inside this live canary. If a code defect is discovered, classify/record it and STOP; fix it in a new offline child.

## 12. Required final block

Print only this final scalar block at the very end of the Hermes task output:

```text
=== COMELIT MVP1 ENTRANCE CANARY ===
TASK_ID=COMELIT-MVP1-ENTRANCE-CANARY
EXPECTED_SHA=1402a15254340317a4683b6b781024b23073eefd
ACCEPTED_MAIN_SHA=<sha>
MAIN_MOVED=false|true
DEPLOYED_SHA_MATCH=PASS|FAIL|NOT_REACHED
HA_CORE_CHECK=PASS|FAIL|NOT_REACHED
COMELIT_RELOADS=0|1
HA_RESTARTS=0
PRELIVE=PASS|FAIL
REAL_ENTRANCE_RING_COUNT=0|1
RING_EVENT_ID=<uuid|NONE>
MEDIA_SESSION_COUNT=0|1
SNAPSHOT_EVENT_COUNT=<n>
SNAPSHOT_SEQUENCE_FIRST=<n|NONE>
SNAPSHOT_SEQUENCE_LAST=<n|NONE>
FINAL_SNAPSHOT_RETAINED=PASS|FAIL|NOT_REACHED
RECORDING_COUNT=0|1
RECORDING_TARGET_SECONDS=20
RECORDING_STATE=completed|truncated|failed|NOT_REACHED
RECORDING_ACTUAL_SECONDS=<float|NONE>
RECORDING_PROBED_DURATION_SECONDS=<float|NONE>
RECORDING_VIDEO_STREAM_PRESENT=PASS|FAIL|NOT_REACHED
MEDIA_TEARDOWN=PASS|FAIL|NOT_REACHED
LISTENER_READY_AFTER_MEDIA=PASS|FAIL|NOT_REACHED
DOOR_ACTIONS=0|1
GATE_ACTIONS=0
DOOR_OPERATION_EVENT=PASS|FAIL|NOT_REACHED
DOOR_PROTOCOL_ACKED=true|false|UNKNOWN|NOT_REACHED
PHYSICAL_EFFECT_ASSERTED=false
AUTOMATIC_RETRY=false
SECOND_MEDIA_SESSION=false
R30H_E_EXECUTED=false
ROLLBACK_EXECUTED=false
RESULT=<result class>
RESULT_BRANCH=<branch|none>
RESULT_REMOTE_HEAD=<sha|none>
RESULT_PR=<number|none>
=== END COMELIT MVP1 ENTRANCE CANARY ===
```

After this block: STOP. No second canary is authorized.
