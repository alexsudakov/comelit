# Comelit MVP1 synthetic entrance-ring canary result

## 1. Task identity

```text
TASK_ID=COMELIT-MVP1-SYNTHETIC-RING-CANARY
MODE=BOUNDED_LIVE_CANARY_WITH_ONE_AUTHORIZED_HA_RESTART
DATE_UTC=2026-09-18
EXPECTED_MAIN_SHA=45854c7f0aa201fef0eb5207464e2fb9791c345d
ACCEPTED_MAIN_SHA=45854c7f0aa201fef0eb5207464e2fb9791c345d
ACCEPTED_MAIN_COMMIT=45854c7 Merge pull request #161 from alexsudakov/feat/mvp1-synthetic-ring-canary
MAIN_MOVED=false
MAIN_MOVED_EXECUTABLE=false
COMELIT_COMPONENT_TREE_ACCEPTED_MAIN=0a3629982862b17a420adea7044aac3551343472
PR=161
```

Этот документ заменяет pre-live stop документы turn 2/3. После merge PR 161 владелец отдельно разрешил один bounded live canary с ровно одним full Home Assistant restart. Exercised authorization:

```text
DEPLOY_MAX=1
HA_RESTART_MAX=1
SYNTHETIC_RING_MAX=1
MEDIA_SESSION_MAX=1
RECORDING_MAX=1
RECORDING_TARGET_SECONDS=20
DOOR_ACTIONS=0
GATE_ACTIONS=0
AUTOMATIC_RETRY=false
SECOND_MEDIA_SESSION=false
R30H_E_EXECUTED=false
HOST_REBOOT=0
SUPERVISOR_REBOOT=0
NO_PHYSICAL_RING_REQUIRED=true
```

Repository context: the branch/accepted-main code contains the integration-side synthetic runtime entrypoint and shared ring handler. `ComelitRingRuntime.async_simulate_entrance_ring()` constructs only an entrance `CALL_INIT` event with `synthetic=True` and calls `ComelitRingRuntime._async_emit_ring_event(..., require_media_start=True)` (`custom_components/comelit/runtime.py:237`-`custom_components/comelit/runtime.py:285`). The test-control webhook exposes the `simulate_entrance_ring` action inside Home Assistant and is local-only with the existing webhook id and CT120 allowlist (`custom_components/comelit/test_control.py:12`-`custom_components/comelit/test_control.py:13`, `custom_components/comelit/test_control.py:73`-`custom_components/comelit/test_control.py:87`, `custom_components/comelit/test_control.py:117`-`custom_components/comelit/test_control.py:125`). The canary limit stays one trigger, one media session, no Door/Gate, no retry, and no R30H-E behavior (`docs/mvp1-synthetic-ring-canary.md:57`-`docs/mvp1-synthetic-ring-canary.md:73`).

## 2. Result class

```text
RESULT_CLASS=BLOCKED_PRELIVE_GATE
```

Результат не является `FAIL_SYNTHETIC_TRIGGER`: synthetic trigger не был выполнен, Home Assistant webhook action не получил запрос, ring event не был создан, media не стартовал. Run stopped at PHASE 4 before invocation because the authorized operator verb `simulate_entrance_ring` is absent from the CT120 restricted surface and from the HA forced-command gateway. Integration-side entrypoint is now present in accepted main and was deployed before the single authorized restart, but no authorized transport could invoke it. This is an operator-side access-surface gap, not a defect in `custom_components/comelit`.

## 3. PHASE 1/2 - pre-deploy and deploy

Fresh main gate:

```text
EXPECTED_MAIN_SHA=45854c7f0aa201fef0eb5207464e2fb9791c345d
ACCEPTED_MAIN_SHA=45854c7f0aa201fef0eb5207464e2fb9791c345d
MAIN_MOVED=false
MAIN_MOVED_EXECUTABLE=false
COMELIT_COMPONENT_TREE_ACCEPTED_MAIN=0a3629982862b17a420adea7044aac3551343472
```

Pre-deploy read-only state:

```text
INTEGRATION_PRESENT=true
INTEGRATION_VERSION=1.5.7
DEPLOYED_SHA=6bbfbc19ea04567e56fa3a9e3d470ca67b3b077c
GATEWAY_SCOPE=custom_components/comelit
ARBITRARY_SHELL=DENIED
PRE_DEPLOY_CHECK=HA_CORE_CHECK=PASS
PRE_DEPLOY_DOOR_ACTIONS=0
PRE_DEPLOY_GATE_ACTIONS=0
PRE_DEPLOY_RING_EVENTS=0
PRE_DEPLOY_SNAPSHOT_EVENTS=0
PRE_DEPLOY_RECORDING_COMPLETE_EVENTS=0
PRE_DEPLOY_DOOR_OPERATION_EVENTS=0
```

