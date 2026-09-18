# MVP1 Home Assistant → Telegram synthetic-ring live result

Date: 2026-09-18

Result: **PASS_HA_TELEGRAM_SYNTHETIC**

## Scope

Validated the Home Assistant automation consuming the existing Comelit MVP1 ring-media lifecycle:

`comelit_ring` → retained JPEG → Telegram photo → repeated photo edits →
`comelit_recording_complete` → Telegram video → correlated Ignore callback →
button cleanup → listener remains/restores READY.

No Comelit deploy, Comelit reload, Home Assistant restart, Door action, Gate action,
automatic retry, or R30H-E execution occurred in the Telegram validation round.

## Attempts

Two synthetic ring triggers occurred during this operator session:

1. The first trigger ran while the HA automation was disabled. Comelit media itself
   completed successfully, but no Telegram automation path was expected.
2. After the owner enabled the automation, one additional explicitly operator-requested
   trigger exercised the complete HA/Telegram path. The evidence below refers to this
   second trigger.

## Validated HA/Telegram run

Synthetic ring event:

- source: `synthetic_test`
- door: `entrance`
- kind: `CALL_INIT`
- one correlated event_id was used across ring, snapshots, recording, Telegram buttons,
  and callback handling.

Media:

- P116 video packets: 1023
- P116 audio packets: 1061
- snapshot sequence: 1..19
- snapshot cadence: ~1.009 s
- recording target: 20 s
- recording state: `completed`
- recording actual duration: 21.168 s
- media teardown: PASS
- listener READY after media: PASS

Home Assistant automation trace:

- automation triggered from the exact `comelit_ring` event: PASS
- first `comelit_snapshot_updated` delivered the retained JPEG path: PASS
- `telegram_bot.send_photo` executed and returned chat/message identifiers: PASS
- subsequent snapshots executed `telegram_bot.edit_message_media`: PASS
- `comelit_recording_complete` executed `telegram_bot.send_video`: PASS
- `telegram_callback` for Ignore was received: PASS
- callback data matched the current event_id: PASS
- callback chat matched the sent message chat: PASS
- callback message_id matched the message_id returned by `send_photo`: PASS
- Ignore branch executed and answered `Звонок проигнорирован`: PASS
- final `edit_replymarkup` removed the controls: PASS
- Open branch was not executed
- Door actions: 0
- Gate actions: 0

The callback occurred after the 20-second recording had already completed. Therefore
the media-stop branch evaluated the camera switch as already off and performed no
additional stop action.

## Canonical automation decision

PR #168 split Open/Ignore handling into independent callback automations and removed
the exact chat/message correlation enforced by the validated single-run automation.

The validated design keeps callbacks in the bounded ring automation and requires all
of the following before accepting Open/Ignore:

1. callback data contains the current ring event_id;
2. callback chat matches the chat returned by the initial Telegram send;
3. callback message_id matches the exact Telegram message returned by the initial send;
4. callback arrives while the bounded ring automation is still active.

This is the canonical behavior to retain.

## Final classification

```text
RESULT=PASS_HA_TELEGRAM_SYNTHETIC
TELEGRAM_SEND_PHOTO=PASS
TELEGRAM_PHOTO_UPDATE=PASS
TELEGRAM_SEND_VIDEO=PASS
TELEGRAM_CALLBACK_RECEIVED=PASS
CALLBACK_DATA_MATCH=PASS
CALLBACK_CHAT_MATCH=PASS
CALLBACK_MESSAGE_MATCH=PASS
TERMINAL_OUTCOME=ignored
MEDIA_TEARDOWN=PASS
LISTENER_READY_AFTER_MEDIA=PASS
DOOR_ACTIONS=0
GATE_ACTIONS=0
R30H_E_EXECUTED=false
```
