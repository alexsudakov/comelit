# Comelit Ring / Telegram MVP v1 — Home Assistant automation constraint

Status: **normative clarification**  
Date: 2026-09-17  
Applies to: `docs/mvp-ring-telegram-v1-contract.md` and `docs/mvp-ring-telegram-v1-audit-and-dev-task.md`

For MVP v1, **all Telegram messaging and Telegram callback handling must be implemented through Home Assistant automations/scripts using Home Assistant's native Telegram integration/actions**.

This clarification removes any ambiguity from older wording that allowed a later move of Telegram orchestration into the LLM project.

For the current MVP:

```text
comelit_ring
-> Home Assistant automation/script
-> camera / media entities
-> camera.snapshot
-> telegram_bot.send_photo
-> telegram_bot.edit_message_media
-> telegram_bot.edit_replymarkup
-> telegram_bot.answer_callback_query
-> Home Assistant event / comelit.open_door
```

Required rules:

- do not implement Telegram send/edit/callback logic inside `custom_components/comelit`;
- do not implement Telegram orchestration in `llm-home-assistant-stack` for this MVP;
- do not introduce a standalone Telegram daemon, bot worker, n8n flow or third Comelit application server;
- `custom_components/comelit` remains responsible for Comelit protocol/device integration and normalized HA events/entities/actions;
- HA automations/scripts consume `comelit_ring`, manage the Telegram interaction, emit `comelit_ring_interaction`, and call semantic Comelit HA actions when needed;
- Telegram bot tokens, chat IDs and other private deployment values must remain in Home Assistant configuration/secrets and must not be committed to the public repository;
- the offline MVP build task must deliver an HA automation/script/package/blueprint artifact, not a Python Telegram client.

This clarification does not change the remaining MVP contract: one Telegram media message per ring, exact returned `message_id`, approximately 1 Hz serialized screenshot updates with no frame queue, `event_id` callback correlation, one-shot Open/Ignore, 30-second timeout, media teardown before Door, and no automatic retry.
