# MODEL-LATENCY-01: что входит в ожидание основной модели

24 ноября 2026, [карточка #33](https://github.com/notanonenough/reachy-companion/issues/33).
Аудит выполнен офлайн от `4ff1bf225`. Изменены только этот документ и описание PR.
Новых запросов inference, SSH, process/service probes и аппаратных запусков нет.
Модели, настройки, runtime, collector и observer не изменены.

**В трёх связанных голосовых запросах измерено 6.687–7.828s полного main client
call. Его разложение на транспорт, токенизацию, ожидание backend, prefill и decode
пока отсутствует.** Имеющаяся информация позволяет назвать конкретные недостающие
измерения, но не выбрать доказанно более быстрый inference backend или модель.
PERF-01 отдельно меняет scheduler cadence; он не сокращает сам main call по
доказательству из этих старых данных.

## Версия и действительный путь

Все численные voice observations ниже относятся к установленному
`717a6577a9f7c2b3ff6dd22045761866678b37bc`, до PERF-01. Источники:
[принятый опыт717](releases/2026-11-23-717a6577a9f7.md),
[прерванная replica001](releases/2026-11-24-baseline02-replica-001.md) и
[разбор PERF-01](PERFORMANCE-01.md). Текущий аппаратный опыт другого исполнителя
не включён в эту выборку. Replica001 не является принятым baseline трёх узлов:
Mac resource acquisition не состоялся.

Следующие anchors проверены в717 и в базе этого документа. Gateway, private trace,
main model template, launchd main template и artifacts lock между ними одинаковы.
Scheduler в базе уже содержит PERF-01; для исторической cadence используется717.

| Участок | Реальный caller и граница |
|---|---|
| Hub main slot | [runtime.py](../src/reachy_companion/autonomous/runtime.py), `Scheduler.advance/_drain`, `Job`: один main Job; discard результата не означает завершение работающего Job. Job start и trace start — разные anchors. |
| Измеренный client call | [private_audio_trace.py](../src/reachy_companion/private_audio_trace.py), `main_call`: один Hub `monotonic()` перед `main_request` emit, затем `function(task)`, затем `ended_at` при возврате. Включает небольшой bounded trace enqueue перед вызовом. Не включает ожидание candidate до этого start. |
| Hub → Mac | `RemoteGateway.main/inference/call` в runtime: JSON POST `/main`, request identity = task attempt, полное чтение ответа ≤65536 bytes и decode. [Tunnel template](../deploy/current/mac/launchd/local.reachy.tunnels.plist.template) переносит Hub localhost8097 на Mac localhost8097 через SSH reverse forwarding. Timeout не служит cancellation ACK; production не repost inference. |
| Gateway admission | [gateway.py](../src/reachy_companion/autonomous/gateway.py), `Handler.do_POST`, `Gateway.generate`: проверка envelope/dependencies, отдельный main lock с `blocking=False`. Занятость даёт409, не ожидание в Python-очереди. HTTP handlers ограничены8; это не число inference slots. |
| Подготовка и токенизация | `ModelBackend.generate/generate_loaded/count`: проверка audited model, bounded companion envelope, сериализация; **два последовательных `/tokenize` RPC** — system+content и полный formatted prompt. Проверяются text/template/context budgets. Их duration не сохранена. |
| Native completion | `generate_loaded`: один `/completion`, `n_predict=256`, `temperature=.2`, `stream=False`, `cache_prompt=True`. Для spoken response используется JSON schema с единственным response. Gateway ждёт полный ответ, проверяет terminal stop и JSON, строит provenance. |
| Возврат | Gateway JSON encode/write → tunnel → Hub read/decode → trace result → позже `State.complete` и fast arbitration для speech commit. Отдельная задержка end→checked не является decode модели. |

Это собственный serving/client код. Реализация очереди/slot scheduling, KV-cache,
prefill и decode внутри внешнего `llama` здесь не vendored и не была исполнена
или восстановлена по исходникам в этом аудите. Поэтому их подробное поведение
не выводится из имени флага. Сохранённая конфигурация717 сверена с
[main template](../deploy/current/mac/config/config.autonomous.mac.local.json.template):
Qwen3.5-9B-Q4_K_M, audited Metal, build `b11941-19ff817fb`, context8192,
input cap3000, template cap256, output reservation256, reserve256. Это лимиты,
**не фактическое число токенов конкретной реплики**.

[Launchd main template](../deploy/current/mac/launchd/local.reachy.llm.plist.template)
передаёт `-c 8192 -np 1 -ngl 99 --reasoning off --cache-ram 512`.
512 — настроенное значение CLI, не измеренное потребление памяти/попадание в кэш.
[Artifacts lock](../deploy/current/artifacts.lock.json) закрепляет binary build и
GGUF SHA256; веса занимают5680522464 bytes на диске. Это не RSS, GPU allocation
или размер KV-cache. Наличие `cache_prompt=True` и стабильного prefix ordering в
gateway — намерение переиспользовать prefix, не evidence hit для этих requests.

## Наблюдаемые величины и пробелы

Обозначения источников: A — private717 `trace-trial/correlation-bounded.json`;
B — private replica001 `performance-intervals.json`. Обе проекции ранее независимо
сверены с trace по task/attempt/input/authority; публично используются только
порядковые labels A1/B1/B2. Полные тексты, prompts, profiles, записи и private IDs
в этот документ не входят. `observed` означает сохранённые timestamps/metadata;
разности timestamps в таблице помечены `derived`.

| Величина | Статус, значение | Clock / linkage / n | Источник и предел вывода |
|---|---|---|---|
| Main start/end | observed | Hub monotonic каждого сеанса; A1, B1, B2; n=3 pairs | A/B, `main_request/main_result` пары. Не общий clock двух сеансов. |
| Main client elapsed | derived: A1 7.649993s; B1 7.828230s; B2 6.687042s | Разность своей пары; n=1+2 | A/B. A1/B2 готовы к speech, B1 discarded. Не compute-only и не распределение production p99. |
| Admission → main start | derived: A1 1.779605s; B1 .935340s; B2 7.498118s | Hub, тот же input lineage; n=3 | A/B. Включает scheduler/arbitration/занятый main; не очередь llama. |
| B2 admission → B1 main end | derived: 5.250867s | Один Hub session, два явно связанных последовательностью slot requests; n=1 overlap | B. Доказывает пересечение с незавершённым предыдущим client call, не GPU busy duration. |
| B1 main end → B2 main start | derived: 2.247250s | Тот же session; n=1 gap | B. Включает дальнейшую arbitration/cadence; timestamps всех fast calls отсутствуют. |
| Main end → checked | derived: A1 .023191s; B1 .012455s; B2 .010806s | Hub, тот же task/attempt; n=3 | A/B. Дренирование/проверка результата, не чистая стоимость validation. |
| Checked → speech commit | derived: A1 1.261417s; B2 1.226927s | Hub, каждый свой accepted answer; n=2 | A/B; для discarded B1 отсутствует. Не смешивать с model latency. |
| STT client recognized | derived: A1 2.615217s; B1 2.176780s; B2 2.259907s | Hub, свои chunks; n=3 | A/B. Отдельно36+10 empty результатов; не усреднять вместе ради voice latency. |
| TTS first PCM / producer complete | observed adapter intervals: A1 .466630/.526200s; B2 .334854/.385376s | Локальный elapsed adapter в Hub; n=2 | A/B. First PCM не first audible и не первый токен LLM. |
| Tokenization1/2, gateway preparation, server queue, prefill, decode, serialize, network | missing duration | Ни одного request-linked stage pair для A1/B1/B2; n=0 | В client call входят неизвестные части; нельзя получить их вычитанием несвязанных status/других запусков. |
| Фактические input/output/cached tokens и TTFT | missing для A1/B1/B2 | n=0 связанных retained samples | Native response может дать `tokens_predicted`; gateway возвращает usage с точными input counts и output count, если доступен. `main_call` usage не сохраняет; native timings/TTFT gateway не переносит. |
| Cache hit, cold/warm, server load/CPU/GPU для этих calls | missing | n=0 per-call доказательств | Restart сервиса не доказывает disk-cold; три Mac gauges в baseline не получены. Нельзя объявить bottleneck compute/memory/cache. |

Для B2 `5.250867 + 2.247250 = 7.498118s`: это полное разбиение **ожидания до
main start**, не разложение main6.687s. A1, B1 и B2 не складываются между собой.
Не делим число символов ответа на время и не называем результат tokens/s.
Действующие200ms guard — отдельная норма управляющего progress, не latency budget
генерации; менять её ради этих секунд не предлагается.

Дополнительно найден старый локальный `data/stability/model-9b-benchmark.json`:
сохранены четыре числовых usage с input238/232/184/244 и output33/16/12/11,
а также seconds2.881/1.934/1.473/1.662. Его audit совпадает с model/build выше,
но нет связи с A1/B1/B2, boot/request/clock anchors, доказанной cache state и
полного протокола этих seconds. Это подтверждает наличие числового usage в
ответе прежнего probe, **не объясняет ускорение/замедление717**. Поле input и
тексты result не выводились и не использовались для token estimate. Полные
prompts/profile не читались ради приблизительного подсчёта токенов.

В сохранённых наборах A/B нет per-request native server timing receipt.
Текущие live/rotating Mac logs не использовались: они относятся также к другому
владельцу и не являются frozen evidence этих calls. `production_logs.run_logged`
сохраняет child output с rotation, но не добавляет gateway attempt correlation.
Даже найденная строка llama timing без такого join не заполнит таблицу A/B.

## Локальная воспроизводимость

Private evidence остаётся в каталоге владельца `reachy-release-backups`:

| Файл | SHA256 |
|---|---|
| `20261123-717a6577a9f7/trace-trial/correlation-bounded.json` | `2877dce4896b18b49eb8b7ab5d174cc91b25fe360cc4be753661d9c7c44afb22` |
| `20261124-baseline02-replica-001/performance-intervals.json` | `ff852433f4da77f62257d673dd550a0e40be01a098005195f252c486477b1316` |
| Отдельный старый `data/stability/model-9b-benchmark.json` | `db0fd7a5151f736febc298b152cbc65423343bfd30517d0d451d3799aaa1dfa5` |

Команда только читает две bounded проекции; без imports runtime, network,
моделей, процессов и записи. Аргумент — локальный private backup root.
Исторические ключи A `main_compute/stt_compute` переименованы в выводе: их
названия не делают client interval вычислительным временем.

```sh
python3 - "$HOME/reachy-release-backups" <<'PY'
import hashlib, json, math, pathlib, sys
root = pathlib.Path(sys.argv[1])
specs = [
    ('20261123-717a6577a9f7/trace-trial/correlation-bounded.json',
     '2877dce4896b18b49eb8b7ab5d174cc91b25fe360cc4be753661d9c7c44afb22'),
    ('20261124-baseline02-replica-001/performance-intervals.json',
     'ff852433f4da77f62257d673dd550a0e40be01a098005195f252c486477b1316'),
]
items = []
for name, expected in specs:
    raw = (root / name).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == expected
    items.append(json.loads(raw))
a, b = items
first, second = b['voice_chains']
t1, t2 = [c['timeline_hub_since_trace_start_s'] for c in (first, second)]
overlap = t1['main_end'] - t2['admission']
gap = t2['main_start'] - t1['main_end']
assert overlap > 0 and gap > 0
assert math.isclose(overlap + gap, second['admission_to_main_start_s'], abs_tol=1e-9)
for c, t in ((first, t1), (second, t2)):
    assert math.isclose(t['main_end'] - t['main_start'], c['main_client_s'], abs_tol=1e-9)
assert [c['main_outcome'] for c in (first, second)] == ['discarded', 'ready']
print(json.dumps(dict(main_client_s=[a['hub_local_seconds']['main_compute'],
    first['main_client_s'], second['main_client_s']],
    overlap_s=overlap, gap_s=gap,
    wait_before_second_main_s=overlap + gap), indent=2))
PY
```

## Минимальный следующий опыт — предложение, не разрешение запуска

Сначала отдельная карточка instrumentation: content-free gateway/backend stage
receipt для одного exact attempt с boot/clock domain, input/output token counts,
cache processed/reused counts, gateway receive/admit, обе tokenize start/end,
completion submit/first token/full response и validation/serialization anchors.
Каждый anchor обязан иметь определение, missing/unsupported вместо0. Не сохранять
prompt/profile/token IDs; один non-private синтетический фиксированный fixture
с digest/размером и зафиксированным template достаточно для одинакового input.
Этот PR не добавляет hooks и не включает получение таких данных.

После review и отдельного окна предложен минимальный пилот из шести serial calls
через обычный Hub client/gateway path, без второго владельца/motion:

1. Зафиксировать candidate, binary/model/tokenizer hashes, effective settings,
   один identical synthetic companion envelope, seed/доступные sampling defaults,
   output cap/schema. Температура остаётся.2; одинаковый input не гарантирует
   одинаковый output, поэтому counts и termination обязательны. Не менять seed
   молча относительно штатного settings. Зафиксировать сопутствующие workers.
2. Три отдельных пары: разрешённый cold-server/cache-empty start → один call;
   затем точный повтор на том же boot без intervening inference → warm call.
   Получается n=3 cold-server и n=3 warm. Cache-empty/hit принимаются только по
   фактическим receipts; иначе label unknown. Это не OS page-cache cold и не
   инструкция сбрасывать OS caches. Model load/readiness duration считать отдельно
   от main call. Перезапуск сервера — только в будущей отдельной разрешённой схеме.
3. Client TTFT возможен лишь если действительно наблюдаем token delivery.
   Сейчас `stream=False`: full-response arrival нельзя назвать TTFT. Предпочтителен
   server first-token anchor при прежнем transport; это **server TTFT**. Streaming
   observer/client требует отдельной reviewed ветви сравнения, одинакового input
   и явного отличия transport mode; не выдавать её за неизменный production path.
4. Считать durations только внутри своего monotonic domain. Связать Hub attempt
   и backend request/slot receipt явным ID. Server durations можно сопоставить
   client total, но не вычитать absolute Mac timestamps из Hub. Остаток после
   вычитания доказанно вложенных непересекающихся intervals — unallocated overhead,
   не автоматически network. Потерянные/error/cancel calls включать в denominator.
5. По каждому call сохранить TTFT или missing, full completion, counts, cache
   state, termination/outcome. Представить все шесть значений, не p99/SLO. Один
   acquisition/identity/guard failure прекращает серию с штатным cleanup; retry
   не заменяет неудачный sample. Hardware/speech onset сюда не подразумевается.

Такой пилот разделит хотя бы tokenization, server execution и client overhead,
а cold/warm пары проверят, помогает ли cache на **этом одинаковом input**. Это
ещё не распределение реальных меняющихся companion contexts, не quality test
и не основание обещать скорость в быту. Resource observer требует своей принятой
зависимости; отсутствие его Mac измерений нельзя заменить «CPU0».

## Варианты после измерения

Все эффекты ниже — гипотезы без численной оценки ускорения. Следующее решение
выбирается по измеренному доминирующему участку и отдельному согласованному scope.

| Вариант | Что проверять сначала | Цена / ограничение |
|---|---|---|
| Уменьшить лишнюю подготовку/tokenizer RPC | Время двух counts; возможность сохранить точный budget proof одним согласованным tokenizer API | Нельзя просто удалить guard/count. Кэш counts требует точного input/model/tokenizer identity и bounded memory. |
| Улучшить reuse стабильного prefix | Реальные reused/processed tokens и cold/warm same-input pairs; стабильный порядок уже есть | Дополнительный cache потребляет память; изменяющийся context может не давать reuse. `cache_prompt=True` уже включён. |
| Сократить контекст или вывод | Фактические input/output counts, prefill/decode доли и response completeness | Потеря grounding/памяти/качества или truncated JSON; output cap256 уже существует, не утверждать что генерируются все256. |
| Ранний streaming к TTS | Server TTFT и время до validated complete answer | Меняет нынешний atomic checked-final/authority/STOP контракт; текст до полной validation нельзя автоматически озвучить. Не равен ускорению full completion. |
| Менее дорогая модель/другая quantization/backend | Сначала одинаковый-input baseline и отдельный русский quality/grounding набор | Качество, память, unsupported kernels; меньший файл не доказывает меньшую latency. Миграция вне этого аудита. |
| Больше slots/concurrency или cancellation устаревшего main | Доказанный blocked demand и terminal cancellation semantics | Throughput может расти ценой latency/памяти; отмена client Future не останавливает backend. Нельзя снять busy/unknown fence до terminal ACK. |

Ближайший обоснованный шаг — принять узкую content-free stage instrumentation и
fixture для одинакового input. Выбор модели, нового streaming-контракта или
параллелизма до этих измерений был бы экспериментальной гипотезой, а не исправлением
установленной причины main6.7–7.8s.
