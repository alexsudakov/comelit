# P116 R28 Listener-Attached Inbound Media Analysis

TASK_ID=COMELIT-P116-R28-LISTENER-ATTACHED-INBOUND-MEDIA
MODE=DEV_OFFLINE
ROUND=4_NATIVE_STATIC_RESOLUTION_AND_CONDITIONAL_CANDIDATE
BASE_SHA=a30b1cbfef81c26c2a2fe28d3b280bf253161d9d
LIVE_AUTHORIZED=false
RAW_PAYLOAD_EMITTED=false
PRODUCTION_FILES_CHANGED=0

ROUND 2 UPDATE: `STATIC_PREVIEW_PATH_FOUND` changed from `UNKNOWN` to `true` because staged dex sources contain a complete inbound Android/SDK/UI preview path, not only native-symbol inventory. `PREVIEW_ANSWERS_CALL` changed from `UNKNOWN` to `false` because `startCall`/media opening and `answer`/`AnswerCallRequest` are separate SDK operations. `PREVIEW_CAN_RUN_WHILE_RINGING` changed from `UNKNOWN` to `true` because the not-connected/ringing UI consumes preview bytes before `CONNECTED`. `INBOUND_MEDIA_REQUEST_DIRECTION` was added as `BIDIRECTIONAL_API_INBOUND_DIRECTION_UNKNOWN`: parsers prove received media-request events, while `MediaReqEvt.Companion.message` proves a client-originated message builder; the exact inbound preview direction remains unresolved. `IMPLEMENTATION` changes from `BLOCKED_NEEDS_MORE_EVIDENCE` to `READY_FOR_NEXT_ROUND` for a candidate/test/runner round only; no production implementation is authorized here.

ROUND 3 UPDATE: `INBOUND_MEDIA_REQUEST_DIRECTION` changed from `BIDIRECTIONAL_API_INBOUND_DIRECTION_UNKNOWN` to `DEVICE_TO_CLIENT` for the parsed `HANDLE_MEDIAREQ` event because staged parsers construct `MediaReqEvt`/`VideoCallMediaReqEvt` only from received notifications, the SDK call consumer does not handle that object by emitting a media request, and targeted searches found zero reachable callers of `MediaReqEvt.Companion.message(...)`. `MEDIAREQ_BUILDER_CALLERS=0` was added for that correction. `INBOUND_VIDEO_RX_INITIATION=UNKNOWN` was added because native symbols prove `auto_start_videorx`, `start_videorx`, and `handle_mediareq` exist, but the staged native evidence does not prove which path initiates inbound video receive. `DOOR_DURING_ATTACHED_MEDIA_STATIC` changed from `UNKNOWN` to `POSSIBLE` as a static feasibility finding only: official call UI wires Door actions during incoming-call handling, and our Door runtime can signal the persistent listener, but no physical Door action or media interleaving proof was run. `IMPLEMENTATION` changed to `BLOCKED_NEEDS_MORE_EVIDENCE`; Phase 3B was skipped by contract because native RX initiation and media-teardown survival remain `UNKNOWN`.

ROUND 4 UPDATE: `INBOUND_VIDEO_RX_INITIATION` changed from `UNKNOWN` to `AUTO_ON_INCOMING_CALL` because the staged native libraries show the incoming-alerting FSM path reaching `CallFsm::start_videorx(int)` and `RtpDispatcher::startVideoRX(...)`, without the SDK `answer-call` path. `SAME_UPSTREAM_TRANSPORT`, `SAME_ICE_SESSION`, `SAME_PSEUDOTCP`, `SAME_CTPP_REGISTRATION`, and `SAME_NATIVE_PROCESS` changed from `UNKNOWN` to `true` as bounded static findings because the media RX chain is `RtpDispatcher::startVideoRX -> ViperTunnel::openMediaRXChannel -> ViperTunnel::openChannel -> viper_tunnel_channel_create`, with no media-path edge to `System::createRemoteConnection` or tunnel creation. `NEW_CLOUD_NEGOTIATION_REQUIRED`, `NEW_ICE_REQUIRED`, and `NEW_PSEUDOTCP_REQUIRED` changed from `UNKNOWN` to `false` on the same native chain. `MEDIA_TEARDOWN_PRESERVES_TRANSPORT` and `MEDIA_TEARDOWN_PRESERVES_REGISTRATION` changed from `UNKNOWN` to `true` for the official native media-only close because `CallFsm::stop_videorx()` reaches `RtpDispatcher::stopVideoRX -> ViperTunnel::closeMediaRXChannel`; `MEDIA_TEARDOWN_PRESERVES_RING_LISTENER` remains `UNKNOWN` because official media-channel close is not a live HA listener-survival proof. Phase 4B ran and added a research-only offline candidate transform, focused tests, and a live-disabled runner with materialized helper substitution.

## 1. Scope, Method, Evidence Inventory

Scope: analysis and documentation only. No production code, tests, transforms, runners, captures, native binaries, Home Assistant deployment, live Comelit session, Door/Gate action, listener restart, media bootstrap, or network probe was created or executed in this round.

Method: read-only inspection of the current repository contract, current HA runtime code, P68-P106 media lineage, P25-P27 closed evidence, staged official-app static artifacts, staged saved captures, external `comelit-vip` as corroborating static material only, and direct `rg --hidden --no-ignore`/`nl` reads over staged `dex7`, `dex8`, and `dex9` sources.

Evidence inventory:

| Input | Classification | sha256 / UTC | Anchor |
|---|---|---:|---|
| Repository base | PROVEN_STATIC | `a30b1cbfef81c26c2a2fe28d3b280bf253161d9d` | parent task context |
| Staged provenance | PROVEN_OFFLINE | fetched UTC `2026-09-13T13:54Z` | `.r28-evidence/PROVENANCE.txt:1` |
| External `comelit-vip` files | CORROBORATING_EXTERNAL_STATIC | ref `4c1cba401030c705132174e60fb3886f667a442f`, UTC `2026-09-13T13:54Z` | `.r28-evidence/PROVENANCE.txt:3` |
| Official app dex sources | PROVEN_OFFLINE inventory | dex7/8/9 source trees, UTC `2026-09-13T13:54Z` | `.r28-evidence/PROVENANCE.txt:27` |
| Official app prior analysis | PROVEN_OFFLINE inventory | `7c8afb723e36c9d82831496bd1eea16623642b09978ea34e89df667312df2fe4` | `.r28-evidence/PROVENANCE.txt:39` |
| Official app native libraries | PROVEN_OFFLINE static input | `libvipcomelit.so`, `libsafecomelit.so`, `libcomelitvipkit.so`; hashes recorded in provenance | `.r28-evidence/PROVENANCE.txt` |
| Saved self-activation capture | OBSERVED, not inbound proof | `f15bb1922f55237bfaeb570bd288f7023e0196c05e878dfdaa76ad165bbc044a` | `.r28-evidence/PROVENANCE.txt:47` |
| Saved P2P RTSP capture | OBSERVED, not inbound proof | `62888c21a795d3a2716423a196d9b68e80f73843f5202fcd23837312298f8ec3` | `.r28-evidence/PROVENANCE.txt:49` |

## 2. Current Architecture On Main

Current production media contract is listener-isolated, not listener-attached. It says persistent Ring/Door runs while media is inactive, but is intentionally paused before separately bootstrapped media starts and restored after media teardown is confirmed (`docs/intercom-media-session-architecture.md:11`, `docs/intercom-media-session-architecture.md:71`). It also caps one media session at an absolute 600 seconds, with leases unable to extend the deadline (`docs/intercom-media-session-architecture.md:17`, `docs/intercom-media-session-architecture.md:148`).

`ComelitMediaSessionManager` implements that contract: it pauses the listener, starts the media transport, starts an absolute deadline, and only resumes the listener after media stop is confirmed (`custom_components/comelit/media_session.py:64`, `custom_components/comelit/media_session.py:189`, `custom_components/comelit/media_session.py:327`). Teardown fails closed by entering error if media stop cannot be confirmed, rather than starting a second upstream session (`custom_components/comelit/media_session.py:341`).

The runtime supervisor enforces `paused_media`: while held, the native listener is fully stopped and reconnect is disabled (`custom_components/comelit/supervisor.py:35`, `custom_components/comelit/supervisor.py:149`). Current Door operations live on `ComelitRingRuntime` and require the listener process to be running and ready (`custom_components/comelit/runtime.py:307`, `custom_components/comelit/runtime.py:312`). Current media bootstrap is a separate native process and cloud negotiation path (`custom_components/comelit/media_transport.py:448`, `custom_components/comelit/media_transport.py:600`, `custom_components/comelit/media_transport.py:642`).

