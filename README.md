# Phystech Trace — Reconciliation Engine

Самостоятельный четвёртый этап Phystech Trace: строит воспроизводимые ожидаемые значения по результатам Structured Extraction и графу Document Linking. Арифметику выполняет детерминированный движок с `Decimal`; LLM при включённой и явно разрешённой передаче данных предлагает экономически осмысленный план и причины включения/исключения источников.

Сервис не сравнивает ожидаемое значение с КФЗ и не делает вывод о достоверности. Это выполняет следующий Verification Engine.

## Поддерживаемые контракты

- Structured Extraction `schema_version = 1.2.0`.
- Document Linking `contract_version = 1.2.0`.
- Контракты запроса и результата Reconciliation Engine `1.0.0`; выходной JSON Schema является отдельным API-контрактом для Verification Engine.
- Исходные upstream JSON Schema поставляются в `schemas/upstream/`, реальные Extraction fixtures — в `fixtures/upstream-structured-extraction-1.2.0/`.

Upstream SHA и найденное несоответствие примера Linking задокументированы в [docs/contracts.md](docs/contracts.md).

## Запуск локально

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[test]"
Copy-Item .env.example .env
uvicorn reconciliation_engine.api:app --reload
```

Интерактивный Swagger UI доступен по адресу `http://127.0.0.1:8000/docs`, OpenAPI — `http://127.0.0.1:8000/openapi.json`, проверка готовности — `http://127.0.0.1:8000/health`.

## API

- `POST /api/v1/reconciliations` — принимает исходные JSON Extraction, Linking 1.2.0, контекст и необязательные ранее подтверждённые решения.
- `GET /api/v1/reconciliations/{reconciliation_id}` — читает сохранённый результат.

Входные данные проверяются upstream JSON Schema и согласованностью снимка: document/extraction ID, версия и состав комплекта должны совпадать. Для каждой цели обязателен точный `kfz_document_id` и `kfz_source_path` (JSON Pointer) на показатель КФЗ. При несовместимой версии или структуре API возвращает `422` с точными `path`, `code` и `message`.

## Пример из upstream Extraction

`examples/act-reconciliation-request.json` и `examples/act-reconciliation-result.json` содержат валидный запрос и выходной контрактный пример с provenance. Пример указывает на настоящий Q1 показатель `reported_total`, тогда как подтверждаемый акт относится к апрелю. Поэтому результат намеренно имеет `status=manual_review` и `expected_value=null`; движок не выдаёт нестыкующийся период как подтверждённую сумму. Числовой расчёт пяти строк акта (`1 180 300,00 RUB`) проверяется отдельно арифметическими тестами. Linking snapshot в примере минимальный и контрактно-валидный 1.2.0 с пустым графом: опубликованный upstream output example оказался 1.0.0 и не соответствует его 1.2.0 схеме.

Без одобренного решения и без разрешённой LLM-модели сервис возвращает `manual_review`/`insufficient_data` с кандидатами и причинами. Это ожидаемое безопасное поведение, а не тестовая заглушка. Реальные планы пользователя могут быть переданы в `prior_decisions`; LLM-план строится только если `.env` настроен и запрос явно разрешает внешнюю обработку открытого или обезличенного контекста.

## LLM

Скопируйте `.env.example` и настройте `LLM_ENABLED=true`, `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`. Поддерживается OpenAI-compatible `/chat/completions`, включая Polza и локальные серверы; для локального endpoint ключ может быть пустым. Внешний вызов дополнительно требует `context.data_classification` равный `open` или `anonymized` и `context.external_llm_allowed=true`. Для закрытых данных модель остаётся выключенной, кроме явно настроенного оператором `LLM_TRUSTED_LOCAL=true` для локально контролируемой модели/endpoint. В prompt не передаются `source_value`, координаты или полная provenance; идентификаторы документов, строк и связей заменяются псевдонимами. Нормализованные описания строк и evidence значения передаются только в разрешённом режиме.

Правила планировщика имеют отдельные версии: исходная `prompts/calculation-plan.v1.0.0.txt`, предыдущая `prompts/calculation-plan.v1.0.1.txt` и текущая `prompts/calculation-plan.v1.0.2.txt`.

## Тесты

```powershell
pytest
```

Зафиксированный прогон описан в [docs/test-results.md](docs/test-results.md). Тесты планировщика и арифметики разделены; для арифметических проверок используются сохранённые планы без LLM.

## Docker

```powershell
docker build -t phystech-trace-reconciliation .
docker run --rm -p 8000:8000 --env-file .env -v ${PWD}/data:/app/data phystech-trace-reconciliation
```

## Документы

- [Архитектура](docs/architecture.md)
- [Контракты](docs/contracts.md)
- [Модель расчёта](docs/calculation-model.md)
- [Результаты проверок](docs/test-results.md)
- [Статус live E2E-теста Gemma 4](docs/live-llm-evaluation.md)

## Синтетический acceptance и текущие ограничения

`examples/synthetic/` содержит отдельный сквозной acceptance-набор с явно синтетическими Extraction, snapshot-bound планом, результатом и эталоном. Его успешный расчёт проверяет вычислительный путь, но не считается успешным upstream fixture.

Для закрытого контекста `LLM_TRUSTED_LOCAL=true` недостаточно: endpoint также должен быть loopback/private или использовать точный hostname из `LLM_TRUSTED_HOSTS`. Внешние API доступны только для открытых или разрешённых обезличенных данных при `external_llm_allowed=true`. Prompt не включает исходные денежные значения, `source_value` и полную provenance; он использует псевдонимы документов, строк и связей.

GitHub Actions запускает тесты, пересобирает синтетический acceptance-набор, собирает Docker-образ и проверяет `/health`, `/openapi.json` и `/docs`.
