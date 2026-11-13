# Интеграция с Phystech Trace

## Передаваемые данные

Отправляйте в `POST /api/v1/verifications`:

1. `extraction`: полный Extraction JSON для `kfz_report`.
2. `reconciliation_result`: полный объект provisional Reconciliation 1.0.0. Expected values, операции и source IDs должны быть сформированы Reconciliation.
3. `linking_result`: Linking 1.2.0 JSON при наличии; он нужен для каждого `used_sources[].link_id`.
4. `supporting_extractions`: Extraction JSON для документов, на которые указывают `used_sources`.
5. `context`: известный период сравнения и comparison tolerance. Контекстный период не заменяет период, извлечённый из КФЗ.

В production передавайте `X-Service-Token`. Токен настраивается отдельно для каждого `project_id` через `VERIFICATION_PROJECT_TOKENS`; тот же project scope требуется для чтения истории, результата и diagnostics. Локальный Compose привязывает порт только к `127.0.0.1` и может работать в `development` режиме.

Формы запроса и ответа находятся в `examples/request-matched.json`, `examples/response-matched.json`, `examples/request-mismatch.json`, `examples/response-mismatch.json`. Это синтетические демо, не реальные финансовые данные проекта.

## Требования к Reconciliation adapter

- Не заменяйте отсутствующий expected value числом `0`; передавайте `null`.
- Для каждого KFZ target задавайте точный pointer, например `/fields/reported_total/value` или `/line_items/2/amount/value`.
- Передавайте `semantic_key`, `value_type`, period, currency/unit, VAT basis и comparison basis для обеих сторон.
- Сохраняйте `used_sources`, `excluded_sources`, `operations`, формулы, applied rules, warnings и provenance.
- Источник должен указывать extraction ID, точный JSON Pointer, row ID если он есть, provenance locator и `operation_ids`. `system_validated` допустим после machine validation; `human_confirmed` сохраняет отдельный human trust.
- Если использовалось Linking, укажите `link_id`/`evidence_index` и не теряйте Linking input document versions/hashes. Verification разрешит ID, сверит документы, endpoint path, raw value, row ID, conflicts и diagnostics.
- Заполните `run_metadata.input_data` совпадающими Extraction/Linking versions и hashes, `linking_run_id` и `calculation_id`. Hash должен соответствовать переданному immutable artifact `input_hash`.
- Все used sources должны быть связаны с существующими operation IDs и input source IDs; output операции должен однозначно совпадать с expected value. Не включайте excluded или неиспользованные документы как inputs расчёта.

## REST вызовы

```http
POST /api/v1/verifications
Content-Type: application/json
X-Service-Token: <project-scoped-token>
```

Одинаковый request JSON идемпотентен. Полученный `verification_id` можно использовать для результата и diagnostics:

```http
GET /api/v1/verifications/{verification_id}?project_id={project_id}
GET /api/v1/verifications/{verification_id}/diagnostics?project_id={project_id}
GET /api/v1/verifications?project_id={project_id}&limit=50&offset=0
```

Контрактная ошибка возвращает HTTP 422 с безопасными `contract`, `path`, `message`; значения финансовых полей в ошибках не повторяются. Ошибка авторизации — 401/404, отсутствующий или чужой project-scoped run — 404, превышение размера — 413, таймаут — 504. `GET /docs` и `/openapi.json` публикуют API для Reporting/Vue клиента.

## Подключение настоящего Reconciliation

После согласования настоящей схемы добавьте отдельный входной адаптер, который нормализует новый контракт в `target` + `result` модель. Не меняйте `comparison.py` ради перестановки JSON полей. Увеличьте `contract_version`, сохраните текущую 1.0.0 схему для воспроизводимости и добавьте контрактные fixtures настоящего Reconciliation.

## Граница end-to-end

Тесты Verification Engine подтверждают его API и совместимость входных Extraction/Linking схем на доступных fixtures. Полный прогон Parser → Reporting невозможен до подключения настоящего Reconciliation и Reporting; текущие `request-*` используют явно синтетический Reconciliation результат.
