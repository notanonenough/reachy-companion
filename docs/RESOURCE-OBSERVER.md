# OBSERVE-01: внешний наблюдатель ресурсов и status

Карточка [#28](https://github.com/notanonenough/reachy-companion/issues/28),
потребитель [BASELINE-02](BASELINE-02.md). Это offline-подготовка следующего
измерения. Установленный `stand-2026-11-23.1` / exact
`717a6577a9f7c2b3ff6dd22045761866678b37bc`, его source/config/guards не меняются.
Документ и `--execute` сами по себе не разрешают аппаратное окно.

## Источники, единицы и границы

Один отдельный observer process на узел, максимум 180 ticks с частотой не выше
1Hz, до 8 immutable process instances. Нет catch-up bursts. Один probe ограничен
250ms; acquisition receipts — 3s. JSONL: максимум 2MiB, 1621 records,
64KiB/record. Fixed deadline наблюдателя не продлевает runtime lease.

Linux использует принятый `production_baseline.parse_proc_stat`: CPU cumulative
`(utime+stime)/SC_CLK_TCK`, RSS `pages*SC_PAGE_SIZE`, boot ID и start_ticks.
Оба sysconf берутся на том же узле. Identity проверяется до/после чтения.

Mac использует `proc_pid_rusage(pid,RUSAGE_INFO_V0,buffer)` из libSystem.
Локальные primary SDK headers `sys/resource.h` и `libproc.h` задают ABI;
C fixture с clang сравнивает sizeof/offsets с ctypes: size96, user16,
resident64, start80 на проверенном Mac. RSS — `ri_resident_size` bytes.
Start identity — `ri_proc_start_abstime`, а не PID или округлённое время `ps`.
CPU cumulative — `ri_user_time+ri_system_time` в **Mach absolute ticks**,
умноженные на `mach_timebase_info.numer/denom/1e9`. Это не lifetime `%CPU`.

Первичные Apple XNU источники:
[fill_task_rusage](https://github.com/apple-oss-distributions/xnu/blob/f6217f891ac0bb64f3d375211650a4c1ff8ca1ea/osfmk/kern/bsd_kern.c#L1187-L1219)
копирует task power counters;
[task_power_info_locked](https://github.com/apple-oss-distributions/xnu/blob/f6217f891ac0bb64f3d375211650a4c1ff8ca1ea/osfmk/kern/task.c#L6367-L6393)
получает Mach counters;
[proc_get_rusage](https://github.com/apple-oss-distributions/xnu/blob/f6217f891ac0bb64f3d375211650a4c1ff8ca1ea/bsd/kern/kern_resource.c#L3219-L3277)
не превращает их в nanoseconds перед copyout. Собственный child с 32MiB allocation
и≈0.35s process_time независимо проверяет conversion и RSS. На авторском Mac
numer/denom=125/3: observer delta0.3500798s, child0.350003s, ratio1.000219,
RSS51904512 bytes, identity stable. Это измерение fixture, не worker baseline.
Linux real child проверяется только на Linux; Mac ABI test только на Mac.
Недоступная платформа помечается skipped, а не PASS.

Targets берутся только из известных receipts:

- Hub — точные PID/start_ticks `owner_started` и binding `owner_bound` прежнего
  supervisor. Listener provenance проверяется теми же exact functions до и после
  status GET. Наблюдатель не получает STOP/renew interface.
- Robot — фиксированный unit `reachy-production-audio` MainPID до/после process
  start receipt. При PID0/смене/неизвестной identity acquisition incomplete.
- Mac — существующий `production-control.mac_owned_processes`: fixed launchd
  labels плюс их потомки по PID/PPID. Поэтому launcher не подменяет worker.
  Receipt `process_identity` сверяется повторно, затем immutable Mach identity
  читается до/после каждого sample. Старый `ps lstart` служит только fence
  acquisition receipt, не CPU source или постоянной identity. Его coarse
  resolution не является доказательством отсутствия любой race во время discovery.
  Более8 processes — incomplete, без скрытого усечения или выбора «удобных» PID.

Новый PID не подменяет старый target; нет повторного discovery/reconnect/restart.
Нет чтения command lines/environ/process memory или process text. RSS нескольких
процессов не складывается в unique memory; CPU — scope процессов, не весь узел
и не GPU. `missing/identity_changed/timeout/unsupported/error` никогда не CPU0.

## Format и consumer

Resource rows содержат version/kind/node/host_boot/clock_basis=host_monotonic,
probe_begin/end/at, role enum, PID, process_start_identity/identity_basis,
cumulative cpu_s, rss_bytes, units, sample_state/error_kind enum. Error payloads
и произвольные exception strings не экспортируются. Footer `observer_end`
сохраняет incomplete/reason/records/ticks. Ошибка финальной записи меняет returned
verdict/exit на incomplete даже когда записать footer уже невозможно.

Hub JSONL также содержит status rows: declaration candidate, полный binding
controller/source/session, request begin/end/outcome, existing lease progress/
timing/maxima, pressure phase/queue/ages/limits, last fast/main Job latency,
busy/counters/first diagnostics. GET только local127.0.0.1:8791 с existing token;
никаких новых endpoints. Binding и child listener ownership проверяются перед
и после запроса. Token не выводится. Ответ ограничен256KiB и250ms.

Collector принимает один mixed stream для `--status` и `--resources`; для
нескольких узлов resource JSONL объединяются после known observer exit локально.
Новый consumer группирует distributions по role+PID+host boot+identity basis+
start identity, затем выдаёт coverage узла. Разные workers не смешиваются.
Новый формат с отсутствующим/неполным footer остаётся incomplete даже при
нескольких удачных samples. Legacy Linux `start_ticks` rows по-прежнему читаются,
но completion unknown. Повторный elapsed — тот же snapshot только внутри полного
candidate/controller/source/session binding; новый binding/reset разрывает
сегмент. Latest Job latency и cumulative max не превращаются в call percentiles.

## Воспроизводимая сборка без стенда

Нужен Python≥3.11 проекта. Assembly читает только локальный approved snapshot и
модули этой версии. Проверяет все четыре exact base SHA256, затем делает небольшой
patch: attachment start после ACTIVE; observer finish request за2s до bounded end;
cleanup после owner stop/exit/shutdown;
incomplete observer запрещает acceptance. Existing owner control не дублируется.
Remote supervisor, камера/sampler и terminal helper остаются byte-identical.
Unknown base/hash или изменившийся anchor дают отказ до создания output.

```sh
PYTHONPATH=src python deploy/autonomous/assemble_observer_harness.py \
  --base /Users/notanonenough/reachy-release-backups/20261123-private-trace-harness-approved \
  --output /ABS/PRIVATE/NEW-OBSERVER-SNAPSHOT

PYTHONPATH=src python /ABS/PRIVATE/NEW-OBSERVER-SNAPSHOT/reachy-trace-acceptance.py
PYTHONPATH=src python deploy/autonomous/resource_observer.py --node mac
PYTHONPATH=src:tests python -m unittest test_resource_observer test_observer_integration test_production_baseline -v
```

Без `--execute` оба execution CLI не читают inputs, не вызывают resource/API/
network/process probes. Assembly отдельно читает helpers и записывает заявленный
новый private0700 directory/files0600 + manifest SHA256. Снимок и exact hashes
независимо проверяются до любого hardware окна.

Отдельный regression исполняет actual `observer_runner.main` acquisition→run→
finally для всех трёх узлов с fake known receipts и реальным FinishControl/pipe.
Это проверяет wiring entrypoint, включая Mac service-helper namespace.

Exact approved-base integration tests локально собирают этот snapshot и
исполняют actual start/finally AST с fake transports/processes: normal,
early spawn failure, hanging observer, diskfull, SSH loss. В этих сценариях
используются реальные локальные observer children/control pipes и terminal footer,
а remote transport заменён fixture; заранее готовый footer не подменяет выход. Прежние семь
lifecycle regressions также выполняются против собранных local/remote helpers,
включая logging failure и foreign same-controller listener. На машине без
private approved base эти конкретные tests skipped с явной причиной;
platform readers/consumer/manager tests и Linux child остаются исполнимыми в CI.
Для независимого повтора можно задать `REACHY_APPROVED_HARNESS`.

## Следующее аппаратное окно: только после назначения

1. Ведущий назначает единственного владельца и exact installed717. Проверяются
   hashes собранного snapshot, прежние preflight и known owner receipts.
2. Единственный normal Hub запускает прежний harness. После ACTIVE attachment
   запускает один read-only child на Mac и по одному через SSH на Hub/robot.
   Linux получает ephemeral private helper bundle вне installed source; никакой
   package/config installation. Право renew/STOP остаётся у прежнего supervisor.
3. За2s до обычного bounded trial end supervisor неблокирующе посылает
   `finish\n` по stdin каждого observer child; в finally повторяет idempotent
   request при раннем выходе. Это команда observer, не runtime STOP. Только
   принятие команды самим observer подтверждает finish. Measurement window
   заканчивается на его host-local timestamp; пересёкший границу probe
   отмечается dropped_inflight, прежние ошибки не удаляются.
   При observer error не делать restart/reconnect. Ошибка evidence сохраняется;
   физическая остановка идёт по прежнему authenticated stop → tracked child exit
   → device/Mac shutdown. Затем каждый observer child отдельно graceful wait2s;
   только при неуспехе terminate/wait1s, kill/wait1s и incomplete. Remote terminal
   должен прийти через ещё открытый SSH, разрыв транспорта не равен finish ACK. Logger failure не выбрасывается в owner cleanup.
   EOF/SSH loss даёт unknown/incomplete; remote observer имеет собственный deadline,
   но исчезновение SSH не выдаётся за известный remote exit. Arrival order finish
   и аварийного runtime STOP не гарантируется: ранний stop может честно оставить
   measurement incomplete. Safety STOP не ждёт observer.
4. Проверить три footer, coverage/identities и terminal receipts. Unsupported
   на любом узле блокирует полноту baseline, но не физический STOP. Raw inputs
   остаются private. Первые результаты этой разработки не являются аппаратной
   CPU/RSS статистикой установленного717.

Ограничения: sampling1Hz не видит короткие пики; identity fences не гарантируют
atomic OS snapshot; Mac acquisition coarse receipt limitation указана выше;
нет GPU/host-total/unique-RSS, точной acoustic latency или новых гарантий TTL.
