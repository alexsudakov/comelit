# P116 R29H Lifetime And Evidence Hardening

R29G root cause: after accepted Entrance `CALL_INIT` and one registered-CTPP
mediareq26 `OPEN`, the inherited entrance signaling watchdog still owned the
main loop. It fired at `ENTRANCE_SIGNALING_TIMEOUT STAGE=1`, set `failed`, quit
the loop, and exited before the observation timer could mark completion or the
runner could send `STOP`.

Exit and main-loop ownership after accepted Entrance `CALL_INIT`:

| Path | Interval | Classification | R29H handling |
| --- | --- | --- | --- |
| Entrance signaling timeout before `CALL_INIT` | pre-call | `ALLOWED_BEFORE_OPEN` | fail closed |
| Entrance signaling timeout after `CALL_INIT` but before real `OPEN` completion | pre-open | `ALLOWED_BEFORE_OPEN` | fail closed |
| Entrance signaling timeout after real `OPEN` and before observation end | observation | `MUST_BE_SUPPRESSED_OR_DEFERRED` | defer, emit `R29H_INHERITED_MAIN_LOOP_QUIT_DEFERRED=true`, keep bounded section alive |
| Entrance signaling timeout after observation end but before `STOP` | waiting-for-stop | `MUST_BE_SUPPRESSED_OR_DEFERRED` | defer until single `STOP` path owns cleanup |
| Entrance signaling settle/start failure before `OPEN` | pre-open | `ALLOWED_BEFORE_OPEN` | fail closed |
| Fatal RTP forwarding socket/profile/send failure after `OPEN` | observation | `ALLOWED_DURING_OBSERVATION` external hard failure | classify as hard failure and attempt the single `STOP` cleanup when transport remains usable |
| PseudoTCP notify/close failure before `OPEN` | pre-open | `ALLOWED_BEFORE_OPEN` | fail closed |
| PseudoTCP notify/close failure after `OPEN` | observation or waiting-for-stop | `ALLOWED_DURING_OBSERVATION` external hard failure | classify explicitly and attempt single `STOP` if possible |
| Holder shim launch/provenance/runtime failure | before candidate ready/open | `ALLOWED_BEFORE_OPEN` | runner fail closed, no live PASS |
| Holder shim termination after `OPEN` before `STOP` | observation or waiting-for-stop | `ALLOWED_DURING_OBSERVATION` external hard failure | runner reports liveness from measurement and blocks PASS on contradiction |
| Inherited absolute/watchdog timeout before `OPEN` | pre-open | `ALLOWED_BEFORE_OPEN` | fail closed |
| Inherited absolute/watchdog timeout after `OPEN` before `STOP` | bounded section | `MUST_BE_SUPPRESSED_OR_DEFERRED` unless it proves hard process failure | bounded section owns observation and STOP |
| Observation timer callback success | observation end | `ALLOWED_DURING_OBSERVATION` | transition to `R29H_LIFETIME_WAITING_FOR_STOP` |
| Observation timer callback failure | observation | `ALLOWED_DURING_OBSERVATION` external hard failure | classify and attempt single `STOP` |
| SIGUSR2 media-only teardown before `OPEN` | pre-open | `ALLOWED_BEFORE_OPEN` | refuse `STOP` before open |
| SIGUSR2 media-only teardown after full observation | waiting-for-stop | `ALLOWED_AFTER_STOP` once STOP is sent | send exactly one `STOP`, finalize cleanup, controlled exit |
| Second SIGUSR2 or second STOP | any | `MUST_BE_SUPPRESSED_OR_DEFERRED` | refuse duplicate, keep `STOP_MAX_COUNT=1` |
| Final research cleanup after STOP | post-stop | `ALLOWED_AFTER_STOP` | controlled candidate exit |

R29H keeps the inherited fail-closed behavior before real `OPEN`. Once `OPEN`
is real, the candidate owns a bounded section: `OPEN_WRITE_COMPLETED`,
observation, observation finalization, exactly one `STOP`, bounded post-STOP
evidence, and controlled exit. The runner now reports liveness by measurement
at each decision point and treats process/candidate-marker conflicts as
`LIVENESS_EVIDENCE=CONTRADICTION`, which prevents PASS.
