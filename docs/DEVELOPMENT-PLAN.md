# Карта разработки Reachy Companion

Обновлено: 23 ноября 2026, Asia/Baku. Единственный редактор — ведущий `/root`.
Основание: [правила работы](../AGENTS.md), [решения 1–38](REVIEW-NOTES.md),
[целевое поведение](BEHAVIOR.md). Карта описывает проверенный исходный код;
сохранённая конфигурация не считается доказательством текущего состояния устройств.

## Цель этапа и принятая основа

Цель — личный автономный компаньон: непрерывное восприятие и выбор поведения
в активном сеансе, включая тишину, с памятью и управляемой владельцем личностью.
Первый этап — связать все решения с реализацией и устранить ближайшие конкретные
расхождения через существующий путь запуска, сохраняя остановку и разрешения.

Исходная общая версия: `f75fb382b460f6963ce674efcf4f16b5e1b9de15` (`origin/main`).
В ней уже есть Python Scheduler, регулярные fast-вызовы и самостоятельные
кандидаты в тишине, SQLite-состояние, допуски, аудиовладелец и камера через daemon.
Одна диалоговая модель, шесть согласованных модулей и общий каталог возможностей
пока не приняты как реализованный результат. Go/gRPC остаются кандидатами
для сравнительного опыта; число процессов не зафиксировано (§15 имеет приоритет
над ранними схемами §12–14).

## Активная работа и следующий контакт

