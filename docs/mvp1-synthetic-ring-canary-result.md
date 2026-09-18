# Comelit MVP1 synthetic entrance-ring canary result

## 1. Task identity and summary

```text
TASK_ID=COMELIT-MVP1-SYNTHETIC-RING-CANARY-ROUND2
MODE=BOUNDED_SYNTHETIC_TRIGGER_LIVE_RUN
DATE_UTC=2026-09-18
ACCEPTED_MAIN_SHA=a5fa10b42cfc7dc7cd6a2add37d01c82482f43aa
ACCEPTED_COMPONENT_TREE=5683dbb1a8a4d428ebb2e0f99cbd867352f8e3f9
PREVIOUS_DEPLOYED_SHA=204ec3aa6cf7c6e8057b2336094675e7353c24f1
DEPLOYED_SHA=a5fa10b42cfc7dc7cd6a2add37d01c82482f43aa
PAYLOAD_BYTES=6183999
PAYLOAD_SHA256=bc66bc7ef74c71ce8926b2f05a6007ee1ba5236efee79b5e0668a0bb1d8b9cd7
PAYLOAD_MEMBERS=55
PAYLOAD_OUTSIDE_MEMBERS=0
PAYLOAD_GATES=GZIP_TEST=PASS PAX_HEADERS=0 TYPE_FLAG_BYTE156=53 MAGIC257=ustar
RESULT=PASS_MVP1_SYNTHETIC_RING_CANARY
```

Один authorized live round выполнен. Accepted main был deployed, Home Assistant был один раз перезапущен по `USER_APPROVED`, затем один synthetic entrance ring прошел через media, snapshot, recording и teardown без Door/Gate actions.

## 2. Authorization and hard limits

```text
DEPLOY_COUNT=1
HA_RELOADS=0
HA_RESTARTS=1
SYNTHETIC_TRIGGER_COUNT=1
SYNTHETIC_RING_COUNT=1
RING_EVENT_COUNT=1
MEDIA_SESSION_COUNT=1
SECOND_MEDIA_SESSION=false
RECORDING_COUNT=1
SECOND_RECORDING=false
RECORDING_TARGET_SECONDS=20
DOOR_ACTIONS=0
GATE_ACTIONS=0
AUTOMATIC_RETRY=false
SECOND_TRIGGER=false
HAOS_REBOOT=0
SUPERVISOR_REBOOT=0
VM_REBOOT=0
CT120_REBOOT=0
R30H_E_EXECUTED=false
```

Метод наблюдения: HA forced-command gateway (`status`, `check`, `deploy`, `restart USER_APPROVED`, `logs-follow`), CT120 dispatch verbs (`comelit-ha-ring-test-status`, `comelit-ha-ring-test-simulate-entrance-ring`) и webhook `comelit-ha-ring-test-control-v1` с CT120 `local_only`.

CT120 wrapper в этом раунде не менялся:

```text
CT120_DISPATCH_SHA256=5c082fe54e67d78cb8c9443753663e7592940f0e5850193c6888bbb405146dd7
CT120_RING_RUNTIME_SHA256=428a58b1ff06c0644c95c7acddb6ee7e0cd074813e8b8528161d2f58c3d83eb5
```

## 3. Result class and verdict

```text
RESULT_CLASS=PASS_MVP1_SYNTHETIC_RING_CANARY
```

Доказано в этом round:

- `RING_EVENT=PASS`: один `CALL_INIT` ring event с `event_id=ed9e81af-6e3e-4f08-a514-55012a407a0f`.
- `MEDIA_SINGLE_SESSION=PASS`: ровно одна media session, `MEDIA_SESSION_COUNT=1`, `SECOND_MEDIA_SESSION=false`.
- `P78_RTPC_SIGNALING_RESULT=PASS`.
- `P80_VIDEO_RTP_FORWARDING=PASS`, `P116_VIDEO_COUNT=1007`.
- `P80_AUDIO_RTP_FORWARDING=PASS`, `P116_AUDIO_COUNT=1067`.
- `SNAPSHOT_REFRESH=PASS`: 19 декодируемых JPEG snapshot updates с cadence около 1 s.
- `RECORDING_COMPLETE_EVENT=PASS`: `state=completed`, `duration_actual_seconds=21.287`.
- `MEDIA_TEARDOWN=PASS`: два teardown observation показывают `ring_media.running=false` и `active_event_id=null`.
- `LISTENER_READY_AFTER_MEDIA=PASS`: OBS1 и OBS2 показывают `running=true`, `listener_ready=true`, `last_error=null`.
- `DOOR_ACTIONS=0`, `GATE_ACTIONS=0`.

