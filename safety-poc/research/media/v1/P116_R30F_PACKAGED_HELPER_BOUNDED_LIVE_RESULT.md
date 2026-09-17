# P116 / R30F - packaged helper bounded live result

TASK_ID=`COMELIT-P116-R30F-PACKAGED-HELPER-BOUNDED-LIVE`

Status: **BLOCKED at activation boundary / restored to pre-R30F deployed tree**

## Scope and authorization

R30F was authorized as a bounded camera-only live stage for the Comelit Home
Assistant integration. The authorized live surface was limited to the Comelit
integration, exact-main `custom_components/comelit/**` deployment after
rollback backup, at most one config-entry reload, at most 10 entrance-camera
media attempts, scalar/status/log evidence, and temporary `/tmp` stream
verification if needed.

No Home Assistant restart/reboot, Door action, Gate action, go2rtc/Frigate
change, credential/account change, persistent/raw RTP/H264/audio capture, or
production-code edit was authorized.

## Preflight evidence

Fresh source of truth:

```text
origin/main=bd83d6eebd91bf2003ff12f2fedac36494afb9ab
repo packaged native sha256=a336477aa3564f4c99983a71621fc630885c55bf7ff07909bc70838d851a49b8
repo transport pin sha256=a336477aa3564f4c99983a71621fc630885c55bf7ff07909bc70838d851a49b8
```

Installed state before intervention:

```text
INTEGRATION_PRESENT=true
INTEGRATION_VERSION=1.5.7
DEPLOYED_SHA=b96ad1690e216f8e81934314470259b1abcc495d
installed native sha256 derived from deployed commit=35a9a1604c4bef3667713e3487b68aadc79501c4630748d7143ee9ee7cd85622
installed transport pin derived from deployed commit=35a9a1604c4bef3667713e3487b68aadc79501c4630748d7143ee9ee7cd85622
hard_limit_seconds=600
deploy delta b96ad16..bd83d6e custom_components=exactly 2 files:
  custom_components/comelit/media_transport.py
  custom_components/comelit/native/comelit-media
```

Predeploy gates passed. The listener was treated as healthy enough to proceed
because the freshest stable pre-intervention state had
`running=true`, `listener_ready=true`, `supervisor_running=true`,
`last_error=null`, media inactive, and a later 300 s window did not show
continued reconnect/native-exit cycling. Earlier transient listener cycling was
recorded but was not persistent at the deploy gate.

Rollback backup was materialized from repository commit
`b96ad1690e216f8e81934314470259b1abcc495d` because the HA gateway denies
arbitrary shell/read access to copy live bytes. This backup is faithful to the
installed tree through the gateway's `DEPLOYED_SHA=b96ad16...` identity and
`DEPLOY_SCOPE=/config/custom_components/comelit`, not through byte-reading the
HA filesystem.

## Exact-main deployment and activation attempt

The exact-main payload was a `git archive` of
`bd83d6eebd91bf2003ff12f2fedac36494afb9ab:custom_components/comelit`, gzip
normalized with `gzip -n`.

```text
payload bytes=6180877
OUTSIDE_MEMBERS=0
payload native sha256=a336477aa3564f4c99983a71621fc630885c55bf7ff07909bc70838d851a49b8
payload pin literal=a336477aa3564f4c99983a71621fc630885c55bf7ff07909bc70838d851a49b8
gateway deploy output=DEPLOYED_SHA=bd83d6ee... | DEPLOY_SCOPE=/config/custom_components/comelit | HA_RESTARTED=NO | DEPLOY=PASS
```

The owner performed the Comelit config-entry reload once. Reload evidence:

```text
reconnect_count 202 -> 0
last_native_exit_code 6 -> None
no setup/unload exception in 240 s window
13:42:38 INFO runtime Comelit ring listener READY for persistent 3300s cycle
HA_CORE_CHECK=PASS
DEPLOYED_SHA=bd83d6eebd91bf2003ff12f2fedac36494afb9ab
```

Attempt 1 was the owner UI `switch.comelit_entrance_camera` enable action with
the HA camera view intentionally not opened. It failed closed before media
became active:

```text
2026-09-17 13:54:00.020 ERROR (MainThread) [custom_components.comelit.media_transport] Comelit entrance media transport stopped: media_native_binary_sha256_mismatch
  (source=('custom_components/comelit/media_transport.py', 588))
2026-09-17 13:54:00.022 ERROR (MainThread) [homeassistant.components.websocket_api.http.connection] [3483592776848] Error during service call to switch.turn_on: Cannot start Comelit entrance media session: media_start_failed
2026-09-17 13:54:00.023 DEBUG (Recorder) [homeassistant.components.recorder.core] Processing task: <Event system_log_event[L]: name=homeassistant.components.websocket_api.http.connection, message=['[3483592776848] Error during service call to switch.turn_on: Cannot start Comelit entrance media session: media_start_failed'], level=ERROR, source=('components/websocket_api/commands.py', 336)>
```

No `Comelit entrance media session ACTIVE` line, P116/P80 native markers,
stream-worker line, switch `=on` recorder dump, Door/Gate field, or second
toggle occurred. Post-failure state was safe:

```text
DEPLOYED_SHA=bd83d6eebd91bf2003ff12f2fedac36494afb9ab
HA_CORE_CHECK=PASS
listener running/listener_ready/supervisor_running=true
last_error=null
reconnect_count=0
last_native_exit_code=None
camera.comelit_entrance=idle
media_active=False
media_phase=inactive
video_forwarding=False
audio_forwarding=False
video_recovery_shim_running=False
DOOR_ACTIONS=0
GATE_ACTIONS=0
```

This established an activation blocker: the new binary was deployed, but the
loaded Python module did not use the new pin, or the binary replacement path was
untrusted. R30F then used Attempt 2 as a rollback discriminator and restoration
step instead of the originally planned HA Stream consumer attempt.

## H_A / H_B discrimination

```text
ATTEMPT_2_HYPOTHESIS=Rollback to the preflight b96ad1690e216f8e81934314470259b1abcc495d integration tree will restore loaded old Python pin plus old on-disk native binary consistency if the Attempt 1 mismatch was caused by config-entry reload not re-importing Python modules.
ATTEMPT_2_DISTINGUISHING_EVIDENCE=If one post-rollback owner switch-on reaches Comelit entrance media session ACTIVE or emits P80/P116 native markers, H_A is confirmed and new Python activation requires whole-HA restart; if the same media_native_binary_sha256_mismatch occurs after rollback, H_B or an untrusted binary deploy/restore path is supported and live attempts stop.
```

Rollback deploy used the preflight archive and no post-rollback config-entry
reload:

```text
sha256(rollback archive)=d093d3e0902870279fa6378b290b6d1efa3f1e9d36bf7e7c92005960d29ce1a7
gateway output=DEPLOYED_SHA=b96ad1690e216f8e81934314470259b1abcc495d | DEPLOY_SCOPE=/config/custom_components/comelit | HA_RESTARTED=NO | DEPLOY=PASS
post-rollback status=INTEGRATION_PRESENT=true | INTEGRATION_VERSION=1.5.7 | DEPLOYED_SHA=b96ad1690e216f8e81934314470259b1abcc495d
HA_CORE_CHECK=PASS
post-rollback listener running/listener_ready/supervisor_running=true
last_error=null
reconnect_count=0
last_native_exit_code=None
```

Attempt 2 owner action: enable `switch.comelit_entrance_camera` once; camera
view intentionally not opened. It started a real media session on the
rolled-back tree:

```text
13:58:25.436 INFO [custom_components.comelit.media_transport] Comelit entrance media session ACTIVE
13:58:26.457 .. 13:58:48.478 (1 Hz) [custom_components.comelit.camera] Comelit HLS diagnostics: ha_stream_available=unknown ha_stream_container_format=unknown ha_stream_created=false ha_stream_start_worker_count=unknown ha_stream_video_codec=unknown hls_provider_present=false hls_segment_count=unknown
13:58:48.778 INFO [custom_components.comelit.media_transport] Comelit entrance media transport completed: protocol_native_markers=[...] p116_native_markers=[...]
13:58:54.050 INFO [custom_components.comelit.runtime] Comelit ring listener READY for persistent 3300s cycle
```

No stream-worker line, `media_native_binary_sha256_mismatch`, or Door/Gate field
appeared. Media was deliberately stopped by the owner:

