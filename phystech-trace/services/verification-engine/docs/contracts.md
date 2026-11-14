# Контракты и версии

## Зафиксированные upstream версии

Commit SHA и ссылки записаны в [`contracts/upstream-sources.json`](../contracts/upstream-sources.json). Upstream Extraction и Linking схемы сохранены побайтно в `contracts/upstream/`.

| Данные | Версия схемы | Правило |
| --- | --- | --- |
| Structured Extraction | `1.2.0` | Текущая upstream schema сохранена побайтно; несовместимый major отклоняется |
| Document Linking | `1.2.0` | Текущая upstream schema сохранена побайтно; `status` и `verification_status` не смешиваются |
| Reconciliation result | Provisional `run_metadata`/`targets` 1.0.0 and native `input_snapshot`/`calculations` 1.0.0 | Две формы одной версии различаются по структуре и проверяются разными адаптерами |
| Verification result | `1.2.0` | Additive schema в `contracts/verification-result-1.2.0.schema.json`; схемы 1.0.0 и 1.1.0 сохранены, SQLite reader помечает старые результаты `legacy_unverified` |

## Входной API

```json
{
  "project_id": "synthetic-project",
  "extraction": {"schema_version": "1.2.0", "document_type": "kfz_report"},
  "supporting_extractions": [],
  "linking_result": null,
  "reconciliation_result": {
    "contract_version": "1.0.0",
    "run_metadata": {},
    "targets": []
  },
  "context": {
    "period": null,
    "tolerance": {
      "absolute": null,
      "absolute_unit": null,
      "relative": null,
      "rounding_scale": null,
      "rounding_mode": "HALF_UP"
    },
    "notes": []
  }
}
```

Полные тела находятся в `examples/request-matched.json` и `examples/request-mismatch.json`.

## Provisional Reconciliation 1.0.0

`contracts/reconciliation-result-1.0.0.schema.json` требует:

- `run_metadata`: run/project/calculation IDs, время, версия движка, extraction ID и schema version, nullable hash и Linking run ID;
- `target`: KFZ document/extraction IDs, точный JSON Pointer, semantic key, value type, period, currency/unit, VAT basis и comparison basis;
- `result`: expected value с явным `null` при отсутствии, тип/смысл, период и единицы, полнота, eligibility, формула, применённые правила, использованные/исключённые источники, операции, диагностика, warnings и provenance;
- `used_sources`: идентификатор документа и extraction, JSON Pointer, строка при наличии, состояние доказательства и Linking evidence reference при наличии.

Десятичные financial values передаются строками или объектом `{ "amount": "...", "currency": "..." }`. Для известных арифметических операций Verification независимо проверяет результат через Decimal; неподдерживаемые операции остаются непроверенными. `expected_value: null` не означает ноль.

## Native Reconciliation Engine 1.0.0

Опубликованная форма Reconciliation Engine также использует `contract_version: 1.0.0`, но содержит `input_snapshot`, `calculations`, `reconciliation_id` и `scope`. Схема зафиксирована в `contracts/reconciliation-engine/`; источник, commit и SHA-256 копий перечислены в `contracts/reconciliation-engine-sources.json`.

Адаптер читает `target.kfz_origin`, `calculation_plan`, `used_sources`, `steps`, `provenance` и `input_snapshot`. Verification сверяет точные Extraction IDs/версии и SHA-256 canonical JSON, разрешает исходные JSON Pointer, восстанавливает fact IDs и fact input hashes, а затем повторно вычисляет поддерживаемые `sum`, `add`, `subtract`, `multiply`, `divide` и `round` операции через Decimal. Трасса, формула, exact value, округление и `expected_value` должны согласоваться. Неполная или неподдерживаемая операция не может стать окончательным `matched`/`mismatch`.

Реальный upstream пример — `manual_review` без использованных значений; он проверяется как неполный и не считается успешным расчётом. Отдельный upstream-generated acceptance fixture синтетический и служит только проверке арифметического proof evaluator.

## Linking upstream discrepancy

Интеграционная ветка декларирует Linking output 1.2.0 и содержит соответствующую схему. Соседний `services/document-linking/examples/linking-result.json` имеет payload `contract_version: 1.0.0` и отклоняется той схемой: пример использует `detection_method: rules` вместо schema const `llm` и не содержит обязательные `processing_metadata.llm.strategy`, `estimated_input_tokens`, `link_validation_diagnostics`, `analysis_summary`. Пример сохранён как upstream artifact без изменений, тест фиксирует несовместимость. Синтетический, явно помеченный Link result 1.2.0 используется для тестирования контракта, но не выдаётся за реальный production result.

## Verification result 1.2.0

Ответ содержит run/project/calculation IDs, fingerprint, summary counts, проверяемую полноту и результат каждого Reconciliation target. На уровне показателя сохраняются:

- исходное и нормализованное значение и Extraction status;
- JSON Pointer, document/extraction/row IDs и provenance;
- Reconciliation formula, операции, rules и источник expected value;
- использованные и исключённые источники, Link evidence, все diagnostics;
- абсолютная и относительная разница с формулой, правила допуска, классификации и uncertainty.
- отдельные `trust` значения для технической валидности, автоматического Link подтверждения, human review и достоверности расчёта.

`conclusion` отдельно сообщает `has_proven_mismatch`, `coverage_complete`, количество доказанных расхождений, непроверенных и неприменимых показателей. `overall_status=mismatch` сохраняет приоритет при наличии других unresolved indicators, а completeness остаётся false. `/openapi.json` публикует реальные Pydantic схемы API. Схемы 1.0.0 и 1.1.0 сохранены. Ранее сохранённые `matched`/`mismatch` не перепроверяются при чтении: адаптер сохраняет исходное значение в `legacy_status`, понижает текущий статус до `needs_review`, ставит `integrity_status=legacy_unverified` и не считает такое доказательство проверенным.

## Проверки provisional Reconciliation

Входные upstream схемы не менялись. Для native результата проверяются calculation/snapshot IDs, Extraction versions и hashes, source fact IDs/hashes, exact JSON Pointers, operation graph, следы шагов, формула и итоговая Decimal арифметика. Для provisional адаптера поддерживаются простые формальные операции; запись одинакового `output_value` и `expected_value` сама по себе недостаточна. Для обеих форм результат без проверяемого proof остаётся `unproven`.

## Большие комплекты и ссылки на артефакты

Обычный лимит HTTP body по умолчанию равен 16 МиБ и настраивается через `VERIFICATION_MAX_REQUEST_BYTES` (жёсткий предел 64 МиБ). Для больших комплектов `POST /api/v1/verifications/from-artifacts` принимает project-scoped `{artifact_id, sha256}` ссылки. Внешний доверенный artifact service предварительно кладёт JSON object по адресу `<VERIFICATION_ARTIFACT_ROOT>/<sha256(project_id)>/<sha256>.json`; API не предоставляет загрузку произвольных файлов. Каждый объект проверяется по размеру и SHA-256, а кеш ограничен `VERIFICATION_ARTIFACT_CACHE_BYTES`. При обработке адаптер всё равно передаёт материализованные JSON объекты схеме и движку.

Актуальный список integration repo и точные commit/schema hashes находятся в [`contracts/upstream-sources.json`](../contracts/upstream-sources.json). Контракт Reconciliation остаётся предварительным: интеграционные детали и ограничения описаны в [`reconciliation-integration.md`](reconciliation-integration.md).
