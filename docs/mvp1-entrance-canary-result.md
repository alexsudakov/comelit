# Comelit MVP1 entrance canary result

## 1. Task Identity

```text
TASK_ID=COMELIT-MVP1-ENTRANCE-CANARY
MODE=BOUNDED_LIVE_PRODUCTION_CANARY
RESULT_DOC_DATE_UTC=2026-09-17
DEPLOY_START_UTC=2026-09-17T21:17:01Z
DEPLOY_END_UTC=2026-09-17T21:17:11Z
IMPLEMENTATION_BASE_SHA=1402a15254340317a4683b6b781024b23073eefd
ACCEPTED_MAIN_SHA=6bbfbc19ea04567e56fa3a9e3d470ca67b3b077c
ACCEPTED_MAIN_COMMIT=6bbfbc19ea04567e56fa3a9e3d470ca67b3b077c 2026-09-18T00:08:54+03:00 Merge pull request #159 from alexsudakov/docs/mvp1-entrance-canary-tree-gate
RESULT_WORKTREE=/home/hermes/repos/comelit-worktrees/mvp1-canary-result
RESULT_BRANCH=docs/mvp1-entrance-canary-result
```

Contracts/addendum read:

- `docs/mvp1-entrance-canary-contract.md`
- `docs/mvp1-entrance-canary-execution-task.md`
- `docs/mvp1-entrance-canary-main-gate-addendum.md`
- `docs/mvp-integration-v1-contract.md`
- `docs/mvp-integration-v1-offline-build-result.md`
- `docs/intercom-media-session-architecture.md`
- `docs/ha-integration-target-architecture.md`

The live contract authorizes exact current-main deployment, at most one Comelit reload only if needed, one real entrance ring, one media session, one 20-second recording, one later entrance Door action, zero Gate actions, zero retry, and forbids a full Home Assistant restart without separate approval (`docs/mvp1-entrance-canary-contract.md:7`-`docs/mvp1-entrance-canary-contract.md:19`). The execution task requires no physical/media action until every pre-live gate passes (`docs/mvp1-entrance-canary-execution-task.md:83`-`docs/mvp1-entrance-canary-execution-task.md:111`).

## 2. Result Class

```text
RESULT_CLASS=BLOCKED_HA_RESTART_REQUIRED
PREFLIGHT_VERDICT=STOP_HA_RESTART_REQUIRED
ARMING_ALLOWED=NO
```

Reason: exact-main `custom_components/comelit/**` was safely deployed on disk, but the loaded Home Assistant Python module set could not be proven to contain the MVP1 Python delta, and the proven activation path for changed custom-component Python is a full Home Assistant restart, which this canary forbids.

This is a fail-closed pre-live stop. Zero physical, media, Door and Gate side effects occurred: no real entrance ring was armed or consumed, no media session was started, no snapshot or recording was attempted, no Door action was issued, and no Gate action was issued.

## 3. Identity Gate

```text
IMPLEMENTATION_BASE_SHA=1402a15254340317a4683b6b781024b23073eefd
EXPECTED_COMELIT_COMPONENT_TREE_SHA=e4d70ad372cc92cf16d13eb8ebcc54932f437079
CURRENT_COMELIT_COMPONENT_TREE_SHA=e4d70ad372cc92cf16d13eb8ebcc54932f437079
COMELIT_COMPONENT_TREE_MATCH=true
MAIN_MOVED=false
```

The normative main gate for this canary is component-tree identity. The addendum requires the live task to resolve `custom_components/comelit` at fresh `origin/main` and require `COMELIT_COMPONENT_TREE_MATCH=true` against `e4d70ad372cc92cf16d13eb8ebcc54932f437079` (`docs/mvp1-entrance-canary-main-gate-addendum.md:30`-`docs/mvp1-entrance-canary-main-gate-addendum.md:42`). It further states that documentation/non-component changes do not make `MAIN_MOVED=true` when the Comelit component tree still matches (`docs/mvp1-entrance-canary-main-gate-addendum.md:53`-`docs/mvp1-entrance-canary-main-gate-addendum.md:57`).

Observed identity evidence:

