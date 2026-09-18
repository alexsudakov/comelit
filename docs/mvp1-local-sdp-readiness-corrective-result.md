# MVP1 local SDP readiness corrective result

## Summary

```text
TASK_ID=COMELIT-MVP1-LOCAL-SDP-READINESS-CORRECTIVE
MODE=STRICTLY_OFFLINE_CORRECTIVE
DATE_UTC=2026-09-18
RESULT=PASS_OFFLINE_LOCAL_SDP_READINESS_READY
FIX_APPLIED=true
HOST_VERIFIED=true
CHANGED_FILES=4 modified + 2 new
```

Исправление подтверждено host-authoritative offline-прогонами оркестратора. Live Comelit, HA deploy/reload/restart, Door/Gate и synthetic trigger не выполнялись.

## Root cause

Подтвержденный source-level ordering defect: native helper сообщает `P80_MEDIA_ACTIVE=true`, после чего `async_start()` возвращал успех раньше появления `local-rtp.sdp`.

Точка interleaving: `P80_MEDIA_ACTIVE_BEFORE_LOCAL_SDP_WRITE`.

Исходный порядок:

Перечисленные `path:line` - это позиции accepted main `204ec3aa6cf7c6e8057b2336094675e7353c24f1` ДО фикса; после фикса номера строк сдвинулись. Это forensic-цитаты исходного порядка, а не текущего файла.

- `custom_components/comelit/media_transport.py:657`-`677`: `_async_run_cycle()` сначала ждал `_media_active`, а `_write_local_sdp()` выполнялся только после этого окна.
- `custom_components/comelit/media_transport.py:476`-`491`: `async_start()` ждал только `_media_active` через `asyncio.wait(... timeout=45 ...)` и мог вернуть success сразу после active.
- `custom_components/comelit/media_transport.py:258`-`279`: `active` означал `_media_active.is_set()` плюс live process, а `local_sdp_ready` требовал `active`, running shim и существующий SDP-файл.
- `custom_components/comelit/media_session.py:194`-`207`: manager после `async_start()` проверял только `transport.active` и переводил фазу в `MEDIA_PHASE_ACTIVE`.
- `custom_components/comelit/ring_media.py:151`-`160`, `:218`-`:221`: provider требовал `manager.active` и `local_sdp_ready`; при неготовом SDP `async_record_mp4()` получал `stream_unavailable` и `RECORDING_STATE_FAILED`.

Итог: `media_manager ACTIVE` не гарантировал `transport.local_sdp_ready`.

## Fix

В `custom_components/comelit/media_transport.py` введены:

- `_MEDIA_STARTUP_WINDOW_SECONDS = 45.0`, именующий прежний inline timeout без нового числового тайминга.
- `_MEDIA_LOCAL_SDP_READY_REASON = "local_sdp_ready_timeout"`.
- Приватный `self._local_sdp_ready_event` рядом с `_offer_ready` и `_media_active`.
- `clear()` события на каждом bootstrap-start, в `async_stop()`, и в `finally` у `_async_run_once()`.
- После `_write_local_sdp()` событие ставится только если истинно существующее свойство `self.local_sdp_ready`, то есть `active + shim.running + local-rtp.sdp exists`.
- `async_start()` теперь использует один общий deadline: phase 1 ждет media active или завершение task, phase 2 ждет local SDP readiness или завершение task на остатке того же окна.
- При active без SDP до истечения окна start fail-closed: `last_error=local_sdp_ready_timeout`, исключение `ComelitMediaTransportError("local_sdp_ready_timeout")`, затем штатный teardown через `async_stop()`.

Не добавлены sleep, retry, polling loop, второй Stream или перенос SDP-логики в `ring_media.py`.

Актуальные позиции нового кода в `custom_components/comelit/media_transport.py`: `async_start()` реализует две bounded-фазы на общем deadline; `_local_sdp_ready_event` устанавливается сразу после `_write_local_sdp()` под проверкой `self.local_sdp_ready`; событие очищается в bootstrap-start, `async_stop()` и `finally` у `_async_run_once()`.

## Behavioural tests

Host focused command:

```text
cd safety-poc
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=$PWD/src python3 -m unittest tests.test_mvp1_local_sdp_readiness_corrective
Ran 5 tests in 4.625s
OK
```

TEST A `test_a_delayed_sdp_readiness_blocks_async_start_until_ready`:

```text
TRANSPORT_ACTIVE_BEFORE_SDP=true
ASYNC_START_RETURNED_BEFORE_SDP=false
ASYNC_START_RETURNED_AFTER_SDP=true
PASS
```

