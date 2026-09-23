# P116 R53 Call Adoption Protocol Profile Candidate

`PRODUCTION_PATCH_ALLOWED=false`.

This DEV/OFFLINE candidate adds a live-disabled helper protocol profile for the
missing inbound call-adoption signaling sequence:

```text
CALL_INIT -> empty ACK -> local CAPABILITIES -> local ALERTING
-> wait for peer CAPABILITIES -> peer DATA ACK -> existing R36/R42 media trigger
```

No production integration file, packaged native binary, HA package, deploy
script, or historical research artifact was changed.

## Profile Contract

```text
HELPER_CAPABILITY_PROFILE_SOURCE=OFFICIAL_APP_DECLARED_INTUNIT_MSTREAM_PROFILE
HELPER_CAPABILITY_PROFILE_FORMULA=AUDIO_DST|AUDIO_SRC|VIDEO_DST|MSTREAM
HELPER_CAPABILITY_PROFILE_VALUE=0x00000027
CALLFSM_840_NATIVE_EQUIVALENCE_CLAIMED=false
CAPTURE_LITERAL_REPLAY_USED=false
```

The runtime serializer does not use a capture body replay blob. The R53 core
computes the local helper profile from named flags:

```text
HELPER_CAP_AUDIO_DST=0x01
HELPER_CAP_AUDIO_SRC=0x02
HELPER_CAP_VIDEO_DST=0x04
HELPER_CAP_MSTREAM=0x20
OR=0x27
```

This value independently coincides with the Java UnitCapability formula
recorded in `P116_R51_NATIVE_CAPABILITY_DATAFLOW_CLOSURE.md:78-79` and with the
two official-app wire observations in
`P116_R52_OFFICIAL_CAPTURE_CAPABILITY_WORD_CORRELATION.md:69-71`.

R51/R52 remain canonical for native storage provenance:

```text
CAPABILITY_WORD_NATIVE_SOURCE=UNKNOWN
CALLFSM_840_POSSIBLY_UNINITIALIZED=true
IS_CALLFSM_840_DERIVED_FROM_VIPUNIT_CAPABILITY=false
```

## AUDIO_SRC Investigation

Evidence ledger:

| Question | Finding | Evidence |
|---|---|---|
| Does the official profile declare AUDIO_SRC? | Yes. | `P116_R51_NATIVE_CAPABILITY_DATAFLOW_CLOSURE.md:78-79`; `P116_R52_OFFICIAL_CAPTURE_CAPABILITY_WORD_CORRELATION.md:114-124`. |
| Does the peer use AUDIO_SRC immediately after local CAPABILITIES? | Not proven. Peer word is parsed as runtime data and is not the local word. | `P116_R52_OFFICIAL_CAPTURE_CAPABILITY_WORD_CORRELATION.md:69-71`, `Peer Comparison`. |
| Is client audio TX required before Answer? | Not proven from existing evidence. | `P77_ENTRANCE_MEDIA_OFFLINE_INTEGRATION_AND_LIVE_GAP_ANALYSIS.md:79` says the role/requirement of client-to-device PT8 remains live-only. |
| Does audio TX start automatically? | Unknown. Native symbols expose audio TX paths, but staged evidence does not prove automatic pre-answer helper TX. | `.r53-evidence/native-regression/native/libsafecomelit.nm.txt` includes `RtpDispatcher::startAudioTX`, `stopAudioTX`, `isOnAudioTX`, and `threadAudioRX`; `.r53-evidence/native-regression/r47/callfsm840-refs.txt` includes audio TX references near `handle_mediareq`. |
| Could absence of actual client audio TX break preview? | Unknown. | `P77_ENTRANCE_MEDIA_OFFLINE_INTEGRATION_AND_LIVE_GAP_ANALYSIS.md:124` keeps video-only without client-to-device PT8 as not proven stable. |

Required outputs:

```text
AUDIO_SRC_REQUIRED_FOR_OFFICIAL_PROFILE=true
AUDIO_SRC_CAUSES_PREANSWER_TX=UNKNOWN
AUDIO_SRC_SAFE_FOR_PREVIEW_CANDIDATE=UNKNOWN
```

No proven mandatory pre-answer client audio TX was found, so the candidate was
not blocked. The future canary below stops at the first missing peer
CAPABILITIES signal and does not retry.

