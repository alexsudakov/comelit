# Comelit MVP1 synthetic entrance-ring canary result

## 1. Task identity

```text
TASK_ID=COMELIT-MVP1-SYNTHETIC-RING-CANARY
MODE=BOUNDED_SYNTHETIC_TRIGGER_LIVE_RUN
DATE_UTC=2026-09-18
DEPLOYED_SHA=45854c7f0aa201fef0eb5207464e2fb9791c345d
RESULT=FAIL_SNAPSHOT
```

Этот документ заменяет предыдущий trigger-surface result. В этом запуске wrapper gap был минимально исправлен на CT120, один synthetic trigger был выполнен через restricted route, ring event был создан, ровно одна media session была начата и затем завершилась. Canary остановлен после единственного разрешенного trigger round; повторный trigger запрещен.

## 2. Authorization and hard limits

```text
CT120_WRAPPER_MUTATION_FILES_MAX=2
SYNTHETIC_TRIGGER_MAX=1
MEDIA_SESSION_MAX=1
RECORDING_MAX=1
RECORDING_TARGET_SECONDS=20
DEPLOY=0
HA_RELOADS=0
HA_RESTARTS=0
HOST_REBOOTS=0
SUPERVISOR_REBOOTS=0
DOOR_ACTIONS=0
GATE_ACTIONS=0
AUTOMATIC_RETRY=false
SECOND_TRIGGER=false
SECOND_MEDIA_SESSION=false
R30H_E_EXECUTED=false
```

Accepted main was already deployed and activated by the previous run:

```text
DEPLOYED_SHA=45854c7f0aa201fef0eb5207464e2fb9791c345d
```

The integration-side synthetic path creates an entrance-only synthetic `CALL_INIT` event and enters the shared `_async_emit_ring_event` handler (`custom_components/comelit/runtime.py:237`-`custom_components/comelit/runtime.py:285`). Constants remain `SNAPSHOT_REFRESH_TARGET_SECONDS=1` and `RECORDING_TARGET_SECONDS=20` (`custom_components/comelit/const.py:46`-`custom_components/comelit/const.py:47`).

## 3. Result class

```text
RESULT_CLASS=FAIL_SNAPSHOT
```

Trigger succeeded: `SYNTHETIC_TRIGGER_COUNT=1`, `SYNTHETIC_RING_COUNT=1`, `RING_EVENT_COUNT=1`, event id was present, and the event was `source=synthetic_test`, `door=entrance`, `kind=CALL_INIT`, `direction=DEVICE_TO_CLIENT`. Exactly one media session became ACTIVE and the listener returned READY after teardown.

The canary still fails the snapshot gate. The observed upstream media session delivered zero video RTP packets, no video forwarding marker appeared, and the session lifetime was about 0.18 s. With no video packets and no HLS provider in the read-only samples, the snapshot lifecycle had no observed decodable frame source, and the 20 s recording target could not be proven met. Snapshot and recording artifact/state fields are therefore `UNPROVEN` with `PENDING_OPERATOR_RELAY`, while the run classification is `FAIL_SNAPSHOT` on the observed zero-video evidence.

## 4. PHASE A - wrapper preflight

Read-only CT120 preflight:

```text
/usr/local/sbin/hermes-comelit-dispatch owner=root:root mode=755
sha256_before=092ea7d29391840f4d3162e5df9f17270de08d328178c68187455036c8d9f6cf
HA-family cases before=comelit-ha-ring-test-start|comelit-ha-ring-test-status|comelit-ha-ring-test-stop
fallthrough=*) exec "$BACKUP"

/usr/local/sbin/comelit-ha-ring-runtime owner=root:root mode=755
sha256_before=06a291181d363d7c8c6358cd16f14ce6a61385f8e6bacae35c5c4c66782b7804
action whitelist before=start|status|stop

DISPATCH_SYNTAX=PASS
RUNTIME_SYNTAX=PASS
BLOCKER_REPRODUCED=true
ROLLBACK_MATERIAL=/tmp/mvp1-synth/orig/ on orchestration host
```

The blocker was reproduced before mutation: no simulate verb existed, and the runtime wrapper rejected every action outside `start|status|stop`.

