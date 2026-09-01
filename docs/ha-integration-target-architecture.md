# Comelit Home Assistant Integration — Target Architecture and MVP Requirements

Status: approved design baseline
Date: 2026-09-01
Repository baseline at decision time: `f0dba9324741b376f67da26543deec58fc4cdd76`

## 1. Purpose

This document fixes the agreed target architecture and user-facing requirements for the Comelit integration.

The project must not introduce a separate permanent Comelit application server as a third architectural layer. The target solution is one of two places only:

1. Home Assistant custom integration (`custom_components/comelit`) for Comelit device integration and HA-facing functionality.
2. The existing LLM-for-smart-home project for LLM/Telegram-specific orchestration where that is more appropriate.

CT120/P13/P14 is a transitional and safety-validated backend for Door actuation while the Home Assistant integration is being completed. It is not the target application architecture by itself.

## 2. Target architecture

Primary target:

```text
                     LLM / Hermes
                         |
              HA LLM/MCP tool call
                         |
                         v
+--------------------------------------------------+
|                 Home Assistant                   |
|                                                  |
|          custom_components/comelit               |
|                                                  |
|  Door control | Ring events | Cameras | Record  |
|                                   |              |
|                            later: full duplex     |
+------------------------+-------------------------+
                         |
                         v
                      Comelit
```

During migration, Door actuation may remain:

```text
Home Assistant Comelit integration
        -> P14 on CT120
        -> immutable P13 one-shot runtime
        -> Comelit Door
```

The integration must hide this migration detail from end users and callers.

## 3. Physical topology and logical identifiers

There are two call/door points:

- `entrance` — apartment-building entrance panel and entrance Door.
- `gate` — gate panel and gate Door.

A ring from `entrance` is associated only with the entrance Door.
A ring from `gate` is associated only with the gate Door.

External callers must use only the logical closed set:

```text
entrance
gate
```

Raw Comelit peer addresses, output indexes, device identifiers, protocol addresses, or other low-level target data must not be caller-controlled.

## 4. Door control API

### 4.1 Public Home Assistant action

The public action must be semantic and must not require a safety-layer operation identifier:

```yaml
action: comelit.open_door
data:
  door: entrance
```

or:

```yaml
action: comelit.open_door
data:
  door: gate
```

### 4.2 Internal operation identity

`operation_id` remains required internally for one-shot/idempotency/audit semantics but must be generated inside the integration/runtime.

The public HA action, dashboard buttons, automations, Hermes and LLM tools must not generate or pass `operation_id`.

The returned diagnostic result may include the generated operation identifier.

### 4.3 One shared Python implementation

All Door entry points must converge on one internal method, conceptually:

```python
await runtime.async_open_door(door)
```

The following must all use that method and must not emulate each other:

- dashboard `ButtonEntity` press;
- `comelit.open_door` HA action;
- Hermes/LLM/MCP tool call.

### 4.4 Safety semantics retained

The integration must retain the already validated P13/P14 safety properties:

- one operation -> at most one actuation transport invocation;
- no automatic retry;
- internal operation identity generated before the one-shot execution boundary;
- post-send ambiguity is terminal `UNKNOWN_OUTCOME`;
- trusted protocol outcomes remain `ACKED`, `FAILED_SAFE`, `UNKNOWN_OUTCOME`;
- protocol ACK does not prove physical Door state;
- `physical_effect_asserted=false`;
- `physical_door_state=UNKNOWN` unless a separate physical feedback mechanism is proven later.

## 5. Home Assistant user interface — MVP

The MVP must expose two user-operable buttons:

```text
Comelit — Entrance
  - Open Door

Comelit — Gate
  - Open Gate
```

Normal button press is allowed. A dashboard button is a human command and invokes the same internal `async_open_door(door)` method as the HA action.

The integration must not expose a misleading `lock` entity until real physical lock/door state feedback exists.

## 6. Home Assistant diagnostics

Diagnostics are approved and should be marked as diagnostic entities where appropriate.

Minimum diagnostic information:

- integration/backend connectivity;
- protocol/runtime status;
- live/ready status when applicable;
- non-secret backend identity/health metadata.

Secrets must never be exposed in state, attributes, diagnostics, logs, events or service responses.

The result of each Door operation should also be emitted as an HA event rather than represented as a fake physical Door state.

Suggested event payload:

```text
door
operation_id
state
reason
runner_invoked
retry_allowed=false
physical_effect_asserted=false
```

## 7. Hermes / LLM integration surface

Hermes must be able to call the Comelit functionality directly as a semantic tool and must not imitate a UI button press.

Preferred design:

```text
Hermes
  -> authorization / confirmation in the LLM project
  -> HA LLM/MCP Comelit tool
  -> integration internal async_open_door(door)
```

Minimum LLM tool contract:

```text
open_door(door: "entrance" | "gate")
```

The integration should expose this through Home Assistant's LLM/MCP integration mechanism where practical. The standard HA action remains available independently for automations/scripts.

Hermes confirmation/authorization remains the responsibility of the LLM project. A direct human button press in Home Assistant does not require Hermes confirmation.

