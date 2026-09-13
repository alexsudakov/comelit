# P116 R25 Recovery-Point Live Validation

TASK_ID=COMELIT-P116-R25-RECOVERY-POINT-LIVE-VALIDATION
MODE=REDACTED_FACT_RECORD
LIVE_FACT_SCOPE=ONE_SESSION_ONE_HA_VERSION_ONE_CLIENT

## Verified Live Facts

```text
MAIN_SHA=b96ad1690e216f8e81934314470259b1abcc495d
DEPLOYED_SHA_BEFORE=ffb469ce7b4def6cda5d320387337c1e51df6be6
DEPLOYED_SHA_AFTER=b96ad1690e216f8e81934314470259b1abcc495d
DEPLOY=PASS
HA_CORE_CHECK=PASS
HA_RESTART_USED=1
LISTENER_READY_AFTER_RESTART=true
MEDIA_SESSION_USED=1
VALID_R25_WINDOW=true
RTP_HA_STREAM_OVERLAP=true
VISIBLE_VIDEO=true
VISIBLE_VIDEO_IS_LIVE=true
VIDEO_PACKET_COUNT_MAX=1650
VIDEO_RECOVERY_SHIM_RUNNING_DURING_LIVE=true
VIDEO_RECOVERY_INPUT_PACKETS_MAX=1670
VIDEO_RECOVERY_OUTPUT_PACKETS_MAX=1678
VIDEO_RECOVERY_ELIGIBLE_NONIDR_I_COUNT=8
VIDEO_RECOVERY_INJECTED_COUNT=8
VIDEO_RECOVERY_EXISTING_RECOVERY_COUNT=0
VIDEO_RECOVERY_IDR_COUNT=2
VIDEO_RECOVERY_UNSUPPORTED_PACKET_COUNT=0
VIDEO_RECOVERY_MALFORMED_COUNT=0
VIDEO_RECOVERY_LAST_ERROR=None
RECOVERY_OUTPUT_INPUT_DELTA=8
RECOVERY_COUNTER_INVARIANT=PASS
HA_STREAM_CREATED=true
HA_STREAM_AVAILABLE=true
HA_STREAM_START_WORKER_COUNT=1
HA_STREAM_WORKER_ERROR_COUNT=unknown
HA_STREAM_CONTAINER_FORMAT=sdp
HA_STREAM_VIDEO_CODEC=h264
HLS_PROVIDER_PRESENT=true
HLS_SEGMENT_COUNT=4
HLS_PART_COUNT=34
HLS_FIRST_PART_HAS_KEYFRAME=true
HLS_FIRST_SEGMENT_COMPLETE=true
HLS_SECOND_SEGMENT_CREATED=true
HLS_HTTP_ROUTING_PROVEN=true
HLS_HTTP_MASTER_STATUS=200
HLS_HTTP_MEDIA_STATUS=200
HLS_HTTP_INIT_STATUS=200
HLS_HTTP_PART_STATUS=200
HLS_INIT_BYTES=780
HLS_FIRST_PART_BYTES=44125
HLS_CODEC_STRING=avc1.42801e
WORKER_ERROR_COUNT_NOTE=unknown means "no error recorded yet", not zero and not a broken lookup
RTP_STOP_AFTER_SECONDS=34.9 (helper-side: P116_VIDEO_LAST_MONOTONIC_MS - P116_VIDEO_FIRST_MONOTONIC_MS = 34859 ms)
HELPER_RTP_INTEGRITY: P116_VIDEO_SEQ_GAPS=0 DUPLICATES=0 OUT_OF_ORDER=0 TIMESTAMP_REGRESSIONS=0 SSRC_COUNT=1 SSRC_CHANGES=0 PT_SET=99
HELPER_NAL_SHAPE: FUA_COUNT=1443 SINGLE_NAL_COUNT=227 SPS_COUNT=10 PPS_COUNT=10 MARKER_COUNT=893
HELPER_AUDIO: P116_AUDIO_COUNT=1750 AUDIO_PT_SET=8 (audio path unchanged)
TEARDOWN: media_active=false media_phase=inactive remaining_seconds=0 listener_paused=false video_recovery_shim_running=false
LISTENER_AFTER_SESSION: running=true listener_ready=true
MEDIA_SESSIONS_OBSERVED=1
D2_RECOVERY_POINT_FIX=LIVE_VALIDATED
D2_NON_IDR_RANDOM_ACCESS_MISMATCH=CONFIRMED_AS_PRACTICAL_ROOT_CAUSE_FOR_THIS_PATH
D1_CHANGED=false
LIVE_REQUIRED_FOR_D2_GOING_FORWARD=false
```

## Scope And Caveats

This conclusion is scoped to one live session on one Home Assistant version and one client: Chrome desktop. It is not proof for all browsers, devices, operating systems, Home Assistant versions, or Comelit panels.

This was not a controlled A/B experiment. The R22-era failure mode was observed on the same Home Assistant version and the same pipeline, and in R25 the recovery-point shim injection was present in the same valid window in which live video was visible. That makes the causal link strong for this path, but it is not a universal proof.

D1 is unchanged. Video RTP still stops about 35 seconds after media start, and that remains a separate workstream from the D2 recovery-point validation.

## Redaction Boundary

No token, HLS URL, endpoint URL, raw SDP, raw RTP, media payload, auth/session identifier, target identifier, peer address, SSRC value, sequence value, timestamp value, or raw remote IP is recorded here. This document records only bounded scalars and redacted state facts.
