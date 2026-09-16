# P116 / R30C — native CTP adoption evidence (Hermes result)

TASK_ID=`COMELIT-P116-R30C-NATIVE-CTP-ADOPTION-EVIDENCE`

BASE_SHA=`2ef16c404ff438a714b0c1904b52b4997f57dc5d`

BRANCH=`research/p116-r30c-native-ctp-adoption-evidence`

MODE=`OFFLINE_STATIC_ONLY`

HERMES_ROLE=`STATIC_EVIDENCE_ORCHESTRATOR`

LIVE_AUTHORIZED=`false`

NETWORK_TX_ALLOWED=`false`

PARENT_CONTRACT=`safety-poc/research/media/v1/P116_R30C_NATIVE_CTP_ADOPTION_EVIDENCE_CONTRACT.md`

Все технические идентификаторы, имена символов, смещения и маркеры — английские;
человекочитаемые пояснения — русские. Формат отчёта серии P116 (BASE_SHA, evidence
inventory, bounded findings, classification, decision gate) сохранён.

## 1. Итог одной строкой

Оба оставшихся transport unknown R30B закрыты статическими native-данными
`libvipcomelit.so`: inbound CTP callback id — это **direction-transformed wire id**
(`internal_id = BE(recv[2..3]) ^ 0x8000`, classification **B**), а
`ctp_write(call_ctp_id, ...)` кладёт на wire **сам внутренний id** (big-endian), то
есть ровно тот же id с перевёрнутым direction bit; sequence/ack полностью
принадлежат CTP transport connection object, а не `CallFsm`/CSP.

```text
OFFICIAL_NATIVE_LOCAL_ID_EQUIVALENCE=PROVEN
CTP_WRITE_WIRE_ID_MAPPING=PROVEN
SEQUENCE_STATE_OWNER=CTP_TRANSPORT_CONNECTION_OBJECT
```

## 2. Метод и границы

Работа выполнена только read-only на уже существующих CT120-артефактах
(`nm`/`aarch64-linux-gnu-nm`, `readelf`, `aarch64-linux-gnu-objdump -dC`, `strings`,
`grep`, `sed`, `sha256sum`, bounded pipelines по `.text`). Ничего не запускалось
против Comelit endpoint: ни listener, ни research candidate, ни helper, ни ICE,
ни PseudoTCP/cloud session, ни media lane. Сеть Comelit не затрагивалась.

Для каждого native-входа в локальный evidence-log (вне Git) записаны: artifact
class, локальный путь, SHA256, архитектура. В публичном документе используются
только alias + SHA256 + архитектура, без приватных абсолютных путей.

Bounded-дисassembly ниже приведён минимально необходимыми фрагментами
(по 1–4 инструкции на вывод), без полных дампов и без абсолютных адресов:
ссылки даны как `symbol + relative offset` внутри функции.

## 3. Evidence inventory