TEST B `test_b_sdp_never_ready_fails_closed_without_retry`:

```text
SDP_READY_TIMEOUT_BOUNDED=PASS
SDP_READY_TIMEOUT_REASON=local_sdp_ready_timeout
SPAWN_COUNT=1
PASS
```

TEST C `test_c_process_exit_between_active_and_sdp_ready_fails_without_hang`:

```text
PROCESS_EXIT_BEFORE_SDP_HANDLED=PASS
SPAWN_COUNT=1
PASS
```

TEST D `test_d_manager_active_implies_sdp_ready_and_timeout_restores_listener`:

```text
MANAGER_ACTIVE=true
TRANSPORT_LOCAL_SDP_READY=true
MEDIA_MANAGER_ACTIVE_IMPLIES_SDP_READY=PASS
timeout path: manager inactive, listener resumed once, SPAWN_COUNT=1
PASS
```

TEST E `test_e_preserve_single_flight_and_fail_before_sdp_ready`:

```text
pre-SDP record: RECORDING_STATE_FAILED
pre-SDP last_failure_reason=stream_unavailable
pre-SDP STREAM_CONSTRUCTOR_COUNT=0
STREAM_CONSTRUCTOR_COUNT=1
RETURNED_STREAM_OBJECT_IDENTICAL=true
SNAPSHOT_AND_RECORDING_SHARE_STREAM=true
ASYNC_CLOSE_SINGLE_STREAM=PASS
PASS
```

