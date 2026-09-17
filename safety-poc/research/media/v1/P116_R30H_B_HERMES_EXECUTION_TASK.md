# Hermes execution task — P116 / R30H-B same-session repeat `0x001A` live proof

TASK_ID=`COMELIT-P116-R30H-B-REPEAT-001A-LIVE-PROOF`

MODE=`BOUNDED_LIVE_RESEARCH`

User approval status: `AUTHORIZED`.

The user explicitly authorized `R30H-B live` on 2026-09-17.

## Execution model

- Hermes is the orchestrator only.
- Use one bounded Codex CLI context for semantic inspection, evidence interpretation, and result-document authorship.
- Hermes may perform the approved infrastructure relay on CT120 and return raw scalar/stdout evidence into the same Codex context.
- Do not create a second semantic child unless the current child is irrecoverably broken before any live action; in that case STOP and report instead of silently restarting the task.

## Mandatory source bootstrap

Start with a fresh authenticated fetch and use the actual latest accepted `origin/main`.

At task creation the expected main is:

```text
7335a351d9ec652d82d271af59a04b87276189ea
```

Read at minimum:

```text
safety-poc/research/media/v1/P116_R30H_B_REPEAT_001A_LIVE_PROOF_CONTRACT.md
safety-poc/research/media/v1/P116_R30H_A_REPEAT_001A_OFFLINE_REVALIDATION_RESULT.md
safety-poc/research/media/v1/P116_R26_D1_MEDIA_LEASE_REFRESH_ANALYSIS.md
safety-poc/research/media/v1/P116_R27_D1_REPEAT_001A_LIVE_PROOF.md
safety-poc/research/media/v1/P116_R30G_RESTART_ACTIVATED_BOUNDED_LIVE_RESULT.md
safety-poc/research/media/v1/entrance_p116_r27_repeat_001a_transform.py
safety-poc/research/media/v1/ct120_run_p116_r27_repeat_001a_live.sh
safety-poc/tests/test_p116_r27_repeat_001a_contract.py
```

## Goal

Run exactly one corrected R27 research candidate session on the physical entrance-camera path and determine whether the one same-session repeat client `0x001A` around 20 seconds extends video RTP beyond the established untreated ~35-second boundary.

Do not test anything else.

## Hard limits

```text
MAX_LIVE_INVOCATIONS=1
MAX_REPEAT_001A=1
MAX_TOTAL_CLIENT_001A=2
MAX_MEDIA_OBSERVATION_SECONDS=70
OUTER_TIMEOUT_SECONDS=150
MAX_HA_RESTARTS=0
MAX_HA_RELOADS=0
MAX_DOOR_ACTIONS=0
MAX_GATE_ACTIONS=0
SECOND_MEDIA_SESSION=false
PERIODIC_REFRESH_LOOP=false
```

The existing research delay remains:

```text
REPEAT_DELAY_SECONDS=20
REPEAT_DELAY_IS_PROTOCOL_CONSTANT=false
REPEAT_DELAY_PROMOTED_TO_PRODUCTION=false
```

Do not change it to 15 seconds during this task.

## Phase 1 — repository and identity preflight

On CT120, configure repo-local Git credentials without exposing the token:

```bash
git config credential.helper 'store --file=/root/.config/git/comelit.credentials'
git config credential.useHttpPath true
```

Requirements:

- `/root/.config/git/comelit.credentials` exists and mode is `600`;
- remote URL contains no token;
- fetch `origin main` succeeds authenticated;
- use the actual latest accepted main;
- repository used by the live runner is a full clone with `.git` directory, clean, and detached/exact at accepted main if necessary.

Do not print credential contents.

Record:

```text
FRESH_MAIN_FETCHED=<true|false>
ACCEPTED_MAIN_SHA=<sha>
REPO_HEAD=<sha>
REPO_HEAD_EQUALS_ACCEPTED_MAIN=<true|false>
WORKTREE_CLEAN=<true|false>
REMOTE_CREDENTIAL_FREE=<true|false>
CREDENTIAL_FILE_MODE_OK=<true|false>
```

## Phase 2 — offline gates before live

Before any listener stop or candidate execution:

1. Confirm R30H-A result is present and `PASS_LIVE_READY`.
2. Re-run the focused R27 contract test.
3. Confirm current runner/transform/build pins are self-consistent.
4. Confirm base wrapper hash gate.
5. Confirm current production listener is ready and no production media session is active.
6. Confirm Door/Gate action counters/baseline remain zero through the established safe status path if available.