| ALIAS | CLASS | ARCH | SHA256 | PROVENANCE |
|---|---|---|---|---|
| `NATIVE_LIB_VIPCOMELIT` | proprietary shared library (primary) | ELF 64-bit ARM aarch64, stripped, 1003800 bytes, 1829 dynsym entries | `465c841a8a8400c8e301a18b728594b295a49b5bd5a127fa6b9643f94bf884f0` | staged research artifact on CT120 (read-only), pre-existing since R29A |
| `NATIVE_LIB_SAFECOMELIT` | proprietary shared library (second build) | ELF 64-bit ARM aarch64, stripped, 1684024 bytes, 2656 dynsym entries | `83a6fa2f8166366c73d3dc1b1a487451579b7e1121ce01d6996d6befc06e239b` | staged research artifact on CT120 (read-only) |
| `NATIVE_LIB_VIPKIT` | proprietary shared library (no CTP layer) | ELF 64-bit ARM aarch64, stripped, 124152 bytes, 138 dynsym entries | `2fe212c8ee2ecce8f64c556af01e91d148b3e7a001876d159c84ac50611476c1` | staged research artifact on CT120 (read-only); не содержит `ctp_*` и `VipUnitImpl` |
| `STAGED_DISASM_R29A` | existing text disassembly/provenance (diagnostic cross-check only) | text | — | pre-existing `.r29a-evidence`-набор CT120 (R29A lineage) |
| `PUBLIC_REF_CTP_PY` | public external source (pinned) | text | `165e1cb267ae0f3d731cccf7eccbb224b624a5a2a280de4e30b45d785f291178` | `jfmlima/comelit-vip@e3714dcccadb5bf934c32ce1400d891c3cfc61bb` `custom_components/comelit_vip/viper/ctp.py`, read-only HTTPS GET |
| `PUBLIC_REF_SESSION_PY` | public external source (pinned) | text | `7833a81fb85d758c2b3e6a172601a5dac480fa552e1b7b0c6dd0364783fb794f` | same pinned ref, `.../viper/session.py`, read-only HTTPS GET |

Proprietary binaries и raw captures в Git не копировались. Raw packet bytes,
network addresses, session/auth material не публикуются.

## 4. Подтверждённый CTP wire layout (native)

Оба направления CTP-транспорта (`NATIVE_LIB_VIPCOMELIT`, и идентично во втором
build) работают с одним и тем же 8-байтовым header, что совпадает с R30A:

```text
offset 0    flags      (TX: аргумент | 0x80, если body пустой)
offset 1    version    (TX: константа 0x18; RX: проверяется на равенство 0x18)
offset 2..3 connection (big-endian)
offset 4    sequence   (TX: conn[+137])
offset 5    acknowledgement (TX: conn[+138])
offset 6..7 body length (big-endian)
offset 8..  body
```

Anchors (bounded):

- TX serializer (`CTP_TX_SERIALIZE`, `NATIVE_LIB_VIPCOMELIT` +0x88/+0x8c):
  `mov w8, #0x18` → `strb w8, [x0, #1]`; `orr w8, w24, w10, lsl #7` → `strb w8, [x0]`.
- RX acceptance (`CTP_RX_ACCEPT` +0xb8): bound `cmp w9, #0x578` (1400) для
  length-поля; version-проверка `cmp w8, #0x18` в RX-deliver (`CTP_RX_DELIVER` +0x108).
- Единственная `rev16` в области CTP — сериализация connection-поля
  (`CTP_TX_SERIALIZE` +0x7c).

## 5. Вопрос A — mapping `call_ctp_id` (inbound adoption)

### 5.1 Извлечение inbound connection field

`CTP_RX_ACCEPT` (единственный parser входящих CTP-пакетов; вызывается и из
`ctp_tap_inject` (+0x2c, tap/Viper-путь), и из socket-пути `ctp_run`):

```text
CTP_RX_ACCEPT +0x98   ldrh  w9, [x1, #2]        ; recv bytes 2..3, little-endian load
CTP_RX_ACCEPT +0x9c   eor   w9, w9, #0x80       ; invert bit 7 of the first wire byte
CTP_RX_ACCEPT +0xa0   rev   w9, w9              ; byte swap
CTP_RX_ACCEPT +0xa4   lsr   w20, w9, #16        ; w20 = internal connection id
```

Это ровно `internal_id = ((recv[2] ^ 0x80) << 8) | recv[3]`, то есть
**big-endian значение wire connection field с перевёрнутым битом 15**.

Проверка «bit 15 / 0x8000 / 0x7fff» по всей `.text` библиотеки:

- `eor ... #0x80` встречается в `NATIVE_LIB_VIPCOMELIT` **ровно один раз** — на
  этом самом месте (RX path); литерала `0x8000` в CTP-коде нет;
- `mov w9, #0x7fff` + `and w10, w20, #0x7fff` + `cmp` → отклонение reserved-id
  (`CTP_RX_ACCEPT` +0xa8..+0xb4);
