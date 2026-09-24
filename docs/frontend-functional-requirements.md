# Функциональные требования — Comelit UI

Статус: **approved user requirements baseline, amended after standard HA camera validation**  
Дата: 2026-09-24  
Область: Home Assistant Custom Card и Telegram Mini App для Comelit

## 1. Назначение

Документ фиксирует пользовательские и функциональные требования к единому интерфейсу Comelit для:

- домофона;
- двустороннего разговора;
- открытия соответствующей двери/калитки;
- просмотра камер видеонаблюдения;
- дальнейшей реализации интерфейса как Home Assistant Custom Card и/или Telegram Mini App.

Требования дополняют:

- `docs/ha-integration-target-architecture.md`;
- `docs/intercom-media-session-architecture.md`.

При конфликте safety/lifecycle правил приоритет имеют более строгие утверждённые protocol/safety contracts проекта.


## 2. Общая структура страницы

Интерфейс MUST иметь две верхнеуровневые вкладки:

```text
[ Домофон ] [ Видеонаблюдение ]
```

Обе реализации — Home Assistant Custom Card и Telegram Mini App — MUST использовать одинаковую логическую структуру, но источники данных для двух вкладок различаются:

- «Домофон» получает состояние, capabilities и semantic actions из `custom_components/comelit`;
- «Видеонаблюдение» работает со стандартными Home Assistant `camera.*` entities и не требует, чтобы обычная камера была известна интеграции Comelit.

Frontend MUST NOT требовать изменения собственного кода при добавлении новой surveillance camera, уже опубликованной в Home Assistant как стандартная `camera.*` entity и включённой в configured surveillance set.

Surveillance set SHOULD определяться средствами Home Assistant, предпочтительно через HA label; явный allowlist MAY использоваться как fallback или override. Frontend MUST NOT автоматически включать вообще все `camera.*` entities Home Assistant.

Raw RTSP/HTTP source URLs, usernames, passwords и иные camera credentials MUST NOT передаваться во frontend и MUST NOT становиться частью публичного UI contract.

## 3. Вкладка «Домофон»

### 3.1 Состав

Во вкладке MUST отображаться ровно две логические точки домофона:

```text
Подъезд
Калитка
```

Логические идентификаторы:

```text
entrance
gate
```

Каждая точка имеет собственную:

- камеру;
- call/media state;
- входящую call identity;
- связанную дверь;
- кнопку открытия;
- capability двустороннего разговора после его отдельной protocol validation.

### 3.2 Жёсткая привязка действий

Frontend MUST NOT угадывать, какую дверь следует открыть.

Связи фиксированы:

```text
entrance camera/call -> entrance door
gate camera/call     -> gate door
```

Кнопка открытия MUST вызывать только semantic backend action для текущей логической точки.

Raw Comelit peer address, output index, protocol target, device id или иные низкоуровневые параметры MUST NOT передаваться пользователем или frontend.

### 3.3 Обычный просмотр

В отсутствие активного звонка пользователь может выбрать:

- «Подъезд»;
- «Калитка».

Просмотр камеры не должен автоматически начинать разговор и не должен включать микрофон.

Обычный camera view должен использовать уже утверждённый on-demand media lifecycle и не создавать постоянную upstream Comelit media session.

Если конкретная intercom camera ещё не прошла required protocol/media validation, UI MUST показывать её как недоступную, а не имитировать рабочую функцию.

## 4. Входящий звонок

При входящем звонке интерфейс MUST:

1. открыть или приоритетно показать вкладку «Домофон»;
2. выбрать именно вызывающую логическую точку;
3. показать источник звонка;
4. показать associated camera;
5. предложить только действия, допустимые для этой точки и текущего состояния.

Минимальный UI:

```text
Входящий звонок: Подъезд / Калитка

[ Ответить ] [ Открыть ] [ Игнорировать ]
```

Семантика:

- **Ответить** — начать full-duplex conversation только после соответствующей protocol validation;
- **Открыть** — открыть только дверь, связанную с вызывающей точкой;
- **Игнорировать** — прекратить пользовательскую обработку уведомления; это не должно самопроизвольно генерировать непроверенную Comelit reject/hangup operation.

## 5. Активный разговор

### 5.1 Общие требования

После ответа conversation MUST оставаться привязанным к исходной логической точке на всё время вызова.

Пример:

```text
active_call_panel = entrance
```

означает, что до завершения вызова:

```text
audio RX -> entrance
audio TX -> entrance
door action -> entrance
hangup -> entrance call/session
```

Conversation audio MUST NOT записываться.