| Карточка | Статус, владелец и ревьюер | Следующий шаг и контакт |
|---|---|---|
| [MAP-01](#map-01-карта-всех-решений) | В работе; автор карты — ведущий `/root`, аудит — `/root/implementer`, независимый ревьюер — `/root/reviewer` | Ведущий собирает карту; ревьюер проверяет точный коммит. Контакт 23.11.2026 в 20:45 Asia/Baku, затем новая контрольная точка по результату. |

Ведущий работает в `reachy-development-map`, исполнитель — в `reachy-audit-map`,
ревьюер — в `/tmp/reachy-review-map`; рабочие ветки короткоживущие `codex/*`.
Основную рабочую копию `reachy-companion` не используют для продуктовых правок.
Стенд пока никому не выделен; все текущие проверки офлайн.

## Ближайшая очередь и препятствия

1. **CHAR-01, готова после MAP-01.** Запретить изменение личности и принципов
   результатом модели/фонового обновления; дать владельцу явную офлайн-правку
   через существующий production CLI. Основание §35; контракт согласован
   ведущим и техлидом до реализации. Владелец — `/root/implementer`,
   ревьюер — `/root/reviewer`.
2. **CONTRACT-01, подготовка контракта.** Описать общий конверт наблюдений,
   каталог возможностей и результаты шести модулей (§7–10,15–16,19–22).
   До реализации обеих сторон техлид проверяет совместимость, недоступность
   источника, отзыв допуска и обратную связь. Транспорт пока не выбирать.
3. **BASELINE-01, подготовка измерений.** Инвентаризация версий и штатных
   интерфейсов, единые часы/погрешность, исходная совместная нагрузка и бюджеты
   (§4,10,17–19,25,27–29). Нужен последовательный доступ к стенду.
4. **BEHAVIOR-01, после фиксации контракта цикла.** Одна диалоговая модель
   через текущий Scheduler, регулярный вызов в тишине, отмена и актуальность
   результатов (§23–24,30,35); сравнение с текущей парой моделей.

GitHub CLI установлен, но не авторизован; сохранённых HTTPS credentials нет,
чтение Issues через API вернуло HTTP 504. `git fetch origin` доступен по SSH;
`git ls-remote origin 'refs/pull/*/head'` не показал PR refs. Полный список Issues
не проверен. Пока трекер недоступен, постоянное место карточек — этот файл,
локальный эквивалент PR — опубликованная ветка/точный коммит и документ ревью.
Это предусмотренный [AGENTS.md](../AGENTS.md) порядок. Повторная авторизация
владельца для продолжения Git-работы не требуется.

## Карточки

### MAP-01 — карта всех решений

- Результат: опубликованный `docs/DEVELOPMENT-PLAN.md` с покрытием 1–38,
  доказательствами, пробелами, зависимостями и приёмкой каждого пункта.
- Границы: документация и чтение кода; без изменения продукта и стенда.
- Зависимости: опубликованные AGENTS, BEHAVIOR, REVIEW-NOTES и свежая `origin/main`.
- Владелец: ведущий `/root`; аудит кода: `/root/implementer`;
  независимый техлид: `/root/reviewer`.
- Проверка: номера 1–38 ровно по одному, локальные ссылки существуют;
  техлид выборочно воспроизводит утверждения через штатные тесты и проверяет
  приоритет §15, разделение §23/35 и отсутствие ложной аппаратной приёмки.
- База: `f75fb382b460f6963ce674efcf4f16b5e1b9de15`;
  рабочая ветка: `codex/development-map`. Проверяемый коммит и решение ревью
  будут сохранены перед приёмкой.

### CHAR-01 — личность меняет только владелец

- Ожидаемый результат: модель, reflection и VPS-update не могут менять
  `personality`/`principles`; память и цель продолжают обновляться. Владелец
  может явно изменить профиль при остановленном runtime.
- Решение: §35 и BEHAVIOR; исходное расхождение — `Services.advance/update`,
  автоматически вызывающие `maintenance=character` и применяющие patch.
- Границы: существующие Services, схемы ответа модели и production CLI;
  без новой сетевой службы, голосового редактора профиля, смены моделей,
  развёртывания или изменения аппаратного поведения.
- Контракт: Services принимает только `goal`/`memory`; нет `origin=owner`
  из model payload. Удалить character inference и предложения такой правки
  из схем модели; поздние старые character-ответы отклонять. Новый
  `production set-character` использует существующий `DurableStore.update`,
  CAS (`expected`), причину и `DurableStore.claim`, отказывая при активном
  владельце runtime. Начальная инициализация и доверенный rollback сохраняются.
- Зависимости: принятая MAP-01 и согласованная выше граница owner/model.
- Владелец: `/root/implementer`; независимый ревьюер: `/root/reviewer`.
- Воспроизводимая приёмка: виртуальное время после character deadline —
  ни вызова character inference, ни изменения профиля; model/VPS/mixed patch
  и поздний character result не меняют профиль; memory/goal продолжаются;
  CLI сохраняет валидную правку с новой ревизией, отказывает при stale revision,
  слишком длинной строке и работающем runtime. Ключевые тесты ревьюер запускает
  самостоятельно. Это программный результат, физических эффектов не заявляем.
- Статус: готова к назначению после MAP-01; базу, ветку, контрольную точку
  и точный коммит ведущий добавит при выдаче.

## Как читать привязку решений

**Т** — согласованное требование; **Г** — гипотеза или вариант для измерения;
**П** — дальнейшая перспектива; **И** — исследование завершено, перенос не принят.
«Есть» означает найденный код/конфигурацию и названную проверку, а не успешное
физическое испытание. Отсутствие подтверждения явно остаётся пробелом.
Зависимости ниже — рабочий порядок задач, а не требование переписать систему
целиком до небольшого полезного исправления.

## Что реально запускается

`companion` объявлен в `pyproject.toml` → [src/reachy_companion/__main__.py](../src/reachy_companion/__main__.py). Сохранённый производственный запуск: [scripts/reachy-on](../scripts/reachy-on) → [scripts/production-control](../scripts/production-control); unit [deploy/current/hub/systemd/reachy-production.service.template](../deploy/current/hub/systemd/reachy-production.service.template) → `deploy/autonomous/production_start.py hub` → [autonomous/companion_session.py](../src/reachy_companion/autonomous/companion_session.py); device unit аналогично вызывает `production_start.py device`. Hub использует Python [autonomous/runtime.py:Scheduler](../src/reachy_companion/autonomous/runtime.py); фоновый IO — [autonomous/services.py:Services](../src/reachy_companion/autonomous/services.py). Сохранённые units/configs свидетельствуют о конфигурации, не о фактической версии на включённом устройстве.

В `Scheduler.advance` есть регулярный fast LLM даже в тишине и единственный заменяемый autonomous-кандидат для main раз в 30 с. Старые agent/finite/native ветви и эксперименты нельзя автоматически считать текущим production. Сохранённый профиль `bounded_stock` использует `StockMotionAdapter` на Hub; отдельный `MotionRuntime` показывает `supported=bounded_antenna17_only`, не готовую локальную координацию всех приводов.

## Привязка всех 38 пунктов

В каждой строке «приёмка» означает будущую проверку недостающего результата. Ни один будущий опыт не заявлен выполненным. Т — требование/согласованное направление; Г — гипотеза или выбор после измерения; П — перспектива. Уточнение §15 имеет приоритет над числом процессов §12–14; §30/35 — над прежней парой LLM.

| § | Тип | Проверяемая опора в текущем дереве | Фактическое состояние и недостающий результат | Зависимости | Приёмка/ближайшая проверка |
|---|---|---|---|---|---|
| 1 | Т | [deploy/current/robot/utilities/u96-safe-launcher.sh:18](../deploy/current/robot/utilities/u96-safe-launcher.sh); [scripts/production-control:ensure_robot_awake](../scripts/production-control); [tests/test_wake_startup.py](../tests/test_wake_startup.py) | Launcher отключает boot wake и stop sleep; ручной запуск отдельно делает guarded wake. Заводское включение не восстановлено. | 2, 29, 37 | Определить заводской эталон версии; затем физическая кнопка при остановленном Mac, отдельно штатный sleep и рестарт. |
| 2 | Т | [deploy/current/robot/systemd/reachy-mini-daemon.service.template](../deploy/current/robot/systemd/reachy-mini-daemon.service.template); [deploy/current/robot/vendor/manifest.json](../deploy/current/robot/vendor/manifest.json); [deploy/current/robot/vendor/reachy-mini-1.2.11-live-status.patch](../deploy/current/robot/vendor/reachy-mini-1.2.11-live-status.patch); [deploy/current/manifest.json](../deploy/current/manifest.json) | Сохранён изменённый daemon/launcher, не заводской эталон. Камера использует `/venvs/mini_daemon`. Изоляция Companion и восстановление ещё нужны. | 15, 29, 37 | Сверить образ/версию и чистый SDK, diff штатных units; Companion отсутствует/остановлен, factory lifecycle работает. |
| 3 | Т + Г выбора | [src/reachy_companion/production_logs.py:run_logged,prune_reports](../src/reachy_companion/production_logs.py); [deploy/current/hub/systemd/reachy-report-retention.timer.template](../deploy/current/hub/systemd/reachy-report-retention.timer.template); аналог робота | Mac уже RotatingFileHandler; Linux journald плюс свой таймер отчётов. Готовая общая retention-политика не выбрана. | 33 | Инвентаризация нужных отчётов, выбор journald/tmpfiles/logrotate по формату, проверка лимита/давности/активного сеанса. |
| 4 | Т; Go — Г | [autonomous/audio_peer.py](../src/reachy_companion/autonomous/audio_peer.py); [deploy/autonomous/device_audio_runtime.py](../deploy/autonomous/device_audio_runtime.py); [autonomous/camera_sensor.py](../src/reachy_companion/autonomous/camera_sensor.py); [tests/test_audio_stop_capacity.py](../tests/test_audio_stop_capacity.py) | Есть ограниченные слоты, отдельная остановка и lease. Нет принятого бюджета и сравнительных p99 на целевом устройстве. | 15, 17, 37 | Зафиксировать бюджет и baseline CPU/RSS/задержек при совместной нагрузке, потере связи и зависшем обработчике. |
| 5 | Т, уточнено 15 | [agent.py](../src/reachy_companion/agent.py); [autonomous/audio_peer.py](../src/reachy_companion/autonomous/audio_peer.py); [autonomous/camera_sensor.py](../src/reachy_companion/autonomous/camera_sensor.py); [docs/ROBOT-INTERFACES.md](ROBOT-INTERFACES.md) | Обязанности распределены между Agent, audio, camera, Hub и factory; единый согласованный локальный слой ещё не выделен. | 2, 15 | Матрица обязанностей/владения, путь каждого сигнала и отмены через публичный entrypoint; обоснование процессов. |
| 6 | Т | [autonomous/audio_peer.py:AudioPolling](../src/reachy_companion/autonomous/audio_peer.py); [autonomous/gateway.py:Gateway](../src/reachy_companion/autonomous/gateway.py); [autonomous/vision.py](../src/reachy_companion/autonomous/vision.py); [deploy/current/mac/ssh/config.template](../deploy/current/mac/ssh/config.template) | Hub получает audio observations, но Mac gateway запрашивает camera frames через туннель. Централизации всех потоков на Hub нет. | 8, 15, 20, 22, 24 | Проследить звук/кадр/метрики/состояние и отключить прямой опрос робота вычислителями; проверить свежесть и backpressure. |
| 7 | Т; дополнительные сенсоры — Г | [autonomous/camera_sensor.py:Measurements.publish,snapshot](../src/reachy_companion/autonomous/camera_sensor.py); [autonomous/audio_peer.py:publish_level](../src/reachy_companion/autonomous/audio_peer.py); [imu_readout.py:temperature_readout](../src/reachy_companion/imu_readout.py); [autonomous/network_observation.py](../src/reachy_companion/autonomous/network_observation.py) | Реальны brightness/change, RMS/delta, сеть; IMU readout отдельно, не полный каталог. Нажатие/нагрузка/сила не доказаны. | 9, 10, 29 | Каталог source/unit/sequence/time/TTL/unavailable; одинаковые записи шума; картинка при повороте/освещении; доступность servo данных read-only. |
| 8 | Т; транспорт — Г | [autonomous/audio_peer.py:PersistentPeer,AudioPolling,create_server](../src/reachy_companion/autonomous/audio_peer.py); [autonomous/lease_datagram.py](../src/reachy_companion/autonomous/lease_datagram.py); [autonomous/video_adapter.py:LatestFrameProcessor](../src/reachy_companion/autonomous/video_adapter.py) | HTTP polling и Base64 media, отдельный stop listener; UDP служит lease, не доказанному PCM-транспорту. Есть latest-only в отдельных видеообработчиках. Общий streaming контракт ещё нужен. | 16, 17, 18, 25 | Замеры возраста и очереди при медленном потребителе, reconnect, loss; отдельные требования для media и подтверждаемых команд. |
| 9 | Т | [autonomous/contracts.py:Sensor,Authority](../src/reachy_companion/autonomous/contracts.py); [assets/autonomous-contracts.json](../src/reachy_companion/assets/autonomous-contracts.json); [tests/fixtures/contracts/schemas/capabilities.schema.json](../tests/fixtures/contracts/schemas/capabilities.schema.json); [autonomous/services.py:sensors](../src/reachy_companion/autonomous/services.py) | Типизированные частные контракты и ручной словарь сенсоров есть; fixture schema не подключённый динамический production-каталог. | 10, 15, 16 | Регистрация нового source/executor видна Hub/модели без перекройки цепочки, старый Hub явно отвечает supported/unsupported; регистрация не разрешает привод. |
| 10 | Т | [autonomous/person_follow.py:plan](../src/reachy_companion/autonomous/person_follow.py); [autonomous/stock_motion_adapter.py:follow](../src/reachy_companion/autonomous/stock_motion_adapter.py); [deploy/current/hub/config/config.autonomous.mac.local.json.template](../deploy/current/hub/config/config.autonomous.mac.local.json.template) (`follow_person=true`); [autonomous/state.py](../src/reachy_companion/autonomous/state.py) | Код рассчитывает head/body, но не доказано физическое участие всех осей. Battery/power/servo.load/lidar остаются unknown. Полного паспорта установленного железа нет. | 9, 29, 37 | Read-only inventory всех устройств → адаптер → Hub consumer → сценарий; телеметрия позы/видео подтверждают body yaw, недоступные источники помечены. |
| 11 | Т | [autonomous/person_follow.py:measured_pose,PersonFollow.plan](../src/reachy_companion/autonomous/person_follow.py); [autonomous/stock_motion_adapter.py](../src/reachy_companion/autonomous/stock_motion_adapter.py); [hub.py](../src/reachy_companion/hub.py) | Ограниченный head/body planner есть на Hub. Высокоуровневый локальный target/TTL/cancel/feedback контракт не реализован целиком. | 9, 15, 29 | Различить gaze/body, относительное/абсолютное, координаты; выполнить цель из ненулевой позы, отменить/заменить и проверить фактическую позу. |
| 12 | Т; язык/процесс — Г, уточнено 15 | [autonomous/stock_motion_adapter.py](../src/reachy_companion/autonomous/stock_motion_adapter.py); [autonomous/person_follow.py](../src/reachy_companion/autonomous/person_follow.py); [autonomous/motion_runtime.py](../src/reachy_companion/autonomous/motion_runtime.py); [native/factory-head-v156/](../native/factory-head-v156) | Фоновое follow/survey на Hub и отдельные узкие native опыты не составляют единого локального непрерывного планировщика. | 11, 15, 17, 34 | Измерить период/jitter/CPU, смешение фоновой и целевой траектории; stop/privacy/sleep/потеря Hub прекращают прежние цели. |
| 13 | Историческое Т, заменено 15 | [Agent unit](../deploy/current/robot/systemd/reachy-voice-agent.service.template); три `deploy/current/robot/systemd/reachy-{voice-agent,production-audio,camera-sensor}.service.template`; [docs/ROBOT-INTERFACES.md](ROBOT-INTERFACES.md) | Существующие три службы не являются тремя целевыми из §13. Не закреплять их число как решение. | 15 | По шести обязанностям проверить независимость media/control; процессы выбрать после нагрузочной проверки. |
| 14 | Т | [autonomous/speech_adapter.py:HttpTTS.stream,SpeechAdapter](../src/reachy_companion/autonomous/speech_adapter.py); [autonomous/playback.py](../src/reachy_companion/autonomous/playback.py); [voice.py](../src/reachy_companion/voice.py) `/stream/say`; [brains.py:answer](../src/reachy_companion/brains.py) | TTS PCM уже потоковый; основной HTTP LLM в brains использует stream=False. Остановка отдельным путём есть. Ранний первый текст/слово и непрерывность не доказаны. | 8, 15, 24, 26 | Один trace LLM→TTS→Hub→PCM: первое слово до полного ответа, bounded buffer, отмена поздних чанков, измерить слышимый звук. |
| 15 | Т, актуальная граница | [motion_policy.py](../src/reachy_companion/motion_policy.py); [camera_permission.py](../src/reachy_companion/camera_permission.py); `autonomous/{playback,audio_peer,camera_sensor,stock_motion_adapter}.py`; [agent.py](../src/reachy_companion/agent.py) | Все шесть обязанностей имеют частичные реализации, но общих адаптеров source/executor и каталога нет; текущие права/epochs стоит переиспользовать. | 9, 20, 29 | Ревью контрактов шести модулей и одного владельца источника/действий; конкурирующие media не задерживают revoke/stop; процессы остаются измеряемым решением. |
| 16 | Г технологии + Т совместимости | [autonomous/contracts.py](../src/reachy_companion/autonomous/contracts.py); [assets/autonomous-contracts.json](../src/reachy_companion/assets/autonomous-contracts.json); [tests/fixtures/contracts/validate_design.py](../tests/fixtures/contracts/validate_design.py); `pyproject.toml` | Production Python/JSON, нет Go/gRPC-протокола. Существующие JSON schema не подтверждают negotiated capabilities. | 9, 15, 17 | Минимальный прототип, old/new matrix, обязательное unsupported блокирует только нужный режим, schema-breaking/generated consistency в CI. |
| 17 | Т измерений | `deploy/autonomous/{audio_peer_network_probe,native_scheduler_probe,speech_network_probe}.py`; [tests/test_turn_latency.py](../tests/test_turn_latency.py); [autonomous/runtime.py:latencies](../src/reachy_companion/autonomous/runtime.py) | Есть probes/программные метрики; нет свежего общего baseline и утверждённых бюджетов каждого физического пути. | 4, 8, 18, 37 | Письменные бюджеты до сравнения; p50/95/99/max, clocks/error, CPU/RSS/очереди и потери на одинаковой совместной нагрузке. |
| 18 | Г профиля сети | [docs/LOCAL-NETWORK-DESIGN.md](LOCAL-NETWORK-DESIGN.md); [deploy/current/router/uci/network.template](../deploy/current/router/uci/network.template); [deploy/current/router/uci/wireless.template](../deploy/current/router/uci/wireless.template); QoS nft templates Hub/robot | Есть воспроизводимые снимки OpenWrt/QoS и проект; свежая топология и нагрузочные числа не проверены этим аудитом. | 17, 37 | Read-only radio/routes/queues, первый опыт существующего одного 5 GHz радио с одновременными потоками; затем сравнение вариантов uplink. |
| 19 | Т очереди исследований | [docs/LOCAL-MEDIA-RESEARCH.md](LOCAL-MEDIA-RESEARCH.md); `autonomous/{camera_sensor,audio_peer,video_adapter}.py`; [tests/test_camera_sensor.py](../tests/test_camera_sensor.py) | Исследование имеется; пять флажков реализации остаются открыты. Есть частичные метрики/буферы, нет общей завершённости. | 7–17 | Пять опытов блокнота: каталог, шум/VAD, кадр+движение, bounded queues/cancel, сопоставимый transport benchmark. |
| 20 | Т направления | [autonomous/companion_session.py](../src/reachy_companion/autonomous/companion_session.py); [autonomous/services.py](../src/reachy_companion/autonomous/services.py); [hub.py](../src/reachy_companion/hub.py); `autonomous/{audio_adapter,speech_adapter,stock_motion_adapter}.py` | Hub координатор/клиенты уже есть, но пары неоднородны и видео частично напрямую Mac. Каталог/confirmed state нужно объединить. | 15, 22, 24 | Сквозной trace каждой пары, общая authority/TTL/capability, panel показывает подтверждённое роботом состояние. |
| 21 | Т | [autonomous/runtime.py:Scheduler.advance](../src/reachy_companion/autonomous/runtime.py); [autonomous/audio_peer.py:_watch_loop](../src/reachy_companion/autonomous/audio_peer.py); [motion_policy.py](../src/reachy_companion/motion_policy.py); [autonomous/stock_motion_adapter.py](../src/reachy_companion/autonomous/stock_motion_adapter.py) | Hub асинхронен; локальный audio watchdog есть. Локальные движения/реакции ещё не общая программа на Ричи. | 11, 12, 20, 23 | Заблокированный внешний model/VLM не останавливает восприятие; revoke действует локально, фактический результат возвращается Hub. |
| 22 | Предложенная Т схема | [autonomous/audio_peer.py:AudioPolling,PeerClient](../src/reachy_companion/autonomous/audio_peer.py); [autonomous/camera_sensor.py:Handler](../src/reachy_companion/autonomous/camera_sensor.py); [autonomous/gateway.py](../src/reachy_companion/autonomous/gateway.py) | Сейчас Hub открывает audio polling, Mac frame polling; требуемый robot→Hub вход для аудио/кадров/метрик ещё не реализован. | 8, 15, 20 | Проверить инициатора и ответы каждого из шести потоков, reconnect/identity; независимый stop от очереди playback. |
| 23 | Т; Go — Г | [autonomous/runtime.py:Scheduler.ingest,advance](../src/reachy_companion/autonomous/runtime.py); [autonomous/state.py:apply](../src/reachy_companion/autonomous/state.py); [autonomous/services.py:advance](../src/reachy_companion/autonomous/services.py) | Event handling и background Job есть, но fast LLM продолжает выбирать действия. Полностью детерминированный быстрый Hub цикл ещё нужен. | 30, 31; технология 17 | Заблокированная main, media flood, StopRequested/PermissionRevoked/Timeout и stale completion; bounded queue-to-send задержка. |
| 24 | Т | [autonomous/runtime.py:RemoteGateway](../src/reachy_companion/autonomous/runtime.py); [autonomous/audio_adapter.py:RemoteTranscriber](../src/reachy_companion/autonomous/audio_adapter.py); [autonomous/speech_adapter.py:HttpTTS](../src/reachy_companion/autonomous/speech_adapter.py); [autonomous/gateway.py](../src/reachy_companion/autonomous/gateway.py); config templates | Адреса моделей и сервисов конфигурируются, но gateways не три единых независимых интерфейса Hub; STT получает завершённый фрагмент. | 6, 20, 22, 26 | Подменить только адрес видео или диалогового backend; streaming input начинается до конца реплики и не накапливается. |
| 25 | Г выбора транспорта/кодека | [autonomous/audio_peer.py](../src/reachy_companion/autonomous/audio_peer.py) Base64 `/observation`,`/write`; [autonomous/camera_sensor.py:Measurements.frame](../src/reachy_companion/autonomous/camera_sensor.py); [autonomous/lease_datagram.py](../src/reachy_companion/autonomous/lease_datagram.py) | PCM и JPEG в JSON/Base64; текущий UDP — контроль lease. Бинарная пересылка/PCM loss policy ещё кандидаты. | 8, 17, 18 | Побайтовая проверка JPEG/PCM; байты+CPU+first-chunk+tail latency, одиночные/серийные потери, короткие слова/отрицания. |
| 26 | Т; backend — Г | [voice.py:VoicePipeline,serve](../src/reachy_companion/voice.py); [transcription.py](../src/reachy_companion/transcription.py); `autonomous/{vision,object_detector}.py`; [worker_container.py](../src/reachy_companion/worker_container.py) | Whisper/Vosk/Piper и VLM/YOLOX уже используются; STT не доказан progressive-input, комплексного сравнения нет. | 24, 25, 27, 28 | Единый корпус RU audio/scenes, одновременная нагрузка; ошибки STT/визуала, freshness, TTFT/first audible, отмена. |
| 27 | Г повторного использования | [microphone.py](../src/reachy_companion/microphone.py); [capture_pump.py](../src/reachy_companion/capture_pump.py); [deploy/autonomous/device_audio_runtime.py](../deploy/autonomous/device_audio_runtime.py); [deploy/current/robot/factory-python.lock](../deploy/current/robot/factory-python.lock) | Свой WebRTC VAD; DoA/speech_detected исследованы по 1.2.11, не подключены к общему Hub-каталогу. | 7, 29, 37 | Read-only DSP/channel inventory; одинаковые фразы в тишине/шуме/своём TTS, DoA сзади неоднозначен; сравнение Vosk не равно выбору. |
| 28 | Г повторного использования | [autonomous/camera_sensor.py:CameraSensor.run](../src/reachy_companion/autonomous/camera_sensor.py); [autonomous/person_follow.py](../src/reachy_companion/autonomous/person_follow.py); [autonomous/object_detector.py](../src/reachy_companion/autonomous/object_detector.py); [tests/test_person_follow.py](../tests/test_person_follow.py) | Заводская камера переиспользуется; обнаружение Mac и собственная геометрия follow. Новые YuNet/head-tracking не подтверждены в 1.2.11. | 29, 11, 17 | Геометрия 3×3, body rotation, stale frames; сравнить штатный look_at_image без движения и текущую геометрию, затем физическая точность. |
| 29 | Исследование завершено; перенос Г/Т | [docs/REVIEW-NOTES.md](REVIEW-NOTES.md) §29; [deploy/current/robot/factory-python.lock](../deploy/current/robot/factory-python.lock); [firewall.py](../src/reachy_companion/firewall.py); [deploy/current/hub/systemd/reachy-robot-tunnel.service.template](../deploy/current/hub/systemd/reachy-robot-tunnel.service.template) | Подробный version-pinned обзор есть. Он не означает доступность реальных IMU/DoA и физического stop; SDK upgrade не принят. | 1,2,9,10,15,17,37 | Паспорт 1.2.11 и read-only диагностика узла; по каждому P0/P1 отдельно проверить источники/права/отмену и дать решение. |
| 30 | Т одной модели; выбор модели Г | [autonomous/runtime.py:Scheduler.advance](../src/reachy_companion/autonomous/runtime.py) fast/main; [autonomous/gateway.py:Gateway.locks](../src/reachy_companion/autonomous/gateway.py); hub config `models.fast`+`models.main` | Реально две роли/endpoint. Регулярность в тишине частично есть, одна диалоговая модель ещё не внедрена. | 23, 31, 35, 17 | Один inference backend вызывается по cadence и речи, direct events не ждут LLM; RU corpus, отмена/новая реплика/тишина/initiative. |
| 31 | Исследование завершено; правила Т, classifier Г | [intents.py:classify,classify_with_model](../src/reachy_companion/intents.py); [voice.py:VoicePipeline.classify](../src/reachy_companion/voice.py); [tests/test_interaction.py](../tests/test_interaction.py); [autonomous/state.py](../src/reachy_companion/autonomous/state.py) | Есть прямые команды и optional model classifier, но нормализатор удаляет пунктуацию до проверки: отдельное «замолчи» в кавычках становится stop. Полный Hub event router ещё не готов. | 23,30 | Whole-utterance tests с цитатами/отрицаниями/ASR без пунктуации и NFC; owner/TTL отдельно; ML только после сравнения с правилами. |
| 32 | П | [brains.py:answer](../src/reachy_companion/brains.py) openclaw/hermes; [autonomous/workflows.py:WorkflowClient](../src/reachy_companion/autonomous/workflows.py); [deploy/workflows/](../deploy/workflows); config `workflows.enabled=false` | Текстовые адаптеры и synthetic workflows есть, живые integrations не включены/не подтверждены. Блокирующий полный ответ. | 24,30,34 | Offline trace одинаковый для агентов/обычной модели, identity/cancel/capability; первый полезный workflow определить отдельно. |
| 33 | Т | [autonomous/durable.py:DurableStore.append,Delivery](../src/reachy_companion/autonomous/durable.py); [autonomous/services.py:log,advance](../src/reachy_companion/autonomous/services.py); [tests/test_production_cycle.py](../tests/test_production_cycle.py); [tests/test_s3_delivery_connection.py](../tests/test_s3_delivery_connection.py) | Durable SQLite outbox/retry/batching существует, но append намеренно оставляет только metadata; write синхронный в цикле. Нет полного тестового audio/video/model архива с bounded producer queue. | 3,17,24 | Offline/slow S3, restart/idempotence, completeness+redaction, disk cap gap markers, сравнить latency export on/off. |
| 34 | Исследование завершено; перенос Г | [docs/REACHY-ECOSYSTEM-RESEARCH.md](REACHY-ECOSYSTEM-RESEARCH.md); [emotion_library.py](../src/reachy_companion/emotion_library.py); [assets/pollen-emotions-v1.json](../src/reachy_companion/assets/pollen-emotions-v1.json); [speech_clock.py](../src/reachy_companion/speech_clock.py); [autonomous/stock_motion_adapter.py](../src/reachy_companion/autonomous/stock_motion_adapter.py) | Есть закреплённые emotion assets и часть timing; не единая локальная композиция primary/idle/gaze/speech. Совместимость новых apps не равна совместимости 1.2.11. | 11,12,14,29,33 | Начать с одного executor/generations; три жеста из ненулевой позы без sidecar sound, consumed PCM sync, отмена; версия/license каждого донора. |
| 35 | Т; частота/хранилище Г; reflection П | [autonomous/runtime.py:Scheduler.advance](../src/reachy_companion/autonomous/runtime.py); [autonomous/state.py:snapshot](../src/reachy_companion/autonomous/state.py); [autonomous/services.py:update,advance](../src/reachy_companion/autonomous/services.py); [autonomous/durable.py](../src/reachy_companion/autonomous/durable.py); [tests/test_production_cycle.py](../tests/test_production_cycle.py) | Тишина, TTL, goal CAS, background IO и overload уже есть. Fast/main ещё две модели. **Прямой конфликт на исходной базе:** periodic character maintenance и model update могут менять personality/principles без запроса владельца. | 23,30,31,36; запрет auto-character независим | Программно доказать регулярную итерацию в тишине/stale context/разные goals; запретить model/background character mutation, оставить явный owner update; device acceptance отдельная. |
| 36 | Т редактируемой памяти; recognition П/Г | [autonomous/memory.py:MemoryStore.commit,recall](../src/reachy_companion/autonomous/memory.py); [autonomous/context.py:ContextProvider](../src/reachy_companion/autonomous/context.py); [autonomous/durable.py](../src/reachy_companion/autonomous/durable.py) memory string; [tests/test_memory_context.py](../tests/test_memory_context.py) | Provenance/CAS/forget для записей есть отдельно от character summary. Готового знакомства/связывания лица/голоса с записью нет. | 9,28,30,35 | Owner confirmation→recall→correction/delete; спорное сходство не перезаписывает личность, слова не приписываются присутствующему автоматически. |
| 37 | Действующее разрешение | [docs/REVIEW-NOTES.md](REVIEW-NOTES.md) §37; [scripts/factory_ssh.py](../scripts/factory_ssh.py); [scripts/production-control](../scripts/production-control); [deploy/current/release.py](../deploy/current/release.py); [deploy/autonomous/robot_inventory.py](../deploy/autonomous/robot_inventory.py) | Доступ разрешён владельцем; аудит не проверял connectivity и запущенный SHA. | Координация ведущего | Перед каждым опытом узел/версия/занятость; не повторное согласование разрешённого опыта. |
| 38 | Действующий процесс | [AGENTS.md](../AGENTS.md); [docs/REVIEW-NOTES.md](REVIEW-NOTES.md) §38; git baseline | Роли назначены, карта подготовлена. Приёмка этой карты требует независимого ревью точного коммита и публикации в main. | MAP-01, reviewer | По каждому diff base/head/checks/reviewer verdict, свежий main; только ведущий merge и карта, автор исправляет замечания. |

## Воспроизведённые проверки

На указанном SHA из отдельного дерева с `PYTHONPATH=src`:

- `/Users/notanonenough/workspaces/reachy-companion/.venv-review/bin/python -m unittest discover -s tests -p test_production_cycle.py` — 35 tests, OK.
- `PYTHONPATH=src:tests /Users/notanonenough/workspaces/reachy-companion/.venv-review/bin/python -m unittest test_camera_sensor test_person_follow test_audio_peer test_memory_context test_wake_startup test_interaction test_network_observation test_imu_readout` — 92 tests, OK.

Итого 127 тестов. Использовались fake/mock IO. Это подтверждает выбранные программные paths, не physical latency/wake/sound. Системный [/usr/bin/python3](../../../../../usr/bin/python3) не имеет jsonschema; существующий `.venv-review` пригоден. Рабочее дерево осталось чистым.


## Порядок зависимостей и журнал проверки

Взаимные ссылки между §9/15/16/20/22 обозначают один совместно проектируемый
контракт CONTRACT-01, а между §23/30/31/35 — контракт поведения BEHAVIOR-01.
Это не циклические блокировки карточек. Сначала фиксируется интерфейс группы,
затем реализация и совместная проверка. Восстановление заводской основы (§2)
предшествует подтверждению boot lifecycle (§1); инвентаризация §10/29 входит
в BASELINE-01 и уточняет каталог, не требует готового исполнения всех приводов.
Выбор Go/gRPC и числа процессов ждёт сравнительного измерения; черновой
контракт можно согласовать до выбора транспорта. CHAR-01 от этих опытов не зависит.

Независимый техлид дополнительно выполнил на исходной базе 95 тестов:
`test_production_cycle.py` (35), `test_autonomous.py` (29),
`test_memory_context.py` (31), каждый через
`PYTHONPATH=src /Users/notanonenough/workspaces/reachy-companion/.venv/bin/python -m unittest discover -s tests -p <файл>`
из отдельной рабочей копии. Эти наборы частично пересекаются с 127 тестами
исполнителя; складывать их как число уникальных тестов нельзя.

Точный коммит карты, итог независимого ревью и факт наличия в origin/main
фиксируются после проверки. Ни один тест в этом этапе не подтверждает
физическое движение, звук или текущую версию стенда.
