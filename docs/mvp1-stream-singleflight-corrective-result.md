# Comelit MVP1 stream single-flight corrective result

## Summary

```text
TASK_ID=COMELIT-MVP1-STREAM-SINGLEFLIGHT-CORRECTIVE
MODE=STRICTLY_OFFLINE_CODEX_CHILD
DATE_UTC=2026-09-18
RACE_VERDICT=RACE_PROVEN_CODE_LEVEL
FIX_APPLIED=true
RESULT=PASS_OFFLINE_STREAM_SINGLEFLIGHT_READY
```

## Code-level race verdict

`RACE_PROVEN_CODE_LEVEL`.

Production wiring creates one `HAStreamMediaProvider` and passes that same object as both `snapshot_provider` and `recording_provider` (`custom_components/comelit/__init__.py:182`-`custom_components/comelit/__init__.py:191`). The ring lifecycle starts a snapshot task and immediately awaits recording on the same event loop (`custom_components/comelit/ring_media.py:380`-`custom_components/comelit/ring_media.py:389`). The snapshot loop calls `async_capture_jpeg()` (`custom_components/comelit/ring_media.py:453`-`custom_components/comelit/ring_media.py:454`), while recording calls `async_record_mp4()` (`custom_components/comelit/ring_media.py:488`-`custom_components/comelit/ring_media.py:492`).

Both public methods enter `_async_create_stream()` (`custom_components/comelit/ring_media.py:192`-`custom_components/comelit/ring_media.py:196`, `custom_components/comelit/ring_media.py:218`-`custom_components/comelit/ring_media.py:221`). The construction path awaits `_async_stream_source()` and dynamic camera settings before assigning `_stream` (`custom_components/comelit/ring_media.py:172`-`custom_components/comelit/ring_media.py:189`); `_async_stream_source()` itself awaits the executor job checking local SDP readiness (`custom_components/comelit/ring_media.py:151`-`custom_components/comelit/ring_media.py:160`). Without a single-flight guard around that awaited region, two concurrent callers can both observe `_stream is None`, both construct a `Stream`, both append it to HA stream data, and only then assign `_stream`.

## Fix

`HAStreamMediaProvider` now has a lazy `asyncio.Lock` matching the existing camera style. `_async_create_stream()` keeps the fast `_stream` return, creates/acquires the lock, re-checks `_stream` inside the lock, then performs source/settings resolution, `Stream` construction, registration, and assignment exactly once (`custom_components/comelit/ring_media.py:147`-`custom_components/comelit/ring_media.py:189`).

No changes were made to `media_transport.py`, native helpers, P116 behavior, R30H-E, repeat-`0x001A`, protocol signaling, the 600 s media hard limit, or the 20 s recording target.

## Behavioral test

Added `safety-poc/tests/test_mvp1_stream_singleflight_corrective.py`.

The test uses `async_capture_jpeg()` and `async_record_mp4()` concurrently on the same provider. A controlled async barrier holds the first call inside the awaited stream-source step while the second `_async_create_stream()` call enters, then releases the barrier. Assertions prove:

```text
CONCURRENT_CREATE_CALLS=2
STREAM_CONSTRUCTOR_COUNT=1
RETURNED_STREAM_OBJECT_IDENTICAL=true
SNAPSHOT_AND_RECORDING_SHARE_STREAM=true
ASYNC_CLOSE_SINGLE_STREAM=PASS
```

The behavioral assertions are at `safety-poc/tests/test_mvp1_stream_singleflight_corrective.py:151`-`safety-poc/tests/test_mvp1_stream_singleflight_corrective.py:180`.

## Secondary audit

Using only the supplied upstream provenance:

`homeassistant/components/stream/__init__.py` at ref `2026.9.2`, sha256 `f63cbbfa0d286fadf11c680b193942ad0cb0b3f7a1ba035a5f99e3d950b4bd95`, shows `Stream.start()` has its own start/stop lock and spawns a worker thread; `Stream.async_record()` raises `HomeAssistantError("Stream already recording to ...")` only when a recorder output already exists on that same `Stream`; it adds `RECORDER_PROVIDER`, calls `await self.start()`, and only waits for the first HLS segment in the lookback branch when an HLS provider output exists on that same `Stream`. `async_get_image` is a method on the same upstream `Stream`.

`homeassistant/components/stream/recorder.py` at ref `2026.9.2`, sha256 `7c24fbeff3714b2a6ee637a9c35a7d92e5229faad0464aab7e67712d75562006`, shows recorder output muxes to `<video_path>.tmp` and renames to `video_path`; a leftover `.tmp` alone is not a retained recording artifact.

Candidate classifications:

```text
SECOND_INDEPENDENT_CAUSE=false
TWO_STREAMS_FIXED_RTP_PORTS_SECOND_WORKER_IMMEDIATE_RETURN=NOT_PROVEN_OFFLINE
SHARED_STREAM_MAKES_HLS_LOOKBACK_REACHABLE=true_if_HLS_PROVIDER_EXISTS_ON_SHARED_STREAM
HLS_LOOKBACK_SESSION_LIFETIME_CHANGE=EXPECTED_TO_WAIT_FOR_FIRST_SEGMENT_WHEN_HLS_EXISTS_BUT_NOT_PROVEN_WITHOUT_UPSTREAM_RUNTIME
```

The two-Stream/fixed-RTP-port collision is a plausible mechanism for the observed ~0.18 s lifetime and zero-video outcome, but this child cannot prove the worker failure mode offline from repository code plus the supplied upstream excerpts alone. No different independently proven root cause was found.

The shared-Stream fix makes the upstream HLS lookback branch reachable when snapshot/image work has created or caused an HLS provider on the same `Stream`, because recording no longer runs on a separate Stream object whose outputs lack the snapshot-side HLS provider. Whether this changes the actual live session lifetime remains `NOT_PROVEN_OFFLINE` until the canary is rerun.

