# Baseline для масштабного ревью

## Границы и порядок чтения

Репозиторий объединяет ранее незакоммиченные изменения голосового цикла,
разрешения камеры/движения, визуальное внимание, сетевую диагностику и
эксплуатационные команды. Снимок текущей установки выделен в `deploy/current/`.
Он получен сверкой реальных процессов, effective systemd units/drop-ins,
launchd plists, конфигов, Python-пакетов, моделей и OpenWrt UCI на четырёх узлах.

Начать ревью с `COMPONENTS.md` и manifest, затем:

1. **Полномочия и STOP:** `agent.py`, `microphone.py`, `camera_permission.py`,
   `motion_policy.py`, `hub.py`, `autonomous/{contracts,state,actuator_guard,
   lease_datagram,audio_peer,stock_motion_adapter}.py`.
2. **Жизненный цикл сеанса:** `production_start.py`, `device_audio_runtime.py`,
   `scripts/production-control`, `autonomous/{runtime,production,companion_session}.py`.
3. **Звук/модели:** `voice.py`, `transcription.py`, `recognition.py`,
   `autonomous/{gateway,audio_adapter,speech_adapter,voice_chain}.py`.
4. **Зрение/реакции:** `camera_sensor.py`, `object_detector.py`, `vision.py`,
   `person_follow.py`, `visual_attention.py`, `scene_changes.py`.
5. **Оператор и эксплуатация:** `control_page.py`, `production_status.py`,
   `production_logs.py`, `deploy/current/` и три deployment helpers.
6. **Память и доставка:** `autonomous/{memory,durable,context}.py`, `experience.py`.

`docs/BEHAVIOR.md` описывает целевое поведение, а не подтверждает реализацию
каждого требования. Альтернативные native/Windows/Docker/workflow ветви
отмечены отдельно в COMPONENTS. Исторические patch/preimage fixtures сохранены
для регрессий; старые installers не являются источником актуальной конфигурации.

## Что приведено к единому источнику

- Linux project services используют один архив исходников через `ROOT/current`;
  прежние `ops-*` и `continuous-*` overrides больше не определяют активный код.
- Mac использует тот же checkout; worker/gateway перечитывают код после
  контролируемого перезапуска. Модельные binaries/weights сверяются отдельно.
- 95 шаблонов конфигурации связывают содержимое Git с установленными файлами.
  Новые количества/итоги при дальнейшем обновлении смотреть в manifest.
- Effective unit заводского daemon консолидирован без перезапуска процесса
  (PID до и после 908); сеть не перезапускалась.
- Заводской SDK выделен отдельно: версия 1.2.11 и точный проверяемый двухстрочный
  live-status patch; Bluetooth/launcher/ALSA/boot настройки сохранены.
- Router UCI, LAN/WAN/AP/DHCP/firewall/SSH и профили NetworkManager обоих Linux
  узлов сохранены. На Mac сохранены plists, SSH config и known_hosts.
- Credentials не включены. Их назначения и процедура восстановления описаны
  в DEPLOYMENT; рендер без обязательных значений завершается ошибкой.

Релизный архив содержит commit и хеш каждого файла. Документационный commit
после выкладки может отличаться от runtime release commit; проверка сравнивает
также **всё содержимое исполняемого проектного кода**, чтобы это различие не
скрывало расхождение версий. Итоговый machine-readable отчёт:
`deploy/current/observations/verification.json`.

## Проверки

Выполняются в отдельном `.venv-review` по `requirements/dev.lock` и
`requirements/robot.lock`, с editable install без дополнительных зависимостей.
Команды в README. Полный Git history обязателен для historical-preimage тестов.
Отдельно выполняется JavaScript тест панели и сборка wheel/sdist.
Итог: **1753 теста, 1727 прошли, 26 пропущены**, ошибок нет; JavaScript панели
и wheel/sdist прошли. После исправления пути network dispatcher повторно
прошли 8 deployment-тестов. Число skip и границы проверки записаны в
verification.json.

Deployment-тесты проверяют обязательные секреты, SHA шаблонов, JSON, отсутствие
старых release-путей, установку в изолированный root, backup, scope-изоляцию,
подмену stage и запрещённые пути. Проверки на устройствах включают SHA кода,
SDK, конфигов и моделей, effective launch settings и HTTP health. Отчёт не
подменяет физическую проверку микрофона/динамика/камеры/движений.

## Известные ограничения для ревью

| Область | Наблюдение и значение |
|---|---|
| Legacy snapshot vision | `snapshot_vision.py` требует SDK 1.11.0, а factory environment содержит 1.2.11. Этот старый путь не совместим с текущим factory SDK; автономный `camera_sensor.py` реализует другой путь. Не считать spoken snapshot route проверенным. |
| Legacy Windows settings | В полных config.local templates остаются наблюдавшиеся `192.168.2.134`/Windows параметры для старых функций. Текущая речь идёт через Hub router → Mac. Сохранение фактического конфига не делает эти маршруты работоспособными. |
| Физическая задержка ответа | Пользователь наблюдал медленный ответ; сверка версий/health не является измерением сквозной задержки. Для следующего ревью нужны реальные audio timelines и отдельная приёмка на устройстве. |
| Сеанс production | До сверки Hub production и device audio были failed/inactive. Подготовка baseline не должна автоматически разрешать новый автономный сеанс или движение; запуск — явная команда оператора. |
| Перенос состояния | Сохранённое намерение оператора не равно активному lease. Старые owner/boot epochs и deadline нельзя импортировать на новую ОС; разрешения, привязанные к прежнему Agent boot, могут потребовать включения заново. |
| SoX provenance | Точный наблюдавшийся бинарник сохранён и проверяем. Его `--version` пуст; соответствие приложенному reference source14.4.2 и воспроизводимая компиляция не доказаны. См. vendor/README. |
| Полная ОС | Образы и package inventories закреплены, но полный OS rebuild/прошивка на чистом железе не выполнялись. Доступность старых Debian/APK пакетов зависит от архива поставщика. |
| Новые SSH host keys | Known_hosts фиксируют текущие устройства. После переустановки ключи нужно проверить и обновить; отключать StrictHostKeyChecking для обхода не требуется. |
| S3/личные данные | Память и delivery queue не входят в Git; restore credentials/данных отдельный. HTTP health не доказывает доставку каждой старой записи. |
| Альтернативные пути | Windows, Docker, native factory-head и workflow tools остаются для тестов/отдельного использования, но не входят в текущий running deployment. |

## Правила следующего изменения

Менять канонический template и его SHA одновременно. Сначала тесты и render,
затем commit, immutable archive, сверка на устройстве и переключение current.
Не копировать отдельные Python-файлы в старые release directories: это снова
создаст несколько неопределённых версий. Не хранить журналы, secret stages,
веса или локальные backup в Git. После изменения конфигурации обновить
COMPONENTS/DEPLOYMENT и observation report, затем проверить чистоту дерева.
