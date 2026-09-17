# Задача Hermes — P116 / R30H-C offline corrective для musl launcher

TASK_ID=`COMELIT-P116-R30H-C-MUSL-LAUNCHER-OFFLINE-CORRECTIVE`

MODE=`OFFLINE_ONLY`

Статус разрешения: `AUTHORIZED_OFFLINE_ONLY`.

Пользователь после результата R30H-B `INCONCLUSIVE` поручил продолжить предложенный offline corrective execution boundary. Это разрешение не включает ни одной новой live-попытки.

## 1. Роли

- Hermes — только оркестратор: Git, подготовка isolated repo/worktree/full clone, запуск проверок, CT120 offline relay, независимая проверка фактов, commit/push/PR attempt.
- Всю семантическую диагностику и написание/изменение executable research-кода выполняет один bounded контекст Codex CLI.
- Hermes не пишет executable-код самостоятельно.
- Используй один Codex session на весь R30H-C; при необходимости продолжай через `codex exec resume`, а не создавай новый semantic child.
- Если задача требует расширения за установленный scope, STOP и верни точный blocker.

## 2. Source bootstrap

На CT120 сначала выполни свежий authenticated fetch `origin/main` и используй фактический latest accepted main.

На момент постановки задачи ожидаемый accepted main:

```text
ef4d9cd832d262564e80b1efaaf1b84e1c5b4ee9
```

Если `origin/main` уже новее — не откатывай его.

Для GitHub в каждом используемом clone/worktree Comelit настрой repo-local credential helper:

```bash
git config credential.helper 'store --file=/root/.config/git/comelit.credentials'
git config credential.useHttpPath true
```

Обязательные требования:

- `/root/.config/git/comelit.credentials` существует;
- права файла `600`;
- содержимое credential-файла никогда не выводится;
- remote URL не содержит token;
- origin остаётся вида `https://github.com/alexsudakov/comelit.git`;
- authenticated `git fetch origin main` проходит успешно.

Прочитай минимум:

```text
safety-poc/research/media/v1/P116_R30H_C_MUSL_LAUNCHER_OFFLINE_CORRECTIVE_CONTRACT.md
safety-poc/research/media/v1/P116_R30H_B_REPEAT_001A_LIVE_PROOF_RESULT.md
safety-poc/research/media/v1/P116_R30H_A_REPEAT_001A_OFFLINE_REVALIDATION_RESULT.md
safety-poc/research/media/v1/P116_R30H_B_REPEAT_001A_LIVE_PROOF_CONTRACT.md
safety-poc/research/media/v1/ct120_run_p116_r27_repeat_001a_live.sh
safety-poc/research/media/v1/ct120_run_p116_r30h_a_repeat_001a_offline_preflight.sh
safety-poc/research/media/v1/ct120_build_p80_haos_media_helper.sh
safety-poc/research/media/v1/entrance_p116_r27_repeat_001a_transform.py
safety-poc/tests/test_p116_r27_repeat_001a_contract.py
```

## 3. Цель

Исправить ровно дефект R30H-B:

```text
raw musl candidate ELF
-> direct exec на glibc CT120
-> /lib/ld-musl-x86_64.so.1 отсутствует
-> cannot execute: required file not found
```

После R30H-C будущий live runner должен иметь цепочку:

```text
materialized wrapper
-> per-run candidate launcher
-> explicit musl loader
-> exact candidate ELF
-> explicit packaged runtime library path
```

R30H-C должен доказать эту цепочку полностью offline.

## 4. Жёсткие запреты

Во время всей задачи:

```text
R27_LIVE_RUN=YES запрещён
COMELIT_LIVE_EXECUTED=false
LIVE_INVOCATIONS=0
PRODUCTION_LISTENER_TOUCHED=false
HA_TOUCHED=false
HA_RESTARTED=false
HA_RELOADED=false
HA_DEPLOYED=false
DOOR_ACTIONS=0
GATE_ACTIONS=0
RAW_MEDIA_CAPTURE=false
RAW_PCAP_CAPTURE=false
```

Не вызывай webhook stop/start/status Home Assistant для этой задачи. Не трогай production listener вообще.

