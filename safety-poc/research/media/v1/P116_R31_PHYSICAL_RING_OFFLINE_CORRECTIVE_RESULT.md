# P116 R31 Physical Ring Offline Corrective Result

TASK_ID=COMELIT-P116-R31-PHYSICAL-RING-OFFLINE-CORRECTIVE-DOC (`OPERATOR_LIVE_EVIDENCE`).  
MODE=DEV_OFFLINE and this pass authored only this repository document (`OPERATOR_LIVE_EVIDENCE`).  
BASE_SHA=4ef019cf3fd240ceae4663d82d91a2cdca17f600 (`OPERATOR_LIVE_EVIDENCE`).  
LIVE_INVOCATIONS=0 and NETWORK_TX=0 for this pass (`OPERATOR_LIVE_EVIDENCE`).  

## FACTS

PHYSICAL_RING_EVENT=PASS and FAILURE_BOUNDARY=MEDIA_BOOTSTRAP_BEFORE_ACTIVE are operator-classified facts for event `c2d2558c-72cf-43a4-a51c-44e88c5b5a99` (`OPERATOR_LIVE_EVIDENCE`).  
The operator live evidence says the real ring was an entrance `CALL_INIT` from safe scalar source `00000643`, direction `DEVICE_TO_CLIENT`, with `snapshot_event_count=0`, `recording_event_count=1`, `recording_state=failed`, `recording_reason=media_start_failed`, and `duration_actual_seconds=0.0` (`OPERATOR_LIVE_EVIDENCE`).  
The operator live evidence says the media helper failed as `media_native_exited_before_active:6` after `REMOTE_SDP_LOADED=true`, `ICE_CONNECTED_FINAL=true`, `ICE_READY_FINAL=true`, `SELECTED_PAIR_FINAL=true`, `PSEUDOTCP_STARTED_FINAL=true`, and `PSEUDOTCP_OPEN_FINAL=true` (`OPERATOR_LIVE_EVIDENCE`).  
The operator live evidence says `P116_VIDEO_COUNT=0` and `P116_AUDIO_COUNT=0` for the physical ring media failure (`OPERATOR_LIVE_EVIDENCE`).  
The operator live evidence says a later restored listener cycle ended with `native_exit:6`, `PSEUDOTCP_OPEN_FINAL=false`, `PSEUDOTCP_CLOSED_BEFORE_OPEN=true`, and supervisor READY restored (`OPERATOR_LIVE_EVIDENCE`).  
The operator live evidence says a separate post-recovery manual Entrance Door press produced `UNKNOWN_OUTCOME`, `protocol_acked=false`, and no physical opening by operator relay (`OPERATOR_LIVE_EVIDENCE`).  

## CHILD A - IMPLEMENTED CORRECTIVE

