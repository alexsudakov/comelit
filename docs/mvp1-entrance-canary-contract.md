# Comelit MVP1 unified entrance canary — live contract

Status: **LIVE AUTHORIZED by user**  
Authorization date: 2026-09-17  
Canonical implementation base: `1402a15254340317a4683b6b781024b23073eefd`

User-authorized scope, verbatim in meaning:

```text
deploy exact current main into Home Assistant;
reload only the Comelit integration if needed;
one real entrance ring;
one media session;
verify snapshot refresh and one 20-second recording;
then teardown and prove listener READY;
then exactly one entrance Door action;
Gate actions = 0;
retry = 0;
full Home Assistant restart is forbidden without separate approval.
```

This contract is the complete side-effect boundary for the canary.

## 1. Objective

Prove the integration MVP end-to-end in production Home Assistant in one bounded entrance scenario:

```text
exact-main deploy
-> Comelit integration activation
-> listener READY
-> arm one entrance-ring observation
-> one real entrance ring
-> one comelit_ring(event_id)
-> exactly one entrance media session
-> latest.jpg created and refreshed multiple times
-> comelit_snapshot_updated sequence advances
-> exactly one retained recording targeting 20 s
-> comelit_recording_complete
-> media teardown
-> listener READY
-> exactly one entrance Door action
-> exactly one comelit_door_operation
-> STOP
```

Telegram is not part of this canary.

## 2. Hard limits

```text
DEPLOY_MAX=1
COMELIT_RELOAD_MAX=1
HA_RESTART_MAX=0
ENTRANCE_RING_LOGICAL_MAX=1
MEDIA_SESSION_MAX=1
RECORDING_MAX=1
RECORDING_TARGET_SECONDS=20
DOOR_ACTION_MAX=1
GATE_ACTION_MAX=0
AUTOMATIC_RETRY=false
SECOND_MEDIA_SESSION=false
R30H_E_EXECUTED=false
```

If any phase fails, stop. Do not retry that phase through a second media session, second Door attempt, second deploy, second reload, or alternate protocol path.

## 3. Access boundaries

### Home Assistant

Use only the established forced-command HA gateway. No arbitrary HA shell.

Allowed:

```text
status
logs
check
deploy exact repository SHA scoped to custom_components/comelit/**
reload only the Comelit config entry/integration, at most once, only if needed for activation
read Comelit entities/events/diagnostics
read/verify retained /media/comelit/rings/<event_id>/ artifacts through already-approved integration-scoped mechanisms
```

Forbidden:

```text
full Home Assistant restart
Supervisor reboot
host reboot
changes outside custom_components/comelit/**
unrelated entity/service mutations
Telegram mutations
```

A full HA restart requires new explicit user approval and is not implied by this contract.

### CT120 / Comelit live support

If diagnostic support is necessary, use the already-established Hermes -> restricted SSH route to CT120. It may inspect Comelit-specific processes, ports, logs and bounded temporary task artifacts. It must not alter firewall/networking, reboot CT120, stop unrelated services, expose credentials or create a second media session.

CT120 must not become a permanent production runtime.

## 4. Deployment contract

1. Fresh authenticated fetch `origin/main`.
2. Require accepted main to equal the intended exact deploy SHA. If main has advanced unexpectedly, stop before deploy and report `MAIN_MOVED=true`; do not silently deploy another revision.
3. Verify clean exact source and CI/safety evidence for the SHA.
4. Pre-deploy HA `check` through the forced gateway.
5. Deploy only `custom_components/comelit/**` from exact SHA using the established integration-scoped deployment path.
6. Verify deployed source identity/check output.
7. If the currently loaded Python modules already match the deployed exact main, do not reload unnecessarily.
8. Otherwise perform at most one Comelit integration/config-entry reload.
9. Full HA restart is forbidden. If activation requires a full restart, classify `BLOCKED_HA_RESTART_REQUIRED` and STOP.
10. No automatic rollback is authorized by this contract. Preserve pre-deploy identity/evidence and report if rollback becomes necessary.

## 5. Pre-live gates

Before arming the ring:

```text
DEPLOYED_SHA_MATCH=PASS
HA_CORE_CHECK=PASS
COMELIT_IMPORT_OR_ACTIVATION=PASS
HA_RESTARTS=0
LISTENER_RUNNING=true
LISTENER_READY=true
LISTENER_LAST_ERROR=null
MEDIA_ACTIVE=false
RING_MEDIA_LIFECYCLE_ACTIVE=false
ENTRANCE_DOOR_BASELINE_ACTIONS=0
GATE_BASELINE_ACTIONS=0
RECORDING_TARGET_SECONDS=20
SNAPSHOT_REFRESH_TARGET_SECONDS=1
```

Also verify an HA-allowed media path is available for the actual generated target under `/media/comelit/rings/<event_id>/` once an event id exists. Do not pre-create a fake event id that could collide with the real ring.

