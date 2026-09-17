# P116 / R30G - restart-activated bounded live result

TASK_ID=`COMELIT-P116-R30G-RESTART-ACTIVATED-BOUNDED-LIVE`

Status: **completed / exact-main left deployed / no rollback restart used**

## Authorization and boundaries

R30G was authorized to deploy exact fresh-main `custom_components/comelit/**`,
perform one full Home Assistant restart to activate the deployed Python code,
run bounded entrance-camera media attempts, and use a second Home Assistant
restart only after rollback deployment if exact-main could not be kept safely.

No Door action, Gate action, HAOS/VM/host reboot, go2rtc/Frigate change,
unrelated integration change, credential/account change, production-code edit,
raw/persistent media capture, or blind retry was performed.

```text
MAX_HA_RESTARTS=2
HA_RESTARTS=1
RESTART_1_PURPOSE=activate_exact_main_python
RESTART_2_PURPOSE=rollback_recovery_only
RESTART_2_RESULT=NOT_RUN
```

## Preflight evidence

The 12 required preflight items were closed before deploy:

1. Fresh `origin/main` SHA: `6a711a4939e7980e8e5091191588f347a34f2e88`.
2. Repository packaged native helper SHA:
   `a336477aa3564f4c99983a71621fc630885c55bf7ff07909bc70838d851a49b8`.
3. Repository `MEDIA_NATIVE_BINARY_SHA256` pin:
   `a336477aa3564f4c99983a71621fc630885c55bf7ff07909bc70838d851a49b8`.
4. Current deployed Comelit identity from gateway:
   `DEPLOYED_SHA=b96ad1690e216f8e81934314470259b1abcc495d`.
5. Preflight deployed native helper SHA and transport pin:
   `35a9a1604c4bef3667713e3487b68aadc79501c4630748d7143ee9ee7cd85622`.
6. Listener state and health: `running=true`, `listener_ready=true`,
   `last_error=null`, `supervisor_running=true`, `reconnect_count=0`.
7. Media/session inactive: camera recorder state showed
   `media_active=False`, `media_phase=inactive`, `remaining_seconds=0`,
   `listener_paused=False`, `video_forwarding=False`, `audio_forwarding=False`.
8. Camera/session entity availability: `camera.comelit_entrance=idle` with
   `automatic_session_start=False`; no switch state-change occurred before the
   owner action, which is acceptable because the camera/session attributes prove
   no active session.
9. Hard limit: `hard_limit_seconds=600`.
10. HA core health: `HA_CORE_CHECK=PASS`.
11. Rollback artifact:
   `/tmp/r30g/rollback-comelit-b96ad1690e216f8e81934314470259b1abcc495d.tar.gz`,
   sha256 `fbc0ffb6a70a29965c686c902db2612437d666745728d86ed00679eeb80d41a4`,
   54 members, `OUTSIDE_MEMBERS=0`, payload native/pin `35a9a160...`.
12. Door/Gate baseline: `network_door_action_performed=false`,
   `physical_door_action=false`, `p13_executed=false`, `p14_executed=false`;
   `DOOR_ACTIONS=0`, `GATE_ACTIONS=0`.

Deploy payload:

```text
DEPLOY_PAYLOAD=/tmp/r30g/deploy-main-6a711a4939e7980e8e5091191588f347a34f2e88.tar.gz
DEPLOY_PAYLOAD_SHA256=fb1aba138aa46b594f066e69005d2d6aba30d6aa03c3626f982b0c15bff564ca
DEPLOY_PAYLOAD_MEMBERS=54
DEPLOY_PAYLOAD_OUTSIDE_MEMBERS=0
DEPLOY_PAYLOAD_NATIVE_SHA256=a336477aa3564f4c99983a71621fc630885c55bf7ff07909bc70838d851a49b8
DEPLOY_PAYLOAD_TRANSPORT_PIN=a336477aa3564f4c99983a71621fc630885c55bf7ff07909bc70838d851a49b8
PREFLIGHT_VERDICT=PASS
```

## Exact-main deploy and restart #1

Exact-main deployment was integration-scoped to
`custom_components/comelit/**`.

```text
DEPLOYED_MAIN_SHA=6a711a4939e7980e8e5091191588f347a34f2e88
DEPLOYED_NATIVE_SHA256=a336477aa3564f4c99983a71621fc630885c55bf7ff07909bc70838d851a49b8
DEPLOYED_TRANSPORT_PIN=a336477aa3564f4c99983a71621fc630885c55bf7ff07909bc70838d851a49b8
DEPLOY_SHA_GATE=PASS
HA_RESTARTED_BY_DEPLOY=NO
```