Осталось `PENDING_OPERATOR_RELAY`, не как причина inconclusive, а как restricted-surface metadata gap:

```text
FINAL_LATEST_JPG_SIZE_SHA256=PENDING_OPERATOR_RELAY
RECORDING_MP4_SIZE=PENDING_OPERATOR_RELAY
RECORDING_PROBED_DURATION_SECONDS=PENDING_OPERATOR_RELAY
RECORDING_VIDEO_STREAM_PRESENT=PENDING_OPERATOR_RELAY
```

Доступные производные закрывают MVP acceptance window: `RECORDING_FILE_EXISTS=true` и `SIZE>0` следуют из `state=completed`; `duration_actual_seconds=21.287` находится в expected 18.0-24.0 s window.

## 4. Accepted main, deploy, and payload identity

```text
ACCEPTED_MAIN_SHA=a5fa10b42cfc7dc7cd6a2add37d01c82482f43aa
ACCEPTED_COMPONENT_TREE=5683dbb1a8a4d428ebb2e0f99cbd867352f8e3f9
PREVIOUS_DEPLOYED_SHA=204ec3aa6cf7c6e8057b2336094675e7353c24f1
DEPLOYED_SHA=a5fa10b42cfc7dc7cd6a2add37d01c82482f43aa
DEPLOY_UTC=2026-09-18T12:36:00Z
DEPLOY=PASS
HA_RESTARTED_BY_DEPLOY=NO
```

Payload identity:

```text
PAYLOAD_BYTES=6183999
PAYLOAD_SHA256=bc66bc7ef74c71ce8926b2f05a6007ee1ba5236efee79b5e0668a0bb1d8b9cd7
PAYLOAD_MEMBERS=55
PAYLOAD_OUTSIDE_MEMBERS=0
GZIP_TEST=PASS
PAX_HEADERS=0
TYPE_FLAG_BYTE156=53
MAGIC257=ustar
```

## 5. PHASE A - pre-deploy gate

Pre-deploy gates before deploy:

```text
HA_CORE_CHECK=PASS
MEDIA_ACTIVE=false
RING_MEDIA_LIFECYCLE_ACTIVE=false
LISTENER_RUNNING=true
LISTENER_READY=true
LISTENER_LAST_ERROR=null
DOOR_ACTIONS=0
GATE_ACTIONS=0
```

## 6. PHASE B - deploy

Timeline, UTC:

```text
12:36:00 deploy a5fa10b4 -> DEPLOY=PASS HA_RESTARTED=NO
12:36:0x status -> DEPLOYED_SHA=a5fa10b4
12:36:0x check -> HA_CORE_CHECK=PASS
```

Deploy не вызвал HA restart. Единственный restart в round был отдельным `restart USER_APPROVED`.

## 7. PHASE C - restart and activation evidence

```text
12:36:05 restart USER_APPROVED -> HA_CORE_RESTART_REQUESTED=true
HA_RESTARTS=1
HA_RELOADS=0
```

Post-restart activation:

```text
HA_CORE_CHECK=PASS
DEPLOYED_SHA=a5fa10b4
LISTENER_RUNNING=true
LISTENER_READY=true
LAST_ERROR=null
snapshot_event_count=0
recording_event_count=0
recording_result=null
reconnect_count=0
```

Capture markers:

```text
entity_id=camera.comelit_entrance, old_state=None x1
Comelit ring listener READY for persistent 3300s cycle x1
```

## 8. PHASE D - pre-trigger readiness

