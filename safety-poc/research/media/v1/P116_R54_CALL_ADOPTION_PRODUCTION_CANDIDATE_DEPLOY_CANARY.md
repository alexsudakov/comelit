# P116 R54 Call Adoption Production Candidate

## Scope

This round is the offline production-candidate preparation for the approved
one-ring canary. The executor does not deploy, restart Home Assistant, execute
the candidate against Comelit, send Door/Gate actions, self-activate, retry a
canary, try an alternate capability profile, or add audio TX.

Owner approval context:

```text
OWNER_APPROVAL_ID=P116_R54_BUILD_DEPLOY_ONE_RING_CANARY_V1
DEPLOY_AUTHORIZED=true
HA_RESTART_AUTHORIZED=true
PHYSICAL_RING_AUTHORIZED=true
PROTECTIVE_ROLLBACK_AUTHORIZED=true
```

Live fields remain the orchestrator's responsibility.

## Canonical Contract

The native storage claims remain unchanged:

```text
CALLFSM_840_NATIVE_EQUIVALENCE_CLAIMED=false
CAPABILITY_WORD_NATIVE_SOURCE=UNKNOWN
CALLFSM_840_POSSIBLY_UNINITIALIZED=true
```

The helper profile is a protocol profile, not a CallFsm+840 reconstruction and
not a capture literal:

```text
AUDIO_DST 0x01 | AUDIO_SRC 0x02 | VIDEO_DST 0x04 | MSTREAM 0x20 = 0x00000027
```

`AUDIO_SRC` is declaration-only. R54 adds no `startAudioTX`, no PT8 generator,
no microphone path, no answer-call path, and no audio workaround.

## Transform Chain

Input is the frozen listener:

```text
safety-poc/research/door/v1_5_7/comelit-v4-persistent-ctpp-door.c
sha256=5827d9fd043b85fc0c59a31661a1a125c6b239771e2a70c3e5afdd95f1a03c73
```

Generation chain:

```text
frozen v1.5.7 listener/Door
-> entrance_p116_r42b_listener_attached_media_transform.py
-> entrance_p116_r54_call_adoption_listener_transform.py
-> generated candidate source outside git
```

R54 is marker-gated and fail-closed. It refuses missing or duplicated anchors
and does not use heuristic insertion. It inserts the R45 serializer region and
the canonical R53 profile core, then adds a small listener bridge that:

1. starts R53 adoption after R35 captures CALL_INIT;
2. emits ACK, local CAPABILITIES, and local ALERTING through the existing R35
   writer hook using inert R54 queue kinds;
3. waits for a current-generation peer CAPABILITIES frame;
4. sends the R45 peer DATA ACK;
5. only then invokes the existing R42 runtime media trigger so the RTPC channel
   OPEN and MEDIAREQ26 OPEN remain R42-owned.

Corrective turn 3 keeps the canonical R53 core as the single peer-handling
owner. R53 exposes `r53_handle_peer_capabilities_with_trigger(...)` for the
listener bridge, while the existing `r53_handle_peer_capabilities(...)`
signature remains as a compatibility wrapper for R53 harness callers. The R54
listener no longer duplicates the peer validation or ACK chain; it provides
only the R42 media-trigger callback.

No generated proprietary-derived C source is committed.

## Offline Gates

Recorded deterministic source gates:

```text
FROZEN_BASE_SHA256_GATE=PASS
R42B_TRANSFORM_GATE=PASS
R54_TRANSFORM_GATE=PASS
GENERATED_SOURCE_DETERMINISTIC=true
GENERATED_SOURCE_SHA256=1370e6fda24ce2a7baa6d9a1e5d12b6ac1a3534872d370ef5157e9bb453878be
PEER_HANDLING_DEFINITION_COUNT=1
QUEUE_MEDIA_OPEN_CALL_SITE_COUNT=1
R54_ATTRIBUTABLE_WARNINGS_EXPECTED=0
PREEXISTING_WARNINGS_ATTRIBUTED=3
```

