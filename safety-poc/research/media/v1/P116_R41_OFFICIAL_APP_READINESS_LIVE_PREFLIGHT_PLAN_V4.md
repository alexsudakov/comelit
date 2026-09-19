# P116 R41 v4 — Official-App Readiness No-Ring Preflight Runner

Status: **DEV implementation only / live execution not authorized**.  
Base: exact R40H head `f317bc1145b4165db0ef3677ebba777edd6780d1`.  
This document supersedes R41 v3 operationally without rewriting v1/v2/v3.

## 1. Purpose

R40H established that the official app readiness gate for this project's legacy VIP system must use:

1. the current door-entry toolbar state `CONNECTED`;
2. a **fresh** transition into `ComelitStatus.RegisterStatus.REGISTERED` during this attempt;
3. no later `VIPER SOCKET CONNECTION LOST` / deregistration event.

R41 remains a **zero-ring preflight**. A PASS only says that the official app became ready during the
bounded listener-release window. It does not authorize a physical ring or R42.

## 2. v4 correction: one persistent logcat stream

R41 v3 mixed two independent cursor concepts:

- Android `adb logcat -T`, which selects an initial time/tail position;
- R40H's host-local `monotonic_seq`, which is the actual freshness boundary used by
  `evaluate_fresh_registration`.

v4 removes that ambiguity from the load-bearing path.

The live-capable runner starts **exactly one** filtered logcat process before the listener is paused:

```text
adb -s <runtime serial> logcat -v brief -T 1 -s   ComelitStatus:I ViperSocketReaderRun:E '*:S'
```

`-T 1` is used only to keep the startup backlog small. It is **not** the attempt cursor.

Each line is immediately passed to
`entrance_p116_r41_persistent_logcat_cursor.SafeLogEventBuffer`. The reducer retains only the two
already-proven safe event types from R40H and assigns accepted events a host-local monotonically increasing
sequence number.

Immediately before the single listener `stop` request, the runner records:

```text
PRE_PAUSE_SAFE_EVENT_CURSOR=current_safe_event_sequence
```

Only reduced events with `sequence > PRE_PAUSE_SAFE_EVENT_CURSOR` can satisfy the fresh-registration gate.

The logcat process is never restarted during an attempt and `adb logcat -c` is forbidden. If the stream
dies or the reader thread fails, readiness becomes blocked and listener restoration runs.

## 3. Safe persisted surface

Raw logcat lines, Android timestamps, PIDs, device identifiers and the adb serial are not persisted by the
cursor model and are not printed by the runner.

The in-memory reduced shape is limited to:

```text
source
monotonic_seq
from_state
to_state
```

where states are the closed enum:

```text
NONE
NOT_REGISTERED
REGISTERING
REGISTERED
```

The independent transport-loss marker is represented only as
`source=VIPER_TRANSPORT_FAILURE`.

## 4. Runner

Implemented runner:

`ct120_run_p116_r41_v4_no_ring_preflight.py`

Exact live approval token:

```text
R41_APPROVAL=I_APPROVE_R41_V4_NO_RING_PREFLIGHT_ONCE
```

Without that exact environment value the runner stops before reading private runtime inputs, starting adb,
contacting Home Assistant, or changing listener state.

Runtime-only inputs:

- `--control-url-file`: existing test-control webhook URL in a current-owner mode-600 file;
- `--adb-serial`: Android adb target, never printed;
- `--timeout-seconds`: operator-approved readiness window;
- `--attempt-id`: bounded filesystem-safe attempt identity.

No private HA address is committed to the repository.

## 5. Listener lifecycle

The runner reuses only the existing closed control actions:

```text
status
stop
start
```

The sequence is:

```text
1. exact approval gate
2. listener READY on two samples
3. start one persistent safe logcat stream
4. arm detached continuous-down failsafe
5. capture PRE_PAUSE_SAFE_EVENT_CURSOR
6. write failsafe pause-start marker
7. issue exactly one listener stop request
8. confirm paused on two status samples
9. discard any operator UI-state file written before pause confirmation
10. request a fresh toolbar sample
11. wait for CONNECTED + fresh uninvalidated REGISTERED
12. call R40H evaluate_readiness_v3 with ring_budget_available=false
13. require one-second stable candidate and re-evaluate freshness
14. perform NO ring
15. restore listener first with one normal start request
16. verify READY on two samples
17. disarm failsafe
18. emit the final bounded result block
```

An ambiguous stop response is treated as possibly accepted, so restoration remains mandatory.

## 6. Operator UI input

After pause is confirmed the runner deletes any pre-existing attempt UI file and emits:

```text
R41_OPERATOR_UI_STATE_SAMPLE_NOW=true
```

The operator/orchestrator then writes exactly one closed-set value to the mode-private attempt file:

```text
CONNECTED
CONNECTING
NOT_CONNECTED
UNKNOWN
```

A pre-pause value cannot satisfy the gate.

## 7. Readiness evaluation

The runner constructs R40H `ReadinessObservationV3` with:

```text
system_class=LEGACY_VIP
listener_state=PAUSED
ring_budget_available=false
CURRENT_UI_STATE=<post-pause operator sample>
fresh_registration=<persistent-stream freshness verdict>
```

The best successful verdict is therefore:

```text
official_app_ready=true
physical_ring_allowed=false
```

Any violation where `physical_ring_allowed=true` is a terminal runner error.

## 8. Timeout and failsafe

`APP_READY_PROTOCOL_TIMEOUT_SECONDS` remains **UNPROVEN**.

The runner accepts an operational timeout only in:

```text
1..240 seconds
```

The 240-second cap is an implementation safety margin below the already-proven 300-second
continuous-down recovery ceiling. It is not an estimate of protocol registration latency.

Before pause, the parent starts a detached failsafe child. The child does nothing until the parent writes
the attempt's `pause-started` marker. If listener state then remains continuously non-ready for 300 seconds,
the child issues **at most one** infrastructure recovery `start` request and exits. This is recovery, never
an experiment retry.

Under normal completion, the parent restores the listener, verifies READY, and only then disarms the
failsafe.

## 9. Hard prohibitions

The runner contains no path for:

- physical ring;
- synthetic ring;
- Door/Gate actuation;
- media start/stop;
- Home Assistant reload/restart;
- logcat buffer clear;
- retrying the experimental listener stop;
- a second readiness attempt.

`RING_BUDGET_CONSUMED=false` in every result.

## 10. Offline verification target

Focused tests cover:

- brief-format safe log reduction;
- stale pre-cursor REGISTERED rejection;
- fresh post-cursor REGISTERED acceptance;
- later transport failure invalidation;
- exact approval gate;
- one persistent logcat command and no `logcat -c`;
- runtime-only control URL;
- closed status/stop/start control surface;
- post-pause UI sample freshness;
- hardcoded false ring budget;
- single experimental stop;
- one normal restore start;
- detached one-shot failsafe recovery;
- missing approval = zero live work.

Full repository CI remains authoritative after the stacked PR is opened.

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