```text
ACTIVE 13:58:25.436 -> teardown 13:58:48.778 = 23.342 s
P116_VIDEO_FIRST_MONOTONIC_MS=997413995 -> P116_VIDEO_LAST_MONOTONIC_MS=997437122 = 23.127 s
P116_AUDIO_FIRST_MONOTONIC_MS=997413893 -> P116_AUDIO_LAST_MONOTONIC_MS=997437122 = 23.229 s
```

P116 native markers:

```text
P116_VIDEO_COUNT=1128 | FIRST_SEQ=63040 | LAST_SEQ=64167 | FIRST_TS=3843762852 | LAST_TS=3845850852 | SEQ_GAPS=0 | DUPLICATES=0 | OUT_OF_ORDER=0 | TIMESTAMP_REGRESSIONS=0 | SSRC_COUNT=1 | SSRC_CHANGES=0 | PT_SET=99 | MARKER_COUNT=595 | FIRST_KEYFRAME_MONOTONIC_MS=997413996 (+1 ms after first packet) | SPS_COUNT=7 | PPS_COUNT=7 | FUA_COUNT=998 | SINGLE_NAL_COUNT=130
P116_AUDIO_COUNT=1163 | FIRST_SEQ=11774 | LAST_SEQ=12936 | FIRST_TS=235042720 | LAST_TS=235228640 | SEQ_GAPS=0 | DUPLICATES=0 | OUT_OF_ORDER=0 | TIMESTAMP_REGRESSIONS=0 | SSRC_COUNT=1 | SSRC_CHANGES=0 | PT_SET=8
```

Selected protocol markers:

```text
P80_MEDIA_ACTIVE=true
P80_VIDEO_RTP_PORT=17899
P80_AUDIO_RTP_PORT=17808
P80_VIDEO_RTP_FORWARDING=PASS
P80_AUDIO_RTP_FORWARDING=PASS
P78_RTPC_SIGNALING_RESULT=PASS
P80_DEVICE_0002_GATE=PASS
P80_DEVICE_000A_VALIDATION=PASS
P80_DEVICE_ACK_000A_OBSERVED=PASS
P80_DEVICE_ACK_001A_OBSERVED=PASS
PSEUDOTCP_OPEN_FINAL=true
PSEUDOTCP_GRACEFUL_CLOSE_COMPLETE=true
PSEUDOTCP_GRACEFUL_CLOSE_TIMEOUT=false
ICE_CONNECTED_FINAL=true
ICE_READY_FINAL=true
```

Conclusion: H_A is confirmed. Config-entry reload restored integration runtime
health but did not re-import the updated custom-component Python module. New
Python activation for the exact-main R30E helper requires a whole-HA restart,
which is outside R30F authorization.

## Post-attempt invariant and final deployment state

Post-Attempt-2 invariant:

```text
media_active=False
media_phase=inactive
video_forwarding=False
audio_forwarding=False
camera/session control off
listener running/listener_ready/supervisor_running=true
last_error=null
reconnect_count=0
last_native_exit_code=None
network_door_action_performed=false
physical_door_action=false
DEPLOYED_SHA=b96ad1690e216f8e81934314470259b1abcc495d
HA_CORE_CHECK=PASS
```

Final production deployment state is restored to the pre-R30F deployed identity
`b96ad1690e216f8e81934314470259b1abcc495d`. The R30E exact-main helper was
deployed during the stage but is not the final deployed tree.

## Local gates

Hermes host, `safety-poc`:

```text
static_safety_check.py=PASS
NETWORK_IMPORTS_PRESENT=false
COMELIT_ENDPOINTS_PRESENT=false
SOURCE_FILES_SCANNED=29
compileall custom_components/comelit=PASS
```

Focused suite:

```text
tests.test_p107_musl_package_provenance
tests.test_p116_provenance_binary_analysis
tests.test_p80_media_transport_static_contract
tests.test_p116_ha_stream_rtp_bridge
tests.test_p116_r24_recovery_shim_lifecycle

Ran 44
failures=1
skipped=1
```

Failure classification:

```text
FAILED test_committed_build_metadata_records_historical_non_runtime_mismatch
AssertionError: '755' != '775'
meta NATIVE_BINARY_MODE=755 vs live worktree file mode
CLASSIFICATION=NOT_A_R30F_REGRESSION / HOST_UMASK_ENVIRONMENT_ARTIFACT
R30F_WORKTREE_FILE_MODE=775 under host umask 0002
CONTROL_WORKTREE_FILE_MODE=755 under umask 022
committed mode=100755 in both
control tests.test_p116_provenance_binary_analysis=Ran 3, OK (skipped=1)
git config tar.umask=unset, git default 0002
```

