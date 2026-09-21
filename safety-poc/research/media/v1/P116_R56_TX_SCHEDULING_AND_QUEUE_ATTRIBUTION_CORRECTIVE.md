# P116 R56 TX Scheduling and Queue Attribution Corrective

## Scope

Offline-only corrective. No deploy, HA restart, reload, physical ring, self-activation, Door/Gate action, Comelit live network TX, ADB, ptrace/watchpoint, proprietary-binary execution against Comelit, production promotion, production file change, commit, or push was performed.

Base: `9f1e90165e4281a5ecfa259366a3171fd0e301f1`.

## P12 Lifecycle

Evidence source: `.r56-evidence/generated/corrected-7c937a9e.c`, `.r56-evidence/live/tx-queue-inventory.txt`, `.r56-evidence/live/R55_FORENSIC.md`.

The P12 TX owner is a single pending buffer:

- `p12_queue_bytes` rejects if `p12_tx_pending` is true, length is zero, or length exceeds `P12_TX_MAX`; on success it copies bytes, sets offset zero, stores `P12TxKind`, and sets `p12_tx_pending = TRUE` (`corrected-7c937a9e.c:1330-1349`).
- `p12_flush_tx` is the clear path. It sends from `p12_tx + p12_tx_offset`, advances offset after positive writes, returns success without clearing on `EWOULDBLOCK`, returns failure on other PseudoTCP send errors, and only when offset reaches length clears `p12_tx_pending = FALSE` before calling `p12_tx_completed(completed)` (`corrected-7c937a9e.c:4270-4316`).
- `p12_tx_pending != FALSE` means the single P12 slot is still owned by a pending frame. It can be fully unsent, partially written, or awaiting a later writable callback.
- Release and write completion are the same proven event: `p12_tx_completed(kind)` after `p12_flush_tx` clears the slot.
- `PseudoTcpWritable` calls `pseudotcp_writable_cb`, which sets `failed = TRUE` only if `try_send_echo_ack()`, `try_send_uaut_open()`, or `p12_flush_tx()` returns false (`corrected-7c937a9e.c:7755-7770`). That is not a P12 busy-slot path: echo ACK and UAUT OPEN send from their own buffers with `pseudo_tcp_socket_send()` (`corrected-7c937a9e.c:7190-7199`, `corrected-7c937a9e.c:7096-7105`), while `p12_flush_tx()` returns true for an empty queue or `EWOULDBLOCK` backpressure (`corrected-7c937a9e.c:4272-4273`, `corrected-7c937a9e.c:4288-4294`).
- `EWOULDBLOCK` is transient send backpressure and leaves `p12_tx_pending` set (`corrected-7c937a9e.c:4288-4294`).
- Partial writes are supported because positive `n` advances `p12_tx_offset` and the loop continues until complete or blocked (`corrected-7c937a9e.c:4275-4285`).
- Synchronous completion exists: a `p12_flush_tx` call can clear the buffer and invoke `p12_tx_completed` before returning (`corrected-7c937a9e.c:4307-4316`).
- Writable callbacks may fire with an empty queue because `p12_flush_tx` returns true immediately if `!p12_tx_pending` (`corrected-7c937a9e.c:4272-4273`).
- RTPC/MEDIA OPEN uses the same queue: `r42_queue_media_channel_open` calls `p12_queue_vip_frame(... P12_TX_R42_MEDIA_CHANNEL_OPEN)` and then `p12_flush_tx` (`corrected-7c937a9e.c:2892-2906`); MEDIAREQ26 OPEN uses the R35 writer and expects `P12_TX_R35_MEDIA_OPEN` (`corrected-7c937a9e.c:2932-2948`).

Result scalars:

```
P12_SINGLE_SLOT_CONFIRMED=true
P12_SLOT_BUSY_IS_TRANSIENT=true
P12_SLOT_RELEASE_EVENT=p12_tx_completed(kind)
P12_WRITE_COMPLETION_EVENT=SAME_AS_RELEASE
P12_PARTIAL_WRITE_SUPPORTED=true
P12_WRITABLE_CALLBACK_REENTRANT_SAFE=true
MEDIA_OPEN_SHARES_P12_TX_QUEUE=true
```

