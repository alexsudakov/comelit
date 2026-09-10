# P105 LEN24 Fallback Forensic

## Observed Live Fact

В одном ограниченном live-прогоне кандидат P99/P100 дошел до рабочей media
сессии:

```text
P80_DEVICE_ACK_000A_OBSERVED=PASS
P78_RTPC_CLIENT_001A_SENT=PASS
P80_PREACTIVE_MEDIA_DEMUX=PASS
P80_PREACTIVE_MEDIA_PAYLOAD_TYPE=8
P80_DEVICE_ACK_001A_OBSERVED=PASS
P80_POST_001A_ACK_GATE=PASS
P78_RTPC_SIGNALING_RESULT=PASS
P80_MEDIA_ACTIVE=true
P80_AUDIO_RTP_FORWARDING=PASS
P80_VIDEO_RTP_FORWARDING=PASS
PSEUDOTCP_NOTIFY_PACKET=FAIL LEN=24
```

`PSEUDOTCP_NOTIFY_PACKET=FAIL` в `recv_cb()` является терминальным: после
неуспешного `pseudo_tcp_socket_notify_packet()` выставляется `failed = TRUE`,
и при наличии `loop` вызывается `g_main_loop_quit(loop)`. Поэтому LEN=24 - это
не шум в логах, а datagram, который убивает уже поднятую media-сессию.

## Static Receive Path

P105 анализирует receive path в кандидатном C, детерминированно полученном
применением P101 к frozen source
`safety-poc/research/door/v1_5_7/comelit-v4-persistent-ctpp-door.c`.

```text
RECEIVE_PATH_FACT name=P80_INTERCEPT line=729
RECEIVE_PATH_FACT name=PSEUDOTCP_NULL_EARLY_RETURN line=732
RECEIVE_PATH_FACT name=PSEUDOTCP_NOTIFY_PACKET_CALL line=773
RECEIVE_PATH_FACT name=NOTIFY_FAILURE_BRANCH line=779
RECEIVE_PATH_FACT name=NOTIFY_FAILURE_FAILED_TRUE line=787
RECEIVE_PATH_FACT name=NOTIFY_FAILURE_LOOP_QUIT line=790
```

Порядок важен: сначала пробуется `p80_try_forward_wrapped_rtp()`, затем
prestart/`!pseudo_tcp` early path, затем datagram передается в
`pseudo_tcp_socket_notify_packet()`. Диагностика P105 добавляется только перед
этой передачей и не меняет саму передачу или fatal branch.

## LEN=24 Structural Gates

Для текущего media classifier LEN=24 не является автоматически невозможным.
Чтобы packet был принят как offset-8 wrapped RTP, он должен пройти все три
проверки:

```text
LEN24_OFFSET8_INNER_LEN_REQUIRED=16
LEN24_WRAPPER_NON_UNIQUE=true
LEN24_NOT_STRUCTURALLY_EXCLUDED_FROM_OFFSET8_WRAPPED_RTP=true
```

То есть `read_le16(packet + 2) + 8 == 24`, RTP version bits at offset 8 равны
2, и payload type равен 99 или 8. Это не доказывает, что observed LEN=24 был
RTP; это только запрещает делать обратную ошибку: нельзя отбрасывать все
24-byte datagrams по одному размеру.

## Frozen Capture Output

Реальный запуск против staged `self_activation.pcap`:

```text
PCAP_SHA256_GATE=PASS
CAPTURE_LABEL=self_activation.pcap
LEN24_DATAGRAM_COUNT=34
PSEUDOTCP_LEN24_VERDICT=OBSERVED_UNRESOLVED
PSEUDOTCP_LEN24_CLASSIFICATION=UNKNOWN
PSEUDOTCP_LEN24_EVIDENCE=LEN=24 observed but no known structural predicate matched
```

Реальный запуск против staged `p2p_rtsp.pcap`:

```text
PCAP_SHA256_GATE=PASS
CAPTURE_LABEL=p2p_rtsp.pcap
LEN24_DATAGRAM_COUNT=761
PSEUDOTCP_LEN24_VERDICT=OBSERVED_UNRESOLVED
PSEUDOTCP_LEN24_CLASSIFICATION=UNKNOWN
PSEUDOTCP_LEN24_EVIDENCE=LEN=24 observed but no known structural predicate matched
```