Conversation MUST использовать существующий Comelit media/session ownership model и не создавать второй независимый upstream Comelit session manager.

### 5.2 Запрет переключения между домофонами

Во время активного разговора MUST NOT быть возможности переключить изображение или разговор:

```text
Подъезд -> Калитка
Калитка -> Подъезд
```

То есть другая домофонная точка MUST NOT становиться selectable camera target до завершения текущего разговора.

Это правило действует даже если технически видеопоток второй панели может быть доступен.

Frontend MUST визуально сохранять идентичность активного разговора и не допускать неоднозначности между:

- камерой разговора;
- аудиоканалом;
- кнопкой открытия;
- hangup action.

### 5.3 Просмотр других камер во время разговора

Во время активного разговора пользователь MAY переключиться во вкладку «Видеонаблюдение» и смотреть любую доступную обычную камеру.

Такое переключение MUST NOT:

- менять `active_call_panel`;
- перенаправлять microphone audio;
- менять remote audio source;
- менять associated door;
- завершать conversation lease;
- начинать новый intercom conversation;
- открывать вторую intercom media session.

Разговор продолжает быть связан с исходной домофонной точкой.

Пользователь MAY вернуться из «Видеонаблюдения» к текущей активной домофонной точке.

Пользователь MUST NOT во время этого же разговора перейти к другой домофонной точке.

### 5.4 Завершение разговора

Hangup MUST:

1. завершить conversation media TX/RX;
2. выполнить утверждённый Comelit call/media teardown;
3. освободить conversation lease;
4. восстановить persistent listener согласно действующему lifecycle contract;
5. вернуть UI в обычный режим.

Если teardown не подтверждён, backend MUST fail closed согласно `docs/intercom-media-session-architecture.md`.


## 6. Вкладка «Видеонаблюдение»

### 6.1 Состав и ownership

Во вкладке MUST отображаться выбранные обычные камеры видеонаблюдения, опубликованные Home Assistant как стандартные `camera.*` entities.

Обычные surveillance cameras MUST NOT принадлежать runtime/lifecycle интеграции Comelit. Они могут быть созданы любой подходящей HA integration, например Generic Camera, ONVIF или другой camera integration.

Интеграция Comelit MUST оставаться владельцем только intercom-specific функций:

- `entrance` / `gate`;
- incoming call state;
- intercom media/session lifecycle;
- conversation audio;
- associated Door semantic actions.

Камеры `entrance` и `gate` MUST NOT дублироваться во вкладке «Видеонаблюдение», даже если соответствующие intercom views представлены в HA как `camera.*`.

### 6.2 Выбор surveillance entities

Frontend MUST NOT содержать hardcoded transport catalog, RTSP ports или Comelit-specific список surveillance endpoints.

Набор камер SHOULD формироваться из Home Assistant entity/label configuration. Предпочтительный механизм:

```text
standard HA camera.* entities
        +
configured HA label
        |
        v
surveillance set
```

Explicit entity allowlist MAY использоваться как override/fallback.

Добавление новой камеры в surveillance set MUST NOT требовать изменения `custom_components/comelit` и SHOULD NOT требовать изменения frontend-кода.

### 6.3 Нормализованная frontend model

Для ordinary surveillance camera frontend достаточно нормализованной модели, эквивалентной:

```text
entity_id
display_name
group: surveillance
availability
source_kind: home_assistant_camera
capabilities
```

Минимальные capabilities:

```text
video
snapshot
fullscreen
audio_rx
```

Capability MUST отражать реально доступную функцию Home Assistant/player, а не предположение по типу RTSP source.

Intercom-only capabilities:

```text
audio_tx
call
door_open
associated_door
```

MUST поступать только из Comelit intercom model и MUST NOT выводиться из обычной `camera.*` entity.

### 6.4 Дедупликация

Если одна физическая surveillance camera представлена несколькими HA entities, UI MAY показывать одну логическую камеру только при наличии явного mapping или достоверного HA/backend identity.

Недоказанные соответствия MUST NOT объединяться только по похожему изображению, адресу, имени или номеру порта.

### 6.5 Представление

Основной режим вкладки SHOULD отображать grid/list камер с:

- friendly name;
- live preview или thumbnail, если доступен;
- availability/connecting state.

Выбор камеры должен открывать live view через стандартный Home Assistant camera/media path.

Поведение live preview в Custom Card должно быть эквивалентно штатному HA `camera_view: live` для совместимых `camera.*` entities.

Preload stream НЕ является обязательным требованием. Custom Card MUST NOT самопроизвольно включать preload или требовать постоянно открытой surveillance RTSP session.