Перед trigger listener был running и ready, last error отсутствовал, ring media counters были reset:

```text
LISTENER_RUNNING=true
LISTENER_READY=true
LAST_ERROR=null
snapshot_event_count=0
recording_event_count=0
recording_result=null
reconnect_count=0
DOOR_ACTIONS=0
GATE_ACTIONS=0
```

## 9. PHASE E - single synthetic trigger

```text
T0=2026-09-18T12:36:06Z
T1=2026-09-18T12:36:07Z
ACTION=simulate_entrance_ring
OK=true
RUNNING=true
LISTENER_READY=true
RING_OBSERVED=true
DOOR=entrance
SOURCE=synthetic_test
KIND=CALL_INIT
DIRECTION=DEVICE_TO_CLIENT
EVENT_ID=ed9e81af-6e3e-4f08-a514-55012a407a0f
LAST_ERROR=null
P13_EXECUTED=false
P14_EXECUTED=false
PHYSICAL_DOOR_ACTION=false
NETWORK_DOOR_ACTION_PERFORMED=false
```

Log marker:

```text
2026-09-18T12:36:07.042Z WARNING [custom_components.comelit.runtime]
Synthetic Comelit entrance ring emitted for bounded test:
event_id=ed9e81af-6e3e-4f08-a514-55012a407a0f
```

Это штатное synthetic-ring уведомление для bounded test, не defect.

## 10. PHASE F - startup ordering proof for PR #165

Startup timeline:

```text
12:36:06 trigger
12:36:07.042 synthetic ring emitted
12:36:17.948 Comelit entrance media session ACTIVE
12:36:39.237 recording_result timestamp completed
12:36:39.408 Comelit entrance media transport completed
```

Negative probes in the observation window:

```text
stream_unavailable=0
local_sdp_ready_timeout=0
media_native_binary_sha256_mismatch=0
media_start_failed=0
ERROR ... [custom_components.comelit...]=0
WARNING ... [custom_components.comelit...]=1
```

The one warning is the expected synthetic-ring notification above.

Derived PR #165 gates:

```text
LOCAL_SDP_READY_AFTER_MEDIA_ACTIVE=PASS (DERIVED)
MEDIA_MANAGER_ACTIVE_IMPLIES_SDP_READY=PASS (DERIVED)
```

`local_sdp_ready` itself is not exposed directly in the approved read-only surface; `extra_state_attributes` for the camera do not include that field. The derived proof is behavioral and constructive: before the fix, the first provider call after ACTIVE observed `local_sdp_ready=false`, returned `stream_unavailable`, and recording failed in about 0.002-0.007 s. In this round snapshots advanced from sequence 1 to 19 and recording ran for `21.287` s to `state=completed`, so SDP was ready before the manager became ACTIVE for ring media.

## 11. PHASE G - media and HA Stream evidence

Media / RTP markers:

```text
P80_MEDIA_ACTIVE=true
P78_RTPC_SIGNALING_RESULT=PASS
P80_VIDEO_RTP_FORWARDING=PASS
P80_AUDIO_RTP_FORWARDING=PASS
P116_VIDEO_COUNT=1007
P116_AUDIO_COUNT=1067
MEDIA_SESSION_ACTIVE_LINES=1
TRANSPORT_COMPLETED_LINES=1
media_active=True recorder samples=46
video_last_packet_age_seconds=0.2..1.4
session lifetime ACTIVE -> transport completed=21.460 s
```

`ha_stream_created=false` и `hls_provider_present=false` в recorder dumps для `camera.comelit_entrance` относятся к stream самой camera entity (`camera.py::async_create_stream`), который поднимается только при открытии camera view в UI. Ring path использует собственный `HAStreamMediaProvider` Stream, и этот объект не зеркалируется в camera entity attributes.

Отсутствие `ha_stream_created=true` у camera entity не означает отсутствие HA Stream в ring path. Ring-path HA Stream доказан конструктивно и поведенчески: 19 декодируемых JPEG snapshots означают, что `Stream.async_get_image()` отдавал кадры, а `state=completed` recording означает, что тот же Stream принял `RECORDER_PROVIDER` и записал непустой файл.

