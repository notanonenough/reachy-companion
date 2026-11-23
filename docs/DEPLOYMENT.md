# Восстановление текущей установки

Этот документ описывает baseline от 14 ноября 2026. Источник конфигурации —
`deploy/current/manifest.json`, а не старые `install_*.py` и не README из прошлых
релизов. Каждый шаблон имеет SHA-256, конечный путь, права, владельца и scope.
`runtime` — приложение и его запуск; `network` — сеть/SSH/firewall;
`factory` — заводская среда Reachy, ALSA и загрузочные настройки.

## Что требуется сохранить вне Git

Репозиторий воспроизводит программу и настройки, но не переносит идентичность
устройства, пользовательскую память и действующие полномочия.

| Материал | Куда установить | Примечание |
|---|---|---|
| Общий bearer token | `ROOT/secrets/token` на Mac, Hub, Reachy | Одинаковое значение, режим 0600; можно создать новый при восстановлении всей схемы |
| Gateway token | `ROOT/secrets/autonomous-mac.token` на Mac и Hub | Одинаковое значение, 0600 |
| S3 key ID / secret | Mac `ROOT/secrets/yacloud.s3.key.pub`, `…priv` | Нужны для текущей доставки в `reachy-s3`; endpoint/region/prefix находятся в шаблоне |
| Операторский SSH-ключ | Mac `~/.ssh/id_ed25519` | Private key в Git не хранится; public key подставляется в authorized_keys |
| Ключ Hub → Robot | Hub `~/.ssh/reachy_robot_tunnel` | Public key с ограничениями — у `reachy-tunnel` на роботе |
| Wi-Fi PSK | Закрытый JSON по `values.example.json` | LinkedList, Vuqar 5G, резервные Katv и Hotspot |
| SSH host keys | `/etc/ssh/ssh_host_*`, router Dropbear keys | При новой ОС генерируются новые; сверить fingerprint локально и обновить known_hosts |
| Память/очередь доставки | Нужные SQLite/JSON из `ROOT/data/` | Отдельная согласованная backup-копия; не нужна для старта с пустой памятью |

`SECRET_*_PUBLIC_KEYS` — полные строки authorized_keys, включая ограничения.
Для tunnel key действуют `restrict,port-forwarding,permitopen=…`; взять
ограничения из существующего файла или из `deploy/local-security/` и перечислить
только loopback-порты 8000, 8090, 8780, 8781, 8794. Не заменять файл просто
неограниченным публичным ключом. Закрытый JSON и отрендеренные stages содержат
секреты: хранить вне Git, с доступом только владельцу.

Секреты, password hashes, приватные host keys, записи разговора, память и логи
в Git намеренно отсутствуют. Полный закрытый исходный снимок текущей установки
на рабочем Mac сохранён в игнорируемом `data/repository-audit-20261114/`.
Он не является публичным установочным пакетом и требует отдельного backup.

## 1. Базовые ОС и учётные записи

Точные URL, SHA-256 и исходные ревизии образов — в `os-images.json`:

- Reachy: Reachy Mini OS v0.2.3, образ 2026-01-14. Сохраняет factory Python,
  GStreamer/libcamera, GPIO/ALSA и motor-controller 1.5.6. Пользователь `pollen`,
  home `/home/pollen`, группы audio/video/dialout/gpio/i2c/spi/input/render/netdev.
- Hub: Raspberry Pi OS Lite arm64 2026-10-06 (Debian 13). Пользователь `deploy`,
  home `/home/deploy`, sudo и SSH. Наблюдавшийся kernel — 6.18.50+rpt-rpi-v8.
- Router: OpenWrt 25.12.6 для **xiaomi_mi-router-4a-gigabit-v2**. Sysupgrade-образ
  предназначен для совместимой установленной OpenWrt; первичная разблокировка
  стоковой Xiaomi — отдельная процедура производителя/модели.
- Mac: Apple Silicon, macOS 26.6.2 (25G83); текущий Python 3.13.18. Нужны Command
  Line Tools, SSH и рабочий GUI launchd domain пользователя.

Перед записью образа проверить SHA-256 из manifest. Эта подготовка репозитория
не перепрошивала устройства и не проводила полную установку на чистых SD-картах.
`*/os-packages.txt` фиксируют весь установленный набор пакетов и версии. После
образа сверить с ним пакеты, особенно ALSA, nftables, SSH, NetworkManager и
factory media libraries. Это инвентарь, а не обещание вечной доступности старых
Debian/APK пакетов в rolling mirrors; для побитового восстановления ОС нужен
собственный архив пакетов или образ текущего диска.