## 8. Cameras

There are ordinary RTSP cameras and two intercom-associated cameras.

### 8.1 Ordinary cameras

MVP requirement: live view only.

No recording, detection or analytics are required for ordinary cameras at this stage.

### 8.2 Intercom cameras

The user-visible goal is to view them similarly to ordinary cameras if the Comelit system permits it without interfering with calls or other viewers.

Before finalizing the camera implementation, perform a concurrency/protocol test to determine which model applies:

1. Multiple concurrent RTSP sessions are supported and do not interfere with Comelit calls.
2. Only one upstream RTSP session is practical, but a persistent upstream plus local fan-out (for example through go2rtc) does not interfere with calls.
3. An active RTSP session interferes with incoming/outgoing call media, so explicit start-view/stop-view session management is required.

Required research matrix includes at least:

- one RTSP client;
- two simultaneous RTSP clients;
- RTSP plus official Comelit live view;
- RTSP plus incoming ring/call;
- RTSP plus active conversation;
- resource/session release after closing RTSP.

No permanent start/stop UI mechanism should be designed until this behavior is proven.

## 9. Incoming ring user scenario

There are two source panels: `entrance` and `gate`.

The integration must ultimately detect the source panel and emit a normalized HA event, conceptually:

```text
comelit_ring
```

Suggested event data:

```text
call_id
door: entrance | gate
source panel identity
camera entity/reference
timestamp
snapshot path/reference
```

The exact protocol detection method is not yet fixed. Determining it from code, captures and runtime logs is the immediate next research task.

## 10. Snapshot and recording behavior

On ring detection:

1. capture a snapshot from the camera associated with the calling panel;
2. immediately start one common recording flow;
3. record 60 seconds;
4. keep the clip regardless of whether the call is opened, ignored, answered or times out;
5. retention is manual deletion for now.

Ring interaction timeout: 30 seconds, configurable later.

The recording flow should be outcome-independent; opening the Door must not stop or delete the recording.

Audio conversation recording is not required.

Physical storage location for retained recordings remains an implementation decision to resolve before recording is deployed.

## 11. Telegram / notification scenario

Telegram is not required to be implemented through Home Assistant specifically. Two acceptable target implementations are:

1. HA automation reacting to the normalized Comelit ring event.
2. LLM-for-smart-home project reacting to the same logical Comelit functionality/event path.

Do not introduce a third permanent standalone Comelit application server only for Telegram.

Desired notification UI:

```text
[ snapshot ]

Ring: Entrance or Gate

[Open] [Call] [Ignore]
```

- `Open` opens only the Door associated with the ring source.
- `Ignore` stops further notification handling only; it does not actively reject or terminate the Comelit call.
- `Call` is reserved for the later full-duplex implementation.

Duplicate-open protection tied to `call_id` may be added later. It is not an MVP blocker. Automatic retry remains forbidden.

HA Companion actionable notifications are not required at this stage.

## 12. Full-duplex conversation — later phase

Desired final behavior is full duplex, not push-to-talk.

Future scope:

- answer call;
- receive remote audio;
- transmit microphone audio;
- hang up;
- maintain the corresponding Comelit signaling/media session.

Conversation audio must not be recorded.

The final frontend/transport choice for this function (HA UI/WebRTC, LLM/Telegram-related UI, or another existing project surface) is intentionally deferred until the Comelit call/media protocol has been proven.

## 13. MVP boundary

The next MVP implementation target is intentionally narrower than the complete vision:

1. two logical Doors (`entrance`, `gate`);
2. internal operation ID generation;
3. working HA buttons;
4. `comelit.open_door(door)` HA action;
5. direct Hermes LLM/MCP semantic tool path;
6. diagnostics and Door-operation event;
7. no ring workflow required yet;
8. no live intercom conversation required yet;
9. no Telegram dependency required yet.

Before implementing this MVP, the project must determine the exact Comelit mapping/actuation path for the `gate` Door with the same closed-set and one-shot safety discipline already applied to the entrance Door.

## 14. Immediate next research task: incoming ring detection

The next research boundary is repository/runtime evidence only and must not cause a physical Door action.

Goal: determine exactly how an incoming call/ring from each panel is represented in the Comelit protocol and how to distinguish `entrance` from `gate`.

Research sources, in priority order:

1. existing project source code and parsers;
2. existing saved logs/captures/artifacts already collected during Comelit protocol research;
3. read-only runtime logs on CT120;
4. only if evidence remains insufficient, a controlled new capture while a user intentionally rings one panel at a time.

Required output of the research:

- protocol message(s) that indicate a ring/call start;
- source-panel identifier and mapping to `entrance` / `gate`;
- call/session identifier if one exists;
- relevant state transitions (ring start, answer, timeout/end);
- whether the event is UDP/TCP and whether it is already observable by the current ViP session code;
- minimal implementation hook for an MVP HA event producer;
- evidence showing that ring detection itself is read-only/non-actuating.

No assumption about a specific opcode/message name is accepted until confirmed from the available code/capture/runtime evidence.