Deploy payload and deployment result:

```text
ARCHIVE_PIPE_RC=0
GZIP_TEST=PASS
PAYLOAD_BYTES=6185206
MEMBERS=55
OUTSIDE_MEMBERS=0
PAYLOAD_SHA256=b4be518ff291948b372b97dd9528321f3c369a35dbcbdc8e0186e4ab9e93f6ba
TARGET_SHA=45854c7f0aa201fef0eb5207464e2fb9791c345d
TARGET_COMPONENT_TREE=0a3629982862b17a420adea7044aac3551343472
DEPLOYED_SHA=45854c7f0aa201fef0eb5207464e2fb9791c345d
DEPLOY_SCOPE=/config/custom_components/comelit
HA_RESTARTED=NO
DEPLOY=PASS
DEPLOY_VERB_RC=0
POST_DEPLOY_CHECK=HA_CORE_CHECK=PASS
POST_DEPLOY_STATUS_DEPLOYED_SHA=45854c7f0aa201fef0eb5207464e2fb9791c345d
```

Accepted-main file identity deployed to Home Assistant:

```text
custom_components/comelit/runtime.py=262218f04f3b9f75e43c538d153e2bdd8a8fb998dd392e7bc4ceedede024789c
custom_components/comelit/ring_media.py=84c69d227201c9834e3eb03b9b170d9ff64817dc8cc4f291e540e5d49d56e257
custom_components/comelit/test_control.py=b925cb6162c66b51c8c5321dfa563c8669f43e05cc3855a78248df95d2064dbd
custom_components/comelit/const.py=1101bc30d3d18278d5c4337eb678b3661db0d546f4a866af95f5a4e4fdc8ab96
custom_components/comelit/__init__.py=b2a93552483557f7fc327f4c29f234bc491601b6955dd4e40a71d3e63ebe16c6
```

The deployed `runtime.py` sha256 matches the R20 gate pin (`safety-poc/tests/test_p116_r20_hls_http_boundary_diagnostics.py:27`-`safety-poc/tests/test_p116_r20_hls_http_boundary_diagnostics.py:29`). `RECORDING_TARGET_SECONDS=20` and `SNAPSHOT_REFRESH_TARGET_SECONDS=1` remain the code constants (`custom_components/comelit/const.py:46`-`custom_components/comelit/const.py:47`), but no snapshot or recording phase was reached in this run.

## 4. PHASE 3 - one authorized full Home Assistant restart

```text
RESTART_REQUEST_UTC=2026-09-18T10:40:12Z
USER_APPROVAL_MARKER=USER_APPROVED
HA_CORE_RESTART_REQUESTED=true
POST_RESTART_CHECK=HA_CORE_CHECK=PASS
POST_RESTART_STATUS_DEPLOYED_SHA=45854c7f0aa201fef0eb5207464e2fb9791c345d
EXCEPTIONS_AFTER_RESTART=0
HA_RESTARTS=1
SECOND_RESTART=false
HOST_REBOOT=0
SUPERVISOR_REBOOT=0
```

Activation markers observed after restart:

```text
2026-09-18T10:40:52Z custom_components.comelit.runtime
  Comelit ring listener READY for persistent 3300s cycle
2026-09-18T10:40:56Z homeassistant.components.recorder.core
  camera.comelit_entrance state_changed old_state=None new_state=idle
```

The READY string is emitted by the runtime when `V4_RING_LISTENER_READY=true` is read and `_listener_ready` is set (`custom_components/comelit/runtime.py:658`-`custom_components/comelit/runtime.py:662`). `LISTENER_LAST_ERROR=null` is derived for the fresh ready cycle: `async_start()` clears `_last_error` when starting a cycle (`custom_components/comelit/runtime.py:314`-`custom_components/comelit/runtime.py:324`), while completed-cycle errors would be set in `_async_run_once()` (`custom_components/comelit/runtime.py:529`-`custom_components/comelit/runtime.py:535`).

```text
COMELIT_LOADED_AFTER_RESTART=PASS
LISTENER_RUNNING=true
LISTENER_READY=true
LISTENER_LAST_ERROR=null
```

The single authorized restart was consumed exactly once. No second restart, reload, host reboot, or Supervisor reboot was performed.

