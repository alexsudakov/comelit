# P116 R58 Attached Media STOP Cleanup Corrective

## 1. STOP contract

PROVEN_STATIC: Python runtime path is `async_stop_attached_media()` / `attached_media.async_stop()` -> SIGUSR2. Native path is `g_unix_signal_add` -> `r37_bounded_stop_signal_cb` -> historically `r37_bounded_stop_request` -> `r37_stop_and_dispose` -> `r35_send_stop` -> RTP disarm -> `r35_dispose_media_rx_channel`.

PROVEN_OFFLINE: R58 changes that callback to `r58_stop_request(..., R58_STOP_ORIGIN_HA_SIGNAL)` and preserves the historical callback prints.

## 2. Canary marker table

| marker | OBSERVED | timestamp | obs |
| --- | --- | --- | --- |
| `BOUNDED_STOP_REQUEST_RECEIVED` | UNKNOWN | UNKNOWN | not_published |
| `R37_BOUNDED_STOP_RESULT` | UNKNOWN | UNKNOWN | not_published |
| `CALL_BOUND_MEDIA_STOP_SENT_COUNT` | UNKNOWN | UNKNOWN | not_published |
| `R42_ATTACHED_MEDIA_STOP_SENT` | true | 2026-09-22 19:59:20.745 | published |
| `R42_MEDIA_STOP_CHANNEL` | UNKNOWN | UNKNOWN | not_published |
| `RTP_DISARMED` | UNKNOWN | UNKNOWN | not_published |
| `MEDIA_RX_CHANNEL_DISPOSED` | UNKNOWN | UNKNOWN | not_published |
| `R42_MEDIA_CHANNEL_CLOSED` | false | UNKNOWN | published |
| `R42_LISTENER_RTP_FORWARDING_ARMED` | true | 2026-09-22 19:59:20.745 | published |

OBSERVED: markers that the deployed HA path did not publish are `UNKNOWN`, not `false`.

## 3. Release chain

OBSERVED: `HA_RELEASE_REQUEST -> SIGUSR2_REQUESTED -> SIGUSR2_NATIVE_CALLBACK` is inferred from stop initiation and the historical STOP tail.
PROVEN_BY_CODE: `R37_STOP_REQUEST -> STOP_BUILT -> STOP_ENQUEUED -> STOP_FLUSHED -> RTP_DISARMED -> CHANNEL_DISPOSED`.
NOT_REACHED: `CHANNEL_CLOSED_MARKER -> HA_CLOSED_EVENT`.
NOT_OBSERVABLE: raw frame boundaries and raw ids are not published.

## 4. Failure boundary

PROVEN_STATIC: `STOP_FAILURE_BOUNDARY=DISPOSE_NO_CLOSED_MARKER`.
OBSERVED: `R42_ATTACHED_MEDIA_STOP_SENT=true` and `R42_LISTENER_RTP_FORWARDING_ARMED=false` exclude `HA_SIGNAL_NOT_DELIVERED`, `NATIVE_SIGNAL_CALLBACK_NOT_RUN`, `STOP_REQUEST_REJECTED`, `STOP_ENQUEUE_FAILED`, `STOP_NOT_FLUSHED`, `CLOSED_MARKER_NOT_PARSED_BY_HA`, and `REMOTE_RELEASE_RACE`.
PROVEN_STATIC: `TIMEOUT_TOO_SHORT` is not selected because the native marker was never generated, and the R33 contract requires no remote STOP ACK.

## 5. R56 scheduler findings

PROVEN_STATIC: `MEDIA_OPEN_SHARES_P12_TX_QUEUE=true`.
PROVEN_STATIC: `MEDIA_STOP_SHARES_P12_TX_QUEUE=true`.
PROVEN_STATIC: `MEDIA_STOP_USES_R56_SCHEDULER=false` before R58. The direct path is `r35_glib_transport_writer()` -> `p12_queue_vip_frame()` -> `p12_queue_bytes()`, where `p12_tx_pending` produces the BUSY attribution and no queued STOP.

## 6. Enqueue vs flush

