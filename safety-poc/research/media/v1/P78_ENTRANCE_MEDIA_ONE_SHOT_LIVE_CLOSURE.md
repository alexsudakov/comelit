# P78 Entrance Media One-Shot Live Closure

TASK_ID=COMELIT-P78-ENTRANCE-MEDIA-ONE-SHOT-LIVE-CLOSURE  
BASE_MAIN_SHA=661f9d4c26350f2fdbce0a1c55b04ad1e5c86ee2  
EXECUTION_MODE=OFFLINE_IMPLEMENTATION_ONLY  
LIVE_EXECUTION_AUTHORIZED=false

## Назначение

P78 закрывает последний live-only разрыв между уже доказанной signaling/control
цепочкой P46-P76 и доказанным P77 media receive/oracle path. Эта итерация не
выполняет live запуск и не меняет persistent ring listener.

Архитектурные ограничения остаются прежними:

- listener и on-demand media имеют независимый lifecycle;
- listener не останавливается, не запускается и не перезапускается P78;
- разрешён максимум один live wrapper invocation;
- автоматический retry запрещён;
- второй CTPP OPEN запрещён;
- Door path недоступен;
- live session state генерируется заново, capture payload не replay'ится.

## Reviewed commit pin

Launcher не содержит самоссылочный embedded commit SHA. После PR/CI/merge
фактический reviewed `main` SHA передаётся через:

```text
P78_REVIEW_COMMIT_SHA=<merged-reviewed-main-sha>
P78_REVIEWED_LIVE_RUN=YES
```

До live launcher требует одновременно:

- `origin/main == P78_REVIEW_COMMIT_SHA`;
- local `HEAD == P78_REVIEW_COMMIT_SHA`;
- P77 base `661f9d4...` является ancestor reviewed SHA;
- launcher, P78 transform и P78 verifier в рабочем дереве имеют blob именно из
  reviewed SHA;
- исторические P46-P77/base inputs имеют зафиксированные blob SHA.

Любое несовпадение завершает preflight fail-closed до live boundary.

## One-shot sentinel

Sentinel:

```text
/root/.comelit-p78-live-consumed
```

создаётся атомарно через `O_CREAT|O_EXCL`, затем fsync файла и родительского
каталога. Он создаётся непосредственно перед единственным вызовом Comelit
wrapper.

Семантика:

- уже существующий sentinel -> отказ до runtime;
- ошибка подготовки до live -> one-shot не считается потреблённым;
- после начала live sentinel никогда автоматически не удаляется;
- concurrent second invocation не может пройти atomic create;
- `LIVE_INVOCATIONS <= 1`;
- automatic retry отсутствует.

## Serialized TX progression

Base writer допускает только один `p12_tx_pending`. Поэтому P78 не ставит две
ViP frame подряд.

RTPC OPEN:

```text
OPEN_1 queue/flush
-> P12_TX_RTPC_OPEN_1 completion
-> OPEN_2 queue/flush
-> P12_TX_RTPC_OPEN_2 completion
-> WAIT_DEVICE_OPEN
```

Media control:

```text
device OPEN
-> client RESPONSE queue/flush
-> RESPONSE completion
-> WAIT_DEVICE_RESPONSES
-> two paired device RESPONSE
-> 000A queue/flush
-> 000A completion
-> 001A queue/flush
-> 001A completion
-> signaling PASS / bounded media observation
```

Таким образом progression привязан к фактическому `p12_tx_completed()`, а не к
двум back-to-back queue calls.

## Runtime media capture

CT120 preflight доказал:

```text
ANY_RAW_RC=1
ANY_LINUX_SLL2_RC=0
ANY_LINUX_SLL_RC=0
```

Поэтому launcher явно использует:

```text
tcpdump -i any -y LINUX_SLL2
```

и перед sentinel повторно проверяет поддержку DLT через compile-only `tcpdump
-d`, без packet capture.

Сам capture process ограничен `CAPTURE_WINDOW_SECONDS=12`; это именно граница
процесса tcpdump, а не `wrapper timeout + 12 seconds`.

## Runtime PCAP verifier

P78 verifier больше не использует P77 frozen `BOUNDARY_PACKET=218` и не
использует исторический packet number/timestamp как runtime criterion.

Поддерживаются classic PCAP linktypes:

- `LINKTYPE_RAW = 101`;
- `LINKTYPE_LINUX_SLL = 113`;
- `LINKTYPE_LINUX_SLL2 = 276`.

