# P116 R32 Attached Inbound Media Evidence

FACTS

R32 is an offline evidence round and does not authorize production implementation, live Comelit interaction, Comelit network TX, Door/Gate action, listener restart, merge, deploy, or literal packet replay (`PROJECT_CONTEXT.md:6`, `PROJECT_CONTEXT.md:7`, `PROJECT_CONTEXT.md:9`, `PROJECT_CONTEXT.md:10`, `PROJECT_CONTEXT.md:23`, `PROJECT_CONTEXT.md:24`).

Every verdict below is derived from repository evidence opened in this worktree; no web research was used because R30 already records public corroboration and R32 did not need a new external fact (`safety-poc/research/media/v1/P116_R30_CALL_BOUND_CTP_ENVELOPE_RECOVERY.md:59`, `safety-poc/research/media/v1/P116_R30B_OFFLINE_CALL_TRANSACTION_RESULT.md:56`).

R31 was not read by command in this run because the task also forbids git commands; therefore no R32 conclusion depends on R31-only material (`safety-poc/research/media/v1/P116_R30B_OFFLINE_CALL_TRANSACTION_RESULT.md:246`).

CHILD 1 - CALL-SCOPED TRANSACTION HANDLE

The call CTP id source is the CTP header connection field at payload bytes `2..3`, not the outer Viper CTPP channel handle (`safety-poc/research/media/v1/P116_R30_CALL_BOUND_CTP_ENVELOPE_RECOVERY.md:38`, `safety-poc/research/media/v1/P116_R30_CALL_BOUND_CTP_ENVELOPE_RECOVERY.md:63`, `safety-poc/research/media/v1/P116_R30_CALL_BOUND_CTP_ENVELOPE_RECOVERY.md:90`, `safety-poc/research/media/v1/P116_R30_CALL_BOUND_CTP_ENVELOPE_RECOVERY.md:92`).

Native RX transforms the received wire connection field by toggling the direction bit and stores the resulting internal id as the CTP connection object's single id at `conn[+36]` (`safety-poc/research/media/v1/P116_R30C_NATIVE_CTP_ADOPTION_EVIDENCE_RESULT.md:96`, `safety-poc/research/media/v1/P116_R30C_NATIVE_CTP_ADOPTION_EVIDENCE_RESULT.md:106`, `safety-poc/research/media/v1/P116_R30C_NATIVE_CTP_ADOPTION_EVIDENCE_RESULT.md:121`, `safety-poc/research/media/v1/P116_R30C_NATIVE_CTP_ADOPTION_EVIDENCE_RESULT.md:127`).

The official native callback chain passes that id unchanged through `ViperCtpTapCbksMngr::onNewCTPConnection`, `VipUnitImpl::new_call_ctp_conn`, `handleCtpStart`, and `CallFsm::initNewConnectionStart` (`safety-poc/research/media/v1/P116_R30C_NATIVE_CTP_ADOPTION_EVIDENCE_RESULT.md:133`, `safety-poc/research/media/v1/P116_R30C_NATIVE_CTP_ADOPTION_EVIDENCE_RESULT.md:139`, `safety-poc/research/media/v1/P116_R30C_NATIVE_CTP_ADOPTION_EVIDENCE_RESULT.md:142`, `safety-poc/research/media/v1/P116_R30C_NATIVE_CTP_ADOPTION_EVIDENCE_RESULT.md:145`, `safety-poc/research/media/v1/P116_R30C_NATIVE_CTP_ADOPTION_EVIDENCE_RESULT.md:148`).

The helper can capture the primitive scalar because the persistent listener already receives a complete CTP packet on `v4_ctpp_channel_id`, and the existing parser was reading CTP flags/version, inner length, and body offset without naming the connection field (`safety-poc/research/media/v1/P116_R30_CALL_BOUND_CTP_ENVELOPE_RECOVERY.md:65`, `safety-poc/research/media/v1/P116_R30_CALL_BOUND_CTP_ENVELOPE_RECOVERY.md:67`, `safety-poc/research/media/v1/P116_R30_CALL_BOUND_CTP_ENVELOPE_RECOVERY.md:75`, `safety-poc/research/media/v1/P116_R30_CALL_BOUND_CTP_ENVELOPE_RECOVERY.md:80`).

The minimal safe scalar retained at CALL_INIT is the validated call CTP connection bytes plus sequence, acknowledgement, and logical address roles; the R30B model names these separately from the outer CTPP handle and logical call id (`safety-poc/research/media/v1/P116_R30B_OFFLINE_CALL_TRANSACTION_RESULT.md:25`, `safety-poc/research/media/v1/P116_R30B_OFFLINE_CALL_TRANSACTION_RESULT.md:38`, `safety-poc/research/media/v1/P116_R30B_OFFLINE_CALL_TRANSACTION_RESULT.md:40`, `safety-poc/research/media/v1/P116_R30B_OFFLINE_CALL_TRANSACTION_RESULT.md:41`, `safety-poc/research/media/v1/P116_R30B_OFFLINE_CALL_TRANSACTION_RESULT.md:42`, `safety-poc/research/media/v1/P116_R30B_OFFLINE_CALL_TRANSACTION_RESULT.md:52`).

It is not `v4_ctpp_channel_id` because that field is the already-open persistent CTPP channel id and the R30 layer correction says the outer CTPP handle is not the call transaction (`safety-poc/research/door/v1_5_7/comelit-v4-persistent-ctpp-door.c:183`, `safety-poc/research/door/v1_5_7/comelit-v4-persistent-ctpp-door.c:230`, `safety-poc/research/door/v1_5_7/comelit-v4-persistent-ctpp-door.c:3593`, `safety-poc/research/media/v1/P116_R30_CALL_BOUND_CTP_ENVELOPE_RECOVERY.md:40`, `safety-poc/research/media/v1/P116_R30_CALL_BOUND_CTP_ENVELOPE_RECOVERY.md:61`).

