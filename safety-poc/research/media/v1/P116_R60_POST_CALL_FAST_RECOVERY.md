# P116 R60 Track A post-call PseudoTCP fast recovery

Дата: 2026-09-22. Режим: `OFFLINE_FORENSIC_ONLY`. Native build, deploy, HA restart, live TX, listener launch, Door/Gate actions and physical ring were not run. Track B не затрагивался. `TRACK_A_DOOR_SEMANTICS_CHANGED=false`.

## A2 Window Decomposition

`OBSERVED` Граница окна остается такой же, как в R59: media CLOSED at `2026-09-22 21:26:54.919` -> fresh READY at `2026-09-22 21:27:46.128`, therefore `POST_CALL_UNAVAILABLE_MS=51209`.

`PROVEN_OFFLINE` Decomposition from committed fixture `P116_R59_R58_CANARY_TIMELINE_EVIDENCE.txt`:

```
POST_CALL_EXIT_LATENCY_MS=6
FIRST_RECONNECT_START_DELAY_MS=5618
FIRST_RECONNECT_LIFETIME_MS=34875
BETWEEN_RECONNECT_BACKOFF_MS=5155
SECOND_RECONNECT_TO_READY_MS=5555
SUM_RECONCILIATION=6+5618+34875+5155+5555=51209
TOLERANCE_MS=0 for fixture arithmetic, live-log timestamp precision +/-1ms
```

Sources: CLOSED/exit/reconnect/fresh READY timestamps are observed fixture timestamps; `FIRST_RECONNECT_START_DELAY_MS` is derived from first failure plus the observed supervisor log and `RECONNECT_DELAY_SECONDS=5`; `FIRST_RECONNECT_LIFETIME_MS` is derived from the policy-delayed reconnect start to the second native failure; `BETWEEN_RECONNECT_BACKOFF_MS` is derived from second failure through the second policy-delayed reconnect start; `SECOND_RECONNECT_TO_READY_MS` is derived from that second reconnect start to READY.

## A3 First Reconnect Verdict

`PROVEN_STATIC` `FIRST_RECONNECT_LAST_PROVEN_STAGE=PSEUDOTCP_PRE_OPEN_AFTER_ICE_READY_SELECTED_PAIR`. In generated source, `component_state_changed_cb()` on `NICE_COMPONENT_STATE_READY` sets `ice_ready`, prints `ICE_READY=PASS`, requires `report_selected_pair()` success, then calls `start_pseudotcp()`; `start_pseudotcp()` creates the socket and calls `pseudo_tcp_socket_connect()` (`comelit_ice_offer_holder.v4-persistent.c:5019-5075`, `4822-4924`). Consequence: if a reconnect attempt reached PseudoTCP, it already had ICE READY and a selected pair.

`PROVEN_OFFLINE` `FIRST_RECONNECT_35S_TIMER_MATCH=LIBNICE_PRE_ESTABLISHED_RETRANSMIT_30x1000MS_PLUS_BOOTSTRAP`. In `EXTERNAL_UPSTREAM_SOURCE` libnice 0.1.22, `transmit()` returns `ETIMEDOUT` once `segment->xmit >= 30` before `PSEUDO_TCP_ESTABLISHED`, and `notify_clock()` caps pre-established RTO to `DEF_RTO=1000` ms (`libnice-0.1.22-agent-pseudotcp.c:1004-1007`, `2064-2071`). Observed first reconnect process lifetime is `34875ms`; subtracting `30000ms` leaves `4875ms` for cloud/native bootstrap before the PseudoTCP timer budget dominates. This is compatible with timeout-driven close, not an immediate close.

`PROVEN_OFFLINE` `FIRST_RECONNECT_FAILURE_IMMEDIATE_OR_TIMEOUT_DRIVEN=TIMEOUT_DRIVEN`. The first reconnect failure at `21:27:35.418` is `PSEUDOTCP_CLOSED`/`STARTUP`; the derived process lifetime `34875ms` is inconsistent with an immediate packet reject and matches the pre-OPEN retransmission model. Armed state at close: `pseudo_tcp` created, PseudoTCP connect started, `pseudotcp_open=false`; R59/R60 safe marker tail says no call adoption markers were true in the failed reconnect. The listener did not receive a proven remote close marker; it waited for local retransmit timeout detection via libnice clock/closed callback.

