# AUDIO-TURN-01: одна admission на завершённую реплику

Карточка [#39](https://github.com/notanonenough/reachy-companion/issues/39).
[Измеренный предыдущий путь](releases/2026-11-24-model-timing-receipts.md)
допускал распознанный технический 4s fragment как отдельную реплику. Следующий
fragment заменял candidate, пока первый main оставался занят. Это изменение
устраняет такую admission до окончания реплики; ускорение модели не заявляется.

## Штатный путь и совместимость

`device_audio_runtime → TurnEndpoint → AudioPeer.publish → /observation →
AudioPolling → AudioAdapter → Scheduler.ingest`.

Normal production `companion_session` явно включает `endpoint_v1=True`.
Библиотечный AudioAdapter по умолчанию остаётся legacy для существующих отдельных
fixture/probe callers. Legacy mode **отвергает** typed segments, а strict mode
отвергает payload без typed metadata. Неизвестная граница не становится final.
Device runtime по умолчанию публикует новый protocol. Старые device и новый normal
Hub не совместимы для dialogue admission: обновлять как один проверенный candidate.
Normal `production_start.py device` явно выбирает `--audio-protocol endpoint_v1`
и lease lifetime; legacy с lease отвергается до создания owner/mic/capture.

Отдельный `deploy/autonomous/realtime_audio_session.py` — старый practice probe,
используемый для `voice_memory_fixture` — сохраняет `voice-working-2`: одна source
sequence, один PCM digest и age<2000ms. Для него новый device binary запускают
**явно** с `device_audio_runtime.py --audio-protocol legacy --lifetime finite`
вместе с прежними обязательными config/output/owner/controller/duration и capture
opt-in аргументами. Его Hub command `realtime_audio_session.py` не меняется.
LegacyEndpoint использует прежний ResponseEndpoint→untyped publish без aggregate
relabel. Это отдельный finite опыт с собственным разрешением и обычным cleanup;
его нельзя использовать для приёмки normal production или нового turn contract.
Без этого producer flag legacy practice consumer отвергнет typed observations.
Untyped библиотечные fixtures сохраняют прежний путь; нового handshake нет.

Typed metadata version1 содержит:

- `turn_id`: случайная source-local identity, ограниченная 32 hex chars;
- `segment_index`: 0..2, точная последовательность внутри turn;
- `end_reason`: `deadline` или `silence`; `final` точно равен второму варианту;
- `sample_start/sample_end`: полуоткрытые смещения mono16k source capture samples;
- `clock_basis=source_capture_samples`, область identity — текущий source boot.

Это счётчик доставленных capture frames, не hardware wall timestamp и не Hub
clock. ALSA reader по-прежнему отказывает при overrun/неизвестной continuity.
Capture-age mapping и source authentication остаются у существующего transport.
Никаких выводов об идентичности человека или источнике TV из turn_id нет.

## Границы и отмена

Device сохраняет bounded unread remainder и speech-active VAD state между
deadline segments. Silence-only tail завершает уже начатую речь без требования
пяти новых voiced frames. После cap device подавляет остаток речи до настоящей
VAD-паузы; не начинает новый turn посреди той же длинной речи. Exclusion/permission
сброс уничтожает накопление. Existing 4s endpoint и VAD silence settings не меняются.

Device peer имеет отдельный bounded FIFO **одного turn: максимум три записи и
192000 mono samples (384000 bytes PCM)**. Это новый конечный предел удержания
на source; Hub PCM turn не накапливает. Один нормальный ALSA read может дать
deadline и silence segments сразу. `/observation` выдаёт один oldest segment
за запрос с исходными sequence и captured_end, без обновления свежести.
Existing poll interval остаётся 50ms. Новый turn при недоставленном старом
явно уничтожает старый FIFO; cap, discontinuity, stale oldest, permission
withdrawal и STOP очищают retained PCM и блокируют продолжение потерянного turn.
Legacy mailbox остаётся latest-only и не смешивается с typed FIFO. Source status
показывает только длину, sample count и фиксированную причину отказа.

Hub держит только один STT worker, один pending PCM slot прежнего размера и
до трёх текстовых результатов. Raw PCM turn на Hub не собирается. Результаты
склеиваются одним пробелом без угадывания/переписывания смысла. Limits: три segments,
12s source samples и 1024 characters вместе с разделителями. Recognized nonfinal
не создаёт candidate/main. Final silence с пустым STT завершает прежний текст;
пустой весь turn не создаёт utterance.

Полученный final защищён до проверки его STT: следующий raw turn может занимать
только один отдельный pending slot, его перезапись не отзывает finishing worker.
Если pending ещё занят самим final, следующий raw capture получает capacity отказ.
После final admission более новая recognized реплика использует обычный State
supersession. Никакого продления TTL или второго worker нет; глобальные отказы
по-прежнему уничтожают оба состояния. Основание и replay:
[trial002](releases/2026-11-27-audio-final-isolation.md).

Same source/capture authority, exact observation sequence, segment index и
смежные sample intervals обязательны. Gap/reorder/overwrite, ошибка STT, expiry,
cap, echo, privacy/STOP/source change уничтожают retained text; поздний worker
остаётся accounted, но не применяется. `last_turn_drop` — фиксированная причина,
не текст. Нет retry, дополнительного inference или неограниченной очереди.

Per-segment TTL прежний. Общий deadline — минимум первоначальных deadlines;
следующий segment не продлевает prefix. 12s — максимальный cap, **не гарантия
принять 12s речь** при более коротком TTL. Deployment STT TTL8s не изменён,
library fallback2s тоже. На admission проверяется earliest deadline; transcript
Sensor получает консервативный age от него с округлением вверх до milliseconds.
Lease/guards, операторские сроки и политика main admission не менялись.

## Приватная причинная связь

STT records сохраняют собственный segment metadata и исходный текст результата.
Input admission имеет отдельный aggregate lineage `source:turn:turn_id`, marker
`aggregation=endpoint_v1`, не более трёх ordered member refs, source sample bounds,
earliest deadline и digest фактического объединённого текста. Он не выдаётся за
текст одного final STT. Trace остаётся default-off и сохраняет прежние STOP/privacy
fences; public status содержит только counters/reason.

Offline baseline collector сохраняет event denominators и individual STT metrics,
но явно помечает составную audio chain `aggregate_timing_unsupported`. Он не
подменяет full-turn latency duration последнего fragment. Legacy trace calculation
не меняется. Полная агрегация интервальных метрик требует отдельной проверки
всех member/clock joins; отсутствие такой метрики сейчас видно как incomplete.

## Offline проверка и следующая приёмка

`tests/test_audio_turn.py` проверяет настоящий normal run_session с peer HTTP,
HttpSTT и Scheduler: complete question + format instruction по разные стороны
deadline дают один полный candidate и один main; silence-only tail и короткая
silence-ended реплика тоже. Burst regression использует normal 1024-frame reads:
конец речи в3.62s даёт два segments в одном read на4.02s. Они проходят две настоящие
HTTP poll при занятом первом STT; только после release допускается один полный main.
Queue checks проверяют byte accounting, caps, stale dequeue и очистку STOP/privacy. PCM и ответы моделей синтетические, аппаратного
качества VAD/STT и ускорения это не доказывает.

Отдельные checks покрывают remainder, caps, metadata validation, legacy refusal,
gap/reorder, earliest expiry equality, overwrite, error, echo, privacy, source
change, STOP и late worker. Существующие audio/device/trace/collector tests
сохраняют legacy поведение. Hardware acceptance только в отдельном окне ведущего:
один quiet normal session, цельная реплика через 4s, один правильный ответ,
actual durations и verified STOP. Нового опыта в этой карточке пока не выполнено.
