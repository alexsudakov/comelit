# Issue #319 R10 — offline media-owner call-adoption PoC

## Граница результата

Это только детерминированная модель и fake harness. PASS этого harness **не
является разрешением live adoption**, production TX или RTPC OPEN. Модуль не
импортируется production-кодом и сам не импортирует production-пакет, R54
listener transform или сетевые библиотеки.

## PROVEN

- Один `INITIAL CALL_INIT` и четыре одинаковых retransmit дают одно логическое
  событие и один adoption-триплет.
- Полный flush каждого кадра предшествует следующему; partial и `EWOULDBLOCK`
  сохраняют единственный P12 slot, timeout завершает попытку fail-closed. При
  отказе занятый или частично записанный slot не очищается: его исходный владелец
  получает настоящий поздний completion, но adoption-цепочка больше не движется.
- Early peer `CAPABILITIES` хранится как разобранные поля и ACK ставится только
  после flush локального triplet; foreign/malformed не создаёт TX intent.
- Adoption, R27 refresh/repeat-001A и self-activation конкурируют за один slot;
  adoption имеет приоритет, двойной записи нет, refresh index меняется только
  после полного flush соответствующего refresh.
- Same-channel rebind выбирается только при совпавшей protocol call identity,
  generation и доказанном owner. Switch выбирается только после подтверждённого
  закрытия старого канала и при одном upstream.
- Genuine second call в той же generation переводит модель в `OBSERVE_ONLY` из-за
  ambiguity; он не считается retransmit.
- Generation mismatch, отсутствие call identity, unexpected peer response,
  receiver terminal и teardown uncertainty завершаются fail-closed без retry.
  `FAIL_CLOSED` и `OBSERVE_ONLY` защёлкнуты: последующий `CALL_INIT` не начинает
  новую попытку и не создаёт TX intent.
- Fake writer хранит только intent/байты в памяти и не имеет transport/producer
  handle: real TX, real producer, network, audio TX, Door/Gate и `EVENT_RING`
  заданы неизменяемыми нулевыми инвариантами. Дополнительно AST-тест запрещает
  production imports и вызовы `send`/`sendall`/`sendto`/`connect`.
- SHA-256 упакованных `comelit-media` и `comelit-v4` закреплены тестом как
  `2a10b69e...d8f045` и `0f1798bf...edbab` соответственно.

## NOT_PROVEN

- Live adoption, совместимость с физическим peer и право включить production TX.
- Production P78/P80 integration, listener transformation или изменение safety
  gates.
- Фактический RTPC rebind/switch/OPEN, teardown старого канала и media continuity.
- Значение call identity из `episode_id`, owner generation surrogate, frame SHA
  или временного окна: такие подмены намеренно не поддерживаются.
- Второй upstream, audio TX, Door/Gate и HA поведение — они вне scope и не
  исполняются.

## Переиспользованные контракты

- `R45SerializerAdapter` вызывает Python-facing сериализаторы из
  `entrance_p116_r45_call_adoption_core`: ACK — полный пустой CTP envelope с
  `flags=0x80` и нулевым body, CAPABILITIES/ALERTING используют R45 body и CTP
  envelope builders. Байтовые формы в адаптере не продублированы.
- `R53ProfileAdapter` получает call type, capability word и alerting argument
  через `helper_runtime_fields()` из
  `entrance_p116_r53_call_adoption_profile_core`; константы профиля в адаптере
  не продублированы.
- `P12ArbiterAdapter`/`FakeWriter`: R56 single-slot, `EWOULDBLOCK`, partial flush,
  release-before-completion callback и progress только от full-flush. Семантика
  timeout относится к контракту R56; сама модель не кодирует длительность.

## Проверки

- Локальная матрица `test_issue319_media_owner_call_adapter.py`: 20 тестов,
  `OK`, включая terminal latch, настоящий late completion после partial flush,
  сохранение чужого R27 slot/очереди и отрицательные RTPC ownership-ветви.
- Совместный regression R45/R53/R54/R56/R10: 60 тестов, `OK`; `compileall`
  изменённых Python-модулей также завершён успешно.
- `compileall` miniapp и четыре обязательных `node --check` завершены с кодом 0.
- `dev_v2_offline_safety.sh` дошёл до полного discover: новые R10-тесты прошли,
  всего выполнено 2528 тестов. Итог текущего sandbox-прогона — 2 failure и 6
  error в несвязанных baseline-проверках: Git-dependent provenance (Git
  запрещён контрактом executor), UDP sink, executable-mode provenance. Поэтому
  полный entrypoint в этом окружении не заявлен как PASS.
- Обязательный pytest miniapp не запускался: модуль `pytest` отсутствует в
  доступном системном Python.
- Production import path отсутствует; доступны только sibling research-модули
  R45/R53. Production-код, R54 `_assert_gates` и упакованный native helper не
  изменялись.

R54 listener-specific transform не применяется к P80 и production-файлы не
изменяются.