```text
ACCEPTED_MAIN_SHA=6bbfbc19ea04567e56fa3a9e3d470ca67b3b077c
CURRENT_COMELIT_COMPONENT_TREE_SHA=6bbfbc19...:custom_components/comelit = e4d70ad372cc92cf16d13eb8ebcc54932f437079
EXPECTED_COMELIT_COMPONENT_TREE_SHA=e4d70ad372cc92cf16d13eb8ebcc54932f437079
COMELIT_COMPONENT_TREE_MATCH=true
IMPLEMENTATION_BASE_SHA=1402a15254340317a4683b6b781024b23073eefd exists and is an ancestor of ACCEPTED_MAIN_SHA
git diff --stat 1402a15254340317a4683b6b781024b23073eefd ACCEPTED_MAIN_SHA -- custom_components/comelit -> EMPTY
```

Repository-level `main` advanced after the implementation base by documentation-only merges:

```text
6bbfbc1 Merge pull request #159 (docs/mvp1-entrance-canary-tree-gate)
ea872fd docs(mvp1): gate canary on Comelit component tree
0fa9ea7 Merge pull request #158 (docs/mvp1-entrance-canary)
a21db5e docs(mvp1): add unified entrance canary execution task
2b5eeb4 docs(mvp1): define unified entrance canary contract
```

## 4. Deployment Evidence

Deployment was completed and safe to leave on disk. It wrote only `custom_components/comelit/**`, did not restart Home Assistant, and post-deploy HA core check passed. The only outstanding requirement is a full Home Assistant restart to activate the already-deployed exact-main Python.

Payload construction:

```text
git -C /home/hermes/repos/comelit archive --format=tar --prefix='custom_components/comelit/' 6bbfbc19ea04567e56fa3a9e3d470ca67b3b077c:custom_components/comelit | gzip -n
ARCHIVE_PIPE_RC=0
GZIP_TEST=PASS
PAYLOAD_BYTES=6184476
MEMBERS=55
OUTSIDE_MEMBERS=0
PAYLOAD_SHA256=e518be17b2828493f3dbee82a365ba58388cc37c7fb5f304e55d30e20c9b8899
TARGET_SHA=6bbfbc19ea04567e56fa3a9e3d470ca67b3b077c
TARGET_COMPONENT_TREE=e4d70ad372cc92cf16d13eb8ebcc54932f437079
```

Gateway status before deploy:

```text
INTEGRATION_PRESENT=true
INTEGRATION_VERSION=1.5.7
DEPLOYED_SHA=6a711a4939e7980e8e5091191588f347a34f2e88
GATEWAY_SCOPE=custom_components/comelit
ARBITRARY_SHELL=DENIED
```

Deploy result:

```text
DEPLOY_INVOKE_UTC=2026-09-17T21:17:02Z
DEPLOYED_SHA=6bbfbc19ea04567e56fa3a9e3d470ca67b3b077c
DEPLOY_SCOPE=/config/custom_components/comelit
HA_RESTARTED=NO
DEPLOY=PASS
DEPLOY_VERB_RC=0
```

Gateway status after deploy:

```text
INTEGRATION_PRESENT=true
INTEGRATION_VERSION=1.5.7
DEPLOYED_SHA=6bbfbc19ea04567e56fa3a9e3d470ca67b3b077c
GATEWAY_SCOPE=custom_components/comelit
ARBITRARY_SHELL=DENIED
```

HA checks:

```text
PRE_DEPLOY_CHECK: HA_CORE_CHECK=PASS
POST_DEPLOY_CHECK: HA_CORE_CHECK=PASS
HA_RESTARTS=0
COMELIT_RELOADS=0
```

Per-file deployed-content identity cross-check against `docs/mvp-integration-v1-offline-build-result.md` changed-file hashes (`docs/mvp-integration-v1-offline-build-result.md:94`-`docs/mvp-integration-v1-offline-build-result.md:99`):