На роботе создать системного пользователя `reachy-tunnel` с home
`/var/lib/reachy-tunnel`, shell `/usr/sbin/nologin` (если его нет). Не блокировать
public-key SSH этого аккаунта способом, запрещающим sshd аутентификацию вообще.
Основной пользователь имеет UID1000; номера системных групп брать из образа.
Списки sudoers и sshd drop-ins включены в network scope. Не переносить пароль
пользователя или PIN серийного устройства из другого робота.

## 2. Сеть и доступ

Сначала настроить router локально, затем Hub/Reachy, затем Mac. Применять
network scope на существующей машине через локальную консоль или соединение,
которое переживёт смену адресов. На текущей системе менять сеть для обновления
Python-кода не требуется.

1. В закрытой копии `values.example.json` заполнить все `SECRET_*`. Оставленный
   `REPLACE_FROM_PRIVATE_STORE` рендерер отвергает.
2. Отрендерить для каждого host (`router`, `hub`, `robot`, `mac`):

   ```sh
   python3 deploy/current/manage.py render router --values /private/values.json --output /private/stage-router
   ```

3. На router нет Python. Копировать файлы из `stage-router/rootfs/` по путям
   из `rendered.json`, предварительно сохранив `/etc/config`, SSH и системные
   файлы; соблюдать mode. UCI-конфиги проверять `uci show` без публикации вывода.
   Перезапуск network/firewall/DNS выполнять локально после проверки.
4. На Linux установить network scope инструментом ниже. `nmcli connection reload`
   перечитывает профили; подключение `LinkedList-5GHz` выполняется отдельно.
   На роботе создать ссылки
   `/etc/NetworkManager/dispatcher.d/pre-up.d/70-reachy-firewall` и
   `pre-down.d/70-reachy-firewall` на
   `/etc/NetworkManager/dispatcher.d/70-reachy-firewall`. Обработчик использует
   `ROOT/current/src`. На Hub Ethernet autoconnect выключен; Wi-Fi power saving выключен. На router
   AP 5 GHz channel36/VHT80, 2.4 GHz channel6/HT20, LAN192.168.0.1/24.
5. Настроить Mac en0: Vuqar 5G, DHCP, MTU1492; ожидаемый адрес192.168.100.31.
   Router WAN ожидается192.168.100.45. Если DHCP другой — согласовать адреса
   и правило WAN SSH в router firewall.
6. Установить только управляемый Mac SSH-доступ способом ниже; остальные
   файлы network scope не нужны для обновления приложения.
   На новых ОС проверить новые host fingerprints через доверенный локальный
   доступ; закреплённые known_hosts текущих устройств не подходят новым ключам.
   Проверить `ssh reachy-hub`, `ssh reachy-mini`, `ssh reachy-router-vuqar`.

## Mac: выбрать прямой LAN или доступ через router

Live [BASELINE-01](BASELINE-01.md) обнаружила Mac в LAN192.168.0/24,
а старый alias по-прежнему использовал jump192.168.100.45 и отсутствующий
known_hosts. Для такого случая есть `deploy/current/access.py`, использующий
четыре закреплённых manifest templates: managed config и robot/Hub/router
known_hosts. `--route direct` явно задаёт `ProxyJump none`; `--route jump`
сохраняет путь через `reachy-router-vuqar`. В обоих случаях pinned keys,
`StrictHostKeyChecking yes`, users/addresses неизменны. `ProxyCommand none`
стоит после `ProxyJump`: иначе чужой `Host *` может перехватить прямой маршрут,
а перестановка строк может отключить выбранный jump.

Выполнять от владельца Mac home, без sudo. Backup и stage содержат частную SSH
конфигурацию, хранить вне Git. Сначала локальный rehearsal в отдельном корне:

```sh
umask 077
access_work=$(mktemp -d)
python3 deploy/current/access.py render --home "$HOME" --route direct --output "$access_work/stage"
python3 deploy/current/access.py install --stage "$access_work/stage" --root "$access_work/rehearsal" --backup "$access_work/rehearsal-backup"
python3 deploy/current/access.py verify --backup "$access_work/rehearsal-backup"
python3 deploy/current/access.py rollback --backup "$access_work/rehearsal-backup"
```