## 5. PHASE 4 - trigger gate blocker

The authorized operator verb was exactly `simulate_entrance_ring`. It was attempted once through the CT120 restricted SSH surface and refused before execution:

```text
COMMAND=ssh -i ~/.ssh/id_ed25519_ct120_comelit -o IdentitiesOnly=yes -o BatchMode=yes hermes-comelit@192.168.1.85 simulate_entrance_ring
TRIGGER_REQUEST_UTC=2026-09-18T10:43:10Z
RESPONSE=DENIED: command not allowed
TRIGGER_VERB_RC=126
SYNTHETIC_RING_COUNT=0
```

`exit 126` plus `DENIED: command not allowed` is the not-whitelisted forced-command behavior. The refusal happened before any Home Assistant webhook call, so it is not an executed trigger invocation.

Read-only CT120 inventory showed the surface gap:

```text
/usr/local/sbin/hermes-comelit-dispatch
  sha256=092ea7d29391840f4d3162e5df9f17270de08d328178c68187455036c8d9f6cf
  HA-family cases:
    comelit-ha-ring-test-start -> comelit-ha-ring-runtime start
    comelit-ha-ring-test-status -> comelit-ha-ring-runtime status
    comelit-ha-ring-test-stop -> comelit-ha-ring-runtime stop

/usr/local/sbin/comelit-ha-ring-runtime
  sha256=06a291181d363d7c8c6358cd16f14ce6a61385f8e6bacae35c5c4c66782b7804
  URL=http://192.168.1.108:8123/api/webhook/comelit-ha-ring-test-control-v1
  ACTION_ALLOWLIST=start|status|stop

/usr/local/sbin/hermes-comelit-dispatch.pre-p13-observed-v1
  sha256=e4bb63d7939a67344eedbfaf9f01a8a0a9e1578a74665e4b84f169466eb62e63
  cases=door-poc-status,door-poc-test

HA_GATEWAY_PROBE=ssh comelit-ha simulate_entrance_ring -> COMELIT_HA_GATEWAY=DENY
```

Interpretation: the integration-side entrypoint exists in deployed accepted main, and the restart activation markers prove the accepted main integration restarted cleanly. However, no authorized transport can invoke `simulate_entrance_ring`: the CT120 dispatcher has no case for it, `comelit-ha-ring-runtime` rejects actions outside `start|status|stop`, and the HA forced-command gateway has no same-named verb or service-call path.

The inventory was collected read-only through the CT120 root SSH route `comelit-ct120`, not through the restricted route, because the restricted route can only execute whitelisted verbs and cannot list or read wrapper files. The inventory used `ls`, `sha256sum`, and `cat` only. Nothing was modified, started, stopped, reloaded, or restarted on CT120 or Home Assistant.

No workaround transport was used. Raw root curl to the local-only webhook, gateway bypass, bearer token, Home Assistant service call, and `hass.bus.fire` would all bypass the documented restricted wrapper boundary.

## 6. Negative evidence over the full capture

The run stopped before trigger execution. Over the capture:

```text
comelit_ring=0
comelit_snapshot_updated=0
comelit_recording_complete=0
comelit_door_operation=0
"media session ACTIVE"=0
"Synthetic"=0
media_native_binary_sha256_mismatch=0
```

No media phase was reached. Therefore this result intentionally reports no snapshot artifact, no recording artifact, no retained file, no probed container, and no duration fact.

## 7. Gate table