The deploy path used the same archive transport class used by previous deploys
in this lane. This test failure did not cause the live activation blocker; the
live blocker occurred at loaded Python/native SHA pin consistency.

## Production-defect / write-scope extension

No production code was changed in R30F.

Finding:

```text
file/custom lifecycle area=custom_components/comelit/media_transport.py and Home Assistant custom-component integration lifecycle
mechanism=the deployment gateway can replace custom_components/comelit files, and the owner UI config-entry reload can unload/setup the integration, but HA does not re-import already-loaded custom-component Python modules. The loaded media_transport.py therefore retained the old MEDIA_NATIVE_BINARY_SHA256 while the on-disk native helper was replaced with the R30E binary, causing _native_gate() to fail closed with media_native_binary_sha256_mismatch.
minimal proposed fix/scope extension=add an activation-safe lifecycle mechanism or explicit loaded-code identity diagnostic for custom_components/comelit, likely spanning custom_components/comelit/__init__.py and custom_components/comelit/media_transport.py. Any actual activation of changed Python on this HAOS target currently requires whole-HA restart authorization.
```

Because whole-HA restart is forbidden in R30F, the correct result is `BLOCKED`,
not a helper/media-path failure. The R30E helper never reached an active media
session while exact-main was deployed.

```text
=== COMELIT P116 R30F PACKAGED HELPER BOUNDED LIVE ===
TASK_ID=COMELIT-P116-R30F-PACKAGED-HELPER-BOUNDED-LIVE
BASE_SHA=bd83d6eebd91bf2003ff12f2fedac36494afb9ab
DEPLOYED_MAIN_SHA=bd83d6eebd91bf2003ff12f2fedac36494afb9ab
FINAL_DEPLOYED_SHA=b96ad1690e216f8e81934314470259b1abcc495d
DEPLOYED_NATIVE_SHA256=a336477aa3564f4c99983a71621fc630885c55bf7ff07909bc70838d851a49b8
FINAL_DEPLOYED_NATIVE_SHA256=35a9a1604c4bef3667713e3487b68aadc79501c4630748d7143ee9ee7cd85622
EXPECTED_NATIVE_SHA256=a336477aa3564f4c99983a71621fc630885c55bf7ff07909bc70838d851a49b8
DEPLOY_SHA_GATE=PASS
ROLLBACK_BACKUP=/tmp/comelit-r30f-*/rollback-comelit-b96ad1690e216f8e81934314470259b1abcc495d.tar.gz sha256=d093d3e0902870279fa6378b290b6d1efa3f1e9d36bf7e7c92005960d29ce1a7
HA_RESTARTS=0
INTEGRATION_RELOADS=1
MAX_LIVE_ATTEMPTS=10
LIVE_ATTEMPTS_USED=2
ATTEMPT_1_RESULT=FAIL
ATTEMPT_1_MEDIA_DURATION_SECONDS=na
HISTORICAL_36S_BOUNDARY_SURPASSED=undetermined
ATTEMPT_2_RESULT=PASS
ATTEMPT_2_CLASS=ROLLBACK_DISCRIMINATOR_H_A_CONFIRMED
HA_STREAM_CONSUMER_PROVEN=false
HA_STREAM_ERROR=none
LISTENER_READY_BEFORE=true
LISTENER_READY_AFTER=true
LISTENER_RESTORED_AFTER_EACH_ATTEMPT=true
DOOR_ACTIONS=0
GATE_ACTIONS=0
RAW_MEDIA_COMMITTED=false
GO2RTC_CHANGED=false
FRIGATE_CHANGED=false
PRODUCTION_CODE_CHANGED=false
RESULT_DOC=safety-poc/research/media/v1/P116_R30F_PACKAGED_HELPER_BOUNDED_LIVE_RESULT.md
PR=none
RESULT=BLOCKED
RESULT_CLASS=BLOCKED_HA_RESTART_REQUIRED
=== END COMELIT P116 R30F PACKAGED HELPER BOUNDED LIVE ===
```