```text
custom_components/comelit/const.py      = 1101bc30d3d18278d5c4337eb678b3661db0d546f4a866af95f5a4e4fdc8ab96  doc=1101bc30d3d18278d5c4337eb678b3661db0d546f4a866af95f5a4e4fdc8ab96  MATCH
custom_components/comelit/runtime.py    = 0ca72bfe9ad3cb3fe417dd9de80278cdc04f7d2fd1a5724bb739c96bdc19ab6c  doc=0ca72bfe9ad3cb3fe417dd9de80278cdc04f7d2fd1a5724bb739c96bdc19ab6c  MATCH
custom_components/comelit/__init__.py   = b2a93552483557f7fc327f4c29f234bc491601b6955dd4e40a71d3e63ebe16c6  doc=b2a93552483557f7fc327f4c29f234bc491601b6955dd4e40a71d3e63ebe16c6  MATCH
custom_components/comelit/ring_media.py = 657c8dc33aaf3619765778e3c1b378fb50edbe75a7b4b2cdc105812aedd7f96d  doc=657c8dc33aaf3619765778e3c1b378fb50edbe75a7b4b2cdc105812aedd7f96d  MATCH
```

## 5. Activation Analysis

Gateway surface:

```text
status | check | logs | logs-follow | deploy <sha> | rollback | restart USER_APPROVED
no verb reads loaded Python objects / sys.modules
deploy writes files only and self-reports HA_RESTARTED=NO
the config-entry reload verb does not exist on the gateway; an unknown-verb probe returns COMELIT_HA_GATEWAY=DENY
restart USER_APPROVED is a full Home Assistant restart and is forbidden here
```

`RELOAD_DECISION=SKIP` is a deliberate, reasoned zero. The gateway exposes no `reload` verb at all, so the only conceivable Comelit reload in this environment would be the owner's UI config-entry Reload. The project-local evidence below proves that path restarts unload/setup objects but does not load changed custom-component Python. The user authorization permits a reload only if needed for activation (`docs/mvp1-entrance-canary-contract.md:76`-`docs/mvp1-entrance-canary-contract.md:83`), and this reload path cannot achieve activation. Therefore `COMELIT_RELOADS=0` is not an omission.

Upstream Home Assistant evidence, labelled `EXTERNAL_UPSTREAM_SOURCE`; both files were retrieved by the orchestrator on the orchestration host over read-only HTTPS, bytes kept outside the repository.

```text
EXTERNAL_UPSTREAM_SOURCE=config_entries.py
url=https://raw.githubusercontent.com/home-assistant/core/2026.9.2/homeassistant/config_entries.py
ref=2026.9.2
retrieval_utc=2026-09-17T21:16:44Z
bytes=156716
sha256=14186676771573b13290107e5376ce62c2d302d9f4c1647b6dd9d41fdb020cfb
grep -E 'sys\.modules|importlib' -> NO_MATCH
citations: async_reload at line 2473; unload/setup both use integration.async_get_component at lines 752, 1016, 1101; unload calls component.async_unload_entry at line 1046; setup calls component.async_setup_entry at line 803.

EXTERNAL_UPSTREAM_SOURCE=loader.py
url=https://raw.githubusercontent.com/home-assistant/core/2026.9.2/homeassistant/loader.py
ref=2026.9.2
retrieval_utc=2026-09-17T21:16:44Z
bytes=62355
sha256=e54ea10fe718347da38559fd911246e541ce2fe9cbd926d7a4cb2ff1ae436c18
citations: async_get_component returns self._cache[domain] when present at lines 999-1008; _get_component imports once and assigns cache[domain] = importlib.import_module(self.pkg_path) at lines 1089-1096.
```

Project-local/proven evidence, `COMELIT-P116 R30F`:

```text
deploy + owner UI config-entry Reload НЕ активирует изменённый Python кастомного компонента: HA
перезапускает unload/setup, но модуль уже в sys.modules и повторно не импортируется... Reload при
этом выглядит «успешным»: счётчики пересозданных объектов сбрасываются (reconnect_count 202→0,
last_native_exit_code 6→None, listener снова READY) — это доказательство пересоздания объектов, НЕ
загрузки нового кода... Активатор изменённого custom-component Python ровно один — полный HA restart.
```

