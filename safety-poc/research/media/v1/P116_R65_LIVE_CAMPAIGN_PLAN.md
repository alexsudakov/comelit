# P116 R65 live campaign plan

Mode: bounded live proposal only. Do not run from this offline child.

Hypothesis: after the R30H-E offline corrective, same-session repeat client `0x001A` refreshes can be emitted without opening a second ICE/PseudoTCP/CTPP/RTPC session and can be classified from scalar markers alone.

Authorized bounded run shape, if separately approved:

- Use the existing R27 live runner path; do not author a broader runner for this phase.
- One media session, one initial `0x001A`, bounded same-session refresh `0x001A` sends only.
- No Door/Gate action, no production helper replacement, no raw capture, no candidate `main()` outside the wrapper path.

Required scalar markers:

- Sent counts: `INITIAL_001A_SENT_COUNT`, `REPEAT_001A_SENT_COUNT`, `TOTAL_001A_SENT_COUNT`, `R27_THIRD_001A_BLOCKED`.
- Repeat body/gate: `R27_REPEAT_001A_BUILD`, `R27_REPEAT_001A_VALIDATION`, `R27_REPEAT_BODY_DIFF_GATE`, `R27_REPEAT_BODY_CHANGED_OFFSETS`, `R27_REPEAT_CTP_ACK_BYTE_UNCHANGED`, `R27_REPEAT_SEQUENCE_MODEL`, `R27_REPEAT_SEQUENCE_SOURCE`.
- Response classification: exactly one of `SECOND_001A_RESPONSE=STRUCTURAL_ACK|AMBIGUOUS|ABSENT`, plus `R27_REPEAT_ACK_BINDING` when structural.
- Same-session observations: `HELPER_PROCESS_UNCHANGED`, `ICE_NEGOTIATION_COUNT`, `PSEUDOTCP_OPEN_COUNT`, `CTPP_REGISTRATION_COUNT`, `RTPC_CLIENT_OPEN_COUNT`, `SELF_ACTIVATION_COUNT`, plus existing helper evidence gate markers proving same helper, same ICE, same PseudoTCP, same CTPP, and same RTPC allocations.
- RTP progress: `P80_VIDEO_RTP_PACKETS` before repeat, `VIDEO_PACKET_COUNT_AT_REPEAT`, `VIDEO_RTP_AFTER_REPEAT`, `VIDEO_RTP_PAST_35S`, `VIDEO_RTP_PAST_40S`, `VIDEO_RTP_LAST_SECONDS_FROM_INITIAL_START`.
- Safety closure: `R27_USABLE_EVIDENCE`, `R27_RUN_CLASSIFICATION`, teardown/session-closed markers, and no live scalar suppression for usable evidence.

Classification:

- `REPEAT_ACCEPTED`: repeat sent once, body gates pass, same-session markers pass, response is structural ACK, and RTP progresses after repeat.
- `REPEAT_AMBIGUOUS`: repeat sent once and body gates pass, but response is ambiguous or absent while same-session markers remain pass.
- `REPEAT_NOT_SENT`: repeat count remains zero; classify by the first failing precondition/build/validation marker.
- `RUN_NOT_USABLE`: helper evidence, teardown, or scalar-suppression gates fail.

## Attempt 1 live evidence

CT120 attempt 1 ran at repo HEAD `cb449d07790071ebca4f804ac576dea42433c2de` with runner `RC=0`. Preconditions were clean: listener active PID `19978`, credential TTL `604751`, ports `17899/17808` free, no established UDP, no campaign processes.

Raw final scalars:

- `LIVE_INVOCATIONS=1`, `WRAPPER_RC=0`, `R27_RUN_CLASSIFICATION=OBSERVATION_USABLE`, `R27_USABLE_EVIDENCE=true`.
- Credential gate: `CREDENTIAL_STATUS_PRESENT=true`, `CREDENTIAL_TTL_SECONDS=604749`, `CREDENTIAL_TTL_GATE=PASS`, `CREDENTIAL_REFRESH_REQUIRED=false`.
- Repeat: `INITIAL_001A_SENT_COUNT=1`, `REPEAT_001A_SENT_COUNT=1`, `TOTAL_001A_SENT_COUNT=2`, `R27_REPEAT_EXECUTED=true`.
- Response: `SECOND_001A_RESPONSE=STRUCTURAL_ACK`, `SECOND_001A_ACK_CLASSIFICATION=STATE_SCOPED_STRUCTURAL`.
- RTP: `VIDEO_RTP_BEFORE_REPEAT=true`, `VIDEO_PACKET_COUNT_AT_REPEAT=995`, `VIDEO_RTP_AFTER_REPEAT=true`, `VIDEO_RTP_PAST_35S=true`, `VIDEO_RTP_PAST_40S=true`, `VIDEO_RTP_PAST_75S=false`, `VIDEO_RTP_LAST_SECONDS_FROM_INITIAL_START=56`, `MEDIA_ACTIVE_DURATION_SECONDS=100`, `VIDEO_PACKET_COUNTER_PROGRESSING=true`.
- Identity: `ICE_NEGOTIATION_COUNT=1`, `PSEUDOTCP_OPEN_COUNT=1`, `CTPP_REGISTRATION_COUNT=1`, `RTPC_CLIENT_OPEN_COUNT=2`, `SELF_ACTIVATION_COUNT=1`, `HELPER_PROCESS_UNCHANGED=true`, `SECOND_MEDIA_SESSION=false`, `MEDIA_SESSION_IDENTITY_UNCHANGED=true`, `NEW_RTPC_OPEN=false`, `NEW_SELF_ACTIVATION=false`.
- Safety closure: `MEDIA_TEARDOWN=CONFIRMED`, `LISTENER_RESTORED=true`, `LISTENER_READY_AFTER=true`, `CAMPAIGN_PROCESSES_REMAINING=NONE`, `RTP_SINK_PORTS_REMAINING=0`, `DOOR_ACTIONS_SENT=0`, `GATE_ACTIONS_SENT=0`, `OFFICIAL_APP_CAPTURE=false`, `RAW_PCAP_CAPTURE=false`.

Attempt 1 classification: `REPEAT_ACCEPTED_SAME_SESSION_RTP_EXTENDED_TO_56S`. Proven: one repeat was sent, the panel returned a same-session structural ACK, video RTP progressed after the repeat and past 40 seconds, session identity was unchanged, and teardown/listener restoration were confirmed. Not proven: the cutoff root cause, whether the 56 second video stop is grant expiry, and whether the structural ACK causally refreshed the grant.

Grant model for attempt 2: local evidence shows a repeat at 20 seconds and last video RTP at 56 seconds, leaving an observed post-request interval of about 36 seconds. A bounded periodic cadence of `25` seconds uses `CADENCE_SOURCE=LOCAL_LIVE_EVIDENCE` and an `11` second safety margin before that observed interval. This is a hypothesis, not a proof. It is falsified if bounded periodic refreshes still fail to keep RTP flowing past 75 seconds in one unchanged session.

Attempt 2 acceptance set:

- `REFRESH_CADENCE_SECONDS=25`, `CADENCE_SOURCE=LOCAL_LIVE_EVIDENCE`, `CADENCE_SAFETY_MARGIN_SECONDS=11`, `REFRESH_OVERLAP=false`, `REFRESH_RETRY=false`.
- `REFRESH_SENT_COUNT>=2`, with per-refresh `REFRESH_RESPONSE_<i>=STRUCTURAL_ACK` or otherwise fail-closed.
- `VIDEO_RTP_PAST_75S=true`, `MEDIA_ACTIVE_DURATION_SECONDS>=90`, `VIDEO_PACKET_COUNTER_PROGRESSING=true`.
- Same session unchanged: `MEDIA_SESSION_IDENTITY_UNCHANGED=true`, `SECOND_MEDIA_SESSION=false`, `ICE_NEGOTIATION_COUNT=1`, `PSEUDOTCP_OPEN_COUNT=1`, `CTPP_REGISTRATION_COUNT=1`, `RTPC_CLIENT_OPEN_COUNT=2`, `SELF_ACTIVATION_COUNT=1`.
- Safety closure: `MEDIA_TEARDOWN=CONFIRMED`, `LISTENER_RESTORED=true`, `LISTENER_READY_AFTER=true`, `CAMPAIGN_PROCESSES_REMAINING=NONE`, `RTP_SINK_PORTS_REMAINING=0`, `DOOR_ACTIONS_SENT=0`, `GATE_ACTIONS_SENT=0`.