It is not an RTPC target id because P76 allocates RTPC target ids for helper RTPC open/response/client media bodies, while native stores the call id in the CTP connection object and passes it to `CallFsm` (`safety-poc/research/media/v1/entrance_rtpc_control_media_runtime_transform.py:249`, `safety-poc/research/media/v1/entrance_rtpc_control_media_runtime_transform.py:259`, `safety-poc/research/media/v1/entrance_rtpc_control_media_runtime_transform.py:294`, `safety-poc/research/media/v1/P116_R30C_NATIVE_CTP_ADOPTION_EVIDENCE_RESULT.md:121`, `safety-poc/research/media/v1/P116_R30C_NATIVE_CTP_ADOPTION_EVIDENCE_RESULT.md:145`).

It is not a self-activation transaction id because the R29A mapping says P78/P97 queueing uses `v4_ctpp_channel_id` and self-activation lineage, while native `mediareq26` is bound to the inbound `CallFsm` call CTP id (`safety-poc/research/media/v1/P116_R29A_INBOUND_MEDIA_WIRE_CONTRACT.md:244`, `safety-poc/research/media/v1/P116_R29A_INBOUND_MEDIA_WIRE_CONTRACT.md:267`, `safety-poc/research/media/v1/P116_R29A_INBOUND_MEDIA_WIRE_CONTRACT.md:380`).

CALL_CTP_ID_SOURCE=CTP_HEADER_CONNECTION_BYTES_2_3_DIRECTION_TRANSFORMED_NATIVE_CONN_ID
CALL_CTP_ID_LIFETIME=INBOUND_CALL_CTP_CONNECTION_OBJECT_CONN36_TO_CALLFSM_STORED_ID_UNTIL_CALL_TRANSACTION_CLOSE
HELPER_CAN_CAPTURE_CALL_CTP_ID=true

CHILD 2 - CALL-BOUND MEDIAREQ26 OPEN / STOP

The CTP wrapper contract is an 8-byte CTP header, an inner body, four-byte padding, a trailer marker, and source/destination logical addresses; R30C proves version `0x18`, connection bytes `2..3`, sequence byte `4`, acknowledgement byte `5`, and body length bytes `6..7` (`safety-poc/research/media/v1/P116_R30C_NATIVE_CTP_ADOPTION_EVIDENCE_RESULT.md:73`, `safety-poc/research/media/v1/P116_R30C_NATIVE_CTP_ADOPTION_EVIDENCE_RESULT.md:74`, `safety-poc/research/media/v1/P116_R30C_NATIVE_CTP_ADOPTION_EVIDENCE_RESULT.md:75`, `safety-poc/research/media/v1/P116_R30C_NATIVE_CTP_ADOPTION_EVIDENCE_RESULT.md:76`, `safety-poc/research/media/v1/P116_R30C_NATIVE_CTP_ADOPTION_EVIDENCE_RESULT.md:77`, `safety-poc/research/media/v1/P116_R30C_NATIVE_CTP_ADOPTION_EVIDENCE_RESULT.md:78`, `safety-poc/research/media/v1/P116_R30C_NATIVE_CTP_ADOPTION_EVIDENCE_RESULT.md:79`, `safety-poc/research/media/v1/P116_R30C_NATIVE_CTP_ADOPTION_EVIDENCE_RESULT.md:80`).

The 26-byte inner media request uses opcode `0x0011`; the existing P76 full packet builder writes a 26-byte inner length, writes opcode `0x0011`, writes OPEN action/flags at the first two media fields, writes the media target id, writes profile fields, and returns a 60-byte packet (`safety-poc/research/media/v1/entrance_rtpc_control_media_runtime_transform.py:294`, `safety-poc/research/media/v1/entrance_rtpc_control_media_runtime_transform.py:304`, `safety-poc/research/media/v1/entrance_rtpc_control_media_runtime_transform.py:306`, `safety-poc/research/media/v1/entrance_rtpc_control_media_runtime_transform.py:307`, `safety-poc/research/media/v1/entrance_rtpc_control_media_runtime_transform.py:308`, `safety-poc/research/media/v1/entrance_rtpc_control_media_runtime_transform.py:309`, `safety-poc/research/media/v1/entrance_rtpc_control_media_runtime_transform.py:311`).

The R30 recovery reclassified the P76/P78 60-byte form as a full CTP packet whose inner body is a 26-byte media request, so R32 does not promote it as a bare registered-CTPP media request (`safety-poc/research/media/v1/P116_R30_CALL_BOUND_CTP_ENVELOPE_RECOVERY.md:118`, `safety-poc/research/media/v1/P116_R30_CALL_BOUND_CTP_ENVELOPE_RECOVERY.md:120`, `safety-poc/research/media/v1/P116_R30_CALL_BOUND_CTP_ENVELOPE_RECOVERY.md:122`, `safety-poc/research/media/v1/P116_R30_CALL_BOUND_CTP_ENVELOPE_RECOVERY.md:136`, `safety-poc/research/media/v1/P116_R30_CALL_BOUND_CTP_ENVELOPE_RECOVERY.md:142`, `safety-poc/research/media/v1/P116_R30_CALL_BOUND_CTP_ENVELOPE_RECOVERY.md:148`).