Для выбранного ViP flow verifier структурно:

1. исключает PseudoTCP-shaped UDP;
2. исключает STUN-shaped UDP;
3. оставшийся selected-flow UDP обязан пройти строгий P77 offset-8 RTP parser;
4. неизвестный payload type, malformed wrapper, inconsistent wrapper profile
   или residual selected-flow UDP дают fail-closed;
5. H264 собирается только из `DEVICE_TO_CLIENT` PT99 через P77 single-NAL,
   STAP-A и FU-A reconstruction.

Raw/hex/base64 media payload не выводится.

## Mandatory live decode gate

Default verifier invocation остаётся offline-safe: без `--decode` external
codec tools не запускаются.

P78 live launcher всегда вызывает verifier с `--decode`.

Для live PASS требуются:

1. `P78_H264_ORACLE=PASS` и ненулевой reconstructed Annex-B H264;
2. `ffprobe` находит video stream `codec_name=h264`;
3. bounded `ffmpeg` decode с `-xerror` завершается успешно;
4. после успешного decode `ffmpeg` извлекает ровно один scratch JPEG;
5. JPEG имеет mode `0600`;
6. verifier возвращает `0`.

Основные markers:

```text
P78_FFPROBE_STATUS=PASS
P78_FFMPEG_DECODE_STATUS=PASS
P78_SCRATCH_JPEG_CREATED=true
P78_SCRATCH_JPEG_COUNT=1
P78_DECODE_STATUS=PASS
```

Ошибки ffprobe, ffmpeg decode или frame extraction не маскируются и не могут
дать финальный PASS.

## Listener contract

До live и после teardown launcher выполняет только HA webhook action `status` и
требует:

```text
supervisor_running=true
running=true
listener_ready=true
last_error=null
```

Запрещены listener start/stop/restart и Home Assistant restart/stop.

Итоговый invariant:

```text
LISTENER_CHANGED=NO
```

## Final live PASS gate

`P78_RUN_RESULT=PASS` возможен только при одновременном выполнении:

```text
wrapper_rc == 0
P78_RTPC_SIGNALING_RESULT == PASS
capture bound == PASS
verifier_rc == 0
P78_H264_ORACLE == PASS
P78_FFPROBE_STATUS == PASS
P78_FFMPEG_DECODE_STATUS == PASS
P78_DECODE_STATUS == PASS
P78_SCRATCH_JPEG_COUNT == 1
listener after == RUNNING_READY
```

Иначе результат `UNKNOWN_OUTCOME`/`FAIL`; автоматического повторного live запуска
нет.

## Safety invariants

```text
DOOR_ACTION_SENT_COUNT=0
P78_DOOR_ACTION_SENT=false
SECOND_CTPP_OPEN=false
P78_SECOND_CTPP_OPEN=false
AUTOMATIC_RETRY=false
P78_AUTO_RETRY=false
P78_MEDIA_PAYLOAD_STDOUT=false
P78_RAW_PAYLOAD_EMITTED=false
P78_HOME_ASSISTANT_CORE_STOPPED=false
P78_HOME_ASSISTANT_CORE_RESTARTED=false
P78_PSEUDOTCP_GRACEFUL_CLOSE_FORCE=false
```

## Offline tests

P78 tests должны доказывать:

- serialized OPEN1 -> OPEN2 и 000A -> 001A через TX completion;
- отсутствие second CTPP OPEN и Door entrypoint;
- отсутствие frozen packet-218 dependency;
- synthetic RAW/SLL/SLL2 PCAP acceptance;
- unsupported linktype и residual traffic fail-closed;
- ffprobe/ffmpeg/JPEG decode gates;
- live launcher всегда использует `--decode`;
- strict final PASS conjunction;
- atomic sentinel, no retry и status-only listener lifecycle.

## LIVE_ONLY facts

До отдельного explicitly authorized one-shot всё ещё не доказаны:

- panel acceptance generated RTPC sequence;
- появление runtime offset-8 RTP/H264;
- реальный ffmpeg decode и screenshot;
- необходимость 0x1800 ACK как причинного media gate;
- release upstream media resources после graceful close;
- listener readiness после фактического live attempt.

До merge reviewed P78 commit:

```text
LIVE_SCRIPT_RUNNABLE=false
LIVE_EXECUTION_AUTHORIZED=false
```