## A4 M1/M2/M3 Verdict

`SUPPORTED` `RECONNECT_TOO_EARLY_HYPOTHESIS=SUPPORTED`. Correlation is not causality: the saved evidence shows post-call fatal exit, reconnect count=1, a timeout-shaped STARTUP close, then count=2 and READY. This supports an early reconnect/server-held-session explanation, but does not prove the server rejected SYN because of the previous session.

`SUPPORTED` `SERVER_SIDE_SESSION_RELEASE_DELAY_EVIDENCE=SUPPORTED`. The discriminating support is timing: first reconnect enters a PseudoTCP timeout-shaped dead wait and fresh READY appears only after the later reconnect. The saved windows do not include a wire capture or remote RELEASE marker, so this remains supported, not proven.

M1: `SUPPORTED`. Previous process exited on `PSEUDOTCP_NOTIFY_PACKET` six ms after media CLOSED, with no media-path PseudoTCP close in R58. A new process then timed out pre-OPEN. This is the best fit.

M2: `REJECTED_FOR_SDP_STALENESS`, `UNKNOWN_FOR_REGISTRATION_IDENTITY`. Static source unlinks `OFFER_FILE`, `REMOTE_FILE`, and `STOP_FILE` at process start (`comelit_ice_offer_holder.v4-persistent.c:5752-5768`), and Python writes a new `remote.sdp` after every `runtime.async_start()` negotiation (`runtime.py:1035-1108`). Other state persists: `RUN_DIR`, `/root/.config/comelit/secrets.env` during cycle setup, `p12-ucfg-response.json`, cloud/P2P registration identity, call-generation logic, and CTPP binding. No saved evidence proves stale persisted identity caused the failure.

M3: `SUPPORTED_AS_CONTRIBUTOR_NOT_ROOT_CAUSE`. The media STOP path publishes `R58_STOP_CLOSED=true` and `R42_MEDIA_CHANNEL_CLOSED=true`, but the R58 media STOP/remote-release path does not call `pseudo_tcp_socket_close()` or `pseudo_tcp_socket_shutdown()`. The only transformed-chain `pseudo_tcp_socket_close(pseudo_tcp, FALSE)` is on the process stop file callback, not the attached-media STOP path. `PSEUDOTCP_TEARDOWN_CALLS_ON_MEDIA_STOP=0`; call sites found: `pseudo_tcp_socket_close(pseudo_tcp, FALSE)` on STOP_FILE process stop only.

Additional observation that would flip the verdict to proven: live wire capture or bounded native marker showing old session remote RELEASE/FIN/RST timing and first reconnect SYN packets unanswered until a server release boundary.

## A5 notify_packet FALSE And Shipped Source

`PROVEN_STATIC` `PSEUDO_TCP_NOTIFY_PACKET_FALSE_REASONS=LEN_GT_MAX_PACKET,LEN_LT_HEADER_SIZE,PARSE_HEADER_SIZE_NOT_24,WRONG_CONVERSATION,CLOSED_OR_FIN_ACK_WITH_DATA,RST_FLAG,CTL_LEN_ZERO,UNKNOWN_CTL_CODE,INVALID_RTT,RECOVERY_RETRANSMIT_FAILURE,FIN_WITH_DATA,INVALID_FIN_STATE`.

