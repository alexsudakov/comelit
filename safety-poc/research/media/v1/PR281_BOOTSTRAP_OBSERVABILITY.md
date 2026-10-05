# PR281 Bootstrap Observability

## Scope

This round is instrumentation only.

`BEHAVIOR_CHANGED=false`
`BOOTSTRAP_ALGORITHM_CHANGED=false`
`HA_17999_ARCHITECTURE_CHANGED=false`

The activation algorithm remains unchanged: a sink that is known and inactive is activated even when the bootstrap cache is empty. The decision path still finds the matching sink, snapshots the cache, installs the activation queue, sends the snapshot packets if any, pops the queue, sets `sink.active = True`, replays queued live packets, and returns `True`. The new code only reads cache diagnostics and emits bounded log records around those existing steps. It does not add gates, waits, retries, replay attempts, timers, or teardown changes.

## Marker Catalogue

All Python RTP/bootstrap markers are emitted through `custom_components.comelit.h264_recovery`.

`output_sink_activation`

- `port`: sink UDP port.
- `bootstrap_packets`: current bootstrap snapshot packet count.
- `bootstrap_bytes`: current bootstrap snapshot byte count.
- `bootstrap_has_sps`: whether the cache has SPS.
- `bootstrap_has_pps`: whether the cache has PPS.
- `bootstrap_has_complete_idr`: whether the cache has a marker-completed IDR access unit.
- `bootstrap_idr_packets`: packet count in the cached IDR access unit.
- `bootstrap_age_ms`: monotonic age of the completed IDR access unit at query time, or `NA`.
- `queued_live_packets`: queued live packets at activation record time.
- `activation_result`: `activated`, `already_active`, or `unknown_port`.

`output_sink_bootstrap_sent`

- `port`: sink UDP port.
- `attempted_packets`: bootstrap packets attempted.
- `sent_packets`: packets accepted by `sendto`.
- `send_errors`: send exceptions caught while sending bootstrap.

`shim_first_rtp`, `shim_first_sps_cached`, `shim_first_pps_cached`, `shim_first_idr_start_seen`, `shim_first_complete_idr_cached`

- `at`: wall-clock UTC ISO 8601 timestamp.
- `ssrc`: RTP SSRC.
- `sequence`: RTP sequence number.
- `bytes`: RTP packet bytes, or complete-IDR access-unit bytes for `shim_first_complete_idr_cached`.

`input_rtp_summary`

- `input_rtp_packets`: upstream RTP datagrams accepted by the shim protocol.
- `first_rtp_at`: first upstream RTP wall-clock UTC ISO 8601 timestamp, or `NA`.
- `last_rtp_at`: last upstream RTP wall-clock UTC ISO 8601 timestamp, or `NA`.
- `input_rtp_duration_ms`: monotonic duration between first and last upstream RTP datagram.

`ha_stream_created`

- `stream_label`: HA Stream label (`comelit_attached` or `comelit_miniapp_attached` for attached media).
- `source_basename`: SDP source basename only, never the full source path or URL.

Mini App client diagnostics add these closed-schema events through the existing `/diagnostics` channel:

- `hls_manifest_request`
- `hls_manifest`
- `hls_level_loaded`
- `hls_frag_loaded`
- `hls_frag_buffered`
- `hls_buffer_appended`
- `hls_first_frame`

Their media-state counters are bounded integers: `ready_state`, `current_time_ms`, `duration_ms`, `buffered_count`, `buffered_start_ms`, `buffered_end_ms`, `video_width`, `video_height`, `total_video_frames`, and `dropped_video_frames` when available. Existing `elapsed_ms` and `stage_ms` remain in the diagnostics envelope.

## Design Notes

The bootstrap cache now has a read-only diagnostics accessor. It reports SPS/PPS presence, snapshot counts and bytes, cached IDR access-unit counts and bytes, IDR SSRC/timestamp, first/last RTP sequence, and completed-IDR age. The only new retained metadata is RTP header metadata and the monotonic completion instant for the already-cached IDR access unit.

Diagnostics are fail-safe. Logging uses wrapped helpers, and activation/cache diagnostic reads have a safe fallback so diagnostic exceptions do not propagate into media control flow or change return values.

No RTP payload bytes are logged. Records contain counts, byte lengths, ports, SSRC, sequence numbers, timestamps, and bounded enums.

Steady-state per-packet diagnostic cost is O(1). The expensive bootstrap diagnostics path that snapshots the cache runs only while `not self._first_complete_idr_logged`; after `shim_first_complete_idr_cached` has emitted, packet handling keeps only O(1) input timestamp/count bookkeeping and bounded first-milestone flag checks. `_log_cache_milestones()` also returns before NAL parsing once SPS, PPS, and IDR-start milestones have all been logged.

HLS browser milestones are guarded by a per-session `hlsMilestones` set. Repeated Hls.js fragment or buffer events emit at most one record per milestone, and the existing 250 ms client-side batching path remains unchanged.

The ring/camera attached provider now passes `stream_label="comelit_attached"` explicitly. The Mini App attached provider continues to use `stream_label="comelit_miniapp_attached"` and `attached-miniapp-rtp.sdp`; the ring/camera path uses `attached-local-rtp.sdp`.

## Test Inventory

Added offline coverage in `tests/miniapp/test_h264_recovery.py`:

- Empty-cache activation logs `bootstrap_packets=0`, false SPS/PPS/complete-IDR flags, and still activates.
- STAP-A SPS+PPS plus complete FU-A IDR reports SPS/PPS/complete-IDR and snapshot packet count.
- Incomplete FU-A IDR without marker reports `complete_idr=false`.
- Activating the same port twice emits only one bootstrap-send record.
- 17999 and 18099 activation markers are distinguishable by `port=`.

Existing miniapp diagnostics tests cover the expanded closed event schema and the mirrored client/server counter cap.

## Activation Semantics Evidence

The activation branch remains the same behavioral sequence. The only additions are:

- reading `_bootstrap_diagnostics_safe()` before logging;
- `_log_activation(...)` before the existing bootstrap-send loop;
- send counters around the existing `sendto(packet)` calls;
- `_log_bootstrap_sent(...)` after the existing activation queue pop;
- logging for the already-active and unknown-port returns without changing those return values.

No condition was added that requires a non-empty bootstrap before activation. Test `test_empty_cache_activation_diagnostics_record_current_behavior` records the current behavior: `bootstrap_packets=0` and `activation_result=activated`, with `activate_output_port(18099) is True`.
