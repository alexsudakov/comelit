# P116 R37 Attached Inbound Media Live-Readiness Closure

FACTS

R48 supersedes the field ownership stated below for `CallFsm+824/+832`. Primary native constructor
evidence now identifies `CallFsm+824` as `unitdata_t_TAG*` / `VipUnitImpl*` and `CallFsm+832` as
`cfg_t*`. The local CAPABILITIES call-type byte is therefore read from `[[CallFsm+824] + 18]`, not
from a `cfg_t*` at `CallFsm+824`.

R37 base is the exact R36 head `afdab40f97f3e85ac7b7f54a8aad49cbd2d80750`. No R32, R33, R34, R35, or R36
file was modified by this round. No file under `custom_components/**`, no existing `P116_*.md` document,
and no existing test/transform/serializer file was read for modification or written to. Five new paths
were added: `safety-poc/research/media/v1/entrance_p116_r37_attached_media_live_readiness_transform.py`,
`safety-poc/research/media/v1/ct122_build_p116_r37_attached_media_candidate.sh`,
`safety-poc/tests/native/p116_r37_attached_media_live_readiness_host_harness.c`,
`safety-poc/tests/test_p116_r37_attached_media_live_readiness.py`, and this document. R37 is an offline
`OFFLINE_ONLY` research round: no listener was run against a live device, no packet was transmitted on
the Comelit network, no Door/Gate action occurred, no physical or synthetic ring occurred, no Home
Assistant reload/restart occurred, no new packet capture was made, and the R37 candidate binary was
never executed (`candidate_executed=false`, verified by `readelf`/`strings`/`sha256sum`/`cmp` only).

EXECUTOR PROVENANCE

This round was executed by Claude Code CLI (model `claude-sonnet-5`) acting as substitute semantic
implementation executor because Codex CLI, the usual executor for this repository, is quota-blocked
(`You've hit your usage limit … try again at Sep 20th, 2026 4:57 PM`). The operator explicitly
authorized Claude Code CLI as the substitute semantic executor for R37 under the SAME prohibitions as
every prior R3x round (no live invocation, no new capture, no production file, no protocol invention,
no git write command). Hermes (the orchestrator) owns git (add/commit/push remain outside this
executor's actions), owns the worktree/branch, and independently re-runs the verification, digests,
host harness, and musl build shown below. All five R37 artifacts are research-only: no production file,
native production binary, or normative document was touched.

## SECTION 1 — CHILD A: THE SEVEN OPEN RUNTIME-FIELD SOURCES, TRACED TO EXACT NATIVE ORIGIN

Evidence: `.r33-evidence/native-disasm/disasm-CallFsm_go_in_alerting.txt`,
`disasm-CallFsm_start_videorx.txt` (full file), `disasm-RtpDispatcher_startVideoRX.txt` (full file),
`disasm2-RtpDispatcher__getMaxRtpPayload___const.txt`,
`disasm3-RtpDispatcher__RtpDispatcher_cfg_t___void___unsigned_int__unsigned_short_.txt`,
`disasm-ViperTunnel_openMediaRXChannel.txt`, `disasm-viper_tunnel_channel_create.txt`,
`disasm2-viper_channel_get_id.txt`, `disasm2-csp_send_mediareq26.txt`.

Every field below was traced this round to an EXACT native storage location and, where the evidence
allows, to its writer. None of the seven items is "closed" by inventing a value: each row states either
a PROVEN native source plus a proof that the source is unreachable by this helper (BLOCKED, not
invented), or an explicit residual gap in the staged evidence.

### (1) cfg capability threshold: `cfg->+16 <= 0x35`

`CallFsm::go_in_alerting()` reads it at `disasm-CallFsm_go_in_alerting.txt:35-38`
(`ldr x8,[x19,#824]; ldrh w8,[x8,#16]; cmp w8,#0x35`); the SAME check is re-applied in
`CallFsm::st_in_alerting()`'s capability-report handler (`disasm-CallFsm_st_in_alerting.txt:238-241`,
already cited by R36 SECTION 2). `cfg` (`CallFsm+824`) is a pointer to an externally-owned structure —
SECTION 2 below identifies it as `RtpDispatcher::cfg_t*`, the SAME pointer `RtpDispatcher`'s own
constructor receives and stores verbatim (`disasm3-RtpDispatcher__RtpDispatcher_...txt:78788`,
`stur x1,[x20,#-20]`, landing at `RtpDispatcher+48` — see SECTION 2). `RtpDispatcher`'s constructor never
writes `cfg_t+16` itself; the value is populated by whatever allocates and fills the `cfg_t` structure
before constructing `RtpDispatcher`, which is outside the disassembly staged for this repository (no
capture of the `cfg_t`-populating call site exists on disk). SOURCE: PROVEN (a field on an
externally-owned, non-wire, per-process `cfg_t` structure). VALUE / WRITER: UNPROVEN (evidence ends at
the pointer; the populating call site was not staged). HELPER_CAN_READ_OR_DERIVE: **false** — this
helper is a separate process (SECTION 2) with no access to that structure's memory, and the field is
never carried on the wire. CONFIDENCE: this is a real, evidenced gate (SECTION 2 of R36 already proved
`go_in_alerting()` cannot even *attempt* `start_videorx` if this comparison fails) — per CHILD A4 ("no
fail-open"), the helper cannot assume it always passes.

### (2) tunnel-busy: `RtpDispatcher+136` bit0

Read twice: once by `CallFsm::go_in_alerting()` via the SAME object accessed as `CallFsm+24`
(`disasm-CallFsm_go_in_alerting.txt:25,28`, `ldr x8,[x19,#24]; ldrb w10,[x8,#136]`), and once by
`RtpDispatcher::startVideoRX` on `this` directly (`disasm-RtpDispatcher_startVideoRX.txt:20-23`,
`ldrb w8,[x0,#136]; tbz w8,#0,...` — if set, the function returns `-1` immediately without doing
anything). `RtpDispatcher`'s own constructor zeroes this byte at construction
(`disasm3-RtpDispatcher__RtpDispatcher_...txt:78788` region, `strb wzr,[x19,#136]` at offset 78bc — see
the constructor listing) and the bit is otherwise set to `1` the moment a TUNNEL-form RX actually starts
(`disasm-RtpDispatcher_startVideoRX.txt:43,95,99`, three `strb w8,[x20,#136]` sites all writing `1`).
SOURCE: PROVEN — an in-process "already RXing" reentrancy latch, not wire-visible. HELPER_EQUIVALENT:
**exists** — R35's own `open_sent`/`stop_sent`/`state` fields (`R35AttachedMediaSession`,
`entrance_p116_r35_attached_media_native_transform.py:211-249`) already enforce the SAME semantic
("never start a second RX while one is active") via `r35_require_live_channel`/`r35_send_open`'s
`R35_ERR_OPEN_ALREADY_EMITTED` gate, proven exhaustively by R35's own host harness
(`P116_R35_ATTACHED_INBOUND_MEDIA_RESEARCH_HELPER.md` SECTION 4). This is the ONE field of the seven
this round can and does treat as CLOSED via equivalence — reading the real bit is unnecessary because
the helper already enforces the identical invariant on its own state, and R35's mechanism is unchanged
by this round.