## Before/After State Machine

Before R56, `r53_start_after_call_capture` synchronously emitted invite ACK, local CAPABILITIES, and local ALERTING, while `r45_emit` only knew that the writer was called. `p12_queue_bytes` success did not mean the frame had flushed. Peer CAPABILITIES then emitted peer DATA ACK and immediately called the R42 media trigger.

R56 keeps R45 as serializer owner and R53 as profile/failure enum owner, but moves production TX ordering into the R54 listener transform:

`IDLE -> NEED_INVITE_ACK -> WAIT_INVITE_ACK_FLUSH -> NEED_LOCAL_CAPABILITIES -> WAIT_LOCAL_CAPABILITIES_FLUSH -> NEED_LOCAL_ALERTING -> WAIT_LOCAL_ALERTING_FLUSH -> WAIT_PEER_CAPABILITIES -> NEED_PEER_DATA_ACK -> WAIT_PEER_DATA_ACK_FLUSH -> MEDIA_TRIGGER_READY`.

`p12_tx_completed(kind)` is the progression hook for each R54 frame. The next frame is attempted only after the previous R54 `P12TxKind` completion. Synchronous flush completion is accepted because it is still proven by `p12_tx_completed`.

Completion wiring contract:

- The P12 kind enum includes `P12_TX_R54_INVITE_ACK`, `P12_TX_R54_LOCAL_CAPABILITIES`, `P12_TX_R54_LOCAL_ALERTING`, and `P12_TX_R54_PEER_DATA_ACK` (`corrected-7c937a9e.c:667-670`; R56 generator insertion source `entrance_p116_r54_call_adoption_listener_transform.py:35-45`).
- `p12_flush_tx()` clears `p12_tx_pending = FALSE` only after the full buffer is sent, then calls `p12_tx_completed(completed)` (`corrected-7c937a9e.c:4307-4316`).
- R56 wires those four R54 kinds through `p12_tx_completed(kind)` to `r54_p12_tx_completed(kind)` (`entrance_p116_r54_call_adoption_listener_transform.py:215-220`; parent-verified generated source lines 4667-4672).
- `r54_p12_tx_completed(kind)` advances from each `WAIT_*_FLUSH` state to the next `NEED_*` state only on the matching completed kind: invite ACK to local CAPABILITIES, local CAPABILITIES to local ALERTING, local ALERTING to peer wait or peer DATA ACK, and peer DATA ACK to `MEDIA_TRIGGER_READY` (`entrance_p116_r54_call_adoption_listener_transform.py:574-615`).
- The media trigger is therefore gated on the peer DATA ACK full-flush path, not on enqueue.

## Queue Attribution

R56 adds bounded subjects:

`NONE`, `INVITE_ACK`, `LOCAL_CAPABILITIES`, `LOCAL_ALERTING`, `PEER_DATA_ACK`, `MEDIA_OPEN`, `MEDIA_STOP`, `OTHER_EXISTING`.

Reasons:

`NONE`, `BUSY`, `INVALID_LENGTH`, `NO_WRITER`, `TRANSPORT`, `ALLOCATION`, `UNKNOWN`.

New markers include `R54_TX_SUBJECT`, `R54_TX_WAITING_FOR_SLOT`, `R54_TX_ENQUEUED`, `R54_TX_FLUSHED`, `R54_TX_QUEUE_FAIL_SUBJECT`, and `R54_TX_QUEUE_FAIL_REASON`. Busy is a transient wait condition and does not set `failed = TRUE`.

`R54_PEER_DATA_ACK_SENT` is now intentionally an alias of the flushed state. The R56 diagnostics source emits both `R54_PEER_DATA_ACK_FLUSHED` and `R54_PEER_DATA_ACK_SENT` from `g_r54_peer_data_ack_flushed` (`entrance_p116_r54_call_adoption_listener_transform.py:348-350`). The earlier invite-ACK-derived meaning is gone, so the diagnostic name no longer reports mere enqueue or an unrelated R45 counter.

