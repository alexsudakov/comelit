# P116 / R30H-D — corrected-runner same-session repeat `0x001A` bounded live proof contract

TASK_ID=`COMELIT-P116-R30H-D-REPEAT-001A-LIVE-PROOF`

MODE=`BOUNDED_LIVE_RESEARCH`

User authorization: explicit authorization was given on 2026-09-17 for exactly one bounded live run on the physical entrance camera, with temporary stop and mandatory restoration of the persistent Comelit listener, exactly one repeat client `0x001A` at the existing 20-second research delay, observation up to 70 seconds, no second media session, no retry, Door/Gate actions zero, and no Home Assistant restart/reload/deploy.

## 1. Purpose

R30H-D answers one narrow protocol question:

> With the R30H-C execution-boundary corrective active, does exactly one same-session repeat client CTPP media request `0x001A`, emitted after media is already active and before the established untreated ~35-second RTP cutoff, extend entrance-camera RTP beyond that cutoff in the same unchanged media session?

This is a bounded proof stage only. It is not a production refresh implementation.

## 2. Source of truth

At task creation the accepted repository main is:

```text
8ec80651bd56f34898222dee07e140269c9fdb94
```

Execution MUST begin with a fresh authenticated `git fetch origin main` and MUST use the actual latest accepted `origin/main`. A newer accepted main MUST NOT be rolled back merely to match the SHA above.

Relevant accepted lineage:

```text
safety-poc/research/media/v1/P116_R30H_C_MUSL_LAUNCHER_OFFLINE_CORRECTIVE_RESULT.md
safety-poc/research/media/v1/P116_R30H_B_REPEAT_001A_LIVE_PROOF_RESULT.md
safety-poc/research/media/v1/P116_R30H_A_REPEAT_001A_OFFLINE_REVALIDATION_RESULT.md
safety-poc/research/media/v1/P116_R30G_RESTART_ACTIVATED_BOUNDED_LIVE_RESULT.md
safety-poc/research/media/v1/P116_R26_D1_MEDIA_LEASE_REFRESH_ANALYSIS.md
safety-poc/research/media/v1/entrance_p116_r27_repeat_001a_transform.py
safety-poc/research/media/v1/ct120_run_p116_r27_repeat_001a_live.sh
safety-poc/tests/test_p116_r27_repeat_001a_contract.py
```

## 3. Inherited facts

R30G established the untreated boundary and ruled out HA Stream as the initiating cause:

```text
R30G_ATTEMPT_1_VIDEO_RTP_SPAN_SECONDS=34.580
R30G_ATTEMPT_2_VIDEO_RTP_SPAN_SECONDS=35.330
HA_STREAM_CONSUMER_PROVEN=true
HISTORICAL_36S_BOUNDARY_SURPASSED=false
```

R30H-B did not test the repeat hypothesis because the raw musl ELF failed before helper startup.

R30H-C closed that execution-boundary blocker offline:

```text
R30H_C_RESULT=PASS_EXECUTION_PATH_READY
LOADER_PROBE_EXECUTED=true
LOADER_PROBE_RC=0
LOADER_PROBE_RESOLUTION=PASS
CANDIDATE_MAIN_EXECUTED=false
GLIBC_RESOLUTION_USED=false
WRAPPER_BINDING_GATE=PASS
RAW_CANDIDATE_PATH_PRESENT_AS_HOLDER=false
CANDIDATE_LAUNCHER_PATH_PRESENT_IN_CANDIDATE_WRAPPER=true
ONE_SHOT_REPEAT_CONTRACT=PASS
```

R30H-C did not prove any live protocol or RTP behavior.

## 4. Authorized live scope

Authorized actions are limited to:

1. Authenticated GitHub fetch on CT120 under the project credential rules.
2. Prepare one clean full clone/detached checkout at actual accepted `origin/main`.
3. Re-run bounded offline gates needed to prove current runner/candidate identity.
4. Use the established Comelit listener status/control path for read-only status, one stop before the run, and mandatory restoration after the run.
5. Execute exactly one invocation of the accepted corrected `ct120_run_p116_r27_repeat_001a_live.sh`.
6. Permit the existing research candidate to emit at most one initial client `0x001A` and exactly one bounded repeat attempt at the existing 20-second delay if its fail-closed preconditions are met.
7. Observe scalar/native markers and localhost RTP counters only.
8. Observe up to 70 seconds after media active, with the runner's existing 150-second outer hard bound.
9. Teardown the research session and restore the persistent Comelit listener.
10. Write and push the result document.

Hard limits:

```text
MAX_LIVE_INVOCATIONS=1
MAX_MEDIA_SESSIONS=1
MAX_INITIAL_001A=1
MAX_REPEAT_001A=1
MAX_TOTAL_CLIENT_001A=2
REPEAT_DELAY_SECONDS=20
MAX_MEDIA_OBSERVATION_SECONDS=70
OUTER_TIMEOUT_SECONDS=150
MAX_HA_RESTARTS=0
MAX_HA_RELOADS=0
MAX_HA_DEPLOYS=0
MAX_DOOR_ACTIONS=0
MAX_GATE_ACTIONS=0
AUTOMATIC_RETRY=false
PERIODIC_REFRESH_LOOP=false
```

The 20-second delay remains a research value only:

```text
REPEAT_DELAY_IS_PROTOCOL_CONSTANT=false
REPEAT_DELAY_PROMOTED_TO_PRODUCTION=false
```

## 5. Explicitly forbidden actions

R30H-D does NOT authorize:

- a second live invocation for any reason;
- a second camera/media session;
- a third client `0x001A`;
- automatic retry of the repeat;
- periodic refresh implementation;
- changing the repeat delay to 15 seconds or any other value;
- Door action;
- Gate action;
- any physical actuator action;
- any `custom_components/comelit/**` production-code change;
- replacement of packaged `custom_components/comelit/native/comelit-media`;
- Home Assistant deploy;
- Home Assistant config-entry reload;
- Home Assistant Core restart;
- HAOS/VM/Proxmox reboot;
- go2rtc/Frigate changes;
- unrelated integration changes;
- credential changes;
- raw PCAP capture;
- raw RTP/H264/audio persistence;
- official-app capture;
- new protocol experiments beyond the accepted one-shot repeat path;
- executable-code changes during the live child.

If any forbidden action appears necessary, STOP and report the blocker. Do not consume another live invocation.

## 6. Repository and identity preflight

Before any listener stop or live execution, prove:

```text
FRESH_MAIN_FETCHED=true
ACCEPTED_MAIN_SHA=<actual latest accepted origin/main>
REPO_HEAD_EQUALS_ACCEPTED_MAIN=true
WORKTREE_CLEAN=true
REMOTE_CREDENTIAL_FREE=true
CREDENTIAL_FILE_MODE_OK=true
R30H_C_RESULT_PRESENT=true
R30H_C_RESULT=PASS_EXECUTION_PATH_READY
R27_RUNNER_PRESENT=true
R27_TRANSFORM_PRESENT=true
R27_CONTRACT_TEST_PRESENT=true
EXPECTED_GENERATED_SOURCE_SHA_GATE=PASS
BASE_WRAPPER_SHA256_GATE=PASS
FOCUSED_R27_CONTRACT_TEST=PASS
```

Use the Comelit credential store without printing it:

```text
/root/.config/git/comelit.credentials
```

Repo-local Git configuration must remain:

```text
credential.helper=store --file=/root/.config/git/comelit.credentials
credential.useHttpPath=true
```

The remote URL must remain credential-free.

## 7. Execution-path preflight

Before listener stop, re-prove enough of R30H-C to prevent consuming the sole live invocation on the old raw-musl failure:

```text
CANDIDATE_SOURCE_SHA256=<sha>
CANDIDATE_BINARY_SHA256=<sha>
CANDIDATE_INTERPRETER=/lib/ld-musl-x86_64.so.1
LOADER_PROBE_EXECUTED=true
LOADER_PROBE_RC=0
LOADER_PROBE_RESOLUTION=PASS
CANDIDATE_MAIN_EXECUTED=false
GLIBC_RESOLUTION_USED=false
WRAPPER_BINDING_GATE=PASS
RAW_CANDIDATE_PATH_PRESENT_AS_HOLDER=false
CANDIDATE_LAUNCHER_PATH_PRESENT_IN_CANDIDATE_WRAPPER=true
```

The offline loader-native probe is allowed and does not count as a live invocation because candidate `main()` is not entered and no Comelit network request is made.

If this gate fails, STOP before listener stop and before live execution.

## 8. Production-state preflight

Immediately before live execution prove via the established safe status path:

```text
LISTENER_READY_BEFORE=true
PRODUCTION_MEDIA_ACTIVE_BEFORE=false
DOOR_ACTIONS_BEFORE=0
GATE_ACTIONS_BEFORE=0
CAMPAIGN_PROCESSES_BEFORE=0
```

A healthy listener-ready state may be used with the accepted media-exclusivity invariant to prove no production media lease is active. Do not add a new HA mechanism solely to obtain another scalar.

## 9. Exact live runner

Use the accepted current runner directly:

```text
safety-poc/research/media/v1/ct120_run_p116_r27_repeat_001a_live.sh
```

Run it exactly once with:

```text
R27_LIVE_RUN=YES
R27_EXPECTED_COMMIT_SHA=<accepted-main-sha>
REPO=<clean full clone at accepted-main-sha>
```

Do not execute the candidate wrapper manually in parallel or before/after the runner.

The corrected runner must itself:

- build the ephemeral candidate;
- validate generated-source provenance;
- materialize the per-run musl loader and candidate launcher;
- materialize the wrapper bound to the launcher, not raw ELF;
- verify wrapper parsing/binding;
- verify listener ready;
- stop only the persistent Comelit listener;
- start localhost video/audio RTP sinks;
- execute exactly one candidate-wrapper invocation;
- allow at most one repeat `0x001A` attempt according to existing fail-closed gates;
- teardown the candidate;
- restore the persistent listener;
- emit the final scalar block.

## 10. Evidence acceptance gate

A protocol conclusion is valid only if all are true:

```text
LIVE_INVOCATIONS=1
R27_RUN_CLASSIFICATION=OBSERVATION_USABLE
R27_USABLE_EVIDENCE=true
R27_HELPER_EVIDENCE_GATE=PASS
TEARDOWN_CONFIDENCE=CONFIRMED
```

Additionally the live log must prove the corrected execution path reached helper protocol/media state; the absence of the prior R30H-B `cannot execute: required file not found` failure is necessary but not sufficient.

If the acceptance gate fails, classify `INCONCLUSIVE`. Do not infer repeat behavior from partial or suppressed scalars, and do not retry.

## 11. Required repeat evidence

When the acceptance gate passes, record exactly:

```text
R27_REPEAT_EXECUTED=<true|false>
INITIAL_001A_SENT_COUNT=<n>
REPEAT_001A_SENT_COUNT=<n>
TOTAL_001A_SENT_COUNT=<n>
SECOND_001A_RESPONSE=<STRUCTURAL_ACK|ABSENT|AMBIGUOUS|...>
VIDEO_RTP_BEFORE_REPEAT=<true|false>
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

Also record localhost sink packet counts when available as corroborating transport evidence; they do not override native helper-lineage gates.

## 12. Positive proof

Use `PASS_REPEAT_EXTENDS_RTP` only if all of the following are proven in the one usable session:

```text
R27_REPEAT_EXECUTED=true
INITIAL_001A_SENT_COUNT=1
REPEAT_001A_SENT_COUNT=1
TOTAL_001A_SENT_COUNT=2
VIDEO_RTP_BEFORE_REPEAT=true
VIDEO_RTP_AFTER_REPEAT=true
VIDEO_RTP_PAST_40S=true
VIDEO_RTP_LAST_SECONDS_FROM_INITIAL_START>=40
ICE_NEGOTIATION_COUNT=1
PSEUDOTCP_OPEN_COUNT=1
CTPP_REGISTRATION_COUNT=1
RTPC_CLIENT_OPEN_COUNT=2
SELF_ACTIVATION_COUNT=1
HELPER_PROCESS_UNCHANGED=true
```

An ACK alone is not positive proof. The decisive evidence is RTP lifetime beyond 40 seconds in the unchanged session.

This proves only that one same-session repeat can extend the observed media lifetime under this environment. It does not establish a production cadence or authorize a periodic refresh loop.

## 13. Result classes

Use exactly one result class:

### `PASS_REPEAT_EXTENDS_RTP`

The acceptance gate passes, the repeat is sent exactly once, and video RTP continues beyond 40 seconds in the unchanged session.

### `FAIL_REPEAT_NO_EXTENSION`

The acceptance gate passes, repeat execution is proven exactly once, but video RTP does not continue beyond 40 seconds.

### `BLOCKED_REPEAT_NOT_EXECUTED`

The acceptance gate otherwise passes through a usable media path but the repeat is not emitted because an existing bounded fail-closed repeat precondition prevents it.

### `INCONCLUSIVE`

Use for any evidence-quality failure, helper-lineage failure, outer timeout, execution-path failure, teardown uncertainty, listener-restoration uncertainty, or other state that prevents a protocol conclusion.

No result class permits an automatic retry.

## 14. Mandatory restoration

After the sole live invocation, regardless of result, prove:

```text
CAMPAIGN_PROCESSES_REMAINING=NONE
CT120_RESEARCH_HELPER_STOPPED=true
CT120_RESEARCH_SESSION_CLOSED=true
R30H_D_SESSION_CLOSED=true
TEARDOWN_CONFIDENCE=CONFIRMED
LISTENER_RUNNING_AFTER=true
LISTENER_READY_AFTER=true
PRODUCTION_MEDIA_ACTIVE=false
DOOR_ACTIONS_SENT=0
GATE_ACTIONS_SENT=0
HA_RESTARTED=false
HA_RELOADED=false
HA_DEPLOYED=false
SECOND_MEDIA_SESSION=false
```

If listener restoration fails, do not restart or reload Home Assistant. Preserve evidence and report `INCONCLUSIVE` with the exact restoration blocker.

## 15. Repository write scope

The live child may write only the result document:

```text
safety-poc/research/media/v1/P116_R30H_D_REPEAT_001A_LIVE_PROOF_RESULT.md
```

Do not modify executable code in R30H-D.

The result document must separate:

- source/preflight identity;
- R30H-C execution-path gate;
- live helper/protocol identity;
- initial and repeat `0x001A` facts;
- repeat response classification;
- RTP timing/effect;
- teardown/listener restoration;
- forbidden-action evidence;
- what remains unproven;
- exact final result class.

Never commit tokens, credentials, raw SDP, raw packet bytes, raw RTP/H264/audio, private session secrets, or transient authentication material.

## 16. GitHub completion

After the run and restoration:

1. independently verify the result document against captured scalar output;
2. commit only the result document;
3. push using the project token/credential-store rules;
4. attempt PR creation;
5. if CT120 PAT lacks `createPullRequest`, return branch name and exact remote head SHA for ChatGPT to finish the PR.

## 17. Stop condition

After R30H-D result publication, STOP.

Do not implement periodic refresh or production behavior automatically, even after `PASS_REPEAT_EXTENDS_RTP`.

A production implementation is a new semantic child requiring a separate decision and authorization.