### (3) media-eligibility gate: `CallFsm+840` bit2 (re-derived; NOT a TUNNEL/ADDRESS selector)

R36 SECTION 2 labeled this "tunnel-vs-address selector". Full re-derivation of
`CallFsm::start_videorx` this round (`disasm-CallFsm_start_videorx.txt:19-25`) shows it is not that: at
entry, `ldrb w8,[x0,#840]; tbnz w8,#2,6bfb0` — if bit2 is **clear**, execution falls straight through to
the shared stack-check-and-return epilogue at `6bf9c`/`6c070` (`disasm-CallFsm_start_videorx.txt:20-25`)
and the function does **nothing at all**: no RX start attempt, no packet, not even a log line. Only if
bit2 is **set** does the function proceed to decide TUNNEL vs ADDRESS (item 4 below). SOURCE: PROVEN — a
master "is media even eligible on this call/tunnel" gate on `CallFsm` itself, set by native runtime state
outside the disassembly staged for this round (no write site for `CallFsm+840` was found in the
functions captured; it is very likely written during `CallFsm` construction/tunnel-attachment, a call
site not present in this evidence set). HELPER_CAN_READ_OR_DERIVE: **false** — no wire representation,
no memory access. Per CHILD A4, a guard that can suppress the entire OPEN attempt cannot be assumed
invariant without proof, and none exists in this evidence set.

### (4) the TUNNEL/ADDRESS choice itself: `cfg->+288 != NULL` (re-derived; this is the REAL selector)

Inside the bit2-set branch, `CallFsm::start_videorx` reads `cfg->+152` (byte) and `cfg->+288` (pointer)
(`disasm-CallFsm_start_videorx.txt:39-44,81-83`, `ldrb w9,[x8,#152]; ... ldr x8,[x8,#288]`): if
`cfg->+288` is non-NULL, execution falls to the TUNNEL-form `csp_send_mediareq26` call (flags base
`0x32`, `disasm-CallFsm_start_videorx.txt:58-73`); if it is NULL, execution falls to the ADDRESS-form
call (`RtpDispatcher::getSockName`-derived address, flags base `0x30`,
`disasm-CallFsm_start_videorx.txt:84-120`). Independently, `RtpDispatcher::startVideoRX` makes the SAME
kind of decision on its OWN cached pointer, `RtpDispatcher+56` (the constructor's second, `void*`,
parameter — `disasm3-RtpDispatcher__RtpDispatcher_...txt`, `stur x2,[x20,#-12]` landing at offset 56):
`cbz x0,79190` (`disasm-RtpDispatcher_startVideoRX.txt:29,41`) branches to a FULLY-IMPLEMENTED,
actively-maintained ADDRESS-mode path (`inet_aton`, `Rtp::rtp_rx_start` with an explicit `in_addr*`,
`disasm-RtpDispatcher_startVideoRX.txt:190-232`) when that pointer is NULL, and to
`ViperTunnel::openMediaRXChannel` (item 5 below) when it is non-NULL
(`disasm-RtpDispatcher_startVideoRX.txt:158-178`). SOURCE: PROVEN as TWO independent runtime-pointer
checks (`cfg->+288`, `RtpDispatcher+56`) that plausibly reference the SAME underlying "is a Viper tunnel
attached" fact, but this equivalence is NOT independently proven by disassembly in this evidence set
(no capture ties the two pointers together). Both are pure in-process C++ object state — never carried
on the wire, and not derivable from any CTP frame. `ACTUAL_MEDIA_FORM=RUNTIME_DEPENDENT`. Per A1: "TUNNEL
as an invariant... must be PROVEN. Runtime-dependent and non-decidable by the helper ⇒ BLOCKED." That is
exactly this evidence's honest conclusion — **not** "TUNNEL is safe to assume," even though every prior
round (R34/R35/R36) has, in practice, only ever built the TUNNEL form. The existence of a complete,
non-dead ADDRESS-mode implementation is itself evidence against treating TUNNEL as a compile-time
invariant: dead code is not this — `RtpDispatcher::startVideoRX`'s ADDRESS branch performs real
`inet_aton`/`getSockName`/`rtp_rx_start` work, the signature of a maintained, reachable path.

### (5) profile-selector: `CallFsm+812`

Read only inside the ADDRESS-form flags composition (`disasm-CallFsm_start_videorx.txt:93`,
`ldrb w9,[x20,#812]`) — confirms R36's own citation. Because item (4) is `RUNTIME_DEPENDENT`
(BLOCKED, not proven-TUNNEL), this field cannot be marked `NOT_APPLICABLE` the way A1 allows only when
TUNNEL is *proven* invariant. SOURCE: PROVEN location, on `CallFsm` directly (not through `cfg`).
HELPER_CAN_READ_OR_DERIVE: **false** — no wire representation.

### (6) max RTP payload: `RtpDispatcher::getMaxRtpPayload() const`