Ring detection is read-only. The normalized contract accepts only an incoming direction, CALL_INIT kind, and closed source-to-door mapping, and does not invent a protocol call id (`safety-poc/docs/RING_EVENT_CONTRACT.md:5`, `safety-poc/docs/RING_EVENT_CONTRACT.md:54`). The implementation rejects unsupported direction/kind/source and emits only normalized safe markers (`safety-poc/src/comelit_safety_poc/ring_event.py:75`, `custom_components/comelit/ring_event.py:70`).

## 3. Proven Inbound-Call Signaling Path

Answer A:

`PROVEN_OFFLINE`: our persistent listener reaches a registered CTPP state and stays in the ring-listen state after registration (`safety-poc/research/ring/v4_3/comelit_ice_offer_holder.v4-persistent.c:1623`, `safety-poc/research/ring/v4_3/comelit_ice_offer_holder.v4-persistent.c:1647`, `safety-poc/research/ring/v4_3/comelit_ice_offer_holder.v4-persistent.c:1671`). `CALL_INIT` is observed inside that registered listener and explicitly must not terminate the registered PseudoTCP/CTPP session (`safety-poc/research/ring/v4_3/comelit_ice_offer_holder.v4-persistent.c:3627`, `safety-poc/research/ring/v4_3/comelit_ice_offer_holder.v4-persistent.c:3682`).

`PROVEN_STATIC`: the official app represents an incoming call as a call-scoped object keyed by a notification `callId`, not as the registration transaction. `ComelitNotification.CallStart` carries `callId`, `unitId`, `endpointId`, buttons, and profile fields (`dex9/sources/com/comelitgroup/sdk/notification/ComelitNotification.java:82`, `dex9/sources/com/comelitgroup/sdk/notification/ComelitNotification.java:129`, `dex9/sources/com/comelitgroup/sdk/notification/ComelitNotification.java:145`, `dex9/sources/com/comelitgroup/sdk/notification/ComelitNotification.java:158`). `ComelitSDKAndroid.handleCallStartNotification` hands that call-start object to Android Telecom as a new incoming call (`dex9/sources/com/comelitgroup/sdk/incomingcall/ComelitSDKAndroid.java:79`, `dex9/sources/com/comelitgroup/sdk/incomingcall/ComelitSDKAndroid.java:85`, `dex9/sources/com/comelitgroup/sdk/incomingcall/ComelitSDKAndroid.java:89`). `CallService.onCreateIncomingConnection` decodes the call-start object, sets the activity extras from the call id and endpoint, creates a `CallConnection`, registers it by `callId`, and calls `CallManager.INSTANCE.createCall(endpointId, callerName, callId, buttons)` (`dex9/sources/com/comelitgroup/sdk/incomingcall/CallService.java:75`, `dex9/sources/com/comelitgroup/sdk/incomingcall/CallService.java:107`, `dex9/sources/com/comelitgroup/sdk/incomingcall/CallService.java:116`, `dex9/sources/com/comelitgroup/sdk/incomingcall/CallService.java:145`, `dex9/sources/com/comelitgroup/sdk/incomingcall/CallService.java:146`). `CallManager.createCall` marks a call as incoming when a non-null call id is supplied and stores the active call by that id (`dex9/sources/com/comelitgroup/sdk/call/CallManager.java:359`, `dex9/sources/com/comelitgroup/sdk/call/CallManager.java:362`, `dex9/sources/com/comelitgroup/sdk/call/CallManager.java:363`, `dex9/sources/com/comelitgroup/sdk/call/CallManager.java:372`).

`STRONGLY_SUPPORTED`: the call transaction is distinct from the persistent registration transaction. The SDK call object builds either an offer-data-channel `Connexus` path or a Nimbus-created `Connexus` path with call-scoped channels (`dex9/sources/com/comelitgroup/sdk/call/Call.java:285`, `dex9/sources/com/comelitgroup/sdk/call/Call.java:289`, `dex9/sources/com/comelitgroup/sdk/call/Call.java:291`, `dex9/sources/com/comelitgroup/sdk/call/Call.java:293`, `dex9/sources/com/comelitgroup/sdk/call/Call.java:301`). External corroboration models one transport, one CTPP channel, registration, inbound calls, Door, and outgoing video calls all as CTP connections on that channel (`.r28-evidence/external/comelit-vip/session.py:1`, `.r28-evidence/external/comelit-vip/session.py:456`, `.r28-evidence/external/comelit-vip/session.py:664`).

The call-context and ack/sequence conclusion for our production candidate is therefore: the registration transaction remains the listener's persistent CTPP context; the call context is the inbound `callId` plus endpoint/call-scoped channels. The exact low-level sequence/ack bytes for the inbound call transaction remain out of scope from dex Java/Kotlin and are not emitted here.

Answer B:

`PARTIALLY_PROVEN_STATIC`: the official app inbound preview sequence is:

```text
registered listener receives call-start notification
-> Android Telecom onCreateIncomingConnection
-> CallConnection registered by callId and SDK Call created as incoming
-> onShowIncomingCallUi starts ringing and call-state observation
-> VipCallActivity.showUIForIncomingCall binds a callId-keyed VipCallViewModel
-> VipCallScreen launches startCall after permissions
-> Call.start registers Connexus/video/status/listeners and opens Connexus
-> remote video updates CallState.video; preview bytes are also carried in CallState
-> not-connected UI receives previewImageBytes while status is INITIALIZED/CLOSED/LOADING
-> explicit answer is separate
```

Anchors: `CallConnection` stores call id from the call-start notification, sets ringing in the constructor, and on UI display starts ringer, notification, and call observer (`dex9/sources/com/comelitgroup/sdk/incomingcall/CallConnection.java:77`, `dex9/sources/com/comelitgroup/sdk/incomingcall/CallConnection.java:93`, `dex9/sources/com/comelitgroup/sdk/incomingcall/CallConnection.java:102`, `dex9/sources/com/comelitgroup/sdk/incomingcall/CallConnection.java:105`, `dex9/sources/com/comelitgroup/sdk/incomingcall/CallConnection.java:107`). `VipCallActivity.showUIForIncomingCall` gets the call id, resolves a `VipCallViewModel` keyed by that call id, collects call state, and passes callbacks and state into `VipCallScreen` (`dex7/sources/com/comelit/bigapp/call/VipCallActivity.java:78`, `dex7/sources/com/comelit/bigapp/call/VipCallActivity.java:95`, `dex7/sources/com/comelit/bigapp/call/VipCallActivity.java:114`, `dex7/sources/com/comelit/bigapp/call/VipCallActivity.java:183`, `dex7/sources/com/comelit/bigapp/call/VipCallActivity.java:321`). `VipCallViewModel.startCall` and `answer` are separate methods (`dex9/sources/com/comelitgroup/shared/VipCallViewModel.java:42`, `dex9/sources/com/comelitgroup/shared/VipCallViewModel.java:46`).

`Call.start` registers listeners, changes state to loading, and opens `Connexus` (`dex9/sources/com/comelitgroup/sdk/call/Call.java:1006`, `dex9/sources/com/comelitgroup/sdk/call/Call.java:1010`, `dex9/sources/com/comelitgroup/sdk/call/Call.java:1016`). Listener registration includes remote video, `Connexus` state, call-channel/libcomelit-channel notifications, and audio devices (`dex9/sources/com/comelitgroup/sdk/call/Call.java:1040`, `dex9/sources/com/comelitgroup/sdk/call/Call.java:1041`, `dex9/sources/com/comelitgroup/sdk/call/Call.java:1043`, `dex9/sources/com/comelitgroup/sdk/call/Call.java:1047`, `dex9/sources/com/comelitgroup/sdk/call/Call.java:1049`). Remote video updates call state and clears the snapshot URL (`dex9/sources/com/comelitgroup/sdk/call/Call.java:1082`, `dex9/sources/com/comelitgroup/sdk/call/Call.java:1083`, `dex9/sources/com/comelitgroup/sdk/call/Call.java:1088`). Preview bytes are separately fed into `CallState` (`dex9/sources/com/comelitgroup/sdk/call/Call.java:929`, `dex9/sources/com/comelitgroup/sdk/call/Call.java:932`). The not-connected screens receive `previewImageBytes` while call status is initial/closed/loading (`dex7/sources/com/comelit/bigapp/call/ui/VipCallScreenKt.java:193`, `dex7/sources/com/comelit/bigapp/call/ui/VipCallScreenKt.java:195`, `dex7/sources/com/comelit/bigapp/call/ui/VipCallScreenKt.java:207`, `dex7/sources/com/comelit/bigapp/call/ui/VipCallScreenKt.java:220`, `dex7/sources/com/comelit/bigapp/call/ui/VipCallScreenKt.java:230`).

