# P116 R29A Inbound Media Wire Contract

TASK_ID=COMELIT-P116-R29A-INBOUND-MEDIA-WIRE-CONTRACT
MODE=DEV_OFFLINE
ROUND=R29A-4
BASE_SHA=9607708ca555e615895583dd719850ffc809cd73
LIVE_RUN=NOT_RUN
RAW_PAYLOAD_EMITTED=false
PRODUCTION_FILES_CHANGED=0
NATIVE_PRODUCTION_BINARY_CHANGED=false

## Scope And Evidence

This round analyses only staged text evidence under
`.r29a-evidence/native-disasm/` plus the existing repository lineage. It did
not contact the Comelit network, production listener, Home Assistant, Door,
Gate, PseudoTCP, ICE, CTPP registration, or any live device.

New staged evidence reviewed in this round:

- `disasm3-CallFsm__initNewConnectionStart_unsigned_short__csp_msgbuf__.txt`
- `disasm3-ViperTunnel__onChannelOpenRes_viper_channel_str___viper_error_.txt`
- `disasm3-RtpDispatcher__RtpDispatcher_cfg_t___void___unsigned_int__unsigned_short_.txt`
- `symbol-index-batch3.txt`
- Prior staged `symbol-index-batch2.txt`, including the `csp_send_*` layer,
  RTP TX/RX helpers, and Viper tunnel/channel helpers.

No proprietary binary, raw payload, token, session id, absolute address, or byte
dump is included here. Function references use symbol names and relative
instruction descriptions only.

## Round 2 Findings

F1_CLOSE_PATH_WIRE_EMISSION=CONFIRMED_REFINED. `CallFsm::stop_videorx()`
checks the video-RX enable/running guards, emits exactly one
`csp_send_mediareq26` for the transition, then calls
`RtpDispatcher::stopVideoRX()`. The previous
`MEDIA_CLOSE_WIRE_ACTION=RTPC_CLOSE` label was imprecise. The load-bearing
close primitive is a call-bound `mediareq26` stop emission plus local media
disposal. In tunnel mode, `stopVideoRX` also calls
`ViperTunnel::closeMediaRXChannel(saved_channel_ptr, saved_channel_id)`.
That direct function is local validation/status work; its `setChannelStatus`
callee can conditionally enter `closeChAndFreeStructure` and
`viper_channel_close`, but the close model is not a required standalone RTPC
close and not a call/CTP release.

F2_DISPATCH_MODEL=REFUTED_AS_INDIRECT. `csp_send_mediareq26` constructs a
fixed-size message buffer with message type `0x1A`, stores a `0x1100` prefix,
copies argument-derived fields into the body, and tail-dispatches directly to
`ctp_write`. The staged text does not show an unresolved indirect sender for
this helper.

F3_OPEN_LOCAL_MODEL=CONFIRMED_WITH_WIRE_SPLIT. `RtpDispatcher::startVideoRX`
starts local RX state. With a tunnel pointer present it calls
`ViperTunnel::openMediaRXChannel`, which uses media RX channel type `0xa`,
stores the returned channel pointer and id, and sets the RTP payload type. In
the no-tunnel branch it uses `inet_aton`, `Rtp::rtp_rx_start`, a `Thread`, and
payload setup. `startVideoRX` itself does not call `csp_send_mediareq26`; the
call-bound wire media request is emitted by `CallFsm::start_videorx`.

F4_CLOSE_LOCAL_MODEL=PARTLY_REFUTED. Directly,
`ViperTunnel::closeMediaRXChannel` only logs, validates
`viper_channel_get_id`, locks, searches the channel-status list, calls
`setChannelStatus`, unlocks, and logs. However `setChannelStatus` has a visible
conditional path for closed state that calls `closeChAndFreeStructure`, and
that callee calls `viper_channel_close` and `viper_channel_free`. Therefore the
direct function is local/status-oriented, but the transitive tunnel-mode close
can send a Viper channel-close frame. This transitive frame is secondary to the
call-bound `mediareq26` stop and cannot be treated as the exact semantic close
primitive without the status/flag condition.

## Official Native Call And Dataflow

The inbound call adoption path is:

```text
VipUnitImpl::new_call_ctp_conn
-> VipUnitImpl::handleCtpStart
-> VipUnitImpl::vip_unit_accept_call
-> CallFsm construction
-> CallFsm::initNewConnectionStart(call_ctp_id, csp_msgbuf*)
-> CallFsm::st_idle/go_in_alerting/st_in_alerting
```

`initNewConnectionStart` stores the inbound call CTP id into the `CallFsm`,
copies caller/callee logical addresses from the received START message, sends
capability and alerting reports on that call CTP id, then queues the alerting
state event. Later `start_videorx` and `stop_videorx` both load the same
stored call CTP id before calling `csp_send_mediareq26`; this proves the
`mediareq26` emissions are call-scoped, not global registration writes.

The official video RX start path is:

```text
CallFsm::go_in_alerting or CallFsm::st_in_alerting
-> CallFsm::start_videorx(int)
-> RtpDispatcher::startVideoRX(int, in_addr*)
-> optional ViperTunnel::openMediaRXChannel(...)
-> CallFsm::start_videorx emits csp_send_mediareq26(open)
```

