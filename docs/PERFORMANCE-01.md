# PERF-01: первый разбор задержки ответа и поворота

24 ноября 2026, [карточка #30](https://github.com/notanonenough/reachy-companion/issues/30).
Это software-изменение; установленный `717a6577a9f7c2b3ff6dd22045761866678b37bc`
не обновлялся и не запускался для этой проверки. Аппаратное сравнение ещё предстоит.

## Исходные наблюдения

Источники: [принятый ограниченный опыт717](releases/2026-11-23-717a6577a9f7.md)
и сохранённая реплика001 [BASELINE-02](BASELINE-02.md) на том же runtime717.
Вторая реплика здесь не подразумевается: replica001 прервана из-за ошибки
Mac observer acquisition и не является полным resource baseline. Из private
trace использованы только связанные task/attempt/input/authority интервалы;
тексты, идентификаторы и записи не включены в документ. Все voice-интервалы ниже
относятся к одному Hub monotonic clock, не к вычитанию часов разных устройств.

| Интервал, секунды |717, один ответ|replica001, ход1|replica001, ход2|
|---|---:|---:|---:|
| STT call |2.615|2.177|2.260|
| STT end → admission |.027|.023|.025|
| Admission → main start |1.780|.935|7.498|
| Main call |7.650|7.828|6.687|
| Main end → checked |.023|.012|.011|
| Checked → speech commit |1.261|—|1.227|
| TTS first PCM |.467|—|.335|
| TTS producer complete |.526|—|.385|
| STT end → playback stop receipt |11.887|—|16.451|
| Результат |committed|discarded, без речи|committed|

Это client/RPC-интервалы; STT/main call включают транспорт и работу сервера,
не только вычисление модели. Для replica001 ещё10 пустых STT не смешаны с двумя
распознанными ходами. First PCM не равен first audible. Точное время звука у уха
и физическое начало движения отсутствуют; из этих данных нельзя получить
p95/p99 или обещать величину ускорения всему диалогу.

| Motion receipt |717, последние4 уникальных following|replica001,2 уникальных surveying|
|---|---|---|
| Planning, s |.146/.120/.113/.112|.155/.084|
| Synchronous dispatch, s |.868/.916/1.169/1.319|1.574/1.591|
| Command duration, s |.35/.35/.35/.35|.8/.8|
| Frame age at dispatch, s |.994/.590/.860/.828|.827/.962|
| Physical onset / target arrival |missing|missing|

22 копии status во втором наборе сведены к двум request receipts, конфликтов0.
`dispatch_s` в `StockMotionAdapter.follow` охватывает весь blocking
`Hub.expression`, включая permission/pose/daemon проверки, submit и ожидание
исчезновения UUID. Это не чистый network-submit latency и не доказанное время
достижения позы. Frame age — возраст receipt, не подтверждённое время экспозиции.

Новый receipt дополнительно сохраняет `dispatch_started_at` и, при успешном
возврате вызова, `dispatch_finished_at` в Hub monotonic clock. Это вход/выход
`Hub.expression`, включая его проверки и wait, не физический onset/arrival.
`dispatch_s` вычисляется из тех же двух значений; при исключении finished
отсутствует, а не равен0. Existing sampler получает receipt и измеренную позу
с Hub-local request begin/end без дополнительного опроса. В будущем опыте
это позволит связать первый наблюдённый сдвиг позы с command request и дать
sampling bracket с учётом длительности RPC/неизвестного возраста FK. В baseline717
такой absolute anchor отсутствует; полное before/after физического onset из
старого журнала невозможно. Точность sampler порядка .2s плюс время запросов,
не точный момент начала движения.

## Причина и граница исправления

Штатный путь голоса: `Scheduler.ingest/advance` → `gateway.fast` → `State.apply`
→ единственный main Job → `State.complete` → новое решение fast → `State.apply`
→ speech adapter. Production templates задают период fast1s. Даже при свободном
fast-слоте поступивший запрос или готовый main ждал `next_tick`. Детерминированный
probe через настоящий Scheduler: quiet decision запущено в100.00 и завершено
в100.01; новое событие в100.02; раньше следующий запрос fast был только в101.00.
Лишнее ожидание .98s воспроизводится и с `enable_production`/SQLite.

Теперь новое принятое обращение, готовый main или фактическое освобождение main
при ожидающем кандидате оставляет один coalesced сигнал. Он может запустить
свежий fast view раньше quiet tick. Реактивный запуск ограничен одним за
`period_s`; обычный запуск тоже потребляет накопленный сигнал и отодвигает
следующий quiet tick. При занятом fast сигнал ждёт; catch-up и параллельных fast
нет. Старт main и commit речи остаются решениями модели с прежними
State.apply, authority/dependency/deadline, STOP и privacy проверками.
В том же probe запуск происходит в100.02, затем по-прежнему требуется fast result.
1000 событий за10s не дают более12 запусков, включая исходный quiet request;
без событий сохраняется обычный период.

Большой интервал7.498s не объявлен целиком исправленным. В replica001:

- admission второго хода:15.513245s от начала trace;
- первый main client заканчивается20.764112s, checked20.776567s (discarded);
- второй main начинается23.011362s.

Доказано5.251s перекрытия ожидания с ещё выполняющимся первым main; ещё2.247s
проходит после его client completion. Отзыв результата не освобождает занятый
вычислительный слот. Новое событие не обходит этот контракт. Последний остаток
включает fast arbitration и cadence; в trace нет timestamps всех fast calls,
поэтому нельзя приписать весь остаток одному такту. Main6.687–7.828s —
`llama_native` call с проверенным provenance, но без сохранённых prefill/decode
и transport durations. По имеющимся данным разделить эти части невозможно;
замена модели или качества не обоснована этим измерением и здесь не выполняется.

## Длительность движения

Production follow использует `StockMotionAdapter`, а не native antenna adapter.
После движения сохраняются busy/UUID fences и требование нового кадра после
completion; camera.person cadence и freshness не меняются. Planning/dispatch
накладные расходы этим изменением не объявлены устранёнными.

Фиксированные .8s для survey были комфортным default, не паспортным пределом.
Survey теперь применяет тот же minjerk расчёт, что уже использовал following:
максимум .35s, angle/rate и sqrt((10/sqrt(3))*angle/acceleration), с округлением
вверх до миллисекунды. Для yaw/body/pitch rates остаются26/20/12°/s,
acceleration320/250/160°/s². Типичный survey5°head/4°body получает .35s вместо.8
(на .45s меньше заданная duration). Крупная pitch correction требует дольше,
это не безусловное сокращение каждого движения до .35.

Не изменены gains, deadband, цель, размер шага, minjerk, pause/dwell,
absolute/slew/speed/acceleration dispatch guards и measured pose envelope.
Эти software guards — принятый ограничительный контракт, не новая сертификация
аппаратных пределов. Following уже использует эту формулу, его .35s corrections
не ускоряются. Проверены крайние позы и коррекции, прежние cancel/stale/STOP
маршруты. Реальное начало/завершение более быстрого survey проверяется отдельно.

## Воспроизведение и дальнейшая приёмка

Из рабочей копии, с Python окружением проекта:

```sh
PYTHONPATH=src:tests python -m unittest test_response_performance test_person_follow test_stock_motion_adapter test_stock_motion_routing -v
PYTHONPATH=src:tests python -m unittest discover -s tests -q
python -m build --no-isolation
```

Controlled Futures заменяют только transport/model jobs; production tests
используют настоящий Scheduler, State, Services и временную SQLite. Проверяются
число запусков, quiet cadence, bursts, занятый main/fast, late revoked results,
ready commit только после решения fast, STOP/mute/privacy; motion tests
прогоняют прежний validator на новом timing и сохраняют cancel/stale checks.
Это не аппаратные receipts. После code review и CI ведущий отдельно выбирает
exact candidate, установку и одно ограниченное сравнение motion/voice с теми же
моделями и конфигурацией. #30 остаётся открытой до фактической проверки.