Focused host harness coverage compiles the generated R35/R36/R45/R53/R54
regions with a fake writer and asserts:

```text
CALL_INIT -> ACK -> CAP -> ALERTING -> peer CAP -> peer ACK -> one MEDIA_OPEN
ORDERING=PASS
PEER_ACK_BEFORE_MEDIA_TRIGGER=PASS
ONE_OPEN_PER_GENERATION=PASS
FAIL_CLOSED=PASS
```

Negative cases include duplicate peer CAPABILITIES, foreign connection, prior
generation through R35/R53, malformed peer CAPABILITIES, video bit clear,
missing writer, and media-open write failure. The peer capability word is
runtime-parsed and is not hardcoded to `0x1B`.

## Build And Promotion Contract

The parent-run builder is:

```text
safety-poc/research/media/v1/ct122_build_p116_r54_call_adoption_candidate.sh
```

It gates the frozen source, the R42-b transform, the R54 transform, and the R53
core hashes; generates source A/B and requires byte-identical source; compiles
binary A/B in Alpine/musl containers with `--network none`; requires identical
binary hashes; and checks:

```text
interpreter=/lib/ld-musl-x86_64.so.1
needed=libc.musl-x86_64.so.1,libglib-2.0.so.0,libgobject-2.0.so.0,libnice.so.10
MUSL_INTERPRETER_GATE=PASS
NO_GLIBC_DEPENDENCY=PASS
NO_NEW_RUNTIME_DEPENDENCY=PASS
candidate_executed=false
comelit_network_requests=0
```

If Docker or the apk closure is unavailable, the builder reports
`BUILD_RC=NOT_RUN_BY_EXECUTOR` and leaves binary promotion to the orchestrator.
The offline executor did not promote a binary in this phase; binary fields in
`P116_R54_BUILD_INFO.txt` are `PENDING_PARENT_BUILD`.

## Diagnostics Contract

R54 native markers are bounded scalar markers:

```text
R54_CALL_ADOPTION_STARTED=true|false
R54_INVITE_ACK_SENT=true|false
R54_LOCAL_CAPABILITIES_SENT=true|false
R54_LOCAL_CAPABILITY_WORD=<uint>
R54_LOCAL_ALERTING_SENT=true|false
R54_WAITING_PEER_CAPABILITIES=true|false
R54_PEER_CAPABILITIES_SEEN=true|false
R54_PEER_CAPABILITY_WORD=<uint>
R54_PEER_VIDEO_REQUESTED=true|false
R54_PEER_DATA_ACK_SENT=true|false
R54_CALL_ADOPTION_FAILURE_STAGE=<bounded enum>
```

`custom_components/comelit/media_diagnostics.py` parses only these whitelisted
keys under the `R54_` prefix. Boolean evidence is monotonic false-to-true.
Capability scalars are generation-scoped. `R42_CALL_GENERATION` resets the R54
call-adoption fields for the new generation without weakening the existing R42
diagnostics behavior. Failure stage accepts only the bounded enum from the R53
core and drops any unrecognized value.

Forbidden diagnostic content remains forbidden: raw payload, logical addresses,
CTP connection id, tokens, and auth material are not logged.

## Preservation Arguments

The listener remains the persistent listener process:

```text
RUN_DIR=/run/comelit-p2p
Door SIGUSR1 handler preserved
Door tick callback preserved
READY semantics preserved
R35/R36/R42 media path preserved
STOP/cleanup path preserved
AUTOMATIC_MEDIA_RETRY=false
ONE_MEDIA_OPEN_PER_GENERATION=true
DOOR_SEMANTICS_CHANGED=false
```

R54 does not call Door, Gate, self-activation, or network primitives. The only
new production Python change is diagnostics parsing for the new bounded R54
markers.

## Canary Design

Operational facts for the orchestrator:

```text
approved gateway commands: status | check | logs | logs-follow | deploy <sha> | rollback | restart USER_APPROVED
deploy <sha> writes only custom_components/comelit and self-reports HA_RESTARTED=NO
config-entry reload does not re-import changed custom-component Python
activation requires one full HA restart: restart USER_APPROVED
pre-deploy INTEGRATION_VERSION=1.5.8
pre-deploy DEPLOYED_SHA=643231f1ab789af8ea905953b9cf3cf335cd8f90
pre-deploy HA_CORE_CHECK=PASS
rollback native sha256=75c645b241677ccf411968c93aa13f8745c0ee772ae128728b5134fe9c943a54
rollback native size=235072
```

Canary budget:

```text
MAX_PHYSICAL_RING_ATTEMPTS=1
observation window up to 45 s after CALL_INIT
no retry
no alternate profile
no audio experiment
primary causal gate=PEER_CAPABILITIES_SEEN
```

## Read-only canary observability

The approved HA gateway exposes only these commands to the orchestrator:

```text
status
check
logs-follow
deploy <sha>
restart USER_APPROVED
rollback
```

Arbitrary shell is denied, and `status`/`check` do not expose
`runtime.status()["media_diagnostics"]`. Therefore the one-ring live phase is
observable read-only only through the integration log stream surfaced by
`logs-follow`. A criterion without an observable log line blocks the live phase
(STOP before deploy).

Each criterion below has exactly one bounded log substring. Values are emitted
only after the runtime marker key matches the safe marker regex and the value
passes the existing bounded scalar/diagnostic value gate; raw payload, logical
addresses, CTP connection id, tokens, and auth material are never published.
Generation-scoped criteria log at most once per call generation.

| Criterion | Native marker key | Exact log substring |
| --- | --- | --- |
| CALL_INIT_SEEN | `R42_CALL_GENERATION` | `Comelit canary evidence CALL_INIT_SEEN` |
| CALL_ADOPTION_STARTED | `R54_CALL_ADOPTION_STARTED` | `Comelit canary evidence CALL_ADOPTION_STARTED` |
| INVITE_ACK_SENT | `R54_INVITE_ACK_SENT` | `Comelit canary evidence INVITE_ACK_SENT` |
| LOCAL_CAPABILITIES_SENT | `R54_LOCAL_CAPABILITIES_SENT` | `Comelit canary evidence LOCAL_CAPABILITIES_SENT` |
| LOCAL_CAPABILITY_WORD | `R54_LOCAL_CAPABILITY_WORD` | `Comelit canary evidence LOCAL_CAPABILITY_WORD` |
| LOCAL_ALERTING_SENT | `R54_LOCAL_ALERTING_SENT` | `Comelit canary evidence LOCAL_ALERTING_SENT` |
| WAITING_PEER_CAPABILITIES | `R54_WAITING_PEER_CAPABILITIES` | `Comelit canary evidence WAITING_PEER_CAPABILITIES` |
| PEER_CAPABILITIES_SEEN | `R54_PEER_CAPABILITIES_SEEN` | `Comelit canary evidence PEER_CAPABILITIES_SEEN` |
| PEER_CAPABILITY_WORD | `R54_PEER_CAPABILITY_WORD` | `Comelit canary evidence PEER_CAPABILITY_WORD` |
| PEER_VIDEO_REQUESTED | `R54_PEER_VIDEO_REQUESTED` | `Comelit canary evidence PEER_VIDEO_REQUESTED` |
| PEER_DATA_ACK_SENT | `R54_PEER_DATA_ACK_SENT` | `Comelit canary evidence PEER_DATA_ACK_SENT` |
| CALL_ADOPTION_FAILURE_STAGE | `R54_CALL_ADOPTION_FAILURE_STAGE` | `Comelit canary evidence CALL_ADOPTION_FAILURE_STAGE` |
| MEDIAREQ26_OPEN_SENT | `R42_MEDIAREQ26_OPEN_CHANNEL` | `Comelit canary evidence MEDIAREQ26_OPEN_SENT` |
| RTP_RECEIVED | `P80_VIDEO_RTP_FORWARDING` | `Comelit canary evidence RTP_RECEIVED` |
| H264_DETECTED | `P116_VIDEO_SPS_COUNT` | `Comelit canary evidence H264_DETECTED` |
| STOP_SENT | `R42_ATTACHED_MEDIA_STOP_SENT` | `Comelit canary evidence STOP_SENT` |
| CHANNEL_CLOSED | `R42_MEDIA_CHANNEL_CLOSED` | `Comelit attached inbound media CLOSED` |
| CLEANUP_COMPLETE | `R42_LISTENER_RTP_FORWARDING_ARMED` | `Comelit canary evidence CLEANUP_COMPLETE` |
| LISTENER_READY_AFTER | `V4_RING_LISTENER_READY` | `Comelit ring listener READY` |