## Attempt 2 live evidence (instrument failure, not a protocol verdict)

CT120 attempt 2 ran with the bounded periodic refresh candidate and returned `WRAPPER_RC=124`. Raw scalars: `R27_RUN_CLASSIFICATION=INCONCLUSIVE_OUTER_TIMEOUT`, `MEDIA_TEARDOWN=UNCERTAIN`, `R27_SESSION_CLOSED=false`, and zero candidate markers present in the captured session log even though the candidate process was launched and (per the listener side effects) reached `MEDIA_ACTIVE`. In both attempt 1 and attempt 2 the runner's local UDP sinks recorded `video.count=0` / `audio.count=0` while the helper's own internal counters printed `P80_VIDEO_RTP_FORWARDING=PASS` and a progressing `P80_VIDEO_RTP_PACKETS` value — the sink was never an independent witness in either attempt, so attempt 1's "RTP continued after repeat" claim rests on `HELPER_INTERNAL_COUNTER_EVIDENCE` only (the candidate's self-reported counters), not on packets independently observed leaving the panel.

`R27_RUN_CLASSIFICATION=INCONCLUSIVE_OUTER_TIMEOUT` is classified here as an **instrument defect**, not a protocol verdict: nothing about attempt 2's `WRAPPER_RC=124` demonstrates that bounded periodic refresh fails to hold RTP open past 75s. It demonstrates that the wrapper's outer bound and the candidate's I/O/signal handling were not designed to coexist with a hard `timeout` kill, and that the sink was not wired to independently witness anything. All three are fixed offline in this corrective; none of them touch the R27 protocol logic under test.

Defects found and fixed:

1. **Tautological/too-tight outer bound.** `OUTER_TIMEOUT_SECONDS` was a bare literal `120` alongside `MAX_LIVE_OBSERVATION_SECONDS=115`, leaving only 5 seconds of margin for build, listener-stop, and candidate-launch steps before the helper's own 115s observation window could complete — not enough headroom, so the outer `timeout` fired while the candidate was still mid-session. Fix: `SETUP_MARGIN_SECONDS=60` and `MEDIA_OBSERVATION_SECONDS=115` are now independent named constants, `OUTER_TIMEOUT_SECONDS=$((SETUP_MARGIN_SECONDS + MEDIA_OBSERVATION_SECONDS))=175`, and a new `MIN_SETUP_MARGIN_SECONDS=45` floor makes `R27_BOUND_INVARIANT` a real, falsifiable check (`REQUIRED_MIN_WRAPPER_BOUND_SECONDS = MEDIA_OBSERVATION_SECONDS + MIN_SETUP_MARGIN_SECONDS`, compared against the actual `OUTER_TIMEOUT_SECONDS`) instead of comparing a sum against itself. Test: `test_runner_bound_invariant_is_falsifiable` extracts the shipped invariant block and proves it both PASSes with the real constants and FAILs when `SETUP_MARGIN_SECONDS` is shrunk below `MIN_SETUP_MARGIN_SECONDS`.
2. **No line buffering and no bound-signal handling in the candidate.** The candidate wrote fully-buffered stdout and had no `SIGTERM`/`SIGINT` handler, so when the outer `timeout` sent its bound signal, any unflushed marker output was lost — explaining the zero candidate markers in attempt 2 despite the candidate having run. Fix: `setvbuf(stdout, NULL, _IOLBF, 0)` / unbuffered stderr at `main()` entry, plus `r27_bound_signal_handler()` installed for `SIGTERM`/`SIGINT` that prints `R27_WRAPPER_BOUND_HIT=true`, `R27_HELPER_SUMMARY_PRINTED=true`, `R27_PARTIAL_MARKERS_PRESENT=true`, `R27_LAST_STAGE=BOUND_SIGNAL`, cancels pending refresh timers, prints the partial final summary, begins a graceful stop, flushes, and quits the main loop. Test: `test_bound_signal_prints_partial_summary_and_graceful_stop` (compiled behavioural harness) plus `test_bound_signal_flushes_partial_summary_and_graceful_stop` (source-presence contract test).
3. **UDP sink was not an independent witness.** `start_udp_sink`'s Python child inherited the runner's stdout/stderr, so `VIDEO_SINK_PID="$(start_udp_sink ...)"` blocked on the command substitution's pipe until the background child's write end closed, instead of returning the PID immediately; combined with the sink's fixed observation window, this meant the sink was effectively never listening during the media session's real RTP flow in either attempt, so it always read back 0. Fix: the child's stdout/stderr are now redirected to `"${count_file}.log"` so command substitution returns immediately, and the final block reports `R27_VIDEO_SINK_DATAGRAMS` / `R27_AUDIO_SINK_DATAGRAMS` (0 is reported explicitly, never omitted) plus a derived `R27_CONTINUATION_EVIDENCE_SOURCE` marker: `INDEPENDENT_UDP_SINK` only when the sink counted a nonzero value, `HELPER_INTERNAL_COUNTER_ONLY_SINK_ZERO` when the sink ran but counted zero, and `HELPER_INTERNAL_COUNTER_ONLY` when the sink value is missing/non-numeric. Attempt 1's existing `HELPER_INTERNAL_COUNTER_EVIDENCE` label (in this document, above) is left as-is and now has a live-runner counterpart it can be checked against. Test: `test_runner_udp_sink_is_an_independent_witness` extracts the shipped `start_udp_sink`/`stop_pid`/`sink_datagram_count` functions, runs them against a real ephemeral UDP port, sends 3 datagrams, and asserts the sink reports `3`.