The equivalent fields are wrapper length, inner opcode, OPEN action/flags, media-channel/target-id slot, fixed profile fields, trailer/address form, and sequence/ack byte positions; the unproven fields are live peer acceptance, native media-channel allocator equivalence, and exact production profile generation beyond the observed/static profile constants (`safety-poc/research/media/v1/P116_R30B_OFFLINE_CALL_TRANSACTION_RESULT.md:98`, `safety-poc/research/media/v1/P116_R30B_OFFLINE_CALL_TRANSACTION_RESULT.md:100`, `safety-poc/research/media/v1/P116_R30B_OFFLINE_CALL_TRANSACTION_RESULT.md:101`, `safety-poc/research/media/v1/P116_R30B_OFFLINE_CALL_TRANSACTION_RESULT.md:104`, `safety-poc/research/media/v1/P116_R30B_OFFLINE_CALL_TRANSACTION_RESULT.md:115`, `safety-poc/research/media/v1/P116_R30B_OFFLINE_CALL_TRANSACTION_RESULT.md:240`, `safety-poc/research/media/v1/P116_R30B_OFFLINE_CALL_TRANSACTION_RESULT.md:242`).

OPEN is call-bound in the offline model because it is serialized as a full CTP DATA packet using the call transaction connection and not the outer CTPP handle (`safety-poc/research/media/v1/entrance_p116_r30b_call_transaction_model.py:256`, `safety-poc/research/media/v1/entrance_p116_r30b_call_transaction_model.py:265`, `safety-poc/research/media/v1/entrance_p116_r30b_call_transaction_model.py:296`, `safety-poc/research/media/v1/entrance_p116_r30b_call_transaction_model.py:297`, `safety-poc/research/media/v1/entrance_p116_r30b_call_transaction_model.py:306`, `safety-poc/research/media/v1/entrance_p116_r30b_call_transaction_model.py:529`, `safety-poc/research/media/v1/entrance_p116_r30b_call_transaction_model.py:532`).

STOP is call-bound in the offline model because it requires ACTIVE media state, reuses the allocated media channel id, builds a stop-form mediareq26, and serializes through the same call transaction packet path (`safety-poc/research/media/v1/entrance_p116_r30b_call_transaction_model.py:271`, `safety-poc/research/media/v1/entrance_p116_r30b_call_transaction_model.py:279`, `safety-poc/research/media/v1/entrance_p116_r30b_call_transaction_model.py:281`, `safety-poc/research/media/v1/entrance_p116_r30b_call_transaction_model.py:283`, `safety-poc/research/media/v1/entrance_p116_r30b_call_transaction_model.py:541`, `safety-poc/research/media/v1/entrance_p116_r30b_call_transaction_model.py:544`).

The native open ordering is local RX/channel setup first, then one of the mutually exclusive `csp_send_mediareq26` sites, and not a wait on `onChannelOpenRes` (`safety-poc/research/media/v1/P116_R29A_INBOUND_MEDIA_WIRE_CONTRACT.md:150`, `safety-poc/research/media/v1/P116_R29A_INBOUND_MEDIA_WIRE_CONTRACT.md:152`, `safety-poc/research/media/v1/P116_R29A_INBOUND_MEDIA_WIRE_CONTRACT.md:156`, `safety-poc/research/media/v1/P116_R29A_INBOUND_MEDIA_WIRE_CONTRACT.md:195`, `safety-poc/research/media/v1/P116_R29A_INBOUND_MEDIA_WIRE_CONTRACT.md:319`).

The count per successful native transition is exactly one call-bound OPEN per guarded start and exactly one call-bound STOP per guarded media-stop transition when media was active (`safety-poc/research/media/v1/P116_R29A_INBOUND_MEDIA_WIRE_CONTRACT.md:195`, `safety-poc/research/media/v1/P116_R29A_INBOUND_MEDIA_WIRE_CONTRACT.md:196`, `safety-poc/research/media/v1/P116_R29A_INBOUND_MEDIA_WIRE_CONTRACT.md:373`, `safety-poc/research/media/v1/P116_R29A_INBOUND_MEDIA_WIRE_CONTRACT.md:376`, `safety-poc/research/media/v1/P116_R29A_INBOUND_MEDIA_WIRE_CONTRACT.md:377`).

The old R29C registered-CTPP test is not equivalent because it queued only the bare 26-byte body on `v4_ctpp_channel_id`, and R29I live evidence was negative only for that tested path (`safety-poc/research/media/v1/P116_R30_CALL_BOUND_CTP_ENVELOPE_RECOVERY.md:150`, `safety-poc/research/media/v1/P116_R30_CALL_BOUND_CTP_ENVELOPE_RECOVERY.md:152`, `safety-poc/research/media/v1/P116_R30_CALL_BOUND_CTP_ENVELOPE_RECOVERY.md:155`, `safety-poc/research/media/v1/P116_R30_CALL_BOUND_CTP_ENVELOPE_RECOVERY.md:158`, `safety-poc/research/media/v1/P116_R30_CALL_BOUND_CTP_ENVELOPE_RECOVERY.md:162`, `safety-poc/research/media/v1/P116_R30_CALL_BOUND_CTP_ENVELOPE_RECOVERY.md:164`).

MEDIAREQ26_OPEN_CONTRACT=PARTIAL
MEDIAREQ26_STOP_CONTRACT=PARTIAL
REGISTERED_CTPP_EQUIVALENT=false

CHILD 3 - MEDIA RX CHANNEL LIFETIME

The native open lifecycle is `CallFsm::start_videorx` to `RtpDispatcher::startVideoRX` to `ViperTunnel::openMediaRXChannel` to `openChannel` to `viper_tunnel_channel_create` (`safety-poc/research/media/v1/P116_R28_LISTENER_ATTACHED_INBOUND_MEDIA_ANALYSIS.md:423`, `safety-poc/research/media/v1/P116_R28_LISTENER_ATTACHED_INBOUND_MEDIA_ANALYSIS.md:436`, `safety-poc/research/media/v1/P116_R28_LISTENER_ATTACHED_INBOUND_MEDIA_ANALYSIS.md:438`, `safety-poc/research/media/v1/P116_R28_LISTENER_ATTACHED_INBOUND_MEDIA_ANALYSIS.md:439`, `safety-poc/research/media/v1/P116_R28_LISTENER_ATTACHED_INBOUND_MEDIA_ANALYSIS.md:440`).