Не устанавливай musl/loader в host `/lib`, `/usr/lib`, `/usr/local/lib`. Не меняй `ldconfig`, system loader config или host packages.

Не запускай candidate `main()` в R30H-C. Цель — доказать loader resolution и wrapper/launcher binding, не сетевое поведение helper.

## 5. Подготовка репозитория

Используй чистый isolated clone или worktree. Если scripts требуют `.git` каталог, допустим отдельный полный clone, как в R30H-A/B.

Перед Codex зафиксируй:

```text
FRESH_MAIN_FETCHED=true
ACCEPTED_MAIN_SHA=<sha>
REPO_HEAD=<sha>
REPO_HEAD_EQUALS_ACCEPTED_MAIN=true
WORKTREE_CLEAN=true
REMOTE_CREDENTIAL_FREE=true
CREDENTIAL_FILE_MODE_OK=true
```

Создай bounded branch, например:

```text
research/p116-r30h-c-musl-launcher-offline-corrective
```

## 6. Один bounded Codex context

Передай Codex контракт и source bootstrap. Разрешённый write scope:

```text
safety-poc/research/media/v1/ct120_run_p116_r27_repeat_001a_live.sh
safety-poc/tests/test_p116_r27_repeat_001a_contract.py
safety-poc/research/media/v1/ct120_run_p116_r30h_c_musl_launcher_offline.sh
safety-poc/research/media/v1/P116_R30H_C_MUSL_LAUNCHER_OFFLINE_CORRECTIVE_RESULT.md
```

Дополнительно разрешается минимальная правка:

```text
safety-poc/research/media/v1/ct120_build_p80_haos_media_helper.sh
```

только если builder сейчас не выдаёт machine-readable путь к реально выбранному rootfs. Такая правка не должна менять source generation, compiler flags, ABI, binary contents или packaged artifacts.

Запрещено менять:

```text
custom_components/comelit/**
safety-poc/research/media/v1/entrance_p116_r27_repeat_001a_transform.py
```

Если Codex считает изменение transform необходимым — STOP, не расширяй scope автоматически.

## 7. Требуемая реализация corrective

Codex должен устранить raw-candidate substitution в будущем live runner.

Требуется materialize per-run launcher, который normal-mode запускает candidate через explicit musl loader и explicit library path.

Loader должен происходить из того же builder-selected Alpine rootfs, который использовался для candidate build. Не использовать произвольный системный loader.

Предпочтительный путь:

1. Получить exact builder rootfs path из build provenance.
2. Проверить `${ROOTFS}/lib/ld-musl-x86_64.so.1`.
3. Записать loader SHA256.
4. Скопировать loader в текущий run-root или доказать безопасное использование exact rootfs loader path.
5. Проверить SHA после копирования, если копирование выполнялось.
6. Использовать explicit runtime library path из `custom_components/comelit/native/lib`.
7. Создать owner-executable launcher без fallback.
8. Materialized Comelit wrapper должен подставлять launcher, а не raw candidate.

Не добавлять retry, refresh loop, protocol behavior или новую media session.

## 8. Offline loader probe

До признания corrective готовым реально запусти loader-native probe над exact candidate без входа в candidate `main()`.

Используй `ld-musl` dependency/list mode или эквивалентный no-main loader probe, подтверждённый фактическим loader на CT120.

Нельзя ограничиться только `readelf`/`file`/`strings`.

Обязательные факты:

```text
LOADER_PROBE_EXECUTED=true
LOADER_PROBE_RC=0
LOADER_PROBE_RESOLUTION=PASS
CANDIDATE_MAIN_EXECUTED=false
CANDIDATE_SHA_GATE=PASS
CANDIDATE_INTERPRETER_MATCH=PASS
GLIBC_RESOLUTION_USED=false
COMELIT_NETWORK_REQUESTS=0
```

Dependency output должен быть bounded/sanitized. Не коммить credentials или sensitive environment.

Если probe показывает missing dependency, неправильный loader, glibc fallback или иной unresolved runtime edge — исправляй внутри текущего bounded Codex scope, если это обычный implementation defect. Если потребуется системная установка/архитектурное изменение — STOP.

