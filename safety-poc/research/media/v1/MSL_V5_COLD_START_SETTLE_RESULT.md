# MSL-V5 — cold-start entrance settle: the parameter is measurable, the live hypothesis is blocked before the settle

TASK_ID=`COMELIT-MSL-V5-COLD-START-SETTLE-OPTIMIZATION`
BRANCH=`research/media-startup-settle-v5`
BASE_HEAD=`c1f69d3ccdbe3b37aca63263970a99838909a8fa` (origin/main, R65 lineage already merged)
FINAL_HEAD=`761a4f6402a63b02ab57e04c44b86ddf63a87d70`

V1/V2/V3/V4 result documents are untouched. No production code, entity or configuration changed.

## 1. Verdict

```text
RESULT=SETTLE_REDUCTION_BLOCKED
BLOCKER=PRE_SIGNALING_ICE_STALL  (two identical live runs stalled before CTPP registration)
MINIMUM_PROVEN_SETTLE_MS=NONE
SELECTED_SETTLE_MS=NONE
V5_MEDIA_ATTEMPTS_USED=2/5   (3 further slots deliberately unused; no brute force)
CLI_INVOCATIONS_USED=1/1
```

The round delivered a reproducible, fail-closed way to change exactly one constant and to measure it against
the V1 baseline. It did **not** obtain a settle verdict, because the cold-start helper never reached the point
where the settle applies.

## 2. PHASE 0 — the parameter is real (mechanically proven)

Regenerating the current R65 candidate from `safety-poc/research/door/v1_5_7/comelit-v4-persistent-ctpp-door.c`:

```text
GENERATED_SHA256=4fc6188c6231b94682205973b6a6f628ca005e8b7c3a04efbd8056c5a608c58c  (9980 lines)
#define ENTRANCE_SIGNAL_SETTLE_MS occurrences: exactly 1, value 4000
g_timeout_add(ENTRANCE_SIGNAL_SETTLE_MS, entrance_signal_start_cb, NULL) occurrences: exactly 1
no later overlay overrides the value
R65_SETTLE_PRESENT=true / R65_SETTLE_MS=4000 / LATER_OVERLAY_OVERRIDES_SETTLE=false
```

## 3. The overlay (one CLI invocation, codex-cli)

`safety-poc/research/media/v1/entrance_p116_r66_startup_settle_transform.py` composes R65 and replaces the
single settle constant, fail-closed on zero or more than one anchor, for
`safety-poc/research/media/v1/entrance_msl_v5_settle_instrumentation_transform.py`
(R66 + the V1 `MSL_T00..T18` stage markers, same names and reference, so numbers stay comparable to the
9193/9973 ms baseline). Candidates and their *instrumented* generated-source SHAs (the composition the CT120
builder actually uses):

```text
settle  4000 ms  3c7798c8312da964dc6e9d57113504130a8702475adc2ef8fa3448310375bcab   == V1 baseline instrumentation source
settle  2000 ms  d9d5a469de3b451f3faa6b7575de5b5c7f08ee1daafe66f5c5939f1e77a890e3
settle  1000 ms  65e51666dd15a84cc74eb5f2ef8e3bdae09ad76d9cdd2abec9eca257e414783d
settle   500 ms  f348e6d75a5b5505a3292b91d6da0dd820c168a811d3e1053635516ea93dfdef
settle     0 ms  091c1f832d4b899436d65e20c1036695484b8c2b2a3826e42d136bfbcff3b628
```

Equality and isolation proofs: `R66_TRANSFORM(settle=4000) == R65` byte-identical; the 4000 ms instrumented
composition is byte-identical to the V1 baseline instrumentation source; each candidate differs from the
4000 ms output only in the settle constant and the V5 markers. Whole-TU compile gate PASS, host suite
`Ran 2247 tests / OK (skipped=1)`, offline safety PASS, `custom_components/**` diff empty. The single CLI child
reported `BLOCKED` only because its sandbox denies UDP socket creation (3 UDP-sink tests); the same suite
passes on the host, which is the recorded result.

## 4. Live attempts