`go_in_alerting` calls `start_videorx(1)` when the video bit is requested and
RX is not already active. `st_in_alerting` has several guarded event branches
that can call `start_videorx(1)`, `start_videorx(0)`, or
`stop_videorx()`. The count rule is therefore per successful guarded
invocation: `start_videorx` emits one `mediareq26` open after local RX setup
succeeds or is not required; `stop_videorx` emits one `mediareq26` stop before
local/tunnel RX teardown.

## Argument And Field Model Of `csp_send_mediareq26`

`csp_send_mediareq26` takes the call CTP id as its first argument, allocates a
26-byte message, and writes it through `ctp_write(call_ctp_id, msg, 26)`.
Observed fields, without promoting raw values to protocol constants:

CSP_MEDIAREQ26_ARG_MODEL=CALL_CTP_ID_PLUS_ACTION_FLAGS_ADDRESS_OR_CHANNEL_PORT_PAYLOAD_AND_MEDIA_PROFILE_FIELDS.

| FIELD | SOURCE |
|---|---|
| prefix/header word | helper-local immediate stored at message start |
| message discriminator | the `mediareq26` helper sets the write length and message type to `0x1A` |
| media request action/state byte | second argument; open uses the start form, close uses the stop form |
| media flags/direction byte | third argument; open derives this from the `start_videorx` parameter and call/config flags, close clears or uses the tunnel-close form |
| address field | copied from the address pointer unless the flags select the tunnel/channel form, in which case it is zeroed |
| port or tunnel media-channel id | fourth scalar argument; open uses the local socket port or saved media channel id, close uses the local socket port or saved media channel id |
| max RTP payload | `RtpDispatcher::getMaxRtpPayload()` on open; zero on close |
| remaining media profile fields | copied from call/config fields on open; zeroed on close |

Open-path distinction: in tunnel mode, `startVideoRX` stores a media channel id
and `start_videorx` emits `mediareq26` with a tunnel/channel-form flag and no
address pointer. In no-tunnel mode, it calls `getSockName`, uses the local
socket address pointer and port, and derives flags from the start argument and
call state. Close-path distinction: `stop_videorx` emits the stop action, zero
payload/profile fields, and either the saved tunnel media-channel id or the
current local socket port. There is one `mediareq26` emission per guarded start
or stop invocation.

MEDIA_OPEN_WIRE_ACTION=VIPER_CHANNEL_OPEN_PLUS_CTP_MEDIAREQ26. The Viper
channel-open is tunnel-local control, and the `mediareq26` is call-bound CTP.
MEDIA_CLOSE_WIRE_ACTION=CALL_BOUND_MEDIAREQ26_STOP_PLUS_LOCAL_MEDIA_DISPOSAL.
In tunnel mode a conditional Viper media-channel close may occur through
`setChannelStatus`, but the exact close rule proven here is not "RTPC close".
MEDIA_CLOSE_CALL_EFFECT=MEDIA_ONLY_STOP; no `csp_send_release`, `ctp_close`,
registration close, PseudoTCP close, process stop, Door, or Gate action is part
of the visible media-only stop path.

## Viper Channel Open Response Pairing

`ViperTunnel::openChannel` allocates a local status node, creates a
`viper_channel_str`, sends `viper_tunnel_channel_open`, and then installs the
receive callback with `setReceivedCbk` before returning success to
`openMediaRXChannel`. `CallFsm::start_videorx` emits `csp_send_mediareq26`
after `RtpDispatcher::startVideoRX` returns. It does not call or wait for
`ViperTunnel::onChannelOpenRes`.

`onChannelOpenRes` is a later peer-response handler. It locks the tunnel status
list, pairs the response by the exact `viper_channel_str*`, derives the channel
type from the matching status node, maps the Viper error to an event error
class, unlocks, and notifies `EvtSender::sendViperChannelOpenRes`. Therefore
the pairing rule is pointer/status-node pairing, not call-id pairing and not a
numeric helper target-id equivalence.

ON_CHANNEL_OPEN_RES_PAIRING=RESPONSE_PAIRED_TO_LOCAL_CHANNEL_POINTER_STATUS.
The media request does not wait for this response in the visible start path.
Whether first RTP is strictly gated by that peer response is UNKNOWN from this
staged evidence; first RTP is at least downstream of the local open/send and
the call-bound `mediareq26` request.

## RtpDispatcher Media State Storage

`RtpDispatcher::RtpDispatcher(cfg_t*, void*, unsigned int, unsigned short)`
stores constructor inputs and zeroes the media state used later by RX open and
close. The relevant recovered layout is:

| STATE | STORAGE MODEL |
|---|---|
| tunnel pointer | constructor stores the second pointer argument into dispatcher state; `startVideoRX` checks it before choosing tunnel vs UDP RX |
| local config/session fields | constructor stores config and scalar inputs, creates RTP RX/TX sessions, and stores RTP/session pointers |
| video RX active flag | initialized false; `startVideoRX` sets it before opening local/tunnel RX; `stopVideoRX` clears it |
| media RX channel pointer | initialized null at dispatcher offset zero; tunnel-mode `startVideoRX` stores the return value of `openMediaRXChannel` there |
| media RX channel id | `openMediaRXChannel` writes the low channel id through the supplied int pointer; `startVideoRX` passes the dispatcher id slot and `stopVideoRX` later passes that saved id to `closeMediaRXChannel` |
| thread/local UDP resources | constructor initializes RX sessions; no-tunnel `startVideoRX` creates the RX thread; `stopVideoRX` shuts down/stops RX and joins/deletes the thread |

