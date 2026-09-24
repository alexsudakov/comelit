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