- `mov w24, #0x7fff` / `ands w8, w8, #0x7fff` в конструкторе исходящих
  соединений — генерация локального id со снятым битом 15.

### 5.2 Куда попадает id

```text
CTP_RX_ACCEPT +0xf4  ldrh w8, [x25, #36]   ; linear list lookup по conn[+36]
CTP_NEW_CONN_IN      strh w26, [x19, #36]  ; id сохраняется в conn[+36] БЕЗ преобразований
```

Connection object (calloc 1×0x98) в `CTP_NEW_CONN_IN`: очереди `+0x48` (TX,
наполняется `ctp_write`), `+0x58` (payload для приложения, читается `ctp_read`),
`+0x68` (RX raw); `+0x36` — 16-bit id; `+0x88/+0x8a/+0x8b` — sequence/ack/flags;
`+0x8d` — «notified», `+0x91` — tap flag. Отдельного `local_id`/`peer_id` поля в
объекте **нет**: id один.

### 5.3 Уведомление приложения (callback chain)

```text
CTP_TX_DRIVER +0x130  (queue +0x58 non-empty && conn[+141] == 0)
CTP_TX_DRIVER +0x1c8  ldrh w0, [x19, #36]   ; id идёт в callback как есть
CTP_TX_DRIVER +0x1cc  blr  x9               ; cb(id, data) = 0x97578 wrapper
0x97578               w1 = id ; tail-call ViperCtpTapCbksMngr::onNewCTPConnection
onNewCTPConnection    ctp_get_addresses(id, ...) ; fail → ctp_close(id)
onNewCTPConnection    VipUnitImpl::new_call_ctp_conn(unit, id, 0)
ctpVipUnitCallback    → VipUnitImpl::new_call_ctp_conn(unit, id)
new_call_ctp_conn     and w21, w1, #0xffff ; reject 0xffff ; csp_recv(id, &msg)
new_call_ctp_conn     msg type 0x01 → handleCtpStart(msg, id)
handleCtpStart        require type==0x01, body len >= 0x28, body[22]==1
handleCtpStart        vip_unit_accept_call(...) ; fail → csp_send_release(id, 8)
handleCtpStart +0x178 CallFsm::initNewConnectionStart(id, msg)   ; w1 = id
```

То есть **id не меняется ни на одном шаге** от CTP-слоя до
`CallFsm::initNewConnectionStart`; значение уже содержит direction transform из
5.1. Это согласуется с R29A (stored inbound call CTP id), но теперь доказано, что
именно значение имеет в себе XOR.

### 5.4 Классификация A/B/C/D

```text
LOCAL_ID_CLASSIFICATION=B_NATIVE_CALLBACK_ID_IS_DIRECTION_TRANSFORMED_WIRE_ID
OFFICIAL_NATIVE_LOCAL_ID_EQUIVALENCE=PROVEN
```

Per contract §6 classification B с прямым native dataflow допускает промоушен
R30B-кандидата `connection ^ 0x8000` до native contract.

Явные negative-проверки (что НЕ найдено):

| ПРОВЕРКА | РЕЗУЛЬТАТ |
|---|---|
| XOR/OR/BIC с литералом `0x8000` в CTP-коде | NOT_FOUND (нет ни одного) |
| отдельный `OR 0x8000` при приёме | NOT_FOUND |
| `BIC/AND` при приёме id | только reserved-rejection `and 0x7fff` |
| byte swap отдельно от direction transform | NO — `rev/rev16` это wire-encoding, XOR применяется к BE-значению |
| lookup table по id | NO — линейный обход связного списка по `conn[+36]` |
| раздельные `local_id`/`peer_id` в объекте | NO — единственное 16-bit поле id |

## 6. Отдельный вывод про `ctp_write`

