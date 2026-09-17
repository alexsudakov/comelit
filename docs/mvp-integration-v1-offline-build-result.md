# Comelit MVP1 Integration Offline Build Result

TASK_ID=`COMELIT-MVP1-INTEGRATION-OFFLINE-BUILD`  
MODE=`OFFLINE_ONLY`  
BASE_SHA=`c9fff4e47bea3d0ec7d6a9aa6f36049931c5a643`  
BRANCH=`feat/mvp1-integration-offline-build`

## Source Audit

- `comelit_ring`: implemented. `EVENT_RING = "comelit_ring"` is defined in `custom_components/comelit/const.py:23`. `ComelitRingRuntime` parses a complete ring marker batch, adds `event_id` and `timestamp`, stores `_last_ring_event`, and fires `EVENT_RING` in `custom_components/comelit/runtime.py:673-684`.
- `camera.comelit_entrance`: implemented. `ENTRANCE_CAMERA_ENTITY_ID = "camera.comelit_entrance"` is defined in `const.py:135`; `ComelitEntranceCamera` assigns that entity id in `camera.py:246` and uses HA Stream stills in `camera.py:561-572`.
- `switch.comelit_entrance_camera`: implemented. `ENTRANCE_MEDIA_SWITCH_ENTITY_ID = "switch.comelit_entrance_camera"` is defined in `const.py:133`; `ComelitEntranceMediaSwitch.async_turn_on()` acquires the session manager with `reason="ha_switch"` in `switch.py:88-90`.
- `ComelitMediaSessionManager`: implemented. The manager is defined in `media_session.py:64`, enforces entrance-only media in `media_session.py:167-169`, pauses listener before transport start in `media_session.py:189-196`, and is created once per config entry in `__init__.py:170-178`.
- Camera snapshot path: missing before this task. Existing code could return a still from HA Stream, but had no stable per-event `/media/comelit/rings/<event_id>/latest.jpg`, no atomic latest replacement, and no `comelit_snapshot_updated` event.
- HA Stream recording capability: `PROVEN_UPSTREAM_SOURCE` for Home Assistant Core tag `2026.9.2`. Upstream `Stream.async_record(self, video_path: str, duration: int = 30, lookback: int = 5) -> None` exists, and `camera.record` delegates to `camera.async_create_stream()` then `stream.async_record(video_path, duration=..., lookback=...)`. The Comelit provider pre-checks HA path allowlist when available, calls that signature with `lookback=0`, measures recorder wall-clock time honestly, and remains fail-closed if the deployed HA runtime is missing or renames the method.
- `comelit_door_operation`: implemented. `EVENT_DOOR_OPERATION = "comelit_door_operation"` is defined in `const.py:25`; `_finalize_door_operation()` emits it in `runtime.py:307-321`; all completed `async_open_door()` paths return through it, including `runtime.py:348`, `runtime.py:362`, `runtime.py:388`, and `runtime.py:442`.
- Existing entrance/gate buttons: implemented. `button.py:39-43` registers entrance and gate button entities. Entrance press calls the shared runtime in `button.py:117-126`. Gate press is fail-closed and deliberately never calls runtime in `button.py:180-186`. Gate actuation remains unvalidated in `const.py:72-76`.

PR #155/#156 separation: reusable integration changes are the existing Door operation event finalizer/service path and media entities/session manager. Telegram package material, `telegram_bot.*`, and `comelit_ring_interaction` remain optional consumer/example artifacts and were not modified or used as MVP gates.

## Design

Added `custom_components/comelit/ring_media.py` as a focused coordinator instead of growing `runtime.py` or `camera.py`.

Rationale: `runtime.py` remains responsible for listener process parsing and event emission; `media_session.py` remains the one upstream session owner; `ring_media.py` owns per-ring artifact paths, snapshot refresh, recording terminalization, duplicate lifecycle suppression, and unload cancellation. The listener schedules the coordinator as a config-entry background task after firing `comelit_ring`, so ring reading is not blocked for 20 seconds.

The coordinator:

