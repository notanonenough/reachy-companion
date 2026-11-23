# Первая invalid complete-authority причина

`companion_session.run_session` сохраняет `first_lease_invalid` непосредственно
перед первым вызовом `lease.close()` из существующей invalid-authority ветки.
Запись использует тот же `now`, snapshot speech receipt и captured peer/status/
authority, что и исходный short-circuit `valid`. В valid/unarmed ветках и при
явном user stop такая запись не создаётся. Условия допуска, TTL, tick, close и
reconnect не изменены.

Запись содержит фиксированный `cause=invalid_complete_authority`, booleans
`predicates` и производный список `failed_checks`: наличие peer receipt,
operator_ready, наличие/свежесть peer status, наличие/свежесть speech receipt,
microphone enabled, not quiet, not privacy, binding matches. Зависимый predicate
при отсутствующем prerequisite имеет `null`, а не выдуманное false.

Также сохраняются elapsed session time, startup phase, локальный возраст peer
status, signed остаток speech receipt и существующие lease timings, вычисленные
по тому же `now`. Числа конечные, ограничены ±10^12 ms и округлены до 0.001 ms;
неизвестные значения — null. Это диагностическая точность представления,
не измеренная точность часов. Raw identity/binding, токены, речь, память,
профили и exception text не копируются.

`lease_already_withdrawn` и фиксированный `prior_withdrawal_reason` позволяют
отличить invalid-ветку от уже произошедшего reducer expiry/transport withdrawal.
Такая запись доказывает вход в invalid-ветку, не утверждает, что именно она
первой закрыла lease в другом worker. Существующие lease first_close/timing и
withdrawal_reason сохраняют своё значение. `diagnostic_unavailable=true`
означает, что safe extractor не смог построить данные; это не препятствует
прежнему close и не объявляет неизвестный predicate доказанным.
Краткий log и last_session также сохраняют fixed-enum `lease_withdrawal_reason`
из существующего отчёта lease. Поэтому worker expiry/transport withdrawal при
ещё valid authority не требует выдуманного first-invalid события.
`controller_stop` сам по себе не доказывает user stop: это прежнее общее имя close,
которое читается вместе с session reason и first-invalid записью.

Первый snapshot хранится как immutable JSON; каждый live publish, STOPPED
publish и final report получает отдельную копию. Следующие ticks, cleanup и
изменение возвращённого consumer dict его не переписывают. `production_logs`
и `production_status` пропускают новый объект через один bounded projector.
Self-contained remote probe включает только исходники доверенных локальных
projector-функций и не требует новой версии package на инспектируемом узле.

```sh
PYTHONPATH=src:tests .venv-review/bin/python -m unittest test_lease_diagnostics -v
PYTHONPATH=src:tests .venv-review/bin/python -m unittest test_companion_session test_audio_peer_lease test_production_operations
```

Проверки выполняют настоящий run_session с детерминированными входами и
настоящим PeerLease tick/close, а также joined loopback HTTP scenario с реальными
Scheduler/SpeechAdapter/AudioPolling. Standalone remote probe проверяется в
локальном subprocess без SSH. Эта карточка добавляет диагностику; причину
предыдущего аппаратного завершения и исправленный hardware E2E она не доказывает.

## Первый reducer expiry

`first_reducer_expiry` отвечает на более узкий вопрос: какой этап и Python-стек
reducer наблюдались при первом закрытии с `reducer_expired`. `run_session`
регистрирует собственный thread ident только внутри процесса. На границах
startup/status control, speech advance, Scheduler.advance, peer polling,
playback control, lease gate, publication, ожидания и cleanup он присваивает
immutable пару `(stage, entered_monotonic)`. Метка не является progress tick,
не обновляет authority или deadline и не принимает решений о продлении.

`PeerLease` сначала выполняет прежние присваивания withdrawal reason,
first_close и closed. Только при первичном `reducer_expired` он один раз
снимает диагностику. Существующий lease lock уже удерживается; sampler не
берёт новых или reducer locks, не вызывает IO и не ждёт завершения reducer.
`sys._current_frames()` выбирает только зарегистрированный поток; обход
`f_back` ограничен 16 кадрами. Ссылки на frames сразу освобождаются. Locals,
globals, аргументы, source lines и абсолютные пути не читаются и не выводятся.
Модули внутри локального package превращаются в относительные dotted names,
остальные кадры — `external`. Function — ограниченное имя доверенного code
object; это метаданные установленного кода, не пользовательский текст.

Запись содержит fixed-enum stage, `stage_age_ms`, `progress_age_ms` из прежнего
first_close, `capture_delay_ms` от локальной отметки сразу после closed,
`trigger=worker|tick`, `capture_status=captured|thread_missing|unregistered|capture_failed`,
`stage_changed_during_capture`, `stack_truncated` и максимум 16 записей
`{module,function,line}`. Numeric bounds совпадают с остальной диагностикой;
module ≤160, function ≤96, line — integer 1..1,000,000 либо null. Проекция
занимает менее 8192 байт JSON. Она хранится immutable JSON и выдаётся свежими
копиями в lease status, live/STOPPED publish, final report, краткий log и
standalone `production_status` probe / last_session. Capture failure не
отменяет latch, не запускает повтор и не подменяет withdrawal reason.
При valid progress, initial unarmed и других первых причинах поле равно null.

Это **stack at detection**, не доказательство причины stall. `worker` может
наблюдать ещё удерживаемый reducer; `tick` обнаруживает expiry уже после его
возвращения и обычно показывает lease gate. Stage и stack не атомарный снимок:
flag отмечает смену tuple во время capture, но false не доказывает отсутствие
движения внутри этапа. Поток может исчезнуть, а внешние/C frames не объясняются
этим снимком. По одному снимку нельзя приписывать задержку SQLite, сети, модели,
CPU или OS. Порог 200 ms, validity checks, renewal/close и reconnect не изменены.

```sh
PYTHONPATH=src:tests .venv-review/bin/python -m unittest test_reducer_diagnostics -v
```

Основной тест запускает настоящий run_session, Scheduler, loopback HTTP и
независимый PeerLease worker. Event удерживает reducer в scheduler_advance;
worker синхронизируется между ACK и следующей итерацией и возобновляется после
истечения реального неизменного бюджета. Поэтому проверяется именно worker
expiry, а не случайный late ACK. Reducer всё ещё удержан, когда worker закрывает
lease и сохраняет стек. Отдельно проверяются tick detection, остальные reasons,
capture failure/missing thread, неизменность первой записи и privacy/size bounds.
Это управляемый scheduling probe, а не измерение аппаратной нагрузки. Следующий
аппаратный опыт и выбор установленного candidate принадлежат RELEASE-01.