Если первый запуск потока занимает время, UI SHOULD показывать `connecting`, а не считать камеру недоступной до истечения разумного media timeout.

Для ordinary surveillance camera минимально требуются:

- live video;
- fullscreen;
- receive audio только если текущий HA media path действительно его предоставляет.

Microphone, call и Door controls MUST отображаться только для intercom point при наличии соответствующего validated Comelit capability.


## 7. Media presentation

### 7.1 Intercom media path

Для intercom camera существующий рабочий Home Assistant path остаётся допустимым viewing path и fallback:

```text
Comelit RTP
-> local RTP/SDP
-> Home Assistant Stream / PyAV
-> HLS
-> Comelit camera entity / HA frontend
```

Этот path относится к on-demand intercom media lifecycle и подчиняется `ComelitMediaSessionManager`.

### 7.2 Surveillance media path

Обычные камеры видеонаблюдения используют независимый стандартный Home Assistant path:

```text
camera source
-> standard HA camera integration
-> camera.*
-> HA Stream / media provider
-> Custom Card / HA frontend
```

Конкретный camera source transport не является частью frontend contract.

Surveillance viewing MUST NOT acquire a Comelit intercom media lease, pause the persistent Comelit listener или менять `active_call_panel`.

Практически подтверждённый baseline: standard Generic Camera с H.264 stream source работает как обычная HA `camera.*` entity и может отображаться live без переноса камеры в `custom_components/comelit`.

### 7.3 WebRTC

Для low-latency просмотра Home Assistant MAY использовать HA-managed go2rtc/WebRTC infrastructure, если конкретная `camera.*` entity/provider совместимы с этим path.

HLS/обычный HA Stream должен оставаться допустимым fallback.

Для intercom full-duplex conversation WebRTC остаётся отдельным кандидатом и MUST NOT считаться доказанным backchannel transport до соответствующей validation.

### 7.4 Preload

Preload stream является operational/performance option Home Assistant, а не частью функционального Comelit UI contract.

Custom Card MUST NOT включать preload автоматически.

Пользователь MAY включить preload для отдельных камер, если это необходимо для уменьшения startup latency и приемлемо по ресурсам/числу постоянных upstream sessions.

### 7.5 Микрофон

Microphone access MUST:

- запрашиваться только при явном действии пользователя «Ответить»/начать разговор;
- не активироваться при обычном открытии камеры;
- прекращаться при hangup;
- прекращаться при ошибке или закрытии conversation UI;
- не использоваться для ordinary surveillance cameras.


## 8. Реализации frontend

### 8.1 Home Assistant Custom Card

Custom Card SHOULD использовать:

- Home Assistant authentication;
- стандартные HA `camera.*` entities/media APIs для ordinary surveillance;
- HA entity/label configuration для формирования surveillance set;
- текущие Comelit entities/events/services только для intercom-specific функций;
- HA-managed media/WebRTC infrastructure, где это применимо;
- semantic Comelit actions для Door/call functions.

Custom Card MUST NOT:

- требовать отдельный постоянный Comelit application server;
- хранить или запрашивать raw RTSP credentials;
- переносить ordinary surveillance cameras внутрь Comelit integration только ради отображения UI.

### 8.2 Telegram Mini App

Mini App MUST предоставлять ту же логическую структуру:

```text
Домофон
Видеонаблюдение
```

и те же ограничения active-call routing.

Для surveillance Mini App должен получать ограниченное представление выбранных HA camera entities через trusted gateway/API facade. Raw RTSP credentials и unrestricted Home Assistant access token MUST NOT передаваться Mini App.

Authentication/authorization должен использовать ограниченный trusted gateway или эквивалентный short-lived authorization mechanism.

Telegram является frontend/notification surface и MUST NOT становиться владельцем отдельной upstream Comelit session.


## 9. Camera/backend separation

Frontend объединяет два независимых backend domains:

```text
custom_components/comelit
  -> entrance/gate
  -> call state
  -> intercom media/session owner
  -> Door semantic actions
              \
               \
                -> normalized UI model
               /
              /
standard HA camera integrations
  -> camera.*
  -> surveillance entity selection
  -> HA media presentation
```

Home Assistant Custom Card может собирать эту модель непосредственно из HA state/entity metadata.

Telegram Mini App получает эквивалентную ограниченную модель через trusted gateway.

Обычная surveillance camera MUST оставаться обычной HA camera entity. Добавление или удаление такой камеры не должно изменять Comelit protocol/runtime implementation.