The corrected media-session source defines safe failure stages `listener_pause` and `transport_start`, a public `safe_media_start_failure_reason()`, and a bounded safe-value regex for retained failure reasons (`custom_components/comelit/media_session.py:24-29`, `custom_components/comelit/media_session.py:71-79`).  
The media-session status now retains `last_start_failure`, `last_start_failure_stage`, `last_start_failure_at`, `transport_last_error`, and `transport_native_exit_code` as historical start-failure diagnostics (`custom_components/comelit/media_session.py:185-201`).  
The media start sequence still pauses the listener before starting transport and still raises a media-session error after recovery on any start failure (`custom_components/comelit/media_session.py:244-257`).  
The round-1 stale-error defect is fixed because `_capture_start_failure()` reads `transport.last_error` and `transport.last_native_exit_code` only when the failure stage is `transport_start` (`custom_components/comelit/media_session.py:352-363`).  
The listener-pause failure path derives its reason from a safe `ComelitMediaSessionError` message or falls back to `listener_pause_failed`, and it clears transport detail fields to `None` for that stage (`custom_components/comelit/media_session.py:363-386`).  
The recovery path still stops active transport if needed, resumes the listener, and resets inactive on successful recovery (`custom_components/comelit/media_session.py:389-413`).  
The ring-media coordinator imports the public sanitizer rather than a private helper (`custom_components/comelit/ring_media.py:50-57`).  
The ring-media coordinator captures the retained failure snapshot when `ComelitMediaSessionError` or invalid ring media input prevents media startup, while the public recording event reason remains `media_start_failed` (`custom_components/comelit/ring_media.py:418-430`).  
The ring-media coordinator copies manager diagnostics into its own retained status fields so a later success does not erase the historical failed-ring snapshot (`custom_components/comelit/ring_media.py:537-569`).  
The camera and switch expose the retained keys in entity attributes (`custom_components/comelit/camera.py:262-276`, `custom_components/comelit/switch.py:60-76`).  
The focused R31 test proves nested transport failure reason retention and exception text preservation for `media_native_exited_before_active:6` (`safety-poc/tests/test_p116_r31_media_start_failure_diagnostics.py:139-159`).  
The focused R31 test proves recovery to inactive keeps historical diagnostics while `last_error` returns to `None` (`safety-poc/tests/test_p116_r31_media_start_failure_diagnostics.py:161-176`).  
The focused R31 test proves a listener-pause failure does not report a stale transport error or native exit code (`safety-poc/tests/test_p116_r31_media_start_failure_diagnostics.py:178-203`).  
The focused R31 test proves current active state and historical failure diagnostics are not mixed (`safety-poc/tests/test_p116_r31_media_start_failure_diagnostics.py:205-224`).  
The focused R31 test proves unsafe raw transport values are suppressed and boolean native exit codes are not retained (`safety-poc/tests/test_p116_r31_media_start_failure_diagnostics.py:226-258`).  
The focused R31 test proves a successful later start preserves the retained history unchanged (`safety-poc/tests/test_p116_r31_media_start_failure_diagnostics.py:259-272`).  
The focused R31 ring-media test proves the failed recording event reason stays `media_start_failed` while retained diagnostics survive a later successful lifecycle (`safety-poc/tests/test_p116_r31_media_start_failure_diagnostics.py:335-374`).  
The focused R31 attribute test proves the camera and switch source expose every retained key (`safety-poc/tests/test_p116_r31_media_start_failure_diagnostics.py:377-396`).  
The expected hash-pin ledger changed only the camera and media-session digests in the ring telegram offline build guard while leaving the media-transport and native-helper pins unchanged (`safety-poc/tests/test_mvp1_ring_telegram_offline_build.py:248-263`).  
The expected media-session digest changed in the R18 HLS diagnostic guard while the media-transport and native-helper digests remained pinned (`safety-poc/tests/test_p116_r18_hls_runtime_diagnostics.py:16-24`).  
The expected media-session digest changed in the R24 recovery shim lifecycle guard while the native helper digest remained pinned (`safety-poc/tests/test_p116_r24_recovery_shim_lifecycle.py:13-20`).  
No source in this corrective changes fail-closed media ownership, retry policy, start/stop ordering, phases, leases, or the public recording completion event contract (`custom_components/comelit/media_session.py:222-296`, `custom_components/comelit/ring_media.py:393-456`, `custom_components/comelit/switch.py:79-81`).  

## CHILD B - PHYSICAL RING MEDIA ROOT CAUSE

B1 is CONFIRMED_BY_SOURCE that production ring media starts a separate lifecycle by calling `RingMediaCoordinator.async_start_for_ring()` and then `ComelitMediaSessionManager.async_acquire()` (`custom_components/comelit/runtime.py:228-263`, `custom_components/comelit/ring_media.py:334-363`, `custom_components/comelit/ring_media.py:393-395`).  
B1 is CONFIRMED_BY_SOURCE that `ComelitMediaSessionManager.async_acquire()` pauses the listener before transport start (`custom_components/comelit/media_session.py:244-253`).  
B1 is CONFIRMED_BY_SOURCE that pausing media stops the persistent runtime and marks the supervisor `paused_media` (`custom_components/comelit/supervisor.py:149-168`, `custom_components/comelit/supervisor.py:183-196`).  
B1 is CONFIRMED_BY_SOURCE that the transport owns a separate native media process, run directory, cloud P2P negotiation, and packaged `custom_components/comelit/native/comelit-media` helper (`custom_components/comelit/media_transport.py:23-37`, `custom_components/comelit/media_transport.py:632-687`).  
B1 is CONFIRMED_BY_SOURCE that native inbound media is call-scoped: `initNewConnectionStart` stores the inbound call CTP id, and `start_videorx` / `stop_videorx` use the stored call CTP id for call-bound `mediareq26` (`safety-poc/research/media/v1/P116_R29A_INBOUND_MEDIA_WIRE_CONTRACT.md:72-90`).  
B1 is CONFIRMED_BY_SOURCE that native video RX calls `RtpDispatcher::startVideoRX`, optionally opens a `ViperTunnel::openMediaRXChannel`, and then emits call-bound `mediareq26(open)` (`safety-poc/research/media/v1/P116_R29A_INBOUND_MEDIA_WIRE_CONTRACT.md:92-100`, `safety-poc/research/media/v1/P116_R29A_INBOUND_MEDIA_WIRE_CONTRACT.md:129-140`).  
B1 is CONFIRMED_BY_SOURCE that the current production scheme is an architecturally unproven self-activation substitute for native inbound-call media because helper-local P78/P97 media signaling is bound to `v4_ctpp_channel_id`, while native media is bound to the inbound `CallFsm` call CTP id (`safety-poc/research/media/v1/P116_R29A_INBOUND_MEDIA_WIRE_CONTRACT.md:220-223`, `safety-poc/research/media/v1/P116_R29A_INBOUND_MEDIA_WIRE_CONTRACT.md:343-348`).  