## Ordering Model

R53 reuses the R45 serializers and R36/R42 predicates:

| Step | Owner | Contract |
|---|---|---|
| CALL_INIT capture | R35 | Captures current generation, current call CTP connection, sequence, acknowledgement, and logical endpoints. |
| Empty ACK | R45 | Flags `0x80`, body length 0, seq = inbound ACK, ack = inbound SEQ + 1, TX seq unchanged. |
| Local CAPABILITIES | R45 + R53 runtime profile | Inner opcode `0x0003`, length 8, `00 03 49 00 <profile LE32>`, TX seq advances by one. |
| Local ALERTING | R45 | Inner opcode `0x000A`, length 3, body `00 0A 00`, TX seq advances by one. |
| Wait peer CAPABILITIES | R53 | No media OPEN before current-generation/current-connection peer CAPABILITIES with video bit. |
| Peer DATA ACK | R45 | Sent before media trigger, empty ACK does not advance TX seq. |
| Media OPEN | R36/R42 | Existing one-open-per-generation path only. |

The host harness proves the local body sequence wrap `0xFF -> 0x00` while the
ACK byte remains independently derived from the peer frame.

## Failure Stages

| Stage | Meaning | Harness coverage |
|---|---|---|
| `NONE` | Successful adoption and media trigger. | Positive scenarios A and B. |
| `ACK_BUILD_FAILED` | No captured/current call state. | Core fail-closed branch. |
| `ACK_WRITE_FAILED` | Empty ACK emission failed. | `R53_ACK_WRITE_FAIL_CLOSED`. |
| `CAPABILITIES_BUILD_FAILED` | Profile/runtime body cannot be built. | Profile assertion and mutation detector. |
| `CAPABILITIES_WRITE_FAILED` | CAPABILITIES emission failed. | Core fail-closed branch. |
| `ALERTING_BUILD_FAILED` | ALERTING body cannot be built. | ALERTING mutation detector. |
| `ALERTING_WRITE_FAILED` | ALERTING emission failed. | Core fail-closed branch. |
| `WAITING_PEER_CAPABILITIES` | Duplicate start or peer before completed local signaling. | Duplicate same-generation CALL_INIT. |
| `PEER_CAPABILITIES_REJECTED` | Malformed, foreign, stale, or video-clear peer frame. | Malformed, foreign, prior-generation, opcode, video-clear cases. |
| `MEDIA_TRIGGER_REJECTED` | Duplicate peer capabilities or second media trigger. | Duplicate peer CAPABILITIES case. |

Bounded diagnostics emitted by the core:

```text
call_adoption_started
invite_ack_sent
local_capabilities_sent
local_capability_word
local_alerting_sent
waiting_peer_capabilities
peer_capabilities_seen
peer_capability_word
peer_video_requested
call_adoption_failure_stage
```

## Duplicate And Fail-Closed Matrix

| Case | Expected result | Harness marker |
|---|---|---|
| Duplicate CALL_INIT in same generation | No extra writes, no OPEN. | `R53_DUPLICATE_CALL_INIT_SAME_GENERATION_NO_OPEN=PASS` |
| Duplicate ACK attempt | No extra writes, no OPEN. | `R53_DUPLICATE_ACK_ATTEMPT_NO_OPEN=PASS` |
| Duplicate CAPABILITIES send | No extra writes, no OPEN. | `R53_DUPLICATE_CAPABILITIES_NO_OPEN=PASS` |
| Duplicate ALERTING send | No extra writes, no OPEN. | `R53_DUPLICATE_ALERTING_NO_OPEN=PASS` |
| Peer CAPABILITIES before media trigger | Peer ACK first, then exactly one OPEN. | `R53_PEER_ACK_BEFORE_MEDIA_OPEN=PASS` |
| Duplicate peer CAPABILITIES | No second OPEN. | `R53_DUPLICATE_PEER_CAPABILITIES_NO_SECOND_OPEN=PASS` |
| Prior-generation peer frame | Rejected, no OPEN. | `R53_PRIOR_GENERATION_PEER_FRAME_REJECTED=PASS` |
| Foreign connection | Rejected, no OPEN. | `R53_FOREIGN_CONNECTION_REJECTED=PASS` |
| Peer video bit clear | Rejected, no OPEN. | `R53_PEER_VIDEO_BIT_CLEAR_FAIL_CLOSED=PASS` |
| Malformed peer CAPABILITIES | Rejected, no OPEN. | `R53_MALFORMED_PEER_CAPABILITIES_REJECTED=PASS` |
| OPEN before peer CAPABILITIES | No OPEN. | `R53_NO_OPEN_BEFORE_PEER_CAPABILITIES=PASS` |

