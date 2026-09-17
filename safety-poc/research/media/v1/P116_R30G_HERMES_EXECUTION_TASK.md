# P116 / R30G — Hermes/Codex execution task: restart-activated bounded live

TASK_ID=`COMELIT-P116-R30G-RESTART-ACTIVATED-BOUNDED-LIVE`

Status: **AUTHORIZED BY USER / EXACT-MAIN DEPLOY / MAX 2 HA RESTARTS / RESTART #2 ROLLBACK-ONLY**

Primary contract:

`safety-poc/research/media/v1/P116_R30G_RESTART_ACTIVATED_BOUNDED_LIVE_CONTRACT.md`

## Roles

- Hermes: orchestrator only.
- Codex CLI: semantic executor and owner of diagnosis/hypothesis choice.
- Use one bounded Codex context for inspect -> preflight -> rollback preparation -> exact-main deploy -> restart #1 -> activation proof -> live attempts -> keep/rollback decision -> optional rollback restart #2 -> result.
- Hermes may mechanically relay exact Codex infrastructure commands where the Codex sandbox cannot access HA/CT120, returning complete stdout/stderr/scalar evidence to the same Codex context.
- Ordinary technical/test/CI defects inside the authorized child remain with Codex. Escalate only a new semantic, architecture, credential, production-write, safety, or restart boundary.

## Bootstrap

1. `git fetch origin main` and use actual latest `origin/main`; do not roll back a newer accepted main.
2. Read:

```text
safety-poc/research/media/v1/P116_R30G_RESTART_ACTIVATED_BOUNDED_LIVE_CONTRACT.md
safety-poc/research/media/v1/P116_R30F_PACKAGED_HELPER_BOUNDED_LIVE_RESULT.md
safety-poc/research/media/v1/P116_R30E_NATIVE_HELPER_REBUILD_PROVENANCE_RESULT.md
safety-poc/research/media/v1/P116_R30E_CI_FINALIZATION.md
safety-poc/docs/P116_HA_STREAM_RTP_BRIDGE.md
```

3. Create a separate R30G branch/worktree from fresh main.
4. Keep GitHub remote credential-free and use the project repo-local credential helper. Never print credentials.
5. Verify `codex-cli` availability/version. If unavailable, stop `RESULT=BLOCKED_EXECUTOR_UNAVAILABLE`.

## User authorization

The user explicitly authorized on 2026-09-17:

> R30G: deploy exact-main and up to two Home Assistant restarts; the second restart is authorized only for rollback if needed.

This authorization does not permit Door/Gate, HAOS/VM/host reboot, unrelated integrations, go2rtc/Frigate changes, protocol experiments outside current production behavior, or production-code edits.

## Restart budget

```text
MAX_HA_RESTARTS=2
RESTART_1_REQUIRED=true
RESTART_1_PURPOSE=activate_exact_main_python
RESTART_2_ALLOWED_ONLY_AFTER_ROLLBACK_DEPLOY=true
RESTART_2_PURPOSE=rollback_recovery_only
```

Never use restart #2 to retry exact-main, camera media, HA Stream, or generic troubleshooting.

No restart #3.

## Preflight

Before any write/restart/live operation Codex must define the exact procedure and Hermes must collect authoritative evidence for:

- fresh-main SHA;
- repo packaged helper SHA;
- repo transport pin;
- current deployed Comelit tree identity;
- preflight native helper SHA and transport pin using the trusted R30F mechanism;
- listener health;
- media/session inactive;
- camera/session entity state/availability;
- hard limit `<=600` seconds;
- HA core health;
- trusted rollback artifact for the actual preflight tree + SHA/integrity evidence;
- Door actions = 0 and Gate actions = 0 for this task.

Fail closed before deploy if rollback is not trustworthy, listener is persistently unhealthy, media is unexpectedly active, or fresh-main helper/pin disagree.

Do not assume preflight production is still `b96ad1690...`; record actual state.

## Deploy exact-main

Deploy only exact fresh-main:

```text
custom_components/comelit/**
```

Do not copy research/tests/docs to HA.

Verify after deploy, before restart #1:

```text
DEPLOYED_TREE_IDENTITY=<fresh-main>
DEPLOYED_NATIVE_SHA256=<repo packaged helper sha>
DEPLOYED_TRANSPORT_PIN=<repo transport pin>
MEDIA_INACTIVE=true
```

The accepted R30E helper is expected to be:

`a336477aa3564f4c99983a71621fc630885c55bf7ff07909bc70838d851a49b8`

