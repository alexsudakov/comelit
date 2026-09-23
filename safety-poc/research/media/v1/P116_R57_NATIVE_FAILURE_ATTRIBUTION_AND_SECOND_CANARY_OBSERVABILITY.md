# P116 R57 Native Failure Attribution and Second-Canary Observability

BASE_SHA=28932ee505e4e1b4c0548c685034358822c35ba5
EVIDENCE_BUNDLE=.r57-evidence/

## Scope

Offline-only. No deploy, HA restart/reload, physical ring, self-activation, Door/Gate action, Comelit live
network TX, ADB, ptrace, proprietary-binary execution against Comelit, production promotion, production file
change, musl build, git commit, or push was performed by this executor. This round only reads the evidence
bundle prepared by the parent, edits generator sources under `safety-poc/`, adds a new host-compiled C test
harness, and runs the offline test suites (`cc`, not the musl cross toolchain).

## D1 — First-canary timeline

All ten `Comelit canary evidence <CRITERION>` lines and the ring event line share timestamp
`2026-09-21 21:00:41.981` (`.r57-evidence/live/canary-markers.txt:6-18`). R55 already proved this is one
synchronous burst emitted by `r54_publish_diagnostics(..., R54_DIAGNOSTICS_LOCAL_AFTER_TRIO)` right after
`r54_handle_call_init()` drives invite ACK / local CAPABILITIES / local ALERTING onto the R54 TX scheduler and
sets `WAITING_PEER_CAPABILITIES` — it is a snapshot of local-phase state, not a peer observation
(`.r57-evidence/docs/P116_R55_POST_CANARY_FAILURE_FORENSIC.md` §"R55 Corrected Premature-Publication Finding").

The listener stopped at `2026-09-21 21:00:55.454` with `native_exit:6` (`.r57-evidence/live/canary-markers.txt:21`).

```
FIRST_CANARY_EXIT_AFTER_CALL_INIT_MS=13473
FIRST_CANARY_LAST_PROVEN_STATE=WAITING_PEER_CAPABILITIES
FIRST_CANARY_LAST_PROVEN_TX_SUBJECT=UNKNOWN
FIRST_CANARY_TIMEOUT_COMPATIBLE=false
```

`13473` is `21:00:55.454 - 21:00:41.981`, directly computable from the two timestamps and not otherwise in
question.

`FIRST_CANARY_LAST_PROVEN_STATE=WAITING_PEER_CAPABILITIES` is the last state the live evidence actually proves,
not a claim about the true state at the moment of exit. `custom_components/comelit/runtime.py:9438-9442`
(generated-source line numbers in `.r57-evidence/generated/r56-generated-43647e1a.c`) shows `main()` calls
`r54_publish_diagnostics(&g_r54_call_adoption, R54_DIAGNOSTICS_GENERATION_END)` — which would print the real
`R54_TX_STATE`, `R54_TX_SUBJECT`, and `R54_CALL_ADOPTION_FAILURE_STAGE` at exit — immediately after the
unconditional `PSEUDOTCP_OPEN_FINAL=%s` print and before `return failed ? 6 : 0;`. Both prints are followed by
`fflush(stdout)`. But the observed bounded tail (`safe_native_markers`, exactly 20 entries, matching
`_NATIVE_MARKER_TAIL_LIMIT=20` in `custom_components/comelit/runtime.py:73`) ends with `PSEUDOTCP_OPEN_FINAL=true`
— it contains **no** `R54_*` field from that final publish call, even though `R54_` is in
`_NATIVE_MARKER_PREFIXES` (`custom_components/comelit/runtime.py:63-72`) and would otherwise occupy the newest
slots in the ring buffer. Since the native process is proven (by code, both flush calls present) to have written
those `R54_*` lines before exiting, their absence from the captured tail is an HA-side capture-timing gap between
subprocess-exit detection and the stdout line-reader draining the final buffered chunk, not evidence that the
process never printed them. This is a Python-side (`runtime.py`) observability gap outside this round's native
C scope; it is called out here because it is why `FIRST_CANARY_LAST_PROVEN_TX_SUBJECT` and the true terminal
`R54_TX_STATE` are `UNKNOWN` from live evidence rather than reconstructable.

The proven bounded tail itself: two `V4_RING_RETRANSMIT_SUPPRESSED=true` + `V4_RING_RETRANSMIT_SHA256` +
`PSEUDOTCP_APP_RX_EVENT` triples (two suppressed ring retransmits, each followed by an app-level receive event),
a third `PSEUDOTCP_APP_RX_EVENT` with a classified `V4_RX_ECHO_*` set (an echo reply parsed and classified,
`BODY_LEN=29`), then `P12_TX_QUEUE=FAIL`, then the fixed `GENERATION_END` shutdown block
(`ICE_OFFER_HELD` … `PSEUDOTCP_OPEN_FINAL`, unconditionally printed by every exit path per
`.r57-evidence/generated/r56-generated-43647e1a.c:9403-9436`, so it carries no causal information about *why*
the loop quit). `P12_TX_QUEUE=FAIL` is the raw `p12_queue_bytes()` site
(`.r57-evidence/code/p12-queue-bytes.txt:14`), which carries no subject; it is **not** immediately preceded or
followed by `R54_TX_QUEUE_FAIL_SUBJECT`/`R54_TX_QUEUE_FAIL_REASON` (R56's attributed wrapper markers, confirmed
present in the generated source at lines 1966-1967/1975-1976), which is evidence the rejected enqueue was **not**
from the R54 call-adoption scheduler's own attributed path — more likely a concurrent echo-reply or
ring-retransmit-ack write colliding with the single P12 slot, consistent with the RX activity immediately
preceding it in the same tail window.

## D2 — P12 step-timeout hypothesis: disproven

```
P12_STEP_TIMEOUT_SECONDS=6
P12_STEP_TIMEOUT_STARTED_AT=p12_begin_auth() arms a single recurring 200ms GSource once (p12_stage_timeout_cb); the deadline itself (p12_deadline_us) is (re)armed at every P12 bootstrap stage transition via p12_set_deadline()
P12_STEP_TIMEOUT_EXPIRES_AT=DISARMED (p12_deadline_us forced to 0) whenever p12_stage reaches P12_STAGE_V4_LISTEN_RING; only re-armed while p12_stage is a bootstrap-transitional stage
FIRST_CANARY_EXIT_MATCHES_P12_TIMEOUT=false
```

There are **two independent mechanisms** sharing the same `P12_STEP_TIMEOUT_SECONDS=6` constant, and neither can
explain the first canary:

1. **Legacy P12 bootstrap timeout** (`p12_set_deadline()` / `p12_stage_timeout_cb()`,
   `.r57-evidence/code/p12-set-deadline.txt`). `p12_stage_timeout_cb` bails immediately (no-op) when
   `p12_stage` is `P12_STAGE_IDLE` or `P12_STAGE_DONE`; otherwise it polls every 200 ms and fires `failed = TRUE`
   only if `p12_deadline_us > 0` and expired. `.r57-evidence/generated/r56-generated-43647e1a.c:4631-4641` shows
   that after **every** `p12_tx_completed()` callback (including all four R54 call-adoption kinds,
   `P12_TX_R54_INVITE_ACK` … `P12_TX_R54_PEER_DATA_ACK`, which `break` into this same shared tail), the code
   unconditionally clears `p12_deadline_us = 0` whenever `p12_stage == P12_STAGE_V4_LISTEN_RING`, and only calls
   `p12_set_deadline()` (re-arms) otherwise. The ring listener was already `READY` (`V4_RING_LISTENER_READY=true`
   observed before the canary, per the R54 canary doc) — i.e. `p12_stage` was already
   `P12_STAGE_V4_LISTEN_RING` — and none of R54's TX completions change `p12_stage`. So this deadline was
   **disarmed for the entire call-adoption window**, and this legacy timeout structurally could not have fired.

2. **R56 TX-wait timeout** (`r54_tx_set_wait_deadline()` / `r54_tx_wait_timeout_cb()`,
   `.r57-evidence/generated/r56-generated-43647e1a.c:3092-3172`), added by R56 and reusing the same
   `P12_STEP_TIMEOUT_SECONDS` constant for its own, unrelated 6 s deadline
   (`g_r54_tx_wait_deadline_us`, a separate variable). Its callback calls `r54_tx_terminal_failure()`, which only
   sets `g_r54_tx_state = R54_TX_STATE_TERMINAL_FAILURE` and the diagnostics failure stage — it **never** sets
   the global `failed` and **never** calls `g_main_loop_quit()` (confirmed again by this round; matches R56's own
   finding). Even if this timeout had fired during the canary, it structurally cannot cause `native_exit:6` by
   itself; call adoption would simply stall in `TERMINAL_FAILURE` while the process kept running.

Both mechanisms are demoted. The apparent numerical tension the round brief flagged (6 s constant vs. 13.473 s
observed gap) is explained, not by a re-arm race, but by the constant being irrelevant to this exit: the fatal
setter belongs to a different subsystem entirely (see D3/D4).

## D3 — Complete `failed = TRUE` setter map (26 real sites)

All 26 sites are inherited unchanged from the frozen v1.5.7 listener (none are inside the R53/R54/R45 regions;
confirmed by diffing `r54.transform(source)` against the R56 evidence sha — byte-identical, and none of R54's own
call-adoption paths, including `r54_tx_terminal_failure`, ever touch the global `failed`).

| # | Line(s)† | Function | Triggering condition | R56 reachable | First-canary compatible | Existing marker | New `P116_NATIVE_FAILURE_ID` |
|---|------|----------|----------------------|----------------|--------------------------|------------------|-------------------------------|
| 1 | 463 | `p80_try_forward_wrapped_rtp` | RTP profile mismatch (`!p80_profile_accept`) | media-only, post `MEDIAREQ26 OPEN` | NO — media never opened this canary | `P80_WRAPPER_PROFILE_MISMATCH=true` | `P80_RTP_FORWARD` |
| 2 | 481 | `p80_try_forward_wrapped_rtp` | loopback socket create fail | media-only | NO | `P80_RTP_FORWARD_SOCKET=FAIL` | `P80_RTP_FORWARD` |
| 3 | 499 | `p80_try_forward_wrapped_rtp` | forward `sendto` fail | media-only | NO | `P80_RTP_FORWARD_SEND=FAIL` | `P80_RTP_FORWARD` |
| 4 | 903 | `recv_cb` | `pseudo_tcp_socket_notify_packet()` rejects wire packet | always (whole session) | **YES** | `PSEUDOTCP_NOTIFY_PACKET=FAIL` | `PSEUDOTCP_NOTIFY_PACKET` |
| 5 | 979 | `absolute_timeout_cb` | 3300 s absolute session timeout, non-ready branch | only pre-`READY`; fires once at T+3300s from listener start | NO — listener already READY, 3300s ≫ 13.473s | `ICE_HOLDER_TIMEOUT=true` / `PSEUDOTCP_TIMEOUT=true` | `ABSOLUTE_SESSION_TIMEOUT` |
| 6 | 1212 | `p12_stage_timeout_cb` | legacy P12 stage deadline expired | disarmed during ring listening (D2) | NO | `P12_READONLY_STAGE_TIMEOUT stage=%u` | `P12_STEP_TIMEOUT` |
| 7 | 4548 | `p12_tx_completed` (Door case) | chained `v4_door_queue_write` fails mid-sequence | Door-write only | NO — `DOOR_ACTIONS=0` this round | (`v4_door_emit_result`) | `DOOR_WRITE` |
| 8 | 4566 | `p12_tx_completed` (Door case) | settle-timer `g_timeout_add` install fails | Door-write only | NO | (`v4_door_emit_result`) | `DOOR_WRITE` |
| 9 | 5217 | `v4_door_tick_cb` | door deadline exceeded mid-send | Door-write only | NO | (`v4_door_emit_result`) | `DOOR_TIMER` |
| 10 | 5268 | `v4_door_tick_cb` | initial `v4_door_queue_write(1)` fails | Door-write only | NO | (`v4_door_emit_result`) | `DOOR_WRITE` |
| 11 | 7231 | `uaut_response_timeout_cb` | startup UAUT open response never seen | one-shot, pre-READY | NO — listener reached READY, this gate already passed | `VIP_UAUT_OPEN_RESPONSE_TIMEOUT=true` | `UAUT_OPEN_TIMEOUT` |
| 12 | 8061 | `pseudotcp_readable_cb` | `try_parse_initial_echo()` fails | only while `!echo_ack_sent` (pre-READY) | NO | (implicit) | `RECV_PARSE` |
| 13 | 8091 | `pseudotcp_readable_cb` | `try_parse_uaut_response()` → `p12_process_post_uaut()` fails | **always**, post-handshake — this is the *only* receive-processing path for the entire persistent ring-listening lifetime (`.r57-evidence/generated/r56-generated-43647e1a.c:7242-7248` routes every post-handshake receive through `p12_process_post_uaut`, the generic V4/CTPP frame demux at line 5282) | **YES — top candidate** | (implicit) | `RECV_PARSE` |
| 14 | 8122 | `pseudotcp_readable_cb` | `pseudo_tcp_socket_get_error()` transport error on recv | always | **YES — top candidate** | `PSEUDOTCP_RECV=FAIL` | `PSEUDOTCP_RECV_TRANSPORT` |
| 15 | 8144 | `pseudotcp_writable_cb` | echo-ack/UAUT-open/`p12_flush_tx` send fails | always (R56 proved only non-`EWOULDBLOCK` PseudoTCP send errors reach this, never a busy P12 slot alone) | **YES — top candidate** | (implicit) | `PSEUDOTCP_WRITABLE_TRANSPORT` |
| 16 | 8184 | `pseudotcp_closed_cb` | transport closed (before or after open) | always | **YES — top candidate** | `PSEUDOTCP_CLOSED_BEFORE_OPEN` / `AFTER_OPEN` | `PSEUDOTCP_CLOSED` |
| 17 | 8220 | `pseudotcp_write_packet_cb` | malformed conversation-wire prefix | always (every outbound wire write) | YES (requires an internal encoding bug; not excluded) | `PSEUDOTCP_CONVERSATION_WIRE=FAIL` | `PSEUDOTCP_WRITE_PACKET` |
| 18 | 8242 | `pseudotcp_write_packet_cb` | `nice_agent_send()` length mismatch | always — this is the transport every `p12_flush_tx()` send ultimately funnels through | **YES — top candidate** | `PSEUDOTCP_WRITE_PACKET=FAIL` | `PSEUDOTCP_WRITE_PACKET` |
| 19 | 8277 | `pseudotcp_clock_cb` | closed detected on clock tick, before open | only while `!pseudotcp_open` | NO — `PSEUDOTCP_OPEN_FINAL=true` proves open was already achieved | `PSEUDOTCP_CLOSED_BEFORE_OPEN=true` | `PSEUDOTCP_CLOCK_CLOSED` |
| 20 | 8534 | `component_state_changed_cb` | `report_selected_pair()` fails on ICE READY | one-shot on first READY transition (`start_pseudotcp()` short-circuits true once started) | NO — no ICE restart evidence | `SELECTED_PAIR=FAIL` | `ICE_CONNECTIVITY` |
| 21 | 8548 | `component_state_changed_cb` | `start_pseudotcp()` fails on ICE READY | one-shot | NO | `PSEUDOTCP_START=FAIL` | `ICE_CONNECTIVITY` |
| 22 | 8569 | `component_state_changed_cb` | ICE component transitions to FAILED | can recur any time in principle | NO — tail shows continued `PSEUDOTCP_APP_RX_EVENT` activity through the window, which requires a live selected pair; an unconditional immediate-quit ICE_FAILED is inconsistent with continued RX right up to the queue-fail marker | `ICE_CONNECTIVITY=FAIL` | `ICE_CONNECTIVITY` |
| 23 | 8962 | `remote_sdp_check_cb` | remote SDP file read fails | one-shot, guarded by `!remote_loaded` latch | NO — `REMOTE_SDP_LOADED=true` observed in the exit tail proves `remote_loaded` already latched true, and it never resets | `REMOTE_SDP_READ=FAIL` | `SDP_FILE` |
| 24 | 9000 | `remote_sdp_check_cb` | remote primitives import/parse fails | one-shot, same latch | NO — same proof | `REMOTE_PRIMITIVES_IMPORT=FAIL` | `SDP_FILE` |
| 25 | 9103 | `candidate_gathering_done_cb` | ICE candidate gathering empty/failed | one-shot (fires once per ICE session; no restart call site in this source) | NO | `ICE_GATHER=FAIL` | `ICE_GATHER` |
| 26 | 9140 | `candidate_gathering_done_cb` | local offer-SDP file write fails | one-shot | NO | `OFFER_WRITE=FAIL` | `SDP_FILE` |

