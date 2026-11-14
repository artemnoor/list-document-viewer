# Результаты проверок

## Verification Engine 1.2.0 — 14 ноября 2026

### Локальные тесты

Команда:

```powershell
python -m pytest --tb=short
python -m compileall -q app tests
```

Результат последнего полного прогона: **72 passed**, 1 предупреждение Starlette TestClient о будущей замене `httpx` на `httpx2`. `pytest-asyncio` также вывел предупреждение, что scope event loop не задан.

Набор покрывает unit, upstream/schema contract, property-based Decimal arithmetic, regressions, API, concurrency, idempotence, storage migration, artifact references, >2 МиБ bundles, invalid hashes/versions and missing proof. Отдельно проверено, что запись одинаковых `output_value` и `expected_value` не скрывает неверную арифметику, а неполные цели не становятся `matched`.

Файл upstream-generated synthetic acceptance output отдельно проверяет native fact hashes и Decimal plan. Все исходные источники сверяются с synthetic Extraction; модифицированная операция/trace/expected value отвергается. Этот тест не считается реальным положительным Reconciliation запуском.

### Интеграция с доступным upstream Reconciliation result

`tests/fixtures/upstream/reconciliation-engine/act-reconciliation-result.json` — реальный результат движка на зафиксированном upstream commit. Calculation помечен `manual_review`, `used_sources` и trace пусты; snapshot объявляет Linking run, для которого в запросе нет соответствующего Linking result. Verification принимает и разбирает контракт, но возвращает `insufficient_data`; matched и mismatch отсутствуют. Итог: 81 `insufficient_data`, 12 `needs_review`, coverage incomplete. Это успешная проверка совместимости/отказа, а не полный E2E расчёта.

### Большой набор fixtures и artifact references

- Pretty-printed request со всеми upstream Extraction fixtures и настоящим Reconciliation result имеет 2,428,762 байта и проходит API с HTTP 200 при лимите по умолчанию 16 МиБ.
- Полный доступный набор upstream JSON, включая старый Linking fixture с `contract_version=1.0.0`, также превышает 2 МиБ; API получает запрос и отвечает контрактной ошибкой HTTP 422, а не ошибкой размера 413. Причина — несовместимость этого fixture с заявленной Linking 1.2.0 схемой.
- `/from-artifacts` проверен через временное project-scoped хранилище: ссылки проходят hash validation, повтор идемпотентен, чужой project scope не открывает файл, tampered content отклоняется.

### Docker Compose smoke

```powershell
docker compose config --quiet
$env:POLZA_AI_ENABLED = "false"
docker compose up --build --detach
```

Обе команды завершились успешно. Образ 1.2.0 healthy; `/health`, `/docs`, `/openapi.json` отвечают, OpenAPI сообщает 1.2.0. Свежий synthetic запрос вернул `matched`, `conclusion.coverage_complete=true`; scoped GET и project history доступны. Локальная SQLite volume содержала совпадающий исторический fingerprint из 1.1.0, поэтому при первом повторе legacy adapter ожидаемо вернул `legacy_unverified`/`needs_review`. Следующий запрос с новым fingerprint подтвердил свежий путь; данные volume не удалялись.

Во всех новых проверках внешние LLM-вызовы были отключены. Ни live Polza вызов, ни полный Parser → Reconciliation → Verification → Reporting E2E в этом прогоне не выполнялись.

### GitHub Actions

CI запускает полный pytest matrix на Python 3.11 и 3.12 и отдельный Docker Compose smoke после push и pull request. Push commit a4209a6 проверен успешным [GitHub Actions run 43513739458](https://github.com/artemnoor/phystech-trace-verification-engine/actions/runs/43513739458): оба Python job и Docker Compose smoke завершились успешно.