The native dispatcher stores a tunnel pointer, an active flag, a media RX channel pointer, a media RX channel id, and local RTP/thread resources, so a helper implementation would need persistent per-call state beyond a UDP forwarding descriptor (`safety-poc/research/media/v1/P116_R29A_INBOUND_MEDIA_WIRE_CONTRACT.md:171`, `safety-poc/research/media/v1/P116_R29A_INBOUND_MEDIA_WIRE_CONTRACT.md:177`, `safety-poc/research/media/v1/P116_R29A_INBOUND_MEDIA_WIRE_CONTRACT.md:179`, `safety-poc/research/media/v1/P116_R29A_INBOUND_MEDIA_WIRE_CONTRACT.md:180`, `safety-poc/research/media/v1/P116_R29A_INBOUND_MEDIA_WIRE_CONTRACT.md:181`, `safety-poc/research/media/v1/P116_R29A_INBOUND_MEDIA_WIRE_CONTRACT.md:182`, `safety-poc/research/media/v1/P116_R29A_INBOUND_MEDIA_WIRE_CONTRACT.md:184`).

The native response handler pairs channel-open responses by the exact local `viper_channel_str*` and status node, not by call id or helper target id (`safety-poc/research/media/v1/P116_R29A_INBOUND_MEDIA_WIRE_CONTRACT.md:156`, `safety-poc/research/media/v1/P116_R29A_INBOUND_MEDIA_WIRE_CONTRACT.md:157`, `safety-poc/research/media/v1/P116_R29A_INBOUND_MEDIA_WIRE_CONTRACT.md:159`, `safety-poc/research/media/v1/P116_R29A_INBOUND_MEDIA_WIRE_CONTRACT.md:160`, `safety-poc/research/media/v1/P116_R29A_INBOUND_MEDIA_WIRE_CONTRACT.md:163`).

The native close lifecycle is `CallFsm::stop_videorx` to call-bound mediareq26 STOP to `RtpDispatcher::stopVideoRX` to `ViperTunnel::closeMediaRXChannel`, preserving registration and process resources in the visible path (`safety-poc/research/media/v1/P116_R29A_INBOUND_MEDIA_WIRE_CONTRACT.md:333`, `safety-poc/research/media/v1/P116_R29A_INBOUND_MEDIA_WIRE_CONTRACT.md:334`, `safety-poc/research/media/v1/P116_R29A_INBOUND_MEDIA_WIRE_CONTRACT.md:335`, `safety-poc/research/media/v1/P116_R29A_INBOUND_MEDIA_WIRE_CONTRACT.md:337`, `safety-poc/research/media/v1/P116_R29A_INBOUND_MEDIA_WIRE_CONTRACT.md:338`, `safety-poc/research/media/v1/P116_R29A_INBOUND_MEDIA_WIRE_CONTRACT.md:339`).

The helper has component pieces only: P76 allocates RTPC target ids, P80 owns forwarding flags/descriptors, and R29 teardown closes local forwarding state without a call-bound stop or saved Viper media-channel pointer/id (`safety-poc/research/media/v1/P116_R29A_INBOUND_MEDIA_WIRE_CONTRACT.md:246`, `safety-poc/research/media/v1/P116_R29A_INBOUND_MEDIA_WIRE_CONTRACT.md:247`, `safety-poc/research/media/v1/P116_R29A_INBOUND_MEDIA_WIRE_CONTRACT.md:248`, `safety-poc/research/media/v1/P116_R29A_INBOUND_MEDIA_WIRE_CONTRACT.md:251`, `safety-poc/research/media/v1/P116_R29A_INBOUND_MEDIA_WIRE_CONTRACT.md:252`, `safety-poc/research/media/v1/P116_R29A_INBOUND_MEDIA_WIRE_CONTRACT.md:253`).

The packaged helper binary contains helper-local P76/P80/P97 and `v4_ctpp_channel_id` symbols but no `RtpDispatcher`, `ViperTunnel`, `openMediaRXChannel`, `closeMediaRXChannel`, `startVideoRX`, `stopVideoRX`, or `viper_tunnel_channel_create` strings (`custom_components/comelit/native/comelit-media:strings`, `safety-poc/tests/test_p116_r32_call_bound_media_evidence.py:180`, `safety-poc/tests/test_p116_r32_call_bound_media_evidence.py:183`, `safety-poc/tests/test_p116_r32_call_bound_media_evidence.py:186`).

MEDIA_RX_CHANNEL_OPEN_EQUIVALENT=NO_EQUIVALENT
MEDIA_RX_CHANNEL_CLOSE_EQUIVALENT=NO_EQUIVALENT
MEDIA_RX_STATE_REQUIRED=per_call_ctp_state plus one media channel pointer-equivalent, one media channel id, RTP socket/forward state, pointer/status pairing state, media active flag, exactly-one OPEN/STOP counters, and fail-closed ownership preserving listener/registration/PseudoTCP.

KNOWN R29/R30 CONTRACT (what previous rounds already proved, with anchors)

R28/R29 proved the official native incoming chain reaches video RX automatically during incoming alerting and uses the same upstream transport/session family, while R28 still left HA listener survival after live attached media unknown (`safety-poc/research/media/v1/P116_R28_LISTENER_ATTACHED_INBOUND_MEDIA_ANALYSIS.md:331`, `safety-poc/research/media/v1/P116_R28_LISTENER_ATTACHED_INBOUND_MEDIA_ANALYSIS.md:332`, `safety-poc/research/media/v1/P116_R28_LISTENER_ATTACHED_INBOUND_MEDIA_ANALYSIS.md:334`, `safety-poc/research/media/v1/P116_R28_LISTENER_ATTACHED_INBOUND_MEDIA_ANALYSIS.md:337`, `safety-poc/research/media/v1/P116_R28_LISTENER_ATTACHED_INBOUND_MEDIA_ANALYSIS.md:344`, `safety-poc/research/media/v1/P116_R28_LISTENER_ATTACHED_INBOUND_MEDIA_ANALYSIS.md:322`).