Для проверки с существующей конфигурацией перед rehearsal скопировать её
в `REHEARSAL_ROOT/$HOME/.ssh/config` (без начального `/` в относительном пути).
Инструмент переносит свои два парных `BEGIN/END reachy…` блока в начало;
остальные байты сохраняет, завершает управляемую область `Host *`.
Отсутствующий каталог `~/.ssh/cm` создаётся с mode0700 и учитывается при откате.
Непарные/повторные маркеры и symlink в файле либо родительском пути дают отказ
до изменения файлов. Если после старого блока идут чужие параметры или
`Include`, удаление блока разрешено только при доказанно той же области
`Host`/`Match`; иначе инструмент отказывает до backup/установки. Владелец должен
явно определить желаемую область этих строк перед повторением. Входной stage сверяется с ровно четырьмя pinned templates,
а не принимается как произвольный список путей.

После принятия prep PR и передачи окна ведущим выполнить реальную установку:

```sh
python3 deploy/current/access.py install --stage "$access_work/stage" --backup "$access_work/installed-backup"
python3 deploy/current/access.py verify --backup "$access_work/installed-backup"
ssh -G reachy-mini | rg '^(hostname|user |proxyjump|proxycommand|hostkeyalias|userknownhostsfile|stricthostkeychecking) '
ssh -G reachy-hub | rg '^(hostname|user |proxyjump|proxycommand|hostkeyalias|userknownhostsfile|stricthostkeychecking) '
# Новое соединение: старый ControlMaster не должен маскировать маршрут.
ssh -S none -o BatchMode=yes -o ConnectTimeout=5 reachy-mini hostname
ssh -S none -o BatchMode=yes -o ConnectTimeout=5 reachy-hub hostname
```

Для `.local` aliases маршрут тот же. `ssh -G` проверяет итоговую конфигурацию,
не доступность устройства. Для jump дополнительно проверить router с его
закреплённым ключом; direct не требует настройки router. Не применять общий
`manage.py install --scope network` ради этого изменения: он устанавливает и
другие network-файлы. Mac reverse tunnels к Hub используют те же aliases и
после разрешённого запуска возвращают compute ports18097/18082/8097.

Backup0700 содержит preimages0600, исходные mode и факт отсутствия каждого
файла в `journal.json`, записанные до первой установки. Ключи устанавливаются
перед config. Атомарная замена отдельного файла не делает весь набор атомарным:
после interruption использовать тот же backup для восстановления:

```sh
python3 deploy/current/access.py rollback --backup "$access_work/installed-backup"
```

Rollback сначала проверяет весь набор: файл должен соответствовать исходному
или установленному digest/mode. Более поздняя чужая правка останавливает откат
без изменений; разбирать её вручную с backup. Частичная установка и повторный
rollback поддержаны; исходно отсутствовавшие файлы удаляются, пустые созданные
каталоги убираются. Backup не перезаписывается. Службы не запускаются и router,
factory, private keys, профиль и память не меняются.

## 3. Код и Python

Получить полный Git checkout выбранного коммита. Рабочее дерево для сборки
релиза должно быть чистым:

```sh
python3 deploy/current/release.py build --root "$PWD" --output /private/reachy-release.tar.gz
```

На Hub и Reachy распаковать **один и тот же архив** в новый уникальный каталог
`ROOT/releases/<release-id>` и проверить:

```sh
python3 ROOT/releases/RELEASE/deploy/current/release.py verify --root ROOT/releases/RELEASE
```

Здесь и ниже `ROOT`/`RELEASE` — обозначения, их заменить реальными путями.
Не распаковывать поверх предыдущего релиза. `release.json` содержит Git commit,
SHA каждого файла и общий content digest. Создать симлинк `ROOT/current` на
проверенный релиз; смена выполняется атомарным переименованием временной ссылки.

Создать окружения в стабильных путях, вне `current`:

| Узел | Python / окружение | Lock |
|---|---|---|
| Hub | 3.13.5, `ROOT/.venv-router` | `deploy/current/hub/python.lock` |
| Reachy Companion | 3.13.5, `ROOT/.venv` | `deploy/current/robot/python.lock` |
| Mac | 3.13.18, `ROOT/.venv` | `deploy/current/mac/python.lock` |
| Reachy factory | 3.12.12, `/venvs/mini_daemon` из образа | `deploy/current/robot/factory-python.lock` |

Пример для Hub:

```sh
python3.13 -m venv /home/deploy/reachy-companion/.venv-router
/home/deploy/reachy-companion/.venv-router/bin/python -m pip install -r /home/deploy/reachy-companion/current/deploy/current/hub/python.lock
```

Собрать wheel на машине ревью (`.venv-review/bin/python -m build --no-isolation`),
перенести один и тот же `dist/reachy_companion-0.2.0-py3-none-any.whl` на оба
Linux узла и установить в их окружения:

```sh
ROOT/.venv-router/bin/python -m pip install --no-deps --force-reinstall /private/reachy_companion-0.2.0-py3-none-any.whl
```

На роботе заменить `.venv-router` на `.venv`. Это синхронизирует также CLI и
package metadata, а не только `PYTHONPATH`. Проверить, что
`importlib.metadata.distributions()` содержит одну версию `reachy-companion`
(0.2.0); старые дубли metadata/каталоги pip `~eachy*` переместить в backup вне
`site-packages`. На Mac допустим editable install из текущего checkout.
Версии вспомогательных pip/build/setuptools/wheel записаны в итоговом
`observations/verification.json`, отдельно от runtime locks.

Проект импортируется через `PYTHONPATH=ROOT/current/src`, заданный в units.
На Mac используется `PYTHONPATH=ROOT/src` из plists и полный checkout. При
разработке можно установить `pip install --no-deps -e .`. Для фиксированного
production окружения не заменять lock расплывчатым `pip install -U`.

Factory environment нельзя заменить project venv. Сверить SDK1.2.11 и
применить только проверенный патч (без запуска оборудования):

```sh
sudo /venvs/mini_daemon/bin/python ROOT/current/deploy/current/robot/vendor/apply.py apply --site-packages /venvs/mini_daemon/lib/python3.12/site-packages
```

Патч откажется работать при неизвестном preimage. Factory scope включает
launcher, BLE-утилиты, `~/.asoundrc` и `/boot/firmware/config.txt`; на новой ОС
установить до старта factory daemon. На текущей — достаточно сверки, без
перезапуска daemon и загрузочных служб.

## 4. Модели и бинарники Mac

```sh
.venv/bin/python deploy/current/artifacts.py fetch --root "$PWD" --home "$HOME"
.venv/bin/python deploy/current/artifacts.py verify --root "$PWD" --home "$HOME"
```

Скрипт проверяет размер/SHA-256 и заменяет файл только после проверки.
Для llama сначала загружается закреплённый `unzstd`, затем точный standalone
бинарник b11941. Модели скачиваются по immutable ревизиям; особенно важно не
заменять Qwen0.8B файлом того же имени с `main` — его содержимое уже изменилось.
SoX восстанавливается из сохранённого бинарника; происхождение его исходной
сборки ограниченно известно, см. `deploy/current/vendor/README.md`.

Создать ссылки `~/.local/bin/play`, `rec`, `soxi` → `sox`, и `reachy-on`,
`reachy-off` → соответствующие файлы `ROOT/scripts/`. `~/.local/bin` добавить
в PATH интерактивного shell. Plists содержат абсолютные пути и от PATH не зависят.

## 5. Рендер, пробная установка и активация

Для нестандартных путей указать `HOME`, `ROOT`, `SOURCE_ROOT` в закрытом JSON.
На Linux SOURCE_ROOT должен быть `ROOT/current`. При переносе пользователя
также адаптировать `User=` и owner в manifest: текущая установка закрепляет
пользователей deploy/pollen/notanonenough.

```sh
python3 deploy/current/manage.py render hub --values /private/values.json --output /private/stage-hub
python3 deploy/current/manage.py install --stage /private/stage-hub --backup /private/rehearsal-backup --root /private/rehearsal-root
python3 deploy/current/manage.py verify --stage /private/stage-hub --root /private/rehearsal-root
```

На целевом Linux после переноса stage:

```sh
sudo python3 ROOT/current/deploy/current/manage.py install --stage /private/stage-hub --backup /private/pre-install
sudo python3 ROOT/current/deploy/current/manage.py verify --stage /private/stage-hub
```

По умолчанию устанавливается только runtime. Для новой установки отдельно
добавить `--scope network`, а на Reachy `--scope factory`. Сетевые/заводские
файлы не активируются самим helper. Папка backup должна быть новой; файлы
пишутся атомарно, содержимое stage предварительно проверяется по хешам.

**Обновление старой установки:** сохранить базовые unit-файлы и каталоги
`/etc/systemd/system/reachy-*.service.d/`, затем убрать старые drop-ins именно
у заменяемых проектных units. Канонические unit-шаблоны уже содержат их
эффективные настройки. Оставленный `zzz-continuous.conf` переопределит новый
PYTHONPATH и вернёт старый код. Factory daemon/bluetooth при обычном обновлении
проекта не заменять. Сохранить старую ссылку `current` для отката.

После установки:

```sh
sudo systemctl daemon-reload
```