## Observability follow-up

`RingMediaCoordinator.status()` exposes `snapshot_event_count`, `snapshot_sequence_last`, `snapshot_average_interval_seconds`, `snapshot_path`, `recording_event_count`, and `recording_result` (`custom_components/comelit/ring_media.py:287`-`custom_components/comelit/ring_media.py:312`). `ComelitRingRuntime.status()` embeds that dictionary under `ring_media` (`custom_components/comelit/runtime.py:198`-`custom_components/comelit/runtime.py:220`). `test_control.py` starts from `runtime.status()` and returns that payload for `start`, `status`, `simulate_entrance_ring`, and `stop` (`custom_components/comelit/test_control.py:16`-`custom_components/comelit/test_control.py:31`, `custom_components/comelit/test_control.py:57`-`custom_components/comelit/test_control.py:94`).

Therefore the integration already exposes these fields through the HA test-control JSON response. The remaining drop is classified as `ct120-wrapper`, based on the supplied operator evidence that `/usr/local/sbin/comelit-ha-ring-runtime` prints only the fixed key list. No HA API extension or repository production change is required for this follow-up.

## Gates

Sandbox run:

```text
python3 scripts/static_safety_check.py
STATIC_SAFETY_CHECK=PASS
SOURCE_FILES_SCANNED=29

python3 -m compileall -q ../custom_components/comelit
COMPILEALL=PASS

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=$PWD/src python3 -m unittest tests/test_mvp1_stream_singleflight_corrective.py
Ran 1 test in 0.003s
OK

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=$PWD/src python3 -m unittest discover -s tests
Ran 1564 tests in 34.374s
FAILED failures=1 errors=2 skipped=5
```

Sandbox full-suite non-regression classifications:

```text
test_p116_provenance_binary_analysis.P116ProvenanceBinaryAnalysisTests.test_committed_build_metadata_records_historical_non_runtime_mismatch=NOT_A_STREAM_SINGLEFLIGHT_REGRESSION_NATIVE_BINARY_MODE_755_VS_775
test_p116_r29i_preopen_idle_and_sink_ownership.P116R29IPreOpenIdleAndSinkOwnership.test_nonzero_datagram_sink_materializes_final_counter_after_exit=NOT_A_STREAM_SINGLEFLIGHT_REGRESSION_UDP_SINK_SANDBOX_ERROR
test_p116_r29i_preopen_idle_and_sink_ownership.P116R29IPreOpenIdleAndSinkOwnership.test_zero_datagram_sink_materializes_final_counter_after_exit=NOT_A_STREAM_SINGLEFLIGHT_REGRESSION_UDP_SINK_SANDBOX_ERROR
```

Host-authoritative run supplied by orchestrator:

```text
focused: PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=$PWD/src python3 -m unittest tests.test_mvp1_stream_singleflight_corrective
Ran 1 test in 0.003s
OK

full: PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=$PWD/src python3 -m unittest discover -s tests
Ran 1564 tests in 30.006s
FAILED failures=1 skipped=1
only failure=test_p116_provenance_binary_analysis...NATIVE_BINARY_MODE_755_VS_775

baseline accepted main 0fffbf5efcc0bef04ce2e07f2b70d805724df409, measured earlier at 45854c7f with same component tree
Ran 1563 tests
FAILED failures=1 skipped=1
branch_delta=+1 new test

static: STATIC_SAFETY_CHECK=PASS SOURCE_FILES_SCANNED=29
compile: COMPILEALL=PASS
```

## Falsification evidence

```text
TEST_AGAINST_UNFIXED_CODE=FAILED
AssertionError: 2 != 1
TEST_AGAINST_FIXED_CODE=OK
```

The same test module fails against accepted main with unfixed `ring_media.py` because two `Stream` constructors are observed under the forced concurrent window, and passes with the single-flight guard. Therefore `STREAM_CONSTRUCTOR_COUNT=1` is a derived behavioral measurement, not a textual assertion.

## Required gates

```text
STREAM_CREATE_SINGLE_FLIGHT=PASS
CONCURRENT_STREAM_CREATE_TEST=PASS
STREAM_CONSTRUCTOR_COUNT=1
RETURNED_STREAM_OBJECT_IDENTICAL=true
SNAPSHOT_RECORDING_SHARED_STREAM=PASS
ASYNC_CLOSE_SINGLE_STREAM=PASS
RECORDING_TARGET_SECONDS=20
MEDIA_SESSION_CODE_UNCHANGED=PASS
MEDIA_TRANSPORT_CODE_UNCHANGED=PASS
NATIVE_CODE_UNCHANGED=PASS
R30H_E_EXECUTED=false
COMELIT_LIVE_EXECUTED=false
HA_DEPLOYED=false
HA_RELOADED=false
HA_RESTARTED=false
SYNTHETIC_TRIGGER_COUNT=0
DOOR_ACTIONS=0
GATE_ACTIONS=0
```

`MEDIA_SESSION_CODE_UNCHANGED` evidence: orchestrator verified `git diff --name-only origin/main -- custom_components/comelit/media_session.py` is empty.

`MEDIA_TRANSPORT_CODE_UNCHANGED` evidence: orchestrator verified `git diff --name-only origin/main -- custom_components/comelit/media_transport.py custom_components/comelit/camera.py custom_components/comelit/__init__.py custom_components/comelit/const.py` is empty.

`NATIVE_CODE_UNCHANGED` evidence: orchestrator verified `git diff --name-only origin/main -- custom_components/comelit/native` is empty; the only changed component file is `custom_components/comelit/ring_media.py`.
