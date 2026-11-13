# Phystech Trace — Verification Engine

Самостоятельный backend этапа Verification в Phystech Trace. Сервис сравнивает показатели итогового КФЗ из Structured Extraction с ожидаемыми значениями из предварительного контракта Reconciliation, проверяет допустимость сравнения и сохраняет доказательную цепочку. Сервис **не** извлекает данные из PDF и не пересчитывает Reconciliation.

## Что реализовано

- FastAPI REST API с OpenAPI/Swagger и типизированными запросами/ответами.
- Детерминированное сравнение `Decimal`, периодов, строк, дат, логических значений и количеств.
- Явные статусы `matched`, `mismatch`, `insufficient_data`, `needs_review`, `not_applicable`.
- Проверка версий, JSON Schema, точных JSON Pointer, extraction IDs, строк, provenance и Link IDs/evidence.
- Классификация установленной причины отдельно от гипотезы.
- SQLite история запусков и идемпотентное повторение одинаковых запросов.
- Исходные Extraction 1.2.0 fixtures и Linking пример upstream сохранены в `tests/fixtures/upstream/`; синтетические данные отдельно лежат в `tests/fixtures/synthetic/`.
- Версии upstream и commit SHA записаны в [`contracts/upstream-sources.json`](contracts/upstream-sources.json).

Если задана переменная `POLZA_AI_API_KEY` и `POLZA_AI_ENABLED` не выключен, рабочее приложение подключает Polza AI и Gemma 4 26B A4B (`google/gemma-4-26b-a4b-it`). Без ключа внешний provider выключен. В модель отправляются только обезличенные evidence tokens, статусы, коды диагностики и категории — без сумм, названий документов и исходного текста. Она может добавлять только неподтверждённые гипотезы с разрешаемыми references и не может менять значения или статусы. Для каждого показателя со статусом `mismatch`, `needs_review` или `insufficient_data` создаётся отдельный запрос к провайдеру; тарификация идёт по правилам Polza AI.

## Локальный запуск

Требуется Python 3.11+.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[test]"
$env:VERIFICATION_DB_PATH = "data/verification.sqlite3"
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Swagger UI: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs). Служебные OpenAPI и health endpoints находятся на `/openapi.json` и `/health`.

Проверка примерных запросов из PowerShell:

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:8000/api/v1/verifications `
  -Method Post -ContentType "application/json" -InFile examples/request-matched.json

Invoke-RestMethod -Uri http://127.0.0.1:8000/api/v1/verifications `
  -Method Post -ContentType "application/json" -InFile examples/request-mismatch.json
```

Оба запроса используют только синтетические данные. Первый возвращает `matched` для суммы и периода. Второй возвращает `mismatch` для суммы: `100.00 - 110.25 = -10.25 RUB`.

## Docker

```powershell
docker compose up --build
```

SQLite хранится в named volume `verification-data`. Опубликованный порт можно изменить через `VERIFICATION_PORT`.

Compose передаёт ключ `POLZA_AI_API_KEY` из окружения Windows внутрь контейнера. Идентификатор модели и адрес API можно переопределить через `POLZA_AI_MODEL` и `POLZA_AI_BASE_URL`. Подробности — в [`docs/polza-ai.md`](docs/polza-ai.md).

## Тесты

```powershell
python -m pip install -e ".[test]"
pytest
```

Набор проверяет числовые и содержательные сценарии, upstream-контракты, property-based арифметику, API, идемпотентность и SQLite. Фактический последний прогон описан в [`docs/test-results.md`](docs/test-results.md).

## API

| Метод | Endpoint | Назначение |
| --- | --- | --- |
| `GET` | `/health` | Состояние сервиса |
| `POST` | `/api/v1/verifications` | Запуск или повторное получение результата по fingerprint входов |
| `GET` | `/api/v1/verifications/{verification_id}` | Полный результат |
| `GET` | `/api/v1/verifications?project_id=...` | История запусков |
| `GET` | `/api/v1/verifications/{verification_id}/diagnostics` | Диагностика и причины ручной проверки |
| `GET` | `/docs` | Swagger UI |
| `GET` | `/openapi.json` | OpenAPI schema |

## Ограничения текущей интеграции

- Reconciliation Engine ещё не предоставляет финальный контракт. Текущий [`reconciliation-result-1.0.0.schema.json`](contracts/reconciliation-result-1.0.0.schema.json) — предварительный межсервисный контракт, проверяемый синтетическими fixtures.
- Проверки полного E2E Phystech Trace не заявляются: Reconciliation и Reporting ещё не подключены.
- Пример Linking, поставляемый upstream, содержит `contract_version: 1.0.0` и не проходит приложенную там же схему результата 1.2.0. Сырые исходные данные сохранены без изменений. Контрактно валидный synthetic Linking 1.2.0 используется отдельно в тестах.
- Метка `human_confirmed` принимается как декларация Reconciliation/Linking и проверяется на согласованность ссылок. Сервис не проверяет цифровую подпись или факт пользовательского действия во внешнем workflow.
- Неизвестный допуск не заменяется значением по умолчанию. Для денежного сравнения нужны одинаковые валюта и VAT basis; для сопоставления — совместимые периоды и economic basis.

## Документация

- [`docs/architecture.md`](docs/architecture.md) — компоненты и поток данных.
- [`docs/contracts.md`](docs/contracts.md) — входные/выходные схемы и версии.
- [`docs/verification-logic.md`](docs/verification-logic.md) — правила сравнений и статусов.
- [`docs/polza-ai.md`](docs/polza-ai.md) — подключение Polza AI / Gemma через окружение Windows.
- [`docs/classification.md`](docs/classification.md) — категории и требования к доказательству причины.
- [`docs/integration-guide.md`](docs/integration-guide.md) — подключение к Phystech Trace.
- [`docs/test-results.md`](docs/test-results.md) — фактические тестовые результаты и ограничения.
- Примеры запросов/ответов находятся в `examples/`.