RTPDISPATCHER_MEDIA_STATE_STORAGE=POINTER_AND_ID_STORED_IN_DISPATCHER_AFTER_TUNNEL_OPEN.
This gives the helper-local mirror a concrete requirement: a PASS
implementation would need persistent per-call media channel pointer/id
equivalents, not just an RTP socket descriptor.

## Explicit `0x1A` Taxonomy

| EMISSION FORM | TRIGGER | BOUND TO | COUNT PER TRANSITION | WIRE/ LOCAL | HELPER EQUIVALENT | EVIDENCE |
|---|---|---|---|---|---|---|
| self-activation `0x1A` | older entrance self-activation media-start path | persistent registered CTPP/self-activation lineage, not a native inbound `CallFsm` | forbidden; expected count `0` in R29 | WIRE | FORBIDDEN | R29 transform replaces `entrance_signal_queue_self_activation` with disabled stub; P116 R29 proof lists `SELF_ACTIVATION_SENT_COUNT` gate |
| R27 repeat-loop `0x1A` | attempted second same-session media request after initial media active | P78/P97 generated RTPC media request lineage | forbidden; expected repeat count `0` in R29 | WIRE | FORBIDDEN | P116 R27 proof leaves repeat/effect NOT_PROVEN and candidate helper not executed; R29 transform has no `R27_REPEAT_001A` region |
| call-bound `mediareq26` open | guarded `CallFsm::start_videorx` during `go_in_alerting` or selected `st_in_alerting` events | stored inbound call CTP id from `initNewConnectionStart` | exactly one per successful guarded `start_videorx` invocation; for initial alerting preview this is one if RX was not already active and local setup succeeds | WIRE | UNKNOWN/PLAUSIBLE_ONLY | `start_videorx` has two mutually exclusive `csp_send_mediareq26` call sites for tunnel vs no-tunnel forms; both use the stored call CTP id |
| call-bound `mediareq26` stop | guarded `CallFsm::stop_videorx` when video RX is enabled/running | stored inbound call CTP id from `initNewConnectionStart` | exactly one per successful guarded media-stop transition before `stopVideoRX` | WIRE | UNKNOWN | `stop_videorx` prepares stop fields, calls `csp_send_mediareq26`, then calls `RtpDispatcher::stopVideoRX` |
| local media RX channel allocation | `RtpDispatcher::startVideoRX` with tunnel pointer present | local Viper tunnel object and status list | one local channel pointer/id allocation per successful tunnel-mode RX start | LOCAL plus tunnel control open | NO_PROVEN_EQUIVALENT | `openMediaRXChannel` passes type `0xa` to `openChannel`; `openChannel` stores status and calls `viper_tunnel_channel_open` |
| media-only local teardown | `RtpDispatcher::stopVideoRX` after call-bound stop request | saved local media channel pointer/id and RTP sessions | one teardown attempt per guarded stop while RX active | LOCAL plus conditional tunnel channel close | PROVEN_COMPONENT_ONLY | `stopVideoRX` clears active flag, calls `closeMediaRXChannel` in tunnel mode, or shuts down local RTP in no-tunnel mode |

ZERO_ONE_A_TAXONOMY_ROWS=6.
GATE_REFINEMENT_PROPOSED=true. The blanket `no client 0x001A` prohibition must
be refined, not deleted:

- `SELF_ACTIVATION_SENT_COUNT=0` remains mandatory.
- `R27_REPEAT_SENT_COUNT=0` remains mandatory.
- `CALL_BOUND_MEDIAREQ26_SENT_COUNT` must be an exact expected count keyed to
  native call-FSM transitions: one for the successful alerting video-RX start,
  and one for the guarded media-stop transition if media was active.
- A self-activation emission or repeat-loop emission still fails the gate even
  though call-bound `mediareq26` open/stop emissions are now proven native
  behavior.

The current helper cannot yet implement that refinement because it has no
anchored call-bound `mediareq26` builder or call CTP binding equivalent.

## Helper Lineage Mapping

| OFFICIAL NATIVE PRIMITIVE | OUR HELPER PRIMITIVE | MAPPING_STATUS | Anchors and ownership |
|---|---|---|---|
| call-bound `csp_send_mediareq26` open/stop | P78/P97 `p78_queue_rtpc_client_001a` and R27 repeat helper | UNKNOWN | Both are client-originated media-signaling shapes, but P78/P97 are bound to `v4_ctpp_channel_id` and allocator-backed self-activation lineage, while native `mediareq26` is bound to the inbound `CallFsm` call CTP id stored by `initNewConnectionStart`. No field-by-field builder mapping exists. |
| local media-channel state/allocation | P73/P74 allocator-backed RTPC target allocation | PROVEN_COMPONENT_ONLY | Both allocate local target ids, but official state is a `viper_channel_str*` plus id stored in `RtpDispatcher` and paired by pointer in `onChannelOpenRes`; P73/P74 only produce helper target ids and bodies. |
| local RTP forwarding enable | P80 forwarding and RTP descriptors | PROVEN_COMPONENT_ONLY | Both manage local RTP receive/forwarding resources. P80 has no Viper media channel pointer/id or call-bound `mediareq26` emission. |
| media-only close | R29 `r29_media_only_teardown` local forwarding disable | PROVEN_COMPONENT_ONLY | R29 disables P80 forwarding/descriptors and preserves listener/process state. Native media-only stop first emits call-bound `mediareq26` stop and then tears down saved media channel/RTP state. |
| `ViperTunnel::onChannelOpenRes` pairing | P75 RTPC response pairing | PLAUSIBLE_SHAPE_ONLY | P75 pairs responses by helper target id; native pairs by local channel pointer/status node and then sends an event. This is not a proven equivalent. |
| `CallFsm::handle_mediareq` | no inbound helper receive/response model | NO_EQUIVALENT | Official `handle_mediareq` reacts to received peer media requests for local TX control; it does not open inbound RX. |

