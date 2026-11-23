# Контракт модулей Ричи и Hub: CONTRACT-01

Версия проекта интерфейса: **1.0**, 23 ноября 2026. Основание — пункты 7–10,
15–16 и 19–22 [блокнота](REVIEW-NOTES.md), карточка
[CONTRACT-01](https://github.com/notanonenough/reachy-companion/issues/2).

Это согласуемый контракт и исполняемые примеры. Он **не подключён к production**:
не добавляет сетевой сервис, каталог в работающий Scheduler, Go/gRPC или новое
управление приводами. Описанное ниже обязательно для будущих адаптеров.
[Текущая схема](ROBOT-INTERFACES.md) остаётся исходной точкой. Число процессов,
транспорт, медиакодеки и аппаратные бюджеты выбираются отдельно по измерениям.
Численные значения fixtures синтетические и не являются принятыми бюджетами.

## Шесть пар и владельцы

Общий адаптер источника захватывает устройство один раз и раздаёт данные модулям.
Модуль исполнения — единственный владелец действия. Разрешения выдаёт локальный
доверенный компонент; объявление возможности не выдаёт допуск. Один адаптер
может объявлять source и executor под разными capability id одного устройства.

| Модуль Ричи → пара Hub | Кто открывает вызов | Локальный владелец и контракт | Буферизация и потеря | Существующая опора |
|---|---|---|---|---|
| Разрешения → подтверждённое состояние/координатор | Hub → Ричи | `inspect/set/revoke`; запрос изменения отличается от подтверждённого состояния. На Ричи проверяются owner, scope, epoch и срок, уведомляются исполнители. | Ограниченная очередь управления; при переполнении обычный запрос получает busy. Revoke/stop имеет отдельный обслуживаемый слот и не ждёт медиа. | [motion_policy](../src/reachy_companion/motion_policy.py), [camera_permission](../src/reachy_companion/camera_permission.py), [Agent](../src/reachy_companion/agent.py) |
| Движение → цель/отмена/результат | Hub → Ричи | Локальный исполнитель принимает цель, согласует оси через factory API, публикует фактический результат/unknown. Hub не посылает параллельные команды напрямую daemon после миграции этого пути. | Одна активная цель и максимум одна замещающая; новое поколение отзывает старую. Стоп доступен независимо. Неизвестный исход не разрешает повторное движение. | [StockMotionAdapter](../src/reachy_companion/autonomous/stock_motion_adapter.py), [PersonFollow](../src/reachy_companion/autonomous/person_follow.py), [Hub](../src/reachy_companion/hub.py) — сейчас планирование на Hub |
| Воспроизведение → доставка TTS/прогресс | Hub → Ричи | Один PCM owner, `start/write/finish/stop`, stream id и generation. Приём чанка не равен его звучанию; прогресс — measured consumed frames либо unknown. | Ограниченный буфер в кадрах и миллисекундах; пропуск виден по sequence/range, просроченные чанки не догоняются. Stop отзывает накопленные и поздние чанки. | [Playback](../src/reachy_companion/autonomous/playback.py), [audio_peer](../src/reachy_companion/autonomous/audio_peer.py), [SpeechAdapter](../src/reachy_companion/autonomous/speech_adapter.py) |
| Отправка аудио → аудиошлюз/STT | Ричи → Hub | Единственный capture adapter; stream id, формат, frame offset/count, sequence, время и gap. Первый блок доступен до финализации реплики; ASR завершает её отдельным событием. | Ограниченное окно; устаревший блок отбрасывается с gap, без тихого склеивания. Конкретный loss/reorder budget согласуется до опыта. | [AlsaCapture](../src/reachy_companion/autonomous/alsa_capture.py), [AudioAdapter](../src/reachy_companion/autonomous/audio_adapter.py), [device runtime](../deploy/autonomous/device_audio_runtime.py); сейчас polling завершённых фрагментов |
| Отправка видео → видеошлюз/наблюдения | Ричи → Hub | Factory camera остаётся владельцем захвата. Frame id связывает bytes, параметры crop/scale/calibration и результат обработки; сведения о собственном движении — отдельное наблюдение с provenance. | Один актуальный кадр плюс один обрабатываемый; замещение считается. Просроченные inference results отвергаются. | [camera_sensor](../src/reachy_companion/autonomous/camera_sensor.py), [LatestFrameProcessor](../src/reachy_companion/autonomous/video_adapter.py), [Vision](../src/reachy_companion/autonomous/vision.py); сейчас Mac опрашивает кадры напрямую |
| Метрики/события → каталог и кэш чувств | Ричи → Hub | Адаптер регистрирует описание и sequence/boot наблюдений; Hub определяет поддержку и делает описание/актуальное значение доступным модели. | Для периодической метрики один latest slot на source. События — ограниченная подтверждаемая очередь, overflow выдаёт gap/count; не превращать потерю событий в отсутствие события. | [Services](../src/reachy_companion/autonomous/services.py), [State.ingest](../src/reachy_companion/autonomous/state.py), [Sensor](../src/reachy_companion/autonomous/contracts.py), audio RMS/camera metrics |

Логические очереди не обещают сетевой изоляции. До установки для каждого
адаптера фиксируются численные caps, p95/p99/max, время опыта и политика
исчерпания лимита. Для stop/revoke нельзя занимать общий с медиапотоком
неограниченный executor. При потере связи локальные leases истекают, новые
действия прекращаются; фактическая остановка подтверждается отдельно.

## Каталог и согласование версий

Общий envelope имеет `protocol` major; первая версия — 1. Соединение получает
новый `connection_id`, обе стороны объявляют boot id, поддерживаемые semantic
schema versions и лимиты. Hub сохраняет `catalog_generation` и подтверждает
каждый descriptor: `supported`, `limited` с выбранной minor-версией и причиной,
либо `unsupported` с причиной. До подтверждения значения не становятся ready,
а команды не отправляются. Аутентификация узлов и разрешения независимы от
этих полей; текст descriptor от модели не регистрирует адаптер.

Каталог передаётся атомарным полным `Catalog` snapshot: protocol, connection_id,
catalog_generation, source_boot_id и capabilities (до 64 descriptors и общего
byte bound). Все entries имеют одинаковые generation/boot и уникальные id.
Новый snapshot заменяет предыдущий только после полной проверки; отсутствующий
id означает removal. Повреждённый snapshot не применяется частично. Generation
строго возрастает в пределах boot, duplicate того же содержимого идемпотентен,
тот же generation с иным содержимым — conflict. На reconnect заново подтверждается
текущий snapshot, readiness прежнего connection не переносится автоматически.

Ingress получает доверенное локальное подтверждение согласования, а не только
объявленный descriptor: connection, source boot, catalog generation, capability id,
semantic, выбранные major/minor, status и digest полного descriptor. Подтверждение
должно совпадать с текущим каталогом и локально поддерживаемым типом. Отсутствующее,
unsupported или старое подтверждение не позволяет сделать observation ready.
Это отдельный барьер перед State.ingest; модель и источник не выдают его сами.

Для данного проекта envelope ограничен 16 KiB до decode; binary media передаётся
отдельно. Схема ограничивает имена/массивы/скалярные arguments; semantic handler
проверяет точный набор, единицы и диапазоны аргументов. Эти ограничения пока
проверяет только design verifier, runtime decoder внедряется отдельной карточкой.

Descriptor ([схема](../tests/fixtures/robot_hub_contract/envelopes.schema.json),
`Capability`) содержит:

| Поле | Смысл |
|---|---|
| `id`, `source_boot_id`, `catalog_generation` | Стабильный id capability, конкретная загрузка владельца и версия набора. id не меняется от reconnect, boot меняется от перезапуска. |
| `module`, `direction` | Одна из шести обязанностей; `source` либо `executor`. |
| `semantic`, `version {major, minor, min_minor}` | Тип значений/команд и диапазон совместимости. Например, новый `room.temperature` имеет уже известный `metric.scalar`, а неизвестный `motion.gripper` требует своего обработчика. |
| `description`, `unit`, `range` | Краткое назначение, объявленная единица, допустимый диапазон либо null. Неподтверждённые пределы не выдумываются. Для scalar единицы и диапазон обязательны перед использованием в автоматическом правиле. |
| `period_ms`, `ttl_ms`, `availability` | Ожидаемый период (null для нерегулярного источника), максимальная актуальность, available/unknown/disabled/offline. Наличие возможности не означает доступность показания. |
| `operations`, `coordinate_frame` | Для executor — допустимые операции и система координат. Это список возможностей, не разрешение их вызывать. Для source operations пуст. |
| `required_for` | Режимы, для которых возможность обязательна. Отказ новой gripper блокирует grasp, не независимый dialogue. Обязательный источник не подменяется нулём. |

Тип `metric.scalar/1` принимает конечное число либо boolean с объявленной
единицей; тип и единица не меняются под прежним id. Типы медиа задают формат
семплов/изображения и ссылки на binary payload, а не JSON/Base64-метрики.
`motion.target/1` до production требует отдельного versioned описания осей,
геометрии, диапазонов, единиц и способов обратной связи. Общего descriptor
недостаточно для подключения произвольного привода к координации. Fixture
`fixture.motion` — программный пример допуска, не паспорт настоящей кинематики.

Minor добавляет только необязательные поля с определённым поведением при их
отсутствии. Отправитель обязан сериализовать **выбранную** minor-версию, не
посылать неизвестные поля старому строгому decoder. Стороны выбирают
`min(peer.minor, local.max_minor)`, только если major совпадает и результат
не меньше peer.min_minor. `limited` означает явный downgrade; новая обязательная
семантика требует повышения min_minor или major. Не менять смысл поля/id,
не переиспользовать удалённые имена; при выборе Protobuf резервировать и номера.

Отключение/removal capability немедленно делает её кэш unavailable и отзывает
связанные новые действия; старые источники не возвращаются от позднего пакета.
Reconnect требует нового connection id и повторного согласования каталога.
Новый boot сбрасывает sequence только после регистрации нового источника.
Неизвестный исход старой команды сохраняется до сверки; reconnect не означает
право отправить её заново. Schema/version matrix входит в CI будущей интеграции.

## Наблюдения, время и свежесть

`Observation` содержит capability id, boot, catalog generation, connection,
sequence, challenge id, `sample_mono_ms`, `time_basis`, `age_at_send_ms`, TTL,
availability, value, reason и confidence. Sequence строго возрастает в пределах
(capability, boot); повтор не обновляет возраст. Время sample принадлежит
часам источника и не вычитается из Hub monotonic. UTC допустимо для диагностики
с известной погрешностью, но само по себе не даёт допуска действию.

`time_basis=sample` означает известную точку измерения; `source_receipt` —
только получение исходных данных локальным адаптером (например, кадра из
socket). Это не известное время экспозиции. `unknown` оставляет возраст
измерения неизвестным. Confidence null означает отсутствие оценки; численное
значение интерпретируется только по документированному типу источника и не
является автоматически вероятностью личности или безопасности действия.

Для первого адаптера используем консервативную causal challenge-схему:

1. Получатель выдаёт непредсказуемый challenge, связывает его с connection/boot
   и записывает локальный monotonic момент. На bidirectional push-stream это
   управляющее сообщение, не смена инициатора потока.
2. Источник включает challenge и возраст данных **на момент отправки**, включая
   локальную очередь/обработку. Не подписывает заранее конверт для поздней отправки.
3. Получатель при приёме берёт свои monotonic часы. Верхняя оценка возраста:
   `age_at_send + (receipt - challenge_issued) + clock_error_budget`.
   Это консервативнее односторонней задержки и не требует синхронных часов.
   Error budget учитывает измеренную погрешность длительности часов источника;
   если её граница неизвестна, возраст unknown. Не использовать прежний ping
   как гарантированную задержку нового пакета.
4. Challenge должен принадлежать текущему соединению и boot, быть ещё в
   ограниченном реестре получателя. Срок его хранения ограничен максимальным
   TTL. Неизвестный/просроченный challenge или отрицательная длительность дают
   unknown, а не нулевой age. При последующем чтении возраст растёт локально.

Применяется минимум TTL сообщения, descriptor и локальной политики получателя
(`policy_ttl_ms` в исполняемом примере); локальный предел обязателен и валидируется. При
`age >= TTL` наблюдение не используется как свежее. Late/replayed/wrong-boot
пакет не замещает текущий sample. Unavailable sample имеет null value, состояние
и причину; ноль — допустимое реальное значение. Disconnected/disabled источник
удаляет актуальное значение, а не сохраняет last good как новое измерение.

[Services.advance](../src/reachy_companion/autonomous/services.py) уже добавляет
полный RTT текущего опроса к age сенсора. Это полезная основа: будущий push adapter
должен сохранить консервативность. [Sensor.view](../src/reachy_companion/autonomous/contracts.py)
хранит локально приведённый возраст и TTL; не выдавать его вычисленный
`captured_at` за аппаратное время экспозиции. Для совместимого projection
оставляем в summary `time_basis`, unit и confidence; unknown не получает summary.
Production-integration должна дополнительно хранить registry/provenance и
sequence, которых нынешний Sensor сам по себе не проверяет. Есть также граничное
различие: нынешний `Sensor.view` допускает равенство age и TTL; новый validated
snapshot должен применять договорённое `age < TTL` и при чтении, не только
при ingress. Этот переход включён в CATALOG-01, текущий код здесь не меняется.

## Команды, допуски и результат

`Command` связывает command id, capability/catalog, connection, существующий
`Authority.wire()`, generation, operation/arguments, permit id/epoch и срок.
Исполнитель сверяет authority с собственным подтверждённым состоянием. Поля
сообщения не создают authority. Отдельный scoped permit нужен потому, что
нынешний Authority не содержит независимый motor policy epoch. Не смешивать
motor epoch, microphone epoch и operator epoch.

Дедлайн приводится к локальным часам принимающего исполнителя тем же способом
causal challenge; маленький ttl от отправителя нельзя увеличить локальным
буфером. Допуск проверяется при принятии и непосредственно перед физическим
выходом/каждой порцией. Permit должен совпасть по capability, владельцу,
поколению, epoch и сроку; default — deny. Аргументы проверяет обработчик
согласованного semantic-типа: зарегистрированное имя операции не допускает
произвольный JSON к SDK. Ошибка в одном поле отклоняет всю команду.

- `accepted` — команда допущена/поставлена, **не** физический результат.
- `running` — наблюдаемый прогресс конкретной команды.
- `completed` — завершённый результат операции. Для motion требуется measured
  pose/evidence с погрешностью; для playback — consumed frames. Если таких
  доказательств нет, physical_verified=false и нельзя утверждать достижение
  позы/слышимое завершение. Transport-only completion не закрывает физическую
  приёмку карточки.
- `cancelled` — прекращение подтверждено в оговорённой области; время и остаток
  движения/звука отдельно измеряются. Один ACK отмены этого не доказывает.
- `rejected` — действие не было допущено, с ограниченной причиной.
- `unknown` — исполнение могло начаться, подтверждение потеряно. Не считать это
  success, cancelled или разрешением повторить физическую команду.

`Result` имеет тот же command id/authority/generation, статус, reason,
physical_verified и evidence id. Телеметрия позы/PCM — отдельное наблюдение с
provenance; указатель на неё не делает невалидную телеметрию достоверной.

Повтор **того же** command id и содержания возвращает прежнюю квитанцию без
повторного исполнения; тот же id с другим содержимым даёт conflict. Таблица
дедупликации ограничена, но запись нельзя выселить раньше срока replay/получения
терминального результата; при исчерпании места новые команды получают busy.
После restart неизвестные операции сверяются с factory owner, не переигрываются.

Replace отзывает старую generation до допуска новой. Cancel/revoke доступен
владельцу области даже после истечения права на новые движения; не требует
разрешения начать действие. Исполняемый пример разделяет `command_admitted`
для новой цели и `owned_control_admitted` для отмены. Последний требует текущую
аутентифицированную authority и локальную запись владельца конкретного
(capability, command id, generation), но не live permit на новую цель. Аргументы
отмены содержат точный target_command_id; иной владелец, область или поколение
не допускаются. Ограниченный срок управляющего сообщения сохраняется.
Поздний completion предыдущего поколения может
обновить журнал своей команды, но не resurrect старый output или допуск.
При невозможности подтвердить остановку состояние unknown блокирует новую
конфликтующую цель. Полный STOP/quiet/privacy/sleep распространяется и на idle.

## Исполняемые примеры и граница их доказательства

[Fixtures](../tests/fixtures/robot_hub_contract/examples.json) объявляют шесть
синтетических descriptors и конверты. [Проверка](../tests/test_robot_hub_contract.py)
не импортируется production и не является вторым runtime: чистые helpers
проверяют договорённые правила над конечными векторами, без сокетов и устройств.
Один пример проектирует новую scalar-метрику в настоящий `State.ingest`/`Sensor`.

```sh
PYTHONPATH=src:tests .venv-review/bin/python -m unittest test_robot_hub_contract -v
```

Проверяются 13 сценариев: новый room.temperature без отдельной ветки обработки сенсора;
unsupported gripper на старом Hub и блокировка только grasp; minor downgrade
и несовместимый major; обязательное подтверждение support/каталога и локальный TTL; registration без permit; отзыв permit/смена generation и собственная отмена после отзыва;
stale/replay/reconnect/reboot; unknown age против нуля; accepted/unknown receipt
без повторного действия; допустимые/лишние/out-of-range arguments; latest-only метрика и независимый control slot.
Последний trace моделирует политику очередей, не измеряет реальный Scheduler.
Фикстура аргументов motion описывает только синтетический yaw ±0,3 rad;
это не рабочие физические пределы. Медиаканалы, фактическая отмена,
производительность и калибровка не проверены.

## Что переиспользовать и что внедрять следующим

| Существующее место | Решение |
|---|---|
| [contracts.Authority/Binding/Sensor](../src/reachy_companion/autonomous/contracts.py) | Переиспользовать identity и локальную TTL-проекцию; добавить отдельные registry/sequence/permit metadata, не копировать Scheduler. Causality JSON из старой schema содержит ещё snapshot-поля и не равен Authority.wire. |
| [State.ingest](../src/reachy_companion/autonomous/state.py) | Уже принимает новые sensor id в пределах sensor_cap. Ставить validated adapter перед ingest; сам State не является проверкой нового сетевого envelope. |
| [Services.advance](../src/reachy_companion/autonomous/services.py), [production.attach](../src/reachy_companion/autonomous/production.py) | Добавить согласование descriptors для зарегистрированных читателей и bounded latest ingress; сохранить один owner State/SQLite и независимые IO Jobs. Нынешний HTTP reader имеет строгий старый shape, обновлять совместимо. |
| [companion_session](../src/reachy_companion/autonomous/companion_session.py), [production_start](../deploy/autonomous/production_start.py) | Использовать существующий путь запуска; конфигурация selects adapters, а не второй orchestration loop. |
| [camera_sensor](../src/reachy_companion/autonomous/camera_sensor.py), [audio_peer](../src/reachy_companion/autonomous/audio_peer.py) | Источники boot/sequence/age и metadata; начать с метрик. Не переписывать PCM/video transport вместе с каталогом. |
| [историческая capability schema](../tests/fixtures/contracts/schemas/capabilities.schema.json) | Описывает вызовы web/shell/reason/speech, а не аппаратный каталог. Не подключать как будто она уже умеет negotiate сенсоры/приводы. Старые design fixtures сохраняются как история. |

**Следующая узкая карточка CATALOG-01 (проект передачи ведущему).** В существующий
`production.attach → Services.advance → Scheduler.ingest → State.snapshot`
подключить каталог и scalar observation adapter для одной пары metrics на
существующем HTTP пути. Начать с программного источника и текущих численных
метрик camera_sensor; не менять захват камеры, медиапоток и движение.
Добавить versioned descriptor/boot/sequence к источнику, явно согласовывать
поддержку и переход на старый формат; без silent fallback к новым полям.
Описание/единицы/актуальность нового источника видны в модельном snapshot.

Приёмка CATALOG-01: обычный production entrypoint с loopback source добавляет
новую метрику без изменения State, отзывает кэш при removal/privacy/disconnect,
не принимает old boot/sequence, при чтении age >= TTL уже stale, unknown остаётся unknown, slow reader не
накапливает задачи; все старые sensor paths и STOP проходят регрессии. Техлид
проверяет реальный registry и адаптер, не только эти design helpers. Новые
пределы descriptor/очереди фиксируются конфигурацией и негативными тестами.
Аппаратную доступность/точность и совместную нагрузку принимает BASELINE-01.
После этой пары — отдельные карточки media ingress и единого motion executor;
не переносить все шесть обязанностей одним неразличимым изменением.
