# P116 R29I Pre-open Idle And Sink Ownership Hardening

Status: research/offline hardening only. No live authorization is implied.

## Trigger

The previous live attempt completed a clean production handoff and brought the
research listener to READY, but the candidate then exited before any `CALL_INIT`
because the inherited `ENTRANCE_SIGNALING_TIMEOUT` still owned the pre-OPEN
main-loop lifetime. The physical ring prompt therefore outlived the candidate.
The same run also exposed a second evidence defect: UDP sinks reported started
and finalized while their final count files were absent/UNKNOWN.

## R29I changes

1. In the research candidate only, an inherited entrance signaling timeout is
   treated as an idle/stale timeout while the persistent research listener is
   already READY, no `CALL_INIT` transaction has been created, and no media OPEN
   has been sent. The listener remains alive for the outer bounded human-ring
   window. Suppression ends at `CALL_INIT`: a pre-OPEN signaling timeout during
   an actual call transaction remains fail-closed. PseudoTCP/registration and
   other transport failures also remain fail-closed, and the runner retains
   bounded CALL_INIT/OPEN deadlines.
2. UDP sinks are no longer started through command substitution. They are direct
   children of the runner, are terminated and joined deterministically, and
   atomically materialize final counters even when the count is zero. Missing or
   non-numeric final counters after join are a tooling failure, not zero and not
   a protocol observation.
3. Ring evidence is separated into prompt-issued, user-reported physical action,
   and observed CALL_INIT. The runner can prove the first and third only; the
   second remains orchestration/user evidence.

## Safety invariants

- No live run in R29I offline hardening.
- No Comelit network TX in tests/models.
- Mediareq26 OPEN/STOP payload/profile/binding semantics are unchanged.
- At most one OPEN and one STOP remain the inherited R29C contract.
- No self-activation, R27 repeat/refresh, Door or Gate action is introduced.
- Production Home Assistant files are not changed.

## Offline acceptance

- READY listener survives modeled 30 s and 90 s pre-ring idle windows.
- CALL_INIT after long idle can still reach the single-OPEN-capable state.
- A CALL_INIT-created transaction still fails closed on a pre-OPEN signaling timeout.
- Explicit transport/registration failures remain fail-closed.
- Generated candidate contains the READY/no-CALL_INIT/no-OPEN timeout ownership guard.
- Generated runner launches sinks as direct children and joins them before
  reading counters.
- Real subprocess tests prove zero- and nonzero-datagram final counter
  materialization after process join.
- Generated runner passes `bash -n`; new Python files pass `py_compile`.

The media-open and media-only-teardown models remain BLOCKED until a separately
authorized live experiment supplies protocol evidence.