## 5. PHASE B - minimal CT120 wrapper mutation

Only the two authorized operator-owned CT120 files were modified:

```text
RUNTIME_EDIT_STATE=applied
DISPATCH_EDIT_STATE=applied
PATCH_APPLY=PASS
runtime_sha256_after=37938f4ce76abeb268f92e34a388bf03dee6d8f808a62d487d32c29e4009c65c
dispatch_sha256_after=5c082fe54e67d78cb8c9443753663e7592940f0e5850193c6888bbb405146dd7
owner=root:root
mode=755
RUNTIME_SYNTAX=PASS
DISPATCH_SYNTAX=PASS
```

Exact runtime diff:

```diff
-    start|status|stop) ;;
+    start|status|stop|simulate_entrance_ring) ;;
```

Exact dispatch diff, inserted before the `*)` fallthrough:

```diff
+    comelit-ha-ring-test-simulate-entrance-ring)
+        exec "$HA_RUNTIME" simulate_entrance_ring
+        ;;
+
```

Validation matrix:

```text
V1 comelit-ha-ring-test-status:
  OK=true ACTION=status RUNNING=true LISTENER_READY=true LAST_ERROR= RING_OBSERVED=false
  P13_EXECUTED=false P14_EXECUTED=false PHYSICAL_DOOR_ACTION=false
  RESULT=read-only path intact

V2 bare simulate_entrance_ring:
  DENIED: command not allowed
  RESULT=arbitrary verbs still refused

V3 /usr/local/sbin/comelit-ha-ring-runtime bogus_action:
  ERROR=BAD_ACTION rc=2
  RESULT=unknown runtime action still rejected before curl/no HTTP request

V4 wiring:
  dispatch:109 exec "$HA_RUNTIME" simulate_entrance_ring
  runtime:9 start|status|stop|simulate_entrance_ring
  RESULT=wiring proven without executing trigger
```

`start` and `stop` were not executed because they have listener side effects; their unchanged case blocks were validated by reading the wrapper.

## 6. PHASE C - pre-trigger gates

No deploy, reload, or restart was performed in this phase:

```text
DEPLOYED_SHA=45854c7f0aa201fef0eb5207464e2fb9791c345d
HA_CORE_CHECK=PASS
COMELIT_LOADED=true
LISTENER_RUNNING=true
LISTENER_READY=true
LISTENER_LAST_ERROR=null
SYNTHETIC_TRIGGER_COUNT=0
MEDIA_SESSION_COUNT=0
DOOR_ACTIONS=0
GATE_ACTIONS=0
```

The entrance camera status was inactive before the trigger:

```text
media_active=False
media_phase=inactive
remaining_seconds=0
listener_paused=False
video_packet_count=0
```

## 7. PHASE D - single synthetic trigger

The one authorized trigger was invoked exactly once through the restricted route:

```text
COMMAND=ssh -i ~/.ssh/id_ed25519_ct120_comelit -o IdentitiesOnly=yes -o BatchMode=yes hermes-comelit@192.168.1.85 comelit-ha-ring-test-simulate-entrance-ring
TRIGGER_REQUEST_UTC=2026-09-18T11:02:53Z
TRIGGER_VERB_RC=0
OK=true
ACTION=simulate_entrance_ring
RUNNING=true
LISTENER_READY=true
RING_OBSERVED=true
PRESS_PANEL_NOW=true
RING_DOOR=entrance
RING_SOURCE=synthetic_test
RING_KIND=CALL_INIT
RING_DIRECTION=DEVICE_TO_CLIENT
LAST_ERROR=
P13_EXECUTED=false
P14_EXECUTED=false
PHYSICAL_DOOR_ACTION=false
```

Derived result:

```text
SYNTHETIC_TRIGGER_COUNT=1
SYNTHETIC_RING_COUNT=1
RING_EVENT_COUNT=1
RING_EVENT_ID=863ec5c5-8111-4ff4-8308-6d30ce6609eb
RING_SYNTHETIC=true
DOOR_ACTIONS=0
GATE_ACTIONS=0
```

## 8. PHASE E/F - media, snapshot, and recording evidence

Timeline, UTC:

```text
2026-09-18T11:02:53Z custom_components.comelit.runtime WARNING
  Synthetic Comelit entrance ring emitted for bounded test:
  event_id=863ec5c5-8111-4ff4-8308-6d30ce6609eb

2026-09-18T11:03:05Z custom_components.comelit.media_transport INFO
  Comelit entrance media session ACTIVE

2026-09-18T11:03:05Z custom_components.comelit.media_transport INFO
  Comelit entrance media transport completed

2026-09-18T11:03:11Z custom_components.comelit.runtime INFO
  Comelit ring listener READY for persistent 3300s cycle
```

Media transport completion markers:

```text
P78_RTPC_SIGNALING_RESULT=PASS
P80_MEDIA_ACTIVE=true
P80_AUDIO_RTP_FORWARDING=PASS
P80_VIDEO_RTP_PORT=17899
P80_AUDIO_RTP_PORT=17808
P80_MEDIA_AUTO_CLOSE_3000MS=false
P80_MEDIA_LIFETIME_OWNER=<redacted>
P80_DEVICE_0002_GATES=PASS
P80_DEVICE_000A_GATES=PASS
P78_RTPC_GATES=PASS
P80_PREACTIVE_MEDIA_DEMUX=PASS
ICE_HOLDER_STOP=true
PSEUDOTCP_GRACEFUL_CLOSE_COMPLETE=true
PSEUDOTCP_GRACEFUL_CLOSE_TIMEOUT=false
PSEUDOTCP_NOTIFY_PACKET_CLASS=EXPECTED_TERMINAL_SHUTDOWN
P116_VIDEO_COUNT=0
P116_VIDEO_PT_SET=NONE
P116_VIDEO_SPS_COUNT=0
P116_VIDEO_PPS_COUNT=0
P116_VIDEO_MARKER_COUNT=0
P116_VIDEO_SSRC_COUNT=0
P116_AUDIO_COUNT=5
P116_AUDIO_FIRST_SEQ=27859
P116_AUDIO_LAST_SEQ=27863
P116_AUDIO_FIRST_MONOTONIC_MS=1084094123
P116_AUDIO_LAST_MONOTONIC_MS=1084094196
P116_AUDIO_PT_SET=8
media_native_binary_sha256_mismatch=0
```

Derived media facts from these markers:

```text
MEDIA_SESSION_COUNT=1
MEDIA_SESSION_LIFETIME_SECONDS_APPROX=0.18
VIDEO_RTP_PACKETS=0
AUDIO_RTP_PACKETS=5
AUDIO_RTP_SPAN_MS_APPROX=73
P80_VIDEO_RTP_FORWARDING_MARKER=ABSENT
SECOND_MEDIA_SESSION=false
```

Camera recorder samples in order:

```text
2026-09-18T11:03:05.667Z media_active=True media_phase=active listener_paused=True remaining_seconds=600 video_recovery_shim_running=True video_packet_count=0 audio_packet_count=0 hls_provider_present=False
2026-09-18T11:03:05.675Z media_active=False media_phase=stopping listener_paused=True remaining_seconds=0 video_recovery_shim_running=True video_packet_count=0 audio_packet_count=0 hls_provider_present=False
2026-09-18T11:03:05.686Z media_active=False media_phase=stopping listener_paused=True hls_provider_present=False
2026-09-18T11:03:05.851Z media_active=False media_phase=stopping listener_paused=True video_packet_count=0 audio_packet_count=1 hls_provider_present=False
```

Required interpretation:

- One and only one media session was observed.
- The media session ended in about 0.18 s.
- Video RTP count was zero.
- Audio RTP count was five packets spanning about 73 ms.
- No `P80_VIDEO_RTP_FORWARDING` marker appeared.
- `hls_provider_present=False` for every sample, so HA Stream did not expose an HLS provider in the read-only samples.
- No `Comelit ring media lifecycle failed`, no `Comelit snapshot loop failed`, no native-binary mismatch, and no Comelit WARNING/ERROR other than the synthetic-ring log pair were observed.