Restart #1 was used only to activate the exact-main Python code:

```text
RESTART_1_RESULT=PASS
POST_RESTART_HA_CORE_READY=true
POST_RESTART_LISTENER_READY=true
POST_RESTART_MEDIA_INACTIVE=true
POST_RESTART_CAMERA_SESSION_INACTIVE=true
POST_RESTART_DOOR_ACTIONS=0
POST_RESTART_GATE_ACTIONS=0
```

## Loaded-code identity

`LOADED_CODE_IDENTITY_PROVEN=true`.

After restart #1 and exact-main deployment, the first media start produced
`MISMATCH_MATCHES=0`, reached `P80_MEDIA_ACTIVE=true`, and emitted native
markers including `P80_VIDEO_RTP_FORWARDING=PASS`,
`P80_AUDIO_RTP_FORWARDING=PASS`, `P78_RTPC_SIGNALING_RESULT=PASS`,
`P80_DEVICE_000A_VALIDATION=PASS`, `P80_DEVICE_ACK_000A_OBSERVED=PASS`,
`P80_DEVICE_ACK_001A_OBSERVED=PASS`, `PSEUDOTCP_OPEN_FINAL=true`,
`ICE_CONNECTED_FINAL=true`, and P116 RTP counters. The loaded Python
`_native_gate()` therefore accepted the deployed `a336477a...` native helper
and allowed helper execution. This distinguishes R30G from R30F, where the same
path failed before media activation with `media_native_binary_sha256_mismatch`.

```text
MEDIA_NATIVE_BINARY_SHA256_MISMATCH=false
```

## Attempt 1 - upstream/helper historical boundary

Owner action: turn on `switch.comelit_entrance_camera`; do not open the HA
camera entity view; manually switch off after observation. Camera view was not
opened, so the HA Stream consumer leg was intentionally not exercised.

```text
ATTEMPT_1_RESULT=FAIL_HISTORICAL_RTP_STOP_REPRODUCED
SESSION_ACTIVE_LINE=2026-09-17 14:31:59.721 Comelit entrance media session ACTIVE
SESSION_COMPLETED_LINE=2026-09-17 14:34:06.797 Comelit entrance media transport completed
OWNER_SWITCH_OFF=true
SESSION_LEASE_DURATION_SECONDS=127.076
ATTEMPT_1_MEDIA_DURATION_SECONDS=34.580
HISTORICAL_36S_BOUNDARY_SURPASSED=false
MEDIA_NATIVE_BINARY_SHA256_MISMATCH=false
```

Native RTP evidence:

```text
P116_VIDEO_COUNT=1694
P116_VIDEO_FIRST_SEQ=2422
P116_VIDEO_LAST_SEQ=4115
P116_VIDEO_FIRST_TS=3847650852
P116_VIDEO_LAST_TS=3850768452
P116_VIDEO_FIRST_MONOTONIC_MS=999428278
P116_VIDEO_LAST_MONOTONIC_MS=999462858
P116_VIDEO_RTP_SPAN_SECONDS=34.580
P116_VIDEO_SEQ_GAPS=0
P116_VIDEO_DUPLICATES=0
P116_VIDEO_OUT_OF_ORDER=0
P116_VIDEO_TIMESTAMP_REGRESSIONS=0
P116_VIDEO_SSRC_COUNT=1
P116_VIDEO_SSRC_CHANGES=0
P116_VIDEO_PT_SET=99
P116_VIDEO_MARKER_COUNT=887
P116_VIDEO_FIRST_KEYFRAME_MONOTONIC_MS=999428279
P116_VIDEO_SPS_COUNT=10
P116_VIDEO_PPS_COUNT=10
P116_VIDEO_FUA_COUNT=1512
P116_VIDEO_SINGLE_NAL_COUNT=182
P116_AUDIO_COUNT=1735
P116_AUDIO_FIRST_SEQ=40563
P116_AUDIO_LAST_SEQ=42297
P116_AUDIO_FIRST_TS=235533472
P116_AUDIO_LAST_TS=235810912
P116_AUDIO_FIRST_MONOTONIC_MS=999428178
P116_AUDIO_LAST_MONOTONIC_MS=999462857
P116_AUDIO_RTP_SPAN_SECONDS=34.679
P116_AUDIO_SEQ_GAPS=0
P116_AUDIO_DUPLICATES=0
P116_AUDIO_OUT_OF_ORDER=0
P116_AUDIO_TIMESTAMP_REGRESSIONS=0
P116_AUDIO_SSRC_COUNT=1
P116_AUDIO_SSRC_CHANGES=0
P116_AUDIO_PT_SET=8
```

