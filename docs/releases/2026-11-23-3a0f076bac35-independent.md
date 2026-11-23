# RELEASE-01: независимый опыт — кадр, движение и завершение

Карточка [#9](https://github.com/notanonenough/reachy-companion/issues/9) остаётся
открытой. **Успешный выпуск и тег не объявлены:** робот был слышен, но контрольный
ответ на2+2 не получен, причина неверного ответа пока не локализована.

Независимый reviewer провёл один опыт на неизменном установленном кандидате
`3a0f076bac3575ccc6504e8bd320ad5a50554b7f`. Версии и артефакты установки описаны
в [предшествующем авторском протоколе](2026-11-23-3a0f076bac35.md).
Этот документ составлен исполнителем по bounded evidence reviewer; reviewer
сверяет текст со своими измерениями. Данные двух опытов не объединяются в один.
Ни продуктовый код, ни runtime configs, ни limits/guards здесь не менялись.

## Восстановление начальной позы

Все времена — 23.11.2026, Asia/Baku (UTC+4). В22:43 preflight подтвердил
stopped owners, отсутствие running moves и свободное управление Hub. Работа
прошла через штатные Hub actions и существующий operator grant; SDK/direct
motor bypass не применялся.

1. Штатный `sleep`, receipt22:43:27.878: completion_observed=true,
   moves_observed=1. Body yaw приблизился к нулю, но motors остались **enabled**.
   Отдельные измерения22:43:34 и22:43:45 подтвердили enabled. Предположение
   «sleep обязательно переводит в disabled» оказалось неверным; wake не выполнялся.
2. После согласования с ведущим выполнен один существующий Hub `neutral`
   expression, receipt22:44:42.959, ok=true, steps_observed=1. Цель head/antennas
   zero, body=None; длительность шага1.5s. Измеренная после него поза:
   head yaw0.413°, pitch4.194°, body yaw−0.352°. Она прошла прежний follow guard.

Это изменение физической позы через разрешённые операции. Лимит envelope не
расширялся, latch старого сеанса вручную не сбрасывался; далее создан новый
обычный сеанс. Stock receipt сам сообщает pose_verified=false и
hard_stop_certified=false; измеренный feedback приводится отдельно.

## Один обычный сеанс

| Действие | Время / результат |
|---|---|
| normal start begin/end | 22:45:22.046 /22:45:36.560, exit0 |
| camera_on end | 22:45:37.780, accepted=true |
| Независимый Mac mic capture begin | 22:45:39.113 |
| Синтетический акустический вопрос2+2 через Mac speaker | 22:45:43.094–22:45:48.055, exit0; не text injection |
| Предел90s / stop begin/end | 22:47:05.110 /22:47:07.496, exit0 |
| shutdown end / camera_off end | 22:47:08.276 /22:47:08.889, exit0/off |
| Стенд явно освобождён reviewer | 22:49 |

Сохранено424 status records, из них351 ACTIVE, последний elapsed90.637s.
`first_reducer_expiry` и `first_lease_invalid` не возникли; max reducer tick gap
106.128ms, worker scheduling gap136.727ms, lease transport errors0. Это ещё одно
ограниченное невоспроизведение прежнего reducer stall, не доказательство его
причины или устранения. Monotonic значения разных helper-процессов не склеиваются;
для их порядка использованы записанные UTC timestamps.

## Кадр и физическое движение

Два ранних frame helper вызова ошиблись уровнем ключей config и завершились
**до** сетевого `/frame` запроса. Исправлен только временный диагностический
reader: `gateway.vision` / `production.sensors`; продукт и конфигурация не менялись.

| Успешный `/frame` receipt | Sequence | Age / TTL |
|---|---:|---:|
| 22:46:14.574 | 26451615 | 208ms /1500ms |
| 22:46:19.105 | 26451755 | 54ms /1500ms |

Оба имеют один source generation и разные sequence/content hashes. Первый JPEG
reviewer лично открыл и подтвердил реальное непустое изображение; второй
визуально не открывался. В рамках опыта **свежий полученный видимый кадр
подтверждён**. `exposure_age_known=false`: возраст receipt не превращается
в известное время экспозиции. Изображения и описание частной обстановки в Git
не включены.

В ordinary runtime наблюдались33 completed motion, tracking_mode=following,
tracking_error=null. Независимые measured pose samples дали диапазоны:

| Координата | Диапазон |
|---|---:|
| Head yaw | −6.19…59.47° |
| Head pitch | −8.60…5.03° |
| Body yaw | −8.88…48.96° |

Следовательно, физическое движение и feedback подтверждены отдельно от command
receipts. Это не сертификация hard stop и не доказательство точного достижения
каждой целевой позы. В последнем ACTIVE motion execution_busy=false; аварийное
прерывание активного движения этим stop не проверено.

## Завершение и неизменность профиля

Hub final accepted=true, cleanup_verified=true, errors=[], cleanup_issues=[],
все execution_busy=false; elapsed91.383s. Получен peer terminal ACK:
stop_known=true, execution_busy=false, terminal_unknown=false. Device final
accepted=true/controller_stop, elapsed94.556s, microphone_restored=true,
capture_closed=true, playback stop_known=true/execution_busy=false.

Независимые проверки после shutdown подтвердили microphone/camera off,
capture/reader/process closed, running moves=[], robot production/camera
MainPID0/inactive и Hub production MainPID0/inactive. На Mac project jobs
отсутствуют, порты18097/18098/18099/8082/8097 закрыты.

В восьми measured pose samples за≈1.12s после stop диапазон yaw≈0.372°,
body≈0.264°. Это ограниченная стационарность с небольшими вариациями измерений,
не точный ноль и не измерение hard-stop deadline. Reviewer локально сравнил
personality/principles с backup перед3a0: unchanged=true. Значения/хеш профиля
не экспортировались.

## Слышимый ответ и оставшийся acoustic gate

Владелец сообщил, что слышал ответ Ричи после заметной задержки: по смыслу
«число — назови его», вместо ожидаемого4. Это независимое подтверждение
**слышимого вывода**, но контрольный ответ неверен. Задержка здесь качественная:
численное end-to-end время этим сообщением не измерено.

Actual STT распознал два фрагмента4.00s/1.04s; модельная и TTS цепочка оставила
связанные owner/task/turn/digest receipts, один TTS output24334frames.
Исходные тексты actual STT и model output не сохранялись. Частная независимая
Mac запись содержит79.605s PCM; её offline ASR распознал полный контрольный
стимул, но отдельный robot reply не выделил. PCM/wall alignment не проверен.

Поэтому акустическая цепочка «полный вопрос→правильное STT→правильный ответ→
слышимый robot output» **остаётся OPEN**. Нельзя по счётчикам или digest receipts
решить, потерялся ли текст при сегментации/STT либо неверный ответ выбрала модель.
Телевизор оставался включённым; фоновая речь не считается обращением или
идентичностью владельца. Следующий диагностический шаг определяет ведущий с
техлидом; этот протокол не разрешает повторный старт.

## Evidence и проверка

Закрытый корень reviewer:
`/Users/notanonenough/reachy-review-evidence/20261123-3a0f076bac35`.
Content-free evidence: preflight/sleep/neutral/pose/frame metadata JSON и
`trial/{actions,status,final-hub,final-device,final-independent-robot,
final-independent-mac,audio-content-free-evidence,reviewer-summary}`
(`status.jsonl`, остальные `.json`). Private WAV/JPEG/transcripts в PR не входят.

Final reports на узлах: Hub
`data/production-875b7cbb9a544291bb1d548c1f268cd3/hub.json`, robot
`data/production-8571e0c926364f97a06cffce369073ee/device.json`.
Версию и source hashes можно сверить read-only командами из
[протокола установки](2026-11-23-3a0f076bac35.md#доказательства-и-повторяемая-сверка)
в согласованном окне. Полный выпуск остаётся незавершённым до принятого решения
по неверному ответу и acoustic gate.