- uses only `ComelitMediaSessionManager.async_acquire(panel="entrance", reason="ring_media")`, so snapshot and recording share one upstream session;
- derives `/media/comelit/rings/<event_id>/latest.jpg` and `recording.mp4` only from a safe event id;
- writes snapshots with temp file plus `os.replace`;
- emits `comelit_snapshot_updated` only after the JPEG is available;
- runs a serial latest-only snapshot loop with no queue/backlog;
- emits one `comelit_recording_complete` terminal event for completed/truncated/failed states;
- classifies recording state from measured recorder wall time: completed only when the recorder returns at or beyond the target, truncated when it returns early, failed on exception or missing retained file;
- classifies recorder exceptions from the retained final artifact: a non-empty final `recording.mp4` after a recorder exception is `truncated`, while no final file or a `.tmp` file only is `failed`;
- suppresses duplicate active ring lifecycles;
- cancels on config-entry unload before media manager shutdown.

## Upstream Evidence

Pinned ref: Home Assistant Core `2026.9.2`, selected because the official GitHub API release endpoint identified it as the newest stable release at retrieval time (`html_url: https://github.com/home-assistant/core/releases/tag/2026.9.2`).

Shell retrieval note: the Codex sandbox could not fetch the files directly: `curl` through the configured proxy failed with `Failed to connect to 127.0.0.1 port 8118`; clearing proxy variables then failed DNS resolution. Hermes fetched and hashed the exact bytes on the orchestration host outside the repo using read-only HTTPS at `2026-09-17T20:36:26Z`. These artifacts are tagged `EXTERNAL_UPSTREAM_SOURCE`, not committed to this repository.

| File | URL | Ref | Retrieval UTC | Bytes | SHA256 |
|---|---|---|---|---:|---|
| `homeassistant/components/stream/__init__.py` | `https://raw.githubusercontent.com/home-assistant/core/2026.9.2/homeassistant/components/stream/__init__.py` | `2026.9.2` | `2026-09-17T20:36:26Z` | 23065 | `f63cbbfa0d286fadf11c680b193942ad0cb0b3f7a1ba035a5f99e3d950b4bd95` |
| `homeassistant/components/camera/__init__.py` | `https://raw.githubusercontent.com/home-assistant/core/2026.9.2/homeassistant/components/camera/__init__.py` | `2026.9.2` | `2026-09-17T20:36:26Z` | 39944 | `f141b0dd0e5940d30aca4cec5337dfd70905d69cb10a2d194796578907c497b5` |
| `homeassistant/components/stream/manifest.json` | `https://raw.githubusercontent.com/home-assistant/core/2026.9.2/homeassistant/components/stream/manifest.json` | `2026.9.2` | `2026-09-17T20:36:26Z` | unknown | `d8f5f25d5c4cf6cca695344c85f81b1e1d83a56838d05cd9a50d4711d026edc8` |
| `homeassistant/components/stream/recorder.py` | `https://raw.githubusercontent.com/home-assistant/core/2026.9.2/homeassistant/components/stream/recorder.py` | `2026.9.2` | `2026-09-17T20:36:26Z` | 7759 | `7c24fbeff3714b2a6ee637a9c35a7d92e5229faad0464aab7e67712d75562006` |

Evidence:

