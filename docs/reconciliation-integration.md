# Требования Verification к Reconciliation

Дата актуальной проверки upstream: 14 ноября 2026. Используемая опубликованная схема и неизменённые fixtures закреплены SHA-256 в [`../contracts/reconciliation-engine-sources.json`](../contracts/reconciliation-engine-sources.json). Verification принимает две формы с `contract_version: 1.0.0`, различая их по обязательным полям:

| Форма | Идентификация | Адаптер |
| --- | --- | --- |
| Старый provisional handoff | `run_metadata`, `targets` | `ProvisionalReconciliationAdapter` |
| Reconciliation Engine | `input_snapshot`, `calculations`, `reconciliation_id`, `scope` | `ReconciliationEngine10Adapter` |

Обе схемы валидируются отдельно. Нативный адаптер не переименовывает upstream документ и строку: сохраняет `document_id`, `extraction_id`, `row_id`, `link_id`, JSON Pointer, provenance, input fingerprints, а для calculation указывает JSON Pointer на `/calculations/{index}`. Совпадение версий само по себе не выбирает адаптер.

## Идентификаторы и fingerprints

Для provisional handoff должны совпадать project ID, primary extraction ID/schema version/input hash и hashes всех используемых supporting Extraction. При наличии Linking должны совпасть Linking run ID, версия, входные документы, Extraction IDs/versions и input hashes.

Для native result Verification сверяет каждый `input_snapshot.extraction_results[]` с фактически переданным документом: document ID, extraction ID, Extraction `version`, schema version и SHA-256 canonical JSON. Публичный Reconciliation Engine использует `json.dumps(..., ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)` для canonical JSON. Если snapshot содержит Linking run, одноимённый run/version/hash должен прийти во входе Verification. Документы, которых нет в snapshot, не могут подтверждать использованный source.

`provenance.input_snapshot_sha256` каждого native calculation обязан совпадать с `input_snapshot.snapshot_sha256`. Это связывает calculation с заявленным snapshot; само по себе оно не является подписью издателя. Verification независимо перепроверяет Extraction hashes и используемые значения.

## Доказательства источников

Каждый использованный источник должен разрешаться в переданной Extraction по точному JSON Pointer к wrapper `value`, с точными document/extraction/row IDs, исходным `source_value`, status, confidence, валютой/единицей и provenance locator. Для native Calculation Engine дополнительно пересчитываются:

- `fact_id = fact_` + первые 20 hex SHA-256 от UTF-8 строки `document_id|source_path`;
- `input_hash` факта — SHA-256 canonical JSON от факт-записи, восстановленной по исходному Extraction wrapper;
- набор `calculation_plan.included` должен точно совпадать с используемыми fact IDs;
- плановые шаги не должны ссылаться вперёд, на отсутствующие или исключённые значения; каждый включённый факт участвует ровно один раз в итоговом выражении;
- `related_links` должны разрешаться в переданном Linking и проходить проверку endpoint values, документов, строк, versions, fingerprints и evidence. Для supporting-документа без подтверждаемой связи источник остаётся `unconfirmed`.

`status=confirmed`, `verification_status=human_confirmed` или вложенный `human_confirmation` не принимаются как самостоятельное доказательство. Экспертное подтверждение хранится отдельно от технической валидности и автоматически проверенной связи.

## Проверка calculation proof

Verification не реализует финансовый планировщик Reconciliation. Для формального плана native 1.0.0 она независимо вычисляет только перечисленные операции через `Decimal`: `sum`, `add`, `subtract`, `multiply`, `divide` и `round` с `ROUND_HALF_UP`. Проверяются arity и порядок DAG, уникальность step IDs, входные ссылки, полнота/достижимость шагов, точный trace (`step_id`, operation, inputs и value), сгенерированное по плану выражение, `exact_value_before_rounding`, rounding scale/mode и итоговый `expected_value`.

В provisional формате поддерживаются числовые sum/add/subtract/multiply/divide/round и точный `period_selection`. Неподдерживаемая текстовая арифметика, неполная операция или невозможность проверить формулу дают `unproven`/`needs_review`; противоречие между повторным вычислением и output/exact/expected даёт `invalid` и блокирует окончательные статусы. Сравнение одного записанного `output_value` с `expected_value` не доказывает расчёт.

Период actual читается из Extraction. Период target/context не подменяет исходное значение. Явный mismatch допустим только при валидных входных fingerprints, доказательствах и расчёте; при ошибке расчёта или отсутствии источников результат остаётся unresolved.

## Охват

Reconciliation должен выдавать calculation для каждого применимого показателя КФЗ или явный статус/причину, почему показатель не рассчитывался. Verification сохраняет каждую непроверенную цель и выявляет показатели Extraction без соответствующего target. Общий `matched` требует полного проверенного охвата. Общий `mismatch` имеет приоритет над unresolved и `not_applicable`, а полнота отдельно отражается в `conclusion.coverage_complete`.

## Примеры доступной интеграции

- `tests/fixtures/upstream/reconciliation-engine/act-reconciliation-result.json` — реальный upstream Reconciliation Engine result, но его target помечен `manual_review`, trace и used sources пусты. Он интегрируется и корректно остаётся `insufficient_data`; это не положительный E2E расчёт.
- `tests/fixtures/synthetic/reconciliation-engine/acceptance-result.json` вместе с `acceptance-request.json` — synthetic acceptance output, сформированный настоящим Reconciliation Engine. Он используется отдельно для проверки Decimal proof и fact hashes. Supporting act facts там не сопровождаются реальной relationship evidence, поэтому Verification не объявляет весь результат `matched`.

## Что требуется от следующих версий Reconciliation

Не меняя опубликованные схемы, следующие версии должны сохранять точную связь `calculation_id` ↔ snapshot ↔ target; все Extraction IDs/versions/hashes; используемые и исключённые fact IDs с исходными JSON Pointers и input hashes; формальный calculation plan и полный ordered trace; единицы, currency, amount basis, период и rounding policy; provenance источника и проверяемые ссылки Linking; явное разделение `calculated`, `manual_review`, `insufficient_data` и `not_applicable`. Изменение этих полей оформляйте новой версией схемы и отдельным adapter. Verification не принимает status без соответствующих proof данных как окончательный результат.