## 9. Wrapper/launcher gate

После исправления независимо проверь Hermes'ом, а не только по self-report Codex:

```text
BASE_HOLDER_PATH_PRESENT_IN_CANDIDATE_WRAPPER=false
RAW_CANDIDATE_PATH_PRESENT_AS_HOLDER=false
CANDIDATE_LAUNCHER_PATH_PRESENT_IN_CANDIDATE_WRAPPER=true
CANDIDATE_LAUNCHER_OCCURRENCES=1
BASE_WRAPPER_PATH_OCCURRENCES=0
CANDIDATE_WRAPPER_PARSE=PASS
WRAPPER_BINDING_GATE=PASS
LAUNCHER_LOADER_PATH_MATCH=true
LAUNCHER_CANDIDATE_PATH_MATCH=true
LAUNCHER_LIBRARY_PATH_MATCH=true
LAUNCHER_BASE_HELPER_FALLBACK=false
```

Отдельно проверь, что exact raw candidate ELF по-прежнему существует и SHA совпадает с build provenance; отсутствие raw path как holder означает только отсутствие direct-exec, а не отсутствие candidate artifact.

## 10. Сохранение R27 semantics

Повтори focused contract module. Должны остаться истинны:

```text
INITIAL_001A_MAX_COUNT=1
REPEAT_001A_MAX_COUNT=1
TOTAL_001A_MAX_COUNT=2
THIRD_001A_FAIL_CLOSED=true
REPEAT_AFTER_INITIAL_ACK=true
REPEAT_AFTER_MEDIA_ACTIVE=true
REPEAT_REQUIRES_VIDEO_PROGRESS=true
R27_REPEAT_DELAY_SECONDS=20
R27_REPEAT_DELAY_IS_PROTOCOL_CONSTANT=false
R27_REPEAT_DELAY_PROMOTED_TO_PRODUCTION=false
ACK_TIMEOUT_RETRY=false
NO_NEW_SESSION_SETUP_PATHS=true
```

Generated source SHA должен остаться:

```text
1c9f13cff0d1d3599e00109146310c7372b1b0ae12117bb46ad68f091a841d42
```

Если изменился — `RESULT=BLOCKED_SOURCE_DRIFT`; pin не переписывать.

## 11. Новый offline harness

Создай:

```text
safety-poc/research/media/v1/ct120_run_p116_r30h_c_musl_launcher_offline.sh
```

Он должен:

- отказать без явного `R30H_C_OFFLINE_RUN=YES`;
- отказать если `R27_LIVE_RUN=YES` присутствует;
- не принимать/не требовать HA webhook/token;
- не останавливать listener;
- не выполнять candidate main;
- выполнить build/provenance gates;
- materialize launcher и corrected wrapper;
- выполнить loader no-main probe;
- вывести финальный итоговый блок только в конце;
- вернуть non-zero при любом обязательном gate failure.

Не смешивать итоговый блок с промежуточным шумом. В финале должны быть только безопасные скаляры.

## 12. Тесты

Запусти как минимум:

```text
python compile для изменённых Python-файлов
bash -n для runner/builder/harness/launcher materialization
focused test_p116_r27_repeat_001a_contract.py
новые/обновлённые tests для R30H-C launcher binding
repository offline-safety suite
```

Если broad suite содержит pre-existing failures, докажи это сравнением с fresh accepted main и не маскируй их изменением unrelated tests.

## 13. Независимая верификация Hermes

После Codex Hermes должен самостоятельно подтвердить:

- diff находится только в разрешённом scope;
- generated source SHA не изменился;
- candidate build provenance валиден;
- loader probe действительно исполнялся и exit 0;
- candidate main не запускался;
- wrapper содержит launcher ровно один раз;
- wrapper не содержит raw candidate как holder;
- launcher содержит exact loader/candidate/library paths;
- base helper fallback отсутствует;
- `R27_LIVE_RUN=NO` refusal происходит до любых listener/network side effects;
- `custom_components/comelit/**` не менялся;
- Door/Gate/HA/listener не затрагивались.

## 14. Result document

Codex должен создать:

```text
safety-poc/research/media/v1/P116_R30H_C_MUSL_LAUNCHER_OFFLINE_CORRECTIVE_RESULT.md
```

