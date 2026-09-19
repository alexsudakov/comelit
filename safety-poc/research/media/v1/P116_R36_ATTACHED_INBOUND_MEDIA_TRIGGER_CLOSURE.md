# P116 R36 Attached Inbound Media Trigger Closure

FACTS

R36 base is the exact R35 head `2073fae95dfe381f1533ee49279905d3df5bcdb8`. No R32, R33, R34, or R35 file was modified by this round. No file under `custom_components/**`, no existing `P116_*.md` document, and no existing test/transform/serializer file was read for modification or written to. This round proceeded in two turns. Turn 1 added this document and `safety-poc/tests/test_p116_r36_attached_media_trigger.py`, recovering the native OPEN-gate mechanism precisely (SECTION 1/2) but leaving the exact CTP wire opcode for the trigger event only DERIVED by pattern, not independently confirmed, and therefore left the trigger `UNPROVEN` and added no overlay. Turn 2 is a bounded corrective: the orchestrator independently reproduced every turn-1 citation (CONFIRMED) and supplied NEW evidence — an independent, executable public CTP client implementation already staged as `.r33-evidence/public-vip/viper/{ctp.py,call.py}` — that confirms the wire opcode and body layout turn 1 had only derived. SECTION 4 below re-rules on that evidence; SECTION 6 adds the overlay this closes: `safety-poc/research/media/v1/entrance_p116_r36_attached_media_trigger_transform.py`, `safety-poc/tests/native/p116_r36_attached_media_trigger_host_harness.c`, `safety-poc/research/media/v1/ct123_build_p116_r36_attached_media_trigger_candidate.sh`, and the extended `safety-poc/tests/test_p116_r36_attached_media_trigger.py`. R36 is an offline OFFLINE_ONLY research round throughout both turns: no listener was run against a live device, no packet was transmitted on the Comelit network, no Door/Gate action occurred, no physical or synthetic ring occurred, no Home Assistant reload/restart occurred, no new packet capture was made, and neither the R35 nor the R36 candidate binary was ever executed (`candidate_executed=false`, verified by `readelf`/`strings`/`sha256sum`/`cmp` only).

EXECUTOR PROVENANCE

This round was executed by Claude Code CLI (model `claude-sonnet-5`) acting as substitute semantic implementation executor because Codex CLI, the usual executor for this repository, is blocked by its ChatGPT usage limit (resets 2026-09-20 16:57). The operator explicitly re-authorized Claude Code CLI as the substitute executor for this OFFLINE research task under the SAME prohibitions as every prior R3x round (no live invocation, no new capture, no production file, no protocol invention). Hermes (the orchestrator) owns git (add/commit/push remain outside this executor's actions), independently re-ran and reproduced every turn-1 citation, supplied the turn-2 public-vip evidence, and independently re-ran the verification and build commands shown below. All four R36 artifacts are research-only: no production file, native production binary, or normative document was touched.

## SECTION 1 — CHILD 1: INIT → IDLE → ALERTING CONTROL FLOW

Evidence: `.r33-evidence/native-disasm/disasm-VipUnitImpl_new_call_ctp_conn.txt`, `disasm-VipUnitImpl_handleCtpStart.txt`, `disasm3-CallFsm__initNewConnectionStart_unsigned_short__csp_msgbuf__.txt`, `disasm-CallFsm_st_idle.txt`, `disasm-CallFsm_go_in_alerting.txt`, `disasm-CallFsm_st_in_alerting.txt`.

**(1) What happens right after `initNewConnectionStart`.** `VipUnitImpl::handleCtpStart` allocates a `CallFsm`, calls `CallFsm::init()`, then calls `CallFsm::initNewConnectionStart(connId, msgbuf)` (`disasm-VipUnitImpl_handleCtpStart.txt:93-104`, `bl ec8f0 <CallFsm::initNewConnectionStart(...)@plt>` at line 103). For the default (non-`'F'`, non-`'R'` subtype) inbound-ring case, `initNewConnectionStart` itself: (a) copies caller/callee logical addresses (`disasm3-...initNewConnectionStart....txt:98-105`), (b) sends `csp_send_capab_report` — an OUTBOUND wire frame carrying this device's own `flags@840` state (`disasm3-...initNewConnectionStart....txt:109-111`), (c) sends `csp_send_alerting` — a second OUTBOUND wire frame telling the caller "ringing" (`disasm3-...initNewConnectionStart....txt:112-114`), then (d) self-enqueues a LOCAL FSM event `0x901` on the CallFsm's own event queue via `evq_add` (`disasm3-...initNewConnectionStart....txt:134-139`, `mov w1, #0x901`). Function returns `0`.

**(2) Which event drives idle → incoming alerting.** The self-posted local event `0x901`, not a wire-received event. `CallFsm::st_idle()` dispatches on it: `and w8,w0,#0xff00; cmp w8,#0xa00; b.ne ...` (`disasm-CallFsm_st_idle.txt:20-23`) routes local (non-`0xa00`-group) events to the low path, then `cmp w2,#0x901; b.eq 6b0d8` (`disasm-CallFsm_st_idle.txt:30-31`). At `6b0d8` it reads `cfg->byte18` (call-type discriminator, `'I'`=0x49 for intercom) and `this->byte104` (call subtype, stamped from the START message by `initNewConnectionStart`): if subtype `'R'` (0x52) it calls `go_connected()` directly (self-activation-style immediate connect, no ring); otherwise it calls `CallFsm::go_in_alerting()` (`disasm-CallFsm_st_idle.txt:40-46,136-140`).

**(3) Where that event originates.** From inside the SAME call — `initNewConnectionStart`'s own `evq_add` call, not from any external producer, network callback, or timer.

**(4) Whether a second wire frame is required (for the ALERTING transition itself).** No. `go_in_alerting()` is reached purely from the self-posted `0x901` event; no additional wire frame is read before it runs.

**(5) Whether a timer/main-loop dispatch is required.** `evq_add`/`evq_next` are a local FIFO drained by the FSM's own run loop; the self-posted event is processed in the FSM's ordinary event-dispatch cycle immediately following `initNewConnectionStart`'s return (same call stack that started with `new_call_ctp_conn`'s `csp_recv`), not gated behind any additional external timer.

