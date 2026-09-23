# P116 R40F — Official-App Readiness, Re-Derived From Raw Recovered Evidence

Round: `COMELIT-P116-R40F-OFFICIAL-APP-READINESS-EVIDENCE`. Mode: `RESEARCH_OFFLINE / DEV_OFFLINE`.
`LIVE_INVOCATIONS=0`. This document, the `entrance_p116_r40f_official_app_readiness_model.py` overlay and
the focused tests are this round's deliverables. `P116_R40_OFFICIAL_APP_READINESS_CLOSURE.md`,
`P116_R40_OFFICIAL_APP_READINESS_OFFLINE_PLAN.md`, `entrance_p116_r40_official_app_readiness_model.py` and
`P116_R41_OFFICIAL_APP_READINESS_LIVE_PREFLIGHT_PLAN.md` are all unchanged and referenced, not rewritten.

## Executor provenance

```
EXECUTOR=claude-code-cli
EXECUTOR_SUBSTITUTION_AUTHORIZED_BY_USER=true
```

Claude Code CLI acted as the semantic implementation executor for R40F, dispatched directly (not a Codex
quota fallback this round). Hermes (the orchestrator) owns git (add/commit/push), the worktree/branch, and
independently reruns every verification command below. No git command of any kind was run by this executor.

## 0. Why this round exists, and what changed since R40

R40 (`P116_R40_OFFICIAL_APP_READINESS_CLOSURE.md`, SECTION 0) explicitly recorded that its executor's
worktree contained **none** of the raw decompiled `dex7/8/9` official-app source trees or native
disassembly — those directories are ephemeral, git-excluded analysis inputs that existed only on the
hosts/worktrees of the R28/R33/R36/R37 rounds that produced them. R40 could therefore only re-synthesize
already-promoted `Pxx` document citations; it explicitly named this an evidence gap, not a proof of absence.

R40E (a prior, separate recovery round) located and verified that those raw trees still exist, intact, on
this host:

* `RAW_R28_EVIDENCE_USED=true` — `/home/hermes/worktrees/comelit-p116-r28/.r28-evidence/official-app/`
  (`dex7/sources` 2899 files, `dex8/sources` 2908 files, `dex9/sources` 6497 files, `native-disasm/` 8
  files, `native-libs/` 3 files sha256-verified against CT120).
* `RAW_R33_EVIDENCE_USED=true` — `/home/hermes/repos/comelit-worktrees/p116-r33-primitive-closure/safety-poc/research/media/v1/.r33-evidence/`
  (`public-vip/viper/*.py`, `native-disasm/full-disasm-libvipcomelit.txt`, `native-disasm/symbol-inventory.txt`).
* Additional native disassembly sets at `.r29a-evidence/`, `.r29c-evidence/`, `.r29e-evidence/` (57 files
  each), used for the `VipUnitImpl::new_call_ctp_conn` disassembly cited in CHILD D below.

This round re-derives CHILD A/B/C/D/F directly from those raw sources — not from re-reading prior `Pxx`
document prose — and finds real, non-call-scoped, pre-call evidence that the earlier promoted documents had
missed because their own search ledgers (e.g. `P116_R28...md` SECTION 14) were scoped to the
`com.comelitgroup.sdk.incomingcall` / `CallService` / `CallManager` namespace (dex9) that R28's own dispatch
named as candidates. The actual pre-call registration/readiness machinery for the VIP door-entry unit lives
in a **different, older namespace** in the same APK: `com.comelit.bigapp.*` (dex7), the "BigApp" legacy
engine that the door-entry (`DoorEntryContentFragment`) screen itself uses. Nothing in R28–R39 ever searched
that namespace for readiness vocabulary; this round did, and found it.

## 1. CHILD A — pre-call app/SDK lifecycle