Документ должен разделять:

- source/main identity;
- R30H-B blocker;
- corrective design;
- loader provenance;
- candidate provenance;
- no-main loader probe;
- wrapper/launcher binding;
- preserved R27 semantics;
- tests;
- forbidden-action evidence;
- точный result class;
- что ещё НЕ доказано.

## 15. Result class

Разрешённые классы:

```text
PASS_EXECUTION_PATH_READY
BLOCKED_SOURCE_DRIFT
BLOCKED_LOADER_PROBE
FAIL_WRAPPER_LAUNCHER_BINDING
INCONCLUSIVE
```

`PASS_EXECUTION_PATH_READY` означает только, что execution blocker R30H-B закрыт offline. Он не означает, что repeat `0x001A` продлевает RTP, и не разрешает live.

## 16. GitHub completion

После PASS/корректной terminal classification:

- commit bounded diff;
- push branch с repo-local credential helper;
- попытайся создать PR;
- если PAT снова не имеет `createPullRequest`, верни branch + exact remote head SHA;
- token не выводить и не помещать в remote URL.

## 17. Обязательный финальный блок

Финальный вывод Hermes должен завершаться отдельным блоком:

```text
=== COMELIT P116 R30H-C MUSL LAUNCHER OFFLINE CORRECTIVE ===
TASK_ID=COMELIT-P116-R30H-C-MUSL-LAUNCHER-OFFLINE-CORRECTIVE
BASE_SHA=<sha>
R30H_B_RESULT=INCONCLUSIVE
CANDIDATE_SOURCE_SHA256=<sha>
CANDIDATE_BINARY_SHA256=<sha>
CANDIDATE_INTERPRETER=/lib/ld-musl-x86_64.so.1
BUILDER_ROOTFS_MODE=<mode>
SOURCE_MUSL_LOADER_SHA256=<sha>
RUN_MUSL_LOADER_SHA256=<sha-or-same-path>
LOADER_COPY_SHA_GATE=<PASS|NOT_COPIED>
LOADER_PROBE_EXECUTED=<true|false>
LOADER_PROBE_RC=<n>
LOADER_PROBE_RESOLUTION=<PASS|FAIL>
CANDIDATE_MAIN_EXECUTED=false
GLIBC_RESOLUTION_USED=false
WRAPPER_BINDING_GATE=<PASS|FAIL>
RAW_CANDIDATE_PATH_PRESENT_AS_HOLDER=false
CANDIDATE_LAUNCHER_PATH_PRESENT_IN_CANDIDATE_WRAPPER=true
LAUNCHER_LOADER_PATH_MATCH=<true|false>
LAUNCHER_CANDIDATE_PATH_MATCH=<true|false>
LAUNCHER_LIBRARY_PATH_MATCH=<true|false>
ONE_SHOT_REPEAT_CONTRACT=<PASS|FAIL>
EXPECTED_SOURCE_SHA_GATE=<PASS|FAIL>
R27_REPEAT_DELAY_SECONDS=20
R27_REPEAT_DELAY_IS_PROTOCOL_CONSTANT=false
R27_REPEAT_DELAY_PROMOTED_TO_PRODUCTION=false
COMELIT_LIVE_EXECUTED=false
LIVE_INVOCATIONS=0
PRODUCTION_LISTENER_TOUCHED=false
HA_TOUCHED=false
DOOR_ACTIONS=0
GATE_ACTIONS=0
CUSTOM_COMPONENTS_TOUCHED=false
RESULT_DOC=safety-poc/research/media/v1/P116_R30H_C_MUSL_LAUNCHER_OFFLINE_CORRECTIVE_RESULT.md
BRANCH=<branch>
REMOTE_HEAD=<sha>
PR=<number|none>
RESULT=<result-class>
=== END COMELIT P116 R30H-C MUSL LAUNCHER OFFLINE CORRECTIVE ===
```

## 18. STOP

После R30H-C остановись.

Не запускай R30H-D/live автоматически. Даже при `PASS_EXECUTION_PATH_READY` следующая live-попытка требует отдельного явного разрешения пользователя.
