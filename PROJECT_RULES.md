# Comelit — правила проекта

Статус: **consolidated project rules / working contract**  
Репозиторий: `alexsudakov/comelit`  
Область: исследование протокола Comelit ViP, safety-PoC, Home Assistant integration, CT120 validation, Door/Ring/media functionality.

Этот документ собирает правила, которые были приняты в рабочих диалогах проекта и подтверждены текущими архитектурными документами репозитория.

Он не заменяет доказанные phase-specific research contracts (`Pxx_*.md`) и нормативные архитектурные документы. Если конкретный protocol/research contract более новый и более узкий, он определяет факты соответствующей фазы; этот файл определяет общий способ работы и safety boundaries.

---

## 1. Приоритет правил

При конфликте использовать следующий порядок:

1. Явное указание пользователя для текущей задачи, если оно не отменяет уже зафиксированные safety-инварианты без отдельного осознанного решения.
2. Нормативные документы проекта:
   - `docs/ha-integration-target-architecture.md`
   - `docs/intercom-media-session-architecture.md`
3. Последний promoted phase-specific research contract в `safety-poc/research/...` для затрагиваемой области.
4. Этот `PROJECT_RULES.md`.
5. Старые сообщения, черновики, локальные заметки и superseded research artifacts.

Если правило или факт был доказан только для одной фазы/одного capture, не переносить его автоматически на другую фазу.

Если более новый документ явно отвергает старую гипотезу, старую гипотезу считать историей, а не альтернативным контрактом.

---

## 2. Целевая архитектура

### 2.1 Home Assistant — конечный runtime

Целевая архитектура — прямая Home Assistant integration:

```text
Home Assistant
  -> custom_components/comelit
  -> Comelit
```

Не вводить отдельный постоянный Comelit application server как третий production-слой.

### 2.2 Роль CT120

CT120 используется для:

- разработки;
- reverse engineering;
- offline/static analysis;
- controlled validation;
- хранения внешних research artifacts/captures, когда они не должны попадать в Git.

CT120 не является целевым production runtime для интеграции.

### 2.3 Persistent listener

Постоянная Ring/Door P2P/ViP session — отдельный 24x7 lifecycle domain.

Она не должна зависеть от on-demand media lifecycle.

Media start/stop не должен останавливать, пересоздавать или ломать persistent listener, если только отдельное protocol evidence не докажет необходимость такого перехода.

---

## 3. Git workflow

Для разработки действует правило:

```text
feature/research branch
→ offline tests
→ PR
→ CI
→ review
→ merge
```

Обязательные правила:

- не редактировать `main` напрямую;
- одна исследовательская/реализационная итерация — отдельная ветка;
- новая ветка должна базироваться на актуальном `main`;
- перед началом фиксировать/проверять baseline SHA;
- перед PR проверять diff и scope;
- merge выполнять только после обязательных CI/tests;
- после merge следующий этап начинать от нового актуального `main`, а не продолжать старую ветку как будто она является Source of Truth.

GitHub `main` — Source of Truth для принятых project artifacts.

Локальная копия, вывод старого скрипта или текст в диалоге не заменяет проверку фактического SHA в GitHub.

---

## 4. CI и тестирование

Минимальный PR gate включает применимые проверки репозитория, в том числе:

- `offline-safety`;
- `Validate HACS`;
- targeted tests новой фазы;
- полный regression suite, когда изменение затрагивает общий runtime/parser/contract.

Если обязательный test/gate не выполнялся или завершился ошибкой, не считать задачу завершённой.

`SKIPPED`, `NOT_PROVIDED`, `NOT_PROVEN` и `UNAVAILABLE` не преобразуются в PASS.

---

## 5. Общий research принцип: offline-first

Перед любым live experiment использовать максимально возможную цепочку:

```text
repository/code review
→ saved captures
→ static DEX/JNI/native analysis
→ deterministic synthetic/offline verifier
→ frozen-capture validation
→ только затем controlled live, если он всё ещё необходим
```

Live experiment не используется только потому, что он быстрее или проще.

Если contract можно доказать статически или на уже сохранённом capture — live запуск не нужен.

---

## 6. FACT / OBSERVED / PROVEN / NOT_PROVEN

В research artifacts необходимо различать минимум следующие состояния:

- `PROVEN` / `PROVEN_STATIC` / `PROVEN_OFFLINE` — правило действительно доказано заявленным методом;
- `OBSERVED` / `CAPTURE_VALIDATED` — наблюдалось в конкретном capture;
- `NOT_PROVEN` — данных недостаточно;
- `REJECTED` — гипотеза была проверена и отвергнута;
- `BLOCKED` — проверка невозможна без нового разрешения/источника;
- `DEFERRED` — вопрос сознательно оставлен на следующую фазу.

Нельзя повышать один наблюдавшийся scalar, порядок пакетов, target ID, address, sequence value или иной capture-specific byte до protocol generation contract без независимого подтверждения.

---

## 7. Capture-specific значения не являются константами

Значения из одного PCAP нельзя просто перенести в runtime implementation.

В частности:

- target/channel IDs должны генерироваться по доказанному allocator/runtime contract;
- session-specific state должен создаваться заново;
- captured addresses/identifiers не должны становиться caller-controlled constants;
- numeric sequential relation, замеченная в одном capture, не считается универсальным protocol rule без доказательства;
- observed packet order не считается total causal order, если доказан только partial order.

При необходимости frozen capture должен быть SHA-gated.

---

## 8. Никакого literal packet replay как реализации

Не использовать capture replay как production protocol implementation.

Даже controlled live probe должен генерировать session state по доказанным generation rules, а не отправлять сохранённый бинарный payload целиком.

Saved PCAP используется для анализа, regression validation и structural comparison, но не как источник готового runtime-сеанса.

---

## 9. Proprietary artifacts и чувствительные данные

Не коммитить в Git без отдельного явного решения:

- APK/DEX proprietary artifacts;
- native Comelit binaries;
- raw PCAP с потенциальными credentials/session material;
- raw media payload;
- OAuth/refresh/access tokens;
- passwords/keys;
- device/session authorization material.

В research docs/verifiers предпочтительно хранить:

- SHA256;
- semantic markers;
- offsets/structural evidence;
- bounded disassembly excerpts;
- counts/status fields;
- paths к внешнему artifact только когда это действительно нужно.

Не выводить secrets/raw authorization material в CI logs, diagnostics или user-visible output.

---

## 10. Live experiment требует отдельного разрешения

По умолчанию research phase считается **offline-only**.

Live transmission разрешается только когда:

1. offline/static evidence исчерпано;
2. сформулирован конкретный узкий вопрос, который невозможно закрыть иначе;
3. подготовлен bounded one-shot probe;
4. пользователь явно разрешил live запуск.

Наличие generator/serializer/state-machine code само по себе не означает разрешение отправить его в сеть.

Наличие `PROVEN_OFFLINE` не означает `LIVE_AUTHORIZED=true`.

---

## 11. Базовый live-probe safety contract

Если отдельная более новая фаза не утвердила иной controlled contract, применять следующий baseline:

- ровно **один live invocation** на одно пользовательское разрешение;
- **никакого automatic retry**;
- не выполнять literal replay capture;
- не отправлять второй CTPP OPEN в рамках probe, если он не был отдельно доказан и явно разрешён;
- regenerate session state;
- не выполнять Door action;
- не смешивать media research и Door validation;
- bounded internal timeout около 45 секунд и bounded outer timeout около 75 секунд, если конкретный probe не требует ещё более короткого лимита;
- после timeout/ошибки прекращать probe, а не повторять автоматически;
- log output должен быть semantic/bounded, без raw payload/secrets.

Любое расширение этого контракта — отдельное решение следующей фазы, а не молчаливое ослабление guardrails.

---

## 12. Persistent listener во время live research

Persistent Ring/Door listener должен оставаться работающим по умолчанию.

Если controlled experiment технически требует его остановить:

1. остановить только непосредственно перед экспериментом;
2. выполнить ровно разрешённый bounded experiment;
3. восстановить listener независимо от SUCCESS/FAIL/TIMEOUT;
4. проверить, что listener снова READY;
5. не оставлять систему в состоянии «listener выключен» после research step.

Останавливать listener «на всякий случай» нельзя.

---

## 13. Door safety — отдельный домен

Door control и media/ring research не смешиваются.

### 13.1 Во время media research

Запрещено отправлять Door action.

Media lifecycle, serializers, probes, cleanup и tests должны иметь явный invariant:

```text
DOOR_ACTION_SENT=false
```

### 13.2 Door operation

Когда задача действительно касается Door control:

- one operation → at most one actuation transport invocation;
- automatic retry запрещён;
- operation identity создаётся внутри integration/runtime;
- post-send ambiguity является terminal `UNKNOWN_OUTCOME`;
- protocol ACK не доказывает физическое открытие двери;
- `physical_effect_asserted=false`, пока нет отдельного физического feedback mechanism;
- прямой caller не управляет raw peer/output/protocol address.