B2 is CONFIRMED_BY_SOURCE that the v1.5.7 listener has a `failed` flag and exits after loop completion through the normal C main path; the entrance signaling transform sets `failed = TRUE` and calls `g_main_loop_quit()` on settle or timeout failures (`safety-poc/research/door/v1_5_7/comelit-v4-persistent-ctpp-door.c:25-32`, `safety-poc/research/media/v1/entrance_self_activation_signaling_transform.py:327-369`).  
B2 is CONFIRMED_BY_SOURCE that the entrance signaling lane has `ENTRANCE_SIGNAL_SETTLE_MS=4000`, `ENTRANCE_SIGNAL_TIMEOUT_MS=20000`, and timeout output `ENTRANCE_SIGNALING_TIMEOUT=true STAGE=%u` (`safety-poc/research/media/v1/entrance_self_activation_signaling_transform.py:71-91`, `safety-poc/research/media/v1/entrance_self_activation_signaling_transform.py:353-369`).  
B2 is CONFIRMED_BY_SOURCE that the packaged helper is the SHA-pinned `custom_components/comelit/native/comelit-media`, and the string scan found `ENTRANCE_SIGNALING_TIMEOUT=true STAGE=%u`, `P80_MEDIA_ACTIVE=true`, and `PSEUDOTCP_OPEN_FINAL=%s` in that binary (`custom_components/comelit/media_transport.py:23-37`, binary string scan of `custom_components/comelit/native/comelit-media`).  
B2 is CONFIRMED_BY_SOURCE that `true STAGE=3` is not a safe stored marker value because marker values allow only listed scalar words or digits/comma lists, and unsafe values are stored as `<redacted>` (`custom_components/comelit/media_transport.py:42-48`, `custom_components/comelit/media_transport.py:401-414`).  
B2 exact `STAGE=n` is UNPROVEN from stored safe marker tails because the timeout value with both `true` and `STAGE=n` is redacted by `_safe_native_marker()` (`custom_components/comelit/media_transport.py:401-414`).  
B2 is CONFIRMED_BY_SOURCE that the bounded stage class is pre-media: self-activation requires a structural ACK, video event requires a structural ACK, and success waits for a device-video event before media observation (`safety-poc/research/media/v1/entrance_self_activation_signaling_transform.py:462-492`).  
B2 is CONFIRMED_BY_SOURCE that `P80_MEDIA_ACTIVE=true` is emitted only after `entrance_signal_begin_media_observation()` is reached in the HA media runtime lane, which explains why the operator's `P116_VIDEO_COUNT=0` belongs to a before-active failure (`custom_components/comelit/media_transport.py:689-707`, `custom_components/comelit/media_transport.py:754-760`, `OPERATOR_LIVE_EVIDENCE`).  

B3 is CONFIRMED_BY_SOURCE that the round-2 synthetic canary had `SYNTHETIC_RING_COUNT=1`, `P78_RTPC_SIGNALING_RESULT=PASS`, `P80_VIDEO_RTP_FORWARDING=PASS`, `P116_VIDEO_COUNT=1007`, `P116_AUDIO_COUNT=1067`, 19 snapshots, and completed recording (`docs/mvp1-synthetic-ring-canary-result.md:25-46`, `docs/mvp1-synthetic-ring-canary-result.md:63-74`, `docs/mvp1-synthetic-ring-canary-result.md:255-260`, `docs/mvp1-synthetic-ring-canary-result.md:275-290`).  
B3 is CONFIRMED_BY_SOURCE that the synthetic path creates a HA event with `source=synthetic_test`, `kind=CALL_INIT`, and `synthetic=True`, then requires normal media start (`custom_components/comelit/runtime.py:267-285`).  
B3 is CONFIRMED_BY_SOURCE that the test-control webhook action `simulate_entrance_ring` calls `runtime.async_simulate_entrance_ring()` and returns `synthetic=true` (`custom_components/comelit/test_control.py:73-87`).  
B3 is CONFIRMED_BY_SOURCE that the physical path parses real native ring markers and emits an event from `parse_v4_safe_ring()` after native output includes all ring keys (`custom_components/comelit/runtime.py:733-760`).  
B3 semantic difference is CONFIRMED_BY_SOURCE: the synthetic canary validates "HA-synthesised ring event with no native inbound call transaction in flight," while the physical event validates "real inbound CALL_INIT observed by the listener" (`custom_components/comelit/runtime.py:267-285`, `safety-poc/research/door/v1_5_7/comelit-v4-persistent-ctpp-door.c:4071-4205`).  