Media request direction for the parsed event is `INBOUND_MEDIA_REQUEST_DIRECTION=DEVICE_TO_CLIENT`. `CallFsmEventType` assigns `HANDLE_MEDIAREQ` as an enum value accepted by `fromInt` (`dex8/sources/com/comelitgroup/comelitcorekit/type/CallFsmEventType.java:12`, `dex8/sources/com/comelitgroup/comelitcorekit/type/CallFsmEventType.java:18`, `dex8/sources/com/comelitgroup/comelitcorekit/type/CallFsmEventType.java:48`). `VipMessageParser.parse` decodes a received message, routes VIP `CALL_EVENT` into `getVipCallEvent`, maps the received `event_id` through `CallFsmEventType.fromInt`, and constructs `MediaReqEvt` for the `HANDLE_MEDIAREQ` branch (`dex8/sources/com/comelitgroup/comelitvipkit/VipMessageParser.java:240`, `dex8/sources/com/comelitgroup/comelitvipkit/VipMessageParser.java:293`, `dex8/sources/com/comelitgroup/comelitvipkit/VipMessageParser.java:346`, `dex8/sources/com/comelitgroup/comelitvipkit/VipMessageParser.java:350`, `dex8/sources/com/comelitgroup/comelitvipkit/VipMessageParser.java:358`, `dex8/sources/com/comelitgroup/comelitvipkit/VipMessageParser.java:359`). The SAFE parser has the same received-message branch into `VideoCallMediaReqEvt` (`dex8/sources/com/comelitgroup/comelitsafekit/SafeMessageParser.java:629`, `dex8/sources/com/comelitgroup/comelitsafekit/SafeMessageParser.java:847`, `dex8/sources/com/comelitgroup/comelitsafekit/SafeMessageParser.java:851`, `dex8/sources/com/comelitgroup/comelitsafekit/SafeMessageParser.java:859`, `dex8/sources/com/comelitgroup/comelitsafekit/SafeMessageParser.java:860`).

The reachable SDK consumer evidence does not show a client-side media-request response. In `Call.registerListeners`, libcomelit-channel notifications are parsed, but the consumer updates call FSM status, capability, voice status, or RTSP state; it has no `MediaReqEvt` branch and no send on that parsed event (`dex9/sources/com/comelitgroup/sdk/call/Call.java:1040`, `dex9/sources/com/comelitgroup/sdk/call/Call.java:1049`, `dex9/sources/com/comelitgroup/sdk/call/Call.java:1426`, `dex9/sources/com/comelitgroup/sdk/call/Call.java:1427`, `dex9/sources/com/comelitgroup/sdk/call/Call.java:1437`, `dex9/sources/com/comelitgroup/sdk/call/Call.java:1444`, `dex9/sources/com/comelitgroup/sdk/call/Call.java:1461`). `MediaReqEvt.Companion.message(fsmId, hdOn)` still exists as a builder (`dex8/sources/com/comelitgroup/comelitvipkit/event/vip/callevent/MediaReqEvt.java:51`, `dex8/sources/com/comelitgroup/comelitvipkit/event/vip/callevent/MediaReqEvt.java:56`, `dex8/sources/com/comelitgroup/comelitvipkit/event/vip/callevent/MediaReqEvt.java:57`, `dex8/sources/com/comelitgroup/comelitvipkit/event/vip/callevent/MediaReqEvt.java:59`), but targeted caller searches found zero `MediaReqEvt.Companion`/`MediaReqEvt.INSTANCE` references and only the declaration-side `message(` match. Therefore the builder is not evidence of a client-initiated inbound request in the staged sources.

Native video receive initiation is now `INBOUND_VIDEO_RX_INITIATION=AUTO_ON_INCOMING_CALL` as a static native finding. The bounded chain is:

```text
VipUnitImpl::new_call_ctp_conn
-> VipUnitImpl::handleCtpStart
-> VipUnitImpl::vip_unit_accept_call
-> CallFsm::enqueueEvent
-> CallFsm::st_idle
-> CallFsm::go_in_alerting
-> CallFsm::start_videorx
-> RtpDispatcher::startVideoRX
```

The supporting state names are `IN_ALERTING`, not `CONNECTED`, and dex still proves `answer-call` is separate from preview start. This does not mean no internal call transaction is adopted: `vip_unit_accept_call` is part of the native inbound call/FSM adoption path. It means the video RX path is reachable from incoming alerting and is not gated by the SDK explicit answer request. `CallFsm::auto_start_videorx()` exists but the PLT-mapped call scan found no named caller in the staged libraries; it is not the load-bearing edge for this conclusion.

## 4. Same-Session Proof And Proof Gate

`PROVEN_STATIC`: official app call media is call-scoped rather than a second registration transaction. In the incoming path, `CallService` creates one SDK `Call` for the notification's call id (`dex9/sources/com/comelitgroup/sdk/incomingcall/CallService.java:144`, `dex9/sources/com/comelitgroup/sdk/incomingcall/CallService.java:146`), and `CallManager` stores it in `activeCalls` by call id (`dex9/sources/com/comelitgroup/sdk/call/CallManager.java:372`). `Call` creates call-scoped channels and a `Connexus` instance (`dex9/sources/com/comelitgroup/sdk/call/Call.java:285`, `dex9/sources/com/comelitgroup/sdk/call/Call.java:287`, `dex9/sources/com/comelitgroup/sdk/call/Call.java:289`, `dex9/sources/com/comelitgroup/sdk/call/Call.java:293`, `dex9/sources/com/comelitgroup/sdk/call/Call.java:301`).

`PROVEN_STATIC`: RTPC channel creation is subordinate to the native Viper tunnel/channel map, not a new ICE or PseudoTCP constructor by itself. P70 traces official `openChannel` through `ViperTunnel::openChannel`, channel map lookup, `viper_tunnel_channel_create`, and the RTPC OPEN serializer (`safety-poc/research/media/v1/P70_RTPC_OPEN_STATIC_PROVENANCE.md:42`, `safety-poc/research/media/v1/P70_RTPC_OPEN_STATIC_PROVENANCE.md:68`, `safety-poc/research/media/v1/P70_RTPC_OPEN_STATIC_PROVENANCE.md:76`). P73 proves RTPC uses the generic channel allocator and map entry, with runtime-dependent ids and no RTPC-specific allocator branch (`safety-poc/research/media/v1/P73_RTPC_TARGET_ID_STATIC_PROVENANCE.md:115`, `safety-poc/research/media/v1/P73_RTPC_TARGET_ID_STATIC_PROVENANCE.md:144`).

Transport classification:

| Field | Value | Confidence | Anchor |
|---|---:|---|---|
| SAME_ICE_SESSION | true | PROVEN_STATIC for native media RX path | media RX opens a ViperTunnel media channel; no edge from `start_videorx`/`openMediaRXChannel` to `createRemoteConnection` |
| SAME_PSEUDOTCP | true | PROVEN_STATIC for native media RX path | `RtpDispatcher::startVideoRX -> ViperTunnel::openMediaRXChannel -> ViperTunnel::openChannel -> viper_tunnel_channel_create` |
| SAME_CTPP_REGISTRATION | true | STRONGLY_SUPPORTED_STATIC | incoming call is adopted under `VipUnitImpl`, while media RX opens a channel rather than a new registration transaction |
| SAME_NATIVE_PROCESS | true | PROVEN_STATIC | inbound call FSM, RTP dispatcher, and ViperTunnel media channel symbols are in the same official native process/library path |

Architectural proof gate:

| Gate | Value | Confidence | Anchor |
|---|---:|---|---|
| SAME_UPSTREAM_TRANSPORT | true | PROVEN_STATIC | media RX channel creation is inside an existing `ViperTunnel` object, not through tunnel creation |
| NEW_ICE_REQUIRED | false | PROVEN_STATIC for native media RX path | media RX channel open does not call `System::createRemoteConnection`, `createViperTunnel`, or `pOpenViperTunnelP2P` |
| NEW_PSEUDOTCP_REQUIRED | false | PROVEN_STATIC for native media RX path | media RX uses `ViperTunnel::openChannel` and `viper_tunnel_channel_create` inside the tunnel |
| NEW_CTPP_REGISTRATION_REQUIRED | false | STRONGLY_SUPPORTED_STATIC | incoming call is call id scoped (`dex9/sources/com/comelitgroup/sdk/incomingcall/CallService.java:107`, `dex9/sources/com/comelitgroup/sdk/call/CallManager.java:363`); listener preserves registration through CALL_INIT (`safety-poc/research/ring/v4_3/comelit_ice_offer_holder.v4-persistent.c:3682`) |
| NEW_CLOUD_NEGOTIATION_REQUIRED | false | PROVEN_STATIC for native media RX path | media RX channel open has no edge to remote-connection or tunnel-creation symbols |
| NEW_CALL_TRANSACTION_REQUIRED | true | PROVEN_STATIC | incoming call object and active call are created by call id (`dex9/sources/com/comelitgroup/sdk/incomingcall/CallService.java:145`, `dex9/sources/com/comelitgroup/sdk/call/CallManager.java:372`) |
| NEW_RTPC_CHANNELS_REQUIRED | true | STRONGLY_SUPPORTED_STATIC | media requires call-scoped `Connexus.open`/remote video and RTPC lineage (`dex9/sources/com/comelitgroup/sdk/call/Call.java:1016`, `dex9/sources/com/comelitgroup/sdk/call/Call.java:1041`; `safety-poc/research/media/v1/P75_RTPC_CONTROL_MEDIA_STATE_MACHINE.md:82`) |
| MEDIA_TEARDOWN_PRESERVES_TRANSPORT | true | PROVEN_STATIC for native media-only close | `CallFsm::stop_videorx -> RtpDispatcher::stopVideoRX -> ViperTunnel::closeMediaRXChannel` |
| MEDIA_TEARDOWN_PRESERVES_REGISTRATION | true | STRONGLY_SUPPORTED_STATIC | media-only close reaches channel close, not remote connection creation or registration replacement |
| MEDIA_TEARDOWN_PRESERVES_RING_LISTENER | UNKNOWN | UNKNOWN | no inbound media teardown capture |
| PREVIEW_ANSWERS_CALL | false | PROVEN_STATIC | `startCall` opens media path; `answer` is separate (`dex9/sources/com/comelitgroup/sdk/call/CallManager.java:462`, `dex9/sources/com/comelitgroup/sdk/call/CallManager.java:649`) |
| PREVIEW_CAN_RUN_WHILE_RINGING | true | PROVEN_STATIC | not-connected screen receives preview bytes before connected screen (`dex7/sources/com/comelit/bigapp/call/ui/VipCallScreenKt.java:207`, `dex7/sources/com/comelit/bigapp/call/ui/VipCallScreenKt.java:220`) |
| REGISTRATION_TRANSACTION_PRESERVED | PROVEN | PROVEN_STATIC for listener CALL_INIT, UNKNOWN through media | `safety-poc/research/ring/v4_3/comelit_ice_offer_holder.v4-persistent.c:3682` |
| INBOUND_CALL_TRANSACTION_MODEL | PROVEN_STATIC | PROVEN_STATIC | `dex9/sources/com/comelitgroup/sdk/incomingcall/CallService.java:146`; `dex9/sources/com/comelitgroup/sdk/call/CallManager.java:363` |

Listener-attached media is now classified as `R28_OFFLINE_ARCHITECTURE=PROVEN_STATIC_FOR_NATIVE_MEDIA_PATH_WITH_LIVE_TEARDOWN_GAP`. Native static evidence proves the official incoming media path uses call/media channels inside the already-open native tunnel and that media-only close is channel-scoped. It still does not prove our HA listener readiness survives a real attached-media start/stop cycle.

## 5. Preview Versus Answer Semantics

Answer C:

`PROVEN_STATIC`: preview media opening is separable from answering. `VipCallScreen` launches `startCall` as soon as microphone permission is resolved and only invokes `answer` automatically when `hasAnsweredFromNotification` and microphone permission are true (`dex7/sources/com/comelit/bigapp/call/ui/VipCallScreenKt$VipCallScreen$1$1.java:50`, `dex7/sources/com/comelit/bigapp/call/ui/VipCallScreenKt$VipCallScreen$1$1.java:51`, `dex7/sources/com/comelit/bigapp/call/ui/VipCallScreenKt$VipCallScreen$1$1.java:52`, `dex7/sources/com/comelit/bigapp/call/ui/VipCallScreenKt$VipCallScreen$1$1.java:53`). `startCall` delegates to `Call.start`; `answer` delegates to `Call.answer` (`dex9/sources/com/comelitgroup/shared/VipCallViewModel.java:42`, `dex9/sources/com/comelitgroup/shared/VipCallViewModel.java:46`, `dex9/sources/com/comelitgroup/sdk/call/CallManager.java:462`, `dex9/sources/com/comelitgroup/sdk/call/CallManager.java:649`).

`PROVEN_STATIC`: `AnswerCallRequest` is a distinct libcomelit JSON-RPC request with method `answer-call` and an FSM id parameter (`dex9/sources/com/comelitgroup/sdk/call/jsonrpc/libcomelit/AnswerCallRequest.java:114`, `dex9/sources/com/comelitgroup/sdk/call/jsonrpc/libcomelit/AnswerCallRequest.java:126`, `dex9/sources/com/comelitgroup/sdk/call/jsonrpc/libcomelit/AnswerCallRequest.java:166`, `dex9/sources/com/comelitgroup/sdk/call/jsonrpc/libcomelit/AnswerCallRequest.java:171`). `SetVideoResolutionRequest` is a separate method `set-video-resolution`, sent when the libcomelit channel opens (`dex9/sources/com/comelitgroup/sdk/call/Call.java:1376`, `dex9/sources/com/comelitgroup/sdk/call/Call.java:1382`, `dex9/sources/com/comelitgroup/sdk/call/Call.java:2139`, `dex9/sources/com/comelitgroup/sdk/call/Call.java:2145`; `dex9/sources/com/comelitgroup/sdk/call/jsonrpc/libcomelit/SetVideoResolutionRequest.java:114`, `dex9/sources/com/comelitgroup/sdk/call/jsonrpc/libcomelit/SetVideoResolutionRequest.java:118`). `SwitchToNextStreamRequest` is another separate method and is only issued from the button-action path (`dex9/sources/com/comelitgroup/sdk/call/Call.java:1982`, `dex9/sources/com/comelitgroup/sdk/call/Call.java:1999`, `dex9/sources/com/comelitgroup/sdk/call/Call.java:2003`; `dex9/sources/com/comelitgroup/sdk/call/jsonrpc/libcomelit/SwitchToNextStreamRequest.java:95`, `dex9/sources/com/comelitgroup/sdk/call/jsonrpc/libcomelit/SwitchToNextStreamRequest.java:97`).

Required-for-preview classification from offline evidence:

| Operation | Required for preview? | Reason |
|---|---:|---|
| ACCEPT / ANSWER | false | `startCall` opens media path; `answer` and `AnswerCallRequest` are separate (`dex9/sources/com/comelitgroup/sdk/call/Call.java:939`, `dex9/sources/com/comelitgroup/sdk/call/Call.java:1883`) |
| INVITE response | UNKNOWN | not represented by name in staged dex; ledger rows searched for call setup concepts |
| SETUP ACK | UNKNOWN | not represented by name in staged dex; low-level CTP sequence not exposed |
| capabilities negotiation | true-ish for UI state, exact wire requirement UNKNOWN | capabilities update UI flags (`dex9/sources/com/comelitgroup/sdk/call/Call.java:1437`, `dex9/sources/com/comelitgroup/sdk/call/Call.java:1443`), but preview can receive remote video independently |
| UDPM | UNKNOWN | not resolved by staged dex |
| RTPC/Connexus open | true | `Call.start` calls `connexus.open` and registers remote video (`dex9/sources/com/comelitgroup/sdk/call/Call.java:1016`, `dex9/sources/com/comelitgroup/sdk/call/Call.java:1041`) |
| media request | DEVICE_TO_CLIENT parsed request; exact response body still bounded by native media RX path | parsers construct received media-request events, builder callers are zero, and native incoming alerting reaches video RX (`dex8/sources/com/comelitgroup/comelitvipkit/VipMessageParser.java:358`; `dex8/sources/com/comelitgroup/comelitvipkit/event/vip/callevent/MediaReqEvt.java:51`) |

Answer D:

`PREVIEW_ANSWERS_CALL=false`. Static evidence supports preview/answer as distinct operations. Architectural consequence: the next implementation round may model attached preview as media-starting/ringing-preserving, but must still gate any explicit answer/accept operation separately and never treat preview start as consent to answer.

## 6. Teardown Semantics

Answer G:

`PROVEN_STATIC`: official SDK call stop is call-scoped. `CallManager.stopCall` delegates to `Call.stop` by call id and later removes that active call from the active map (`dex9/sources/com/comelitgroup/sdk/call/CallManager.java:1434`, `dex9/sources/com/comelitgroup/sdk/call/CallManager.java:1436`, `dex9/sources/com/comelitgroup/sdk/call/CallManager.java:1404`, `dex9/sources/com/comelitgroup/sdk/call/CallManager.java:1406`). `Call.stop` stops recording, sends a call-end request only in the new call-state path, closes `Connexus`, marks the call closed, and cancels the call coroutine scope (`dex9/sources/com/comelitgroup/sdk/call/Call.java:2385`, `dex9/sources/com/comelitgroup/sdk/call/Call.java:2391`, `dex9/sources/com/comelitgroup/sdk/call/Call.java:2354`, `dex9/sources/com/comelitgroup/sdk/call/Call.java:2361`, `dex9/sources/com/comelitgroup/sdk/call/Call.java:2362`). `requestCallEnd` sends over the call channel, not a registration channel (`dex9/sources/com/comelitgroup/sdk/call/Call.java:2184`, `dex9/sources/com/comelitgroup/sdk/call/Call.java:2190`).

`PROVEN_STATIC` for official media-only close scope: `CallFsm::stop_videorx()` reaches `RtpDispatcher::stopVideoRX()` and then `ViperTunnel::closeMediaRXChannel(...)`. That close path is channel-scoped and does not construct a new remote connection, close the Viper tunnel, or replace registration.

`UNKNOWN` remains for our HA listener survival after live attached media. The official media-only close proves what the native media channel does; it does not prove a Home Assistant listener process remains ready after a real inbound attached-media start/stop cycle. The exact call-transaction end state after media-only stop also remains a live scalar gap.

## 7. Door Coexistence Static Analysis

`DOOR_DURING_ATTACHED_MEDIA_STATIC=POSSIBLE`.

Current production deliberately blocks Door while separate media owns the upstream connection (`docs/intercom-media-session-architecture.md:192`, `custom_components/comelit/supervisor.py:149`). Official incoming-call static evidence shows Door is available as a call notification/action path during incoming-call handling: `CallConnection.onOpenDoor` selects `SET_POWER` button actions and launches execution (`dex9/sources/com/comelitgroup/sdk/incomingcall/CallConnection.java:126`, `dex9/sources/com/comelitgroup/sdk/incomingcall/CallConnection.java:142`, `dex9/sources/com/comelitgroup/sdk/incomingcall/CallConnection.java:145`, `dex9/sources/com/comelitgroup/sdk/incomingcall/CallConnection.java:153`), and `CallService` wires a pending service action for open door (`dex9/sources/com/comelitgroup/sdk/incomingcall/CallService.java:127`, `dex9/sources/com/comelitgroup/sdk/incomingcall/CallService.java:137`). Our current Door path can use the persistent listener process when running and ready (`custom_components/comelit/runtime.py:307`, `custom_components/comelit/runtime.py:312`, `custom_components/comelit/runtime.py:352`). Therefore static coexistence is possible, not blocked by the staged state machine; this is not physical proof and no Door command was executed.

## 8. Official App Static-Analysis Results

| Required field | Value | Provenance and semantic chain |
|---|---:|---|
| STATIC_CALL_PATH_FOUND | true | `handleCallStartNotification` adds a Telecom incoming call; `CallService.onCreateIncomingConnection` creates `CallConnection` and SDK `Call`; `VipCallActivity` renders the call UI (`dex9/sources/com/comelitgroup/sdk/incomingcall/ComelitSDKAndroid.java:79`, `dex9/sources/com/comelitgroup/sdk/incomingcall/CallService.java:75`, `dex9/sources/com/comelitgroup/sdk/incomingcall/CallService.java:144`, `dex7/sources/com/comelit/bigapp/call/VipCallActivity.java:78`). |
| STATIC_PREVIEW_PATH_FOUND | true | `VipCallScreen` launches `startCall`, `Call.start` opens `Connexus`, remote video and preview bytes feed `CallState`, and not-connected UI receives preview bytes (`dex7/sources/com/comelit/bigapp/call/ui/VipCallScreenKt$VipCallScreen$1$1.java:51`, `dex9/sources/com/comelitgroup/sdk/call/Call.java:1016`, `dex9/sources/com/comelitgroup/sdk/call/Call.java:1088`, `dex7/sources/com/comelit/bigapp/call/ui/VipCallScreenKt.java:220`). |
| STATIC_MEDIA_OPEN_PATH_FOUND | true | `Call.start` registers remote video and calls `connexus.open`; P70/P73 trace official RTPC open through Java/JNI/native ViperTunnel open and allocator (`dex9/sources/com/comelitgroup/sdk/call/Call.java:1041`, `dex9/sources/com/comelitgroup/sdk/call/Call.java:1016`; `safety-poc/research/media/v1/P70_RTPC_OPEN_STATIC_PROVENANCE.md:42`, `safety-poc/research/media/v1/P73_RTPC_TARGET_ID_STATIC_PROVENANCE.md:165`). |
| STATIC_MEDIA_TEARDOWN_PATH_FOUND | true | `Call.stop` calls `requestCallEnd` for new call states, closes call-scoped `Connexus`, marks call state closed, and cancels the call coroutine scope (`dex9/sources/com/comelitgroup/sdk/call/Call.java:2354`, `dex9/sources/com/comelitgroup/sdk/call/Call.java:2361`, `dex9/sources/com/comelitgroup/sdk/call/Call.java:2362`, `dex9/sources/com/comelitgroup/sdk/call/Call.java:2385`, `dex9/sources/com/comelitgroup/sdk/call/Call.java:2391`). Native media-only close reaches `CallFsm::stop_videorx -> RtpDispatcher::stopVideoRX -> ViperTunnel::closeMediaRXChannel`. HA listener survival remains UNKNOWN. |

Required artifact provenance: official-app dex/native/prior-analysis artifacts were staged from CT120 at UTC `2026-09-13T13:54Z` (`.r28-evidence/PROVENANCE.txt:27`, `.r28-evidence/PROVENANCE.txt:36`, `.r28-evidence/PROVENANCE.txt:39`). The staged prior analysis hash is `7c8afb723e36c9d82831496bd1eea16623642b09978ea34e89df667312df2fe4` (`.r28-evidence/PROVENANCE.txt:39`).

## 9. Saved Capture Analysis Result

`CAPTURE_INBOUND_MEDIA_EVIDENCE=UNAVAILABLE`.

The staged captures are identified as self-activation/outgoing candidates in provenance (`.r28-evidence/PROVENANCE.txt:47`). Prior analysis of `self_activation.pcap` records one ring-like frame, but its direction is client-to-device, so it is not inbound DEVICE_TO_CLIENT CALL_INIT evidence (`.r28-evidence/official-app/prior-analysis/comelit-media-offline-analysis.txt:1901`, `.r28-evidence/official-app/prior-analysis/comelit-media-offline-analysis.txt:1903`, `.r28-evidence/official-app/prior-analysis/comelit-media-offline-analysis.txt:1904`). P77 proves media/RTP in the self-activation capture, not inbound preview (`safety-poc/research/media/v1/P77_ENTRANCE_MEDIA_OFFLINE_INTEGRATION_AND_LIVE_GAP_ANALYSIS.md:49`, `safety-poc/research/media/v1/P77_ENTRANCE_MEDIA_OFFLINE_INTEGRATION_AND_LIVE_GAP_ANALYSIS.md:65`). `p2p_rtsp.pcap` is an RTSP/P2P contrast capture and P77 does not classify it as the same offset-8 media proof (`safety-poc/research/media/v1/P77_ENTRANCE_MEDIA_OFFLINE_INTEGRATION_AND_LIVE_GAP_ANALYSIS.md:120`).

## 10. External Corroboration And Constants

External corroboration says one transport and one CTPP channel carry registration, inbound calls, Door, and outgoing video call transactions (`.r28-evidence/external/comelit-vip/session.py:1`). It also shows inbound calls adopted as a CTP connection on the open CTPP channel, with ring callback before acknowledgement and a call-end watcher (`.r28-evidence/external/comelit-vip/session.py:456`, `.r28-evidence/external/comelit-vip/session.py:475`, `.r28-evidence/external/comelit-vip/session.py:521`). It models RTPC media channels and media payload handlers inside the same connection (`.r28-evidence/external/comelit-vip/call.py:131`, `.r28-evidence/external/comelit-vip/call.py:153`, `.r28-evidence/external/comelit-vip/call.py:161`).

Per-constant support:

| Constant / concept | Our evidence supports | Note |
|---|---:|---|
| one persistent transport can carry CTPP registration and CALL_INIT | yes | our listener proves registration and CALL_INIT in one session (`safety-poc/research/ring/v4_3/comelit_ice_offer_holder.v4-persistent.c:1647`, `safety-poc/research/ring/v4_3/comelit_ice_offer_holder.v4-persistent.c:3627`) |
| official app has call-scoped incoming media preview | yes | `CallService` -> `CallManager.createCall` -> `VipCallScreen` -> `Call.start` (`dex9/sources/com/comelitgroup/sdk/incomingcall/CallService.java:146`, `dex7/sources/com/comelit/bigapp/call/ui/VipCallScreenKt$VipCallScreen$1$1.java:51`) |
| media uses RTPC/Connexus channels | yes for official app and self-activation lineage | `Call.start` opens `Connexus` (`dex9/sources/com/comelitgroup/sdk/call/Call.java:1016`); P70/P75/P76 (`safety-poc/research/media/v1/P70_RTPC_OPEN_STATIC_PROVENANCE.md:138`, `safety-poc/research/media/v1/P75_RTPC_CONTROL_MEDIA_STATE_MACHINE.md:93`) |
| no new CTPP OPEN for initial media path | yes for self-activation only | `SECOND_CTPP_OPEN=false` (`safety-poc/research/media/v1/P76_RTPC_C_RUNTIME_PARITY.md:117`) |
| external refresh cadence | no | R26 rejects adopting the external cadence (`safety-poc/research/media/v1/P116_R26_D1_MEDIA_LEASE_REFRESH_ANALYSIS.md:47`) |
| external repeated media request effect | no | R27 leaves repeat/effect not proven (`safety-poc/research/media/v1/P116_R27_D1_REPEAT_001A_LIVE_PROOF.md:89`) |
| external handle/id start values | no | our allocator start is runtime-dependent (`safety-poc/research/media/v1/P73_RTPC_TARGET_ID_STATIC_PROVENANCE.md:175`) |
| external timeouts | no | not promoted into our production contract |

## 11. Proposed Production Model, Design Text Only

Proposed future shape, blocked only on live HA listener-survival proof before production:

```text
ComelitSessionRuntime
  owns one persistent cloud/P2P/PseudoTCP/VIP native session
  owns registration and listener readiness
  RingController observes CALL_INIT and creates local event_id
  DoorController issues one-shot Door attempts only through proven state gates
  AttachedMediaController attaches to an active inbound call context
    binds normalized ring event to call-scoped context
    opens call-scoped media channels without answering only after the inbound RX contract is proven
    forwards raw H264 RTP to the existing loopback H264RecoveryRtpShim path
    tears down media-only resources without stopping registration/listener
```

`ComelitMediaSessionManager` should not be removed. In the listener-attached model it becomes the media lease/lifetime manager and arbiter of maximum media lifetime, leases, and HA-visible state, not the owner of a separate upstream session. The already-proven data plane remains Python-side `H264RecoveryRtpShim -> HA Stream -> HLS -> camera entity`; R28 must not move H264 recovery into native C (`custom_components/comelit/h264_recovery.py:179`, `custom_components/comelit/media_transport.py:540`, `custom_components/comelit/camera.py:219`).

Ring-driven user-flow state model:

```text
LISTENING
-> CALL_INIT
-> RINGING
-> ATTACHED_MEDIA_STARTING
-> RING_MEDIA_ACTIVE
-> IGNORE | OPEN | TIMEOUT
-> ATTACHED_MEDIA_STOPPING
-> LISTENING
```

The persistent registration never stops in this proposed model. Round 4 native static evidence supports media RX channel open and close without new transport or registration, but does not prove HA listener readiness after a live attached-media stop. `OPEN` means only a future user-flow branch; no Door execution is part of R28. Mapping sketch: HA-local `event_id` binds normalized ring event, door enum, attached call context, media lease id, and notification/Telegram interaction context. The protocol call identifier remains `UNKNOWN` until proven, matching the existing ring contract (`safety-poc/docs/RING_EVENT_CONTRACT.md:54`).

## 11A. Round 4 Research Candidate

Phase 4B result: `PHASE_4B=RUN`.

Candidate path: `safety-poc/research/media/v1/entrance_p116_r28_listener_attached_media_transform.py`.

The candidate is an offline-only state model, not production code and not a network helper. Its state machine is:

```text
LISTENER_READY
-> CALL_INIT from entrance
-> ARMED
-> ACTIVE
-> CLOSED | FAILED_CLOSED
```

Fail-closed gates: no media before `CALL_INIT`; unknown or gate source does not arm entrance media; malformed signaling moves to `FAILED_CLOSED`; registration state and call-transaction state are distinct objects; a second `CALL_INIT` during active media is blocked; teardown is idempotent; Door, Gate, refresh loop, new ICE, new cloud negotiation, new PseudoTCP, and new registration are all represented as false and cannot be enabled by the model.

Explicit UNKNOWN seam: `teardown_ring_listener_survival_proven` defaults false and reports `MEDIA_TEARDOWN_PRESERVES_RING_LISTENER=UNKNOWN`. This keeps the live HA listener-survival gap visible even though native media-channel close is statically scoped to `closeMediaRXChannel`.

The RTP boundary is scalar-only: `emit_h264_rtp_to_loopback_boundary(...)` increments packet counts for the existing `H264RecoveryRtpShim` path and never opens a socket or emits payload bytes.

Focused tests: `PYTHONPATH=safety-poc/src python3 -m unittest safety-poc/tests/test_p116_r28_listener_attached_media_contract.py` ran `21` tests, `OK`, with `1` skip for `sandbox_loopback_udp_denied`. `python3 -m py_compile` passed for the new Python files. `bash -n safety-poc/research/media/v1/ct120_run_p116_r28_listener_attached_media_live.sh` passed.

Runner path: `safety-poc/research/media/v1/ct120_run_p116_r28_listener_attached_media_live.sh`. It defaults `R28_LIVE_RUN=false`; materializes a candidate helper; substitutes the helper into a per-lane wrapper; executes the wrapper in self-check mode; and requires `CANDIDATE_HELPER_EXECUTED=true` plus helper provenance before any possible live step. This carries forward the R27 materialized-helper lesson and avoids env-path substitution fallback to the base wrapper.

30-second/D1 assessment:

`OBSERVED_BASELINE_EXCEEDS_30S=true` as an observation only. R25 observed video RTP for 34.9 seconds in one live session (`safety-poc/research/media/v1/P116_R25_RECOVERY_POINT_LIVE_VALIDATION.md:56`), and P116 stream bridge notes other observed runs near the same range (`safety-poc/docs/P116_HA_STREAM_RTP_BRIDGE.md:30`). This is not a guarantee and not a production constant. Refresh remains unimplemented and unproven (`safety-poc/research/media/v1/P116_R26_D1_MEDIA_LEASE_REFRESH_ANALYSIS.md:57`, `safety-poc/research/media/v1/P116_R27_D1_REPEAT_001A_LIVE_PROOF.md:91`).

## 12. Unknowns, Missing Evidence, Bounded Remaining Proof

MISSING_EVIDENCE:

1. A saved or future bounded capture/log proving inbound DEVICE_TO_CLIENT CALL_INIT followed by preview/video, RTPC open, media request handling, and RTP in the same listener session, with only scalar booleans/counts/directions.
2. A scalar teardown observation showing whether media-only stop preserves HA listener readiness after an attached-media run.
3. A scalar call-transaction observation showing whether media-only stop leaves, releases, or ends the incoming call transaction.
4. A bounded state-machine proof for Door behavior while ring-attached media is active; no physical Door action in this proof.
5. Low-level sequence/ack semantics for the inbound call CTP transaction, reported only as abstract booleans/counts/directions.

Remaining bounded live proof design text only:

```text
precondition: listener running and ready, no active media, LIVE_AUTHORIZED=true in a later task
observe inbound CALL_INIT
do not answer, do not open Door
attempt attached preview only if operator authorizes preview-state test
record scalar markers:
  same native process true/false
  new cloud negotiation observed true/false
  new ICE observed true/false
  new PseudoTCP observed true/false
  new CTPP registration observed true/false
  new call transaction observed true/false
  new RTPC channels observed true/false
  media request direction device_to_client
  inbound video rx initiation auto_on_incoming_call
  RTP observed true/false
  preview answered/mutated call true/false/unknown
stop attached media only
record transport/registration/listener survival true/false
record call transaction release/end state true/false/unknown
```

## 13. Confidence Ledger And Final Marker