### 13.3 Gate

`gate` нельзя считать идентичным `entrance`.

Door/media profile для gate должен быть независимо подтверждён прежде, чем стать production behavior.

---

## 14. Intercom media — только on-demand

Intercom-associated camera/media session нельзя держать постоянно.

Причина: активная Comelit media session может мешать подключению официального приложения или других пользователей.

Обязательные правила:

- media session запускается только по запросу;
- Home Assistant startup не запускает intercom video «для поддержания камеры live»;
- максимальная длительность одной upstream media session — **180 секунд** от фактического успешного старта;
- deadline абсолютный и не продлевается snapshot/viewer/recording/new lease;
- по deadline выполняется forced clean teardown;
- unload/reload/shutdown/error также должны освобождать upstream media resources;
- cleanup должен быть idempotent;
- пока concurrency не доказан, во всей integration допускается максимум **одна активная upstream intercom media session**;
- media lifecycle не вызывает Door;
- persistent listener остаётся отдельным lifecycle domain.

---

## 15. Один media session manager

Все intercom media consumers должны использовать одного владельца upstream lifecycle, концептуально:

```text
ComelitMediaSessionManager
```

Нельзя создавать отдельные независимые upstream sessions для:

- camera live view;
- snapshot;
- recording;
- будущего full-duplex conversation.

Snapshot/recording/viewer могут использовать lease/reason поверх одной текущей upstream session.

Ни один consumer не должен обходить manager и создавать второй upstream media transport самостоятельно.

---

## 16. Home Assistant media entities

Принятая модель:

- switch — явный manual start/force stop;
- active binary sensor — фактическое состояние upstream media session;
- remaining sensor — остаток абсолютного 180-second deadline;
- camera entity — потребитель lifecycle manager, а не постоянно открытая upstream session.

Запрошенное состояние switch и реальное состояние media session не должны смешиваться.

Если setup failed, active sensor остаётся inactive даже если пользователь включил switch.

Manual `turn_off` — force stop, который может прекратить текущие leases, включая запись.

---

## 17. Snapshot и recording

Snapshot при inactive media:

```text
acquire short media lease
→ дождаться decodable frame/IDR
→ JPEG
→ release lease
→ stop upstream session, если других leases нет
```

Snapshot не должен оставлять media session открытой до 180 секунд без другой причины.

Ring recording baseline:

```text
ring
→ start media
→ snapshot
→ record 60 seconds
→ release recording lease
→ stop media, если других leases нет
```

Recording не зависит от того, открыта ли Door, проигнорирован ли звонок или позже начат разговор.

Conversation audio recording не входит в scope.

---

## 18. Entrance и Gate нельзя объединять без evidence

Текущий исследовательский media target — `entrance`, пока gate не прошёл отдельную validation.

Нельзя предполагать, что:

- media signaling одинаков;
- camera profile одинаков;
- address/target roles одинаковы;
- Door output одинаков;
- timeout/resource behavior одинаков.

Общие механизмы можно переиспользовать только после того, как panel-specific contract подтверждён.

---

## 19. Ordinary RTSP cameras и intercom cameras — разные классы

Обычные RTSP cameras могут иметь обычную модель live-view.

На intercom cameras нельзя автоматически переносить обычную RTSP модель, потому что upstream session имеет ресурсные/concurrency ограничения.

Для intercom camera приоритет — корректный lifecycle/release, а не постоянная доступность потока.

---

## 20. Media PoC acceptance gates

До production exposure camera/switch/recording необходимо доказать минимум:

1. entrance self-activation запускает valid media session on demand;
2. H.264 можно декодировать в still image и playable short recording;
3. teardown реально освобождает Comelit media session;
4. repeated start/stop не оставляет process/socket/session leaks;
5. persistent listener продолжает работать до, во время и после media;
6. official Comelit client снова может подключиться после нашего stop;
7. 180-second timeout освобождает session даже при оставшемся local viewer;
8. Door action нигде не emitted;
9. одновременно существует не более одной upstream intercom media session, пока concurrency не валидирована отдельно;
10. gate не экспонируется как копия entrance без отдельного validation.

---

## 21. Protocol generation: semantic state, а не capture bytes

Новые serializers/state machines должны работать с semantic state:

- dynamic target IDs;
- allocator state;
- observed OPEN/RESPONSE facts;
- proven binding relations;
- proven partial causal order.

