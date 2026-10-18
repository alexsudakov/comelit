# R61 observability contract corrective

Status: implementation contract. `HIGH_A2=OPEN`; `HIGH_3=REFRAMED`.

## Post-stop attribution

Post-stop attribution requires positive native ordering evidence in the same
bounded generation tail: `R58_STOP_CLOSED=true` and/or
`R42_MEDIA_CHANNEL_CLOSED=true` must precede the first native failure marker.
The close and failure must also occur within the bounded 10-second terminal
evidence window; an old close left by a completed call while the listener is
idle cannot classify a later process failure.
Only then does the captured evidence include bounded `R61_NATIVE_EXIT_CONTEXT`
and `R61_NATIVE_EXIT_CLASSIFICATION=POST_STOP_NATIVE_FAILURE` markers. A Python
pause request alone is not evidence, and a failure observed before close is
left unclassified. The native verdict is preserved verbatim: an exit 6 remains exit 6,
`P116_NATIVE_EXIT_INTENTIONAL_STOP=false` remains false, and the native failure
ID/count remain visible. The R61 marker records ordering and stop context only;
it does not claim that the pause caused the exit or convert a concurrent
transport failure into an intentional success. A failure already observed
before the pause request receives no pause-context marker. The marker is reset
with the native generation and uses the same bounded terminal logging path.

## Receive freshness

`VIDEO_RX_STALLED` / `video_rx_stalled` is a current-state boolean for the current call generation's
attached **video** receive channel. Python derives it at each native refresh
tick by comparing the new `VIDEO_PACKET_COUNT_AT_REPEAT` with the preceding
tick. The first count establishes a baseline; an unchanged/decreasing count is
stalled, and an advancing count clears the flag immediately. The native
native `RX_STALLED=true` line is retained only as `RX_STALLED_RAW` /
`rx_stalled_raw` because its producer emits no
false line and combines video and audio with OR; an absent audio stream must
not mark progressing attached video as stalled. This is diagnostic only and
does not change RTP or call lifecycle policy.

`RTP_STALL_SECONDS_RAW` / `rtp_stall_seconds_raw` is the producer's integer sample, not wall time or a
cumulative per-call counter. At a refresh tick the producer subtracts its
chosen stalled-since monotonic millisecond value (last stalled video/audio
packet when available, otherwise the preceding refresh tick) from the current
refresh time and truncates to seconds. Python retains that sample only while
the video-counter comparison says video is stalled; video progress clears it
to zero. `LAST_*_RTP_MONOTONIC_MS` uses the same native monotonic clock. All
values are bound to `R42_CALL_GENERATION` and published only in that
generation's media diagnostics snapshot as `video_rtp_stall_seconds` only
while the adjacent video-counter comparison proves a video stall.

## Logging and terminal evidence

High-rate protected diagnostic logs have both a four-event per-key ceiling and
a 96-event aggregate ceiling per generation. Retained marker tails remain
separately bounded, and terminal lifecycle/failure markers continue through
the ordinary de-duplicated terminal path. Values pass fixed scalar or enum
allowlists; raw packet or payload data is never published. Thus a 600-second
session cannot produce HA's 200-message per-module interval from this canary
surface even if every 15-second sample changes.

## Stop-completed fields

At `ring_media_stop_completed`, `viewer_count=UNPROVABLE`: the ring-media
coordinator does not own the Mini App viewer registry and must not fabricate a
count. `elapsed_ms` is request-to-completion latency measured with Python's
monotonic clock. It is `0` when there was no explicit stop request, including
the unchanged 600-second `hard_limit` path; it is not session duration.

## Call state and attached media

The repository proves two separate bounded state machines. `call_state` is a
signalling projection with a 120-second evidence timeout; attached media owns
its receive/fanout lifecycle and retains the independent 600-second ceiling.
There is `NO_EVIDENCE` that `call_state=error` is intended to terminate an
already attached media generation. Accordingly R61 changes no product state or
media lifecycle behaviour. Follow-up: decide that product relationship before
adding any coupling.

## Open decisions

`HIGH_A2=OPEN`: same-call owner handoff remains unproven.

`HIGH_3=REFRAMED`: repository evidence does not establish that a fresh native
identity sample will exist at the later 120-second boundary, so requiring one
there is not currently verifiable. The safety requirement remains fail-closed:
for each observed same-call retransmission, suppress it only when its native
identity matches the live call and owner generation; otherwise record
`HIGH_3` unresolved and perform no automatic handoff/replay. Verification
requires a bounded trace containing the initial frame and every observed
retransmission, with identical call identity, suppression decisions, and zero
unproven owner transitions. Absence of a later frame is not identity proof.