OPEN_MAPPING_STATUS=UNKNOWN for the call-bound mediareq emission;
PROVEN_COMPONENT_ONLY for local RTP forwarding; PROVEN_COMPONENT_ONLY for
local target allocation shape; no proven executable `openMediaRXChannel`
equivalent. CLOSE_MAPPING_STATUS=UNKNOWN for the call-bound stop mediareq;
PROVEN_COMPONENT_ONLY for local descriptor/forwarding disposal; UNKNOWN for a
faithful saved-pointer/id media-channel close.

## Round 3 Helper-Local Mapping

This round verifies only helper-local evidence. The parent official-side facts
above stand. The listener lineage has persistent CTPP/CSPB channel open,
registration, write/queue, and requested/server channel ids, but no native
media lane. The media lane composed into R29 comes from P76/P78/P80/P97/P106 and
R29 itself.

| OFFICIAL PRIMITIVE | OUR HELPER PRIMITIVE | BINDING/SEMANTIC INPUTS | OWNERSHIP | MAPPING_STATUS | ANCHOR (helper file:function) | EVIDENCE |
|---|---|---|---|---|---|---|
| `csp_send_mediareq26` call-bound open emission | `p76_build_client_001a` builds the 60-byte client action `0x001A`; `p76_generate_client_exchange` binds it to the second allocated RTPC target; `p78_queue_rtpc_client_001a` queues it | Helper inputs are prior client CTPP sequence plus action `0x001A`, flags, second RTPC target id, fixed geometry, and address roles. Queueing uses `v4_ctpp_channel_id`, not a stored inbound call CTP id. The allowed/forbidden distinction is trigger and binding: self-activation/P78/P97 use registered listener CTPP after video ACK staging, while native uses the inbound call transaction. The message content is media-request-like but not the same 26-byte native helper buffer. | Client initiated; helper-owned persistent CTPP, not proven call-owned | PROVEN_COMPONENT_ONLY | `entrance_rtpc_control_media_runtime_transform.py:p76_build_client_001a`; `entrance_rtpc_control_media_runtime_transform.py:p76_generate_client_exchange`; `entrance_p78_rtpc_media_live_stage_transform.py:p78_queue_rtpc_client_001a`; `entrance_p116_r29_listener_attached_media_live_transform.py:p78_queue_rtpc_client_001a` | P76 writes action `0x001A`, geometry, roles, and target into a 60-byte body. P78 queues `p78_rtpc_client_001a` on `v4_ctpp_channel_id`. R29 replaces that queue with a disabled stub. No helper field proves rebinding to `CallFsm`'s stored call CTP id. |
| `csp_send_mediareq26` call-bound stop emission | None found in helper media lineage | Native stop uses action/state stop fields, zero payload/profile fields, and a port or saved media-channel id before local teardown. Helper has no builder for a stop-form CTPP media request and no queued media-stop body. | No helper owner | NO_EQUIVALENT | `entrance_p116_r29_listener_attached_media_live_transform.py:r29_media_only_teardown`; `entrance_p106_teardown_state_classification_transform.py:add_p106_runtime` | R29 teardown disables forwarding and closes local forwarding descriptors only. P106 classifies PseudoTCP graceful-stop state; it is not mediareq26 stop emission. Repository search found open/client `0x001A` builders, not a stop media request builder. |
| `viper_tunnel_channel_create` / local media RX channel allocation | `p76_allocate_target_id` plus `p76_generate_client_exchange`; base CTPP allocator `v4_ctpp_requested_channel_id` / `v4_ctpp_channel_id` | P76 allocates two RTPC target ids from helper runtime state; the second id is embedded in client `0x001A`. Base `v4_queue_open_ctpp` allocates a persistent CTPP requested id and later saves the server channel id. Neither stores a `viper_channel_str*` media RX pointer nor binds the id to an inbound call FSM. | Helper allocates local RTPC target ids and owns persistent CTPP; native owns Viper media channel pointer/id per dispatcher/call | PROVEN_COMPONENT_ONLY | `entrance_rtpc_control_media_runtime_transform.py:p76_allocate_target_id`; `entrance_rtpc_control_media_runtime_transform.py:p76_generate_client_exchange`; `door/v1_5_7/comelit-v4-persistent-ctpp-door.c:v4_queue_open_ctpp`; `door/v1_5_7/comelit-v4-persistent-ctpp-door.c:p12_handle_stream_readable` | P76 has allocator state, collision skip, and target binding. Door listener saves `v4_ctpp_channel_id` after CTPP OPEN response. These are allocation components, not native media channel pointer/id equivalence. |
| `ViperTunnel::openMediaRXChannel` / `RtpDispatcher::startVideoRX` local media RX establishment | P80 `p80_media_forwarding_enabled`, `p80_video_rtp_fd`, `p80_audio_rtp_fd`, target-ready flags and packet counters; P97 `p97_finish_after_device_ack_001a` starts observation | Helper media RX/forwarding starts only after P97 observes the client `0x001A` ACK and calls `entrance_signal_begin_media_observation`. P80 then accepts wrapped RTP and forwards PT99/PT8 to local loopback sockets. It has no Viper channel object and no native `RtpDispatcher` RX session. | Helper local Home Assistant forwarding state | PROVEN_COMPONENT_ONLY | `entrance_p97_complete_post_000a_ack_cycle_transform.py:p97_finish_after_device_ack_001a`; `entrance_p80_ha_media_runtime_transform.py:entrance_signal_begin_media_observation`; `entrance_p80_ha_media_runtime_transform.py:p80_try_forward_wrapped_rtp`; `entrance_p116_r29_listener_attached_media_live_transform.py:r29_start_attached_media_from_call_init` | P97 gates media-active until device ACK for helper `0x001A`; P80 enables forwarding and lazily opens local UDP loopback descriptors on first valid RTP. R29 start currently sets scalar call state and then blocks open. |
| `ViperTunnel::closeMediaRXChannel` plus conditional transitive channel close, and `RtpDispatcher::stopVideoRX` | `r29_media_only_teardown` local forwarding disposal | Inputs are SIGUSR2/idempotent local teardown state, P80 forwarding flag and local descriptor variables. It closes neither process, global listener stop file, PseudoTCP, registration CTPP, reconnect, nor a saved Viper media channel pointer/id. It also emits no call-bound wire close. | Helper local process owns descriptor disposal; listener/registration/transport preserved | PROVEN_COMPONENT_ONLY | `entrance_p116_r29_listener_attached_media_live_transform.py:r29_media_only_teardown`; `entrance_p116_r29_listener_attached_media_live_transform.py:r29_sigusr2_poll_cb`; `entrance_p80_ha_media_runtime_transform.py:p80_try_forward_wrapped_rtp`; `door/v1_5_7/comelit-v4-persistent-ctpp-door.c:stop_check_cb` | R29 explicitly closes only P80 video/audio forwarding descriptors and marks second teardown invocation refused. It does not call `pseudotcp_begin_graceful_stop`, use the stop file as media teardown, close registration, or queue channel close. |
| First-RTP dependency on `ViperTunnel::onChannelOpenRes` | P97 ACK gate plus P80 forwarding gate; no helper `onChannelOpenRes` equivalent | Native order from staged evidence is local open/setup first, `setReceivedCbk` installed, then `csp_send_mediareq26` open emitted; `onChannelOpenRes` is a later response/event notification handler and is not called or waited on by `start_videorx`. Helper order is `0x001A` TX, device ACK, then P80 forwarding. | Peer/device ultimately sends RTP; client owns local receive gates | UNKNOWN | `entrance_p97_complete_post_000a_ack_cycle_transform.py:p97_queue_client_001a_after_ack`; `entrance_p97_complete_post_000a_ack_cycle_transform.py:p97_finish_after_device_ack_001a`; staged `.r29a-evidence/native-disasm/disasm-ViperTunnel_openChannel.txt:ViperTunnel::openChannel`; staged `.r29a-evidence/native-disasm/disasm3-ViperTunnel__onChannelOpenRes_viper_channel_str___viper_error_.txt:ViperTunnel::onChannelOpenRes` | Offline evidence proves `onChannelOpenRes` is not a precondition for native `mediareq26` emission. It does not prove whether the first RTP packet from the device is strictly after a peer channel-open response in all tunnel cases. Helper P97 requires ACK before forwarding, but that ACK is not the same as native pointer/status-node pairing. |