`H264_DETECTED` is logged from the first positive H.264 evidence counter; the
table records `P116_VIDEO_SPS_COUNT` as the canonical table key, while the
runtime accepts the same bounded positive-count shape for the existing
`P116_VIDEO_PPS_COUNT`, `P116_VIDEO_SINGLE_NAL_COUNT`, and
`P116_VIDEO_FUA_COUNT` evidence markers. No required criterion lacks a native
marker after this corrective.

Rollback triggers:

```text
deploy hash mismatch
listener not READY
native crash or crash-loop
malformed diagnostics contract
call-adoption FAIL
media end-to-end FAIL after adoption PASS
cleanup uncertainty
```

Protective rollback uses the approved gateway rollback plus at most the
authorized rollback HA restart. Door and Gate actions remain forbidden.

## Verification Record

Parent canonical verification for this corrective is authoritative:

```text
PARENT_FOCUSED_R54=Ran 11 tests; OK
PARENT_REGRESSIONS=Ran 161 tests; OK
PARENT_CANONICAL_CI_COMMAND=Ran 2043 tests in 35.563s; OK (skipped=1); errors=0
PARENT_BASELINE_WITH_R54_TEST_FILE_MOVED_ASIDE=2032
PARENT_DELTA=+11, no new failure
PARENT_STATIC_SAFETY=STATIC_SAFETY_CHECK=PASS
CANONICAL_CI_REQUIRES=PYTHONPATH=safety-poc/src
```

Executor-local verification is recorded separately from the parent canonical
basis. Where this sandbox differs because of UDP-sink timing/flakiness, that is
local-only and does not replace the parent canonical result.

```text
EXECUTOR_FOCUSED_R54=Ran 17 tests; OK
EXECUTOR_REGRESSIONS=Ran 179 tests; OK
EXECUTOR_FULL_DISCOVERY=Ran 2049 tests in 39.321s; FAILED errors=2 skipped=5
EXECUTOR_FULL_DISCOVERY_LOCAL_DIFFERENCE=UDP sink final counter materialization errors in test_p116_r29i_preopen_idle_and_sink_ownership
EXECUTOR_STATIC_SAFETY=STATIC_SAFETY_CHECK=PASS; NETWORK_IMPORTS_PRESENT=false; COMELIT_ENDPOINTS_PRESENT=false; SOURCE_FILES_SCANNED=29
EXECUTOR_GENERATED_SOURCE_SHA256=1370e6fda24ce2a7baa6d9a1e5d12b6ac1a3534872d370ef5157e9bb453878be
EXECUTOR_SINGLE_PEER_HANDLING_OWNER=true
EXECUTOR_DUPLICATE_PEER_CHAIN_REMOVED=true
```

The additive R42-b test updates only extend the frozen schema field-count
assertions from 23 to 34 because R54 adds 11 additive call-adoption fields. The
original 23 field names are still asserted as subsets and no assertion was
weakened.

Closing corrective record:

```text
CODEX_ITERATIONS=3
FULL_OFFLINE_SUITE=PASS
FULL_OFFLINE_SUITE_BASIS=parent canonical
MISSING_REQUIRED_EVIDENCE=PARENT_MUSL_BUILD,PROMOTED_BINARY
```

## Corrective Rule

A production-code correction after a failed canary requires a new offline gate
and a new owner approval for a second physical canary. A later follow-up commit
may add sanitized live results to this document, but must not change production
code unless a new approved offline round is opened.