Fail closed before live if any required gate fails.

## Phase 3 — exact live runner

Use the accepted current `ct120_run_p116_r27_repeat_001a_live.sh` directly. Do not hand-reimplement the protocol sequence.

Run it with:

```text
R27_LIVE_RUN=YES
R27_EXPECTED_COMMIT_SHA=<accepted-main-sha>
REPO=<clean-full-clone-at-accepted-main>
```

The runner itself must:

- build the ephemeral candidate;
- prove expected generated-source SHA;
- materialize the candidate wrapper;
- verify wrapper rewrite/parse;
- verify listener ready;
- stop only the Comelit persistent listener;
- start localhost RTP sinks;
- execute exactly one candidate wrapper invocation;
- allow the one-shot repeat logic;
- stop/teardown the candidate;
- restore the persistent listener;
- print its final scalar block.

Do not run the candidate wrapper manually in parallel or a second time.

## Phase 4 — evidence acceptance gate

A protocol conclusion is valid only if:

```text
LIVE_INVOCATIONS=1
R27_RUN_CLASSIFICATION=OBSERVATION_USABLE
R27_USABLE_EVIDENCE=true
R27_HELPER_EVIDENCE_GATE=PASS
TEARDOWN_CONFIDENCE=CONFIRMED
```

If any of these fail, classify `INCONCLUSIVE` and do not infer repeat behavior from suppressed/partial scalars.

## Phase 5 — repeat proof interpretation

Capture exactly:

```text
R27_REPEAT_EXECUTED=<true|false>
INITIAL_001A_SENT_COUNT=<n>
REPEAT_001A_SENT_COUNT=<n>
TOTAL_001A_SENT_COUNT=<n>
SECOND_001A_RESPONSE=<STRUCTURAL_ACK|ABSENT|AMBIGUOUS|...>
VIDEO_RTP_BEFORE_REPEAT=<...>
VIDEO_PACKET_COUNT_AT_REPEAT=<n>
VIDEO_RTP_AFTER_REPEAT=<true|false>
VIDEO_RTP_PAST_35S=<true|false>
VIDEO_RTP_PAST_40S=<true|false>
VIDEO_RTP_LAST_SECONDS_FROM_INITIAL_START=<n>
ICE_NEGOTIATION_COUNT=<n>
PSEUDOTCP_OPEN_COUNT=<n>
CTPP_REGISTRATION_COUNT=<n>
RTPC_CLIENT_OPEN_COUNT=<n>
SELF_ACTIVATION_COUNT=<n>
HELPER_PROCESS_UNCHANGED=<true|false>
```

Primary positive proof requires:

```text
R27_REPEAT_EXECUTED=true
INITIAL_001A_SENT_COUNT=1
REPEAT_001A_SENT_COUNT=1
TOTAL_001A_SENT_COUNT=2
VIDEO_RTP_AFTER_REPEAT=true
VIDEO_RTP_PAST_40S=true
VIDEO_RTP_LAST_SECONDS_FROM_INITIAL_START>=40
```

An ACK alone is not enough.

If the repeat executes but RTP remains at/below 40 seconds, classify `FAIL_REPEAT_NO_EXTENSION`.

If repeat never executes despite otherwise usable media state, classify `BLOCKED_REPEAT_NOT_EXECUTED`.

## Phase 6 — mandatory safety restoration

