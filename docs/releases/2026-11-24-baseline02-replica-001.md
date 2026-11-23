# BASELINE-02: первая реплика прервана из-за неполного Mac observer

Карточка [#26](https://github.com/notanonenough/reachy-companion/issues/26).
**Baseline не принят:** запланированная120s реплика остановлена после наблюдения
`acquisition_failed` от Mac observer. Hub final elapsed34.074s; сведения о CPU/RSS
Mac отсутствуют. Штатное завершение подтверждено. Повторного старта не было.
Это протокол неудачной попытки измерения, а не исправление runtime или новый выпуск.

## Версии и разрешённые окна

Runtime всех трёх узлов оставался принятым
`stand-2026-11-23.1` / `717a6577a9f7c2b3ff6dd22045761866678b37bc`.
Production checkout Mac также717; результат готовится в отдельной ветке от
`1214c0c50`. Source, runtime configs, модели, TTL и guards исполнитель не менял.
Послесеансовая повторная сверка remote config hashes в этом протоколе не заявляется.

Observer — reviewed `ae581296dc628c2016d2046a98e5d02b37bcbf4c`, merge
`dab21fc09b8a32ebb7cd8698a66ba56eeb1ecec4`, [PR29](https://github.com/notanonenough/reachy-companion/pull/29).
Использован только private snapshot `20261124-observer-harness-review-v3`:
manifest SHA256 `a53af67437d6335b7194981ca24295eb6e8d559c00cf89aaa88a7670ef04cc67`.
Все10 файлов сверены до запуска. Предыдущие v1/v2 не запускались.
Observer helpers доставлялись отдельно от installed runtime; package/config
installation не выполнялась.

Readiness-окно ведущего00:15–00:30 Asia/Baku фактически завершено00:17 и освобождено.
Независимый reviewer сверил private receipts и anchors офлайн. Затем отдельным
назначением в карте `457c24047`/#26 выделена **одна** реплика00:19–00:35 с одним
исполнителем. Фактическое hardware-окно освобождено00:22:24 после cleanup.
Следующий опыт требует отдельного назначения и новой принятой зависимости observer.

## Readiness: установленная версия и остановленные владельцы

Read-only SSH/локальные проверки до старта подтвердили:

- Linux release manifests:673 файла, exact717. Effective source identity60 модулей
  на каждом узле сверена с принятыми `identity-{mac,hub,robot}.json`, включая
  origin/hash/loader bytecode match. Это source provenance, не измерение worker.
- Конфигурации Mac8, Hub7, robot6 совпали с expected hashes из accepted717
  `trace-trial/reviewer-runtime-config-proof.json`. Значения конфигураций и секреты
  не экспортировались; проверки не рендерили новые настройки.
- Hub production inactive/MainPID0,8791 закрыт, manual Hub отсутствует,
  ownership free, action_running=false, stock motion completion известен.
- Robot production audio и camera services inactive/MainPID0; микрофон выключен,
  capture/reader/process закрыты; camera disabled; running_moves=[].
  control_mode=enabled, pose/joint fields присутствуют. Это не новый follow envelope.
- Mac шесть fixed launchd labels unloaded, known owned PID count0; порты
 18097/18098/18099/8082/8097 закрыты.
- Linux `/proc`/boot identity и sysconf доступны (USER_HZ100/page4096 на этих
  узлах); Mac resource API symbols доступны. Resource API calls, fixture runs,
  starts и hardware writes в readiness равнялись0.

Stopped workers не запускались ради получения receipts. Поэтому readiness не
доказывала worker coverage или допустимый target count. Camera panel не выдаёт
отдельные reader/process-closed поля: зафиксированы disabled и inactive unit/PID0.

## Единственный запуск и ранний abort

Запущен existing reviewed harness с параметрами:

```text
reachy-trace-acceptance.py --execute
  --candidate 717a6577a9f7c2b3ff6dd22045761866678b37bc
  --duration 120
  --output /Users/notanonenough/reachy-release-backups/20261124-baseline02-replica-001
```

Interpreter — `.venv-review/bin/python` проекта; `PYTHONPATH` указывает на
production checkout717/src. Remote supervisor получал135s, trace180s;
observer finish планировался на118s, normal stop на120s. Эти плановые сроки
не были достигнуты из-за ранней остановки.

Небольшой reviewed launcher сделал один `execv` этого exact harness, сохранив
собственный PID и Mach start identity. Abort повторно проверил host boot/basis/
Mach identity и отправил SIGINT только этому локальному supervisor. Не было
TTY group interrupt, `pkill`, второго Hub owner или обхода runtime guards.
Reviewer независимо проверил dry-run, отказ на stale identity, exact argv,
сохранение identity через exec и прохождение SIGINT в Python finally.

| Private helper | SHA256 |
|---|---|
| `launch.py` | `d0d6b79e50e5b479c4c7d70cc50ffaf2cf8e531cbc6d1408eeb2a25cddd2ee3e` |
| `abort.py` | `0df5b0a551874f9319a61030757021cc774dc2a6ac27d946897814b90a1272aa` |

Время ниже — журнал supervisor на Mac, Asia/Baku24.11.2026. Это наблюдение
последовательности lifecycle, не точная физическая STOP или acoustic latency.

| Событие | Время |
|---|---|
| Один preflight/start | 00:21:28.823 |
| Device service started | 00:21:40.805 |
| ACTIVE/listening_ready наблюдены | 00:21:45.570 |
| Camera-on receipt accepted | 00:21:48.237 |
| Acoustic capture / controlled stimulus begin | 00:21:49.545 /00:21:53.556 |
| Stimulus exited0 | 00:21:57.873 |
| Mac acquisition failure обнаружен; identity-fenced abort, observer finish request | 00:22:17.943 |
| Authenticated STOP admission ACK | 00:22:19.060 |
| Tracked foreground Hub terminal known | 00:22:19.886 |
| Device/Mac shutdown / camera-off accepted | 00:22:20.889 /00:22:21.479 |
| Independent terminal checks saved | 00:22:23.160 |
| Private trace copied / trial_finished | 00:22:23.944 |

Observer startup происходил после ACTIVE. Как и оговорено до опыта, harness
не имел pre-stimulus three-node ACK gate: камера и stimulus уже начались к
моменту первого чтения observer files. Mac файл содержал только failure footer;
Hub и robot уже давали samples. Исполнитель сразу применил согласованный abort;
нового запуска или повторного discovery после остановки не было.

## Завершение и ограниченные измерения

Локальный harness завершился кодом130 из-за намеренного KeyboardInterrupt,
пройдя existing finally. Authenticated STOP202 был только admission ACK;
затем проверен настоящий Hub child PID43431/start_ticks11810015, exit0 и один
binding-matched final. Hub final: accepted=true, cleanup_verified=true,
errors=[], cleanup_issues=[], все busy=false, control handlers0/listenerfalse;
peer stop_known=true/terminal_unknown=false. Final elapsed34.074108573s.
`accepted=true` описывает runtime cleanup, **не полноту этого baseline**.

Independent finals: robot microphone disabled/closed, capture_active=false,
reader_alive=false, process_alive=false; camera disabled; running_moves=[];
pose_pair_equal=true в двух близких samples, production/camera units inactive/PID0.
Hub production inactive/PID0,8791 закрыт. Mac jobs=[], все пять worker ports закрыты.
Два совпавших pose samples не являются hard-stop certification.

| Observer | Сохранённые результаты | Полнота |
|---|---|---|
| Hub |32 resource samples +32 status;1 process instance,31 CPU deltas | finish_accepted=true, incomplete=false |
| Robot |32 resource samples;1 process instance,31 CPU deltas | finish_accepted=true, incomplete=false |
| Mac |0 resource samples, один `acquisition_failed` footer | incomplete; CPU/RSS missing |

Для наблюдавшегося Hub owner CPU median75.961%/max91.949% одного core,
RSS max54,878,208 bytes; для robot audio CPU median24.020%/max38.016%,
RSS max32,882,688 bytes. CPU n=31, RSS n=32 у каждого. Это process scope,
не весь узел/GPU/уникальная память и не стабильная tail-гарантия.

Hub status:32 ACTIVE snapshots, sampled queue max1, pressure ACTIVE32,
reported cumulative max_tick_gap179.414471ms; first invalid/expiry отсутствуют
в snapshots и final. Это ограниченное невоспроизведение старого reducer stall,
не доказательство его устранения; per-tick distribution отсутствует.

Private trace закрыта без drops:36 data records плюс footer. В ней12 STT results,
две admission/main цепочки и один speech commit/terminal/playback stop. Тексты,
WAV и prompt/profile не публикуются. Качество ответа, точная acoustic latency
и новая physical-motion приёмка этим протоколом не заявляются.

## Что установлено о Mac failure

Наблюдаемый footer содержит только `acquisition_failed`. Исторические stage,
exception enum, elapsed acquisition и target count не сохранены; stderr observer
был направлен в DEVNULL. Конкретный первый exception этого опыта неизвестен.

Офлайн выявлена отдельная доказанная структурная несовместимость:
все шесть accepted717 launchd plists запускают `production_logs.run`.
`run_logged` остаётся logger parent и создаёт worker через Popen;
`mac_owned_processes` включает roots **и** descendants. Даже минимальная здоровая
топология шести logger/worker пар даёт12 processes при cap8. Keep-awake helpers
могут добавить ещё процессы. Это не подсчёт PID, наблюдённых в прерванном опыте.

Независимый reviewer подал синтетические шесть таких пар в настоящий
`mac_owned_processes`, получил12 receipts, затем в настоящий `observer_runner`:
он отказал до resource read/run и записал точно такой же footer. Автор повторил
этот offline repro. Дополнительная fixture в exact v3 runner показала, что
no receipts,9 targets,receipt changed,deadline и API unavailable дают тот же
сохранённый footer. Все process/network/resource calls в fixture заменены или
запрещены. Поэтому topology defect воспроизведён, но утверждать именно его
историческим первым exception только по этому footer нельзя.

Следующая dependency должна явно ограничить coverage compute provider trees
(llm/fast/worker/gateway/vlm), отделить support logger/tunnels/caffeinate по
проверяемым known receipts и сохранить bounded stage/count diagnostics.
Cap8 не поднимается вслепую. Исправление observer/collector сюда не входит;
его владельца и отдельное окно после приёмки назначает ведущий. #26 остаётся открытой.

## Приватные доказательства и повтор вычислений

Roots под `~/reachy-release-backups/`:

| Root | Manifest SHA256 |
|---|---|
| `20261124-baseline02-readiness-001` | `4da25840fff4f62163a45cdc8da8f6d1981554df1b7382ef5556d729c9152902` |
| `20261124-baseline02-runner-001` | `bb46ab08e1836fd2fd786cc0b926ba9f8a8e93750e15e545b0cd55e4ff04769d` |
| `20261124-baseline02-replica-001` | `ea4aa695f68ee23bf0c6d3e059b88456931997df86a0bc793c8dffe3a4c0624d` |

Readiness root содержит exact read-only commands и comparison anchors.
Runner root — reviewed launch/abort, immutable local PID/Mach receipt и console.
Replica root — observer streams/footers, actions/owner events/finals, private
trace/WAV, `baseline-summary.json`, `summary.json`, `static-topology.json`,
оба offline repro и их результаты. Raw evidence в Git не копируется.

Повтор только офлайн, Python≥3.11, из принятого source tree observer:

```sh
EVIDENCE=/Users/notanonenough/reachy-release-backups/20261124-baseline02-replica-001
PYTHONPATH=src python -B "$EVIDENCE/reproduce-mac-topology.py"
PYTHONPATH=src python -B "$EVIDENCE/reproduce-acquisition.py"
PYTHONPATH=src python -B deploy/autonomous/production_baseline.py \
  --candidate 717a6577a9f7c2b3ff6dd22045761866678b37bc \
  --trace "$EVIDENCE/private-trace.jsonl" --status "$EVIDENCE/observer-hub.jsonl" \
  --resources "$EVIDENCE/observer-combined.jsonl" --final "$EVIDENCE/final-bounded.json"
```

Коллектор выдаёт content-free числовые итоги и Mac incomplete. Эти команды не
запускают hardware; запуск новой реплики этим документом не разрешается.