B4 is CONFIRMED_BY_SOURCE that the listener `CALL_INIT` branch is keyed by `prefix == 0x18C0` and `action == 0x0028` and is observation-only with no call answer, no media activation, and no actuator action (`safety-poc/research/door/v1_5_7/comelit-v4-persistent-ctpp-door.c:4071-4089`).  
B4 is CONFIRMED_BY_SOURCE that the branch emits safe ring fields and explicitly emits `NETWORK_DOOR_ACTION_PERFORMED=false` and `PHYSICAL_DOOR_ACTION=false` (`safety-poc/research/door/v1_5_7/comelit-v4-persistent-ctpp-door.c:4142-4188`).  
B4 is CONFIRMED_BY_SOURCE that the branch consumes the frame and returns without terminating the persistent registered session (`safety-poc/research/door/v1_5_7/comelit-v4-persistent-ctpp-door.c:4191-4205`).  
B4 helper-visible call-scoped identifier availability is REFUTED_BY_SOURCE because R29B states the existing listener observes inbound `CALL_INIT` on persistent CTPP but exposes no separate inbound call CTP transaction id equivalent to native `CallFsm` storage (`safety-poc/research/media/v1/P116_R29B_HELPER_LOCAL_INBOUND_MEDIA_MAPPING.md:26-31`).  

B5 is CONFIRMED_BY_SOURCE that missing primitives are helper-visible inbound call CTP transaction id capture/storage, call-bound `mediareq26` OPEN/STOP generation with proven field sources, and media RX channel runtime allocation/lifetime (`safety-poc/research/media/v1/P116_R29B_HELPER_LOCAL_INBOUND_MEDIA_MAPPING.md:41-50`, `safety-poc/research/media/v1/P116_R29B_HELPER_LOCAL_INBOUND_MEDIA_MAPPING.md:228-237`).  
B5 is CONFIRMED_BY_SOURCE that R30B kept production files unchanged and did not prove live call-bound media behavior (`safety-poc/research/media/v1/P116_R30B_OFFLINE_CALL_TRANSACTION_RESULT.md:69-94`).  
B5 is CONFIRMED_BY_SOURCE that R30D changed offline model/source identity but not packaged production binary or `custom_components/comelit`, and was not live readiness (`safety-poc/research/media/v1/P116_R30D_NATIVE_CTP_RUNTIME_INTEGRATION_RESULT.md:28-47`, `safety-poc/research/media/v1/P116_R30D_NATIVE_CTP_RUNTIME_INTEGRATION_RESULT.md:56-66`).  
B5 is CONFIRMED_BY_SOURCE that R30E rebuilt provenance to a packaged binary matching HEAD while still recording `LIVE_READY=false`, `LIVE_INVOCATIONS=0`, and no HA deployment (`safety-poc/research/media/v1/P116_R30E_NATIVE_HELPER_REBUILD_PROVENANCE_RESULT.md:50-99`).  

B6 is CONFIRMED_BY_SOURCE that R29B still had `R29_MEDIA_OPEN_MODEL=BLOCKED`, `R29_MEDIA_ONLY_TEARDOWN_MODEL=BLOCKED`, and `CALL_BOUND_MEDIAREQ26_OPEN_GENERATION=BLOCKED` (`safety-poc/research/media/v1/P116_R29B_HELPER_LOCAL_INBOUND_MEDIA_MAPPING.md:33-37`, `safety-poc/research/media/v1/P116_R29B_HELPER_LOCAL_INBOUND_MEDIA_MAPPING.md:43-48`).  
B6 is CONFIRMED_BY_SOURCE that the R29B gap still applies to the current helper unless a call-scoped CTP handle and call-bound 26-byte mediareq26 builders are added (`safety-poc/research/media/v1/P116_R29B_HELPER_LOCAL_INBOUND_MEDIA_MAPPING.md:228-237`).  