MAPPING_ROWS_TOTAL=6.
MAPPING_PROVEN_EQUIVALENT=0.
MAPPING_PROVEN_COMPONENT_ONLY=4.
MAPPING_PLAUSIBLE=0.
MAPPING_NO_EQUIVALENT=1.
MAPPING_UNKNOWN=1.
ROW1_MEDIAREQ26_OPEN_EQUIVALENT=PROVEN_COMPONENT_ONLY.
ROW2_MEDIAREQ26_STOP_EQUIVALENT=NO_EQUIVALENT.
ROW3_CHANNEL_ALLOCATOR_EQUIVALENT=PROVEN_COMPONENT_ONLY.
ROW4_LOCAL_MEDIA_RX_STATE_EQUIVALENT=PROVEN_COMPONENT_ONLY.
ROW5_MEDIA_ONLY_DISPOSAL_EQUIVALENT=PROVEN_COMPONENT_ONLY.
ROW6_FIRST_RTP_DEPENDENCY=UNKNOWN_NOT_ON_CHANNEL_OPEN_RES_BEFORE_MEDIAREQ26_EMISSION.

OPEN_MAPPING_STATUS=UNKNOWN: row 1 has the helper media-request component, row
3 has target-id allocation components, and row 4 has local forwarding state, but
there is no executable helper-local model that binds the allowed request to the
inbound call CTP transaction instead of self-activation/P78/P97 registered CTPP
signaling.