`CALL_RECEIVER_PRECONDITIONS=PARTIAL` (upgraded from R40's `PARTIAL` — same verdict word, materially more
of the chain now has direct evidence). `APP_READY_INTERNAL_STATE=ComelitStatus.RegisterStatus.REGISTERED`
(upgraded from R40's `UNPROVEN`).

Re-derived pre-call chain, all citations from raw `dex7/8/9` sources (not from prior `Pxx` prose):

```text
APP_PROCESS
  -> ComelitApplication (dex7/sources/com/comelit/bigapp/application/ComelitApplication.java, cited by
     HbEngine.java imports) / ComelitBaseService (Service, android.app.Service subclass) start
  -> SDK_INIT: com.comelitgroup.sdk.core.ComelitSDK.initialize(clientId, cloudEnvironment, tokenProvider,
     isDebug) -> internalInitialize$core_release -- logs "SDK initialized with clientId: ... cloud
     baseUrl: ..." (dex9/sources/com/comelitgroup/sdk/core/ComelitSDK.java)
     -- IN PARALLEL, the legacy engine's own init: ComelitEngineConnector(connectorType, engine, context)
     constructor calls engine.setAudioEncodeDecode/setUseEchoCanceller/... then starts
     JsonServerSocketMng.getInstance().start(context) if not already started
     (dex7/sources/com/comelit/bigapp/engine/managers/ComelitEngineConnector.java)
  -> AUTH/SESSION: com.comelitgroup.authentication.Authentication.initialize(authenticationMode, nimbus,
     group, onSignOut, authenticationMigration) -- loads persisted OAuth2/CCS tokens from
     ObservableSettings("comelit_authentication_storage"), starts TokenRefresherActor, migrates CCS->OAuth2
     if applicable; Authentication.signIn(email, password) / handleUrl(redirectUrl) exchange credentials
     for an OAuth2TokenResponse via com.comelitgroup.nimbus.oauth2.OAuth2Requester
     (dex7/sources/com/comelitgroup/authentication/Authentication.java, lines 375-453 initialize(); OAuth2
     classes in dex8/sources/com/comelitgroup/nimbus/oauth2/)
  -> VIP/CONNECTION REGISTRATION: ComelitEngineConnector.createSystemFromSettings() ->
     ComelitStatus.setEngineViperStatus(ViperStatus.OPENING); ComelitStatus.setEngineVipRegStatus(
     RegisterStatus.REGISTERING); VipCloudConnector.INSTANCE.connect(apartmentId, callback) [cloud/WebRTC
     path] -- or, for the direct-tunnel path, createSystemFromVip() ->
     connectionStrategy()/createSystemFromWizard() -> this.engine.createViperTunnel(mainSystemID, ...)
     (native, returns a file descriptor) -> new ViperSocketReaderRunnable(fd, engine, mainSystemID,
     context) on a dedicated Thread, pumping engine.addReceivedPacketFromSocket(sysId, bytes) from the
     native VIP engine's raw socket
     (dex7/sources/com/comelit/bigapp/engine/managers/ComelitEngineConnector.java lines 143-160, 224-400;
     dex7/sources/com/comelit/bigapp/viper/ViperSocketReaderRunnable.java)
     Native side (independently re-derived from disassembly, not dex): VipUnitImpl::new_call_ctp_conn
     (libvipcomelit.so @0x7d4bc) calls csp_recv into a csp_msgbuf, requiring an already-open CTP
     socket/session (the tunnel established above) before it can dispatch to handleCtpSetOutput or
     handleCtpStart -- i.e. the native CTP command dispatcher this round traced cannot run at all until
     the Java-side tunnel/registration chain above has already produced a live file descriptor.
  -> On success, the callback sets ComelitStatus.setEngineViperStatus(ViperStatus.OPEN);
     ComelitStatus.setEngineVipRegStatus(RegisterStatus.REGISTERED) -- and, independently, the native
     engine emits a bridged status event over the JSON control socket: a JSON message with
     `"subunit_fsm_status_change"` carrying field `subunit_fsm_status` in
     {"registering", "fail_wait", "registered"}, parsed by ReadFromJsonSocket and mapped 1:1 onto the same
     `ComelitStatus.RegisterStatus` enum (dex7/sources/com/comelit/bigapp/application/jsonsocket/ReadFromJsonSocket.java
     lines 260-270, 347-357). This is a genuine native-FSM-to-Java bridge event name, not dex-only prose.
  -> CALL NOTIFICATION RECEIVER ARMED: with RegisterStatus.REGISTERED, the same JSON socket / Viper
     channel that carried the registration event also carries `"call_event"` /
     `"call_fsm_status_change"` messages (forwardCallEvent, same switch statement in
     ReadFromJsonSocket.java) and the native chain independently re-confirmed by R28/R33/this round:
     VipUnitImpl::new_call_ctp_conn -> handleCtpStart -> vip_unit_accept_call -> CallFsm::enqueueEvent ->
     CallFsm::st_idle -> CallFsm::go_in_alerting -> CallFsm::start_videorx -> RtpDispatcher::startVideoRX
     (native-disasm/disasm-VipUnitImpl_new_call_ctp_conn.txt, disasm-CallFsm_*.txt, r29a-evidence set) --
     and, in the newer dex9 SDK namespace, ComelitNotification.CallStart ->
     ComelitSDKAndroid.handleCallStartNotification -> CallService.onCreateIncomingConnection ->
     CallManager.INSTANCE.createCall(...) (dex9/sources/com/comelitgroup/sdk/incomingcall/*, previously
     cited by R28).
  -> CallStart possible
```

`FAILURE_PATH` / `RETRY`/`BACKOFF` (UI/log-observable): `ViperSocketReaderRunnable.setReconnecting()` fires
on any socket read error or EOF -- sets `ViperStatus.CLOSED`, `RegisterStatus.NOT_REGISTERED`, and
broadcasts `ServiceBroadcastEventsEnum.CREATE_VIPER_CONNECTION` (unless the connector is in
`ConnectorType.WIZARD`, which instead broadcasts `ENGINE_RECONNECTION`) — both observable via `Log.e(TAG,
"VIPER SOCKET CONNECTION LOST")`. `ComelitEngineConnector.createSystemFromSettings`'s cloud callback sets
the same `ViperStatus.CLOSED` / `RegisterStatus.NOT_REGISTERED` pair on
`!vipCloudConnectionResult.isConnected()`. No numeric backoff/retry-interval constant for VIP
**registration** (as distinct from the already-known call-scoped `CallFsm` timers) was found anywhere in
this raw search — consistent with R40's CHILD E finding, now confirmed against the raw sources rather than
inferred from their absence in promoted documents.

`APP_READY_INTERNAL_STATE=ComelitStatus.RegisterStatus.REGISTERED` is a genuine, named, pre-call, non-call-
scoped internal state (`dex7/sources/com/comelit/bigapp/application/ComelitStatus.java`, static field
`regStatus`, enum `RegisterStatus {NONE, NOT_REGISTERED, REGISTERING, REGISTERED}`), directly refuting R40's
"no such pre-call state name ... was found" finding — that finding was correct given the evidence R40 had
access to (only dex9's `CallFsm`/`incomingcall` namespace), and is now superseded by this round's access to
dex7's `com.comelit.bigapp.application` namespace.

## 2. CHILD B — UI-observable readiness

`UI_READY_SIGNAL=PROVEN` (upgraded from R40's `NONE`). `UI_READY_SIGNAL_VALUE=ToolbarDeviceConnectionStatus.CONNECTED`.

| UI_LABEL_OR_ICON | SOURCE | INTERNAL_STATE | PRE_CALL | CALL_RECEIVE_CAPABILITY_IMPLIED | FALSE_POSITIVE_RISK |
|---|---|---|---|---|---|
| VIP toolbar connection icon: `NOT_CONNECTED` | `dex8/sources/com/comelitgroup/comelit_material_design/toolbar/ToolbarDeviceConnectionStatus.java`, rendered via `ToolbarUtils.defaultVipConnectionStatusAction` on `DoorEntryContentFragment` (`dex7/sources/com/comelit/bigapp/fragment/doorentry/DoorEntryContentFragment.java`) | `RegisterStatus.NONE` or `NOT_REGISTERED` | Yes — shown before any call exists | No | Low — direct 1:1 enum mapping, no heuristic |
| VIP toolbar connection icon: `CONNECTING` | same | `RegisterStatus.REGISTERING` | Yes | No | Low |
| VIP toolbar connection icon: `CONNECTED` | same | `RegisterStatus.REGISTERED` | Yes | **Yes** — this is the same internal state CHILD A traced as the precondition for the native CTP tunnel that `VipUnitImpl::new_call_ctp_conn` requires | Medium — the icon reflects the last-known `RegisterStatus`, which can theoretically go stale between the native socket closing and `ViperSocketReaderRunnable.setReconnecting()` detecting the EOF/error and pushing `NOT_REGISTERED`; this is a same-process, same-JVM state read with no network round-trip of its own, so the staleness window is bounded by how fast the reader thread notices a socket close, not by any external latency |

`SOURCE`: the mapping is exact and mechanical, not interpreted — `ToolbarUtilsKt.asToolbarConnectionStatus`
(`dex7/sources/com/comelit/bigapp/utilities/ToolbarUtilsKt.java`) is a compiler-generated `when` over
`ComelitStatus.RegisterStatus` with no other branches:
`NONE|NOT_REGISTERED -> NOT_CONNECTED`, `REGISTERING -> CONNECTING`, `REGISTERED -> CONNECTED`.
`ToolbarUtils.defaultVipConnectionStatusAction(fragment)` (`ToolbarUtils.java` lines 26-36) constructs this
action for `ToolbarDeviceType.VIP` by directly reading `ComelitStatus.getEngineVipRegStatus()` — the exact
static field CHILD A traced back to the native registration chain. `DoorEntryContentFragment` is the VIP
door-entry screen itself (found via `grep` for `defaultVipConnectionStatusAction`/`ToolbarDeviceType.VIP`
usage across `dex7`), not an unrelated screen — an operator opening the door-entry screen and reading this
exact toolbar icon is reading a value one level of indirection from the same native FSM chain that gates
`VipUnitImpl::new_call_ctp_conn`.

This satisfies R40F's CHILD B bar ("`UI_READY_SIGNAL=PROVEN` only if code shows the state precedes CallStart
capability"): the chain is `ComelitEngineConnector`/`ViperSocketReaderRunnable` (registration, no call
object exists yet) -> `ComelitStatus.RegisterStatus` -> `ToolbarUtilsKt.asToolbarConnectionStatus` ->
toolbar icon, entirely independent of any `CallStart`/`CallFsm`/`CallManager` code path. No label was
invented; the exact cited enum values above are the only strings this round asserts an operator can read.

## 3. CHILD C — machine-observable readiness

`MACHINE_READY_SIGNAL=ComelitStatus.RegisterStatus.REGISTERED` (upgraded from R40's `UNPROVEN`).
`MACHINE_READY_SIGNAL_SOURCE=ComelitFlowStatus.vipConnectionStatus` (StateFlow) /
`ComelitFlowStatus.vipConnectionStatusLiveData` (LiveData). `NETWORK_READY_SIGNAL=PARTIAL` (upgraded from
R40's `NONE` — see caveat below).

`dex7/sources/com/comelit/bigapp/application/ComelitFlowStatus.java` exposes the exact same `RegisterStatus`
value CHILD A/B traced as both a `kotlinx.coroutines.flow.StateFlow<ComelitStatus.RegisterStatus>`
(`getVipConnectionStatus()`) and an `androidx.lifecycle.LiveData<ComelitStatus.RegisterStatus>`
(`getVipConnectionStatusLiveData()`), updated by `notifyVipConnectionChange(status)` — itself called from
`ComelitStatus.setEngineVipRegStatus` (`ComelitStatus.java`, the same setter CHILD A traced to
`ComelitEngineConnector`/`ReadFromJsonSocket`/`ViperSocketReaderRunnable`).

Observability classification, per this child's (A)/(B)/(C) scale:

* **(A) observable from UI/app logs without payload capture: yes.** `Log.i(TAG, "VIP REGISTER CHANGED " +
  regStatus + " -> " + status)` fires on every transition (`ComelitStatus.setEngineVipRegStatus`), and the
  native bridge event itself is a JSON control-socket message (`subunit_fsm_status_change` /
  `subunit_fsm_status`), not a VIP/CTPP media payload — reading it requires no SDP/RTP/CTP payload decode,
  only the same already-parsed JSON the app itself consumes.
* **(B) observable as a passive safe scalar: yes, as designed here.** This round does not propose
  committing any payload capture. The editable scalar this closure proposes for a future instrumented
  reader (not executed this round) is a plain boolean: `REGISTRATION_READY_SEEN=true|false`, defined as
  `ComelitStatus.RegisterStatus == REGISTERED` at sample time. `entrance_p116_r40f_official_app_readiness_model.py`'s
  `ReadinessObservation.registration_ready_seen: Optional[bool]` is exactly this scalar; it is optional
  (`None` when not sampled) so the model degrades gracefully to CHILD B's UI-only signal when no
  instrumentation exists, which is the case for every observation this round can actually produce.
* **(C) requiring payload/internal instrumentation:** none of the above requires it. Reading this signal
  live (as opposed to statically, as this round did) would require either an on-device log reader or a
  future Xposed/Frida-style instrumentation hook — out of scope for R40F, which performs no live
  invocation of any kind (`LIVE_INVOCATIONS=0`).

`NETWORK_READY_SIGNAL=PARTIAL`, not `PROVEN`: the underlying native VIP tunnel establishment
(`engine.createViperTunnel`, `VipCloudConnector.connect`) is a network operation whose success is exactly
what flips `RegisterStatus` to `REGISTERED` — so in one sense the readiness signal *is* network-derived.
But this round found no independently-observable **wire-level** signature (e.g. a specific packet shape or
sequence) that would let an outside observer (a phone-side capture, as in R39) distinguish `REGISTERING`
from `REGISTERED` without the app's own internal JSON/native bridge event — the R39 lesson (SECTION 5 below)
stands: TLS+STUN+UDP-keepalive alone are not sufficient, and this round did not find a wire-level
alternative that would be. `NETWORK_READY_SIGNAL=PARTIAL` reflects "the readiness state is network-caused
but only observable app-side," not "observable purely from the wire."

## 4. CHILD D — native pre-call registration

`NATIVE_PRECALL_READY_STATE=UNPROVEN` (unchanged from what independent native evidence alone can support).
`NATIVE_PRECALL_READY_PROVEN=false`.

Re-reading `native-disasm/disasm-VipUnitImpl_new_call_ctp_conn.txt`
(`.r29a-evidence/native-disasm/`, symbol `VipUnitImpl::new_call_ctp_conn(unsigned short, void*)@@Base`,
`libvipcomelit.so@0x7d4bc`, size `0x150`): the function's own body is a CTP message dispatcher — it calls
`csp_recv` into a `csp_msgbuf`, and branches on the message's second byte to `VipUnitImpl::handleCtpSetOutput`
(byte in `[0x20, 0x21]`) or `VipUnitImpl::handleCtpStart` (byte `== 0x1`), then always calls `ctp_close` on
that message buffer. This function's precondition, from the disassembly alone, is only "a `csp_recv` call on
file descriptor/session `w19` returns a message" — it contains **no** visible state check, flag read, or
handle validation that would itself constitute "ready to accept an inbound call" (contrast with `CallFsm+840`
bit2 and the `cfg` capability threshold R37 found gating `CallFsm::go_in_alerting`, both of which *are*
concrete native gates, but both are call-scoped — they run only after a call object already exists).

What this means concretely: the native evidence alone still cannot answer "is there a concrete native
state/handle that unambiguously means ready to accept an inbound call" — the answer this round found is
one layer up, in Java (`ComelitEngineConnector`'s tunnel establishment, CHILD A), not inside the CTP
dispatcher itself. `new_call_ctp_conn`'s only real precondition is that it is being called at all, which
requires the file descriptor/session `ViperSocketReaderRunnable` reads from to already be open — i.e. the
Java-side `RegisterStatus.REGISTERED` transition is a **necessary** condition for this function to ever run
with meaningful data (before that point, there is no open tunnel for `csp_recv` to read from), but the
disassembly itself does not encode a named "ready" state — it is a bare dispatcher. `PROVEN=false` records
that this round did not find a native-side confirmation of the Java-side signal, only a plausible
architectural relationship between them (the FD churn precedes the CTP dispatch).

## 5. CHILD E — R39 boundary reclassification

`R39_NOT_READY_BOUNDARY=stuck_between_REGISTERING_and_REGISTERED` (narrowed from R40's fully-open
"somewhere after network reachability and before CallStart"). `R39_NOT_READY_ROOT_CAUSE=PARTIAL` (upgraded
from R40's `UNPROVEN`).

With the state machine from CHILD A now traced, the R39 capture's transport signature (TLS to 443 for the
full 258.28 s, 26 STUN packets, 96 UDP-keepalive-candidate packets, 8 distinct peers, no `CALL_INIT`-shaped
traffic — `P116_R39_OFFICIAL_APP_PHONE_CAPTURE.md` section 3, reproduced this round by rerunning
`entrance_p116_r39_phone_capture_trace_model.py` against the original capture, still `packet_count=901`,
`duration_seconds=258.28`, `peer_count=8`, matching `tests/fixtures/p116_r39_phone_capture_scalars.json`
exactly) is now recognizable as **exactly** the traffic shape `ComelitEngineConnector.createSystemFromSettings`
/ `connectionStrategy` (STUN candidate gathering for `P2PStrategy`, TLS to the cloud API for
`VipCloudConnector.connect`'s Nimbus HTTPS calls, UDP for the P2P/Viper tunnel keepalive once a candidate
pair is chosen) produces *during* the `REGISTERING` -> `REGISTERED` transition — not traffic that could only
occur after `REGISTERED`. This narrows the boundary from R40's fully-open range to: the phone was
**attempting** VIP tunnel/cloud registration establishment for the whole 258 s window and never completed it
(`RegisterStatus` never reached `REGISTERED`, equivalently `ViperStatus` never reached `OPEN`) — consistent
with, though not the same evidentiary weight as, a `fail_wait`/`REGISTERING`-stuck state the native bridge
event vocabulary (CHILD A) shows the app can actually be in.

`PARTIAL`, not `PROVEN`: this round still has **no app-side log or the JSON control-socket messages
themselves** from the exact R39 capture window — only the wire-level transport shape and the now-known fact
that this shape matches the registration-establishment code path rather than only the post-registration
idle-keepalive path. It remains possible (though this round found no evidence either way) that
`RegisterStatus` briefly reached `REGISTERED` at some point inside the 258 s window and then reverted — the
payload-blind capture parser (privacy contract, unchanged from R39/R40) cannot distinguish these
sub-cases. Declaring a specific `REGISTERING` sub-state (e.g. specifically P2P STUN negotiation vs. cloud
HTTPS registration) as *the* cause would be inventing a fact this evidence does not support.

## 6. CHILD F — VPN/PCAPdroid static analysis

`VPN_SENSITIVE_API_FOUND=true`. `VPN_EXPLICITLY_DETECTED=false`. `NETWORK_BINDING_USED=false`.
`NETWORK_CHANGE_RESTARTS_SESSION=true`. `HYPOTHESIS_B_STATIC_SUPPORT=WEAKLY_SUPPORTED` (upgraded from R40's
`INCONCLUSIVE`, which itself was `INCONCLUSIVE` only because R40 had zero raw sources to search).
`PROVEN_CAUSE=false` (unchanged — this is architectural plausibility from static code, not a live-confirmed
causal link to the specific R39 attempt).

A targeted search of the full raw `dex7/8/9` trees (not available to R40) for `NetworkCallback`,
`bindProcessToNetwork`, `ConnectivityManager`, `VpnService`, `isVpn`, `NETWORK_TYPE_VPN`, `activeNetwork`,
`NetworkCapabilities` found real, non-third-party hits (excluding `com/google/`, `com/androidx/`,
`com/kotlin*`, `com/okhttp3/`):

* `dex9/sources/com/comelitgroup/sugar/utilities/ConnectionHelper.java` (a different subsystem, the "Sugar"
  alarm-panel module, not VIP door entry) — `isNetworkAvailable()` checks `networkCapabilities.hasTransport(1)
  || hasTransport(0) || hasTransport(3) || hasTransport(2)` (WIFI, CELLULAR, ETHERNET, BLUETOOTH) but never
  checks `hasTransport(4)` (`TRANSPORT_VPN`) — a network whose only reported transport is VPN would read as
  "not available" here. This is not the VIP path, but shows the general app-wide pattern: no code in this
  APK explicitly branches on VPN transport.
* `dex7/sources/com/comelit/bigapp/application/WifiReceiver.java` (the actual VIP-path network classifier,
  called from `ComelitEngineConnector.createSystemFromVip`/`connectionStrategy` to choose local-vs-remote
  connection): uses the deprecated `ConnectivityManager.getActiveNetworkInfo()` / `NetworkInfo.getType()`
  and only recognizes type `1` (WIFI), `0` (MOBILE), `9` (ETHERNET) — `TYPE_VPN` (`17`) is not one of the
  three recognized branches. If the active network reports type `17` while connected, the receiver's
  `isConnected()` branch falls through all three `if`/`else if` checks to a bare `return` (line 35) that
  calls **no** `ComelitStatus.setNetworkConnectionType(...)` at all — i.e. a VPN-classed active network is
  silently ignored by this specific receiver, neither treated as connected nor as disconnected.
* `dex7/sources/com/comelit/bigapp/ComelitService.java` (`update(ComelitStatusEvent, Object)`, case 1,
  `NETWORK_STATUS`, lines 371-395): when `getNetworkConnectionType() != TYPE_NONE` **and**
  `getPreviousNetworkConnectionType() != TYPE_NONE` (i.e. a real recognized-type-to-recognized-type
  transition), the code logs `"NETWORK_STATUS" "RECREATE"` and calls `initComelitEngine(true, true)` —
  tearing down and reconstructing the entire Comelit engine, which per CHILD A necessarily re-runs the whole
  `REGISTERING` -> `REGISTERED` sequence from scratch.

`NETWORK_CHANGE_RESTARTS_SESSION=true`: this is a real, cited, unconditional code path — any transition
between two *recognized* network types (WIFI<->MOBILE<->ETHERNET) triggers a full VIP registration
teardown/rebuild, independent of PCAPdroid specifically. `HYPOTHESIS_B_STATIC_SUPPORT=WEAKLY_SUPPORTED`
rather than `SUPPORTED`, because the mechanism this round found is asymmetric and not a clean match for
"PCAPdroid/VpnService specifically disrupts registration": (a) `WifiReceiver` appears to silently ignore a
VPN-classed active network entirely (no state change fires), which argues *against* a VPN toggle alone
triggering `ComelitService`'s "RECREATE" path via that receiver; but (b) enabling a local VPN capture app can
plausibly cause a brief transient window where `getActiveNetworkInfo()` returns `null` or an unrecognized
type before or after the VPN interface attaches, which **would** hit `WifiReceiver`'s explicit `TYPE_NONE`
fallback (`ComelitStatus.setNetworkConnectionType(TYPE_NONE)`, `Log.i("CONNECTION CHANGED", "CONNECTION
CHANGED OFFLINE")`) — and a *subsequent* recognized-type detection (e.g. WIFI reappearing as the classified
active network once routing settles) from a `TYPE_NONE` previous state triggers the milder "CREATE" branch
(`initComelitEngine(false, true)`), not full "RECREATE", but still a fresh registration attempt starting
from `NOT_REGISTERED`. This round found the mechanism; it did not find, and does not claim to have found, a
trace correlating this mechanism to what actually happened during the R39 capture — that would require a
live, instrumented re-run, out of scope here.

## 7. CHILD G — session release / exclusivity (Hypothesis A re-check)

`SESSION_EXCLUSIVITY_PROVEN=false` (unchanged from R40 — searched the raw sources this time, still no
positive hit for VIP-registration-specific exclusivity). `RELEASE_LATENCY_STATIC_BOUND=UNPROVEN` (unchanged).
`HYPOTHESIS_A_STATIC_SUPPORT=INCONCLUSIVE` (unchanged from R40's verdict, now confirmed against raw sources
rather than inferred from their absence).

A raw-source search for "already connected"/"duplicate login"/"duplicate session"/"kick previous"/"replace
session"/"registration conflict" across `dex7/8/9` found one real, load-bearing hit:
`com.comelitgroup.nimbus.CcapiErrorCode.USER_ALREADY_REGISTERED` (`dex8/sources/com/comelitgroup/nimbus/CcapiErrorCode.java`,
raw code `9001`), which `Authentication.createUser` (`dex7/sources/com/comelitgroup/authentication/Authentication.java`
lines 546-555, `WhenMappings.$EnumSwitchMapping$0`) maps to `CreateUserResult.USER_ALREADY_EXIST`. This is a
**cloud account creation** conflict (Nimbus/CCAPI user registration, i.e. creating a new Comelit cloud
account with an email already in use), not a VIP-unit session-exclusivity/kick-previous-client mechanism —
it does not describe what happens when the persistent listener releases the media session and the official
app tries to acquire it. No `RegisterStatus`-adjacent exclusivity/kick logic was found. The verdict stays
`INCONCLUSIVE`, now on stronger footing (an actual raw-source search, not merely "not found in promoted
documents").

## 8. CHILD H — ready-gate model update

`OFFICIAL_APP_READY_GATE=PARTIAL` (same word as R40, materially stronger evidentiary basis).
`OFFICIAL_APP_READY_MODEL=PARTIAL` (this round adds a genuinely new overlay model, per the instruction not to
cosmetically "improve" the model when nothing load-bearing changed — here, something load-bearing *did*
change, so the overlay is warranted, but it narrows rather than fully resolves R40's gate).

Per this round's explicit instruction ("if a machine-ready signal exists readiness must require it; if a UI
state is proven the operator state must match that exact proven UI state ... if both, use both"),
`entrance_p116_r40f_official_app_readiness_model.py` replaces R40's abstract
`OperatorAppState.OPERATOR_CONFIRMED_USABLE` judgement call with the concrete, cited
`OfficialAppUiConnectionState.CONNECTED` (the exact `ToolbarDeviceConnectionStatus.CONNECTED` value from
CHILD B), and adds an optional `registration_ready_seen: bool | None` scalar for CHILD C's machine signal —
a plain boolean, not a payload capture, consistent with CHILD C's explicit instruction. Precedence: a
`CONNECTED` UI read is necessary; if the machine signal was explicitly sampled and is `False`, it overrides
a `CONNECTED` UI read (contradicting machine state wins, fail-closed — protects against a stale icon); if
`True`, it corroborates; if not sampled (`None`, the only case this round can actually produce, since no
live instrumentation ran), the gate proceeds on the UI signal alone. Listener-state and ring-budget gating
are unchanged from R40 (a ring while the listener is `READY` still reaches the listener, not the app — the
exact R39 failure mode). `TLS`/`STUN`/`UDP`-keepalive alone still can never unlock readiness — the
`NetworkContextScalars`/`assert_network_context_not_load_bearing` invariant from R40 is preserved unchanged
and re-tested against the same real R39 fixture.

R40's original model (`entrance_p116_r40_official_app_readiness_model.py`) is untouched and still imports
and passes its own tests unmodified — this round's model is a separate, additional file, not a rewrite.

## 9. CHILD I — R41 decision

`R41_PREFLIGHT_IMPLEMENTABLE=true` (same boolean as R40's plan already assumed, now on stronger footing).

Conditions checked: (1) a concrete readiness observation now exists that is **not** merely an abstract
operator judgement — it is a specific, cited, real app string/icon (`ToolbarDeviceConnectionStatus.CONNECTED`
on the door-entry screen's own toolbar) the operator is asked to literally read, optionally corroborated by
a plain boolean machine-signal scalar if a future round adds instrumentation; (2) it can be obtained
no-ring — opening the app and reading its own toolbar icon involves no physical ring, no Door/Gate action,
no listener interaction beyond what R40's plan already required; (3) fail-closed, listener-restore semantics
are unchanged from R40 (same `ListenerState` gating, same "restore listener first" ordering in the existing
`P116_R41_OFFICIAL_APP_READINESS_LIVE_PREFLIGHT_PLAN.md` contract, which this round does not rewrite); (4)
the protocol timeout for VIP registration remains `UNPROVEN` from static evidence alone (CHILD A/E — no
retry/backoff constant found for registration specifically), so any future R41 attempt must still use an
explicit, operator-approved bounded timeout rather than a value this document supplies; (5) a `PASS` from
this signal does not auto-authorize R42 — unchanged.

This round does **not** rewrite `P116_R41_OFFICIAL_APP_READINESS_LIVE_PREFLIGHT_PLAN.md`. A future round
should update that plan's SECTION 3 step 5 to read the concrete `ToolbarDeviceConnectionStatus` label off
`DoorEntryContentFragment` instead of an abstract `OperatorAppState`, and to call
`entrance_p116_r40f_official_app_readiness_model.evaluate_readiness` instead of R40's model — that update is
left to that future round, not performed here, per this round's constraint against rewriting existing R40/R41
files.

## 10. Evidence ledger

| SOURCE_KIND | FILE | SYMBOL_OR_METHOD | LINE_RANGE | VERDICT |
|---|---|---|---|---|
| dex | `dex7/sources/com/comelit/bigapp/application/ComelitStatus.java` | `RegisterStatus`, `setEngineVipRegStatus`, `getEngineVipRegStatus` | enum ~L44-49, setter ~L192-201 | Real, named, pre-call, non-call-scoped VIP registration state machine (CHILD A/C) |
| dex | `dex7/sources/com/comelit/bigapp/application/ComelitFlowStatus.java` | `vipConnectionStatus` (StateFlow), `vipConnectionStatusLiveData` (LiveData), `notifyVipConnectionChange` | L60-91, L126-129 | Machine-observable, app-log-observable, no-payload readiness signal (CHILD C) |
| dex | `dex7/sources/com/comelit/bigapp/utilities/ToolbarUtilsKt.java` | `asToolbarConnectionStatus(RegisterStatus)` | full file | Exact, mechanical `RegisterStatus -> ToolbarDeviceConnectionStatus` mapping (CHILD B) |
| dex | `dex8/sources/com/comelitgroup/comelit_material_design/toolbar/ToolbarDeviceConnectionStatus.java` | `NOT_CONNECTED, CONNECTING, CONNECTED` | full file | The cited UI enum/label itself (CHILD B) |
| dex | `dex7/sources/com/comelit/bigapp/utilities/ToolbarUtils.java` | `defaultVipConnectionStatusAction` | L26-36 | Binds the mapping to `ToolbarDeviceType.VIP`, reads `ComelitStatus.getEngineVipRegStatus()` directly (CHILD B) |
| dex | `dex7/sources/com/comelit/bigapp/fragment/doorentry/DoorEntryContentFragment.java` | (usage site, `grep` match for `defaultVipConnectionStatusAction`) | n/a (grep hit only, no full read) | Confirms the VIP toolbar status is rendered on the door-entry screen itself, not an unrelated screen (CHILD B) |
| dex | `dex7/sources/com/comelit/bigapp/engine/managers/ComelitEngineConnector.java` | `createSystemFromSettings`, `createSystemFromVip`, `connectionStrategy`, `createSystemFromWizard` | L143-160, L224-260, L376-400 | Pre-call VIP tunnel/cloud registration establishment, sets `RegisterStatus` transitions (CHILD A) |
| dex | `dex7/sources/com/comelit/bigapp/viper/ViperSocketReaderRunnable.java` | `run`, `setReconnecting` | full file (~85 lines) | Native-socket-to-Java pump; failure path sets `NOT_REGISTERED`, broadcasts reconnection event (CHILD A) |
| dex | `dex7/sources/com/comelit/bigapp/application/jsonsocket/ReadFromJsonSocket.java` | `subunit_fsm_status_change` handling | L260-270, L347-357 | Native-FSM-to-Java bridge event; `subunit_fsm_status` in {registering, fail_wait, registered} (CHILD A/C) |
| dex | `dex7/sources/com/comelitgroup/authentication/Authentication.java` | `initialize`, `signIn`, `createUser`, `TokenRefresherActor` | L375-453, L502-556 | Real AUTH/SESSION stage — OAuth2/CCS token storage, sign-in, token refresh (CHILD A) |
| dex | `dex9/sources/com/comelitgroup/sdk/core/ComelitSDK.java` | `initialize`, `internalInitialize$core_release` | full file (~230 lines) | SDK_INIT stage, distinct from the legacy bigapp engine init (CHILD A) |
| dex | `dex9/sources/com/comelitgroup/shared/VipCloudConnector.java` | `connect` | full file (~350 lines) | Cloud/WebRTC VIP registration path used by `createSystemFromSettings`'s cloud branch (CHILD A) |
| dex | `dex9/sources/com/comelitgroup/nimbus/CcapiErrorCode.java` | `USER_ALREADY_REGISTERED` (9001) | enum entry | Cloud-account conflict code, not VIP-session exclusivity (CHILD G, `INCONCLUSIVE`) |
| dex | `dex9/sources/com/comelitgroup/sugar/utilities/ConnectionHelper.java` | `isNetworkAvailable` | full file (~25 lines) | `hasTransport()` check omits `TRANSPORT_VPN` (4) — different subsystem, corroborating pattern (CHILD F) |
| dex | `dex7/sources/com/comelit/bigapp/application/WifiReceiver.java` | `onReceive` | full file (~47 lines) | VIP-path network classifier; recognizes WIFI/MOBILE/ETHERNET only, silently ignores VPN-typed active network (CHILD F) |
| dex | `dex7/sources/com/comelit/bigapp/ComelitService.java` | `update(ComelitStatusEvent, Object)` | L369-444 | `NETWORK_STATUS` case triggers full engine "RECREATE" on recognized-type network transitions (CHILD F) |
| native_disasm | `.r29a-evidence/native-disasm/disasm-VipUnitImpl_new_call_ctp_conn.txt` | `VipUnitImpl::new_call_ctp_conn(unsigned short, void*)@@Base` | `libvipcomelit.so@0x7d4bc`, size `0x150` | Bare CTP dispatcher, no visible native "ready" gate of its own; precondition is an open FD/session from the Java side (CHILD D) |
| prior_doc | `P116_R37_ATTACHED_INBOUND_MEDIA_LIVE_READINESS.md` section 1 | `CallFsm+840` bit2, `cfg` capability threshold | n/a | Call-scoped native gates, reused verbatim, not re-derived this round (CHILD A precondition citation) |
| prior_doc | `P116_R39_OFFICIAL_APP_PHONE_CAPTURE.md` section 3-4; `tests/fixtures/p116_r39_phone_capture_scalars.json` | `packet_count=901`, `duration_seconds=258.28`, `peer_count=8`, `transport_categories` | n/a | Reproduced this round by rerunning the R39 trace model against the original capture (unchanged from R40) |

## 11. Verification

Commands run in this worktree (`safety-poc/` as working directory unless noted):

```bash
cd safety-poc
python3 -m unittest tests.test_p116_r40f_official_app_readiness_evidence -v
python3 -m unittest tests.test_p116_r40_official_app_readiness -v
python3 -m unittest tests.test_p116_r39_official_app_phone_capture -v
python3 -m unittest tests.test_p116_r37_attached_media_live_readiness tests.test_p116_r36_attached_media_trigger tests.test_p116_r35_attached_media_native_helper -v
python3 -m unittest tests.test_p116_r34_attached_media_offline_impl tests.test_p116_r33_offline_scalar_trace tests.test_p116_r32_call_bound_media_evidence -v
python3 -m unittest discover -s tests
python3 scripts/static_safety_check.py
python3 -m compileall research/media/v1/entrance_p116_r40f_official_app_readiness_model.py tests/test_p116_r40f_official_app_readiness_evidence.py
cd ..
git diff --check
```

Baseline: the single pre-existing `NATIVE_BINARY_MODE` 755-vs-775 failure
(`test_p116_provenance_binary_analysis.P116ProvenanceBinaryAnalysisTests.test_committed_build_metadata_records_historical_non_runtime_mismatch`)
is reproduced unchanged at this round's base and is **not** fixed here — a pre-existing filesystem-mode
artifact unrelated to R40F content, separated from the verdict exactly as R35/R36/R37/R40 separated it.

Scope check: this round wrote only under `safety-poc/research/media/v1/` (two new files) and
`safety-poc/tests/` (one new file). `custom_components/comelit/**`, the native production binary, and every
normative doc are untouched. No raw/decompiled evidence, APK, dex tree, native lib, or disassembly bundle was
copied into this repository — every citation above points at the pre-existing, git-excluded evidence
directories in place (`/home/hermes/worktrees/comelit-p116-r28/.r28-evidence/`, the R33 evidence tree, and
the R29a/c/e native-disasm sets), not at bytes committed here.

Privacy/leak scan: this document, the model, and the test module were checked for IPv4-shaped strings,
hexdumps, and credential-like tokens (same regex families as the R39 privacy guard, now also asserted by
`ClosureDocumentInvariantTests.test_closure_is_address_free` and
`test_closure_has_no_credential_or_token_like_strings`); none are present. The CT120 directory excluded by
policy (credential-adjacent OAuth/session-token static artifacts) was never read and is not cited anywhere
in this document (`test_closure_does_not_reference_excluded_oauth_evidence` asserts the excluded directory's
name never appears here). No raw PCAP, device id, token, or credential appears anywhere in this round's
output.

```text
=== COMELIT P116 R40F READINESS EVIDENCE ===
BASE_R40_SHA=123c1fd046f5d74956e89e795b439be379594f97
EXECUTOR=claude-code-cli
EXECUTOR_SUBSTITUTION_AUTHORIZED_BY_USER=true
RAW_R28_EVIDENCE_USED=true
RAW_R33_EVIDENCE_USED=true
PRECALL_STATE_MACHINE=PARTIAL
CALL_RECEIVER_PRECONDITIONS=PARTIAL
APP_READY_INTERNAL_STATE=ComelitStatus.RegisterStatus.REGISTERED
UI_READY_SIGNAL=PROVEN
UI_READY_SIGNAL_VALUE=ToolbarDeviceConnectionStatus.CONNECTED
MACHINE_READY_SIGNAL=ComelitStatus.RegisterStatus.REGISTERED
NETWORK_READY_SIGNAL=PARTIAL
NATIVE_PRECALL_READY_STATE=UNPROVEN
NATIVE_PRECALL_READY_PROVEN=false
R39_NOT_READY_BOUNDARY=stuck_between_REGISTERING_and_REGISTERED
R39_NOT_READY_ROOT_CAUSE=PARTIAL
VPN_SENSITIVE_API_FOUND=true
VPN_EXPLICITLY_DETECTED=false
NETWORK_BINDING_USED=false
NETWORK_CHANGE_RESTARTS_SESSION=true
HYPOTHESIS_B_STATIC_SUPPORT=WEAKLY_SUPPORTED
SESSION_EXCLUSIVITY_PROVEN=false
RELEASE_LATENCY_STATIC_BOUND=UNPROVEN
HYPOTHESIS_A_STATIC_SUPPORT=INCONCLUSIVE
OFFICIAL_APP_READY_GATE=PARTIAL
OFFICIAL_APP_READY_MODEL=PARTIAL
R41_PREFLIGHT_IMPLEMENTABLE=true
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
R40_REGRESSION=PASS
R39_REGRESSION=PASS
FULL_OFFLINE_TESTS=PASS
STATIC_SAFETY=PASS
PR=NONE
MERGED=false
RESULT=PARTIAL_R40F_READY_GATE
NEXT_STEP=A future round should (1) update P116_R41_OFFICIAL_APP_READINESS_LIVE_PREFLIGHT_PLAN.md SECTION 3 step 5 to sample the concrete ToolbarDeviceConnectionStatus label on DoorEntryContentFragment via entrance_p116_r40f_official_app_readiness_model.evaluate_readiness instead of R40's abstract OperatorAppState, (2) add real app-log instrumentation for the registration_ready_seen scalar this round left at None, and (3) if raw dex/native access remains available, search dex9's ComelitSDKAndroid/CallService chain for whether it and the dex7 bigapp ComelitEngineConnector chain traced here are the same runtime call path or two parallel implementations in the same APK, which this round did not fully resolve.
=== END COMELIT P116 R40F READINESS EVIDENCE ===
```
