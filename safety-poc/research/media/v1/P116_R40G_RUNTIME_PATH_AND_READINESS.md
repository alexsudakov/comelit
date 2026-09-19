# P116 R40G — Runtime Path (dex7↔dex9) and Readiness Closure

Round: `COMELIT-P116-R40G-RUNTIME-PATH-READINESS`. Mode: `RESEARCH_OFFLINE / DEV_OFFLINE`. `LIVE_INVOCATIONS=0`.
Base: exact R40F head `73ef4904155951d35b78b7c791dcab1978966782`. This document, an optional overlay model
(`entrance_p116_r40g_official_app_readiness_model.py`), the R41 contract successor
(`P116_R41_OFFICIAL_APP_READINESS_LIVE_PREFLIGHT_PLAN_V2.md`) and the focused tests are this round's
deliverables. `P116_R40F_OFFICIAL_APP_READINESS_EVIDENCE.md`, `entrance_p116_r40f_official_app_readiness_model.py`,
`P116_R40_OFFICIAL_APP_READINESS_CLOSURE.md`, `P116_R40_OFFICIAL_APP_READINESS_OFFLINE_PLAN.md`,
`entrance_p116_r40_official_app_readiness_model.py` and `P116_R41_OFFICIAL_APP_READINESS_LIVE_PREFLIGHT_PLAN.md`
are all unchanged and referenced, never rewritten.

## Executor provenance

```
EXECUTOR=claude-code-cli
EXECUTOR_FALLBACK_USED=false
```

Hermes (the orchestrator) owns git (add/commit/push), the worktree/branch, and independently reruns every
verification command below. No git command of any kind was run by this executor.

## 0. Why this round exists

R40F proved `APP_READY_INTERNAL_STATE=ComelitStatus.RegisterStatus.REGISTERED`, `UI_READY_SIGNAL=PROVEN`
(`ToolbarDeviceConnectionStatus.CONNECTED`) and the mechanical chain `REGISTERED` ->
`ToolbarUtilsKt.asToolbarConnectionStatus` -> `CONNECTED` -> door-entry toolbar, entirely from the dex7
`com.comelit.bigapp.*` ("BigApp" legacy engine) namespace. It explicitly left open whether that chain and
the dex9 `com.comelitgroup.sdk.*` namespace (`ComelitSDKAndroid`, `CallService`, `CallManager`,
`ComelitNotification.CallStart`) previously cited by R28 are the same runtime path or two parallel
implementations in the same APK — CHILD A below answers that question with real call/import evidence, not
"same APK ⇒ same path" inference, and the answer reshapes CHILD B/D/E.

## 1. CHILD A — dex7 ↔ dex9 runtime ownership

`DEX7_DEX9_RUNTIME_RELATION=BRIDGED_SUBSYSTEMS` (neither `SAME_PATH_PROVEN` nor cleanly
`PARALLEL_IMPLEMENTATIONS` — the two namespaces share one Android `Service`/`Activity` target and one
app-level SDK-init call site, but the actual **CallStart-triggering** mechanism is selected per-system, not
shared).

**The bridge that exists.** `ComelitApplication.onCreate()` (dex7,
`dex7/sources/com/comelit/bigapp/application/ComelitApplication.java` line ~404-406, app-process-global,
runs once) calls `ComelitSDK.INSTANCE.initialize(...)` then
`ComelitSDKAndroid.configureForIncomingCalls$default(ComelitSDK.INSTANCE, comelitApplication2,
VipCallActivity.class, ..., getString(R.string.call_in), new CallStartNotificationConfiguration(...), ...)`.
`VipCallActivity` is the dex7 legacy engine's own call-UI `Activity`
(`dex7/sources/com/comelit/bigapp/call/VipCallActivity.java`) — the dex9 SDK is configured, at app startup,
to launch **that same dex7 Activity** as its `callActivityClass` (`ComelitSDKAndroid.java`,
`configureForIncomingCalls`, sets `IncomingCallModuleConfiguration` and registers a `PhoneAccountHandle` for
`CallService.class`). This is the one real, load-bearing, cited bridge point: both namespaces converge on
the same call-UI Activity and the same one-time SDK bootstrap, regardless of which system type is active.

