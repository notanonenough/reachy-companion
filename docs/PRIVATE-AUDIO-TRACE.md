# Частная диагностика одного голосового сеанса

AUDIO-TRACE-01 наблюдает настоящий normal production путь. По умолчанию trace
отключён. Он не исправляет распознавание, сегментацию или ответы модели, не
меняет authority, TTL, renewal, STOP, playback либо reconnect. Offline loopback
проверяет корреляцию; аппаратное качество голоса принимает RELEASE-01 отдельно.

## Что сохраняется

JSONL содержит `version=1`, отдельный `trace_id`, `hub_boot_id`, `kind`, локальный
`at` и `clock_basis=hub_monotonic`. Внутри одной этой области можно сопоставлять
локальные start/end. `captured_end` AudioAdapter — консервативное локальное
сопоставление по возрасту capture (`hub_monotonic_conservative_mapping`), не
измеренный timestamp hardware. `audio_s` — длина принятого S16LE PCM / 32000.
Часы устройства, Mac и Hub не вычитаются друг из друга. Derived время начала
аудио не выдаётся за измеренное время device capture.

| kind | Данные и доказательство |
|---|---|
| `session_begin` | Локальное начало ограниченного trace window |
| `stt_result` | Фактический bounded STT text, source/sequence/lineage, PCM SHA256, audio duration, локальные start/end и stale/error disposition |
| `stt_disposition` | Передача результата к admission либо withdrawal/drop |
| `input_admission` | Реально созданный State input ref и новые authority/interaction/speech epochs; blocked не объявляется принятым |
| `input_retry` | Существующий context/memory retry переносит lineage только от зарегистрированного parent ref при полном совпадении authority; без сравнения текстов |
| `main_request` | Только utterance и task/attempt/input ref/authority, без prompt/context |
| `main_result` | Фактический ответ с disposition `unchecked`, локальным завершением и ограниченной проекцией proof |
| `main_checked` | Результат существующего State.complete/checked_final: ready/failed/discarded и проверенный proof, если он появился |
| `speech_commit` | Принятый SpeechAdapter proposal, text/output binding и original task/ref |
| `speech_terminal` | Реальные TTS frames, SHA256 принятых PCM bytes, stream ID, authority/operator binding, producer timing, completion/cancellation |
| `playback_stop` | Local/device stream IDs и source boot, generation, submitted/written/last-progress consumed frames, отдельный stop_consumed_frames из stop receipt и stop/provenance flags; это наблюдение, не новая physical attestation |
| `trace_end` | Bounded итог записи; отсутствие footer означает неполный trace |

Main/speech text сохраняется только для input refs, реально принятых из audio
в этой trace-сессии. Bounded registry содержит максимум 128 refs. Штатный context retry может создать новый ref; trace сохраняет доказанную
связь со старым task ref в точке его создания. Неизвестный parent, изменённая
authority или потеря записи связи оставляют новый ref metadata-only и incomplete.
Background,
reflection/research и memory maintenance не становятся источником сохранённого
текста. Законный audio-linked ответ сохраняется как есть, включая использование
контекста самой моделью: trace не интерпретирует и не редактирует его смысл.
Полный prompt, memory/profile, configuration, tokens, exception payloads,
raw PCM/JPEG не сохраняются. `text_sha256` использует существующий
`voice_chain.digest` (канонический JSON строки); PCM SHA256 — непосредственно
байты PCM. Дайджесты этих двух представлений не взаимозаменяемы.

Текст не обрезается. Если целая запись не помещается, она пропускается и trace
становится incomplete. Поэтому trace не может создать видимость того, что STT
сам обрезал фразу. Отсутствие записи при incomplete не доказывает отсутствие
события. Recorded result и admitted input — разные события; старый результат
может существовать без принятого ref.

## Ограничения и отказ записи

Явный window — 1..300 секунд. Его окончание закрывает только content capture;
production lifetime `lease` и runtime продолжаются без изменений. Hard ceilings:
512 JSONL records включая footer, 1 MiB всего, 16 KiB на запись, queue 32.
Reducer делает только bounded projection/serialization и nonblocking enqueue.
Writer забирает immutable bytes под коротким lock, пишет в файл вне lock.
Содержимое не проходит через State ledger, обычный outbox, status или логи.

STOP event или наблюдаемая privacy необратимо закрывают content capture этой
сессии. Поздние STT/model/terminal callbacks могут оставить metadata без text.
Записи, уже поставленные в очередь до отзыва, допустимо дописать после него.
Снятие privacy не включает trace снова. Очередь/лимиты/потеря lineage/writer
failure помечают incomplete и bounded dropped count, не меняя решение runtime.
Drain после обычного cleanup ограничен 0.5 s и выполняется один раз; последующие
close не ждут снова. Если writer не завершился, результат `drain_timeout`.
Отсутствующий или недописанный footer не считается успешно закрытым trace.

