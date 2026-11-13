# Интеграция с Phystech Trace

## Передаваемые данные

Отправляйте в `POST /api/v1/verifications`:

1. `extraction`: полный Extraction JSON для `kfz_report`.
2. `reconciliation_result`: полный объект provisional Reconciliation 1.0.0. Expected values, операции и source IDs должны быть сформированы Reconciliation.
3. `linking_result`: Linking 1.2.0 JSON при наличии; он нужен для каждого `used_sources[].link_id`.
4. `supporting_extractions`: Extraction JSON для документов, на которые указывают `used_sources`.
5. `context`: известные период и comparison tolerance. Не задавайте произвольные значения допуска.

Формы запроса и ответа находятся в `examples/request-matched.json`, `examples/response-matched.json`, `examples/request-mismatch.json`, `examples/response-mismatch.json`. Это синтетические демо, не реальные финансовые данные проекта.

## Требования к Reconciliation adapter

- Не заменяйте отсутствующий expected value числом `0`; передавайте `null`.
- Для каждого KFZ target задавайте точный pointer, например `/fields/reported_total/value` или `/line_items/2/amount/value`.
- Передавайте `semantic_key`, `value_type`, period, currency/unit, VAT basis и comparison basis для обеих сторон.
- Сохраняйте `used_sources`, `excluded_sources`, `operations`, формулы, applied rules, warnings и provenance.
- Источник должен указывать extraction ID, JSON Pointer и row ID если он есть. Указывайте `evidence_status: human_confirmed` только после соответствующей проверки источника.
- Если связывание было нужно, укажите `link_id` и `evidence_index`. Verification разрешит ID в Linking result, проверит статус, endpoint path и raw evidence.
- Заполните `run_metadata.input_data` версиями и hashes входов, `linking_run_id` и `calculation_id`.

## REST вызовы

```http
POST /api/v1/verifications
Content-Type: application/json
```

Одинаковый request JSON идемпотентен. Полученный `verification_id` можно использовать для результата и diagnostics:

```http
GET /api/v1/verifications/{verification_id}
GET /api/v1/verifications/{verification_id}/diagnostics
GET /api/v1/verifications?project_id={project_id}&limit=50&offset=0
```

Контрактная ошибка возвращает HTTP 422 с `contract`, `path`, `message`; отсутствующий run — 404. `GET /docs` и `/openapi.json` публикуют API для Reporting/Vue клиента.

## Подключение настоящего Reconciliation

После согласования настоящей схемы добавьте отдельный входной адаптер, который нормализует новый контракт в `target` + `result` модель. Не меняйте `comparison.py` ради перестановки JSON полей. Увеличьте `contract_version`, сохраните текущую 1.0.0 схему для воспроизводимости и добавьте контрактные fixtures настоящего Reconciliation.

## Граница end-to-end

Тесты Verification Engine подтверждают его API и совместимость входных Extraction/Linking схем на доступных fixtures. Полный прогон Parser → Reporting невозможен до подключения настоящего Reconciliation и Reporting; текущие `request-*` используют явно синтетический Reconciliation результат.
