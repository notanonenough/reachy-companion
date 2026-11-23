# PERF-01: один quiet trial общего кандидата

24 ноября2026, [#30](https://github.com/notanonenough/reachy-companion/issues/30)
и [#35](https://github.com/notanonenough/reachy-companion/issues/35).
Кандидат `3aea1cd42d0e13b396766bea3bfd4659d698eef5` установлен и независимо
проверен на Mac, Hub и Ричи. **Приёмка не пройдена:** после STOP остались
`busy:audio` и `busy:background`; Hub exit2, cleanup/accepted false. Один опыт,
без повторного старта, recovery, calibration или новых настроек. Новый тег не создан.

## Установка и owner

Из clean detached candidate построены один archive и wheel. Проверены696
source files,126 package files и61 canonical top-level identities, effective
imports всех узлов. Hub использует `.venv-router`, robot — canonical shared
venv, Mac — editable ROOT/src ровно этого SHA. Project base services получили
новые PIDs; factory daemon/Bluetooth/tunnel не перезапускались.

| Артефакт | SHA256 |
|---|---|
| release.tar.gz | `82b5de827b1f6d4910f8b197d771166fcb5caf1722d60faf8a81e7a5a69e7f7b` |
| wheel | `aba7432ddd94aa47de7112db25db7b04a9c1a223e11d5b4b1b035e6d133dd4eb` |
| source manifest content | `8800e5b192396eaba658abcc33f795a9311fab146f41fcea5c8cdde6b1622876` |

Предыдущийfc554 сохранён как actual installed package backup:252files/узел
Linux с hashes/modes, прежние archive/wheel, Mac source/config/plists/metadata,
Hub SQLite `quick_check=ok`. Все21 runtime config (8+7+6) byte-equal прежнему
accepted render под неизменными templates/manifest; это эквивалентность, не новый
render. Legacy sensors, профиль, модели, guards и limits сохранены.
Installation manifest46files SHA
`c708ad513e76420878ff9caeaa231d59008d58071ae6fa47f3032cd315c4c835`.

Original approved local harness `44ee0de5f498a4dcdd3f4da25dbf5eb55f8952f8b663e32f0b7be7eb790486bc`,
remote `aa2310807750870c8c2bc3cf205f046e122e3404de40d4cc2999885daac3298d`.
Reviewed launch `72c5b18b8d2cb31485c22f05791eb987953d1cf61c57ab1b445a76ab2fdf31d7`,
abort `30d05f07e3f060fbbf2d4177e9ca032e1c1339c304511d7708c147e640e51aba`.
Один foreground normal Hub, один own PID/Mach fence, bound listener/authenticated
STOP, known exit перед private trace copy; без observer v3 и второго controller.
Reader manifest `2b7575b58e518f443b2d5f40abed3fe9832354463ac8725455037bdd2cd25a8c`
отдельно reviewed после исправления device join на top-level Hub source_boot
и проверки положительного PID/start_ticks обеих owner receipts (17fixtures).

Время Asia/Baku: fresh stopped/free01:30:08; ACTIVE01:30:27.872;
camera01:30:30.545; capture01:30:31.867; один synthetic acoustic stimulus
01:30:35.870–01:30:40.690; Hub known exit01:32:00.642;
device/Mac shutdown01:32:02.604; camera off01:32:03.220;
independent checks01:32:04.808. Окно явно освобождено около01:33.
Команда держала общий Mac без проектных tests/builds/benchmarks в этом окне.
Условия комнаты/TV заново не подтверждены; дополнительных stimuli не было.

## Сохранённые причинные цепочки

Whole trace **incomplete**:92records+footer, reason`occupied_at_close`, dropped1.
Это явный маркер занятого worker, не доказательство ровно одного потерянного
события. Ни полнота всех событий, ни отсутствие поздних событий не утверждаются.
Присутствующие завершённые subchains независимо сопоставлены по source/owner,
task/attempt/input/authority и text/PCM digests.

Два recognized inputs соответствуют арифметическому вопросу и отдельной
инструкции о формате ответа. Правильный numeric результат первого main был
discarded; второй main получил только инструкцию и выдал отказ, который стал
единственным сохранённым speech commit. Это подтверждённое семантическое
разделение контрольной фразы; точная endpoint-причина в trace не хранится.
Raw text не публикуется. Этот второй input нельзя описывать как полный вопрос,
как в предыдущемfc554 опыте. Исправление admission ведётся отдельно в
[#39](https://github.com/notanonenough/reachy-companion/issues/39).

| Hub-local client interval,s | Question | Format-only |
|---|---:|---:|
| STT call |2.173456|2.419031|
| STT end→admission |.030695|.020203|
| Admission→main |1.772406|7.606797|
| Main call |7.895261|6.642803|
| Main end→checked |.017027|.021499|
| Checked→speech |—|.844593|
| First PCM / producer |—|.446634 / .712057|
| STT end→playback stop |—|18.009471|

Второй main wait включает7.246575s фактически занятого первого main и.360222s
после его completion. Отзыв результата не освобождает ещё работающий слот.
Единственный сохранённый stream37709frames совпадает с device consumed/known
stop receipt. Это не измерение first audible; новая human audibility receipt
на момент протокола не получена. Same-call native model timing сохранён для
#35: четыре main calls, два audio-linked и два metadata-only; prompt evaluation
5.591–6.935s, predicted.851–1.262s. Client call не равен GPU compute; cached
post-count не доказывает cache hit, TTFT/cache-hit отсутствуют.

## Движение и terminal gate

26unique motion receipts (1102snapshot copies, no conflicting duplicates):
25accepted и один operator rejection до `stock_begin`. Command duration
.350–.425s, median.390; synchronous expression call .892–1.307s, median1.204.
Эти интервалы не доказывают physical onset/target arrival. Ранее измеренный
yaw residual/target-nearness gap не объявлен исправленным и не калибровался.

Здесь `motion_after.stop_known=true`, stock diagnostics null: последняя ошибка
до начала stock operation корректно не связывается со старым UUID. Прежний
`motion_stop_unknown` не воспроизвёлся; его историческая причина не установлена.
Peer STOP known, control handlers0; matched device accepted/capture closed/
microphone restored/playback known. Independent production PIDs0, Mac jobs0,
ports closed, mic/camera off, running moves empty. Восемь последующих pose
samples за1.169s дали yaw range.0544°, pitch.0562°, body0: bounded stationarity,
не hard-stop deadline и не retroactive worker ACK. Personality/principles unchanged.

Hub final сохранил живой audio thread и минимум один Services future после
прежнего1s cleanup grace: audio started38 против37 retained STT results;
pending=false/waiting_terminal=false. Точная audio subphase и конкретное имя
background owner не retained. Known process exit не заменяет terminal completion
этих workers. Это отдельный gate от физического STOP и от split-input ошибки.

## Связанное исправление и проверка

Normal Hub теперь сохраняет немедленный прежний STOP/withdrawal и затем ждёт
только фактическое завершение retained workers до8s от finally entry. Нет новых
jobs, `advance`, применения результатов к State/закрытой SQLite. Busy после
границы остаётся ошибкой, trace incomplete; bounded `terminal_drain` объясняет
remaining categories/ages. Это best-effort grace с margin до supervisor10s,
не гарантия transport termination или hard total shutdown. Existing close
может превысить её, что явно отмечается overrun.

Для head delay найден другой управляемый источник: internal follow делал8
factory GET до POST, из них4 повторяли следующий mutation preflight. Теперь
follow делает4: daemon→owner→running→fresh state, с прежними operator checks
между ними. Empty active list и enabled control_mode проверяются именно здесь;
fresh measured limits, UUID completion/STOP, ordinary expressions/actions
сохранены. Scripted actual Hub tests проверяют порядок, смену operator/owner,
bad pose, active own/foreign UUID и отказ до POST. Уменьшение RPC count доказано
офлайн; сокращение физической задержки требует нового принятого candidate/окна.

Private evidence root: `~/reachy-release-backups/20261124-3aea1cd42d0e/combined-trial-001`.
17file bounded manifest SHA
`884886db3d921dddd40c753a80f2b1c64ecfd4381bc6c0d5099287263476b1cb`;
включает independent reviewer audit и numeric extractor, исключает raw trace/audio.
Локальное воспроизведение numeric correlation: `python3 extract-performance.py`
в этом private root; требуется сохранённый private trace, текст на stdout не выходит.
Проверка кода: `PYTHONPATH=src:tests python -m unittest test_terminal_drain test_follow_preflight`.
Аппаратный опыт не повторяется этими командами.
