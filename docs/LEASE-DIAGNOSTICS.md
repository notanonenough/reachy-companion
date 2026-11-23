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
