# P116 / R30F — Hermes/Codex execution task: packaged helper bounded live

TASK_ID=`COMELIT-P116-R30F-PACKAGED-HELPER-BOUNDED-LIVE`

Status: **BOUNDED LIVE AUTHORIZED BY USER / NO DOOR OR GATE**

Primary contract:

`safety-poc/research/media/v1/P116_R30F_PACKAGED_HELPER_BOUNDED_LIVE_CONTRACT.md`

## Roles

- Hermes: orchestrator only.
- Codex CLI: semantic executor and owner of diagnostics/hypothesis choice.
- One bounded Codex context should own inspect -> deploy plan -> live attempts -> diagnosis -> rollback/restore checks -> result.
- Ordinary implementation/test/CI defects stay in the same child and are corrected by Codex; escalate only a new semantic/scope/safety/credential/restart boundary.

## Bootstrap

1. `git fetch origin main` and use actual fresh `origin/main`; do not roll back a newer main.
2. Verify the R30E rebuild/provenance result and CI finalization are present.
3. Verify this task and the R30F contract are present in current main.
4. Create a separate R30F branch/worktree.
5. Keep GitHub remote credential-free and use the project repo-local credential helper. Never print credentials.
6. Verify `codex-cli` availability/version. If unavailable, stop `RESULT=BLOCKED_EXECUTOR_UNAVAILABLE`.

## Authorization

The user explicitly authorized the next bounded Comelit live stage on 2026-09-17.

Authorized scope:

- one HA integration only: Comelit;
- one exact-main integration deployment after backup/SHA verification;
- at most one Comelit integration reload if needed;
- maximum 10 physical entrance-camera media attempts;
- existing camera/media activation path only;
- read-only HA logs/state/process/socket diagnostics;
- bounded HA Stream consumer request;
- CT120 evidence/diagnostics as needed;
- temporary stream verification only under `/tmp`, removed afterward.

Forbidden:

- whole HA restart/reboot;
- Door or Gate actions;
- unrelated integrations;
- go2rtc or Frigate install/config changes;
- persistent/raw media capture in Git/evidence;
- protocol refresh/repeat experiments outside current production behavior;
- cloud/account/credential changes.

If whole-HA restart is needed for activation or rollback, stop `BLOCKED_HA_RESTART_REQUIRED`.

## Preflight and deployment

Codex must first produce the exact procedure. Hermes may mechanically execute infrastructure commands where Codex sandbox cannot, but must return complete scalar/status evidence to the same Codex context.

Before deploy verify and record:

- fresh-main SHA;
- repo native helper SHA and transport pin;
- installed HA native helper SHA and transport pin;
- listener healthy + media inactive;
- camera/session entity states;
- hard limit <=600s;
- rollback backup + SHA manifest for installed `custom_components/comelit/**`.

Deploy only exact-main `custom_components/comelit/**`, once. Verify deployed helper SHA against accepted R30E SHA `a336477aa3564f4c99983a71621fc630885c55bf7ff07909bc70838d851a49b8` unless fresh accepted main explicitly supersedes it.

Do not copy research/tests/docs to HA. Use integration reload only if required and supported. No HA restart.

If deploy/activation fails, rollback if possible without HA restart. Do not run live attempts with uncertain installed state.

## Live attempt lifecycle

Maximum 10 attempts; no identical blind retries.

### Attempt 1

Test the upstream/helper path without intentionally adding an HA Stream consumer. Observe up to 90 seconds. If healthy past 60 seconds, deliberately stop. Determine whether the historical ~35–36s stop is surpassed using objective media counters/timing, not only active state.

Capture safe scalar markers/counters and teardown reason. Verify listener restoration.

### Attempt 2

If Attempt 1 establishes a healthy upstream path, or Codex has a concrete reason, start a fresh session and invoke the normal HA Stream consumer. Determine objectively whether HA/FFmpeg/PyAV consumes the local RTP/SDP source.

Temporary `/tmp` output may be checked with ffprobe/metadata and deleted. Do not preserve or commit raw media.

### Attempts 3–10

Each requires a specific evidence-backed hypothesis and distinguishing result written before the attempt. Stop when decisive evidence is obtained or a new permission/architecture boundary is reached.

## Mandatory invariant after every attempt

- media inactive;
- camera/session control inactive;
- listener ready/running;
- no persistent reconnect/error regression;
- Door actions 0;
- Gate actions 0.

Do not use full HA restart for recovery.

## Write scope

By default, repository writes are limited to:

`safety-poc/research/media/v1/P116_R30F_PACKAGED_HELPER_BOUNDED_LIVE_RESULT.md`

No production-code edits are authorized in this live child. If an implementation defect is proven, return the exact minimal proposed write-scope extension before editing.

## Git/GitHub

After result creation:

- commit/push with project credential rules;
- create PR if token capability permits;
- if PR cannot be created, return branch + exact head SHA;
- do not deploy any follow-on production-code fix automatically.

## Final block

The useful block must be LAST:

```text
=== COMELIT P116 R30F PACKAGED HELPER BOUNDED LIVE ===
TASK_ID=COMELIT-P116-R30F-PACKAGED-HELPER-BOUNDED-LIVE
BASE_SHA=<fresh-main>
DEPLOYED_MAIN_SHA=<sha>
DEPLOYED_NATIVE_SHA256=<sha>
EXPECTED_NATIVE_SHA256=<sha>
DEPLOY_SHA_GATE=<PASS|FAIL>
ROLLBACK_BACKUP=<path-or-id>
HA_RESTARTS=0
INTEGRATION_RELOADS=<count>
MAX_LIVE_ATTEMPTS=10
LIVE_ATTEMPTS_USED=<count>
ATTEMPT_1_RESULT=<PASS|FAIL|SKIPPED|BLOCKED>
ATTEMPT_1_MEDIA_DURATION_SECONDS=<value-or-na>
HISTORICAL_36S_BOUNDARY_SURPASSED=<true|false|undetermined>
ATTEMPT_2_RESULT=<PASS|FAIL|SKIPPED|BLOCKED>
HA_STREAM_CONSUMER_PROVEN=<true|false|undetermined>
HA_STREAM_ERROR=<value-or-none>
LISTENER_READY_BEFORE=<true|false>
LISTENER_READY_AFTER=<true|false>
LISTENER_RESTORED_AFTER_EACH_ATTEMPT=<true|false>
DOOR_ACTIONS=0
GATE_ACTIONS=0
RAW_MEDIA_COMMITTED=false
GO2RTC_CHANGED=false
FRIGATE_CHANGED=false
PRODUCTION_CODE_CHANGED=false
RESULT_DOC=<path-or-none>
PR=<number-or-none>
RESULT=<PASS_END_TO_END|PASS_UPSTREAM_ONLY|BLOCKED|FAIL>
=== END COMELIT P116 R30F PACKAGED HELPER BOUNDED LIVE ===
```

STOP after R30F. Do not begin another live/architecture child automatically.