The HA-side recorder showed the media lease stayed active after RTP silence:
`video_last_packet_age_seconds` and `audio_last_packet_age_seconds` began
growing around 14:32:35, while `media_active=True` and `media_phase=active`
continued until owner switch-off at 14:34:06.

## Attempt 2 - HA Stream consumer

Attempt 2 was run as a diagnostic consumer-leg test even though Attempt 1 did
not prove a healthy upstream/helper path. Owner action: turn on
`switch.comelit_entrance_camera`, open `camera.comelit_entrance` in the HA
frontend, hold the view open, then switch off manually.

```text
ATTEMPT_2_RESULT=PASS_HA_STREAM_CONSUMER_PROVEN_WITH_UPSTREAM_TIMEOUT
SESSION_ACTIVE_LINE=2026-09-17 14:39:15.387 Comelit entrance media session ACTIVE
SESSION_COMPLETED_LINE=2026-09-17 14:40:34.923 Comelit entrance media transport completed
SESSION_LEASE_DURATION_SECONDS=79.536
MEDIA_NATIVE_BINARY_SHA256_MISMATCH=false
HA_STREAM_CONSUMER_PROVEN=true
```

Criterion applied: `HA_STREAM_CONSUMER_PROVEN=true` requires objective evidence
that HA Stream/FFmpeg consumed the local SDP/RTP source, not merely helper RTP.
Attempt 2 satisfies that criterion: HA created a stream and HLS provider,
started a worker, identified `container_format=sdp` and `video_codec=h264`,
created an init segment, created HLS parts and multiple segments, generated an
HTTP endpoint, and self-probed the endpoint before the upstream RTP source went
silent.

HA Stream/HLS evidence:

```text
ha_stream_created=true
ha_stream_available=true then false after worker timeout
ha_stream_start_worker_count=1 peak 2 after automatic restart
ha_stream_worker_error_count=1
ha_stream_container_format=sdp
ha_stream_video_codec=h264
hls_provider_present=true
hls_segment_count=4
hls_part_count=34
hls_init_bytes=780
hls_first_part_bytes=52941
hls_first_part_has_keyframe=true
hls_first_segment_complete=true
hls_second_segment_created=true
hls_endpoint_generated=true
hls_probe_mode=self_http
hls_probe_completed=true
video_packet_count_HA_side=1750
audio_packet_count_HA_side=1750
```

Video recovery shim evidence:

```text
video_recovery_shim_running=true
video_recovery_input_packets=1767
video_recovery_output_packets=1775
video_recovery_idr_count=2
video_recovery_injected_count=8
video_recovery_eligible_nonidr_i_count=8
video_recovery_unsupported_packet_count=0
video_recovery_malformed_count=0
video_recovery_last_error=None
```

HA Stream worker errors were observed only after helper RTP had gone silent:

```text
2026-09-17 14:40:10.923 Error from stream worker: Error demuxing stream (Operation timed out, /run/comelit-media/local-rtp.sdp)
2026-09-17 14:40:43.814 Error from stream worker: Error demuxing stream while finding first packet (Operation timed out, /run/comelit-media/local-rtp.sdp)
```

These worker errors are recorded as downstream symptoms of upstream RTP silence,
not as the root cause of the R30G failure.

Native RTP evidence for Attempt 2:

