# PERF-01: полный trial004, правильное значение и раздельная акустическая проверка

27 ноября 2026, [#30](https://github.com/notanonenough/reachy-companion/issues/30).
Точная установленная версия `6d87fffeeefb80cdc56b7cf19f8a96ec6786a920`.
Один normal90s опыт завершился штатным STOP, known exit0 и подтверждённым cleanup.
Один aggregate дошёл до правильного арифметического значения в полной фразе и
подтверждённого device PCM. Независимое акустическое подтверждение ответа пока
**unknown**. Это протокол измерений, не выпуск и не закрытие всей #30.
Для этого bounded release обязательный открытый gate — слышимость правильного
ответа; numeric-only остаётся ограничением опыта, а не новым release gate.

## Установка и откат

Один clean archive716files, wheel/sdist128packagefiles и canonical61 проверены
независимо: source/effective imports всех трёх узлов, Linux site packages,
single metadata и фактические deploy `production_start.py`/`device_audio_runtime.py`.
Mac ROOT ровно candidate. Перезапущены только project base services;
factory/Bluetooth/tunnel сохранены. Runtime configs21 (Mac8/Hub7/robot6)
byte-equal принятым; legacy sensors, profile и физические guards не менялись.
После опыта personality/principles отдельно сравнены с backup: unchanged.
Configs после опыта повторно не перечитывались.

| Артефакт | SHA256 |
|---|---|
| Archive | `4416fc3239e39397af2d3c3937754e1ac20c31cbda6131163bd33929b907b4d0` |
| Wheel | `0e0c11ce627b47efc930632a07952e938dc51741aecefc0f15469eb52c820f99` |
| Content manifest | `85311e215d6982ab818337351e64b55f77f06d364e28c3075de97d37a015dae1` |
| Installation manifest56 | `b9900e9018fc5feaae42e5a541a73746cf9428ac25cc9ccd8f0027248a836d03` |

Backup предыдущего `2c17c0ff6b7d499d9d2e8082651d12ea34cee676` содержит actual
packages (260files на каждом Linux-узле), hashes/modes, SQLite quick_check OK,
прежние archive/wheel, Mac source/config/plists/metadata. Откат при отдельном
назначении: STOP/free, восстановить actual packages **и** source/current,
перезапустить project bases, сверить import/config identities. Старые leases,
очереди и поздние owner edits не восстанавливать. Откат не выполнялся.

## Единственный голосовой опыт

Global trial004 — новый candidate-local `combined-trial-001`. Original harness
44ee0de5/aa231080 неизменён; launcher
`70538ec9adf703fa84e437924731cb1a5c748b03f4afb83363868b6b2e33eaa8`,
abort30d05f07. Candidate/path-only delta независимо проверена,17 reader fixtures,
original snapshot/literal hashes и zero-action dryrun PASS. Observer v3 не запускался.
До старта enabled/free/moves[], yaw6.412°, pitch1.219°, body11.338° проходят
прежний measured_pose guard. Wake/recovery не нужны. Других project workloads
во время опыта не было; равенство условий комнаты прежним опытам не установлено.

| Событие, Asia/Baku | Время |
|---|---|
| Fresh stopped/free / fresh pose |17:55:19.665 / 17:55:37.894|
| ACTIVE/listening |17:55:58.672|
| Camera on / независимая Mac capture |17:56:01.348 / 17:56:02.684|
| Один synthetic acoustic вопрос |17:56:06.684–17:56:11.019|
|90s boundary / authenticated STOP ACK |17:57:28.645 / 17:57:29.803|
| Known foreground exit0 |17:57:31.029|
| Device/Mac shutdown / camera off |17:57:32.705 / 17:57:33.376|
| Independent finals / private trace после exit |17:57:34.996 / 17:57:35.875|

Trace74records+footer, dropped0, incomplete false. Seq6 deadline/nonfinal и seq7
silence/final одного turn, contiguous capture intervals, actual joined digest,
один audio input/task/attempt/main, checked authority/proof и speech commit
сопоставлены. Арифметический вопрос распознан, окончание инструкции формата — нет:
final1.22s segment дал empty STT. Поэтому ответ содержит правильное значение4
в полной фразе, **не только число**. Нельзя приписывать модели нарушение полностью
сохранённой инструкции. Два поздних autonomous main не дали второго speech.
28235 frames одного TTS потока совпали с device_consumed_pcm и verified stop.

| Hub-local interval,s | Значение |
|---|---:|
| Prefix STT call |2.463811|
| Final mapped capture end→final STT start |1.404407|
| Final STT call |2.346427|
| Final result→aggregate admission |.029407|
| Admission→main start |.926201|
| Main client call |7.962366|
| Main end→checked |.023254|
| Checked→speech commit |.900297|
| Speech commit→first producer PCM |.419558|
| Final mapped capture end→first producer PCM |14.011919|

Prefix STT перекрывается с capture: не складывать его повторно. Это n=1,
Hub receipt mapping, не конец слышимого вопроса→first audible sound.
Native same-call reports: prompt6.735334s, predicted1.136197s,1207input/18output,
reported_cache_n0. Main client включает transport, tokenization и validation.
Оставшаяся задержка не названа исправленной быстрым scheduler wake.

Независимый Mac WAV70.571s: primary offline ASR выделил контрольный вопрос
(2.54–5.90s PCM), ответа не выделил. Дополнительный bounded8–45s анализ с gain12,
без VAD, также не дал надёжного совпадения ответа. Это **unknown**, не доказательство
тишины. PCM/wall alignment не подтверждён. Фактический TTS PCM не сохранён;
один hash не позволяет восстановить waveform для сравнения. Сам consumed PCM
не является свидетельством слышимости в комнате. Сырые WAV/trace/transcripts
остаются приватными; человеческое прослушивание/свидетель — отдельное доказательство.

## Движение и terminal receipts

1190 повторных receipt observations сведены к27 accepted и одному late failed
motion; conflicting duplicates0. Command duration .350–.425s (median .379),
planning median .099s, expression dispatch .805–1.212s (median1.037).
Исторический3aea median1.204s и current1.037s — разные сеансы, не рандомизированное
сравнение и не физический onset. Время expression включает проверку/submit/wait.

43 quiet pre-dispatch samples: jitter yaw.146°, pitch.058°, body.088° <1°.
Принятый критерий1° и две последовательные same-axis samples в направлении target
наблюдался27/27. Target-near allaxes≤1° два samples — **0/27**: достижение цели
не доказано. FK age неизвестен; receipt brackets не измеряют физический onset
или .35s trajectory. Calibration/offset/limits не менялись.

Hub accepted/cleanup true, first-invalid и reducer-expiry отсутствуют, errors[],
все owned jobs false; peer stop known, handlers0/listener closed. Device accepted,
capture closed/microphone restored/playback closed/stop known; owner/source joins
совпали. Terminal drain .552888s из8s, completed, remaining0, no overrun.
Motion stop known, stock first-failure null. Причину late failed dispatch нельзя
установить по одному общему exception; он не делает подтверждённый STOP unknown.
Independent services inactive/PID0, Mac jobs0/ports closed, mic/camera off/moves[].
8 post-stop samples за1.172s: yaw range.152°, pitch.101°, body.088° — bounded
stationarity, не hard-stop deadline. Никаких повторных голосовых запусков.

## Отдельная камера и границы приёмки

После завершения trial004 ведущий отдельно разрешил camera-only проверку с
минимальным ordinary mic owner. CAS `/microphone` использует `listen=false`,
без device audio runtime/аудиозахвата; panel camera_on, только camera-sensor unit,
producer `/frame`, затем camera_off, exact-owner mic off и stop camera unit.
Первый шаг18:02:23–18:02:27: frame assertion после фиксированных2s не прошёл;
availability до assert не retained, точная причина не установлена. Cleanup PASS,
operator policy прежняя. Journal содержит обычный start/stop,4.042s CPU startup.
Проверка готовности только по elapsed time признана недостаточной; отдельно
разрешён один диагностический повтор с bounded content readiness и сохранением
каждого результата.

Диагностический повтор18:03:16.791–18:03:21.536 прошёл:8 probes за~3.78s
(первый URLError, затем disabled, затем available), один сохранённый JPEG.
Producer source `0f86bd82-6045-4701-b7c0-be47c353f9f0`, sequence202338,
receipt age76ms/TTL1500; exposure age unknown. JPEG SHA256
`8cf1eaaa754cd8cd7b7cabc27292fb745934001fe30569ed859851e0c944748d`.
Автор и независимый reviewer локально подтвердили непустой видимый кадр;
содержание/изображение не публикуются. Это producer `/frame` отдельного
camera-only цикла, не кадр90s trial и не новая проверка Hub relay.
Mic/capture/listening off, owner released, camera off, camera/production PIDs0,
policy unchanged; errors/cleanup_errors пусты. Аппаратное окно освобождено.

Private evidence: `~/reachy-release-backups/20261127-6d87fffeeefb/combined-trial-001`
и соседний `camera-only`; raw content в Git не переносится. Исторические
intermittent failures не объявлены полностью устранёнными по одному успеху.

Bounded evidence manifest-v2,24 files SHA256 `3bdb8ff697d3f9066ccafaf90bc523da0f4488c14c5b39e0afb5b8db2ead61bb`.
