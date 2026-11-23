# MODEL-TIMING-01: четыре настоящих same-call receipts

Карточка [#35](https://github.com/notanonenough/reachy-companion/issues/35).
Один normal production опыт 24.11.2026 на candidate
`3aea1cd42d0e13b396766bea3bfd4659d698eef5` подтвердил перенос измерений
[MODEL-TIMING-01](../MODEL-TIMING-01.md) через actual main → private trace.
Это проверка instrumentation, **не успешная приёмка всего опыта**:
Hub `accepted=false`, cleanup issues `busy:audio` и `busy:background`;
известное завершение процесса и последующее освобождение узлов проверены владельцем.
Whole trace incomplete: `occupied_at_close`, 92 records, dropped=1.
Каждый из четырёх рассмотренных model receipts отдельно complete.

## Источники и привязка

Private directory: `/Users/notanonenough/reachy-release-backups/20261124-3aea1cd42d0e/combined-trial-001`.
Raw text и полные prompt/context в этот протокол не включены.

| Private artifact | SHA256 |
|---|---|
| `private-trace.jsonl` | `878eb3977e086b1adb2266de0d78da3cf5b334e1ce0925d6fe2f6ccfa2b46063` |
| `model-timing-bounded.json` | `05c39abacdea07342368e62bf6be92a753fc35653786da0e7c8fc6ca14e2793e` |

Для каждой пары main_request/main_result совпадают task, attempt, authority и
started_at; receipt.request_id совпадает с attempt, gateway_boot_id — с
authority.compute_boot_id. Все семь stages имеют state=complete. Ниже M1–M4 —
порядковые обозначения, не опубликованные private identities. M1/M2 audio-linked;
M3/M4 metadata-only: их нельзя включать в распределение голосовой задержки.

Все четыре receipts: backend `llama_native`, build `b11941-19ff817fb`;
weight/tokenizer SHA256 `03b74727a860a56338e042c4420bb3f04b2fec5734175f4cb9fa853daf52b7e8`,
template SHA256 `da8586387961d27cf1f580f825cde64cae3eeacf407c27362d19a5390a60cc23`,
config SHA256 `1e827543ae34396a4a44daaa8ec41a2250e919a4eff44c4feae51302e8bee987`.
Это audited gateway configuration provenance, не новая аттестация binary.

## Измеренное и reported

Все durations в таблице — **секунды**. Native prompt/predicted поля исходно в
milliseconds, здесь разделены на 1000. Client interval использует Hub monotonic;
два tokenizer RPC и completion — Gateway monotonic одного вызова. Разные clocks
не вычитаются. Reported native — слова provider, не независимый profiler.

| Call / checked outcome | Hub client | 2 tokenizer RPC, сумма | Gateway completion | Native prompt, reported | Native predicted, reported | Input/output tokens |
|---|---:|---:|---:|---:|---:|---:|
| M1 audio / discarded | 7.895261 | 0.023951 | 7.853972 | 6.935099 | 0.911554 | 1303 / 13 |
| M2 audio / ready | 6.642803 | 0.019143 | 6.603999 | 5.712561 | 0.850512 | 1067 / 17 |
| M3 metadata / discarded | 6.768820 | 0.012683 | 6.737400 | 5.591143 | 1.103543 | 1002 / 18 |
| M4 metadata / discarded | 6.921971 | 0.014291 | 6.884959 | 5.597235 | 1.262294 | 999 / 18 |

Output reservation=256 и template tokens=17 во всех четырёх; reservation не actual
output. Validation занимает 0.000100–0.000394s. Enclosing totals перекрываются с
children, складывать их нельзя. n=4, из них audio n=2: tail/throughput гарантий нет.
Во всех четырёх reported_cache_n=0; reported_tokens_cached=1315/1083/1019/1016.
Последнее поле не объявляется cache hit. TTFT и cache_hit остаются missing.
Подтверждённый крупный этап — completion, внутри него dominant reported prompt
processing; экономия двух tokenizer RPC сама по себе не устранит 6–8s main.

## Полная наблюдаемая цепочка второго audio input

STT: recognized n=2, empty n=35. Их durations не смешиваются. Recognized STT
заняли 2.173456s и 2.419031s. Последняя capture boundary локально сопоставлена
с Hub clock; это не измеренное окончание человеческой речи на device clock.

| Непересекающийся интервал второй цепочки | Seconds |
|---|---:|
| Mapped capture end → STT start | 0.147673 |
| STT | 2.419031 |
| STT end → admission | 0.020203 |
| Admission → main start | 7.606797 |
| Main client | 6.642803 |
| Main end → checked | 0.021499 |
| Checked → speech commit | 0.844593 |
| Commit → first PCM | 0.451842 |
| **Mapped capture end → first PCM** | **18.154441** |

В ожидании main 7.246575s совпадают с ещё выполняющимся M1; после его client end
до M2 start ещё 0.360222s. First PCM не first audible и не model TTFT.
Producer first PCM elapsed=0.446634s, total producer elapsed=0.712057s;
playback stop verified. Это одна наблюдаемая цепочка, не общая latency гарантия.

Private semantic review подтвердил: первый recognized segment содержал вопрос,
второй — дополнительное требование формата. Первый main result discarded,
второй ready. Actual historical endpoint reason не сохранён: точное объяснение
4s границы основано на audio duration и коде, не на отсутствующем wire flag.
Существующий normal device endpoint публикует speech-active deadline fragment
так же, как silence-ended input; каждый recognized result допускается отдельно.

Следующий конкретный шаг — [#39](https://github.com/notanonenough/reachy-companion/issues/39):
typed turn/segment/final, сохранение непрерывности кадров, bounded последовательное
STT и одна admission после фактической VAD-паузы. Ожидаемый проверяемый эффект —
нет преждевременного main на deadline fragment и замещения вопроса его продолжением.
Скорость native generation этим не объявляется исправленной. Изменения модели,
TTL и cache settings не входят. Prefix reorder пока не доказанное ускорение.

## Повторная числовая проверка без inference

Следующая команда читает только bounded projection и печатает числа без текста:

```sh
python3 - "$PRIVATE_DIR/model-timing-bounded.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
for r in d['records']:
    if r['kind'] != 'main_result':
        continue
    t = r['model_timing']; s = t['stages']; n = t['reported_native']
    assert not t['incomplete']
    assert t['request_id'] == r['attempt_id']
    assert t['gateway_boot_id'] == r['authority']['compute_boot_id']
    assert all(v['state'] == 'complete' for v in s.values())
    print(*(round(v, 6) for v in (
        r['ended_at'] - r['started_at'],
        s['tokenize_text']['duration_s'] + s['tokenize_prompt']['duration_s'],
        s['completion']['duration_s'], n['reported_prompt_ms'] / 1000,
        n['reported_predicted_ms'] / 1000)), t['usage'])
assert d['trace_end']['incomplete'] and d['trace_end']['dropped'] == 1
PY
```

`PRIVATE_DIR` — указанный выше private directory. Команда не делает network,
model calls или process probes; raw trace для этой таблицы не требуется.