## Peer Race Contract

Contract A is implemented. If peer CAPABILITIES arrives before local ALERTING has flushed, R56 validates bounded semantic fields, stores only parsed state required for ACK sequencing, and waits until `P12_TX_R54_LOCAL_ALERTING` completion. It does not retain raw payload. After local flush, the scheduler emits peer DATA ACK once and triggers media only after peer ACK completion.

`PEER_CAPABILITIES_DURING_LOCAL_TX=stored_semantic_scalars_until_local_alerting_flush`

## Duplicate CALL_INIT Contract

A corrective sub-turn added a race matrix (`r56_duplicate_call_init_no_replay`,
`r56_generation_replaced_no_cross_write`) to the host harness and it caught a real defect: the prior
`r54_handle_call_init()` unconditionally called `r53_reset_state(&g_r54_call_adoption, g_r35_session.call_generation)`
on every invocation, including a repeated `CALL_INIT` for a call the TX scheduler was already mid-chain on
(any `WAIT_*_FLUSH` state). That reset the state machine back to `NEED_INVITE_ACK`, discarded the bounded
pending-peer-capabilities state kept for the early-peer race, and re-drove the chain, re-enqueuing frames on
top of the one already owned by the single P12 TX slot.

The fix keys the decision on the same generation authority the scheduler already tracks
(`g_r54_tx_generation`, set once per generation from `g_r35_session.call_generation`, which is itself owned
by the pre-existing R35 capture contract: `call_generation` / `call_ctp_connection` / call sequence):

- **Same generation** (`g_r54_tx_generation != 0 && g_r54_tx_generation == g_r35_session.call_generation`):
  the repeated `CALL_INIT` is ignored by the TX scheduler before `r53_reset_state` is reached. No state reset,
  no re-enqueue, no re-drive, and any in-flight `WAIT_*_FLUSH` progress or stored pending-peer-capabilities
  state is preserved untouched. The scheduler emits `R54_TX_DUPLICATE_CALL_INIT_IGNORED=true` followed by
  `R54_TX_STATE=<unchanged state>` and returns success unless the scheduler was already in
  `TERMINAL_FAILURE` (a duplicate is not itself a terminal failure).
- **New generation** (`g_r54_tx_generation != g_r35_session.call_generation`): unchanged from the original R56
  design. `r53_reset_state` runs, the scheduler starts at `NEED_INVITE_ACK` for the new generation, and any
  stale completion for the old generation is already dropped by the existing generation guard in
  `r54_p12_tx_completed`/`r54_tx_drive` (`TX_GENERATION_REPLACED`), so no cross-generation write is possible.
  This path was already covered and passing before this sub-turn (`R56_GENERATION_REPLACED_NO_CROSS_WRITE`).

```
DUPLICATE_CALL_INIT_CONTRACT=same_generation_ignore
DUPLICATE_MARKER=R54_TX_DUPLICATE_CALL_INIT_IGNORED
NEW_GENERATION_REPLACES_SAFELY=true
```

The race matrix itself needed one test-infrastructure fix, made in the harness driver only (not in the
generated production region): `r56h_hold_at_wait_state()` used a single `p12_flush_tx()` call per loop
iteration expecting it to complete exactly one P12 TX frame, but `r54_p12_tx_completed()` synchronously
re-drives and can enqueue-and-flush the next frame inline, so one call could cascade through all three local
`WAIT_*_FLUSH` states in a single step and the helper could only ever observe `WAIT_INVITE_ACK_FLUSH`. A
`g_fake_p12_single_step_mode` flag now re-arms `g_fake_p12_hold_flush` immediately before driving the
completion callback, so each `p12_flush_tx()` call advances exactly one P12 TX slot; this only changes test
scaffolding behavior used by the new hold-at-state helper and does not alter any existing assertion or the
full-cascade behavior other R56 tests rely on (e.g. `r56_busy_wait_serialized`).