- Recording API: `Stream.async_record(self, video_path: str, duration: int = 30, lookback: int = 5) -> None` exists in upstream `stream/__init__.py:559`. It raises `HomeAssistantError` when `self.hass.config.is_allowed_path(video_path)` is false, raises `HomeAssistantError("Stream already recording to ...")` if the same Stream already has a recorder output, adds `RecorderOutput(..., timeout=duration)`, awaits `self.start()`, awaits `recorder.async_record()`, returns `None`, and has no retry loop.
- Snapshot API: `Stream.async_get_image(self, width=None, height=None, wait_for_next_keyframe=False) -> bytes | None` exists in upstream `stream/__init__.py:597`.
- `camera.record`: implemented by `async_handle_record_service(...)` in upstream `camera/__init__.py:1155`; it obtains `stream = await camera.async_create_stream()` and calls `await stream.async_record(...)` in `camera/__init__.py:1169`.
- `RecorderOutput`: upstream `stream/recorder.py:35` creates the parent directory, muxes with PyAV to `<video_path>.tmp`, then renames the temporary file to the final path; audio is optional. Comelit only treats the final non-empty `recording.mp4` path as a retained artifact. A leftover `.tmp` does not count as completed or truncated output.
- `stream/manifest.json`: requires `PyTurboJPEG==1.8.3`, `av==17.0.1`, and `numpy==2.3.2`, so the HA stream integration already ships the encoder stack needed for recording.
- Stream registration: upstream `create_stream(...)` starts at `stream/__init__.py:179` and appends the created stream to `hass.data[DOMAIN][ATTR_STREAMS]` at `stream/__init__.py:212`. Comelit keeps direct construction because the local SDP path needs `pyav_options={"protocol_whitelist": "file,udp,rtp"}`, which upstream `create_stream` derives from the stream options schema and does not expose as a public option. This still preserves one upstream Comelit session: the direct Stream consumes the local SDP produced by the already acquired `ComelitMediaSessionManager` transport, not a second Comelit cloud/native session.
  Snapshot and recording share the same `HAStreamMediaProvider._stream` object and local SDP path; focused tests assert one Stream instance and one registration after calling both `async_capture_jpeg()` and `async_record_mp4()`.

## Gate Evidence

| Gate | Result | Derivation |
|---|---:|---|
| `RING_EVENT_CONTRACT_UNCHANGED` | PASS | Constant and runtime event emission preserved; asserted by `test_existing_contract_constants_are_unchanged`. |
| `RING_EVENT_ID_CORRELATION` | PASS | Runtime-generated `event_id` is passed to coordinator paths/events; exercised by `test_snapshot_and_recording_use_one_session_and_safe_paths`. |
| `RING_DEDUP_UNCHANGED` | PASS | Existing parser/dedup path unchanged; no native/ring parser edits. |
| `SNAPSHOT_LOOP_SINGLE_SESSION` | PASS | One manager acquire across snapshot+recording; focused test asserts `acquire_calls == 1`. |
| `SNAPSHOT_FIRST_FRAME` | PASS | First snapshot event precedes recording terminal event; focused test asserts event ordering. |
| `SNAPSHOT_REFRESH_TARGET_SECONDS` | 1 | Constant `SNAPSHOT_REFRESH_TARGET_SECONDS = 1`; asserted by focused test. |
| `SNAPSHOT_REFRESH_SERIAL_NO_QUEUE` | PASS | Fake provider records max in-flight capture as 1 with slow capture; focused test asserts `max_in_flight == 1`. |
| `SNAPSHOT_SEQUENCE_MONOTONIC` | PASS | Focused test observes snapshot sequences `[1, 2]`. |
| `SNAPSHOT_EVENT_SAFE_PAYLOAD` | PASS | Focused test validates safe keys and absence of token/chat data. |
| `SNAPSHOT_FINAL_FILE_RETAINED` | PASS | Focused test reads final `latest.jpg` after lifecycle and verifies temp file is gone. |
| `RECORDING_TARGET_SECONDS` | 20 | Constant `RECORDING_TARGET_SECONDS = 20`; focused test asserts provider receives 20. |
| `RECORDING_SINGLE_SESSION` | PASS | Same manager acquire assertion as snapshot lifecycle. |
| `RECORDING_COMPLETE_EVENT_COMPLETED` | PASS | Focused test emits `state=completed` only when provider reports completion and measured recorder wall-clock reaches 20 s; fast completion is downgraded to `truncated`. |
| `RECORDING_COMPLETE_EVENT_TRUNCATED` | PASS | Focused tests validate explicit truncated result, normal recorder return before target, and recorder exception with a non-empty final retained file all become terminal `truncated` with measured wall-clock duration. |
| `RECORDING_COMPLETE_EVENT_FAILED` | PASS | Focused tests validate `state=failed` for provider failure, start failure, recorder exception without a final retained file, `.tmp`-only recorder output, missing recorder method, and HA allowlist rejection. |
| `RECORDING_SAFE_PATH` | PASS | Focused test validates `/comelit/rings/<event_id>/recording.mp4`; unsafe event id rejected; provider pre-checks HA allowlist when available and upstream recorder checks HA allowed path before writing. |
| `MEDIA_TEARDOWN_AFTER_RECORDING` | PASS | Focused test asserts manager release after terminal recording. |
| `LISTENER_RESTORE_CONTRACT` | PASS | Existing manager tests prove release restores listener; new lifecycle releases its lease and leaves restoration to manager. |
| `DUPLICATE_RING_NO_SECOND_LIFECYCLE` | PASS | Focused test asserts second active start returns false and only one acquire/record call occurs; duplicate CALL_INIT cannot reach recorder. |
| `UNLOAD_CLEANUP` | PASS | Focused test cancels active lifecycle, releases manager, and emits truncated terminal event. |
| `DOOR_OPERATION_EVENT_UNCHANGED` | PASS | Runtime finalizer preserved; existing ring-telegram tests still pass. |
| `EXISTING_BUTTONS_REGRESSION` | PASS | Button source hash remains pinned in `test_p116_r20_hls_http_boundary_diagnostics`. |
| `GATE_CAPABILITY_GUARDS_UNCHANGED` | PASS | Focused test asserts gate unsupported by service and `press_allowed=false`; existing gate tests still pass. |
| `AUTOMATIC_RETRY` | false | No retry loop added; recording provider is called once, a second recorder on the same Stream is never attempted by the coordinator, and start/recorder failures emit failed. |
| `TELEGRAM_REQUIRED` | false | No Telegram use in new integration module; examples untouched. |
| `R30H_E_EXECUTED` | false | No R30H-E/repeat-`0x001A` files changed or executed. |