**(6) Whether the transition is inevitable for an incoming video-capable call.** Yes for the default subtype (proven above): every valid inbound START (`action==1`, `disasm3-...initNewConnectionStart....txt:16-18`) that is neither subtype `'F'` (rejected/released, `disasm3-...initNewConnectionStart....txt:66-93`) nor subtype `'R'` (immediate connect) reaches `go_in_alerting()` deterministically.

**(7) Whether `start_videorx` can run in the same logical transaction cycle as CALL_INIT.** `go_in_alerting()` itself calls `start_videorx(1)` only if a gate holds (SECTION 2). That gate (`this->flags100` bit 3) is unconditionally zeroed by `initNewConnectionStart` (`disasm3-...initNewConnectionStart....txt:30`, `str wzr,[x0,#100]`) and is not written anywhere else in `initNewConnectionStart`. **Therefore for a virgin inbound call, `start_videorx` cannot fire inside the same CALL_INIT cycle that produced `go_in_alerting()`** — SECTION 3 shows what later event supplies that bit.

**Preview vs. answered-call distinction (re-derived, not assumed).** `go_connected()` — the transition that marks the call answered — is reached from two places only: (a) the `st_idle` subtype-`'R'` immediate-connect shortcut (self-activation-like, bypasses ringing entirely and is out of scope for a normal ring), and (b) a `st_in_alerting` branch that sends `csp_send_voicestatus`/`csp_send_connect` (`disasm-CallFsm_st_in_alerting.txt:428-449`). The capability-report-driven `start_videorx` branch traced in SECTION 3 (`disasm-CallFsm_st_in_alerting.txt:200-245`) ends at the common event-dispatch exit (`b 6bea4`, line 245) and **does not call `go_connected()`**. This is native-library-level confirmation of R28's client-library-level finding (`P116_R28_LISTENER_ATTACHED_INBOUND_MEDIA_ANALYSIS.md:127-128`, `PREVIEW_ANSWERS_CALL=false`/`PREVIEW_CAN_RUN_WHILE_RINGING=true`, originally proven only from decompiled Android `CallManager.java`): video RX start and call-answer are independent FSM transitions at the native layer too, and the video-start path runs while the call is still `st_in_alerting` (ringing), not after `go_connected()`.

`ALERTING_TRANSITION_TRIGGER=INITIAL_CALL_START_INTERNAL` (evidence label: `PROVEN_STATIC`).
`SECOND_WIRE_FRAME_REQUIRED=true` for `start_videorx` specifically (not for entering the alerting/ringing state) — see SECTION 3.

## SECTION 2 — CHILD 2: EXACT `start_videorx` GUARDS

Evidence: `.r33-evidence/native-disasm/disasm-CallFsm_go_in_alerting.txt:25-45`, `disasm-CallFsm_st_in_alerting.txt:200-245`, `disasm-CallFsm_start_videorx.txt` (full file).

