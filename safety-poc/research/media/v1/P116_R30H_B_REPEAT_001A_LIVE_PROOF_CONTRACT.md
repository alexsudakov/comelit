# P116 / R30H-B — same-session repeat `0x001A` bounded live proof contract

TASK_ID=`COMELIT-P116-R30H-B-REPEAT-001A-LIVE-PROOF`

MODE=`BOUNDED_LIVE_RESEARCH`

User authorization: explicit authorization for `R30H-B live` was given on 2026-09-17.

## 1. Purpose

R30H-B answers one narrow protocol question left open by R26/R27/R30G/R30H-A:

> Does one same-session repeat client CTPP media request `0x001A`, sent after media is already active and before the historical ~35–36 second RTP cutoff, extend entrance-camera RTP in the same unchanged media session?

This child is a proof stage, not a production implementation stage.

R30H-B MUST use the already revalidated R27 research candidate and corrected candidate-wrapper binding. It MUST NOT add a periodic refresh loop, change the research delay to 15 seconds, modify production code, deploy a new Home Assistant integration, or perform a Home Assistant restart.

## 2. Source of truth

At task creation the accepted repository main is:

```text
7335a351d9ec652d82d271af59a04b87276189ea
```

Execution MUST begin with a fresh authenticated `git fetch origin main` and MUST use the actual latest accepted `origin/main`. A newer accepted main MUST NOT be rolled back merely to match the SHA above.

Relevant accepted lineage:

- `P116_R30H_A_REPEAT_001A_OFFLINE_REVALIDATION_RESULT.md` — `PASS_LIVE_READY`.
- `P116_R26_D1_MEDIA_LEASE_REFRESH_ANALYSIS.md` — initial video-start request identified as client `0x001A`; same-session repeat remained unproven.
- `P116_R27_D1_REPEAT_001A_LIVE_PROOF.md` — historical live attempt was insufficient because the candidate helper never executed.
- `entrance_p116_r27_repeat_001a_transform.py` — one-shot repeat research overlay.
- `ct120_run_p116_r27_repeat_001a_live.sh` — corrected bounded live runner.
- `test_p116_r27_repeat_001a_contract.py` — one-shot/fail-closed contract tests.

## 3. Inherited facts that must not be re-proven by broad experimentation

R30G already established:

```text
LOADED_CODE_IDENTITY_PROVEN=true
HA_STREAM_CONSUMER_PROVEN=true
R30G_ATTEMPT_1_VIDEO_RTP_SPAN_SECONDS=34.580
R30G_ATTEMPT_2_VIDEO_RTP_SPAN_SECONDS=35.330
HISTORICAL_36S_BOUNDARY_SURPASSED=false
```

R30H-A established offline:

```text
RESULT=PASS_LIVE_READY
CANDIDATE_SOURCE_SHA256=1c9f13cff0d1d3599e00109146310c7372b1b0ae12117bb46ad68f091a841d42
CANDIDATE_BINARY_SHA256_REFERENCE=baeb9406b503a43542bc89b2a89a8d18b5564b429646113ccfd81367432f69a4
WRAPPER_BINDING_GATE=PASS
BASE_WRAPPER_FALLBACK_POSSIBLE=false
ONE_SHOT_REPEAT_CONTRACT=PASS
R30H_A_REPEAT_DELAY_SECONDS=20
R30H_A_REPEAT_DELAY_IS_PROTOCOL_CONSTANT=false
R30H_A_REPEAT_DELAY_PROMOTED_TO_PRODUCTION=false
```

The external 15-second cadence remains corroborating evidence only. R30H-B tests the existing one-shot 20-second research repeat because 20 seconds is still safely before the observed ~35-second cutoff.

## 4. Authorized live scope

R30H-B authorizes exactly one bounded live entrance-camera research session through the accepted corrected R27 runner.

Authorized actions:

1. Authenticated GitHub fetch on CT120 under the project credential rules.
2. Prepare a clean repository at the actual accepted `origin/main`.
3. Run offline preflight/build gates required by `ct120_run_p116_r27_repeat_001a_live.sh`.
4. Read-only Home Assistant/Comelit listener status through the already established control path.
5. Stop only the persistent Comelit listener for the bounded research session.
6. Execute exactly one candidate-wrapper invocation.
7. Permit exactly one research same-session repeat client `0x001A`, expected around 20 seconds after media active.
8. Observe only bounded scalar/native markers and localhost RTP packet counters required by the accepted runner.
9. Teardown the research session.
10. Restore the persistent Comelit listener and verify readiness.
11. Write a result document and commit/push it.

No second live invocation is authorized in this child, including as a retry after an inconclusive or failed run.

```text
MAX_LIVE_INVOCATIONS=1
MAX_REPEAT_001A=1
MAX_TOTAL_CLIENT_001A=2
SECOND_MEDIA_SESSION=false
AUTOMATIC_RETRY=false
```

## 5. Explicitly forbidden actions

R30H-B does NOT authorize:

- Door action;
- Gate action;
- second camera/media session;
- third `0x001A`;
- periodic refresh loop;
- changing repeat delay from 20 seconds to 15 seconds;
- production refresh implementation;
- any `custom_components/comelit/**` code change;
- replacement of packaged `custom_components/comelit/native/comelit-media`;
- deploy to Home Assistant;
- config-entry reload;
- Home Assistant Core restart;
- HAOS reboot;
- VM reboot;
- Proxmox/host reboot;
- go2rtc or Frigate changes;
- unrelated integration changes;
- credential changes;
- raw PCAP capture;
- raw RTP/H264/audio persistence;
- official-app capture;
- new protocol experiments beyond the existing one-shot repeat path.

If any of the above is required, STOP and report the exact blocker.

## 6. Preflight gates

Before stopping the production listener, execution MUST prove:

```text
FRESH_MAIN_FETCHED=true
REPO_HEAD_EQUALS_ACCEPTED_MAIN=true
WORKTREE_CLEAN=true
R30H_A_RESULT_PRESENT=true
R30H_A_RESULT=PASS_LIVE_READY
R27_RUNNER_PRESENT=true
R27_TRANSFORM_PRESENT=true
R27_CONTRACT_TEST_PRESENT=true
EXPECTED_GENERATED_SOURCE_SHA_GATE=PASS
BASE_WRAPPER_SHA256_GATE=PASS
LISTENER_READY_BEFORE=true
PRODUCTION_MEDIA_ACTIVE_BEFORE=false
DOOR_ACTIONS_BEFORE=0
GATE_ACTIONS_BEFORE=0
```

The focused R27 contract test SHOULD be run before live execution. Any failure in candidate generation, candidate build, wrapper substitution, helper identity, or listener health is fail-closed: no live invocation.

## 7. Candidate identity and wrapper-binding gate

R30H-B MUST preserve the R30H-A corrective that prevents silent fallback to the base helper.

Before live invocation, record and prove:

```text
CANDIDATE_SOURCE_SHA256=<sha>
CANDIDATE_BINARY_SHA256=<sha>
CANDIDATE_WRAPPER_PARSE=PASS
BASE_HOLDER_PATH_PRESENT_IN_CANDIDATE_WRAPPER=false
CANDIDATE_HOLDER_PATH_PRESENT_IN_CANDIDATE_WRAPPER=true
WRAPPER_BINDING_GATE=PASS
```

A run is unusable if helper-lineage markers do not prove the candidate media path reached the expected state.

## 8. Live observation

The accepted runner observes for up to 70 seconds after media active and has an outer 150-second hard bound.

The live child MUST make only the existing one-shot repeat attempt. Expected semantics:

```text
INITIAL_001A_SENT_COUNT=1
REPEAT_001A_SENT_COUNT=1
TOTAL_001A_SENT_COUNT=2
THIRD_001A=false
NEW_ICE_NEGOTIATION_AFTER_REPEAT=false
NEW_PSEUDOTCP_AFTER_REPEAT=false
NEW_CTPP_REGISTRATION_AFTER_REPEAT=false
NEW_RTPC_OPEN_AFTER_REPEAT=false
NEW_SELF_ACTIVATION_AFTER_REPEAT=false
HELPER_PROCESS_UNCHANGED=true
```

