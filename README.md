# Phystech Trace — Verification Engine

[![CI](https://github.com/artemnoor/phystech-trace-verification-engine/actions/workflows/ci.yml/badge.svg)](https://github.com/artemnoor/phystech-trace-verification-engine/actions/workflows/ci.yml)

Самостоятельный backend этапа Verification в Phystech Trace. Сервис сравнивает показатели итогового КФЗ из Structured Extraction с ожидаемыми значениями из предварительного контракта Reconciliation, проверяет допустимость сравнения и сохраняет доказательную цепочку. Сервис **не** извлекает данные из PDF и не пересчитывает Reconciliation.

## Что реализовано

- FastAPI REST API с OpenAPI/Swagger и типизированными запросами/ответами.
- Детерминированное сравнение `Decimal`, периодов, строк, дат, логических значений и количеств.
- Явные статусы `matched`, `mismatch`, `insufficient_data`, `needs_review`, `not_applicable`.
- Проверка версий, JSON Schema, точных JSON Pointer, extraction IDs, строк, provenance и Link IDs/evidence.
- Отдельная оценка технической валидности, automatic Link validation, human confirmation и calculation trust.
- Проверка Calculation/Reconciliation fingerprints, операций и полного охвата показателей.
- Межсервисная авторизация по отдельному токену проекта, обязательный project scope для чтения результатов и ограничение размера/time budget.
- Классификация установленной причины отдельно от гипотезы.
- SQLite история запусков и идемпотентное повторение одинаковых запросов.
- Исходные Extraction 1.2.0 fixtures и Linking пример upstream сохранены в `tests/fixtures/upstream/`; синтетические данные отдельно лежат в `tests/fixtures/synthetic/`.
- Версии upstream и commit SHA записаны в [`contracts/upstream-sources.json`](contracts/upstream-sources.json).

Если задан `POLZA_AI_API_KEY` и включён `POLZA_AI_ENABLED`, сервис подключает Polza AI и Gemma 4 26B A4B (`google/gemma-4-26b-a4b-it`). Без ключа или при `POLZA_AI_ENABLED=false` Verification работает детерминированно. В модель отправляются только псевдонимные evidence tokens, статусы, коды диагностики и категории — без сумм, идентификаторов документов и исходного текста. Она может добавлять только гипотезы и не меняет результат. Timeout ограничен; вызов идёт вне транзакции SQLite.

## Локальный запуск

Требуется Python 3.11+.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[test]"
$env:VERIFICATION_DB_PATH = "data/verification.sqlite3"
$env:VERIFICATION_AUTH_MODE = "development"
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

Compose по умолчанию публикует сервис только на `127.0.0.1`. Перед локальным запуском скопируйте `.env.example` в `.env`. Для production задайте `VERIFICATION_AUTH_MODE=required` и `VERIFICATION_PROJECT_TOKENS` как JSON map `project_id` → уникальный секрет; передавайте его в `X-Service-Token`. Compose передаёт `POLZA_AI_API_KEY` из окружения Windows внутрь контейнера только если он задан. Настройка модели и обработка ключа описаны в [`docs/polza-ai.md`](docs/polza-ai.md).

## Тесты

```powershell
python -m pip install -e ".[test]"
pytest
```

Набор проверяет числовые и содержательные сценарии, upstream-контракты, property-based арифметику, API, идемпотентность и SQLite. Фактический последний прогон описан в [`docs/test-results.md`](docs/test-results.md).

GitHub Actions запускает полный набор на Python 3.11 и 3.12 при push и pull request, а отдельная задача проверяет Docker Compose и HTTP smoke flow без внешнего Polza API.

## API

| Метод | Endpoint | Назначение |
| --- | --- | --- |
| `GET` | `/health` | Состояние сервиса |
| `POST` | `/api/v1/verifications` | Запуск или повторное получение результата по fingerprint входов |
| `GET` | `/api/v1/verifications/{verification_id}?project_id=...` | Полный результат только в указанном project scope |
| `GET` | `/api/v1/verifications?project_id=...` | История запусков |
| `GET` | `/api/v1/verifications/{verification_id}/diagnostics?project_id=...` | Диагностика и причины проверки |
| `GET` | `/docs` | Swagger UI |
| `GET` | `/openapi.json` | OpenAPI schema |

## Ограничения текущей интеграции

- Reconciliation Engine ещё не предоставляет финальный контракт. Текущий [`reconciliation-result-1.0.0.schema.json`](contracts/reconciliation-result-1.0.0.schema.json) — предварительный межсервисный контракт, проверяемый синтетическими fixtures.
- Проверки полного E2E Phystech Trace не заявляются: Reconciliation и Reporting ещё не подключены.
- Пример Linking, поставляемый upstream, содержит `contract_version: 1.0.0` и не проходит приложенную там же схему результата 1.2.0. Сырые исходные данные сохранены без изменений. Контрактно валидный synthetic Linking 1.2.0 используется отдельно в тестах.
- Автоматическая проверка может завершиться без human review, если source references, fingerprints и calculation trace прошли проверки. Human confirmation отражается отдельно; сама метка `status=confirmed` не доказывает правильность Link.
- Неизвестный допуск не заменяется значением по умолчанию. Для денежного сравнения нужны одинаковые валюта и VAT basis; для сопоставления — совместимые периоды и economic basis.
- Общий `matched` требует полного охвата; любой `not_applicable` остаётся видимым в `completeness` и не может превратить неполную проверку в общий успех.
- Reconciliation 1.0.0 — предварительный handoff. Точные проверки fingerprints, operations и требования к будущему proof описаны в [`docs/reconciliation-integration.md`](docs/reconciliation-integration.md).

## Документация

- [`docs/architecture.md`](docs/architecture.md) — компоненты и поток данных.
- [`docs/contracts.md`](docs/contracts.md) — входные/выходные схемы и версии.
- [`docs/reconciliation-integration.md`](docs/reconciliation-integration.md) — требования к Reconciliation IDs, hashes, evidence и calculation trace.
- [`docs/verification-logic.md`](docs/verification-logic.md) — правила сравнений и статусов.
- [`docs/polza-ai.md`](docs/polza-ai.md) — подключение Polza AI / Gemma через окружение Windows.
- [`docs/classification.md`](docs/classification.md) — категории и требования к доказательству причины.
- [`docs/integration-guide.md`](docs/integration-guide.md) — подключение к Phystech Trace.
- [`docs/test-results.md`](docs/test-results.md) — фактические тестовые результаты и ограничения.
- [`docs/remediation-report.md`](docs/remediation-report.md) — причины дефектов, исправления и подтверждающие проверки.
- Примеры запросов/ответов находятся в `examples/`.
