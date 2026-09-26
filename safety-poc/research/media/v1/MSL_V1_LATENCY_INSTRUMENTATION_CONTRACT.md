# MSL-V1 Latency Instrumentation Contract

MSL-V1 composes `entrance_p116_r65_production_media_refresh_transform.py`; it does not fork the R65/P27/P80/P106 chain and does not add ICE, PseudoTCP, CTPP, RTPC, Door, Gate, retry, or second-session behavior.

All `MSL_TNN_*_MONO_MS` values are milliseconds elapsed from the single monotonic base written by the runner to `MSL_CLOCK_BASE_FILE`. The helper refuses to run if that file is absent, unreadable, malformed, or non-positive and emits `MSL_CLOCK_BASE_MISSING=true`.

`MSL_START_REFERENCE=T03_NATIVE_MEDIA_HELPER_PROCESS_START`

## Stage Sites

T00 is emitted by `ct120_run_msl_v1_baseline_live.sh` at runner entry after the clock base is written.

T01 is emitted by the runner immediately before the listener stop webhook.

T02 is emitted by the runner only after the stopped listener runtime status is confirmed.

T03 is emitted in generated C `main()` after `msl_load_clock_base()` succeeds and before helper side effects.

T04 is emitted at the existing `ICE_GATHER=PASS` local SDP offer-ready site.

T05 is emitted by the runner/wrapper at the OAuth access-token-available boundary; the runner also emits the preflight token-availability marker before stopping the listener.

T06 is emitted by the instrumented wrapper immediately before the cloud P2P request call site.

T07 is emitted by the instrumented wrapper when the remote SDP write succeeds.

T08 is emitted at the existing `ICE_CONNECTED=PASS` / `ICE_READY=PASS` site.

T09 is emitted at the existing `PSEUDOTCP_OPEN=PASS` site.

T10 is emitted at the existing `VIP_UAUT_OPEN_RESPONSE=PASS` site.

T11 is emitted at the existing `V4_CTPP_INITIAL_ACK_OBSERVED=true` registration-ready site.

T12 is emitted at `P78_RTPC_OPEN_2_SENT=PASS`, the second existing media OPEN control send. Existing R65 still emits `P78_RTPC_OPEN_1_SENT=PASS` separately; MSL keeps one required T12 marker so the marker key remains single-emission.

T13 is emitted at the existing initial `P78_RTPC_CLIENT_001A_SENT=PASS` site.

T14 is emitted at the existing `P80_DEVICE_ACK_001A_OBSERVED=PASS` structural ACK/media-acceptance site.

T15 is emitted at the existing `P80_MEDIA_ACTIVE=true` site.

T16 is emitted at the first audio RTP forwarding site, before `P80_AUDIO_RTP_FORWARDING=PASS`.

T17 is emitted at the first video RTP forwarding site, before `P80_VIDEO_RTP_FORWARDING=PASS`.

T18 is emitted when H.264 observation has seen SPS, PPS, and IDR evidence in the existing RTP classifier.

T19-T24 are not part of this child. Reason: HA Stream worker, HLS part/segment/playlist, and local HLS HTTP fetch occur in the Home Assistant stream/HLS pipeline, while this child instruments only the CT120 cold-start native helper and cloud-wrapper path.

## Summary

The helper emits `MSL_START_TO_FIRST_RTP_MS`, `MSL_START_TO_DECODABLE_VIDEO_MS`, `MSL_DELTA_T08_T09_MS`, `MSL_DELTA_T09_T11_MS`, `MSL_DELTA_T11_T15_MS`, and `MSL_DELTA_T15_T17_MS` directly from recorded one-shot marker values. Cross-boundary deltas involving T05-T07 are recomputed by Hermes from the combined runner/wrapper/helper log using the same monotonic base.

The runner always emits safety closure scalars: `DOOR_ACTIONS_SENT=0`, `GATE_ACTIONS_SENT=0`, `PHYSICAL_RING_ACTIONS=0`, `AUTOMATIC_PROTOCOL_RETRY=false`, `SECOND_MEDIA_SESSION=false`, `MEDIA_TEARDOWN`, `CAMPAIGN_PROCESSES_REMAINING`, and `RTP_SINK_PORTS_REMAINING`.