Repository citation: `safety-poc/research/media/v1/P116_R30F_PACKAGED_HELPER_BOUNDED_LIVE_RESULT.md:188`-`safety-poc/research/media/v1/P116_R30F_PACKAGED_HELPER_BOUNDED_LIVE_RESULT.md:191` concludes "Config-entry reload restored integration runtime health but did not re-import the updated custom-component Python module"; `safety-poc/research/media/v1/P116_R30F_PACKAGED_HELPER_BOUNDED_LIVE_RESULT.md:267`-`safety-poc/research/media/v1/P116_R30F_PACKAGED_HELPER_BOUNDED_LIVE_RESULT.md:270` states the mechanism: "HA does not re-import already-loaded custom-component Python modules."

Pre-deploy deployed revision:

```text
PRE_DEPLOY_DEPLOYED_SHA=6a711a4939e7980e8e5091191588f347a34f2e88
PRE_DEPLOY_COMPONENT_TREE=17112d9da473eb22498676e110316a9c150b3bd1
POST_DEPLOY_COMPONENT_TREE=e4d70ad372cc92cf16d13eb8ebcc54932f437079
```

`COMELIT-P116 R30G` result-document citation: `safety-poc/research/media/v1/P116_R30G_RESTART_ACTIVATED_BOUNDED_LIVE_RESULT.md` records that exact-main `6a711a4939e7980e8e5091191588f347a34f2e88` was deployed integration-scoped with `HA_RESTARTED_BY_DEPLOY=NO` (`safety-poc/research/media/v1/P116_R30G_RESTART_ACTIVATED_BOUNDED_LIVE_RESULT.md:70`-`safety-poc/research/media/v1/P116_R30G_RESTART_ACTIVATED_BOUNDED_LIVE_RESULT.md:81`), then a full HA restart was used only to activate exact-main Python (`safety-poc/research/media/v1/P116_R30G_RESTART_ACTIVATED_BOUNDED_LIVE_RESULT.md:83`-`safety-poc/research/media/v1/P116_R30G_RESTART_ACTIVATED_BOUNDED_LIVE_RESULT.md:93`). Its loaded-code identity section records `LOADED_CODE_IDENTITY_PROVEN=true` and explains that the loaded Python accepted the deployed native helper path after restart (`safety-poc/research/media/v1/P116_R30G_RESTART_ACTIVATED_BOUNDED_LIVE_RESULT.md:95`-`safety-poc/research/media/v1/P116_R30G_RESTART_ACTIVATED_BOUNDED_LIVE_RESULT.md:112`). For this canary, the last restart-activated loaded revision is therefore the pre-deploy `6a711a4` line, not the newly written `6bbfbc1` files.

MVP1 changed Python content is real and activation-sensitive:

- `DATA_RING_MEDIA` exists in `custom_components/comelit/const.py:11`.
- `SNAPSHOT_REFRESH_TARGET_SECONDS = 1` and `RECORDING_TARGET_SECONDS = 20` exist in `custom_components/comelit/const.py:46`-`custom_components/comelit/const.py:47`.
- `RingMediaCoordinator` is constructed and attached to the runtime in `custom_components/comelit/__init__.py:182`-`custom_components/comelit/__init__.py:198`.
- `ComelitRingRuntime.set_ring_media_coordinator()` and `_async_start_ring_media()` exist in `custom_components/comelit/runtime.py:219`-`custom_components/comelit/runtime.py:232`.
- The runtime schedules ring media after firing `comelit_ring` in `custom_components/comelit/runtime.py:697`-`custom_components/comelit/runtime.py:705`.

Conclusion:

```text
COMELIT_ACTIVATION=FAIL
```

## 6. Pre-Live Gate Table

The contract pre-live gates are defined in `docs/mvp1-entrance-canary-contract.md:118`-`docs/mvp1-entrance-canary-contract.md:140`; the execution task repeats the required read-only proof in `docs/mvp1-entrance-canary-execution-task.md:83`-`docs/mvp1-entrance-canary-execution-task.md:111`.