```text
P116_VIDEO_COUNT=1767
P116_VIDEO_FIRST_SEQ=473
P116_VIDEO_LAST_SEQ=2239
P116_VIDEO_FIRST_TS=3850818852
P116_VIDEO_LAST_TS=3853997652
P116_VIDEO_FIRST_MONOTONIC_MS=999863984
P116_VIDEO_LAST_MONOTONIC_MS=999899314
P116_VIDEO_RTP_SPAN_SECONDS=35.330
P116_VIDEO_SEQ_GAPS=0
P116_VIDEO_DUPLICATES=0
P116_VIDEO_OUT_OF_ORDER=0
P116_VIDEO_TIMESTAMP_REGRESSIONS=0
P116_VIDEO_SSRC_COUNT=1
P116_VIDEO_SSRC_CHANGES=0
P116_VIDEO_PT_SET=99
P116_VIDEO_MARKER_COUNT=904
P116_VIDEO_FIRST_KEYFRAME_MONOTONIC_MS=999863985
P116_VIDEO_SPS_COUNT=10
P116_VIDEO_PPS_COUNT=10
P116_VIDEO_FUA_COUNT=1633
P116_VIDEO_SINGLE_NAL_COUNT=134
P116_AUDIO_COUNT=1772
P116_AUDIO_FIRST_SEQ=21478
P116_AUDIO_LAST_SEQ=23249
P116_AUDIO_FIRST_TS=235823200
P116_AUDIO_LAST_TS=236106880
P116_AUDIO_FIRST_MONOTONIC_MS=999863844
P116_AUDIO_LAST_MONOTONIC_MS=999899294
P116_AUDIO_RTP_SPAN_SECONDS=35.450
P116_AUDIO_SEQ_GAPS=0
P116_AUDIO_DUPLICATES=0
P116_AUDIO_OUT_OF_ORDER=0
P116_AUDIO_TIMESTAMP_REGRESSIONS=0
P116_AUDIO_SSRC_COUNT=1
P116_AUDIO_SSRC_CHANGES=0
P116_AUDIO_PT_SET=8
P80_MEDIA_ACTIVE=true
P80_VIDEO_RTP_FORWARDING=PASS
P80_AUDIO_RTP_FORWARDING=PASS
ICE_CONNECTED_FINAL=true
PSEUDOTCP_GRACEFUL_CLOSE_COMPLETE=true
```

Attempt 2 therefore proves the HA Stream consumer path works inside the RTP
window, but it also reproduces the same ~35 second upstream/helper RTP stop.

## Attempts 3-5

No further attempts were run. No additional restart, retry, protocol experiment,
or production-code edit was authorized or needed for R30G classification.

## Diagnosis and production-defect finding

R30G proves activation and HA Stream consumption, but the accepted R30E
helper/exact-main path still stops producing forwarded RTP around the historical
boundary:

```text
ATTEMPT_1_VIDEO_RTP_SPAN_SECONDS=34.580
ATTEMPT_1_AUDIO_RTP_SPAN_SECONDS=34.679
ATTEMPT_2_VIDEO_RTP_SPAN_SECONDS=35.330
ATTEMPT_2_AUDIO_RTP_SPAN_SECONDS=35.450
HISTORICAL_36S_BOUNDARY_SURPASSED=false
```

The defect is not root-caused in R30G. The collected markers establish clean RTP
before silence, no sequence gaps, no duplicates, no out-of-order packets, no RTP
timestamp regressions, stable SSRCs, valid PT sets, successful forwarding
markers, and graceful close after owner stop. They do not distinguish whether
the stop is helper-side receive/forward logic, an upstream remote/device/cloud
RTP cessation, or a protocol lifetime/keepalive condition in the native path.

Minimal follow-on evidence that would localize helper-side versus upstream-side
without committing raw media would be scalar native telemetry that separates
remote inbound RTP receive counters from local forwarded RTP counters over time,
plus explicit native reason markers for pseudotcp/ICE/media channel liveness at
the first moment forwarded RTP stops. That requires a new authorized
production-code/native telemetry change or an approved bounded diagnostic
outside this result-doc-only write scope.

Potential files for a future scoped fix or telemetry extension:

```text
custom_components/comelit/media_transport.py
custom_components/comelit/h264_recovery.py
safety-poc/research/media/v1/entrance_p106_teardown_state_classification_transform.py
custom_components/comelit/native/comelit-media
```

No production-code changes were made in R30G.

## Post-attempt invariant

After each attempt, and finally after Attempt 2:

```text
MEDIA_INACTIVE=true
CAMERA_SESSION_INACTIVE=true
LISTENER_READY=true
PERSISTENT_NEW_RECONNECT_OR_ERROR=false
last_error=null
last_native_exit_code=null
last_native_failure_markers=[]
reconnect_count=0
HA_CORE_READY=true
DEPLOYED_SHA=6a711a4939e7980e8e5091191588f347a34f2e88
DOOR_ACTIONS=0
GATE_ACTIONS=0
```

One unrelated Home Assistant template warning was observed after testing:
`Template loop detected` for a user `sensor.unavailable_entities` template. It
was a single non-Comelit event and did not affect the Comelit integration
classification.

## Keep or rollback decision

`KEEP_OR_ROLLBACK_FINAL=keep exact-main deployed`.