B7 is CONFIRMED_BY_SOURCE that native evidence supports option A, ring-attached media inside the inbound listener session, because native media is attached to the inbound call transaction and call-bound mediareq26 (`safety-poc/research/media/v1/P116_R29A_INBOUND_MEDIA_WIRE_CONTRACT.md:72-100`, `safety-poc/research/media/v1/P116_R29A_INBOUND_MEDIA_WIRE_CONTRACT.md:129-140`).  
B7 option B, accepting a separate new post-ring media session, is UNPROVEN because the repository proves it exists in production but not that it is native-equivalent for physical inbound calls (`custom_components/comelit/media_session.py:244-253`, `custom_components/comelit/media_transport.py:632-687`, `safety-poc/research/media/v1/P116_R29A_INBOUND_MEDIA_WIRE_CONTRACT.md:343-348`).  
B7 option C, insufficient evidence, remains available as an architecture decision if the user rejects the native-equivalent direction (`safety-poc/research/media/v1/P116_R29A_INBOUND_MEDIA_WIRE_CONTRACT.md:366-366`).  
B7 is ARCHITECTURE_DECISION_REQUIRED because choosing option A would make manual/self-activation media and ring-attached inbound media two bootstrap paths that must share one ownership and safety model (`custom_components/comelit/media_transport.py:216-223`, `custom_components/comelit/supervisor.py:35-45`).  

## CHILD C - DOOR UNKNOWN_OUTCOME OFFLINE ANALYSIS

C1 is CONFIRMED_BY_SOURCE that the native door transaction has `V4_DOOR_STEP_TIMEOUT_SECONDS=6`, `V4_DOOR_SETTLE_MS=1000`, `v4_door_write_count=5`, and a SIGUSR1 handler that only sets a pending flag (`safety-poc/research/door/v1_5_7/comelit-v4-persistent-ctpp-door.c:217-225`, `safety-poc/research/door/v1_5_7/comelit-v4-persistent-ctpp-door.c:271-278`, `safety-poc/research/door/v1_5_7/comelit-v4-persistent-ctpp-door.c:2449-2454`).  
C1 is CONFIRMED_BY_SOURCE that the READY guard rejects as `V4_DOOR_RESULT=REJECTED_NOT_READY` when listener ready, registration, CTPP channel, stage, door idle state, or no pending TX preconditions are not met (`safety-poc/research/door/v1_5_7/comelit-v4-persistent-ctpp-door.c:2563-2580`).  
C1 is CONFIRMED_BY_SOURCE that accepted door operation reuses the existing CTPP channel and records no physical-effect assertion (`safety-poc/research/door/v1_5_7/comelit-v4-persistent-ctpp-door.c:2582-2597`).  
C1 is CONFIRMED_BY_SOURCE that each door write prints `V4_DOOR_OPERATION_WRITE_%u_SENT=true`, and after five writes the code prints `V4_DOOR_OPERATION_WRITES_SENT=5` and `V4_DOOR_DOOR_SPECIFIC_ACK_PROVEN=false` (`safety-poc/research/door/v1_5_7/comelit-v4-persistent-ctpp-door.c:1926-1961`).  
C1 is CONFIRMED_BY_SOURCE that the settle callback prints `V4_DOOR_SETTLE_COMPLETE=true`, keeps `V4_DOOR_DOOR_SPECIFIC_ACK_PROVEN=false`, and emits `UNKNOWN_OUTCOME` (`safety-poc/research/door/v1_5_7/comelit-v4-persistent-ctpp-door.c:2516-2536`).  
C1 is CONFIRMED_BY_SOURCE that the deadline path emits `UNKNOWN_OUTCOME` after a send has started and `FAILED_SAFE` before a send has started (`safety-poc/research/door/v1_5_7/comelit-v4-persistent-ctpp-door.c:2540-2561`, `safety-poc/research/door/v1_5_7/comelit-v4-persistent-ctpp-door.c:2599-2608`).  
C1 invariant is CONFIRMED_BY_SOURCE: native `UNKNOWN_OUTCOME` implies at least one local TX write boundary was crossed or the operation reached post-write settle, and no door-specific ACK was proven (`safety-poc/research/door/v1_5_7/comelit-v4-persistent-ctpp-door.c:2491-2512`, `safety-poc/research/door/v1_5_7/comelit-v4-persistent-ctpp-door.c:2528-2533`).  
C1 is CONFIRMED_BY_SOURCE that Python sends SIGUSR1, waits 10 seconds, maps `UNKNOWN_OUTCOME`, and converts process-exit pending futures to `UNKNOWN_OUTCOME` (`custom_components/comelit/runtime.py:38-44`, `custom_components/comelit/runtime.py:445-516`, `custom_components/comelit/runtime.py:547-552`).  