Оба захвата содержат LEN=24, поэтому результат не `NOT_OBSERVED`. Эти capture
counts не доказывают роль live datagram после media-active: staged captures
имеют свою временную и сессионную структуру. Они доказывают только, что
LEN=24 встречается на выбранной lane и что по P105 scalar predicates эти
экземпляры не классифицируются как offset-8 RTP, RTCP, STUN или defined
PseudoTCP header shape.

## Hypothesis Table

```text
HYPOTHESIS role=offset-8 wrapped RTP status=REFUTED reason=no LEN=24 datagram clears wrapper/version/PT 99-or-8 gates
HYPOTHESIS role=RTCP status=REFUTED reason=no LEN=24 datagram has offset8 RTCP packet-type range
HYPOTHESIS role=PseudoTCP/control frame status=REFUTED reason=24-byte PseudoTCP header predicate did not match
HYPOTHESIS role=CTPP/control status=NOT_DECIDABLE_OFFLINE reason=no payload bytes or live stream state are available to bind a CTPP semantic role
HYPOTHESIS role=other already-known protocol frame status=REFUTED reason=no STUN magic at datagram offset 4
HYPOTHESIS role=malformed/unexpected input status=SUPPORTED reason=none of the structural known-protocol predicates matched
HYPOTHESIS role=UNKNOWN status=NOT_DECIDABLE_OFFLINE reason=structural evidence is insufficient for a unique semantic classification
```

`malformed/unexpected input` здесь означает только structural fallback bucket:
из offline evidence не следует семантическая роль. Поэтому итог не
`PROVEN_CLASSIFIED`.

```text
PSEUDOTCP_LEN24_STATUS=OBSERVED_UNRESOLVED
PSEUDOTCP_LEN24_CLASSIFICATION=UNKNOWN
PSEUDOTCP_LEN24_EVIDENCE=LEN=24 observed but no known structural predicate matched
```

## Live-Only Remainder

Остается live-only:

- точный state при datagram после `P80_MEDIA_ACTIVE=true`;
- совпадает ли live LEN=24 с offset-8 wrapper length 16;
- имеет ли live datagram RTP version bits at offset 8 и PT 99/8;
- попадает ли byte 9 в RTCP packet-type range 200..211;
- присутствует ли STUN magic at offset 4;
- удовлетворяет ли live datagram P105 PseudoTCP-header-shape predicate;
- происходит ли notify failure сразу после этого же diagnostic signature.

Следующий live run будет печатать bounded scalar diagnostics:

```text
LEN24_FALLBACK_LEN=%u
LEN24_FALLBACK_MEDIA_ACTIVE=%s
LEN24_FALLBACK_PREACTIVE_ARMED=%s
LEN24_FALLBACK_WRAPPER_INNER_LEN_LE16=%u
LEN24_FALLBACK_WRAPPER_LEN_CONSISTENT=%s
LEN24_FALLBACK_VERSION_BITS_0=%u
LEN24_FALLBACK_VERSION_BITS_8=%u
LEN24_FALLBACK_PT_AT_8=%u
LEN24_FALLBACK_RTCP_PT_RANGE=%s
LEN24_FALLBACK_STUN_MAGIC_PRESENT=%s
LEN24_FALLBACK_PSEUDOTCP_HEADER_SHAPE=%s
LEN24_FALLBACK_PSEUDOTCP_FLAGS_BYTE=%u
LEN24_FALLBACK_DIAGNOSTIC_ONLY=true
```

Bound: first 8 distinct `(len, flags, pseudotcp_header_shape)` signatures.

## Classifier Policy

P105 не добавляет classifier rule, потому что semantic role LEN=24 offline не
доказана. Игнорировать все 24-byte packets запрещено: LEN=24 structurally can
fit an offset-8 wrapper with 16-byte inner packet, and live-only diagnostics
must classify the actual terminal datagram before any behavior change.
