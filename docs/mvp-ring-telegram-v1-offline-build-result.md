# Comelit MVP1 Ring Telegram Offline Build Result

TASK_ID=`COMELIT-MVP1-RING-TELEGRAM-OFFLINE-BUILD`  
MODE=`OFFLINE_ONLY`  
BASE_SHA=`317870fa39ec5f53f4060fed522c3950b60866b5`  
BRANCH=`feat/mvp1-ring-telegram-offline-build`

## Source Identity

The worktree started at accepted `origin/main` `317870fa39ec5f53f4060fed522c3950b60866b5`. Private project context was read for safety/lifecycle rules and was not copied into this public repository.

## Reuse vs New Code

Reused unchanged: `comelit_ring` parsing/emission, source mapping, ring deduplication path, media manager/session transport, camera/switch/listener diagnostics, gate actuation gating, R30H-E/repeat-`0x001A` artifacts.

New/changed:

- `custom_components/comelit/runtime.py`: one shared Door operation finalizer emits `comelit_door_operation`.
- `custom_components/comelit/__init__.py`, `const.py`, `services.yaml`: `comelit.emit_ring_interaction` service for HA orchestration to emit `comelit_ring_interaction`; optional `event_id` on `comelit.open_door`.
- `examples/home-assistant/packages/comelit_ring_telegram_mvp.yaml`: production-oriented HA package example.
- `safety-poc/tests/test_mvp1_ring_telegram_offline_build.py`: focused offline acceptance gates.
- `safety-poc/tests/test_p116_r20_hls_http_boundary_diagnostics.py`: updated stale runtime hash for the intentional Door-event runtime change.

## Event Decisions

`comelit_door_operation` is emitted by `ComelitRingRuntime._finalize_door_operation()` at `custom_components/comelit/runtime.py:307`. All completed `async_open_door()` results return through this function (`runtime.py:348`, `362`, `388`, `442`), so service and ButtonEntity paths cannot diverge. Payload includes `operation_id`, `door`, `state`, `protocol_acked`, `write_count`, `door_specific_ack_proven`, `automatic_retry_allowed=false`, `physical_effect_asserted=false`, plus optional `event_id`.

`comelit_ring_interaction` is produced by HA orchestration through `comelit.emit_ring_interaction` (`custom_components/comelit/__init__.py:74`). This is the minimal integration service needed because HA core documentation covers consuming/firing events from integrations, but HA has no built-in native automation action for arbitrary custom bus events without an integration-provided service. Relevant public docs: `https://www.home-assistant.io/docs/configuration/events/`, `https://developers.home-assistant.io/docs/integration_events/`.

Telegram actions use current native HA Telegram actions and response data: `telegram_bot.send_photo` with `response_variable`, `telegram_send.chats[0].chat_id/message_id`, `telegram_bot.edit_message_media`, and `telegram_bot.edit_replymarkup`. Relevant public docs: `https://www.home-assistant.io/actions/telegram_bot.send_photo/`, `https://www.home-assistant.io/actions/telegram_bot.edit_message_media/`, `https://www.home-assistant.io/integrations/telegram_bot`.

Callback encoding decision: use `comelit|open|<event_id>` and `comelit|ignore|<event_id>` rather than `comelit:open:<event_id>`. HA documents inline keyboard rows as `button text:callback data` and documents the resulting `telegram_callback.data` field, but the docs do not prove that additional colons inside callback data survive that parser. The pipe-delimited value avoids ambiguity while preserving `event_id` as the correlation key. Residual uncertainty: this remains offline/static until a separately authorized Telegram canary.

## Artifact Guarantees

Artifact: `examples/home-assistant/packages/comelit_ring_telegram_mvp.yaml`.

Control flow: `comelit_ring` trigger in `mode: single` with `max_exceeded: silent`; capture `event_id`/`door`; entrance-only media start; bounded wait for video forwarding/packet progress; first `camera.snapshot`; exactly one `telegram_bot.send_photo`; capture returned `chat_id/message_id`; sequential repeat waits up to one second for matching callback or captures/edits the same message; terminal outcomes emitted once; keyboard removal is guarded by non-empty Telegram IDs and `continue_on_error`; media stopped; listener READY and switch off checked before `comelit.open_door`.

`notification_failed` is explicit when the first send does not return usable IDs (`examples/home-assistant/packages/comelit_ring_telegram_mvp.yaml:83`), and teardown remains reachable because markup edit is guarded (`yaml:210`) and media stop/listener wait follow it (`yaml:223`, `227`).

`media_failed` is reachable when the entrance media switch is no longer on or camera forwarding/packet progress is gone (`yaml:118`). It emits `comelit_ring_interaction(outcome=media_failed)` (`yaml:130`), stops the loop by setting `terminal_outcome`, still reaches media release/listener wait, and cannot call Door because Door is gated to `terminal_outcome == 'open_requested'` plus listener wait completion.

