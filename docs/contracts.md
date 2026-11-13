# Контракты и версии

## Зафиксированные upstream версии

Commit SHA и ссылки записаны в [`contracts/upstream-sources.json`](../contracts/upstream-sources.json). Upstream Extraction и Linking схемы сохранены побайтно в `contracts/upstream/`.

| Данные | Версия схемы | Правило |
| --- | --- | --- |
| Structured Extraction | `1.2.0` | Текущая upstream schema сохранена побайтно; несовместимый major отклоняется |
| Document Linking | `1.2.0` | Текущая upstream schema сохранена побайтно; `status` и `verification_status` не смешиваются |
| Reconciliation result | `1.0.0` provisional | Версия обязательна и должна быть ровно `1.0.0` до согласования нового адаптера |
| Verification result | `1.1.0` | Additive schema в `contracts/verification-result-1.1.0.schema.json`; v1.0.0 сохранена, SQLite reader адаптирует старые rows |

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

Десятичные financial values передаются строками или объектом `{ "amount": "...", "currency": "..." }`. Verification не суммирует `used_sources` повторно. `expected_value: null` не означает ноль.

## Linking upstream discrepancy

Интеграционная ветка декларирует Linking output 1.2.0 и содержит соответствующую схему. Соседний `services/document-linking/examples/linking-result.json` имеет payload `contract_version: 1.0.0` и отклоняется той схемой: пример использует `detection_method: rules` вместо schema const `llm` и не содержит обязательные `processing_metadata.llm.strategy`, `estimated_input_tokens`, `link_validation_diagnostics`, `analysis_summary`. Пример сохранён как upstream artifact без изменений, тест фиксирует несовместимость. Синтетический, явно помеченный Link result 1.2.0 используется для тестирования контракта, но не выдаётся за реальный production result.

## Verification result 1.1.0

Ответ содержит run/project/calculation IDs, fingerprint, summary counts, проверяемую полноту и результат каждого Reconciliation target. На уровне показателя сохраняются:

- исходное и нормализованное значение и Extraction status;
- JSON Pointer, document/extraction/row IDs и provenance;
- Reconciliation formula, операции, rules и источник expected value;
- использованные и исключённые источники, Link evidence, все diagnostics;
- абсолютная и относительная разница с формулой, правила допуска, классификации и uncertainty.
- отдельные `trust` значения для технической валидности, автоматического Link подтверждения, human review и достоверности расчёта.

`null` используется, когда относительная разница математически не определена (expected равен нулю) или вход отсутствует. Публичная схема — `contracts/verification-result-1.1.0.schema.json`; предыдущая `1.0.0` не удалена. `/openapi.json` публикует реальные Pydantic схемы API.

## Проверки provisional Reconciliation

Входная схема 1.0.0 не менялась. До присвоения окончательного статуса Verification проверяет run calculation ID, project/extraction IDs, schema versions, первичный и используемые supporting extraction hashes; при наличии Linking сверяет Linking run/contract versions и input fingerprints. Для каждой цели также проверяются уникальные source/operation IDs, ссылки source↔operation, совпадение формулы с input source IDs там, где IDs явно указаны в формуле, и совпадение operation output с единственным заявленным expected value. Это контроль целостности handoff, не повторный расчёт суммы.

Актуальный список integration repo и точные commit/schema hashes находятся в [`contracts/upstream-sources.json`](../contracts/upstream-sources.json). Контракт Reconciliation остаётся предварительным: интеграционные детали и ограничения описаны в [`reconciliation-integration.md`](reconciliation-integration.md).