| NAME | SOURCE | WHEN_SET | HELPER_VISIBLE | R35_ALREADY_CAPTURES |
|---|---|---|---|---|
| tunnel-busy (media-manager `+136` bit0) | `ldr x8,[x19,#24]; ldrb w10,[x8,#136]` — a media-manager/tunnel object distinct from `CallFsm`, `disasm-CallFsm_go_in_alerting.txt:25,28` | native runtime tunnel state, not visible in any wire message | `UNPROVEN` (no wire representation found) | `false` |
| video-requested (`CallFsm+100` bit3, "`flags100`") | `ldr w8,[x19,#100]`, `disasm-CallFsm_go_in_alerting.txt:29`; gate at `disasm-CallFsm_go_in_alerting.txt:32` and re-checked at `disasm-CallFsm_st_in_alerting.txt:233,235` | zeroed by `initNewConnectionStart` (`disasm3-...initNewConnectionStart....txt:30`); overwritten wholesale by the received CAPABILITY_REPORT handler, `str w8,[x5,#100]!` at `disasm-CallFsm_st_in_alerting.txt:215` (event `0xa03`) and identically at the standalone `CallFsm::handle_capability_report` (`full-disasm-libvipcomelit.txt:11025`) | `PARTIAL` — see SECTION 3 | `false` |
| call-active (`CallFsm+113`) | `ldrb w8,[x19,#113]`, `disasm-CallFsm_go_in_alerting.txt:33` and `disasm-CallFsm_st_in_alerting.txt:236` | set to `1` unconditionally for any valid START (`disasm3-...initNewConnectionStart....txt:22`) | `true` (always true after CALL_INIT for a valid call) | `true` (R35 already gates on a valid captured call) |
| cfg capability threshold (`cfg->+16 <= 0x35`) | `ldr x8,[x19,#824]; ldrh w8,[x8,#16]`, `disasm-CallFsm_go_in_alerting.txt:35-38` and `disasm-CallFsm_st_in_alerting.txt:238-241` | static per-device config, loaded once at CALL_INIT time (`cfg` pointer is available from `CallFsm` construction) | `UNPROVEN` (local device config, no known wire representation; likely a fixed per-firmware constant) | `false` |
| tunnel-vs-address selector (`CallFsm+840` bit2) | `ldrb w8,[x0,#840]; tbnz w8,#2,...`, `disasm-CallFsm_start_videorx.txt:19-20` | native tunnel-availability state | `UNPROVEN` | `false` (R35 always builds the TUNNEL form) |
| profile-selector (`CallFsm+812`) | `ldrb w9,[x20,#812]`, `disasm-CallFsm_start_videorx.txt:93` (ADDRESS-form flags composition only) | native call/profile config | `UNPROVEN` | `false` |
| `start_arg` bit0/bit1 (tunnel-form selector / video-request echo) | literal `1` at every call site reached from a virgin ring (`disasm-CallFsm_go_in_alerting.txt:40`, `disasm-CallFsm_st_in_alerting.txt:243`); derived from tunnel-busy at `disasm-CallFsm_st_in_alerting.txt:451,553` for other branches | compiled-in constant per call site, or derived from the SAME tunnel-busy bit already listed above | `false` (not derived from any wire field) | `true` (R35's `r35_open_flags` reproduces the resulting bit3 derivation byte-exact against the R34 oracle) |

`start_videorx`'s own body (`disasm-CallFsm_start_videorx.txt`) then: computes the TUNNEL-form flags byte as base `0x32` with bit3 re-derived from `start_arg>>1` (`disasm-CallFsm_start_videorx.txt:59-65`, `bfi w2,w12,#3,#1`) or the ADDRESS-form flags byte as base `0x30` composed with the bit2 profile-selector and bit3 from `start_arg` (`disasm-CallFsm_start_videorx.txt:96-103`) — this is **byte-identical** to the derivation already ported offline as R34's `open_flags`/R35's `r35_open_flags` (`P116_R35_ATTACHED_INBOUND_MEDIA_RESEARCH_HELPER.md:13`), independently confirming that prior port against fresh native disassembly.

**Can R35 build a correct OPEN using only data available in the CALL_INIT branch?** No. The video-requested gate (`flags100` bit3) is provably zero at CALL_INIT time and is not set by any code inside `initNewConnectionStart`; it is written only by the CAPABILITY_REPORT handler processing a later, distinct wire event (SECTION 3). All other guards (call-active, cfg threshold, tunnel-busy, profile-selector) are either already true unconditionally after a valid CALL_INIT or are local device/runtime state not carried by the CALL_INIT frame itself, so they do not change this answer.

`START_VIDEO_RX_GUARDS=PROVEN` (all guards enumerated with citations; the one that gates whether OPEN is even attempted is fully traced to its source).
`ALL_OPEN_FIELD_SOURCES_AVAILABLE_AT_CALL_INIT=false`.

## SECTION 3 — CHILD 3: WIRE/TIMING CORRELATION (existing evidence only)

Searched: `research/media/v1/P116_R2*`, `P116_R3*` docs, `entrance_self_activation_capture.json`, and a repository-wide search for `*.pcap*`/`*capture*` artifacts (`find . -iname "*.pcap*" -o -iname "*capture*"`). No packet capture or capture-derived artifact in this repository contains a decoded frame for the CALL_INIT→ALERTING follow-up traffic on an attached-media inbound call; `entrance_self_activation_capture.json` and its verifier (`entrance_p78_capture_verifier.py`) cover the unrelated older self-activation `0x001A` lineage, not the native `CallFsm` call-bound path. R29A's own "Observational Live Plan" (`P116_R29A_INBOUND_MEDIA_WIRE_CONTRACT.md:279-309`) lists the exact missing facts this round's native disassembly now partially answers (SECTION 4), but that plan was never executed (`R29_READY_FOR_ORIGINAL_LIVE=false`, `LIVE_RUN=NOT_RUN`), and R36 is prohibited from executing it or capturing new traffic.

Requested timeline (`CALL_START`, `ALERTING_EVENT`, `MEDIA_RX_LOCAL_OPEN`, `MEDIAREQ26_OPEN`, `CHANNEL_OPEN_RESPONSE`, `FIRST_RTP`): **UNPROVEN**. Reason: no existing wire capture of an attached-media inbound call exists on disk to correlate these points; the ordering established this round (SECTION 1/3) is a native code-flow ordering (CALL_INIT → self-posted `0x901` → `go_in_alerting` → later received CAPABILITY_REPORT event `0xa03` → `start_videorx` → local RX setup → `csp_send_mediareq26`), not a timestamped wire trace. R29A already separately proved, from disassembly alone, that `start_videorx`'s `mediareq26` emission does not wait for `ViperTunnel::onChannelOpenRes` (`P116_R29A_INBOUND_MEDIA_WIRE_CONTRACT.md:152-154,163-167`); this round found no staged evidence to add to that. Exact capture needed to close this: a legitimate, already-authorized live inbound ring with full CTP traffic capture on the call-bound connection, timestamped against local RTP arrival — explicitly out of scope for this offline round.

## SECTION 4 — CHILD 4: HELPER-OBSERVABLE TRIGGER (RE-RULED, TURN 2)

Turn 1 recorded the native mechanism as `PROVEN_STATIC` but its wire-level signature as `PARTIAL/derived` — internally consistent by pattern, but not independently confirmed, because no packet capture of the attached-media follow-up traffic exists on disk (SECTION 3). The orchestrator independently reproduced every turn-1 citation (CONFIRMED, listed verbatim in the turn-2 task) and supplied the missing confirmation: an independent, executable public CTP client implementation, already staged read-only evidence in this worktree (never committed to this repository) at `.r33-evidence/public-vip/viper/ctp.py` and `.r33-evidence/public-vip/viper/call.py`.

**The native mechanism (unchanged from turn 1, PROVEN_STATIC).** `CallFsm::st_in_alerting()` dispatches wire-received event `0xa03` (`disasm-CallFsm_st_in_alerting.txt:22-24,115-116`) to a handler that stores the received message's offset-4 payload word verbatim into `this->flags100` (`str w8,[x5,#100]!`, `disasm-CallFsm_st_in_alerting.txt:213-215`), then calls `start_videorx(1)` iff bit 3 of that word is set and the tunnel-busy/call-active/cfg-threshold guards hold (`disasm-CallFsm_st_in_alerting.txt:231-244`). See SECTION 1/2 for the full trace.

**The wire-level signature (turn 2: CONFIRMED, not merely derived).** `.r33-evidence/public-vip/viper/ctp.py:28` pins `OP_CAPABILITIES = 0x0003` in the SAME opcode table as the already-pinned `OP_INVITE = 0x0001` and `OP_MEDIA_REQUEST = 0x0011` — the exact value turn 1 had only derived by pattern (`0xa00 | opcode_low_byte` applied to the FSM event `0xa03`). `.r33-evidence/public-vip/viper/call.py:43` gives the exact byte layout: `_CAPABILITIES = bytes.fromhex("00 03 49 00 27 00 00 00")` — opcode `0x0003` at bytes 0-1, a call-type byte `0x49` (`'I'`) at byte 2 matching the native call-type byte this round's SECTION 1 already cited, and the capability word at bytes 4-7 — exactly the offset the native `str w8,[x5,#100]!` handler reads (`ldr w2,[x20,#4]` equivalent). `call.py:120-128` shows this is sent as a plain CTP `FLAG_DATA` frame on the call connection (`await conn.send(_CAPABILITIES, FLAG_DATA)`) and that the library explicitly waits for the peer's own reply on the same opcode (`await conn.wait(opcode=OP_CAPABILITIES, timeout=timeout)`) before proceeding — independently confirming this is a genuine, real, bidirectional CTP exchange on the call-bound connection, not a native-library-internal artifact.

This closes the one gap turn 1 left open: native sender (this round's disassembly), independent public receiver/opcode table (`ctp.py`), and independent public body layout (`call.py`) all agree, and the payload offset matches the native handler exactly. The wire-level discriminator is no longer a derivation; it is confirmed by an independent, executable implementation.

**The one residual question, and why it does not block the offline overlay.** The public sample's own outbound capability word is `0x27` (`0b0010_0111`) — bit 3 (`0x08`) is CLEAR in that specific sample. This is the ONE thing this evidence cannot settle: whether a real entrance panel's OWN capabilities reply sets bit 3. That is a **live-behaviour question** (what does actual hardware send), not a wire-contract unknown (what does the protocol look like, where is the field, what does bit 3 mean when set — all now confirmed/traced). An offline overlay's job is to correctly PARSE and GATE on this already-confirmed field; it does not need to know in advance what value real hardware will send, any more than R35's already-accepted OPEN/STOP serializers needed to know in advance what a real peer would do with the packets they build. Per the task's own ruling framework, this residual uncertainty does not block CHILD 6.

`HELPER_OBSERVABLE_MEDIA_START_TRIGGER=true`.
`HELPER_TRIGGER_KIND=FOLLOWUP_CTP_EVENT`.

## SECTION 5 — CHILD 5: STOP TRIGGER (RE-RULED, TURN 2)

Evidence: `.r33-evidence/native-disasm/disasm-CallFsm_stop_videorx.txt`, `disasm-CallFsm_st_in_alerting.txt` (event `0xb0e`/hangup teardown block, lines 338-457 and 496-521), R35's STOP mechanics (`P116_R35_ATTACHED_INBOUND_MEDIA_RESEARCH_HELPER.md` SECTION 4/6, still unedited this round).

**PROTOCOL stop triggers (native, receiver-observed).** `stop_videorx()` is called from call-teardown (`0xb0e` RELEASE/hangup, `disasm-CallFsm_st_in_alerting.txt:503-521`) and from the same capability-report re-evaluation path when a later CAPABILITY_REPORT clears `flags100` bit 3. `.r33-evidence/public-vip/viper/ctp.py:30` additionally confirms a wire opcode for call release, `OP_RELEASE = 0x000E`, which by the same now-confirmed `0xa00 | opcode_low_byte` pattern predicts FSM event `0xa0e` — matching this round's own disassembly finding of a `handle_csp_release`-class handler dispatched at exactly `cmp w2,#0xa0e` (`disasm-CallFsm_st_in_alerting.txt:117-118,193-198`). R36 does **not** wire either of these as an automatic STOP this round: SECTION 6 wires the OPEN trigger only, and a native-mirroring auto-stop on RELEASE would be new scope beyond what this corrective turn asked for. It is recorded here as a well-evidenced candidate for a future round, not implemented now.

**HA/user-policy stop trigger — re-examined per the orchestrator's explicit instruction.** Turn 1 marked this `PROVEN`, reasoning from R35's OFFLINE-proven state-machine correctness (`r35_send_stop`'s ordering/idempotency/byte-exact serialization, all demonstrated by R35's own host harness with a FAKE writer). That reasoning conflates two different claims. What R35 actually proved: `r35_send_stop`, once called, behaves correctly (exactly-one-STOP, STOP-before-disposal, byte-exact body) — an OFFLINE MECHANISM proof, never exercised against a real socket. What neither R35 nor this round's SECTION 6 overlay establishes: an actual, real, invocable call site for a "bounded timer" or "operator action" anywhere in the candidate. `entrance_p116_r35_attached_media_native_transform.py` and the new `entrance_p116_r36_attached_media_trigger_transform.py` both contain zero `g_timeout_add`/retry constructs by design (R35's `_assert_gates` and this round's own `_assert_gates` both actively forbid it, `entrance_p116_r36_attached_media_trigger_transform.py` gate `R36_NO_RETRY_GATE`), and neither wires any operator-facing control. So "operator/bounded-timer STOP" describes a mechanism whose INTERNAL correctness is proven and whose EXTERNAL trigger does not yet exist in the candidate — precisely the same class of gap SECTION 4 closed for OPEN, just not yet closed for STOP.

`HELPER_OBSERVABLE_MEDIA_STOP_TRIGGER=true` (the operator/bounded-timer concept is a sound, helper-observable trigger in principle, and R35's `r35_send_stop` remains reachable and correct when called).
`FIRST_LIVE_STOP_MODEL=PARTIAL` — missing piece named: no real bounded-timer or operator-invocable call site for `r35_send_stop` exists anywhere in the candidate; only its internal ordering/idempotency/serialization correctness is offline-proven (R35's host harness), not a live invocation path. Closing this to `PROVEN` requires a future round to wire an actual bounded trigger (an explicit external control point, not a native-mirroring auto-stop, to keep operator control over when RX tears down) and re-run R35/R36's harnesses against it.

## SECTION 6 — CHILD 6: OFFLINE R36 AUTOMATIC-OPEN-TRIGGER OVERLAY — ADDED

CHILD 6 now applies: SECTION 4 names a trigger point that is PROVEN on both axes required (native mechanism AND wire-level signature), with only a live-behaviour question (not a protocol unknown) left open. Three new files implement it, none of which edit any R35/R34/R33 file or the canonical generator:

- **`safety-poc/research/media/v1/entrance_p116_r36_attached_media_trigger_transform.py`** — a NEW overlay `transform(r35_source)` applied strictly on top of the R35-augmented candidate (raises if the input is not already R35-augmented, and raises on re-application — the same idempotency discipline R35 uses). It inserts two regions:
  - A dependency-free trigger-core region (`R36_ATTACHED_MEDIA_TRIGGER_BEGIN`/`_END`, no GLib/libnice/printf, verified by `_assert_gates`) with exactly two decision functions and one action function: `r36_is_capabilities_for_current_call` (fail-closed on wrong CTP flag, wrong opcode, too-short body, no live call via `r35_call_ready`, or a connection that does not match the session's captured call after the SAME direction transform `r35_capture_call_ctp_id` already applies — this is what makes stale/prior-call and registration-handle frames fail closed); `r36_capabilities_video_requested` (tests bit 3 of the confirmed capability word); and `r36_trigger_open_from_capabilities`, which calls R35's own `r35_allocate_media_rx_channel`, `r35_send_open`, and `r35_enable_rtp` in sequence and defines no new writer, serializer, or channel-allocation rule (`_assert_gates` fails the build if a duplicate writer symbol appears in this region).
  - One wiring insertion (`R36_WIRING_TRIGGER_BEGIN`/`_END`) in the SAME generic per-frame receive loop R35 already hooked for CALL_INIT capture, anchored on the existing "Other CTPP traffic" fallback comment (stable text, untouched by R35's own edit) so a matching CAPABILITIES frame is recognized — printing only the bounded markers `R36_CAPABILITIES_OBSERVED=true`/`R36_TRIGGER_RESULT=OPEN_SENT|REJECTED` — instead of falling through to the generic prefix/action log line.
  - `r35_send_stop` is never called by either new region (`_assert_gates` gate `R36_STOP_MUST_STAY_EXPLICIT_GATE`): STOP remains reachable only by explicit call, per SECTION 5.
  - `media_channel_id` is not a proven native field (SECTION 2, unchanged): the trigger reuses the session's own call connection id as a stable, real, already-unique-per-call local reference rather than inventing a network value, and the code comment says so explicitly; `max_rtp_payload`/`channel_profile_word`/`profile_selector` remain zero, UNPROVEN local fields, unchanged by this round.
- **`safety-poc/tests/native/p116_r36_attached_media_trigger_host_harness.c`** — combined with R35's extracted core region and R36's extracted trigger-core region, compiles with `cc -std=c99 -Wall -Wextra -pedantic` at zero warnings and drives all nine required scenarios plus one extra (bit3-clear does not trigger), all against a fake writer/RTP-arm hook (no socket, no fork, no Door/Gate):

  | # | Scenario | Marker | Result |
  |---|---|---|---|
  | 1 | pre-trigger | `R36_SCENARIO_1_PRE_TRIGGER` | PASS — `open_count=0` before any capabilities event |
  | 2 | exact trigger | `R36_SCENARIO_2_EXACT_TRIGGER` | PASS — `open_count=1`, RTP armed exactly once |
  | 3 | duplicate trigger | `R36_SCENARIO_3_DUPLICATE_TRIGGER` | PASS — second matching event rejected by R35's own `open_sent` gate, `open_count` stays 1 |
  | 4 | stale/prior call | `R36_SCENARIO_4_STALE_PRIOR_CALL` | PASS — a capabilities frame carrying an OLDER captured call's connection is rejected by the connection-match guard, `open_count=0` |
  | 5 | registration-handle misuse | `R36_SCENARIO_5_REGISTRATION_HANDLE_MISUSE` | PASS — capture itself fails closed (R35's own rule) when the derived connection equals the outer handle, so no live call ever exists to trigger on |
  | 6 | STOP before OPEN | `R36_SCENARIO_6_STOP_BEFORE_OPEN` | PASS — R35's own `R35_ERR_STOP_BEFORE_OPEN` gate, unchanged |
  | 7 | one valid STOP | `R36_SCENARIO_7_ONE_VALID_STOP` | PASS — `stop_count=1` after an explicit `r35_send_stop` call following a trigger-produced OPEN |
  | 8 | duplicate STOP | `R36_SCENARIO_8_DUPLICATE_STOP` | PASS — rejected, no second write |
  | 9 | terminal call | `R36_SCENARIO_9_TERMINAL_CALL_REJECTED` | PASS — after `r35_teardown_call`, `r35_call_ready` fails, the guard rejects the frame outright |

  Plus `R36_CHECK_BIT3_CLEAR_DOES_NOT_TRIGGER=PASS` (the public sample's own observed word, `0x27`, correctly does not trigger — SECTION 4's residual question stays honestly visible in the test, not silently assumed away) and `R36_NETWORK_TX=0`/`R36_DOOR_ACTIONS=0`/`R36_GATE_ACTIONS=0`.
- **`safety-poc/research/media/v1/ct123_build_p116_r36_attached_media_trigger_candidate.sh`** — extends the R35 build lane with a third pipeline stage (canonical → R35 overlay → R36 overlay), same Alpine 3.24.1 / musl / `--network none` / local APK closure recipe as `ct122`, run this round (raw gates in VERIFICATION below); build root `/home/hermes/comelit-r36-build-<timestamp>/`, outside the repository tree.
- **`safety-poc/tests/test_p116_r36_attached_media_trigger.py`** — rewritten to test this overlay: transform reproducibility/idempotency, digest invariance of the canonical and R35 stages, the confirmed-opcode arithmetic pin, and every harness scenario above via subprocess-compiled markers, plus the fail-closed properties that still apply (R35's own file is untouched and still shows zero automatic callers; `r35_send_stop` still shows zero automatic callers anywhere in the R36 candidate).

Bounded observability markers actually emitted (values only, never a call id, channel id, IP, token, SDP, or payload byte): `R36_CAPABILITIES_OBSERVED=true`, `R36_TRIGGER_RESULT=OPEN_SENT|REJECTED` (wiring); `CALL_BOUND_MEDIA_OPEN_SENT_COUNT`, `CALL_BOUND_MEDIA_STOP_SENT_COUNT` (harness). The remaining turn-1-contract markers (`ATTACHED_RTP_ARMED`, `VIDEO_RTP_COUNT`, etc.) describe live-only observability and are correctly not exercised offline this round; nothing in this overlay performs network I/O.

`AUTOMATIC_OPEN_TRIGGER_WIRED=true`.
`AUTOMATIC_STOP_TRIGGER_WIRED=false` (unchanged: STOP remains explicit-invocation-only, per SECTION 5's finding that its live trigger point is not yet proven).
`BUILD_GATES=PASS` (raw gate block in VERIFICATION).

## SECTION 7 — CHILD 7: LIVE-READINESS DECISION

| Condition | Status this round |
|---|---|
| Helper-observable OPEN trigger PROVEN | YES — `true` (SECTION 4) |
| All OPEN field sources available | NO — `ALL_OPEN_FIELD_SOURCES_AVAILABLE_AT_CALL_INIT=false` (SECTION 2, unchanged: cfg threshold, tunnel-busy, profile-selector, max RTP payload, and the local media-channel identity remain unproven local/runtime fields) |
| One-OPEN gate demonstrated offline | YES — harness scenarios 1-3, this round |
| Bounded STOP trigger/model PROVEN | NO — `FIRST_LIVE_STOP_MODEL=PARTIAL` (SECTION 5): mechanism proven, live invocation path not yet wired |
| One-STOP gate demonstrated offline | YES — harness scenarios 6-8, this round (mechanism only, not live trigger) |
| Call/listener preservation model intact | Inherited from R35 (`MODELED`, not independently re-verified this round since no listener ran) |
| No new ICE/cloud/PseudoTCP/registration | Unchanged: `NEW_ICE=0`, `NEW_CLOUD=0`, `NEW_PSEUDOTCP=0`, `NEW_REGISTRATION=0` |
| Candidate builds reproducibly | YES — `ct123` this round, all gates PASS (VERIFICATION) |
| Candidate NOT executed | Unchanged: `candidate_executed=false` |

Two required conditions remain unmet (full OPEN field-sourcing, and a live-invocable bounded STOP). `IMPLEMENTATION_READY_FOR_BOUNDED_LIVE=false` — the trigger gap this round set out to close IS closed, but live readiness requires every row above, and it does not lower the bar to reach `true` prematurely.

## VERIFICATION

Commands run in this worktree (`safety-poc/` as working directory unless noted):

```bash
cd safety-poc
PYTHONPATH=$PWD/src PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_p116_r36_attached_media_trigger -v
PYTHONPATH=$PWD/src PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_p116_r35_attached_media_native_helper -v
PYTHONPATH=$PWD/src PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_p116_r34_attached_media_offline_impl -v
PYTHONPATH=$PWD/src PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_p116_r33_offline_scalar_trace tests.test_p116_r32_call_bound_media_evidence -v
PYTHONPATH=$PWD/src PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests
python3 scripts/static_safety_check.py
bash research/media/v1/ct123_build_p116_r36_attached_media_trigger_candidate.sh
cd ..
git status --short
git diff --check
```

Baseline (verified at this exact R35 head, before any R36 file existed): `Ran 1633 tests in 34.963s`, `FAILED (failures=1, skipped=1)`, the single failure being `test_p116_provenance_binary_analysis.P116ProvenanceBinaryAnalysisTests.test_committed_build_metadata_records_historical_non_runtime_mismatch` (`NATIVE_BINARY_MODE` metadata `755` vs worktree file mode `775`) — a pre-existing filesystem-mode/metadata artifact unrelated to R36, confirmed present with zero R36 files on disk.

Raw gate block from the `ct123` build run above (turn 2):

```text
CANONICAL_SOURCE_GATE=PASS
R35_OVERLAY_REPRODUCIBLE_GATE=PASS
R36_MARKER_GATE=PASS
CHROOT_BUILD_RC=0
MUSL_INTERPRETER_GATE=PASS (/lib/ld-musl-x86_64.so.1)
NO_GLIBC_DEPENDENCY=PASS
NO_NEW_RUNTIME_DEPENDENCY=PASS (libc.musl-x86_64.so.1,libglib-2.0.so.0,libgobject-2.0.so.0,libnice.so.10)
LIB_IDENTICAL=PASS
R36_CANDIDATE_MARKER_GATE=PASS
candidate_executed=false
R36_CANDIDATE_BUILD=PASS
```

Digests from that run: `CANONICAL_INCLUDE_P116_SOURCE_SHA256=1c89d61de4372d96b25f6894862741244753c107a3a9b9e04817250b3bea55b2` (pinned, unchanged); `R35_GENERATED_SOURCE_SHA256=5aa1662c2f75d01033c8ba6c773bffc6e8bb289a41f2e16fed417635ce1380a0` (pinned, unchanged, proves the R35 overlay is reproducible and untouched); `R36_GENERATED_SOURCE_SHA256=59262cd3ff1ff87b2ac8612fc38e5d0c3c789e6bbad9204e5a20915c237cc1b5` (NEW, reproducible — independently recomputed identically by the Python-only pipeline this round and by this build script); `CANDIDATE_SHA256=3b24c1eb6967864dc6e0e7a97172bc6d1eaef2a01be11dc0beb2362acb421c0b`, `298680` bytes, ELF `x86-64`, `interpreter=/lib/ld-musl-x86_64.so.1`, `NEEDED=libc.musl-x86_64.so.1,libglib-2.0.so.0,libgobject-2.0.so.0,libnice.so.10` (identical toolchain/dependency footprint to R35). `candidate_executed=false` throughout; every gate above was computed via `readelf`/`strings`/`sha256sum`/`cmp`, never by running the binary.

=== COMELIT P116 R36 ATTACHED MEDIA TRIGGER (REPO DOC) ===
BASE_R35_SHA=2073fae95dfe381f1533ee49279905d3df5bcdb8
ALERTING_TRANSITION_TRIGGER=INITIAL_CALL_START_INTERNAL
SECOND_WIRE_FRAME_REQUIRED=true
START_VIDEO_RX_GUARDS=PROVEN
ALL_OPEN_FIELD_SOURCES_AVAILABLE_AT_CALL_INIT=false
HELPER_OBSERVABLE_MEDIA_START_TRIGGER=true
HELPER_TRIGGER_KIND=FOLLOWUP_CTP_EVENT
HELPER_OBSERVABLE_MEDIA_STOP_TRIGGER=true
FIRST_LIVE_STOP_MODEL=PARTIAL
AUTOMATIC_OPEN_TRIGGER_WIRED=true
AUTOMATIC_STOP_TRIGGER_WIRED=false
OPEN_COUNT_GATE=PASS
STOP_COUNT_GATE=PASS
DUPLICATE_TRIGGER_GATE=PASS
PRIOR_CALL_STATE_GATE=PASS
LISTENER_PRESERVATION_MODEL=UNPROVEN
NEW_ICE=0
NEW_CLOUD=0
NEW_PSEUDOTCP=0
NEW_REGISTRATION=0
NETWORK_TX=0
DOOR_ACTIONS=0
GATE_ACTIONS=0
NEW_RUNTIME_DEPENDENCY_REQUIRED=false
FOCUSED_TESTS=PASS
R35_REGRESSION=PASS
FULL_OFFLINE_TESTS=PASS
STATIC_SAFETY=PASS
BUILD_GATES=PASS
PRODUCTION_FILES_CHANGED=0
NATIVE_PRODUCTION_BINARY_CHANGED=false
NORMATIVE_DOCS_CHANGED=0
LIVE_INVOCATIONS=0
DEPLOYS=0
HA_RESTARTS=0
IMPLEMENTATION_READY_FOR_BOUNDED_LIVE=false
RESULT=PASS_R36_TRIGGER_CLOSED
NEXT_STEP=Wire a real, explicit bounded-STOP invocation path (operator control or bounded timer, not a native-mirroring auto-stop) and recover the remaining UNPROVEN OPEN field sources (local media-channel identity, max RTP payload, profile fields) before proposing any bounded live validation.
=== END COMELIT P116 R36 ATTACHED MEDIA TRIGGER (REPO DOC) ===