If any pre-live gate fails, STOP before any physical ring/media/Door action.

## 6. Ring arming

After all gates pass, enter an explicit `ARMED_FOR_ONE_ENTRANCE_RING` state.

The canary must accept exactly one new logical `comelit_ring` where:

```text
door=entrance
kind=CALL_INIT
```

CALL_INIT retransmits belonging to the same logical event are not additional rings.

A Gate ring does not consume or convert into the entrance canary and must not start Gate media or Gate action.

A second distinct entrance ring after the first accepted event must not start a second media lifecycle and must not extend the canary.

The executor should surface a clear ARMED marker so the user/operator can physically trigger one entrance call. No synthetic HA event may substitute for this proof.

## 7. Media and snapshot acceptance

For the accepted `event_id`:

- exactly one `RingMediaCoordinator` lifecycle may acquire media;
- exactly one upstream entrance media session;
- no periodic `0x001A` refresh and no R30H-E behavior;
- `latest.jpg` must become a valid non-empty JPEG;
- at least two successful `comelit_snapshot_updated` events must be observed;
- snapshot `sequence` starts at 1 and increases monotonically;
- each snapshot event must carry the same `event_id` and `door=entrance`;
- the retained `latest.jpg` must exist after teardown;
- latest-only semantics: no evidence of multiple queued snapshot workers;
- snapshot refresh target remains approximately 1 second, but exact wall-clock jitter is observational and not a failure by itself.

Do not retain raw RTP/H264/audio/PCAP as canary artifacts.

## 8. Recording acceptance

For the same `event_id` and same media session:

```text
RECORDING_TARGET_SECONDS=20
RECORDING_COUNT=1
```

Require one `comelit_recording_complete` with:

```text
event_id=<accepted event>
door=entrance
duration_target_seconds=20
state=completed
```

For PASS, the retained final MP4 must:

- exist;
- be non-empty;
- be recognized as an MP4/media file by an available safe probe;
- contain a video stream;
- have measured duration reasonably consistent with a 20-second target.

Use a practical acceptance interval of `>=18.0 s` and `<=24.0 s` for this first live proof because HA Stream writes segment-bounded recordings. Record the exact measured duration.

If state is `truncated` or `failed`, or the file is unusable, classify the canary as failed/inconclusive according to evidence. Do not start a second recording or media session.

No audio requirement for MVP1.

## 9. Teardown and listener gate

After recording reaches its terminal event:

- snapshot lifecycle stops;
- media coordinator releases its lease;
- HA Stream provider closes;
- production media becomes inactive;
- persistent listener resumes.

Before Door action require two consecutive status observations, separated by a short bounded interval, both showing:

```text
listener_running=true
listener_ready=true
listener_last_error=null
media_active=false
ring_media_lifecycle_active=false
```

If listener READY is not proven, Door action is forbidden and the canary stops.

## 10. Door action

Only after all preceding gates pass:

- perform exactly one existing semantic entrance Door action through the production HA integration path;
- Gate actions remain zero;
- no retry, even on timeout or unknown outcome;
- require exactly one `comelit_door_operation` corresponding to the attempt;
- record protocol result fields;
- do not infer physical opening solely from protocol ACK;
- `physical_effect_asserted=false` unless independently observed by a human/physical sensor already present and explicitly part of evidence.

A Door timeout/unknown protocol outcome is terminal for this canary. No second press.

## 11. Failure handling

Any of the following stops the canary immediately with no retry:

- exact deployed SHA mismatch;
- HA check failure;
- activation would require full HA restart;
- listener not READY before ring;
- more than one logical entrance ring accepted;
- more than one media session/acquire;
- snapshot lifecycle duplicate/concurrency violation;
- recording state not completed;
- recording file missing/unusable/outside accepted duration;
- teardown not proven;
- listener READY not proven after media;
- any Gate action;
- any second Door attempt;
- R30H-E/repeat-0x001A behavior observed or enabled.

Do not automatically rollback, restart HA, retry the canary, or start a second session.

## 12. Result classes

```text
PASS_MVP1_ENTRANCE_CANARY
BLOCKED_HA_RESTART_REQUIRED
BLOCKED_PRELIVE_GATE
BLOCKED_NO_REAL_RING
FAIL_SNAPSHOT
FAIL_RECORDING
FAIL_TEARDOWN
FAIL_LISTENER_RESTORE
FAIL_DOOR_OPERATION
INCONCLUSIVE
```

## 13. Required result document

Create:

```text
docs/mvp1-entrance-canary-result.md
```

Repository writes after live execution are limited to the result/evidence document and any strictly necessary non-executable evidence summary. No raw media, credentials, PCAP or private identifiers are committed.

After commit/push/PR attempt: STOP. No second canary is authorized.