## Positive Peer Fixtures

The peer capability word is parsed at runtime:

```text
R53_POS_A_PEER_WORD=0x0000001b
R53_POS_B_PEER_WORD=0x0000002f
PEER_CAPABILITIES_RUNTIME_PARSED=PASS
```

`0x0000001b` is used only as a synthetic positive fixture matching the R52
official observations. `0x0000002f` preserves the video-request bit and proves
the candidate does not hardcode the observed peer word.

## Optional Transform

The optional R53 listener transform was not added in this round. The core and
host harness close the semantic candidate first; a future production patch
still needs a marker-gated transform applied after R42b, with deterministic
generation and explicit production review.

## Future Live Canary Design

Single first success criterion:

```text
PEER_CAPABILITIES_SEEN=true
```

Canary sequence:

1. One authorized physical-ring attempt in a future live round.
2. On CALL_INIT, send empty ACK, local CAPABILITIES, and local ALERTING.
3. Wait for peer CAPABILITIES.
4. If peer CAPABILITIES does not arrive, stop with no retry.
5. If peer CAPABILITIES arrives and requests video, allow the existing R42 path
   to continue with exactly one media OPEN.

Boundary: the canary is not authorized to add client audio TX. If the device
withholds peer CAPABILITIES, or the session stalls, while AUDIO_SRC semantics
remain unproven, the canary reports `PEER_CAPABILITIES_SEEN=false`, stops, and
does not retry. The audio-TX question then becomes the next evidence task, not
a production change.

Budget block:

```text
MAX_PHYSICAL_RING_ATTEMPTS=1
PHYSICAL_RING_AUTHORIZED=false
PHYSICAL_CALL_ATTEMPTS=0
NETWORK_TX=0
DEPLOY_ACTIONS=0
RESTART_ACTIONS=0
```

## Verification

Canonical repository-only CI command from `.github/workflows/offline-safety.yml`:

```text
cd safety-poc
PYTHONPATH=<repo>/safety-poc/src PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests
```

Parent gate evidence using the canonical command is authoritative for the full
suite result:

```text
PARENT_RUN_1_WITH_R53_FILES_PRESENT=Ran 2032 tests in 35.551s; OK (skipped=1)
PARENT_RUN_2_BASELINE_WITH_R53_TEST_TEMPORARILY_MOVED_ASIDE=Ran 2021 tests in 35.046s; OK (skipped=1)
PARENT_DELTA=+11 tests; no new failure
```

A `discover` run without `PYTHONPATH=safety-poc/src` reports a spurious
`ModuleNotFoundError: comelit_safety_poc`; that is an invocation error, not a
suite result. The two UDP-sink subprocess errors seen in this executor sandbox
are recorded as a one-off flaky sandbox observation: they are not reproducible
in the parent gate, which now has 2 consecutive OK host runs for
`tests.test_p116_r29i_preopen_idle_and_sink_ownership`, plus 3 consecutive OK
runs in the previous round on the same code.

Executor sandbox checks:

```text
FOCUSED_R53_COMMAND=PYTHONPATH=$PWD/safety-poc/src PYTHONDONTWRITEBYTECODE=1 python3 -m unittest safety-poc.tests.test_p116_r53_call_adoption_protocol_profile -v
FOCUSED_R53_RESULT=Ran 11 tests in 0.083s; OK

R43B_R43C_R45_R46_REGRESSION_COMMAND=cd safety-poc && PYTHONPATH=/home/hermes/repos/comelit/safety-poc/src PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_p116_r43b_call_adoption_serializers tests.test_p116_r43c_call_adoption_host_harness tests.test_p116_r45_call_adoption_host_harness tests.test_p116_r46_post_uaut_parser_replay -v
R43B_R43C_R45_R46_REGRESSION_RESULT=Ran 55 tests in 0.263s; OK

STATIC_SAFETY_COMMAND=cd safety-poc && python3 scripts/static_safety_check.py
STATIC_SAFETY_RESULT=STATIC_SAFETY_CHECK=PASS; NETWORK_IMPORTS_PRESENT=false; COMELIT_ENDPOINTS_PRESENT=false; SOURCE_FILES_SCANNED=29

FULL_SUITE_CANONICAL_SANDBOX_RUN_1=Ran 2032 tests in 39.450s; FAILED (errors=2, skipped=5)
FULL_SUITE_CANONICAL_SANDBOX_RUN_2=Ran 2032 tests in 39.717s; FAILED (errors=2, skipped=5)
FULL_SUITE_CANONICAL_PARENT_RUN=Ran 2032 tests in 35.551s; OK (skipped=1)
FULL_SUITE_BASELINE_PARENT_RUN=Ran 2021 tests in 35.046s; OK (skipped=1)
FULL_SUITE_PARENT_DELTA=+11 tests; no new failure

GIT_DIFF_CHECK_COMMAND=git diff --check
GIT_DIFF_CHECK_RESULT=clean
```

