# P116 / R65 — long media cutoff corrective result

TASK_ID=`COMELIT-P116-R65-LONG-MEDIA-CUTOFF-CORRECTIVE`
Status: **PASS_LONG_MEDIA_FIXED / production artifact not yet deployed**
Date: 2026-09-24

## 1. Scope and baseline

The task started from accepted public `main`:

```text
BASE_SHA=be3fb5265b19a1212054d81f030cb896d7952d54
BASE_RELEASE=1.5.11
BRANCH=research/p116-r65-long-media-cutoff-corrective
```

The observed production defect was that entrance on-demand video/RTP stopped after
approximately 30–35 seconds even though the Home Assistant media-session manager has
an absolute 600-second ceiling.

The live campaign was explicitly limited to self-activated entrance media. It required
no physical ring or intercom-button action and sent no Door/Gate action.

## 2. Result summary

The internal cause of the panel's historical ~35-second cutoff is **not proven**.
The working corrective mechanism is proven live:

```text
WORKING_MECHANISM=SAME_SESSION_PERIODIC_0x001A_REFRESH
WORKING_MECHANISM_LIVE_PROVEN=true
REFRESH_CADENCE_SECONDS=25
CADENCE_SOURCE=LOCAL_LIVE_EVIDENCE
CADENCE_SAFETY_MARGIN_SECONDS=11
```

A single same-session refresh was first proven to receive a structural ACK and extend
video beyond the historical cutoff. A subsequent bounded periodic-refresh run kept
video RTP progressing for 115 seconds in one unchanged upstream session.

This supports a request/grant-refresh model, but does not by itself prove the panel's
internal timer semantics. Therefore:

```text
ROOT_CAUSE=NOT_PROVEN
```

## 3. Historical blocker closed first

R30H-D had failed before sending its repeat request because the repeat buffer was
validated before it was populated.

R30H-E corrected that defect offline:

- build the repeat request from the runtime-generated initial `0x001A` body;
- change only CTP sequence wire byte 4 by +1 modulo 256;
- preserve independent ACK/state byte 5;
- preserve target, geometry and role/address semantics;
- validate with the existing P76 validator after construction;
- no frozen packet replay;
- no validator weakening;
- no retry;
- no new ICE/PseudoTCP/CTPP/RTPC/self-activation path.

The rollover case `0xff -> 0x00` with the ACK/state byte unchanged is covered by the
compiled behavioral harness.

## 4. Bounded live campaign

| Attempt | Repository point / purpose | Result | RTP evidence | Session / cleanup |
| --- | --- | --- | --- | --- |
| 1 | R30H-E corrected one-shot repeat; prove one same-session repeat | **PASS_REPEAT_ACCEPTED** | Repeat at ~20 s received `STRUCTURAL_ACK`; video progressed past 35 s and 40 s to 56 s. Evidence source was helper internal counters because the local UDP sink wiring was later found defective. | ICE=1, PseudoTCP=1, CTPP=1, RTPC opens=2, self-activation=1, second media session=false; teardown confirmed; listener restored. |
| 2 | Bounded periodic-refresh candidate; intended >75 s proof | **INCONCLUSIVE_INSTRUMENT_FAILURE** | Outer wrapper timed out; candidate output buffering and UDP-sink command-substitution wiring made the run unsuitable for a protocol verdict. | Teardown evidence uncertain during the run; listener subsequently recovered. Instrument defects were corrected before another protocol attempt. |
| 3 | Corrected instrumentation + periodic refresh | **PASS_LONG_MEDIA_ACCEPTANCE** | Independent UDP sink observed 5623 video and 5770 audio datagrams. `VIDEO_RTP_PAST_40S=true`, `VIDEO_RTP_PAST_75S=true`, last video RTP at 115 s, counter progressing. | One unchanged session for 115 s; teardown confirmed; no campaign process/UDP sink left; listener PID unchanged and reconnect count did not increase. |