The function itself is a single field read, no computation: `ldr w0,[x0,#68]; ret`
(`disasm2-RtpDispatcher__getMaxRtpPayload___const.txt:9-10`). `RtpDispatcher+68` is populated ONCE, at
construction, verbatim from the constructor's FOURTH parameter (`unsigned short`):
`and w8,w4,#0xffff; ... str w8,[x20,#68]!` (`disasm3-RtpDispatcher__RtpDispatcher_...txt:78764-78778`).
SOURCE: PROVEN to the exact byte-precision: **not** MTU discovery, **not** a hardcoded literal inside
the getter, **not** derived from tunnel state — a plain constructor-injected configuration value.
VALUE / CALL SITE: UNPROVEN — the disassembly of whoever constructs `RtpDispatcher` (and therefore
supplies this literal/config value) is not staged in this evidence set (no `new RtpDispatcher(...)` call
site was captured; `caller-xref.txt` reports zero resolved callers for every symbol in this evidence set,
a known limitation of the xref tool, not proof of no callers). HELPER_CAN_READ_OR_DERIVE: **false** — a
per-instance, in-process constructor argument, never carried on the wire.

### (7) local media RX channel identity — the CRITICAL field (A2)

Full chain, traced this round end-to-end:

1. `RtpDispatcher::startVideoRX`'s TUNNEL branch calls
   `ViperTunnel::openMediaRXChannel(callback, &this[+8], this)`
   (`disasm-RtpDispatcher_startVideoRX.txt:164-174`) — the second argument is the address of
   `RtpDispatcher+8`, an `int*` output parameter.
2. `ViperTunnel::openMediaRXChannel` calls `ViperTunnel::openChannel(...)`
   (`disasm-ViperTunnel_openMediaRXChannel.txt:39`), which (via `viper_tunnel_channel_create`, next)
   allocates a channel object, then calls `viper_channel_get_id(channel)`
   (`disasm-ViperTunnel_openMediaRXChannel.txt:44`) and writes the returned 16-bit id to `*out_id`
   (`disasm-ViperTunnel_openMediaRXChannel.txt:51`, `str w8,[x19]`).
3. `viper_tunnel_channel_create` allocates the id from **`ViperTunnel`'s own internal, live, stateful
   counter** at `ViperTunnel+296`, combined with a channel-type bit (`ViperTunnel+0`) shifted into bit15
   (`disasm-viper_tunnel_channel_create.txt:22-43`, `id = (type << 15) | sequential_counter`), checked
   for collision against a linked list of already-allocated channel nodes rooted at `ViperTunnel+0x110`
   (and `+272`/`+280` for the empty-list case) before being accepted — i.e. genuine, live,
   collision-avoiding allocation inside the real `ViperTunnel` object, not a formula an outside process
   could replicate without that object's live state.
4. `viper_channel_get_id` itself is `ldrh w0,[x0,#36]; ret`
   (`disasm2-viper_channel_get_id.txt:9-10`) — the allocated id stored on the channel node at
   construction (`disasm-viper_tunnel_channel_create.txt:66`, `strh w20,[x0,#36]`).
5. Back in `CallFsm::start_videorx`'s TUNNEL branch, the id is read from `RtpDispatcher+8`
   (`disasm-CallFsm_start_videorx.txt:47`, `ldr w22,[x0,#8]`) and passed as `csp_send_mediareq26`'s
   4th argument.
6. `csp_send_mediareq26` stores that 4th argument at **body bytes 8–9**
   (`disasm2-csp_send_mediareq26.txt:54`, `strh w22,[x1,#8]`) — exactly the byte range this round's
   dispatch instructions named as the target.