Rollback was not performed and restart #2 was not consumed. Exact-main is safe
to leave deployed because restart #1 succeeded, loaded-code identity is proven,
HA core is healthy, the Comelit listener recovered, media/session is inactive,
Door/Gate actions remained zero, and no persistent new reconnect/error
regression exists. The ~35 second RTP stop is a functional production defect,
but it leaves the system safely tearable down and does not create a material
production regression requiring rollback under the R30G contract.

```text
EXACT_MAIN_LEFT_DEPLOYED=true
ROLLBACK_PERFORMED=false
RESTART_2_USED_FOR_ROLLBACK_ONLY=na
RESTART_2_RESULT=NOT_RUN
```

## Final classification

R30G is classified as `FAIL`: exact-main activation and HA Stream consumption
were proven, but the core historical media-duration goal failed because RTP
still stops at approximately 35 seconds in both live attempts.

```text
=== COMELIT P116 R30G RESTART-ACTIVATED BOUNDED LIVE ===
TASK_ID=COMELIT-P116-R30G-RESTART-ACTIVATED-BOUNDED-LIVE
BASE_SHA=6a711a4939e7980e8e5091191588f347a34f2e88
PRE_R30G_DEPLOYED_SHA=b96ad1690e216f8e81934314470259b1abcc495d
DEPLOYED_MAIN_SHA=6a711a4939e7980e8e5091191588f347a34f2e88
FINAL_DEPLOYED_SHA=6a711a4939e7980e8e5091191588f347a34f2e88
EXPECTED_NATIVE_SHA256=a336477aa3564f4c99983a71621fc630885c55bf7ff07909bc70838d851a49b8
DEPLOYED_NATIVE_SHA256=a336477aa3564f4c99983a71621fc630885c55bf7ff07909bc70838d851a49b8
FINAL_DEPLOYED_NATIVE_SHA256=a336477aa3564f4c99983a71621fc630885c55bf7ff07909bc70838d851a49b8
DEPLOYED_TRANSPORT_PIN=a336477aa3564f4c99983a71621fc630885c55bf7ff07909bc70838d851a49b8
DEPLOY_SHA_GATE=PASS
ROLLBACK_BACKUP=/tmp/r30g/rollback-comelit-b96ad1690e216f8e81934314470259b1abcc495d.tar.gz sha256=fbc0ffb6a70a29965c686c902db2612437d666745728d86ed00679eeb80d41a4
MAX_HA_RESTARTS=2
HA_RESTARTS=1
RESTART_1_RESULT=PASS
RESTART_2_USED_FOR_ROLLBACK_ONLY=na
RESTART_2_RESULT=NOT_RUN
LOADED_CODE_IDENTITY_PROVEN=true
MEDIA_NATIVE_BINARY_SHA256_MISMATCH=false
MAX_LIVE_ATTEMPTS=5
LIVE_ATTEMPTS_USED=2
ATTEMPT_1_RESULT=FAIL_HISTORICAL_RTP_STOP_REPRODUCED
ATTEMPT_1_MEDIA_DURATION_SECONDS=34.580
HISTORICAL_36S_BOUNDARY_SURPASSED=false
ATTEMPT_2_RESULT=PASS_HA_STREAM_CONSUMER_PROVEN_WITH_UPSTREAM_TIMEOUT
HA_STREAM_CONSUMER_PROVEN=true
HA_STREAM_ERROR=downstream_after_upstream_rtp_silence: Error demuxing stream (Operation timed out, /run/comelit-media/local-rtp.sdp); Error demuxing stream while finding first packet (Operation timed out, /run/comelit-media/local-rtp.sdp)
LISTENER_READY_BEFORE=true
LISTENER_READY_AFTER=true
LISTENER_RESTORED_AFTER_EACH_ATTEMPT=true
EXACT_MAIN_LEFT_DEPLOYED=true
ROLLBACK_PERFORMED=false
DOOR_ACTIONS=0
GATE_ACTIONS=0
RAW_MEDIA_COMMITTED=false
GO2RTC_CHANGED=false
FRIGATE_CHANGED=false
PRODUCTION_CODE_CHANGED=false
RESULT_DOC=safety-poc/research/media/v1/P116_R30G_RESTART_ACTIVATED_BOUNDED_LIVE_RESULT.md
PR=none
RESULT=FAIL
=== END COMELIT P116 R30G RESTART-ACTIVATED BOUNDED LIVE ===
```