After the one live invocation, regardless of result, prove:

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
HA_RELOADED=false
```

If the listener is not restored, do not restart Home Assistant. STOP with `INCONCLUSIVE` and report the restoration blocker.

## Phase 7 — result document

Write only:

```text
safety-poc/research/media/v1/P116_R30H_B_REPEAT_001A_LIVE_PROOF_RESULT.md
```

The result doc must clearly separate:

- preflight facts;
- candidate/build/wrapper identity;
- live session facts;
- repeat response class;
- RTP timing/effect;
- teardown/listener restoration;
- what was not proven;
- exact result class.

No raw token, raw SDP, raw packet bytes, raw RTP/H264/audio, peer credentials, private addresses not already canonical, or secret/session material may be committed.

## Phase 8 — GitHub completion

Commit/push only the result document unless this task was blocked before live and no result doc is justified.

Attempt PR creation. If the CT120 token still lacks `createPullRequest`, return branch name and exact remote head SHA so ChatGPT can create the PR with the connected GitHub tool.

Do not change executable code in R30H-B.

## Required final result class

Exactly one of:

```text
PASS_REPEAT_EXTENDS_RTP
FAIL_REPEAT_NO_EXTENSION
BLOCKED_REPEAT_NOT_EXECUTED
INCONCLUSIVE
```

## Required final marker block

Print this block LAST, after all other output:

```text
=== COMELIT P116 R30H-B REPEAT 001A LIVE PROOF ===
TASK_ID=COMELIT-P116-R30H-B-REPEAT-001A-LIVE-PROOF
BASE_SHA=<accepted-main-sha>
LIVE_AUTHORIZED=true
MAX_LIVE_INVOCATIONS=1
LIVE_INVOCATIONS=<0|1>
R30H_A_RESULT=PASS_LIVE_READY
CANDIDATE_SOURCE_SHA256=<sha|NOT_REACHED>
CANDIDATE_BINARY_SHA256=<sha|NOT_REACHED>
WRAPPER_BINDING_GATE=<PASS|FAIL|NOT_REACHED>
R27_HELPER_EVIDENCE_GATE=<PASS|FAIL|NOT_REACHED>
R27_RUN_CLASSIFICATION=<value>
R27_USABLE_EVIDENCE=<true|false>
R27_REPEAT_DELAY_SECONDS=20
R27_REPEAT_DELAY_IS_PROTOCOL_CONSTANT=false
R27_REPEAT_DELAY_PROMOTED_TO_PRODUCTION=false
R27_REPEAT_EXECUTED=<true|false|NOT_REACHED>
INITIAL_001A_SENT_COUNT=<n|NOT_REACHED>
REPEAT_001A_SENT_COUNT=<n|NOT_REACHED>
TOTAL_001A_SENT_COUNT=<n|NOT_REACHED>
SECOND_001A_RESPONSE=<value|NOT_REACHED>
VIDEO_RTP_AFTER_REPEAT=<true|false|NOT_REACHED>
VIDEO_RTP_PAST_35S=<true|false|NOT_REACHED>
VIDEO_RTP_PAST_40S=<true|false|NOT_REACHED>
VIDEO_RTP_LAST_SECONDS_FROM_INITIAL_START=<n|NOT_REACHED>
ICE_NEGOTIATION_COUNT=<n|NOT_REACHED>
PSEUDOTCP_OPEN_COUNT=<n|NOT_REACHED>
CTPP_REGISTRATION_COUNT=<n|NOT_REACHED>
RTPC_CLIENT_OPEN_COUNT=<n|NOT_REACHED>
SELF_ACTIVATION_COUNT=<n|NOT_REACHED>
HELPER_PROCESS_UNCHANGED=<true|false|NOT_REACHED>
CAMPAIGN_PROCESSES_REMAINING=<NONE|FOUND|UNKNOWN>
CT120_RESEARCH_HELPER_STOPPED=<true|false>
CT120_RESEARCH_SESSION_CLOSED=<true|false>
R30H_B_SESSION_CLOSED=<true|false>
TEARDOWN_CONFIDENCE=<CONFIRMED|UNCERTAIN>
LISTENER_RUNNING_AFTER=<true|false>
LISTENER_READY_AFTER=<true|false>
PRODUCTION_MEDIA_ACTIVE=<false|true|unknown>
DOOR_ACTIONS_SENT=0
GATE_ACTIONS_SENT=0
HA_RESTARTED=false
HA_DEPLOYED=false
HA_RELOADED=false
SECOND_MEDIA_SESSION=false
THIRD_001A=false
REFRESH_LOOP=false
PRODUCTION_CODE_CHANGED=false
RESULT_DOC=safety-poc/research/media/v1/P116_R30H_B_REPEAT_001A_LIVE_PROOF_RESULT.md
PR=<number|none>
RESULT=<PASS_REPEAT_EXTENDS_RTP|FAIL_REPEAT_NO_EXTENSION|BLOCKED_REPEAT_NOT_EXECUTED|INCONCLUSIVE>
=== END COMELIT P116 R30H-B REPEAT 001A LIVE PROOF ===
```

After this block, STOP. Do not start a production refresh implementation or another live child automatically.