**The runtime switch that is not a bridge.** `ComelitFirebaseMessagingService.onMessageReceived(RemoteMessage)`
(dex7, `dex7/sources/com/comelit/bigapp/notification/ComelitFirebaseMessagingService.java` lines ~149-197)
is the actual OS entry point for a push-delivered `CallStart`. It parses the FCM payload
(`ComelitNotificationParserKt.parse`) into a `ComelitNotification.CallStart`, looks up the target
`Systems` row, and branches on `Systems.isLegacySystem()` (`Systems.java` line 183:
`public boolean isLegacySystem() { return getApartmentId() == null; }`):

* **Non-legacy** (`apartmentId != null` — a cloud-registered VIP unit): calls
  `ComelitSDKKt.handleNotification(ComelitSDK.INSTANCE, callStartCopy$default)` (dex9,
  `dex9/sources/com/comelitgroup/sdk/incomingcall/ComelitSDKKt.java`) ->
  `ComelitSDKAndroid.handleCallStartNotification` (dex9) -> `TelecomManager.addNewIncomingCall` ->
  `CallService.onCreateIncomingConnection` (dex9, `CallService.java`) -> `CallRegistry.INSTANCE.register` +
  `CallManager.INSTANCE.createCall(endpointId, callerName, callId, buttons)` (dex9). `CallStart` here
  originates entirely from a Firebase push message; `ComelitStatus.RegisterStatus` (the legacy VIP-tunnel
  state R40F traced) is never read anywhere in this branch.
* **Legacy** (`apartmentId == null` — the on-premise/direct VIP-tunnel unit class):
  `!systemByProfileId.isLegacySystem()` is `false`, so this branch is skipped entirely; the push handler
  falls through to `postComelitSDKNotification`, which only builds a plain local Android `Notification`
  (`ComelitNotificationBuilder`) — it does **not** call `CallService`/`CallManager`/`Telecom` for this
  system class. The actual "an inbound call now exists" signal for a legacy system arrives over the
  **native JSON-socket bridge** `ReadFromJsonSocket` already cited by R40F: the same `run()` loop that
  parses `subunit_fsm_status_change` (registration transitions) also parses `call_event` / `cfp_event` /
  `call_fsm_status_change` messages and dispatches them via `forwardCallEvent(type, jObj)` ->
  `this.mService.handleCallFsmStatusChange(...)` / `handleCallErrorEvent(...)` on the bound `ComelitService`
  (`ReadFromJsonSocket.java` lines ~260-357, `forwardCallEvent` ~524-560) — feeding the native `CallFsm`
  chain R37/R40F already traced (`VipUnitImpl::new_call_ctp_conn` -> `handleCtpStart` ->
  `vip_unit_accept_call` -> `CallFsm::enqueueEvent` -> ... -> `VipCallActivity`).

`DEX7_TO_DEX9_BRIDGE=ComelitFirebaseMessagingService.onMessageReceived branches on Systems.isLegacySystem()
(apartmentId==null); non-legacy routes to ComelitSDKKt.handleNotification -> ComelitSDKAndroid ->
CallService/CallManager (dex9, Telecom, FCM-push-triggered); legacy falls through to a local notification
only. Both system classes converge on the shared VipCallActivity registered once at app startup by
ComelitApplication.onCreate via ComelitSDKAndroid.configureForIncomingCalls.`

`CALLSTART_ORIGIN_PATH=system-class-dependent. For the legacy VIP-tunnel class (apartmentId==null) that
R28/R33/R37/R40F's entire RegisterStatus/ComelitEngineConnector/CallFsm chain describes -- and which this
project's on-premise CT120/CT122 hardware class matches -- CallStart is native-JSON-socket-driven
(ReadFromJsonSocket.forwardCallEvent -> ComelitService.handleCallFsmStatusChange -> native CallFsm),
independent of Firebase push and independent of dex9's CallService/CallManager. For a cloud/apartmentId-
registered system, CallStart instead arrives via Firebase push -> ComelitSDKAndroid/CallService/CallManager
(dex9, Telecom-based), independent of ComelitStatus.RegisterStatus.`

**Why this matters for R40F.** R40F's whole `RegisterStatus.REGISTERED` -> `ToolbarDeviceConnectionStatus.CONNECTED`
chain is real and load-bearing **only for the legacy system class** — for a hypothetical cloud/apartmentId
system, `RegisterStatus` is irrelevant to whether that system's `CallStart` pipeline (dex9, push-triggered)
can fire at all. R40F's model did not state this scope boundary explicitly; CHILD E below addresses it.

## 2. CHILD B — REGISTERED → inbound call capability

`REGISTERED_IMPLIES_RECEIVER_ARMED=PARTIAL` (same verdict word as R40's/R40F's `CALL_RECEIVER_PRECONDITIONS`,
now backed by a concrete same-object/same-thread proof plus one newly identified, real gap).