Файл создаётся эксклюзивно, mode0600, без следования ссылкам в компонентах пути,
в существующем owned mode0700 каталоге вне repository/config roots. Имеющийся
файл, неверный путь или cap отклоняются до запуска session runtime. После
старта ошибка writer не меняет `accepted`/`cleanup_verified`. Final report
правдиво содержит `transcripts_retained=true` при opt-in и только summary
`{enabled,incomplete,reason,records_written,dropped}`; raw_audio_retained остаётся
false. Краткий log и installed-host last_session получают ту же bounded
проекцию без пути, текста или digest. Default-off не создаёт файлов/summary.

## Один явный production запуск

Эта инструкция не выдаёт аппаратное разрешение. Ведущий сначала выбирает
reviewed exact candidate с green CI и одно окно для RELEASE-01.

1. Проверить установленный exact candidate и effective imports на всех узлах.
   Отказаться от запуска при active Hub service, `MainPID != 0`, занятом 8791
   или существующем manual Hub owner. Не останавливать чужой owner ради прохода
   preflight. Проверить исходные mic/motion/Mac ownership условия обычного выпуска.
2. Поднять те же Mac services штатными helper-функциями и только device service.
   Не вызывать `production-control start`: он запустил бы второй Hub owner.
   Старые guard/wake/profile правила остаются прежними.
3. На Hub создать новый приватный каталог вне installation root (`umask 077`,
   `mkdir -m 700`, без `-p` для каталога сеанса). Один отслеживаемый foreground
   supervisor запускает существующую entrypoint, например:

   ```sh
   PYTHONPATH=/home/deploy/reachy-companion/current/src \
   /home/deploy/reachy-companion/.venv-router/bin/python \
     /home/deploy/reachy-companion/current/deploy/autonomous/production_start.py hub \
     --root /home/deploy/reachy-companion \
     --config /home/deploy/reachy-companion/config.autonomous.mac.local.json \
     --token-file /home/deploy/reachy-companion/secrets/autonomous-mac.token \
     --peer-url http://192.168.0.184:8780 --peer-stop-port 8781 \
     --lease-datagram-port 8782 --trusted-private-lan \
     --private-audio-trace /home/deploy/reachy-private-traces/NEW_SESSION/trace.jsonl \
     --private-audio-trace-seconds 120
   ```

   Адреса/остальные flags берутся из принятых unit settings этого выпуска.
   Supervisor сохраняет child PID и Linux process start ticks; это один foreground
   процесс, не daemon, persistent override или auto-restart. CLI flags не сохраняются
   в service config/environment и не переходят на следующий обычный start.
4. Authenticated GET `http://127.0.0.1:8791/status` даёт точный
   `{controller,source_boot,session_boot}`. Прежде принять первый binding и
   перед POST `/stop` supervisor проверяет, что listener8791 принадлежит именно
   отслеживаемому child PID с теми же process start ticks. Preflight и одинаковый
   controller сами по себе этого не доказывают. Зафиксировать binding; при его смене
   не присваивать себе новый owner. В конце опыта POST `/stop` отправляет ровно
   этот dict с тем же bearer token после повторной проверки status. HTTP202 —
   только admission. `SessionClient.status/stop` реализуют существующий протокол.
5. Дождаться exit именно отслеживаемого Hub PID и совпадающего final report.
   `production-control stop` сам по себе manual Hub не останавливает! При
   недоступном HTTP stop supervisor может послать SIGTERM только своему child
   после проверки PID/start ticks, затем bounded wait; без `pkill`, повторного
   запуска или reconnect. Обрыв SSH/неизвестный owner/timeout не является успехом:
   отметить collection unknown/incomplete, выполнить доступный safety cleanup,
   не возобновлять опыт автоматически.
6. После известного exit выполнить обычный device/Mac shutdown. Независимо
   проверить stop/terminal receipts, `execution_busy=false`, закрытый capture,
   восстановленный mic owner, `control_transport.handlers=0` и остановленный
   control listener. Использовать существующий `cleanup_receipts`, не footer
   trace как свидетельство физической остановки. Частный JSONL копировать только
   после известного exit, сохранять mode0700/0600 вне Git и обычных логов.

RELEASE-01 держит проверенный supervisor/harness и конкретное окно. Успешный
exit harness означает сбор evidence, а не принятую правильность ответа. В PR/
issue публикуются только обезличенные выводы; trace, текст, акустические записи
и частные inputs не публикуются. Очистка артефактов — явное действие владельца;
автоматического upload или retention job для них нет.

## Offline проверка

```sh
PYTHONPATH=src:tests .venv-review/bin/python -m unittest test_private_audio_trace -v
```

Тест использует typed AudioPeer PCM fixture и настоящие AudioPolling, HttpSTT,
RemoteGateway, HttpTTS, production Scheduler/SQLite и Playback внутри normal
run_session. Серверы STT/model/TTS возвращают синтетические известные результаты;
это не измерение качества моделей/железа. Три последовательных входа и stale
result проверяют точные тексты/refs/proofs/PCM; отдельные варианты default-off,
slow/broken writer и STOP/privacy проверяют тот же голосовой путь и lease calls.