| Gate | Label | Value | Evidence |
| --- | --- | --- | --- |
| `DEPLOYED_SHA_MATCH` | `PROVEN_OBSERVED` | `PASS` | STATUS_AFTER `DEPLOYED_SHA=6bbfbc19ea04567e56fa3a9e3d470ca67b3b077c` equals `TARGET_SHA`. |
| `HA_CORE_CHECK` | `PROVEN_OBSERVED` | `PASS` | Pre- and post-deploy gateway checks both reported `HA_CORE_CHECK=PASS`. |
| `COMELIT_IMPORT_OR_ACTIVATION` / `COMELIT_ACTIVATION` | `DERIVED` | `FAIL` | Upstream loader cache behavior, local R30F reload finding, R30G restart activation proof, pre-deploy loaded identity `6a711a4`, no HA restart. |
| `HA_RESTARTS` | `PROVEN_OBSERVED` | `0` | Deploy reported `HA_RESTARTED=NO`; scalar `HA_RESTARTS=0`; restart forbidden by `docs/mvp1-entrance-canary-contract.md:86`-`docs/mvp1-entrance-canary-contract.md:97`. |
| `LISTENER_RUNNING` | `PROVEN_OBSERVED` | `true` | Post-deploy scalars report `LISTENER_RUNNING=true`; logs show READY for persistent cycle at `2026-09-18 00:17:22.332`. |
| `LISTENER_READY` | `PROVEN_OBSERVED` | `true` | Exact observed line: `2026-09-18 00:17:22.332 INFO ... listener READY for persistent 3300s cycle`. |
| `LISTENER_LAST_ERROR` | `DERIVED` | `null` | Current cycle started at `00:17:22.332`; runtime clears `_last_error` in `async_start()` at `custom_components/comelit/runtime.py:257`-`custom_components/comelit/runtime.py:267`; completed-cycle errors set it at `custom_components/comelit/runtime.py:467`-`custom_components/comelit/runtime.py:472`. |
| `MEDIA_ACTIVE` | `PROVEN_OBSERVED` | `false` | Camera recorder sample: `media_active=False`, `media_phase=inactive`, `remaining_seconds=0`. |
| `RING_MEDIA_LIFECYCLE_ACTIVE` | `PROVEN_OBSERVED` | `false` | No ring occurred after deploy and no ring-media marker was observed; scheduling would only occur after a ring event (`custom_components/comelit/runtime.py:697`-`custom_components/comelit/runtime.py:705`). |
| `ENTRANCE_DOOR_BASELINE_ACTIONS` / `DOOR_ACTIONS` | `PROVEN_OBSERVED` | `0` | Scalar `DOOR_ACTIONS=0`; no `comelit_door_operation` observed. |
| `GATE_BASELINE_ACTIONS` / `GATE_ACTIONS` | `PROVEN_OBSERVED` | `0` | Scalar `GATE_ACTIONS=0`. |
| `RECORDING_TARGET_SECONDS` | `PROVEN_OBSERVED` | `20` | `custom_components/comelit/const.py:47`; offline result records same at `docs/mvp-integration-v1-offline-build-result.md:164`. |
| `SNAPSHOT_REFRESH_TARGET_SECONDS` | `PROVEN_OBSERVED` | `1` | `custom_components/comelit/const.py:46`; offline result records same at `docs/mvp-integration-v1-offline-build-result.md:160`-`docs/mvp-integration-v1-offline-build-result.md:161`. |
| HA-allowed generated media path | `UNPROVEN` | `NOT_REACHED` | Contract says verify the actual generated target under `/media/comelit/rings/<event_id>/` once an event id exists (`docs/mvp1-entrance-canary-contract.md:138`); no ring/event id occurred. |

Read-only Comelit log lines observed:

```text
2026-09-18 00:16:31.812 WARNING (MainThread) [custom_components.comelit.supervisor] Comelit listener cycle ended; reconnecting in 5s (count=18)   [PRE-DEPLOY, local time UTC+3]
2026-09-18 00:17:11.685 ERROR   (MainThread) [custom_components.comelit.runtime] Comelit ring listener stopped: native_exit:6; safe_native_markers=['ICE_COMPONENT_STATE=<redacted>', 'ICE_COMPONENT_STATE=<redacted>', 'ICE_CONNECTED=PASS', 'PSEUDOTCP_RX_BEFORE_START=24', 'ICE_COMPONENT_STATE=READY']   [during the deploy window]
2026-09-18 00:17:11.847 WARNING (MainThread) [custom_components.comelit.supervisor] Comelit listener cycle ended; reconnecting in 5s (count=19)
2026-09-18 00:17:22.332 INFO    (MainThread) [custom_components.comelit.runtime] Comelit ring listener READY for persistent 3300s cycle
(no further Comelit cycle-end/error line for the following ~8 minutes)
```