Mapping to observed event: R58 first process saw `P116_NATIVE_FAILURE_ID=PSEUDOTCP_NOTIFY_PACKET`, phase `LISTENER_READY`, count=1, immediately after media CLOSED. The HA windows do not carry the native stderr `PSEUDOTCP_NOTIFY_PACKET=FAIL LEN=%u`, so `LEN=UNKNOWN`. The two length guards are possible only if inbound UDP length was outside libnice PseudoTCP bounds; process branches are possible only after a valid 24-byte header. `RST_FLAG` and `CLOSED_OR_FIN_ACK_WITH_DATA` would represent remote/closed-state terminal traffic; `WRONG_CONVERSATION`, `CTL_LEN_ZERO`, `UNKNOWN_CTL_CODE`, `INVALID_RTT`, `FIN_WITH_DATA`, and recovery retransmit failure remain possible without packet bytes.

`PROVEN_OFFLINE` `SHIPPED_LIBNICE_SOURCE_SUFFICIENT=true`. Evidence: build metadata in the task states the proven build used libnice 0.1.22; committed derived fixture `P116_R60_LIBNICE_0_1_22_EVIDENCE.txt` records upstream URL/ref, whole-file sha256 `d0eb851f16bf546096f8edcc9fce3b3d32cdb4f035d3d35662d615dd28920dee`, byte size `80443`, and exact line-numbered snippets for the timer and FALSE-return branches. Native binary sha256 is derived in tests from the R58 provenance record, not from a bare test literal. For this R60 question, upstream libnice evidence is sufficient to explain timer and FALSE-return branches.

`PROVEN_OFFLINE` `NEEDS_SHIPPED_SO_STATIC_INSPECTION=false`. Reason: no evidence suggests a patched libnice, and the needed behavior is from upstream source plus known build version. Static inspection of shipped `.so` would be needed only if future evidence contradicts upstream branch behavior or build provenance.

## A6 Call Lifecycle Verdict

`OBSERVED` media CLOSED is proven: `R58_STOP_PHASE=CLOSED`, `R58_STOP_CLOSED=true`, `R42_MEDIA_CHANNEL_CLOSED=true`, and HA `Comelit attached inbound media CLOSED`.

`PROVEN_STATIC` media CLOSED is not call CLOSED. In the transformed source, inbound RELEASE opcode `0x000E` dispatches to `r37_handle_remote_release()`, and that handler calls `r35_teardown_call(s)` after `r58_stop_request(... R58_STOP_ORIGIN_REMOTE_RELEASE)`. That implies call transaction terminality is tied to inbound RELEASE handling, not to local media channel disposal.

`UNKNOWN` `REMOTE_RELEASE_OBSERVED=UNKNOWN`. Saved fixture and windows do not contain `R37_REMOTE_RELEASE_OBSERVED=true`.

`UNKNOWN` `LOCAL_CALL_TEARDOWN_COMPLETE=UNKNOWN`. The static path would complete teardown after inbound RELEASE, but the required live marker is absent.

`UNKNOWN` `CALL_TRANSACTION_ACTIVE_AT_EXIT=UNKNOWN`. The absence of `R37_REMOTE_RELEASE_OBSERVED=true` prevents proving whether the call transaction was still active at the `PSEUDOTCP_NOTIFY_PACKET` exit. Exact marker that would close it: `R37_REMOTE_RELEASE_OBSERVED=true` before `P116_NATIVE_FAILURE_COUNT=1`, ideally with `R37_PROTOCOL_STOP_RESULT` and `POST_CALL_TRANSPORT_STATE`.

## A7 Corrective Decision

`PROVEN_OFFLINE` `RECOVERY_CORRECTIVE_CLASS=NO_FUNCTIONAL_CORRECTIVE`.

`PROVEN_OFFLINE` `RECOVERY_CORRECTIVE_IMPLEMENTED=false`.

Reason: the strongest root-cause class is `RECOVERY_ROOT_CAUSE=EARLY_RECONNECT_SUPPORTED_NOT_PROVEN`, with M3 as a contributor. The proof is insufficient for `EARLY_RECONNECT_GUARD`, `FAST_FAIL_FIRST_RECONNECT`, `GRACEFUL_POST_CALL_RECYCLE`, or `STALE_SESSION_STATE_CORRECTIVE` without risking masked transport errors. Missing proof: remote release/session-release timing or packet capture proving that the first reconnect waits on a server-held previous session.