## 12. PHASE H - snapshot result

```text
snapshot_event_count=19
snapshot_sequence_last=19
snapshot_average_interval_seconds=1.021
snapshot_path=/media/comelit/rings/ed9e81af-6e3e-4f08-a514-55012a407a0f/latest.jpg
SNAPSHOT_REFRESH_TARGET_SECONDS=1
FINAL_SNAPSHOT_EXISTS=true
FINAL_LATEST_JPG_SIZE_SHA256=PENDING_OPERATOR_RELAY
```

`FINAL_SNAPSHOT_EXISTS=true` является безопасным производным фактом: snapshot event emitted только после decodable JPEG frame и atomic write+replace. Raw JPEG bytes в Git не коммитились и в документ не включаются.

## 13. PHASE I - recording result

```text
recording_event_count=1
state=completed
duration_target_seconds=20
duration_actual_seconds=21.287
recording_path=/media/comelit/rings/ed9e81af-6e3e-4f08-a514-55012a407a0f/recording.mp4
door=entrance
event_id=ed9e81af-6e3e-4f08-a514-55012a407a0f
reason=NONE
RECORDING_FILE_EXISTS=true
RECORDING_FILE_SIZE_GT_ZERO=true
RECORDING_MP4_SIZE=PENDING_OPERATOR_RELAY
RECORDING_PROBED_DURATION_SECONDS=PENDING_OPERATOR_RELAY
RECORDING_VIDEO_STREAM_PRESENT=PENDING_OPERATOR_RELAY
```

`RECORDING_FILE_EXISTS=true` и `RECORDING_FILE_SIZE_GT_ZERO=true` следуют из `state=completed`: `_async_record_mp4` ставит `RECORDING_STATE_COMPLETED` только если `path.is_file()` и `path.stat().st_size > 0`. Файловые metadata с HAOS не читались из restricted surface: `ARBITRARY_SHELL=DENIED`.

Acceptance duration window `18.0..24.0` s закрывается доступным значением `duration_actual_seconds=21.287`.

## 14. PHASE J - teardown and listener after

Two teardown observations:

```text
OBS1=2026-09-18T12:37:15Z
running=true
listener_ready=true
last_error=null
ring_media.running=false
active_event_id=null
reconnect_count=0
media_active=False recorder samples x3
```

```text
OBS2=2026-09-18T12:37:45Z
running=true
listener_ready=true
last_error=null
ring_media.running=false
active_event_id=null
reconnect_count=0
media_active=False recorder samples x3
```

Derived:

```text
MEDIA_TEARDOWN=PASS
LISTENER_READY_AFTER_MEDIA=PASS
SECOND_MEDIA_SESSION=false
SECOND_RECORDING=false
```

## 15. What was not checked or not proven

Не проверялось и не доказывается этим документом:

- `ha_stream_created=true` на `camera.comelit_entrance`; это camera-entity UI stream surface, не ring-path Stream proof.
- HAOS arbitrary shell metadata for retained artifacts; `latest.jpg` size/sha256, `recording.mp4` size, ffprobe duration и explicit video-stream presence остаются `PENDING_OPERATOR_RELAY`.
- Содержимое JPEG/MP4, credentials, raw RTP/audio и PCAP. Эти данные не включались и не должны коммититься в Git.
- Real physical Door/Gate actuation. В этом bounded synthetic canary `DOOR_ACTIONS=0` и `GATE_ACTIONS=0` намеренно.

## 16. Superseded history

Предыдущий round superseded текущим результатом:

```text
TASK_ID=COMELIT-MVP1-SYNTHETIC-RING-CANARY
RESULT=FAIL
reason=stream_unavailable
duration_actual_seconds=0.002
state=failed
event_id=1a0d4bdc-7020-4bb1-a4df-5d040c38e744
timestamp=2026-09-18T11:54:31.325628+00:00
recording_event_count=1
```

Этот historical result сохранен только как предыдущий round: он заменен live round 2, где `RESULT=PASS_MVP1_SYNTHETIC_RING_CANARY`.