**What is now proven, not just architecturally plausible.** `JsonServerSocketMng` accepts a connection and
constructs exactly one `ReadFromJsonSocket` per accepted socket
(`dex7/sources/com/comelit/bigapp/application/jsonsocket/JsonServerSocketMng.java` line 77). That single
`Runnable`'s `run()` loop is the **same** code that (a) parses `subunit_fsm_status_change` and sets
`ComelitStatus.setEngineVipRegStatus(REGISTERED)` directly in its own dispatch switch, and (b) parses
`call_event`/`call_fsm_status_change` and calls `forwardCallEvent`. This is not "the same socket carries
both message types" as an architectural inference — it is the same `Runnable` instance, same thread, same
`while` loop, same `switch` on `strOptString5`. Observing `RegisterStatus.REGISTERED` therefore proves the
exact object that would parse the next inbound `call_event` already exists and is actively reading.

**The real gap this round found.** `forwardCallEvent` opens with `if (!this.mBound || callErrorEvt == null)
return;` (`ReadFromJsonSocket.java`, `forwardCallEvent`) — it silently drops the event (no retry, no log
visible to the operator beyond the parse itself) unless `this.mBound` is `true`. `mBound` is set
asynchronously, from `ServiceConnection.onServiceConnected` (`ReadFromJsonSocket.java` constructor calls
`bindService()`, which is inherently async per the Android `bindService` contract), not from the
`RegisterStatus` state machine. The `subunit_fsm_status_change` branch that sets `REGISTERED` does **not**
check `mBound` — so it is theoretically possible for `RegisterStatus` to reach `REGISTERED` in the brief
window before `onServiceConnected` has fired, in which case an inbound `call_event` arriving in that exact
window would be silently dropped by `forwardCallEvent`'s guard rather than reaching `CallFsm`. No code path
re-delivers a dropped event once `mBound` later becomes `true`. This is a genuine `STATE_PRESENT` (`RegisterStatus==REGISTERED`)
vs. `RECEIVER_ARMED` (`mBound==true`) distinction with a real, cited, asynchronous seam between them — not
merely "the native call-scoped gates apply after a call object exists" (R40F's framing).

`CALL_RECEIVER_PRECONDITIONS=PARTIAL`: `STATE_PRESENT` (REGISTERED) is proven; `RECEIVER_ARMED` (mBound and
the call-scoped `CallFsm`/`RtpDispatcher` native gates R37 already found) is not independently observable
from Java alone and is not guaranteed to co-occur with `REGISTERED` in the narrow bind-race window identified
above. In practice the `JsonServerSocketMng.start(context)` call happens in `ComelitEngineConnector`'s
constructor, before `createSystemFromSettings()` (which drives `REGISTERING`/`REGISTERED`) is invoked, so the
`bindService()` call and the registration-status messages both originate after the socket exists — but
`bindService()`'s completion is still asynchronous relative to message parsing on the same thread, and this
round found no explicit synchronization between the two.

## 3. CHILD C — safe machine readiness scalar

`REGISTRATION_READY_SCALAR_SOURCE=existing production Android logcat line: Log.i(TAG="ComelitStatus", "VIP
REGISTER CHANGED " + old + " -> " + new) (ComelitStatus.setEngineVipRegStatus, ComelitStatus.java line
~213)`. `REGISTRATION_READY_SCALAR_FEASIBLE=true`.

Traced the app's custom `com.comelitgroup.logger.Log` wrapper
(`dex8/sources/com/comelitgroup/logger/Log.java`) to its default logger list: `listOf(new PlatformLogger())`.
`PlatformLogger` (`dex8/sources/com/comelitgroup/logger/PlatformLogger.java`) implements every level as a
direct, unconditional call to `android.util.Log.{e,w,i,d,v}` — i.e. this is not an internal-only or
debug-build-gated sink; as shipped, this line reaches the standard Android log buffer in the production
build this repository's evidence was extracted from.

| OPTION | SOURCE | REQUIRES_APP_MODIFICATION | REQUIRES_ADB | REQUIRES_ROOT | EXPOSES_SECRETS_RISK | CAN_REDUCE_TO_SAFE_BOOLEAN | LIVE_FUTURE_FEASIBLE |
|---|---|---|---|---|---|---|---|
| **Existing logcat line (chosen)** | `Log.i("ComelitStatus", "VIP REGISTER CHANGED ...")` via `android.util.Log`, readable with `adb logcat -s ComelitStatus:I` | false | true | false | false — only enum names (`NONE`/`NOT_REGISTERED`/`REGISTERING`/`REGISTERED`), no token/SDP/session data | true — `"registered" in line` | true, least invasive |
| StateFlow/LiveData in-process read (`ComelitFlowStatus.vipConnectionStatus`/`vipConnectionStatusLiveData`) | same field, but only readable from inside the app's own process | true (would need injected code or a debug build to expose it) | maybe (to push a debug APK) | false | false | true, but strictly more invasive than the log line | possible, not preferred |
| Frida/Xposed hook on `ComelitStatus.setEngineVipRegStatus` | native runtime instrumentation | true (instrumentation counts as modification of the running app) | true | often true (Frida server / Xposed typically need root or a patched app) | low if scoped to the enum value only, but the hook mechanism itself is far more invasive | true | explicitly deprioritized per this round's instruction |
| Existing debug/export/status UI in the app | none found — `grep` across `dex7/8/9` for a settings/about screen literally printing `RegisterStatus` text found no hit beyond the toolbar icon (CHILD B) itself | n/a | n/a | n/a | n/a | false this round (no such UI exists) | not available |

`APP_MODIFICATION_REQUIRED=false`, `ADB_REQUIRED=true`, `ROOT_REQUIRED=false`. The least invasive future path
is exactly what CHILD C asked to prefer: an **existing, unmodified, production log line**, read via `adb
logcat` on a device with USB debugging enabled — no Frida, no Xposed, no APK patch, no root. This round does
**not** implement that live reader; it only establishes that it is feasible and safe (a plain boolean
derivable from an already-redacted enum name, matching R40F's `registration_ready_seen: Optional[bool]`
scalar exactly).

## 4. CHILD D — staleness / false-positive analysis

`UI_CONNECTED_STALENESS_RISK=MEDIUM` (unchanged word from R40F's implicit framing, now backed by a concrete
mechanism analysis and one concrete unresolved gap).

**The toolbar is live-bound, not a stale snapshot.** `DoorEntryContentFragment.initObserver()`
(`dex7/sources/com/comelit/bigapp/fragment/doorentry/DoorEntryContentFragment.java` lines ~149-155)
registers `ComelitFlowStatus.INSTANCE.getVipConnectionStatusLiveData().observe(getViewLifecycleOwner(), ...)`,
and the observer callback (`lambda$initObserver$0`) calls `initToolbar()` on every emission — which rebuilds
the toolbar action via `ToolbarUtils.defaultVipConnectionStatusAction(this)`, re-reading
`ComelitStatus.getEngineVipRegStatus()`. Because `notifyVipConnectionChange` (called from
`ComelitStatus.setEngineVipRegStatus`, same setter CHILD A/B traced) drives this same `LiveData`, any
`REGISTERED -> NOT_REGISTERED` transition (e.g. `ViperSocketReaderRunnable.setReconnecting()` on socket
EOF/error) propagates to the toolbar icon on the main thread, synchronously with the state change, bound to
the fragment's view lifecycle — this is not an extra, app-introduced staleness layer; there is no polling
delay and no need to leave/reopen the screen.

**The real staleness source: silent transport death.** `ViperSocketReaderRunnable.run()`
(`dex7/sources/com/comelit/bigapp/viper/ViperSocketReaderRunnable.java`) is a blocking loop:
`this.fis.read(bArr)`; a return of `i < 0` or an `IOException` triggers `setReconnecting()` ->
`ComelitStatus.setEngineViperStatus(CLOSED)` + `setEngineVipRegStatus(NOT_REGISTERED)`, synchronously, on the
same thread. This detection is correct **but only fires on an actual OS-level read error or EOF** (e.g. a
FIN/RST from the peer). This round searched the available Java sources
(`ComelitEngineConnector.java`, `ViperSocketReaderRunnable.java`, `ReadFromJsonSocket.java`) and the R33/R29a
native-disassembly symbol inventories for any keepalive/heartbeat/ping/watchdog mechanism on this specific
tunnel and found **none** — `NATIVE_KEEPALIVE_FOUND=UNPROVEN` (not `false`: the available native-disasm sets
are small, targeted symbol lists from prior rounds' specific searches, not a full disassembly of
`libvipcomelit.so`, so absence-of-evidence is not proof of absence here). If the underlying transport goes
silently unreachable (radio silence, NAT/firewall timeout with no FIN/RST delivered, remote power loss)
without ever producing a read error, `RegisterStatus`/the toolbar icon could remain `REGISTERED`/`CONNECTED`
indefinitely with no code path to correct it — a real, evidenced blind spot, not fixed by this round
(fixing it would require either native-side keepalive evidence this round could not access, or a live
instrumented test, both out of scope for `RESEARCH_OFFLINE`).

`DUAL_SIGNAL_GATE_REQUIRED=true`, **with an important caveat this round surfaces**: the "machine signal"
(`registration_ready_seen`, `ComelitFlowStatus.vipConnectionStatus`) and the UI signal
(`ToolbarDeviceConnectionStatus.CONNECTED`) are reads of **the same underlying static field**
(`ComelitStatus.regStatus`), not independent corroboration. Sampling both at the same instant cannot detect
the silent-transport-death case above — a stuck stale value reads as `CONNECTED` and
`registration_ready_seen=True` simultaneously. Genuine independent corroboration (e.g., proof the transport
itself is still alive, independent of this one Java-side field) remains `UNPROVEN` this round. What the dual
gate *does* still protect against — and the reason it should stay required — is an operator/tooling
transcription error (misreading or mis-plumbing the UI label independent of the underlying field), which is
a different, real failure mode from staleness.

## 5. CHILD E — R40F model review

`R40F_MODEL_SEMANTICS=PARTIAL`.

The `registration_ready_seen: Optional[bool]` / `None`-degrades-to-UI-only semantics in
`entrance_p116_r40f_official_app_readiness_model.py` remains correct given the evidence available to R40F
and is not contradicted by CHILD A-D: with no live instrumentation, `None` degrading to the UI-only signal is
still the only offline-honest default. Two real gaps this round found, neither cosmetic:

1. **Undocumented scope boundary (CHILD A).** R40F's model implicitly treats `RegisterStatus`/`CONNECTED` as
   *the* readiness gate for "the official app," without stating that this is true **only for the legacy
   (`apartmentId == null`) VIP-tunnel system class** — a cloud/apartmentId-registered system's `CallStart`
   pipeline (dex9, Firebase-push-triggered) does not read `RegisterStatus` at all, so the model would silently
   describe the wrong subsystem if ever pointed at that system class. This project's hardware class (an
   on-premise CT120/CT122 VIP unit) matches the legacy class the model already covers, but the model itself
   does not say so.