CLOSE_MAPPING_STATUS=UNKNOWN: row 2 has no helper wire stop equivalent, and row
5 is local descriptor/forwarding disposal only. This is not enough to model
native `mediareq26` stop plus saved media-channel pointer/id disposal.

GATE_REFINEMENT_IMPLEMENTED=false. The deterministic refinement remains
documented, but Phase B did not implement counters because neither model
reached PASS. The current R29 transform keeps the forbidden self-activation and
P78 client-`0x001A` queue stubs.

## Observational Live Plan

This is planning output only. It is not authorization to run live. The probe is
single-question and bounded to one inbound call, and it must not watch traffic
outside the listed direction/message relation.

```text
MISSING_FACT=whether peer first RTP is ordered after the peer channel-open response paired by ViperTunnel::onChannelOpenRes
REQUIRED_OBSERVATION=in one inbound call, compare the peer channel-open response handled by ViperTunnel::onChannelOpenRes for the locally opened media channel with the first inbound RTP packet on that same media lane
CLIENT_TX_ALLOWED=false
DOOR_GATE=false
RING_BUDGET=ONE_INBOUND_CALL
MUST_NOT_DO=no self-activation, no repeat loop, no second call, no Door/Gate, no new registration
YIELDS=boolean:first_rtp_after_on_channel_open_res

MISSING_FACT=whether exactly one call-bound mediareq26 emitted in the inbound alerting transition produces device reaction or RTP without any preceding device-side media request
REQUIRED_OBSERVATION=in one inbound call, observe the alerting-transition client-to-peer call-bound mediareq26 open and then whether a peer reaction or first RTP follows before any peer-to-client media request on that call transaction
CLIENT_TX_ALLOWED=true:exactly one call-bound mediareq26 open on the stored inbound call transaction during the initial alerting transition
DOOR_GATE=false
RING_BUDGET=ONE_INBOUND_CALL
MUST_NOT_DO=no self-activation, no repeat loop, no second call, no Door/Gate, no new registration
YIELDS=boolean:single_alerting_mediareq26_open_accepted_without_preceding_peer_mediareq

MISSING_FACT=whether the inbound call stored CTP id from the call transaction can carry our lane's media-request emission without the registered-CTPP self-activation lineage
REQUIRED_OBSERVATION=in one inbound call, bind the candidate media request to the stored inbound call CTP id and confirm whether the peer accepts or rejects that call-scoped relation without any registered-CTPP self-activation emission
CLIENT_TX_ALLOWED=true:exactly one call-bound mediareq26 open on the stored inbound call transaction for the candidate media lane
DOOR_GATE=false
RING_BUDGET=ONE_INBOUND_CALL
MUST_NOT_DO=no self-activation, no repeat loop, no second call, no Door/Gate, no new registration
YIELDS=boolean:stored_inbound_call_ctp_id_carries_candidate_media_request
```

## Open Decision Table

| OPEN STEP | INITIATOR | INPUT STATE | OUTPUT STATE | WIRE ACTION | OUR EQUIVALENT | EVIDENCE |
|---|---|---|---|---|---|---|
| CALL_INIT | DEVICE | Persistent listener has registered CTPP/PseudoTCP | New incoming call CTP connection reaches native call handler | Device-originated CTP START/CALL_INIT received | Existing listener detects `V4_RING_KIND=CALL_INIT` | `new_call_ctp_conn` dispatches CTP START; v1_5_7 listener reports CALL_INIT without terminating registration |
| call transaction creation | CLIENT LIBRARY | Valid incoming CTP START and capacity | `CallFsm` allocated, initialized, inserted into active list | capability/alerting reports on stored call CTP id | R29 sets scalar call transaction state only | `handleCtpStart` allocates `CallFsm`; `initNewConnectionStart` stores call CTP id and queues alerting |
| HANDLE_MEDIAREQ | DEVICE when present | `st_in_alerting` receives peer media request event | Local TX may start/stop; event dispatched onward | NONE for RX open; it reacts to received request | NONE | `st_in_alerting` calls `handle_mediareq`; `handle_mediareq` starts/stops audio/video TX and never calls `openMediaRXChannel` |
| media RX channel allocation | CLIENT LIBRARY | Video RX enabled, tunnel exists, no video RX already running | Local media `viper_channel_str*` and id stored in `RtpDispatcher` | Viper channel-open frame on existing tunnel | NO_PROVEN_EQUIVALENT | `startVideoRX` calls `openMediaRXChannel`; `openChannel` creates status/channel and calls `viper_tunnel_channel_open` |
| call-bound media request | CLIENT LIBRARY | Local/tunnel RX setup has completed enough to provide target id or socket address/port | Device requested to send media to selected RX target | one `csp_send_mediareq26` open on stored call CTP id | UNKNOWN | `start_videorx` calls `RtpDispatcher::startVideoRX`, then one of two mutually exclusive `csp_send_mediareq26` sites |
| RTPC OPEN/RESPONSE | CLIENT LIBRARY / DEVICE | Existing Viper tunnel has a locally created media RX channel | Peer response is paired to the local channel status entry | Viper channel-open send, then peer response handling | PLAUSIBLE_SHAPE_ONLY | `openChannel` calls `viper_tunnel_channel_open`; `onChannelOpenRes` pairs by channel pointer/status, not helper target id |
| channel-open response | DEVICE | Peer responds to previously sent Viper channel open | Local event emitted with paired channel type/error | response handled; no send from this handler | PLAUSIBLE_SHAPE_ONLY | `onChannelOpenRes` pairs by pointer/status and calls `EvtSender::sendViperChannelOpenRes` |
| RTP forwarding enable | CLIENT LIBRARY / LOCAL | Local RTP RX session or media channel has been started | Video RX active and packets can be consumed | NONE by itself | P80 forwarding enable is component-only | `RtpDispatcher::startVideoRX` starts RX socket/thread or media channel; P80 forwards local RTP only after its own media-active gate |
| first RTP | DEVICE | Device accepted/opened media route and sends packets | Local RTP packets received | Device sends RTP | P80 RTP forwarding | Official prerequisites include local RX setup plus call-bound media request; response-before-first-RTP is UNKNOWN |