SOURCE: PROVEN, completely, to `viper_tunnel_channel_create`'s live internal counter inside the real
`ViperTunnel` object. `MEDIA_CHANNEL_ID_ALLOCATOR=viper_tunnel_channel_create` (native, internal to
`libvipcomelit.so`). `MEDIA_CHANNEL_ID_AVAILABLE_BEFORE_MEDIAREQ26=true` — but only WITHIN the SAME
process's own call stack, synchronously, immediately before `csp_send_mediareq26` is invoked.
`MEDIA_CHANNEL_ID_EQUALS_CALL_CTP=false` (proven false: the allocator is a `ViperTunnel`-internal
sequential counter combined with a type bit, structurally unrelated to and independently incrementing
from the call's CTP connection id established at `CALL_INIT`/`csp_recv`). `MEDIA_CHANNEL_ID_EQUALS_REGISTERED_CTPP=false`
(same reasoning; R30/R32 already proved the registered CTPP handle is a distinct outer transport handle).
**Equivalence check (required by A2):** this helper (the R35/R36/R37 musl candidate) does **not** link
`libvipcomelit.so` — its build `NEEDED` set is `libc.musl-x86_64.so.1,libglib-2.0.so.0,libgobject-2.0.so.0,libnice.so.10`
only (unchanged by this round, verified by this round's own build, SECTION 8). It therefore has no shared
memory with, and no call path into, the real `ViperTunnel` object's `+296` counter or `+0x110` collision
table. No existing helper-side allocator can supply an equivalent value without either (a) guessing a
value that could collide with a channel id the REAL native library independently allocates on the SAME
physical Viper tunnel connection (a wire-protocol correctness hazard, not merely a research-honesty one),
or (b) this helper becoming part of the SAME process/address space as `libvipcomelit.so` — a new runtime
coupling this round is prohibited from adding (CHILD G: "If the real media-channel primitive needs a new
runtime dependency: do not add it; `RESULT=BLOCKED_RUNTIME_ABI`" — here the "dependency" would be
process/library co-location, not merely a `.so`, which is an even larger architectural change).
`LIVE_MEDIA_CHANNEL_IDENTITY_PROVEN=false`. `MEDIA_CHANNEL_ID_SOURCE=BLOCKED_RUNTIME_PRIMITIVE` (native
source fully proven; helper-side equivalence proven impossible under the current architecture, not merely
unproven).

### Summary table

| # | Field | Native source | Wire-visible? | Helper can read/derive? | Status |
|---|---|---|---|---|---|
| 1 | cfg capability threshold `cfg->+16<=0x35` | external `cfg_t` field, writer not staged | no | no | BLOCKED (unproven value, no fail-open) |
| 2 | tunnel-busy `RtpDispatcher+136` bit0 | in-process reentrancy latch | no | N/A | **CLOSED via R35 equivalence** |
| 3 | media-eligibility `CallFsm+840` bit2 | in-process gate, writer not staged | no | no | BLOCKED (can suppress OPEN entirely) |
| 4 | TUNNEL/ADDRESS `cfg->+288`/`RtpDispatcher+56` | in-process pointers | no | no | BLOCKED — `RUNTIME_DEPENDENT`, not provably invariant |
| 5 | profile-selector `CallFsm+812` | in-process byte | no | no | BLOCKED (ADDRESS-only; cannot be ruled `NOT_APPLICABLE` since #4 is unresolved) |
| 6 | max RTP payload `RtpDispatcher+68` | ctor parameter, call site not staged | no | no | BLOCKED (source kind proven, value unproven) |
| 7 | media RX channel identity | `viper_tunnel_channel_create` live counter | no | no (separate process, no `libvipcomelit.so` link) | **BLOCKED — CRITICAL, architectural** |

`ALL_OPEN_FIELD_SOURCES_AVAILABLE_AT_TRIGGER=false`. `LIVE_MEDIA_CHANNEL_IDENTITY_PROVEN=false`.
`OPEN_PLACEHOLDER_FIELDS_REMAIN=9` (counted at the `R35MediaRequestSources` struct-field granularity
R36's own trigger leaves as zero/placeholder and never sets to a proven value: `media_channel_id`
(placeholder = call CTP id, not proven), `max_rtp_payload`, `profile_selector`, `channel_profile_word`,
`profile_halfwords[0]`, `profile_halfwords[1]`, `profile_halfwords[2]`, `profile_halfword_3`,
`profile_byte_4` — `entrance_p116_r36_attached_media_trigger_transform.py:155-161`).
`ALL_OPEN_RUNTIME_FIELDS_PROVEN=false`.

## SECTION 2 — WHY THIS IS AN ARCHITECTURAL BOUNDARY, NOT A MISSING DERIVATION

Every BLOCKED field above shares the same shape: C++ object state (`RtpDispatcher`, `ViperTunnel`, the
shared `cfg_t`) living inside `libvipcomelit.so`'s own process. The R35/R36/R37 candidate is, and remains
after this round, a *separate* musl binary — `NEEDED=libc.musl-x86_64.so.1,libglib-2.0.so.0,libgobject-2.0.so.0,libnice.so.10`,
verified unchanged by this round's own build (SECTION 8). It communicates with the rest of the system
only by parsing bytes already flowing on a CTP connection it observes (`r35_parse_ctp_envelope`) and by
queuing outbound bytes through the existing transport (`p12_queue_vip_frame`) — it has never had, and
this round does not add, any mechanism to read another process's memory or call into `libvipcomelit.so`'s
functions. Recovering these fields for real would require either (a) linking this helper into the same
address space as `libvipcomelit.so` (a new, large runtime coupling — effectively becoming part of the
device's native call-processing library rather than an attached observer of it), or (b) a live capture
of the missing call sites (`cfg_t` population, `RtpDispatcher` construction) that is explicitly out of
scope for an offline round. Neither is available to this round; this is why CHILD A cannot be closed to
`true` here, and why R37 does not attempt to paper over it with an invented constant (explicitly
prohibited: "A constant observed in an old capture is NOT proof of a source").

## SECTION 3 — CHILD B: THE REAL BOUNDED STOP CONTROL

Independent of the OPEN blocker above (STOP never needs to allocate a NEW channel identity — it
references whatever channel a prior OPEN already established), this round adds a real, explicit,
externally-invocable STOP path.

**Mechanism.** `g_unix_signal_add(SIGUSR2, r37_bounded_stop_signal_cb, NULL)`
(`entrance_p116_r37_attached_media_live_readiness_transform.py`, `WIRING_REGION`) installs a GLib
main-loop `GSource` for `SIGUSR2`. Unlike a raw `signal()` handler, `g_unix_signal_add`'s callback is
dispatched from the ordinary main loop (GLib implements it via a self-pipe/`signalfd`, never invoking
application code in real POSIX signal context) — satisfying CHILD B's requirement ("no complex/network
work inside the POSIX signal context; defer to the normal main loop") more strongly than a raw handler +
flag would, and without any periodic check of any kind (no `g_timeout_add`, matching R35/R36's own "no
retry" discipline, enforced by this round's `_assert_gates` `R37_NO_RETRY_GATE`). The callback calls
exactly one dispatcher, `r37_bounded_stop_request` (`CORE_REGION`), which does nothing but call R35's
own, unmodified `r35_send_stop`/`r35_dispose_media_rx_channel` — no new writer, no new serializer, no new
channel-allocation rule (enforced by `R37_REUSES_R35_GATE`/`R37_NO_DUPLICATE_WRITER_GATE`).

**Exactly one external request per media lifetime.** The `GSource` is kept installed
(`G_SOURCE_CONTINUE`) rather than torn down after first use; idempotency is enforced by R35's own
`stop_sent`/`stop_count` state (`R35_ERR_SECOND_STOP` if called again before disposal,
`R35_ERR_STALE_CHANNEL` if called again after this round's own immediate post-stop disposal step already
ran — both are the SAME semantic event, "a duplicate, already-handled request," and both are counted as
such by `duplicate_stop_request_ignored_count`). This is not a second idempotency mechanism: it is
telemetry over R35's existing one.

**Markers (values only, never raw ids).** `BOUNDED_STOP_REQUEST_RECEIVED`,
`CALL_BOUND_MEDIA_STOP_SENT_COUNT`, `RTP_DISARMED`, `MEDIA_RX_CHANNEL_DISPOSED` — all counters on the
new `R37BoundedStopTelemetry` struct, printed by the wiring callback.

**B1: the first future live run design.** `CAPABILITY trigger → at most one OPEN → observe RTP →
bounded observation window → explicit external SIGUSR2 → r37_bounded_stop_request → at most one STOP →
media-only disposal → listener alive` — with a hard outer timeout supplied by the EXISTING
`absolute_timeout_cb`/`g_timeout_add_seconds(3300, ...)` mechanism already present in the generated
helper (unedited by R35/R36/R37) and a fail-closed cleanup policy inherited directly from R35's own
`r35_require_live_channel`/`r35_call_ready` gates: any state this round's dispatchers cannot positively
prove ready is refused, never assumed. This design is recorded here as the plan for a future live round;
no live run occurred in R37.

`REAL_BOUNDED_STOP_PATH=true`. `FIRST_LIVE_STOP_MODEL=PROVEN` — R35 already proved `r35_send_stop`'s
internal correctness; this round closes the ONE gap R35/R36 explicitly left open (SECTION 8 of R35's
own document, SECTION 5 of R36's own document): a real, external, bounded invocation call site now
exists and is host-harness-proven end-to-end (SECTION 6, scenarios 8–10).

## SECTION 4 — CHILD C: PROTOCOL STOP EVENTS AND THE REMOTE-TERMINATION RACE RULE

Two already-proven native stop causes (R36 SECTION 5) are now wired as ADDITIONAL, fail-closed
local/media stop paths — **not** a substitute for the explicit bounded STOP above.

**A later CAPABILITY_REPORT clearing bit3** (`r37_handle_capability_cleared`): recognized in the SAME
per-frame receive loop, matching on the SAME opcode/connection guard R36's own trigger already uses
(`R36_OP_CAPABILITIES`, `r35_call_ready`), but with bit3 **clear**. It calls the SAME
`r37_stop_and_dispose` sequence as the bounded control, but deliberately does **not** call
`r35_teardown_call` — the call itself is not over (matching CHILD D's preservation requirement); only
channel/RTP state changes. Host harness scenario 12 (SECTION 6) proves `r35_call_ready(s)` is still true,
and `s->call_transaction_alive` unchanged, after this handler runs.

**RELEASE** (`r37_handle_remote_release`): recovered wire opcode `OP_RELEASE=0x000E`
(`.r33-evidence/public-vip/viper/ctp.py:30`, already cited by R36 SECTION 5 as predicting native FSM
event `0xb0e`/`0xa0e`). The public sample's own `FLAG_FIN=0x20` is noted as the OTHER plausible wire flag
for a connection-closing frame (`.r33-evidence/public-vip/viper/ctp.py:23`); since no staged capture
pins the exact flag byte a real RELEASE frame carries, this round's wiring accepts **either**
`R35_CTP_FLAG_DATA` or `R37_CTP_FLAG_FIN` rather than guessing one (a residual, explicitly-recorded
uncertainty, same honesty discipline as R36 SECTION 4's bit3-value residual question — not a
wire-contract unknown, a live-behaviour one).

**The required race rule: `REMOTE_CALL_TERMINATED ⇒ no stale media write ⇒ local state cleanup /
exact native-equivalent behaviour`.** R36 SECTION 5 already found `stop_videorx()` is called as PART of
native call-teardown on RELEASE — i.e. native sequencing stops media BEFORE the call transaction is
gone, not after. `r37_handle_remote_release` reproduces that exact order: it attempts ONE
stop-and-dispose sequence FIRST, while `r35_call_ready(s)` is still true, THEN calls `r35_teardown_call`.
Once teardown has run, `r35_call_ready(s)` is false and every subsequent call to
`r37_bounded_stop_request`/`r37_handle_capability_cleared` is rejected with
`R35_ERR_NO_CALL_TRANSACTION_OR_BARRIER` — no stale write can ever follow. Host harness scenario 11
(SECTION 6) proves this directly: a RELEASE arriving first performs exactly one legitimate write; a
LATER external bounded-STOP request is received (counted), rejected, and produces zero additional
writes (`R37_SCENARIO_11_STALE_WRITE_COUNT=0`). This is not invented ordering: it mirrors the native
ordering R36 already cited (`disasm-CallFsm_st_in_alerting.txt:503-521`), not a new assumption.

`REMOTE_RELEASE_HANDLING=PROVEN` (mechanism and ordering; the RELEASE wire-flag ambiguity noted above is
a recorded residual, not a blocker — the opcode/connection match, the part that decides *whether* this
is a RELEASE frame at all, is confirmed). `CAPABILITY_CLEAR_STOP_HANDLING=PROVEN`.

## SECTION 5 — CHILD D: LISTENER/CALL PRESERVATION INVARIANTS

Offline, by code, unchanged from R35 (`r35_preserve_listener_registration_pseudotcp`,
`entrance_p116_r35_attached_media_native_transform.py:580-584`) and extended by this round's own
functions:

- **No new cloud, ICE, PseudoTCP, or CTPP registration.** Neither `r37_bounded_stop_request` nor either
  protocol-stop handler references `nice_agent_*`, `pseudotcp_*`, or any registration/`v4_ctpp_*` symbol
  (enforced by `_assert_gates`' dependency-free-core forbidden-symbol list, same as R35/R36).
- **No call release triggered by media STOP.** `r37_bounded_stop_request` and
  `r37_handle_capability_cleared` never call `r35_teardown_call` — verified by direct inspection
  (neither function contains that call) and by host-harness scenario 12 (`r35_call_ready` still true
  afterward).
- **After a media-only STOP, the inbound call/listener transaction can continue if the remote side did
  not end it.** Proven by construction: `r37_stop_and_dispose` only ever touches `channel_allocated`,
  `channel_disposed`, `rtp_armed`, and `stop_sent`/`stop_count` (all fields `r35_dispose_media_rx_channel`
  already owns) — it never touches `call_ctp_valid`, `call_transaction_alive`, `listener_alive`,
  `registration_alive`, or `pseudotcp_alive`.
- **No listener stop, process exit, or self-activation.** No R37 function calls `exit`, `g_main_loop_quit`,
  or any `entrance_self_activation_*`/`P12_TX_ENTRANCE_SELF_ACTIVATION` symbol (same forbidden-symbol
  gate).
- **RELEASE is the one case where call state IS cleared** — by design (SECTION 4): the call really is
  over, and `r35_teardown_call` (R35's own, unmodified function) is the correct, already-proven cleanup.

`LISTENER_PRESERVATION_MODEL=PASS` — the code-level invariants above (no `r35_teardown_call` from either
STOP path except RELEASE, no new ICE/cloud/PseudoTCP/registration symbol reachable, `r35_call_ready`
still true and `call_transaction_alive` unchanged after `r37_handle_capability_cleared`, host-harness
scenario 12) are demonstrated offline this round. This is still a MODELED result, not a live one: the
underlying booleans (`listener_alive`, `registration_alive`, `pseudotcp_alive`) are research-model state
set at capture time (R35, unchanged), not live component state, because no listener ran this round
either — the same caveat R35/R36 recorded, carried forward rather than silently dropped.

## SECTION 6 — CHILD E/F: OVERLAY AND HOST HARNESS (ALL 15 REQUIRED SCENARIOS RUN)

**Why an overlay was added despite CHILD A being BLOCKED.** CHILD E gates the overlay on CHILD A **and**
B being "sufficiently closed." CHILD A is not closed for OPEN (SECTION 1/2); CHILD B **is** fully closed
(SECTION 3), and does not depend on any CHILD A field (STOP never allocates a new channel identity).
Per the operator's explicit critical instruction, this overlay therefore adds **zero** new OPEN-related
code — R36's existing OPEN trigger is untouched byte-for-byte, and `_assert_gates`' `R37_NO_NEW_OPEN_PATH_GATE`
fails the build closed if any R37 region ever calls `r35_allocate_media_rx_channel`/`r35_send_open`. What
the overlay DOES add: the bounded STOP control (SECTION 3) and the two protocol-stop handlers
(SECTION 4). `OVERLAY_ADDED=true` — CHILD B/C are real, proven, additive closures that do not require
inventing the CHILD A fields.

**Files:** `entrance_p116_r37_attached_media_live_readiness_transform.py` (the overlay, applied strictly
on top of R36's output; raises if the input is not already R36-augmented, and raises on re-application);
`tests/native/p116_r37_attached_media_live_readiness_host_harness.c` (research-only, never compiled into
the packaged/candidate binary); `ct122_build_p116_r37_attached_media_candidate.sh` (extends the pipeline
with a fourth stage); `test_p116_r37_attached_media_live_readiness.py`.

**All 15 CHILD F scenarios were run.** Compiled and executed this round
(`cc -std=c99 -Wall -Wextra -pedantic`, zero warnings, zero side effects:
`R37_NETWORK_TX=0`/`R37_DOOR_ACTIONS=0`/`R37_GATE_ACTIONS=0`):

| # | Scenario | Marker | Result | Note |
|---|---|---|---|---|
| 1 | CALL_INIT only ⇒ OPEN=0 | `R37_SCENARIO_1_CALL_INIT_ONLY` | PASS | inherited from R35/R36, unedited |
| 2 | CAPABILITY bit3 clear ⇒ OPEN=0 | `R37_SCENARIO_2_CAPABILITY_BIT3_CLEAR` | PASS | inherited |
| 3 | valid CAPABILITY + valid runtime fields ⇒ OPEN=1 | `R37_SCENARIO_3_VALID_CAPABILITY_OPENS_MECHANISM_ONLY` | PASS | **mechanism-only** — proves R36's trigger fires offline; NOT proof `media_channel_id` is a real native value (see #7) |
| 4 | missing media channel id ⇒ OPEN=0 | `R37_SCENARIO_4_MISSING_MEDIA_CHANNEL_ID` | PASS | R35's own `channel_id==0` bad-argument gate |
| 5 | stale/prior media channel ⇒ OPEN=0 | `R37_SCENARIO_5_STALE_PRIOR_MEDIA_CHANNEL` | PASS | R35's `STALE_CHANNEL_GATE`, re-exercised here |
| 6 | registered CTPP used as media channel ⇒ OPEN=0 | `R37_SCENARIO_6_REGISTERED_CTPP_AS_MEDIA_CHANNEL` | PASS | R35's registration-handle-misuse rule |
| 7 | call CTP used incorrectly as media-channel id ⇒ OPEN=0 | `R37_SCENARIO_7_CALL_CTP_AS_MEDIA_CHANNEL_ID` | **FAIL** | **run exactly as specified, and honestly reported.** R36's real, unedited trigger deliberately reuses the call CTP connection id as channel id (`R37_SCENARIO_7_CHANNEL_ID_EQUALS_CALL_CTP=true`, `OPEN=1`) — this is independent, executable confirmation of SECTION 1 item 7, not a test defect. R37 does not rewrite R36 (prohibited) to force this to pass. |
| 8 | external bounded STOP before OPEN ⇒ STOP=0 | `R37_SCENARIO_8_BOUNDED_STOP_BEFORE_OPEN` | PASS | new this round |
| 9 | external bounded STOP after OPEN ⇒ STOP=1 | `R37_SCENARIO_9_BOUNDED_STOP_AFTER_OPEN` | PASS | new this round |
| 10 | duplicate STOP ⇒ STOP remains 1 | `R37_SCENARIO_10_DUPLICATE_STOP` | PASS | new this round |
| 11 | remote release before external STOP ⇒ stale write=0 | `R37_SCENARIO_11_REMOTE_RELEASE_BEFORE_EXTERNAL_STOP` | PASS | new this round; `R37_SCENARIO_11_STALE_WRITE_COUNT=0` |
| 12 | capability clears bit3 after OPEN ⇒ proven stop behaviour | `R37_SCENARIO_12_CAPABILITY_CLEARS_BIT3_AFTER_OPEN` | PASS | new this round; call/listener preserved |
| 13 | terminal call + later trigger ⇒ OPEN=0 / no duplicate STOP | `R37_SCENARIO_13_TERMINAL_CALL_LATER_TRIGGER` | PASS | inherited + new dispatcher, both fail closed |
| 14 | media disposal invalidates channel identity | `R37_SCENARIO_14_DISPOSAL_INVALIDATES_CHANNEL_IDENTITY` | PASS | R35's `STALE_CHANNEL_GATE`, re-exercised via R37's dispatcher |
| 15 | new CALL generation cannot reuse a prior media channel | `R37_SCENARIO_15_NEW_CALL_GENERATION_CANNOT_REUSE_CHANNEL` | PASS | R35's `call_generation`/`channel_generation` gate, re-exercised via R37's dispatcher |

`HARNESS_SCENARIOS=1-6,8-15 PASS; 3 PASS(mechanism-only); 7 FAIL(honest, expected, confirms SECTION 1
item 7)`. `R37_HARNESS_RESULT=FAIL` (the harness's own summary marker; not overridden or hidden — see
`test_overall_harness_result_reflects_scenario_7_honestly` in the Python test module). This FAIL is the
correct, evidence-driven outcome: 14 of 15 scenarios genuinely close new or already-proven ground; the
15th is a deliberate, literal re-run of the exact rule CHILD A found the current architecture cannot
satisfy, and it is reported as failing rather than silently dropped or rewritten to pass.

## SECTION 7 — CHILD G: BUILD / ABI

Same offline discipline as the R35/R36 lanes. Pipeline: canonical `--include-p116` → R35 overlay
(unedited, reproducibility-checked) → R36 overlay (unedited, reproducibility-checked) → R37 overlay (new).
Build root `/home/hermes/comelit-r37-build-20260919T125326Z/` (mode `700`, outside the repository tree).
`APK_CLOSURE=/home/hermes/musl-apk-closure-p80` (109 packages, per `MANIFEST.sha256`).

Raw gate block from this round's build:

```text
CANONICAL_SOURCE_GATE=PASS
R35_OVERLAY_REPRODUCIBLE_GATE=PASS
R36_OVERLAY_REPRODUCIBLE_GATE=PASS
CHROOT_BUILD_RC=0
MUSL_INTERPRETER_GATE=PASS (/lib/ld-musl-x86_64.so.1)
NO_GLIBC_DEPENDENCY=PASS
NO_NEW_RUNTIME_DEPENDENCY=PASS (libc.musl-x86_64.so.1,libglib-2.0.so.0,libgobject-2.0.so.0,libnice.so.10)
LIB_IDENTICAL=PASS
R37_MARKER_GATE=PASS
PRODUCTION_MARKER_INTEGRITY_GATE=PASS
candidate_executed=false
R37_CANDIDATE_BUILD=PASS
```

Digests: `CANONICAL_INCLUDE_P116_SOURCE_SHA256=1c89d61de4372d96b25f6894862741244753c107a3a9b9e04817250b3bea55b2`
(pinned, unchanged); `R35_GENERATED_SOURCE_SHA256=5aa1662c2f75d01033c8ba6c773bffc6e8bb289a41f2e16fed417635ce1380a0`
(pinned, unchanged); `R36_GENERATED_SOURCE_SHA256=59262cd3ff1ff87b2ac8612fc38e5d0c3c789e6bbad9204e5a20915c237cc1b5`
(pinned, unchanged — R37 proves both prior overlays are reproducible and untouched);
`R37_GENERATED_SOURCE_SHA256=d314efcecc10b2656fa069c069833c9d8815c8753749554e8b83702241a0950a` (NEW, reproducible
— independently recomputed identically by the Python-only pipeline and by this build script);
`CANDIDATE_SHA256=18d6d091d9da9f57b0a44fc9376567a6c1d91acb03da74a8a7d70fed73ecc699`, `303208` bytes, ELF `x86-64`,
`interpreter=/lib/ld-musl-x86_64.so.1`, `NEEDED=libc.musl-x86_64.so.1,libglib-2.0.so.0,libgobject-2.0.so.0,libnice.so.10`
— **identical dependency footprint to R35/R36**: `g_unix_signal_add` is provided by the SAME
`libglib-2.0.so.0` already linked; no new shared library was added. `NEW_RUNTIME_DEPENDENCY=false`. The
compiler emitted zero R37-specific warnings (the pre-existing `-Wunused-function` warnings for
`v4_door_tick_cb`, `absolute_timeout_cb`, `p76_*`, etc. are unrelated dead code already present before
R37 and untouched by it). `candidate_executed=false` throughout — every gate was computed via
`readelf`/`strings`/`sha256sum`/`cmp`, never by running the binary. Since the media-channel primitive
that would be needed to close CHILD A is unreachable WITHOUT a new runtime coupling (SECTION 1 item 7),
and this round adds none, `RESULT` below is `BLOCKED_MEDIA_CHANNEL`, not `BLOCKED_RUNTIME_ABI` — R37
itself introduces no new dependency; it is CHILD A's blocked field that WOULD require one if ever closed.

## SECTION 8 — LIVE-READINESS GATE

| Condition | Status this round |
|---|---|
| `OPEN_TRIGGER_PROVEN` | YES (unchanged, inherited from R36) |
| `ALL_OPEN_RUNTIME_FIELDS_PROVEN` | **NO** — SECTION 1, 6/7 fields BLOCKED |
| `LIVE_MEDIA_CHANNEL_IDENTITY_PROVEN` | **NO** — SECTION 1 item 7, architectural |
| `NO_PLACEHOLDER_FIELD_USED_FOR_NETWORK_PACKET` | **NO** — R36's inherited trigger still uses the call-CTP-id placeholder (scenario 7); R37 adds no NEW placeholder use but does not remove the inherited one (cannot edit R36) |
| `OPEN_COUNT_MAX=1` | YES (R35/R36, unchanged; re-proven scenarios 1-3) |
| `REAL_BOUNDED_STOP_PATH` | **YES** — new this round, SECTION 3 |
| `STOP_COUNT_MAX=1` | YES (scenario 10) |
| `STOP_BEFORE_DISPOSAL` | YES (R35, unchanged; `r37_stop_and_dispose` calls disposal only after a successful stop) |
| `STALE_CHANNEL_WRITE_FORBIDDEN` | YES (scenarios 5, 14) |
| `REMOTE_TERMINATION_SAFE` | **YES** — new this round, SECTION 4, scenario 11 |
| `NEW_ICE=0` / `NEW_CLOUD=0` / `NEW_PSEUDOTCP=0` / `NEW_REGISTRATION=0` | YES (SECTION 5) |
| `SELF_ACTIVATION_USED=false` | YES |
| `DOOR/GATE=0` | YES |
| build reproducible | YES (SECTION 7) |
| `candidate_executed=false` | YES |

Two of the required conditions were newly closed this round (`REAL_BOUNDED_STOP_PATH`,
`REMOTE_TERMINATION_SAFE`); the remainder that were already `false`/blocked before this round
(`ALL_OPEN_RUNTIME_FIELDS_PROVEN`, `LIVE_MEDIA_CHANNEL_IDENTITY_PROVEN`,
`NO_PLACEHOLDER_FIELD_USED_FOR_NETWORK_PACKET`) remain false/blocked, now with an exact architectural
reason (SECTION 1/2) rather than an open research question. `IMPLEMENTATION_READY_FOR_BOUNDED_LIVE=false`.

## SECTION 9 — BASELINE FAILURE SEPARATION

The pre-existing baseline failure `test_p116_provenance_binary_analysis.P116ProvenanceBinaryAnalysisTests.test_committed_build_metadata_records_historical_non_runtime_mismatch`
(`NATIVE_BINARY_MODE` metadata `755` vs worktree file mode `775`) is reproduced, unchanged, at this
round's base (R36 head, verified with zero R37 files on disk, see VERIFICATION below) and is NOT fixed
by this round — it is a pre-existing filesystem-mode/metadata artifact unrelated to R37 model, test,
transform, or documentation content, exactly as R35/R36 separated it.

## VERIFICATION

Commands run in this worktree (`safety-poc/` as working directory unless noted):

```bash
cd safety-poc
PYTHONPATH=$PWD/src PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_p116_r37_attached_media_live_readiness -v
PYTHONPATH=$PWD/src PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_p116_r36_attached_media_trigger tests.test_p116_r35_attached_media_native_helper -v
PYTHONPATH=$PWD/src PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_p116_r34_attached_media_offline_impl -v
PYTHONPATH=$PWD/src PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_p116_r33_offline_scalar_trace tests.test_p116_r32_call_bound_media_evidence -v
PYTHONPATH=$PWD/src PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests
python3 scripts/static_safety_check.py
bash research/media/v1/ct122_build_p116_r37_attached_media_candidate.sh
cd ..
git status --short
git diff --check
```

Raw results are reported verbatim in the executor report accompanying this document.

=== COMELIT P116 R37 ATTACHED MEDIA LIVE READINESS (REPO DOC) ===
EXECUTOR=claude-code-cli
EXECUTOR_SUBSTITUTION_AUTHORIZED_BY_USER=true
BASE_R36_SHA=afdab40f97f3e85ac7b7f54a8aad49cbd2d80750
OPEN_TRIGGER_PROVEN=true
CAPABILITY_TRIGGER_PROVEN=true
ACTUAL_MEDIA_FORM=RUNTIME_DEPENDENT
CFG_THRESHOLD_SOURCE=BLOCKED (read-site proven at cfg->+16, SECTION 1 item 1; populating writer not staged in evidence; unreachable by this helper)
TUNNEL_BUSY_SOURCE=PROVEN (RtpDispatcher+136 bit0, SECTION 1 item 2: ctor-zeroed and all three set-to-1 sites cited; closed for the helper via R35's own equivalent idempotency gate, not by reading the real bit)
PROFILE_FIELDS_SOURCE=BLOCKED (read-sites proven at CallFsm+812 and cfg->+360..+368, SECTION 1 item 5; populating writers not staged in evidence; unreachable by this helper)
MAX_RTP_PAYLOAD_SOURCE=BLOCKED (proven to be a ctor parameter at RtpDispatcher+68, SECTION 1 item 6 -- not MTU discovery, not a hardcoded literal; the constructing call site/value is not staged in evidence; unreachable by this helper)
LIVE_MEDIA_CHANNEL_IDENTITY_PROVEN=false
MEDIA_CHANNEL_ID_SOURCE=BLOCKED_RUNTIME_PRIMITIVE (viper_tunnel_channel_create, native, internal to libvipcomelit.so's live ViperTunnel object, SECTION 1 item 7)
MEDIA_CHANNEL_ID_EQUALS_CALL_CTP=false
MEDIA_CHANNEL_ID_EQUALS_REGISTERED_CTPP=false
OPEN_PLACEHOLDER_FIELDS_REMAIN=9
ALL_OPEN_RUNTIME_FIELDS_PROVEN=false
NO_PLACEHOLDER_FIELD_USED_FOR_NETWORK_PACKET=false (R36's inherited, unedited OPEN trigger still serializes the call-CTP-connection-id as the channel-id placeholder into a real network-bound MEDIAREQ26 OPEN body; harness scenario 7 confirms this executably -- OPEN=1, channel_id_equals_call_ctp=true -- and R37 cannot edit R35/R36 files to block it)
REAL_BOUNDED_STOP_PATH=true
FIRST_LIVE_STOP_MODEL=PROVEN
REMOTE_RELEASE_HANDLING=PROVEN
CAPABILITY_CLEAR_STOP_HANDLING=PROVEN
STALE_CHANNEL_GATE=PASS
STOP_ORDER_GATE=PASS
SELF_ACTIVATION_USED=false
OVERLAY_ADDED=true (CHILD B/C fully closed independently of the CHILD A blocker; zero new OPEN wiring)
HARNESS_SCENARIOS=1-6,8-15 PASS; 3 PASS(mechanism-only); 7 FAIL(honest, expected)
R37_GENERATED_SOURCE_SHA256=d314efcecc10b2656fa069c069833c9d8815c8753749554e8b83702241a0950a
CANDIDATE_SHA256=18d6d091d9da9f57b0a44fc9376567a6c1d91acb03da74a8a7d70fed73ecc699
CANDIDATE_BYTES=303208
BUILD_GATE_LINES=CANONICAL_SOURCE_GATE=PASS,R35_OVERLAY_REPRODUCIBLE_GATE=PASS,R36_OVERLAY_REPRODUCIBLE_GATE=PASS,CHROOT_BUILD_RC=0,MUSL_INTERPRETER_GATE=PASS,NO_GLIBC_DEPENDENCY=PASS,NO_NEW_RUNTIME_DEPENDENCY=PASS,LIB_IDENTICAL=PASS,R37_MARKER_GATE=PASS,PRODUCTION_MARKER_INTEGRITY_GATE=PASS,candidate_executed=false,R37_CANDIDATE_BUILD=PASS
OPEN_COUNT_GATE=PASS
STOP_COUNT_GATE=PASS
DUPLICATE_TRIGGER_GATE=PASS
PRIOR_CALL_STATE_GATE=PASS
LISTENER_PRESERVATION_MODEL=PASS
NEW_ICE=0
NEW_CLOUD=0
NEW_PSEUDOTCP=0
NEW_REGISTRATION=0
NETWORK_TX=0
DOOR_ACTIONS=0
GATE_ACTIONS=0
NEW_RUNTIME_DEPENDENCY_REQUIRED=false
FOCUSED_TESTS=PASS
R36_REGRESSION=PASS
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
RESULT=BLOCKED_MEDIA_CHANNEL
NEXT_STEP=Recover the RtpDispatcher/ViperTunnel/cfg_t call sites (constructor arguments, cfg_t population) via either a live, authorized capture of device process memory/call sites or a decision to co-locate this helper inside libvipcomelit.so's own process; neither is in scope for an offline round, and no bounded live validation should be proposed until MEDIA_CHANNEL_IDENTITY_PROVEN=true.
=== END COMELIT P116 R37 ATTACHED MEDIA LIVE READINESS (REPO DOC) ===
