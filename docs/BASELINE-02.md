# BASELINE-02: подготовка измерений normal production

Карточка [#26](https://github.com/notanonenough/reachy-companion/issues/26).
Это офлайн-подготовка и предложение следующего окна. Новые starts, сеть,
аппаратные probes и установка этой работой не выполняются. Испытанная версия:
`stand-2026-11-23.1`, `717a6577a9f7c2b3ff6dd22045761866678b37bc`.
Исполнение будущего окна и фактический baseline остаются в той же карточке.

## Что уже можно измерять

| Существующий источник | Что означает | Повторное использование и предел |
|---|---|---|
| `autonomous/companion_session.py:run_session`, live status | Снимок текущих counters, очередей, свежести и busy; публикация планируется раз в 50ms | Чтение status существующим владельцем. Интервал публикации не гарантирует период reducer. |
| `runtime.py:Scheduler.latencies` | Последний Job start → обработка completion reducer для fast/main | Это client+очередь+доставка completion, не compute time. Повторные status-значения не отдельные вызовы. |
| `runtime.py:pressure_status` | Активный возраст jobs и число candidates/ready tasks | Очередь и overload наблюдаются отдельно от успешных ответов; не вычитать их из latency без доказательства. |
| `audio_peer.py:PeerLease.status` | Накопленный max tick gap, errors, текущий progress age, timing | Max — одно верхнее наблюдение, не выборка для percentile. Полный status содержит больше, чем сохранённый717 bounded sampler. |
| `lease_diagnostics.py` | Первый invalid gate и первый reducer expiry, stage/stack при обнаружении | Коллектор повторно использует существующие bounded projectors. `trigger=tick` показывает detection после возврата reducer; stack не обязательно причина stall. |
| `private_audio_trace.py`, actual production hooks | Уникальные STT/source/sequence, admitted input, main task/attempt, speech/stream/stop | Сопоставление в одном trace/Hub boot и clock domain. Только whitelisted числовые итоги выходят из коллектора. |
| `production_logs.py`, `production_status.py` | Content-free final/diagnostics и last session | Final и stop receipts нужны независимо от наличия полноценной voice trace. |
| `audio_peer_network_probe.py` | Отдельный конечный lease/status опыт без inference/PCM | Сам renew/stop; **не запускать параллельно normal owner**. Не заменяет joint-load baseline. |
| `speech_network_probe.py` | Реальная сеть с ReplayGateway/ReplayPCM | Другой scheduler и simulated output; его max advance не характеризует normal production. |
| `native_scheduler_probe.py` | Отдельный Scheduler и действительные motor commands | Не наблюдатель; не использовать для текущего окна или параллельно владельцу. |
| Одобренный private trace harness | Один foreground Hub PID/start_ticks, listener provenance, authenticated stop, terminal cleanup | Переиспользовать без второго owner или permanent service override; не превращать collector в runtime. |

Источники и consumers прочитаны вместе с BEHAVIOR и REVIEW-NOTES §4,10,17–19,
25,27–30,37–38. Модель0.8B+9B, транспорт, sensor settings, factory SDK и guards
этой подготовкой не меняются. Переход на одну диалоговую модель — отдельное
согласованное направление, а не вывод из одного медленного ответа.

## Числа до следующего сравнения

| Число | Статус и источник |
|---|---|
| 200ms reducer progress | Действующее ограничение принятого production launcher (`production_start.py --lease-progress-s .2`); CLI `companion_session` отдельно имеет default100ms. Не согласованный p99 и не допустимое время любого blocking call. |
| 300ms device lease / peer-status / operator freshness | Существующие проверки `audio_peer.py` и `companion_session.py`, с их собственными anchors и строгим expiry. Не складывать в обещанную physical STOP latency. |
| ≤100ms renewal HTTP timeout; пауза worker20ms | Реализация PeerLease; scheduling/network могут добавить время. Нельзя вывести 50Hz гарантированный прогресс. |
| 50ms publish, 5ms loop wait | Планируемые интервалы, не realtime deadline гарантии. |
| 1 занятый STT slot + latest pending input | Ограниченная очередь AudioAdapter; overwrite/stale/error считаются отдельно, не маскируются успешными ответами. |
| trace: ≤300s,512 records,1MiB,16KiB/record,queue32 | Действующие caps #22. Полный/сломанный writer означает incomplete evidence, а не автоматически physical failure. |
| Конкретные STT result TTL, task/proposal deadlines, overload limits, model IDs | Брать из точных runtime configs установленного717 и фиксировать allowlisted числа перед окном. Примеры config в Git не выдавать за installed значения. |
| 3×120s, sampler1Hz для OS resources | **Предложение этого протокола**, ещё не аппаратное разрешение и не long-run test. |
| Целевые ear latency, p95/p99, CPU/RSS ceilings | **Не установлены**. Не выводить их из малой выборки; решение после baseline принимает ведущий/владелец. |

Сохраняется прежний факт15b: primary reducer_expired202.470ms при200ms до
camera/stimulus. Последующие175s/90s/90s не воспроизвели его; причины это не
устраняет. Текущая наблюдаемая верхняя граница не разрешает поднять guard.

## Офлайн-команды и форматы

Коллектор только читает локальные файлы; нет запуска процессов, подключения к
сети, запуска hardware или импортов alternate probes. Стандартный stdout —
JSON фиксированных полей; paths, raw text, IDs, prompt, digests и profile не
публикуются. Размер trace≤1MiB/512 строк/16KiB на строку; status/resources≤32MiB,
10000 строк/256KiB; final — ровно один объект либо список из одного объекта.
Ошибки чтения/формата дают фиксированный `invalid_input`, exit2 без raw exception.

```sh
PYTHONPATH=src python3 deploy/autonomous/production_baseline.py \
  --candidate 717a6577a9f7c2b3ff6dd22045761866678b37bc --dry-run

EVIDENCE=/Users/notanonenough/reachy-release-backups/20261123-717a6577a9f7/trace-trial
PYTHONPATH=src python3 deploy/autonomous/production_baseline.py \
  --candidate 717a6577a9f7c2b3ff6dd22045761866678b37bc \
  --trace "$EVIDENCE/private-trace.jsonl" --status "$EVIDENCE/status.jsonl" \
  --final "$EVIDENCE/final-bounded.json" > /tmp/baseline-717-summary.json

PYTHONPATH=src:tests python3 -m unittest test_production_baseline -v
```

`--dry-run` не открывает даже входные файлы. `--candidate` — декларация provenance
оператора, не самостоятельное доказательство installed identity: до сравнения
нужны manifest/identity receipts из протокола717. Коллектор не меняет inputs,
не запускает прежний `audit-correlation.py` (тот перезаписывает local summary).

Missing file отличается от empty/incomplete trace и stale dispositions.
Footer/counters, duplicate JSON keys, typed authority, duplicate/conflicting IDs и обязательный порядок событий проверяются; incomplete не скрывается
при наличии нескольких удачных цепочек. Каждый main join использует task,
attempt,input_ref,authority; retry наследует только зарегистрированный parent.
Первоначальный audio admission anchor сохраняется при retry; ожидание нового retry candidate имеет отдельный интервал. STT counts и интервалы разделены на recognized/empty/stale/error/other. Число
исходных событий сохраняется даже при потере join. Background main не попадает
в voice latency; ready/discarded/failed имеют отдельные counts. Соответствие
terminal по ID не выдаётся за проверенную остановку: flags считаются отдельно.

Интервалы — Hub monotonic client observations в одном boot. Main/STT включают
transport/service/queue, а `main_end_to_checked` включает доставку completion
reducer. TTS first PCM — первый chunk у producer, не первое слышимое слово.
Clock alignment между Hub/Mac/robot не доказан, timestamps между узлами не
вычитаются. Capture mapping и WAV ASR не используются как acoustic stopwatch.
Percentiles — median и empirical nearest-rank p95/p99 с явным n, без population
или tail гарантии. При n=1 все ranks равны единственному измерению.

Status counters — только наблюдаемые deltas, не абсолютное число за весь сеанс:
первый sample — baseline. Missing identity/status, source change, elapsed reset,
counter reset разрывают последовательность. Отсутствующие пары — null, не0.
Повторные last Job latency и cumulative max не создают новые call samples.
Poll duration учитывает и unavailable/error ответы даже без peer identity, с отдельными outcome counts; counters через эту границу не соединяются. Это локальный Hub request interval; Mac received timestamp не
вычитается из него. Частота sampling ограничивает наблюдаемость коротких пиков.

### Проверка сохранённого717

Повторный offline пересчёт дал1 audio-linked цепочку и2 metadata-only main,
ready1/discarded2. STT: recognized1 (2.615216846s), empty36 (median0.071666342s).
Все следующие voice интервалы имеют **n=1**:

| Интервал | Hub local seconds |
|---|---:|
| STT end → admission | 0.026575084 |
| Admission → main start | 1.779605159 |
| Main client | 7.649992996 |
| Main end → checked | 0.023190823 |
| Checked → speech commit | 1.261417298 |
| TTS first PCM / producer elapsed | 0.466630397 /0.526199767 |
| STT end → playback stop receipt | 11.886538296 |

384 status rows,351 ACTIVE;33 не имеют пригодной peer identity. Наблюдаемый
cumulative max tick gap126.161689ms; invalid/expiry snapshot rows0.
Старый bounded sampler не сохранил queue depth/progress age/last Job latency,
CPU/RSS. Их нельзя восстановить из успешного final или считать нулями.
Сохранённые числовые итоги совпали с `correlation-bounded.json`; его исторические
ключи `stt_compute`/`main_compute` здесь сознательно называются client interval.
Тексты, private trace, WAV и profile в Git не входят.

## Предложение будущего окна: три отдельные реплики

Ведущий после review выделяет одного владельца, exact717 и окно. До этого
следующие действия **не выполнять**. Три120s реплики — ограниченная воспроизводимость,
не доказательство длительной устойчивости; число speech turns определяется
фактическими решениями normal runtime, не форсируется collector.

1. Владелец проверяет version/manifest/config receipts, service inactive/MainPID0,
   отсутствие чужого8791/manual Hub, доступность terminal checks. Записывает
   fixed candidate/model/config/topology, нагрузку, условия звука/сцены и clocks.
2. Использует одобренный snapshot
   `~/reachy-release-backups/20261123-private-trace-harness-approved` и его manifest;
   проверяет зависимые helper paths без изменения кода. Его `--duration 120`
   означает local120s → remote135s → trace180s, не150s. Runtime lifetime остаётся
   lease. Dry-run harness не является разрешением `--execute`.
3. В отдельно выделенном окне вызов одной реплики:

   ```sh
   python3 /tmp/reachy-trace-acceptance.py --execute \
     --candidate 717a6577a9f7c2b3ff6dd22045761866678b37bc \
     --duration 120 --output /ABS/PRIVATE/NEW-REPLICA-DIRECTORY
   ```

   Это существующий reviewed helper, сверенный со snapshot; не новый экземпляр
   production-control start. Прежний non-private controlled stimulus, camera,
   metric reads, автономный fast/main, TTS и разрешённое motion работают совместно.
   Не запускать дополнительно motor/network/replay probes, CPU stress или fault
   injection. Для stress/loss/reconnect нужен следующий отдельно reviewed опыт.
4. Trace cap/footer/queue loss проверяются для каждой реплики. Сохранить counters,
   latest gauges и first snapshots; увеличение sampling не менять в runtime.
   Будущий observer может расширить **свою** whitelist полями уже имеющегося
   status (`lease.progress_age_ms`, `runtime.pressure`, `runtime.latency_s`) после
   отдельного review observer; старые717 данные не восполнять выдуманными значениями.
5. Любой first invalid/expiry, owner identity change, unknown terminal, busy после
   stop, trace incomplete или иная evidence failure прекращает серию. Сохранить
   первичный snapshot/stage/stack с trigger, затем штатный authenticated stop;
   не менять TTL и не перезапускать автоматически. Отсутствие expiry в samples
   не доказывает его отсутствие между ними: сверить final/first diagnostics.
6. Перед первым binding и POST/stop8791 подтвердить listener→tracked child
   PID/start_ticks, точный binding.202 — только admission; дождаться child exit,
   final accepted/cleanup_verified, все busyfalse, handlers0, verified peer stop,
   device/Mac shutdown и независимых terminal проверок. При HTTP failure — только
   identity-checked SIGTERM своего child; SSH loss/unknownexit не принятие. Сам
   `production-control stop` manual Hub не закрывает. Полная процедура —
   [PRIVATE-AUDIO-TRACE.md](PRIVATE-AUDIO-TRACE.md).
7. Следующая реплика допускается только после проверки предыдущей владельцем,
   с новым private directory и новым явным start; никакого shell loop/retry.
   После3 успешных реплик ведущий решает отдельное длительное окно. Текущий
   harness ограничен120s, а trace300s/512 records: нельзя молча снять эти caps
   или назвать360s разных boots единым soak. Длительный observer/редкий trace
   потребуют отдельного lifecycle review, но не заранее другого runtime.

## Подготовка CPU/RSS без запуска observer

`parse_proc_stat` — чистый parser сохранённого `/proc/PID/stat`, не reader и не
процесс. Будущий отдельный observer вне reducer:1Hz,≤180samples/node/replica,
только Hub/robot production child и явно выбранные Mac worker PIDs; никаких
command lines, environ, process contents. Перед/после чтения проверить PID и
start_ticks, host boot; смена → sample unknown. Linux USER_HZ через
`sysconf(SC_CLK_TCK)`, page size через `sysconf(SC_PAGE_SIZE)` у того же узла.
RSS=pages×page_size; CPU=(utime+stime)/USER_HZ. Не фиксировать100Hz/4096bytes
как универсальные. Сохранить host-local monotonic timestamp.

Optional `--resources FILE` принимает JSONL из `parse_proc_stat` плюс
`node=hub|robot|mac`. CPU delta разрешена только одной PID instance/host boot/clock
при возрастающем local time и неубывающем CPU. Результат `% одного core` может
превышать100% на multicore. RSS — snapshot distribution, не allocation rate.
Reset/missing/unsupported не превращается в CPU0. Mac parser пока unsupported:
значения null/missing до отдельно проверенного `ps` observer с process-start
identity, явными units и без command args. Этот PR проверяет единицы и reset на
синтетических `/proc` fixtures; executable observer не запускался и не заявлен.

Acoustic latency/stop deadline требуют независимых совместно привязанных
событий с оценкой clock error; пока такого инструмента нет, output — missing.
Слышимый правильный ответ717 и consumed PCM подтверждают другие свойства, но
не точное время до уха. Это остаётся отдельной измерительной зависимостью.