Attempt 3 accepted scalars:

```text
LIVE_MEDIA_ATTEMPTS=3
MAX_AUTHORIZED_LIVE_MEDIA_ATTEMPTS=10

REFRESH_CADENCE_SECONDS=25
REFRESH_SENT_COUNT=4
REFRESH_RESPONSE_1=STRUCTURAL_ACK
REFRESH_RESPONSE_2=STRUCTURAL_ACK
REFRESH_RESPONSE_3=STRUCTURAL_ACK
REFRESH_RESPONSE_4=STRUCTURAL_ACK
REFRESH_OUTSTANDING=false
REFRESH_OVERLAP=false
REFRESH_RETRY=false
REFRESH_FAIL_CLOSED=false

INITIAL_001A_SENT_COUNT=1
TOTAL_001A_SENT_COUNT=5

VIDEO_RTP_PAST_40S=true
VIDEO_RTP_PAST_75S=true
VIDEO_RTP_LAST_SECONDS_FROM_INITIAL_START=115
MEDIA_ACTIVE_DURATION_SECONDS=115
MEDIA_ACTIVE_DURATION_WITHIN_CAP=true
VIDEO_PACKET_COUNTER_PROGRESSING=true

R27_VIDEO_SINK_DATAGRAMS=5623
R27_AUDIO_SINK_DATAGRAMS=5770
R27_CONTINUATION_EVIDENCE_SOURCE=INDEPENDENT_UDP_SINK

ICE_NEGOTIATION_COUNT=1
PSEUDOTCP_OPEN_COUNT=1
CTPP_REGISTRATION_COUNT=1
RTPC_CLIENT_OPEN_COUNT=2
SELF_ACTIVATION_COUNT=1
HELPER_PROCESS_UNCHANGED=true
SECOND_MEDIA_SESSION=false
MEDIA_SESSION_IDENTITY_UNCHANGED=true

MEDIA_TEARDOWN=CONFIRMED
TEARDOWN_CONFIDENCE=CONFIRMED
R27_SESSION_CLOSED=true
CAMPAIGN_PROCESSES_REMAINING=NONE
RTP_SINK_PORTS_REMAINING=0
LISTENER_READY_AFTER=true

DOOR_ACTIONS=0
GATE_ACTIONS=0
PHYSICAL_RING_ACTIONS=0
PHYSICAL_INTERCOM_BUTTON_PRESSES=0
```

The historical `VIDEO_RTP_AFTER_REPEAT` one-shot marker is not used as the periodic
acceptance signal because its old definition required exactly one repeat. The production
lineage generalizes that diagnostic to `VIDEO_RTP_AFTER_LAST_REFRESH`.

## 5. Production implementation

Commit `7ef1444f7b0754315ed78f125e5d9101ac648263` promoted the live-proven
same-session refresh logic into a production generator:

```text
safety-poc/research/media/v1/entrance_p116_r65_production_media_refresh_transform.py
```

Production properties:

- refresh cadence remains 25 seconds;
- exactly one refresh may be outstanding;
- no automatic retry after timeout/ambiguous response;
- refresh failure is fail-closed and begins graceful teardown;
- teardown cancels refresh scheduling;
- no new upstream session/bootstrap path;
- no Door/Gate reachability is added;
- the R27 115-second research self-timeout is removed;
- the research refresh-count cap 4 is raised to a defense-in-depth cap 32;
- the Home Assistant manager's 600-second absolute deadline remains the governing bound;
- a new viewer/snapshot/lease still cannot re-arm or extend that deadline;
- R64 persistent-listener/post-call observability lineage is not modified.

## 6. Reproducible production native build

Commit `0593a21e5481c7cb57e2bebbd0361c254f8bc43e` promoted the packaged
production helper after two independent CT120 offline builds.