Snapshot and recording artifacts are not directly observable from the restricted read-only channel. The ring media code logs failure paths such as missing HA Stream recording API, snapshot loop failure, media lifecycle failure, release failure, and cleanup failure (`custom_components/comelit/ring_media.py:217`-`custom_components/comelit/ring_media.py:220`, `custom_components/comelit/ring_media.py:392`-`custom_components/comelit/ring_media.py:408`, `custom_components/comelit/ring_media.py:424`-`custom_components/comelit/ring_media.py:434`), but no success-path log line exposes snapshot sequence, retained file hash, recording state, or probed recording duration. `comelit_snapshot_updated` and `comelit_recording_complete` are HA bus events with no entity mirror exposed by the restricted gateway. Therefore:

```text
SNAPSHOT_EVENT_COUNT=UNPROVEN
FINAL_SNAPSHOT_RETAINED=UNPROVEN
RECORDING_STATE=UNPROVEN
RECORDING_PROBED_DURATION_SECONDS=NONE
RECORDING_VIDEO_STREAM_PRESENT=UNPROVEN
UNPROVEN_REASON=PENDING_OPERATOR_RELAY
```

The single trigger was already consumed, so these cannot be re-measured by another trigger in this run.

## 9. PHASE G - teardown and listener restore

Post-trigger status observations:

```text
2026-09-18T11:04:39Z RUNNING=true LISTENER_READY=true LAST_ERROR=
2026-09-18T11:04:51Z RUNNING=true LISTENER_READY=true LAST_ERROR=
```

The listener READY line after teardown was observed at `2026-09-18T11:03:11Z`. The first last-in-window camera sample was at the teardown instant: `media_active=False`, `media_phase=stopping`, `listener_paused=True`.

The continuing read-only capture then observed a clean post-teardown idle sample:

```text
2026-09-18T11:05:43Z camera.comelit_entrance:
media_active=False
media_phase=inactive
listener_paused=False
video_packet_count=0
audio_packet_count=0
hls_provider_shim_present=False
video_recovery_shim_running=False
remaining_seconds=0
```

This clean idle sample proves `MEDIA_TEARDOWN=PASS` and `LISTENER_READY_AFTER_MEDIA=PASS` in addition to the two status observations and the post-teardown `listener READY` line.

`RING_OBSERVED=false` in both later status observations is expected after supervisor starts a new listener cycle: `ComelitRingRuntime.async_start()` clears `_last_ring_event` and `_last_error` (`custom_components/comelit/runtime.py:314`-`custom_components/comelit/runtime.py:324`). The ring was observed as true inside the trigger response at `2026-09-18T11:02:53Z`.

```text
MEDIA_TEARDOWN=PASS
LISTENER_READY_AFTER_MEDIA=PASS
DOOR_ACTIONS=0
GATE_ACTIONS=0
```

## 10. Gate table