C2 is CONFIRMED_BY_SOURCE that Python parses `V4_DOOR_REJECT_STAGE`, `V4_DOOR_DOOR_SPECIFIC_ACK_PROVEN`, `V4_DOOR_EXISTING_CTPP_REUSED`, `V4_DOOR_REJECT_RESPONSE_WORD`, `V4_DOOR_REQUESTED_CHANNEL_ID`, `V4_DOOR_RESPONSE_CHANNEL_ID`, `V4_DOOR_WRITE_COUNT`, and `V4_DOOR_CTPP_CHANNEL_ID` (`custom_components/comelit/runtime.py:665-720`).  
C2 is CONFIRMED_BY_SOURCE that native emits but Python does not parse `V4_DOOR_COMMAND_ACCEPTED`, `V4_DOOR_OPERATION_WRITES_SENT`, per-write sent markers, and `V4_DOOR_SETTLE_COMPLETE` (`safety-poc/research/door/v1_5_7/comelit-v4-persistent-ctpp-door.c:1926-1948`, `safety-poc/research/door/v1_5_7/comelit-v4-persistent-ctpp-door.c:2524-2526`, `safety-poc/research/door/v1_5_7/comelit-v4-persistent-ctpp-door.c:2582-2591`, `custom_components/comelit/runtime.py:665-731`).  
C2 exact observed `UNKNOWN_OUTCOME` sub-branch is UNPROVEN offline because the missing parsed marker is a safe sent/settle branch marker such as `V4_DOOR_SETTLE_COMPLETE` or `V4_DOOR_OPERATION_WRITE_<n>_SENT` (`safety-poc/research/door/v1_5_7/comelit-v4-persistent-ctpp-door.c:1926-1948`, `safety-poc/research/door/v1_5_7/comelit-v4-persistent-ctpp-door.c:2524-2533`, `custom_components/comelit/runtime.py:665-731`).  

C3 is CONFIRMED_BY_SOURCE that listener READY is emitted immediately after `v4_registered=TRUE` and `v4_listener_ready=TRUE`, and before the stage is set back to `P12_STAGE_V4_LISTEN_RING` (`safety-poc/research/door/v1_5_7/comelit-v4-persistent-ctpp-door.c:1846-1889`).  
C3 is CONFIRMED_BY_SOURCE that the supervisor READY state is driven by `runtime.listener_ready` polling (`custom_components/comelit/supervisor.py:198-234`).  
C3 is CONFIRMED_BY_SOURCE that `async_open_door()` can report `UNKNOWN_OUTCOME` from either the 10-second Python wait timeout or process-exit pending future resolution (`custom_components/comelit/runtime.py:464-516`, `custom_components/comelit/runtime.py:547-552`).  
C3 READY-before-door-actually-usable race is UNPROVEN because native READY plus the door guard are necessary but not proven sufficient for a physical relay effect, and the observed `UNKNOWN_OUTCOME` could also be a post-send no-ACK path or Python timeout/process-exit path (`safety-poc/research/door/v1_5_7/comelit-v4-persistent-ctpp-door.c:1846-1889`, `safety-poc/research/door/v1_5_7/comelit-v4-persistent-ctpp-door.c:2563-2580`, `custom_components/comelit/runtime.py:464-516`, `custom_components/comelit/runtime.py:547-552`).  
C3 current READY contract needs additional observability rather than a proven lifecycle fix because no cited repository source proves that READY guarantees door-specific ACK eligibility or physical relay readiness (`safety-poc/research/door/v1_5_7/comelit-v4-persistent-ctpp-door.c:1846-1889`, `custom_components/comelit/runtime.py:474-516`).  

C4 is CONFIRMED_BY_SOURCE that automatic retry is forbidden by the native door contract and exposed as false in HA results (`safety-poc/research/door/v1_5_7/comelit-v4-persistent-ctpp-door.c:227-238`, `custom_components/comelit/runtime.py:486-500`).  
C4 is CONFIRMED_BY_SOURCE that no change should weaken the protocol ACK requirement because Python requires both `state == "ACKED"` and `door_specific_ack_proven` before `protocol_acked=true` (`custom_components/comelit/runtime.py:474-514`).  
C4 is CONFIRMED_BY_SOURCE that no production fix is justified without a proven root cause because the exact observed `UNKNOWN_OUTCOME` sub-branch remains UNPROVEN offline (`custom_components/comelit/runtime.py:665-731`, `safety-poc/research/door/v1_5_7/comelit-v4-persistent-ctpp-door.c:1926-1961`, `safety-poc/research/door/v1_5_7/comelit-v4-persistent-ctpp-door.c:2516-2536`).  

## INFERENCE

