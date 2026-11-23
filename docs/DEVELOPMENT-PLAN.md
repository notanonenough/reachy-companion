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

В `origin/main` приняты: карта всех 38 пунктов; [CHAR-01 #3](https://github.com/notanonenough/reachy-companion/pull/3)
(предложение личности через PR без автоматического применения);
[CI-01 #6](https://github.com/notanonenough/reachy-companion/pull/6);
[BASELINE-01 #11](https://github.com/notanonenough/reachy-companion/pull/11)
(фактическая инвентаризация узлов);
[CONTRACT-01 #10](https://github.com/notanonenough/reachy-companion/pull/10)
(согласованный контракт шести модулей, ещё не runtime);
[access prep #13](https://github.com/notanonenough/reachy-companion/pull/13)
(выбираемый SSH-маршрут с закреплёнными ключами и откатом);
[CATALOG-01 #14](https://github.com/notanonenough/reachy-companion/pull/14)
(opt-in scalar registry через штатный production цикл, подтверждённый программно).
Аппаратный кандидат `362002991` установлен на Mac/Hub/Ричи; выпуск ещё не принят.
Кандидат завершил опыт после102.58s: Hub прекратил renewal по ещё не установленной
причине, device закрыл controller lease. Сквозная акустика, кадр, движение и
verified cleanup не приняты; текущие процессы и outputs остановлены.

## Активная работа и следующий контакт

| Карточка | Статус, владелец и ревьюер | Следующий шаг и контакт |
|---|---|---|
| [RELEASE-01, Issue #9](https://github.com/notanonenough/reachy-companion/issues/9) | Новый диагностический rollout; единственный автор стенда — `/root/implementer`, reviewer — `/root/reviewer` | PR #17 принят, выбран `15b784eeafd47cf585e6c87249cec4d523896e41`. Установить/проверить и выполнить один прежний bounded сценарий, затем stop и разбор. После прерывания лимитом возобновлено прежнему автору: окно до 22:35, контроль 22:20 Asia/Baku. Сначала сверить отсутствие частичного rollout. Исходная причина ещё не исправлена. |

Ведущий работает в `reachy-development-map`, исполнитель — в `reachy-audit-map`,
ревьюер — в `/tmp/reachy-review-map`; рабочие ветки короткоживущие `codex/*`.
Основную рабочую копию `reachy-companion` не используют для продуктовых правок.
Read-only инвентаризация закончена; reviewer освободил стенд в 21:18:20 Asia/Baku.
После явного «продолжай» 22:12 автору #9 продлено окно до 22:35 для exact `15b784eea` и одного диагностического опыта.
Сверены origin/main, открытая Issue #9 и отсутствие открытых PR; Mac production checkout пока `362002991`.
Оба автора были прерваны лимитом; прежний владелец стенда возобновлён, reviewer подтвердил доступность.
Reviewer получает стенд только после освобождения и явной передачи ведущим.
LEASE-01 принята через PR #17; её автор `/root/ci_implementer` ожидает результат
аппаратной диагностики для следующей конкретной зависимости; контроль 22:20.
CATALOG входит в новый кандидат, но реальные readers остаются в прежнем legacy mode.
CI-01 принята в 21:03 Asia/Baku: [PR #6](https://github.com/notanonenough/reachy-companion/pull/6),
проверенный head `bc63ac863b64194e70a04510f0fdae0f0f2395d0`, merge в origin/main
`ee3b7abc6c908e8160862ebe768630545379ef40` проверен после слияния. Issue #5 закрыта,
удалённая ветка удалена; автор переключает рабочую копию и удаляет локальную ветку.
[Независимое ревью](https://github.com/notanonenough/reachy-companion/pull/6#pullrequestreview-6025799267)
воспроизвело 42 macOS tests. Оба Linux workflow (45222558837, 45222572115) успешны:
1753 tests, 26 skipped, панель и сборка. Устранены 11 platform-temp ошибок и
race ожидания server handler; production guards не менялись.

Второму исполнителю `/root/ci_implementer` после закрытия CI-01 передана
CONTRACT-01 (передача записана в Issue #2 до начала). Независимый ревьюер подтвердил
ёмкость очереди: сначала заканчивает CHAR-01, затем контракт. Контракт не зависит
от правки личности; его design docs/fixtures не редактируют runtime, схемы и
документы CHAR-01. У каждого автора остаётся одна активная карточка.

## Ближайшая очередь и препятствия

1. **CHAR-01 принята; контракт уточнён владельцем.** Модель может предложить
   изменение personality/principles через отдельный черновик и настоящий GitHub PR
   без обязательного авто-ревьюера. Профиль меняется только после ручного принятия
   владельцем и явного применения; прямое фоновое применение запрещено. Основание §35; контракт согласован
   ведущим и техлидом до реализации. Владелец — `/root/implementer`,
   ревьюер — `/root/reviewer`.
2. **[CONTRACT-01, Issue #2](https://github.com/notanonenough/reachy-companion/issues/2), принята через PR #10.** Контракт шести модулей (§7–10,15–16,19–22)
   описывает каталог, актуальность, допуски и результаты. Следующая узкая задача
   [CATALOG-01, Issue #12](https://github.com/notanonenough/reachy-companion/issues/12)
   принята через PR #14: scalar registry/adapter в существующем runtime.
   Медиатранспорт и движение в неё не входят.
3. **[BASELINE-01, Issue #8](https://github.com/notanonenough/reachy-companion/issues/8), принята через PR #11.** Инвентаризация версий и штатных
   интерфейсов выполнена. Погрешность часов, совместная нагрузка и численные
   бюджеты (§4,10,17–19,25,27–29) остаются следующими аппаратными измерениями
   после первого рабочего выпуска; инвентаризация их не доказывает.
4. **BEHAVIOR-01, после фиксации контракта цикла.** Одна диалоговая модель
   через текущий Scheduler, регулярный вызов в тишине, отмена и актуальность
   результатов (§23–24,30,35); сравнение с текущей парой моделей.

GitHub-доступ восстановлен и проверен 23.11.2026 в 20:48 Asia/Baku:
открытых PR и Issues перед возобновлением не было. CHAR-01 перенесена в
[Issue #1](https://github.com/notanonenough/reachy-companion/issues/1), последующие
изменения проходят через реальные PR в main. MAP-01 сохраняет исторический
локальный эквивалент ревью: на момент её приёмки трекер был недоступен.

При возобновлении сверены main, PR и все рабочие копии. Прерванные агенты
возобновлены; рабочая копия исполнителя была чистой, продуктовых изменений
до прерывания не было. Владелец CHAR-01 не менялся: `/root/implementer`
фактически начал работу в `codex/owner-character` от `a6826c789` в 20:48.

## Ближайший выпуск и постоянная аппаратная приёмка

Владелец установил стартовый ритм: **еженедельное релизное окно по пятницам
с 15:00 Asia/Baku; раньше — при готовности текущего выпуска**. Эта политика
передаётся следующему ведущему вместе с картой. Регулярное дежурство уже
обновлено; отдельную дублирующую автоматизацию не создавать.

Для каждого окна выбирается точный кандидат из `main` и один владелец стенда.
После фактической приёмки ведущий ставит тег и публикует GitHub Release.
Неуспешная проверка ведёт к исправлению и ближайшему повтору, а не к пропуску
непройденного условия. Если новых изменений для установки нет, оставить одну
отметку о проверке окна без пустого релиза. Первый выпуск продолжается в #9;
новый ритм не перезапускает и не отменяет уже идущие проверки.
Автор #9 закрепляет тот же порядок в DEPLOYMENT вместе со следующим протоколом.

[Issue #9 — релиз на реальном стенде](https://github.com/notanonenough/reachy-companion/issues/9)
обязательна в дополнение к инвентаризации #8. Исходный кандидат — принятый commit
`407f4c56e5bca3544fcbbadbb1ac9f14c8e93fad`; новые docs в main его не подменяют.
Инвентаризация выявила препятствие штатному запуску: hardcoded старый Mac
ProxyJump и отсутствующие pinned known_hosts paths. Прямой read-only доступ с
StrictHostKeyChecking и сохранёнными ключами работает. Для #9 нужна проверенная
правка конфигурации доступа с backup/rollback; после её code review ведущий
выбрал новый кандидат `362002991d9c7d8f623af7ed28b91aad365e1bb8` после принятия PR #13.
Роутер пока менять оснований нет. Последующие изменения main кандидата не подменяют.
Назначенный автор #9 — `/root/implementer`, независимый reviewer — `/root/reviewer`,
выпуск принимает ведущий. Первый опыт автора выполнен в окне21:36–21:45; сейчас стенд остановлен.
Резервирование за автором продлено до22:25, контроль22:10; reviewer получает
окно отдельно после освобождения. Новый запуск требует принятого SHA диагностики.

Проверяются версии и рабочие entrypoints всех затронутых служб Ричи/Hub/Mac,
штатный start, микрофон→STT→слышимый ответ, свежий кадр, движение с обратной связью
и stop. Конфигурация/секреты/память сохраняются, предыдущая версия и откат записываются
до установки по [DEPLOYMENT.md](DEPLOYMENT.md). HTTP health не доказывает физический
эффект. Любое неподтверждённое обязательное поведение оставляет выпуск открытым.

Для этого и каждого следующего выпуска тег ставится только на прошедший кандидат,
GitHub Release ссылается на протокол с узлами, версиями, фактическими результатами,
ограничениями и откатом. Предлагаемый первый тег `stand-2026-11-23.1`; пока тег и
Release не созданы, аппаратная приёмка не пройдена. Подробная постоянная карточка — #9.

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
  проверенный и опубликованный коммит: [`719f40a61`](https://github.com/notanonenough/reachy-companion/commit/719f40a61f719165f9fc4bfffa72dc64a5388f1c).
  **Принята 23.11.2026 в 20:44 Asia/Baku:** независимое [APPROVED](reviews/MAP-01.md),
  свежая база совпала, наличие в `origin/main` проверено после push.
  Карточка закрыта, слитая ветка `codex/development-map` удалена локально и в origin.
  Это локальный эквивалент PR по правилам проекта.

### CHAR-01 — личность меняет только владелец

[Issue #1](https://github.com/notanonenough/reachy-companion/issues/1) закрыта после
[PR #3](https://github.com/notanonenough/reachy-companion/pull/3). Автор `/root/implementer`,
независимый reviewer `/root/reviewer`. Принята 23.11.2026 в 21:07 Asia/Baku:
проверенный head `dcba48254661d824f1e61cacc27f41c0d904f0f3`, подтверждённый merge
в origin/main `407f4c56e5bca3544fcbbadbb1ac9f14c8e93fad`.

[Независимое APPROVED](https://github.com/notanonenough/reachy-companion/pull/3#pullrequestreview-6025860091)
подтвердило неизменность diff после rebase и 120 совместных tests. Полные Linux
runs 45223311455/45223326620 успешны: 1767 tests, Node UI, wheel/sdist.
[Синтетический PR #7](https://github.com/notanonenough/reachy-companion/pull/7) подтвердил
публикацию без auto reviewer и без изменения временного профиля; закрыт unmerged.
Remote working branch удалена, автор удаляет локальную при переходе к #8.

Результат: модель может сохранить предложение; явный publisher создаёт настоящий
GitHub PR; владелец вручную принимает/отклоняет, отдельный apply проверяет точную
принятую версию и профильный CAS. Прямое model/background применение запрещено.
Code PR не принимает persona proposal. Установленный профиль не менялся;
развёртывание и физическая приёмка — отдельная Issue #9.

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
| 9 | Т | [autonomous/contracts.py:Sensor,Authority](../src/reachy_companion/autonomous/contracts.py); [assets/autonomous-contracts.json](../src/reachy_companion/assets/autonomous-contracts.json); [tests/fixtures/contracts/schemas/capabilities.schema.json](../tests/fixtures/contracts/schemas/capabilities.schema.json); [autonomous/services.py:sensors](../src/reachy_companion/autonomous/services.py) | CATALOG-01 принята: [scalar registry](../src/reachy_companion/autonomous/scalar_catalog.py) и [протокол](SCALAR-CATALOG.md) подключены через production/Services, explicit support/ack и metadata видны модели. Проверены HTTP loopback и camera cache; executor catalog и аппаратное включение ещё впереди. | 10, 15, 16 | Регистрация нового source/executor видна Hub/модели без перекройки цепочки, старый Hub явно отвечает supported/unsupported; регистрация не разрешает привод. |
| 10 | Т | [autonomous/person_follow.py:plan](../src/reachy_companion/autonomous/person_follow.py); [autonomous/stock_motion_adapter.py:follow](../src/reachy_companion/autonomous/stock_motion_adapter.py); [deploy/current/hub/config/config.autonomous.mac.local.json.template](../deploy/current/hub/config/config.autonomous.mac.local.json.template) (`follow_person=true`); [autonomous/state.py](../src/reachy_companion/autonomous/state.py) | Код рассчитывает head/body, но не доказано физическое участие всех осей. Battery/power/servo.load/lidar остаются unknown. Полного паспорта установленного железа нет. | 9, 29, 37 | Read-only inventory всех устройств → адаптер → Hub consumer → сценарий; телеметрия позы/видео подтверждают body yaw, недоступные источники помечены. |
| 11 | Т | [autonomous/person_follow.py:measured_pose,PersonFollow.plan](../src/reachy_companion/autonomous/person_follow.py); [autonomous/stock_motion_adapter.py](../src/reachy_companion/autonomous/stock_motion_adapter.py); [hub.py](../src/reachy_companion/hub.py) | Ограниченный head/body planner есть на Hub. Высокоуровневый локальный target/TTL/cancel/feedback контракт не реализован целиком. | 9, 15, 29 | Различить gaze/body, относительное/абсолютное, координаты; выполнить цель из ненулевой позы, отменить/заменить и проверить фактическую позу. |
| 12 | Т; язык/процесс — Г, уточнено 15 | [autonomous/stock_motion_adapter.py](../src/reachy_companion/autonomous/stock_motion_adapter.py); [autonomous/person_follow.py](../src/reachy_companion/autonomous/person_follow.py); [autonomous/motion_runtime.py](../src/reachy_companion/autonomous/motion_runtime.py); [native/factory-head-v156/](../native/factory-head-v156) | Фоновое follow/survey на Hub и отдельные узкие native опыты не составляют единого локального непрерывного планировщика. | 11, 15, 17, 34 | Измерить период/jitter/CPU, смешение фоновой и целевой траектории; stop/privacy/sleep/потеря Hub прекращают прежние цели. |
| 13 | Историческое Т, заменено 15 | [Agent unit](../deploy/current/robot/systemd/reachy-voice-agent.service.template); три `deploy/current/robot/systemd/reachy-{voice-agent,production-audio,camera-sensor}.service.template`; [docs/ROBOT-INTERFACES.md](ROBOT-INTERFACES.md) | Существующие три службы не являются тремя целевыми из §13. Не закреплять их число как решение. | 15 | По шести обязанностям проверить независимость media/control; процессы выбрать после нагрузочной проверки. |
| 14 | Т | [autonomous/speech_adapter.py:HttpTTS.stream,SpeechAdapter](../src/reachy_companion/autonomous/speech_adapter.py); [autonomous/playback.py](../src/reachy_companion/autonomous/playback.py); [voice.py](../src/reachy_companion/voice.py) `/stream/say`; [brains.py:answer](../src/reachy_companion/brains.py) | TTS PCM уже потоковый; основной HTTP LLM в brains использует stream=False. Остановка отдельным путём есть. Ранний первый текст/слово и непрерывность не доказаны. | 8, 15, 24, 26 | Один trace LLM→TTS→Hub→PCM: первое слово до полного ответа, bounded buffer, отмена поздних чанков, измерить слышимый звук. |
| 15 | Т, актуальная граница | [motion_policy.py](../src/reachy_companion/motion_policy.py); [camera_permission.py](../src/reachy_companion/camera_permission.py); `autonomous/{playback,audio_peer,camera_sensor,stock_motion_adapter}.py`; [agent.py](../src/reachy_companion/agent.py) | Принят [контракт шести пар](ROBOT-HUB-CONTRACT.md) и первая runtime пара scalar metrics. Общих media/executor adapters ещё нет; текущие права/epochs переиспользуются. | 9, 20, 29 | Ревью контрактов шести модулей и одного владельца источника/действий; конкурирующие media не задерживают revoke/stop; процессы остаются измеряемым решением. |
| 16 | Г технологии + Т совместимости | [autonomous/contracts.py](../src/reachy_companion/autonomous/contracts.py); [assets/autonomous-contracts.json](../src/reachy_companion/assets/autonomous-contracts.json); [tests/fixtures/contracts/validate_design.py](../tests/fixtures/contracts/validate_design.py); `pyproject.toml` | Production Python/JSON, нет Go/gRPC. CATALOG-01 подтверждает negotiated support/ack для opt-in scalar metrics; это не реализация всех media/executor capabilities. | 9, 15, 17 | Минимальный прототип, old/new matrix, обязательное unsupported блокирует только нужный режим, schema-breaking/generated consistency в CI. |
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
| 35 | Т; частота/хранилище Г; reflection П | [autonomous/runtime.py:Scheduler.advance](../src/reachy_companion/autonomous/runtime.py); [autonomous/state.py:snapshot](../src/reachy_companion/autonomous/state.py); [autonomous/services.py:update,advance](../src/reachy_companion/autonomous/services.py); [autonomous/durable.py](../src/reachy_companion/autonomous/durable.py); [tests/test_production_cycle.py](../tests/test_production_cycle.py) | Тишина, TTL, goal CAS, background IO и overload уже есть. Fast/main ещё две модели. CHAR-01 принята через PR #3: прямое применение профиля моделью закрыто, отдельный proposal→GitHub PR без auto reviewer→owner acceptance→apply реализован программно. Код установлен на candidate362 в #9, digest реального профиля не изменился; полный аппаратный выпуск ещё не принят. | 23,30,31,36; запрет auto-character независим | Программно доказать регулярную итерацию в тишине/stale context/разные goals; запретить прямую model/background character mutation; проверить отдельный proposal→PR→owner acceptance→apply и owner update; device acceptance отдельная. |
| 36 | Т редактируемой памяти; recognition П/Г | [autonomous/memory.py:MemoryStore.commit,recall](../src/reachy_companion/autonomous/memory.py); [autonomous/context.py:ContextProvider](../src/reachy_companion/autonomous/context.py); [autonomous/durable.py](../src/reachy_companion/autonomous/durable.py) memory string; [tests/test_memory_context.py](../tests/test_memory_context.py) | Provenance/CAS/forget для записей есть отдельно от character summary. Готового знакомства/связывания лица/голоса с записью нет. | 9,28,30,35 | Owner confirmation→recall→correction/delete; спорное сходство не перезаписывает личность, слова не приписываются присутствующему автоматически. |
| 37 | Действующее разрешение | [docs/REVIEW-NOTES.md](REVIEW-NOTES.md) §37; [scripts/factory_ssh.py](../scripts/factory_ssh.py); [scripts/production-control](../scripts/production-control); [deploy/current/release.py](../deploy/current/release.py); [deploy/autonomous/robot_inventory.py](../deploy/autonomous/robot_inventory.py) | Доступ разрешён владельцем; #8 зафиксировала фактические узлы, #9 проверила direct strict SSH и установленный candidate362. Занятость стенда ведётся отдельно. | Координация ведущего | Перед каждым опытом узел/версия/занятость; не повторное согласование разрешённого опыта. |
| 38 | Действующий процесс | [AGENTS.md](../AGENTS.md); [docs/REVIEW-NOTES.md](REVIEW-NOTES.md) §38; git baseline | MAP-01 принята в origin/main, роли и CHAR-01 назначены; процесс каждого следующего изменения проверяется отдельно. | MAP-01, reviewer | По каждому diff base/head/checks/reviewer verdict, свежий main; только ведущий merge и карта, автор исправляет замечания. |

## Воспроизведённые проверки

На указанном SHA из отдельного дерева с `PYTHONPATH=src`:

- `/Users/notanonenough/workspaces/reachy-companion/.venv-review/bin/python -m unittest discover -s tests -p test_production_cycle.py` — 35 tests, OK.
- `PYTHONPATH=src:tests /Users/notanonenough/workspaces/reachy-companion/.venv-review/bin/python -m unittest test_camera_sensor test_person_follow test_audio_peer test_memory_context test_wake_startup test_interaction test_network_observation test_imu_readout` — 92 tests, OK.

Итого 127 тестов. Использовались fake/mock IO. Это подтверждает выбранные программные paths, не physical latency/wake/sound. Системный `/usr/bin/python3` не имеет jsonschema; существующий `.venv-review` пригоден. Рабочее дерево осталось чистым.


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

Карта принята по точному коммиту `719f40a61` после [независимого ревью](reviews/MAP-01.md);
23.11.2026 в 20:44 Asia/Baku ведущий проверил этот результат в `origin/main`. Ни один тест в этом этапе не подтверждает
физическое движение, звук или текущую версию стенда.

Контроль 23.11.2026 в 21:00 Asia/Baku: ведущий сверил `origin/main` (`f1b87ed41`),
PR #3/#6 и чистые рабочие копии обоих авторов; следующий шаг CHAR-01 у ревьюера,
CI-01 у ведущего после CI. Работы продолжаются, следующая контрольная точка —
21:10 Asia/Baku, результат сообщается раньше.

Приёмка CI-01 21:03 Asia/Baku: сопоставлены точный head, независимое review и два
успешных CI; свежая main отличалась от проверенной базы только картой. После merge
проверена ancestry exact head в origin/main, закрытие Issue #5 и удаление remote
ветки. Автору CHAR-01 передана база, CONTRACT-01 передана освободившемуся автору.

21:08 Asia/Baku: CHAR-01 принята, следующий шаг передан одному автору #8;
CONTRACT-01 продолжает второй автор. Кандидат #9 зафиксирован; окно read-only #8
выделено до любых изменений стенда. Ведущий продолжает сопровождение до результатов.

Контроль 21:15 Asia/Baku: PR #10 и чистая рабочая копия сверены, новый head
`59f18d2aeda1b8fe134c4017f4e339590230b25a` получил [APPROVED](https://github.com/notanonenough/reachy-companion/pull/10#pullrequestreview-6026041053).
Три замечания support/ack, local TTL и scoped cancel исправлены и закрыты;
55 tests воспроизведены независимо, полный CI ожидается. Следующий контакт21:25.
Автор #8 сообщил проверенные старые current targets `review-20261114-7fc7f0204`
на обоих Linux узлах и успешный verify640files, отчёт ещё оформляется и требует
отдельного review. Mac jobs/Hub сеанс остановлены, robot audio failed; эти
предварительные данные не являются приёмкой нового выпуска.

Контроль 21:20 Asia/Baku: BASELINE-01 принята через [PR #11](https://github.com/notanonenough/reachy-companion/pull/11),
точный head `1eaf703cc624f44f4fa7e6ad45504f908e7acdbf`, merge
`3bbbc3ae3379274600ef0e9768470997c04e717c` проверен в origin/main.
[Независимое review](https://github.com/notanonenough/reachy-companion/pull/11#pullrequestreview-6026108041)
повторило read-only проверки на узлах; оба CI45225911564/45225862252 успешны.
Issue8 закрыта, remote ветка удалена, локальную автор удаляет при следующем старте.
Факты — [BASELINE-01](BASELINE-01.md); прежний installed7fc не объявляется нынешним
working сеансом. Автору передана Issue9: сначала code/config prep PR (Refs9),
после его приёмки — новый кандидат и отдельное окно изменений стенда.

CONTRACT CI выявил существующий race теста storage failure: expiry допуска раньше
SQLite. Ведущий разрешил test-only фиксацию часов и fault injection в достигнутой
транзакции; production/TTL/guards не меняются, verified revoke сохраняется.
Автор и reviewer воспроизвели причину; новая версия проходит review/CI.

Приёмка CONTRACT-01 21:27 Asia/Baku: [PR #10](https://github.com/notanonenough/reachy-companion/pull/10)
слит после [независимого APPROVED](https://github.com/notanonenough/reachy-companion/pull/10#pullrequestreview-6026242151)
точного `cb044599d7011d9b6bfd666f4b6d424ec9003d2e`. Reviewer повторил 67 tests
и delayed-heartbeat сценарий; оба Linux CI45226609182/45226625903 успешны
(1780 tests, 26 skipped, Node и package build). Свежая main добавляла только
BASELINE/map docs; merge-tree без конфликтов. Merge
`b1c87370cedf8d180f2b48964d9f647460e16887` и ancestry проверены в origin/main,
Issue2 закрыта, remote branch удалена; локальную автор удаляет при переходе.

[CATALOG-01 #12](https://github.com/notanonenough/reachy-companion/issues/12)
назначена освободившемуся `/root/ci_implementer`, reviewer `/root/reviewer`.
Техлид подтвердил границу: существующий production цикл, bounded scalar catalog,
explicit compatibility и freshness; без media/motion/deploy. Первый loopback
и план — 21:40 Asia/Baku. Аппаратные accuracy/load остаются непроверенными;
BASELINE дала inventory, а не приёмку этих свойств. Access boundary #9 отдельно
согласована техлидом, стенд пока свободен.

Контроль 21:32 Asia/Baku: prep [PR #13](https://github.com/notanonenough/reachy-companion/pull/13),
head `4d4f5f192428b56c30e59578f9a4593e34b61a66`, получил конкретное
[CHANGES REQUESTED](https://github.com/notanonenough/reachy-companion/pull/13#pullrequestreview-6026325207):
удаление managed Host boundary меняло effective config чужого alias (0→42),
хотя строки сохранялись. Автор исправляет, live install не выполнялся.
CATALOG уже воспроизводит первый loopback через штатный production entrypoint;
13 новых/55 existing tests прошли локально, пока не независимая приёмка.
Следующий шаг автора — camera/config edges и PR, контроль21:50.

Приёмка CATALOG-01, 21:45 Asia/Baku: PR #14 слит как
`43bcc45bd1ddec8ace6860252474d15193652e85`; ancestry точного reviewed head
`972959f65e2f24e7412a1fce07d9fd4fc692a3a3` проверена в origin/main.
[Независимое APPROVED](https://github.com/notanonenough/reachy-companion/pull/14#pullrequestreview-6026526400)
подтвердило 134 targeted tests и два delayed probes. Оба Linux CI
45230437328/45230450409 успешны: 1817 tests, 26 skipped, Node и сборка.
Issue #12 закрыта, remote branch удалена; автор удаляет local branch при переходе
к [LEASE-01 #15](https://github.com/notanonenough/reachy-companion/issues/15).

Аппаратный контроль 21:45 и передача 21:46: кандидат `362002991` установлен,
но сквозной опыт не принят. Подробности сохраняет
[protocol PR #16](https://github.com/notanonenough/reachy-companion/pull/16),
не закрывающий #9. Автор и reviewer подтвердили нехватку first-invalid данных;
второму исполнителю назначена #15, reviewer прежний, контроль21:55.
Стенд остановлен, новые start/recovery отложены до принятой диагностики и
явного выбора следующего кандидата. Это не отказ от выпуска и не его приёмка.