```text
ctp_write(id, data, len):
  +0x10  and  w8, w0, #0xffff          ; id без преобразований
  +0x24  ldrh w9, [x20, #36]           ; linear list lookup по conn[+36]
  +0x2c  b.ne <loop>
  +0x30  ldrb w8, [x20, #143]          ; gate-байт соединения
  +0x4c  malloc(0x18)                  ; node: +8 = payload, +16 = len
  +0x80  b pckqueue_add                ; в очередь conn+0x48
```

`ctp_write` сам **ничего не сериализует** и не меняет id: он ищет объект
соединения по тому же 16-bit id (`conn[+36]`), что и `ctp_read` (+0x58),
`ctp_get_addresses` (+0x144==1), `ctp_conn_is_on_tap` (+0x145), и складывает
payload в очередь `conn+0x48`. Wire-header формирует TX serializer при отправке:

```text
CTP_TX_SERIALIZE +0x4c  ldrh  w27, [x19, #36]   ; id соединения
CTP_TX_SERIALIZE +0x7c  rev16 w9, w27           ; big-endian представление
CTP_TX_SERIALIZE +0x90  strh  w9, [x0, #2]      ; wire bytes 2..3
```

Следствие для adopted inbound call (наши ответные пакеты, включая
капабилити/алертинг и последующий `csp_send_mediareq26` → `ctp_write(id, msg, 26)`):

```text
out[2] = recv[2] ^ 0x80
out[3] = recv[3]
```

то есть на wire уходит **direction-transformed** значение, а не «сырые» принятые
байты и не какой-то третий handle.

```text
CTP_WRITE_WIRE_ID_MAPPING=PROVEN
```

## 7. Вопрос B — sequence / acknowledgement

Семантика полей (native, все anchors — `NATIVE_LIB_VIPCOMELIT`):

| ПОЛЕ | РОЛЬ | ANCHOR |
|---|---|---|
| `conn[+137]` | TX sequence byte, идёт в wire byte 4 | `CTP_TX_SERIALIZE` +0xa8 `strb w21, [x0, #4]` |
| `conn[+138]` | acknowledgement byte, идёт в wire byte 5 | `CTP_TX_SERIALIZE` +0xac `strb w28, [x0, #5]` |
| `conn[+136]` | «next/ожидаемая» sequence-метка (сравнивается с ack пира) | `CTP_RX_DELIVER` +0xc4..+0xd4, `CTP_TX_DRIVER` +0xc4 |
| `conn[+140]` | флаг перехода (после валидного body/ack) | `CTP_RX_DELIVER` +0xb8/+0xd8 |
| `conn[+141]` | «приложение уведомлено о новом соединении» | `CTP_TX_DRIVER` +0x1d4, +0x130 |

Инициализация **принятого inbound** соединения (`CTP_NEW_CONN_IN`, w1 = recv[4],
w2 = recv[5]):

```text
+0x60  strh w26(=id),      [x19, #36]
+0x64  strb w25(=recv[4]), [x19, #138]   ; ack ← sequence byte принятого пакета
+0x68  strb w24(=recv[5]), [x19, #136]   ; next  ← ack byte принятого пакета
+0x6c  strb w24(=recv[5]), [x19, #137]   ; TX sequence ← ack byte принятого пакета
```

Инициализация **исходящего** соединения (общий конструктор +0x64..+0xf8) другая:
id генерируется как `rand`-fold со снятым битом 15 (с проверкой коллизий в двух
глобальных списках), а `conn[+136] = conn[+137] = rand_byte`, `conn[+138] = rand_byte`.
То есть random seed существует только у инициатора; принятая сторона seed'ится
полями SYN.

Обновление на приёме (`CTP_RX_DELIVER`):