Frontend MUST NOT зависеть от transport-specific camera details и MUST NOT требовать общего Comelit camera registry для ordinary surveillance.

## 10. Safety и lifecycle invariants

UI MUST соблюдать действующие project invariants:

- no automatic Door retry;
- Door operation remains semantic and one-shot;
- protocol ACK does not prove physical opening;
- no raw Comelit target selection from frontend;
- at most one active intercom upstream media session until another concurrency model is independently proven;
- ordinary surveillance viewing MUST NOT silently create a second intercom session;
- ordinary surveillance camera sessions MUST remain independent from `ComelitMediaSessionManager`;
- raw surveillance camera credentials/source URLs MUST NOT be exposed to frontend or Mini App;
- conversation uses the existing media/session owner;
- 600-second absolute media ceiling remains in force until explicitly changed by a later approved architecture decision;
- conversation audio is not recorded;
- secrets/tokens/session material are not exposed in frontend state, URLs, logs or diagnostics.

## 11. Availability and error handling

UI MUST distinguish at least:

```text
available
connecting
active
unavailable
error
```

Для intercom UI SHOULD additionally distinguish relevant call states such as:

```text
idle
ringing
answering
in_call
ending
```

Если capability недоступен или ещё не validated:

- control MUST be disabled/hidden according to UI policy;
- backend MUST remain authoritative;
- frontend MUST NOT synthesize success.

При потере surveillance stream активный intercom call не должен завершаться только из-за ошибки выбранной surveillance camera.


## 12. Минимальные acceptance scenarios

Функциональность считается соответствующей требованиям после проверки как минимум следующих сценариев:

1. Открыть «Домофон» и выбрать «Подъезд» без включения микрофона.
2. Открыть «Домофон» и выбрать «Калитка» без включения микрофона, если gate media validated; иначе получить корректный unavailable state.
3. Получить входящий звонок от `entrance` и увидеть именно entrance camera/actions.
4. Получить входящий звонок от `gate` и увидеть именно gate camera/actions после соответствующей validation.
5. Ответить на вызов и получить full-duplex audio после завершения protocol implementation.
6. Во время entrance call убедиться, что gate intercom camera не может быть выбрана.
7. Во время gate call убедиться, что entrance intercom camera не может быть выбрана.
8. Во время active intercom call перейти в «Видеонаблюдение» и открыть ordinary HA camera без изменения call/audio/door binding.
9. Вернуться к исходной активной домофонной точке и продолжить тот же разговор.
10. Завершить разговор и подтвердить безопасный media teardown и восстановление listener.
11. Открыть каждую configured surveillance `camera.*` entity из surveillance set.
12. Добавить новую standard HA camera в configured label/allowlist и убедиться, что она появляется в UI без изменения Comelit integration/frontend code.
13. Убедиться, что невыбранная HA camera entity не появляется автоматически во вкладке «Видеонаблюдение».
14. Проверить отсутствие дублей entrance/gate во вкладке «Видеонаблюдение».
15. Проверить live preview ordinary HA camera через эквивалент `camera_view: live` при выключенном preload.
16. Проверить, что включение/выключение HA preload для отдельной surveillance camera не меняет intercom lifecycle.
17. Проверить, что обычный просмотр surveillance camera никогда не запрашивает microphone permission.
18. Проверить, что conversation microphone прекращает работу после hangup/error/закрытия UI.

## 13. Зафиксированные UX-решения

На дату этого документа утверждены следующие решения:

- одна страница Comelit;
- две вкладки: «Домофон» и «Видеонаблюдение»;
- во вкладке «Домофон» ровно две логические точки: «Подъезд» и «Калитка»;
- ordinary surveillance cameras остаются стандартными Home Assistant `camera.*` entities и не переносятся в `custom_components/comelit`;
- surveillance set формируется средствами HA/configuration, предпочтительно через label, с возможностью explicit allowlist;
- entrance/gate не дублируются во вкладке «Видеонаблюдение»;
- live presentation ordinary cameras использует стандартный HA media path; `camera_view: live` является подтверждённым baseline behavior;
- preload stream не является обязательным и не включается frontend автоматически;
- во время активного разговора нельзя переключаться между двумя домофонными точками;
- во время активного разговора можно смотреть ordinary surveillance cameras;
- просмотр другой surveillance camera не меняет active call/audio/door binding;
- после просмотра surveillance camera можно вернуться только к текущей active intercom point до завершения разговора;
- Custom HA Card и Telegram Mini App должны реализовывать одну и ту же функциональную модель;
- Telegram Mini App не получает raw camera credentials или unrestricted HA token.