## Timeout

Every wait state arms a monotonic deadline using the existing P12 step timeout:

```
TX_WAIT_TIMEOUT_SOURCE=P12_STEP_TIMEOUT_SECONDS
TX_WAIT_TIMEOUT_MS=6000
```

The timeout callback is fail-closed: it sets `TX_WAIT_TIMEOUT`, emits generation-end diagnostics, does not retry, and does not trigger media.

## native_exit:6

The previous R56 document attribution was wrong. The provable writable-callback path is:

`PseudoTcpWritable -> pseudotcp_writable_cb -> try_send_echo_ack/try_send_uaut_open/p12_flush_tx -> failed = TRUE`.

Only non-`EWOULDBLOCK` send/transport errors can make the callees return false on this path:

- `try_send_echo_ack()` writes directly from `echo_ack + echo_ack_offset`; it returns true when nothing is due and treats `EWOULDBLOCK` as success, returning false only after another PseudoTCP send error (`corrected-7c937a9e.c:7178-7185`, `corrected-7c937a9e.c:7190-7225`).
- `try_send_uaut_open()` writes directly from `uaut_open + uaut_open_offset`; it returns true when nothing is due and treats `EWOULDBLOCK` as success, returning false only after another PseudoTCP send error (`corrected-7c937a9e.c:7000-7007`, `corrected-7c937a9e.c:7093-7130`).
- `p12_flush_tx()` returns true for no pending P12 frame and for `EWOULDBLOCK`; it returns false only for another PseudoTCP send error (`corrected-7c937a9e.c:4270-4301`).

Therefore P12 adoption queue occupancy cannot make frozen echo ACK or UAUT OPEN writer attempts fail through the single-slot guard, and a busy/pending P12 slot cannot by itself reach `failed = TRUE` through `pseudotcp_writable_cb`. This path was already non-fatal for a busy slot before R56, and R56 did not modify `try_send_echo_ack`, `try_send_uaut_open`, `p12_flush_tx`, or `pseudotcp_writable_cb`.

Field values:

```
WRITABLE_CB_DIRECT_BUSY_FATAL_BEFORE=false
WRITABLE_CB_DIRECT_BUSY_FATAL_AFTER=false
WRITABLE_CB_DIRECT_BUSY_FATAL_BASIS=PREEXISTING_NON_FATAL
ADOPTION_OCCUPANCY_CAN_FAIL_FROZEN_WRITERS=false
```

The single live canary's `native_exit:6` cause remains unproven from the available evidence. Ranked candidate causes:

1. P12 step deadline expiry: the existing timeout uses `P12_STEP_TIMEOUT_SECONDS` and sets `failed = TRUE` in `p12_stage_timeout_cb` when a stage deadline expires (`corrected-7c937a9e.c:611`, `corrected-7c937a9e.c:1184-1217`). This is plausible for an exit with bounded marker tail and no later completion evidence, but not proven causal.
2. PseudoTCP session failure: `pseudotcp_closed_cb()` unconditionally sets `failed = TRUE` on close (`corrected-7c937a9e.c:7774-7812`), and `pseudotcp_write_packet_cb()` sets `failed = TRUE` on invalid conversation wire bytes or incomplete `nice_agent_send()` (`corrected-7c937a9e.c:7815-7865`).
3. Door write/timer paths: chained door write failure and timer expiry can set `failed = TRUE` after a Door operation starts (`corrected-7c937a9e.c:4164-4198`, `corrected-7c937a9e.c:4826-4896`). They are candidates only if Door action context existed.
4. Receive/parse/session paths: other inventory setters include initial parse/open/auth failures, recv-parse failures, file/SDP failures, and listener lifecycle failures. No single one is attributable to the canary without a direct marker or line-specific runtime trace.

## Generated Source Gates