† Line numbers refer to `.r57-evidence/generated/r56-generated-43647e1a.c` (identical to `r54.transform(source)`
today, confirmed by hash match) and shift slightly after the R57 overlay is applied; the transform locates each
site by unique literal anchors instead of line numbers (see Implementation).

## D4 — Exclusion

```
FIRST_CANARY_COMPATIBLE_FAILED_SETTERS=PSEUDOTCP_NOTIFY_PACKET(#4),RECV_PARSE(#13),PSEUDOTCP_RECV_TRANSPORT(#14),PSEUDOTCP_WRITABLE_TRANSPORT(#15),PSEUDOTCP_CLOSED(#16),PSEUDOTCP_WRITE_PACKET(#17,#18)
FIRST_CANARY_INCOMPATIBLE_FAILED_SETTERS=P80_RTP_FORWARD(#1-3),ABSOLUTE_SESSION_TIMEOUT(#5),P12_STEP_TIMEOUT(#6),DOOR_WRITE(#7,#8,#10),DOOR_TIMER(#9),UAUT_OPEN_TIMEOUT(#11),RECV_PARSE_PRE_READY(#12),PSEUDOTCP_CLOCK_CLOSED(#19),ICE_CONNECTIVITY(#20,#21,#22),SDP_FILE(#23,#24,#26),ICE_GATHER(#25)
FIRST_CANARY_FAILED_SETTER_UNIQUELY_IDENTIFIED=false
FIRST_CANARY_FAILED_SETTER=UNKNOWN
```

Exclusion basis, each proven from static control flow or direct live evidence (never assumption):