Confidence ledger:

| Claim | Confidence |
|---|---|
| Current production media is separate-session/listener-pausing | PROVEN_STATIC |
| Current ring event is incoming CALL_INIT and read-only | PROVEN_OFFLINE |
| Official app has staged inbound call service/UI/SDK media preview path | PROVEN_STATIC |
| Preview and answer are separate official app operations | PROVEN_STATIC |
| Preview can render while official app call UI is not connected | PROVEN_STATIC |
| Self-activation media uses CTPP media signaling, RTPC channels, and RTP forwarding | PROVEN_OFFLINE |
| Official native media open/receive/teardown symbols exist | PROVEN_STATIC |
| Inbound preview can attach without new upstream transport | PROVEN_STATIC for official native media path; live HA scalar still needed |
| Exact inbound media request direction | PROVEN_STATIC for parsed `HANDLE_MEDIAREQ` event |
| Inbound native video RX initiation | PROVEN_STATIC as AUTO_ON_INCOMING_CALL |
| Attached media teardown preserves listener readiness | UNKNOWN |
| Door static coexistence during attached media | POSSIBLE_STATIC, not live-safe proof |

```text
=== COMELIT P116 R28 ROUND 4 REPORT ===
BASE_SHA=a30b1cbfef81c26c2a2fe28d3b280bf253161d9d
DOC_PATH=safety-poc/research/media/v1/P116_R28_LISTENER_ATTACHED_INBOUND_MEDIA_ANALYSIS.md
CHANGED_FIELDS=ROUND,INBOUND_VIDEO_RX_INITIATION,SAME_UPSTREAM_TRANSPORT,SAME_ICE_SESSION,SAME_PSEUDOTCP,SAME_CTPP_REGISTRATION,SAME_NATIVE_PROCESS,NEW_CLOUD_NEGOTIATION_REQUIRED,NEW_ICE_REQUIRED,NEW_PSEUDOTCP_REQUIRED,MEDIA_TEARDOWN_PRESERVES_TRANSPORT,MEDIA_TEARDOWN_PRESERVES_REGISTRATION,R28_OFFLINE_ARCHITECTURE,PHASE_4B,RESEARCH_CANDIDATE_IMPLEMENTED,RESEARCH_CANDIDATE_PATH,RESEARCH_CANDIDATE_TESTS,FOCUSED_TESTS,R28_RUNNER_PATH,IMPLEMENTATION
NATIVE_LIBS_ANALYSED=libvipcomelit.so,libsafecomelit.so,libcomelitvipkit.so
INBOUND_VIDEO_RX_INITIATION=AUTO_ON_INCOMING_CALL
INBOUND_VIDEO_RX_CHAIN=VipUnitImpl::new_call_ctp_conn->VipUnitImpl::handleCtpStart->VipUnitImpl::vip_unit_accept_call->CallFsm::enqueueEvent->CallFsm::st_idle->CallFsm::go_in_alerting->CallFsm::start_videorx->RtpDispatcher::startVideoRX
INBOUND_MEDIA_REQUEST_DIRECTION=DEVICE_TO_CLIENT
SAME_UPSTREAM_TRANSPORT=true
SAME_ICE_SESSION=true
SAME_PSEUDOTCP=true
SAME_CTPP_REGISTRATION=true
SAME_NATIVE_PROCESS=true
NEW_CLOUD_NEGOTIATION_REQUIRED=false
NEW_ICE_REQUIRED=false
NEW_PSEUDOTCP_REQUIRED=false
NEW_CTPP_REGISTRATION_REQUIRED=false
NEW_CALL_TRANSACTION_REQUIRED=true
NEW_RTPC_CHANNELS_REQUIRED=true
PREVIEW_ANSWERS_CALL=false
PREVIEW_CAN_RUN_WHILE_RINGING=true
MEDIA_TEARDOWN_PRESERVES_TRANSPORT=true
MEDIA_TEARDOWN_PRESERVES_REGISTRATION=true
MEDIA_TEARDOWN_PRESERVES_RING_LISTENER=UNKNOWN
DOOR_DURING_ATTACHED_MEDIA_STATIC=POSSIBLE
R28_OFFLINE_ARCHITECTURE=PROVEN_STATIC_FOR_NATIVE_MEDIA_PATH_WITH_LIVE_TEARDOWN_GAP
PHASE_4B=RUN
RESEARCH_CANDIDATE_IMPLEMENTED=true
RESEARCH_CANDIDATE_PATH=safety-poc/research/media/v1/entrance_p116_r28_listener_attached_media_transform.py
RESEARCH_CANDIDATE_TESTS=safety-poc/tests/test_p116_r28_listener_attached_media_contract.py
FOCUSED_TESTS=Ran 21 tests OK skipped=1 sandbox_loopback_udp_denied
R28_RUNNER_PATH=safety-poc/research/media/v1/ct120_run_p116_r28_listener_attached_media_live.sh
R28_LIVE_RUN_DEFAULT=false
R27_REPEAT_USED=false
D1_REFRESH_IMPLEMENTED=false
OBSERVED_BASELINE_EXCEEDS_30S=true
PRODUCTION_FILES_CHANGED=0
NATIVE_PRODUCTION_BINARY_CHANGED=false
TRACKED_FILES_ADDED=safety-poc/research/media/v1/P116_R28_LISTENER_ATTACHED_INBOUND_MEDIA_ANALYSIS.md;safety-poc/research/media/v1/entrance_p116_r28_listener_attached_media_transform.py;safety-poc/tests/test_p116_r28_listener_attached_media_contract.py;safety-poc/research/media/v1/ct120_run_p116_r28_listener_attached_media_live.sh
TRACKED_FILES_MODIFIED=
MISSING_EVIDENCE=ha_listener_survival_after_attached_media_teardown;call_transaction_end_state_after_media_only_stop;door_during_attached_media_bounded_state_machine;inbound_call_transaction_sequence_ack_semantics
IMPLEMENTATION=READY_FOR_NEXT_ROUND
LIVE_RUN=NOT_RUN
=== END COMELIT P116 R28 ROUND 4 REPORT ===
```

## 14. Search Ledger

Command form for dex rows: `rg --hidden --no-ignore -l -F <pattern> .r28-evidence/official-app/dex7/sources .r28-evidence/official-app/dex8/sources .r28-evidence/official-app/dex9/sources | wc -l`. The initial hidden/ignored default was explicitly corrected; counts below use hidden and no-ignore scanning.