PROVEN_STATIC: `R42_ATTACHED_MEDIA_STOP_SENT=true` is printed from `p12_tx_completed()`, so it means TX-slot completion, not initial enqueue. The historical marker name is unchanged. R58 splits phases with `R58_STOP_PHASE=REQUESTED|WAIT_TX_SLOT|ENQUEUED|RTP_DISARMED|DISPOSED|FLUSHED|CLOSED|FAILED`.

## 7. Remote release

PROVEN_STATIC: `REMOTE_RELEASE_CAN_CLOSE_WITHOUT_SIGUSR2_STOP=true`.
PROVEN_STATIC: `HA_CLOSED_MARKER_EMITTED_ON_REMOTE_RELEASE=false` before R58.
PROVEN_OFFLINE: `HA_CLOSED_MARKER_EMITTED_ON_REMOTE_RELEASE=true` after R58.
PROVEN_OFFLINE: at most one protocol STOP is written per generation.

## 8. Dispose semantics

PROVEN_STATIC: `r35_send_stop` sets `stop_sent`, increments `stop_count`, disarms RTP, and marks `R35_STATE_STOP_SENT`.
PROVEN_STATIC: `r35_dispose_media_rx_channel` is synchronous, flips `channel_disposed` / `channel_allocated`, requires no remote response, and marks `R35_STATE_DISPOSED`.
PROVEN_OFFLINE: corrected CLOSED boundary is `R58_CLOSED_BOUNDARY=LOCAL_DISPOSAL_AFTER_STOP_FLUSH`.

## 9. HA side

PROVEN_STATIC: `HA_STOP_TIMEOUT_SECONDS=10` is unchanged.
PROVEN_STATIC: `HA_STOP_TIMEOUT_IS_CAUSAL=false`. Raising the timeout is forbidden because the native close marker was never generated.

## 10. Stream worker

OBSERVED: `STREAM_WORKER_ERROR_CAUSAL=false`. The stream worker error at 2026-09-22 19:59:40.760 is downstream of HA shim stop and local SDP removal after the 19:59:30.744 failure path.

## 11. Observability

PROVEN_OFFLINE: R58 adds bounded `R58_STOP_PHASE`, `R58_STOP_FAILURE_STAGE`, `R58_CLOSED_BOUNDARY`, `R58_STOP_CLOSED`, and `R58_STOP_FAILED` markers. HA accepts only the bounded enum values and value-key dedups `R58_STOP_PHASE`.

## 12. Corrective classes

PROVEN_OFFLINE: class A scheduler integration is implemented by `r58_stop_drive` using the existing single P12 slot.
PROVEN_OFFLINE: class B remote-release authoritative CLOSED is implemented by routing remote release through `r58_stop_request`.
PROVEN_OFFLINE: class C CLOSED on the correct completion boundary is implemented in `r58_stop_publish_closed`.
PROVEN_STATIC: class D `HA parser/event` is `NOT_APPLICABLE`; the native marker was never emitted.

## 13. Harness

PROVEN_OFFLINE: scenarios covered are normal path, queue busy, duplicate HA STOP, remote release before SIGUSR2, remote release after SIGUSR2, SIGUSR2 after closed, write failure, flush timeout, generation replacement, and exactly one protocol STOP.
PROVEN_OFFLINE: gate markers are `R58_HOST_HARNESS_RESULT`, `R58_STOP_COUNT_MAX`, `R58_STOP_FLUSHED_BEFORE_CLOSED`, `R58_HA_CLOSE_CONFIRMATION_REACHED`, `R58_NO_FALSE_STOP_TIMEOUT`, `R58_NETWORK_TX`, `R58_DOOR_ACTIONS`, `R58_GATE_ACTIONS`.

## 14. Regression guarantee

PROVEN_OFFLINE: live-proven chain `CALL_INIT -> ACK -> CAP 0x27 -> ALERTING -> peer CAP -> peer ACK -> OPEN -> RTP/H264` is unchanged outside R58 blocks. The test asserts byte-identical preservation of `R54_INVITE_ACK_SENT`, `R54_LOCAL_CAPABILITIES_SENT`, `R54_LOCAL_ALERTING_SENT`, `R54_PEER_DATA_ACK_FLUSHED`, `R42_MEDIAREQ26_OPEN_PROFILE=CAPTURE_VALIDATED`, and R56 trio ordering markers.