The physical ring did not fail at HA event ingestion because the operator evidence records `comelit_ring=FIRED` and a safe event id, and the failure boundary is after the ring event in media bootstrap (`OPERATOR_LIVE_EVIDENCE`).  
The physical media failure is best bounded to the self-activation signaling lane before `P80_MEDIA_ACTIVE` because operator evidence has PseudoTCP open final true and video/audio counts zero, while `P80_MEDIA_ACTIVE` is the marker that Home Assistant waits for before local SDP readiness (`OPERATOR_LIVE_EVIDENCE`, `custom_components/comelit/media_transport.py:689-711`, `custom_components/comelit/media_transport.py:754-760`).  
The exact `ENTRANCE_SIGNALING_TIMEOUT` stage is not recoverable from HA-stored safe markers because the safe-marker regex redacts compound values such as `true STAGE=n` (`custom_components/comelit/media_transport.py:42-48`, `custom_components/comelit/media_transport.py:401-414`).  
The synthetic canary proves the self-activation/RTPC media lane can work when HA synthesizes a ring event, but it does not prove that a real inbound call transaction can be ignored safely for physical ring media (`docs/mvp1-synthetic-ring-canary-result.md:63-74`, `custom_components/comelit/runtime.py:267-285`, `safety-poc/research/media/v1/P116_R29A_INBOUND_MEDIA_WIRE_CONTRACT.md:72-100`).  
The door result is compatible with sent-no-door-specific-ACK and is not equivalent to "command not sent" unless additional markers prove a pre-send rejection path (`safety-poc/research/door/v1_5_7/comelit-v4-persistent-ctpp-door.c:2491-2512`, `safety-poc/research/door/v1_5_7/comelit-v4-persistent-ctpp-door.c:2528-2533`).  

## KNOWN R29 CONTRACT

R29A proves the native call path stores an inbound call CTP id and binds mediareq26 open/stop to that call-scoped id (`safety-poc/research/media/v1/P116_R29A_INBOUND_MEDIA_WIRE_CONTRACT.md:72-90`).  
R29A proves the helper has no anchored call-bound `mediareq26` builder or call CTP binding equivalent (`safety-poc/research/media/v1/P116_R29A_INBOUND_MEDIA_WIRE_CONTRACT.md:213-214`).  
R29A proves native media-only close requires call-bound `mediareq26(stop)` plus saved media-channel/RTP disposal (`safety-poc/research/media/v1/P116_R29A_INBOUND_MEDIA_WIRE_CONTRACT.md:34-45`, `safety-poc/research/media/v1/P116_R29A_INBOUND_MEDIA_WIRE_CONTRACT.md:350-353`).  
R29B keeps `R29_MEDIA_OPEN_MODEL=BLOCKED` and `R29_MEDIA_ONLY_TEARDOWN_MODEL=BLOCKED` because the helper lacks a separate inbound call CTP transaction id (`safety-poc/research/media/v1/P116_R29B_HELPER_LOCAL_INBOUND_MEDIA_MAPPING.md:26-37`).  
R29B keeps `CALL_BOUND_MEDIAREQ26_OPEN_GENERATION=BLOCKED` and `CALL_BOUND_MEDIAREQ26_STOP_GENERATION=BLOCKED` (`safety-poc/research/media/v1/P116_R29B_HELPER_LOCAL_INBOUND_MEDIA_MAPPING.md:41-50`).  
R29 live proof refused production handoff while the open and teardown models were blocked (`safety-poc/research/media/v1/P116_R29_LISTENER_ATTACHED_MEDIA_LIVE_PROOF.md:33-45`, `safety-poc/research/media/v1/P116_R29_LISTENER_ATTACHED_MEDIA_LIVE_PROOF.md:49-49`).  
R30B/R30C/R30D/R30E added offline call-transaction and rebuild provenance evidence, but they did not add a production inbound-call-scoped lane in `custom_components/comelit` for physical ring media (`safety-poc/research/media/v1/P116_R30B_OFFLINE_CALL_TRANSACTION_RESULT.md:69-94`, `safety-poc/research/media/v1/P116_R30D_NATIVE_CTP_RUNTIME_INTEGRATION_RESULT.md:28-47`, `safety-poc/research/media/v1/P116_R30E_NATIVE_HELPER_REBUILD_PROVENANCE_RESULT.md:50-99`).  

## UNPROVEN HYPOTHESES

