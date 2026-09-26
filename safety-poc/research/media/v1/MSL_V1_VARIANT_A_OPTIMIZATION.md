# MSL V1 Variant A Cold-Start Optimization

## Scope

Variant A keeps the current architecture:

listener pause -> one separate `comelit-media` helper -> one cloud P2P negotiation -> RTP -> HA Stream/HLS.

It is selected only with `MSL_VARIANT_A=YES` in
`ct120_run_msl_v1_baseline_live.sh`. `MSL_VARIANT_A=NO` keeps the baseline
wrapper materialization branch and emits `MSL_A_ENABLED=false`.

## Optimization

`ct120_run_msl_v1_baseline_live.sh` materializes the CT120 cloud wrapper with a
Variant A branch that removes a serial pre-cloud diagnostic log dump from the
critical path. The baseline wrapper starts the helper, waits for `offer.sdp`,
prints `=== ICE OFFER HOLDER ===`, cats the helper log, then transforms SDP and
starts the cloud P2P request. That `cat "$RUN/ice-holder.log"` is diagnostic
I/O only; the existing wrapper already waits for the helper later and prints
`=== ICE HOLDER FINAL LOG ===` from the same file after the media attempt.

Variant A therefore keeps the same ordering constraints:

- `offer.sdp` must exist before SDP transform.
- SDP transform must pass before the single cloud P2P request.
- remote SDP is written once for the already-running helper.
- no retry, no second helper/session, no Door/Gate path.

It also starts the existing OAuth status helper in parallel with helper ICE
gathering when that helper exists. This is a readiness preflight only; it does
not create protocol state and does not replace the existing single cloud P2P
request.

## Attribution Markers

The runner-generated wrapper emits:

- `MSL_T06_CLOUD_P2P_REQUEST_START_MONO_MS`
- `MSL_T07_CLOUD_P2P_RESPONSE_REMOTE_SDP_WRITTEN_MONO_MS`

These split the previous `T04 -> T08` window into:

- helper local offer ready -> cloud request start
- cloud request start -> remote SDP written
- remote SDP written -> helper ICE connected

The C transform documents that T06/T07 are wrapper-emitted rather than helper
emitted.

## Expected Effect

The provable saving is the elapsed time spent printing the initial helper log
between offer readiness and cloud request start. That work is independent of
the cloud request because it reads only `ice-holder.log`; it does not produce
`offer-comelit.sdp`, credentials, the HTTP request body, or `remote.sdp`.

The 5088 ms `T11 -> T12` interval was not changed. Static source inspection
shows it crosses ordered media signaling gates, including the P95 device-0002
gate and RTPC/client ACK ordering. No fixed settle timer in the allowed MSL
instrumentation transform can be removed without changing the R65/P95/P97
generation chain, which is outside Variant A's write scope.