Second-ring behavior: `mode: single` plus `max_exceeded: silent` intentionally drops a second ring while active (`yaml:18` and `21`). The in-artifact comment records that this means no second media session, no Door action, and no active context mutation (`yaml:19`). It surfaces the safety decision in review rather than silently relying on HA defaults.

Snapshot retention: stable path `{{ snapshot_directory }}/comelit_ring_{{ event_id }}.jpg`, deployment-configurable via helper, no token/session/peer identifier in filename, no RTP/H264/audio persistence. Final displayed frame remains because no cleanup job is included. Deployment prerequisite: the configured snapshot directory must be readable by Telegram file sending; HA Telegram docs require adding local file directories such as `/media` to `homeassistant.allowlist_external_dirs`.

Forbidden config evidence: `test_telegram_orchestration_no_secrets` asserts no URLs, token/password/secret assignments, or committed numeric Telegram chat IDs in the package, and asserts no `telegram_bot` dependency inside `custom_components/comelit`.

## Gate Evidence

- `DOOR_OPERATION_EVENT_EXACTLY_ONCE=PASS`: AST/text count, single `EVENT_DOOR_OPERATION` fire in finalizer and no direct fire in `async_open_door`; `safety-poc/tests/test_mvp1_ring_telegram_offline_build.py:158`.
- `DOOR_OPERATION_EVENT_SAFE_PAYLOAD=PASS`: required payload keys and forced false safety fields; line `180`.
- `DOOR_OPERATION_EVENT_FROM_SERVICE_AND_BUTTON_SHARED_PATH=PASS`: service/button both call `async_open_door`, neither fires event directly; line `207`.
- `RING_EVENT_CONTRACT_UNCHANGED=PASS`: event name and payload keys retained; line `221`.
- `RING_SOURCE_MAPPING_UNCHANGED=PASS`: `00000643 -> entrance`, `00000610 -> gate`; line `221`.
- `GATE_ACTUATION_STILL_GATED=PASS`: gate actuation profile false, service entrance-only, gate button raises; line `235`.
- `MEDIA_PROTOCOL_CODE_UNCHANGED=PASS`: protected media files SHA-256 pinned; line `248`.
- `R30H_E_CODE_UNCHANGED=PASS`: R30/R30H protected artifacts SHA-256 pinned; line `248`.
- `TELEGRAM_ORCHESTRATION_NO_SECRETS=PASS`: artifact secret/URL/chat-id scan and no Telegram imports in component; line `265`.
- `TELEGRAM_SINGLE_MESSAGE_MODEL=PASS`: exactly one `telegram_bot.send_photo`; line `274`.
- `TELEGRAM_USES_RETURNED_MESSAGE_ID=PASS`: returned `telegram_send.chats[0]` chat/message IDs used; line `274`.
- `SCREENSHOT_REFRESH_SERIAL_NO_QUEUE=PASS`: `mode: single`, sequential snapshot then edit, no queued/parallel mode; line `290`.
- `SCREENSHOT_REFRESH_TARGET_APPROX_1HZ=PASS`: one-second refresh variable used as callback wait timeout; line `290`.
- `CALLBACK_EVENT_ID_MATCH_REQUIRED=PASS`: callback data embeds event ID and waits only exact callback data; line `305`; YAML parser check line `91`.
- `CALLBACK_ONE_SHOT=PASS`: loop gated by empty `terminal_outcome`; line `305`.
- `IGNORE_NO_DOOR=PASS`: only one Door action exists and is gated to `open_requested`; line `318`.
- `TIMEOUT_NO_DOOR=PASS`: timeout outcome is emitted without Door call; line `318`.
- `OPEN_MEDIA_STOP_BEFORE_DOOR=PASS`: `switch.turn_off` precedes Door call; line `318`.
- `OPEN_LISTENER_READY_GATE_BEFORE_DOOR=PASS`: listener READY wait precedes Door call and `wait.completed` gates Door; line `318`.
- `OPEN_DOOR_MAX_INVOCATIONS=1`: exactly one `comelit.open_door`; line `318`.
- `AUTOMATIC_RETRY=false`: artifact contains no retry and runtime one-shot fields force false; line `318`.
- `INTERACTION_TIMEOUT_SECONDS=30`: artifact variable and loop deadline asserted; line `339`.
- `RECORDING_IMPLEMENTED=false`: no recording actions/events/media persistence terms in artifact; line `339`.

Additional corrective evidence:

- C1 notification failure teardown: guarded IDs, `continue_on_error`, and teardown ordering asserted at `test_mvp1_ring_telegram_offline_build.py:111`.
- C2 early media failure and snapshot/edit failure containment asserted at line `133`.
- C3 callback encoding YAML parse and keyboard/wait matching asserted at line `91`.
- C4 second-ring `mode: single`/`max_exceeded: silent` and explicit comment asserted at line `83`.

## Offline Suite Comparison

Focused MVP module:

```text
Ran 16 tests in 0.026s
OK
```

Authoritative HOST full branch suite:

```text
cd safety-poc && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=$PWD/src python3 -m unittest discover -s tests
Ran 1541 tests in 27.925s
FAILED (failures=1, skipped=1)
```

Authoritative HOST baseline at `317870fa39ec5f53f4060fed522c3950b60866b5`:

```text
Ran 1525 tests, failures=1, skipped=1
```

HOST branch vs HOST baseline: `1541 - 1525 = 16` new MVP1 tests.

Codex sandbox full-suite run retained verbatim for context only:

```text
Ran 1541 tests in 31.993s
FAILED (failures=1, errors=2, skipped=5)
```

Residuals:

- `test_p116_provenance_binary_analysis.P116ProvenanceBinaryAnalysisTests.test_committed_build_metadata_records_historical_non_runtime_mismatch`: `755 != 775`, `NOT_A_MVP1_REGRESSION`.
- In the Codex sandbox run only, `test_p116_r29i_preopen_idle_and_sink_ownership` zero/nonzero UDP sink final counter tests errored because `codex exec` sandboxing blocks UDP datagram sockets. This is `NOT_A_MVP1_REGRESSION`; the authoritative HOST branch run has no such errors, and the HOST baseline has none either. No R29I/research artifact was modified because it is outside this corrective scope.

## Deferred / Not Proven

- `RECORDING_IMPLEMENTED=false`: 60-second retained recording remains deferred.
- `R30H_E_EXECUTED=false`: R30H-E/repeat-`0x001A` not executed or changed.
- Gate media and physical Gate validation not performed; gate actuation remains gated.
- No physical Door validation; protocol ACK is not physical effect.
- No HA deploy/reload/restart, no Telegram send, no live Comelit media, no Door/Gate action.

## Forbidden-Action Evidence

No live commands were run. Only text/AST/YAML/static tests, Python compile, local git/archive/clone for baseline comparison, and local unit tests were executed. No `custom_components/comelit/camera.py`, `media_session.py`, `media_transport.py`, `native/**`, `safety-poc/research/**`, or R30H-E executable artifact was modified.

RESULT_CLASS=`PASS_OFFLINE_MVP_READY`

```text
=== COMELIT MVP1 RING TELEGRAM OFFLINE BUILD ===
TASK_ID=COMELIT-MVP1-RING-TELEGRAM-OFFLINE-BUILD
BASE_SHA=317870fa39ec5f53f4060fed522c3950b60866b5
RING_EVENT=PASS
RING_EVENT_ID=PASS
RING_DEDUP=PASS
DOOR_OPERATION_EVENT=PASS
INTERACTION_EVENT_ARTIFACT=PASS
TELEGRAM_SINGLE_MESSAGE_MODEL=PASS
TELEGRAM_MESSAGE_ID_CAPTURE=PASS
SCREENSHOT_REFRESH_SERIAL_NO_QUEUE=PASS
SCREENSHOT_REFRESH_TARGET_SECONDS=1
INTERACTION_TIMEOUT_SECONDS=30
OPEN_MEDIA_STOP_BEFORE_DOOR=PASS
OPEN_LISTENER_READY_GATE_BEFORE_DOOR=PASS
OPEN_DOOR_MAX_INVOCATIONS=1
IGNORE_NO_DOOR=PASS
TIMEOUT_NO_DOOR=PASS
FINAL_SNAPSHOT_RETENTION=PASS
GATE_ACTUATION_GATED=true
GATE_MEDIA_GATED=true
RECORDING_IMPLEMENTED=false
R30H_E_EXECUTED=false
COMELIT_LIVE_EXECUTED=false
TELEGRAM_MESSAGE_SENT=false
HA_DEPLOYED=false
HA_RELOADED=false
HA_RESTARTED=false
DOOR_ACTIONS=0
GATE_ACTIONS=0
BRANCH=feat/mvp1-ring-telegram-offline-build
REMOTE_HEAD=NOT_PUSHED
PR=none
RESULT=PASS_OFFLINE_MVP_READY
=== END COMELIT MVP1 RING TELEGRAM OFFLINE BUILD ===
```

Marker-block qualification: `BRANCH=feat/mvp1-ring-telegram-offline-build` and `REMOTE_HEAD=NOT_PUSHED` are pre-push authoring values. A commit cannot embed its own pushed head SHA; the authoritative pushed head and PR outcome are reported by the orchestrator's final block for this task.
