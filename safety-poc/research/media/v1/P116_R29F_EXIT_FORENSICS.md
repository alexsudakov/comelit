# P116 R29F Exit Forensics

Evidence is from `/tmp/r29f-evidence/r29f-bundle` only. No opaque identifiers,
addresses, credentials, or payload bodies are reproduced here.

## Conclusion

`REGISTERED_CTPP_OPEN_EVIDENCE=INCONCLUSIVE_TOOLING_FAILURE`.

The candidate reached registered listener ready, observed an entrance
`CALL_INIT`, queued exactly one registered-CTPP mediareq26 OPEN, then exited by
its own inherited entrance-signaling timeout path before the runner could send
the planned SIGUSR2 STOP. The final candidate health markers still reported ICE
ready and PseudoTCP open, and no peer reject/close marker was emitted.

## Cited Evidence

- Candidate ready and transport established:
  `/tmp/r29f-evidence/r29f-bundle/runmedia/ice-holder.log:241-249`.
- Entrance `CALL_INIT` observed, no door/gate action:
  `/tmp/r29f-evidence/r29f-bundle/runmedia/ice-holder.log:332-344`.
- OPEN queued once and candidate moved to `OPEN_SENT_OBSERVING_RTP`:
  `/tmp/r29f-evidence/r29f-bundle/runmedia/ice-holder.log:345-419`.
- Candidate then hit local signaling timeout at stage 1:
  `/tmp/r29f-evidence/r29f-bundle/runmedia/ice-holder.log:421-426`.
- Final candidate transport markers were still healthy:
  `/tmp/r29f-evidence/r29f-bundle/runmedia/ice-holder.log:427-433`.
- Final RTP counters were zero:
  `/tmp/r29f-evidence/r29f-bundle/runmedia/ice-holder.log:434-571`.
- Wrapper observed candidate return code 6 before wrapper result gates:
  `/tmp/r29f-evidence/r29f-bundle/run/wrapper.log:101-103`.
- The wrapper's later `P2_VIP_UAUT_OPEN=FAIL` is in the final wrapper gate
  block, after the candidate final log copy:
  `/tmp/r29f-evidence/r29f-bundle/run/wrapper.log:573-584`.
- Runner read sink counters before finalizing sink processes:
  `/tmp/r29f-evidence/r29f-bundle/run/runner.sh:1103-1108`,
  while the sink writes its count on exit:
  `/tmp/r29f-evidence/r29f-bundle/run/runner.sh:497-505`.
- Runner only sends STOP if the candidate PID is alive:
  `/tmp/r29f-evidence/r29f-bundle/run/runner.sh:1142-1147`;
  live output recorded `STOP_SENT=false`:
  `/tmp/r29f-evidence/r29f-bundle/r29c-live-console.log:216-218`.

## Source Path

Generated candidate source before this fix:
`entrance_signal_timeout_cb()` set `failed = TRUE` and quit the main loop when
`entrance_signal_stage != ENTRANCE_SIGNAL_DONE`; main then returned
`failed ? 6 : 0`.

Source anchors:

- `safety-poc/research/media/v1/entrance_self_activation_signaling_transform.py:353-370`
- generated `/tmp/r29c-before.c:3701-3718`
- generated `/tmp/r29c-before.c:8781-8783`