| Pattern / symbol | Scope | Matching files | Conclusion |
|---|---|---:|---|
| `CallService` | dex7/8/9 sources | 2 | found-and-used: inbound Android service |
| `onCreateIncomingConnection` | dex7/8/9 sources | 1 | found-and-used: Telecom incoming-call entry |
| `handleCallStartNotification` | dex7/8/9 sources | 2 | found-and-used: notification to Telecom |
| `ComelitNotification.CallStart` | dex7/8/9 sources | 12 | found-and-used: call id/endpoint schema |
| `CallManager.INSTANCE.createCall` | dex7/8/9 sources | 2 | found-and-used: incoming SDK call creation |
| `showUIForIncomingCall` | dex7/8/9 sources | 10 | found-and-used: UI path |
| `previewImageBytes` | dex7/8/9 sources | 8 | found-and-used: preview bytes state/UI |
| `VipCallNotConnected` | dex7/8/9 sources | 5 | found-and-used: ringing/not-connected preview UI |
| `startCall` | dex7/8/9 sources | 9 | found-and-used: media-start path |
| `answer` | dex7/8/9 sources | 61 | found-and-used: distinct answer path |
| `AnswerCallRequest` | dex7/8/9 sources | 7 | found-and-used: explicit answer JSON-RPC |
| `sendAnswerCallRequest` | dex7/8/9 sources | 4 | found-and-used: answer request plumbing |
| `SetVideoResolutionRequest` | dex7/8/9 sources | 4 | found-and-used: video-control separate from answer |
| `SwitchToNextStreamRequest` | dex7/8/9 sources | 2 | found-and-used: stream-control separate from answer |
| `HANDLE_MEDIAREQ` | dex7/8/9 sources | 4 | found-and-used: media request parser/builder |
| `MediaReqEvt` | dex7/8/9 sources | 4 | found-and-used: VIP media request event and builder |
| `VideoCallMediaReqEvt` | dex7/8/9 sources | 2 | found-and-used: SAFE media request parser |
| `CallMediaController` | dex7/8/9 sources | 4 | found-but-inconclusive: multimedia helper present, not needed for inbound UI proof |
| `RtspFsmEvent` | dex7/8/9 sources | 13 | found-and-used: RTSP event updates video availability |
| `VipCallFsmStatusChange` | dex7/8/9 sources | 12 | found-and-used: VIP call status updates |
| `RtspCallFsmStatusChange` | dex7/8/9 sources | 13 | found-and-used: RTSP call status updates |
| `requestCallEnd` | dex7/8/9 sources | 2 | found-and-used: call stop/teardown |
| `connexus.close` | dex7/8/9 sources | 4 | found-and-used: call-scoped close |
| `CALL_INIT` | dex7/8/9 sources | 0 | genuinely absent from dex; CALL_INIT proof remains native/listener-side |
| `INCOMING_CALL` | dex7/8/9 sources | 8 | found-but-inconclusive: Android constant names only, not low-level CTP |
| `openChannel` | dex7/8/9 sources | 14 | found-and-used with P70/P73 lineage |
| `auto_start_videorx` | dex7/8/9 sources | 0 | genuinely absent from Java/Kotlin; native symbol only |
| `start_videorx` | dex7/8/9 sources | 0 | genuinely absent from Java/Kotlin; native symbol only |
| `stop_videorx` | dex7/8/9 sources | 0 | genuinely absent from Java/Kotlin; native symbol only |
| `releaseFsm` | dex7/8/9 sources | 0 | genuinely absent from Java/Kotlin; native symbol only |
| `accept_call` | dex7/8/9 sources | 0 | genuinely absent from Java/Kotlin; native symbol only |
| `MediaReqEvt.Companion` | dex7/8/9 sources | 0 | Round 3 caller check: no reachable declaration/caller reference by this spelling |
| `MediaReqEvt.INSTANCE` | dex7/8/9 sources | 0 | Round 3 caller check: no generated singleton caller reference |
| `.message(` | dex7/8/9 sources | 1 | declaration-side match only in `MediaReqEvt`, not a proven caller |
| `HANDLE_MEDIAREQ` | dex7/8/9 sources | 4 | parser/builder enum use; received parser branch is the load-bearing direction evidence |
| `call_init` | dex7/8/9 sources | 0 | confirms no dex low-level CALL_INIT spelling by lowercase pattern |
| `CALL_INIT` | dex7/8/9 sources | 0 | confirms CALL_INIT proof is listener/native lineage, not dex |
| `connexus.close` | dex7/8/9 sources | 4 | call-scoped close found; native media-only close still needed for channel scope |
| `requestCallEnd` | dex7/8/9 sources | 2 | call transaction end request found in call stop path |
| `createViperTunnel` | dex7/8/9 sources | 3 | tunnel creation Java/JNI API exists; native Round 4 scan found no media-RX edge to tunnel creation |
| `openChannel` | dex7/8/9 sources | 14 | RTPC/channel path exists; native Round 4 scan ties media RX to channel creation |
| `PseudoTCP` | dex7/8/9 sources | 0 | no dex proof for same/new PseudoTCP on inbound preview |
| `CTPP` | dex7/8/9 sources | 2 | sparse dex mentions only; no inbound media registration survival proof |
| `ICE` | dex7/8/9 sources | 231 | WebRTC/ICE symbols present; no inbound same-session proof by search alone |
| `auto_start_videorx` | `nm -D -C`, `readelf -sW`, PLT-mapped AArch64 BL scan | symbol present, no named caller found | not load-bearing; incoming RX proof uses `go_in_alerting -> start_videorx` |
| `start_videorx` | `nm -D -C`, `readelf -sW`, PLT-mapped AArch64 BL scan | symbol present in VIP and SAFE libs | reached by `go_in_alerting`, `st_in_alerting`, `go_connected`, `st_connected`, and outgoing states; incoming alerting chain proves `AUTO_ON_INCOMING_CALL` |
| `update_videorx` | `nm -D -C`, `readelf -sW`, PLT-mapped AArch64 BL scan | symbol present, no load-bearing caller found | probed; not required for initiation verdict |
| `stop_videorx` | `nm -D -C`, `readelf -sW`, PLT-mapped AArch64 BL scan | symbol present in VIP and SAFE libs | reached by FSM state paths and calls `RtpDispatcher::stopVideoRX`; proves native media-only close scope, not HA listener survival |
| `stop_videotx` | `nm -D -C`, `readelf -sW`, PLT-mapped AArch64 BL scan | symbol present in VIP and SAFE libs | probes TX stop only; not an RX initiation dependency |
| `handle_mediareq` | `nm -D -C`, `readelf -sW`, PLT-mapped AArch64 BL scan, `strings` | reached by `st_in_alerting`, `st_connected`, and outgoing states | media request handling exists in incoming alerting and connected states; parsed event direction remains `DEVICE_TO_CLIENT` |
| `VipUnitImpl::mediaManagerIsOnVideoRX` | `nm -D -C`, `readelf -sW`, PLT-mapped AArch64 BL scan | symbol present; SAFE live-view handler calls it | status query only; not an initiation edge |
| `VipUnitImpl::new_call_ctp_conn` | PLT-mapped AArch64 BL scan, `strings` | caller of `VipUnitImpl::handleCtpStart` | inbound call transaction adoption path |
| `VipUnitImpl::handleCtpStart` | PLT-mapped AArch64 BL scan | calls `VipUnitImpl::vip_unit_accept_call` | inbound CTP start reaches call FSM machinery |
| `VipUnitImpl::vip_unit_accept_call` | PLT-mapped AArch64 BL scan, `strings` | calls `CallFsm::enqueueEvent` | native call adoption; not SDK explicit `answer-call` |
| `CallFsm::run` | PLT-mapped AArch64 BL scan | called by `VipUnitImpl::run`; receives CSP and queues events | FSM event machinery origin |
| `CallFsm::dequeue_msg` | PLT-mapped AArch64 BL scan | symbol present and calls event-queue helpers | probed for FSM machinery; initiation proof uses state handlers |
| `CallFsm::go_in_alerting` | PLT-mapped AArch64 BL scan, `strings` | called by `st_idle`; calls `start_videorx` | incoming alerting reaches video RX before connected/answer |
| `CallFsm::st_in_alerting` | PLT-mapped AArch64 BL scan, `strings` | calls `start_videorx` and `handle_mediareq` | ringing/in-alerting media path can process media request and start RX |
| `RtpDispatcher::startVideoRX` | PLT-mapped AArch64 BL scan | called by `CallFsm::start_videorx`; calls `ViperTunnel::openMediaRXChannel` | RX opens media channel in tunnel |
| `RtpDispatcher::stopVideoRX` | PLT-mapped AArch64 BL scan | called by `CallFsm::stop_videorx`; calls `ViperTunnel::closeMediaRXChannel` | media-only close path |
| `ViperTunnel::openMediaRXChannel` | `nm -D -C`, PLT-mapped AArch64 BL scan | calls `ViperTunnel::openChannel` | media RX uses tunnel channel creation |
| `ViperTunnel::openChannel` | staged disassembly, PLT-mapped AArch64 BL scan | calls `viper_tunnel_channel_create` | channel creation inside existing tunnel |
| `viper_tunnel_channel_create` | staged disassembly, PLT-mapped AArch64 BL scan | called by `openChannel` and CTP channel open helpers | allocates channels; not remote connection creation |
| `ViperTunnel::closeMediaRXChannel` | `nm -D -C`, PLT-mapped AArch64 BL scan | called by RX stop paths | closes media channel state only; not proof of HA listener survival |
| `createViperTunnel` | staged disassembly + PLT-mapped AArch64 BL scan | tunnel creation path calls P2P/cloud open functions | not reached by media RX channel chain |
| `pOpenViperTunnelP2P` | staged disassembly + PLT-mapped AArch64 BL scan | calls `System::createRemoteConnection` | transport bootstrap path; not reached by media RX channel chain |
| `sysViperSendOnChannel` | staged evidence + prior media analysis + ring lineage | 2 | channel-send plumbing exists; not a media request direction override |
| `PseudoTCP` | staged evidence + prior media analysis + ring lineage | 53 | native media RX chain reuses tunnel channel path; live scalar still needed for HA process observation |
| `CTPP` | staged evidence + prior media analysis + ring lineage | 80 | registration/call lineage present; media RX does not create new registration; live listener survival remains UNKNOWN |

Native-symbol cross-check: plain `objdump` in this sandbox could not disassemble the AArch64 objects. Round 4 therefore used `nm -D -C`, `readelf -sW`, `readelf -rW`, staged native-disasm text, strings, and a bounded PLT-mapped AArch64 `BL` target scan. No raw addresses, offsets, payloads, or identifiers are recorded here.
