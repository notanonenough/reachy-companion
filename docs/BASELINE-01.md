# BASELINE-01: фактический стенд 23 ноября 2026

Карточка: [#8](https://github.com/notanonenough/reachy-companion/issues/8).
Read-only наблюдения автора: **17:08:59–17:16 UTC / 21:08:59–21:16 Asia/Baku**.
База отчёта `38b3c3103536f69702f9404dab33325f04e8a1e0`.
Команды выполнялись последовательно одним владельцем стенда. Не запускались
SDK-конструктор ReachyMini, захват изображения/разговора, движение, установка,
изменение разрешений, DSP/firmware или перезапуск служб. Сырые private configs,
токены и логи не входят в отчёт. Это снимок доступности, не физическая приёмка.

## Узлы и реально используемый код

| Узел | ОС / Python | Источник запуска и проверка |
|---|---|---|
| Reachy `reachy-mini`, aarch64 | Debian 13, 13.3; kernel `6.12.62+rpt-rpi-v8`; companion 3.13.5, factory 3.12.12 | `/home/pollen/reachy-companion/current` → `releases/review-20261114-7fc7f0204`; штатный `release.py verify`: OK, 640 файлов; дополнительных `src/**/*.py` нет |
| Hub `reachy-hub`, aarch64 | Debian 13, 13.7; kernel `6.18.50+rpt-rpi-v8`; Python 3.13.5 | `/home/deploy/reachy-companion/current` → тот же release ID; verify: OK, те же 640 файлов, лишних Python-файлов нет |
| Mac, arm64 | macOS 26.6.2 (25G83); production `.venv` Python 3.13.18 | Plists ссылаются на `/Users/notanonenough/workspaces/reachy-companion/src`; checkout на момент проверки `f1b87ed416a741e495254e58fcccf7be84fb947a`, clean. Launchd jobs не загружены |

Оба Linux-манифеста подтверждают commit
`7fc7f0204179ae1bac2430e281b66520e7f9630f`, content SHA-256
`61b17c5a9a588a784d95ade8e34601f8c9a316a380f657adb10f64f768746091`.
Это установленный предыдущий релиз для планирования отката, **не подтверждение
работоспособного сквозного сеанса**. Корневые Git checkout имеют другие HEAD:
robot `f759ddf12586b4a79e915dbd4638bbcccf6cb5d6`, hub
`7f5249d9c838170112677d46237e65cb81712cdd`. Они dirty (20/19 строк porcelain;
на robot часть старых каталогов недоступна для чтения); ими нельзя подменять
источник `current` или автоматически откатывать дерево.

Linux project environments содержат по одной metadata `reachy-companion 0.2.0`.
Robot: `webrtcvad-wheels 2.0.14.post1`; Hub: `jsonschema 4.26.0`.
Factory `/venvs/mini_daemon`: SDK `reachy_mini 1.2.11`, motor controller `1.5.6`,
`pollen_bmi088_imu_library 1.0.0rc1`, rust kinematics `1.0.3`, pyusb `1.3.1`,
libusb-package `1.0.26.3`. Штатный vendor `apply.py verify` подтвердил патч SDK.
На Mac editable distribution представлена dist-info и source egg-info 0.2.0;
фактический import идёт из checkout. Это не два запущенных процесса. Mac:
jsonschema 4.26.0, vosk 0.3.44, piper-tts 1.8.0, faster-whisper 1.2.1,
numpy 2.5.4, onnxruntime 1.31.1. Хеши весов в этой инвентаризации не проверялись.

## Службы и сквозная доступность

| Узел / unit | Наблюдение | Эффективная точка входа |
|---|---|---|
| Robot `reachy-mini-daemon` | active/running PID 908 | root `u96-safe-launcher.sh`, factory Python |
| Robot `reachy-mini-bluetooth` | active/running PID 907 | `/usr/bin/python3 /bluetooth/bluetooth_service.py` |
| Robot `reachy-voice-agent` | active/running PID 516874 | project `.venv/bin/python -m reachy_companion`, `PYTHONPATH=ROOT/current/src` |
| Robot `reachy-production-audio` | failed, exit-code 2; последний exit **14.11 07:13:51 GMT**, PID 0 | production audio unit; отказ предшествует этой проверке |
| Robot `reachy-camera-sensor` | inactive/dead | factory Python `-m reachy_companion.autonomous.camera_sensor`, `current/src` |
| Hub `reachy-hub`, `reachy-voice`, `reachy-robot-tunnel` | active/running PIDs 707, 709, 708 | project `.venv-router`, `current/src`; отдельный SSH tunnel |
| Hub `reachy-production` | inactive/dead | `.venv-router/bin/python`, `current/deploy/autonomous/production_start.py` |
| Mac `local.reachy.{fast,llm,gateway,tunnels,vlm,worker}` | plists существуют; jobs отсутствуют в `launchctl list` | production checkout, `PYTHONPATH=ROOT/src` |

У перечисленных Linux units `DropInPaths` пуст. Mac health endpoints на
18097/18098/8082/8097/18099 недоступны. На Hub configured compute
`127.0.0.1:18082` и gateway `:8097` отказывают в соединении;
`127.0.0.1:18000/api/daemon/status` отвечает 200 через действующий robot tunnel.
Штатный [production status](../src/reachy_companion/production_status.py)
17:08:59 UTC сообщил compute unavailable, SSHFailed для robot/Hub, session
unavailable: SSH-ошибка здесь не доказывает выключенный узел.

## Сеть и часы

| Узел | Live интерфейс / маршрут | Наблюдение часов |
|---|---|---|
| Mac | en0 `192.168.0.104/24`, MTU 1492, gateway `192.168.0.1` | NTP unknown: `sudo -n systemsetup -getusingnetworktime` требует пароль; настройки не менялись |
| Robot | wlan0 `192.168.0.184/24`, MTU 1500, gateway `.1`; LinkedList **2437 MHz / 2.4 GHz**, −27 dBm, link RX/TX 72.2 Mbit/s | NTP=yes, NTPSynchronized=yes, timezone Europe/London |
| Hub | wlan0 `192.168.0.186/24`, MTU 1500, gateway `.1`; LinkedList **5180 MHz / 5 GHz**, −40 dBm, RX 390 / TX 433.3 Mbit/s | NTP=yes, NTPSynchronized=yes, timezone Europe/Moscow |

Это радиостатистика одного момента, не полезная пропускная способность, RTT или
p95. NTP-флаг не измеряет межузловой skew. Factory status продолжал показывать
старый `wlan_ip=192.168.100.43`; для топологии использован kernel `ip`, не этот
кэш. Router отдельно не инвентаризировался: узлы карточки — robot/Hub/Mac.

**Препятствие штатному доступу:** effective `ssh -G` для обоих aliases содержит
`ProxyJump reachy-router-vuqar` (`192.168.100.45`). Mac уже в LAN192.168.0/24;
обычный SSH завершился `Connection closed by UNKNOWN port 65535`. Каталога
`~/reachy-network-recovery` и указанных там known_hosts нет. Прямой маршрут без
подмены missing known_hosts закономерно отказал при strict checking. Прямой
маршрут **с существующими pinned keys из репозитория** работает, без отключения
проверки ключа и без записи новых ключей:

- robot ED25519 `SHA256:GlOd19ZK0wlxeX+vk0jathiD6sF/2Zynfyvaf0VBKLg`;
- hub ED25519 `SHA256:Ma0vsohxFeAYWa23cxqthN9pp24W+Bo1OGPISykicEA`.

Предложение для отдельной release-карточки: сохранить закрытую копию текущих
Mac SSH config/known_hosts (включая факт отсутствия файла), восстановить pinned
key files и сделать robot/Hub route прямым для этой LAN. Одних render values
недостаточно: [SSH template](../deploy/current/mac/ssh/config.template) содержит
жёсткий `ProxyJump`; key files относятся к **network**, не runtime scope
[manifest](../deploy/current/manifest.json). Не устанавливать весь network scope
ради двух aliases. Сначала согласовать минимальную правку template/manifest либо
явный локальный override; откат возвращает сохранённый config и наличие файлов.
Mac `local.reachy.tunnels` инициирует SSH **к Hub**, reverse ports 18097/18082/8097
обеспечивают Hub→Mac compute. Исправление Mac alias затрагивает этот путь;
отдельного Hub→Mac SSH login менять не требуется. Оснований менять router сейчас
нет. В этой карточке ни одна из этих правок не применялась.

## Источники: что действительно доступно

| Источник | Live API / единицы / свежесть | Потребитель и оставшийся пробел |
|---|---|---|
| Factory / моторы | GET8000 `/api/daemon/status`: SDK1.2.11, backend ready, running, simulation/mock false, mode enabled; `/api/motors/status`: enabled | [stock adapter](../src/reachy_companion/autonomous/stock_motion_adapter.py), [Hub](../src/reachy_companion/hub.py). Enabled не доказывает движение или безопасность stop; running moves `[]`, current app null не доказывают эксклюзивное владение |
| Измеренная поза / суставы | `/api/state/full?with_head_joints=true&with_passive_joints=true&with_doa=true`: меняющийся timestamp, head pose (m/rad), body yaw rad, 7 head joints и 2 antennas rad; passive joints null | Hub/stock adapter используют pose. Неподвижные чтения не проверяют точность, люфт, tracking или stop. OpenAPI рекламирует target flags, но live response с ними **не содержит target полей** |
| IMU | Subscribe-only Zenoh `tcp/localhost:7447`, `reachy_mini/imu_data`: 149 сообщений за 3.020 s, receive span 2.986 s; acceleration m/s², gyro rad/s, quaternion, temperature °C. Пример accel≈[−0.288,0.181,9.794], temp44.5 | Factory backend публикует, проектного autonomous consumer не найдено. Payload без timestamp/sequence; это свежесть получения, не возраст измерения. REST `/api/state/imu`404. Температура чипа не комнатная; калибровка/force/touch не проверены |
| DoA / speech flag | GET `/api/state/doa`200 и full `with_doa=true`: angle rad, speech_detected false; три чтения17:11:37.182842–.608038 UTC, angle1.8675→1.9199 | Factory audio `get_DoA` читает DSP `DOA_VALUE_RADIANS`. Нет измеренной точности/дистанции/идентификации человека и autonomous consumer. Exact DSP firmware, AEC/AGC/NS settings **unknown**: нужен отдельно проверенный read-only USB helper, без writes/reset |
| USB audio / DSP | ALSA card0 Reachy Mini Audio, capture/playback device0, 2 channels, S16_LE, 16000Hz. Оба PCM RUNNING owner PID908 (factory); aliases `plug:reachymini_audio_src/sink` | [audio session](../src/reachy_companion/autonomous/audio_session_control.py)/production audio. Agent microphone_enabled=false, capture_active=false, phase=paused. Factory PCM RUNNING не является записью речи, STT или слышимым ответом |
| Камера | `/tmp/reachymini_camera_socket` существует; factory daemon работает. Agent camera-state enabled=false, generation2, error null; sensor unit inactive. `/api/camera/specs` и `/api/media/status`404 | [camera sensor](../src/reachy_companion/autonomous/camera_sensor.py) и camera perception. Размер/fps/exposure, timestamp свежего кадра и фактический владелец потока не подтверждены; кадры не запрашивались. Socket existence не доказывает живое изображение |
| Батарея, servo current/torque/load, lidar | Не обнаружены как подтверждённые источники в проверенном API; значения unknown | Нужны документированный read-only источник и проверка наличия железа; не выводить из позы/IMU. I²C scan не выполнялся |

## Воспроизведение без изменения стенда

Из checkout этой версии, после получения окна у ведущего:

```sh
# Текущие aliases и закреплённые fingerprints (не выводит private key).
ssh -G reachy-mini | rg '^(hostname|user |proxyjump|hostkeyalias|userknownhostsfile|stricthostkeychecking) '
ssh-keygen -lf deploy/current/mac/ssh/robot-known-hosts.template
ssh-keygen -lf deploy/current/mac/ssh/hub-known-hosts.template

# Функции только для этого shell: config/known_hosts не изменяются.
robot() { ssh -S none -o ProxyJump=none -o UserKnownHostsFile="$PWD/deploy/current/mac/ssh/robot-known-hosts.template" -o BatchMode=yes -o ConnectTimeout=5 reachy-mini "$@"; }
hub() { ssh -S none -o ProxyJump=none -o UserKnownHostsFile="$PWD/deploy/current/mac/ssh/hub-known-hosts.template" -o BatchMode=yes -o ConnectTimeout=5 reachy-hub "$@"; }
robot 'readlink -f /home/pollen/reachy-companion/current; python3 /home/pollen/reachy-companion/current/deploy/current/release.py verify --root /home/pollen/reachy-companion/current'
hub 'readlink -f /home/deploy/reachy-companion/current; python3 /home/deploy/reachy-companion/current/deploy/current/release.py verify --root /home/deploy/reachy-companion/current'
robot '/venvs/mini_daemon/bin/python /home/pollen/reachy-companion/current/deploy/current/robot/vendor/apply.py verify --site-packages /venvs/mini_daemon/lib/python3.12/site-packages'
robot 'systemctl show reachy-mini-daemon reachy-voice-agent reachy-production-audio reachy-camera-sensor -p ActiveState -p SubState -p MainPID -p DropInPaths'
hub 'systemctl show reachy-hub reachy-voice reachy-robot-tunnel reachy-production -p ActiveState -p SubState -p MainPID -p DropInPaths'
robot 'ip -4 -brief addr; ip route; /usr/sbin/iw dev wlan0 link; timedatectl show -p NTPSynchronized -p NTP -p Timezone'
hub 'ip -4 -brief addr; ip route; /usr/sbin/iw dev wlan0 link; timedatectl show -p NTPSynchronized -p NTP -p Timezone'
robot 'curl -fsS --max-time 3 "http://127.0.0.1:8000/api/state/full?with_head_joints=true&with_passive_joints=true&with_doa=true"'
robot 'curl -fsS --max-time 3 http://127.0.0.1:8000/api/state/doa; cat /proc/asound/cards; cat /proc/asound/card0/stream0'
```

IMU-проверка не создаёт ReachyMini и не публикует команды. Перед повторением
сверить factory SDK; его `io/zenoh_client.py` и robot backend определяют topic
и единицы. Подписка живёт три секунды; на диск измерения не сохраняются:

```sh
robot /venvs/mini_daemon/bin/python - <<'PY'
import json, time, zenoh
samples = []
config = zenoh.Config.from_json5(json.dumps({"mode": "client",
    "connect": {"endpoints": ["tcp/localhost:7447"]},
    "scouting": {"multicast": {"enabled": False}}}))
session = zenoh.open(config)
def receive(sample):
    samples.append((time.monotonic(), str(sample.key_expr),
                    json.loads(sample.payload.to_bytes())))
subscriber = session.declare_subscriber("**/imu_data", receive)
time.sleep(3)
subscriber.undeclare()
session.close()
print({"count": len(samples), "first": samples[:1], "last": samples[-1:]})
PY
```

## Следующий опыт и выпуск

[#9](https://github.com/notanonenough/reachy-companion/issues/9) должен отдельно
устранить маршрут доступа, проверить Mac artifacts, сохранить закрытый rollback
backup конфигурации/данных и выпустить один проверенный архив выбранного main.
Кандидат на выдаче — `407f4c56e5bca3544fcbbadbb1ac9f14c8e93fad`; изменения доступа
могут потребовать нового принятого кандидата. Установленная версия выше не содержит
CHAR-01. Текущий профиль владельца менять для опыта не требуется.

После разрешённого запуска проверить реальную цепочку mic→STT→**слышимый** ответ,
новый camera frame с возрастающим timestamp, bounded motion с наблюдаемым эффектом
и feedback, затем stop с прекращением эффекта. HTTP200/создание job не заменяют
эти receipts. Физическое наблюдение владельца или независимый физический канал
нужно предусмотреть до утверждения «слышимо/остановлено».

Для следующей нагрузочной карточки сначала определить часы: локальный monotonic
для очередей/first PCM/движения, получение и возраст frame/IMU, измеренный skew
между узлами. Затем p50/p95/p99 capture→STT, decision→first audible PCM,
stop→последний реально consumed PCM/движение и frame age при совместной нагрузке.
Численные бюджеты, точность DoA/IMU и awake/stop latency здесь **не приняты**.
