# P116 / R30G — restart-activated bounded live contract

TASK_ID=`COMELIT-P116-R30G-RESTART-ACTIVATED-BOUNDED-LIVE`

Status: **LIVE AUTHORIZED BY USER ON 2026-09-17 / EXACT-MAIN DEPLOY / UP TO TWO HA RESTARTS WITH ROLLBACK-ONLY SECOND RESTART**

## 1. Goal

Resume the R30F live validation after the activation-boundary blocker was proven.

R30F established that an exact-main deployment followed by a Comelit config-entry reload replaced the files on disk but did not re-import the already-loaded custom-component Python modules. The old in-memory `MEDIA_NATIVE_BINARY_SHA256=35a9a160...` therefore rejected the new R30E helper `a336477a...` fail-closed. Rollback restored the old Python/binary pair and media startup, proving the activation-boundary diagnosis.

R30G therefore has one narrowly expanded permission: activate exact-main through one full Home Assistant restart, prove that the new Python/native identity is actually loaded, then run the intended media tests. A second Home Assistant restart is authorized only after rollback and only to restore the pre-R30G production tree if the new deployment cannot be kept safely.

## 2. Canonical inputs

Use fresh `origin/main` as source of truth. Do not roll back a newer accepted main.

At contract creation the accepted R30E artifact identity is:

```text
CANONICAL_SOURCE_SHA256=1c89d61de4372d96b25f6894862741244753c107a3a9b9e04817250b3bea55b2
PACKAGED_NATIVE_SHA256=a336477aa3564f4c99983a71621fc630885c55bf7ff07909bc70838d851a49b8
ARTIFACT_PROVENANCE_READY=true
```

R30F final production state was restored to:

```text
FINAL_DEPLOYED_SHA=b96ad1690e216f8e81934314470259b1abcc495d
FINAL_DEPLOYED_NATIVE_SHA256=35a9a1604c4bef3667713e3487b68aadc79501c4630748d7143ee9ee7cd85622
```

Canonical evidence:

```text
safety-poc/research/media/v1/P116_R30E_NATIVE_HELPER_REBUILD_PROVENANCE_RESULT.md
safety-poc/research/media/v1/P116_R30E_CI_FINALIZATION.md
safety-poc/research/media/v1/P116_R30F_PACKAGED_HELPER_BOUNDED_LIVE_RESULT.md
safety-poc/docs/P116_HA_STREAM_RTP_BRIDGE.md
```

## 3. Authorization and hard safety boundary

Authorized:

- work only on the single Home Assistant Comelit integration;
- read-only HA state/log/process/socket diagnostics;
- materialize a rollback backup/restore artifact for the actual preflight deployed Comelit tree;
- deploy exact fresh-main `custom_components/comelit/**` once before restart #1;
- perform **one mandatory full Home Assistant restart** after exact-main deploy to activate the new Python code;
- wait for HA and Comelit to recover and verify post-restart health;
- run bounded entrance-camera media attempts using the existing production camera/session path;
- run the normal Home Assistant Stream consumer path after the upstream/helper test succeeds or when a specific evidence-backed diagnostic reason exists;
- temporary media/stream verification under `/tmp`, summarized by safe metadata and deleted before completion;
- CT120 diagnostics/evidence as needed without changing protocol source;
- deploy the preflight rollback tree if exact-main cannot be kept safely;
- perform **restart #2 only after rollback deploy and only to reactivate the preflight production Python/tree**.

Not authorized:

- more than two full Home Assistant restarts;
- using restart #2 as a retry of exact-main or of a live attempt;
- Home Assistant OS reboot, host reboot, VM reboot, Proxmox restart, or supervisor host reboot;
- Door action;
- Gate action;
- unrelated integration changes;
- go2rtc or Frigate installation/configuration/change;
- new protocol refresh/repeat experiments outside existing production behavior;
- credential/account/cloud changes;
- persistent packet/media capture or committing raw/private media;
- production-code changes in this live child.

Restart accounting is strict:

```text
RESTART_1_PURPOSE=activate_exact_main_python
RESTART_2_PURPOSE=rollback_recovery_only
MAX_HA_RESTARTS=2
```

If exact-main appears unhealthy after restart #1, do not restart it again. Either restore production using the preflight rollback tree + restart #2, or stop if rollback cannot be performed safely.

If restart #2 has been consumed, no further restart is authorized under R30G.

## 4. Preflight before any write/restart/live action

Record and independently verify:

1. fresh `origin/main` SHA;
2. repository packaged native helper SHA;
3. repository `MEDIA_NATIVE_BINARY_SHA256` pin;
4. current deployed Comelit identity reported by the existing deployment gateway/mechanism;
5. current/preflight native helper SHA and transport pin, derived or directly verified using the same trusted mechanism used in R30F;
6. listener state and health;
7. media/session inactive state;
8. camera/session entity availability;
9. current media hard limit, required `<=600` seconds;
10. HA core health before intervention;
11. rollback artifact representing the actual preflight Comelit tree plus its SHA256/integrity metadata;
12. Door/Gate action counters/evidence baseline at zero for this task.