MEDIA_RC6_STAGE exact `STAGE=n` is UNPROVEN because HA safe-marker retention redacts compound timeout values (`custom_components/comelit/media_transport.py:42-48`, `custom_components/comelit/media_transport.py:401-414`).  
CURRENT_HELPER_HAS_CALL_BOUND_BINDING is false by the cited R29B helper-local mapping, and any contrary claim would require new source evidence not present here (`safety-poc/research/media/v1/P116_R29B_HELPER_LOCAL_INBOUND_MEDIA_MAPPING.md:26-31`, `safety-poc/research/media/v1/P116_R29B_HELPER_LOCAL_INBOUND_MEDIA_MAPPING.md:228-237`).  
DOOR_UNKNOWN_OUTCOME_STAGE is UNPROVEN because Python does not parse the safe branch markers that would distinguish accepted-write, per-write, settle, timeout, and process-exit paths (`custom_components/comelit/runtime.py:665-731`, `safety-poc/research/door/v1_5_7/comelit-v4-persistent-ctpp-door.c:1926-1961`, `safety-poc/research/door/v1_5_7/comelit-v4-persistent-ctpp-door.c:2516-2536`).  
DOOR_READY_RACE is UNPROVEN because repository evidence proves READY ordering and the door guard, but not physical relay readiness or door-specific ACK eligibility after READY (`safety-poc/research/door/v1_5_7/comelit-v4-persistent-ctpp-door.c:1846-1889`, `safety-poc/research/door/v1_5_7/comelit-v4-persistent-ctpp-door.c:2563-2580`).  

## ARCHITECTURE DECISION REQUIRED

Option A is ATTACHED_INBOUND_SESSION, where ring media stays inside the existing inbound listener session and implements the native call-scoped mediareq26 and media RX lifetime model (`safety-poc/research/media/v1/P116_R29A_INBOUND_MEDIA_WIRE_CONTRACT.md:72-100`, `safety-poc/research/media/v1/P116_R29A_INBOUND_MEDIA_WIRE_CONTRACT.md:129-140`).  
Option B is SEPARATE_SESSION, where a separate new self-activation session after the ring is accepted despite lacking native inbound-call equivalence (`custom_components/comelit/media_session.py:244-253`, `custom_components/comelit/media_transport.py:632-687`, `safety-poc/research/media/v1/P116_R29A_INBOUND_MEDIA_WIRE_CONTRACT.md:343-348`).  
Option C is INSUFFICIENT_EVIDENCE, where production waits for more evidence before changing ring media architecture (`safety-poc/research/media/v1/P116_R29A_INBOUND_MEDIA_WIRE_CONTRACT.md:366-366`).  
Native evidence supports Option A, but choosing it requires a user decision because manual/self-activation media and ring-attached media would become distinct bootstrap paths under one ownership and safety model (`safety-poc/research/media/v1/P116_R29A_INBOUND_MEDIA_WIRE_CONTRACT.md:72-100`, `custom_components/comelit/supervisor.py:35-45`, `custom_components/comelit/media_transport.py:216-223`).  

## VERIFICATION

Command `cd safety-poc && PYTHONPATH=$PWD/src PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_p116_r31_media_start_failure_diagnostics -v` ran 8 tests and ended `OK` (`COMMAND_OUTPUT_THIS_PASS`).  
Command `cd safety-poc && PYTHONPATH=$PWD/src PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_p80_media_session_manager tests.test_mvp1_ring_telegram_offline_build tests.test_mvp1_synthetic_ring_control tests.test_mvp1_integration_offline_build -v` ran 49 tests and ended `OK` (`COMMAND_OUTPUT_THIS_PASS`).  
The known pre-existing baseline failure was reproduced for `tests.test_p116_provenance_binary_analysis.P116ProvenanceBinaryAnalysisTests.test_committed_build_metadata_records_historical_non_runtime_mismatch`, where `NATIVE_BINARY_MODE '755' != '775'` failed as a worktree file-mode artefact (`COMMAND_OUTPUT_THIS_PASS`).  

```text
=== COMELIT P116 R31 PHYSICAL RING OFFLINE CORRECTIVE (REPO DOC) ===
BASE_SHA=4ef019cf3fd240ceae4663d82d91a2cdca17f600
OBSERVABILITY_DEFECT_CONFIRMED=true
OBSERVABILITY_FIX_IMPLEMENTED=true
PHYSICAL_RING_EVENT_PATH=PASS
PHYSICAL_MEDIA_FAILURE_BOUNDARY=MEDIA_BOOTSTRAP_BEFORE_ACTIVE
MEDIA_RC6_STAGE=UNPROVEN
SYNTHETIC_VS_PHYSICAL_SEMANTIC_DIFFERENCE=CONFIRMED
CALL_BOUND_MEDIAREQ26_REQUIRED=CONFIRMED
CURRENT_HELPER_HAS_CALL_BOUND_BINDING=false
R29B_GAP_STILL_APPLIES=true
ARCHITECTURE_CANDIDATE=ATTACHED_INBOUND_SESSION
ARCHITECTURE_CHANGE_REQUIRED=true
DOOR_UNKNOWN_OUTCOME_STAGE=UNPROVEN
DOOR_READY_RACE=UNPROVEN
LIVE_INVOCATIONS=0
NETWORK_TX=0
=== END COMELIT P116 R31 PHYSICAL RING OFFLINE CORRECTIVE (REPO DOC) ===
```