Forbidden alternatives remain forbidden: no arbitrary timeout shrinking, no converting exit 6 into success, no parallel listener, no reconnect tight loop, and no ignoring post-call PseudoTCP errors.

## A8 Expected Model

`UNRESOLVED` `EXPECTED_POST_CALL_UNAVAILABLE_MS=UNKNOWN`. With no functional corrective, the measured baseline remains `51209ms`. A hypothetical proven early-reconnect guard could target approximately `POST_CALL_EXIT_LATENCY_MS + release_guard + bootstrap_to_READY`; however `release_guard` is not measured or proven. The honest bounded minimum from current evidence cannot be claimed. Reliability is preferred over a nicer number.

## A9 Offline Lifecycle Harness

`PROVEN_OFFLINE` A Python unittest harness implements one scenario function per contract case and derives markers from scenario inputs/source text rather than printing PASS literals.

Case coverage:

- `CASE_A_RESULT=PASS`: old call ends -> old listener transport failure -> reconnect -> registration -> READY.
- `CASE_B_RESULT=PASS`: first reconnect stale/rejected remains a visible `34875ms` dead wait when proof is missing; any model that hides the gap or applies a functional corrective flips to `FAIL`.
- `CASE_C_RESULT=PASS`: unrelated transport failure remains failure-closed and is not recycled as graceful success.
- `CASE_D_RESULT=PASS`: repeated failures use bounded attempts and monotonic non-decreasing backoff; unbounded attempts or tight delays flip to `FAIL`.
- `CASE_E_RESULT=PASS`: listener start/stop events never overlap into parallel listeners.
- `CASE_F_RESULT=PASS`: READY is accepted only after registration for the same attempt.
- `CASE_G_RESULT=PASS`: source-level Door action guard proves `async_wait_ready(timeout=30)` fails safe before `SIGUSR1`; no Door code or semantics were changed for Track A.

Derived harness output:

```
CASE_A_RESULT=PASS
CASE_B_RESULT=PASS
CASE_C_RESULT=PASS
CASE_D_RESULT=PASS
CASE_E_RESULT=PASS
CASE_F_RESULT=PASS
CASE_G_RESULT=PASS
HARNESS_AGGREGATE=PASS
```

Flip tests corrupt each case input and assert the corresponding case flips to `FAIL`. A guard test fails if harness markers are embedded as literal `...=PASS` strings instead of rendered from case results.

## Provenance

`PROVEN_OFFLINE`

```
BASE_SHA=e888cb254830692239082f3925f6ebcede7c53a3
CURRENT_PRODUCTION_SHA=b318101d07f8f32d9f703e845b32c7f3538548b1
PRODUCTION_BINARY_SHA256=40c8a2c19fe5e792c28082ee0b1f60732cd90b5ffaa1cdb05c82575361cef762
GENERATED_SOURCE_BASE_SHA256=7b33945be9bd87fbfff96c2947259e924a113552f2396ee84c77fdb2692082f8
R58_TRANSFORMED_SOURCE_SHA256=e1c82a988d52449121524d32f25af2e648806c73cf4aa29f68dda428f1d2922a
R60_GENERATED_SOURCE_CHANGED=false
R60_NATIVE_BINARY_REBUILT=false
DETERMINISM=not_applicable_no_source_generation_change
ALLOWED_TO_DISPATCH_NATIVE_BUILD=false
```

`EXTERNAL_UPSTREAM_SOURCE` `.r60-evidence/libnice-0.1.22-agent-pseudotcp.c` sha256 `d0eb851f16bf546096f8edcc9fce3b3d32cdb4f035d3d35662d615dd28920dee`; `.h` sha256 `1e4c0c2317e172bb3513ef0ee68a8dfc3158f8e8e93981d148254d47c19180cb`.

`PROVEN_OFFLINE` CI-faithfulness corrective: R60 model/test evidence paths are repo-local only. The model reads the committed fixture `P116_R60_LIBNICE_0_1_22_EVIDENCE.txt`; it does not resolve `.r60-evidence`.