```text
v5-01..v5-03  pre-live harness aborts of the orchestrator wiring (missing MSL_LIVE_RUN, missing
              MSL_ATTEMPT_LEDGER, then a wrong pre-computed expected generated SHA).
              LIVE_INVOCATIONS=0, MSL_RUN_CLASSIFICATION=NOT_RUN, no Comelit/panel interaction,
              Door/Gate=0, production listener READY afterwards, no residuals.
              The operator authorized +3 slots so these do not consume the live budget.

v5-04  settle=1000  LIVE 1  FAIL before signaling
v5-05  settle=1000  LIVE 2  FAIL before signaling (identical)
```

Both live runs:

```text
build PASS: P80_CHROOT_BUILD_RC=0, generated SHA matched the pre-computed value, binary 208e0533...
cloud  PASS: P2P_RESULT=SUCCESS, remote SDP written, credentials PASS
helper stages: MSL_T03 helper start, MSL_T04 local SDP offer ready, V5_SETTLE_CONFIGURED_MS=1000
              then nothing more - no ICE_CONNECTED, no CTPP registration, no settle/signaling markers,
              no V5_*_US markers, no RTPC stage
wrapper killed by the harness bound: WRAPPER_RC=124 (85 s outer timeout)
independent UDP sinks counted real RTP on the helper's ports: video 4123 / 3797, audio 3957 / 3926
```

Because `ENTRANCE_SIGNAL_SETTLE_MS` is armed only *after* fresh CTPP registration, and CTPP registration
happens *after* ICE connectivity, both failures occurred strictly before the parameter under test could have
any effect. The first boundary is therefore

```text
FIRST_BOUNDARY=PRE_SIGNALING_ICE_STALL (class: OTHER_EXACT, before SETTLE_TOO_SHORT_BEFORE_0028)
```

The panel-side RTP reaching the helper's RTP ports while the helper's own ICE/CTPP path never reported
progress is recorded as an observation, not as a pass: none of the required pass criteria
(`SELF_ACTIVATION_0028_ACK`, `CLIENT_0008_ACK`, `DEVICE_0008_OBSERVED`, `DEVICE_0002_OBSERVED`,
`RTPC_CONTROL_COMPLETE`, `DEVICE_ACK_001A_OBSERVED`, first video RTP marker, decodable video marker) could be
verified, and the helper never emitted a first-RTP marker of its own.

The harness bound cannot be widened to compensate: `MAX_BASELINE_OUTER_TIMEOUT_SECONDS=90` is enforced
(`MEDIA_STARTUP_OUTER_TIMEOUT_GATE`), so the setup observation window can move from 85 s to at most 90 s,
which is not a meaningful extension. A third identical run was deliberately not attempted.

## 5. Safety

```text
DOOR_ACTIONS=0 / GATE_ACTIONS=0 / PHYSICAL_RING_ACTIONS=0 / AUTOMATIC_PROTOCOL_RETRY=false
SECOND_MEDIA_SESSION=false
every live run: LISTENER_READY_BEFORE=true, LISTENER_READY_AFTER=true, LISTENER_RESTORE_OK=true,
MEDIA_TEARDOWN=CONFIRMED, CAMPAIGN_PROCESSES_REMAINING=NONE, RTP_SINK_PORTS_REMAINING=0,
production listener restored to READY, CALL_STATE=idle, RECONNECT_COUNT_DELTA=NOT_REACHED
HA_RESTART_USED=false / PRODUCTION_DEPLOYED=false / custom_components/** unchanged
```

## 6. What is reusable, and the next boundary

Reusable: a proven single-constant settle overlay with fail-closed anchors, deterministic candidate hashes, a
V5 runner that keeps every baseline safety property, and a dry-run path that validates the whole wiring without
touching the panel (all ten V5 markers verified synthetically).

Open: why the cold-start helper no longer completes ICE within the harness bound. Until that is understood, no
settle value can be validated live, and reducing the settle further is not justified by any evidence this round
produced. This needs its own bounded investigation (setup/ICE observability) rather than more settle runs.