| Gate | Value | Evidence label | Evidence |
| --- | --- | --- | --- |
| `CT120_RUNTIME_WRAPPER_CHANGED` | true | `PROVEN_OBSERVED` | Runtime whitelist changed exactly one line to add `simulate_entrance_ring`; sha256 after `37938f4ce76abeb268f92e34a388bf03dee6d8f808a62d487d32c29e4009c65c`. |
| `CT120_DISPATCH_WRAPPER_CHANGED` | true | `PROVEN_OBSERVED` | Dispatcher added exactly one case for `comelit-ha-ring-test-simulate-entrance-ring`; sha256 after `5c082fe54e67d78cb8c9443753663e7592940f0e5850193c6888bbb405146dd7`. |
| `CT120_WRAPPER_VALIDATION` | PASS | `PROVEN_OBSERVED` | status worked, unknown restricted verb denied, bogus runtime action rejected before curl, wiring proven without trigger. |
| `DEPLOYED_SHA` | `45854c7f0aa201fef0eb5207464e2fb9791c345d` | `PROVEN_OBSERVED` | Pre-trigger gate observed already activated deployment. |
| `DEPLOY_COUNT` | 0 | `PROVEN_OBSERVED` | No deploy authorized or performed in this phase. |
| `HA_RELOADS` | 0 | `PROVEN_OBSERVED` | No reload authorized or performed. |
| `HA_RESTARTS` | 0 | `PROVEN_OBSERVED` | No restart authorized or performed in this phase. |
| `LISTENER_READY_BEFORE_TRIGGER` | PASS | `PROVEN_OBSERVED` | Pre-trigger status had listener running and ready. |
| `SYNTHETIC_TRIGGER_COUNT` | 1 | `PROVEN_OBSERVED` | Single restricted-route invocation returned rc 0. |
| `SYNTHETIC_RING_COUNT` | 1 | `PROVEN_OBSERVED` | Trigger response showed `RING_OBSERVED=true`; runtime emitted synthetic ring log. |
| `RING_EVENT_COUNT` | 1 | `PROVEN_OBSERVED` | One synthetic event id observed. |
| `RING_SYNTHETIC` | true | `DERIVED` | Runtime synthetic path sets `synthetic=True` and source `synthetic_test` (`custom_components/comelit/runtime.py:277`-`custom_components/comelit/runtime.py:285`); response had `RING_SOURCE=synthetic_test`. |
| `MEDIA_SESSION_COUNT` | 1 | `PROVEN_OBSERVED` | One `Comelit entrance media session ACTIVE` line and no second session marker. |
| `SNAPSHOT_EVENT_COUNT` | UNPROVEN | `UNPROVEN` | Bus event count is not exposed by restricted gateway; relay pending. |
| `SNAPSHOT_SEQUENCE_MONOTONIC` | NOT_REACHED | `NOT_REACHED` | Snapshot sequence values were not observable; no relay yet. |
| `FINAL_SNAPSHOT_RETAINED` | UNPROVEN | `UNPROVEN` | Retained artifact not readable through restricted channel; relay pending. |
| `RECORDING_COUNT` | 1 | `DERIVED` | One ring media lifecycle was started, but recording terminal event payload is not visible through restricted channel. |
| `RECORDING_TARGET_SECONDS` | 20 | `PROVEN_OBSERVED` | Authorization and code constant (`custom_components/comelit/const.py:47`). |
| `RECORDING_STATE` | UNPROVEN | `UNPROVEN` | Recording completion payload and artifact are not visible through restricted channel; relay pending. |
| `RECORDING_VIDEO_STREAM_PRESENT` | UNPROVEN | `UNPROVEN` | Must be probed from retained artifact; relay pending. |
| `ZERO_VIDEO_RTP` | true | `PROVEN_OBSERVED` | Transport marker `P116_VIDEO_COUNT=0`; no video forwarding marker. |
| `MEDIA_TEARDOWN` | PASS | `PROVEN_OBSERVED` | Transport completed, listener READY returned, later clean idle camera sample observed. |
| `LISTENER_READY_AFTER_MEDIA` | PASS | `PROVEN_OBSERVED` | READY line at `2026-09-18T11:03:11Z`, later status observations, and clean idle sample at `2026-09-18T11:05:43Z`. |
| `DOOR_ACTIONS` | 0 | `PROVEN_OBSERVED` | Trigger response `PHYSICAL_DOOR_ACTION=false`; no Door event/action authorized. |
| `GATE_ACTIONS` | 0 | `PROVEN_OBSERVED` | No Gate action authorized or observed. |
| `AUTOMATIC_RETRY` | false | `PROVEN_OBSERVED` | No retry performed. |
| `SECOND_TRIGGER` | false | `PROVEN_OBSERVED` | Single trigger consumed the authorization. |
| `SECOND_MEDIA_SESSION` | false | `PROVEN_OBSERVED` | No second media marker. |
| `R30H_E_EXECUTED` | false | `PROVEN_OBSERVED` | No R30H-E path executed. |

## 11. Deliberate zeros

```text
DEPLOY_COUNT=0
HA_RELOADS=0
HA_RESTARTS=0
HOST_REBOOTS=0
SUPERVISOR_REBOOTS=0
DOOR_ACTIONS=0
GATE_ACTIONS=0
AUTOMATIC_RETRY=false
SECOND_TRIGGER=false
SECOND_MEDIA_SESSION=false
R30H_E_EXECUTED=false
```

These are deliberate zeros. Accepted main was already deployed and activated, so no deploy/reload/restart was authorized. Door and Gate actions were out of scope and remained zero. The one trigger was consumed; no second trigger or second media session was allowed.

## 12. Limitations