Executed focused command:

```
cd safety-poc && PYTHONPATH=/home/hermes/artifacts/comelit/safety-poc/src:/home/hermes/artifacts/comelit/safety-poc PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_p116_r60_post_call_fast_recovery
Ran 26 tests in 0.049s
OK
```

## Sanitisation

`PROVEN_OFFLINE` This document uses committed sanitized fixture, committed derived libnice evidence, and bounded source/provenance records. It contains no raw credentials, payloads, addresses, CTP ids, packet captures, live Door/Gate action claims, or live network observations. Door/Gate/media domains remain separate; this Track A document contains no Door-protocol implementation content.

## Machine Values

```
POST_CALL_UNAVAILABLE_MS_BASELINE=51209
POST_CALL_EXIT_LATENCY_MS=6
FIRST_RECONNECT_START_DELAY_MS=5618
FIRST_RECONNECT_LIFETIME_MS=34875
BETWEEN_RECONNECT_BACKOFF_MS=5155
SECOND_RECONNECT_TO_READY_MS=5555
SUM_RECONCILIATION=6+5618+34875+5155+5555=51209
FIRST_RECONNECT_LAST_PROVEN_STAGE=PSEUDOTCP_PRE_OPEN_AFTER_ICE_READY_SELECTED_PAIR
FIRST_RECONNECT_35S_TIMER_MATCH=LIBNICE_PRE_ESTABLISHED_RETRANSMIT_30x1000MS_PLUS_BOOTSTRAP
FIRST_RECONNECT_FAILURE_IMMEDIATE_OR_TIMEOUT_DRIVEN=TIMEOUT_DRIVEN
RECONNECT_TOO_EARLY_HYPOTHESIS=SUPPORTED
SERVER_SIDE_SESSION_RELEASE_DELAY_EVIDENCE=SUPPORTED
PSEUDO_TCP_NOTIFY_PACKET_FALSE_REASONS=LEN_GT_MAX_PACKET,LEN_LT_HEADER_SIZE,PARSE_HEADER_SIZE_NOT_24,WRONG_CONVERSATION,CLOSED_OR_FIN_ACK_WITH_DATA,RST_FLAG,CTL_LEN_ZERO,UNKNOWN_CTL_CODE,INVALID_RTT,RECOVERY_RETRANSMIT_FAILURE,FIN_WITH_DATA,INVALID_FIN_STATE
SHIPPED_LIBNICE_SOURCE_SUFFICIENT=true
NEEDS_SHIPPED_SO_STATIC_INSPECTION=false
PSEUDOTCP_TEARDOWN_CALLS_ON_MEDIA_STOP=0
REMOTE_RELEASE_OBSERVED=UNKNOWN
LOCAL_CALL_TEARDOWN_COMPLETE=UNKNOWN
CALL_TRANSACTION_ACTIVE_AT_EXIT=UNKNOWN
RECOVERY_ROOT_CAUSE=EARLY_RECONNECT_SUPPORTED_NOT_PROVEN
RECOVERY_CORRECTIVE_IMPLEMENTED=false
RECOVERY_CORRECTIVE_CLASS=NO_FUNCTIONAL_CORRECTIVE
RECOVERY_CORRECTIVE_TARGET=OBSERVABILITY_ONLY_NO_CODE_CHANGE
EXPECTED_POST_CALL_UNAVAILABLE_MS=UNKNOWN
CASE_A_RESULT=PASS
CASE_B_RESULT=PASS
CASE_C_RESULT=PASS
CASE_D_RESULT=PASS
CASE_E_RESULT=PASS
CASE_F_RESULT=PASS
CASE_G_RESULT=PASS
HARNESS_AGGREGATE=PASS
GENERATED_SOURCE_CHANGED=false
ALLOWED_TO_DISPATCH_NATIVE_BUILD=false
MISSING_REQUIRED_EVIDENCE=remote_RELEASE_marker_or_wire_capture
```