```text
+0x3c  ldrb w24, [x1, #4]          ; peer sequence
+0x40  cmp  w24, conn[+138]        ; ожидается именно текущее значение ack
       (body принимается и кладётся в conn+0x58 только при совпадении)
+0xac  add  w8, w24, #1
+0xb8  strb w8, [x19, #138]        ; ack = peer_sequence + 1 (mod 256)
+0xc4  ldrb w8, [x1, #5]           ; peer ack
+0xc8  cmp  w8, conn[+136]
+0xd4  strb w8, [x19, #137]        ; TX sequence продвигается при совпадении
+0x184 ldrb w23, [x1] ; tbnz #6    ; запрос ACK → пустой пакет (len 0)
```

Отправка (`CTP_TX_DRIVER`): после успешной отправки payload из очереди `conn+0x48`
счётчик «next» инкрементируется ровно на 1, а копия отправленного буфера/длины
сохраняется для ретрансмиссии:

```text
+0xa4  strh len, [x19, #120]
+0xa8  str  ptr, [x19, #128]
+0xb0  strb wzr, [x19, #139]       ; reset retry counter
+0xbc  strh 5,   [x19, #62]        ; состояние
+0xc4  add  w8, conn[+136], #1 ; strb w8, [x19, #136]
```

Пустой ACK-пакет строится тем же serializer'ом без изменения `conn[+136]`, то есть
empty ACK **не двигает** sequence — как и в публичной модели.

### Таблица требуемых полей

| FIELD | VALUE | EVIDENCE |
|---|---|---|
| `FIRST_LOCAL_TX_SEQUENCE_SOURCE` | `INBOUND_CTP_PACKET_ACK_BYTE_WIRE_OFFSET_5_COPIED_VERBATIM` | `PROVEN_NATIVE` |
| `LOCAL_SEQUENCE_ADVANCEMENT_RULE` | `PLUS_ONE_MOD_256_PER_BODY_BEARING_SEND; ON_WIRE_VALUE_PROMOTED_WHEN_PEER_ACK_BYTE_MATCHES_CONN_136; EMPTY_ACK_DOES_NOT_ADVANCE` | `PROVEN_NATIVE` |
| `INITIAL_LOCAL_ACK_SOURCE` | `INBOUND_CTP_PACKET_SEQUENCE_BYTE_WIRE_OFFSET_4_COPIED_VERBATIM` | `PROVEN_NATIVE` |
| `ACKNOWLEDGEMENT_UPDATE_RULE` | `PEER_SEQUENCE_PLUS_ONE_MOD_256_ON_ACCEPTED_BODY_PACKET` | `PROVEN_NATIVE` |
| `SEQUENCE_STATE_OWNER` | `CTP_TRANSPORT_CONNECTION_OBJECT_CONN_136_137_138` (не `CallFsm`/CSP) | `PROVEN_NATIVE` |

Практический вывод для будущего helper: transport state (id + sequence + ack)
должен моделироваться на уровне CTP-соединения; media-код не должен подставлять
произвольные sequence/ack значения, а CSP/CallFsm не владеют этими счётчиками.

## 8. P76 structural finding

`safety-poc/research/media/v1/entrance_rtpc_control_media_runtime_transform.py:297`:

```text
p76_write_le32(out + 2, previous_client_ctpp_sequence + 0x00010000u);
```

LE32 по offset 2 покрывает байты 2..5 = connection(2..3) + sequence(4) + ack(5).
Прибавление `0x00010000` увеличивает ровно byte 2 этого LE32, то есть wire byte 4
(sequence), не трогая connection bytes 2..3 и ack byte 5.

```text
P76_SEQUENCE_ADVANCEMENT_STRUCTURAL_SUPPORT=true
```

Bounded caveat: арифметика делает `+1` над составным 32-bit значением, поэтому при
`sequence == 0xff` перенос уходит в byte 3 (ack byte 5), тогда как native transport
ведёт sequence и ack как независимые 8-bit счётчики mod 256. Для helper'а это
означает, что P76-структура верна как историческая аппроксимация, но настоящий
advance rule — байтовый (см. §7). Источник initial seed этим не доказывается.