unless a newer accepted fresh main explicitly supersedes it.

## Restart #1 — mandatory activation restart

Perform exactly one full Home Assistant restart through the existing authorized HA restart mechanism.

Do NOT reboot HAOS, VM, Proxmox host, or physical host.

After restart #1 wait for bounded recovery and verify before any camera action:

```text
HA_CORE_READY=true
COMELIT_SETUP_ERROR=false
LISTENER_READY=true
MEDIA_INACTIVE=true
CAMERA_SESSION_INACTIVE=true
DOOR_ACTIONS=0
GATE_ACTIONS=0
```

If HA/Comelit does not recover sufficiently for safe testing, do not retry exact-main restart. Enter rollback recovery.

## Loaded-code identity gate

Prove restart #1 actually activated the fresh-main Python/native pair.

Do not accept disk identity or listener READY alone.

Use the strongest existing evidence available without code changes. Direct runtime identity is preferred. Otherwise successful media native-gate startup with the fresh-main helper, absence of `media_native_binary_sha256_mismatch`, and exact P80/P116 helper markers may jointly prove the new pair.

Record:

```text
LOADED_CODE_IDENTITY_PROVEN=<true|false>
LOADED_CODE_IDENTITY_EVIDENCE=<concise evidence>
MEDIA_NATIVE_BINARY_SHA256_MISMATCH=<true|false>
```

If mismatch recurs after restart #1, stop exact-main testing and roll back. No exact-main restart retry.

## Live attempts

`MAX_LIVE_ATTEMPTS=5`.

No blind identical retries.

### Attempt 1 — new helper historical-boundary test

- Use the existing Comelit entrance-camera/session control path.
- Do not intentionally add HA Stream consumer.
- Start one media session.
- Observe objective P80/P116/native/RTP counters and timing.
- If healthy, keep it active long enough for objective media evidence beyond 60 seconds, then deliberately stop between about 60 and 90 seconds.
- Record activation latency, session duration, helper exit/teardown reason, video/audio counts, first/last monotonic/timestamp evidence, PT sets, SSRC changes, seq gaps, duplicates, out-of-order, timestamp regressions, SPS/PPS, FU-A/single-NAL and forwarding markers when available.

Set:

```text
HISTORICAL_36S_BOUNDARY_SURPASSED=true
```

only when objective media counters/timing prove healthy media beyond 60 seconds. State alone is insufficient.

After teardown verify mandatory invariant before continuing.

### Attempt 2 — HA Stream consumer

Run when Attempt 1 establishes healthy upstream/helper behavior, or Codex records a concrete diagnostic reason.

- Start a fresh bounded media session.
- Invoke normal HA Stream/camera consumer behavior.
- Determine whether HA/FFmpeg/PyAV objectively consumes the local RTP/SDP source.
- Use read-only logs/process/socket metadata as needed.
- Temporary output may exist only under `/tmp`; inspect safe size/ffprobe/container/codec metadata and delete it before completion.

Set `HA_STREAM_CONSUMER_PROVEN=true` only from objective consumer success, not merely helper RTP activity.

### Attempts 3–5

Before each:

```text
ATTEMPT_N_HYPOTHESIS=<specific evidence-backed hypothesis>
ATTEMPT_N_DISTINGUISHING_EVIDENCE=<result that distinguishes it>
```

No production-code edits and no restart beyond the contract.

## Mandatory post-attempt invariant

After every attempt require:

```text
MEDIA_INACTIVE=true
CAMERA_SESSION_INACTIVE=true
LISTENER_READY=true
PERSISTENT_NEW_RECONNECT_OR_ERROR=false
DOOR_ACTIONS=0
GATE_ACTIONS=0
```

Do not begin another attempt until restored.

If exact-main cannot restore this invariant without another restart, enter rollback recovery. Do not use restart #2 before rollback bytes are deployed.

## Keep / rollback decision

Keep exact-main deployed only if:

- restart #1 succeeded;
- loaded-code identity is proven;
- HA core remains healthy;
- listener is healthy after testing;
- media/session can be left inactive;
- no persistent new regression exists;
- Door/Gate actions remain zero.

For `PASS_END_TO_END` or safe `PASS_UPSTREAM_ONLY`, do not consume restart #2.

If exact-main creates a material production regression, identity mismatch, unrecoverable listener/session state, or otherwise cannot be kept safely, execute rollback recovery.

## Rollback recovery — only legal use of restart #2

Exact sequence:

```text
STOP live attempts
→ make media/session inactive as far as possible
→ deploy trusted preflight rollback Comelit tree
→ verify rollback deployment identity
→ perform HA restart #2
→ wait for HA core + Comelit listener
→ verify known-safe rollback state
→ STOP
```

After restart #2 verify:

```text
ROLLBACK_TREE_ACTIVE=true
HA_CORE_READY=true
LISTENER_READY=true
MEDIA_INACTIVE=true
DOOR_ACTIONS=0
GATE_ACTIONS=0
HA_RESTARTS=2
```

If rollback cannot be safely deployed or restart #2 cannot restore the known production state, return `FAIL_ROLLBACK_RECOVERY`. Never restart again.

## Evidence/privacy

Prefer scalar/status/log evidence.

Never print/commit credentials, raw RTP/H264/audio, screenshots/private frames, or persistent packet/media capture.

Any temporary media artifact must be `/tmp` only, metadata-inspected, then deleted.

## Repository write scope

Exactly:

```text
safety-poc/research/media/v1/P116_R30G_RESTART_ACTIVATED_BOUNDED_LIVE_RESULT.md
```

No production-code edits are authorized.

If a code defect is found, report exact files/root cause/minimal proposed fix/write-scope extension, then stop before editing.

## Git/GitHub

After result creation:

- run focused/full offline gates appropriate to a result-doc-only change;
- commit/push using the project credential rules;
- create PR if capability permits;
- if PR creation is denied, return branch + exact authoritative head SHA;
- do not begin a follow-on child.

## Final block

The useful task summary must be LAST in Hermes output:

```text
=== COMELIT P116 R30G RESTART-ACTIVATED BOUNDED LIVE ===
TASK_ID=COMELIT-P116-R30G-RESTART-ACTIVATED-BOUNDED-LIVE
BASE_SHA=<fresh-main>
PRE_R30G_DEPLOYED_SHA=<sha>
DEPLOYED_MAIN_SHA=<sha>
FINAL_DEPLOYED_SHA=<sha>
EXPECTED_NATIVE_SHA256=<sha>
DEPLOYED_NATIVE_SHA256=<sha>
FINAL_DEPLOYED_NATIVE_SHA256=<sha>
DEPLOYED_TRANSPORT_PIN=<sha>
DEPLOY_SHA_GATE=<PASS|FAIL>
ROLLBACK_BACKUP=<path-or-id-and-sha>
MAX_HA_RESTARTS=2
HA_RESTARTS=<0|1|2>
RESTART_1_RESULT=<PASS|FAIL|NOT_RUN>
RESTART_2_USED_FOR_ROLLBACK_ONLY=<true|false|na>
RESTART_2_RESULT=<PASS|FAIL|NOT_RUN>
LOADED_CODE_IDENTITY_PROVEN=<true|false|undetermined>
MEDIA_NATIVE_BINARY_SHA256_MISMATCH=<true|false|undetermined>
MAX_LIVE_ATTEMPTS=5
LIVE_ATTEMPTS_USED=<count>
ATTEMPT_1_RESULT=<PASS|FAIL|BLOCKED|SKIPPED>
ATTEMPT_1_MEDIA_DURATION_SECONDS=<value-or-na>
HISTORICAL_36S_BOUNDARY_SURPASSED=<true|false|undetermined>
ATTEMPT_2_RESULT=<PASS|FAIL|BLOCKED|SKIPPED>
HA_STREAM_CONSUMER_PROVEN=<true|false|undetermined>
HA_STREAM_ERROR=<value-or-none>
LISTENER_READY_BEFORE=<true|false>
LISTENER_READY_AFTER=<true|false>
LISTENER_RESTORED_AFTER_EACH_ATTEMPT=<true|false|na>
EXACT_MAIN_LEFT_DEPLOYED=<true|false>
ROLLBACK_PERFORMED=<true|false>
DOOR_ACTIONS=0
GATE_ACTIONS=0
RAW_MEDIA_COMMITTED=false
GO2RTC_CHANGED=false
FRIGATE_CHANGED=false
PRODUCTION_CODE_CHANGED=false
RESULT_DOC=<path-or-none>
PR=<number-or-none>
RESULT=<PASS_END_TO_END|PASS_UPSTREAM_ONLY|BLOCKED|FAIL|FAIL_ROLLBACK_RECOVERY>
=== END COMELIT P116 R30G RESTART-ACTIVATED BOUNDED LIVE ===
```

STOP after R30G. Do not begin production-code fixes, go2rtc/Frigate work, Door/Gate work, another restart, or another live/architecture child automatically.