Camera recorder sample at `2026-09-18 00:20:07.052` local, `2026-09-17T21:20:07Z`:

```text
entity_id=camera.comelit_entrance
access_token=<REDACTED>
media_active=False  media_phase=inactive  expires_at=None  remaining_seconds=0  listener_paused=False
video_forwarding=False  audio_forwarding=False  video_packet_count=1750  audio_packet_count=1750
video_last_packet_age_seconds=34516.5  audio_last_packet_age_seconds=34516.6
automatic_session_start=False  hard_limit_seconds=600
video_recovery_shim_running=False  video_recovery_input_packets=0  video_recovery_output_packets=0
hls_provider_present=False  hls_endpoint_generated=False  hls_probe_mode=none  ha_stream_created=False
```

Listener instability attribution:

```text
LISTENER_INSTABILITY_ATTRIBUTION=PRE_EXISTING
ROLLBACK_EXECUTED=false
```

This is an observed pre-existing environment condition, not a regression of this deploy:

1. The first observed cycle-end line was at `00:16:31` with `count=18`, before deploy invocation at `2026-09-17T21:17:02Z`, proving pre-existing cycle history.
2. The listener process path is unchanged by the MVP1 delta: `native/**` and `supervisor.py` were byte-identical between `6a711a4` and accepted main, the helper binary was verified on disk by the loaded pin, and loaded Python remained the pre-deploy revision.
3. The deployed `runtime.py` diff touches `async_open_door`, `_async_start_ring_media`, and ring-event scheduling, not the native-exit/cycle path.

No rollback was performed or required. The contract forbids automatic rollback and requires preserving evidence if rollback becomes necessary (`docs/mvp1-entrance-canary-contract.md:113`-`docs/mvp1-entrance-canary-contract.md:116`, `docs/mvp1-entrance-canary-contract.md:248`-`docs/mvp1-entrance-canary-contract.md:265`).

## 7. Lifecycle Scalars

```text
REAL_ENTRANCE_RING_COUNT=0
RING_EVENT_ID=NONE
MEDIA_SESSION_COUNT=0
SNAPSHOT_EVENT_COUNT=0
SNAPSHOT_SEQUENCE_FIRST=NONE
SNAPSHOT_SEQUENCE_LAST=NONE
FINAL_SNAPSHOT_RETAINED=NOT_REACHED
RECORDING_COUNT=0
RECORDING_STATE=NOT_REACHED
RECORDING_ACTUAL_SECONDS=NONE
RECORDING_PROBED_DURATION_SECONDS=NONE
RECORDING_VIDEO_STREAM_PRESENT=NOT_REACHED
MEDIA_TEARDOWN=NOT_REACHED
LISTENER_READY_AFTER_MEDIA=NOT_REACHED
DOOR_OPERATION_EVENT=NOT_REACHED
DOOR_PROTOCOL_ACKED=NOT_REACHED
```

A run that reached no media or recording phase must not report any snapshot, recording, MP4 container, codec, duration, or retained-artifact fact. The MVP contract requires those facts only after an actual ring/media lifecycle (`docs/mvp-integration-v1-contract.md:175`-`docs/mvp-integration-v1-contract.md:186`, `docs/mvp1-entrance-canary-contract.md:161`-`docs/mvp1-entrance-canary-contract.md:206`), and this canary stopped before arming.

## 8. Forbidden-Action Counts

```text
DOOR_ACTIONS=0
GATE_ACTIONS=0
HA_RESTARTS=0
COMELIT_RELOADS=0
AUTOMATIC_RETRY=false
SECOND_MEDIA_SESSION=false
R30H_E_EXECUTED=false
ROLLBACK_EXECUTED=false
PHYSICAL_EFFECT_ASSERTED=false
TELEGRAM_REQUIRED=false
```

No raw RTP, H264, audio, PCAP, credentials, token material, host credentials, JPEG, or MP4 were captured, printed, or committed. No synthetic Home Assistant event was used. The result is based on deploy/status/check/log/entity observations and repository citations only. The canary stayed inside the hard limits in `docs/mvp1-entrance-canary-contract.md:49`-`docs/mvp1-entrance-canary-contract.md:66`.

