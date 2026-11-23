# Экосистема Reachy Mini: что переносить в Reachy Companion

Дата среза: **23 ноября 2026**. Статус: исследование для плана; рекомендации не реализованы. Исходный контекст: [REVIEW-NOTES, прежде всего 15 и 20–34](REVIEW-NOTES.md), [действующие интерфейсы](ROBOT-INTERFACES.md), [исследование медиа](LOCAL-MEDIA-RESEARCH.md). Целевая установка — Wireless с сохранённым SDK **1.2.11**, а не последняя версия производителя.

## 1. Решение и границы исследования

Лучший путь — заимствовать отдельные проверяемые компоненты, сохранив шесть логических модулей из пункта 15 и один локальный исполнитель движений. Наиболее полезны: композиция движений Pollen/Sage; синхронизация жестов с фактическим воспроизведением; разделение «услышал речь», «приглушил ответ» и «отменил ответ»; внешние отменяемые задания Hermes/OpenClaw; воспроизводимая диагностика. Установка целого стороннего companion сейчас дала бы второй разговорный цикл, второго владельца приводов и несовместимые зависимости.

**Взять готовым:** небольшой закреплённый набор JSON-движений Pollen с проверкой формата и собственной загрузкой без сети во время жеста; позже — отдельные инструменты просмотра/анализа записей в изолированной среде. **Адаптировать:** арбитр движения, PCM-clock, отмену поколений, агентные шлюзы, потоковый речевой backend. **Отложить:** обновление daemon ради WebRTC/JS, новые зрительные модели и браузерный пульт. **Отклонить как основу первой версии:** старые монолитные voice forks, прямые SDK-tools у внешних агентов, пространственную навигацию, обязательный NeMo/ROS/LiveKit ради одного робота.

Проверялись публичные страницы, метаданные GitHub/Hugging Face, исходники на закреплённых SHA, manifests зависимостей, лицензии/карточки ресурсов и выбранные тесты как текст. Исходники скачивались во временный каталог для чтения; сторонние программы не импортировались и не запускались, приложения и модели не устанавливались, к устройствам не подключались. Проверка JSON ниже — статический анализ данных. Аппаратных, акустических и сетевых замеров здесь **нет**.

Обозначения: **К** — свойство подтверждено прочитанным кодом; **А** — заявление автора/документации; **И** — наш инженерный вывод; **П** — будущая проверка. Наличие теста в репозитории не означает, что он выполнен нами. Дата commit показывает наблюдаемую свежесть выбранной ветки, не качество и не обещание поддержки. `archived=false` также не доказывает активность. Номер версии в manifest не всегда соответствует опубликованному release.

## 2. Краткая карта охвата и первичный отбор

