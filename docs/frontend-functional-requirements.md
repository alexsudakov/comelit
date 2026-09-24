# Функциональные требования — Comelit UI

Статус: **approved user requirements baseline**  
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

Обе реализации — Home Assistant Custom Card и Telegram Mini App — MUST использовать одинаковую логическую структуру и одинаковые правила выбора камер.

Frontend MUST получать состав камер и их capabilities из backend/integration metadata и не должен требовать изменения frontend-кода при добавлении новой камеры поддерживаемого типа.

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

### 6.1 Состав

Во вкладке MUST отображаться все доступные камеры, не относящиеся к двум домофонным точкам.

В состав входят:

- камеры, доступные пользователю в официальном приложении Comelit;
- все остальные физические камеры, обнаруженные и подтверждённые проектом;
- камеры, добавленные позднее и опубликованные integration/backend как supported surveillance cameras.

Камеры `entrance` и `gate` MUST NOT дублироваться во вкладке «Видеонаблюдение».

### 6.2 Динамический camera catalog

Frontend MUST NOT содержать hardcoded список surveillance cameras.

Backend должен предоставлять логический camera catalog как минимум с эквивалентом следующих полей:

```text
camera_id
display_name
group: intercom | surveillance
availability
source_kind
capabilities
associated_door
```

Рекомендуемый capability model:

```text
video
audio_rx
audio_tx
call
door_open
snapshot
fullscreen
```

Не все камеры обязаны иметь одинаковые capabilities.

### 6.3 Дедупликация

Если одна физическая камера обнаружена несколькими способами, например:

- как камера в Comelit application;
- как отдельный RTSP endpoint;
- как ранее найденный технический endpoint,

UI SHOULD показывать одну логическую камеру, если backend может достоверно доказать, что источники относятся к одному физическому устройству.

Недоказанные соответствия MUST NOT объединяться только по похожему изображению, адресу или номеру порта.

### 6.4 Представление

Основной режим вкладки SHOULD отображать grid/list доступных камер с:

- логическим именем;
- thumbnail, если доступен;
- availability state.

Выбор камеры должен открывать live view.

Для обычной surveillance camera минимально требуются:

- live video;
- fullscreen;
- receive audio, если источник его предоставляет.

Microphone, call и door controls MUST отображаться только при наличии соответствующего backend capability.

## 7. Media presentation

### 7.1 Текущий путь

Существующий рабочий путь Home Assistant:

```text
Comelit RTP
-> local RTP/SDP
-> Home Assistant Stream / PyAV
-> HLS
-> camera entity / HA frontend
```

должен сохраняться как допустимый viewing path и fallback.

### 7.2 WebRTC

Для low-latency просмотра и full-duplex conversation может быть добавлен WebRTC path через HA-managed go2rtc/WebRTC infrastructure.

Добавление WebRTC MUST NOT само по себе ломать существующий HLS path.

Обычный camera viewer может быть receive-only.

Conversation UI должен иметь отдельную явно управляемую microphone lifecycle.

### 7.3 Микрофон

Microphone access MUST:

- запрашиваться только при явном действии пользователя «Ответить»/начать разговор;
- не активироваться при обычном открытии камеры;
- прекращаться при hangup;
- прекращаться при ошибке или закрытии conversation UI;
- не использоваться для обычных surveillance cameras без соответствующего validated capability.

## 8. Реализации frontend

### 8.1 Home Assistant Custom Card

Custom Card SHOULD использовать:

- Home Assistant authentication;
- текущие Comelit entities/events/services;
- HA-managed media/WebRTC infrastructure, где это применимо;
- semantic actions integration.

Custom Card MUST NOT требовать отдельный постоянный Comelit application server.

### 8.2 Telegram Mini App

Mini App MUST предоставлять ту же логическую структуру:

```text
Домофон
Видеонаблюдение
```

и те же ограничения active-call routing.

Mini App MUST NOT получать долгоживущий unrestricted Home Assistant access token.

Authentication/authorization должен использовать ограниченный trusted gateway или эквивалентный short-lived authorization mechanism.

Telegram является frontend/notification surface и MUST NOT становиться владельцем отдельной upstream Comelit session.

## 9. Camera/backend separation

Frontend MUST работать с логическими cameras/capabilities, а не с transport-specific деталями.

Рекомендуемая граница:

```text
Comelit / RTSP / future sources
            |
            v
camera registry + media/session backend
            |
            +-> HLS/WebRTC presentation
            |
            +-> Custom HA Card
            |
            +-> Telegram Mini App
```

Добавление новой поддерживаемой surveillance camera SHOULD требовать только обновления backend catalog/discovery, без изменения frontend logic.

## 10. Safety и lifecycle invariants

UI MUST соблюдать действующие project invariants:

- no automatic Door retry;
- Door operation remains semantic and one-shot;
- protocol ACK does not prove physical opening;
- no raw Comelit target selection from frontend;
- at most one active intercom upstream media session until another concurrency model is independently proven;
- ordinary surveillance viewing MUST NOT silently create a second intercom session;
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
8. Во время active intercom call перейти в «Видеонаблюдение» и открыть обычную камеру без изменения call/audio/door binding.
9. Вернуться к исходной активной домофонной точке и продолжить тот же разговор.
10. Завершить разговор и подтвердить безопасный media teardown и восстановление listener.
11. Открыть каждую доступную surveillance camera из camera catalog.
12. Добавить новую supported surveillance camera в backend catalog и убедиться, что она появляется в UI без изменения frontend-кода.
13. Проверить отсутствие дублей entrance/gate во вкладке «Видеонаблюдение».
14. Проверить, что обычный просмотр камеры никогда не запрашивает microphone permission.
15. Проверить, что conversation microphone прекращает работу после hangup/error/закрытия UI.

## 13. Зафиксированные UX-решения

На дату этого документа утверждены следующие решения:

- одна страница Comelit;
- две вкладки: «Домофон» и «Видеонаблюдение»;
- во вкладке «Домофон» ровно две логические точки: «Подъезд» и «Калитка»;
- во вкладке «Видеонаблюдение» — все остальные поддерживаемые камеры;
- entrance/gate не дублируются во второй вкладке;
- во время активного разговора нельзя переключаться между двумя домофонными точками;
- во время активного разговора можно смотреть обычные камеры видеонаблюдения;
- просмотр другой surveillance camera не меняет active call/audio/door binding;
- после просмотра surveillance camera можно вернуться только к текущей active intercom point до завершения разговора;
- Custom HA Card и Telegram Mini App должны реализовывать одну и ту же функциональную модель.