Не кодировать capture packet numbers/target IDs как runtime constants.

Если ordering доказан только частично, implementation должен проверять только доказанные causal constraints, а не искусственный total order.

---

## 22. Negative tests обязательны

Для protocol contract недостаточно happy path.

Нужно проверять reject/fail-closed случаи, соответствующие фазе, например:

- malformed frame;
- response-before-open;
- unknown/ambiguous target;
- duplicate response;
- reused allocation;
- wrong binding;
- missing prerequisite;
- forbidden literal captured constant;
- unexpected second invocation;
- retry attempt;
- Door action from media path.

Неполная/неоднозначная sequence должна завершаться как incomplete/invalid, а не автоматически «достраиваться» предположениями.

---

## 23. Fail closed

Если protocol prerequisite не доказан или runtime state неоднозначен:

- не генерировать следующий network action «по догадке»;
- не подставлять captured literal;
- не retry;
- не переходить к Door/media side effect;
- вернуть controlled failure / NOT_PROVEN / BLOCKED в зависимости от контекста.

Safety имеет приоритет над попыткой «довести эксперимент до успеха».

---

## 24. История исследований должна сохраняться

Не переписывать старые Pxx documents так, чтобы создавалось впечатление, будто гипотеза никогда не существовала.

Новый этап должен:

- ссылаться на предыдущий evidence;
- явно указывать promoted/rejected/superseded relation;
- сохранять полезные history markers;
- не менять прошлые результаты задним числом ради «чистой истории».

Это особенно важно для rejected hypotheses и перехода от capture observation к static/offline contract.

---

## 25. Один узкий следующий шаг

В рабочих диалогах использовать итерационный режим.

Предпочтительно:

```text
один конкретный вопрос
→ один bounded test/analysis
→ пользователь возвращает результат
→ анализ результата
→ следующий шаг
```

Не выдавать пользователю одновременно длинную цепочку live-команд, где результат шага 2 зависит от неизвестного результата шага 1.

Offline preparation можно объединять шире, если она не создаёт side effects.

---

## 26. Команды для пользователя

Когда требуется ручной запуск на CT120/HA/другом host:

- давать законченный copy-paste block;
- по возможности включать preflight/check/output markers;
- не требовать вручную собирать команду из нескольких фрагментов ответа;
- пояснение давать на русском языке;
- после команды, результат которой определяет следующий шаг, дождаться фактического output пользователя и только затем выбирать следующую команду.

Не просить повторно данные, которые пользователь уже прислал в текущем проекте.

---

## 27. Hermes task prompts

Если для Comelit используется Hermes, пользователь должен получать полный готовый task prompt одним copy-paste блоком.

Prompt должен явно фиксировать:

- TASK/GOAL;
- branch/base;
- allowed files/scope;
- prohibited actions;
- offline/live authorization;
- Door guard;
- listener guard;
- expected tests;
- required output markers;
- PR/merge boundary, если применимо.

Не оставлять критические safety-правила подразумеваемыми.

---

## 28. Web research

Не выполнять внешний web search без практической необходимости.

Приоритет источников для reverse engineering:

1. код проекта;
2. сохранённые captures/artifacts;
3. официальные app binaries/static provenance;
4. runtime logs;
5. только затем внешние материалы, если они действительно нужны.

Внешний источник не должен автоматически заменять локально доказанный protocol contract.

---

## 29. Deployment в Home Assistant — отдельный этап

Merge в GitHub не означает автоматическое обновление установленной integration в Home Assistant.

После merge production update через HACS/reload/restart выполняется отдельным шагом и только когда соответствующая реализация готова к deployment.

Перед update сравнивать установленную и последнюю версию/commit.

После update/restart проверять logs и health/listener status до перехода к следующей production validation.

Research-only Pxx change не требует deployment в HA, если runtime integration не менялась.

---

## 30. Listener diagnostics

Persistent listener status должен быть наблюдаем из Home Assistant/диагностики, а не требовать каждый раз отдельного shell-script.

Минимальная семантика должна различать состояния вроде:

- ready/active;
- reconnecting/starting;
- unavailable/error.

Нельзя подменять фактическое состояние listener только записью «последний раз был READY».

---

## 31. Не путать ACK с физическим эффектом

Для Door и других side effects protocol acknowledgement означает только подтверждённый protocol outcome в пределах доказанного contract.

Он не доказывает:

- что дверь физически открылась;
- что затвор/реле реально сработал;
- что пользователь получил ожидаемый physical effect.

Физический effect можно утверждать только при отдельном feedback/controlled validation.

---

## 32. Не расширять scope незаметно

Если задача — media research:

- не менять Door behavior;
- не менять gate profile без gate evidence;
- не внедрять full-duplex conversation;
- не включать production camera entities до acceptance gate;
- не менять listener lifecycle без необходимости.

Если задача — Door:

- не менять media protocol «заодно».

Каждый новый рискованный domain получает собственную фазу и тесты.

---

## 33. Full-duplex — последующая фаза

Финальная цель включает bidirectional conversation, но она не должна ускорять текущий media PoC ценой ослабления lifecycle/safety rules.

Будущий conversation path должен использовать тот же media session manager.

Не создавать второй параллельный upstream conversation session manager.

До отдельного решения сохранять 180-second media ceiling и запрет recording conversation audio.

---

## 34. Current phase authorization всегда проверяется отдельно

Нельзя считать, что прошлое разрешение на один live experiment распространяется на следующую фазу.

Каждый live research step требует нового явного approval пользователя.

При подготовке следующей фазы сначала читать latest promoted research contract.

На момент создания этого документа `main` содержит P75, где control/media state machine доказана offline, но live transmission не авторизована. Более новый merged phase contract может изменить именно этот phase gate, но только явно.

---

## 35. Definition of Done для research iteration

Research iteration завершена, когда применимые пункты выполнены:

- branch создан от актуального main;
- вопрос фазы сформулирован узко;
- evidence sources перечислены;
- offline/static analysis выполнен первым;
- generation contract не основан на capture literals;
- positive tests PASS;
- negative/fail-closed tests PASS;
- proprietary artifacts/secrets не попали в Git/logs;
- `DOOR_ACTION_SENT=false` для media research;
- `NETWORK_IO_PERFORMED=false`, если фаза offline-only;
- live не выполнялся без approval;
- diff reviewed;
- CI PASS;
- PR создан и merged только после gate;
- remaining unknowns перечислены явно;
- следующий этап не объявлен доказанным заранее.

---

## 36. Явно запрещённые anti-patterns

- direct commit/edit в `main`;
- production implementation через PCAP literal replay;
- captured target ID/address как постоянная runtime constant;
- автоматический retry Door/live probe;
- второй live invocation без нового approval;
- Door action в media research;
- оставленный выключенным listener после controlled test;
- постоянно открытая intercom media session;
- продление 180-second deadline новым viewer/snapshot/lease;
- параллельные upstream intercom sessions до доказанной concurrency;
- утверждение physical Door success только по ACK;
- перенос entrance contract на gate без validation;
- commit proprietary APK/DEX/native/raw capture payload без отдельного решения;
- вывод secrets/raw auth material;
- `NOT_PROVEN` → guessed implementation;
- observed capture order → invented total causal order;
- merge research-only PR → автоматический HA deploy;
- «agent/script сказал PASS» без проверки фактических tests/diff/artifacts.

---

## 37. Канонические документы

Всегда читать вместе с этим файлом:

- [`docs/ha-integration-target-architecture.md`](docs/ha-integration-target-architecture.md)
- [`docs/intercom-media-session-architecture.md`](docs/intercom-media-session-architecture.md)
- latest relevant promoted contract under `safety-poc/research/`
- [`README.md`](README.md) для текущей production capability/safety summary.

Для текущего media research baseline также полезен latest file в:

```text
safety-poc/research/media/v1/
```

Не ориентироваться только на номер этапа, запомненный из старого диалога: сначала проверить актуальный `main`.

---

## 38. Краткий checklist перед следующим research step

```text
[ ] Проверен актуальный main SHA
[ ] Прочитан latest promoted Pxx contract
[ ] Сформулирован один конкретный unknown
[ ] Проверено: можно ли закрыть его offline/static
[ ] Создана отдельная branch
[ ] Capture literals не становятся generation constants
[ ] Door path не затрагивается
[ ] Listener сохраняется, если его остановка не обязательна
[ ] Live transmission по умолчанию запрещена
[ ] Если live всё же нужен — получено отдельное explicit approval
[ ] Один approval = один bounded invocation, без retry
[ ] Raw payload/secrets не выводятся
[ ] Positive + negative tests PASS
[ ] offline-safety + HACS validation PASS
[ ] PR review/CI PASS до merge
[ ] HA update выполняется отдельно, только если менялся production runtime
```
