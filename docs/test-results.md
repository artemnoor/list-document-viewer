# Результаты тестирования

## Verification Engine 1.1.0 — 13 ноября 2026

Полный набор `pytest`:

```text
60 passed, 1 warning in 6.44s
```

В наборе есть unit, upstream/schema contract, property-based Decimal, regression, API, security, idempotence и concurrency checks. Property test выполняет 60 Hypothesis examples. Проверяются несовпадающие и отсутствующие hashes/версии, отсутствие operation proof, противоречивые formula/input/output, Extraction period, неподтверждённые ссылки, tolerance, `not_applicable` coverage и ложные подтверждения. Проверяется, что SQLite не держит транзакцию во время optional provider call.

Текущие upstream Extraction 1.2.0 и Linking 1.2.0 схемы сверены с commit в `contracts/upstream-sources.json`; доступные Extraction fixtures и synthetic Linking 1.2.0 проходят контрактные проверки. Старый upstream Linking sample с payload version 1.0.0 намеренно остаётся несовместимым с декларированной схемой 1.2.0.

Docker Compose smoke после пересборки:

- `docker compose config --quiet` — успешно.
- Образ 1.1.0 собран, сервис healthy; внешний порт привязан только к `127.0.0.1:8000`.
- `/health`, `/docs` и `/openapi.json` отвечают успешно; OpenAPI сообщает версию 1.1.0.
- Синтетический matched request вернул `matched`, schema 1.1.0 и `completeness.complete=true`; scoped GET и project history доступны.

В этом smoke использовался только синтетический matched запрос, поэтому внешний вызов Polza не выполнялся. Provider проверяется unit-тестами на псевдонимном payload и на независимость статуса от его ошибок.

Предупреждение тестовой среды: установленный Starlette сообщает о будущем переходе с `httpx` на `httpx2` в `TestClient`. Также `pytest-asyncio` предупреждает о неустановленном scope event loop; тесты приложения используют синхронные fixtures.

## Историческая live-проверка Polza

Ранее был отправлен один синтетический mismatch. Gemma 4 26B A4B вернула три schema-валидные гипотезы, которые не меняли детерминированный статус. В запросе были только pseudonymous tokens и коды; финансовые значения и документы не отправлялись. Этот единичный live-запуск не является частью текущего `pytest` прогона.

Полный E2E Parser → Reconciliation → Verification → Reporting не заявляется: Reconciliation 1.0.0 остаётся предварительным, а Reporting не подключён.

## GitHub Actions CI

Workflow `.github/workflows/ci.yml` запускает полный `pytest` набор на Python 3.11 и 3.12 при push и pull request. Отдельная задача собирает Docker Compose и проверяет синтетический API flow с отключённым внешним Polza. Локальная YAML-проверка workflow, `docker compose config --quiet` и полный набор тестов прошли; GitHub-hosted результат появляется в [Actions](https://github.com/artemnoor/phystech-trace-verification-engine/actions/workflows/ci.yml).

Первый GitHub Actions run [43503524091](https://github.com/artemnoor/phystech-trace-verification-engine/actions/runs/43503524091) завершился успешно: оба Python набора и Docker Compose smoke прошли. Runner оставил только информационное уведомление о миграции `ubuntu-latest` на Ubuntu 26.