R29A proved the helper mapping was blocked because the helper had component-level target allocation and RTP forwarding but no executable call-bound inbound mapping or media-only teardown equivalence (`safety-poc/research/media/v1/P116_R29A_INBOUND_MEDIA_WIRE_CONTRACT.md:341`, `safety-poc/research/media/v1/P116_R29A_INBOUND_MEDIA_WIRE_CONTRACT.md:343`, `safety-poc/research/media/v1/P116_R29A_INBOUND_MEDIA_WIRE_CONTRACT.md:350`, `safety-poc/research/media/v1/P116_R29A_INBOUND_MEDIA_WIRE_CONTRACT.md:360`, `safety-poc/research/media/v1/P116_R29A_INBOUND_MEDIA_WIRE_CONTRACT.md:418`, `safety-poc/research/media/v1/P116_R29A_INBOUND_MEDIA_WIRE_CONTRACT.md:419`).

R30 proved the outer CTPP handle is an outer carrier and not the call transaction; it also proved the current listener observes full inner CTP packets and can parse the missing connection/sequence/ack fields (`safety-poc/research/media/v1/P116_R30_CALL_BOUND_CTP_ENVELOPE_RECOVERY.md:38`, `safety-poc/research/media/v1/P116_R30_CALL_BOUND_CTP_ENVELOPE_RECOVERY.md:40`, `safety-poc/research/media/v1/P116_R30_CALL_BOUND_CTP_ENVELOPE_RECOVERY.md:42`, `safety-poc/research/media/v1/P116_R30_CALL_BOUND_CTP_ENVELOPE_RECOVERY.md:80`, `safety-poc/research/media/v1/P116_R30_CALL_BOUND_CTP_ENVELOPE_RECOVERY.md:174`, `safety-poc/research/media/v1/P116_R30_CALL_BOUND_CTP_ENVELOPE_RECOVERY.md:176`).

R30B proved an offline intercepted model can wrap OPEN and STOP as complete 60-byte CTP packets with a 26-byte inner media request, reversed logical addresses, one open, one stop, and zero network writes (`safety-poc/research/media/v1/P116_R30B_OFFLINE_CALL_TRANSACTION_RESULT.md:77`, `safety-poc/research/media/v1/P116_R30B_OFFLINE_CALL_TRANSACTION_RESULT.md:78`, `safety-poc/research/media/v1/P116_R30B_OFFLINE_CALL_TRANSACTION_RESULT.md:82`, `safety-poc/research/media/v1/P116_R30B_OFFLINE_CALL_TRANSACTION_RESULT.md:83`, `safety-poc/research/media/v1/P116_R30B_OFFLINE_CALL_TRANSACTION_RESULT.md:84`, `safety-poc/research/media/v1/P116_R30B_OFFLINE_CALL_TRANSACTION_RESULT.md:102`, `safety-poc/research/media/v1/P116_R30B_OFFLINE_CALL_TRANSACTION_RESULT.md:108`).

R30D promoted native direction-bit equivalence and sequence/ack ownership to the CTP transport connection object, but it also stated the packaged native helper binary was not rebuilt and live readiness remained false (`safety-poc/research/media/v1/P116_R30D_NATIVE_CTP_RUNTIME_INTEGRATION_RESULT.md:19`, `safety-poc/research/media/v1/P116_R30D_NATIVE_CTP_RUNTIME_INTEGRATION_RESULT.md:20`, `safety-poc/research/media/v1/P116_R30D_NATIVE_CTP_RUNTIME_INTEGRATION_RESULT.md:21`, `safety-poc/research/media/v1/P116_R30D_NATIVE_CTP_RUNTIME_INTEGRATION_RESULT.md:23`, `safety-poc/research/media/v1/P116_R30D_NATIVE_CTP_RUNTIME_INTEGRATION_RESULT.md:28`, `safety-poc/research/media/v1/P116_R30D_NATIVE_CTP_RUNTIME_INTEGRATION_RESULT.md:32`).

UNPROVEN / BLOCKED + EVIDENCE REQUESTS (bounded, safe, machine-checkable)

EVIDENCE_REQUEST_1=BLOCKED: provide read-only staged native disassembly for `CallFsm::initNewConnectionStart`, `CallFsm::start_videorx`, and both `csp_send_mediareq26` call sites from the same official binary/version used by R30C, with only offsets/field roles and no raw payloads, to settle the exact stored field offset/name and native OPEN profile source (`safety-poc/research/media/v1/P116_R30C_NATIVE_CTP_ADOPTION_EVIDENCE_RESULT.md:145`, `safety-poc/research/media/v1/P116_R29A_INBOUND_MEDIA_WIRE_CONTRACT.md:195`).

EVIDENCE_REQUEST_2=BLOCKED: provide read-only staged native disassembly for `CallFsm::stop_videorx`, `RtpDispatcher::stopVideoRX`, and `ViperTunnel::closeMediaRXChannel` from the same official binary/version used by R30C, with only offsets/field roles and no raw payloads, to settle the exact STOP field source and pointer/id disposal rule (`safety-poc/research/media/v1/P116_R29A_INBOUND_MEDIA_WIRE_CONTRACT.md:333`, `safety-poc/research/media/v1/P116_R29A_INBOUND_MEDIA_WIRE_CONTRACT.md:334`).