The restricted Home Assistant gateway exposes only `status`, `check`, `logs`, `logs-follow`, `deploy`, `rollback`, and `restart`. It does not expose HA bus event payloads, retained media directory listing, hashes, or media probing. Therefore snapshot sequence, final snapshot retention, recording state, probed duration, and recording video stream presence remain `UNPROVEN` until operator relay reads the event directory.

No raw media, credentials, bearer tokens, or private payloads are included in this report. Marker owner fields are redacted as `<redacted>`.

## 13. Next steps

Read-only operator relay for the event directory:

```text
EVENT_DIR=/media/comelit/rings/863ec5c5-8111-4ff4-8308-6d30ce6609eb/
ls -l /media/comelit/rings/863ec5c5-8111-4ff4-8308-6d30ce6609eb/
sha256sum /media/comelit/rings/863ec5c5-8111-4ff4-8308-6d30ce6609eb/latest.jpg /media/comelit/rings/863ec5c5-8111-4ff4-8308-6d30ce6609eb/recording.mp4
ffprobe -v error -show_entries format=duration -of default=nw=1:nk=1 /media/comelit/rings/863ec5c5-8111-4ff4-8308-6d30ce6609eb/recording.mp4
ffprobe -v error -select_streams v -show_entries stream=codec_type -of default=nw=1:nk=1 /media/comelit/rings/863ec5c5-8111-4ff4-8308-6d30ce6609eb/recording.mp4
```

Separate offline corrective candidate, not fixed here:

```text
CANDIDATE_DEFECT_NOT_PROVEN=HAStreamMediaProvider.async_record_mp4_OR_RingMediaCoordinator_may_close_media_session_before_video_arrives_when_local_SDP_has_no_video_yet
```

Motivation: the recorder/media lifecycle returned after about 0.18 s, before any video RTP arrived; `P116_VIDEO_COUNT=0`; no `P80_VIDEO_RTP_FORWARDING` marker appeared; `hls_provider_present=False` for every sample. This candidate is not proven because artifact relay is pending and no code was changed during the live canary.

## 14. Final scalar block

```text
=== COMELIT MVP1 SYNTHETIC RING CANARY ===
CT120_RUNTIME_WRAPPER_CHANGED=true
CT120_DISPATCH_WRAPPER_CHANGED=true
CT120_WRAPPER_VALIDATION=PASS
DEPLOYED_SHA=45854c7f0aa201fef0eb5207464e2fb9791c345d
DEPLOY_COUNT=0
HA_RELOADS=0
HA_RESTARTS=0
LISTENER_READY_BEFORE_TRIGGER=PASS
SYNTHETIC_TRIGGER_COUNT=1
SYNTHETIC_RING_COUNT=1
RING_EVENT_COUNT=1
RING_EVENT_ID=863ec5c5-8111-4ff4-8308-6d30ce6609eb
RING_SYNTHETIC=true
MEDIA_SESSION_COUNT=1
SNAPSHOT_EVENT_COUNT=UNPROVEN
SNAPSHOT_SEQUENCE_FIRST=NONE
SNAPSHOT_SEQUENCE_LAST=NONE
SNAPSHOT_SEQUENCE_MONOTONIC=NOT_REACHED
SNAPSHOT_AVERAGE_INTERVAL_SECONDS=NONE
FINAL_SNAPSHOT_RETAINED=UNPROVEN
RECORDING_COUNT=1
RECORDING_TARGET_SECONDS=20
RECORDING_STATE=UNPROVEN
RECORDING_PROBED_DURATION_SECONDS=NONE
RECORDING_VIDEO_STREAM_PRESENT=UNPROVEN
MEDIA_TEARDOWN=PASS
LISTENER_READY_AFTER_MEDIA=PASS
DOOR_ACTIONS=0
GATE_ACTIONS=0
AUTOMATIC_RETRY=false
SECOND_TRIGGER=false
SECOND_MEDIA_SESSION=false
R30H_E_EXECUTED=false
RESULT=FAIL_SNAPSHOT
RESULT_BRANCH=docs/mvp1-synthetic-ring-canary-result
RESULT_REMOTE_HEAD=<orchestrator-published>
RESULT_PR=none
=== END COMELIT MVP1 SYNTHETIC RING CANARY ===
```
