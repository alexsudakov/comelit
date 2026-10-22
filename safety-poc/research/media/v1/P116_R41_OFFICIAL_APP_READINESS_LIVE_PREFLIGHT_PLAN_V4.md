# P116 R41 v4 — Official-App Readiness No-Ring Preflight Runner

Status: **DEV implementation only / live execution not authorized**.  Base model:
R40H `f317bc1145b4165db0ef3677ebba777edd6780d1`.

## Safety contract

This is a zero-ring readiness preflight.  Repository presence, merge, and a
successful offline test do not authorize execution.  The public runner refuses
all runtime inputs and work unless the exact one-attempt approval value is
present:

```text
R41_APPROVAL=I_APPROVE_R41_V4_NO_RING_PREFLIGHT_ONCE
```

It exposes only `status`, one `stop`, and one recovery `start`.  It contains no
ring, synthetic-ring, Door/Gate, media, HA reload/restart, firmware, or logcat
clear action.  `ring_budget_available` is hardcoded false.

## Persistent safe evidence

One filtered `adb logcat -v brief -T 1` process starts before pause.  `-T 1`
limits initial backlog only.  The attempt boundary is a host-local cursor in
that uninterrupted process.  The reducer retains only closed-enum registration
transitions and the transport-failure marker; raw lines, timestamps, PIDs,
serials, and device identifiers are neither printed nor persisted.  A lost
reader fails the attempt closed.  Device-controlled input is bounded to 512
bytes per line and 4096 reduced events; either limit fails the attempt closed
instead of retaining unbounded evidence.

## Listener and failsafe lifecycle

The runner requires two READY samples, confirms a detached failsafe handshake,
then issues exactly one `stop`.  An ambiguous response is treated as possibly
accepted and therefore requires restoration.  The safe-event cursor is
captured only after two PAUSED samples, so an event racing with `stop` is
conservatively stale and can never become false fresh evidence.

The internal `--_failsafe-child` cannot be invoked as an alternate public
entrypoint: it requires one-shot configuration and parent-liveness pipes
inherited from the already-authorized parent.  The URL is passed only through
that pipe and is not persisted.  Both the configuration capability and
heartbeat descriptors must be actual inherited pipes; regular-file descriptor
injection is rejected.

The child is the sole owner of the only `start` call site.  Normal cleanup writes
a private `restore-request`; the same child sends one start and exits.  If the
parent dies while the listener remains continuously down, that child sends one
start after 300 seconds and exits.  It exits without runtime action when the
parent disappears before pause or while the listener is READY.  A 600-second
post-pause ceiling prevents an indefinite orphan when state oscillates; at that
ceiling, anything short of two READY samples (including unknown state) receives
the same sole recovery `start`.
The pre-pause armed lifetime is separately capped at 30 seconds and expires
without a control action because `stop` cannot precede the private pause marker.
After two READY samples, the parent disarms and reaps the child; a stuck child
is terminated because recovery is already confirmed.

Private runtime files must be regular, current-owner mode-0600 files.  Attempt
directories must be new, current-owner mode-0700 directories under an absolute,
current-owner mode-0700 run root.  Symlink inputs fail closed.

## Offline result

```text
=== COMELIT P116 R41 V4 PREFLIGHT RUNNER ===
BASE_R40H_SHA=f317bc1145b4165db0ef3677ebba777edd6780d1
RUNNER_CREATED=true
PERSISTENT_LOGCAT_STREAM=true
ADB_T_USED_AS_ATTEMPT_CURSOR=false
ADB_T_INITIAL_BACKLOG_ONLY=true
HOST_SAFE_EVENT_CURSOR=true
LOGCAT_BUFFER_CLEAR=false
RAW_LOGCAT_PERSISTED=false
RING_BUDGET_AVAILABLE_HARDCODED_FALSE=true
CHILD_CAPABILITY_GATE=true
SINGLE_START_OWNER=true
ORPHAN_LIFETIME_BOUNDED=true
POST_PAUSE_UNKNOWN_RECOVERED_ONCE=true
EVIDENCE_CURSOR_AFTER_CONFIRMED_PAUSE=true
LIVE_EXECUTED=false
ADB_LIVE_INVOCATIONS=0
LISTENER_PAUSE_COUNT=0
LISTENER_RESUME_COUNT=0
PHYSICAL_RING_COUNT=0
SYNTHETIC_RING_COUNT=0
DOOR_ACTIONS=0
GATE_ACTIONS=0
MEDIA_ACTIONS=0
HA_RESTARTS=0
HA_RELOADS=0
NEXT_LIVE_AUTHORIZED=false
RESULT=RUNNER_IMPLEMENTED_OFFLINE
=== END COMELIT P116 R41 V4 PREFLIGHT RUNNER ===
```