The repeat response MAY classify as `STRUCTURAL_ACK`, `ABSENT`, or `AMBIGUOUS`; R30H-B must report the observed class without inventing a stronger interpretation.

## 9. Primary proof question

The decisive evidence is whether video RTP continues beyond the historical cutoff after the repeat.

Strong positive proof requires all of:

```text
R27_RUN_CLASSIFICATION=OBSERVATION_USABLE
R27_REPEAT_EXECUTED=true
INITIAL_001A_SENT_COUNT=1
REPEAT_001A_SENT_COUNT=1
TOTAL_001A_SENT_COUNT=2
VIDEO_RTP_AFTER_REPEAT=true
VIDEO_RTP_PAST_40S=true
VIDEO_RTP_LAST_SECONDS_FROM_INITIAL_START>=40
```

`VIDEO_RTP_PAST_40S=true` is used as the minimum proof threshold because R30G reproduced the untreated stop at 34.580 and 35.330 seconds. A result materially beyond 40 seconds therefore crosses the established baseline with margin.

If the repeat is sent but RTP still ends at or before 40 seconds, the lease-extension hypothesis is NOT proven.

A repeat ACK alone is not sufficient to claim lease extension.

## 10. Result classes

Use exactly one final result class:

### `PASS_REPEAT_EXTENDS_RTP`

Use when the run is usable, the repeat was actually sent exactly once, and video RTP continues beyond 40 seconds in the same session.

This result proves a one-shot same-session `0x001A` repeat can extend the observed RTP lifetime under this environment. It does NOT by itself choose a production cadence or authorize a periodic implementation.

### `FAIL_REPEAT_NO_EXTENSION`

Use when the run is usable and repeat execution is proven, but video RTP does not continue beyond 40 seconds.

### `BLOCKED_REPEAT_NOT_EXECUTED`

Use when the candidate reaches a usable media path but the repeat does not execute because a bounded precondition/gate prevents it.

### `INCONCLUSIVE`

Use for outer timeout, teardown uncertainty, insufficient helper-lineage evidence, loss of listener restoration confidence, or other evidence quality failures that prevent a safe protocol conclusion.

No automatic retry is allowed for any result class.

## 11. Teardown and production restoration

Regardless of result, the bounded session MUST end and the production listener MUST be restored.

Required final safety state:

```text
CAMPAIGN_PROCESSES_REMAINING=NONE
CT120_RESEARCH_HELPER_STOPPED=true
CT120_RESEARCH_SESSION_CLOSED=true
R30H_B_SESSION_CLOSED=true
TEARDOWN_CONFIDENCE=CONFIRMED
LISTENER_RUNNING_AFTER=true
LISTENER_READY_AFTER=true
PRODUCTION_MEDIA_ACTIVE=false
DOOR_ACTIONS_SENT=0
GATE_ACTIONS_SENT=0
HA_RESTARTED=false
HA_DEPLOYED=false
```

If listener restoration fails, do not perform a Home Assistant restart. Report `INCONCLUSIVE` and the exact restoration evidence/blocker.

## 12. Repository write scope

Default repository write scope is result evidence only:

```text
safety-poc/research/media/v1/P116_R30H_B_REPEAT_001A_LIVE_PROOF_RESULT.md
```

No executable or production code changes are authorized in R30H-B.

If an ordinary defect in the existing research runner prevents execution before any live invocation and Codex can make a bounded research-only corrective without changing protocol semantics, STOP and report the defect and proposed patch rather than silently expanding this live child. A separate decision is required before changing executable research code during R30H-B.

## 13. GitHub rules

All GitHub operations on CT120 must use the project credential store:

```text
/root/.config/git/comelit.credentials
```

The token must never be printed, logged, embedded in URLs, scripts, commits, or result documents. Repository remotes remain credential-free.

Per-repository settings where GitHub access is needed:

```bash
git config credential.helper 'store --file=/root/.config/git/comelit.credentials'
git config credential.useHttpPath true
```

## 14. Stop boundary

After one live invocation, result capture, listener restoration, and result-doc commit/push/PR attempt, STOP.

R30H-B does not automatically authorize production implementation, a second live test, a 15-second periodic refresh, or any following child.
