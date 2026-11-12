# Issue 319: матрица offline-доказательств RELEASE -> CALL_INIT

Область: только диагностика и offline proof. Production-код, `production_emit_allowed`,
P0-константы, native-бинарники, workflow и `.dev/hermes-dev.yaml` не изменялись.

Статусы сохранены: P0_A=NOT_FIXED, P0_B=NOT_FIXED, LIVE_ACCEPTANCE=NOT_RUN, ISSUE319=OPEN.
Физический звонок, дверь, калитка, live TX, CT120, deploy — не выполнялись (0).

## Использование предыдущего артефакта

Артефакт triage-запуска (`test_issue319_release_call_init_offline_proof.py`,
sha256 `091c99fa…bd68`) использован только как неподтверждённый входной контекст.
Файл создан заново в этом worktree: `tests/miniapp/test_issue319_release_call_init_offline_proof.py`.
Его 8 исходных тестов сохранены без ослабления (одно переименование модуля загрузки
`ring_shadow_release_proof` во избежание конфликта имён) и расширены новыми сценариями.
Результат прогона предыдущего запуска доказательством для этого кандидата не является.

## Покрытие 10 сценариев

Обозначения: NEW — новый тест в `test_issue319_release_call_init_offline_proof.py` (далее `release_proof`);
EXISTING — уже имеющийся тест; NOT_PROVEN — различение невозможно, запинено текущее поведение.

| # | Сценарий | Статус | Тесты |
|---|----------|--------|-------|
| 1 | RELEASE -> CALL_INIT при перекрытии завершения старого media | NEW | `release_proof::test_release_then_call_init_never_emits_without_call_identity`, `::test_controller_release_line_between_call_inits_never_emits`; EXISTING `test_optionf_round2a_ringid_probe.py::test_p6_release_attribution_survives_entrance_gate_tombstone_revive_release` |
| 2 | CALL_INIT при outstanding refresh | NEW + EXISTING | `release_proof::test_call_init_with_outstanding_refresh_stays_shadow`; EXISTING `test_issue319_ring_episode.py::test_default_is_not_observed_not_absent`, `::test_deferred_refresh_ack_diagnostics_are_accepted` |
| 3 | ACK, non-ACK, ABSENT, malformed | NEW + EXISTING | ACK/non-ACK/ABSENT/DEFERRED: EXISTING `test_issue319_ring_episode.py::test_ordered_episode_records_ring_ack_rtp_exit_and_lifecycle`, `::test_out_of_order_and_duplicate_events_do_not_regress_counters` (AMBIGUOUS, ABSENT), `::test_deferred_refresh_ack_diagnostics_are_accepted`; malformed/absent identity: NEW `release_proof::test_malformed_batch_variants_fail_closed`, `::test_malformed_and_absent_identity_batches_fail_closed`, `::test_retransmit_marker_without_prior_identity_fails_closed`, `::test_incomplete_identity_never_emits_even_when_allowed` |
| 4 | Retransmit одного вызова | NEW | `release_proof::test_retransmit_of_one_call_is_suppressed_not_emitted`, `::test_controller_retransmit_marker_is_suppressed` |
| 5 | Два последовательных разных вызова от одной панели | NEW (listener); NOT_PROVEN (media) | `release_proof::test_sequential_calls_in_listener_generation_are_not_suppressed`, `::test_sequential_listener_calls_do_not_emit_without_emit_gate` |
| 6 | Изменение owner generation | NEW | `release_proof::test_owner_generation_change_is_never_proof_of_new_call`, `::test_new_media_generation_after_listener_never_emits` |
| 7 | Один writer, нет второго upstream owner | NEW | `release_proof::test_single_media_owner_running_at_a_time`, `::test_shadow_module_has_only_two_owner_kinds` |
| 8 | Teardown uncertainty и восстановление listener | EXISTING | `test_issue319_ring_episode.py::test_teardown_failed_seal_is_handle_bound_and_idempotent`, `::test_late_teardown_failed_seal_cannot_touch_new_generation`, `::test_teardown_failures_publish_fail_closed_integrated_evidence`, `::test_ordered_episode_records_ring_ack_rtp_exit_and_lifecycle` (listener_resumed) |
| 9 | Call-state timeout 120 s и media hard limit 600 s | NEW (source pin) + EXISTING | `release_proof::test_call_state_timeout_and_media_hard_limit_are_pinned` (`runtime._CALL_STATE_TIMEOUT_SECONDS=120.0`, `const.RING_MEDIA_HARD_LIMIT_SECONDS=600`, `media_session.MEDIA_SESSION_HARD_LIMIT_SECONDS=600`), `::test_watchdog_boundary_yields_unresolved_never_emit`; EXISTING `test_optionf_upstream_media_observability.py::test_600_second_canary_cannot_reach_ha_module_rate_limit` |
| 10 | Door/Gate non-retry и fail-closed | NEW | `release_proof::test_gate_batches_never_retry_or_emit`, `::test_guard_decisions_never_request_terminal_retry`, `::test_guard_never_enables_production_effect_or_tx`, malformed door/source mismatch в сценарии 3 |

## Обязательный дополнительный случай: два РАЗЛИЧНЫХ физических вызова в одной media-generation

Статус: **NOT_PROVEN**.

Достоверного независимого идентификатора вызова нет. Не являются доказанным call ID:
`V4_RING_BODY_32_35` (семантика UNKNOWN, не подтверждена live), полный frame SHA,
owner generation, handoff epoch, timestamp, пара CTP.
Текущая shadow-модель подавляет второй CALL_INIT внутри одной media-generation
(`SUPPRESS`, `same_process_media_retransmit`), не отличая его от retransmit.

Запинено тестами `release_proof::test_media_owner_second_call_init_is_pinned_as_unproven_gap`
и `::test_media_generation_differing_frame_sha_is_not_call_identity`
(разные SHA кадров не меняют решение). Идентификатор не изобретался.
Следствие: production emit включать нельзя (`INDEPENDENT_NATIVE_CALL_IDENTITY_PROVEN=False`,
`PRODUCTION_EMIT_GATE_PROVEN=False`); константы пинит `::test_p0_status_remains_not_fixed`.

## Ограничения этапа Developer

Локальный запуск тестов Developer'ом не выполнялся (в fallback-окружении нет Bash);
исполнение полного набора проверок `.dev/hermes-dev.yaml` принадлежит доверенному VERIFY.