R56 is generator-integrated in `entrance_p116_r54_call_adoption_listener_transform.py` and `entrance_p116_r53_call_adoption_profile_core.py`, plus bounded parser/test updates. The obsolete R53 immediate-trio orchestrator `r53_start_after_call_capture` was removed from the canonical R53 core after the R54 TX state machine took over sequencing. The now-dead profile predicate `r53_helper_profile_is_expected` was also removed so no replacement generated-source warning is introduced. Regeneration from the frozen source was byte-identical across two runs.

```
CORRECTED_GENERATED_SOURCE_SHA256=43647e1a5f8524e2ab1c85111e8f9ac606f9d57aa5e5d5f4767cf077be42b0a2
CORRECTED_SOURCE_DETERMINISTIC=true
OLD_IMMEDIATE_TRIO_PATTERN_PRESENT=false
GENERATED_SOURCE_TX_SCHEDULER_EQUIVALENCE=PASS
DOOR_SEMANTICS_CHANGED=false
REMOVED_DEAD_SYMBOLS=r53_start_after_call_capture,r53_helper_profile_is_expected
```

The prior sha (`f6e43a10636d0b6a12ce558fd5526d0843e4b2612a659c1b4e76dcc2ac32a8d0`) was the pre-duplicate-fix
generated source that the parent's host run correctly failed against (`R56_DUPLICATE_CALL_INIT_NO_REPLAY=FAIL`).
The sha above reflects the duplicate-`CALL_INIT` scheduler fix described above and was confirmed
byte-identical across two regeneration runs.

## Offline Verification

Turn-3 focused suites passed:

- `test_p116_r53_call_adoption_protocol_profile` + `test_p116_r54_call_adoption_production_candidate`: 28 tests OK.
- `test_p116_r55_post_canary_failure_forensic`, `test_p116_r42b_canary_observability`, `test_p116_r42b_capabilities_diag_behavior`, and `test_p116_r45_call_adoption_host_harness`: 87 tests OK.

Turn-3 parent-host canonical verification was authoritative at that point: `Ran 2055 / OK (skipped=1)`, 0 errors.
The parent's independent host rerun after turn 3/4 caught the duplicate-`CALL_INIT` defect
(`R56_DUPLICATE_CALL_INIT_NO_REPLAY=FAIL`, `R54_HOST_HARNESS_RESULT=FAIL`) before any live attempt; that
failure report is what this sub-turn corrects.

This sub-turn's focused rerun of `test_p116_r54_call_adoption_production_candidate` is 18/18 OK, with every
`R54_HOST_HARNESS_RESULT`/`R56_*` marker at `PASS`. Sandbox full-suite discovery
(`PYTHONPATH=src python3 -m unittest discover -s tests -p "test_*.py"`) ran 2056 tests, `OK (skipped=1)`, 0
errors/failures — no test was removed by this sub-turn, so the count is at or above the turn-3 figure. The
parent-host run remains the gate for the corrected generated-source sha above.

## Production/Build

No binary was built or promoted by this executor. Parent-owned binary/build fields remain pending, except for the expected warning attribution after dead-symbol removal:

`BUILD_RC`, `CORRECTED_BINARY_SHA256`, `CORRECTED_BINARY_SIZE`, `CORRECTED_BINARY_DETERMINISTIC`, `PRODUCTION_SHA_UNCHANGED`.

Expected build warning set after parent musl rebuild:

```
EXPECTED_BUILD_WARNINGS_TOTAL=3
EXPECTED_BUILD_WARNINGS_NEW=0
EXPECTED_BUILD_WARNINGS_PREEXISTING=R35_SECOND_OPEN_FORBIDDEN_STATES,p116_print_final_rtp_summary,pseudotcp_success_quit_cb
```

`BINARY_PROMOTED=false`, `CORRECTIVE_DEPLOYED=false`.

## Remaining Unknowns

No required P12 lifecycle evidence is unknown. Remaining unverified items are parent-owned build/production invariants and host rerun of sandbox-flaky tests.
