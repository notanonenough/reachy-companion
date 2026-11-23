# MODEL-TIMING-01: числовые этапы одного main call

Карточка [#35](https://github.com/notanonenough/reachy-companion/issues/35), продолжение
[аудита](MODEL-LATENCY-01.md). Это instrumentation без доказательства ускорения.
Новых inference/RPC, streaming, retries, моделей или settings нет. Аппаратная
проверка одной штатной цепочки требует отдельного candidate и окна ведущего.

`ModelBackend.generate` создаёт один local recorder для main. Два существующих
`count` и существующий completion выполняются ровно по одному разу, как раньше.
Gateway возвращает дополнительный `model_timing`; `RemoteGateway` сохраняет
прежний output/verdict и slot/quarantine поведение. `main_call` проверяет attempt
и compute boot против task authority и сохраняет только типизированную проекцию
в существующем bounded private `main_result`. Default-off trace не создаёт файл;
метрики не добавляются в status, public reports или outbox.

## Контракт version1

`clock_basis=gateway_monotonic` относится к durations внутри одного Gateway
процесса. Абсолютные timestamps Mac не передаются и не вычитаются из Hub clocks.
`request_id` совпадает с main attempt, `gateway_boot_id` — с compute authority.
`backend`, audited `build`, SHA256 model ID, weight/tokenizer/template и config
связывают receipt с моделью. Это provenance конфигурации gateway, не новый способ
независимой аттестации фактически загруженного server binary/weights.

`config_sha256` — канонический JSON SHA256 фиксированного allowlist model settings:
context/admission/input/template/output/reserve caps, temperature, structured_reply,
completion/tokenizer backend, message template, assistant prefix и stop strings.
В receipt сохраняется только digest. URLs, credentials/env, character/profile,
utterance, memory, prompt и raw response не копируются и не хэшируются этим helper.
Server CLI flags, sampling defaults вне этого allowlist и runtime code identity
нужно связывать с release/config evidence будущего опыта отдельно.

| Stage | Начало → конец, локальные monotonic durations в секундах |
|---|---|
| `tokenize_text` | Вход/возврат существующего `count(system+content)`, включая HTTP encode/read/decode и проверку token list. |
| `tokenize_prompt` | Вход/возврат `count(formatted_prompt)` с той же границей. |
| `completion` | Перед существующим backend completion branch → сразу после полного ответа `post`/SDK complete; HTTP branch включает encode/read/decode. |
| `validation` | После completion → проверка terminal/content/JSON, projection и provenance, построение result. Не server decode. |
| `backend_total` | После создания recorder/provenance → возврат backend body, включая подготовку и вышеуказанные stages. |
| `gateway_total` | Перед прежней role-lock admission → возврат backend к `Gateway.generate`; последующий lock release не включён. |
| `handler_to_pre_serialize` | Вход handler → после прежних request/dependency проверок и generation, перед final timing projection и `reply`. JSON serialization/write не измерены. |

Все stage entries содержат `state=complete|failed|missing` и `duration_s`.
Failed/unreached/invalid — null, не0. Настоящая нулевая измеренная duration
допустима. Duration ограничена0..3600s; bool/NaN/infinity/negative/overflow не
считаются числом. Enclosing total и дочерние stages перекрываются: **нельзя их
складывать**. Остаток total после непересекающихся children — не автоматически
network/queue. Hub main elapsed остаётся прежним отдельным client interval,
включающим транспорт Hub↔Gateway и bounded trace enqueue перед вызовом.

`usage` сохраняет существующие exact input_tokens/text_tokens/template_tokens,
output_reserved и output_tokens, когда последний доступен. Известные counts
сохраняются и при последующей ошибке. Reservation не называется actual output.
Counts — целые0..10,000,000; bool и дробь отвергаются только в диагностике.
Исходный generation output/usage/verdict это не исправляет и не заменяет.

`reported_native` содержит только nullable числовые поля исходного native ответа:

- `reported_prompt_ms`, `reported_predicted_ms`: milliseconds,0..3,600,000;
- `reported_cache_n`, `reported_prompt_n`, `reported_predicted_n` из `timings`;
- `reported_tokens_evaluated`, `reported_tokens_cached`, `reported_tokens_predicted`
  из top-level ответа; counts — целые с тем же cap.

Это provider-reported величины. Они не объявляются independently measured;
`prompt_ms` не TTFT, `tokens_cached/cache_n` не подтверждённый cache hit. Старые
checkpoint файлы послужили свидетельством имён полей, но не присоединяются к
новым requests. Отсутствующие поля и unsupported provider остаются null;
`ttft_s` и `cache_hit` всегда null при нынешнем пути. Невалидные diagnostics
дают `incomplete=true` и фиксированный reason без exception/body text. Прочие
поля raw response отбрасываются. Receipt с неверной version/clock/identity не
получает trusted request/gateway identity. Identity mismatch не меняет verdict
самого inference — прежние authority checks результата остаются ответственными.

## Ошибки и отсутствие terminal

В trace-enabled штатном Scheduler optional per-call callback получает максимум
один metadata-only `main_transport` после уже случившейся transport ошибки,
**до прежнего production health polling**. Дополнительного запроса нет. Это
не terminal, не cancellation/stop ACK и не освобождение main slot.

- `execution_unknown`: HTTP503 с привязанным diagnostic receipt;
- `observed_error_receipt`: другой полученный HTTP error либо503 без trusted receipt;
- `transport_failure`: ошибка транспорта вообще без HTTP response.

Отдельный fixed `transport_diagnostic_status` различает verified_receipt,
partial_diagnostic, no_response, missing_diagnostic, malformed_diagnostic,
identity_mismatch. При последних четырёх server receipt missing/untrusted;
сохраняются только outer client task/attempt/Hub authority, не выдуманный server
boot или stages. Callback failure поглощается и не меняет polling/retry/outcome.
Без trace callback отсутствует, чтение error body ради diagnostics не добавляется.

Если Job впоследствии завершился, `main_result` сохраняет обычный terminal
return/exception и имеющийся receipt. Если quarantine не завершился, остаётся
только `main_transport`; отсутствие terminal не маскируется. STOP/privacy
прекращают content capture по прежним правилам; поздняя metadata-only запись
разрешена в пределах прежнего lifetime/caps и не содержит raw text.

Offline `production_baseline` знает новый fixed kind, валидирует envelope,
authority/attempt/boot и causality с существующим request. Nonterminal receipt
не создаёт audio chain и не входит в completed main pairs/latency denominators.
Отдельного timing aggregation в этом изменении нет. Старый trace без такого
события даёт прежние интервалы. Частичный trace без terminal остаётся incomplete.

## Bounds и проверка

Helper не выполняет IO и не создаёт очередь/locks/background workers. Число
stages/usage/native fields фиксировано; recorder один на существующий запрос.
Existing trace immutable serialization, async writer, record≤16KiB,
queue≤32, session≤512records/1MiB и overflow→incomplete остаются действующими.
Метаданные могут приблизить прежний cap; превышение не маскируется усечением
и не влияет на inference. `model_timing` входит в canonical code identity и wheel.

Offline tests используют actual local Gateway→synthetic native HTTP server→
RemoteGateway→private trace. Controlled clock даёт .1/.2/.3/.4s для двух counts,
completion и validation; call order/payload и исходный result без дополнительного
receipt совпадают с вариантом recorder off. Проверяются partial422, actual503
quarantine с retained receipt до окончания poll, отсутствие repost, callback
failure/disabled, malformed/missing/foreign diagnostics, one-shot, privacy,
consumer missing-terminal/foreign-authority, existing default-off/STOP и caps.
Проверены production ContextGateway, AuditedGateway и FrozenModelBackend:
optional diagnostics проходят через прежние whitelist/instance guards; NativeGateway
по-прежнему запрещает main. Поздний отзыв memory dependency сохраняет уже
измеренные stages/counts только этого handler request и прежний422.

```sh
PYTHONPATH=src:tests python -m unittest test_model_timing test_production_baseline test_gateway_tokenizer_unknown test_autonomous test_private_audio_trace test_worker_code_identity -q
PYTHONPATH=src:tests python -m unittest discover -s tests -q
python -m build --no-isolation
```

Это software fixtures, не измерение настоящих моделей. Следующая приёмка — один
отдельно разрешённый normal-chain trial с сопоставлением typed receipts и
installed identity. Cold/warm серия, TTFT/streaming, отмена устаревшей генерации,
смена модели и изменение budgets этим изменением не разрешаются.