Preflight fails closed if the listener is persistently unhealthy, media is unexpectedly active, the rollback artifact cannot be trusted, or the exact-main native binary and transport pin disagree.

The preflight rollback identity is authoritative for restart #2. Do not hard-code `b96ad1690...` if production has legitimately advanced before execution.

## 5. Exact-main deploy and restart #1

Deployment is integration-scoped:

- deploy only exact fresh-main `custom_components/comelit/**`;
- do not copy research/tests/docs into Home Assistant;
- verify deployed-tree identity through the existing deployment gateway;
- verify exact-main native helper SHA and exact-main transport pin before restart;
- require `media inactive` before restart;
- no config-entry reload is required as a substitute for restart; R30F already proved it is insufficient for code activation.

Then perform restart #1 using the existing authorized Home Assistant restart mechanism only.

Do not reboot HAOS/VM/host.

After restart #1, use a bounded recovery window and require objective recovery evidence before any camera activation:

```text
HA_CORE_READY=true
COMELIT_SETUP_ERROR=false
listener ready/running
media inactive
camera/session control inactive
Door actions = 0
Gate actions = 0
```

If Home Assistant or Comelit does not recover sufficiently to make the next live action safe, enter rollback recovery instead of attempting another exact-main restart.

## 6. Loaded-code identity gate

R30G must explicitly prove that restart #1 activated a Python/native pair consistent with fresh main.

Preferred evidence, in descending order:

1. direct read-only runtime identity from the loaded integration/module, if an existing diagnostic path already exposes it and no production-code change is required;
2. exact-main deployed-tree identity + successful native SHA gate/media startup using the exact-main helper, with no `media_native_binary_sha256_mismatch` and with native P80/P116 markers proving the helper process actually started;
3. equivalent existing runtime evidence that unambiguously distinguishes the new pair from the R30F old-memory/new-disk mismatch.

Do not claim `LOADED_CODE_IDENTITY_PROVEN=true` solely because files on disk match fresh main or because the listener reports READY.

If the first media start again produces `media_native_binary_sha256_mismatch`, exact-main activation has failed despite restart #1. Do not retry restart #1. Roll back.

## 7. Live attempt budget

`MAX_LIVE_ATTEMPTS=5`.

This budget is sufficient for the two planned tests plus limited evidence-backed diagnosis. Blind identical retries are forbidden.

Before Attempt 3–5 record:

```text
ATTEMPT_N_HYPOTHESIS=<specific hypothesis>
ATTEMPT_N_DISTINGUISHING_EVIDENCE=<what result changes the conclusion>
```

Attempts do not authorize additional HA restarts.

### Attempt 1 — exact R30E helper / historical ~36-second boundary

Purpose: finally test the accepted R30E helper after its Python/native pair has been activated by restart #1.

- Start one entrance-camera media session using the existing Comelit session control path.
- Do not intentionally add an HA Stream consumer during the baseline.
- Observe objective media/native markers.
- Continue long enough to cross the historical failure boundary. If media remains healthy past 60 seconds, deliberately stop the session between approximately 60 and 90 seconds instead of waiting for the 600-second hard limit.
- Record activation latency, media duration, helper exit/teardown reason, video/audio packet counts, first/last timestamps/monotonic times when exposed, PT sets, SSRC count/changes, seq gaps, duplicates, out-of-order, timestamp regressions, SPS/PPS, FU-A/single-NAL counters, forwarding markers, and relevant P80/P116/native status.

`HISTORICAL_36S_BOUNDARY_SURPASSED=true` requires objective RTP/native timing or counters beyond 60 seconds followed by deliberate teardown or an otherwise objectively healthy session beyond 60 seconds. `media_active=true` alone is insufficient.

If media terminates around the historical boundary, do not blind-retry. Diagnose the teardown evidence within the existing scope. If the exact-main helper is not safe to keep, enter rollback recovery.

### Attempt 2 — Home Assistant Stream consumer

Run if Attempt 1 proves a healthy upstream/helper path, or Codex states a concrete diagnostic reason why the consumer test is still useful.

- Start a fresh bounded entrance-camera session.
- Invoke normal Home Assistant Stream/camera consumer behavior through existing integration/HA facilities.
- Determine objectively whether HA/FFmpeg/PyAV consumes the local RTP/SDP source.
- Existing read-only socket/process/log evidence may be used.
- A temporary output under `/tmp` may be inspected by safe metadata/size/ffprobe and then deleted.
- Record stream-worker/demux result, source/consumer binding when observable, timing relative to first/last RTP, codec/container metadata for produced output, and any HA Stream error.

