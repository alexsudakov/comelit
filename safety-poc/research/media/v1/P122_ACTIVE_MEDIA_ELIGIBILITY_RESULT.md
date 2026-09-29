# P122 Active Media Eligibility Corrective Result

## Root Cause

The P122 on-demand media Door eligibility gate still required
`entrance_signal_stage == ENTRANCE_SIGNAL_OBSERVE_MEDIA`.

The shipped P85 media lifecycle changes the successful active-media transition
to:

```c
entrance_signal_stage = ENTRANCE_SIGNAL_DONE;
entrance_signaling_result = TRUE;
p80_media_forwarding_enabled = TRUE;
```

at the same point where `P80_MEDIA_ACTIVE=true` is emitted. That made a normal
production on-demand active-media session fail P122 Door eligibility as
`REJECTED_NOT_READY`.

## Predicate Change

Before:

```c
entrance_signal_stage == ENTRANCE_SIGNAL_OBSERVE_MEDIA
```

After:

```c
entrance_signal_stage != ENTRANCE_SIGNAL_DONE
```

inside the ordered fail-closed gate evaluator. P122 is inserted before the
generated declaration of `entrance_signaling_result`, so the in-scope production
predicate is the P85 active-media stage `ENTRANCE_SIGNAL_DONE`. The generated
lineage test verifies that P85 sets `entrance_signaling_result = TRUE` in the
same active-media transition.

No P85 transform, media lifecycle weakening, Gate path, R66 persistent-listener
path, or call-time single-message profile was changed.

## Reject Gate Mapping

`P122_ONDEMAND_DOOR_REJECT_GATE=<SAFE_ENUM>` is emitted only on the reject path.
The enum is selected by the same ordered gate evaluator used by the accept
check:

- `SIGNAL_STAGE`: `entrance_signal_stage != ENTRANCE_SIGNAL_DONE`
- `MEDIA_FORWARDING`: `!p80_media_forwarding_enabled`
- `RTPC_STAGE`: `p78_rtpc_stage != P78_RTPC_COMPLETE`
- `PSEUDOTCP`: `!pseudo_tcp || !pseudotcp_open`
- `GRACEFUL_STOP`: `pseudotcp_graceful_stop_started`
- `CTPP`: `v4_ctpp_channel_id == 0u`
- `TX_PENDING`: `p12_tx_pending`
- `REFRESH_OUTSTANDING`: `r27_repeat_outstanding`
- `REFRESH_FAIL_CLOSED`: `r27_refresh_fail_closed`
- `INITIAL_001A`: `r27_initial_001a_sent_count != 1u`
- `DOOR_INFLIGHT`: `p122_door_inflight`
- `DOOR_ALREADY_SENT`: `p122_door_sent`

The marker value is a compile-time literal from this enum mapping. No raw
protocol bytes, addresses, channel ids, tokens, SDP, or payload are printed.

## Generated Source

Generated P122 source SHA256:

```text
fa5f3fef61b6673718d677e150770c2af6fe2c752d0756034c9ad5e1864a384c
```

## Native Rebuild And Promotion

Promoted native binary SHA256:

```text
5811415a95bbeb687e7f91d5a1ed70c67473086ddefa4bfb602eba2798ad0573
```

Size: 311360 bytes.

Hermes ran independent CT120 canonical builds A and B at
`82efeeb96f6b56a374ffc60e9933c79a8a4ac31f` with `P80_BUILD_PROFILE=P122`,
`P80_BUILD_INCLUDE_P116=1`, and the P122 on-demand media Door transform. Build A
and build B produced the same binary SHA256 above, and the binary comparison
gate passed.

Generated source SHA256 remained:

```text
fa5f3fef61b6673718d677e150770c2af6fe2c752d0756034c9ad5e1864a384c
```

Superseded native/source pair:

```text
a3c95f3ec8c5c00963946c8ff550760fadd792a314bb72692e4281da35a5a6a5
fd375a37e427e680db60984f6d74807e56892a1a042a168032a6dfa42411eff5
```

Profile source gate and profile binary gate both passed for P122. The earlier
candidate build with the same binary bytes was blocked only by the stale legacy
marker gate.

## Test Results

Focused corrective module:

```text
Ran 8 tests in 0.619s
OK
```

Existing P122 module:

```text
Ran 8 tests in 0.115s
OK
```

Full-suite and static verification results are recorded in the final execution
report for this corrective.

## Execution Boundary

No live Home Assistant deploy, restart, reload, camera test, Comelit network
experiment, Door action, Gate action, native binary rebuild, or protocol write
outside the offline host harness was performed.