- **Media-only sites (#1-3)** excluded because the live evidence proves media never opened this canary
  (`MEDIAREQ26_OPEN_SENT=false`, `RTP_RECEIVED=false` in the canary criteria table).
- **Door sites (#7-10)** excluded because `DOOR_ACTIONS=0` is a proven counter for this round/canary
  (`.r57-evidence/live/r54-live-summary.txt:77`) and these paths are only reachable from an HA-triggered Door
  write.
- **Startup-one-shot sites (#5, #6, #11, #12, #19-21, #23-25)** excluded because the listener had already reached
  `V4_RING_LISTENER_READY=true` before the canary call, and each of these sites is gated by a latch, guard, or
  compile-time constant (`p12_stage != IDLE/DONE` disarmed at `V4_LISTEN_RING`, `!echo_ack_sent`,
  `!remote_loaded`, one-shot ICE READY/gathering-done signal, 3300 s absolute timeout) that the READY state
  already proves has passed or been disarmed.
- **#22 (ICE_CONNECTIVITY=FAIL / ICE FAILED transition)** is the one site excluded on evidence rather than a
  static latch: it is *reachable* in principle at any time, but the observed marker tail shows
  `PSEUDOTCP_APP_RX_EVENT` (app-level PseudoTCP data delivery, which requires an intact selected ICE pair)
  occurring immediately before the terminal `P12_TX_QUEUE=FAIL`/shutdown block, which is inconsistent with an
  unconditional immediate-quit ICE-FAILED transition having already happened.
- **#26 (`OFFER_WRITE=FAIL`)** is grouped with `SDP_FILE` and excluded on the same one-shot-startup basis as
  #23/#24 (local offer write happens once, during initial ICE gathering, long before the ring/READY state).

Seven sites remain compatible and are not further distinguishable from the available evidence: `#4` (raw
PseudoTCP notify-packet reject), `#13` (the generic post-handshake receive demux — every ring/CALL_INIT/
CAPABILITIES/ACK/echo frame for the rest of the session's life passes through here), `#14` (PseudoTCP transport
recv error), `#15` (PseudoTCP writable-callback send failure — the same callback the observed
`P12_TX_QUEUE=FAIL` marker sits adjacent to), `#16` (PseudoTCP transport closed), `#17`/`#18` (PseudoTCP
write-packet failure — the shared transport every `p12_flush_tx()` send, including R54's own local trio and
peer ACK, ultimately calls through). `FIRST_CANARY_FAILED_SETTER_UNIQUELY_IDENTIFIED=false`: a second live
canary with R57's observability in place is required to prove which one of these seven actually fired.

## Failure-identity contract (implementation)

Generator-integrated in a new overlay module,
`safety-poc/research/media/v1/entrance_p116_r57_native_failure_attribution_transform.py`, layered on top of
`entrance_p116_r54_call_adoption_listener_transform.transform()` (which itself already chains R35/R36/R42b/R45/
R53). It never edits the generated `.c` file or the frozen listener (`safety-poc/research/door/v1_5_7/
comelit-v4-persistent-ctpp-door.c`, sha256 unchanged, `EXPECTED_FROZEN_SHA256` gate still enforced); it applies
unique-literal-anchored text patches to the R54-transformed candidate, the same technique R54 itself already
uses against frozen-base anchors (`_ENUM_ANCHOR`, `_WRITER_ANCHOR`, etc.).

Adds, in one new region (`R57_NATIVE_FAILURE_ATTRIBUTION_BEGIN/END`, inserted immediately after
`R54_CALL_ADOPTION_LISTENER_END`):

- `P116NativeFailureId` (18 values: `NONE` plus 17 covering every site above, splitting classes further than the
  round's minimum list where causes are materially different — e.g. `PSEUDOTCP_RECV_TRANSPORT` vs `RECV_PARSE`,
  `ICE_CONNECTIVITY` vs `ICE_GATHER`, `ABSOLUTE_SESSION_TIMEOUT`/`UAUT_OPEN_TIMEOUT` vs `P12_STEP_TIMEOUT`) and
  `P116NativeFailurePhase` (the round's 9-value minimum, unchanged).
- `p116_infer_phase()` — best-effort dynamic phase classification from existing state
  (`v4_listener_ready`, `r42_media_stage`, `g_r54_tx_state`) for the handful of cross-phase sites (the generic
  PseudoTCP callbacks and the RTP forwarder); read-only, no new writes or control flow.
- `p116_record_failure(id, phase)` — **first-fail-wins**: increments a bounded `g_p116_failure_count`
  unconditionally, but only assigns `g_p116_failure_id`/`g_p116_failure_phase` the first time (while still
  `NONE`). A cascade of later `failed = TRUE` sites can never overwrite the root cause.
- `p116_emit_timeout_observability(kind)` — prints `P116_TIMEOUT_KIND=<kind>` and
  `P116_TIMEOUT_PHASE=<enum>` for every timeout, wired into the R56 TX-wait timeout callback
  (`r54_tx_wait_timeout_cb`) **without** touching its existing non-fatal semantics (still never sets `failed`,
  still never quits the loop — verified by a dedicated regression test).
- `p116_emit_native_exit_summary(failed)` — inserted immediately before `return failed ? 6 : 0;` (the only
  `main()` return site), prints `P116_NATIVE_EXIT_CODE`, `P116_NATIVE_FAILURE_ID`, `P116_NATIVE_FAILURE_PHASE`,
  `P116_NATIVE_FAILURE_COUNT`. With `failed=false`, `g_p116_failure_id` provably stays `P116_FAILURE_NONE`
  (nothing sets it on the success path). With `failed=true`, one of the 26 sites must have run
  `p116_record_failure()` first (every `failed = TRUE;` occurrence in the generated source is proven, by a
  regression test scanning the actual generated text, to be immediately preceded by a
  `p116_record_failure(P116_FAILURE_...)` call), so the ID can never stay `NONE`.

```
P116_NATIVE_FAILURE_ID_ENUM=NONE,STARTUP,ABSOLUTE_SESSION_TIMEOUT,P12_STEP_TIMEOUT,UAUT_OPEN_TIMEOUT,RECV_PARSE,PSEUDOTCP_RECV_TRANSPORT,PSEUDOTCP_WRITABLE_TRANSPORT,PSEUDOTCP_CLOSED,PSEUDOTCP_WRITE_PACKET,PSEUDOTCP_CLOCK_CLOSED,PSEUDOTCP_NOTIFY_PACKET,ICE_CONNECTIVITY,ICE_GATHER,SDP_FILE,DOOR_WRITE,DOOR_TIMER,P80_RTP_FORWARD,OTHER
P116_NATIVE_FAILURE_PHASE_ENUM=STARTUP,LISTENER_READY,CALL_ADOPTION_LOCAL,WAIT_PEER_CAPABILITIES,PEER_ACK,MEDIA_OPEN,MEDIA_ACTIVE,MEDIA_STOP,GENERATION_END
NATIVE_EXIT_6_WITHOUT_FAILURE_ID=false
OBSERVABILITY_PROTOCOL_WRITES_ADDED=0
```

No protocol writes were added: the R57 region contains no `p12_queue_bytes`/`p12_queue_vip_frame`/
`p12_flush_tx`/`nice_agent_send`/`pseudo_tcp_socket_send` call (enforced by a transform-time gate and a
regression test). The ACK serializer, CAPABILITIES profile, ALERTING serializer, R56 scheduler transitions,
queue depth, the 6000 ms R56 TX-wait timeout value, the peer-capability predicate, peer-ACK ordering, media-OPEN
semantics, and Door behaviour are all unchanged — R57 only ever inserts a call *before* an existing
`failed = TRUE;` assignment or *before* the existing `return`, it never changes an existing condition, ordering,
or assignment.

## Generated-source / build provenance

```
CORRECTED_GENERATED_SOURCE_SHA256=fbd6137a5bb8b0f7258bfe69d72481c70272645aae0d4c0f0dff8c66d0b2237c
CORRECTED_SOURCE_DETERMINISTIC=true
PRE_FIX_CANDIDATE_SOURCE_SHA256=db6bee616fb3a0abc1fb7e98dce2157b9e46bc22b62ef8bb9116e287744d5552
PRE_FIX_CANDIDATE_BUILD_RC=1
PRE_FIX_CANDIDATE_DEFECT=DECLARATION_ORDER
FROZEN_SOURCE_SHA256_UNCHANGED=5827d9fd043b85fc0c59a31661a1a125c6b239771e2a70c3e5afdd95f1a03c73
GENERATED_LINES=9684
R56_BASELINE_SHA256=43647e1a5f8524e2ab1c85111e8f9ac606f9d57aa5e5d5f4767cf077be42b0a2
```

Regeneration is byte-identical across two independent `transform()` runs (asserted by a dedicated test) and across two
independent CLI invocations. No binary was built or promoted by this executor; the musl build and production promotion
remain parent-owned, as in R55/R56.

`CORRECTED_GENERATED_SOURCE_SHA256` is the *corrective* value (declaration order fixed — see the next-but-one
section). The first R57 candidate, `db6bee61…`, was byte-deterministic too and still did not compile; determinism is
not a compilability gate, which is why the whole-translation-unit gate below now exists.

## Integration marker plumbing (CORRECTIVE turn 2)

Turn 1 (native side) is accepted unchanged (`CORRECTED_GENERATED_SOURCE_SHA256` above is reproduced
byte-identical by this turn). Independent orchestrator review found a gap that defeats the round's stated
purpose ("the next live canary cannot end in an unexplained `native_exit=6`"): `custom_components/comelit/
runtime.py` would have silently discarded every one of the new markers.

**The gap.** `_NATIVE_MARKER_PREFIXES` did not include `"P116_"`, so `_remember_native_marker()` returned before
`P116_NATIVE_EXIT_CODE`, `P116_NATIVE_FAILURE_ID`, `P116_NATIVE_FAILURE_PHASE`, `P116_NATIVE_FAILURE_COUNT`,
`P116_TIMEOUT_KIND` and `P116_TIMEOUT_PHASE` ever reached `_native_marker_tail` — the only source of
`last_native_failure_markers`, which is the sole failure evidence logged at
`Comelit ring listener stopped: native_exit:6`. Even with the prefix added, the generic
`_NATIVE_MARKER_SAFE_VALUE_RE` (`PASS|FAIL|true|false|READY|OPEN|CLOSED|UNKNOWN_OUTCOME|REJECTED|
REJECTED_NOT_READY|FAILED_SAFE|<digits>`) does not model an enum value such as
`PSEUDOTCP_WRITABLE_TRANSPORT` or `WAIT_PEER_CAPABILITIES`, so the identity would have resolved to `<redacted>`
in the tail and been dropped from the canary-criteria log — reproducing, on the integration side, exactly the
opacity D1 found on the native side for the first canary.

**Fix, `custom_components/comelit/runtime.py`.**

- `"P116_"` added to `_NATIVE_MARKER_PREFIXES`.
- Four new bounded, module-level vocabularies reused verbatim from the native `P116NativeFailureId` /
  `P116NativeFailurePhase` enums and the one `p116_emit_timeout_observability()` call site (all three defined in
  `entrance_p116_r57_native_failure_attribution_transform.py`):
  ```
  _P116_FAILURE_IDS   = {NONE, STARTUP, ABSOLUTE_SESSION_TIMEOUT, P12_STEP_TIMEOUT, UAUT_OPEN_TIMEOUT,
                          RECV_PARSE, PSEUDOTCP_RECV_TRANSPORT, PSEUDOTCP_WRITABLE_TRANSPORT, PSEUDOTCP_CLOSED,
                          PSEUDOTCP_WRITE_PACKET, PSEUDOTCP_CLOCK_CLOSED, PSEUDOTCP_NOTIFY_PACKET,
                          ICE_CONNECTIVITY, ICE_GATHER, SDP_FILE, DOOR_WRITE, DOOR_TIMER, P80_RTP_FORWARD, OTHER}
  _P116_FAILURE_PHASES = {STARTUP, LISTENER_READY, CALL_ADOPTION_LOCAL, WAIT_PEER_CAPABILITIES, PEER_ACK,
                           MEDIA_OPEN, MEDIA_ACTIVE, MEDIA_STOP, GENERATION_END}
  _P116_TIMEOUT_KINDS  = {R54_TX_WAIT_TIMEOUT}     # the only literal p116_emit_timeout_observability() ever prints
  # P116_TIMEOUT_PHASE reuses _P116_FAILURE_PHASES (it prints p116_failure_phase_name() too)
  ```
  `_P116_MARKER_VOCABULARIES` maps each of `P116_NATIVE_FAILURE_ID` / `P116_NATIVE_FAILURE_PHASE` /
  `P116_TIMEOUT_KIND` / `P116_TIMEOUT_PHASE` to its vocabulary. `P116_NATIVE_EXIT_CODE` and
  `P116_NATIVE_FAILURE_COUNT` are numeric and need no vocabulary — they already pass the existing
  `[0-9]{1,10}` branch of `_NATIVE_MARKER_SAFE_VALUE_RE`.
- `_remember_native_marker()` (the tail-capture / `last_native_failure_markers` path) now checks
  `_P116_MARKER_VOCABULARIES.get(key)` first; a hit gates on membership, a miss falls through to the pre-existing
  generic regex unchanged. This is a per-key lookup, not a loosened regex: every other key (`ICE_*`,
  `PSEUDOTCP_*`, `V4_*`, `R54_*`, other `P116_*` telemetry such as `P116_VIDEO_SPS_COUNT`, etc.) is completely
  unaffected and goes through exactly the same generic-regex path as before R57.
- `_safe_native_marker_value()` (the canary-criteria-log path used by `_observe_canary_log_marker`) gets the same
  vocabulary lookup appended after its existing checks (generic regex, diagnostic regex,
  `R54_CALL_ADOPTION_FAILURE_STAGE` whitelist — all untouched), so the new keys can also surface as
  `Comelit canary evidence <CRITERION>` log lines, not just survive in the tail.
- `_CANARY_OBSERVABILITY_MARKERS` gains: `P116_NATIVE_EXIT_CODE`→`NATIVE_EXIT_CODE`,
  `P116_NATIVE_FAILURE_ID`→`NATIVE_FAILURE_ID`, `P116_NATIVE_FAILURE_PHASE`→`NATIVE_FAILURE_PHASE`,
  `P116_NATIVE_FAILURE_COUNT`→`NATIVE_FAILURE_COUNT`, `P116_TIMEOUT_KIND`→`TIMEOUT_KIND`,
  `P116_TIMEOUT_PHASE`→`TIMEOUT_PHASE`. None of these keys hit the existing H264/boolean/`PASS`-only `elif`
  branches in `_observe_canary_log_marker`, so they are unfiltered once their vocabulary check passes.
- Anything outside a bounded vocabulary is kept as `<redacted>` in the tail (never silently dropped from the tail
  entirely — an unrecognized key prefix is still dropped as before) and is never mapped to a canary criterion
  (`_safe_native_marker_value` returns `None`, so `_observe_canary_log_marker` returns before logging).
- Tail-limit check: the six exit-summary/timeout-observability lines
  (`P116_TIMEOUT_KIND`, `P116_TIMEOUT_PHASE`, `P116_NATIVE_EXIT_CODE`, `P116_NATIVE_FAILURE_ID`,
  `P116_NATIVE_FAILURE_PHASE`, `P116_NATIVE_FAILURE_COUNT`) are the terminal stdout lines before native exit, well
  inside `_NATIVE_MARKER_TAIL_LIMIT=20`; a dedicated test feeds a realistic 10-line pre-exit tail (modeled on the
  D1 first-canary tail shape) plus these six and confirms all six remain present at the newest end of
  `last_native_failure_markers`, and a second test overflows the ring buffer with 30 unrelated lines ahead of them
  to prove eviction always favors the newest (terminal) entries.

**`media_diagnostics.py`: `NOT_NEEDED`.** `_MEDIA_DIAGNOSTIC_PREFIXES` already includes `"P116_"` (added for the
unrelated `P116_VIDEO_*` RTP-evidence markers), but `observe_line()` gates every non-`R42_CALL_GENERATION` key on
membership in `_RECOGNIZED_MEDIA_DIAGNOSTIC_KEYS` and returns `False` (a no-op, not an error or a dropped/flagged
value) for anything outside it. The six new exit/failure/timeout keys are native-process-lifecycle diagnostics,
not per-call media evidence — `MediaCallDiagnostics` has no field for them and none is needed: they carry no
media-channel/RTP/capability information, and `runtime.py`'s own `last_native_failure_markers`/canary-criteria
log is the correct, already-fixed home for them. `observe_line()` returning `False` for these keys is verified by
a dedicated test to leave the snapshot completely unmutated (no field-count or allow-list change required).

**CLI cwd-independence fix.** `entrance_p116_r57_native_failure_attribution_transform.py --sha256` used
`Path(__file__).resolve().parents[3]` (already the `safety-poc/` directory, since the module lives at
`safety-poc/research/media/v1/...py`) and then joined `"safety-poc" / "research" / "door" / ...` onto it,
producing a doubled `.../safety-poc/safety-poc/research/door/v1_5_7/comelit-v4-persistent-ctpp-door.c` that never
exists — `FileNotFoundError` on every invocation, from every cwd (confirmed: the failure is not actually
cwd-dependent, it is a wrong `parents[]`-index/duplicated-segment bug that happens to have been described via a
cwd symptom). Fixed by dropping the redundant `"safety-poc"` segment, matching the pattern the existing test
module (`safety-poc/tests/test_p116_r57_native_failure_attribution.py`) already uses
(`ROOT = Path(__file__).resolve().parents[1]` from `tests/`, then `ROOT / "research" / "door" / ...`). Verified
`--sha256` now prints `db6bee616fb3a0abc1fb7e98dce2157b9e46bc22b62ef8bb9116e287744d5552` identically when invoked
with cwd set to the repo root, `safety-poc/`, and an unrelated directory (`/tmp`). (That value is the pre-corrective
candidate; after the turn-3 declaration-order correct the same CLI prints
`fbd6137a5bb8b0f7258bfe69d72481c70272645aae0d4c0f0dff8c66d0b2237c`, again from all three cwds — the cwd fix itself is
unchanged.)

**New tests.** `safety-poc/tests/test_p116_r57_integration_marker_plumbing.py` (17 tests) exercises the real
`ComelitRingRuntime._async_read_output()` → `_remember_native_marker()` / `_observe_canary_log_marker()` →
`_capture_native_failure()` path (the same integration code path that produced the R54 live canary markers):
exit-summary capture and non-redaction, canary-criteria log lines (including the success/`NONE` case), tail-limit
survival under both a realistic and an overflowing pre-exit tail, the two negative probes (out-of-vocabulary
`P116_` value stays `<redacted>`/never reaches the canary log; an unrelated unknown-prefix key is still dropped
entirely), a same-vocabulary-lookup regression check that no other marker class (`ICE_*`, `R54_CALL_ADOPTION_
FAILURE_STAGE`, other `P116_*` telemetry) was loosened, the `media_diagnostics.py` no-op confirmation, and the CLI
cwd-independence fix (subprocess, three different cwds).

## Declaration-order corrective (build-blocking, CORRECTIVE turn 3)

The first R57 candidate did not compile. The orchestrator built it with the proven musl pipeline
(`alpine:3.24.1`, apk closure, `--network none`, fixed source filename, two independent runs):

```
SOURCE_SHA256=db6bee616fb3a0abc1fb7e98dce2157b9e46bc22b62ef8bb9116e287744d5552
BUILD_A_RC=1  BUILD_B_RC=1  BUILD_WARNINGS_TOTAL=6
11 x error:
  :463:9:  error: implicit declaration of function 'p116_record_failure'
  :463:29: error: 'P116_FAILURE_P80_RTP_FORWARD' undeclared (first use in this function)
  :463:59: error: implicit declaration of function 'p116_infer_phase'
  :906:29: error: 'P116_FAILURE_PSEUDOTCP_NOTIFY_PACKET' undeclared
  :983:25: error: 'P116_FAILURE_ABSOLUTE_SESSION_TIMEOUT' undeclared
  :983:64: error: 'P116_PHASE_STARTUP' undeclared
  :1217:29: error: 'P116_FAILURE_P12_STEP_TIMEOUT' undeclared
  :3171:17: error: implicit declaration of function 'p116_emit_timeout_observability'
  :3615:1: error: static declaration of 'p116_record_failure' follows non-static declaration
  :3625:1: error: static declaration of 'p116_emit_timeout_observability' follows non-static declaration
```

**Cause.** The R57 overlay emitted its typedefs, both enums and every helper at one late anchor (immediately after
`/* R54_CALL_ADOPTION_LISTENER_END */`, generated lines ~3474-3641) while the per-site instrumentation starts much
earlier: the earliest instrumented function is `p80_try_forward_wrapped_rtp` (first `failed = TRUE;` site at generated
line 463), then `recv_cb` 906, `absolute_timeout_cb` 983, `p12_stage_timeout_cb` 1217 and `r54_tx_wait_timeout_cb`
3171 — up to ~3200 lines before the overlay's own declarations. Everything must be declared before its first use, so
the candidate was not compilable at all. The generated text itself was well-formed and byte-deterministic; only a
whole-translation-unit compile could have caught it (see the new gate below).

**Recovery.** An earlier executor attempt had begun introducing an early anchor (`_EARLY_ANCHOR_BEFORE`) and died
mid-edit on account limits, leaving the transform half-patched. The orchestrator restored the transform to its last
working state and verified it regenerates deterministically to `db6bee61…` (the sha the failing build consumed);
the restored file contained no early anchor, so this turn applied the fix from that last working state.

**Fix — the overlay is split into declarations-early and definitions-late.** Moving the whole region early is not
possible without also moving state it cannot own: `p116_infer_phase()` reads `v4_listener_ready`,
`r42_media_stage` and `g_r54_tx_state` and switches on the R42/R54 enum constants (`R42_MEDIA_*`,
`R54_TX_STATE_*`), all of which are declared *after* line 463 in the generated file and live in previously accepted,
out-of-scope rounds (R42/R54/R55/R56 regions, the R56 scheduler and the frozen listener are all frozen for this
round).

- `R57_NATIVE_FAILURE_ATTRIBUTION_DECLS_BEGIN/END` — the two typedefs/enums and four `static` prototypes — is now
  emitted immediately before the pre-existing P80 media-forwarding state
  (`static gboolean p80_media_forwarding_enabled = FALSE;`, generated line 68), the same early anchor the P100
  compile-order corrective already uses for its own declaration-order fix. Declarations only: no file-scope state is
  defined there and no helper body appears there, so nothing in the early block depends on later code.
- `R57_NATIVE_FAILURE_ATTRIBUTION_BEGIN/END` — the three file-scope state objects and the five helper bodies,
  content-unchanged, stays at the late R54 anchor, where the R42/R54 state those bodies read is already declared.

The four prototypes are `static`, matching the `static` definitions exactly: because an implicit declaration counts as
non-static, that is precisely what removes the `static declaration … follows non-static declaration` half of the
defect. Generation-time gates enforce the contract and refuse to emit a bad candidate:
`R57_DECLARATION_ORDER_GATE` (every first use of `p116_record_failure(P116_FAILURE_…`,
`p116_emit_timeout_observability("…` and `p116_emit_native_exit_summary(failed)` must sit after `*_DECLS_END`),
`R57_EARLY_DECLARATION_GATE` (each required declaration is in the early block),
`R57_LATE_DUPLICATE_DECLARATION_GATE` / `R57_LATE_TYPEDEF_GATE` / `R57_DECLARATION_DUPLICATION_GATE` (nothing is
restated in the late block — a duplicated enumerator, or a typedef declared twice with different layout, would be a C
redeclaration error), and `R57_EARLY_ANCHOR_GATE` (the anchor must be present exactly once).

**Strictly additive observability, unchanged.** All 26 `failed = TRUE;` sites keep their own preceding
`p116_record_failure(P116_FAILURE_…)` call with first-fail-wins, and the terminal exit summary still runs immediately
before the single `return failed ? 6 : 0;`. The write surfaces on the corrected generated source are identical to the
pre-fix candidate: `p12_queue_bytes(` 3, `p12_queue_vip_frame(` 13, `pseudo_tcp_socket_send(` 3, `p12_flush_tx(` 22,
`r42_queue_media_channel_open(` 2 — no protocol, scheduler, timeout or Door semantics were touched by this corrective
(pinned by `test_protocol_write_surfaces_unchanged`).

### Whole-translation-unit compile gate (new)

`safety-poc/tests/test_p116_r57_whole_tu_compile_gate.py` (8 tests) closes the hole that let this defect through: it
regenerates the real candidate through the real transform and compiles the ENTIRE translation unit — all ~9.7k lines,
every function, not just the R57 region:

```
cc -std=gnu11 -fsyntax-only -Wall -Wextra \
   -Werror=implicit-function-declaration -Werror=implicit-int \
   -I safety-poc/tests/native/whole_tu_stub_include <generated>.c
```

**Mode: `fsyntax-only`** (stated explicitly, as required). The offline sandbox has no Alpine/musl `glib-2.0` +
libnice dev headers, so a full `cc -c` cannot run here; the stub headers at
`safety-poc/tests/native/whole_tu_stub_include/` (`glib.h`, `glib-unix.h`, `glib/gstdio.h`, `nice/agent.h`,
`nice/pseudotcp.h`) supply the declarations, and the orchestrator's musl container build remains the authoritative
full compile. `-fsyntax-only` is sufficient for this defect class because undeclared identifiers, implicit
declarations, conflicting redeclarations, static/non-static conflicts and use-before-declaration are all front-end
diagnostics emitted before code generation. `-Werror=implicit-function-declaration` / `-Werror=implicit-int` promote
GCC's implicit-declaration and implicit-int *warnings* to errors, so the gate cannot pass "by warning only".

**What it asserts.** Exit status 0 for the whole unit; zero `error:` diagnostic lines; and none of the
declaration-order diagnostics `implicit declaration` / `undeclared` / `conflicting types` / `static declaration of`.
Plus:

- negative control 1 — `test_gate_catches_the_original_declaration_order_defect`: the early declaration block is
  programmatically relocated back to the late R54 anchor, reproducing the first candidate's ordering; the gate must
  fail on it. On this host that control reproduces the orchestrator's musl build error-for-error at the same sites:
  `:463:9 implicit declaration of 'p116_record_failure'`, `:463:29 'P116_FAILURE_P80_RTP_FORWARD' undeclared`,
  `:463:59 implicit declaration of 'p116_infer_phase'`, `:906:29 'P116_FAILURE_PSEUDOTCP_NOTIFY_PACKET' undeclared`,
  `:983:25`/`:983:64 'P116_FAILURE_ABSOLUTE_SESSION_TIMEOUT'`/`'P116_PHASE_STARTUP' undeclared`,
  `:1217:29 'P116_FAILURE_P12_STEP_TIMEOUT' undeclared`, `:3171:17 implicit declaration of
  'p116_emit_timeout_observability'`, and `static declaration of 'p116_record_failure'` /
  `'p116_emit_timeout_observability' follows non-static declaration` — 11 errors, same functions, same classes.
- negative control 2 — `test_gate_catches_synthetic_use_before_declaration`: a minimal unit with a call before its
  declaration must fail, proving the mode rejects the class independently of this generator.
- non-vacuity — `test_gate_is_not_vacuous_about_the_stub_headers`: a probe including the stubbed `glib.h` must
  compile, so a green gate cannot be explained by silently-missing headers.
- regression pins — write-surface counts (3/13/3/22/2), 26 `failed = TRUE;` sites, declaration-before-use ordering,
  every declaration emitted exactly once, and byte-determinism across two generations.

If no C compiler exists at all (`cc`, then `gcc`, then `clang`), these gate tests `skipTest` with an explicit message
rather than passing silently — recorded here so a skip is never mistaken for a green gate. On this host `cc` is
present (GCC 13.3.0, host glibc toolchain, `-std=gnu11`) and the full gate ran: corrected unit `rc=0`, both control
units `rc=1`. The single diagnostic the stub build still prints on the corrected unit is a
stub artifact — `g_checksum_get_string()` is declared `gpointer` in the stub and used as a `%s` argument in the
pre-existing `V4_RX_ECHO_SHA256` print — and cannot occur in the real musl build, where the real glib prototype is
used; the stub-mode warning count is therefore not comparable to the musl warning count.

**Expected orchestrator build after this corrective** (the gate's own prediction, to be confirmed by the musl rerun):
`BUILD_RC=0`, `BUILD_WARNINGS_TOTAL=3` (`R35_SECOND_OPEN_FORBIDDEN_STATES`, `p116_print_final_rtp_summary`,
`pseudotcp_success_quit_cb`), `BUILD_WARNINGS_NEW=0`.

**CLI note.** The transform CLI now also accepts `--source`/`--output` (mirroring
`ct122_build_p116_r54_call_adoption_candidate.sh`'s use of the R54 transform), so the candidate can be regenerated
directly; `--report` and `--sha256` behave as before.

## No live action

This round performed no deploy, no HA restart/reload, no physical ring, no self-activation, no Door/Gate action,
no Comelit network transmission, no ADB/ptrace, and no execution of the native binary — proprietary or
generated — against the real Comelit panel or hub. All analysis is static (reading the evidence bundle and
generated source) or executed against a host-compiled (`cc`, not musl) synthetic harness with fabricated state,
never against real protocol traffic.

## Verification

- Native focused suite: `cd safety-poc && PYTHONPATH=$PWD/src PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_p116_r57_native_failure_attribution -v` → 14 tests, OK (includes a compiled-and-executed fault-injection matrix: 10 scenarios, all `PASS`).
- New integration-plumbing suite (CORRECTIVE turn 2): `python3 -m unittest tests.test_p116_r57_integration_marker_plumbing -v` → 17 tests, OK.
- R42b/R53/R54(+R56)/R55 regression: `python3 -m unittest tests.test_p116_r42b_canary_observability tests.test_p116_r53_call_adoption_protocol_profile tests.test_p116_r54_call_adoption_production_candidate tests.test_p116_r55_post_canary_failure_forensic -v` → 103 tests, OK.
- Canonical full offline suite from `safety-poc/`: `PYTHONPATH=$PWD/src PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests` → Ran 2087 tests; OK (skipped=1) — 17 more than the turn-1 count of 2070, matching exactly the new integration-plumbing test count; no test removed.
- Static safety: `python3 -m py_compile` on `custom_components/comelit/runtime.py`, `custom_components/comelit/media_diagnostics.py` (unmodified, compiled to confirm no accidental edit broke it), the R57 transform module, and both R57 test modules → PASS.
- `NATIVE_TRANSFORM_SHA256` reproduced identically (`db6bee616fb3a0abc1fb7e98dce2157b9e46bc22b62ef8bb9116e287744d5552`) both before and after this turn's changes, and from three different invocation cwds (repo root, `safety-poc/`, `/tmp`) after the CLI fix — confirms the native side is untouched and the cwd fix works.
- `git diff --check` → clean; only `custom_components/comelit/runtime.py` modified (integration plumbing), plus the turn-1 untracked files and one new untracked test file.
- Forbidden-substring scan (tokens/secrets/IPs) on the modified/new files → clean (the only `secret` hits are the pre-existing `_prepare_helper_secret`/`_remove_helper_secret` function names, unrelated to this turn).
- The R57 observability region was additionally syntax-checked standalone with `gcc -std=c11 -Wall -Wextra
  -fsyntax-only` against minimal type stubs → no warnings, no errors.

### Corrective turn 3 (declaration order + whole-TU gate)

- Focused suite: `python3 -m unittest tests.test_p116_r57_native_failure_attribution
  tests.test_p116_r57_whole_tu_compile_gate tests.test_p116_r57_integration_marker_plumbing -v` → **Ran 41 tests,
  OK** (16 native attribution incl. the 2 new declaration-order tests, 8 whole-TU gate, 17 integration plumbing).
  Nothing was weakened: the only edit to a pre-existing assertion is the integration module's pinned native-transform
  hash, which moved from `db6bee61…` (broken candidate) to `fbd6137a…` (corrected candidate) — the pin's purpose.
- Regression bundle (R42b canary observability / R42b capabilities diag / R42b attach-failure reason / R53 / R54(+R56
  invariants) / R55 / P100 compile order): → **Ran 109 tests, OK**.
- Canonical full offline suite from `safety-poc/` (`bash scripts/run_offline_suite.sh`) → `STATIC_SAFETY_CHECK=PASS`,
  **Ran 2097 tests, OK (skipped=1)**, `OFFLINE_SUITE=PASS`, script exit 0 — 10 more than the turn-2 count of 2087
  (2 new declaration-order tests + 8 new whole-TU gate tests); no test removed.
- Whole-TU compile gate on the corrected candidate: `cc -std=gnu11 -fsyntax-only -Wall -Wextra
  -Werror=implicit-function-declaration -Werror=implicit-int -I safety-poc/tests/native/whole_tu_stub_include` →
  `rc=0`; the same command on the reproduced pre-fix ordering → `rc=1` with the orchestrator's exact 11 musl errors.
- Corrected generated source determinism: `fbd6137a5bb8b0f7258bfe69d72481c70272645aae0d4c0f0dff8c66d0b2237c` from
  two independent `transform()` calls, two independent CLI invocations (`--output`), with `cmp` byte-equal.
- Frozen source unchanged (`5827d9fd…`), `git diff --check` clean, no other tracked file modified (`runtime.py` is
  the previously accepted integration-plumbing change from turn 2, untouched by this turn).

As with prior rounds, a sandbox run is not the authoritative gate; the orchestrator's independent host rerun is.
