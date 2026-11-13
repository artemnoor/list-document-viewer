# Результаты тестирования

Последний полный зафиксированный прогон `pytest` до подключения Polza provider: 13 ноября 2026.

```text
43 passed, 1 warning in 9.62s
```

Набор включает 43 автоматических test cases (плюс 60 Hypothesis примеров Decimal арифметики):

- совпадение, mismatch, границы допуска, округление, отрицательные суммы, expected=0;
- отсутствующие значения, partial calculation, unit/currency/VAT/basis/period mismatch;
- confirmed/suspected duplicate, missing document, unconfirmed source и Linking evidence;
- Extraction 1.2.0 fixtures, контрактно валидный synthetic Linking 1.2.0, конфликт raw Linking fixture и объявленной схемы;
- provenance и unresolved pointers, совместимость версий и проверки output JSON Schema;
- API create/get/history/diagnostics/health/docs/OpenAPI, SQLite идемпотентность и чтение записей старого формата;
- необязательные de-identified LLM suggestions, schema-bound только к гипотезам и разрешённым evidence tokens.

**Предупреждения среды:** в сводке pytest присутствует предупреждение установленного Starlette о будущей замене `httpx` на `httpx2` в `TestClient`; тесты завершились успешно. До сводки глобальный pytest-asyncio выводит предупреждение о loop scope, хотя проект не использует async fixtures.

Docker image собран и оставлен запущенным через Compose на `http://127.0.0.1:8000`. Smoke-проверка контейнера подтвердила health, Swagger и OpenAPI (`200`), сценарии `matched` и `mismatch` (`100.00` против `110.25`, разница `-10.25`), повтор с тем же fingerprint и выдачу истории. Записи SQLite, созданные более ранней версией результата, читаются с явной пометкой об отсутствии исторической `input_metadata`.

После подключения Polza AI выполнен один live-запрос с синтетическим mismatch: API вернул `mismatch`, Gemma вернула три schema-валидные гипотезы, ошибок provider не записано. Внешний запрос содержал только `ReviewCase` с псевдонимными tokens и кодами. Автоматический `pytest` после этого подключения не запускался.

Это не полный E2E Phystech Trace: реальные Reconciliation output и Reporting не подключены.

Сценарии синтетического набора и предполагаемые статусы независимо записаны в `tests/fixtures/synthetic/expected-statuses.json`. Upstream Linking sample ожидаемо не проходит интеграционную schema 1.2.0; тест закрепляет наблюдаемую несовместимость, а не исправляет исходный JSON.