TEST E - preservation-тест уже смерженного single-flight fix (PR #164), он не зависит от transport-правки, поэтому на unfixed дереве он проходит штатно; это НЕ противоречие.

## Gates

```text
LOCAL_SDP_READINESS_EVENT=PASS
TRANSPORT_START_WAITS_FOR_SDP=PASS
NO_SUCCESS_BEFORE_SDP_READY=PASS
SDP_READY_TIMEOUT_BOUNDED=PASS
SDP_READY_TIMEOUT_REASON=local_sdp_ready_timeout
PROCESS_EXIT_BEFORE_SDP_HANDLED=PASS
MEDIA_MANAGER_ACTIVE_IMPLIES_SDP_READY=PASS
STREAM_CREATE_SINGLE_FLIGHT=PASS
STREAM_CONSTRUCTOR_COUNT=1
RECORDING_TARGET_SECONDS=20
NATIVE_CODE_UNCHANGED=PASS
R30H_E_EXECUTED=false
COMELIT_LIVE_EXECUTED=false
HA_DEPLOYED=false
HA_RELOADED=false
HA_RESTARTED=false
SYNTHETIC_TRIGGER_COUNT=0
DOOR_ACTIONS=0
GATE_ACTIONS=0
```

Механические доказательства unchanged-скаляров:

- `LOCAL_SDP_READINESS_EVENT=PASS`: host focused run `tests.test_mvp1_local_sdp_readiness_corrective` прошел `Ran 5 tests in 4.625s OK`.
- `TRANSPORT_START_WAITS_FOR_SDP=PASS`: TEST A host-run измерил `ASYNC_START_RETURNED_BEFORE_SDP=false`.
- `NO_SUCCESS_BEFORE_SDP_READY=PASS`: TEST A host-run измерил отсутствие return до release SDP и success после SDP-ready.
- `SDP_READY_TIMEOUT_BOUNDED=PASS`: TEST B host-run прошел bounded timeout path без retry.
- `SDP_READY_TIMEOUT_REASON=local_sdp_ready_timeout`: TEST B host-run проверил exact reason.
- `PROCESS_EXIT_BEFORE_SDP_HANDLED=PASS`: TEST C host-run прошел process-exit path без ложного success.
- `MEDIA_MANAGER_ACTIVE_IMPLIES_SDP_READY=PASS`: TEST D host-run измерил `MANAGER_ACTIVE=true` и `TRANSPORT_LOCAL_SDP_READY=true`.
- `STREAM_CREATE_SINGLE_FLIGHT=PASS`: TEST E host-run подтвердил общий stream; полный набор сохраняет `test_mvp1_stream_singleflight_corrective`.
- `STREAM_CONSTRUCTOR_COUNT=1`: TEST E host-run напечатал `STREAM_CONSTRUCTOR_COUNT=1`.
- `RECORDING_TARGET_SECONDS=20`: `custom_components/comelit/const.py` не изменялся; TEST E вызывает запись с `target_seconds=20`.
- `NATIVE_CODE_UNCHANGED=PASS`: `git diff --name-only 204ec3aa6cf7c6e8057b2336094675e7353c24f1 -- custom_components/comelit/native` = empty.
- `R30H_E_EXECUTED=false`: R30H-E live/research команды не запускались; protected-gates diff для `safety-poc/scripts` пуст.
- `COMELIT_LIVE_EXECUTED=false`: `static_safety_check.py` показал `COMELIT_ENDPOINTS_PRESENT=false`.
- `HA_DEPLOYED=false`: в этом child'е на host выполнялись только `python3 -m unittest` (focused / pins subset / discover), `scripts/static_safety_check.py`, `python3 -m compileall`, `git diff --check`, `git status`/`git diff --name-only`, `sha256sum`; HA deploy-команды не запускались.
- `HA_RELOADED=false`: тот же host command set; HA reload-команды не запускались.
- `HA_RESTARTED=false`: тот же host command set; HA restart-команды не запускались.
- `SYNTHETIC_TRIGGER_COUNT=0`: тот же host command set; synthetic-trigger команды не запускались.
- `DOOR_ACTIONS=0`: Door entrypoints не вызывались; protected-gates diff пуст.
- `GATE_ACTIONS=0`: Gate entrypoints не вызывались; protected-gates diff пуст.

Protected-gates diff vs accepted main:

```text
git diff --name-only 204ec3aa6cf7c6e8057b2336094675e7353c24f1 -- \
  custom_components/comelit/media_session.py custom_components/comelit/ring_media.py \
  custom_components/comelit/camera.py custom_components/comelit/__init__.py \
  custom_components/comelit/const.py custom_components/comelit/runtime.py \
  custom_components/comelit/native safety-poc/scripts
-> EMPTY
```

## Falsification evidence

```text
TEST_AGAINST_UNFIXED_CODE=FAILED (4 of 5 tests, measurement mismatches)
TEST_AGAINST_FIXED_CODE=OK
```

Host falsification command and result:

```text
cd /tmp/mvp1-sdp/flip-base/safety-poc
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=$PWD/src python3 -m unittest tests.test_mvp1_local_sdp_readiness_corrective
Ran 5 tests in 0.017s
FAILED (failures=4)
```

| test | что измерено против unfixed кода | исключение/строка assertion |
| --- | --- | --- |
| `test_a_delayed_sdp_readiness_blocks_async_start_until_ready` | `async_start()` вернулся до SDP-ready | `line 319: self.assertFalse(start_task.done())`; `AssertionError: True is not false` |
| `test_b_sdp_never_ready_fails_closed_without_retry` | active без SDP не дал fail-closed timeout | `AssertionError: ComelitMediaTransportError not raised` |
| `test_c_process_exit_between_active_and_sdp_ready_fails_without_hang` | отсутствует `_local_sdp_ready_event` в unfixed transport | `AssertionError: False is not true` |
| `test_d_manager_active_implies_sdp_ready_and_timeout_restores_listener` | manager перешел в active до SDP-ready | `line 393: self.assertEqual(manager.phase, media_session.MEDIA_PHASE_STARTING)`; `AssertionError: 'active' != 'starting'` |
| `test_e_preserve_single_flight_and_fail_before_sdp_ready` | single-flight preservation из PR #164 | PASS on unfixed code |

TEST E - preservation-тест уже смерженного single-flight fix (PR #164), он не зависит от transport-правки, поэтому на unfixed дереве он проходит штатно; это НЕ противоречие.

## Host-authoritative run

Focused:

```text
cd safety-poc
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=$PWD/src python3 -m unittest tests.test_mvp1_local_sdp_readiness_corrective
Ran 5 tests in 4.625s
OK
```

Pins subset:

```text
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=$PWD/src python3 -m unittest tests.test_p116_r18_hls_runtime_diagnostics tests.test_p116_r20_hls_http_boundary_diagnostics tests.test_mvp1_ring_telegram_offline_build
Ran 45 tests in 0.072s
OK
```

Full suite fixed tree:

```text
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=$PWD/src python3 -m unittest discover -s tests
Ran 1569 tests in 34.429s
FAILED (failures=1, skipped=1)
only failure = test_p116_provenance_binary_analysis.P116ProvenanceBinaryAnalysisTests.test_committed_build_metadata_records_historical_non_runtime_mismatch
```

Baseline accepted main `204ec3aa6cf7c6e8057b2336094675e7353c24f1`:

```text
Ran 1564 tests in 29.927s
FAILED (failures=1, skipped=1)
same single failure = ...NATIVE_BINARY_MODE 755 vs 775
branch_delta = +5 new tests
```

Static / compile / diff / status:

```text
python3 scripts/static_safety_check.py
STATIC_SAFETY_CHECK=PASS
NETWORK_IMPORTS_PRESENT=false
COMELIT_ENDPOINTS_PRESENT=false
SOURCE_FILES_SCANNED=29

python3 -m compileall -q custom_components/comelit
COMPILEALL_RC=0

git diff --check
DIFFCHECK_RC=0 (no output)

git status --short --untracked-files=all
 M custom_components/comelit/media_transport.py
 M safety-poc/tests/test_mvp1_ring_telegram_offline_build.py
 M safety-poc/tests/test_p116_r18_hls_runtime_diagnostics.py
 M safety-poc/tests/test_p116_r20_hls_http_boundary_diagnostics.py
?? docs/mvp1-local-sdp-readiness-corrective-result.md
?? safety-poc/tests/test_mvp1_local_sdp_readiness_corrective.py
```

Diff stat:

```text
custom_components/comelit/media_transport.py                      +38 -4
safety-poc/tests/test_mvp1_ring_telegram_offline_build.py          +1 -1
safety-poc/tests/test_p116_r18_hls_runtime_diagnostics.py          +1 -1
safety-poc/tests/test_p116_r20_hls_http_boundary_diagnostics.py    +1 -1
new: safety-poc/tests/test_mvp1_local_sdp_readiness_corrective.py  529 lines
new: docs/mvp1-local-sdp-readiness-corrective-result.md
```

## Hash-pin re-pin

Re-pin сделан в turn 2 из-за авторизованного изменения `custom_components/comelit/media_transport.py`. Это расширение файлового набора относительно исходных трех файлов и оно чисто механическое: 3 строки, 1 digest.

```text
OLD=fad1dacadf0655237bb8a72d0e7c29492c88362ea57128c81dfad48119a16c51
NEW=52e4873ede9c8df16f81ac88dba4c7ffaf27842738e22ab68896c216411aa1d0
(custom_components/comelit/media_transport.py; sha256sum on host)
files: test_p116_r18_hls_runtime_diagnostics.py:17, test_p116_r20_hls_http_boundary_diagnostics.py:19,
       test_mvp1_ring_telegram_offline_build.py:252
assertion itself unchanged (assertEqual(_sha256(TRANSPORT), EXPECTED_MEDIA_TRANSPORT_SHA256))
media_session.py / camera.py / native pins NOT touched
safety-poc/research/media/v1/P116_R30E_*.md NOT touched (historical phase record)
```

Host pins subset подтвердил, что проверка не ослаблена:

```text
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=$PWD/src python3 -m unittest tests.test_p116_r18_hls_runtime_diagnostics tests.test_p116_r20_hls_http_boundary_diagnostics tests.test_mvp1_ring_telegram_offline_build
Ran 45 tests in 0.072s
OK
```

Исторический документ `safety-poc/research/media/v1/P116_R30E_*.md` намеренно не переписывался: это phase record, а не текущий authoritative result.

## Sandbox-only artifacts

Sandbox run до host-authoritative подтверждения:

```text
sandbox full suite: Ran 1569 tests in 38.503s, FAILED failures=1 errors=2 skipped=5
host full suite: Ran 1569 tests in 34.429s, FAILED failures=1, skipped=1
```

Sandbox-only classification:

- `test_p116_r29i_preopen_idle_and_sink_ownership.*`: `NOT_A_LOCAL_SDP_READINESS_REGRESSION_SANDBOX_UDP_SINK`.
- В host-run этих ошибок нет: host failures=1, и это тот же pre-existing `...NATIVE_BINARY_MODE 755 vs 775`, который падает на accepted main.

## Observations and limits

- Offline tests prove source-level ordering and lifecycle behavior with controlled fake subprocess/executor boundaries; they do not prove the original live 2-7 ms race timing on hardware.
- Offline tests do not prove HA frontend/service observability of the new transport reason beyond transport/manager behavior.
- `ring_media.status()["recording_result"]["reason"]` behavior was not changed in this child; existing `media_start_failed`-level behavior remains outside this patch.
- Hash-pin re-pin is complete for `media_transport.py`; the assertion remains unchanged and host pins subset passes.
- No live RTP, Comelit cloud, HA Stream runtime, Door, Gate, reload or restart was exercised.
