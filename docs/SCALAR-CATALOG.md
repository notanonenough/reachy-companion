# Scalar-каталог в production цикле

CATALOG-01 подключает одну пару metrics из [общего контракта](ROBOT-HUB-CONTRACT.md).
`production.attach` создаёт HTTP reader; один `Services` владеет registry и
передаёт проверенные события через `Scheduler.ingest` в `State`. Модель получает
обычный `FastView` с optional `scalar` metadata. Отдельного orchestration loop,
владельца камеры или процесса здесь нет.

## Настройка и совместимость

Для существующего `production.sensors` отсутствие `protocol` означает
`legacy-v1`: прежний GET и строгий shape `availability/summary/age_ms/ttl_ms`,
не более 8192 байт. Новые поля не принимаются молча. Новый путь включается
явно, без fallback и автоматического определения версии:

```json
{
  "camera.metrics": {
    "protocol": "scalar-catalog-v1",
    "url": "http://127.0.0.1:8794/metrics",
    "token_file": "private/robot.token",
    "source_id": "configured-camera-reader",
    "period_s": 0.5,
    "timeout_s": 2,
    "enabled": true,
    "max_capabilities": 2,
    "policy_ttl_ms": 1500,
    "clock_error_ms": null
  }
}
```

Это фрагмент `production.sensors`, не готовая конфигурация развёртывания.
`clock_error_ms=null` сохраняет возраст/актуальность unknown. Предел погрешности
задаётся локальной политикой после обоснования; `1` в loopback-тестах —
синтетическое условие теста, не измерение стенда. Источник не может назначить
себе этот предел. Регистрация описания не даёт разрешения на захват или движение.

Конфигурация ограничивает число readers двенадцатью, `max_capabilities` — 1..12
(по умолчанию 4), `policy_ttl_ms` — 1..60000 (по умолчанию 1500), известную
`clock_error_ms` — 0..60000. Таймауты/периоды используют существующие ограничения
конфигурации. Новый response и camera request ограничены 16384 байтами. Каждый
reader занимает один Job с двумя последовательными HTTP запросами и хранит один
актуальный batch. Медленное чтение не создаёт заменяющие jobs и не задерживает
обработку STOP владельцем Scheduler.

## Обмен и проверка владельцем

1. Владелец создаёт одноразовый challenge и фиксирует logical connection,
   локально поддерживаемые semantics и предел каталога. IO worker делает POST
   `catalog_request` с connection id. Источник возвращает полный `Catalog`.
2. Чистая функция выбирает только `metric.scalar` major 1 / minor 0.
   Совместимый более новый minor даёт `limited`; несовместимый major/min_minor,
   другой semantic, module или direction дают `unsupported`. Worker отправляет
   POST `observation_request` с выбранными версиями, digest всего каталога,
   boot/generation/connection и challenge. Источник проверяет agreement и
   возвращает `scalar_snapshot`: точный `ack` и bounded `observations`.
3. Worker возвращает только кандидата. Владелец заново проверяет active reader,
   source binding, captured authority/connection/challenge, локальное соглашение,
   digest/boot/generation, весь batch и глобальную ёмкость State. До завершения
   проверки ни один sensor не меняется. Ack предыдущего poll не подходит.

Wire-формы Capability/Catalog/Observation определены в
[поставляемой schema](../src/reachy_companion/assets/scalar-catalog.json).
`source_response` — stateless helper для ограниченного HTTP источника; он
не хранит registry и не владеет устройством. Внешний JSON сам по себе не является
подтверждением доверия: reader выбирается локальной конфигурацией, HTTP использует
HTTPS либо явный loopback endpoint и настроенный bearer credential.

Идентичность `State` — `scalar:` + SHA-256 от пары reader/capability id, поэтому
два readers с одинаковым capability id не перезаписывают друг друга. Читаемые
reader/id, description, unit, semantic/version/support, source boot, connection,
catalog generation, sequence и time basis доступны в `scalar` metadata.
Описание — данные источника, не инструкции модели. Никаких веток State для
конкретного sensor id не добавлено.

Каталог атомарный, с уникальными id и едиными boot/generation. Изменение
содержимого при прежней generation отклоняется. Sequence строго возрастает по
capability в пределах source boot и не сбрасывается при reconnect/privacy или
смене catalog generation. Registry сохраняет до 64 sequence tombstones и до 8
retired boot id. При исчерпании reader закрывает допуск; для sequence history
нужен новый source boot, для boot history — явное пересоздание configured reader.
Это ограничения реализации, не аппаратные бюджеты.

## Свежесть и отзыв

Возраст — верхняя граница `age_at_send_ms + полный локальный elapsed poll +
clock_error_ms`, округлённая вверх. Elapsed включает оба HTTP запроса и ожидание
между завершением Job и обработкой владельцем. Межхостовые monotonic timestamps
не вычитаются; неизвестная граница, age или time basis сохраняет unknown.
Эффективный TTL — минимум message, descriptor и локальной политики.

Scalar `Sensor.view` использует строгое `age < TTL` при каждом чтении. Равенство
и более старые наблюдения дают stale, пустой summary и `value=null` в snapshot.
Реальный численный ноль остаётся нулём. Старые Sensor paths сохраняют свою
совместимость, в том числе прежнюю TTL-проекцию.

Removal удаляет id и metadata из State; disable/privacy/STOP, ошибка транспорта,
невалидный batch или отзыв configured reader убирают весь его текущий кэш и
меняют logical connection. Старый занятый IO slot сохраняется до завершения:
его ответ не регистрирует источник снова. Пока сетевой сбой ещё не определён,
готовность ограничена TTL на чтении. Retired boot и duplicate/out-of-order
sequence не восстанавливают ready после переподключения.

## Численные метрики камеры

Новый authenticated POST `/metrics` использует тот же `Measurements` cache.
Он публикует brightness и image_change как ratio 0..1 с `source_receipt` time
basis. Exposure age, распознанные объекты и причина изменения изображения
неизвестны. Process boot отделён от catalog generation; generation меняется при
clear/binding, собственный sequence измерений не сбрасывается внутри boot.
Старые GET `/sensor`, `/frame` и capture worker не меняют свой протокол.

## Воспроизведение

```sh
PYTHONPATH=src:tests .venv-review/bin/python -m unittest test_scalar_catalog -v
PYTHONPATH=src:tests .venv-review/bin/python -m unittest test_camera_sensor test_autonomous test_production_cycle test_robot_hub_contract test_network_observation
```

Первый набор открывает настоящий loopback HTTP server, вызывает production
`attach`, прогоняет Services/Scheduler и проверяет sensor в snapshot модели.
Проверяется и настоящий camera `/metrics` endpoint с искусственным содержимым
кэша, без запуска capture. Негативные сценарии включают ack/challenge, unknown
age, TTL equality, owner delay, versions, boot/sequence, atomic failure/capacity,
removal/privacy/disconnect/late Job и STOP.

Эти проверки не подтверждают физическую точность, нагрузку или E2E-задержки.
BASELINE-01 (#8) подтвердил только inventory/access. Аппаратная приёмка и
включение CATALOG-01 в release candidate требуют отдельного решения ведущего.