## 9. Cleanup State

```text
CANARY_OWNED_MEDIA_TASK_EXISTS=false
MEDIA_ACTIVE=false
PERSISTENT_LISTENER_RESTORED=true
PERSISTENT_LISTENER_READY=true
/media/comelit/rings/**=UNTOUCHED
```

No canary-owned media task exists because no ring was armed and no media phase began. Media is inactive from the recorder sample. The persistent listener is running and READY from the post-deploy observation. `/media/comelit/rings/**` was untouched because no ring event id was generated.

## 10. Limitations And Uncertain Evidence

The loaded-module identity is proven by construction plus project-local proven behavior, not by directly reading `sys.modules`; the gateway cannot read loaded Python objects. The evidence is still sufficient to fail closed because deploy writes files only, Home Assistant loader/component paths cache imported components, owner UI reload was already shown not to reload changed custom-component Python, R30G needed a restart to prove loaded-code identity, the pre-deploy deployed revision was `6a711a4`, and this canary performed zero restarts.

The exact required next step is one full Home Assistant restart to activate the already-deployed exact-main Python, followed by a re-baselined canary run under a new user authorization.

```text
NO_SECOND_CANARY_AUTHORIZED=true
RESULT=BLOCKED_HA_RESTART_REQUIRED
TERMINAL_FOR_THIS_TASK=true
```

`RESULT_REMOTE_HEAD=none` and `RESULT_PR=none` below are intentional: this document cannot embed the head SHA of the commit that contains it, and the authoritative pushed branch head and PR attempt result are published in the Hermes final block.

## 11. Canonical Final Scalar Block

```text
=== COMELIT MVP1 ENTRANCE CANARY ===
TASK_ID=COMELIT-MVP1-ENTRANCE-CANARY
EXPECTED_SHA=1402a15254340317a4683b6b781024b23073eefd
ACCEPTED_MAIN_SHA=6bbfbc19ea04567e56fa3a9e3d470ca67b3b077c
IMPLEMENTATION_BASE_SHA=1402a15254340317a4683b6b781024b23073eefd
EXPECTED_COMELIT_COMPONENT_TREE_SHA=e4d70ad372cc92cf16d13eb8ebcc54932f437079
CURRENT_COMELIT_COMPONENT_TREE_SHA=e4d70ad372cc92cf16d13eb8ebcc54932f437079
COMELIT_COMPONENT_TREE_MATCH=true
MAIN_MOVED=false
DEPLOYED_SHA_MATCH=PASS
HA_CORE_CHECK=PASS
COMELIT_RELOADS=0
HA_RESTARTS=0
PRELIVE=FAIL
REAL_ENTRANCE_RING_COUNT=0
RING_EVENT_ID=NONE
MEDIA_SESSION_COUNT=0
SNAPSHOT_EVENT_COUNT=0
SNAPSHOT_SEQUENCE_FIRST=NONE
SNAPSHOT_SEQUENCE_LAST=NONE
FINAL_SNAPSHOT_RETAINED=NOT_REACHED
RECORDING_COUNT=0
RECORDING_TARGET_SECONDS=20
RECORDING_STATE=NOT_REACHED
RECORDING_ACTUAL_SECONDS=NONE
RECORDING_PROBED_DURATION_SECONDS=NONE
RECORDING_VIDEO_STREAM_PRESENT=NOT_REACHED
MEDIA_TEARDOWN=NOT_REACHED
LISTENER_READY_AFTER_MEDIA=NOT_REACHED
DOOR_ACTIONS=0
GATE_ACTIONS=0
DOOR_OPERATION_EVENT=NOT_REACHED
DOOR_PROTOCOL_ACKED=NOT_REACHED
PHYSICAL_EFFECT_ASSERTED=false
AUTOMATIC_RETRY=false
SECOND_MEDIA_SESSION=false
R30H_E_EXECUTED=false
ROLLBACK_EXECUTED=false
RESULT=BLOCKED_HA_RESTART_REQUIRED
RESULT_BRANCH=docs/mvp1-entrance-canary-result
RESULT_REMOTE_HEAD=none
RESULT_PR=none
=== END COMELIT MVP1 ENTRANCE CANARY ===
```