`HA_STREAM_CONSUMER_PROVEN=true` requires objective successful consumer evidence, such as a valid non-empty temporary stream/snapshot artifact or equivalent established HA Stream success. Helper RTP alone is insufficient.

### Attempts 3–5 — adaptive diagnostics only

Allowed only for a specific evidence-backed hypothesis from earlier attempts and only while:

- no new architecture decision is required;
- no production-code write is required;
- no additional restart beyond the R30G allowance is required;
- listener/session safety remains intact.

Stop early on decisive success, deterministic blocker, rollback need, or new permission boundary.

## 8. Mandatory post-attempt invariant

After every live attempt require:

```text
media inactive
camera/session control inactive/off
listener ready/running
no persistent new reconnect/error regression
Door actions = 0
Gate actions = 0
```

A temporary listener recovery period may be observed, but the next attempt cannot begin until the invariant is restored.

If the invariant cannot be restored under the exact-main deployment without another restart, enter rollback recovery rather than using restart #2 as an exact-main retry.

## 9. Keep-versus-rollback decision

Exact-main may remain deployed at task completion only when all of the following are true:

```text
restart #1 completed successfully
loaded-code identity is proven
HA core is healthy
Comelit listener is healthy after testing
no persistent new error/reconnect regression exists
camera/session can be left inactive
Door/Gate actions remained zero
```

For a normal successful R30G (`PASS_END_TO_END` or `PASS_UPSTREAM_ONLY`), leave exact-main deployed and do not consume restart #2.

Rollback is required when exact-main causes a material production regression or unsafe/uncertain state, including examples such as:

- HA/Comelit cannot recover safely after restart #1;
- loaded-code/native identity remains inconsistent;
- exact-main media cannot start because of an activation/package mismatch;
- listener health cannot be restored;
- a new persistent failure makes the current production state materially worse than preflight.

A test finding that merely shows the historical ~36-second defect still exists, while the integration remains otherwise healthy and safely tearable-down, is evidence of an unresolved helper defect; Codex must explicitly judge whether keeping exact-main is safe. If safety/production quality is uncertain, prefer rollback.

## 10. Rollback recovery and restart #2

Restart #2 is legal only in this sequence:

```text
1. stop live attempts
2. ensure media/session inactive as far as possible
3. deploy the trusted preflight rollback Comelit tree
4. verify rollback-tree deployment identity on disk/gateway
5. perform HA restart #2
6. wait for HA + Comelit listener recovery
7. verify rollback identity/health and zero Door/Gate actions
8. STOP
```

Forbidden use of restart #2:

- retry exact-main activation;
- retry a camera session;
- retry HA Stream;
- generic troubleshooting before rollback bytes are restored;
- reboot HAOS/VM/host.

If rollback bytes cannot be deployed safely, or restart #2 does not recover the known production state, return `FAIL_ROLLBACK_RECOVERY` with exact evidence. No restart #3.

## 11. Evidence handling

Prefer scalar/status/log metadata.

Never commit or print credentials, raw RTP/H264/audio, screenshots/private video frames, or persistent media captures.

Temporary stream artifacts:

- `/tmp` only;
- bounded;
- inspect only safe size/container/codec metadata as required;
- remove before completion;
- never commit.

## 12. Repository write scope

Default R30G write scope is exactly:

```text
safety-poc/research/media/v1/P116_R30G_RESTART_ACTIVATED_BOUNDED_LIVE_RESULT.md
```

No production-code edits are authorized in this child.

If live evidence identifies an ordinary implementation defect, Codex may provide:

- exact file(s);
- root cause;
- minimal proposed fix;
- required write-scope extension;
- focused verification plan.

But stop before editing production code.

## 13. Result classes

```text
PASS_END_TO_END
  exact-main activated through restart #1 + loaded-code identity proven + R30E helper objectively survives >60s + HA Stream consumer succeeds + listener healthy; exact-main remains deployed

PASS_UPSTREAM_ONLY
  exact-main activated + loaded-code identity proven + R30E helper objectively survives >60s + HA Stream remains a separately localized blocker + listener healthy; exact-main may remain deployed if safe

BLOCKED
  deterministic new permission/architecture/write-scope boundary prevents completion; production must be left in a known safe state

FAIL_ROLLBACK_RECOVERY
  exact-main required rollback and the authorized rollback sequence could not restore the known production state

FAIL
  authorized path fails in another decisive way while safety/restore state is still known
```

## 14. Stop boundary

After the R30G result, STOP.

Do not automatically begin:

- production-code correction;
- go2rtc/Frigate work;
- Door/Gate work;
- another HA restart;
- another live/architecture child.
