# P116 R65 live campaign plan

Mode: bounded live proposal only. Do not run from this offline child.

Hypothesis: after the R30H-E offline corrective, one same-session repeat client `0x001A` can be emitted without opening a second ICE/PseudoTCP/CTPP/RTPC session and can be classified from scalar markers alone.

Authorized bounded run shape, if separately approved:

- Use the existing R27 live runner path; do not author a broader runner for this phase.
- One media session, one initial `0x001A`, at most one repeat `0x001A`.
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