На новом Hub включить `reachy-hub`, `reachy-voice`, `reachy-robot-tunnel`,
`reachy-network-qos`, `reachy-report-retention.timer`, `pi-wifi-diagnostics`.
На новом роботе — `reachy-mini-daemon`, `reachy-mini-bluetooth`,
`reachy-voice-agent`, `reachy-companion-firewall`, `reachy-network-qos`,
`reachy-report-retention.timer`. Использовать `systemctl enable --now …` только
после сети, секретов, data-directory и зависимостей. Создать `ROOT/data` с правом
записи пользователю сервиса и `ROOT/secrets` с режимом0700.

**Не включать на boot** `reachy-production`, `reachy-production-audio`,
`reachy-camera-sensor`: это сеансные службы. При обновлении перезапускаются
только прежде работавшие базовые проектные службы. Старые epochs/leases не
восстанавливаются и не являются переносимой конфигурацией.

На Mac установить runtime stage от имени владельца, проверить plists через
`plutil -lint`, загрузить нужные jobs `launchctl bootstrap gui/$(id -u) PATH`
и `launchctl kickstart gui/$(id -u)/LABEL`. Если job уже загружен, после изменения
plist нужны `bootout` и `bootstrap`. Изменение только Python-кода требует
перезапуска worker/gateway. Команда `scripts/reachy-on` запускает полноценный
сеанс, поэтому не использовать её как простую проверку конфигурации.

## 6. Приёмка и откат

Регулярное релизное окно — **по пятницам с 15:00 Asia/Baku**. Если текущий
выпуск готов раньше, его можно проверить и выпустить до этого окна. Ведущий
выбирает точный принятый commit из `main`, назначает одного владельца стенда
и отдельное окно независимого reviewer; более поздняя `main` не подменяет
кандидат во время опыта.

После установки обязательна фактическая приёмка ниже. Только затем ведущий
ставит tag на проверенный commit и публикует GitHub Release со ссылкой на
протокол. Failed gate остаётся открытым: исправление проходит PR/review/CI,
ведущий выбирает новый кандидат и назначает ближайший повтор, без ожидания
следующей пятницы. Если новых изменений нет, достаточно одной отметки об этом
в журнале проверки/карте; пустой релиз и новый tag не создаются.

1. `manage.py verify` сверяет конфигурационные файлы; указать каждый нужный scope.
   На router сверять SHA файлов из rendered manifest по SSH или локально.
2. `release.py verify` на Hub и Reachy подтверждает тот же архив. Проверить
   `systemctl show UNIT -p Environment -p ExecStart -p FragmentPath -p DropInPaths`:
   проектные пути ведут через `current`, старых overlays нет.
3. `artifacts.py verify` на Mac подтверждает все веса и бинарники.
4. `scripts/production-control status --json` проверяет модели, gateway, worker,
   состояние Hub/Robot и factory. Панель доступна через localhost18080/control.
5. В выделенном окне единственный автор выполняет новый штатный start:
   реальная речь с микрофона → STT → слышимый ответ, свежий кадр с timestamp,
   допустимое движение с измеренной обратной связью, затем stop с наблюдаемым
   прекращением звука/движения. Acoustic observation/человек нужны для слова
   «слышимый»; consumed PCM и HTTP health этого не доказывают.
   `production-control stop` завершает сеанс; `reachy-off` выгружает также Mac jobs.
6. В протоколе записать exact main SHA/архив, узлы, effective import/units,
   предыдущую установленную версию и границы её известной работоспособности,
   команды, время/часы, наблюдение каждого эффекта и закрытый путь rollback.
   Не включать память, профиль, secrets и сырые разговоры/кадры в публичный PR.
7. Автор освобождает стенд; независимый reviewer подтверждает тот же кандидат
   и физические результаты. Ведущий после этой приёмки ставит понятный тег
   на проверенный commit и публикует GitHub Release со ссылкой на протокол.
   Более новая main не подменяет кандидат. Непроверенный обязательный сценарий
   остаётся открытым и блокирует тег успешного выпуска.

Откат: остановить сеанс, вернуть прежнюю ссылку `current`, unit-файлы и
соответствующие drop-ins из закрытого backup, выполнить daemon-reload и
перезапустить только затронутые базовые службы. Конфигурацию вернуть из backup
с прежними правами/владельцами. Не восстанавливать старые активные leases,
не воспроизводить отложенные движения и не откатывать сетевые файлы, если они
не менялись. Старые каталоги релизов можно хранить для отката; службы не должны
ссылаться на них напрямую.