## 15. Provenance (orchestrator-filled after the DEV round)

PROVEN_OFFLINE:

```
CORRECTED_GENERATED_SOURCE_SHA256=e1c82a988d52449121524d32f25af2e648806c73cf4aa29f68dda428f1d2922a
CORRECTED_GENERATED_SOURCE_DETERMINISTIC=true
GENERATED_LINES=10016
R57_BASELINE_SOURCE_SHA256=fbd6137a5bb8b0f7258bfe69d72481c70272645aae0d4c0f0dff8c66d0b2237c
SOURCE_SHA256=5827d9fd043b85fc0c59a31661a1a125c6b239771e2a70c3e5afdd95f1a03c73
BUILD_RC=0
BUILD_WARNINGS_TOTAL=3
BUILD_WARNINGS_NEW=0
CORRECTED_BINARY_SHA256=40c8a2c19fe5e792c28082ee0b1f60732cd90b5ffaa1cdb05c82575361cef762
CORRECTED_BINARY_DETERMINISTIC=true
BINARY_PROMOTED=false
BUILD_MUSL=RUN_BY_ORCHESTRATOR
DEPLOYMENT=NOT_RUN
LIVE_CANARY=NOT_RUN
```

Orchestrator build evidence (two independent offline `--network none` Alpine 3.24.1 gcc 15.2.0
containers, one canonical compile-input filename, cached apk closure):
`BUILD_A_SHA256 == BUILD_B_SHA256`, `MUSL_INTERPRETER_GATE=PASS`
(`/lib/ld-musl-x86_64.so.1`), `NEEDED=libc.musl-x86_64.so.1,libglib-2.0.so.0,libgobject-2.0.so.0,libnice.so.10`
(unchanged — `NO_NEW_RUNTIME_DEPENDENCY=PASS`), `NO_GLIBC_DEPENDENCY=PASS`. The three warnings are exactly
the R57 baseline set (`R35_SECOND_OPEN_FORBIDDEN_STATES`, `p116_print_final_rtp_summary`,
`pseudotcp_success_quit_cb`).

Orchestrator fixups applied on top of the DEV round (both proven by the real musl build and the
whole-translation-unit gate, not by region-only harness tests):

1. **Declaration order (build-blocking).** The DEV output used `r58_stop_request()` from
   `r37_handle_remote_release()`/`r37_bounded_stop_signal_cb()` without a preceding declaration, and its
   first parameter is the R35-region type `R35AttachedMediaSession` (which does not exist at the early
   `_R58_DECLS` anchor). The whole-TU gate reproduced the failure
   (`implicit declaration of function 'r58_stop_request'` at the first call site, then `conflicting types
   for 'r58_stop_request'` at the definition) — the same class R57 hit. A prototype block is now emitted
   inside the R37 region immediately before `#define R37_OP_RELEASE`, with
   `R58_PROTOTYPE_ORDER_GATE`/`R58_PROTOTYPE_CALLSITE_GATE` assertions. Region-only harness tests cannot
   catch this class; the whole-TU gate now can.
2. **Warning gate (`BUILD_WARNINGS_NEW=0`).** The first orchestrator-corrected candidate produced two new
   warnings: `'r37_bounded_stop_request' defined but not used [-Wunused-function]` and
   `unused parameter 'form' [-Wunused-parameter]`. The R37 synchronous stop-request forwarder is now
   retired in the generator (replaced by an explicit
   `R58_RETIRED_R37_SYNCHRONOUS_STOP_REQUEST_BEGIN/END` comment block, asserted by
   `R58_R37_RETIREMENT_GATE` + `R58_R37_CAPABILITY_CLEARED_PATH_GATE`), because leaving the duplicate
   synchronous write path compiled in would contradict "one owner"; a `-Wno-unused-function` suppression
   was rejected for that reason. `r37_stop_and_dispose()` remains unchanged and is still reached by
   `r37_handle_capability_cleared()`. `(void)form;` was added to the patched remote-RELEASE body.

## 16. Sanitisation

PROVEN_STATIC: this record contains no raw frames, payloads, tokens, addresses, CTP ids, PCAP data, or physical Door/Gate success claims.