## Changed Files

- `custom_components/comelit/const.py` sha256 `1101bc30d3d18278d5c4337eb678b3661db0d546f4a866af95f5a4e4fdc8ab96`: MVP snapshot/recording constants and event attributes.
- `custom_components/comelit/runtime.py` sha256 `0ca72bfe9ad3cb3fe417dd9de80278cdc04f7d2fd1a5724bb739c96bdc19ab6c`: schedules ring media lifecycle after `comelit_ring`.
- `custom_components/comelit/__init__.py` sha256 `b2a93552483557f7fc327f4c29f234bc491601b6955dd4e40a71d3e63ebe16c6`: constructs and unloads the ring media coordinator.
- `custom_components/comelit/ring_media.py` sha256 `657c8dc33aaf3619765778e3c1b378fb50edbe75a7b4b2cdc105812aedd7f96d`: new focused ring snapshot/recording lifecycle.
- `safety-poc/tests/test_mvp1_integration_offline_build.py` sha256 `be18ee6a28800e1154a19c45031bc4992be23edb30a86ff44edc2ab46cc76612`: focused offline behavioral tests.
- `safety-poc/tests/test_p16_ha_background_task_contract.py` sha256 `896f1ca97e095296eeef4bda20d755753b24924621a4eb432f5c16c3419add07`: updated exact background-task count for new scheduler.
- `safety-poc/tests/test_p116_r20_hls_http_boundary_diagnostics.py` sha256 `38cf1f25db9e85e2753e88f3582555c45292ee4544e361a32bb5ca7e49b1c3e2`: updated runtime hash pin after intentional scheduler addition.

## Checks