EVIDENCE_REQUEST_3=BLOCKED: provide one saved, redacted, offline physical-ring call trace or derived scalar log showing CALL_INIT CTP connection bytes, one call-bound OPEN relation, optional channel-open response order, first RTP count/order, one STOP relation, and listener/registration survival booleans, with no raw payloads, no addresses beyond roles, no tokens, and no new live TX in this R32 run (`safety-poc/research/media/v1/P116_R29A_INBOUND_MEDIA_WIRE_CONTRACT.md:286`, `safety-poc/research/media/v1/P116_R29A_INBOUND_MEDIA_WIRE_CONTRACT.md:294`, `safety-poc/research/media/v1/P116_R29A_INBOUND_MEDIA_WIRE_CONTRACT.md:302`).

CHILD 4 - PRODUCTION DESIGN

DESIGN CANDIDATE - not proven:

```text
physical CALL_INIT
-> runtime emits comelit_ring
-> attached-media acquisition
-> same inbound transport/session retained
-> call-scoped media OPEN
-> local RTP forwarding
-> HA Stream provider
-> snapshots + 20s recording
-> call-scoped STOP
-> local media teardown
-> listener remains/returns READY
```

This target flow is a production design candidate only. R32 proves that the helper can capture the call CTP id, that call-bound OPEN/STOP can be modeled as full CTP packets offline, and that native media RX has a channel lifecycle the helper does not yet implement. R32 does not prove live peer acceptance, RTP arrival, HA Stream delivery, recording success, listener survival after attached media, or a helper-equivalent native media RX channel primitive.

The production shape should keep one media owner: `ComelitMediaSessionManager` remains the single integration-level owner and receives an explicit `bootstrap_strategy` selector. The two strategies are `SELF_ACTIVATION` for manual/on-demand media and `ATTACHED_INBOUND_CALL` for physical CALL_INIT media. This is one ownership model with two bootstraps, not two independent media managers.

Acquire/release API surface:

- `acquire_media(strategy, context, deadline=600s)` returns a single lease when no integration media lease is active.
- `context` for `SELF_ACTIVATION` continues to carry the existing manual bootstrap inputs.
- `context` for `ATTACHED_INBOUND_CALL` carries only bounded call-scoped state: captured call CTP connection bytes after direction transform, sequence/ack state, logical address roles, ring/call phase, and the media-channel state once allocated.
- `release_media(lease, reason)` performs the strategy-specific upstream STOP/teardown, then always releases local RTP forwarding state owned by the lease.
- The lease is the only object allowed to transition media phases, expose status, and release resources. Stale lease ids, nested leases, and cross-strategy release attempts fail closed.

Lease semantics:

- One media lease per integration is allowed, covering both strategies.
- The existing 600 s absolute deadline remains the outer lifetime cap for any lease, including attached inbound media. A shorter call or recording timeout may end the lease sooner, but no strategy extends past that deadline.
- Lease state is monotonic: `REQUESTED -> ACQUIRING -> OPEN_SENT -> ACTIVE -> STOP_SENT -> TEARING_DOWN -> RELEASED` or `REQUESTED/ACQUIRING/OPEN_SENT/ACTIVE -> FAILED_CLOSED -> RELEASED`.
- A lease owns local RTP forwarding lifetime and status reporting. It does not own the persistent listener as a disposable resource.

Phase machine:

```text
SELF_ACTIVATION:
IDLE
-> SELF_ACTIVATION_BOOTSTRAP
-> UPSTREAM_MEDIA_SETUP
-> LOCAL_RTP_FORWARDING
-> HA_STREAM_ACTIVE
-> MEDIA_STOP
-> LOCAL_TEARDOWN
-> IDLE

ATTACHED_INBOUND_CALL:
LISTENER_READY
-> CALL_INIT_CAPTURED
-> CALL_TRANSACTION_BOUND
-> MEDIA_RX_CHANNEL_ALLOCATING
-> CALL_BOUND_OPEN_SENT
-> LOCAL_RTP_FORWARDING
-> HA_STREAM_ACTIVE
-> CALL_BOUND_STOP_SENT
-> LOCAL_MEDIA_TEARDOWN
-> LISTENER_READY_OR_PRESERVED
```

For `ATTACHED_INBOUND_CALL`, these are hard constraints: no new cloud negotiation, no new ICE bootstrap, no new PseudoTCP open, no new CTPP registration, and no stopping or tearing down the inbound call transaction before media OPEN. The attached path must use the already-live inbound transport/session and call-scoped transaction state captured at CALL_INIT.

For `SELF_ACTIVATION`, the existing manual media path must remain functional and unchanged in its safety properties. Its self-activation bootstrap may continue to use the existing setup lane and listener interaction model, including current fail-closed behavior, deadline behavior, and status semantics. The only acceptable shared change is routing ownership through the same lease and phase surface; the manual bootstrap contract must not be weakened to make the attached path work.

`listener_paused` interaction:

- `SELF_ACTIVATION` keeps the existing listener pause behavior and must restore the listener according to the current safety rules.
- `ATTACHED_INBOUND_CALL` must not stop the persistent inbound listener or tear down registration/PseudoTCP as a bootstrap step. If the implementation needs an internal "call transaction busy" marker, it must be scoped to the call lease and must not be represented as listener shutdown.
- On release, the attached path proves either `listener_ready=true` or `listener_preserved=true`; otherwise the lease reports fail-closed and no retry is attempted.

Door fail-closed interaction:

- Door/Gate actions are out of scope for R32 attached media and remain fail-closed.
- If media fails during or after physical ring handling, the manager must not trigger Door/Gate retry or infer door success.
- R31 facts stay separate: Door remains `UNKNOWN_OUTCOME` with no protocol-proven door-specific ACK, and R32 does not fix Door behavior.

Status surface:

- Common fields: strategy, lease id role, phase, deadline remaining bucket, media active boolean, last failure class, local RTP counters, OPEN/STOP sent counts, and teardown proven boolean.
- Attached-only bounded fields: `call_ctp_captured`, `call_bound_open_sent_count`, `call_bound_stop_sent_count`, `media_rx_channel_open_count`, `media_rx_channel_close_count`, and setup deltas for ICE/cloud/PseudoTCP/registration.
- The status surface must not include payload literals, addresses, tokens, raw CTP bytes, raw RTP, or packet captures.

Teardown ownership model:

- Upstream media teardown is owned by the active media lease.
- For `ATTACHED_INBOUND_CALL`, the call transaction lifetime is owned by the call/listener subsystem; the media lease may send call-bound OPEN/STOP while the transaction is valid but must not close the call transaction as a side effect of local media teardown.
- For `SELF_ACTIVATION`, upstream bootstrap teardown remains the existing manual-media upstream teardown path under the shared lease owner.
- Local RTP forwarding lifetime is owned by the media lease for both strategies.
- On partial failure before upstream OPEN, local allocations are closed and no STOP is fabricated unless an upstream media-open state is proven.
- On partial failure after upstream OPEN or after RTP forwarding starts, the lease attempts exactly one bounded STOP/close sequence. If STOP or channel close cannot be proven, the lease reports fail-closed, keeps retry forbidden, and preserves the persistent listener/registration/PseudoTCP rather than broadening teardown.

R31 physical-ring facts are inputs, not dependencies on merged code: physical entrance ring reached `comelit_ring=FIRED`, `kind=CALL_INIT`, `direction=DEVICE_TO_CLIENT`, and `PHYSICAL_RING_EVENT=PASS`, while media failed before active with zero video/audio and Door remained unresolved. Therefore the chosen production architecture is attached inbound session media after physical CALL_INIT, but that production flow is not proven by R32.

Gap list and closing evidence requests:

1. Native media-channel primitive remains `NO_EQUIVALENT`. Close with `EVIDENCE_REQUEST_1` and `EVIDENCE_REQUEST_2`: staged read-only native disassembly for the same official binary/version proving `start_videorx`, `openMediaRXChannel`, `stop_videorx`, and `closeMediaRXChannel` field roles, pointer/id disposal, and media channel allocator equivalence.
2. `MEDIAREQ26_OPEN_CONTRACT=PARTIAL`. Close with `EVIDENCE_REQUEST_1` plus one bounded validation proving peer acceptance of one call-bound OPEN without new cloud/ICE/PseudoTCP/registration setup.
3. `MEDIAREQ26_STOP_CONTRACT=PARTIAL`. Close with `EVIDENCE_REQUEST_2` plus one bounded validation proving one call-bound STOP and media RX close after active media.
4. Listener/registration survival after attached media remains unproven. Close with `EVIDENCE_REQUEST_3`: one saved redacted scalar trace with listener/registration survival booleans after STOP.
5. RTP-to-HA Stream delivery is unproven for attached inbound media. Close with `EVIDENCE_REQUEST_3`: bounded video/audio RTP counts and HA snapshot/recording state booleans, not raw RTP.
6. R31 live ring evidence showed `MEDIA_BOOTSTRAP_BEFORE_ACTIVE`, not attached media success. Close with one future bounded R32/R33 live run using the CHILD 5 markers and no retry.
7. The R31 redaction lesson showed compound values such as `true STAGE=n` can become `<redacted>`. Close by emitting each future stage as a separate bounded scalar marker, for example `MEDIA_RC6_STAGE_INDEX=6`, never as a compound string.

PRODUCTION_DESIGN_READY=false because the native media RX channel open/close primitive has `NO_EQUIVALENT`, OPEN/STOP contracts remain `PARTIAL`, and no bounded attached live validation has proven RTP, Stream, recording, STOP, channel close, and listener survival.

CHILD 5 - OBSERVABILITY PLAN

One future R32/R33 live validation may validate the attached path. It must be one bounded physical-ring invocation, with no retry, no Door/Gate action, no listener stop/start, no raw payload logging, no addresses, no tokens, and no capture literals. All values below are counters or bounded scalars incremented in code and snapshotted by the runner before and after the invocation.

Safe markers:

```text
CALL_CTP_CAPTURED=true
```
Meaning: CALL_INIT produced a bounded call CTP transaction scalar from the CTP header connection bytes after the native direction transform. Expected value: `true`.

```text
CALL_BOUND_MEDIA_OPEN_SENT_COUNT=1
```
Meaning: exactly one call-bound mediareq26 OPEN was sent on the captured call transaction. Expected value: `1`.

```text
CALL_BOUND_MEDIA_STOP_SENT_COUNT=1
```
Meaning: exactly one call-bound mediareq26 STOP was sent after media became active or after upstream OPEN was proven. Expected value: `1` for PASS; `0` is acceptable only for INCONCLUSIVE before proven OPEN.

```text
MEDIA_RX_CHANNEL_OPEN_COUNT=1
MEDIA_RX_CHANNEL_CLOSE_COUNT=1
```
Meaning: helper-equivalent media RX channel open/close transitions occurred once each. Expected value: `1` and `1`.

```text
VIDEO_RTP_COUNT
AUDIO_RTP_COUNT
```
Meaning: bounded packet counters observed by local forwarding, not payloads. Expected value: `VIDEO_RTP_COUNT>0`; `AUDIO_RTP_COUNT>=0` unless the selected device/profile is expected to provide audio, in which case `AUDIO_RTP_COUNT>0` must be declared before the run.

