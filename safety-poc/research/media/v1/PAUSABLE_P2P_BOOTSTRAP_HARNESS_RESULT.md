# Pausable P2P Bootstrap Harness Result

TASK_ID=COMELIT-RESEARCH-PAUSABLE-P2P-BOOTSTRAP-HARNESS

## Scope

Additive research-only files were added under `safety-poc/research/media/v1/`
and `safety-poc/tests/`.  No `custom_components/comelit/**` file is modified.
The shipped `custom_components/comelit/native/comelit-media` binary remains
pinned to `83b29ef07be224ffb703a21f50050b1ed5e7eec3e24f185cbfde4c79c111515a`.

## Interlock Contract

The research transform composes the current production generator.  Default
generation is byte-identical to production.  Research generation is opt-in with
`--research` and runtime stage selection is via process environment only:

`RESEARCH_STOP_AFTER_STAGE=6|7|8|9|10|12`, optional
`RESEARCH_HOLD_MS=100..5000`.

`STAGE_11_NOT_SEPARABLE=true`: the reviewed TU has no separable protocol
boundary between CTPP channel setup and CTPP registration.  `P12_TX_V4_CTPP_INIT`
moves directly to `P12_STAGE_V4_WAIT_CTPP_BOOTSTRAP`; the ACK-pair transition is
where `v4_registered`, `v4_listener_ready`, and `V4_CTPP_REGISTRATION=PASS`
become true together.  Stage 11 is emitted only as a pre-register marker, not as
a configurable stop.

## Backend Rollback Research

`BACKEND_RELEASE_ENDPOINT_EXISTS=false`.

Whole-tree and whole-history search found `servicerest/p2p/start` only for the
P2P REST allocation path.  No `/servicerest/p2p/release`, `/stop`, `/end`, or
`/close` endpoint exists in source or history.  Existing `remote_release`
markers in runtime are inbound call-state semantics, not a backend session
release REST call.

`BACKEND_SESSION_EXPLICITLY_RELEASED=false`.

After stage 7/8/9/10/12, helper teardown can prove only local cleanup:
process exit, local file cleanup, PseudoTCP close if opened, libnice agent
disposal by process exit, and CTPP/PseudoTCP socket closure by process exit.
No source evidence proves backend session release-on-transport-close or TTL.

`BACKEND_SESSION_CLEANUP_AFTER_PROCESS_EXIT=NOT_PROVEN`.
`BACKEND_SESSION_TTL=UNKNOWN`.
`BACKEND_SESSION_CLEANUP_SEMANTICS=LOCAL_TRANSPORT_CLOSE_ONLY_PROVEN`.

Live implication: the next live child must not pass stage 7 until the operator
accepts the unresolved backend allocation cleanup risk/TTL.

## Listener Observer Design

`listener_readonly_observer.py` is standalone and read-only.  It samples a
sanitized JSON status snapshot and emits:

`LISTENER_SUPERVISOR_RUNNING`, `LISTENER_READY`, `LISTENER_MEDIA_PAUSED`,
`LISTENER_RECONNECT_COUNT`, `LISTENER_LAST_ERROR`, `LISTENER_PROCESS_PID`,
`LISTENER_SOCKET_IDENTITY`, `LISTENER_SOCKET_PRESENT`,
`LISTENER_CTPP_REGISTERED`, `LISTENER_REGISTRATION_GENERATION`,
`LISTENER_TRANSPORT_ID`, and `LISTENER_CONFLICT_DETECTED`.

Conflict detection compares socket/transport/generation identity against the
ready claim so a stale "ready" state can be distinguished from a displaced old
listener that the supervisor has not noticed.  No production instrumentation was
added in this turn.  If live status cannot materialize socket inode, transport
id, or registration generation from already available diagnostics, a later
read-only production observer may be justified; it must remain sanitized and
control-free.