INBOUND_MEDIA_OPEN_OWNERSHIP=CLIENT_INITIATED. The device initiates the call,
but the staged native RX path opens/starts local media state and sends the
`mediareq26` request from the client library.

## Close Decision Table

| CLOSE STEP | INITIATOR | RESOURCE CLOSED | WIRE ACTION | PERSISTENT RESOURCE PRESERVED | OUR EQUIVALENT | EVIDENCE |
|---|---|---|---|---|---|---|
| video RX disable | CLIENT LIBRARY | Call FSM video RX state | one call-bound `csp_send_mediareq26` stop before local teardown | Registration, PseudoTCP, process preserved in visible path | UNKNOWN | `stop_videorx` prepares stop fields, calls `csp_send_mediareq26`, then `stopVideoRX` |
| media RX channel close | CLIENT LIBRARY | saved Viper media RX channel pointer/id when tunnel mode is active | direct function no send; transitive `setChannelStatus` may call `viper_channel_close` under closed-state/flag condition | Tunnel and registration preserved in visible path | UNKNOWN | `stopVideoRX` passes dispatcher channel pointer/id; `closeMediaRXChannel` validates pointer/id and calls `setChannelStatus` |
| local RTP receive stop | CLIENT LIBRARY | local RX session/thread and buffers | NONE by itself | Registration, PseudoTCP, process preserved | P80 descriptor/forwarding close only | no-tunnel `stopVideoRX` calls RTP shutdown/stop, joins thread, flushes buffers |
| call transaction state | CLIENT LIBRARY | NOT_REQUIRED for media-only stop | NONE shown for call release in media-only close | Call can remain alerting/active unless another FSM event releases it | R29 scalar call state is not protocol close | `stop_videorx` has no `csp_send_release`/`ctp_close`; `st_in_alerting` has separate release branches |
| CTPP registration | NONE | NONE | NONE | Preserved | Preserved by R29 local blocked path | no registration close edge in stop path |
| PseudoTCP | NONE | NONE | NONE | Preserved | Preserved by R29 local blocked path | no tunnel or PseudoTCP close edge in stop path |
| process/listener | NONE | NONE | NONE | Preserved | Preserved by R29 local blocked path | no process stop or main-loop quit edge in stop path |

## Decision

R29_MEDIA_OPEN_MODEL=BLOCKED. The helper-local model now proves component
parts: an allocator-backed client `0x001A` media-request body, queued on the
registered helper CTPP channel in the inherited P78/P97 lane, and local P80
forwarding state. It still does not prove an executable call-bound inbound
mapping. Implementing by reusing P78/P97 would rely on trigger/binding
substitution, not equivalence.

R29_MEDIA_ONLY_TEARDOWN_MODEL=BLOCKED. The native media-only stop is not just a
local UDP descriptor close. It requires one call-bound `mediareq26` stop and
faithful saved media-channel/RTP state disposal, with a possible tunnel channel
close in tunnel mode. The helper only has component-level local teardown.

The helper-local `HANDLE_MEDIAREQ` path remains distinct from client
`mediareq26`: `MEDIAREQ_RECEIVED` is therefore distinct from
`CLIENT_MEDIAREQ_SENT`. Official `handle_mediareq` controls peer-requested local TX,
does not allocate media RX channels, and never calls `openMediaRXChannel`.

CASE D — both models BLOCKED.
R29_READY_FOR_ORIGINAL_LIVE=false.
PHASE_B_IMPLEMENTED=false. No Phase B implementation is authorized because both
models are not PASS. The existing transform remains fail-closed and live
disabled. The runner must keep refusing live before handoff.

MISSING_EVIDENCE=whether peer first RTP is ordered after the peer channel-open response paired by ViperTunnel::onChannelOpenRes; whether exactly one call-bound mediareq26 emitted in the inbound alerting transition produces device reaction or RTP without any preceding device-side media request; whether the inbound call stored CTP id from the call transaction can carry our lane's media-request emission without the registered-CTPP self-activation lineage.

## R29 Integration Delta

These are conditional instructions only. None of this is implemented now, and
the runner must keep refusing live before the handoff.

