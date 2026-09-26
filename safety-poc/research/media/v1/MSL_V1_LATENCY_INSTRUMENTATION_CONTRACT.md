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

## Dry Run

`MSL_DRY_RUN=YES` is an offline, host-independent control-flow check. It cannot be combined with `MSL_LIVE_RUN=YES`; that conflict exits before any control flow that could reach a real media attempt.

The dry run does not require `/root`, `/usr/local/sbin`, chroot, musl, the CT120 base wrapper, the OAuth status helper, the real HA webhook, or any Comelit endpoint. `post_control()` writes canned listener status/stop/start JSON locally, the build phase is marked `DRY_RUN`, and the synthetic session log emits the documented startup markers through T18 plus representative inherited markers such as `ICE_GATHER=PASS`, `P80_MEDIA_ACTIVE=true`, and `P80_VIDEO_RTP_FORWARDING=PASS`.

Successful dry-run output includes `MSL_DRY_RUN_COMPLETED=true`, `MSL_DRY_RUN_REACHED_FINAL_SUMMARY=true`, `LIVE_INVOCATIONS=0`, `MSL_DRY_RUN_COMELIT_INTERACTION=0`, `MSL_DRY_RUN_HA_INTERACTION=0`, `DOOR_ACTIONS_SENT=0`, and `GATE_ACTIONS_SENT=0`.

Corrective-2 extends dry-run coverage to the materialized wrapper itself. The runner creates a shebang'd stub base wrapper and a shebang'd stub helper, materializes the candidate wrapper with the same instrumentation function used by the live path, and executes that wrapper. Required dry-run markers include `MSL_DRY_RUN_WRAPPER_EXECUTED=true`, `MSL_DRY_RUN_WRAPPER_RC=0`, `MSL_WRAPPER_SHEBANG_LINE=1`, and `MSL_WRAPPER_FIRST_LINE_GATE=PASS`.

Wrapper instrumentation is inserted after the shebang line and any immediately following comment block; it is never prepended before `#!`. Live runs print `MSL_WRAPPER_FIRST_LINE`, `MSL_WRAPPER_SHEBANG_LINE`, and `MSL_WRAPPER_FIRST_LINE_GATE`, then print a bounded/redacted tail of the wrapper output so early wrapper failures are visible to the orchestrator without exposing raw SDP, tokens, or media bytes. Dry-run-only markers are emitted only when `MSL_DRY_RUN=YES`.

## Clock Base Ownership

Corrective-3 moves the shared clock base outside `/run/comelit-media`, because the base cloud wrapper clears that media run directory before launching the helper. Live runs use `MSL_CLOCK_DIR=/run/comelit-msl` by default and write `MSL_CLOCK_BASE_PATH=/run/comelit-msl/msl-clock-base`. The runner emits `MSL_CLOCK_BASE_PATH` and `MSL_CLOCK_BASE_WRITTEN_MONO_MS` in the final block.

Dry-run and self-test stubs deliberately reproduce the destructive wrapper step by wiping their media run directory before invoking the stub helper. The clock file is written outside that wiped directory, and successful proof emits `MSL_CLOCK_BASE_SURVIVES_WRAPPER_RM=true` plus `MSL_DRY_RUN_SYNTHETIC_OFFER_WRITTEN=true`.

Synthetic summary deltas are derived from marker differences, not hardcoded. The focused test checks `MSL_START_TO_FIRST_RTP_MS == T17 - T03` and `MSL_START_TO_DECODABLE_VIDEO_MS == T18 - T03`.

`MSL_SELFTEST=YES` is a no-network harness check for Hermes before live attempts. It reuses the destructive wrapper/helper stub path and emits `MSL_SELFTEST_COMPLETED=true`, `MSL_SELFTEST_HA_INTERACTION=0`, `MSL_SELFTEST_COMELIT_INTERACTION=0`, `MSL_SELFTEST_CLOCK_BASE_READABLE=true`, `MSL_SELFTEST_SYNTHETIC_OFFER_WRITTEN=true`, and `MSL_SELFTEST_MARKERS_OBSERVED=<n>`.