Listener-side observation: HA's listener `reconnect_count` moved `26 -> 27` across attempt 1 to attempt 2. This is consistent with defect 2 — without a graceful-stop path, the outer `timeout --kill-after=5s` had to fall through to `SIGKILL` on the candidate, an ungraceful process death that the listener detected as a dropped connection and reconnected from. With the bound-signal handler now performing `pseudotcp_begin_graceful_stop("r27-bound-signal")` before the `kill-after` grace period elapses, a future bound hit should let the candidate release its own resources instead of being killed out from under the listener, and this reconnect should not recur; this is a hypothesis to be confirmed by attempt 3, not yet proven.

Attempt 3 acceptance set (supersedes attempt 2; instrument-focused additions in italics):

- `REFRESH_CADENCE_SECONDS=25`, `CADENCE_SOURCE=LOCAL_LIVE_EVIDENCE`, `CADENCE_SAFETY_MARGIN_SECONDS=11`, `REFRESH_OVERLAP=false`, `REFRESH_RETRY=false`, `REFRESH_SENT_COUNT>=2`.
- `VIDEO_RTP_PAST_75S=true` in one unchanged session, `MEDIA_ACTIVE_DURATION_SECONDS` in `[90, 120]`, *`MEDIA_ACTIVE_DURATION_WITHIN_CAP=true`*, `VIDEO_PACKET_COUNTER_PROGRESSING=true`.
- Same session unchanged: `MEDIA_SESSION_IDENTITY_UNCHANGED=true`, `SECOND_MEDIA_SESSION=false`.
- *`R27_BOUND_INVARIANT=PASS`, `R27_WRAPPER_BOUND_HIT` consistent with `WRAPPER_RC` (only `true` if `WRAPPER_RC` is `124`/`137` or the candidate's own bound-signal marker fired), `R27_RUN_CLASSIFICATION=OBSERVATION_USABLE` (not `INCONCLUSIVE_OUTER_TIMEOUT`).*
- *`R27_VIDEO_SINK_DATAGRAMS` and `R27_AUDIO_SINK_DATAGRAMS` present as explicit values (including `0`), with `R27_CONTINUATION_EVIDENCE_SOURCE` recorded so the evidence basis for RTP continuation is stated rather than assumed.*
- Safety closure: `MEDIA_TEARDOWN=CONFIRMED`, `LISTENER_RESTORED=true`, `LISTENER_READY_AFTER=true`, `CAMPAIGN_PROCESSES_REMAINING=NONE`, `RTP_SINK_PORTS_REMAINING=0`, `DOOR_ACTIONS_SENT=0`, `GATE_ACTIONS_SENT=0`.