## 9. Public external corroboration (отдельно от native)

Pinned ref `jfmlima/comelit-vip@e3714dcccadb5bf934c32ce1400d891c3cfc61bb`,
read-only GET, SHA256 файлов в §3.

- `ctp.py`: layout совпадает с native (`flags, version=0x18, connection:2B, seq, ack,
  body_len:u16be`); docstring: «The connection id is a 15-bit number picked by
  whoever opens it; the peer uses the same id with bit 15 set»;
  `peer_connection_id(connection)` = `struct.unpack(">H") ^ 0x8000`.
- `session.py:_accept_inbound`: `local_id=peer_connection_id(packet.connection)`,
  `peer_id=packet.connection`; `ack()`: `acknowledgement = (packet.sequence + 1) & 0xFF`;
  `send()`: `sequence += 1` только `if body:`.

Совпадение с native теперь полное по двум правилам (direction transform и ack rule).
Расхождение, которое надо помнить: публичная модель инициализирует `sequence` и
`acknowledgement` случайно даже для adopted inbound connection, тогда как native
берёт их из полей принятого пакета (см. §7). Публичные random-fixture значения
тестов (fake panel) как protocol constants не промоутятся.

Классификация этого evidence не повышается выше:

```text
PUBLIC_XOR_RULE_CLASSIFICATION=STRONGLY_SUPPORTED_EXTERNAL
PUBLIC_ACK_RULE_CLASSIFICATION=STRONGLY_SUPPORTED_EXTERNAL
```

(Значения оставлены по формату; сами правила уже независимо доказаны native
dataflow в §5–§7, public слой остаётся вспомогательным corroboration.)

## 10. Saved captures

`SAVED_CAPTURE_EVIDENCE_USED=false`.

На CT120 в наличии только `pcap`, относящиеся к media/self-activation линиям
(P2P-RTSP media, self-activation, P78 media) — сохранённого capture официального
inbound call с последующими call-scoped CTP-ответами, пригодного для relation
table по §5 контракта, не найдено. Извлечение CTP-полей из таких файлов требует
нового executable extractor'а (CTP-слой едет внутри Viper CTPP-нагрузки; готового
декодера в окружении нет: `tshark` отсутствует, есть только `tcpdump`), а R30C
такой инструмент явно не создаёт (contract §10). Поэтому capture-relation table не
строилась, raw bytes не публикуются, и promotion опирается только на native
dataflow — этого достаточно для classification B.

## 11. Остаточные unknowns (bounded, вне двух вопросов R30C)

- Точная bit-семантика маскирования length-поля при приёме (инструкция в
  `CTP_RX_ACCEPT` +0x50/#0xffffff07-форма) не декодирована до логического immediate;
  на выводы §5–§7 не влияет (граница 1400 байт подтверждена).
- Полная нумерация состояний `conn[+62]` и тайминги ретрансмиссии (`conn[+139]`,
  сохранённый буфер `conn+128/+120`) в R30C не разбирались.
- Повторное использование id после reconnect/close на стороне панели и поведение
  при одновременных inbound-соединениях не проверялись.
- Второй build (`NATIVE_LIB_SAFECOMELIT`) проверен выборочно: тот же `eor #0x80`
  path, тот же `and 0x7fff` reserved-check, тот же lookup `[+36]`, тот же инкремент
  `conn[+136]`; построчного diff всего CTP-слоя между build'ами не делалось.

## 12. Safety invariants

```text
LIVE_RUN=NOT_RUN
LIVE_AUTHORIZED=false
NETWORK_TX=0
DOOR_ACTIONS=0
GATE_ACTIONS=0
SELF_ACTIVATION_ACTIONS=0
REFRESH_OR_REPEAT_ACTIONS=0
PRODUCTION_LISTENER_TOUCHED=false
HA_DEPLOY_COUNT=0
HA_RESTART_COUNT=0
HA_RELOAD_COUNT=0
PRODUCTION_FILES_CHANGED=0
```

Listener stop/start/status mutation не выполнялся; production status не читался.
Native artifacts читались read-only, ничего не копировалось в Git.

## 13. Следующий decision gate

Оба unknown'а R30B закрыты, поэтому следующий шаг — **R30D offline** (iterative
tooling, Codex): заменить в R30B-модели инжектируемый `next_tx_sequence_seed` и
corroborating-`XOR` на доказанные правила и добавить negative-тесты:

```text
adopted_local_id_wire_bytes = recv[2] ^ 0x80, recv[3]
adopted_initial_tx_sequence = recv[5]
adopted_initial_ack         = recv[4]
ack_after_body_packet       = (recv[4] + 1) mod 256
sequence_advance            = +1 per body-bearing send, ack-gated
empty_ack                   = sequence unchanged
```

Live-тест R30C не авторизует: `LIVE_CALL_BOUND_MEDIA=NOT_PROVEN` остаётся в силе
до отдельной live-авторизации.

## 14. Acceptance markers

```text
TASK_ID=COMELIT-P116-R30C-NATIVE-CTP-ADOPTION-EVIDENCE
BASE_SHA=2ef16c404ff438a714b0c1904b52b4997f57dc5d
CHANGED_FILES=1
NATIVE_EVIDENCE_AVAILABLE=true
SAVED_CAPTURE_EVIDENCE_USED=false
LOCAL_ID_CLASSIFICATION=B_NATIVE_CALLBACK_ID_IS_DIRECTION_TRANSFORMED_WIRE_ID
OFFICIAL_NATIVE_LOCAL_ID_EQUIVALENCE=PROVEN
CTP_WRITE_WIRE_ID_MAPPING=PROVEN
FIRST_LOCAL_TX_SEQUENCE_SOURCE=INBOUND_CTP_PACKET_ACK_BYTE_WIRE_OFFSET_5_COPIED_VERBATIM
FIRST_LOCAL_TX_SEQUENCE_EVIDENCE=PROVEN_NATIVE
LOCAL_SEQUENCE_ADVANCEMENT_RULE=PLUS_ONE_MOD_256_PER_BODY_BEARING_SEND_ACK_GATED
LOCAL_SEQUENCE_ADVANCEMENT_EVIDENCE=PROVEN_NATIVE
INITIAL_LOCAL_ACK_SOURCE=INBOUND_CTP_PACKET_SEQUENCE_BYTE_WIRE_OFFSET_4_COPIED_VERBATIM
INITIAL_LOCAL_ACK_EVIDENCE=PROVEN_NATIVE
ACKNOWLEDGEMENT_UPDATE_RULE=PEER_SEQUENCE_PLUS_ONE_MOD_256_ON_ACCEPTED_BODY_PACKET
ACKNOWLEDGEMENT_UPDATE_EVIDENCE=PROVEN_NATIVE
SEQUENCE_STATE_OWNER=CTP_TRANSPORT_CONNECTION_OBJECT
SEQUENCE_STATE_OWNER_EVIDENCE=PROVEN_NATIVE
P76_SEQUENCE_ADVANCEMENT_STRUCTURAL_SUPPORT=true
PUBLIC_XOR_RULE_CLASSIFICATION=STRONGLY_SUPPORTED_EXTERNAL
PUBLIC_ACK_RULE_CLASSIFICATION=STRONGLY_SUPPORTED_EXTERNAL
NETWORK_TX=0
DOOR_ACTIONS=0
GATE_ACTIONS=0
SELF_ACTIVATION_ACTIONS=0
REFRESH_OR_REPEAT_ACTIONS=0
PRODUCTION_LISTENER_TOUCHED=false
PRODUCTION_FILES_CHANGED=0
LIVE_AUTHORIZED=false
RESULT=PROVEN_OFFLINE
```