Отправные точки — [официальная галерея приложений](https://pollen-robotics.com/reachy-mini/apps/), [галерея движений](https://pollen-robotics.com/reachy-mini/moves/), HF Spaces/datasets и оригинальные репозитории. На странице moves наблюдались 407 движений из 53 библиотек; страница apps показывала 93 позиции в текущем представлении с JS-фильтром. Это снимок интерфейса, **не полный размер экосистемы** и не число проверенных приложений. Просмотрены 24 адреса исходников: 15 GitHub-репозиториев, 7 Spaces и 2 datasets; глубина проверки различается и указана ниже. Репозиторий SDK включён только как совместимость и источник вынесенных из приложения компонентов.

Первичный фильтр: полезная функция для нашего диалога → доступный исходник → отделимость от чужого владельца оборудования → версия/лицензия/зависимости → проверяемая отмена и задержка. Популярность и эффектность видео не служили критерием принятия.

| Направление | Рассмотренные источники | Результат отбора |
|---|---|---|
| Живой диалог, речевые backend | Pollen Conversation App; HF speech-to-speech; Sage Voice; NVIDIA/brev personal assistant; dwain-barnes local fork; phola Reachy Brain | Первые три — подробная проверка; NVIDIA — образец разделения; старые forks — сравнение и отказ от основы. |
| Фон, жесты, речь и музыка | Conversation `moves.py`; SDK speech tapper/wobbler; Pollen dances code и два datasets; Sage arbiter; TwinPeaksTownie Dancer | Композиция и PCM-clock — приоритет. Dancer — старый просмотрщик, не новый runtime. |
| Перебивание/остановка | Conversation local/server VAD; speech-to-speech CancelScope; Sage InterruptionTracker; Homebody playback/session gates; Claw V2 | Переносить семантику событий и идентичность действий; физическую остановку проверять отдельно. |
| Камера, взгляд, выразительность | Hand Tracker V2; Mime Bot; Sage face/presence; Claw vision; Homebody gesture detection; dimOS blueprint | Получать наблюдения/цели через видеошлюз. Прямое управление трекером и распознавание эмоций человека не брать по умолчанию. |
| Внешние агенты | tobrun Hermes; ai-ag2026 hermes-reachy; Homebody; Reachy Claw; openclaw-embodiment | Homebody и небольшой Hermes WS-plugin — доноры адаптеров. Claw разобран по актуальному и legacy путям. |
| Локально/распределённо/браузер | speech-to-speech LAN; Jetson Claw; Mac Reachy Brain; NVIDIA bot + NAT; Telepresence; Minimal Conversation JS | Выбор узла по возможностям; зависимость от облака/браузера и daemon учитывать явно. |
| Авторинг, воспроизведение, симуляция | Marionette JS и benchmark; Dancer viewer; SDK MuJoCo/Rerun; Sage turn-end; Seeed starter | Офлайн replay и измерительная методика — полезны; чужие скрипты могут двигать робот и не являются read-only. |

Это шире списка в блокноте: дополнительно проверены Homebody после переименования, отдельный Hermes platform plugin, Sage Voice, Mime Bot, Marionette benchmark, браузерные приложения, NVIDIA NeMo/Pipecat и dimOS. Галерейные Radio, Music Quiz, stories, dance-duo и предметные игры не получили глубокий аудит: для первого плана их возможности перекрыты более отделимыми компонентами выше.

## 3. Проверка перспективных реализаций

### 3.1. Pollen Conversation App: основной донор поведения, не совместимое приложение

**К.** Срез `f58eb8f62f9a`, manifest `1.2.0`, Python ≥3.11, **reachy-mini ≥1.11.0**, Apache-2.0. Проверены `moves.py`, `huggingface_realtime.py`, `audio/local_vad.py`, `idle_policy.py`, `main.py`, manifest. `moves.py` организует один поток записи `set_target`, очередь основных движений и состояние listening/speaking; актуальный `main.py` включает wobbling daemon. Новые `start_head_tracking`/`enable_wobbling` не являются возможностями 1.2.11. [Исходники приложения][conversation]

**К.** Listening определяется локальным **ИЛИ** серверным признаком речи. Локальный Silero нужен для ранней физической реакции; в проверенном пути candidate приглушает playback до 0,25, а остановка ожидает server VAD. `_interrupt_playback` помечает response IDs как отброшенные, выключает speaking, при заданном ID отправляет cancel и очищает очередь. Это конкретные механизмы, а не доказательство отсутствия остаточного звука на ALSA. Очереди `output_queue`, `_pending_responses` и команд движения создаются без заданного лимита. Поэтому копировать их как готовый ограниченный runtime нельзя. [Realtime][conversation-realtime], [движения][conversation-moves]

**И.** Перенести: состояния «слушает/говорит/ожидает», отдельную раннюю реакцию движения, очистку старого ответа и последовательность принятия gesture. В нашем модуле «Движение» оставить один writer поверх заводского API; в «Воспроизведении» использовать свои stream ID/generation и подтверждение consumed PCM. Простой локальный выбор idle может выполняться без LLM, но случайный танец из чужой idle-policy не обязан быть уместным в Companion. Применять дозированное дыхание/поворот и настоящие интервалы неподвижности.

**П.** Воспроизвести последовательность local-on → server-on → local-off → server-off, пропажу микрофона и поздние аудиопакеты; движение не возобновляется по одному устаревшему событию. Замерить эффект приглушения на ложные/пропущенные перебивания. Комментарий «~2 ms per 32 ms chunk» в исходнике — оценка автора, не измерение на нашем CM4.

### 3.2. Речь → движение: текущий PTS-wobbler и более старый составной scheduler

**К.** В актуальном SDK `speech_tapper.SwayRollRT` преобразует float32 PCM в небольшие колебания; шаг генерации 50 мс. `HeadWobbler.feed(pcm, play_at_monotonic_ns)` ставит callbacks относительно времени воспроизведения, полученного вызывающей стороной из PTS и задержки sink. `stop/reset` меняют generation и обнуляют offsets. Это привязка к playout, не к приходу токена. Нужны NumPy и GLib/GStreamer для готового scheduler; этих классов в 1.2.11 нет. [Tapper][tapper], [wobbler][wobbler]

**К.** В NVIDIA/brev `bot/services/moves.py` сохранён более самостоятельный менеджер: один primary move плюс speech/tracking offsets, один `set_target` на tick. `processor.py` связывает BotStarted/StoppedSpeaking с поведением; `wobbler.py` — прежняя реализация. Manifest bot требует Python ≥3.13, Pipecat ≥0.0.98, SDK ≥1.2.4; нижняя граница допускает 1.2.11, но не доказывает работу всего набора сегодняшних зависимостей. Лицензия Apache-2.0. [Код demo][nvidia]

**И.** Для Companion наиболее ценно расписание по аудиокурсору, а не конкретная амплитуда качания. [SpeechClock](../src/reachy_companion/speech_clock.py) прямо обозначен как оценка по настенным часам; [Playback](../src/reachy_companion/autonomous/playback.py) уже принимает подтверждённый `consumed_frames`. Адаптер строит offsets из того же PCM, связывает их со `stream_id` и номером sample, применяет их через единый локальный scheduler. GLib не нужно добавлять только ради таймеров, если существующий playback даёт более подходящий clock. Семантический жест внимания/согласия задаётся отдельно от акустического покачивания.

**П.** Одинаковый WAV подать кусками разных размеров и с искусственным jitter; сравнить фазу жестов относительно consumed PCM, паузы и отмену до/после планирования callback. После cancel старые offsets не меняют позу и не запускают возвратный жест без допуска. Фактическое движение и звук сверяются позднее на устройстве. Issue производителя о порче STT при движениях на Wireless — пользовательский A/B-отчёт на других версиях, но достаточный повод включить шум моторов в сценарии, а не увеличивать постоянное idle. [Issue #1334](https://github.com/pollen-robotics/reachy_mini/issues/1334)

### 3.3. Pollen moves: можно брать данные, Companion уже это делает

**К.** Emotion dataset `873ae49f…` и dance dataset `3564295e…` имеют Apache-2.0 в карточках. Это самостоятельные ресурсы: лицензия SDK не лицензирует все 53 библиотеки галереи. В [нашем NOTICE](../src/reachy_companion/assets/NOTICE.txt) уже закреплена **та же** emotion revision; [emotion_library.py](../src/reachy_companion/emotion_library.py) воспроизводит адаптированные ориентации/антенны, без переносов головы, body yaw и звука. Новая работа — отбор жестов, переходы и ограничение повторов, не повторное подключение датасета. [Эмоции][emotions-data], [танцы][dances-data]

Статически проверены реальные `attentive1.json` и `simple_nod.json`: поля `description/time/set_target_data`, одинаковое число времён и кадров, строго возрастающее время; соответственно **215 кадров/4,28 с** и **92 кадра/1,82 с**. В кадрах присутствуют `head`, `antennas`, `body_yaw`, `check_collision`. Парсер `RecordedMove` тега 1.2.11 читает этот основной формат. Это подтверждает структурную переносимость двух файлов, **не безопасность всей библиотеки и не испытанную плавность**. [Парсер 1.2.11][recorded1211]

**И.** Первые кандидаты: укороченный/ослабленный attentive как реакция начала общения, один nod после законченной фразы, спокойное возвращение к текущей опорной позе. Исходный attentive длится больше четырёх секунд — не считать его готовым мгновенным кивком. Не трактовать названия `happy/sad` как распознанную эмоцию человека. Звуковые `.ogg` sidecars первоначально не включать: они конкурируют с TTS и имеют отдельный жизненный цикл.

**К/И.** Python dances library `0.2.1`, Apache-2.0, содержит `DanceMove.evaluate(t)` и `Choreography`, ритмические примитивы с BPM. Зависимость `reachy_mini` не ограничена, поэтому обычная установка способна подтянуть новый SDK. Брать генератор траектории или экспортированные данные с pinned revision; вызов `play_on` переделать в выдачу samples нашему исполнителю. Лицензия библиотеки не даёт прав на коммерческую фонограмму из примера хореографии. [Dances code][dances]

### 3.4. Sage Voice: особенно полезный новый донор чистой логики и replay

**К.** HF Space `c7592c88…`, manifest `0.2.0`, Apache-2.0, Python ≥3.12, **SDK ==1.14.0**, Pipecat Silero ==1.15.0, dances ==0.2.1; опубликованный исходник ссылается на оригинальный `1xabhay/sage-kernel`. Это актуальная отдельная реализация, а не название STT-модели. Проверены `motion/arbiter.py`, `interruption.py`, `turn_end.py`, `clause.py`, `chip.py`, manifest. [Срез Space][sage]

**К.** Arbiter — чистая функция состояния без I/O и потоков: один primary, дополнительные offsets, пределы позы/скорости/ускорения. Подготовка clip сдвигает/масштабирует его в диапазон заранее, чтобы покадровое clipping не уничтожало форму. `InterruptionTracker` различает короткие интервалы аудио между предложениями и весь открытый ответ; `turn_end.py` перебирает пороги тишины на WAV отдельных реплик и считает ошибочные разрезы внутренних пауз. [Арбитр][sage-arbiter], [перебивание][sage-interruption], [калибровка][sage-turn]

**И.** Адаптировать чистый arbiter и методику, не переносить весь Sage kernel. У нас задействовать [motion_runtime](../src/reachy_companion/autonomous/motion_runtime.py), [motion_limits](../src/reachy_companion/motion_limits.py), [expression_player](../src/reachy_companion/expression_player.py); явно преобразовать градусы/радианы и world/body-relative yaw. Новые ограничения не должны неявно ослаблять текущие.

**Что отклонить.** По умолчанию tracker даёт роботу 600 мс речи до автоматического перебивания; для явного stop/отзыва разрешения такое ожидание неприемлемо. Плавное торможение с ненулевым путём не равно требованию «остановить на месте» — политика должна различать обычный переход и отзыв допуска. Комментарии с пилотными числами относятся к прежнему voice bot автора. `chip.py` пишет параметры XMOS и не является готовой read-only диагностикой. Ничего из этого не запускалось.

**П.** На записанных русских репликах сравнить текущий endpointing, 200–1000 мс silence sweep и разумную модель конца реплики: ошибки преждевременного ответа, p95 добавленного ожидания. Для arbiter — replay конкурирующих gaze/idle/speech/gesture, отмены и запрета; ни одного target от отменённого поколения. Для безопасности границ нужен полный анализ между samples, не только проверка нескольких опорных кадров.

### 3.5. Hugging Face speech-to-speech: готовый речевой backend для внешнего узла

**К.** `2cd285679a0c`, manifest `1.1.0`, Python ≥3.11, Apache-2.0. Сервер `/v1/realtime` и отдельные STT/LLM/TTS handlers; `pipeline/cancel_scope.py` имеет generation и discard guard; realtime response handlers разделяют генерацию, аудио и lifecycle. В manifest есть отдельные platform pins для macOS/MLX и Linux/GPU, optional Faster Whisper, Kokoro, WebRTC и другие backend. Это тяжёлый inference stack с Torch/Transformers/ONNX, не замена нашему лёгкому локальному циклу. [Код][s2s], [CancelScope][s2s-cancel], [конфигурация Mac][s2s-mac]

**А.** Официальная инструкция описывает запуск speech engine на компьютере в LAN и conversation app на роботе. Это подтверждает схему размещения; рекламное утверждение о быстроте cascade не является сравнением с нашим Piper/Faster Whisper. [Инструкция HF](https://huggingface.co/blog/local-reachy-mini-conversation)

**И.** Приоритетный отдельный стенд за аудиошлюзом Hub: постоянный вход PCM, события VAD/transcript, поток выхода PCM и cancel. SDK 1.2.11 не нужен серверу; совместимость определяется адаптером PCM/events на Companion. Не сливать существующие отдельные аудио/видео/model gateways в один непрозрачный вызов только ради `/v1/realtime`. В первой версии использовать одну модель диалога, как требует пункт 30. Полный cascade нужен как сравнительный baseline; затем можно оставить только удачные STT/TTS handlers.

**Лицензии/язык.** Apache кода не заменяет проверку весов. [Qwen3-TTS 0.6B CustomVoice](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice) декларирует Apache-2.0 и русский; это кандидат для сравнения с нашим голосом, не принятый выбор. [Distil-large-v3](https://huggingface.co/distil-whisper/distil-large-v3) — MIT, английский ASR: такой default старого local fork не годится как обоснование русской речи. [Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M) имеет Apache-2.0 у весов; доступность нужного языка, голосов, фонемизатора и их лицензий проверяется отдельно. Ревизии конкретных весов и lock окружения фиксируются до испытания; веса здесь не скачивались.

**П.** Сопоставить timestamp первого input chunk, конца речи, transcript, первого текста, первого PCM, первого consumed sample; отдельно cancel и остаток звука. Проверить cancel во время STT/LLM/TTS, reconnect и поздний `response.done`. Само наличие CancelScope не доказывает прерываемость CUDA inference или физического динамика.

### 3.6. Hermes и OpenClaw: брать протокол задания, а не чужой доступ к моторам

**Homebody — предпочтительный донор адаптера. К.** Прежний адрес `Timverhoogt/reachy-mini-hermes` перенаправляется в `Timverhoogt/homebody`; срез `c5c162ce…`, manifest `0.5.54`, Python ≥3.11, SDK ≥1.9.0, Apache-2.0. Зависимости включают sherpa-onnx, ONNX Runtime, OpenCV, websockets и Linux/ESPHome-компоненты. В `homebody/agent_session.py` есть generation-bound request, в `playback_gate.py` — запрет новых producers и учёт операций в полёте перед sleep. Код не держит общий lock на всём непрозрачном SDK-вызове; обычный stop не должен ждать sleep-gate. [Homebody][homebody], [session][homebody-session], [playback gate][homebody-playback]

**К.** В `companion/native_adapters.py` разделены Hermes REST runs и OpenClaw Gateway RPC. Hermes получает `run_id`, читает status/events и вызывает stop конкретного run. OpenClaw проверяет существующий `sessionKey`, отправляет `chat.send` с `idempotencyKey`, фильтрует события по run/session, вызывает `chat.abort` и возвращает **stopping**, а не выдуманное «остановлено». Есть capability handshake и ограниченный event deque. Отдельный HTTP OpenClaw adapter `agent_backends.py` перестраивает payload по allowlist, назначает устойчивый `user` и сохраняет credential на bridge host. Его обычный chat-путь `stream=False`; не путать его с нативным каналом. [Нативные адаптеры][homebody-native], [HTTP adapter][homebody-backends]

**И.** Адаптировать этот узкий слой в шлюз моделей/агентов Hub. Разрешить размещение агента на Mac, Linux/Jetson, Hub или другом совместимом узле; требуются capability probe, лимит задания, progress и подтверждаемая отмена. Агент возвращает текст/предложение действия. Только Companion проверяет допуск, свежесть, границы и выдаёт команду приводу. Компоненты Homebody для детского режима, ESPHome, установщика, своих wake/sleep и другого UI не переносить вместе с адаптером.

Совместимость **агентного API тоже версионная**. [Официальный Hermes API](https://hermes-agent.nousresearch.com/docs/user-guide/features/api-server) описывает runs/status/events/stop; [OpenClaw HTTP](https://docs.openclaw.ai/gateway/openai-http-api) и [Gateway protocol](https://docs.openclaw.ai/gateway/protocol) — разные поверхности. Возможности сегодняшней документации нельзя приписать установленному у пользователя агенту, версия которого в этом исследовании не определялась. Расширенный Homebody `native_discussion` handshake требует специального поддерживаемого контракта, а не любого «OpenAI-compatible» endpoint. Отсутствие feature — явный отказ/упрощённый режим, не обход проверки.

**ai-ag2026/hermes-reachy — маленький альтернативный донор. К.** `704f16eb…`, версия `0.1.0` alpha, MIT, Python ≥3.11, websockets ≥13, без зависимости от SDK на стороне сервера. Plugin регистрирует Hermes platform: `stt/text/interrupt` → MessageEvent, обратно progressive `say` с message/turn ID и отдельные body tool/result. Внешний агент не пишет в моторы. [Plugin][hermes-plugin]

Полезны небольшой контракт и отделение TTS от агента. Но `interrupt` в прочитанном обработчике действует только при непустом тексте, затем полагается на busy-input policy Hermes. Это **не самостоятельная команда физического stop**. В `_current_turn_id` используется последняя turn identity для обхода особенностей очереди Hermes; для нашего адаптера надо проверить, что старые токены не будут ошибочно помечены новым поколением. Additive text edits требуют дедупликации произнесённых фрагментов. Proactive delivery должна проходить отдельное решение Hub о допустимости инициативы. [Adapter][hermes-plugin-adapter]

**tobrun/reachy-mini-hermes-agent — идеи, не готовое заимствование. К.** `89052867…`, последний commit 6 апреля, voice package `0.1.0`, SDK ≥1.2.0, Whisper/httpx; имеется отдельный bridge для жестов и разговорный цикл. В выбранном дереве не найдена лицензия, а API GitHub её не распознал. `reachy_bridge.py` непосредственно вызывает SDK и REST, `capture_image` использует `self._mini.camera.get_frame()`, тогда как проверенный 1.2.11 предоставляет камеру через `media`. Декларация `>=1.2.0` не обеспечивает совместимость всех путей. [Исходник][tobrun]

**П.** Первое задание обоим агентам — разобрать одинаковый записанный trace и указать подтверждённые источниками задержки, без доступа к устройствам. Затем mock-сервис: новый turn, повтор admission, отмена до получения run ID, поздний final, потеря SSE/WS, недоступный агент. Проверить отдельно: «Hub больше не принимает результат», «удалённый run завершился», «динамик/движение остановлены». Это три разных подтверждения. [brains.py](../src/reachy_companion/brains.py) сейчас ждёт полный ответ (`stream=False`) и использует разные правила передачи истории Hermes/OpenClaw; простая замена URL streaming не добавит.

### 3.7. Reachy Claw: обязательное разделение active и legacy

**К.** `suharvest/reachy-claw`, ветка **master**, `c3fc46d8…`, MIT. В manifest активный пакет называется **reachy-voice 0.2.0**, Python ≥3.11, SDK ≥1.8.0. Entry point — `src/reachy_voice`; тестовый путь — `tests/voice`. Старый `legacy/reachy_claw`, root tests и большая часть старого quickstart сохранены для прежних deployments. Поэтому README-команды `reachy-claw` и описания старого OpenClaw backend нельзя выдавать за актуальную установочную инструкцию. [Репозиторий][claw], [manifest][claw-manifest]

**К.** В актуальном `conversation.py` provider-specific работа передана внешнему Realtime V2 gateway, отличаются remote generation completion и application turn lifecycle. В `audio.py` есть диагностика каналов и здоровья audio callback; выбор канала нужен для исключения обратного примешивания reference/raw сигнала к обработанному. `motion.py` содержит отдельный цикл исполнения. Слой speech зависит от vendored wheels **openvoicestream-agent 0.2.0** и **voxedge 0.0.5a0**, заданных через `tool.uv.sources`; это не обычная переносимая зависимость PyPI. Содержимое wheel и все транзитивные лицензии этим аудитом не проверены: готовое внедрение runtime не рекомендовано. [Активный код][claw-active]

**А, не наш замер.** README приводит на Jetson Orin NX около 50 мс ASR TTFT и 60 мс TTS TTFT, сумму ~110 мс и отдельно typical voice-to-voice <1 с с 2B. Заголовок «sub-200ms» нельзя превращать в полную задержку русскоязычного диалога: не указаны единый корпус, p95/p99, endpointing и остаток после cancel; указанные Paraformer/Matcha presets ориентированы на zh/en. [Таблица автора][claw]

**И.** Адаптировать диагностику channel/callback health и разделение «генерация завершена / воспроизведение завершено», рассмотреть provider-neutral gateway как альтернативный стенд. Старую OpenClaw интеграцию использовать лишь как историческое сравнение с Homebody. Не переносить её LLM regex stop в русский управляющий путь; правила пункта 31 сохраняются. В vision stack не импортировать автоматически ArcFace/SCRFD-веса: [InsightFace](https://github.com/deepinsight/insightface#license) различает MIT-код и ограничения pretrained models на некоммерческие исследования. Для Companion пока нужен свежий gaze target, а не база идентичностей и оценка эмоций лица.

### 3.8. Зрение и браузерные приложения: полезные источники наблюдений, но не второй контроллер

| Кандидат | Проверка и применимость | Решение для Companion |
|---|---|---|
| **Hand Tracker V2**, официальный Space | `1024dd10…`, `0.1.0`; Python ≥3.10, незакреплённый SDK, `reachy-mini-toolbox[vision]>=1.1.2`, MediaPipe в коде. Читает `media.get_frame`, вычисляет управление, вызывает `set_target`; лицензия не указана в полученной карточке/дереве. [Источник][hand] | Адаптировать концепцию: landmarks → target с frame ID/TTL. Исполнение только нашим локальным модулем. Для прямого копирования сначала прояснить лицензию и конкретные веса; отсутствие SDK bound не доказывает поддержку 1.2.11. |
| **Mime Bot**, RemiFabre | `20b6709a…`; в браузере MediaPipe Tasks Vision **0.10.35**, геометрия головы и blendshapes → голова/антенны, калибровочные offsets и clamp. Некоторые комментарии вверху старее реально реализованного FaceLandmarker. Отдельной лицензии приложения/загружаемого `.task` в просмотренных материалах не установлено. [Код][mime] | P2: инструмент создания выразительных кривых или наблюдения за собственной мимикой. Не выдавать blendshape за психологическую эмоцию. Камера браузера и камера робота — разные источники. Чужие углы и связку body_yaw=head_yaw не переносить в нашу кинематику без проверки. |
| **Sage face/presence, Homebody gesture detection** | Разделяют восприятие и поведение; Homebody notices указывают источник HaGRID ONNX и Apache-лицензию исходного приложения. Это provenance автора, не наша полная проверка прав каждого веса. [Sage][sage], [notices][homebody-notices] | P2: повторное подтверждение жеста, cooldown и потеря цели полезны. Реальные модели сначала сверить с исходными карточками/хешами; человек/рука должны давать событие, а не команду wake/движение напрямую. |
| **Telepresence / Emotions / Minimal Conversation JS** | Официальные/авторские Spaces; Minimal pin JS SDK **1.11.0**, Marionette — **1.8.0-rc1-main.dbe26af**. OAuth/relay/WebRTC, camera/audio UI; minimal показывает realtime events в браузерном клиенте. Лицензии этих приложений не объявлены в проверенных карточках/manifest. [Telepresence][telepresence], [Emotions UI][emotions-ui], [JS conversation][minimal] | P2: референс панели/операторского теста после отдельного решения об SDK. Современный control/media channel не считать доступным на 1.2.11. В браузере throttling/background tab и разрыв сети требуют локального watchdog; вкладка не владеет безопасностью. |
| **Reachy × dimOS blueprint** | `e46eadd8…`, MIT-код; mono depth на Mac/DGX, RGB-D+кинематика, spatial memory/Rerun; также дополнительная мобильная база и L515. Часть результата требует собственного fork dimOS и отдельных моделей. [Источник][dimos] | Отложить платформу: у нас стационарный робот без этих исполнителей. Взять принцип связывания кадра с позой и учёта старения пространственного наблюдения. Отдельно проверять лицензии DepthPro/других весов при реальной задаче. |

На Wireless detector можно запускать на Pi при доказанной нагрузке или на другом узле через видеошлюз. На Lite daemon и физические USB media находятся на хосте; тест «работает на laptop Lite» ничего не говорит о CM4 и заводском camera socket Wireless. Транспорт выбирается по действующим возможностям. Адаптер обязан передавать размер/crop/scale, время получения кадра, ID и доступность; [person_follow](../src/reachy_companion/autonomous/person_follow.py) получает цель после этих проверок. Компенсация движения камеры и TTL нужны независимо от нейросети.

### 3.9. Отладка, авторинг и симуляция

**Marionette JS. К.** `7798da60…` содержит запись/воспроизведение и, что полезнее для плана, `lib/benchmark.js`, scripts построения отчётов и сравнения Python/JS. Benchmark создаёт аналитическую траекторию антенн (медленный синус → hold → быстрый синус), чтобы отделить качество исполнения от ошибки записи. Это заготовка методики, не опубликованная гарантия задержки. Готовый JS runtime зависит от более нового daemon; app license не установлена. [Space][marionette], [benchmark][marionette-bench]

**И.** Сделать в будущем свой режим replay поверх единого исполнителя: заданная траектория, отправленные targets, наблюдённые poses, PCM и события в общей временной шкале. Эталонную форму можно описать самостоятельно; чужой код копировать после уточнения лицензии. Скрипты `wireless_*`/benchmark могут посылать движения и подключаться к устройству — в исследовании они только читались. Запись движения с последующим replay не заменяет запись всего диалогового сеанса из пункта 33.

**Rerun/MuJoCo. К.** В SDK **v1.2.11** уже есть `utils/rerun.py` с камерой, суставами и временными метками; это более близкий старт, чем перенос нынешнего просмотрщика. Rerun-компонент SDK — Apache-2.0; пакет Rerun, URDF/mesh и другие ресурсы закреплять отдельно. Просмотрщик должен читать наш trace/telemetry без создания конкурирующего writer. MuJoCo — официальный путь simulation, доступный через SDK extra; нынешняя документация описывает больше функций, чем старый тег. [Rerun 1.2.11][rerun1211], [симуляция](https://huggingface.co/docs/reachy_mini/en/platforms/simulation/get_started)

**И/П.** Три уровня проверки: (1) детерминированный offline event replay с mock-исполнителем и виртуальными часами; (2) MuJoCo для геометрии/переходов/протокола; (3) позже Wireless для акустики, механики, CPU и Wi-Fi. Симуляция без XMOS не проверяет AEC, шум сервоприводов, фактический ALSA drain/drop и end-to-end latency. Сохранение `.rrd`/графиков — диагностический экспорт, не основной формат S3-архива. [replay.py](../src/reachy_companion/replay.py) сейчас воспроизводит ответы, а не полный сенсомоторный сеанс.

**TwinPeaksTownie Dancer.** `a66f6724…`, commit октября **2025**, README заявляет Apache-2.0, отдельный LICENSE в скачанном дереве не найден; viewer/choreography полезны как ранний пример, но до копирования нужен нормальный license provenance. Не путать этот репозиторий с нынешним `reachy-dance-duo` в галерее. Для нового scheduler предпочтительнее живые Pollen/Sage. [Источник][dancer]

### 3.10. Остальные варианты: почему не брать целиком

| Решение | Проверенные ограничения | Вывод |
|---|---|---|
| **dwain-barnes local conversation fork** | Commit `77ba9b6e…` от 22.12.2025; package 0.1.0, Apache-2.0, SDK ≥1.2.3rc1, FastRTC, prerelease Gradio `5.50.1.dev1`, Torch/Transformers; defaults Distil-Whisper/Kokoro, опциональный Ultralytics. [Источник][local-fork] | Старый local pipeline; нижняя граница включает 1.2.11, но отсутствие верхних pins и свежих проверок не даёт воспроизводимого окружения. Предпочесть поддерживаемый HF backend; русского качества из README не следует. |
| **phola Reachy Brain** | `7223ba06…`, апрель 2026; alpha, MLX/Mac, Whisper/Gemma/Kokoro, README заявляет MIT и ~3 с turnaround, полноценный LICENSE не найден. [Источник][brain] | Подтверждает полезность Mac как отдельного узла. Цифры автора без сравнимого протокола; не готовая замена текущему Mac worker и не доказательство русского STT/TTS. |
| **NVIDIA/brev personal assistant** | `70b2a614…` от 30.12.2025, Apache-2.0; Python manifest ≥3.13 при более общем README ≥3.10; отдельные bot/NAT/daemon, ElevenLabs и NVIDIA API в демо. [Источник][nvidia] | Брать только scheduler/frame adapter или схему разделения. Demo не целиком local и не обоснование добавлять несколько LLM/router вопреки пункту 30. |
| **openclaw-embodiment** | `1c07bd40…`, package 2.2.0, Python ≥3.9; LICENSE с текстом Apache-2.0, GitHub SPDX `NOASSERTION`; точные старые pins NumPy 1.26.4, OpenCV 4.10, Pydantic 2.9, BLE/TFLite. [Источник][embodiment] | HAL/регистрация capabilities полезны как сравнение, но много нерелевантных устройств и конфликт с нашим vision `numpy>=2`. Отдельно согласовать attribution перед копированием; не внедрять SDK ради абстракции. |
| **Seeed reachy-mini-starter** | `acc5e392…`, январь 2026, MIT; README помечает ROS2 функции как planned. [Источник][starter] | Не считать таблицу планов реализованным ROS2 transport. Отложить до необходимости реальной ROS-экосистемы; для наших шести модулей дополнительный ROS graph не обоснован. |

## 4. Совместимость: приложение, алгоритм и ресурс — разные проверки

| Кандидат | SDK 1.2.11 | Wireless / Lite | Зависимости и лицензия, влияющие на решение |
|---|---|---|---|
| Два проверенных Pollen JSON | Формат совместим статически; полный playback не испытан | Геометрия общая; шум/динамика проверяются отдельно | Apache-2.0 карточек; offline cache, свой manifest. |
| Dances 0.2.1 | `Move/evaluate` — кандидат; unbounded SDK dependency не принимать | На любом узле генерировать samples, локально исполнять | Apache-2.0 кода, лицензия музыки отдельна. |
| Conversation 1.2.0 | **Нет как целое**, требует ≥1.11.0 | Новые API обоих вариантов не равны старому Wireless | Python ≥3.11, mcp 2.x, OpenAI client 2.28; лицензионно Apache-2.0. |
| Tapper/PTS-wobbler current | Только перенос алгоритма/clock adapter | GLib/PTS и ALSA нужно связать с фактическим backend | Apache-2.0 SDK; NumPy; готовый scheduler требует GI. |
| Sage 0.2.0 | **Нет как целое**, ==1.14.0 | Чистый arbiter отделим; Pipecat окружение отдельно | Python ≥3.12, Pipecat ==1.15; Apache-2.0. |
| Homebody 0.5.54 | **Нет как целое**, ≥1.9.0 | Bridge на внешнем узле переносим; robot lifecycle — отдельный адаптер | Apache-2.0 плюс MPL-2.0/BSD JS notices и отдельно модели/звуки. |
| Hermes WS plugin | Не зависит от SDK; клиент ещё нужен | Текстовый endpoint одинаков для обоих | MIT, Python ≥3.11/websockets; версия Hermes plugin API должна быть закреплена. |
| tobrun 0.1.0 | Range допускает; конкретный camera путь несовместим | Авто media/animation не подтверждены на нашей установке | Неустановленная лицензия; Whisper и optional SDK extras. |
| Reachy Claw active 0.2.0 | **Нет как целое**, ≥1.8.0 | Jetson/CM4 path и Lite требуют разных media решений | MIT wrapper; два vendored wheels и веса пока не очищены для переноса. |
| HF speech-to-speech 1.1.0 | Внешний backend SDK-независим | Оба через наш PCM/events adapter | Apache-2.0 кода; платформа, native wheels и лицензии каждой модели отдельно. |
| JS apps/Marionette | **Не считать совместимыми** | Нужен поддерживаемый daemon/relay на robot или Lite host | Новые JS SDK pins; лицензии app code не установлены. |
| Rerun/MuJoCo тега 1.2.11 | Версионный baseline есть | На рабочей станции; не акустическая модель Wireless | Закрепить extras/ресурсы; current viewer API не смешивать со старым SDK. |

«Совместимо статически» означает обнаруженные поля/API и отсутствие очевидного ограничения, а не успешный запуск. Ни один dependency resolver в исследовании не запускался. Системные GStreamer/GI, Python ABI, NumPy, ONNX и wheels aarch64/macOS требуют отдельной матрицы окружений. Для современного Pipecat есть [issue конфликта onnxruntime с SDK 1.10](https://github.com/pollen-robotics/reachy_mini/issues/1493); его нельзя приписывать 1.2.11, но он показывает, почему shared app venv и `pip install latest` не годятся как стратегия интеграции.

**Ресурсы учитываются отдельно от кода.** Для каждого переносимого артефакта нужны URL+revision+hash, автор/лицензия, NOTICE, перечень изменений, runtime-зависимости и язык. У Homebody проверен [THIRD_PARTY_NOTICES][homebody-notices]: он перечисляет в том числе MPL-2.0 `gstwebrtc-api.js`, BSD adapter и происхождение моделей. Это не разрешение копировать весь assets-каталог под одной Apache-лицензией. Для Spaces без явной лицензии пока брать идею/формат и писать адаптер самостоятельно. Публичный доступ и официальный автор не заменяют лицензию.

## 5. Размещение и минимальный общий адаптер

Не закреплять агента за VPS или Mac. Размещение выбирается независимо для распознавания, TTS, зрения и агента; локальный исполнитель и контроль допуска остаются рядом с оборудованием. Это логические границы, а не требование к числу процессов.

| Схема | Что даёт | Где измерять/что не предполагать |
|---|---|---|
| Wireless I/O + Hub routing + Mac inference/agents | Ближе к сохранённой установке, MLX и имеющийся worker | Два сетевых плеча, resampling, очередь Hub и shared нагрузка Mac; «локально» не значит внутри робота. |
| Wireless I/O + Hub + Linux/Jetson/GPU backend | Возможность взять HF/Claw GPU handlers | Наличие aarch64/CUDA wheels и RAM; Orin NX цифры не переносить на Pi/Mac. |
| Inference/agent на Hub | Меньше один сетевой переход | Только если latency/RSS под нагрузкой укладываются; stop/control не должны ждать inference. |
| Всё приложение на Wireless | Нет LAN между локальным VAD и реакцией | Дешёвые события/idle вероятны; полный Torch/LLM stack не принят без измерений памяти, тепла и аудио. |
| Lite + daemon/media на ноутбуке | Удобен офлайн стенд и доступ к мощному хосту | USB/драйверы и локальный звук отличаются от Wireless GStreamer socket/ALSA. |
| Удалённый агент или GPU/Space | Возможность вынести дорогую работу, независимый upgrade | WAN RTT, cold start, reconnect, внешний service contract; локальный lease и stop действуют без ответа сети. |
| Браузер JS + новый daemon | Удобный операторский/авторский интерфейс | Нужно отдельное решение об обновлении; background tab, autoplay, RTC buffering и relay входят в измерение. |

Предлагаемый **контракт адаптера для плана**, не существующий API: capabilities (`stream_input/output`, `cancel_scope`, `session_resume`, media formats, model/SDK revision), `submit(session, request, generation, deadline)`, события `accepted/partial/completed/failed`, `cancel(request)` с отдельными `cancel_requested/cancel_confirmed/cancel_unknown`. Результат содержит идентичность исходного задания и, для зрения, кадра. Агент не получает generic motor SDK; body tool преобразуется в ограниченное предложение `gesture/look`, которое проходит Hub и локальный исполнитель.

Для звука `generation_finished`, `all_audio_received`, `written` и `consumed` — разные состояния. Для движения `command_accepted`, `target_sent`, `present_pose` и `stopped_confirmed` тоже различны. Потеря HTTP/WS не является подтверждённой отменой. После reconnect новый epoch не принимает старые media/results; retries используют idempotency и точный scope. Native Hermes/OpenClaw handshakes дают возможность проверить реальное наличие cancel, тогда как `chat/completions` сам по себе такого контракта не гарантирует.

## 6. Конкретный приоритетный перенос

P0 — фундамент до интеграции внешних runtime; P1 — первые отдельные прототипы; P2 — после измеримого выигрыша P1. Ниже «проверка» — минимальный следующий эксперимент; в этом исследовании он не выполнялся.

| Приоритет / решение | Компонент Companion | Работа адаптера | Минимальная проверка результата | Открытый вопрос |
|---|---|---|---|---|
| **P0: адаптировать единое владение и generation** из Pollen/Sage/Homebody | [stock_motion_adapter](../src/reachy_companion/autonomous/stock_motion_adapter.py), [actuator_guard](../src/reachy_companion/autonomous/actuator_guard.py), [playback](../src/reachy_companion/autonomous/playback.py), будущий локальный scheduler | Перевести gaze/idle/gesture/speech в предложения одному writer; общий admission, независимый отзыв, terminal receipt | Offline replay: speech+gaze+idle, затем запрет, опоздавший target и reboot epoch. Ноль команд старого владельца; неопределённый stop остаётся unknown | Какая область hold/stop у фоновых движений, какие подтверждения реально даёт daemon 1.2.11? |
| **P1: адаптировать PCM-clock и выражение речи** из wobbler | [speech_motion](../src/reachy_companion/speech_motion.py), [speech_clock](../src/reachy_companion/speech_clock.py), [Playback](../src/reachy_companion/autonomous/playback.py), [motion_runtime](../src/reachy_companion/autonomous/motion_runtime.py) | PCM → offsets с sample index; локальное расписание от consumed cursor; epoch сбрасывает все callbacks; ограничить амплитуды | Один WAV: разные chunk sizes, задержка/пауза, cancel. Сравнить фазовую ошибку и устаревшие cues с текущим clock; позднее звук+видео физического жеста | Какая частота/джиттер writer допустимы на CM4, насколько моторы ухудшают русское STT? |
| **P1: взять три подготовленных жеста Pollen** | [emotion_library](../src/reachy_companion/emotion_library.py), [assets/NOTICE](../src/reachy_companion/assets/NOTICE.txt), [expression_player](../src/reachy_companion/expression_player.py) | Продолжить текущий pinned subset; offline crop/scale и manifest; без sidecar audio, без скачивания на пути исполнения | Переход из ненулевой позы, отмена в середине и повтор; валидные времена/матрицы/границы, неуказанные оси сохранены; сравнить узнаваемость/плавность | Сколько данных оригинального 6DoF оставить, где проходит отдельная проверка кинематики и скорости? |
| **P1: адаптировать раздельные speech/turn/interruption события** | [barge_in](../src/reachy_companion/barge_in.py), [barge_candidate](../src/reachy_companion/barge_candidate.py), [audio_peer](../src/reachy_companion/autonomous/audio_peer.py), [runtime](../src/reachy_companion/autonomous/runtime.py) | Ранний listening gate; optional duck; точный stop без grace period; discard old audio и таймаут stale VAD | Корпус: собственный TTS, шум/моторы, реальное перебивание, пауза между предложениями, цитата «хватит»; отдельные FP/FN и stop-tail | Нужен ли Silero сверх XMOS/текущего VAD, какую долю ложного duck допустим? |
| **P1: сравнить HF speech-to-speech как внешний backend** | [voice_chain](../src/reachy_companion/autonomous/voice_chain.py), [speech_adapter](../src/reachy_companion/autonomous/speech_adapter.py), будущие аудио/model gateways | PCM streaming/events/cancel; одна модель; сопоставить форматы и clocks; сохранить наши разрешения и playback | 20 одинаковых русских реплик + отмены на каждой стадии; сравнить WER/качество голоса, p50/p95 до слышимого слова и CPU/RSS с текущим worker | Выбор STT/TTS/весов, холодный старт, Mac против GPU; достаточно ли частичных результатов? |
| **P1: адаптировать Hermes/OpenClaw native runs** из Homebody; WS-plugin как резерв | [brains](../src/reachy_companion/brains.py), [gateway](../src/reachy_companion/autonomous/gateway.py), [workflows](../src/reachy_companion/autonomous/workflows.py) | Раздельный endpoint/capability profile; request/run/session identity, cancel и нормализованные события; tool requests → Hub | Одинаковый trace-analysis task против обычной модели; затем mock late final/duplicate/cancel/disconnect. Измерить first useful text и terminal cancel; отсутствие старого озвучивания | Точные версии установленных агентов, поддерживаемые native методы и польза памяти/процедур относительно модели? |
| **P1: адаптировать offline replay/метрики** из Sage/Marionette/Rerun | [replay](../src/reachy_companion/replay.py), [control_diagnostics](../src/reachy_companion/control_diagnostics.py), [production_logs](../src/reachy_companion/production_logs.py), модуль записи п.33 | Один trace schema с source/receipt/playout clocks и пропусками; ограниченный recorder; exporter Rerun отдельно; playback по умолчанию mock | Воспроизвести один сбой детерминированно; потерять/переставить события; замедлить S3. Видны пропуски, основной цикл не блокируется | Какой trace канонический; retention/лимит диска; лицензия Marionette для прямого кода? |
| **P2: адаптировать vision target providers** из Hand Tracker/Sage/Mime | [camera_sensor](../src/reachy_companion/autonomous/camera_sensor.py), [video_adapter](../src/reachy_companion/autonomous/video_adapter.py), [person_follow](../src/reachy_companion/autonomous/person_follow.py) | Bounding box/landmarks → нормализованная цель с frame ID/TTL; единый camera producer; motor commands только scheduler | Запись головы в движении, лицо потеряно/перекрыто, две цели и задержанный кадр. Ноль движений по stale; сравнить error/jitter и ресурсы | Лицензии конкретных моделей, размещение detector и правила выбора собеседника? |
| **P2: отдельный браузерный/симуляционный стенд** | [control_page](../src/reachy_companion/control_page.py), [control_diagnostics](../src/reachy_companion/control_diagnostics.py) | Read-only trace viewer сначала; управление — только через наш admission. MuJoCo pin 1.2.11 отдельно от новых JS apps | Вкладка закрыта/заморожена, другой controller, reconnect; тесты переходов в симе без акустических выводов | Обновлять SDK или сохранять 1.2.11; нужен ли вообще новый RTC transport? |

## 7. Как оценить результат, не перепутав демонстрацию с измерением

Имеющаяся доказательная база:

| Свидетельство | Что действительно известно | Что из него не следует |
|---|---|---|
| Статический разбор двух JSON Pollen | Число кадров, длительность, монотонность времени и совпадение основных полей с reader 1.2.11 | Плавность/безопасность всех движений, отсутствие столкновений, hardware compatibility целиком |
| PTS + generation в wobbler, discard IDs в Conversation | Механизм есть в выбранном коде | Нулевой audiovisual skew и остановка динамика в заданное время |
| Claw «50+60 мс», phola «~3 с», HF «fast cascade» | Заявления авторов, разные модели/узлы/границы замера | Сравнительный рейтинг и цифры для русского Companion |
| Sage pilot numbers / comments, Wireless issue #1334 | Описания опытов авторов, полезные гипотезы и стресс-сценарии | Наша репликация; универсальный порог VAD/600 мс или диагноз нашего XMOS |
| Unit tests/benchmark scripts в донорах | Существуют сценарии, которые можно адаптировать | Пройденный запуск на наших версиях и оборудовании |

Конкретные образцы прочитанных тестов: [Pollen head_wobbler](https://github.com/pollen-robotics/reachy_mini/blob/0ce74800cd496316ec08802623e77e9875d3f295/tests/unit_tests/test_head_wobbler.py) подменяет GLib timeout записью расписания; [Homebody playback_failed_suspend](https://github.com/Timverhoogt/homebody/blob/c5c162ce8b708bba7703a396eb7c14ab2810bad2/tests/test_playback_failed_suspend.py) моделирует зависший push, позднее поступление PCM, неуспешную очистку и отказ возобновления. Эти сценарии подходят для будущего адаптера, но не подменяют физические измерения.

Следующий этап начинать с замороженного baseline из `deploy/current`, версиями ОС/daemon/SDK/audio firmware и конфигурацией выбранного исполнителя. Записать один корпус речи/шума/кадров и одинаковые сценарии; при сравнении менять один компонент. Начальные 20 реплик — smoke-набор, не достаточная статистика качества. Для устойчивого вывода увеличивать корпус и число повторений, указывать знаменатель ошибок и доверительные интервалы.

Измерять: capture → Hub receive → backend receive → VAD/end-of-turn → transcript → first useful text → first PCM → write → consumed; для жеста — request/target/present pose; для stop — request/локальный revoke/последний consumed sample/последнее допустимое движение. Межмашинные часы требуют синхронизации и оценки её погрешности; нельзя вычитать произвольные monotonic clocks разных узлов. Для playback держать sample cursor; wall clock нужен для связывания журналов, не как единственное доказательство звучания.

По каждому этапу p50/p95/p99, max и N; отдельно warm/cold, пропуски, backlog, ложные срабатывания, WER, CPU/RSS, длительность stop-tail. Проверять при одновременных аудио, видео и движении, медленном backend, разрыве сети, повторной доставке и рестарте. Численные бюджеты времени/ресурсов определить до испытания; этот отчёт не выдаёт их за измеренные. Строгие инварианты уже определены: ноль исполнительных команд от отозванного поколения, ноль скрытого второго writer, отсутствие ложного подтверждения stop, явные stale/unavailable/gaps.

Открытые вопросы перед реализацией: (1) остаётся ли 1.2.11 или планируется отдельный upgrade; (2) точные capabilities/версии внешних агентов; (3) какой PCM clock станет каноническим; (4) выбранные русские STT/TTS и лицензии весов; (5) владелец общей камеры/микрофона и DSP-настроек; (6) способ подтверждения моторной остановки; (7) лицензии выбранных Spaces; (8) аппаратные бюджеты и критерий выигрыша. Эти неизвестные не мешают сначала сделать offline contract/replay и небольшой импорт движений.

## 8. Реестр проверенных срезов и первичных источников

Ссылки ниже закреплены на SHA. Для GitHub указана дата commit выбранной default branch, а не `updated_at`/звёзды; у HF — дата `lastModified` API. Для каждой группы прочитаны manifest/README и названные выше исполняемые файлы; глубокой проверки всех модулей/весов не проводилось. Лицензии в таблице — найденные декларации, не автоматическое разрешение на все вложенные ресурсы.

| Источник | Проверенный SHA / версия manifest | Дата среза источника | Лицензия / оговорка |
|---|---|---|---|
| [pollen-robotics/reachy_mini_conversation_app][conversation] | `f58eb8f62f9a`; 1.2.0 | 2026-11-19 | Apache-2.0 |
| [huggingface/speech-to-speech][s2s] | `2cd285679a0c`; 1.1.0 | 2026-11-23 | Apache-2.0 |
| [Timverhoogt/homebody][homebody] | `c5c162ce8b70`; 0.5.54 | 2026-10-28 | Apache-2.0 + third-party notices |
| [ai-ag2026/hermes-reachy][hermes-plugin] | `704f16eb7c8e`; 0.1.0 alpha | 2026-07-06 | MIT |
| [tobrun/reachy-mini-hermes-agent][tobrun] | `89052867a29a`; voice 0.1.0 | 2026-04-06 | не установлена |
| [suharvest/reachy-claw][claw] | `c3fc46d8bcd4`; active reachy-voice 0.2.0 | 2026-07-28 | MIT wrapper; wheels отдельно |
| [pollen-robotics/reachy_mini_dances_library][dances] | `6808a976d3dd`; 0.2.1 | 2026-11-16 | Apache-2.0 |
| [brevdev/reachy-personal-assistant][nvidia] | `70b2a614bf3a`; bot 0.1.0 | 2025-12-30 | Apache-2.0 |
| [dwain-barnes/reachy_mini_conversation_app_local][local-fork] | `77ba9b6e1843`; 0.1.0 | 2025-12-22 | Apache-2.0 |
| [phola/reachy-brain][brain] | `7223ba062187`; alpha, SHA | 2026-04-06 | MIT в README; LICENSE не найден |
| [TwinPeaksTownie/reachy_mini_dancer][dancer] | `a66f6724b940`; SHA | 2025-10-28 | Apache-2.0 в README; LICENSE не найден |
| [mmartoccia/openclaw-embodiment][embodiment] | `1c07bd40471a`; 2.2.0 | 2026-03-06 | текст Apache-2.0; SPDX NOASSERTION |
| [Seeed-Projects/reachy-mini-starter][starter] | `acc5e392e586`; SHA | 2026-01-08 | MIT |
| [chaotic-curiosity-io/reachy-dimos-blueprint][dimos] | `e46eadd8e561`; SHA | 2026-10-08 | MIT кода; модели отдельно |
| [pollen-robotics/reachy_mini][sdk-current] | `0ce74800cd49`; main, не 1.2.11 | 2026-11-23 | Apache-2.0 |
| [sabhay22/reachy_sage_voice][sage] | `c7592c88832f`; 0.2.0 | 2026-11-17 | Apache-2.0 |
| [pollen-robotics/marionette-js][marionette] | `7798da60a5cd`; SHA; JS SDK prerelease pin | 2026-07-07 | не установлена для приложения |
| [tfrere/minimal-conversation][minimal] | `31a60471d3c0`; 0.1.0; JS SDK 1.11.0 | 2026-10-06 | не установлена для приложения |
| [pollen-robotics/hand_tracker_v2][hand] | `1024dd103fa4`; 0.1.0 | 2026-05-12 | не установлена для приложения/весов |
| [RemiFabre/mime_bot][mime] | `20b6709abd42`; SHA; MediaPipe 0.10.35 | 2026-10-23 | не установлена для приложения/весов |
| [pollen-robotics/emotions][emotions-ui] | `c5f4e20db5f3`; SHA | 2026-10-06 | не установлена для приложения |
| [pollen-robotics/telepresence][telepresence] | `30b19c6d1f74`; SHA | 2026-10-06 | не установлена для приложения |
| [pollen-robotics/reachy-mini-emotions-library][emotions-data] | `873ae49f0b89`; JSON/OGG, revision | 2026-07-07 | Apache-2.0 карточки |
| [pollen-robotics/reachy-mini-dances-library][dances-data] | `3564295e72d4`; JSON, revision | 2026-07-03 | Apache-2.0 карточки |

Дополнительные первичные источники: [SDK 1.2.11](https://pypi.org/project/reachy-mini/1.2.11/), [производитель о media stack](https://huggingface.co/blog/pollen-robotics/reachy-mini-media-stack), [производитель о новых версиях Conversation](https://github.com/pollen-robotics/reachy_mini_conversation_app/releases), [оригинальный Sage kernel](https://github.com/1xabhay/sage-kernel/tree/main/devices/reachy-mini/apps/reachy_sage_voice). Последние страницы динамические; свойства кода в отчёте привязаны к SHA из таблицы. Ни один из 15 проверенных GitHub-репозиториев API не пометил archived; более старые commits обозначены в отборе как старые снимки, а не как формально закрытые проекты.

[conversation]: https://github.com/pollen-robotics/reachy_mini_conversation_app/tree/f58eb8f62f9a4e334411a477d91267c377657d0a
[s2s]: https://github.com/huggingface/speech-to-speech/tree/2cd285679a0c9eddcd08143d783a07da726b433a
[homebody]: https://github.com/Timverhoogt/homebody/tree/c5c162ce8b708bba7703a396eb7c14ab2810bad2
[hermes-plugin]: https://github.com/ai-ag2026/hermes-reachy/tree/704f16eb7c8e551ce43e54a8492dedfb66544a25
[tobrun]: https://github.com/tobrun/reachy-mini-hermes-agent/tree/89052867a29a9be2bca9f91e216efdd7c54e38d2
[claw]: https://github.com/suharvest/reachy-claw/tree/c3fc46d8bcd4510e916d48f738e5039f66b02230
[dances]: https://github.com/pollen-robotics/reachy_mini_dances_library/tree/6808a976d3ddc11952ece67eb2403934fbb62af9
[nvidia]: https://github.com/brevdev/reachy-personal-assistant/tree/70b2a614bf3a82e8687db87b9f312676d43bba59
[local-fork]: https://github.com/dwain-barnes/reachy_mini_conversation_app_local/tree/77ba9b6e18430fc67121023619c40541bc2e8a8d
[brain]: https://github.com/phola/reachy-brain/tree/7223ba06218787ccdfdb1b22ca1c0c403c8fa3ae
[dancer]: https://github.com/TwinPeaksTownie/reachy_mini_dancer/tree/a66f6724b940465658447d3c53b9e46fa0ab4e9e
[embodiment]: https://github.com/mmartoccia/openclaw-embodiment/tree/1c07bd40471a8f5164c0e2e3e1c1e3cd64fe3bd7
[starter]: https://github.com/Seeed-Projects/reachy-mini-starter/tree/acc5e392e586d69000be7a908d82b7a3d5798d30
[dimos]: https://github.com/chaotic-curiosity-io/reachy-dimos-blueprint/tree/e46eadd8e56121eaf6ca73e78f203f35d40235b5
[sdk-current]: https://github.com/pollen-robotics/reachy_mini/tree/0ce74800cd496316ec08802623e77e9875d3f295
[sage]: https://huggingface.co/spaces/sabhay22/reachy_sage_voice/tree/c7592c88832f1dea397164ababe02b05698b78cb
[marionette]: https://huggingface.co/spaces/pollen-robotics/marionette-js/tree/7798da60a5cdfa78fad9343c341f102e686dc0a4
[minimal]: https://huggingface.co/spaces/tfrere/minimal-conversation/tree/31a60471d3c0017631e262eb2fbcfa2acfe2fd75
[hand]: https://huggingface.co/spaces/pollen-robotics/hand_tracker_v2/tree/1024dd103fa4a2a3e59d3bad2050db51bde47581
[mime]: https://huggingface.co/spaces/RemiFabre/mime_bot/tree/20b6709abd424a3222d020969b2231f4432ec631
[emotions-ui]: https://huggingface.co/spaces/pollen-robotics/emotions/tree/c5f4e20db5f317765ddfe2fc83e20c20f9ffbc17
[telepresence]: https://huggingface.co/spaces/pollen-robotics/telepresence/tree/30b19c6d1f742c2fd3dbe9a2b27a857c2f3066ee
[emotions-data]: https://huggingface.co/datasets/pollen-robotics/reachy-mini-emotions-library/tree/873ae49f0b89114b7e535eff0c1f7560d21d9357
[dances-data]: https://huggingface.co/datasets/pollen-robotics/reachy-mini-dances-library/tree/3564295e72d41c1271f46bf5540a3fcad9d5f669
[conversation-realtime]: https://github.com/pollen-robotics/reachy_mini_conversation_app/blob/f58eb8f62f9a4e334411a477d91267c377657d0a/src/reachy_mini_conversation_app/huggingface_realtime.py
[conversation-moves]: https://github.com/pollen-robotics/reachy_mini_conversation_app/blob/f58eb8f62f9a4e334411a477d91267c377657d0a/src/reachy_mini_conversation_app/moves.py
[tapper]: https://github.com/pollen-robotics/reachy_mini/blob/0ce74800cd496316ec08802623e77e9875d3f295/src/reachy_mini/motion/speech_tapper.py
[wobbler]: https://github.com/pollen-robotics/reachy_mini/blob/0ce74800cd496316ec08802623e77e9875d3f295/src/reachy_mini/motion/head_wobbler.py
[sage-arbiter]: https://huggingface.co/spaces/sabhay22/reachy_sage_voice/blob/c7592c88832f1dea397164ababe02b05698b78cb/reachy_sage_voice/motion/arbiter.py
[sage-interruption]: https://huggingface.co/spaces/sabhay22/reachy_sage_voice/blob/c7592c88832f1dea397164ababe02b05698b78cb/reachy_sage_voice/interruption.py
[sage-turn]: https://huggingface.co/spaces/sabhay22/reachy_sage_voice/blob/c7592c88832f1dea397164ababe02b05698b78cb/reachy_sage_voice/turn_end.py
[s2s-cancel]: https://github.com/huggingface/speech-to-speech/blob/2cd285679a0c9eddcd08143d783a07da726b433a/src/speech_to_speech/pipeline/cancel_scope.py
[s2s-mac]: https://github.com/huggingface/speech-to-speech/blob/2cd285679a0c9eddcd08143d783a07da726b433a/example_configs/mac.yaml
[homebody-session]: https://github.com/Timverhoogt/homebody/blob/c5c162ce8b708bba7703a396eb7c14ab2810bad2/homebody/agent_session.py
[homebody-playback]: https://github.com/Timverhoogt/homebody/blob/c5c162ce8b708bba7703a396eb7c14ab2810bad2/homebody/playback_gate.py
[homebody-native]: https://github.com/Timverhoogt/homebody/blob/c5c162ce8b708bba7703a396eb7c14ab2810bad2/companion/native_adapters.py
[homebody-backends]: https://github.com/Timverhoogt/homebody/blob/c5c162ce8b708bba7703a396eb7c14ab2810bad2/companion/agent_backends.py
[homebody-notices]: https://github.com/Timverhoogt/homebody/blob/c5c162ce8b708bba7703a396eb7c14ab2810bad2/THIRD_PARTY_NOTICES.md
[hermes-plugin-adapter]: https://github.com/ai-ag2026/hermes-reachy/blob/704f16eb7c8e551ce43e54a8492dedfb66544a25/src/hermes_reachy/adapter.py
[claw-manifest]: https://github.com/suharvest/reachy-claw/blob/c3fc46d8bcd4510e916d48f738e5039f66b02230/pyproject.toml
[claw-active]: https://github.com/suharvest/reachy-claw/tree/c3fc46d8bcd4510e916d48f738e5039f66b02230/src/reachy_voice
[marionette-bench]: https://huggingface.co/spaces/pollen-robotics/marionette-js/blob/7798da60a5cdfa78fad9343c341f102e686dc0a4/lib/benchmark.js
[recorded1211]: https://github.com/pollen-robotics/reachy_mini/blob/v1.2.11/src/reachy_mini/motion/recorded_move.py
[rerun1211]: https://github.com/pollen-robotics/reachy_mini/blob/v1.2.11/src/reachy_mini/utils/rerun.py