2. **Overstated corroboration independence (CHILD D).** The model's reason strings
   (`connected_ui_confirmed_by_machine_signal_listener_paused_...`) read as if `registration_ready_seen` were
   an independent second signal. CHILD D shows it is the same field as the UI read, so "confirmed by machine
   signal" should not be read as ruling out the silent-staleness case CHILD D identified.

Per this round's instruction not to rewrite R40F's file, `entrance_p116_r40g_official_app_readiness_model.py`
is added as a narrow overlay: it wraps R40F's `ReadinessObservation`/`evaluate_readiness` unchanged (no
duplicated logic) and adds one explicit, load-bearing precondition — an `AppSystemClass` gate that must be
`LEGACY_VIP` for the evaluation to proceed at all, returning `UNPROVEN` with an explicit reason otherwise —
plus a corrected reason string for the machine-signal case that names it a same-field re-read, not
independent corroboration. R40F's own file, model and tests are untouched and still pass unmodified.

## 6. CHILD F — R41 contract v2

`P116_R41_OFFICIAL_APP_READINESS_LIVE_PREFLIGHT_PLAN_V2.md` is added (new file, R41 v1 untouched). It
replaces the abstract `OperatorAppState.OPERATOR_CONFIRMED_USABLE` sampling step with the concrete
`ToolbarDeviceConnectionStatus.CONNECTED` read on `DoorEntryContentFragment`, calls
`entrance_p116_r40g_official_app_readiness_model.evaluate_readiness_v2` (which requires the
`AppSystemClass.LEGACY_VIP` precondition CHILD E added and then delegates to R40F's proven gate logic), and
states the `mBound`/silent-staleness caveats from CHILD B/D as explicit preflight limitations rather than
silently assuming them away. It remains a NO-RING PREFLIGHT contract; no runner is created in R40G.

## 7. CHILD G — bounded timeout policy

`APP_READY_PROTOCOL_TIMEOUT_SECONDS=UNPROVEN` (unchanged — this round re-confirmed, via the raw
`ComelitEngineConnector`/`ReadFromJsonSocket` sources, that no numeric backoff/retry-interval constant exists
for VIP **registration** specifically; call-scoped `CallFsm` timers are a different domain, as R40/R40F
already established).

`APP_READY_OPERATIONAL_TIMEOUT_POLICY`: the R41 v2 preflight must use an explicit, operator-approved
`OPERATIONAL_APP_READY_TIMEOUT_SECONDS` chosen at authorization time — never a value this document supplies
as expected latency. A **safety bound** (not a latency estimate) is derivable from the existing listener
failsafe: R39/R40 already establish and cite a proven **300 s continuous-down** failsafe autoreset threshold
(`P116_R39_OFFICIAL_APP_PHONE_CAPTURE.md` section 4, `P116_R40_OFFICIAL_APP_READINESS_CLOSURE.md` section 5).
Any operator-chosen readiness-sampling timeout for a paused-listener preflight must stay **strictly below**
that 300 s threshold with margin, or the failsafe's own autonomous action could race the preflight's own
"restore listener first" step. `APP_READY_OPERATIONAL_TIMEOUT_MAX_SECONDS=300` is recorded as a ceiling
derived from that cited constant, not as a proven safe operating value — the actual operator-chosen number
must leave headroom below it (this round does not assert a specific margin, since no evidence bounds how
fast the failsafe reacts once triggered).

## 8. CHILD H — R41 implementation readiness

`R41_RUNNER_READY_TO_IMPLEMENT=true`. `R41_MACHINE_CORROBORATION_AVAILABLE=PARTIAL`.

All the pieces CHILD H asks for are now known: the exact UI signal (`ToolbarDeviceConnectionStatus.CONNECTED`
on `DoorEntryContentFragment`, CHILD B/D of R40F), how the operator reports it (a direct read of that toolbar
icon), the already-proven listener pause/resume mechanics and failsafe mechanics (R40/R41 v1, unchanged), an
explicit operator-supplied timeout bounded per CHILD G above, the zero-ring invariant (R41 v1 section 4,
unchanged), restoration ordering (listener first, R41 v1 section 3), and a safe result schema
(`PASS_APP_READY_PREFLIGHT` / `BLOCKED_APP_NOT_READY`, both `RING_BUDGET_CONSUMED=false`). Machine
corroboration is `PARTIAL`, not `true`: CHILD C proved a feasible, safe, no-modification logcat scalar exists,
but CHILD D proved it is not independent of the UI signal, so its presence upgrades transcription-error
protection, not staleness protection. `R41_RUNNER_READY_TO_IMPLEMENT=true` records only that the **contract**
is fully specified; no runner is created this round.

## 9. Evidence ledger

| SOURCE_KIND | FILE | SYMBOL_OR_METHOD | LINE_RANGE | CLAIM | CONFIDENCE |
|---|---|---|---|---|---|
| dex | `dex7/sources/com/comelit/bigapp/application/ComelitApplication.java` | `onCreate` | ~L395-406 | App-startup bridge: `ComelitSDKAndroid.configureForIncomingCalls` registers dex7's `VipCallActivity.class` as dex9 SDK's call-UI target | HIGH — direct source read |
| dex | `dex7/sources/com/comelit/bigapp/notification/ComelitFirebaseMessagingService.java` | `onMessageReceived` | ~L149-197 | FCM push -> `isLegacySystem()` branch: non-legacy routes to `ComelitSDKKt.handleNotification`, legacy falls through to a local notification only | HIGH — direct source read |
| dex | `dex7/sources/com/comelit/bigapp/model/Systems.java` | `isLegacySystem` | L183-184 | `isLegacySystem() == (getApartmentId() == null)` — the exact runtime switch | HIGH — direct source read |
| dex | `dex9/sources/com/comelitgroup/sdk/incomingcall/ComelitSDKKt.java` | `handleNotification` | full file | Dispatches `CallStart` to `ComelitSDKAndroid.handleCallStartNotification` (dex9 SDK path only) | HIGH — direct source read |
| dex | `dex9/sources/com/comelitgroup/sdk/incomingcall/CallService.java` | `onCreateIncomingConnection` | full file | Telecom-based incoming-connection handler, calls `CallManager.INSTANCE.createCall`; entirely independent of `ComelitStatus` | HIGH — direct source read |
| dex | `dex7/sources/com/comelit/bigapp/application/jsonsocket/JsonServerSocketMng.java` | constructor call site | L77 | One `ReadFromJsonSocket` per accepted socket — same object parses both registration and call events | HIGH — direct source read |
| dex | `dex7/sources/com/comelit/bigapp/application/jsonsocket/ReadFromJsonSocket.java` | `forwardCallEvent`, `mBound`, `ServiceConnection` | ~L57-66, L524-560 | `forwardCallEvent` silently drops events unless `mBound==true`; `mBound` set asynchronously via `bindService`/`onServiceConnected`, independent of `RegisterStatus` | HIGH — direct source read |
| dex | `dex7/sources/com/comelit/bigapp/viper/ViperSocketReaderRunnable.java` | `run`, `setReconnecting` | full file | Synchronous same-thread `NOT_REGISTERED` transition on read EOF/error; no keepalive/heartbeat visible in this file | HIGH — direct source read |
| dex | `dex7/sources/com/comelit/bigapp/fragment/doorentry/DoorEntryContentFragment.java` | `initObserver`, `lambda$initObserver$0`, `getToolbarRightActions` | ~L149-167, L566 | Toolbar is live-bound to `ComelitFlowStatus.vipConnectionStatusLiveData` via `getViewLifecycleOwner()`, not a one-shot snapshot | HIGH — direct source read |
| dex | `dex7/sources/com/comelit/bigapp/application/ComelitStatus.java` | `setEngineVipRegStatus` | ~L209-215 | `Log.i("ComelitStatus", "VIP REGISTER CHANGED " + old + " -> " + new)` fires on every transition | HIGH — direct source read |
| dex | `dex8/sources/com/comelitgroup/logger/Log.java` | `i`, `initialize` | full file | Custom logger dispatches to a configurable `Logger` list, default `listOf(PlatformLogger())` | HIGH — direct source read |
| dex | `dex8/sources/com/comelitgroup/logger/PlatformLogger.java` | `i`, `e`, `w`, `d`, `v` | full file | Each level is an unconditional call to `android.util.Log.*` — standard logcat, no build-gate visible | HIGH — direct source read |
| native_disasm | `.r33-evidence/native-disasm/symbol-inventory.txt` | (absence check) | full file (49 lines) | No keepalive/heartbeat/ping/watchdog symbol present in this round's available (small, targeted) native symbol set | MEDIUM — targeted inventory, not a full `.so` disassembly; absence is not proof of absence |
| prior_doc | `P116_R39_OFFICIAL_APP_PHONE_CAPTURE.md` section 4 / `P116_R40_OFFICIAL_APP_READINESS_CLOSURE.md` section 5 | — | n/a | Proven 300 s continuous-down listener-failsafe threshold, reused as CHILD G's safety-bound ceiling, not derived fresh this round | HIGH — cited, previously-verified constant |

## 10. Verification

Commands run in this worktree (`safety-poc/` as working directory unless noted):

```bash
cd safety-poc
python3 -m unittest tests.test_p116_r40g_runtime_path_readiness -v
python3 -m unittest tests.test_p116_r40f_official_app_readiness_evidence -v
python3 -m unittest tests.test_p116_r40_official_app_readiness -v
python3 -m unittest tests.test_p116_r39_official_app_phone_capture -v
python3 -m unittest tests.test_p116_r37_attached_media_live_readiness tests.test_p116_r36_attached_media_trigger tests.test_p116_r35_attached_media_native_helper -v
python3 -m unittest tests.test_p116_r34_attached_media_offline_impl tests.test_p116_r33_offline_scalar_trace tests.test_p116_r32_call_bound_media_evidence -v
python3 -m unittest discover -s tests
python3 scripts/static_safety_check.py
python3 -m compileall research/media/v1/entrance_p116_r40g_official_app_readiness_model.py tests/test_p116_r40g_runtime_path_readiness.py
cd ..
git diff --check
```

Baseline: the single pre-existing `NATIVE_BINARY_MODE` 755-vs-775 failure
(`test_p116_provenance_binary_analysis.P116ProvenanceBinaryAnalysisTests.test_committed_build_metadata_records_historical_non_runtime_mismatch`)
is reproduced unchanged at this round's base and is **not** fixed here — the same pre-existing,
content-unrelated filesystem-mode artifact R35/R36/R37/R40/R40F already separated from their verdicts.

Scope check: this round wrote only under `safety-poc/research/media/v1/` (three new files) and
`safety-poc/tests/` (one new file). `custom_components/comelit/**`, the native production binary, and every
normative doc are untouched. No raw/decompiled evidence, APK, dex tree, native lib, or disassembly bundle was
copied into this repository — every citation above points at the pre-existing, git-excluded evidence
directories in place (`/home/hermes/worktrees/comelit-p116-r28/.r28-evidence/`, the R33 evidence tree, and
the R29a native-disasm set), not at bytes committed here.

Privacy/leak scan: this document, the overlay model, the R41 v2 contract and the test module were checked
for IPv4-shaped strings, hexdumps, and credential-like tokens (same regex families as R39/R40/R40F); none are
present. The CT120/CT122 relay source tree and the excluded `oauth-evidence` directory were never read and
are not cited anywhere in this round's output.

```text
=== COMELIT P116 R40G RUNTIME PATH / READINESS ===
BASE_R40F_SHA=73ef4904155951d35b78b7c791dcab1978966782
R40G_HEAD_SHA=NONE
EXECUTOR=claude-code-cli
EXECUTOR_FALLBACK_USED=false
EXECUTOR_FALLBACK_REASON=NONE
DEX7_DEX9_RUNTIME_RELATION=BRIDGED_SUBSYSTEMS
DEX7_TO_DEX9_BRIDGE=ComelitFirebaseMessagingService.onMessageReceived branches on Systems.isLegacySystem (apartmentId==null); non-legacy routes to ComelitSDKKt.handleNotification->ComelitSDKAndroid->CallService/CallManager (dex9, FCM-push-triggered); legacy falls through to a local notification only; both converge on the shared VipCallActivity registered by ComelitApplication.onCreate
CALLSTART_ORIGIN_PATH=system-class-dependent: legacy (apartmentId==null, this project's hardware class) uses native JSON-socket call_event via ReadFromJsonSocket.forwardCallEvent->ComelitService->CallFsm; cloud/apartmentId-registered systems use Firebase push->ComelitSDKAndroid/CallService/CallManager (dex9), independent of ComelitStatus.RegisterStatus
REGISTERED_IMPLIES_RECEIVER_ARMED=PARTIAL
CALL_RECEIVER_PRECONDITIONS=PARTIAL
REGISTRATION_READY_SCALAR_SOURCE=existing production logcat line Log.i(TAG=ComelitStatus, "VIP REGISTER CHANGED ...") via PlatformLogger->android.util.Log, readable with adb logcat -s ComelitStatus
REGISTRATION_READY_SCALAR_FEASIBLE=true
APP_MODIFICATION_REQUIRED=false
ADB_REQUIRED=true
ROOT_REQUIRED=false
UI_CONNECTED_STALENESS_RISK=MEDIUM
DUAL_SIGNAL_GATE_REQUIRED=true
R40F_MODEL_SEMANTICS=PARTIAL
R41_PLAN_V2=READY
APP_READY_PROTOCOL_TIMEOUT_SECONDS=UNPROVEN
APP_READY_OPERATIONAL_TIMEOUT_POLICY=explicit operator-approved bound at authorization time, safety bound only, never an expected-latency estimate
APP_READY_OPERATIONAL_TIMEOUT_MAX_SECONDS=300
R41_RUNNER_READY_TO_IMPLEMENT=true
R41_MACHINE_CORROBORATION_AVAILABLE=PARTIAL
NEXT_LIVE_AUTHORIZED=false
PHYSICAL_RING_COUNT=0
RING_BUDGET_CONSUMED=false
LISTENER_PAUSE_COUNT=0
LISTENER_RESUME_COUNT=0
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
R40F_REGRESSION=PASS
R40_REGRESSION=PASS
R39_REGRESSION=PASS
FULL_OFFLINE_TESTS=PASS
STATIC_SAFETY=PASS
PR=NONE
MERGED=false
RESULT=PARTIAL_R40G_RUNTIME_PATH
NEXT_STEP=A future round should (1) obtain a fuller native disassembly of libvipcomelit.so specifically searching for a keepalive/heartbeat/watchdog symbol on the VIP tunnel to resolve CHILD D's NATIVE_KEEPALIVE_FOUND=UNPROVEN, (2) if this project's hardware is ever paired via a cloud/apartmentId-registered account rather than the on-premise/legacy class, re-derive readiness against the dex9 CallService/CallManager path instead of ComelitStatus.RegisterStatus, and (3) once explicitly authorized, implement the R41 v2 runner using entrance_p116_r40g_official_app_readiness_model.evaluate_readiness_v2 and an adb-logcat-based registration_ready_seen reader as designed in CHILD C, still with RING_BUDGET_CONSUMED=false.
=== END COMELIT P116 R40G RUNTIME PATH / READINESS ===
```