```text
GENERATED_SOURCE_SHA256=4fc6188c6231b94682205973b6a6f628ca005e8b7c3a04efbd8056c5a608c58c
GENERATED_SOURCE_BYTES=247412

NATIVE_BINARY_SHA256=76218861c72e9a2b87283df6c5c7e0b03a4d7fb11bee4364f59be1513acd6129
NATIVE_BINARY_SIZE=295056
NATIVE_BINARY_MODE=755

BUILD_A_SHA256=76218861c72e9a2b87283df6c5c7e0b03a4d7fb11bee4364f59be1513acd6129
BUILD_B_SHA256=76218861c72e9a2b87283df6c5c7e0b03a4d7fb11bee4364f59be1513acd6129
REPRODUCIBLE_BINARY_CMP_GATE=PASS

MUSL_INTERPRETER_GATE=PASS
INTERPRETER=/lib/ld-musl-x86_64.so.1
NO_GLIBC_DEPENDENCY=PASS
NO_NEW_RUNTIME_DEPENDENCY=PASS
NEEDED=libc.musl-x86_64.so.1,libglib-2.0.so.0,libgobject-2.0.so.0,libnice.so.10

PRODUCTION_DEPLOY_PERFORMED=false
CANDIDATE_EXECUTED=false
```

The current production pin in `media_transport.py` and its provenance tests point to
the promoted R65 binary. The older R30E-era artifact remains historical provenance only.

## 7. Phase D requirement matrix — 13/13

The requirement matrix was audited against actual test names rather than keyword guesses.

| # | Requirement | Actual executable coverage | Gate |
| --- | --- | --- | --- |
| 1 | Refresh scheduling | `test_periodic_refresh_is_single_outstanding_and_ack_gated`; `test_cadence_and_safety_margin_unchanged_from_live_evidence` | PASS |
| 2 | No overlap | `test_periodic_refresh_is_single_outstanding_and_ack_gated`; production inheritance test `test_single_outstanding_no_retry_and_fail_closed_are_inherited_unchanged` | PASS |
| 3 | No retry | `test_ack_timeout_is_absent_fail_closed_and_no_retry`; `test_behavioural_harness_ack_timeout_absent_no_retry`; production inheritance test | PASS |
| 4 | Teardown cancels refresh | `test_stop_after_repeat_cancels_timers`; behavioral harness includes `test_teardown_cancels_pending_refresh` | PASS |
| 5 | Refresh/media failure cancels further refresh and fails closed | timeout/ambiguous paths are checked by `test_ack_timeout_is_absent_fail_closed_and_no_retry`, `test_rejected_state_removed_as_ambiguous`, and the production inheritance test; both paths enter graceful stop rather than schedule retry | PASS |
| 6 | 600 s deadline unchanged / not re-armed | `test_default_hard_limit_is_600_and_deadline_is_not_rearmed`; `test_new_lease_does_not_extend_absolute_deadline` | PASS |
| 7 | One upstream session invariant | `test_no_new_session_setup_paths_in_r27_segments`; `test_no_new_upstream_session_setup_path_added` | PASS |
| 8 | No Door/Gate reachability | `test_door_and_gate_action_paths_unreachable_from_r27_code`; `test_door_and_gate_action_paths_unreachable_from_r65_changes` | PASS |
| 9 | Sequence rollover | compiled harness includes `test_sequence_rollover_does_not_mutate_ack`: `0xff -> 0x00`, ACK byte unchanged | PASS |
| 10 | Malformed repeat fails closed | compiled harness includes `test_malformed_repeat_inputs_fail_closed`; source-level `test_malformed_or_ambiguous_state_does_not_send` | PASS |
| 11 | Unload cleanup | `test_unload_cancels_and_releases_active_lifecycle` | PASS |
| 12 | Existing 20 s recording regression | `test_snapshot_and_recording_use_one_session_and_safe_paths` asserts `RECORDING_TARGET_SECONDS=20` and one retained recording lifecycle | PASS |
| 13 | Existing snapshot/path regression | `test_snapshot_and_recording_use_one_session_and_safe_paths`; `test_safe_path_rejects_unsafe_event_id` | PASS |