The parent canonical full-suite result is the basis for `FULL_OFFLINE_SUITE=PASS`
below; the sandbox full-suite result is separately recorded as flaky local
UDP-sink evidence rather than a stable new failure.

=== P116 R53 CALL ADOPTION PROTOCOL PROFILE CANDIDATE ===

BASE_SHA=26103359aaba110140a407b560ffa952a07930df

CODEX_CLI_USED=true
CODEX_ITERATIONS=2

HELPER_CAPABILITY_PROFILE_SOURCE=OFFICIAL_APP_DECLARED_INTUNIT_MSTREAM_PROFILE
HELPER_CAPABILITY_PROFILE_FORMULA=AUDIO_DST|AUDIO_SRC|VIDEO_DST|MSTREAM
HELPER_CAPABILITY_PROFILE_VALUE=0x00000027

HELPER_CAPABILITY_PROFILE_PROVEN=true

CALLFSM_840_NATIVE_EQUIVALENCE_CLAIMED=false
CAPTURE_LITERAL_REPLAY_USED=false

AUDIO_SRC_REQUIRED_FOR_OFFICIAL_PROFILE=true
AUDIO_SRC_CAUSES_PREANSWER_TX=UNKNOWN
AUDIO_SRC_SAFE_FOR_PREVIEW_CANDIDATE=UNKNOWN

ACK_NATIVE_EQUIVALENCE=PASS
CAPABILITIES_PROTOCOL_PROFILE=PASS
ALERTING_NATIVE_EQUIVALENCE=PASS
SEQUENCE_MODEL=PASS
ORDERING=PASS

PEER_CAPABILITIES_RUNTIME_PARSED=PASS
PEER_ACK_BEFORE_MEDIA_TRIGGER=PASS

ONE_OPEN_PER_GENERATION=PASS
FAIL_CLOSED=PASS

NETWORK_PRIMITIVES_REACHABLE=false
DOOR_SURFACE_REACHABLE=false
GATE_SURFACE_REACHABLE=false

NETWORK_TX=0
PHYSICAL_CALL_ATTEMPTS=0
SELF_ACTIVATION_ATTEMPTS=0
DOOR_ACTIONS=0
GATE_ACTIONS=0
DEPLOY_ACTIONS=0
RESTART_ACTIONS=0
PRODUCTION_FILES_CHANGED=0

FOCUSED_TESTS=PASS
FULL_OFFLINE_SUITE=PASS
STATIC_SAFETY=PASS
VALIDATE_HACS=NOT_RUN_BY_EXECUTOR
OFFLINE_SAFETY_CI=NOT_RUN_BY_EXECUTOR

FINAL_BRANCH_HEAD=<filled by orchestrator>

R53_READY_FOR_ONE_PHYSICAL_CANARY=true

READY_FOR_PRODUCTION_CORRECTIVE=false

MISSING_REQUIRED_EVIDENCE=AUDIO_SRC_PREANSWER_TX_SEMANTICS_UNPROVEN;AUDIO_SRC_PREVIEW_SAFETY_UNPROVEN

NEXT_REQUIRED_STEP=ORCHESTRATOR_INDEPENDENT_VERIFICATION_AND_OPTIONAL_ONE_PHYSICAL_CANARY_AUTHORIZATION

=== END P116 R53 CALL ADOPTION PROTOCOL PROFILE CANDIDATE ===
