# P116 R40H — Fresh Registration Transition / Receiver-Arm / Native Liveness Closure

Round: `COMELIT-P116-R40H-FRESH-REGISTRATION-LIVENESS`. Mode: `RESEARCH_OFFLINE / DEV_OFFLINE`.
`LIVE_INVOCATIONS=0`. Base: exact R40G head `b9ebcd04cb0e86e64af41666fe8e27d0fc191d2c`. This document, two
new overlay/parser modules (`entrance_p116_r40h_registration_log_model.py`,
`entrance_p116_r40h_official_app_readiness_model.py`), the R41 contract successor
(`P116_R41_OFFICIAL_APP_READINESS_LIVE_PREFLIGHT_PLAN_V3.md`) and the focused tests are this round's
deliverables. `P116_R40G_RUNTIME_PATH_AND_READINESS.md`, `entrance_p116_r40g_official_app_readiness_model.py`
and every earlier R40/R40F/R39 document and model are unchanged and referenced, never rewritten.

## Executor provenance

```
EXECUTOR=claude-code-cli+hermes-primary
EXECUTOR_FALLBACK_USED=true
EXECUTOR_FALLBACK_AFTER_PARTIAL=true
EXECUTOR_FALLBACK_REASON=claude_usage_limit
```

Claude Code CLI wrote the first draft of all five files in this round and then terminated mid-round on its
session limit (`You've hit your session limit · resets 10:20pm (UTC)`, exit code 1) **before** it ran any
verification. Hermes (the orchestrator) therefore completed the round as semantic executor under the
operator's explicit R40H fallback authorization, which requires Hermes to independently re-derive every
load-bearing claim against the raw evidence rather than continue the draft as given. What that
re-derivation changed:

* **Independently re-confirmed against raw evidence** (Hermes greps/reads on the recovered sources, not the
  draft's citations): the `registerStatus != status` equality guard around the `Log.i("VIP REGISTER
  CHANGED ...")` call (`ComelitStatus.java` L209-218); every `mBound` write/read and the five `forward*`
  guards (`ReadFromJsonSocket.java` L51, 61, 66, 79, 91, 98, 506-527, 577); the unguarded
  `subunit_fsm_status_change` → `setEngineVipRegStatus` branch (L260-269, L347-357); the
  `ViperSocketReaderRunnable.setReconnecting()` failure path including the `VIPER SOCKET CONNECTION LOST`
  log line and the synchronous `RegisterStatus.NOT_REGISTERED` write (L49-82); and the native TCP keepalive
  parameters — `setsockopt` x4 at `0x98e38/0x98e50/0x98e68/0x98e80` in `ViperTunnel::open`, with
  `SOL_SOCKET/SO_KEEPALIVE=1`, `IPPROTO_TCP/TCP_KEEPCNT=2`, `TCP_KEEPIDLE=10`, `TCP_KEEPINTVL=20`, followed
  by `ViperTunnel::setTunnelCallbacks()`.
* **Corrected by Hermes after independent verification** — the draft's verification claim was false and two
  real defects were found and fixed:
  1. `entrance_p116_r40h_official_app_readiness_model.evaluate_readiness_v3` used an `isinstance` check
     against a class object loaded under a different `importlib` spec name than the test module used, so
     every "ready" case returned `UNPROVEN` (4 failing assertions). Replaced with structural (field-level)
     validation of the fresh verdict, and the delegated gate now receives the fresh transition's strictly
     stronger form of the same field (`registration_ready_seen=True`) instead of the superseded unsampled
     scalar.
  2. `test_p116_r40h_fresh_registration_liveness.test_model_has_no_network_or_process_surface` used bare
     substring matching, so the module's own docstring phrase "invokes no subprocess/adb" tripped it
     (1 failing assertion). Rewritten as an AST/import-level check.
  3. The draft's `FOCUSED_TESTS=PASS` / `FULL_OFFLINE_TESTS=PASS` claims were written before any test run;
     section 12 below now carries Hermes's actually-executed numbers instead.

Hermes owns git (add/commit/push), the worktree/branch, and every verification number in section 12.

## 0. Why this round exists

R40G left four open points: (1) `CONNECTED` may be stale; (2) `registration_ready_seen` and the UI read are
the same `ComelitStatus.regStatus` field, not independent corroboration; (3) `ReadFromJsonSocket.forwardCallEvent`
requires `mBound=true`, unproven to co-occur with `REGISTERED`; (4) `NATIVE_KEEPALIVE_FOUND=UNPROVEN` because
only small, targeted native-disassembly symbol sets were searched. This round re-derives CHILD A-J against a
**full disassembly of `libvipcomelit.so`** (already present, git-excluded, at R33's evidence path —
`.r33-evidence/native-disasm/full-disasm-libvipcomelit.txt`, 152,009 lines, `objdump -d`, sha256-pinned in
its own `PROVENANCE.txt`) plus the complete, un-truncated `ReadFromJsonSocket.java`, `ComelitEngineConnector.java`,
`ComelitStatus.java`, `ViperSocketReaderRunnable.java`, `JsonServerSocketMng.java`, `ComelitFlowStatus.java`
and `ComelitService.java` sources — no new native disassembly was generated; the existing full disassembly
was sufficient and is used as-is.

## 1. CHILD A — fresh registration transition vs. current state

`CURRENT_REGISTERED_SUFFICIENT=false`. `FRESH_REGISTERED_TRANSITION_STRONGER=true`.

**The equality-guard proof (the load-bearing fact this round found).** `ComelitStatus.setEngineVipRegStatus`
(`ComelitStatus.java` L209-218):

```java
public static void setEngineVipRegStatus(RegisterStatus status) {
    RegisterStatus registerStatus = regStatus;
    if (registerStatus != status) {
        previous_regStatus = registerStatus;
        Log.i(TAG, "VIP REGISTER CHANGED " + regStatus + " -> " + status);
        regStatus = status;
        notifyEvent(ComelitStatusEvent.COMELIT_ENGINE_VIP_STATUS, regStatus);
    }
    ComelitFlowStatus.INSTANCE.notifyVipConnectionChange(status);
}
```

The `Log.i("VIP REGISTER CHANGED ...")` line — the exact scalar source R40G CHILD C proved is a safe,
production, unmodified logcat line — sits **inside** the `if (registerStatus != status)` guard. By
construction, this line can only ever be emitted when the previous value differed from the new one. A caller
invoking `setEngineVipRegStatus(REGISTERED)` while already `REGISTERED` produces **no new log line at all**
(only the unconditional `notifyVipConnectionChange` call outside the guard fires, which updates the same
`StateFlow`/`LiveData` R40G CHILD D already showed is not independent corroboration). This means: any
occurrence of `"VIP REGISTER CHANGED X -> REGISTERED"` in the log stream is, by construction, proof of a
**real state transition**, never a re-assertion of an already-REGISTERED value — a guarantee this round did
not have to assume; it is read directly from the guard.

**Every code path that reaches REGISTERED passes through a real prior state change.** Traced every call site
across the recovered sources:

* `ReadFromJsonSocket`'s `subunit_fsm_status_change` dispatch (`ReadFromJsonSocket.java` ~L260-269) maps the
  native FSM's own `subunit_fsm_status` string 1:1: `"registering"` → `REGISTERING`, `"fail_wait"` →
  `NOT_REGISTERED`, `"registered"` → `REGISTERED`. This relays the native registration FSM's own transitions
  verbatim; it does not independently invent a `REGISTERED` value.
* `ComelitEngineConnector.closeAll()` (called from `destroyInstance()`, itself called at the top of
  `getNewInstance()` before creating a new connector) unconditionally sets
  `setEngineVipRegStatus(NOT_REGISTERED)` (L131) as part of teardown — **any engine/connector recreation
  passes through `NOT_REGISTERED` first**, by construction, before a new registration cycle can begin.
* `ViperSocketReaderRunnable.setReconnecting()` (on a real socket read error/EOF, `alive` still true — i.e.
  not a deliberate `stop()`) sets `NOT_REGISTERED` (L78) synchronously, then broadcasts
  `CREATE_VIPER_CONNECTION`, which `ComelitService`'s receiver (`ComelitService.java` case 4, L153-162)
  handles by calling `engineConnector.starViperConnection()` in a new thread — which itself sets
  `ViperStatus.OPENING` (L472) and calls `engine.createViperTunnel(...)` (a **new native tunnel object**,
  CHILD E below), before any subsequent `REGISTERING`/`REGISTERED` message can arrive.
* The cloud (`apartmentId != null`) path in `createSystemFromSettings()` explicitly sets `REGISTERING`
  (L156) before the async `VipCloudConnector.connect` callback later sets either `NOT_REGISTERED` (failure,
  L211) or `REGISTERED` (success, L215) — `REGISTERING` always precedes.
* `ComelitService`'s network-change broadcast handler (case 5, L165) only attempts a fresh
  `startVipFromSettings()` retry when `ComelitStatus.getEngineVipRegStatus() != REGISTERED` — i.e. the app
  itself treats "already REGISTERED" as "do not retry," which is exactly why a **stale** REGISTERED value
  (R40G CHILD D's silent-staleness case) would never self-correct through this path; it is also exactly why
  observing a **fresh** transition into REGISTERED after this attempt's boundary is stronger: it proves the
  app did **not** merely coast on an old value, since the reconnect/creation logic that produced it always
  starts from a real non-REGISTERED state first.

`FRESH_REGISTRATION_ACCEPTED_TRANSITIONS=any transition into REGISTERED whose immediately-preceding state
(per the same "VIP REGISTER CHANGED X -> REGISTERED" line) was NONE, NOT_REGISTERED, or REGISTERING — i.e.
anything other than REGISTERED itself (which the equality guard makes structurally impossible to log as a
"transition" in the first place)`.

`FRESH_REGISTRATION_PROVES_NEW_SESSION=PARTIAL`. A fresh `REGISTERING -> REGISTERED` (or `NOT_REGISTERED ->
REGISTERED`) transition proves the native registration FSM completed a real registration handshake with the
panel after the boundary — a strong liveness signal. It does **not**, by itself, prove a brand-new transport
object (TCP tunnel / P2P session) was created: the native FSM's `"registering"`/`"fail_wait"`/`"registered"`
messages are relayed verbatim from whatever the native engine reports, and this round found no Java-side
proof that every `REGISTERING` necessarily corresponds to a new `engine.createViperTunnel(...)` call versus
an application-level re-register cycle over an already-open tunnel. What **is** proven is the stronger,
practically-relevant claim: every code path this round traced that can produce a fresh transition (engine
recreation, socket-read-error reconnection, cloud connect retry) does so only after tearing down to
`NOT_REGISTERED` first and, for the reconnection path specifically, after a genuinely new
`engine.createViperTunnel(...)` call (CHILD A's second bullet above). Absent further native FSM tracing this
round did not attempt (out of scope for the registration-transition question), "new session" stays `PARTIAL`
rather than `PROVEN`.

## 2. CHILD B — fresh log cursor / freshness model (design only)

`FRESH_LOG_CURSOR_METHOD=host-captured, non-destructive monotonic cursor: immediately before the listener
pause, the operator/runner notes the current position in a live `adb logcat -v time -T "<timestamp>" -s
ComelitStatus:I ViperSocketReaderRun:E` stream (or, equivalently, the device's own monotonic boot-time via
`adb shell cat /proc/uptime`, passed to a subsequent `-T` invocation); every log line consumed by the reducer
below this cursor is assigned an increasing `monotonic_seq`, and the cursor itself is recorded as the
`monotonic_seq` value immediately prior to the first post-pause line. No `adb logcat -c` (destructive clear)
is used or needed — `-T` already restricts the stream to lines at/after a given time without discarding the
device's buffer for other consumers`.

`LOG_BUFFER_CLEAR_REQUIRED=false`.

**Parser design (implemented this round, offline-only).** `entrance_p116_r40h_registration_log_model.py`:

* `reduce_raw_line(tag, message, monotonic_seq) -> Optional[ReducedLogEvent]` — a pure function matching only
  the two known-safe production formats (`ComelitStatus`'s `"VIP REGISTER CHANGED X -> Y"` and
  `ViperSocketReaderRun`'s `"VIPER SOCKET CONNECTION LOST"`); anything else returns `None` and is discarded.
  `ReducedLogEvent` stores exactly `{source: enum, monotonic_seq: int, from_state: enum|None, to_state:
  enum|None}` — never the original line, never a timestamp string, never a PID.
* `evaluate_fresh_registration(events, pre_pause_log_cursor) -> FreshRegistrationVerdict` — drops every event
  at or before the cursor, then walks the remainder in order tracking the last uninvalidated fresh
  `REGISTERED` transition; a later `REGISTERED -> non-REGISTERED` line or a `VIPER SOCKET CONNECTION LOST`
  line (CHILD F) invalidates it.

`REGISTRATION_READY_FRESH_SCALAR=FreshRegistrationVerdict.registration_ready_fresh_scalar` — a single safe
boolean derived only from enum names, a source-tag enum, and small integers; no adb/subprocess call appears
anywhere in the module (`import subprocess` is absent, verified by the focused tests below).

## 3. CHILD C — mBound / receiver-armed lifecycle

`MBOUND_LIFECYCLE=PROVEN`.

Full lifecycle, read from the complete `ReadFromJsonSocket.java` (594 lines, previously only partially
excerpted):

1. `JsonServerSocketMng.start(context)`'s accept-loop thread (`JsonServerSocketMng.java` L69-87), on each
   accepted socket, constructs `new ReadFromJsonSocket(sock, context, messageParserFactory)` (L77) — the
   constructor (`ReadFromJsonSocket.java` L70-76) synchronously calls `bindService()` (L78-88), which itself
   calls `android.content.Context.bindService(...)` — an inherently **asynchronous** Android API; the method
   returns immediately, before `onServiceConnected` fires.
2. Only **after** the constructor returns does `JsonServerSocketMng` create and start the reader `Thread`
   (`new Thread(readFromJsonSocket); thread2.start();`, L78-79) — i.e. `bindService()` is issued strictly
   before the read loop begins, but its completion is not awaited or synchronized with the read loop in any
   way.
3. `ServiceConnection.onServiceConnected` (L57-62, on the main thread, whenever Android delivers it) sets
   `this.mService = ...` then `mBound = true`. `onServiceDisconnected` (L64-67) sets `mBound = false`. Neither
   callback touches `ComelitStatus`.
4. `run()`'s dispatch switch (L152-360-ish) parses `subunit_fsm_status_change` and calls
   `ComelitStatus.setEngineVipRegStatus(...)` directly, **with no `mBound` check anywhere in that branch**.
5. `forwardCallEvent`, `forwardConnectionEvent`, `forwardReport`, `forwardOpenDoorResult`,
   `forwardActuatorResult` (L505-592) are the **only** five methods that read `mBound`, each guarding with
   `if (!this.mBound || ...) return;` before touching `this.mService`.

Every write of `mBound` (`ServiceConnection.onServiceConnected` → `true`; `ServiceConnection.onServiceDisconnected`
→ `false`; `unbind()` → `false` in its `finally` block, L90-101) and every read (`bindService()`/`unbind()`
guards, plus the five `forward*` methods above) is accounted for; there are no others in the file.

`REGISTERED_BEFORE_MBOUND_POSSIBLE=true` (code-level, unsynchronized — the `subunit_fsm_status_change`
branch has no `mBound` gate, so nothing in the Java source prevents it). In practice this window is narrow:
the JSON server socket's accept, and therefore this `ReadFromJsonSocket` construction and `bindService()`
call, happens once during `engine.initEngine(...)` early in `createSystemFromSettings()`/`createSystemFromWizard()`
— well before any VIP tunnel is opened or any `subunit_fsm_status_change` message could possibly arrive
(that requires the subsequent `createBaseSystem()` → `starViperConnection()` → `engine.createViperTunnel(...)`
chain to complete first). This round did not find a code-level guarantee ruling the race out, only a causal
distance that makes it unlikely in the observed control flow — consistent with, not weaker than, R40G's
original framing.

`MBOUND_CAN_DROP_WHILE_REGISTERED=true`. `onServiceDisconnected` can fire (Android delivers it when the
bound service's process dies unexpectedly) independent of `RegisterStatus`, and nothing links it back to
`ComelitStatus`. This is a real, if likely rare (same-process service), gap this round confirms rather than
newly discovers.

`RECEIVER_ARMED_SIGNAL=UNPROVEN`. Neither `onServiceConnected` nor `onServiceDisconnected` contains a
`Log.*` call anywhere in `ReadFromJsonSocket.java` — `mBound` has **no** existing logcat signal, unlike
`RegisterStatus` (CHILD B) or the transport-failure marker (CHILD E/F below). `RECEIVER_ARMED_OBSERVABLE=false`
from outside the app process without instrumentation this round was told to deprioritize (Frida/Xposed/APK
patch).

## 4. CHILD D — does fresh REGISTERED imply mBound?

`FRESH_REGISTERED_IMPLIES_MBOUND=PARTIAL`. `FRESH_REGISTERED_IMPLIES_RECEIVER_ARMED=PARTIAL`.

No happens-before proof exists in the Java source: `mBound`'s write happens on the main thread inside an
Android-delivered `ServiceConnection` callback; the `subunit_fsm_status_change` dispatch happens on the JSON
reader thread's own loop; nothing synchronizes the two (no lock, no `Thread.join`, no `CountDownLatch`,
confirmed absent by inspection of the full `ReadFromJsonSocket.java`). Per this round's own instruction ("if
such ordering is not proven, do not assert it"), this is not asserted as `PROVEN`. It is not asserted as
outright `FALSE` either: CHILD C's causal-distance argument (the JSON socket, and therefore `bindService()`,
is created and issued long before any tunnel/registration exchange can begin) makes the implication likely
true in the traced control flow, even though no explicit synchronization proves it. `PARTIAL` records this
honestly: likely-but-unproven, with a known, narrow, unsynchronized counter-scenario. Because "receiver
armed" (CHILD C's `forwardCallEvent`-can-actually-deliver definition) reduces to exactly this same `mBound`
condition, `FRESH_REGISTERED_IMPLIES_RECEIVER_ARMED` carries the identical verdict and identical caveat.

## 5. CHILD E — native keepalive / liveness (full disassembly search)

`NATIVE_KEEPALIVE_FOUND=PROVEN_PRESENT`. This is the substantive change from R40G's `UNPROVEN` — this round
searched the full 152,009-line `objdump -d` of `libvipcomelit.so` (not the earlier ~49-symbol targeted
inventory) and found two distinct, real mechanisms, both cited to exact demangled symbol names and
disassembled instruction sequences:

**(1) OS-level TCP keepalive on the direct/local tunnel (`ConnectionType.VIPER` / `VIPER_LOCAL`).**
`ViperTunnel::open(char const*, int, int, int)` (address `0x9886c`, matches the independently-recovered
symbol name in R28's pre-existing `native-disasm/ViperTunnel-open.txt`) issues exactly four `setsockopt`
calls immediately before `ViperTunnel::setTunnelCallbacks()` (disassembly at `0x98e08`-`0x98e84`):

| call | level (w1) | optname (w2) | value | meaning (Linux/Android `netinet/tcp.h`, `sys/socket.h`) |
|---|---|---|---|---|
| 1 | `1` (`SOL_SOCKET`) | `9` (`SO_KEEPALIVE`) | `1` | enable OS-level TCP keepalive |
| 2 | `6` (`IPPROTO_TCP`) | `6` (`TCP_KEEPCNT`) | `2` | 2 unanswered probes before declaring dead |
| 3 | `6` (`IPPROTO_TCP`) | `4` (`TCP_KEEPIDLE`) | `10` | 10s idle before the first probe |
| 4 | `6` (`IPPROTO_TCP`) | `5` (`TCP_KEEPINTVL`) | `20` | 20s between probes |

`NATIVE_KEEPALIVE_KIND=OS-level TCP SO_KEEPALIVE (direct/local VIPER path, ViperTunnel::open) + app-level
ping/timestamp mechanism (ViperTunnel::startKeepAliveChecker, VIPER_P2P path only, see below)`.
`NATIVE_KEEPALIVE_INTERVAL_SECONDS=TCP path: KEEPIDLE=10, KEEPINTVL=20, KEEPCNT=2 (worst-case ~50s to a
declared-dead socket); P2P path: UNPROVEN (see below)`.

`NATIVE_KEEPALIVE_FAILURE_ACTION` (TCP path): once the OS declares the socket dead, the blocking
`this.fis.read(bArr)` in `ViperSocketReaderRunnable.run()` (Java) returns `< 0` or throws — the exact
mechanism R40G already traced — invoking `setReconnecting()`, which sets `ViperStatus.CLOSED` +
`RegisterStatus.NOT_REGISTERED` synchronously and broadcasts `CREATE_VIPER_CONNECTION`, driving the retry
chain CHILD A cites. `NATIVE_KEEPALIVE_UPDATES_REGISTER_STATUS=PARTIAL` — proven for the TCP path via this
Java-side handler (the native layer itself never calls into `ComelitStatus`; it only causes the OS to
surface a socket error the Java layer already handles), not proven for the P2P path below.

**(2) App-level keepalive ping on the P2P tunnel (`ConnectionType.VIPER_P2P`).**
`ViperTunnel::startKeepAliveChecker()` (`0x99b80`) is called exactly once in the whole binary, from
`ViperTunnel::p2pTunnelFinishOpening()` (`0x998a0`, immediately after `setTunnelCallbacks()` succeeds,
`0x99918`-`0x99924`). Its body: builds a short fixed string, calls
`ViperTunnel::sendOnChannel(ViperChannelType, char const*, int)` with channel type `2` (an explicit
application-level ping-like message sent over the already-open P2P channel), then records
`std::chrono::steady_clock::now()` into two object fields (offsets `304` and `320`) and sets two boolean
flags (offsets `312`, `328`). This is a real, cited, app-level liveness primitive distinct from generic OS
TCP keepalive (which the P2P/relayed transport does not obviously benefit from at the application-protocol
level). This round located `ViperTunnel::timer()` (`0x9ab44`, a periodic native callback confirmed to exist
on the class) but its body dispatches only to `ViperTunnel::processP2PStatus()` (ICE-session
establishment/retry logic), not to a comparison against the timestamps `startKeepAliveChecker` recorded —
the periodic re-check/failure action for the P2P app-level keepalive was **not located** in this round's
search. `NATIVE_KEEPALIVE_FAILURE_ACTION` (P2P path) = `UNPROVEN`.

`SILENT_STALE_REGISTERED_RISK=MEDIUM` (kept at R40G's fail-closed value as the single reported scalar,
because which `ConnectionType` is active during any given live attempt is not itself provable offline). The
evidence materially changes the picture underneath that scalar, though: for the direct/local TCP path
(`VIPER`/`VIPER_LOCAL` — the connection type expected for this project's on-premise CT120/CT122 hardware
when reachable directly), the risk is now better characterized as **LOW**, with a cited, bounded ~50s
worst-case detection window and a proven, existing Java-side correction path (`setReconnecting` →
`NOT_REGISTERED`). For the P2P/relayed path, the risk remains at R40G's original **MEDIUM/UNPROVEN**
characterization, since the app-level keepalive's failure-detection half was not located. A future round
could resolve this fully by tracing what (if anything) reads `ViperTunnel` offsets 304/312/320/328.

## 6. CHILD F — independent liveness signal

`INDEPENDENT_LIVENESS_SIGNAL=ViperSocketReaderRunnable.setReconnecting()'s Log.e(TAG="ViperSocketReaderRun",
"VIPER SOCKET CONNECTION LOST") line`. `INDEPENDENT_LIVENESS_OBSERVABLE=true`.

This is a genuinely different signal from `registration_ready_seen`/the UI read, not a re-read of the same
field (R40G CHILD D's objection to the prior "confirmed by machine signal" framing): it comes from a
different tag, a different thread (the `ViperSocketReaderRunnable` blocking-read thread, not the JSON-socket
reader thread that sets `RegisterStatus`), and is driven by a different underlying detection mechanism (the
OS-level TCP-keepalive-triggered read error, CHILD E) rather than a parsed application-level JSON message.
Critically, this line is reachable **only** on an undeliberate failure (`stopRequest` is checked first in
`setReconnecting()`; a deliberate `.stop()` suppresses it) and is always followed, in the same call, by
`setEngineVipRegStatus(NOT_REGISTERED)`. Its **absence** between a fresh `REGISTERED` transition and the
current sample time is therefore real corroboration that the native TCP-keepalive-backed transport has not
been flagged dead since that transition — exactly the missing independent signal R40G could not find. It is
implemented as the poisoning check inside `entrance_p116_r40h_registration_log_model.evaluate_fresh_registration`
(CHILD B), not as a separate function, since the two are read from the same log stream in one pass.

Caveat carried over from CHILD E: this specific independent signal only covers the direct/local TCP
connection type. It says nothing about a silently-stuck P2P tunnel, for which no equivalent negative-signal
logcat line was found this round.

## 7. CHILD G — R40G model review

`R40G_MODEL_SEMANTICS=TOO_PERMISSIVE`.

`entrance_p116_r40g_official_app_readiness_model.evaluate_readiness_v2` accepts `registration_ready_seen`
as a plain current-state boolean with no freshness requirement and no cross-check against the CHILD F
transport-failure signal. A stale `REGISTERED` value sampled long after any real transition — R40G CHILD D's
silent-staleness scenario — passes v2's gate exactly as readily as a value that just transitioned a second
ago. Per the round's own preference list ((A) current CONNECTED; (B) current CONNECTED +
`registration_ready_seen`; (C) fresh REGISTERED transition; (D) fresh + receiver-armed; (E) fresh +
independent liveness; (F) other), this round's evidence supports **(E)**: fresh REGISTERED transition
(CHILD A/B) **and** independent-liveness-not-contradicted (CHILD F), specifically because CHILD F is the one
component that is both proven and adb-observable via a plain, unmodified, existing log line — unlike
receiver-armed (`mBound`, option D), which CHILD C proved has **no** existing observable signal at all
(`RECEIVER_ARMED_OBSERVABLE=false`) and would require app instrumentation this round was told to
deprioritize.

`entrance_p116_r40h_official_app_readiness_model.py` is added as a narrow overlay per this finding: it wraps
R40G's `evaluate_readiness_v2` unchanged and adds one new, load-bearing, fail-closed precondition — a
`FreshRegistrationVerdict` (CHILD B) whose `registration_ready_fresh_scalar` is `True` — refusing to produce
a readiness verdict at all otherwise. R40G's own file, model and tests are untouched and still pass
unmodified.

## 8. CHILD H — freshness-aware R41 contract v3

`P116_R41_OFFICIAL_APP_READINESS_LIVE_PREFLIGHT_PLAN_V3.md` is added (new file; V1/V2 untouched). It
distinguishes `CURRENT_UI_STATE` (the literal toolbar read, R40F/R40G) from `FRESH_ATTEMPT_EVIDENCE` (this
round's `FreshRegistrationVerdict`, sampled only from logcat lines after the attempt's `PRE_PAUSE_LOG_CURSOR`),
requires both, remains a NO-RING PREFLIGHT with `ring_budget_available=false` always, and states that
`PASS_APP_READY_PREFLIGHT` does not authorize R42. See the document itself for the full 13-step contract.

## 9. CHILD I — operational time window

`APP_READY_PROTOCOL_TIMEOUT_SECONDS=UNPROVEN` (unchanged — this round re-confirmed no numeric
registration-retry-interval constant exists in the recovered Java sources; the native TCP-keepalive
interval CHILD E found (~50s worst case) bounds *transport-death detection*, not *registration protocol
latency*, and must not be conflated with it). The existing 300s continuous-down listener-failsafe ceiling
(R39/R40, reused unchanged by R40G) still applies: any operator-chosen `OPERATIONAL_APP_READY_TIMEOUT_SECONDS`
must stay `0 < timeout <= 300` with margin below the failsafe. The fresh-transition gate does not change this
bound — it changes what counts as a PASS *within* that same window, not how long the window may be.

## 10. CHILD J — R41 v3 runner implementation readiness

`R41_V3_RUNNER_READY_TO_IMPLEMENT=true`, with an explicit residual-risk statement (native P2P-path
keepalive failure-action and the `mBound`/receiver-armed signal both remain unobservable/unproven, per the
round's own allowance: "if native liveness stays UNPROVEN but the fresh-transition + mBound analysis
suffices, true is allowed with an honest residual-risk statement" — here native liveness for the *direct*
path is proven, the *P2P* path and receiver-armed remain the honest residuals). Closed this round: exact
attempt-freshness boundary (CHILD A/B), exact parser semantics (`entrance_p116_r40h_registration_log_model`),
UI signal (unchanged from R40F/R40G), machine freshness signal (CHILD B/F), listener restore ordering
(unchanged from R41 v1/v2), timeout validation (CHILD I, unchanged bound), zero-ring invariant (unchanged),
fail-closed errors (CHILD G overlay), safe scalar output (CHILD B). Open residuals, stated explicitly rather
than silently assumed away: receiver-arm policy has no observable signal at all (CHILD C/D) so R41 v3 cannot
require it as a gate, only document it as an unresolved limitation; P2P-path native liveness failure-action
is unproven (CHILD E).

## 11. Evidence ledger

| SOURCE_KIND | FILE | SYMBOL_OR_METHOD | LINE_OR_ADDRESS_RANGE | CLAIM | CONFIDENCE |
|---|---|---|---|---|---|
| dex | `dex7/.../application/ComelitStatus.java` | `setEngineVipRegStatus` | L209-218 | The "VIP REGISTER CHANGED" log line sits inside an `if (registerStatus != status)` guard — a REGISTERED->REGISTERED call emits no new log line | HIGH — direct source read |
| dex | `dex7/.../engine/managers/ComelitEngineConnector.java` | `closeAll` | L112-132 | Engine/connector destroy unconditionally sets `NOT_REGISTERED` before any new instance is created | HIGH — direct source read |
| dex | `dex7/.../engine/managers/ComelitEngineConnector.java` | `createSystemFromSettings`, `starViperConnection` | L134-217, L470-507 | Cloud path always sets REGISTERING before REGISTERED/NOT_REGISTERED; local/native retry path always sets ViperStatus.OPENING and calls `engine.createViperTunnel` before any REGISTERING/REGISTERED message can arrive | HIGH — direct source read |
| dex | `dex7/.../viper/ViperSocketReaderRunnable.java` | `run`, `setReconnecting` | full file (89 lines) | Real read error/EOF (not deliberate stop) synchronously sets `NOT_REGISTERED` and broadcasts `CREATE_VIPER_CONNECTION`; logs "VIPER SOCKET CLOSE REQUEST"/"VIPER SOCKET CONNECTION LOST" only on the undeliberate path | HIGH — direct source read |
| dex | `dex7/.../application/jsonsocket/JsonServerSocketMng.java` | `start` (accept-loop Runnable) | L69-90 | `new ReadFromJsonSocket(...)` (constructor calls `bindService()`) completes strictly before the reader `Thread` is created/started | HIGH — direct source read |
| dex | `dex7/.../application/jsonsocket/ReadFromJsonSocket.java` | `mBound` (all writes/reads), `forwardCallEvent`, `forwardConnectionEvent`, `forwardReport`, `forwardOpenDoorResult`, `forwardActuatorResult` | L47-101, L505-592 | Full mBound lifecycle: async ServiceConnection writes, five forward* methods are the only readers, no Log call in onServiceConnected/onServiceDisconnected | HIGH — direct source read, full file (594 lines) |
| dex | `dex7/.../application/jsonsocket/ReadFromJsonSocket.java` | `run` dispatch switch, `subunit_fsm_status_change` branch | ~L260-269 | `subunit_fsm_status_change` sets REGISTERING/NOT_REGISTERED/REGISTERED with no `mBound` check | HIGH — direct source read |
| dex | `dex7/ComelitService.java` | anonymous `BroadcastReceiver.onReceive` | L139-197 | Case 4 (CREATE_VIPER_CONNECTION) retries `starViperConnection()`; case 5 (network change) only retries if `RegisterStatus != REGISTERED` | HIGH — direct source read |
| dex | `dex7/.../application/ComelitFlowStatus.java` | `notifyVipConnectionChange`, `_vipConnectionStatus` | full file | StateFlow/LiveData update is the same field as the UI read, dispatched via `GlobalScope` coroutine, unconditional (outside the equality guard) | HIGH — direct source read |
| native_disasm | `.r33-evidence/native-disasm/full-disasm-libvipcomelit.txt` | `ViperTunnel::open(char const*, int, int, int)` | disasm offset `0x98e08`-`0x98e84` | Four `setsockopt` calls: SOL_SOCKET/SO_KEEPALIVE=1, IPPROTO_TCP/TCP_KEEPCNT=2, IPPROTO_TCP/TCP_KEEPIDLE=10, IPPROTO_TCP/TCP_KEEPINTVL=20 | HIGH — direct disassembly read, cross-referenced against R28's independently-recovered `ViperTunnel-open.txt` symbol name |
| native_disasm | `.r33-evidence/native-disasm/full-disasm-libvipcomelit.txt` | `ViperTunnel::p2pTunnelFinishOpening()`, `ViperTunnel::startKeepAliveChecker()` | disasm offset `0x99920`-`0x99c9c` | App-level keepalive ping (`sendOnChannel`) + `steady_clock::now()` timestamp recording, armed once per P2P tunnel completion; only one caller in the whole binary | HIGH — direct disassembly read |
| native_disasm | `.r33-evidence/native-disasm/full-disasm-libvipcomelit.txt` | `ViperTunnel::timer()`, `ViperTunnel::processP2PStatus()` | disasm offset `0x9ab44`-`0x9ac50` | Periodic native timer dispatches only to ICE-session retry logic, not to a check of the keepalive-checker timestamps | MEDIUM — confirms a periodic timer exists and what it does, but does not prove the keepalive-checker's failure action is absent elsewhere in the binary (a targeted, not exhaustive, dataflow trace of offsets 304/312/320/328) |
| native_disasm | `.r33-evidence/native-disasm/full-disasm-libvipcomelit.txt` | `ComelitEngine::sysSafeKeepalive` | disasm offset `0x8f66c` | Stub returning a fixed error code (`mov w0,#0xffffff9a; ret`) — not implemented in this library build; belongs to the separate "Safe" alarm subsystem, not the VIP door-entry tunnel | HIGH — direct disassembly read |
| prior_doc | `P116_R40G_RUNTIME_PATH_AND_READINESS.md` sections 2-5 | — | n/a | R40G's `REGISTERED_IMPLIES_RECEIVER_ARMED=PARTIAL`, `UI_CONNECTED_STALENESS_RISK=MEDIUM`, `NATIVE_KEEPALIVE_FOUND=UNPROVEN` — the exact findings this round re-derives against fuller evidence | HIGH — cited, previously-verified |

## 12. Verification

Commands run in this worktree (`safety-poc/` as working directory unless noted):

```bash
cd safety-poc
python3 -m unittest tests.test_p116_r40h_fresh_registration_liveness -v
python3 -m unittest tests.test_p116_r40g_runtime_path_readiness -v
python3 -m unittest tests.test_p116_r40f_official_app_readiness_evidence -v
python3 -m unittest tests.test_p116_r40_official_app_readiness -v
python3 -m unittest tests.test_p116_r39_official_app_phone_capture -v
python3 -m unittest tests.test_p116_r37_attached_media_live_readiness tests.test_p116_r36_attached_media_trigger tests.test_p116_r35_attached_media_native_helper -v
python3 -m unittest tests.test_p116_r34_attached_media_offline_impl tests.test_p116_r33_offline_scalar_trace tests.test_p116_r32_call_bound_media_evidence -v
python3 -m unittest discover -s tests
python3 scripts/static_safety_check.py
python3 -m compileall research/media/v1/entrance_p116_r40h_registration_log_model.py research/media/v1/entrance_p116_r40h_official_app_readiness_model.py tests/test_p116_r40h_fresh_registration_liveness.py
cd ..
git diff --check
```

Baseline: the single pre-existing `NATIVE_BINARY_MODE` 755-vs-775 failure
(`test_p116_provenance_binary_analysis.P116ProvenanceBinaryAnalysisTests.test_committed_build_metadata_records_historical_non_runtime_mismatch`)
is reproduced unchanged at this round's base and is **not** fixed here — the same pre-existing,
content-unrelated filesystem-mode artifact every prior round has separated from its verdicts.

Hermes re-ran every check in section 12 after the executor handover (the draft's own PASS claims were
written before any run). Executed results:

* `python3 -m unittest tests.test_p116_r40h_fresh_registration_liveness` → `Ran 40 tests … OK`
  (before Hermes's two corrections this module had 5 failures: 4 `isinstance`-induced `UNPROVEN`s and 1
  docstring-matching hygiene assertion).
* `tests.test_p116_r40g_runtime_path_readiness`, `tests.test_p116_r40f_official_app_readiness_evidence`,
  `tests.test_p116_r40_official_app_readiness`, `tests.test_p116_r39_official_app_phone_capture` → `OK`.
* R37/R36/R35/R34/R33/R32 focused modules → `OK` (no lineage regression).
* `python3 -m unittest discover -s tests` → `Ran 1852 tests`, single failure = the legacy baseline above.
* `python3 scripts/static_safety_check.py` → `PASS` (`NETWORK_IMPORTS_PRESENT=false`,
  `COMELIT_ENDPOINTS_PRESENT=false`, 29 source files scanned).
* `python3 -m compileall` on both new modules and the new test module → clean.
* `git diff --check` → clean.

Scope check: this round wrote only under `safety-poc/research/media/v1/` (four new files) and
`safety-poc/tests/` (one new file). `custom_components/comelit/**`, the native production binary, and every
normative doc are untouched. No raw/decompiled evidence, APK, dex tree, native lib, or disassembly bundle was
copied into this repository — every citation above points at the pre-existing, git-excluded evidence
directories in place (R28's `.r28-evidence/`, R33's `.r33-evidence/`), not at bytes committed here.

Native tooling note: Hermes did generate a local, untracked working inventory of the already-saved
`libvipcomelit.so` under `/tmp/r40h-native/` (`nm -D`, `strings -a`, and an attempted `objdump -d`). The
host's `objdump` cannot disassemble this AArch64 object (empty output), so all instruction-level citations in
section 5 come from the pre-existing CT120-produced full disassembly in R33's `.r33-evidence/native-disasm/`,
which Hermes read directly to confirm the four `setsockopt` calls and their arguments. Nothing from
`/tmp/r40h-native/` was copied into the repository or appears in `git status`.

Privacy/leak scan: this document, both new modules and the test module were checked for IPv4-shaped strings,
hexdumps, and credential-like tokens (same regex families as prior rounds); none are present. The CT120/CT122
relay source tree and the excluded `oauth-evidence` directory were never read and are not cited anywhere in
this round's output. Synthetic log lines used in the test module contain only enum/status text
(`"VIP REGISTER CHANGED ..."`, `"VIPER SOCKET CONNECTION LOST"`) with no device identifiers, IPs, or tokens.

```text
=== COMELIT P116 R40H FRESH REGISTRATION / LIVENESS ===
BASE_R40G_SHA=b9ebcd04cb0e86e64af41666fe8e27d0fc191d2c
R40H_HEAD_SHA=NONE
EXECUTOR=claude-code-cli+hermes-primary
EXECUTOR_FALLBACK_USED=true
EXECUTOR_FALLBACK_AFTER_PARTIAL=true
EXECUTOR_FALLBACK_REASON=claude_usage_limit
CURRENT_REGISTERED_SUFFICIENT=false
FRESH_REGISTERED_TRANSITION_STRONGER=true
FRESH_REGISTRATION_ACCEPTED_TRANSITIONS=transition_into_REGISTERED_from_NONE_or_NOT_REGISTERED_or_REGISTERING
FRESH_REGISTRATION_PROVES_NEW_SESSION=PARTIAL
FRESH_LOG_CURSOR_METHOD=host-captured_pre_pause_monotonic_cursor_via_adb_logcat_-T_non_destructive
LOG_BUFFER_CLEAR_REQUIRED=false
REGISTRATION_READY_FRESH_SCALAR=entrance_p116_r40h_registration_log_model.evaluate_fresh_registration(...).registration_ready_fresh_scalar
MBOUND_LIFECYCLE=PROVEN
REGISTERED_BEFORE_MBOUND_POSSIBLE=true
MBOUND_CAN_DROP_WHILE_REGISTERED=true
RECEIVER_ARMED_SIGNAL=UNPROVEN
RECEIVER_ARMED_OBSERVABLE=false
FRESH_REGISTERED_IMPLIES_MBOUND=PARTIAL
FRESH_REGISTERED_IMPLIES_RECEIVER_ARMED=PARTIAL
NATIVE_KEEPALIVE_FOUND=PROVEN_PRESENT
NATIVE_KEEPALIVE_KIND=os_tcp_so_keepalive_direct_path_plus_app_level_ping_p2p_path
NATIVE_KEEPALIVE_INTERVAL_SECONDS=tcp_path_keepidle10_keepintvl20_keepcnt2_worst_case_50s_p2p_path_unproven
NATIVE_KEEPALIVE_FAILURE_ACTION=tcp_path_proven_viper_socket_reader_setreconnecting_not_registered_p2p_path_unproven
NATIVE_KEEPALIVE_UPDATES_REGISTER_STATUS=PARTIAL
SILENT_STALE_REGISTERED_RISK=MEDIUM
INDEPENDENT_LIVENESS_SIGNAL=viper_socket_reader_run_tag_viper_socket_connection_lost_log_line
INDEPENDENT_LIVENESS_OBSERVABLE=true
R40G_MODEL_SEMANTICS=TOO_PERMISSIVE
R41_PLAN_V3=READY
APP_READY_PROTOCOL_TIMEOUT_SECONDS=UNPROVEN
APP_READY_OPERATIONAL_TIMEOUT_POLICY=operator_supplied_bounded
APP_READY_OPERATIONAL_TIMEOUT_MAX_SECONDS=300
R41_V3_RUNNER_READY_TO_IMPLEMENT=true
NEXT_LIVE_AUTHORIZED=false
PHYSICAL_RING_COUNT=0
RING_BUDGET_CONSUMED=false
LISTENER_PAUSE_COUNT=0
LISTENER_RESUME_COUNT=0
ADB_LIVE_INVOCATIONS=0
NETWORK_TX_TO_COMELIT=0
DOOR_ACTIONS=0
GATE_ACTIONS=0
DEPLOYS=0
HA_RESTARTS=0
HA_RELOADS=0
PRODUCTION_FILES_CHANGED=0
NORMATIVE_DOCS_CHANGED=0
NATIVE_PRODUCTION_BINARY_CHANGED=false
FOCUSED_TESTS=PASS
R40G_REGRESSION=PASS
R40F_REGRESSION=PASS
R40_REGRESSION=PASS
R39_REGRESSION=PASS
FULL_OFFLINE_TESTS=PASS
STATIC_SAFETY=PASS
PR=NONE
MERGED=false
RESULT=PASS_R40H_FRESH_GATE
NEXT_STEP=A future round should (1) trace what, if anything, reads ViperTunnel offsets 304/312/320/328 to close the P2P-path native-keepalive-failure-action gap, (2) once explicitly authorized, implement the R41 v3 runner using entrance_p116_r40h_official_app_readiness_model.evaluate_readiness_v3 plus an adb-logcat-based reduce_raw_line/evaluate_fresh_registration reader as designed in CHILD B, still with RING_BUDGET_CONSUMED=false, and (3) if this project's hardware is ever observed connecting over VIPER_P2P rather than direct VIPER/VIPER_LOCAL, re-derive SILENT_STALE_REGISTERED_RISK specifically for that path before relying on the LOW figure this round found for the direct path.
=== END COMELIT P116 R40H FRESH REGISTRATION / LIVENESS ===
```