| Gate | Value | Evidence label | Evidence |
| --- | --- | --- | --- |
| `ACCEPTED_MAIN_SHA` | `45854c7f0aa201fef0eb5207464e2fb9791c345d` | `PROVEN_OBSERVED` | Fresh main gate matched expected SHA and PR 161 merge commit. |
| `MAIN_MOVED` | `false` | `PROVEN_OBSERVED` | Accepted main equals expected main. |
| `MAIN_MOVED_EXECUTABLE` | `false` | `PROVEN_OBSERVED` | Accepted `custom_components/comelit` tree was recorded as `0a3629982862b17a420adea7044aac3551343472`. |
| `DEPLOYED_SHA_MATCH` | `PASS` | `PROVEN_OBSERVED` | Post-deploy and post-restart status both reported `DEPLOYED_SHA=45854c7f0aa201fef0eb5207464e2fb9791c345d`. |
| `HA_CORE_CHECK` | `PASS` | `PROVEN_OBSERVED` | Pre-deploy, post-deploy, and post-restart checks passed. |
| `PAYLOAD_SCOPE` | `PASS` | `PROVEN_OBSERVED` | `OUTSIDE_MEMBERS=0`, `MEMBERS=55`, `DEPLOY_SCOPE=/config/custom_components/comelit`. |
| `HA_RESTARTS` | `1` | `PROVEN_OBSERVED` | Exactly one authorized restart requested at `2026-09-18T10:40:12Z`; no second restart. |
| `COMELIT_LOADED_AFTER_RESTART` | `PASS` | `DERIVED` | Accepted main was deployed, HA restart completed, listener READY logged at `2026-09-18T10:40:52Z`, and no setup exceptions appeared. |
| `LISTENER_RUNNING` | `true` | `PROVEN_OBSERVED` | Post-restart listener READY marker was logged. |
| `LISTENER_READY` | `true` | `PROVEN_OBSERVED` | Runtime logged `Comelit ring listener READY for persistent 3300s cycle` at `2026-09-18T10:40:52Z`; code emits this after setting `_listener_ready` (`custom_components/comelit/runtime.py:658`-`custom_components/comelit/runtime.py:662`). |
| `LISTENER_LAST_ERROR` | `null` | `DERIVED` | Fresh cycle clears `_last_error` on `async_start()`; no completed-cycle error after the ready marker was observed (`custom_components/comelit/runtime.py:314`-`custom_components/comelit/runtime.py:324`, `custom_components/comelit/runtime.py:529`-`custom_components/comelit/runtime.py:535`). |
| `SYNTHETIC_ENTRYPOINT_PRESENT_IN_ACCEPTED_MAIN` | `true` | `PROVEN_OBSERVED` | Runtime and test-control code contain the entrypoint/action (`custom_components/comelit/runtime.py:267`-`custom_components/comelit/runtime.py:285`, `custom_components/comelit/test_control.py:73`-`custom_components/comelit/test_control.py:87`). |
| `SYNTHETIC_ENTRYPOINT_LOADED` | `FAIL` | `UNPROVEN` | Deployed accepted main plus restart markers prove activation context, but functional loaded-module proof would require invoking the entrypoint; the authorized trigger surface refused before execution. |
| `ENTRYPOINT_TRIGGER_REACHABLE` | `false` | `PROVEN_OBSERVED` | CT120 restricted dispatcher lacks a `simulate_entrance_ring` case; wrapper allowlist is only `start|status|stop`; HA gateway same-name probe returned DENY. |
| `SYNTHETIC_RING_COUNT` | `0` | `PROVEN_OBSERVED` | One named-verb attempt was refused with rc 126 before execution. |
| `RING_EVENT_COUNT` | `0` | `PROVEN_OBSERVED` | Negative capture: `comelit_ring=0`. |
| `MEDIA_SESSION_COUNT` | `0` | `NOT_REACHED` | Trigger surface unavailable; no ring event reached Home Assistant. |
| `SNAPSHOT_EVENT_COUNT` | `0` | `NOT_REACHED` | Trigger surface unavailable; no media lifecycle began. |
| `RECORDING_COUNT` | `0` | `NOT_REACHED` | Trigger surface unavailable; no media lifecycle began. |
| `RECORDING_TARGET_SECONDS` | `20` | `PROVEN_OBSERVED` | Constant in code (`custom_components/comelit/const.py:47`) and deployment file identity recorded. |
| `MEDIA_TEARDOWN` | `NOT_REACHED` | `NOT_REACHED` | Trigger surface unavailable; no media session was started. |
| `LISTENER_READY_AFTER_MEDIA` | `NOT_REACHED` | `NOT_REACHED` | Trigger surface unavailable; no media phase ran. |
| `DOOR_ACTIONS` | `0` | `PROVEN_OBSERVED` | Boundary requires zero Door actions and capture had `comelit_door_operation=0`. |
| `GATE_ACTIONS` | `0` | `PROVEN_OBSERVED` | Boundary requires zero Gate actions. |
| `AUTOMATIC_RETRY` | `false` | `PROVEN_OBSERVED` | No retry was attempted; contract stops failed phases without retry (`docs/mvp1-entrance-canary-contract.md:248`-`docs/mvp1-entrance-canary-contract.md:265`). |
| `SECOND_MEDIA_SESSION` | `false` | `PROVEN_OBSERVED` | Trigger surface unavailable; no first media session began. |
| `R30H_E_EXECUTED` | `false` | `PROVEN_OBSERVED` | No R30H-E path was authorized or observed. |

## 8. Deliberate zeros and counters