```text
python3 -m py_compile custom_components/comelit/const.py custom_components/comelit/runtime.py custom_components/comelit/__init__.py custom_components/comelit/ring_media.py safety-poc/tests/test_mvp1_integration_offline_build.py
PASS

python3 -m compileall -q custom_components/comelit
PASS

(cd safety-poc && python3 scripts/static_safety_check.py)
STATIC_SAFETY_CHECK=PASS
NETWORK_IMPORTS_PRESENT=false
COMELIT_ENDPOINTS_PRESENT=false
SOURCE_FILES_SCANNED=29

(cd safety-poc && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=$PWD/src python3 -m unittest tests.test_mvp1_integration_offline_build)
Ran 15 tests in 2.053s
OK

(cd safety-poc && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=$PWD/src python3 -m unittest discover -s tests)
Ran 1556 tests in 33.733s
FAILED (failures=1, errors=2, skipped=5)
Residuals:
- `test_p116_provenance_binary_analysis...NATIVE_BINARY_MODE`: `755 != 775`, NOT_A_MVP1I_REGRESSION.
- `test_p116_r29i_preopen_idle_and_sink_ownership` zero/nonzero UDP sink tests: sandbox UDP datagram restriction, NOT_A_MVP1I_REGRESSION.

Host-authoritative full suite, run by Hermes outside the Codex sandbox:

cd safety-poc && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=$PWD/src python3 -m unittest discover -s tests
Ran 1556 tests in 30.186s
FAILED (failures=1, skipped=1)

Host run has no UDP-sink errors; the two UDP errors above are sandbox-only because `codex exec` blocks UDP datagram sockets. The only host failure is the pre-existing `755 != 775` native-mode artifact, `NOT_A_MVP1I_REGRESSION`. Host baseline at accepted `main` (`c9fff4e47bea3d0ec7d6a9aa6f36049931c5a643`) was `Ran 1541 / failures=1 / skipped=1`, so the branch delta is exactly the 15 new focused tests.

git diff --check
PASS
```

## Limitations

- No HA runtime was installed or executed in this offline task.
- No live Comelit media, physical camera activation, Door action, Gate action, HA reload/restart, or Telegram send was performed.
- Deployed HA/HAOS version is not inspected in this offline task. If that runtime differs from upstream `2026.9.2` and lacks/renames `Stream.async_record`, Comelit fails closed with `state=failed`.
- Deployment must allow the retained recording path under `/media/comelit/rings/...`; upstream `Stream.async_record` rejects non-allowlisted paths. The future canary must verify Home Assistant allowlist configuration.
- `async_get_image` adds an HLS provider and `async_record` may prepend at most one HLS segment when an HLS output exists, so a retained MP4 may be up to about one segment longer than measured recorder wall time. Event `duration_actual_seconds` is measured wall time, not parsed container duration.
- Container validity/playability of a truncated retained MP4 remains a future canary item; offline tests prove artifact-based state classification, not media-player acceptance.
- Snapshot capture depends on HA Stream producing decodable JPEG bytes at runtime; offline tests prove lifecycle semantics with fakes, not live decode quality.
- Gate media and Gate actuation remain unvalidated and fail-closed.

RESULT_CLASS=`PASS_OFFLINE_INTEGRATION_MVP_READY`

```text
=== COMELIT MVP1 INTEGRATION OFFLINE BUILD ===
TASK_ID=COMELIT-MVP1-INTEGRATION-OFFLINE-BUILD
BASE_SHA=c9fff4e47bea3d0ec7d6a9aa6f36049931c5a643
RING_EVENT=PASS
SNAPSHOT_REFRESH=PASS
SNAPSHOT_REFRESH_TARGET_SECONDS=1
SNAPSHOT_EVENT=PASS
FINAL_SNAPSHOT_RETENTION=PASS
RECORDING_TARGET_SECONDS=20
RECORDING_IMPLEMENTATION=PASS
RECORDING_COMPLETE_EVENT=PASS
MEDIA_SINGLE_SESSION=PASS
MEDIA_TEARDOWN=PASS
LISTENER_RESTORE_CONTRACT=PASS
DOOR_OPERATION_EVENT=PASS
EXISTING_BUTTONS_REGRESSION=PASS
GATE_CAPABILITY_GUARDS_UNCHANGED=true
TELEGRAM_REQUIRED=false
TELEGRAM_CODE_CHANGED=false
R30H_E_EXECUTED=false
COMELIT_LIVE_EXECUTED=false
HA_DEPLOYED=false
HA_RELOADED=false
HA_RESTARTED=false
DOOR_ACTIONS=0
GATE_ACTIONS=0
BRANCH=feat/mvp1-integration-offline-build
REMOTE_HEAD=NOT_PUSHED
PR=none
RESULT=PASS_OFFLINE_INTEGRATION_MVP_READY
=== END COMELIT MVP1 INTEGRATION OFFLINE BUILD ===
```