```text
ICE_BOOTSTRAP_DELTA=0
CLOUD_NEGOTIATION_DELTA=0
PSEUDOTCP_OPEN_DELTA=0
CTPP_REGISTRATION_DELTA=0
```
Meaning: after CALL_INIT, the attached path did not start a new ICE bootstrap, cloud negotiation, PseudoTCP open, or CTPP registration. Expected value: all deltas remain `0`.

Additional bounded markers:

```text
RING_KIND=CALL_INIT
RING_DIRECTION=DEVICE_TO_CLIENT
RING_DOOR_ROLE=entrance
ATTACHED_BOOTSTRAP_STRATEGY=ATTACHED_INBOUND_CALL
LISTENER_READY_BEFORE=true
LISTENER_READY_AFTER=true
LISTENER_STOP_COUNT_DELTA=0
SELF_ACTIVATION_BOOTSTRAP_COUNT_DELTA=0
CLOUD_TX_AFTER_CALL_INIT_COUNT=0
MEDIA_ACTIVE_REACHED=true
HA_STREAM_PROVIDER_ATTACHED=true
SNAPSHOT_CAPTURED_COUNT>=1
RECORDING_SECONDS_REQUESTED=20
RECORDING_STATE=completed
TEARDOWN_PROVEN=true
FAILURE_CLASS=none
LIVE_INVOCATIONS=1
RETRY_COUNT=0
DOOR_ACTIONS=0
GATE_ACTIONS=0
```

Redaction rule: every observable marker is a single safe scalar or enum from a fixed allowlist. Stage indexes must be emitted as separate scalar markers such as `MEDIA_STAGE_INDEX=6` and `MEDIA_STAGE_REACHED=true`; they must not be emitted as compound strings such as `true STAGE=6`, because R31 showed that compound marker values can be redacted and become unusable.

Runner method:

1. Snapshot all setup counters before the physical ring.
2. Allow one physical CALL_INIT invocation to reach the attached media path.
3. Capture only the marker values above.
4. Stop after one bounded attempt; do not retry on failure.
5. Compare after-counters with before-counters and publish only deltas and booleans.

Acceptance gate:

- `PASS_EVIDENCE_READY` requires `CALL_CTP_CAPTURED=true`, one OPEN, one media RX channel open, video RTP greater than zero, HA Stream provider attached, at least one snapshot, 20 s recording completed, one STOP, one media RX channel close, teardown proven, listener ready/preserved after teardown, zero new ICE/cloud/PseudoTCP/registration deltas after CALL_INIT, zero Door/Gate actions, and zero retry.
- `INCONCLUSIVE` applies when CALL_INIT is captured but one or more media validation markers are absent, redacted, or internally inconsistent without unsafe behavior.
- `BLOCKED_PRIMITIVE` applies when the helper still lacks the media RX channel primitive, when OPEN/STOP remains only partial, or when the run cannot prove teardown/listener preservation.

VERIFICATION

Commands to run after this document and its test are finalized:

```bash
cd safety-poc
PYTHONPATH=$PWD/src PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_p116_r32_call_bound_media_evidence -v
PYTHONPATH=$PWD/src PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests
python3 scripts/static_safety_check.py
```

`git status --short` is intentionally not part of R32 verification because the task hard-prohibits git commands in this run.

Results from this R32 run:

```text
tests.test_p116_r32_call_bound_media_evidence: Ran 7 tests in 0.004s - OK
unittest discover -s tests: Ran 1576 tests in 38.410s - FAILED with accepted failures only:
  test_p116_provenance_binary_analysis.P116ProvenanceBinaryAnalysisTests.test_committed_build_metadata_records_historical_non_runtime_mismatch
  test_p116_r29i_preopen_idle_and_sink_ownership.P116R29IPreOpenIdleAndSinkOwnership.test_nonzero_datagram_sink_materializes_final_counter_after_exit
  test_p116_r29i_preopen_idle_and_sink_ownership.P116R29IPreOpenIdleAndSinkOwnership.test_zero_datagram_sink_materializes_final_counter_after_exit
static_safety_check.py: STATIC_SAFETY_CHECK=PASS, NETWORK_IMPORTS_PRESENT=false, COMELIT_ENDPOINTS_PRESENT=false, SOURCE_FILES_SCANNED=29
git status --short: skipped because the task hard-prohibits git commands in this run
```

=== COMELIT P116 R32 ATTACHED INBOUND MEDIA (REPO DOC) ===
BASE_SHA=4ef019cf3fd240ceae4663d82d91a2cdca17f600
CALL_CTP_ID_SOURCE=CTP_HEADER_CONNECTION_BYTES_2_3_DIRECTION_TRANSFORMED_NATIVE_CONN_ID
HELPER_CAN_CAPTURE_CALL_CTP_ID=true
MEDIAREQ26_OPEN_CONTRACT=PARTIAL
MEDIAREQ26_STOP_CONTRACT=PARTIAL
REGISTERED_CTPP_EQUIVALENT=false
MEDIA_RX_CHANNEL_OPEN_EQUIVALENT=NO_EQUIVALENT
MEDIA_RX_CHANNEL_CLOSE_EQUIVALENT=NO_EQUIVALENT
R29B_GAP_CLOSED=false
ATTACHED_PATH_NEW_ICE_EXPECTED=0
ATTACHED_PATH_NEW_CLOUD_EXPECTED=0
ATTACHED_PATH_NEW_PSEUDOTCP_EXPECTED=0
ATTACHED_PATH_NEW_REGISTRATION_EXPECTED=0
PRODUCTION_DESIGN_READY=false
PRODUCTION_FILES_CHANGED=0
LIVE_INVOCATIONS=0
NETWORK_TX=0
DOOR_ACTIONS=0
GATE_ACTIONS=0
DEPLOYS=0
HA_RESTARTS=0
RESULT=BLOCKED_PRIMITIVE
=== END COMELIT P116 R32 ATTACHED INBOUND MEDIA (REPO DOC) ===