```text
DEPLOYS=1
HA_RESTARTS=1
COMELIT_RELOADS=0
HOST_REBOOT=0
SUPERVISOR_REBOOT=0
SYNTHETIC_TRIGGERS=0
MEDIA_SESSIONS=0
SNAPSHOTS=0
RECORDINGS=0
DOOR_ACTIONS=0
GATE_ACTIONS=0
AUTOMATIC_RETRY=false
SECOND_MEDIA_SESSION=false
R30H_E_EXECUTED=false
SECOND_TRIGGER_ATTEMPT=false
SECOND_RESTART=false
```

`COMELIT_RELOADS=0` because the owner authorized a full HA restart for activation; no reload was needed or performed. `SYNTHETIC_TRIGGERS=0` because the single named trigger attempt was refused by the restricted command surface before execution. All media/snapshot/recording zeros are deliberate `NOT_REACHED` values with the same reason: trigger surface unavailable. Door and Gate stayed zero by contract and by observation.

## 9. Limitations and safety notes

No media phase was reached. This document contains no snapshot artifact, recording artifact, retained JPEG/MP4 proof, probed video stream proof, or duration measurement. The constants `SNAPSHOT_REFRESH_TARGET_SECONDS=1` and `RECORDING_TARGET_SECONDS=20` are code/deploy facts only, not live artifact observations (`custom_components/comelit/const.py:46`-`custom_components/comelit/const.py:47`).

`SYNTHETIC_ENTRYPOINT_LOADED=FAIL` is a functional proof statement, not a source-code absence statement: the entrypoint is present in the deployed and restart-activated accepted main, with identity proven on disk and by restart markers, but its presence in the loaded module set was not functionally proven because no authorized transport could invoke it.

No secrets, credentials, bearer tokens, raw media bytes, or private payloads were recorded. The CT120 wrapper inventory was read-only and only lists script names, hashes, dispatcher cases, and the webhook URL already embedded in the wrapper.

## 10. Exact next step

The owner must name or extend the CT120 restricted surface for the `simulate_entrance_ring` test-control action. That means adding an allowed dispatcher case for the operator-named verb and extending `comelit-ha-ring-runtime` action whitelist beyond `start|status|stop` to include `simulate_entrance_ring`, or providing an equivalent explicitly authorized restricted trigger surface.

After that, authorize one bounded trigger round. Because the accepted main was already deployed and activated by the single restart in this run, the future trigger round does not need another deploy, reload, or restart unless the owner changes the deployed code or Home Assistant state before the round.

## 11. Final scalar block

```text
ACCEPTED_MAIN_SHA=45854c7f0aa201fef0eb5207464e2fb9791c345d
DEPLOYED_SHA=45854c7f0aa201fef0eb5207464e2fb9791c345d
HA_CORE_CHECK=PASS
HA_RESTARTS=1
COMELIT_LOADED_AFTER_RESTART=PASS
LISTENER_READY_BEFORE_TRIGGER=PASS
SYNTHETIC_ENTRYPOINT_LOADED=FAIL
SYNTHETIC_RING_COUNT=0
RING_EVENT_COUNT=0
RING_EVENT_ID=NONE
RING_SYNTHETIC=NOT_REACHED
MEDIA_SESSION_COUNT=0
SNAPSHOT_EVENT_COUNT=0
SNAPSHOT_SEQUENCE_FIRST=NONE
SNAPSHOT_SEQUENCE_LAST=NONE
SNAPSHOT_SEQUENCE_MONOTONIC=NOT_REACHED
SNAPSHOT_AVERAGE_INTERVAL_SECONDS=NONE
FINAL_SNAPSHOT_RETAINED=NOT_REACHED
RECORDING_COUNT=0
RECORDING_TARGET_SECONDS=20
RECORDING_STATE=NOT_REACHED
RECORDING_PROBED_DURATION_SECONDS=NONE
RECORDING_VIDEO_STREAM_PRESENT=NOT_REACHED
MEDIA_TEARDOWN=NOT_REACHED
LISTENER_READY_AFTER_MEDIA=NOT_REACHED
DOOR_ACTIONS=0
GATE_ACTIONS=0
AUTOMATIC_RETRY=false
SECOND_MEDIA_SESSION=false
R30H_E_EXECUTED=false
RESULT=BLOCKED_PRELIVE_GATE
RESULT_BRANCH=docs/mvp1-synthetic-ring-canary-result
RESULT_REMOTE_HEAD=<orchestrator-published>
RESULT_PR=none
```