If and when the missing facts are resolved, the R29 candidate must refine the
client `0x1A` gate into form-specific counters with exact expected counts:
`SELF_ACTIVATION_SENT_COUNT=0`, `R27_REPEAT_SENT_COUNT=0`, exactly one
call-bound `mediareq26` open on the successful inbound alerting video-RX start,
and exactly one call-bound `mediareq26` stop on the guarded media-stop
transition when media was active.

The candidate must bind the alerting-transition emission and the media-stop
transition emission to the inbound call transaction, not to registered-CTPP
self-activation lineage. It must mirror local media channel state with the
equivalent of a saved media channel pointer/id plus local RTP receive state.
The media-only disposal path must dispose only local media state: no process
stop, no global stop file, no PseudoTCP close, no registration close, no
Door/Gate action, and no call/registration teardown substituted for media stop.

## Self-check

Refuse-before-handoff remains mandatory. Gate disciplines remain mandatory. No
live run, proprietary artefact, raw address, raw payload, token, or session id
is included. Production files changed remain zero; the native production binary
is unchanged.

## Required Report Scalars

```text
=== COMELIT P116 R29A REPORT (round 4) ===
BASE_SHA=9607708ca555e615895583dd719850ffc809cd73
OBSERVATIONAL_PLAN_BLOCKS=3
OBSERVATIONAL_CLIENT_TX_ALLOWED_VALUES=false; true:exactly one call-bound mediareq26 open on the stored inbound call transaction during the initial alerting transition; true:exactly one call-bound mediareq26 open on the stored inbound call transaction for the candidate media lane
MAPPING_ROWS_TOTAL=6
MAPPING_PROVEN_EQUIVALENT=0
MAPPING_PROVEN_COMPONENT_ONLY=4
MAPPING_PLAUSIBLE=0
MAPPING_NO_EQUIVALENT=1
MAPPING_UNKNOWN=1
ROW1_MEDIAREQ26_OPEN_EQUIVALENT=PROVEN_COMPONENT_ONLY
ROW2_MEDIAREQ26_STOP_EQUIVALENT=NO_EQUIVALENT
ROW3_CHANNEL_ALLOCATOR_EQUIVALENT=PROVEN_COMPONENT_ONLY
ROW4_LOCAL_MEDIA_RX_STATE_EQUIVALENT=PROVEN_COMPONENT_ONLY
ROW5_MEDIA_ONLY_DISPOSAL_EQUIVALENT=PROVEN_COMPONENT_ONLY
ROW6_FIRST_RTP_DEPENDENCY=UNKNOWN_NOT_ON_CHANNEL_OPEN_RES_BEFORE_MEDIAREQ26_EMISSION
GATE_REFINEMENT_IMPLEMENTED=false
OPEN_MAPPING_STATUS=UNKNOWN
CLOSE_MAPPING_STATUS=UNKNOWN
CASE_CLASSIFICATION=CASE D — both models BLOCKED
R29_MEDIA_OPEN_MODEL=BLOCKED
R29_MEDIA_ONLY_TEARDOWN_MODEL=BLOCKED
PHASE_B_IMPLEMENTED=false
PY_COMPILE=PASS
GENERATED_SOURCE_SHA256=NOT_GENERATED
EVIDENCE
NEED=helper-local call-bound mediareq26 open/stop builder and inbound call CTP binding evidence
SYMBOL=p76_build_client_001a; p78_queue_rtpc_client_001a; r29_start_attached_media_from_call_init; csp_send_mediareq26
WHY=required to distinguish allowed call-bound media request from forbidden registered-CTPP self-activation/P78/P97 client 0x001A
NEED=helper-local media RX channel pointer/id lifecycle and close evidence
SYMBOL=p76_allocate_target_id; p80_media_forwarding_enabled; r29_media_only_teardown; ViperTunnel::closeMediaRXChannel
WHY=required to implement media-only teardown without equating it to local UDP descriptor close
NEED=offline or staged evidence proving first RTP ordering relative to Viper peer channel-open response
SYMBOL=ViperTunnel::onChannelOpenRes; ViperTunnel::setReceivedCbk; p97_finish_after_device_ack_001a
WHY=offline evidence proves onChannelOpenRes is not before mediareq26 emission, but not whether peer first RTP is always gated by that response
END_EVIDENCE
FOCUSED_TESTS=safety-poc/tests/test_p116_r29a_inbound_media_wire_contract.py
PRODUCTION_FILES_CHANGED=0
NATIVE_PRODUCTION_BINARY_CHANGED=false
TRACKED_FILES_ADDED=safety-poc/research/media/v1/P116_R29A_INBOUND_MEDIA_WIRE_CONTRACT.md; safety-poc/tests/test_p116_r29a_inbound_media_wire_contract.py
TRACKED_FILES_MODIFIED=none
MISSING_EVIDENCE=whether peer first RTP is ordered after the peer channel-open response paired by ViperTunnel::onChannelOpenRes; whether exactly one call-bound mediareq26 emitted in the inbound alerting transition produces device reaction or RTP without any preceding device-side media request; whether the inbound call stored CTP id from the call transaction can carry our lane's media-request emission without the registered-CTPP self-activation lineage
R29_READY_FOR_ORIGINAL_LIVE=false
LIVE_RUN=NOT_RUN
=== END COMELIT P116 R29A REPORT (round 4) ===
```
