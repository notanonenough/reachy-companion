# Trial002: завершённая реплика отозвана новым raw capture

Продолжение [#39](https://github.com/notanonenough/reachy-companion/issues/39).
Один 90s опыт на `20ccaad220e39e288dab1a3c7e8b535baa70ee54` завершился
с `cleanup_verified=true`, но без audio admission и ответа. Complete private
trace: 66 records, dropped=0; четыре main calls были фоновыми, не голосовыми.
Чистое завершение сеанса не является приёмкой voice behavior.

## Локальные основания

Private directory:
`/Users/notanonenough/reachy-release-backups/20261127-20ccaad220e3/combined-trial-002`.
Raw тексты и акустическая запись здесь не публикуются. Анализ не выполнял
живых probes или повторного inference.

| Artifact | SHA256 |
|---|---|
| `private-trace.jsonl` | `4b6cdf05e42c1de9117fd04dba7d601012d58faf0181afb6cf71d2c27682d23b` |
| `status.jsonl` | `c248dcbfec4c0771bea97e93b40e418314c64ec0497d1c25e92f2e7427f0c6e6` |
| `final-hub-motion.json` | `9ffb7514e333386f334d745bcaf9f4c49062e38f4c56a46f318df36015f1839f` |
| `final-bounded.json` | `0b667f5dd9d2e2530c9f99d8edbafa637bdf65183f0197f1f1349e4aea205e9d` |

Times ниже — Hub monotonic относительно trace_begin; source sample intervals
сверены отдельно и не вычитаются из Hub clock.

| Sequence / один source turn | Capture end | STT start | STT end | Результат |
|---|---:|---:|---:|---|
| 2 / index0, deadline, nonfinal, 4.00s | 10.158350 | 10.270089 | 12.983580 | 26 chars, recognized/fresh |
| 3 / index1, silence, final, 2.82s | 12.979193 | 13.048852 | 15.419705 | 30 chars, stale |

У обоих одинаковый turn_id/source_boot; source intervals `[96960,160960)` и
`[160960,206080)` смежны. Значит VAD/capture, typed metadata, доставка обоих
сегментов и два непустых STT результата наблюдались. Точное качество
распознавания и акустическое окончание человеческой речи эта таблица не измеряет.

Earliest deadline = `436002.801484873 + 8 = 436010.801484873`.
Final STT завершился в `436008.0628395`: оставалось **2.738645s**. Его stale
нельзя объяснить истечением этого TTL. Status показывает submitted4 при elapsed
14.663s, затем submitted5/overwritten1 при15.218s, пока started оставался3.
После возврата final стало stale1. Sequence4 не дошла до STT; sequence5 дала empty.
Итог: submitted28, started27, completed0, overwritten1, stale1, turn_dropped2,
last_turn_drop=`overwritten`, STT errors/timeouts0.

`input_blocked=2` уже присутствовал в первом status elapsed0.179s и не увеличивался
в течение опыта. Первый STT был позже6s; этот счётчик не объясняет потерю вопроса.
Он общий для blocked utterance и sensor admission; точные два ранних события
в данных не идентифицированы. В trace нет ни одного `input_admission`.

## Причина и исправление

В `AudioAdapter.submit` новый index0 отзывал текущий turn общим `_withdraw`,
увеличивая generation. Следующая перезапись pending также отзывала весь adapter.
Таким образом фоновый raw capture обесценивал уже захваченный final, который ещё
распознавался, хотя его authority и earliest TTL оставались действительными.
Event-controlled replay на принятом коде воспроизвёл stale1/completed0 при2.7s
оставшегося TTL. Согласованность кода, timing и counters подтверждает механизм;
точное время обоих `_withdraw` исторически отдельно не записывалось.

Теперь завершённый по endpoint active turn защищён до проверки результата STT.
Единственный pending slot может содержать следующий index0 с его исходным
capture deadline. Перезапись только этого следующего slot не меняет generation
active worker и не уничтожает retained text. Если pending ещё занят final самого
active turn, следующий raw capture отвергается по capacity. Continuation без
сохранённого prefix не превращается в новый turn.

После завершения active final следующий pending начинает распознавание без
обновления deadline. Empty/background result не заменяет признанный вопрос.
Новая настоящая recognized реплика затем использует обычный State supersession:
это не гарантия двух main calls и не смешивание текстов разных turns.
Остаются один worker, один pending PCM, прежние text/sample caps и TTL.
Настоящие STOP/privacy/source/authority/echo, active expiry и STT error по-прежнему
отзывают состояние целиком; старый final при expired authority не применяется.

Регрессия через actual run_session → peer HTTP → HttpSTT → Scheduler воспроизводит
тот же порядок: initial empty seq1; question seq2; held final seq3; pending seq4;
overwriting background seq5; затем release final. Ожидаются один полный audio
input/main, один overwrite и ноль stale; seq5 остаётся empty. Дополнительные
проверки покрывают protected final в pending, missing next prefix, сохранение
original deadlines, real next-turn supersession и глобальные отказы. Это offline
доказательство исправления механизма; повторный физический опыт назначается
ведущим отдельно.