Host-side gates recorded at production-helper promotion:

```text
FULL_UNIT_SUITE=PASS
FULL_UNIT_SUITE_TESTS=2206
FULL_UNIT_SUITE_SKIPPED=1
STATIC_SAFETY_CHECK=PASS
COMPILEALL=PASS
```

GitHub PR CI remains authoritative for the final branch state after this result document
and version metadata are added.

## 8. What is and is not proven

Proven:

- the historical ~35-second user-visible limitation can be eliminated by bounded
  same-session periodic `0x001A` refresh;
- four consecutive refreshes received structural ACKs;
- independent UDP evidence proves video/audio continued in the same session to 115 s;
- the production generator preserves the proven one-outstanding/no-retry/fail-closed
  safety properties;
- the production native helper is reproducibly built and pinned.

Not proven:

- the internal Comelit root cause or exact lease/timer implementation;
- a decoded JPEG specifically after 60 seconds in attempt 3;
- the newly packaged production artifact running inside HAOS.

The last point is deliberate: deployment is a separate HAOS/HACS step.

```text
PRODUCTION_FIX_IMPLEMENTED=true
PRODUCTION_ARTIFACT_LIVE_VALIDATED=false
PRODUCTION_HA_DEPLOY=false
HA_RESTART=false
HA_RELOAD=false
DECODED_FRAME_AFTER_60S=NOT_CHECKED
```

## 9. Final scalar block

```text
=== COMELIT LONG MEDIA CORRECTIVE ===
TASK_ID=COMELIT-P116-R65-LONG-MEDIA-CUTOFF-CORRECTIVE
BASE_SHA=be3fb5265b19a1212054d81f030cb896d7952d54
PRODUCTION_IMPLEMENTATION_HEAD=0593a21e5481c7cb57e2bebbd0361c254f8bc43e
LIVE_CAMERA_AUTHORIZED=true
LIVE_MEDIA_ATTEMPTS=3/10
PHYSICAL_RING_ACTIONS=0
PHYSICAL_INTERCOM_BUTTON_PRESSES=0
DOOR_ACTIONS=0
GATE_ACTIONS=0
ROOT_CAUSE=NOT_PROVEN
WORKING_MECHANISM=SAME_SESSION_PERIODIC_0x001A_REFRESH
WORKING_MECHANISM_LIVE_PROVEN=true
REPEAT_001A_PROVEN=true
REFRESH_CADENCE_SECONDS=25
REFRESH_SENT_COUNT=4
REFRESH_STRUCTURAL_ACK_COUNT=4
ICE_NEGOTIATION_COUNT=1
PSEUDOTCP_OPEN_COUNT=1
CTPP_REGISTRATION_COUNT=1
SELF_ACTIVATION_COUNT=1
SECOND_MEDIA_SESSION=false
VIDEO_RTP_PAST_40S=true
VIDEO_RTP_PAST_75S=true
MAX_PROVEN_MEDIA_SECONDS=115
R27_VIDEO_SINK_DATAGRAMS=5623
R27_AUDIO_SINK_DATAGRAMS=5770
DECODED_FRAME_AFTER_60S=NOT_CHECKED
MEDIA_TEARDOWN=PASS
LISTENER_READY_AFTER=true
AUTOMATIC_RETRY=false
PRODUCTION_FIX_IMPLEMENTED=true
PRODUCTION_ARTIFACT_LIVE_VALIDATED=false
FULL_REGRESSION=PASS
FULL_REGRESSION_TESTS=2206
OFFLINE_SAFETY=PASS
HACS_VALIDATION=PENDING_PR_CI
PRODUCTION_HA_DEPLOY=false
HA_RESTART=false
HA_RELOAD=false
RESULT=PASS_LONG_MEDIA_FIXED
=== END COMELIT LONG MEDIA CORRECTIVE ===
```
